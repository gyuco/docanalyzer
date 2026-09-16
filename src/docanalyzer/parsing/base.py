"""Protocollo dei parser e registry per selezione in base all'estensione."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from docanalyzer.models import ParsedDocument

# Sotto questa soglia di caratteri per pagina consideriamo il PDF una scansione.
SCANNED_CHARS_PER_PAGE = 100


@runtime_checkable
class Parser(Protocol):
    name: str

    def supports(self, path: Path) -> bool: ...

    def parse(self, path: Path) -> ParsedDocument: ...


_REGISTRY: list[Parser] = []


def register(parser: Parser) -> Parser:
    _REGISTRY.append(parser)
    return parser


def get_parser(path: Path, preferred: str | None = None) -> Parser:
    if preferred:
        for parser in _REGISTRY:
            if parser.name == preferred:
                return parser
        raise ValueError(f"Parser sconosciuto: {preferred!r}")
    for parser in _REGISTRY:
        if parser.supports(path):
            return parser
    raise ValueError(f"Nessun parser disponibile per {path.name}")


def available_parsers() -> list[str]:
    return [p.name for p in _REGISTRY]
