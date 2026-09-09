import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_javascript_sources_parse() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")

    sources = list((ROOT / "frontend/static/js").glob("*.js"))
    sources.extend((ROOT / "frontend/digitization_books").glob("*.js"))
    for source in sources:
        subprocess.run(
            [node, "--check", str(source)],
            check=True,
            capture_output=True,
            text=True,
        )
