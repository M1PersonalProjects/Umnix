from __future__ import annotations

import base64
from pathlib import Path
from typing import Awaitable, Callable, Optional

import fitz
from openai import AsyncOpenAI

from backend.web.schemas import OpenAIPageResponse
from backend.digitization_books.pdf_to_images import PdfPageRenderer
from backend.digitization_books.prompts import DIGITIZATION_BOOKS_RULES
from config import settings
from database import db

ProgressCallback = Callable[[str, int, int], Awaitable[None]]
BOOK_FILES_ROOT = Path(__file__).resolve().parents[1] / "files" / "books"


def get_digitization_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=None,
        max_retries=settings.openai_max_retries,
    )


async def _noop_progress(_: str, __: int, ___: int) -> None:
    return None


def _clean_text(value: object) -> str:
    text = str(value or "").replace("\x00", "")
    return text.strip()


def _page_image_path(book_id: int, page_number: int) -> Path:
    directory = BOOK_FILES_ROOT / str(book_id) / "pages"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{page_number}.png"


async def _digitize_page(
    client: AsyncOpenAI,
    *,
    page_number: int,
    extracted_text: str,
    image_bytes: bytes,
) -> OpenAIPageResponse:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    response = await client.beta.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": DIGITIZATION_BOOKS_RULES},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Physical PDF page number: {page_number}.\n"
                            f"Embedded/OCR text:\n{extracted_text}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{encoded}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        response_format=OpenAIPageResponse,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError(f"ИИ не вернул данные для страницы {page_number}")
    return parsed


async def digitize_pdf_path(
    book_id: int,
    pdf_path: Path,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    reset_pages: bool = True,
    client: Optional[AsyncOpenAI] = None,
) -> dict:
    path = Path(pdf_path)
    if not path.exists() or path.stat().st_size <= 0:
        raise ValueError("PDF отсутствует или пуст")
    if path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("PDF должен быть не больше 100 МБ")

    document = fitz.open(str(path))
    try:
        total_pages = len(document)
    finally:
        document.close()
    if total_pages <= 0:
        raise ValueError("PDF не содержит страниц")

    callback = progress_callback or _noop_progress
    ai_client = client or get_digitization_client()
    renderer = PdfPageRenderer(path)
    processed = 0

    await callback("preparing", 0, total_pages)
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            if reset_pages:
                await conn.execute("DELETE FROM page WHERE book_id = $1", book_id)

        for page_number, embedded_text, image_bytes in renderer.iter_pages():
            await callback("recognition", processed, total_pages)
            parsed = await _digitize_page(
                ai_client,
                page_number=page_number,
                extracted_text=embedded_text,
                image_bytes=image_bytes,
            )

            image_path = _page_image_path(book_id, page_number)
            image_path.write_bytes(image_bytes)
            image_url = f"/api/v1/books/{book_id}/pages/{page_number}/image"

            await conn.execute(
                """
                INSERT INTO page (
                    book_id,
                    page_title,
                    page_number,
                    page_paragraph,
                    page_html,
                    page_image,
                    page_text,
                    page_markdown
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (book_id, page_number) DO UPDATE SET
                    page_title = EXCLUDED.page_title,
                    page_paragraph = EXCLUDED.page_paragraph,
                    page_html = EXCLUDED.page_html,
                    page_image = EXCLUDED.page_image,
                    page_text = EXCLUDED.page_text,
                    page_markdown = EXCLUDED.page_markdown
                """,
                book_id,
                _clean_text(parsed.page_title)[:256] or f"Страница {page_number}",
                page_number,
                _clean_text(parsed.page_paragraph)[:100],
                _clean_text(parsed.html_content),
                image_url,
                _clean_text(parsed.raw_text),
                _clean_text(parsed.markdown_content),
            )
            processed += 1
            await callback("saving", processed, total_pages)

    await callback("completed", processed, total_pages)
    return {
        "status": "success",
        "processed_pages": processed,
        "total_pages": total_pages,
    }


async def digitize_pdf_bytes(
    book_id: int,
    pdf_bytes: bytes,
    *,
    client: Optional[AsyncOpenAI] = None,
) -> dict:
    if not pdf_bytes:
        raise ValueError("PDF пуст")
    if len(pdf_bytes) > 100 * 1024 * 1024:
        raise ValueError("PDF должен быть не больше 100 МБ")

    temp_dir = BOOK_FILES_ROOT / ".tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"book-{book_id}.pdf"
    temp_path.write_bytes(pdf_bytes)
    try:
        return await digitize_pdf_path(
            book_id,
            temp_path,
            reset_pages=True,
            client=client,
        )
    finally:
        temp_path.unlink(missing_ok=True)
