from backend.web.response_formatter import contains_raw_latex
from backend.web.response_formatter import telegram_safe_text


def test_telegram_safe_text_removes_raw_latex() -> None:
    source = r"Решение: \(\frac{1}{2} + \sqrt{4}\)"

    result = telegram_safe_text(source)

    assert not contains_raw_latex(result)
    assert "1" in result
    assert "2" in result


def test_plain_text_keeps_normal_url_slashes() -> None:
    source = "Материал: https://example.org/a/b"

    assert "https://example.org/a/b" in telegram_safe_text(source)
