import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _local_module_exists(module_name: str) -> bool:
    path = ROOT.joinpath(*module_name.split("."))
    return path.with_suffix(".py").exists() or (path / "__init__.py").exists()


def test_backend_local_import_targets_exist() -> None:
    missing: list[str] = []
    sources = list((ROOT / "backend").rglob("*.py"))
    sources.extend(ROOT / name for name in ("main.py", "config.py", "database.py", "logger_config.py"))
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend"):
                if not _local_module_exists(node.module):
                    missing.append(f"{source.relative_to(ROOT)}:{node.lineno}:{node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("backend") and not _local_module_exists(alias.name):
                        missing.append(f"{source.relative_to(ROOT)}:{node.lineno}:{alias.name}")
    assert not missing, "\n".join(missing)


def test_template_local_assets_exist() -> None:
    missing: list[str] = []
    pattern = re.compile(r"(?:src|href)=[\"'](/(?:static|digitization-books)/[^\"'?]+)")
    for template in (ROOT / "frontend/templates").glob("*.html"):
        for url in pattern.findall(template.read_text(encoding="utf-8")):
            if url.startswith("/static/"):
                target = ROOT / "frontend/static" / url.removeprefix("/static/")
            else:
                target = ROOT / "frontend/digitization_books" / url.removeprefix("/digitization-books/")
            if not target.exists():
                missing.append(f"{template.name}: {url}")
    assert not missing, "\n".join(missing)
