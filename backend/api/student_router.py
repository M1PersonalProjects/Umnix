from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.auth.security import require_roles
from backend.web.activity import record_activity
from backend.web.attachment_storage import save_upload
from backend.web.ai_tutor import clean_ai_text
from database import db

router = APIRouter(prefix="/api/v1/student", tags=["Student API"])

SENSITIVE_TASK_KEYS = {
    "reference_answer",
    "correct_answer",
    "answer_key",
    "answerKey",
    "solution",
    "solutions",
    "teacher_answer",
    "ai_instructions",
}


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value or {}


def _student_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _student_safe(item)
            for key, item in value.items()
            if key not in SENSITIVE_TASK_KEYS
        }
    if isinstance(value, list):
        return [_student_safe(item) for item in value]
    return value


def _attachment_payload(row: Any) -> Dict[str, Any]:
    attachment_id = int(row["attachment_id"])
    return {
        "attachment_id": attachment_id,
        "original_name": row["original_name"],
        "mime_type": row["mime_type"],
        "extension": row["extension"],
        "size_bytes": row["size_bytes"],
        "download_url": f"/api/v1/attachments/{attachment_id}/download",
        "preview_url": f"/api/v1/attachments/{attachment_id}/preview",
    }


@router.get("/dashboard")
async def student_dashboard(user=Depends(require_roles("student"))):
    """Возвращает профиль и активные задания Учителя без приватных ответов."""
    async with db.pool.acquire() as conn:
        profile = await conn.fetchrow(
            """
            SELECT tg_id, username, role, parent_id
            FROM users
            WHERE tg_id = $1
            """,
            user["tg_id"],
        )
        tasks = await conn.fetch(
            """
            SELECT
                t.task_id,
                t.parent_id,
                t.assignment_source,
                p.mentor_kind,
                t.title,
                t.parent_comment,
                t.subject,
                t.topic,
                t.topic_context,
                t.questions_json,
                t.student_answers_json,
                t.score,
                t.status,
                t.created_at,
                t.sent_at
            FROM tasks_history t
            LEFT JOIN users p ON p.tg_id = t.parent_id
            WHERE t.student_id = $1
              AND t.assignment_source = 'teacher'
              AND t.status IN ('created', 'in_progress', 'pending_review')
            ORDER BY t.created_at ASC
            """,
            user["tg_id"],
        )
        task_ids = [int(row["task_id"]) for row in tasks]
        attachment_rows = []
        if task_ids:
            attachment_rows = await conn.fetch(
                """
                SELECT
                    ta.task_id,
                    ta.attachment_id,
                    a.original_name,
                    a.mime_type,
                    a.extension,
                    a.size_bytes
                FROM task_attachments ta
                JOIN attachments a ON a.attachment_id = ta.attachment_id
                WHERE ta.task_id = ANY($1::bigint[])
                  AND ta.visible_to_student = TRUE
                ORDER BY ta.task_id, ta.sort_order
                """,
                task_ids,
            )

    attachments_by_task: Dict[int, List[Dict[str, Any]]] = {}
    for row in attachment_rows:
        task_id = int(row["task_id"])
        attachments_by_task.setdefault(task_id, []).append(_attachment_payload(row))

    task_items = []
    for raw in tasks:
        item = dict(raw)
        item["topic_context"] = _json_value(item["topic_context"])
        item["questions_json"] = _student_safe(_json_value(item["questions_json"]))
        item["student_answers_json"] = _json_value(item["student_answers_json"])
        item["attachments"] = attachments_by_task.get(int(item["task_id"]), [])
        task_items.append(item)

    return {"profile": dict(profile), "tasks": task_items}


@router.post("/tasks/{task_id}/submit")
async def submit_student_task(
    task_id: int,
    student_answer: str = Form(..., min_length=1, max_length=4000),
    attachments: List[UploadFile] = File(default=[]),
    user=Depends(require_roles("student")),
):
    """Сохраняет ответ Ученика и вложения для ручной проверки Учителем."""
    if len(attachments) > 10:
        raise HTTPException(status_code=422, detail="Можно прикрепить не более 10 файлов")

    async with db.pool.acquire() as conn:
        task = await conn.fetchrow(
            """
            SELECT task_id
            FROM tasks_history
            WHERE task_id = $1
              AND student_id = $2
              AND assignment_source = 'teacher'
              AND status IN ('created', 'in_progress')
            """,
            task_id,
            user["tg_id"],
        )
    if not task:
        raise HTTPException(status_code=404, detail="Активное задание Учителя не найдено")

    stored = []
    for upload in attachments:
        if upload and upload.filename:
            stored.append(await save_upload(upload=upload, owner_id=int(user["tg_id"])))

    answer_text = clean_ai_text(student_answer)
    answer_data = {
        "provided_answer": answer_text,
        "review_status": "pending_review",
        "attachment_ids": [item.attachment_id for item in stored],
    }
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            attempt_number = await conn.fetchval(
                """
                SELECT COALESCE(MAX(attempt_number), 0) + 1
                FROM task_submissions
                WHERE task_id = $1 AND student_id = $2
                """,
                task_id,
                user["tg_id"],
            )
            submission_id = await conn.fetchval(
                """
                INSERT INTO task_submissions (
                    task_id,
                    student_id,
                    answer_text,
                    attempt_number,
                    status
                )
                VALUES ($1, $2, $3, $4, 'pending_review')
                RETURNING submission_id
                """,
                task_id,
                user["tg_id"],
                answer_text,
                int(attempt_number or 1),
            )
            for sort_order, item in enumerate(stored):
                await conn.execute(
                    """
                    INSERT INTO task_submission_attachments (
                        submission_id,
                        attachment_id,
                        sort_order
                    )
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                    """,
                    submission_id,
                    item.attachment_id,
                    sort_order,
                )
            updated = await conn.fetchval(
                """
                UPDATE tasks_history
                SET student_answers_json = $1::jsonb,
                    status = 'pending_review'::task_status,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = $2
                  AND student_id = $3
                  AND assignment_source = 'teacher'
                  AND status IN ('created', 'in_progress')
                RETURNING task_id
                """,
                json.dumps(answer_data, ensure_ascii=False),
                task_id,
                user["tg_id"],
            )
            if not updated:
                raise HTTPException(status_code=409, detail="Задание уже отправлено на проверку")

    await record_activity(
        int(user["tg_id"]),
        "task_submitted",
        f"Задание {task_id}",
        metadata={"task_id": task_id, "attachments": len(stored)},
    )
    return {
        "success": True,
        "status": "pending_review",
        "assignment_source": "teacher",
        "attachment_count": len(stored),
        "message": "Ответ отправлен Учителю и ожидает ручной проверки.",
    }
