import base64
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from xml.etree import ElementTree
from html.parser import HTMLParser

import fitz


MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_PDF_BYTES = 100 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".py", ".log", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".rtf",
}
ZIP_DOCUMENT_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub"}
DOCUMENT_EXTENSIONS = {".pdf", ".djvu", *ZIP_DOCUMENT_EXTENSIONS, *TEXT_EXTENSIONS}
MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/epub+zip": ".epub",
    "text/plain": ".txt", "text/markdown": ".md", "text/csv": ".csv",
    "text/html": ".html", "application/json": ".json", "application/xml": ".xml",
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "image/gif": ".gif",
}


def attachment_size_limit(filename: str, mime_type: str = "") -> int:
    extension = Path(filename or "").suffix.lower()
    if extension == ".pdf" or (mime_type or "").lower() == "application/pdf":
        return MAX_PDF_BYTES
    return MAX_ATTACHMENT_BYTES


class AttachmentError(ValueError):
    pass


@dataclass
class ParsedAttachment:
    filename: str
    mime_type: str
    extracted_text: str = ""
    image_data_urls: List[str] = field(default_factory=list)


class _TextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _html_text(data: bytes) -> str:
    parser = _TextHTMLParser()
    parser.feed(data.decode("utf-8", errors="replace"))
    return " ".join(parser.parts)


def _data_url(data: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def _xml_text(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    chunks = [node.text for node in root.iter() if node.text and node.text.strip()]
    return " ".join(chunks)


def _safe_archive_names(archive: zipfile.ZipFile, predicate) -> List[str]:
    names = [item.filename for item in archive.infolist() if predicate(item.filename)]
    total_size = sum(archive.getinfo(name).file_size for name in names)
    if total_size > 40 * 1024 * 1024:
        raise AttachmentError("Распакованный документ слишком большой")
    return names


def _parse_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = _safe_archive_names(
            archive, lambda name: name.startswith("word/") and name.endswith(".xml")
        )
        return "\n".join(_xml_text(archive.read(name)) for name in names)


def _parse_xlsx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = _safe_archive_names(
            archive,
            lambda name: name == "xl/sharedStrings.xml"
            or bool(re.match(r"xl/worksheets/sheet\d+\.xml", name)),
        )
        return "\n".join(_xml_text(archive.read(name)) for name in names)


def _parse_pptx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = _safe_archive_names(
            archive, lambda name: bool(re.match(r"ppt/slides/slide\d+\.xml", name))
        )
        return "\n".join(_xml_text(archive.read(name)) for name in names)


def _parse_open_document(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = _safe_archive_names(
            archive, lambda name: name == "content.xml" or name.endswith(('.xhtml', '.html'))
        )
        parts = []
        for name in names:
            payload = archive.read(name)
            parts.append(_html_text(payload) if name.endswith(('.xhtml', '.html')) else _xml_text(payload))
        return "\n".join(parts)


def _parse_rtf(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    return re.sub(r"[{}]", " ", text)


def _parse_fitz_document(data: bytes, filetype: str):
    text_parts: List[str] = []
    images: List[str] = []
    document = fitz.open(stream=data, filetype=filetype)
    try:
        for index, page in enumerate(document):
            text = page.get_text("text").strip()
            if text:
                text_parts.append(f"[Страница {index + 1}]\n{text}")
            else:
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(1.35, 1.35),
                    alpha=False,
                )
                images.append(_data_url(pixmap.tobytes("jpeg"), "image/jpeg"))
    finally:
        document.close()
    return "\n\n".join(text_parts), images


def _parse_djvu_external(data: bytes) -> str:
    executable = shutil.which("djvutxt")
    if not executable:
        raise AttachmentError("Для DjVu установите системную утилиту djvulibre (djvutxt)")
    with tempfile.NamedTemporaryFile(suffix=".djvu") as source:
        source.write(data)
        source.flush()
        completed = subprocess.run(
            [executable, source.name], capture_output=True, check=True, timeout=30
        )
    return completed.stdout.decode("utf-8", errors="replace")


def parse_attachment(data: bytes, filename: str, mime_type: str = "") -> ParsedAttachment:
    if not data:
        raise AttachmentError("Вложение пустое")
    safe_name = Path(filename or "attachment").name
    extension = Path(safe_name).suffix.lower()
    mime_type = mime_type or "application/octet-stream"
    size_limit = attachment_size_limit(safe_name, mime_type)
    if len(data) > size_limit:
        limit_mb = size_limit // (1024 * 1024)
        raise AttachmentError(f"Максимальный размер этого вложения — {limit_mb} МБ")
    if not extension:
        extension = MIME_EXTENSIONS.get(mime_type.lower(), "")
    if extension not in IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS:
        raise AttachmentError(f"Формат {extension or mime_type} пока не поддерживается")

    result = ParsedAttachment(filename=safe_name, mime_type=mime_type)
    if extension in IMAGE_EXTENSIONS:
        result.image_data_urls.append(_data_url(data, mime_type if mime_type.startswith("image/") else "image/jpeg"))
    elif extension == ".pdf":
        result.extracted_text, result.image_data_urls = _parse_fitz_document(data, "pdf")
    elif extension == ".docx":
        result.extracted_text = _parse_docx(data)
    elif extension == ".xlsx":
        result.extracted_text = _parse_xlsx(data)
    elif extension == ".pptx":
        result.extracted_text = _parse_pptx(data)
    elif extension in {".odt", ".ods", ".odp", ".epub"}:
        result.extracted_text = _parse_open_document(data)
    elif extension == ".djvu":
        try:
            result.extracted_text, result.image_data_urls = _parse_fitz_document(data, "djvu")
        except Exception:
            result.extracted_text = _parse_djvu_external(data)
    elif extension in {".html", ".htm"}:
        result.extracted_text = _html_text(data)
    elif extension == ".rtf":
        result.extracted_text = _parse_rtf(data)
    else:
        result.extracted_text = data.decode("utf-8", errors="replace")

    result.extracted_text = result.extracted_text.strip()
    if not result.extracted_text and not result.image_data_urls:
        raise AttachmentError("Не удалось извлечь текст или изображение из файла")
    return result
