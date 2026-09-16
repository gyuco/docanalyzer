"""Parser per i formati non-PDF: Office, email, HTML, CSV, immagini con testo.

MarkItDown normalizza tutto in Markdown, che è un buon input per un LLM
perché conserva intestazioni e tabelle senza rumore di markup.
"""

from __future__ import annotations

from pathlib import Path

from docanalyzer.models import PageContent, ParsedDocument
from docanalyzer.parsing.base import register

EXTENSIONS = {
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".csv", ".tsv",
    ".html", ".htm", ".xml", ".json", ".epub", ".msg", ".eml", ".zip",
}


class MarkItDownParser:
    name = "markitdown"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in EXTENSIONS

    def parse(self, path: Path) -> ParsedDocument:
        from markitdown import MarkItDown

        result = MarkItDown(enable_plugins=False).convert(str(path))
        text = result.text_content or ""
        metadata = {"title": result.title} if result.title else {}

        return ParsedDocument(
            source=path,
            parser=self.name,
            # Questi formati non hanno una paginazione affidabile: una pagina sola.
            pages=[PageContent(number=1, text=text)],
            metadata=metadata,
            likely_scanned=False,
        )


register(MarkItDownParser())
