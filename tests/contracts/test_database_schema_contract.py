from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "database.sql").read_text(encoding="utf-8")


def test_chat_attachment_link_contains_session_id() -> None:
    assert "CREATE TABLE chat_message_attachments" in SCHEMA
    assert "session_id UUID NOT NULL REFERENCES chat_sessions" in SCHEMA
    assert "idx_chat_message_attachments_session" in SCHEMA


def test_digitization_schema_contains_required_page_fields() -> None:
    for column in (
        "page_title TEXT",
        "page_number INTEGER NOT NULL",
        "page_paragraph TEXT",
        "page_html TEXT",
        "page_image TEXT",
        "page_text TEXT",
        "page_markdown TEXT",
    ):
        assert column in SCHEMA
