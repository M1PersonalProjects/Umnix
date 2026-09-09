from __future__ import annotations

import hashlib
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from backend.auth.security import require_roles
from backend.digitization_books.archive_extractor import (
    MAX_PDF_BYTES,
    extract_pdf_members,
)
from backend.digitization_books.filename_parser import BookMetadata, parse_textbook_filename
from backend.digitization_books.gpt_vision_client import BOOK_FILES_ROOT
from backend.digitization_books.queue import ensure_queue_storage
from backend.web.activity import record_activity
from database import db

router = APIRouter(
    prefix="/api/v1/admin/digitization",
    tags=["Textbook digitization"],
)

MAX_ARCHIVE_BYTES = 500 * 1024 * 1024
MAX_FILES_PER_BATCH = 20
CHUNK_SIZE = 1024 * 1024


class DigitizationMetadataUpdate(BaseModel):
    book_class: int = Field(..., ge=1, le=11)
    book_program: str = Field(..., min_length=1, max_length=200)
    book_author: str = Field(default="", max_length=300)
    book_title: str = Field(..., min_length=1, max_length=500)


def _safe_name(name: str) -> str:
    clean = Path(str(name or "").replace("\\", "/")).name.strip()
    clean = re.sub(r"[\x00-\x1f]", "", clean)
    return clean or "textbook.pdf"


def _normalized_title(name: str) -> str:
    value = Path(str(name or "")).stem.strip().casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", value)


async def _write_upload(upload: UploadFile, destination: Path, limit: int) -> int:
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as target:
        while True:
            chunk = await upload.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Файл превышает допустимый размер",
                )
            target.write(chunk)
    if total <= 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Получен пустой файл")
    return total


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_or_none(filename: str) -> tuple[Optional[BookMetadata], Optional[str]]:
    try:
        return parse_textbook_filename(filename), None
    except ValueError as exc:
        return None, str(exc)


async def _insert_job(
    conn,
    *,
    batch_id: uuid.UUID,
    owner_id: int,
    original_name: str,
    stored_path: Path,
    size_bytes: int,
) -> dict:
    checksum = _sha256(stored_path)
    duplicate = await conn.fetchrow(
        """
        SELECT job_id, batch_id, status, book_id
        FROM textbook_digitization_jobs
        WHERE checksum_sha256 = $1
          AND status IN ('matching', 'pending', 'processing', 'completed')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        checksum,
    )
    if duplicate:
        stored_path.unlink(missing_ok=True)
        return {
            "duplicate": True,
            "job_id": duplicate["job_id"],
            "batch_id": duplicate["batch_id"],
            "status": duplicate["status"],
            "book_id": duplicate["book_id"],
            "original_name": original_name,
        }

    metadata, parse_error = _metadata_or_none(original_name)
    values = metadata.to_dict() if metadata else {}
    row = await conn.fetchrow(
        """
        INSERT INTO textbook_digitization_jobs (
            batch_id,
            requested_by,
            original_name,
            stored_path,
            size_bytes,
            checksum_sha256,
            proposed_book_class,
            proposed_book_program,
            proposed_book_author,
            proposed_book_title,
            status,
            stage,
            match_type,
            error_text
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            'matching', $11, $12, $13
        )
        RETURNING *
        """,
        batch_id,
        owner_id,
        original_name,
        str(stored_path),
        size_bytes,
        checksum,
        values.get("book_class"),
        values.get("book_program"),
        values.get("book_author"),
        values.get("book_title"),
        "metadata_ready" if metadata else "metadata_needs_review",
        "filename" if metadata else None,
        parse_error,
    )
    return dict(row)


async def _pdf_jobs(
    uploads: List[UploadFile],
    *,
    batch_id: uuid.UUID,
    owner_id: int,
) -> list[dict]:
    storage = ensure_queue_storage()
    jobs: list[dict] = []
    async with db.pool.acquire() as conn:
        for upload in uploads:
            name = _safe_name(upload.filename or "")
            if not name.lower().endswith(".pdf"):
                raise HTTPException(status_code=422, detail=f"{name}: нужен PDF")
            destination = storage / f"{uuid.uuid4().hex}.pdf"
            size = await _write_upload(upload, destination, MAX_PDF_BYTES)
            jobs.append(
                await _insert_job(
                    conn,
                    batch_id=batch_id,
                    owner_id=owner_id,
                    original_name=name,
                    stored_path=destination,
                    size_bytes=size,
                )
            )
    return jobs


async def _zip_jobs(
    upload: UploadFile,
    *,
    batch_id: uuid.UUID,
    owner_id: int,
) -> list[dict]:
    storage = ensure_queue_storage()
    archive_path = storage / f"archive-{uuid.uuid4().hex}.zip"
    await _write_upload(upload, archive_path, MAX_ARCHIVE_BYTES)
    try:
        if not zipfile.is_zipfile(archive_path):
            raise HTTPException(status_code=422, detail="Некорректный ZIP-архив")
        extract_dir = storage / f"extract-{uuid.uuid4().hex}"
        try:
            extracted = list(extract_pdf_members(archive_path, extract_dir))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        jobs: list[dict] = []
        async with db.pool.acquire() as conn:
            for item in extracted:
                destination = storage / f"{uuid.uuid4().hex}.pdf"
                item.path.replace(destination)
                jobs.append(
                    await _insert_job(
                        conn,
                        batch_id=batch_id,
                        owner_id=owner_id,
                        original_name=item.original_name,
                        stored_path=destination,
                        size_bytes=item.size_bytes,
                    )
                )
        shutil.rmtree(extract_dir, ignore_errors=True)
        return jobs
    finally:
        archive_path.unlink(missing_ok=True)


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_digitization_batch(
    files: List[UploadFile] = File(...),
    user=Depends(require_roles("admin")),
):
    if not files:
        raise HTTPException(status_code=422, detail="Выберите PDF или ZIP")
    if len(files) > MAX_FILES_PER_BATCH:
        raise HTTPException(
            status_code=413,
            detail=f"За раз можно загрузить не более {MAX_FILES_PER_BATCH} файлов",
        )

    names = [_safe_name(item.filename or "") for item in files]
    zip_files = [item for item, name in zip(files, names) if name.lower().endswith(".zip")]
    pdf_files = [item for item, name in zip(files, names) if name.lower().endswith(".pdf")]
    if zip_files and (len(zip_files) != 1 or len(files) != 1):
        raise HTTPException(status_code=422, detail="ZIP загружается отдельно от PDF")
    if not zip_files and len(pdf_files) != len(files):
        raise HTTPException(status_code=422, detail="Поддерживаются только PDF и ZIP")

    batch_id = uuid.uuid4()
    if zip_files:
        jobs = await _zip_jobs(
            zip_files[0],
            batch_id=batch_id,
            owner_id=int(user["tg_id"]),
        )
    else:
        jobs = await _pdf_jobs(
            pdf_files,
            batch_id=batch_id,
            owner_id=int(user["tg_id"]),
        )

    await record_activity(
        int(user["tg_id"]),
        "digitization_upload",
        f"Пакет {batch_id}: {len(jobs)} PDF",
        metadata={"batch_id": str(batch_id), "count": len(jobs)},
    )
    return {"batch_id": str(batch_id), "status": "matching", "jobs": jobs}


@router.get("/jobs")
async def list_digitization_jobs(
    limit: int = 200,
    user=Depends(require_roles("admin")),
):
    del user
    limit = min(max(limit, 1), 500)
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                j.*,
                b.book_title,
                b.book_program,
                b.book_class,
                b.book_author
            FROM textbook_digitization_jobs j
            LEFT JOIN book b ON b.book_id = j.book_id
            ORDER BY j.created_at DESC, j.job_id DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(row) for row in rows]


@router.patch("/jobs/{job_id}/metadata")
async def update_digitization_metadata(
    job_id: int,
    payload: DigitizationMetadataUpdate,
    user=Depends(require_roles("admin")),
):
    del user
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE textbook_digitization_jobs
            SET proposed_book_class = $1,
                proposed_book_program = $2,
                proposed_book_author = $3,
                proposed_book_title = $4,
                stage = 'metadata_reviewed',
                match_type = 'manual',
                error_text = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $5 AND status = 'matching'
            RETURNING *
            """,
            payload.book_class,
            payload.book_program.strip(),
            payload.book_author.strip(),
            payload.book_title.strip(),
            job_id,
        )
    if not row:
        raise HTTPException(status_code=409, detail="Метаданные этой задачи уже нельзя менять")
    return dict(row)


@router.get("/empty-books")
async def list_empty_digitization_books(user=Depends(require_roles("admin"))):
    del user
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT b.book_id, b.book_title, b.book_program, b.book_class, b.book_author
            FROM book b
            WHERE NOT EXISTS (SELECT 1 FROM page p WHERE p.book_id = b.book_id)
            ORDER BY b.book_class, b.book_program, b.book_title
            """
        )
    return [dict(row) for row in rows]


@router.post("/jobs/{job_id}/assign/{book_id}")
async def assign_existing_book(
    job_id: int,
    book_id: int,
    user=Depends(require_roles("admin")),
):
    del user
    async with db.pool.acquire() as conn:
        book = await conn.fetchrow(
            """
            SELECT book_id, book_class, book_program, book_author, book_title
            FROM book
            WHERE book_id = $1
            """,
            book_id,
        )
        if not book:
            raise HTTPException(status_code=404, detail="Учебник не найден")
        row = await conn.fetchrow(
            """
            UPDATE textbook_digitization_jobs
            SET proposed_book_class = $1,
                proposed_book_program = $2,
                proposed_book_author = $3,
                proposed_book_title = $4,
                stage = 'metadata_reviewed',
                match_type = 'manual',
                error_text = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $5 AND status = 'matching'
            RETURNING *
            """,
            book["book_class"],
            book["book_program"],
            book["book_author"] or "",
            book["book_title"],
            job_id,
        )
    if not row:
        raise HTTPException(status_code=409, detail="Задачу уже нельзя сопоставить")
    return dict(row)


def _validated_job_metadata(row) -> tuple[int, str, str, str]:
    book_class = row["proposed_book_class"]
    program = str(row["proposed_book_program"] or "").strip()
    author = str(row["proposed_book_author"] or "").strip()
    title = str(row["proposed_book_title"] or "").strip()
    if not isinstance(book_class, int) or not 1 <= book_class <= 11:
        raise ValueError(f"{row['original_name']}: проверьте класс")
    if not program or not title:
        raise ValueError(f"{row['original_name']}: проверьте предмет и название")
    return book_class, program, author, title


def _book_storage_path(book_id: int, original_name: str) -> Path:
    directory = BOOK_FILES_ROOT / str(book_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / _safe_name(original_name)


@router.post("/batches/{batch_id}/confirm")
async def confirm_digitization_batch(
    batch_id: uuid.UUID,
    user=Depends(require_roles("admin")),
):
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT *
                FROM textbook_digitization_jobs
                WHERE batch_id = $1
                ORDER BY job_id
                FOR UPDATE
                """,
                batch_id,
            )
            if not rows:
                raise HTTPException(status_code=404, detail="Пакет не найден")
            if all(row["status"] != "matching" for row in rows):
                return {
                    "batch_id": str(batch_id),
                    "status": "already_started",
                    "jobs_count": len(rows),
                }

            prepared: list[tuple[object, tuple[int, str, str, str]]] = []
            try:
                for row in rows:
                    if row["status"] != "matching":
                        raise ValueError("В пакете есть задача с несовместимым статусом")
                    prepared.append((row, _validated_job_metadata(row)))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            for row, metadata in prepared:
                book_class, program, author, title = metadata
                book = await conn.fetchrow(
                    """
                    INSERT INTO book (
                        book_title,
                        book_program,
                        book_class,
                        book_author
                    )
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (book_title, book_program, book_class)
                    DO UPDATE SET book_author = EXCLUDED.book_author
                    RETURNING book_id
                    """,
                    title,
                    program,
                    book_class,
                    author or None,
                )
                book_id = int(book["book_id"])
                stored_pdf = _book_storage_path(book_id, row["original_name"])
                shutil.copy2(Path(row["stored_path"]), stored_pdf)
                await conn.execute(
                    """
                    UPDATE book
                    SET source_pdf_name = $1,
                        source_pdf_path = $2
                    WHERE book_id = $3
                    """,
                    row["original_name"],
                    str(stored_pdf),
                    book_id,
                )
                await conn.execute(
                    """
                    UPDATE textbook_digitization_jobs
                    SET book_id = $1,
                        status = 'pending',
                        stage = 'queued',
                        match_type = COALESCE(match_type, 'filename'),
                        matched_at = CURRENT_TIMESTAMP,
                        error_text = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = $2
                    """,
                    book_id,
                    row["job_id"],
                )

    await record_activity(
        int(user["tg_id"]),
        "digitization_confirmed",
        f"Пакет {batch_id}: {len(rows)} PDF",
        metadata={"batch_id": str(batch_id), "count": len(rows)},
    )
    return {"batch_id": str(batch_id), "status": "queued", "jobs_count": len(rows)}


@router.post("/jobs/{job_id}/retry")
async def retry_digitization_job(
    job_id: int,
    user=Depends(require_roles("admin")),
):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE textbook_digitization_jobs
            SET status = 'pending',
                stage = 'queued_retry',
                error_text = NULL,
                started_at = NULL,
                finished_at = NULL,
                processed_pages = 0,
                total_pages = 0,
                retry_count = retry_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $1
              AND status = 'failed'
              AND book_id IS NOT NULL
            RETURNING job_id, batch_id, book_id, status, retry_count, original_name
            """,
            job_id,
        )
    if not row:
        raise HTTPException(status_code=409, detail="Повторить эту задачу сейчас нельзя")
    await record_activity(
        int(user["tg_id"]),
        "digitization_retry",
        str(row["original_name"]),
        metadata={"job_id": job_id},
    )
    return dict(row)
