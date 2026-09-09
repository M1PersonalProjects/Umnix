from pathlib import Path
from typing import Iterator

import fitz


class PdfPageRenderer:
    def __init__(self, pdf_path: Path, scale: float = 1.5):
        self.pdf_path = Path(pdf_path)
        self.scale = scale

    def iter_pages(self) -> Iterator[tuple[int, str, bytes]]:
        document = fitz.open(str(self.pdf_path))
        try:
            for index in range(len(document)):
                page = document.load_page(index)
                text = page.get_text("text") or ""
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(self.scale, self.scale),
                    alpha=False,
                )
                yield index + 1, text, pixmap.tobytes("png")
        finally:
            document.close()
