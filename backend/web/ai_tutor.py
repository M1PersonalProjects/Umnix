import asyncio
import re
import uuid
from typing import Any, Dict, List, Optional


from config import settings
from database import db
from backend.web.context_resolver import ResolvedContext, load_locked_context, resolve_context
from backend.web.educational_context import build_educational_context
from backend.web.task_generation import find_requested_task_count
from backend.web.file_parser import ParsedAttachment

from backend.web.prompts import AI_TUTOR_SYSTEM_PROMPT
from backend.web.interactive_apps import (
    InteractiveAppTemporaryError,
    maybe_handle_chat_request,
    card_text as interactive_card_text,
    set_source_message as set_interactive_source_message,
)
from backend.web.response_formatter import canonicalize_message
from logger_config import logger
from backend.web.ai.client import create_chat_completion, openai_client
from backend.web.chat_memory import (
    attachment_inventory,
    build_attachment_context,
    load_context_messages,
    message_attachments_payload,
    session_attachments,
)
from backend.web.conversation_context import (
    ATTACHMENT_MODE,
    BOOK_MODE,
    activate_book_context,
    activate_general_context,
    context_activated_at,
    ensure_telegram_session_row,
    explicit_book_reference,
    normalize_mode,
)




def _session_uuid(session_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(session_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LookupError("Некорректный идентификатор чата") from exc


def _session_field(session: Any, key: str, default: Any = None) -> Any:
    """Read a concrete value without calling AsyncMock.get() in tests."""
    try:
        value = session[key]
    except (KeyError, TypeError, AttributeError):
        return default
    # Real asyncpg values are primitives/UUIDs. Mock placeholders are not
    # meaningful application state and should behave like a missing field.
    if isinstance(value, (str, int, float, bool, uuid.UUID)) or value is None:
        return value
    return default


def clean_ai_text(value: Optional[str]) -> str:
    """
    Убирает LaTeX-формулы и лишние спецсимволы из текста, оставляя только чистый текст.
    """
    text = str(value or "").replace("$", "")
    text = text.replace("\\(", "").replace("\\)", "")
    text = text.replace("\\[", "").replace("\\]", "")
    text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\sqrt\{([^{}]+)\}", r"√(\1)", text)
    text = re.sub(r"\\(?:begin|end)\{[^}]+\}", "", text)
    return re.sub(r"\\[A-Za-z]+\*?", "", text).strip()


def book_mode_footer(context: ResolvedContext) -> str:
    return (
        f"\n\n---\n📘 Основной учебный контекст: «{context.label}». "
        "Сначала использован выбранный учебник; при нехватке материала Umnix может "
        "добавить релевантное внешнее пояснение. Чтобы выйти из Book Mode, используйте /exit_book."
    )

async def ensure_session(conn, user_id: int, session_id: Optional[str] = None):
    if session_id:
        parsed_id = _session_uuid(session_id)
        session = await conn.fetchrow(
            """
            SELECT session_id, user_id, title, book_id, page_id, context_locked,
                   chat_type, active_context_mode, active_paragraph,
                   active_attachment_ids, active_context_updated_at,
                   created_at, updated_at
            FROM chat_sessions WHERE session_id = $1 AND user_id = $2
            """,
            parsed_id,
            user_id,
        )
        if not session:
            raise LookupError("Чат не найден")
        return session

    session = await conn.fetchrow(
        """
        SELECT session_id, user_id, title, book_id, page_id, context_locked,
               chat_type, active_context_mode, active_paragraph,
               active_attachment_ids, active_context_updated_at,
               created_at, updated_at
        FROM chat_sessions WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1
        """,
        user_id,
    )
    if not session:
        new_id = uuid.uuid4()
        session = await conn.fetchrow(
            """
            INSERT INTO chat_sessions (session_id, user_id, title)
            VALUES ($1, $2, 'Новый чат')
            RETURNING session_id, user_id, title, book_id, page_id, context_locked,
                      chat_type, active_context_mode, active_paragraph,
                      active_attachment_ids, active_context_updated_at,
                      created_at, updated_at
            """,
            new_id,
            user_id,
        )
        await conn.execute(
            "UPDATE chat_messages SET session_id = $1 WHERE user_id = $2 AND session_id IS NULL",
            new_id,
            user_id,
        )
    return session


async def ensure_telegram_session(
    user_id: int,
) -> Dict[str, Any]:
    async with db.pool.acquire() as conn:
        row = await ensure_telegram_session_row(conn, user_id)
    return dict(row)


async def create_session(user_id: int, title: str = "Новый чат") -> Dict[str, Any]:
    session_id = uuid.uuid4()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO chat_sessions (session_id, user_id, title)
            VALUES ($1, $2, $3)
            RETURNING session_id, user_id, title, book_id, page_id, context_locked,
                      created_at, updated_at
            """,
            session_id,
            user_id,
            (title.strip() or "Новый чат")[:35],
        )
    return dict(row)


async def list_sessions(user_id: int) -> List[Dict[str, Any]]:
    async with db.pool.acquire() as conn:
        await ensure_session(conn, user_id)
        rows = await conn.fetch(
            """
            SELECT s.session_id, s.title, s.book_id, s.page_id, s.context_locked,
                    s.chat_type, s.active_context_mode, s.active_paragraph,
                    s.active_attachment_ids, s.active_context_updated_at,
                   s.created_at, s.updated_at, COUNT(m.message_id) AS message_count,
                   b.book_title, p.page_number
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON m.session_id = s.session_id
            LEFT JOIN book b ON b.book_id = s.book_id
            LEFT JOIN page p ON p.page_id = s.page_id
            WHERE s.user_id = $1
            GROUP BY s.session_id, b.book_title, p.page_number
            ORDER BY s.updated_at DESC
            """,
            user_id,
        )
    return [dict(row) for row in rows]


async def rename_session(user_id: int, session_id: str, title: str) -> Dict[str, Any]:
    clean_title = title.strip()
    if not clean_title or len(clean_title) > 35:
        raise ValueError("Название должно содержать от 1 до 35 символов")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE chat_sessions SET title = $1, updated_at = CURRENT_TIMESTAMP
            WHERE session_id = $2 AND user_id = $3
            RETURNING session_id, title, book_id, page_id, context_locked, updated_at
            """,
            clean_title,
            _session_uuid(session_id),
            user_id,
        )
    if not row:
        raise LookupError("Чат не найден")
    return dict(row)


async def delete_session(user_id: int, session_id: str) -> None:
    async with db.pool.acquire() as conn:
        session = await conn.fetchrow(
            """
            SELECT session_id, chat_type
            FROM chat_sessions
            WHERE session_id = $1 AND user_id = $2
            """,
            _session_uuid(session_id),
            user_id,
        )
        if not session:
            raise LookupError("Чат не найден")
        if session["chat_type"] == "telegram_default":
            raise ValueError(
                "Постоянный Telegram-чат нельзя удалить. "
                "Его можно переименовать и использовать как обычный чат в WebApp."
            )
        await conn.execute(
            "DELETE FROM chat_sessions WHERE session_id = $1 AND user_id = $2",
            session["session_id"],
            user_id,
        )


async def get_messages(user_id: int, session_id: str) -> List[Dict[str, Any]]:
    async with db.pool.acquire() as conn:
        session = await ensure_session(conn, user_id, session_id)
        rows = await conn.fetch(
            """
            SELECT message_id, sender, message_text, attachment_name, attachment_type,
                   message_source, created_at
            FROM chat_messages
            WHERE user_id = $1 AND session_id = $2
            ORDER BY created_at ASC, message_id ASC
            LIMIT 500
            """,
            user_id,
            session["session_id"],
        )
        profile = await conn.fetchrow(
            "SELECT tg_id, username FROM users WHERE tg_id=$1",
            user_id,
        )
        display_name = (
            str(profile["username"]).strip()
            if profile and profile["username"]
            else str(user_id)
        )
        message_ids = [row["message_id"] for row in rows]
        attachments = await message_attachments_payload(conn, user_id, message_ids)
        app_rows = []
        if message_ids:
            app_rows = await conn.fetch(
                """
                SELECT a.app_id, a.owner_id, a.session_id,
                       COALESCE(v.source_message_id, a.source_message_id) AS source_message_id,
                       a.title, a.app_type, a.question_count, a.current_version, a.created_at, a.updated_at,
                       v.version_no, v.version_id, v.parent_version_id
                FROM interactive_apps a
                JOIN interactive_app_versions v ON v.app_id=a.app_id
                WHERE a.owner_id=$1 AND a.session_id=$3
                  AND COALESCE(
                      v.source_message_id,
                      CASE WHEN v.version_no=a.current_version THEN a.source_message_id END
                  ) = ANY($2::bigint[])
                """,
                user_id,
                message_ids,
                session["session_id"],
            )
    app_by_message = {}
    for app in app_rows:
        data = dict(app)
        data["app_id"] = str(data["app_id"])
        data["session_id"] = str(data["session_id"])
        data["version_no"] = int(data.get("version_no") or data.get("current_version") or 1)
        data["open_url"] = f"/interactive/{data['app_id']}?version={data['version_no']}"
        data["download_url"] = f"/api/v1/interactive/{data['app_id']}/download?version={data['version_no']}"
        app_by_message[app["source_message_id"]] = data
    result = []
    for row in rows:
        item = dict(row)
        item["sender_name"] = display_name if row["sender"] == "user" else "Umnix"
        item["attachments"] = attachments.get(row["message_id"], [])
        item["interactive_app"] = app_by_message.get(row["message_id"])
        result.append(item)
    return result

async def lock_context(
    user_id: int,
    session_id: str,
    manual_context: Dict[str, Any],
) -> ResolvedContext:
    async with db.pool.acquire() as conn:
        session = await ensure_session(conn, user_id, session_id)
        context = await resolve_context(conn, "", manual_context)
        if not context:
            raise LookupError("Не удалось найти выбранный учебный контекст")
        await activate_book_context(
            conn,
            user_id=user_id,
            session_id=session["session_id"],
            book_id=context.book_id,
            page_id=context.page_id,
            paragraph=context.page_paragraph,
        )
    context.source = "locked"
    return context


async def exit_book_mode(user_id: int, session_id: Optional[str] = None) -> Dict[str, Any]:
    async with db.pool.acquire() as conn:
        session = await ensure_session(conn, user_id, session_id)
        row = await activate_general_context(
            conn,
            user_id=user_id,
            session_id=session["session_id"],
        )
    return dict(row)




def _knowledge_source(
    *,
    locked_context: Optional[ResolvedContext],
    database_context: str,
    web_context: str,
) -> str:
    if locked_context and web_context:
        return "book+web"
    if locked_context:
        return "book_mode"
    if database_context and web_context:
        return "database+web"
    if database_context:
        return "database"
    if web_context:
        return "web"
    return "model"


async def search_web_for_education(query: str) -> str:
    """Выполняет web search по исходному запросу пользователя."""
    try:
        response = await asyncio.wait_for(
            openai_client.responses.create(
                model=settings.openai_model,
                tools=[{"type": "web_search_preview"}],
                input=str(query or "").strip(),
            ),
            timeout=90,
        )
        return clean_ai_text(getattr(response, "output_text", ""))[:12000]
    except Exception:
        return ""


def _explicit_web_search(query: str) -> bool:
    value = str(query or "").casefold().replace("ё", "е")
    markers = (
        "в интернете",
        "найди в интернете",
        "поищи в интернете",
        "web search",
        "актуальн",
        "сегодня",
        "последние данные",
        "последние новости",
        "на данный момент",
        "проверь источник",
    )
    return any(marker in value for marker in markers)


def _runtime_context_text(
    role: str,
    context: Optional[ResolvedContext],
    *,
    attachment_text: str = "",
    database_context: str = "",
    web_context: str = "",
    attachments_inventory: str = "",
    output_channel: str = "web",
) -> str:
    """Собирает только фактические данные, которые приложение передаёт тьютору."""
    blocks = [f"USER ROLE: {role}"]
    if context:
        blocks.append(
            "BOOK MODE DATA:\n"
            f"Book: {context.book_title}\n"
            f"Author: {context.book_author or 'not specified'}\n"
            f"Subject: {context.book_program or 'not specified'}\n"
            f"Class: {context.book_class or 'not specified'}\n"
            f"Page: {context.page_number or 'whole selected book'}\n"
            f"Paragraph: {context.page_paragraph or 'not selected'}\n"
            f"Content:\n{str(context.content or '')[:30_000]}"
        )
    if attachment_text:
        blocks.append(f"CHAT ATTACHMENTS DATA:\n{attachment_text[:30_000]}")
    if database_context:
        blocks.append(f"DATABASE MATERIAL:\n{database_context[:20_000]}")
    if web_context:
        blocks.append(f"WEB MATERIAL:\n{web_context[:12_000]}")
    if attachments_inventory:
        blocks.append(f"CHAT FILE LIST:\n{attachments_inventory[:8_000]}")
    if output_channel == "telegram":
        blocks.append("DELIVERY CHANNEL: Telegram; return one concise message when practical.")
    return "\n\n".join(blocks)


async def _save_ai_message(
    user_id: int,
    session_id: uuid.UUID,
    message_text: str,
    message_source: str = "web",
) -> int:
    source = "telegram" if message_source == "telegram" else "web"

    async with db.pool.acquire() as conn:
        message_id = await conn.fetchval(
            """
            INSERT INTO chat_messages
                (user_id, session_id, sender, message_text, message_source)
            VALUES ($1, $2, 'ai', $3, $4)
            RETURNING message_id
            """,
            user_id,
            session_id,
            message_text,
            source,
        )
        await conn.execute(
            """
            UPDATE chat_sessions
            SET updated_at = CURRENT_TIMESTAMP
            WHERE session_id = $1
            """,
            session_id,
        )

    return message_id

async def _generate_conversation_response(
    user_id: int,
    role: str,
    message_text: str,
    session_id: Optional[str] = None,
    attachment: Optional[ParsedAttachment] = None,
    attachment_id: Optional[int] = None,
    manual_context: Optional[Dict[str, Any]] = None,
    lock_selected_context: bool = False,
    message_source: str = "web",
    interactive_app_id: Optional[str] = None,
    interactive_action: Optional[str] = None,
    interactive_version: Optional[int] = None,
) -> Dict[str, Any]:
    clean_text = clean_ai_text(message_text) or "Проанализируй вложение и помоги разобраться."
    if attachment_id is None and attachment is not None:
        candidate_attachment_id = getattr(attachment, "attachment_id", None)
        if isinstance(candidate_attachment_id, int):
            attachment_id = candidate_attachment_id
    if role == "admin":
        role = "parent"
    if role not in {"student", "parent"}:
        raise ValueError("ИИ-тьютор доступен Ученикам и Учителям")

    async with db.pool.acquire() as conn:
        session = await ensure_session(conn, user_id, session_id)
        active_mode = normalize_mode(_session_field(session, "active_context_mode"))
        activated_at = context_activated_at(session)
        locked_context = await load_locked_context(conn, session)
        explicit_context = bool((manual_context or {}).get("book_id"))
        if explicit_context and (lock_selected_context or not locked_context):
            context = await resolve_context(conn, clean_text, manual_context)
        elif locked_context and not locked_context.page_id:
            context = await resolve_context(
                conn, clean_text, {"book_id": locked_context.book_id}
            ) or locked_context
            locked_context = context
        elif locked_context:
            context = locked_context
        elif explicit_book_reference(clean_text):
            # Free AI-helper mode still honors an explicit natural-language textbook
            # reference (e.g. "in textbook X, page 42"). This context applies to
            # the current request without silently locking future messages.
            context = await resolve_context(conn, clean_text, None)
        else:
            context = None

        should_lock_context = bool(lock_selected_context and context)
        if should_lock_context and context:
            activated_at = await activate_book_context(
                conn,
                user_id=user_id,
                session_id=session["session_id"],
                book_id=context.book_id,
                page_id=context.page_id,
                paragraph=context.page_paragraph,
            )
            active_mode = BOOK_MODE
            context.source = "locked"
            locked_context = context
        message_id = await conn.fetchval(
            """
            INSERT INTO chat_messages
                (
                    user_id, session_id, sender, message_text,
                    attachment_name, attachment_type, message_source
                )
            VALUES ($1, $2, 'user', $3, $4, $5, $6) RETURNING message_id
            """,
            user_id,
            session["session_id"],
            clean_text,
            attachment.filename if attachment else None,
            attachment.mime_type if attachment else None,
            "telegram" if message_source == "telegram" else "web",
        )
        if attachment_id is not None:
            owned = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM attachments WHERE attachment_id=$1 AND owner_id=$2)",
                attachment_id,
                user_id,
            )
            if not owned:
                raise LookupError("Вложение не найдено или принадлежит другому пользователю")
            await conn.execute(
                """
                INSERT INTO chat_message_attachments (message_id, attachment_id, session_id, sort_order)
                VALUES ($1, $2, $3, 0)
                ON CONFLICT (message_id, attachment_id) DO UPDATE
                SET session_id=EXCLUDED.session_id
                """,
                message_id,
                attachment_id,
                session["session_id"],
            )

        # Память чатов строго разделена по session_id.
        all_session_attachments = await session_attachments(
            conn,
            user_id,
            session["session_id"],
        )
        selected_attachments = list(all_session_attachments)
        selected_ids = [int(row["attachment_id"]) for row in selected_attachments]
        history = await load_context_messages(
            conn,
            user_id,
            session["session_id"],
            clean_text,
        )
        attachments_inventory_text = attachment_inventory(all_session_attachments)

    interactive_requested = str(interactive_action or "").strip().casefold() in {"create", "edit"}
    current_attachment_text = (
        clean_ai_text(attachment.extracted_text)
        if attachment and attachment.extracted_text
        else ""
    )
    current_image_urls = list(attachment.image_data_urls) if attachment else []

    if interactive_requested:
        attachment_text = current_attachment_text
        image_urls = list(current_image_urls)
    else:
        attachment_text, remembered_image_urls = await build_attachment_context(
            selected_attachments,
            clean_text,
        )
        if current_attachment_text and not attachment_text:
            attachment_text = current_attachment_text
        image_urls = list(dict.fromkeys(current_image_urls + remembered_image_urls))

    interactive_attachment_text = current_attachment_text
    interactive_book_context = locked_context if locked_context else None
    interactive_used_attachment_ids = [attachment_id] if attachment_id is not None else []

    database_context = ""
    web_context = ""
    if not interactive_requested:
        async with db.pool.acquire() as conn:
            educational_bundle = await build_educational_context(
                conn,
                clean_text,
                selected_context=context,
                attachment_text=attachment_text,
                allow_context_resolution=False,
            )
        database_context = educational_bundle.database_context
        requested_learning_items = find_requested_task_count(clean_text)
        needs_count_fallback = bool(
            requested_learning_items
            and requested_learning_items > 8
            and len(database_context) < requested_learning_items * 250
        )
        if needs_count_fallback or _explicit_web_search(clean_text):
            web_context = await search_web_for_education(clean_text)

    try:
        interactive_app = await maybe_handle_chat_request(
            user_id=user_id,
            session_id=session["session_id"],
            message_text=clean_text,
            context=interactive_book_context,
            attachment_text=interactive_attachment_text,
            image_urls=current_image_urls,
            interactive_app_id=interactive_app_id,
            interactive_action=interactive_action,
            interactive_version=interactive_version,
        )
    except InteractiveAppTemporaryError as exc:
        reply = canonicalize_message(str(exc))
        ai_message_id = await _save_ai_message(
            user_id=user_id,
            session_id=session["session_id"],
            message_text=reply,
            message_source=message_source,
        )
        return {
            "message_id": ai_message_id,
            "session_id": str(session["session_id"]),
            "sender": "ai",
            "message_text": reply,
            "context": context.to_dict() if context else None,
            "book_mode": bool(locked_context),
            "used_attachment_ids": interactive_used_attachment_ids,
            "interactive_app": None,
            "interactive_error": True,
            "retryable": True,
        }
    except ValueError as exc:
        logger.warning("Interactive app validation rejected generated content: %s", exc)
        reply = canonicalize_message(
            "Не удалось подготовить интерактивное приложение в нужном качестве. "
            "Попробуйте повторить запрос или уточнить, какие элементы должны быть интерактивными."
        )
        ai_message_id = await _save_ai_message(
            user_id=user_id,
            session_id=session["session_id"],
            message_text=reply,
            message_source=message_source,
        )
        return {
            "message_id": ai_message_id,
            "session_id": str(session["session_id"]),
            "sender": "ai",
            "message_text": reply,
            "context": context.to_dict() if context else None,
            "book_mode": bool(locked_context),
            "interactive_generation_failed": True,
        }

    if interactive_app:
        reply = canonicalize_message(interactive_card_text(interactive_app))
        if locked_context:
            reply += book_mode_footer(locked_context)
        async with db.pool.acquire() as conn:
            ai_message_id = await conn.fetchval(
                """
                INSERT INTO chat_messages
                    (user_id, session_id, sender, message_text, message_source)
                VALUES ($1, $2, 'ai', $3, $4) RETURNING message_id
                """,
                user_id,
                session["session_id"],
                reply,
                "telegram" if message_source == "telegram" else "web",
            )
            if session["title"] == "Новый чат":
                await conn.execute(
                    "UPDATE chat_sessions SET title=$1 WHERE session_id=$2 AND user_id=$3",
                    str(interactive_app.get("title") or "Интерактивное задание")[:35],
                    session["session_id"],
                    user_id,
                )
        await set_interactive_source_message(
            interactive_app["app_id"], ai_message_id, interactive_app.get("version_no")
        )
        return {
            "message_id": ai_message_id,
            "session_id": str(session["session_id"]),
            "sender": "ai",
            "message_text": reply,
            "context": context.to_dict() if context else None,
            "book_mode": bool(locked_context),
            "used_attachment_ids": interactive_used_attachment_ids,
            "interactive_app": interactive_app,
            "knowledge_source": _knowledge_source(
                locked_context=locked_context,
                database_context=database_context,
                web_context=web_context,
            ),
        }
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": AI_TUTOR_SYSTEM_PROMPT}
    ]
    runtime_context = _runtime_context_text(
        role,
        context,
        attachment_text=attachment_text,
        database_context=database_context,
        web_context=web_context,
        attachments_inventory=attachments_inventory_text,
        output_channel=message_source,
    )
    if runtime_context:
        messages.append({
            "role": "user",
            "content": f"APPLICATION DATA FOR THIS REQUEST:\n{runtime_context}",
        })
    for item in history:
        content: Any = item["message_text"]
        if item["message_id"] == message_id and image_urls:
            content = [{"type": "text", "text": item["message_text"]}]
            for image_url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": image_url}})
        messages.append({
            "role": "user" if item["sender"] == "user" else "assistant",
            "content": content,
        })

    # If a previous image is relevant but the current message is text-only, attach it
    # to the current user turn so the multimodal model can inspect the original again.
    if (
        image_urls
        and history
        and history[-1]["message_id"] == message_id
        and not isinstance(messages[-1]["content"], list)
    ):
        messages[-1]["content"] = [
            {"type": "text", "text": history[-1]["message_text"]},
            *[{"type": "image_url", "image_url": {"url": url}} for url in image_urls],
        ]

    response = await asyncio.wait_for(
        create_chat_completion(openai_client,
            messages=messages, temperature=0.35,
            max_tokens=1100 if message_source == "telegram" else 2000
        ),
        timeout=settings.openai_timeout_seconds,
    )
    reply = canonicalize_message(response.choices[0].message.content)
    if locked_context:
        reply += book_mode_footer(locked_context)

    async with db.pool.acquire() as conn:
        ai_message_id = await conn.fetchval(
            """
            INSERT INTO chat_messages
                (user_id, session_id, sender, message_text, message_source)
            VALUES ($1, $2, 'ai', $3, $4) RETURNING message_id
            """,
            user_id,
            session["session_id"],
            reply,
            "telegram" if message_source == "telegram" else "web",
        )
        if session["title"] == "Новый чат":
            generated_title = clean_text.replace("\n", " ")[:35].strip() or "Вложение"
            await conn.execute(
                "UPDATE chat_sessions SET title=$1 WHERE session_id=$2 AND user_id=$3",
                generated_title,
                session["session_id"],
                user_id,
            )

    return {
        "message_id": ai_message_id,
        "session_id": str(session["session_id"]),
        "sender": "ai",
        "message_text": reply,
        "context": context.to_dict() if context else None,
        "book_mode": bool(locked_context),
        "used_attachment_ids": selected_ids,
        "knowledge_source": _knowledge_source(
            locked_context=locked_context,
            database_context=database_context,
            web_context=web_context,
        ),
    }


async def generate_response(
    user_id: int,
    message: str,
    mode: str = "chat",
    *,
    role: Optional[str] = None,
    session_id: Optional[str] = None,
    attachment: Optional[ParsedAttachment] = None,
    attachment_id: Optional[int] = None,
    manual_context: Optional[Dict[str, Any]] = None,
    lock_selected_context: bool = False,
    message_source: str = "web",
    interactive_app_id: Optional[str] = None,
    interactive_version: Optional[int] = None,
    quest_context: Optional[Dict[str, Any]] = None,
    title: str = "",
    original_request: str = "",
    html_document: str = "",
    answers: Optional[Dict[str, Any]] = None,
) -> Any:
    """Единственная публичная точка входа для диалоговых AI-сценариев Umnix."""
    normalized_mode = str(mode or "chat").strip().casefold()
    if role is None:
        async with db.pool.acquire() as conn:
            role = await conn.fetchval("SELECT role::text FROM users WHERE tg_id=$1", user_id)
    if not role:
        raise LookupError("Пользователь не найден")
    resolved_role = "parent" if role == "admin" else str(role)

    if normalized_mode in {"chat", "interactive_create", "interactive_edit"}:
        action = None
        if normalized_mode == "interactive_create":
            action = "create"
        elif normalized_mode == "interactive_edit":
            action = "edit"
        return await _generate_conversation_response(
            user_id=user_id,
            role=resolved_role,
            session_id=session_id,
            message_text=message,
            attachment=attachment,
            attachment_id=attachment_id,
            manual_context=manual_context,
            lock_selected_context=lock_selected_context,
            message_source=message_source,
            interactive_app_id=interactive_app_id,
            interactive_action=action,
            interactive_version=interactive_version,
        )

    if normalized_mode == "quest":
        from backend.web.quest_generation import generate_quest_task_set
        payload = quest_context or {}
        spec = payload.get("spec") or {}
        primary_text = str(payload.get("primary_text") or "none")
        attachment_text = str(payload.get("attachment_text") or "none")
        database_context = str(payload.get("database_context") or "none")
        web_context = str(payload.get("web_context") or "none")
        requested_count = int(payload.get("requested_count") or 5)
        ai_task, questions_json = await generate_quest_task_set(
            openai_client,
            user_content=(
                "Create an engaging Telegram quest-test for a Student. "
                "Infer wording, level and examples from the request, attachment and sources.\n"
                f"Grade: {spec.get('grade')}\n"
                f"Subject: {spec.get('subject')}\n"
                f"Topic: {spec.get('topic')}\n"
                f"Student request: {spec.get('raw_request') or message}\n\n"
                f"ATTACHED MATERIAL:\n{attachment_text}\n\n"
                f"PRIMARY TEXTBOOK CONTEXT:\n{primary_text}\n\n"
                f"RANKED UMNIX KNOWLEDGE-BASE SUPPLEMENTS:\n{database_context}\n\n"
                f"WEB FALLBACK:\n{web_context}"
            ),
            requested_count=requested_count,
        )
        return {"ai_task": ai_task, "questions_json": questions_json}

    if normalized_mode == "interactive_answers":
        if resolved_role != "parent":
            raise PermissionError("Ответы доступны только Учителю")
        from backend.web.interactive_apps import generate_teacher_answer_key
        return await generate_teacher_answer_key(
            title=title,
            request=original_request,
            html_document=html_document,
        )

    if normalized_mode == "interactive_grade":
        from backend.web.interactive_apps import grade_interactive_submission
        return await grade_interactive_submission(
            title=title,
            request=original_request,
            html_document=html_document,
            answers=answers or {},
        )

    raise ValueError(f"Неизвестный AI mode: {mode}")
