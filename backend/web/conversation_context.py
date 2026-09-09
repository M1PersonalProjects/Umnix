from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

TELEGRAM_CHAT_TITLE = "Чат Telegram · Umnix"
TELEGRAM_CHAT_TYPE = "telegram_default"

BOOK_MODE = "book"
ATTACHMENT_MODE = "attachment"
GENERAL_MODE = "general"

ATTACHMENT_REFERENCE_MARKERS = (
    "pdf", "файл", "файлу", "файле", "документ", "вложен",
    "фото", "фотограф", "скан",
)
BOOK_REFERENCE_MARKERS = (
    "учебник", "учебнике", "страниц", "параграф", "§", "book mode",
)
COMPARE_MARKERS = (
    "сравни", "сопостав", "сравнить", "вместе с", "и файл", "и pdf",
)


def normalize_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in {GENERAL_MODE, BOOK_MODE, ATTACHMENT_MODE} else GENERAL_MODE


def explicit_attachment_reference(text: str) -> bool:
    lowered = (text or "").casefold().replace("ё", "е")
    return any(marker.replace("ё", "е") in lowered for marker in ATTACHMENT_REFERENCE_MARKERS)


def explicit_book_reference(text: str) -> bool:
    """Return True when the user explicitly refers to a textbook/page/paragraph."""
    lowered = (text or "").casefold().replace("ё", "е")
    return any(marker.replace("ё", "е") in lowered for marker in BOOK_REFERENCE_MARKERS)


def explicit_mixed_source_request(text: str) -> bool:
    lowered = (text or "").casefold().replace("ё", "е")
    has_attachment = any(
        marker.replace("ё", "е") in lowered for marker in ATTACHMENT_REFERENCE_MARKERS
    )
    has_book = any(
        marker.replace("ё", "е") in lowered for marker in BOOK_REFERENCE_MARKERS
    )
    return has_attachment and has_book and any(marker in lowered for marker in COMPARE_MARKERS)


def active_attachment_ids(session: Any) -> List[int]:
    try:
        raw = session["active_attachment_ids"] or []
    except (KeyError, TypeError, AttributeError):
        return []
    result: List[int] = []
    for value in raw:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed not in result:
            result.append(parsed)
    return result[:8]


def context_activated_at(session: Any) -> Optional[datetime]:
    try:
        value = session["active_context_updated_at"]
    except (KeyError, TypeError, AttributeError):
        return None
    return value if isinstance(value, datetime) else None


def filter_history_since_activation(
    history: Sequence[Dict[str, Any]],
    activated_at: Optional[datetime],
    current_message_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if activated_at is None:
        return list(history)
    result: List[Dict[str, Any]] = []
    for item in history:
        if current_message_id is not None and item.get("message_id") == current_message_id:
            result.append(item)
            continue
        created_at = item.get("created_at")
        if isinstance(created_at, datetime) and created_at >= activated_at:
            result.append(item)
    return result


async def ensure_telegram_session_row(conn, user_id: int):
    row = await conn.fetchrow(
        """
        SELECT session_id, user_id, title, book_id, page_id, context_locked,
               chat_type, active_context_mode, active_paragraph,
               active_attachment_ids, active_context_updated_at,
               created_at, updated_at
        FROM chat_sessions
        WHERE user_id = $1 AND chat_type = 'telegram_default'
        LIMIT 1
        """,
        user_id,
    )
    if row:
        return row

    new_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO chat_sessions (
            session_id, user_id, title, chat_type, active_context_mode
        )
        VALUES ($1, $2, $3, 'telegram_default', 'general')
        ON CONFLICT (user_id)
            WHERE chat_type = 'telegram_default'
        DO NOTHING
        """,
        new_id,
        user_id,
        TELEGRAM_CHAT_TITLE,
    )
    row = await conn.fetchrow(
        """
        SELECT session_id, user_id, title, book_id, page_id, context_locked,
               chat_type, active_context_mode, active_paragraph,
               active_attachment_ids, active_context_updated_at,
               created_at, updated_at
        FROM chat_sessions
        WHERE user_id = $1 AND chat_type = 'telegram_default'
        LIMIT 1
        """,
        user_id,
    )
    if not row:
        raise RuntimeError("Не удалось создать постоянный Telegram-чат")
    return row


async def activate_book_context(
    conn,
    *,
    user_id: int,
    session_id,
    book_id: int,
    page_id: Optional[int],
    paragraph: Optional[str] = None,
):
    row = await conn.fetchrow(
        """
        UPDATE chat_sessions
        SET book_id = $1,
            page_id = $2,
            context_locked = TRUE,
            active_context_mode = 'book',
            active_paragraph = $3,
            active_attachment_ids = '{}'::integer[],
            active_context_updated_at = CURRENT_TIMESTAMP,
            memory_state = (
                COALESCE(memory_state, '{}'::jsonb)
                - 'referenced_attachment_ids'
                - 'active_task_set_message_id'
                - 'current_task_number'
                - 'current_topic'
            ),
            memory_summary = '',
            memory_updated_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE session_id = $4 AND user_id = $5
        RETURNING active_context_updated_at
        """,
        book_id,
        page_id,
        (paragraph or "").strip() or None,
        session_id,
        user_id,
    )
    if not row:
        raise LookupError("Чат не найден")
    return row["active_context_updated_at"]


async def activate_attachment_context(
    conn,
    *,
    user_id: int,
    session_id,
    attachment_ids: Iterable[int],
):
    ids: List[int] = []
    for value in attachment_ids:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed not in ids:
            ids.append(parsed)
    ids = ids[:8]
    if not ids:
        raise ValueError("Не выбран файл для активного контекста")

    row = await conn.fetchrow(
        """
        UPDATE chat_sessions
        SET book_id = NULL,
            page_id = NULL,
            context_locked = FALSE,
            active_context_mode = 'attachment',
            active_paragraph = NULL,
            active_attachment_ids = $1::integer[],
            active_context_updated_at = CURRENT_TIMESTAMP,
            memory_state = (
                (
                    COALESCE(memory_state, '{}'::jsonb)
                    - 'current_book_id'
                    - 'current_page_id'
                    - 'active_task_set_message_id'
                    - 'current_task_number'
                    - 'current_topic'
                    - 'referenced_attachment_ids'
                )
                || jsonb_build_object(
                    'referenced_attachment_ids',
                    to_jsonb($1::integer[])
                )
            ),
            memory_summary = '',
            memory_updated_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE session_id = $2 AND user_id = $3
        RETURNING active_context_updated_at
        """,
        ids,
        session_id,
        user_id,
    )
    if not row:
        raise LookupError("Чат не найден")
    return row["active_context_updated_at"]


async def activate_general_context(conn, *, user_id: int, session_id):
    row = await conn.fetchrow(
        """
        UPDATE chat_sessions
        SET book_id = NULL,
            page_id = NULL,
            context_locked = FALSE,
            active_context_mode = 'general',
            active_paragraph = NULL,
            active_attachment_ids = '{}'::integer[],
            active_context_updated_at = CURRENT_TIMESTAMP,
            memory_state = (
                COALESCE(memory_state, '{}'::jsonb)
                - 'current_book_id'
                - 'current_page_id'
                - 'referenced_attachment_ids'
                - 'active_task_set_message_id'
                - 'current_task_number'
                - 'current_topic'
            ),
            memory_summary = '',
            memory_updated_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE session_id = $1 AND user_id = $2
        RETURNING session_id, title, chat_type, active_context_mode,
                  context_locked, active_context_updated_at
        """,
        session_id,
        user_id,
    )
    if not row:
        raise LookupError("Чат не найден")
    return row
