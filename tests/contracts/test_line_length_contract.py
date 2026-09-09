from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CODE_ROOTS = (ROOT / "backend", ROOT / "frontend", ROOT / "tests")
ROOT_CODE = (
    ROOT / "main.py",
    ROOT / "config.py",
    ROOT / "database.py",
    ROOT / "logger_config.py",
    ROOT / "database.sql",
)
EXTENSIONS = {".py", ".js", ".css", ".html", ".sql"}


def _code_files() -> list[Path]:
    files = list(ROOT_CODE)
    for directory in CODE_ROOTS:
        files.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix in EXTENSIONS
        )
    return sorted(set(files))


def test_code_lines_do_not_exceed_120_characters() -> None:
    violations: list[str] = []
    for path in _code_files():
        relative = path.relative_to(ROOT)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if len(line) > 120:
                violations.append(f"{relative}:{line_number}:{len(line)}")
    assert not violations, "\n".join(violations[:100])
