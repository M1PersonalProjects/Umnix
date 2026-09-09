from typing import Optional

MENTOR_TEACHER = "teacher"
MENTOR_PARENT = "parent"
_VALID_KINDS = {MENTOR_TEACHER, MENTOR_PARENT}


def normalize_mentor_kind(value: Optional[str]) -> str:
    """
    Нормализует значение mentor_kind, возвращая одно из допустимых значений.
    """
    value = (value or "").strip().lower()
    return value if value in _VALID_KINDS else MENTOR_TEACHER


def mentor_label(value: Optional[str], case: str = "nominative") -> str:
    """
    Возвращает метку для mentor_kind в указанном падеже.
    """
    kind = normalize_mentor_kind(value)
    forms = {
        MENTOR_TEACHER: {
            "nominative": "Учитель",
            "genitive": "Учителя",
            "dative": "Учителю",
            "instrumental": "Учителем",
            "plural": "Учителя",
        },
        MENTOR_PARENT: {
            "nominative": "Родитель",
            "genitive": "Родителя",
            "dative": "Родителю",
            "instrumental": "Родителем",
            "plural": "Родители",
        },
    }
    return forms[kind].get(case, forms[kind]["nominative"])
