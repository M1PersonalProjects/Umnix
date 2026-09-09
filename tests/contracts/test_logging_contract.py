from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
LOGGER = (ROOT / "logger_config.py").read_text(encoding="utf-8")
HTTP_LOGGING = (ROOT / "backend/web/request_logging.py").read_text(encoding="utf-8")
BOT_INSTANCE = (ROOT / "backend/bot/bot_instance.py").read_text(encoding="utf-8")
BOT_MIDDLEWARE = (ROOT / "backend/bot/middleware.py").read_text(encoding="utf-8")
CLIENT_LOGGER = (ROOT / "frontend/static/js/client_logger.js").read_text(encoding="utf-8")
AUTH_ROUTER = (ROOT / "backend/api/auth_router.py").read_text(encoding="utf-8")


def test_http_actions_are_logged_for_terminal_and_app_log() -> None:
    assert 'app.middleware("http")(log_http_request)' in MAIN
    assert "RotatingFileHandler" in LOGGER
    assert "logging.StreamHandler" in LOGGER
    assert "log_user_action(" in HTTP_LOGGING


def test_user_action_format_contains_required_fields() -> None:
    assert 'now.strftime("%d.%m.%y")' in LOGGER
    assert 'now.strftime("%H.%M.%S")' in LOGGER
    assert "_status_label(status_code)" in LOGGER
    assert 'f"{source_file}:{int(line_number)}"' in LOGGER


def test_telegram_actions_are_logged_by_middleware() -> None:
    assert "UserActionLogMiddleware" in BOT_INSTANCE
    assert "dp.message.middleware" in BOT_INSTANCE
    assert "dp.callback_query.middleware" in BOT_INSTANCE
    assert "log_user_action(" in BOT_MIDDLEWARE


def test_frontend_runtime_errors_are_forwarded_to_server_logs() -> None:
    assert "window.addEventListener('error'" in CLIENT_LOGGER
    assert "window.addEventListener('unhandledrejection'" in CLIENT_LOGGER
    assert "/api/v1/auth/frontend-error" in CLIENT_LOGGER
    assert '@router.post("/frontend-error"' in AUTH_ROUTER
    assert "log_user_action(" in AUTH_ROUTER
