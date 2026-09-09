from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "frontend/digitization_books/digitization.js").read_text(encoding="utf-8")
ADMIN_HTML = (ROOT / "frontend/templates/admin.html").read_text(encoding="utf-8")
PROMPT = (ROOT / "backend/digitization_books/prompts.py").read_text(encoding="utf-8")


def test_digitization_frontend_has_preview_confirm_and_queue_flow() -> None:
    assert "Предварительный просмотр" in SCRIPT
    assert "Вы точно проверили информацию об Учебнике?" in SCRIPT
    assert "/digitization/batches/" in SCRIPT
    assert "/digitization/jobs" in SCRIPT


def test_admin_has_required_sections() -> None:
    for label in ("Учебники", "Оцифровка", "Редактор страниц", "Пользователи", "Активность"):
        assert label in ADMIN_HTML


def test_digitization_prompt_requires_meaningful_page_title() -> None:
    assert "Never use a generic value" in PROMPT
    assert "page_paragraph" in PROMPT
    assert "raw_text" in PROMPT
    assert "html_content" in PROMPT
    assert "markdown_content" in PROMPT
