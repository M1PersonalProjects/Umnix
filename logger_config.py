from __future__ import annotations

import inspect
import logging
import sys
from datetime import datetime
from http import HTTPStatus
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional, Tuple, Union

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "app.log"
SYSTEM_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
SYSTEM_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class UmnixFormatter(logging.Formatter):
    """Форматирует системные записи и диагностические действия пользователя."""

    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "user_action", False):
            return record.getMessage()
        return super().format(record)


def _configure_logger() -> logging.Logger:
    configured = logging.getLogger("umnix")
    configured.setLevel(logging.INFO)
    configured.propagate = False
    if configured.handlers:
        return configured

    formatter = UmnixFormatter(SYSTEM_LOG_FORMAT, SYSTEM_DATE_FORMAT)
    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    configured.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    configured.addHandler(console_handler)
    return configured


logger = _configure_logger()
user_action_logger = logging.getLogger("umnix.user_action")
user_action_logger.setLevel(logging.INFO)
user_action_logger.propagate = True
user_action_logger.handlers.clear()


def source_location(callback: Optional[Callable]) -> Tuple[str, int]:
    """Возвращает путь и первую строку обработчика относительно корня проекта."""
    if callback is None:
        return "unknown", 0
    try:
        source_file = Path(inspect.getsourcefile(callback) or inspect.getfile(callback)).resolve()
        line_number = inspect.getsourcelines(callback)[1]
        try:
            relative = source_file.relative_to(BASE_DIR)
        except ValueError:
            relative = source_file
        return relative.as_posix(), int(line_number)
    except (OSError, TypeError):
        return "unknown", 0


def exception_location(exc: BaseException) -> Tuple[str, int]:
    """Возвращает последнюю строку исключения внутри проекта, если она доступна."""
    traceback = exc.__traceback__
    selected: Optional[Tuple[str, int]] = None
    while traceback is not None:
        frame_path = Path(traceback.tb_frame.f_code.co_filename).resolve()
        try:
            relative = frame_path.relative_to(BASE_DIR)
            selected = (relative.as_posix(), int(traceback.tb_lineno))
        except ValueError:
            pass
        traceback = traceback.tb_next
    return selected or ("unknown", 0)


def _status_label(status_code: int) -> str:
    try:
        phrase = HTTPStatus(int(status_code)).phrase
    except ValueError:
        phrase = "Unknown Status"
    return f"[{int(status_code)} {phrase}]"


def _clean_field(value: object) -> str:
    return " ".join(str(value or "-").replace("_", " ").split())


def log_user_action(
    tg_id: Optional[Union[int, str]],
    status_code: int,
    explanation: str,
    source_file: str,
    line_number: int,
) -> None:
    """Пишет действие пользователя в единый диагностический формат."""
    now = datetime.now().astimezone()
    user_value = str(tg_id) if tg_id not in (None, "") else "anonymous"
    message = "_".join(
        (
            now.strftime("%d.%m.%y"),
            now.strftime("%H.%M.%S"),
            user_value,
            _status_label(status_code),
            _clean_field(explanation),
            f"{source_file}:{int(line_number)}",
        )
    )
    user_action_logger.info(message, extra={"user_action": True})


for name in ("aiogram", "uvicorn", "uvicorn.access", "openai", "httpx", "asyncio"):
    logging.getLogger(name).setLevel(logging.WARNING)
