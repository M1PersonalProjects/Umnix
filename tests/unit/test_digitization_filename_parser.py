import pytest

from backend.digitization_books.filename_parser import parse_textbook_filename


def test_parses_expected_textbook_filename() -> None:
    result = parse_textbook_filename(
        "1|Математика|Быкова Т. П.|Тесты повыш. сложности 1 часть.pdf"
    )

    assert result.book_class == 1
    assert result.book_program == "Математика"
    assert result.book_author == "Быкова Т. П."
    assert result.book_title == "Тесты повыш. сложности 1 часть"


@pytest.mark.parametrize("book_class", [0, 12, 99])
def test_rejects_class_outside_school_range(book_class: int) -> None:
    with pytest.raises(ValueError, match="от 1 до 11"):
        parse_textbook_filename(f"{book_class}|Математика|Автор|Название.pdf")


def test_rejects_filename_without_four_blocks() -> None:
    with pytest.raises(ValueError, match="Класс\\|Предмет\\|Автор\\|Название"):
        parse_textbook_filename("1|Математика|Название.pdf")
