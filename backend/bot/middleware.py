from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from logger_config import exception_location, log_user_action, source_location


class UserActionLogMiddleware(BaseMiddleware):
    """Логирует пользовательские сообщения и callback-действия Telegram-бота."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_id = self._tg_id(event)
        callback = getattr(data.get("handler"), "callback", None)
        source_file, line_number = source_location(callback or handler)
        explanation = self._explanation(event)
        try:
            result = await handler(event, data)
        except Exception as exc:
            error_file, error_line = exception_location(exc)
            log_user_action(
                tg_id,
                500,
                f"{explanation} failed with {type(exc).__name__}",
                error_file,
                error_line,
            )
            raise
        log_user_action(tg_id, 200, explanation, source_file, line_number)
        return result

    @staticmethod
    def _tg_id(event: TelegramObject) -> Optional[int]:
        sender = getattr(event, "from_user", None)
        return getattr(sender, "id", None)

    @staticmethod
    def _explanation(event: TelegramObject) -> str:
        if isinstance(event, CallbackQuery):
            return "Telegram callback handled"
        if isinstance(event, Message):
            return "Telegram message handled"
        return "Telegram user action handled"
