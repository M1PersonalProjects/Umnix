import json
from typing import Any, Mapping, Optional

from database import db
from logger_config import logger


def _compact_detail(value: str) -> str:
    return " ".join(str(value or "").split())[:1000]


async def record_activity(
    tg_id: int,
    action: str,
    detail: str = "",
    *,
    source: str = "web",
    session_id: Optional[str] = None,
    attachment_id: Optional[int] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    conn=None,
) -> None:
    clean_action = _compact_detail(action)[:80]
    clean_detail = _compact_detail(detail)
    safe_source = source if source in {"web", "telegram", "system"} else "system"
    payload = json.dumps(dict(metadata or {}), ensure_ascii=False, default=str)

    query = """
        INSERT INTO activity_events (
            user_id, source, action, detail, session_id, attachment_id, metadata
        )
        VALUES ($1, $2, $3, $4, $5::uuid, $6, $7::jsonb)
    """
    values = (
        int(tg_id),
        safe_source,
        clean_action,
        clean_detail,
        session_id,
        attachment_id,
        payload,
    )
    try:
        if conn is not None:
            await conn.execute(query, *values)
            return
        if db.pool is None:
            return
        async with db.pool.acquire() as acquired:
            await acquired.execute(query, *values)
    except Exception as exc:
        logger.warning(
            "activity_db_write_failed tg_id=%s action=%s error=%s",
            tg_id,
            clean_action,
            type(exc).__name__,
        )
