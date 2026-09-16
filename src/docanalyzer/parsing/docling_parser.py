"""Fase 2: Docling per PDF scansionati (OCR) e tabelle complesse.

Non si autoseleziona: `supports()` è sempre False, va scelto esplicitamente
con `--parser docling`. Motivo: il primo caricamento scarica ~1 GB di modelli
e su un documento nativo è ordini di grandezza più lento di PyMuPDF.

Installazione:  uv sync --extra ocr
"""

from __future__ import annotations

from pathlib import Path

from docanalyzer.models import PageContent, ParsedDocument
from docanalyzer.parsing.base import register


class DoclingParser:
    name = "docling"

    def supports(self, path: Path) -> bool:
        return False

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:  # pragma: no cover - dipende dall'extra
            raise RuntimeError(
                "Docling non installato. Esegui: uv sync --extra ocr"
            ) from exc

        result = DocumentConverter().convert(str(path))
        doc = result.document

        pages: list[PageContent] = []
        page_numbers = sorted(doc.pages) if doc.pages else [1]
        for number in page_numbers:
            markdown = doc.export_to_markdown(page_no=number)
            pages.append(PageContent(number=number, text=markdown))

        return ParsedDocument(
            source=path,
            parser=self.name,
            pages=pages,
            metadata={"docling_name": doc.name} if doc.name else {},
        )


register(DoclingParser())
