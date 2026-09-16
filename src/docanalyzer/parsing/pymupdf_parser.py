"""Parser PDF nativi: veloce, zero dipendenze pesanti, nessun OCR."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from docanalyzer.models import PageContent, ParsedDocument
from docanalyzer.parsing.base import SCANNED_CHARS_PER_PAGE, register


class PyMuPDFParser:
    name = "pymupdf"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path) -> ParsedDocument:
        pages: list[PageContent] = []
        with pymupdf.open(path) as doc:
            metadata = {k: str(v) for k, v in (doc.metadata or {}).items() if v}
            for index, page in enumerate(doc, start=1):
                # "text" mantiene l'ordine di lettura meglio di "blocks" sui
                # layout a una colonna, che è il caso della gran parte dei
                # documenti bancari e delle fatture.
                pages.append(PageContent(number=index, text=page.get_text("text")))

        total_chars = sum(len(p.text.strip()) for p in pages)
        likely_scanned = bool(pages) and total_chars < SCANNED_CHARS_PER_PAGE * len(pages)

        return ParsedDocument(
            source=path,
            mime_type="application/pdf",
            parser=self.name,
            pages=pages,
            metadata=metadata,
            likely_scanned=likely_scanned,
        )


register(PyMuPDFParser())
