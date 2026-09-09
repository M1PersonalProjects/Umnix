from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTER = (ROOT / "backend/api/attachment_router.py").read_text(encoding="utf-8")
MEMORY = (ROOT / "backend/web/chat_memory.py").read_text(encoding="utf-8")


def test_attachment_api_exposes_upload_preview_and_download() -> None:
    assert '@router.post(""' in ROUTER
    assert '@router.get("/{attachment_id}/preview")' in ROUTER
    assert '@router.get("/{attachment_id}/download")' in ROUTER


def test_chat_history_returns_attachment_actions() -> None:
    assert '"download_url"' in MEMORY
    assert '"preview_url"' in MEMORY


def test_attachment_access_is_checked_before_file_response() -> None:
    assert "ensure_attachment_access" in ROUTER
    assert "FileResponse" in ROUTER
