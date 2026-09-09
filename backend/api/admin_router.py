from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from backend.auth.security import require_roles
from backend.digitization_books.gpt_vision_client import BOOK_FILES_ROOT
from backend.web.activity import record_activity
from backend.web.schemas import BookPayload, PagePayload
from backend.web.ai_tutor import clean_ai_text
from database import db

router = APIRouter(prefix="/api/v1/admin", tags=["Admin API"])


@router.get("/overview")
async def admin_overview(user=Depends(require_roles("admin"))):
    """Возвращает основные счётчики панели Администратора."""
    del user
    async with db.pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        books = await conn.fetchval("SELECT COUNT(*) FROM book")
        pages = await conn.fetchval("SELECT COUNT(*) FROM page")
        tasks = await conn.fetchval("SELECT COUNT(*) FROM tasks_history")
    return {
        "users": int(users or 0),
        "books": int(books or 0),
        "pages": int(pages or 0),
        "tasks": int(tasks or 0),
    }


@router.get("/books")
async def admin_books(user=Depends(require_roles("admin"))):
    """Возвращает учебники с количеством оцифрованных страниц."""
    del user
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
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
            GROUP BY b.book_id
            ORDER BY b.book_class, b.book_program, b.book_title
            """
        )
    return [dict(row) for row in rows]


@router.post("/books", status_code=status.HTTP_201_CREATED)
async def admin_create_book(
    payload: BookPayload,
    user=Depends(require_roles("admin")),
):
    """Создаёт карточку учебника без запуска оцифровки."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO book (
                book_title,
                book_program,
                book_class,
                book_author
            )
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            payload.book_title.strip(),
            payload.book_program.strip(),
            payload.book_class,
            payload.book_author.strip() or None,
        )
    await record_activity(
        int(user["tg_id"]),
        "book_created",
        payload.book_title.strip(),
        metadata={"book_id": int(row["book_id"])},
    )
    return dict(row)


@router.put("/books/{book_id}")
async def admin_update_book(
    book_id: int,
    payload: BookPayload,
    user=Depends(require_roles("admin")),
):
    """Обновляет метаданные учебника."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE book
            SET book_title = $1,
                book_program = $2,
                book_class = $3,
                book_author = $4
            WHERE book_id = $5
            RETURNING *
            """,
            payload.book_title.strip(),
            payload.book_program.strip(),
            payload.book_class,
            payload.book_author.strip() or None,
            book_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Учебник не найден")
    await record_activity(
        int(user["tg_id"]),
        "book_updated",
        payload.book_title.strip(),
        metadata={"book_id": book_id},
    )
    return dict(row)


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_book(
    book_id: int,
    user=Depends(require_roles("admin")),
):
    """Удаляет учебник, страницы и его файлы из локального хранилища."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            DELETE FROM book
            WHERE book_id = $1
            RETURNING book_title
            """,
            book_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Учебник не найден")
    shutil.rmtree(BOOK_FILES_ROOT / str(book_id), ignore_errors=True)
    await record_activity(
        int(user["tg_id"]),
        "book_deleted",
        str(row["book_title"]),
        metadata={"book_id": book_id},
    )


@router.get("/books/{book_id}/pages")
async def admin_pages(
    book_id: int,
    user=Depends(require_roles("admin")),
):
    """Возвращает все страницы учебника для редактора."""
    del user
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                page_id,
                book_id,
                page_title,
                page_number,
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


@router.put("/pages/{page_id}")
async def admin_update_page(
    page_id: int,
    payload: PagePayload,
    user=Depends(require_roles("admin")),
):
    """Обновляет данные оцифрованной страницы."""
    markdown = clean_ai_text(payload.page_markdown)
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE page
            SET page_title = $1,
                page_number = $2,
                page_paragraph = $3,
                page_text = $4,
                page_html = $5,
                page_markdown = $6
            WHERE page_id = $7
            RETURNING page_id, book_id, page_number
            """,
            payload.page_title,
            payload.page_number,
            payload.page_paragraph,
            payload.page_text,
            payload.page_html,
            markdown,
            page_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Страница не найдена")
    await record_activity(
        int(user["tg_id"]),
        "book_page_updated",
        f"Учебник {row['book_id']}, страница {row['page_number']}",
        metadata={"page_id": page_id, "book_id": int(row["book_id"])},
    )
    return {"status": "success", "page_id": page_id}


@router.get("/users")
async def admin_users(
    role: Optional[str] = None,
    search: Optional[str] = None,
    user=Depends(require_roles("admin")),
):
    """Ищет пользователей по роли, username или Telegram ID."""
    del user
    params: List[Any] = []
    query = """
        SELECT tg_id, username, role, mentor_kind, parent_id, created_at
        FROM users
        WHERE TRUE
    """
    if role:
        params.append(role)
        query += f" AND role = ${len(params)}::user_role"
    if search:
        params.append(f"%{search.strip()}%")
        index = len(params)
        query += f" AND (username ILIKE ${index} OR tg_id::text ILIKE ${index})"
    query += " ORDER BY created_at DESC LIMIT 500"
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


@router.get("/family-tree")
async def admin_family_tree(user=Depends(require_roles("admin"))):
    """Возвращает связи Учителей/Родителей и Учеников."""
    del user
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.tg_id AS parent_id,
                p.username AS parent_username,
                p.mentor_kind,
                c.tg_id AS student_id,
                c.username AS student_username
            FROM users p
            LEFT JOIN users c
              ON c.parent_id = p.tg_id
             AND c.role = 'student'
            WHERE p.role IN ('parent', 'admin')
            ORDER BY p.username NULLS LAST, c.username NULLS LAST
            """
        )
    families: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        parent_id = int(row["parent_id"])
        family = families.setdefault(
            parent_id,
            {
                "parent_id": parent_id,
                "parent_username": row["parent_username"],
                "mentor_kind": row["mentor_kind"],
                "children": [],
            },
        )
        if row["student_id"]:
            family["children"].append(
                {
                    "tg_id": int(row["student_id"]),
                    "username": row["student_username"],
                }
            )
    return list(families.values())


@router.get("/activity")
async def admin_activity(
    tg_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = 200,
    user=Depends(require_roles("admin")),
):
    """Возвращает события, историю чатов, файлы, сессии и задания."""
    del user
    safe_limit = min(max(int(limit), 1), 500)
    search = f"%{q.strip()}%" if q and q.strip() else None
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH activity AS (
                SELECT
                    e.activity_id::text AS id,
                    'event'::text AS type,
                    e.user_id,
                    e.action AS sender,
                    e.detail,
                    e.created_at,
                    e.session_id,
                    u.username,
                    u.role::text AS user_role,
                    u.mentor_kind,
                    cs.title AS session_title
                FROM activity_events e
                JOIN users u ON u.tg_id = e.user_id
                LEFT JOIN chat_sessions cs ON cs.session_id = e.session_id

                UNION ALL

                SELECT
                    cm.message_id::text,
                    'chat'::text,
                    cm.user_id,
                    cm.sender,
                    cm.message_text,
                    cm.created_at,
                    cm.session_id,
                    u.username,
                    u.role::text,
                    u.mentor_kind,
                    cs.title
                FROM chat_messages cm
                JOIN users u ON u.tg_id = cm.user_id
                LEFT JOIN chat_sessions cs ON cs.session_id = cm.session_id

                UNION ALL

                SELECT
                    a.attachment_id::text,
                    'file'::text,
                    a.owner_id,
                    'attachment'::text,
                    a.original_name,
                    a.created_at,
                    links.session_id,
                    u.username,
                    u.role::text,
                    u.mentor_kind,
                    links.session_title
                FROM attachments a
                JOIN users u ON u.tg_id = a.owner_id
                LEFT JOIN LATERAL (
                    SELECT cma.session_id, cs.title AS session_title
                    FROM chat_message_attachments cma
                    JOIN chat_sessions cs ON cs.session_id = cma.session_id
                    WHERE cma.attachment_id = a.attachment_id
                    ORDER BY cma.message_id DESC
                    LIMIT 1
                ) links ON TRUE

                UNION ALL

                SELECT
                    cs.session_id::text,
                    'session'::text,
                    cs.user_id,
                    cs.chat_type,
                    cs.title,
                    cs.created_at,
                    cs.session_id,
                    u.username,
                    u.role::text,
                    u.mentor_kind,
                    cs.title
                FROM chat_sessions cs
                JOIN users u ON u.tg_id = cs.user_id

                UNION ALL

                SELECT
                    th.task_id::text,
                    'task'::text,
                    th.student_id,
                    th.status::text,
                    COALESCE(NULLIF(th.title, ''), NULLIF(th.topic, ''), th.status::text),
                    th.created_at,
                    NULL::uuid,
                    u.username,
                    u.role::text,
                    u.mentor_kind,
                    NULL::text
                FROM tasks_history th
                JOIN users u ON u.tg_id = th.student_id
            )
            SELECT *
            FROM activity
            WHERE ($1::bigint IS NULL OR user_id = $1)
              AND (
                    $2::text IS NULL
                    OR user_id::text ILIKE $2
                    OR COALESCE(username, '') ILIKE $2
                    OR COALESCE(sender, '') ILIKE $2
                    OR COALESCE(detail, '') ILIKE $2
                    OR COALESCE(session_title, '') ILIKE $2
                  )
            ORDER BY created_at DESC
            LIMIT $3
            """,
            tg_id,
            search,
            safe_limit,
        )
    return [dict(row) for row in rows]
