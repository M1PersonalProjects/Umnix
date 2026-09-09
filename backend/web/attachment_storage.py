import asyncio
import hashlib
import mimetypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import HTTPException, UploadFile, status

from config import settings
from database import db
from logger_config import logger
from backend.web.file_parser import (
    AttachmentError,
    ParsedAttachment,
    attachment_size_limit,
    parse_attachment,
)


ATTACHMENTS_ROOT = settings.absolute_path(settings.attachments_dir)


@dataclass
class StoredAttachment:
    attachment_id: int
    owner_id: int
    original_name: str
    storage_name: str
    storage_path: str
    mime_type: str
    extension: str
    size_bytes: int
    extracted_text: str
    processing_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "owner_id": self.owner_id,
            "original_name": self.original_name,
            "mime_type": self.mime_type,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "processing_status": self.processing_status,
            "download_url": f"/api/v1/attachments/{self.attachment_id}/download",
            "preview_url": f"/api/v1/attachments/{self.attachment_id}/preview",
        }


def ensure_storage_directory() -> None:
    ATTACHMENTS_ROOT.mkdir(parents=True, exist_ok=True)


def _safe_original_name(filename: Optional[str]) -> str:
    value = Path(filename or "attachment").name.strip()

    if not value:
        return "attachment"

    return value[:512]


def _resolve_storage_path(storage_path: str) -> Path:
    candidate = (ATTACHMENTS_ROOT / storage_path).resolve()
    root = ATTACHMENTS_ROOT.resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный путь вложения",
        ) from exc

    return candidate


async def save_upload(
    upload: UploadFile,
    owner_id: int,
) -> StoredAttachment:
    ensure_storage_directory()

    original_name = _safe_original_name(upload.filename)
    mime_type = (
        upload.content_type
        or mimetypes.guess_type(original_name)[0]
        or "application/octet-stream"
    )

    data = await upload.read()

    try:
        parsed: ParsedAttachment = await asyncio.to_thread(
            parse_attachment,
            data,
            original_name,
            mime_type,
        )
    except AttachmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Attachment parsing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Не удалось обработать вложение",
        ) from exc

    size_limit = attachment_size_limit(original_name, mime_type)

    if len(data) > size_limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Файл превышает допустимый размер",
        )

    extension = Path(original_name).suffix.lower()
    storage_name = f"{uuid.uuid4().hex}{extension}"

    relative_directory = Path(
        str(owner_id),
        str(uuid.uuid4().hex[:2]),
    )
    relative_path = relative_directory / storage_name
    absolute_path = _resolve_storage_path(str(relative_path))

    absolute_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        await asyncio.to_thread(absolute_path.write_bytes, data)
    except OSError as exc:
        logger.exception("Could not save attachment: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сохранить файл",
        ) from exc

    digest = hashlib.sha256(data).hexdigest()

    try:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO attachments (
                    owner_id,
                    original_name,
                    storage_name,
                    storage_path,
                    mime_type,
                    extension,
                    size_bytes,
                    sha256,
                    extracted_text,
                    preview_status,
                    processing_status
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9,
                    'not_required',
                    'ready'
                )
                RETURNING
                    attachment_id,
                    owner_id,
                    original_name,
                    storage_name,
                    storage_path,
                    mime_type,
                    extension,
                    size_bytes,
                    extracted_text,
                    processing_status
                """,
                owner_id,
                original_name,
                storage_name,
                str(relative_path),
                mime_type,
                extension or None,
                len(data),
                digest,
                parsed.extracted_text or None,
            )
    except Exception:
        absolute_path.unlink(missing_ok=True)
        raise

    return StoredAttachment(
        attachment_id=row["attachment_id"],
        owner_id=row["owner_id"],
        original_name=row["original_name"],
        storage_name=row["storage_name"],
        storage_path=row["storage_path"],
        mime_type=row["mime_type"],
        extension=row["extension"] or "",
        size_bytes=row["size_bytes"],
        extracted_text=row["extracted_text"] or "",
        processing_status=row["processing_status"],
    )


async def get_attachment(
    attachment_id: int,
) -> dict[str, Any]:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                attachment_id,
                owner_id,
                original_name,
                storage_name,
                storage_path,
                mime_type,
                extension,
                size_bytes,
                sha256,
                extracted_text,
                preview_status,
                preview_path,
                processing_status,
                processing_error,
                created_at
            FROM attachments
            WHERE attachment_id = $1
            """,
            attachment_id,
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вложение не найдено",
        )

    result = dict(row)
    result["absolute_path"] = _resolve_storage_path(result["storage_path"])
    return result


async def ensure_attachment_access(
    attachment_id: int,
    user: dict[str, Any],
) -> dict[str, Any]:
    attachment = await get_attachment(attachment_id)

    if user.get("is_admin"):
        return attachment

    if attachment["owner_id"] == user["tg_id"]:
        return attachment

    async with db.pool.acquire() as conn:
        allowed = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM task_attachments ta
                JOIN tasks_history th ON th.task_id = ta.task_id
                WHERE ta.attachment_id = $1
                  AND (
                      (th.parent_id = $2 AND th.assignment_source = 'teacher')
                      OR (
                          th.student_id = $2
                          AND ta.visible_to_student = true
                      )
                  )
            )
            OR EXISTS (
                SELECT 1
                FROM task_submission_attachments tsa
                JOIN task_submissions ts
                    ON ts.submission_id = tsa.submission_id
                JOIN tasks_history th
                    ON th.task_id = ts.task_id
                WHERE tsa.attachment_id = $1
                  AND (
                      ts.student_id = $2
                      OR (th.parent_id = $2 AND th.assignment_source = 'teacher')
                  )
            )
            """,
            attachment_id,
            user["tg_id"],
        )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этому вложению",
        )

    return attachment


async def validate_owned_attachments(
    conn,
    attachment_ids: Iterable[int],
    owner_id: int,
) -> list[dict[str, Any]]:
    normalized_ids = list(dict.fromkeys(int(item) for item in attachment_ids))

    if not normalized_ids:
        return []

    if len(normalized_ids) > 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="К одному заданию можно прикрепить не более 10 файлов",
        )

    rows = await conn.fetch(
        """
        SELECT
            attachment_id,
            owner_id,
            original_name,
            storage_path,
            mime_type,
            extension,
            size_bytes,
            extracted_text,
            processing_status
        FROM attachments
        WHERE attachment_id = ANY($1::bigint[])
          AND owner_id = $2
        ORDER BY created_at
        """,
        normalized_ids,
        owner_id,
    )

    found_ids = {row["attachment_id"] for row in rows}
    missing_ids = [
        attachment_id
        for attachment_id in normalized_ids
        if attachment_id not in found_ids
    ]

    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Вложения не найдены или недоступны: {missing_ids}",
        )

    failed = [
        row["original_name"]
        for row in rows
        if row["processing_status"] != "ready"
    ]

    if failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Вложения ещё не обработаны: {', '.join(failed)}",
        )

    rows_by_id = {row["attachment_id"]: dict(row) for row in rows}
    return [rows_by_id[attachment_id] for attachment_id in normalized_ids]


async def load_attachment_for_ai(
    attachment: dict[str, Any],
) -> ParsedAttachment:
    path = _resolve_storage_path(attachment["storage_path"])

    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Файл «{attachment['original_name']}» отсутствует в хранилище",
        )

    data = await asyncio.to_thread(path.read_bytes)

    try:
        return await asyncio.to_thread(
            parse_attachment,
            data,
            attachment["original_name"],
            attachment["mime_type"],
        )
    except AttachmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Не удалось прочитать «{attachment['original_name']}»: {exc}",
        ) from exc


async def list_chat_attachment_library(owner_id: int) -> list[dict[str, Any]]:
    """Возвращает вложения пользователя, сгруппированные по чатам WebApp и Telegram."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                a.attachment_id,
                a.original_name,
                a.mime_type,
                a.extension,
                a.size_bytes,
                a.processing_status,
                a.created_at AS attachment_created_at,
                cm.message_id,
                cm.message_source,
                cm.created_at AS message_created_at,
                s.session_id,
                s.title AS chat_title,
                s.chat_type,
                s.updated_at AS chat_updated_at
            FROM attachments a
            JOIN chat_message_attachments cma
              ON cma.attachment_id = a.attachment_id
            JOIN chat_messages cm
              ON cm.message_id = cma.message_id
             AND cm.user_id = $1
            JOIN chat_sessions s
              ON s.session_id = cm.session_id
             AND s.user_id = $1
            WHERE a.owner_id = $1
            ORDER BY s.updated_at DESC, cm.created_at DESC, a.attachment_id DESC
            """,
            owner_id,
        )

    groups: dict[str, dict[str, Any]] = {}
    seen_by_group: dict[str, set[int]] = {}
    for raw in rows:
        row = dict(raw)
        session_id = str(row["session_id"])
        group = groups.setdefault(
            session_id,
            {
                "session_id": session_id,
                "title": row.get("chat_title") or "Новый чат",
                "chat_type": row.get("chat_type") or "web",
                "source": (
                    "telegram"
                    if row.get("chat_type") == "telegram_default"
                    or row.get("message_source") == "telegram"
                    else "web"
                ),
                "updated_at": row.get("chat_updated_at"),
                "attachments": [],
            },
        )
        attachment_id = int(row["attachment_id"])
        seen = seen_by_group.setdefault(session_id, set())
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        group["attachments"].append(
            {
                "attachment_id": attachment_id,
                "original_name": row["original_name"],
                "mime_type": row["mime_type"],
                "extension": row["extension"],
                "size_bytes": row["size_bytes"],
                "processing_status": row["processing_status"],
                "created_at": row.get("message_created_at") or row.get("attachment_created_at"),
                "message_id": row.get("message_id"),
                "message_source": row.get("message_source") or "web",
                "download_url": f"/api/v1/attachments/{attachment_id}/download",
                "preview_url": f"/api/v1/attachments/{attachment_id}/preview",
            }
        )

    return [group for group in groups.values() if group["attachments"]]


async def forget_attachment_from_chat_memory(
    attachment_id: int,
    owner_id: int,
) -> dict[str, Any]:
    """Удаляет файл из памяти чатов и физически удаляет его, если он больше нигде не нужен."""
    path_to_delete: Optional[Path] = None
    links_removed = 0
    retained_for_tasks = False

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            attachment = await conn.fetchrow(
                """
                SELECT attachment_id, storage_path
                FROM attachments
                WHERE attachment_id = $1 AND owner_id = $2
                FOR UPDATE
                """,
                attachment_id,
                owner_id,
            )
            if not attachment:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Вложение не найдено",
                )

            message_rows = await conn.fetch(
                """
                SELECT DISTINCT cm.message_id
                FROM chat_message_attachments cma
                JOIN chat_messages cm ON cm.message_id = cma.message_id
                WHERE cma.attachment_id = $1 AND cm.user_id = $2
                """,
                attachment_id,
                owner_id,
            )
            message_ids = [int(row["message_id"]) for row in message_rows]
            links_removed = len(message_ids)

            await conn.execute(
                """
                DELETE FROM chat_message_attachments cma
                USING chat_messages cm
                WHERE cma.message_id = cm.message_id
                  AND cma.attachment_id = $1
                  AND cm.user_id = $2
                """,
                attachment_id,
                owner_id,
            )

            if message_ids:
                await conn.execute(
                    """
                    UPDATE chat_messages
                    SET attachment_name = NULL, attachment_type = NULL
                    WHERE user_id = $1 AND message_id = ANY($2::bigint[])
                    """,
                    owner_id,
                    message_ids,
                )

            # Если файл был активным файловым контекстом, убираем только его ID.
            await conn.execute(
                """
                UPDATE chat_sessions
                SET active_attachment_ids = array_remove(
                        COALESCE(active_attachment_ids, '{}'::integer[]), $1
                    ),
                    active_context_mode = CASE
                        WHEN active_context_mode = 'attachment'
                         AND cardinality(array_remove(COALESCE(active_attachment_ids, '{}'::integer[]), $1)) = 0
                        THEN 'general'
                        ELSE active_context_mode
                    END,
                    memory_state = (COALESCE(memory_state, '{}'::jsonb) - 'referenced_attachment_ids')
                        || CASE
                            WHEN cardinality(array_remove(COALESCE(active_attachment_ids, '{}'::integer[]), $1)) > 0
                            THEN jsonb_build_object(
                                'referenced_attachment_ids',
                                to_jsonb(array_remove(COALESCE(active_attachment_ids, '{}'::integer[]), $1))
                            )
                            ELSE '{}'::jsonb
                           END,
                    memory_updated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = $2
                  AND $1 = ANY(COALESCE(active_attachment_ids, '{}'::integer[]))
                """,
                attachment_id,
                owner_id,
            )

            retained_for_tasks = bool(
                await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM task_attachments WHERE attachment_id = $1
                    ) OR EXISTS (
                        SELECT 1 FROM task_submission_attachments WHERE attachment_id = $1
                    ) OR EXISTS (
                        SELECT 1
                        FROM task_drafts td, jsonb_array_elements_text(td.attachment_ids) item
                        WHERE td.status = 'draft' AND item.value = $1::text
                    )
                    """,
                    attachment_id,
                )
            )

            if not retained_for_tasks:
                remaining_chat_links = bool(
                    await conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM chat_message_attachments WHERE attachment_id = $1)",
                        attachment_id,
                    )
                )
                if not remaining_chat_links:
                    await conn.execute(
                        "DELETE FROM attachments WHERE attachment_id = $1 AND owner_id = $2",
                        attachment_id,
                        owner_id,
                    )
                    path_to_delete = _resolve_storage_path(attachment["storage_path"])

    if path_to_delete is not None:
        try:
            await asyncio.to_thread(path_to_delete.unlink, missing_ok=True)
        except OSError:
            logger.warning("Could not delete forgotten attachment file: %s", path_to_delete)

    return {
        "attachment_id": attachment_id,
        "chat_links_removed": links_removed,
        "deleted_from_storage": path_to_delete is not None,
        "retained_for_tasks": retained_for_tasks,
    }


async def delete_attachment(
    attachment_id: int,
    owner_id: int,
) -> None:
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            attachment = await conn.fetchrow(
                """
                SELECT attachment_id, storage_path
                FROM attachments
                WHERE attachment_id = $1
                  AND owner_id = $2
                FOR UPDATE
                """,
                attachment_id,
                owner_id,
            )

            if not attachment:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Вложение не найдено",
                )

            in_use = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM chat_message_attachments
                    WHERE attachment_id = $1
                )
                OR EXISTS (
                    SELECT 1
                    FROM task_attachments
                    WHERE attachment_id = $1
                )
                OR EXISTS (
                    SELECT 1
                    FROM task_submission_attachments
                    WHERE attachment_id = $1
                )
                """,
                attachment_id,
            )

            if in_use:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Вложение уже используется и не может быть удалено",
                )

            await conn.execute(
                """
                DELETE FROM attachments
                WHERE attachment_id = $1
                """,
                attachment_id,
            )

    path = _resolve_storage_path(attachment["storage_path"])

    try:
        await asyncio.to_thread(path.unlink, missing_ok=True)
    except OSError:
        logger.warning("Could not delete attachment file: %s", path)