from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, Optional, Sequence

from pydantic import BaseModel, Field

from config import settings
from database import db
from backend.web.ai import AIUpstreamError, create_chat_completion, openai_client, parse_chat_completion
from backend.web.context_resolver import ResolvedContext
from backend.web.prompts import (
    AI_TUTOR_SYSTEM_PROMPT,
    INTERACTIVE_ANSWER_KEY_RULES,
    INTERACTIVE_TASK_RULES,
)


class InteractiveGeneration(BaseModel):
    """Результат одного AI-вызова генерации приложения."""

    title: str = Field(..., min_length=1, max_length=180)
    app_type: str = Field(default="interactive_app", max_length=40)
    question_count: int = Field(default=0, ge=0, le=500)
    html_document: str = Field(..., min_length=40, max_length=1_500_000)


class InteractiveAppTemporaryError(RuntimeError):
    """Временная ошибка внешнего AI-сервиса."""


class InteractiveAnswerKey(BaseModel):
    answers_markdown: str = Field(..., min_length=1, max_length=160_000)


class InteractiveGrade(BaseModel):
    score: float = Field(default=0, ge=0)
    max_score: float = Field(default=0, ge=0)
    completed: bool = True
    feedback: str = Field(default="", max_length=4000)


_CSP = (
    "default-src 'none'; "
    "style-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; "
    "script-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com "
    "https://cdn.tailwindcss.com; "
    "img-src data: blob:; media-src data: blob:; "
    "font-src data: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
)

_BRIDGE = r"""
<script data-umnix-bridge="1">
(() => {
  const send = payload => window.parent.postMessage({type: 'eduai-interactive-result', payload: payload || {}}, '*');
  window.EduAIInteractive = Object.freeze({ complete: send });
})();
</script>
""".strip()
_SOLUTION_RE = re.compile(
    r"(?:\b(?:const|let|var)\s+(?:correctAnswers?|answerKey|solutionKey)\b|"
    r"\b(?:correctAnswer|correct_answer|answerKey|solutionKey)\s*[:=])",
    re.IGNORECASE,
)

def contains_embedded_solution_data(html: str) -> bool:
    """Ищет очевидный ключ ответов в learner-side коде."""
    return bool(_SOLUTION_RE.search(str(html or "")))


_SAFE_CDN_HOSTS = (
    "https://cdn.jsdelivr.net",
    "https://cdnjs.cloudflare.com",
    "https://unpkg.com",
    "https://cdn.tailwindcss.com",
)


def _is_safe_cdn_url(value: str) -> bool:
    lowered = str(value or "").strip().casefold()
    return any(lowered == host or lowered.startswith(host + "/") for host in _SAFE_CDN_HOSTS)


def _strip_external_attributes(html: str) -> str:
    pattern = re.compile(
        r"\s(?P<name>href|src|action)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
        re.IGNORECASE | re.DOTALL,
    )

    def replace(match: re.Match[str]) -> str:
        name = match.group("name").lower()
        value = match.group("value").strip()
        lowered = value.casefold()
        if name == "action":
            return ""
        if name == "href" and value.startswith("#"):
            return f' href="{value}"'
        if name == "src" and (lowered.startswith("data:") or lowered.startswith("blob:")):
            return f' src="{value}"'
        if _is_safe_cdn_url(value):
            return f' {name}="{value}"'
        return ""

    return pattern.sub(replace, html)


def sanitize_interactive_html(value: str) -> str:
    """Изолирует сгенерированный HTML от host DOM, сети и внешних ресурсов."""
    html = str(value or "").strip()
    if not html:
        raise ValueError("ИИ вернул пустое интерактивное приложение")
    if len(html) > 1_500_000:
        raise ValueError("Интерактивное приложение получилось слишком большим")

    html = re.sub(
        r"<\s*(?:iframe|object|embed|base)\b[^>]*>.*?<\s*/\s*(?:iframe|object|embed|base)\s*>",
        "",
        html,
        flags=re.I | re.S,
    )
    html = re.sub(r"<\s*(?:iframe|object|embed|base)\b[^>]*/?\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"<\s*meta\b[^>]*http-equiv\s*=\s*['\"]?refresh['\"]?[^>]*>", "", html, flags=re.I | re.S)
    html = re.sub(r"@import\s+[^;]+;", "", html, flags=re.I)
    html = re.sub(r"url\(\s*['\"]?(?:https?:)?//[^)]+\)", "none", html, flags=re.I)
    html = _strip_external_attributes(html)

    dangerous = (
        r"window\.parent", r"window\.top", r"window\.opener", r"document\.cookie",
        r"localStorage", r"sessionStorage", r"indexedDB", r"XMLHttpRequest",
        r"WebSocket", r"EventSource", r"navigator\.sendBeacon", r"window\.open\s*\(",
        r"fetch\s*\(", r"(?:window\.)?location(?:\.href|\.assign|\.replace)?",
    )
    for token in dangerous:
        html = re.sub(token, "/* blocked by Umnix */", html, flags=re.I)

    html = re.sub(r"\b(?:javascript|mailto|tel|file):[^\s'\"<>]+", "#", html, flags=re.I)

    csp = f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">'
    if re.search(r"<head\b[^>]*>", html, flags=re.I):
        html = re.sub(r"(<head\b[^>]*>)", r"\1\n" + csp, html, count=1, flags=re.I)
    else:
        html = re.sub(r"(<html\b[^>]*>)", r"\1\n<head>" + csp + "</head>", html, count=1, flags=re.I)

    if re.search(r"</body\s*>", html, flags=re.I):
        html = re.sub(r"</body\s*>", _BRIDGE + "\n</body>", html, count=1, flags=re.I)
    else:
        raise ValueError("ИИ вернул HTML без закрывающего body")
    return html


def _book_context_text(context: Optional[ResolvedContext]) -> str:
    if not context:
        return ""
    return (
        f"Book: {context.book_title}\n"
        f"Author: {context.book_author or 'not specified'}\n"
        f"Subject: {context.book_program or 'not specified'}\n"
        f"Class: {context.book_class or 'not specified'}\n"
        f"Page: {context.page_number or 'whole selected book'}\n"
        f"Paragraph: {context.page_paragraph or 'not selected'}\n"
        f"Content:\n{str(context.content or '')[:80_000]}"
    )


def _extract_complete_html(content: str) -> str:
    value = str(content or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:html)?\s*", "", value, count=1, flags=re.I)
        value = re.sub(r"\s*```$", "", value, count=1)
    start = re.search(r"(?is)(<!doctype\s+html|<html\b)", value)
    if not start:
        raise ValueError("ИИ не вернул полный HTML документ")
    value = value[start.start():].strip()
    if not re.search(r"</html\s*>\s*$", value, re.I):
        raise ValueError("ИИ вернул незавершённый HTML документ")
    if not re.match(r"(?is)^<!doctype\s+html", value):
        value = "<!doctype html>\n" + value
    return value


def _validate_generated_html(html: str) -> None:
    issues: list[str] = []
    if not re.search(r"<html\b", html, re.I) or not re.search(r"</html\s*>", html, re.I):
        issues.append("incomplete HTML document")
    if not re.search(r"<body\b", html, re.I):
        issues.append("missing body")
    if "name=\"viewport\"" not in html and "name='viewport'" not in html:
        issues.append("missing responsive viewport")
    if contains_embedded_solution_data(html):
        issues.append("learner-side answer key detected")
    if "blocked by Umnix" in html:
        issues.append("generated code attempted a blocked host/network API")
    if issues:
        raise ValueError("Interactive app failed validation: " + "; ".join(issues))


def _question_count(html: str) -> int:
    ids = {
        match.group(1)
        for match in re.finditer(
            r"(?:id|name|data-question-id)\s*=\s*['\"]q(\d+)['\"]",
            html,
            re.IGNORECASE,
        )
    }
    return min(len(ids), 500)


def _title_from_html(html: str, fallback: str) -> str:
    for pattern in (r"(?is)<title[^>]*>(.*?)</title>", r"(?is)<h1[^>]*>(.*?)</h1>"):
        match = re.search(pattern, html)
        if match:
            title = re.sub(r"<[^>]+>", " ", match.group(1))
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                return title[:180]
    return (str(fallback or "Интерактивное приложение").strip() or "Интерактивное приложение")[:180]


async def _generate(
    request: str,
    *,
    context: Optional[ResolvedContext],
    attachment_text: str = "",
    image_urls: Sequence[str] = (),
    previous_html: str = "",
) -> InteractiveGeneration:
    """Генерирует HTML только из запроса, BookMode и явно переданных вложений."""
    user_content: list[dict[str, Any]] = [{"type": "text", "text": str(request or "").strip()}]
    book_context = _book_context_text(context)
    if book_context:
        user_content.append({"type": "text", "text": f"BOOK MODE DATA:\n{book_context}"})
    if attachment_text.strip():
        user_content.append({
            "type": "text",
            "text": f"ATTACHED FILE DATA:\n{attachment_text[:100_000]}",
        })
    for image_url in image_urls:
        if image_url:
            user_content.append({"type": "image_url", "image_url": {"url": image_url}})
    if previous_html:
        user_content.append({
            "type": "text",
            "text": f"CURRENT HTML VERSION:\n{previous_html[:1_200_000]}",
        })

    try:
        response = await create_chat_completion(
            openai_client,
            temperature=0.3,
            max_tokens=12000,
            messages=[
                {"role": "system", "content": INTERACTIVE_TASK_RULES},
                {"role": "user", "content": user_content},
            ],
        )
    except AIUpstreamError as exc:
        raise InteractiveAppTemporaryError(
            "Сервис генерации интерактивных приложений временно недоступен."
        ) from exc

    raw_html = _extract_complete_html(response.choices[0].message.content)
    safe_html = sanitize_interactive_html(raw_html)
    _validate_generated_html(safe_html)
    return InteractiveGeneration(
        title=_title_from_html(safe_html, request),
        question_count=_question_count(safe_html),
        html_document=safe_html,
    )


async def generate_teacher_answer_key(*, title: str, request: str, html_document: str) -> str:
    """Формирует приватный ключ ответов только после серверной проверки роли."""
    response = await parse_chat_completion(
        openai_client,
        temperature=0.1,
        messages=[
            {"role": "system", "content": INTERACTIVE_ANSWER_KEY_RULES},
            {
                "role": "user",
                "content": (
                    f"TITLE: {title}\nORIGINAL REQUEST: {request}\n\n"
                    f"LEARNER HTML:\n{html_document[:900_000]}"
                ),
            },
        ],
        response_format=InteractiveAnswerKey,
    )
    parsed = response.choices[0].message.parsed
    if not parsed:
        raise RuntimeError("Не удалось сформировать ответы")
    return parsed.answers_markdown.strip()


async def grade_interactive_submission(
    *, title: str, request: str, html_document: str, answers: Dict[str, Any]
) -> InteractiveGrade:
    """Проверяет ответы на Backend без передачи правильных ответов в браузер."""
    response = await parse_chat_completion(
        openai_client,
        temperature=0.05,
        messages=[
            {"role": "system", "content": AI_TUTOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Evaluate the learner answers for this interactive educational application. "
                    "Return the requested structured score, max_score, completed flag and concise feedback.\n\n"
                    f"TITLE: {title}\nORIGINAL REQUEST: {request}\n"
                    f"LEARNER HTML:\n{html_document[:900_000]}\n\n"
                    f"LEARNER ANSWERS JSON:\n{json.dumps(answers, ensure_ascii=False)[:160_000]}"
                ),
            },
        ],
        response_format=InteractiveGrade,
    )
    parsed = response.choices[0].message.parsed
    if not parsed:
        raise RuntimeError("Не удалось проверить интерактивное задание")
    if parsed.max_score and parsed.score > parsed.max_score:
        parsed.score = parsed.max_score
    return parsed


def serialize_app(row: Any) -> Dict[str, Any]:
    """Сериализует конкретную сохранённую версию для Frontend."""
    data = dict(row)
    data["app_id"] = str(data["app_id"])
    data["session_id"] = str(data["session_id"])
    data["question_count"] = int(data.get("question_count") or 0)
    data["current_version"] = int(data.get("current_version") or 1)
    data["version_no"] = int(data.get("version_no") or data["current_version"])
    if data.get("version_id"):
        data["version_id"] = str(data["version_id"])
    if data.get("parent_version_id"):
        data["parent_version_id"] = str(data["parent_version_id"])
    version = data["version_no"]
    data["open_url"] = f"/interactive/{data['app_id']}?version={version}"
    data["download_url"] = f"/api/v1/interactive/{data['app_id']}/download?version={version}"
    return data


async def create_app(
    *,
    user_id: int,
    session_id: uuid.UUID,
    request: str,
    context: Optional[ResolvedContext],
    attachment_text: str = "",
    image_urls: Sequence[str] = (),
) -> Dict[str, Any]:
    """Сохраняет новый app и неизменяемую версию v1."""
    generated = await _generate(
        request,
        context=context,
        attachment_text=attachment_text,
        image_urls=image_urls,
    )
    app_id = uuid.uuid4()
    version_id = uuid.uuid4()
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO interactive_apps (
                    app_id, owner_id, session_id, title, app_type,
                    question_count, original_request, current_version
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,1)
                """,
                app_id, user_id, session_id, generated.title, generated.app_type,
                generated.question_count, request,
            )
            await conn.execute(
                """
                INSERT INTO interactive_app_versions (
                    app_id, version_no, version_id, parent_version_id,
                    html_document, change_request, created_by
                ) VALUES ($1,1,$2,NULL,$3,$4,$5)
                """,
                app_id, version_id, generated.html_document, request, user_id,
            )
            row = await conn.fetchrow(
                """
                SELECT a.app_id, a.owner_id, a.session_id, a.source_message_id, a.title,
                       a.app_type, a.question_count, a.current_version, a.created_at, a.updated_at,
                       v.version_no, v.version_id, v.parent_version_id
                FROM interactive_apps a
                JOIN interactive_app_versions v ON v.app_id=a.app_id AND v.version_no=1
                WHERE a.app_id=$1
                """,
                app_id,
            )
    return serialize_app(row)


async def edit_app(
    *,
    user_id: int,
    app_id: str,
    request: str,
    context: Optional[ResolvedContext],
    attachment_text: str = "",
    image_urls: Sequence[str] = (),
    base_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Создаёт новую версию из явно выбранной базовой версии."""
    try:
        parsed = uuid.UUID(str(app_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LookupError("Некорректный ID интерактивного задания") from exc
    selected = int(base_version) if base_version not in (None, "") else None
    if selected is not None and selected < 1:
        raise LookupError("Некорректная версия интерактивного задания")

    async with db.pool.acquire() as conn:
        base = await conn.fetchrow(
            """
            SELECT a.*, v.html_document, v.version_no, v.version_id
            FROM interactive_apps a
            JOIN interactive_app_versions v
              ON v.app_id=a.app_id AND v.version_no=COALESCE($3::integer, a.current_version)
            WHERE a.app_id=$1 AND a.owner_id=$2
            """,
            parsed, user_id, selected,
        )
    if not base:
        raise LookupError("Интерактивное приложение или выбранная версия не найдены")

    generated = await _generate(
        request,
        context=context,
        attachment_text=attachment_text,
        image_urls=image_urls,
        previous_html=base["html_document"],
    )
    new_version_id = uuid.uuid4()
    parent_version_id = base["version_id"]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            if not parent_version_id:
                parent_version_id = uuid.uuid4()
                await conn.execute(
                    """
                    UPDATE interactive_app_versions SET version_id=$1
                    WHERE app_id=$2 AND version_no=$3 AND version_id IS NULL
                    """,
                    parent_version_id, parsed, int(base["version_no"]),
                )
            version_no = int(
                await conn.fetchval(
                    "SELECT COALESCE(MAX(version_no),0)+1 FROM interactive_app_versions WHERE app_id=$1",
                    parsed,
                )
                or 1
            )
            await conn.execute(
                """
                INSERT INTO interactive_app_versions (
                    app_id, version_no, version_id, parent_version_id,
                    html_document, change_request, created_by
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                """,
                parsed, version_no, new_version_id, parent_version_id,
                generated.html_document, request, user_id,
            )
            await conn.execute(
                """
                UPDATE interactive_apps
                SET title=$1, app_type=$2, question_count=$3,
                    current_version=$4, updated_at=CURRENT_TIMESTAMP
                WHERE app_id=$5 AND owner_id=$6
                """,
                generated.title, generated.app_type, generated.question_count,
                version_no, parsed, user_id,
            )
            row = await conn.fetchrow(
                """
                SELECT a.app_id, a.owner_id, a.session_id, a.source_message_id, a.title,
                       a.app_type, a.question_count, a.current_version, a.created_at, a.updated_at,
                       v.version_no, v.version_id, v.parent_version_id
                FROM interactive_apps a
                JOIN interactive_app_versions v ON v.app_id=a.app_id AND v.version_no=$2
                WHERE a.app_id=$1 AND a.owner_id=$3
                """,
                parsed, version_no, user_id,
            )
    return serialize_app(row)


async def maybe_handle_chat_request(
    *,
    user_id: int,
    session_id: uuid.UUID,
    message_text: str,
    context: Optional[ResolvedContext],
    attachment_text: str = "",
    image_urls: Sequence[str] = (),
    interactive_app_id: Optional[str] = None,
    interactive_action: Optional[str] = None,
    interactive_version: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Запускает Canvas только по явному действию Frontend."""
    action = str(interactive_action or "").strip().casefold()
    if action == "create":
        return await create_app(
            user_id=user_id,
            session_id=session_id,
            request=message_text,
            context=context,
            attachment_text=attachment_text,
            image_urls=image_urls,
        )
    if action == "edit":
        if not interactive_app_id:
            raise LookupError("Для редактирования выберите конкретную версию приложения")
        return await edit_app(
            user_id=user_id,
            app_id=interactive_app_id,
            request=message_text,
            context=context,
            attachment_text=attachment_text,
            image_urls=image_urls,
            base_version=interactive_version,
        )
    return None


def card_text(app: Dict[str, Any]) -> str:
    """Формирует компактный Telegram-текст; WebApp рисует настоящую карточку."""
    count = int(app.get("question_count") or 0)
    version = int(app.get("version_no") or app.get("current_version") or 1)
    count_line = f"\n{count} вопросов" if count else ""
    base = str(settings.webapp_base_url or "").rstrip("/")
    open_line = (
        f"\n\nОткрыть: {base}/interactive/{app['app_id']}?version={version}"
        if base and not base.startswith("https://localhost")
        else "\n\nОткройте WebApp Umnix — карточка доступна в истории этого чата."
    )
    return (
        f"**Интерактивное приложение: {app['title']}**{count_line}\n"
        f"Версия v{version}."
        f"{open_line}"
    )


async def set_source_message(app_id: str, message_id: int, version_no: Optional[int] = None) -> None:
    """Связывает сообщение чата с конкретной версией приложения."""
    parsed = uuid.UUID(str(app_id))
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE interactive_apps SET source_message_id=$1 WHERE app_id=$2",
            message_id, parsed,
        )
        await conn.execute(
            """
            UPDATE interactive_app_versions v
            SET source_message_id=$1
            FROM interactive_apps a
            WHERE v.app_id=a.app_id AND a.app_id=$2
              AND v.version_no=COALESCE($3::integer, a.current_version)
            """,
            message_id,
            parsed,
            int(version_no) if version_no not in (None, "") else None,
        )
