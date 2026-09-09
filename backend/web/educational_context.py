from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from logger_config import logger
from backend.web.context_resolver import ResolvedContext, resolve_context

MAX_SUPPLEMENTAL_CHARS = 18000
MAX_WEB_CHARS = 12000
SOURCE_LIMIT = 12

_SOURCE_PRIORITY = {
    "peer_textbook": 20,
    "problem_collection": 30,
    "solution_book": 31,
    "eduai_material": 40,
}
_COLLECTION_RE = re.compile(
    r"(?:сборник|задачник|практикум|рабоч(?:ая|ей)\s+тетрад|workbook|problem\s*book|practice)",
    re.I,
)
_SOLUTION_RE = re.compile(r"(?:решеб|гдз|ответы|solution|answer\s*book|solutions\s*manual)", re.I)


@dataclass(frozen=True)
class EducationalSource:
    kind: str
    label: str
    content: str
    book_id: Optional[int] = None
    page_id: Optional[int] = None
    score: int = 0


@dataclass
class EducationalContextBundle:
    """One ranked context object shared by tutor, tasks, grading and interactive apps."""

    primary: Optional[ResolvedContext] = None
    attachment_text: str = ""
    sources: List[EducationalSource] = field(default_factory=list)
    web_context: str = ""

    @property
    def database_context(self) -> str:
        return render_sources(self.sources, max_chars=MAX_SUPPLEMENTAL_CHARS)

    @property
    def local_char_count(self) -> int:
        return sum(
            len(value)
            for value in (
                str(self.primary.content if self.primary else ""),
                self.attachment_text,
                self.database_context,
            )
        )

    @property
    def source_trace(self) -> List[Dict[str, Any]]:
        trace: List[Dict[str, Any]] = []
        if self.primary:
            trace.append(
                {
                    "kind": "selected_textbook",
                    "book_id": self.primary.book_id,
                    "page_id": self.primary.page_id,
                    "label": self.primary.label,
                }
            )
        if self.attachment_text:
            trace.append({"kind": "uploaded_file", "label": "active attachment"})
        trace.extend(
            {
                "kind": source.kind,
                "book_id": source.book_id,
                "page_id": source.page_id,
                "label": source.label,
            }
            for source in self.sources
        )
        if self.web_context:
            trace.append({"kind": "web", "label": "web fallback"})
        return trace


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        if hasattr(row, "get"):
            value = row.get(key, default)
        else:
            value = row[key]
        return default if value is None else value
    except (KeyError, TypeError, AttributeError):
        return default


def selected_context_from_page(row: Any, *, source: str = "selected_page") -> ResolvedContext:
    """Build a primary context from an already-fetched page without another DB round-trip."""
    return ResolvedContext(
        book_id=int(_row_value(row, "book_id", 0) or 0),
        book_title=str(_row_value(row, "book_title", "Учебный материал") or "Учебный материал"),
        book_author=str(_row_value(row, "book_author", "") or ""),
        book_program=str(_row_value(row, "book_program", "") or ""),
        book_class=int(_row_value(row, "book_class", 0) or 0),
        page_id=_row_value(row, "page_id"),
        page_number=_row_value(row, "page_number"),
        page_paragraph=_row_value(row, "page_paragraph"),
        page_title=_row_value(row, "page_title"),
        content=str(
            _row_value(row, "page_markdown", "")
            or _row_value(row, "page_text", "")
            or _row_value(row, "content", "")
            or ""
        ),
        source=source,
        context_mode="single_page",
        used_pages=[{
            "page_id": _row_value(row, "page_id"),
            "page_number": _row_value(row, "page_number"),
            "page_title": _row_value(row, "page_title"),
            "page_paragraph": _row_value(row, "page_paragraph"),
        }],
    )


def _tokens(value: str) -> List[str]:
    stop = {
        "как", "что", "это", "для", "или", "мне", "нужно", "создай", "сделай",
        "задач", "задачи", "заданий", "задание", "объясни", "тема", "учебник",
        "the", "this", "that", "with", "from", "task", "tasks", "explain",
    }
    return [
        token.replace("ё", "е")
        for token in re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", str(value or "").casefold())
        if len(token) >= 3 and token.replace("ё", "е") not in stop
    ][:14]


def _source_kind(title: str, same_subject_level: bool) -> str:
    if _SOLUTION_RE.search(title or ""):
        return "solution_book"
    if _COLLECTION_RE.search(title or ""):
        return "problem_collection"
    if same_subject_level:
        return "peer_textbook"
    return "eduai_material"


def _row_score(row: Any, tokens: List[str], primary: Optional[ResolvedContext]) -> tuple[int, str]:
    title = str(row["book_title"] or "")
    program = str(row["book_program"] or "")
    level = row["book_class"]
    searchable = " ".join(
        [title, program, str(row["page_title"] or ""), str(row["page_paragraph"] or ""), str(row["content"] or "")]
    ).casefold().replace("ё", "е")
    same_program = bool(primary and primary.book_program and program.casefold() == str(primary.book_program).casefold())
    same_level = bool(primary and primary.book_class is not None and level == primary.book_class)
    same_subject_level = same_program and same_level
    kind = _source_kind(title, same_subject_level)
    score = 0
    if same_program:
        score += 35
    if same_level:
        score += 25
    for token in tokens:
        occurrences = searchable.count(token)
        score += min(occurrences, 5) * 4
        if token in title.casefold().replace("ё", "е"):
            score += 8
        if token in str(row["page_title"] or "").casefold().replace("ё", "е"):
            score += 10
    score += max(0, 50 - _SOURCE_PRIORITY[kind])
    return score, kind


async def search_eduai_materials(
    conn,
    query: str,
    *,
    primary: Optional[ResolvedContext] = None,
    limit: int = SOURCE_LIMIT,
    max_chars: int = MAX_SUPPLEMENTAL_CHARS,
) -> List[EducationalSource]:
    """Search other umnix.ai books and rank them by the TOR source hierarchy."""
    tokens = _tokens(query)
    patterns = [f"%{token}%" for token in tokens]
    params: List[Any] = []
    where: List[str] = [
        "COALESCE(NULLIF(BTRIM(p.page_markdown), ''), NULLIF(BTRIM(p.page_text), '')) IS NOT NULL"
    ]
    if primary:
        params.append(int(primary.book_id))
        where.append(f"b.book_id <> ${len(params)}")

    relevance_clause = ""
    if patterns:
        params.append(patterns)
        pos = len(params)
        relevance_clause = f"""
          AND (
            lower(replace(COALESCE(p.page_title, ''), 'ё', 'е')) ILIKE ANY(${pos}::text[])
            OR lower(replace(COALESCE(p.page_paragraph, ''), 'ё', 'е')) ILIKE ANY(${pos}::text[])
            OR lower(replace(COALESCE(p.page_text, ''), 'ё', 'е')) ILIKE ANY(${pos}::text[])
            OR lower(replace(COALESCE(p.page_markdown, ''), 'ё', 'е')) ILIKE ANY(${pos}::text[])
            OR lower(replace(COALESCE(b.book_title, ''), 'ё', 'е')) ILIKE ANY(${pos}::text[])
            OR lower(replace(COALESCE(b.book_program, ''), 'ё', 'е')) ILIKE ANY(${pos}::text[])
          )
        """
    elif primary:
        params.extend([str(primary.book_program or ""), int(primary.book_class or 0)])
        program_pos, class_pos = len(params) - 1, len(params)
        relevance_clause = (
            f" AND (b.book_program ILIKE ${program_pos} OR b.book_class = ${class_pos})"
        )
    else:
        return []

    rows = await conn.fetch(
        f"""
        SELECT b.book_id, b.book_title, b.book_program, b.book_class, b.book_author,
               p.page_id, p.page_number, p.page_title, p.page_paragraph,
               COALESCE(NULLIF(p.page_markdown, ''), p.page_text) AS content
        FROM page p
        JOIN book b ON b.book_id = p.book_id
        WHERE {' AND '.join(where)}
        {relevance_clause}
        ORDER BY p.page_id DESC
        LIMIT 160
        """,
        *params,
    )

    ranked: List[tuple[int, int, Any, str]] = []
    for row in rows:
        score, kind = _row_score(row, tokens, primary)
        ranked.append((_SOURCE_PRIORITY[kind], -score, row, kind))
    ranked.sort(key=lambda item: (item[0], item[1]))

    result: List[EducationalSource] = []
    seen_pages = set()
    total = 0
    for _, neg_score, row, kind in ranked:
        page_key = (row["book_id"], row["page_id"])
        if page_key in seen_pages:
            continue
        content = re.sub(r"\n{3,}", "\n\n", str(row["content"] or "").strip())[:3600]
        if not content:
            continue
        label = (
            f"{row['book_title']} ({row['book_program']}, {row['book_class']} class), "
            f"page {row['page_number'] or '—'}"
        )
        source = EducationalSource(
            kind=kind,
            label=label,
            content=content,
            book_id=row["book_id"],
            page_id=row["page_id"],
            score=-neg_score,
        )
        block_size = len(content) + len(label) + 60
        if result and total + block_size > max_chars:
            break
        result.append(source)
        seen_pages.add(page_key)
        total += block_size
        if len(result) >= limit:
            break
    return result


def render_sources(sources: List[EducationalSource], *, max_chars: int = MAX_SUPPLEMENTAL_CHARS) -> str:
    labels = {
        "peer_textbook": "OTHER TEXTBOOK (same subject/level)",
        "problem_collection": "PROBLEM COLLECTION / WORKBOOK",
        "solution_book": "SOLUTION / ANSWER BOOK (examples only; do not copy sequentially)",
        "eduai_material": "OTHER UMNIX.AI MATERIAL",
    }
    blocks = [
        f"[{labels.get(source.kind, source.kind.upper())}] {source.label}\n{source.content}"
        for source in sources
    ]
    return "\n\n".join(blocks)[:max_chars]


async def build_educational_context(
    conn,
    query: str,
    *,
    selected_context: Optional[ResolvedContext] = None,
    manual: Optional[Dict[str, Any]] = None,
    attachment_text: str = "",
    allow_context_resolution: bool = True,
    allow_web: bool = False,
    web_search: Optional[Callable[[str], Awaitable[str] | str]] = None,
    force_web: bool = False,
    requested_items: int = 0,
) -> EducationalContextBundle:
    """Build source-ranked educational context for any AI feature."""
    primary = selected_context
    if primary is None and allow_context_resolution:
        primary = await resolve_context(conn, query, manual=manual, allow_global_search=False)

    try:
        sources = await search_eduai_materials(conn, query, primary=primary)
    except Exception as exc:
        logger.warning("Supplemental umnix.ai context search failed: %s", exc)
        sources = []
    bundle = EducationalContextBundle(
        primary=primary,
        attachment_text=str(attachment_text or "")[:18000],
        sources=sources,
    )

    # Web is a fallback, not the default source. The caller decides whether freshness or
    # explicit search intent makes it mandatory; otherwise a thin local context triggers it.
    evidence_blocks = (1 if bundle.primary else 0) + len(bundle.sources) + (1 if bundle.attachment_text else 0)
    estimated_local_capacity = max(1, evidence_blocks) * 3
    needs_more_examples = int(requested_items or 0) > estimated_local_capacity
    no_local_evidence = bundle.local_char_count == 0
    should_web = allow_web and (force_web or no_local_evidence or needs_more_examples)
    if should_web and web_search is not None:
        value = web_search(query)
        if inspect.isawaitable(value):
            value = await value
        bundle.web_context = str(value or "")[:MAX_WEB_CHARS]
    return bundle


async def build_context_from_metadata(
    conn,
    query: str,
    metadata: Optional[Dict[str, Any]],
    *,
    attachment_text: str = "",
) -> EducationalContextBundle:
    """Rehydrate the shared context for graders/checkers from stored task metadata."""
    meta = metadata or {}
    manual = {
        "book_id": meta.get("book_id"),
        "page_id": meta.get("page_id"),
        "book_program": meta.get("book_program") or meta.get("subject"),
        "book_class": meta.get("book_class"),
    }
    primary = None
    if any(value not in (None, "") for value in manual.values()):
        try:
            primary = await resolve_context(conn, query, manual=manual, allow_global_search=False)
        except Exception as exc:
            logger.warning("Stored educational context could not be rehydrated: %s", exc)
            primary = None
    return await build_educational_context(
        conn,
        query,
        selected_context=primary,
        attachment_text=attachment_text,
        allow_context_resolution=False,
        allow_web=False,
    )


class EducationalContextService:
    """Stable service facade used by every AI feature."""

    build = staticmethod(build_educational_context)
    build_from_metadata = staticmethod(build_context_from_metadata)
    from_page = staticmethod(selected_context_from_page)
    search_local = staticmethod(search_eduai_materials)
    render_sources = staticmethod(render_sources)
