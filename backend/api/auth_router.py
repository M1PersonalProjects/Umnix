from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.auth.bot_login import (
    consume_bot_login,
    create_bot_login_attempt,
    get_bot_login_state,
)
from backend.auth.security import create_session_token, get_current_user, verify_telegram_webapp_data
from backend.web.activity import record_activity
from backend.web.schemas import (
    FrontendErrorLogRequest,
    TelegramBotAuthStatusRequest,
    WebAppAuthRequest,
    WebAuthRequest,
)
from config import settings
from database import db
from logger_config import log_user_action

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication v1"])


def _value(user, key: str, default=None):
    if hasattr(user, "get"):
        return user.get(key, default)
    try:
        return user[key]
    except (KeyError, TypeError):
        return default


def _auth_response(user, telegram_photo_url: Optional[str] = None) -> dict:
    """Формирует ответ сессии для пользователя."""
    return {
        "status": "success",
        "tg_id": int(user["tg_id"]),
        "username": user["username"],
        "role": user["role"],
        "mentor_kind": _value(user, "mentor_kind"),
        "session_token": create_session_token(int(user["tg_id"])),
        "telegram_photo_url": telegram_photo_url or None,
    }


async def _find_user(tg_id: int):
    """Находит зарегистрированного пользователя по Telegram ID."""
    async with db.pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT tg_id, username, role, parent_id, mentor_kind FROM users WHERE tg_id = $1",
            int(tg_id),
        )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вы ещё не зарегистрированы. Пожалуйста, посетите нашего Telegram-бота.",
        )
    return user


@router.post("/frontend-error", status_code=status.HTTP_204_NO_CONTENT)
async def frontend_error(payload: FrontendErrorLogRequest):
    """Записывает ошибку JavaScript, возникшую до серверного действия."""
    source_file = payload.source_file.lstrip("/") or "frontend"
    log_user_action(
        payload.tg_id,
        500,
        f"Frontend JavaScript error: {payload.message}",
        source_file,
        payload.line_number,
    )
    return None


@router.post("/telegram-webapp")
async def telegram_webapp_login(payload: WebAppAuthRequest, request: Request):
    """Проверяет подписанные Telegram WebApp initData и создаёт локальную сессию."""
    telegram_user = verify_telegram_webapp_data(payload.init_data_raw)
    tg_id = telegram_user.get("id")
    if not isinstance(tg_id, int):
        request.state.audit_message = "Telegram WebApp did not provide a valid user ID"
        raise HTTPException(status_code=400, detail="Telegram не передал идентификатор пользователя")

    request.state.audit_tg_id = tg_id
    request.state.audit_message = "Telegram WebApp login requested"
    try:
        user = await _find_user(tg_id)
    except HTTPException:
        request.state.audit_message = "Telegram WebApp account was not found"
        raise
    request.state.audit_message = "Telegram WebApp login completed"
    await record_activity(tg_id, "login", "Вход в WebApp через Telegram", source="web")
    return _auth_response(user, telegram_user.get("photo_url"))


@router.post("/browser-login")
async def browser_login(payload: WebAuthRequest, request: Request):
    """Выполняет локальный вход по Telegram ID для зарегистрированного пользователя."""
    request.state.audit_tg_id = payload.tg_id
    request.state.audit_message = "Telegram ID login requested"
    try:
        user = await _find_user(payload.tg_id)
    except HTTPException:
        request.state.audit_message = "Telegram ID account was not found"
        raise
    request.state.audit_message = "Telegram ID login completed"
    await record_activity(payload.tg_id, "login", "Вход в WebApp по Telegram ID", source="web")
    return _auth_response(user)


@router.post("/telegram-bot/start")
async def start_telegram_bot_login(request: Request):
    """Создаёт одноразовый Telegram Bot deep-link для подтверждения браузерного входа."""
    attempt = await create_bot_login_attempt()
    username = settings.bot_username.lstrip("@")
    request.state.audit_message = "Telegram Bot login flow started"
    return {
        "status": "pending",
        "request_id": attempt.request_id,
        "browser_token": attempt.browser_token,
        "bot_url": f"https://t.me/{username}?start=web_auth_{attempt.bot_token}",
        "expires_at": attempt.expires_at.isoformat(),
    }


@router.post("/telegram-bot/status")
async def telegram_bot_login_status(payload: TelegramBotAuthStatusRequest, request: Request):
    """Проверяет подтверждение входа владельцем Telegram-аккаунта."""
    row = await get_bot_login_state(str(payload.request_id), payload.browser_token)
    if not row:
        request.state.audit_message = "Telegram Bot login request was not found"
        raise HTTPException(status_code=404, detail="Запрос входа не найден или недействителен")

    expires_at = row["expires_at"]
    if expires_at <= datetime.now(timezone.utc):
        request.state.audit_message = "Telegram Bot login request expired"
        raise HTTPException(status_code=410, detail="Время подтверждения через Telegram истекло")
    if row["consumed_at"] is not None:
        request.state.audit_message = "Telegram Bot login request was already used"
        raise HTTPException(status_code=409, detail="Этот запрос входа уже использован")
    if row["approved_at"] is None or row["tg_id"] is None:
        request.state.audit_message = "Telegram Bot login is waiting for confirmation"
        return {"status": "pending"}

    tg_id = int(row["tg_id"])
    request.state.audit_tg_id = tg_id
    try:
        user = await _find_user(tg_id)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        request.state.audit_message = "Telegram account is confirmed but registration is incomplete"
        return {"status": "registration_required", "tg_id": tg_id}

    if not await consume_bot_login(str(payload.request_id), payload.browser_token):
        request.state.audit_message = "Telegram Bot login request could not be consumed"
        raise HTTPException(status_code=409, detail="Не удалось завершить запрос входа. Повторите попытку.")

    request.state.audit_message = "Telegram Bot login completed"
    await record_activity(tg_id, "login", "Вход в WebApp через Telegram-бот", source="web")
    return _auth_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, user=Depends(get_current_user)):
    """Фиксирует выход; браузер удаляет локальный токен после ответа."""
    tg_id = int(user["tg_id"])
    request.state.audit_tg_id = tg_id
    request.state.audit_message = "User logged out"
    await record_activity(tg_id, "logout", "Выход из WebApp", source="web")
    return None


@router.get("/session")
async def validate_session(request: Request, user=Depends(get_current_user)):
    """Проверяет действительность сохранённой сессии."""
    request.state.audit_tg_id = int(user["tg_id"])
    request.state.audit_message = "Saved session validated"
    return {
        "tg_id": user["tg_id"],
        "username": user["username"],
        "role": user["role"],
        "mentor_kind": _value(user, "mentor_kind"),
        "parent_id": user["parent_id"],
        "is_admin": user["is_admin"],
    }
