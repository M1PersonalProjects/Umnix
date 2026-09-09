from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "database.sql").read_text(encoding="utf-8")
ADMIN = (ROOT / "backend/api/admin_router.py").read_text(encoding="utf-8")
ACTIVITY = (ROOT / "backend/web/activity.py").read_text(encoding="utf-8")


def test_database_contains_activity_event_log() -> None:
    assert "CREATE TABLE activity_events" in SCHEMA
    assert "idx_activity_user_created" in SCHEMA


def test_admin_activity_combines_events_chats_files_sessions_and_tasks() -> None:
    for item_type in ("'event'::text", "'chat'::text", "'file'::text", "'session'::text", "'task'::text"):
        assert item_type in ADMIN


def test_admin_activity_supports_tg_id_and_word_search() -> None:
    assert "tg_id: Optional[int]" in ADMIN
    assert "q: Optional[str]" in ADMIN
    assert "ILIKE" in ADMIN


def test_activity_database_writer_does_not_duplicate_user_action_log() -> None:
    assert "activity tg_id=%s source=%s action=%s detail=%s" not in ACTIVITY
    assert "logger.debug" not in ACTIVITY


def test_admin_activity_task_union_has_single_detail_expression() -> None:
    marker = "FROM tasks_history th"
    start = ADMIN.rfind("SELECT", 0, ADMIN.index(marker))
    task_block = ADMIN[start:ADMIN.index(marker)]
    expression = "COALESCE(NULLIF(th.title, ''), NULLIF(th.topic, ''), th.status::text)"
    assert task_block.count(expression) == 1
