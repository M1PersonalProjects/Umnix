from __future__ import annotations

import re
from typing import Any, Optional

TEACHER = "teacher"
TUTOR_PRACTICE = "tutor_practice"
VALID_ASSIGNMENT_SOURCES = {TEACHER, TUTOR_PRACTICE}


def normalize_assignment_source(value: Optional[str], parent_id: Optional[int] = None) -> str:
    """Нормализует источник задания и поддерживает старые строки до миграции."""
    normalized = (value or "").strip().lower()
    if normalized in VALID_ASSIGNMENT_SOURCES:
        return normalized
    return TEACHER if parent_id is not None else TUTOR_PRACTICE


def infer_difficulty(*values: Any) -> str:
    """Определяет учебную сложность задания."""
    text = " ".join(str(value or "") for value in values).lower().replace("ё", "е")
    if re.search(r"\b(hard|challenging|difficult|advanced|сложн\w*|повышенн\w*|олимпиадн\w*)\b", text):
        return "hard"
    return "normal"
