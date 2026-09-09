from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MEMORY_SOURCE = (ROOT / "backend/web/chat_memory.py").read_text(encoding="utf-8")
TUTOR_SOURCE = (ROOT / "backend/web/ai_tutor.py").read_text(encoding="utf-8")


def test_memory_uses_exactly_last_fifteen_messages() -> None:
    assert "SHORT_TERM_MESSAGES = 15" in MEMORY_SOURCE
    assert "WHERE user_id = $1 AND session_id = $2" in MEMORY_SOURCE
    assert "LIMIT $3" in MEMORY_SOURCE


def test_attachment_memory_is_scoped_to_session() -> None:
    assert "cm.session_id = $2" in MEMORY_SOURCE
    assert "all unique attachments" not in MEMORY_SOURCE.lower()
    assert "session_attachments(" in TUTOR_SOURCE


def test_tutor_does_not_use_cross_chat_summary_memory() -> None:
    assert 'session_memory = ""' in TUTOR_SOURCE
    assert "memory_summary" not in MEMORY_SOURCE


def test_telegram_chat_links_saved_attachment_to_session_memory() -> None:
    source = (ROOT / "backend/bot/handlers/chat.py").read_text(encoding="utf-8")
    assert 'attachment_id=getattr(attachment, "attachment_id", None)' in source


def test_telegram_attachment_storage_failure_is_not_silently_ignored() -> None:
    source = (ROOT / "backend/bot/handlers/media.py").read_text(encoding="utf-8")
    assert 'raise AttachmentError("Не удалось сохранить вложение в память чата")' in source
