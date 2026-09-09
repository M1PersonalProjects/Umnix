from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "config.py").read_text(encoding="utf-8")
TUTOR = (ROOT / "backend/web/ai_tutor.py").read_text(encoding="utf-8")
DIGITIZER = (ROOT / "backend/digitization_books/gpt_vision_client.py").read_text(
    encoding="utf-8"
)


def test_regular_ai_timeout_is_capped_at_ten_minutes() -> None:
    assert "default=600.0" in CONFIG
    assert "le=600" in CONFIG
    assert "timeout=settings.openai_timeout_seconds" in TUTOR


def test_digitization_client_has_no_application_timeout() -> None:
    assert "timeout=None" in DIGITIZER


def test_digitization_is_page_by_page() -> None:
    assert "for page_number, embedded_text, image_bytes in renderer.iter_pages()" in DIGITIZER
    assert "ON CONFLICT (book_id, page_number) DO UPDATE" in DIGITIZER
