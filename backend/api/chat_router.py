from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from backend.auth.security import get_current_user
from database import db
from logger_config import logger
from backend.web.activity import record_activity
from backend.web.attachment_storage import get_attachment, load_attachment_for_ai, save_upload
from backend.web.ai import AIUpstreamError, transcribe_audio
from backend.web.ai_tutor import generate_response
from backend.web.telegram_profile import get_telegram_avatar
from backend.web.ai_tutor import (
    create_session,
    delete_session,
    ensure_session,
    exit_book_mode,
    get_messages,
    list_sessions,
    lock_context as lock_session_context,
    rename_session,
)

router = APIRouter(prefix="/api/v1/tutor", tags=["AI Tutor v1"])
ALLOWED_TUTOR_ROLES = {"student", "parent", "admin"}


def ensure_tutor_role(user) -> None:
    if user["role"] not in ALLOWED_TUTOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ИИ-тьютор доступен Ученикам и Учителям",
        )


class SessionCreate(BaseModel):
    """
    Схема для создания новой сессии чата.
    """
    title: str = Field(default="Новый чат", max_length=35)


class SessionRename(BaseModel):
    """
    Схема для переименования существующей сессии чата.
    """
    title: str = Field(..., min_length=1, max_length=35)


class ContextSelection(BaseModel):
    """
    Схема для выбора контекста учебника для сессии чата.
    """
    book_class: Optional[int] = Field(None, ge=1, le=11)
    book_program: Optional[str] = Field(None, max_length=100)
    book_id: Optional[int] = None
    page_id: Optional[int] = None
    page_number: Optional[int] = Field(None, ge=1)
    page_paragraph: Optional[str] = Field(None, max_length=100)


def _not_found(error: Exception) -> HTTPException:
    """
    Возвращает HTTPException с кодом 404 и сообщением об ошибке.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


@router.get("/profile")
async def tutor_profile(user=Depends(get_current_user)):
    """
    Возвращает профиль одним DTO без дополнительных запросов для каждого сообщения.
    """
    ensure_tutor_role(user)
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tg_id, username, role FROM users WHERE tg_id=$1",
            user["tg_id"],
        )
    if not row:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    username = (row["username"] or "").strip() if row["username"] else ""
    return {
        "tg_id": int(row["tg_id"]),
        "username": username or None,
        "display_name": username or str(row["tg_id"]),
        "role": row["role"],
        "avatar_url": "/api/v1/tutor/profile/avatar",
    }


@router.get("/profile/avatar")
async def tutor_profile_avatar(user=Depends(get_current_user)):
    """
    Проксирует Telegram-аватар и не раскрывает Bot Token браузеру.
    """
    ensure_tutor_role(user)
    avatar = await get_telegram_avatar(int(user["tg_id"]))
    if avatar is None:
        raise HTTPException(status_code=404, detail="Аватар Telegram не найден")
    return Response(
        content=avatar.content,
        media_type=avatar.content_type,
        headers={"Cache-Control": "private, max-age=900"},
    )


@router.get("/sessions")
async def sessions(user=Depends(get_current_user)):
    """
    Возвращает список всех сессий чата для текущего пользователя.
    """
    ensure_tutor_role(user)
    return await list_sessions(user["tg_id"])


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def new_session(payload: SessionCreate, user=Depends(get_current_user)):
    """
    Создает новую сессию чата для текущего пользователя.
    """
    ensure_tutor_role(user)
    return await create_session(user["tg_id"], payload.title)


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, payload: SessionRename, user=Depends(get_current_user)):
    """
    Переименовывает существующую сессию чата для текущего пользователя.
    """
    ensure_tutor_role(user)
    try:
        return await rename_session(user["tg_id"], session_id, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LookupError as exc:
        raise _not_found(exc)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_session(session_id: str, user=Depends(get_current_user)):
    """
    Удаляет существующую сессию чата для текущего пользователя.
    """
    ensure_tutor_role(user)
    try:
        await delete_session(user["tg_id"], session_id)
    except (LookupError, ValueError) as exc:
        raise _not_found(exc)


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str, user=Depends(get_current_user)):
    """
    Возвращает список сообщений для указанной сессии чата текущего пользователя.
    """
    ensure_tutor_role(user)
    try:
        return await get_messages(user["tg_id"], session_id)
    except (LookupError, ValueError) as exc:
        raise _not_found(exc)


@router.put("/sessions/{session_id}/context")
async def set_session_context(
    session_id: str,
    payload: ContextSelection,
    user=Depends(get_current_user),
):
    """
    Устанавливает контекст учебника для указанной сессии чата текущего пользователя.
    """
    ensure_tutor_role(user)
    try:
        context = await lock_session_context(
            user["tg_id"], session_id, payload.model_dump(exclude_none=True)
        )
        return {"book_mode": True, "context": context.to_dict()}
    except (LookupError, ValueError) as exc:
        raise _not_found(exc)


@router.delete("/sessions/{session_id}/context")
async def clear_session_context(session_id: str, user=Depends(get_current_user)):
    """
    Сбрасывает контекст учебника для указанной сессии чата текущего пользователя.
    """
    ensure_tutor_role(user)
    try:
        return await exit_book_mode(user["tg_id"], session_id)
    except (LookupError, ValueError) as exc:
        raise _not_found(exc)


VOICE_MAX_BYTES = 12 * 1024 * 1024
VOICE_SUFFIXES = {".webm", ".ogg", ".oga", ".mp3", ".m4a", ".mp4", ".wav", ".aac", ".flac"}


@router.post("/transcribe")
async def transcribe_voice_message(
    audio: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """
    Распознаёт короткое голосовое сообщение для общего composer ИИ-тьютора.
    """
    ensure_tutor_role(user)
    filename = (audio.filename or "voice.webm").strip() or "voice.webm"
    suffix = Path(filename).suffix.lower()
    content_type = (audio.content_type or "").lower()
    if suffix not in VOICE_SUFFIXES and not content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Поддерживается только аудиозапись")

    chunks = []
    total = 0
    while True:
        chunk = await audio.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > VOICE_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Голосовое сообщение слишком большое")
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=422, detail="Голосовое сообщение пустое")

    try:
        text = await transcribe_audio(
            data=b"".join(chunks),
            filename=filename,
            content_type=content_type or "application/octet-stream",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except AIUpstreamError:
        raise HTTPException(status_code=503, detail="Распознавание голоса временно недоступно")
    except Exception as exc:
        logger.exception("Voice transcription failed: %s", exc)
        raise HTTPException(status_code=502, detail="Не удалось распознать голосовое сообщение")
    return {"text": text}


@router.post("/messages")
async def send_message(
    session_id: str = Form(...),
    message_text: str = Form(default=""),
    attachment: Optional[UploadFile] = File(default=None),
    book_class: Optional[int] = Form(default=None),
    book_program: Optional[str] = Form(default=None),
    book_id: Optional[int] = Form(default=None),
    page_id: Optional[int] = Form(default=None),
    page_number: Optional[int] = Form(default=None),
    page_paragraph: Optional[str] = Form(default=None),
    lock_context: bool = Form(default=False),
    interactive_app_id: Optional[str] = Form(default=None),
    interactive_action: Optional[str] = Form(default=None),
    interactive_version: Optional[int] = Form(default=None),
    user=Depends(get_current_user),
):
    """
    Отправляет сообщение в сессию чата ИИ-тьютора.
    """
    ensure_tutor_role(user)
    if not message_text.strip() and attachment is None:
        raise HTTPException(status_code=422, detail="Введите сообщение или добавьте вложение")

    try:
        async with db.pool.acquire() as conn:
            await ensure_session(conn, user["tg_id"], session_id)
    except (LookupError, ValueError) as exc:
        raise _not_found(exc)

    parsed_attachment = None
    stored_attachment_id = None
    if attachment is not None:
        try:
            stored = await save_upload(upload=attachment, owner_id=user["tg_id"])
            stored_attachment_id = stored.attachment_id
            stored_row = await get_attachment(stored.attachment_id)
            parsed_attachment = await load_attachment_for_ai(stored_row)
            parsed_attachment.attachment_id = stored.attachment_id
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Attachment persistence/parsing failed: %s", exc)
            raise HTTPException(status_code=422, detail="Не удалось обработать вложение")

    manual_context = {
        "book_class": book_class,
        "book_program": book_program,
        "book_id": book_id,
        "page_id": page_id,
        "page_number": page_number,
        "page_paragraph": page_paragraph,
    }
    try:
        if interactive_action == "edit":
            mode = "interactive_edit"
        elif interactive_action == "create":
            mode = "interactive_create"
        else:
            mode = "chat"
        result = await generate_response(
            user_id=user["tg_id"],
            role=user["role"],
            session_id=session_id,
            message=message_text,
            mode=mode,
            attachment=parsed_attachment,
            attachment_id=stored_attachment_id,
            manual_context=manual_context,
            lock_selected_context=lock_context,
            interactive_app_id=interactive_app_id,
            interactive_version=interactive_version,
        )
        result.setdefault("sender_name", "Umnix")
        await record_activity(
            int(user["tg_id"]),
            "tutor_message",
            message_text.strip()[:500] or (attachment.filename if attachment else "Вложение"),
            session_id=session_id,
            attachment_id=stored_attachment_id,
        )
        return result
    except LookupError as exc:
        raise _not_found(exc)
    except Exception as exc:
        logger.exception("Tutor request failed: %s", exc)
        raise HTTPException(status_code=502, detail="ИИ-тьютор временно недоступен")


@router.get("/context/classes")
async def context_classes(user=Depends(get_current_user)):
    """
    Возвращает список всех доступных классов учебников.
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT book_class FROM book ORDER BY book_class")
    return [row["book_class"] for row in rows]


@router.get("/context/subjects")
async def context_subjects(book_class: int, user=Depends(get_current_user)):
    """
    Возвращает список всех доступных предметов для указанного класса учебника.
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT book_program FROM book WHERE book_class=$1 ORDER BY book_program",
            book_class,
        )
    return [row["book_program"] for row in rows]


@router.get("/context/books")
async def context_books(
    book_class: int,
    book_program: str,
    user=Depends(get_current_user),
):
    """
    Возвращает список всех доступных учебников для указанного класса и предмета.
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT book_id, book_title, book_author, book_program, book_class
            FROM book WHERE book_class=$1 AND book_program=$2 ORDER BY book_title
            """,
            book_class,
            book_program,
        )
    return [dict(row) for row in rows]


@router.get("/context/pages")
async def context_pages(book_id: int, user=Depends(get_current_user)):
    """
    Возвращает список всех доступных страниц для указанного учебника.
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT page_id, page_number, page_title, page_paragraph
            FROM page WHERE book_id=$1 ORDER BY page_number
            """,
            book_id,
        )
    return [dict(row) for row in rows]
