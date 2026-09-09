from __future__ import annotations

import json
import uuid
from urllib.parse import quote
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.auth.security import get_current_user
from backend.web.activity import record_activity
from database import db
from backend.web.interactive_apps import contains_embedded_solution_data, serialize_app
from backend.web.ai_tutor import generate_response
from backend.web.assignment_source import TEACHER, normalize_assignment_source


router = APIRouter(prefix="/api/v1/interactive", tags=["Interactive assignments"])


class AssignmentRequest(BaseModel):
    student_ids: List[int] = Field(..., min_length=1, max_length=100)
    title: str = Field(default="", max_length=255)
    comment: str = Field(default="", max_length=4000)


class ResultRequest(BaseModel):
    score: float = 0
    max_score: float = 0
    completed: bool = False
    answers: dict[str, Any] = Field(default_factory=dict)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail="Интерактивное задание не найдено") from exc


async def _accessible_app(conn, app_id: uuid.UUID, user: Any, version: Optional[int] = None):
    """Возвращает только выбранную и доступную пользователю версию приложения."""
    selected_version = int(version) if version not in (None, "") else None
    if selected_version is not None and selected_version < 1:
        raise HTTPException(status_code=404, detail="Версия интерактивного задания не найдена")
    row = await conn.fetchrow(
        """
        SELECT a.app_id, a.owner_id, a.session_id, a.source_message_id, a.title,
               a.app_type, a.question_count, a.original_request, a.current_version, a.created_at,
               a.updated_at, v.html_document, v.version_no, v.version_id, v.parent_version_id,
               EXISTS(
                   SELECT 1 FROM interactive_assignments ia
                   WHERE ia.app_id=a.app_id AND ia.student_id=$2
                     AND (ia.version_no=v.version_no OR (ia.version_no IS NULL AND v.version_no=a.current_version))
               ) AS assigned_to_user
        FROM interactive_apps a
        JOIN interactive_app_versions v
          ON v.app_id=a.app_id AND v.version_no=COALESCE($3::integer, a.current_version)
        WHERE a.app_id=$1
          AND (a.owner_id=$2 OR EXISTS(
              SELECT 1 FROM interactive_assignments ia
              WHERE ia.app_id=a.app_id AND ia.student_id=$2
                AND (ia.version_no=v.version_no OR (ia.version_no IS NULL AND v.version_no=a.current_version))
          ))
        """,
        app_id,
        user["tg_id"],
        selected_version,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Интерактивное задание или версия не найдены")
    if user.get("role") == "student" and contains_embedded_solution_data(row["html_document"]):
        raise HTTPException(
            status_code=409,
            detail=(
                "Это задание создано в старом небезопасном формате. "
                "Учителю нужно обновить его перед выдачей Ученику."
            ),
        )
    return row


@router.get("/students")
async def teacher_students(user=Depends(get_current_user)):
    if user["role"] not in {"parent", "admin"}:
        raise HTTPException(status_code=403, detail="Список Учеников доступен только Учителю")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tg_id, username
            FROM users
            WHERE parent_id=$1 AND role='student'
            ORDER BY username NULLS LAST, tg_id
            """,
            user["tg_id"],
        )
    return [dict(row) for row in rows]


@router.get("/{app_id}")
async def get_interactive(app_id: str, version: Optional[int] = None, user=Depends(get_current_user)):
    async with db.pool.acquire() as conn:
        row = await _accessible_app(conn, _uuid(app_id), user, version)
        db_role = await conn.fetchval("SELECT role::text FROM users WHERE tg_id=$1", user["tg_id"])
    data = serialize_app(row)
    data["html_document"] = row["html_document"]
    # Права Учителя определяем только по канонической записи users.tg_id.
    # Переключение роли во frontend не должно скрывать или выдавать это право.
    is_teacher = db_role in {"parent", "admin"}
    data["can_assign"] = is_teacher and row["owner_id"] == user["tg_id"]
    data["can_view_answers"] = is_teacher
    return data


@router.get("/{app_id}/answers")
async def interactive_answers(app_id: str, version: Optional[int] = None, user=Depends(get_current_user)):
    parsed = _uuid(app_id)
    async with db.pool.acquire() as conn:
        db_user = await conn.fetchrow("SELECT role::text AS role FROM users WHERE tg_id=$1", user["tg_id"])
        if not db_user or db_user["role"] not in {"parent", "admin"}:
            raise HTTPException(status_code=403, detail="Ответы доступны только Учителю")
        row = await _accessible_app(conn, parsed, user, version)
    if not row:
        raise HTTPException(status_code=404, detail="Интерактивное задание не найдено")
    try:
        answers = await generate_response(
            user_id=user["tg_id"],
            role=user["role"],
            mode="interactive_answers",
            message="Сформируй ответы для выбранной версии интерактивного приложения.",
            title=row["title"],
            original_request=row["original_request"] or "",
            html_document=row["html_document"],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось сформировать ответы. Попробуйте позже") from exc
    return {"app_id": str(parsed), "answers_markdown": answers}


@router.get("/{app_id}/versions")
async def versions(app_id: str, user=Depends(get_current_user)):
    parsed = _uuid(app_id)
    async with db.pool.acquire() as conn:
        await _accessible_app(conn, parsed, user)
        rows = await conn.fetch(
            """
            SELECT version_no, version_id, parent_version_id, change_request, created_by, created_at
            FROM interactive_app_versions
            WHERE app_id=$1 ORDER BY version_no DESC
            """,
            parsed,
        )
    return [dict(row) for row in rows]


@router.get("/{app_id}/download")
async def download_interactive(app_id: str, version: Optional[int] = None, user=Depends(get_current_user)):
    parsed = _uuid(app_id)
    async with db.pool.acquire() as conn:
        row = await _accessible_app(conn, parsed, user, version)
    display_name = re_safe_filename(row["title"]) + ".html"
    encoded_name = quote(display_name, safe="")
    await record_activity(
        int(user["tg_id"]),
        "interactive_download",
        display_name,
        session_id=str(row["session_id"]),
        metadata={"app_id": str(parsed), "version": int(row["version_no"])},
    )
    return Response(
        content=row["html_document"],
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="interactive.html"; filename*=UTF-8\'\'{encoded_name}'
            )
        },
    )


def re_safe_filename(value: str) -> str:
    import re
    clean = re.sub(r"[^A-Za-zА-Яа-яЁё0-9._-]+", "_", str(value or "interactive"))
    return clean.strip("._")[:80] or "interactive"


@router.post("/{app_id}/assign", status_code=status.HTTP_201_CREATED)
async def assign_interactive(
    app_id: str,
    payload: AssignmentRequest,
    version: Optional[int] = None,
    user=Depends(get_current_user),
):
    if user["role"] not in {"parent", "admin"}:
        raise HTTPException(status_code=403, detail="Назначать задания может только Учитель")
    parsed = _uuid(app_id)
    created = []
    async with db.pool.acquire() as conn:
        owner = await conn.fetchrow(
            """
            SELECT a.app_id, a.title, a.current_version, v.version_no, v.version_id, v.html_document
            FROM interactive_apps a
            JOIN interactive_app_versions v
              ON v.app_id=a.app_id AND v.version_no=COALESCE($3::integer, a.current_version)
            WHERE a.app_id=$1 AND a.owner_id=$2
            """,
            parsed,
            user["tg_id"],
            int(version) if version not in (None, "") else None,
        )
        if not owner:
            raise HTTPException(status_code=404, detail="Интерактивное задание не найдено")
        if contains_embedded_solution_data(owner["html_document"]):
            raise HTTPException(
                status_code=409,
                detail=(
                    "В приложении обнаружен встроенный ключ ответов. "
                    "Обновите приложение через ИИ перед отправкой Ученику."
                ),
            )
        students = await conn.fetch(
            """
            SELECT tg_id FROM users
            WHERE tg_id = ANY($1::bigint[]) AND parent_id=$2 AND role='student'
            """,
            payload.student_ids,
            user["tg_id"],
        )
        valid_ids = {int(row["tg_id"]) for row in students}
        requested = {int(value) for value in payload.student_ids}
        if valid_ids != requested:
            raise HTTPException(status_code=404, detail="Один или несколько Учеников не привязаны к Учителю")
        async with conn.transaction():
            for student_id in payload.student_ids:
                assignment_batch = uuid.uuid4()
                topic_context = {
                    "source": "interactive_app",
                    "interactive_app_id": str(parsed),
                    "interactive_version": int(owner["version_no"]),
                }
                assignment_title = (payload.title or owner["title"] or "Интерактивное задание").strip()[:255]
                parent_comment = (payload.comment or "").strip()
                questions_json = {
                    "title": assignment_title,
                    "question_text": "Откройте интерактивное задание и выполните его на странице Umnix.",
                    "reference_answer": "Результат проверяется самим интерактивным заданием.",
                    "interactive_app_id": str(parsed),
                    "interactive_version": int(owner["version_no"]),
                }
                task_id = await conn.fetchval(
                    """
                    INSERT INTO tasks_history (
                        student_id, parent_id, assignment_source, assignment_batch_id, title, parent_comment,
                        subject, topic, topic_context, questions_json,
                        score, status, sent_at, updated_at
                    ) VALUES (
                        $1,$2,'teacher',$3,$4,$5,'Интерактивное задание',$4,$6::jsonb,$7::jsonb,
                        0,'created'::task_status,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
                    ) RETURNING task_id
                    """,
                    student_id,
                    user["tg_id"],
                    assignment_batch,
                    assignment_title,
                    parent_comment,
                    json.dumps(topic_context, ensure_ascii=False),
                    json.dumps(questions_json, ensure_ascii=False),
                )
                assignment_id = await conn.fetchval(
                    """
                    INSERT INTO interactive_assignments (app_id, teacher_id, student_id, task_id, version_no)
                    VALUES ($1,$2,$3,$4,$5)
                    ON CONFLICT (app_id, student_id) DO UPDATE
                    SET teacher_id=EXCLUDED.teacher_id, task_id=EXCLUDED.task_id,
                        version_no=EXCLUDED.version_no, assigned_at=CURRENT_TIMESTAMP
                    RETURNING assignment_id
                    """,
                    parsed,
                    user["tg_id"],
                    student_id,
                    task_id,
                    int(owner["version_no"]),
                )
                created.append({"student_id": student_id, "task_id": task_id, "assignment_id": assignment_id})
    await record_activity(
        int(user["tg_id"]),
        "interactive_assigned",
        f"app_id={parsed} students={len(created)}",
        metadata={"app_id": str(parsed), "students": len(created)},
    )
    return {"status": "assigned", "app_id": str(parsed), "assignments": created}


@router.post("/{app_id}/result")
async def save_result(
    app_id: str,
    payload: ResultRequest,
    user=Depends(get_current_user),
):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Результат сохраняется только для Ученика")
    parsed = _uuid(app_id)
    async with db.pool.acquire() as conn:
        assignment = await conn.fetchrow(
            """
            SELECT ia.assignment_id, ia.task_id, COALESCE(ia.version_no, a.current_version) AS version_no,
                   a.title, a.original_request, v.html_document,
                   th.assignment_source, th.parent_id, th.subject, th.topic
            FROM interactive_assignments ia
            JOIN interactive_apps a ON a.app_id=ia.app_id
            JOIN interactive_app_versions v
              ON v.app_id=a.app_id AND v.version_no=COALESCE(ia.version_no, a.current_version)
            LEFT JOIN tasks_history th ON th.task_id=ia.task_id
            WHERE ia.app_id=$1 AND ia.student_id=$2
            """,
            parsed,
            user["tg_id"],
        )
        if not assignment:
            raise HTTPException(status_code=404, detail="Это интерактивное задание не назначено Ученику")
        assignment_source = normalize_assignment_source(
            assignment.get("assignment_source"), assignment.get("parent_id")
        )
        try:
            grade = await generate_response(
                user_id=user["tg_id"],
                role=user["role"],
                mode="interactive_grade",
                message="Проверь ответы Ученика в интерактивном приложении.",
                title=assignment["title"],
                original_request=assignment["original_request"] or "",
                html_document=assignment["html_document"],
                answers=payload.answers,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Не удалось проверить интерактивное задание") from exc
        maximum = max(float(grade.max_score or 0), 0.0)
        score = min(max(float(grade.score or 0), 0.0), maximum) if maximum > 0 else 0.0
        percent = min(100, round((score / maximum) * 100)) if maximum > 0 else 0
        progress = {
            "score": score,
            "max_score": maximum,
            "percent": percent,
            "completed": bool(grade.completed),
            "answers": payload.answers,
            "feedback": grade.feedback,
        }
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO interactive_results (
                    app_id, version_no, student_id, assignment_id,
                    score, max_score, progress, completed
                ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8)
                """,
                parsed,
                assignment["version_no"],
                user["tg_id"],
                assignment["assignment_id"],
                score,
                maximum,
                json.dumps(progress, ensure_ascii=False),
                bool(grade.completed),
            )
            if assignment["task_id"]:
                attempt = await conn.fetchval(
                    """
                    SELECT COALESCE(MAX(attempt_number),0)+1
                    FROM task_submissions WHERE task_id=$1 AND student_id=$2
                    """,
                    assignment["task_id"],
                    user["tg_id"],
                )
                await conn.execute(
                    """
                    INSERT INTO task_submissions (
                        task_id, student_id, answer_text, attempt_number,
                        ai_feedback, score, status, reviewed_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,CURRENT_TIMESTAMP)
                    """,
                    assignment["task_id"],
                    user["tg_id"],
                    json.dumps(payload.answers, ensure_ascii=False),
                    attempt,
                    grade.feedback or "Результат интерактивного задания сохранён.",
                    percent,
                    "completed" if grade.completed else "needs_revision",
                )
                completed_status = "evaluated" if assignment_source == TEACHER else "completed"
                final_status = completed_status if grade.completed else "in_progress"
                await conn.execute(
                    """
                    UPDATE tasks_history
                    SET student_answers_json=$1::jsonb, score=$2,
                        status=$3::task_status,
                        completed_at=CASE
                            WHEN $3 IN ('completed', 'evaluated') THEN CURRENT_TIMESTAMP
                            ELSE completed_at
                        END,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE task_id=$4 AND student_id=$5
                    """,
                    json.dumps(progress, ensure_ascii=False),
                    percent,
                    final_status,
                    assignment["task_id"],
                    user["tg_id"],
                )
    await record_activity(
        int(user["tg_id"]),
        "interactive_result",
        f"app_id={parsed} score={score}/{maximum}",
        metadata={"app_id": str(parsed), "percent": percent},
    )
    return {
        "status": "saved",
        "score": score,
        "max_score": maximum,
        "percent": percent,
        "completed": bool(grade.completed),
        "feedback": grade.feedback,
    }
