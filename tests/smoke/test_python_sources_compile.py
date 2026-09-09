import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_python_sources_compile(tmp_path: Path) -> None:
    sources = [
        path
        for path in (ROOT / "backend").rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    sources.extend(ROOT / name for name in ("main.py", "config.py", "database.py", "logger_config.py"))

    for index, source in enumerate(sources):
        target = tmp_path / f"{index}.pyc"
        py_compile.compile(str(source), cfile=str(target), doraise=True)
