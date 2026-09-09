import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


STOP_WORDS = {
    "как", "что", "это", "для", "или", "мне", "мой", "моя", "при", "про",
    "the", "from", "with", "this", "explain", "book", "класс", "страница",
    "учебник", "задача", "упражнение", "пожалуйста",
}
TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})

MAX_CONTEXT_CHARS = 16000
MAX_SELECTED_PAGES = 6
CHUNK_CHARS = 3200


@dataclass
class ResolvedContext:
    book_id: int
    book_title: str
    book_author: str
    book_program: str
    book_class: int
    page_id: Optional[int] = None
    page_number: Optional[int] = None
    page_paragraph: Optional[str] = None
    page_title: Optional[str] = None
    content: str = ""
    source: str = "natural_language"
    context_mode: str = "whole_book"
    used_pages: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def label(self) -> str:
        page = f", стр. {self.page_number}" if self.page_number else ""
        return f"{self.book_title}{page}"


def _tokens(value: str) -> List[str]:
    values = re.findall(r"[a-zа-яё0-9]+", (value or "").lower())
    return [item for item in values if len(item) >= 3 and item not in STOP_WORDS]


def _transliterate(value: str) -> str:
    return (value or "").lower().translate(TRANSLIT)


def _extract_number(pattern: str, prompt: str) -> Optional[int]:
    match = re.search(pattern, prompt or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_hints(prompt: str) -> Dict[str, Any]:
    return {
        "book_class": _extract_number(
            r"(?:^|\s)(\d{1,2})(?:\s*[-–]?(?:й|ый|ой|го|ого|th|st|nd|rd))?\s*[-–]?\s*(?:класс(?:а|е)?|grade)", prompt
        ),
        "page_number": _extract_number(
            r"(?:стр(?:аниц[аеуы])?\.?|page)\s*№?\s*(\d{1,4})", prompt
        ),
        "paragraph": _extract_number(r"(?:§|параграф)\s*№?\s*(\d{1,4})", prompt),
        "exercise": _extract_number(
            r"(?:упражнени[ея]|задач[аи]|номер|exercise|problem)\s*№?\s*(\d{1,4})",
            prompt,
        ),
        "tokens": _tokens(prompt),
    }


def _book_score(book: Any, hints: Dict[str, Any], manual: Dict[str, Any]) -> int:
    score = 0
    if manual.get("book_id") == book["book_id"]:
        score += 100
    expected_class = manual.get("book_class") or hints.get("book_class")
    if expected_class:
        score += 24 if int(book["book_class"]) == int(expected_class) else -30
    expected_program = (manual.get("book_program") or "").lower()
    if expected_program and expected_program in (book["book_program"] or "").lower():
        score += 35
    searchable = " ".join([
        book["book_title"] or "", book["book_author"] or "", book["book_program"] or ""
    ]).lower()
    searchable_latin = _transliterate(searchable)
    author = (book["book_author"] or "").lower()
    for token in hints.get("tokens", []):
        if token in searchable or token in searchable_latin:
            score += 6
        if token in author or token in _transliterate(author):
            score += 6
    return score


def _row_content(row: Any) -> str:
    return (row["page_markdown"] or row["page_text"] or "").strip()


def _page_meta(row: Any) -> Dict[str, Any]:
    return {
        "page_id": row["page_id"],
        "page_number": row["page_number"],
        "page_title": row["page_title"],
        "page_paragraph": row["page_paragraph"],
    }


def _chunk_text(text: str, chunk_chars: int = CHUNK_CHARS) -> List[str]:
    compact = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not compact:
        return []
    if len(compact) <= chunk_chars:
        return [compact]
    chunks: List[str] = []
    start = 0
    while start < len(compact):
        end = min(len(compact), start + chunk_chars)
        if end < len(compact):
            split = compact.rfind("\n", start, end)
            if split <= start + chunk_chars // 2:
                split = compact.rfind(". ", start, end)
            if split > start:
                end = split + 1
        chunk = compact[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


def _relevance_score(row: Any, chunk: str, tokens: List[str]) -> int:
    if not tokens:
        return 0
    title = f"{row['page_title'] or ''} {row['page_paragraph'] or ''}".lower().replace("ё", "е")
    body = chunk.lower().replace("ё", "е")
    score = 0
    for token in tokens:
        normalized = token.replace("ё", "е")
        if normalized in title:
            score += 12
        occurrences = body.count(normalized)
        if occurrences:
            score += min(occurrences, 5) * 3
    return score


async def _fetch_exact(conn, book_id: int, page_id: Optional[int], page_number: Optional[int]):
    if not page_id and not page_number:
        return await conn.fetchrow(
            """
            SELECT b.book_id, b.book_title, b.book_author, b.book_program, b.book_class,
                   NULL::INTEGER AS page_id, NULL::INTEGER AS page_number,
                   NULL::VARCHAR AS page_paragraph, NULL::VARCHAR AS page_title,
                   NULL::TEXT AS page_markdown, NULL::TEXT AS page_text
            FROM book b WHERE b.book_id = $1
            """,
            book_id,
        )
    query = """
        SELECT b.book_id, b.book_title, b.book_author, b.book_program, b.book_class,
               p.page_id, p.page_number, p.page_paragraph, p.page_title,
               p.page_markdown, p.page_text
        FROM book b LEFT JOIN page p ON p.book_id = b.book_id
        WHERE b.book_id = $1
    """
    params: List[Any] = [book_id]
    if page_id:
        params.append(page_id)
        query += f" AND p.page_id = ${len(params)}"
    elif page_number:
        params.append(page_number)
        query += f" AND p.page_number = ${len(params)}"
    query += " ORDER BY p.page_number NULLS LAST LIMIT 1"
    return await conn.fetchrow(query, *params)


def _to_context(row: Any, source: str) -> Optional[ResolvedContext]:
    if not row:
        return None
    is_page = row["page_id"] is not None
    return ResolvedContext(
        book_id=row["book_id"],
        book_title=row["book_title"],
        book_author=row["book_author"],
        book_program=row["book_program"],
        book_class=row["book_class"],
        page_id=row["page_id"],
        page_number=row["page_number"],
        page_paragraph=row["page_paragraph"],
        page_title=row["page_title"],
        content=_row_content(row)[:MAX_CONTEXT_CHARS],
        source=source,
        context_mode="single_page" if is_page else "whole_book",
        used_pages=[_page_meta(row)] if is_page else [],
    )


async def resolve_book_context(
    conn,
    book_id: int,
    query: str,
    page_id: Optional[int] = None,
    source: str = "manual",
    max_chars: int = MAX_CONTEXT_CHARS,
    max_pages: int = MAX_SELECTED_PAGES,
) -> Optional[ResolvedContext]:
    """Resolve either one selected page or a bounded, relevant whole-book context."""
    if page_id is not None:
        row = await _fetch_exact(conn, int(book_id), int(page_id), None)
        return _to_context(row, source)

    book = await _fetch_exact(conn, int(book_id), None, None)
    if not book:
        return None

    rows = await conn.fetch(
        """
        SELECT b.book_id, b.book_title, b.book_author, b.book_program, b.book_class,
               p.page_id, p.page_number, p.page_paragraph, p.page_title,
               p.page_markdown, p.page_text
        FROM page p
        JOIN book b ON b.book_id = p.book_id
        WHERE p.book_id = $1
          AND COALESCE(NULLIF(BTRIM(p.page_markdown), ''), NULLIF(BTRIM(p.page_text), '')) IS NOT NULL
        ORDER BY p.page_number NULLS LAST, p.page_id
        """,
        int(book_id),
    )

    if not rows:
        return ResolvedContext(
            book_id=book["book_id"],
            book_title=book["book_title"],
            book_author=book["book_author"],
            book_program=book["book_program"],
            book_class=book["book_class"],
            source=source,
            context_mode="whole_book",
        )

    tokens = _tokens(query)
    ranked: List[tuple[int, int, int, Any, str]] = []
    for row in rows:
        for chunk_index, chunk in enumerate(_chunk_text(_row_content(row))):
            score = _relevance_score(row, chunk, tokens)
            page_number = row["page_number"] if row["page_number"] is not None else 10**9
            ranked.append((score, -page_number, -chunk_index, row, chunk))

    if tokens:
        ranked = [item for item in ranked if item[0] > 0]
        if not ranked:
            return ResolvedContext(
                book_id=book["book_id"],
                book_title=book["book_title"],
                book_author=book["book_author"],
                book_program=book["book_program"],
                book_class=book["book_class"],
                source=source,
                context_mode="whole_book",
            )
        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    else:
        ranked.sort(key=lambda item: (item[1], item[2]), reverse=True)

    blocks: List[str] = []
    used_pages: List[Dict[str, Any]] = []
    seen_pages = set()
    total = 0
    for _, _, _, row, chunk in ranked:
        page_key = row["page_id"]
        if page_key not in seen_pages and len(seen_pages) >= max_pages:
            continue
        header = (
            f"Страница {row['page_number'] or '—'}"
            f" | {row['page_title'] or row['page_paragraph'] or 'без заголовка'}"
        )
        block = f"[{header}]\n{chunk}".strip()
        remaining = max_chars - total
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining].rstrip()
        if not block:
            break
        blocks.append(block)
        total += len(block) + 2
        if page_key not in seen_pages:
            seen_pages.add(page_key)
            used_pages.append(_page_meta(row))
        if total >= max_chars:
            break

    return ResolvedContext(
        book_id=book["book_id"],
        book_title=book["book_title"],
        book_author=book["book_author"],
        book_program=book["book_program"],
        book_class=book["book_class"],
        content="\n\n".join(blocks)[:max_chars],
        source=source,
        context_mode="whole_book",
        used_pages=used_pages,
    )


async def resolve_context(
    conn,
    prompt: str,
    manual: Optional[Dict[str, Any]] = None,
    allow_global_search: bool = False,
) -> Optional[ResolvedContext]:
    """Resolve an optional textbook context from filters and natural language."""
    manual = {key: value for key, value in (manual or {}).items() if value not in (None, "")}
    hints = extract_hints(prompt)
    explicit_book_id = manual.get("book_id")
    explicit_page_id = manual.get("page_id")
    page_number = manual.get("page_number") or hints.get("page_number")

    if explicit_book_id and explicit_page_id:
        return await resolve_book_context(
            conn, int(explicit_book_id), prompt, page_id=int(explicit_page_id), source="manual"
        )
    if explicit_book_id and page_number:
        row = await _fetch_exact(conn, int(explicit_book_id), None, int(page_number))
        return _to_context(row, "manual")

    params: List[Any] = []
    query = "SELECT book_id, book_title, book_author, book_program, book_class FROM book WHERE TRUE"
    if explicit_book_id:
        params.append(int(explicit_book_id))
        query += f" AND book_id = ${len(params)}"
    selected_class = manual.get("book_class") or hints.get("book_class")
    if selected_class:
        params.append(int(selected_class))
        query += f" AND book_class = ${len(params)}"
    if manual.get("book_program"):
        params.append(manual["book_program"])
        query += f" AND book_program ILIKE ${len(params)}"
    query += " ORDER BY created_at DESC LIMIT 200"
    books = await conn.fetch(query, *params)
    scored = sorted(
        ((_book_score(book, hints, manual), book) for book in books),
        key=lambda item: item[0], reverse=True,
    )
    selected_book = scored[0][1] if scored and (scored[0][0] > 0 or manual or selected_class) else None
    if selected_book:
        selected_searchable = " ".join([
            selected_book["book_title"] or "", selected_book["book_author"] or "",
            selected_book["book_program"] or "",
        ]).lower()
        selected_latin = _transliterate(selected_searchable)
        has_named_book_hint = any(
            token in selected_searchable or token in selected_latin
            for token in hints.get("tokens", [])
        )
        natural_source = (
            "natural_language_explicit"
            if page_number or hints.get("paragraph") or has_named_book_hint
            else "natural_language"
        )
        source = "manual" if manual else natural_source
        query_text = prompt
        if hints.get("paragraph"):
            query_text += f" параграф {hints['paragraph']}"
        if hints.get("exercise"):
            query_text += f" упражнение {hints['exercise']}"
        if manual.get("page_paragraph"):
            query_text += f" {manual['page_paragraph']}"
        return await resolve_book_context(
            conn,
            int(selected_book["book_id"]),
            query_text,
            source=source,
        )

    if not allow_global_search:
        return None

    terms = hints.get("tokens", [])[:4]
    if not terms:
        return None
    page_params = []
    conditions = []
    for term in terms:
        page_params.append(f"%{term}%")
        position = len(page_params)
        conditions.append(
            f"(p.page_paragraph ILIKE ${position} OR p.page_title ILIKE ${position} "
            f"OR p.page_text ILIKE ${position})"
        )
    page = await conn.fetchrow(
        """
        SELECT b.book_id, b.book_title, b.book_author, b.book_program, b.book_class,
               p.page_id, p.page_number, p.page_paragraph, p.page_title,
               p.page_markdown, p.page_text
        FROM page p JOIN book b ON b.book_id = p.book_id
        WHERE """ + " OR ".join(conditions) + " ORDER BY p.page_id DESC LIMIT 1",
        *page_params,
    )
    return _to_context(page, "natural_language")


async def load_locked_context(conn, session: Any) -> Optional[ResolvedContext]:
    if not session or session["context_locked"] is not True or not session["book_id"]:
        return None
    if session["page_id"]:
        row = await _fetch_exact(conn, session["book_id"], session["page_id"], None)
        return _to_context(row, "locked")
    row = await _fetch_exact(conn, session["book_id"], None, None)
    return _to_context(row, "locked")
