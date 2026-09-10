from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Optional

from backend.web.task_generation import (
    GeneratedTaskSet,
    extract_requested_task_count,
    generate_exact_task_set,
    task_set_payload,
)


_GRADE_RE = re.compile(
    r"(?:^|\b)(?:класс\s*)?(\d{1,2})(?:\s*[-–]?(?:й|ый|ой|го|ого))?\s*(?:класс(?:а|е)?|кл\.?|grade)\b",
    re.IGNORECASE,
)
_GRADE_FOR_RE = re.compile(
    r"\b(?:для|уровень|уровня)\s+(\d{1,2})(?:\s*[-–]?(?:й|ый|ой|го|ого))?\s*(?:класс(?:а|е)?|кл\.?)\b",
    re.IGNORECASE,
)
_GRADE_WORD_RE = re.compile(
    r"\b(перв(?:ый|ого|ом)|втор(?:ой|ого|ом)|трет(?:ий|ьего|ьем)|четверт(?:ый|ого|ом)|"
    r"пят(?:ый|ого|ом)|шест(?:ой|ого|ом)|седьм(?:ой|ого|ом)|восьм(?:ой|ого|ом)|"
    r"девят(?:ый|ого|ом)|десят(?:ый|ого|ом)|одиннадцат(?:ый|ого|ом))\s+класс(?:а|е)?\b",
    re.IGNORECASE,
)
_PRIMARY_SCHOOL_RE = re.compile(
    r"\b(?:первоклассник(?:а|у|ом|и)?|второклассник(?:а|у|ом|и)?|третьеклассник(?:а|у|ом|и)?|"
    r"четвероклассник(?:а|у|ом|и)?)\b",
    re.IGNORECASE,
)

_SUBJECT_LABEL_RE = re.compile(
    r"(?:предмет|subject)\s*[:=\-–]\s*([^;\n,]+)",
    re.IGNORECASE,
)
_TOPIC_LABEL_RE = re.compile(
    r"(?:тема|тему|topic)\s*[:=\-–]\s*([^;\n]+)",
    re.IGNORECASE,
)
_SUBJECT_TOPIC_RE = re.compile(
    r"\bпо\s+([^,;.\n]{2,80}?)\s+(?:на\s+)?тем(?:е|у|а)\s+([^,;.\n]{2,180})",
    re.IGNORECASE,
)
_COUNT_ONLY_RE = re.compile(
    r"^\s*\d{1,3}\s+(?:вопрос(?:а|ов|ы)?|задач(?:а|и|у|е|)?|задани(?:е|я|й|ю)|"
    r"упражнени(?:е|я|й|ю)|questions?|tasks?|problems?)\s*$",
    re.IGNORECASE,
)

_TOPIC_AFTER_REQUEST_RE = re.compile(
    r"(?:квест|тест|вопрос(?:ы|ов)?|задани(?:я|й)?|упражнени(?:я|й)?|тренаж[её]р|quiz|test)"
    r".{0,80}?(?:по|про|об|о|на\s+тему)\s+([^;.\n]{2,180})",
    re.IGNORECASE,
)
_TOPIC_NATURAL_RE = re.compile(
    r"\b(?:по|про|об|о|на\s+тему|по\s+теме)\s+([^;.\n]{2,180})",
    re.IGNORECASE,
)

_REQUEST_PREFIX_RE = re.compile(
    r"^(?:пожалуйста\s+)?(?:сделай|создай|подготовь|составь|придумай|хочу|можно|давай)\s+"
    r"(?:(?:мне\s+)?(?:интересн(?:ый|ую|ое)?\s+|познавательн(?:ый|ую|ое)?\s+|учебн(?:ый|ую|ое)?\s+)?)?"
    r"(?:квест(?:-?тест)?|тест|викторин(?:у|а)|задания?|вопросы?|тренаж[её]р)?\s*",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(
    r"\b(?:пожалуйста|интересн(?:ый|ая|ое|ую)?|познавательн(?:ый|ая|ое|ую)?|"
    r"учебн(?:ый|ая|ое|ую)?|вес[её]л(?:ый|ая|ое|ую)?|сложн(?:ый|ая|ое|ую)?|"
    r"л[её]гк(?:ий|ая|ое|ую)?|повышенн(?:ой|ая|ый|ое)\s+сложности)\b",
    re.IGNORECASE,
)

_SUBJECT_HINTS = (
    (
        "Математика",
        (
            "дроб", "сложен", "вычитан", "умнож", "делен", "делён", "пример", "уравнен",
            "геометр", "фигур", "числ", "счет", "счёт", "арифмет", "процент", "координат",
            "площад", "периметр", "объем", "объём", "больше меньше", "сравнен чис",
        ),
    ),
    (
        "Русский язык",
        (
            "орфограф", "пунктуац", "части речи", "глагол", "существительн", "прилагательн",
            "предложен", "словар", "ударен", "слог", "букв", "алфавит", "корень слова",
            "приставк", "суффикс", "окончан", "местоимен", "нареч",
        ),
    ),
    (
        "Литература",
        (
            "писател", "поэт", "стих", "рассказ", "роман", "геро", "сюжет", "произведен",
            "произведён", "басн", "сказк", "пушкин", "лермонтов", "толстой", "чехов", "гогол",
            "тургенев", "некрасов", "достоевск", "булгаков", "шекспир",
        ),
    ),
    (
        "Биология",
        (
            "животн", "растен", "клетк", "орган", "экосистем", "пищевар", "дыхани", "виды",
            "организм", "анатом", "генет", "бактери", "гриб", "эволюц", "зоолог", "ботаник",
        ),
    ),
    (
        "Окружающий мир",
        (
            "природ", "погода", "времен", "город", "семья", "професс", "окружающ", "родина",
            "континент", "планета", "экология", "безопасност", "животн", "растен",
        ),
    ),
    (
        "Информатика",
        (
            "алгоритм", "программ", "код", "цикл", "услов", "переменн", "компьютер", "информат",
            "данн", "файл", "таблиц", "интернет", "логик", "блок-схем", "python", "scratch",
        ),
    ),
    (
        "Физика",
        (
            "давлен", "сила", "скорост", "масса", "энерг", "электр", "механик", "свет", "ток",
            "напряжен", "сопротивлен", "ускорен", "импульс", "плотност", "температур", "ньютон",
        ),
    ),
    (
        "Химия",
        (
            "атом", "молекул", "реакц", "веществ", "кислот", "щелоч", "элемент", "валентност",
            "оксид", "соль", "раствор", "периодическ", "химическ",
        ),
    ),
    (
        "История",
        (
            "истори", "древн", "войн", "царь", "революц", "век", "событ", "император",
            "средневек", "ссср", "русск импер", "археолог", "цивилизац",
        ),
    ),
    (
        "Обществознание",
        (
            "общество", "право", "государ", "граждан", "эконом", "семья", "закон", "конституц",
            "морал", "политик", "социал", "рынок", "налог", "правовед",
        ),
    ),
    (
        "География",
        (
            "географ", "материк", "океан", "рельеф", "климат", "страны мира", "карта", "глобус",
            "река", "море", "гора", "население", "природная зона",
        ),
    ),
    (
        "Иностранный язык",
        (
            "английск", "english", "немецк", "deutsch", "французск", "лексик", "грамматик",
            "vocabulary", "grammar", "reading", "present simple", "past simple",
        ),
    ),
)

_SUBJECT_ALIASES = {
    "математика": "Математика",
    "алгебра": "Математика",
    "геометрия": "Математика",
    "русский": "Русский язык",
    "русский язык": "Русский язык",
    "литература": "Литература",
    "биология": "Биология",
    "окружающий мир": "Окружающий мир",
    "информатика": "Информатика",
    "программирование": "Информатика",
    "физика": "Физика",
    "химия": "Химия",
    "история": "История",
    "обществознание": "Обществознание",
    "правоведение": "Обществознание",
    "география": "География",
    "английский": "Иностранный язык",
    "английский язык": "Иностранный язык",
}

_GRADE_WORDS = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
    "одиннадцат": 11,
}


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip(" \t\r\n,;.-–"))


def _fold(value: object) -> str:
    return _clean(value).casefold().replace("ё", "е")


def _segments(text: str) -> list[str]:
    return [_clean(part) for part in re.split(r"[;,\n]+", text or "") if _clean(part)]


def _extract_grade(raw: str) -> Optional[int]:
    for pattern in (_GRADE_RE, _GRADE_FOR_RE):
        match = pattern.search(raw)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 11:
                return value

    word_match = _GRADE_WORD_RE.search(raw)
    if word_match:
        folded = _fold(word_match.group(1))
        for prefix, value in _GRADE_WORDS.items():
            if folded.startswith(prefix):
                return value

    primary_match = _PRIMARY_SCHOOL_RE.search(raw)
    if primary_match:
        folded = _fold(primary_match.group(0))
        if folded.startswith("перв"):
            return 1
        if folded.startswith("втор"):
            return 2
        if folded.startswith("треть"):
            return 3
        if folded.startswith("четвер"):
            return 4
    return None


def _strip_request_noise(value: str) -> str:
    text = _clean(value)
    text = _REQUEST_PREFIX_RE.sub("", text)
    text = re.sub(
        r"\b\d{1,3}\s*(?:вопрос(?:а|ов|ы)?|задач(?:а|и)?|задани(?:е|я|й)|упражнени(?:е|я|й))\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:для|на)\s+\d{1,2}\s*(?:класс(?:а|е)?|кл\.?)\b", "", text, flags=re.IGNORECASE)
    text = _GRADE_RE.sub("", text)
    text = _GRADE_FOR_RE.sub("", text)
    text = _GRADE_WORD_RE.sub("", text)
    text = _PRIMARY_SCHOOL_RE.sub("", text)
    text = _NOISE_RE.sub("", text)
    # Grade/count removal can leave a dangling preposition (for example
    # "животные для первоклассника" -> "животные для").
    text = re.sub(r"(?:^|\s)(?:для|на|по)\s*$", "", text, flags=re.IGNORECASE)
    return _clean(text)


def infer_subject_from_text(value: str) -> str:
    folded = _fold(value)
    if not folded:
        return ""

    # Prefer an explicit subject name over broader topical hints. This keeps
    # phrases like "русский язык: животные" in Russian rather than Biology.
    for alias, canonical in _SUBJECT_ALIASES.items():
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", folded):
            return canonical

    best_subject = ""
    best_score = 0
    for subject, hints in _SUBJECT_HINTS:
        score = sum(1 for hint in hints if hint in folded)
        if score > best_score:
            best_subject = subject
            best_score = score
    return best_subject


@dataclass(frozen=True)
class QuestRequestSpec:
    grade: Optional[int]
    subject: str
    topic: str
    requested_count: int
    raw_request: str

    @property
    def missing_fields(self) -> tuple[str, ...]:
        """Return only information that is still genuinely needed.

        The Telegram handler resolves the request against the selected catalog,
        attachments, Umnix textbooks and web context before reading this property.
        Therefore this deliberately reports missing educational anchors rather
        than enforcing a rigid input template.
        """
        missing: list[str] = []
        if self.grade is None:
            missing.append("класс")
        if not self.subject:
            missing.append("предмет")
        if not self.topic:
            missing.append("тема")
        return tuple(missing)


def _looks_like_subject(value: str) -> bool:
    folded = _fold(value)
    if not folded:
        return False
    if folded in _SUBJECT_ALIASES:
        return True
    return any(
        _fold(subject) == folded
        for subject, _hints in _SUBJECT_HINTS
    )


def _extract_topic_from_natural_request(raw: str, subject: str) -> str:
    for pattern in (_TOPIC_AFTER_REQUEST_RE, _TOPIC_NATURAL_RE):
        match = pattern.search(raw)
        if not match:
            continue
        candidate = _strip_request_noise(match.group(1))
        # Remove a trailing grade/count that was captured as part of a natural phrase.
        candidate = re.sub(r"\s+(?:для\s+)?\d{1,2}\s*(?:класс(?:а|е)?|кл\.?)\s*$", "", candidate, flags=re.I)
        candidate = _clean(candidate)
        if candidate and _fold(candidate) != _fold(subject):
            return candidate

    # Free form can itself be the topic: "Пушкин, 6 класс", "животные для
    # первоклассника", "дроби". Do not force the learner to rewrite it as a label.
    candidate = _strip_request_noise(raw)
    if not candidate:
        return ""

    # Strip a leading explicit subject from "математика дроби" while keeping the
    # rest as the topic. This also works when the subject came from catalog state.
    if subject:
        subject_folded = _fold(subject)
        candidate_folded = _fold(candidate)
        subject_tokens = [subject_folded]
        subject_tokens.extend(
            alias
            for alias, canonical in _SUBJECT_ALIASES.items()
            if _fold(canonical) == subject_folded
        )
        for token in sorted(set(subject_tokens), key=len, reverse=True):
            if candidate_folded == token:
                return ""
            if candidate_folded.startswith(token + " "):
                return _clean(candidate[len(token):])

    if _looks_like_subject(candidate):
        return ""
    if _COUNT_ONLY_RE.match(candidate):
        return ""
    if len(candidate) < 2:
        return ""
    return candidate


def parse_quest_request(
    text: str,
    *,
    grade: Optional[int] = None,
    subject: str = "",
    topic: str = "",
    default_count: int = 5,
) -> QuestRequestSpec:
    """Parse a natural Telegram quest request without demanding a form-like message.

    Catalog selections (grade/subject/topic) have priority and never need to be
    repeated. The remaining information may be written conversationally, for example:
    ``"сделай тест по дробям для 7 класса"``, ``"животные для первоклассника"``
    or simply ``"Пушкин, 6 класс"``.

    This function intentionally performs tolerant local inference first. The caller
    can then enrich unresolved values from the selected textbook/page, attachments,
    the Umnix knowledge base and web context. A clarification is only necessary if
    an educational anchor is still missing after that enrichment.
    """
    raw = _clean(text)
    selected_grade = int(grade) if grade not in (None, "") else None
    selected_subject = _clean(subject)
    selected_topic = _clean(topic)

    if selected_grade is None:
        selected_grade = _extract_grade(raw)

    explicit_subject = False
    if not selected_subject:
        match = _SUBJECT_LABEL_RE.search(raw)
        if match:
            selected_subject = _clean(match.group(1))
            explicit_subject = True

    if not selected_topic:
        match = _TOPIC_LABEL_RE.search(raw)
        if match:
            selected_topic = _clean(match.group(1))

    phrase_match = _SUBJECT_TOPIC_RE.search(raw)
    if phrase_match:
        if not selected_subject:
            selected_subject = _clean(phrase_match.group(1))
            explicit_subject = True
        if not selected_topic:
            selected_topic = _clean(phrase_match.group(2))

    parts = _segments(raw)
    useful_parts: list[str] = []
    for part in parts:
        if _COUNT_ONLY_RE.match(part):
            continue
        if (_GRADE_RE.search(part) or _GRADE_FOR_RE.search(part)) and not _strip_request_noise(part):
            continue
        if re.match(r"^(?:класс|предмет|тема|topic|subject)\s*[:=\-–]", part, re.I):
            continue
        useful_parts.append(part)

    # Preserve the literal subject in the familiar compact form
    # "7 класс, математика, дроби". Canonicalization against DB program names is
    # deliberately done later by canonicalize_subject().
    if not selected_subject and useful_parts:
        candidate = useful_parts[0]
        candidate_clean = _strip_request_noise(candidate)
        if candidate_clean and _looks_like_subject(candidate_clean):
            selected_subject = candidate_clean
            explicit_subject = True

    if not selected_topic and len(useful_parts) >= 2:
        first = _strip_request_noise(useful_parts[0])
        second = _strip_request_noise(useful_parts[1])
        if second and (selected_subject or _looks_like_subject(first)):
            selected_topic = second

    # Infer the subject from the entire natural request before selecting a broad topic.
    if not selected_subject:
        selected_subject = infer_subject_from_text(selected_topic or raw)

    if not selected_topic:
        selected_topic = _extract_topic_from_natural_request(raw, selected_subject)

    # A topic can carry enough signal to infer the subject after it was extracted.
    if not selected_subject:
        selected_subject = infer_subject_from_text(selected_topic)

    # In primary school, biology/geography-style everyday topics normally belong to
    # "Окружающий мир". Keep an explicitly selected/labeled subject untouched.
    if (
        selected_grade is not None
        and selected_grade <= 4
        and selected_subject in {"Биология", "География"}
        and not explicit_subject
        and not subject
    ):
        selected_subject = "Окружающий мир"

    requested_count = extract_requested_task_count(raw, default=default_count, maximum=20)
    return QuestRequestSpec(
        grade=selected_grade,
        subject=selected_subject,
        topic=selected_topic,
        requested_count=requested_count,
        raw_request=raw,
    )



def quest_choice_issues(payload: dict[str, Any]) -> list[str]:
    """Validate the closed-answer contract before a quest is saved or shown."""
    issues: list[str] = []
    items = list(payload.get("items") or [])
    for index, item in enumerate(items, start=1):
        options = [str(value or "").strip() for value in (item.get("options") or [])]
        correct_raw = item.get("correct_option_numbers") or []
        try:
            correct = sorted({int(value) for value in correct_raw})
        except (TypeError, ValueError):
            correct = []
        if not 2 <= len(options) <= 6:
            issues.append(f"q{index}: expected 2..6 options, got {len(options)}")
            continue
        if any(not option for option in options):
            issues.append(f"q{index}: empty option")
        if len({_fold(option) for option in options}) != len(options):
            issues.append(f"q{index}: duplicate options")
        if not correct:
            issues.append(f"q{index}: correct_option_numbers is empty")
        elif any(number < 1 or number > len(options) for number in correct):
            issues.append(f"q{index}: correct option number is outside 1..{len(options)}")
        elif len(correct) >= len(options):
            issues.append(f"q{index}: all options cannot be correct")

    if len(items) >= 4:
        option_sizes = {len(item.get("options") or []) for item in items}
        if len(option_sizes) < 2:
            issues.append("quest option counts are monotonous: vary 2..6 choices by difficulty")
    if len(items) >= 6:
        multiple_flags = [len(set(item.get("correct_option_numbers") or [])) > 1 for item in items]
        if not any(multiple_flags):
            issues.append("quest needs at least one multiple-correct item")
        if all(multiple_flags):
            issues.append("quest needs at least one single-correct item")
    return issues


def normalize_quest_choice_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize option text and derived flags without changing answer semantics."""
    result = dict(payload or {})
    normalized_items: list[dict[str, Any]] = []
    for raw in list(result.get("items") or []):
        item = dict(raw or {})
        options = [_clean(value) for value in (item.get("options") or []) if _clean(value)][:6]
        numbers: list[int] = []
        for value in item.get("correct_option_numbers") or []:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= len(options) and number not in numbers:
                numbers.append(number)
        numbers.sort()
        item["options"] = options
        item["correct_option_numbers"] = numbers
        item["allow_multiple"] = len(numbers) > 1
        normalized_items.append(item)
    result["items"] = normalized_items
    result["question_count"] = len(normalized_items)
    return result


def format_quest_question(item: dict[str, Any], index: int, total: int) -> str:
    """Render one Telegram quest question with numbered answer options."""
    options = list(item.get("options") or [])
    multiple = bool(item.get("allow_multiple") or len(item.get("correct_option_numbers") or []) > 1)
    option_lines = "\n".join(f"{number}. {text}" for number, text in enumerate(options, start=1))
    mode = (
        "Можно выбрать несколько вариантов. Ответьте только их номерами, например: 1 3."
        if multiple
        else "Выберите один вариант и ответьте только его номером."
    )
    return (
        f"❓ Вопрос {index} из {total}\n\n"
        f"{str(item.get('question_text') or '').strip()}\n\n"
        f"{option_lines}\n\n"
        f"{mode}"
    ).strip()


def parse_quest_choice_answer(text: str, option_count: int) -> Optional[tuple[int, ...]]:
    """Parse a learner answer made only of option numbers separated by spaces/punctuation."""
    value = str(text or "").strip()
    if not value or option_count < 2:
        return None
    # Only digits and neutral separators are accepted: this keeps the UX explicit
    # and prevents accidental free-text answers from being interpreted as choices.
    if re.search(r"[^0-9\s,;.+]", value):
        return None
    numbers = [int(token) for token in re.findall(r"\d+", value)]
    if not numbers:
        return None
    unique = tuple(sorted(set(numbers)))
    if any(number < 1 or number > option_count for number in unique):
        return None
    return unique


def check_quest_choice_answer(item: dict[str, Any], text: str) -> tuple[Optional[bool], tuple[int, ...]]:
    """Return deterministic correctness for a multiple-choice quest item."""
    options = list(item.get("options") or [])
    selected = parse_quest_choice_answer(text, len(options))
    if selected is None:
        return None, ()
    correct = tuple(sorted({int(value) for value in (item.get("correct_option_numbers") or [])}))
    return selected == correct, selected


async def generate_quest_task_set(
    client,
    *,
    user_content: str,
    requested_count: int,
) -> tuple[GeneratedTaskSet, dict[str, Any]]:
    """Генерирует квест и один раз исправляет некорректный набор вариантов."""
    generated = await generate_exact_task_set(
        client,
        user_content=user_content,
        requested_count=requested_count,
    )
    payload = normalize_quest_choice_payload(task_set_payload(generated))
    issues = quest_choice_issues(payload)
    if not issues:
        return generated, payload

    repair_note = (
        "\n\nCHOICE FORMAT REPAIR. The previous quest did not satisfy the Telegram choice contract:\n- "
        + "\n- ".join(issues[:20])
        + "\nRegenerate the COMPLETE quest with the same requested number of questions. "
          "Every item must have 2..6 distinct options and valid 1-based correct_option_numbers."
    )
    repaired = await generate_exact_task_set(
        client,
        user_content=str(user_content or "") + repair_note,
        requested_count=requested_count,
        temperature=0.2,
    )
    repaired_payload = normalize_quest_choice_payload(task_set_payload(repaired))
    remaining = quest_choice_issues(repaired_payload)
    if remaining:
        raise ValueError("Quest choice validation failed: " + "; ".join(remaining[:12]))
    return repaired, repaired_payload

def canonicalize_subject(subject: str, candidates: list[str], *, threshold: float = 0.72) -> str:
    """Map a free-form/inflected subject name to an existing Umnix program when close enough."""
    value = _clean(subject)
    if not value or not candidates:
        return value
    folded = _fold(value)
    exact = next((item for item in candidates if _fold(item) == folded), None)
    if exact:
        return _clean(exact)

    # Common aliases should map naturally before fuzzy matching. This is useful for
    # catalog programs such as "Математика" when the learner simply wrote "алгебра".
    canonical_hint = _SUBJECT_ALIASES.get(folded)
    if canonical_hint:
        hinted = next((item for item in candidates if _fold(item) == _fold(canonical_hint)), None)
        if hinted:
            return _clean(hinted)

    scored = [
        (SequenceMatcher(None, folded, _fold(item)).ratio(), _clean(item))
        for item in candidates
        if _clean(item)
    ]
    if not scored:
        return value
    score, candidate = max(scored, key=lambda item: item[0])
    return candidate if score >= threshold else value
