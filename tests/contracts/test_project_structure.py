from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_required_top_level_structure_exists() -> None:
    required = (
        "backend/auth",
        "backend/api",
        "backend/bot/handlers",
        "backend/web",
        "backend/digitization_books",
        "backend/files/books",
        "backend/files/attachments",
        "frontend/static/css",
        "frontend/static/js",
        "frontend/templates",
        "frontend/digitization_books",
        "docs",
    )

    for relative in required:
        assert (ROOT / relative).is_dir(), relative


def test_legacy_application_directories_are_not_present() -> None:
    for relative in ("api", "bot", "services", "static", "templates"):
        assert not (ROOT / relative).exists(), relative


def test_legacy_storage_directory_is_not_present() -> None:
    assert not (ROOT / "storage").exists()


def test_release_documentation_matches_new_structure() -> None:
    for relative in ("docs/api_spec.md", "docs/database_schema.md", "docs/user_guide.md"):
        assert (ROOT / relative).is_file(), relative
