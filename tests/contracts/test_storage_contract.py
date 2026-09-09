from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "config.py").read_text(encoding="utf-8")
DIGITIZER = (ROOT / "backend/digitization_books/gpt_vision_client.py").read_text(
    encoding="utf-8"
)


def test_user_attachments_live_under_backend_files() -> None:
    assert 'attachments_dir: str = "backend/files/attachments"' in CONFIG
    assert (ROOT / "backend/files/attachments/.gitkeep").exists()


def test_digitized_book_files_live_under_backend_files_books() -> None:
    assert ' / "files" / "books"' in DIGITIZER
    assert (ROOT / "backend/files/books/.gitkeep").exists()
