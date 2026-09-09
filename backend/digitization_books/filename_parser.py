from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class BookMetadata:
    book_class: int
    book_program: str
    book_author: str
    book_title: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_textbook_filename(filename: str) -> BookMetadata:
    stem = Path(str(filename or "")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]

    parts = [part.strip() for part in stem.split("|")]
    if len(parts) != 4:
        raise ValueError(
            "Название PDF должно иметь формат: "
            "Класс|Предмет|Автор|Название.pdf"
        )

    class_text, program, author, title = parts
    try:
        book_class = int(class_text)
    except ValueError as exc:
        raise ValueError("Класс в названии PDF должен быть числом от 1 до 11") from exc

    if not 1 <= book_class <= 11:
        raise ValueError("Класс в названии PDF должен быть от 1 до 11")
    if not program:
        raise ValueError("В названии PDF не указан предмет")
    if not title:
        raise ValueError("В названии PDF не указано название учебника")

    return BookMetadata(
        book_class=book_class,
        book_program=program[:200],
        book_author=author[:300],
        book_title=title[:500],
    )
