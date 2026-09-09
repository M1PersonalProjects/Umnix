from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from backend.auth.security import get_current_user
from backend.digitization_books.gpt_vision_client import BOOK_FILES_ROOT
from backend.web.activity import record_activity
from database import db

router = APIRouter(prefix="/api/v1/books", tags=["Books v1"])


@router.get("")
async def list_books(
    book_class: Optional[int] = None,
    book_program: Optional[str] = None,
    user=Depends(get_current_user),
):
    del user
    params = []
    query = """
        SELECT
            b.book_id,
            b.book_title,
            b.book_program,
            b.book_class,
            b.book_author,
            b.source_pdf_name,
            COUNT(p.page_id)::integer AS pages_count
        FROM book b
        LEFT JOIN page p ON p.book_id = b.book_id
        WHERE TRUE
    """
    if book_class is not None:
        params.append(book_class)
        query += f" AND b.book_class = ${len(params)}"
    if book_program:
        params.append(book_program)
        query += f" AND b.book_program = ${len(params)}"
    query += """
        GROUP BY b.book_id
        ORDER BY b.book_class, b.book_program, b.book_title
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


@router.get("/{book_id}/pages")
async def list_book_pages(
    book_id: int,
    user=Depends(get_current_user),
):
    del user
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                page_id,
                page_number,
                page_title,
                page_paragraph,
                page_html,
                page_image,
                page_text,
                page_markdown
            FROM page
            WHERE book_id = $1
            ORDER BY page_number
            """,
            book_id,
        )
    return [dict(row) for row in rows]


@router.get("/{book_id}/download")
async def download_book_pdf(
    book_id: int,
    user=Depends(get_current_user),
):
    async with db.pool.acquire() as conn:
        book = await conn.fetchrow(
            """
            SELECT book_title, source_pdf_name, source_pdf_path
            FROM book
            WHERE book_id = $1
            """,
            book_id,
        )
    if not book:
        raise HTTPException(status_code=404, detail="Учебник не найден")
    source_path = str(book["source_pdf_path"] or "").strip()
    if not source_path:
        raise HTTPException(status_code=404, detail="Исходный PDF учебника не сохранён")
    path = Path(source_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Исходный PDF отсутствует в хранилище",
        )
    filename = book["source_pdf_name"] or f"{book['book_title']}.pdf"
    await record_activity(
        int(user["tg_id"]),
        "book_download",
        str(filename),
        metadata={"book_id": book_id},
    )
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=str(filename),
    )


@router.get("/{book_id}/pages/{page_number}/image")
async def book_page_image(
    book_id: int,
    page_number: int,
    user=Depends(get_current_user),
):
    del user
    path = BOOK_FILES_ROOT / str(book_id) / "pages" / f"{page_number}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Изображение страницы не найдено")
    return FileResponse(path=str(path), media_type="image/png")
