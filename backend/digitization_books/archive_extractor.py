import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

MAX_PDF_FILES = 20
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ExtractedPdf:
    original_name: str
    path: Path
    size_bytes: int


def _safe_member_name(value: str) -> str:
    clean = value.replace("\\", "/")
    path = PurePosixPath(clean)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("ZIP содержит небезопасный путь")
    return Path(clean).name


def list_pdf_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    total_size = 0
    for info in archive.infolist():
        if info.is_dir() or "__MACOSX" in PurePosixPath(info.filename).parts:
            continue
        if not info.filename.lower().endswith(".pdf"):
            continue
        _safe_member_name(info.filename)
        if info.file_size > MAX_PDF_BYTES:
            raise ValueError(f"{info.filename}: PDF больше 100 МБ")
        total_size += info.file_size
        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("Распакованный ZIP слишком большой")
        members.append(info)

    if not members:
        raise ValueError("ZIP-архив не содержит PDF-файлов")
    if len(members) > MAX_PDF_FILES:
        raise ValueError(f"В ZIP разрешено не более {MAX_PDF_FILES} PDF")
    return members


def extract_pdf_members(
    archive_path: Path,
    destination_dir: Path,
) -> Iterable[ExtractedPdf]:
    destination_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for index, info in enumerate(list_pdf_members(archive), start=1):
            original_name = _safe_member_name(info.filename)
            destination = destination_dir / f"archive-{index:02d}-{original_name}"
            written = 0
            with archive.open(info, "r") as source, destination.open("wb") as target:
                while True:
                    chunk = source.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_PDF_BYTES:
                        destination.unlink(missing_ok=True)
                        raise ValueError(f"{original_name}: PDF больше 100 МБ")
                    target.write(chunk)
            yield ExtractedPdf(original_name, destination, written)
