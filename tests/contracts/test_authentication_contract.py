from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_HTML = (ROOT / "frontend/templates/auth.html").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "frontend/static/js/auth.js").read_text(encoding="utf-8")
AUTH_ROUTER = (ROOT / "backend/api/auth_router.py").read_text(encoding="utf-8")
BOT_START = (ROOT / "backend/bot/handlers/start.py").read_text(encoding="utf-8")
SCHEMA = (ROOT / "database.sql").read_text(encoding="utf-8")
SECURITY = (ROOT / "backend/auth/security.py").read_text(encoding="utf-8")


def test_browser_login_is_wired_to_tg_id_form() -> None:
    assert "id=\"browser-login\"" in AUTH_HTML
    assert "id=\"telegram-id\"" in AUTH_HTML
    assert "/api/v1/auth/browser-login" in AUTH_JS
    assert "persist(data, 'telegram_id')" in AUTH_JS


def test_telegram_button_uses_bot_handshake() -> None:
    assert "Войти через Telegram Bot" in AUTH_HTML
    assert "https://t.me/EduAI_platform_bot" in AUTH_HTML
    assert "/api/v1/auth/telegram-bot/start" in AUTH_JS
    assert "/api/v1/auth/telegram-bot/status" in AUTH_JS
    assert "web_auth_" in AUTH_ROUTER
    assert 'args.startswith("web_auth_")' in BOT_START


def test_bot_auth_requests_are_persisted_server_side() -> None:
    assert "CREATE TABLE web_auth_requests" in SCHEMA
    assert "browser_token_hash TEXT NOT NULL" in SCHEMA
    assert "bot_token_hash TEXT NOT NULL UNIQUE" in SCHEMA
    assert "expires_at TIMESTAMPTZ NOT NULL" in SCHEMA


def test_login_is_remembered_and_logout_is_available() -> None:
    app_js = (ROOT / "frontend/static/js/app.js").read_text(encoding="utf-8")
    assert "localStorage.setItem(SESSION_KEY" in app_js
    assert "/api/v1/auth/logout" in app_js
    assert "clearSession()" in app_js
    assert "SESSION_TTL_SECONDS = 30 * 24 * 60 * 60" in SECURITY


def test_shared_frontend_bootstrap_does_not_contain_invalid_dynamic_regex() -> None:
    app_js = (ROOT / "frontend/static/js/app.js").read_text(encoding="utf-8")
    assert r"new RegExp(`\\(?:" not in app_js
    assert r"new RegExp(`\\\\(?:" in app_js
    assert "/static/js/app.js?v=20260909-auth-2" in AUTH_HTML
