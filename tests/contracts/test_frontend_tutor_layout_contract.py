from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "frontend/static/css/app.css").read_text(encoding="utf-8")


def test_desktop_tutor_is_full_screen_without_max_width() -> None:
    marker = "Desktop AI Tutor: full-screen workspace without a centered max-width column."
    assert marker in CSS
    block = CSS[CSS.index(marker):]
    assert "@media (min-width: 1280px)" in block
    assert "width: 100vw !important" in block
    assert "max-width: none !important" in block
    assert "height: 100dvh !important" in block


def test_mobile_tutor_rules_are_kept_separate() -> None:
    assert "Mobile AI tutor = one clean chat surface" in CSS
    assert "@media (max-width: 767px)" in CSS
