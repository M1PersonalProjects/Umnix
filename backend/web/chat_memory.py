from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.web.attachment_storage import load_attachment_for_ai

SHORT_TERM_MESSAGES = 15


async def load_context_messages(
    conn,
    user_id: int,
    session_id,
    current_query: str = "",
) -> List[Dict[str, Any]]:
    """Возвращает последние 15 сообщений только текущего чата."""
    del current_query
    rows = await conn.fetch(
        """
        SELECT message_id, sender, message_text, created_at
        FROM chat_messages
        WHERE user_id = $1 AND session_id = $2
        ORDER BY created_at DESC, message_id DESC
        LIMIT $3
        """,
        user_id,
        session_id,
        SHORT_TERM_MESSAGES,
    )
    return [dict(row) for row in reversed(rows)]


async def session_attachments(
    conn,
    user_id: int,
    session_id,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Возвращает все уникальные вложения только текущего чата."""
    rows = await conn.fetch(
        """
        SELECT
            a.attachment_id,
            a.owner_id,
            a.original_name,
            a.storage_path,
            a.mime_type,
            a.extension,
            a.size_bytes,
            a.extracted_text,
            a.processing_status,
            a.created_at,
            cma.message_id,
            cm.created_at AS message_created_at
        FROM chat_message_attachments cma
        JOIN chat_messages cm ON cm.message_id = cma.message_id
        JOIN attachments a ON a.attachment_id = cma.attachment_id
        WHERE cm.user_id = $1
          AND cm.session_id = $2
          AND a.owner_id = $1
        ORDER BY cm.created_at ASC, cma.sort_order ASC, a.attachment_id ASC
        """,
        user_id,
        session_id,
    )
    result: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for raw in rows:
        row = dict(raw)
        attachment_id = int(row["attachment_id"])
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        result.append(row)
        if limit is not None and len(result) >= max(0, int(limit)):
            break
    return result


def attachment_inventory(rows: Sequence[Dict[str, Any]]) -> str:
    """Формирует краткий список файлов текущего чата."""
    items: List[str] = []
    for row in rows:
        attachment_id = row.get("attachment_id")
        name = str(row.get("original_name") or f"attachment-{attachment_id}").strip()
        mime = str(row.get("mime_type") or row.get("extension") or "file").strip()
        items.append(f"- attachment_id={attachment_id}: {name} ({mime})")
    if not items:
        return ""
    return "Files attached to this chat:\n" + "\n".join(items)


async def build_attachment_context(
    selected: Sequence[Dict[str, Any]],
    query: str = "",
) -> Tuple[str, List[str]]:
    """Передаёт ИИ содержимое всех файлов текущего чата."""
    del query
    text_blocks: List[str] = []
    image_urls: List[str] = []
    for row in selected:
        text = str(row.get("extracted_text") or "").strip()
        if text:
            text_blocks.append(
                f"[Attachment {row['attachment_id']}: {row['original_name']}]\n{text}"
            )
        mime = str(row.get("mime_type") or "")
        if mime.startswith("image/") or mime == "application/pdf":
            parsed = await load_attachment_for_ai(row)
            image_urls.extend(parsed.image_data_urls)
    return "\n\n".join(text_blocks), list(dict.fromkeys(image_urls))


async def message_attachments_payload(
    conn,
    user_id: int,
    message_ids: Iterable[int],
) -> Dict[int, List[Dict[str, Any]]]:
    """Возвращает метаданные вложений для вывода в истории чата."""
    ids = [int(value) for value in message_ids]
    if not ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT
            cma.message_id,
            a.attachment_id,
            a.original_name,
            a.mime_type,
            a.extension,
            a.size_bytes,
            a.processing_status,
            a.created_at
        FROM chat_message_attachments cma
        JOIN chat_messages cm ON cm.message_id = cma.message_id
        JOIN attachments a ON a.attachment_id = cma.attachment_id
        WHERE cma.message_id = ANY($1::int[])
          AND cm.user_id = $2
          AND a.owner_id = $2
        ORDER BY cma.message_id, cma.sort_order, a.attachment_id
        """,
        ids,
        user_id,
    )
    result: Dict[int, List[Dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        attachment_id = int(row["attachment_id"])
        payload = {
            "attachment_id": attachment_id,
            "original_name": row["original_name"],
            "mime_type": row["mime_type"],
            "extension": row["extension"],
            "size_bytes": row["size_bytes"],
            "processing_status": row["processing_status"],
            "created_at": row["created_at"],
            "download_url": f"/api/v1/attachments/{attachment_id}/download",
            "preview_url": f"/api/v1/attachments/{attachment_id}/preview",
        }
        result.setdefault(int(row["message_id"]), []).append(payload)
    return result
