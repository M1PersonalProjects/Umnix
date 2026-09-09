from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from config import settings
from logger_config import logger


@dataclass(frozen=True)
class TelegramAvatar:
    """Кэшированное изображение профиля Telegram."""

    content: bytes
    content_type: str


_AVATAR_TTL_SECONDS = 15 * 60
_AVATAR_NEGATIVE_TTL_SECONDS = 45
_avatar_cache: dict[int, tuple[float, Optional[TelegramAvatar]]] = {}


async def get_telegram_avatar(tg_id: int) -> Optional[TelegramAvatar]:
    """
    Безопасно получает аватар через Bot API и не раскрывает токен клиенту.
    """

    now = time.monotonic()
    cached = _avatar_cache.get(int(tg_id))
    if cached and cached[0] > now:
        return cached[1]

    token = settings.bot_token.get_secret_value().strip()
    if not token:
        _avatar_cache[int(tg_id)] = (now + _AVATAR_NEGATIVE_TTL_SECONDS, None)
        return None

    base = f"https://api.telegram.org/bot{token}"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            photos_response = await client.get(
                f"{base}/getUserProfilePhotos",
                params={"user_id": int(tg_id), "limit": 1},
            )
            photos_response.raise_for_status()
            photos_payload = photos_response.json()
            photos = (photos_payload.get("result") or {}).get("photos") or []
            if not photos or not photos[0]:
                avatar = None
            else:
                variants = photos[0]
                file_id = variants[-1].get("file_id")
                if not file_id:
                    avatar = None
                else:
                    file_response = await client.get(f"{base}/getFile", params={"file_id": file_id})
                    file_response.raise_for_status()
                    file_path = (file_response.json().get("result") or {}).get("file_path")
                    if not file_path:
                        avatar = None
                    else:
                        image_response = await client.get(
                            f"https://api.telegram.org/file/bot{token}/{file_path}"
                        )
                        image_response.raise_for_status()
                        avatar = TelegramAvatar(
                            content=image_response.content,
                            content_type=image_response.headers.get("content-type", "image/jpeg"),
                        )
    except Exception as exc:
        logger.info("Telegram avatar unavailable for user %s: %s", tg_id, type(exc).__name__)
        avatar = None

    ttl = _AVATAR_TTL_SECONDS if avatar is not None else _AVATAR_NEGATIVE_TTL_SECONDS
    _avatar_cache[int(tg_id)] = (now + ttl, avatar)
    return avatar
