import asyncio
import io
from typing import List, Optional

from aiogram.types import BufferedInputFile, Message
from fastapi import UploadFile
from starlette.datastructures import Headers

from backend.web.attachment_storage import get_attachment, load_attachment_for_ai, save_upload
from backend.web.response_formatter import format_for_telegram
from backend.web.file_parser import (
    attachment_size_limit,
    AttachmentError,
    ParsedAttachment,
    parse_attachment,
)


async def _parse_safely(data: bytes, filename: str, mime_type: str) -> ParsedAttachment:
    """
    Безопасно парсит вложение, перехватывая ошибки и преобразуя их в AttachmentError.
    """
    try:
        return await asyncio.to_thread(parse_attachment, data, filename, mime_type)
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError(
            f"Не удалось прочитать файл «{filename}». Проверьте, что он не повреждён."
        ) from exc


async def _store_for_chat(data: bytes, filename: str, mime_type: str, owner_id: int) -> Optional[ParsedAttachment]:
    """
    Сохраняет вложение в хранилище и возвращает объект ParsedAttachment.
    """
    try:
        upload = UploadFile(
            file=io.BytesIO(data),
            filename=filename,
            headers=Headers({"content-type": mime_type}),
            size=len(data),
        )
        stored = await save_upload(upload=upload, owner_id=owner_id)
        if not isinstance(stored.attachment_id, int):
            return None
        row = await get_attachment(stored.attachment_id)
        parsed = await load_attachment_for_ai(row)
        parsed.attachment_id = stored.attachment_id
        return parsed
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError("Не удалось сохранить вложение в память чата") from exc


async def parse_telegram_attachment(message: Message) -> Optional[ParsedAttachment]:
    """
    Парсит вложение из Telegram-сообщения, сохраняя его в хранилище и возвращая объект ParsedAttachment.
    """
    if not message.photo and not message.document:
        return None

    buffer = io.BytesIO()
    if message.photo:
        file_info = await message.bot.get_file(message.photo[-1].file_id)
        await message.bot.download_file(file_info.file_path, destination=buffer)
        data = buffer.getvalue() or b"telegram-photo"
        stored = await _store_for_chat(
            data, "telegram-photo.jpg", "image/jpeg", message.from_user.id
        )
        return stored or await _parse_safely(data, "telegram-photo.jpg", "image/jpeg")

    document = message.document
    filename = document.file_name or "telegram-document"
    mime_type = document.mime_type or "application/octet-stream"
    size_limit = attachment_size_limit(filename, mime_type)
    if document.file_size and document.file_size > size_limit:
        limit_mb = size_limit // (1024 * 1024)
        raise AttachmentError(f"Максимальный размер этого вложения — {limit_mb} МБ")

    file_info = await message.bot.get_file(document.file_id)
    await message.bot.download_file(file_info.file_path, destination=buffer)
    data = buffer.getvalue()
    stored = await _store_for_chat(data, filename, mime_type, message.from_user.id)
    return stored or await _parse_safely(data, filename, mime_type)


TELEGRAM_TEXT_LIMIT = 4000
LONG_ANSWER_FILENAME = "umnix-answer.txt"
LONG_ANSWER_CAPTION = (
    "📄 Ответ ИИ-тьютора не помещается в одно текстовое сообщение Telegram. "
    "Полный ответ — в этом файле."
)
EMPTY_ANSWER_FALLBACK = (
    "Не удалось сформировать текстовый ответ. "
    "Попробуйте повторить или немного переформулировать вопрос."
)


def split_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> List[str]:
    """
    Разбивает текстовый ответ на части, которые помещаются в одно Telegram-сообщение.
    """
    remaining = str(text or "")
    chunks: List[str] = []
    while len(remaining) > limit:
        position = remaining.rfind("\n", 0, limit)
        if position < limit // 2:
            position = remaining.rfind(" ", 0, limit)
        if position < limit // 2:
            position = limit
        chunk = remaining[:position].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[position:].lstrip()
    tail = remaining.strip()
    if tail:
        chunks.append(tail)
    return chunks


def _safe_telegram_payload(text: str) -> str:
    """
    Формирует безопасный текст для отправки в Telegram, удаляя LaTeX и обрезая пустые строки.
    """
    raw = str(text or "").strip() or EMPTY_ANSWER_FALLBACK
    return format_for_telegram(raw).strip() or EMPTY_ANSWER_FALLBACK


def _text_document(text: str) -> BufferedInputFile:
    """
    Создаёт BufferedInputFile из текстового ответа для отправки в Telegram как документа.
    """
    return BufferedInputFile(text.encode("utf-8"), filename=LONG_ANSWER_FILENAME)


async def answer_plain(message, text: str, reply_markup: Optional[object] = None):
    """
    Отправляет текстовый ответ в чат Telegram, безопасно разбивая его на части, если он слишком длинный.
    """
    safe_text = _safe_telegram_payload(text)
    if len(safe_text) <= TELEGRAM_TEXT_LIMIT:
        return await message.answer(
            safe_text,
            reply_markup=reply_markup,
            parse_mode=None,
        )

    kwargs = {
        "document": _text_document(safe_text),
        "caption": LONG_ANSWER_CAPTION,
        "parse_mode": None,
    }
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    return await message.answer_document(**kwargs)


async def send_plain_to_chat(
    bot,
    chat_id: int,
    text: str,
    reply_markup: Optional[object] = None,
):
    """
    Отправляет текстовый ответ в чат Telegram, безопасно разбивая его на части, если он слишком длинный.
    """
    safe_text = _safe_telegram_payload(text)
    if len(safe_text) <= TELEGRAM_TEXT_LIMIT:
        kwargs = {
            "chat_id": chat_id,
            "text": safe_text,
            "parse_mode": None,
        }
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        return await bot.send_message(**kwargs)

    kwargs = {
        "chat_id": chat_id,
        "document": _text_document(safe_text),
        "caption": LONG_ANSWER_CAPTION,
        "parse_mode": None,
    }
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    return await bot.send_document(**kwargs)
