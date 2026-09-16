"""Importa i parser così che si registrino. L'ordine definisce la priorità."""

from docanalyzer.parsing import (  # noqa: F401
    pymupdf_parser,
    markitdown_parser,
    text_parser,
    docling_parser,
)
from docanalyzer.parsing.base import Parser, available_parsers, get_parser

__all__ = ["Parser", "available_parsers", "get_parser"]
