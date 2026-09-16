"""Fallback per file di testo semplice."""

from __future__ import annotations

from pathlib import Path

from docanalyzer.models import PageContent, ParsedDocument
from docanalyzer.parsing.base import register

EXTENSIONS = {".txt", ".md", ".log", ".rst"}


class TextParser:
    name = "text"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in EXTENSIONS

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        return ParsedDocument(
            source=path,
            mime_type="text/plain",
            parser=self.name,
            pages=[PageContent(number=1, text=text)],
        )


register(TextParser())
