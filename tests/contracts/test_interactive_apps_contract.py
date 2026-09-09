from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTER = (ROOT / "backend/api/interactive_router.py").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "frontend/static/js/chat.js").read_text(encoding="utf-8")


def test_interactive_api_supports_preview_download_and_assignment() -> None:
    assert '@router.get("/{app_id}")' in ROUTER
    assert '@router.get("/{app_id}/download")' in ROUTER
    assert '"/{app_id}/assign"' in ROUTER


def test_chat_ui_exposes_interactive_open_download_send_actions() -> None:
    assert "interactive-card-action" in CHAT_JS
    assert "/download?version=" in CHAT_JS
    assert "/assign?version=" in CHAT_JS
