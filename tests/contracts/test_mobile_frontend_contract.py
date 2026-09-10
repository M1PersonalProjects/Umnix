from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_HTML = (ROOT / "frontend/templates/auth.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "frontend/static/js/app.js").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "frontend/static/js/chat.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/static/css/app.css").read_text(encoding="utf-8")


def test_login_mobile_is_compact_and_uses_umnixai_brand() -> None:
    assert 'class="auth-page"' in AUTH_HTML
    assert 'class="auth-bot-summary ' in AUTH_HTML
    assert '<span class="umnix-wordmark">UmnixAI</span>' in AUTH_HTML
    assert 'https://t.me/EduAI_platform_bot' in AUTH_HTML
    assert 'body.auth-page .auth-bot-summary' in CSS
    assert 'display: none !important;' in CSS[CSS.index('body.auth-page .auth-bot-summary'):]


def test_login_page_has_no_theme_picker_and_default_theme_is_system() -> None:
    assert "const THEME_KEY = 'umnix.ui.theme';" in APP_JS
    assert "safeGet(THEME_KEY, 'system')" in APP_JS
    assert "document.body.classList.contains('auth-page')" in APP_JS


def test_mobile_tutor_keeps_topbar_book_mode_and_arrow_drawer_controls() -> None:
    assert 'MOBILE AUTH + UNIFIED TOPBAR' in CSS
    assert 'body.student-page[data-active-section="tutor"] .topbar' in CSS
    assert '<span>Book Mode</span>' in APP_JS
    assert "button.textContent = '<'" in CHAT_JS
    assert "button.textContent = '>'" in CHAT_JS
