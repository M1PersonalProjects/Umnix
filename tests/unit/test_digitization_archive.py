import zipfile
from pathlib import Path

import pytest

from backend.digitization_books.archive_extractor import extract_pdf_members


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_extracts_only_pdf_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "books.zip"
    _write_zip(
        archive_path,
        {
            "1|Math|A|Book.pdf": b"%PDF-test",
            "notes.txt": b"ignore",
        },
    )

    extracted = list(extract_pdf_members(archive_path, tmp_path / "out"))

    assert len(extracted) == 1
    assert extracted[0].original_name == "1|Math|A|Book.pdf"
    assert extracted[0].path.read_bytes() == b"%PDF-test"


def test_rejects_archive_without_pdf(tmp_path: Path) -> None:
    archive_path = tmp_path / "empty.zip"
    _write_zip(archive_path, {"notes.txt": b"text"})

    with pytest.raises(ValueError, match="не содержит PDF"):
        list(extract_pdf_members(archive_path, tmp_path / "out"))
