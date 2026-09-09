from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from database import db

BOT_AUTH_TTL_MINUTES = 10


@dataclass(frozen=True)
class BotLoginAttempt:
    request_id: str
    browser_token: str
    bot_token: str
    expires_at: datetime


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def create_bot_login_attempt() -> BotLoginAttempt:
    """Создаёт одноразовую связку браузера и Telegram-бота."""
    request_id = str(uuid.uuid4())
    browser_token = secrets.token_urlsafe(32)
    bot_token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=BOT_AUTH_TTL_MINUTES)

    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM web_auth_requests
            WHERE expires_at < CURRENT_TIMESTAMP - INTERVAL '1 day'
            """
        )
        await conn.execute(
            """
            INSERT INTO web_auth_requests (
                request_id, browser_token_hash, bot_token_hash, expires_at
            )
            VALUES ($1::uuid, $2, $3, $4)
            """,
            request_id,
            _token_hash(browser_token),
            _token_hash(bot_token),
            expires_at,
        )
    return BotLoginAttempt(request_id, browser_token, bot_token, expires_at)


async def approve_bot_login(bot_token: str, tg_id: int) -> bool:
    """Подтверждает браузерный вход владельцем Telegram-аккаунта."""
    if not bot_token:
        return False
    async with db.pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE web_auth_requests
            SET tg_id = $2, approved_at = CURRENT_TIMESTAMP
            WHERE bot_token_hash = $1
              AND approved_at IS NULL
              AND consumed_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
            """,
            _token_hash(bot_token),
            int(tg_id),
        )
    return result == "UPDATE 1"


async def get_bot_login_state(request_id: str, browser_token: str):
    """Возвращает состояние одноразового браузерного входа."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT request_id, tg_id, approved_at, consumed_at, expires_at
            FROM web_auth_requests
            WHERE request_id = $1::uuid
              AND browser_token_hash = $2
            """,
            request_id,
            _token_hash(browser_token),
        )
    return row


async def consume_bot_login(request_id: str, browser_token: str) -> bool:
    """Помечает подтверждённый вход как использованный."""
    async with db.pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE web_auth_requests
            SET consumed_at = CURRENT_TIMESTAMP
            WHERE request_id = $1::uuid
              AND browser_token_hash = $2
              AND approved_at IS NOT NULL
              AND consumed_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
            """,
            request_id,
            _token_hash(browser_token),
        )
    return result == "UPDATE 1"
