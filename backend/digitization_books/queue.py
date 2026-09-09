from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Optional

from backend.digitization_books.gpt_vision_client import digitize_pdf_path
from backend.web.activity import record_activity
from database import db
from logger_config import logger

BASE_DIR = Path(__file__).resolve().parents[1]
QUEUE_STORAGE = BASE_DIR / "files" / ".digitization_queue"
POLL_INTERVAL_SECONDS = 2.0

_worker_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def ensure_queue_storage() -> Path:
    QUEUE_STORAGE.mkdir(parents=True, exist_ok=True)
    return QUEUE_STORAGE


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _recover_interrupted_jobs() -> None:
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE textbook_digitization_jobs
            SET status = 'pending',
                stage = 'recovered_after_restart',
                started_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'processing'
            """
        )


async def _claim_next_job() -> Optional[dict]:
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(220025)")
            row = await conn.fetchrow(
                """
                SELECT
                    job_id,
                    batch_id,
                    requested_by,
                    book_id,
                    original_name,
                    stored_path,
                    checksum_sha256,
                    retry_count
                FROM textbook_digitization_jobs
                WHERE status = 'pending'
                  AND book_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM textbook_digitization_jobs running
                      WHERE running.status = 'processing'
                  )
                ORDER BY created_at, job_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
            if not row:
                return None
            await conn.execute(
                """
                UPDATE textbook_digitization_jobs
                SET status = 'processing',
                    stage = 'starting',
                    started_at = CURRENT_TIMESTAMP,
                    finished_at = NULL,
                    error_text = NULL,
                    processed_pages = 0,
                    total_pages = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = $1
                """,
                row["job_id"],
            )
            return dict(row)


async def _update_progress(
    job_id: int,
    stage: str,
    processed: int,
    total: int,
) -> None:
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE textbook_digitization_jobs
            SET stage = $1,
                processed_pages = $2,
                total_pages = $3,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $4
            """,
            stage,
            processed,
            total,
            job_id,
        )


async def _process_job(job: dict) -> None:
    job_id = int(job["job_id"])
    owner_id = int(job["requested_by"])
    path = Path(job["stored_path"])

    try:
        async def progress(stage: str, processed: int, total: int) -> None:
            await _update_progress(job_id, stage, processed, total)

        result = await digitize_pdf_path(
            int(job["book_id"]),
            path,
            progress_callback=progress,
            reset_pages=True,
        )

        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE textbook_digitization_jobs
                SET status = 'completed',
                    stage = 'completed',
                    processed_pages = $1,
                    total_pages = $2,
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = $3
                """,
                result["processed_pages"],
                result["total_pages"],
                job_id,
            )
        await record_activity(
            owner_id,
            "book_digitization_completed",
            str(job["original_name"]),
            source="system",
            metadata={"job_id": job_id, "book_id": int(job["book_id"])},
        )
        path.unlink(missing_ok=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning(
            "digitization_failed job_id=%s error=%s",
            job_id,
            type(exc).__name__,
        )
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE textbook_digitization_jobs
                SET status = 'failed',
                    stage = 'failed',
                    error_text = $1,
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = $2
                """,
                str(exc)[:4000],
                job_id,
            )
        await record_activity(
            owner_id,
            "book_digitization_failed",
            str(job["original_name"]),
            source="system",
            metadata={"job_id": job_id, "error": type(exc).__name__},
        )


async def _worker_loop() -> None:
    await _recover_interrupted_jobs()
    logger.info("digitization_worker_started")
    while _stop_event is not None and not _stop_event.is_set():
        try:
            job = await _claim_next_job()
            if job:
                await _process_job(job)
                continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("digitization_worker_error error=%s", type(exc).__name__)

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("digitization_worker_stopped")


async def start_digitization_worker() -> None:
    global _worker_task, _stop_event
    if _worker_task and not _worker_task.done():
        return
    ensure_queue_storage()
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        _worker_loop(),
        name="textbook-digitization-worker",
    )


async def stop_digitization_worker() -> None:
    global _worker_task, _stop_event
    if not _worker_task:
        return
    if _stop_event:
        _stop_event.set()
    try:
        await asyncio.wait_for(_worker_task, timeout=10)
    except asyncio.TimeoutError:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    finally:
        _worker_task = None
        _stop_event = None
