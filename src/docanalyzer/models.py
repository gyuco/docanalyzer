"""Schemi dati: documento sorgente, testo estratto, risultati di analisi.

Gli schemi di analisi sono Pydantic: lo stesso schema serve sia per validare
l'output del modello sia per generare il JSON Schema passato all'LLM.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


class PageContent(BaseModel):
    number: int = Field(description="Numero di pagina, 1-based")
    text: str
    # Popolato solo dai parser che sanno rilevarlo (es. Docling in fase 2).
    tables_markdown: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    """Risultato del parsing, indipendente dal formato di partenza."""

    source: Path
    mime_type: str | None = None
    parser: str = Field(description="Nome del parser che ha prodotto il contenuto")
    pages: list[PageContent] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    # True quando il testo estratto è così scarso da far sospettare una scansione.
    likely_scanned: bool = False

    @property
    def text(self) -> str:
        chunks = []
        for page in self.pages:
            chunks.append(page.text)
            chunks.extend(page.tables_markdown)
        return "\n\n".join(c for c in chunks if c.strip())

    @property
    def char_count(self) -> int:
        return len(self.text)


# --------------------------------------------------------------------------- #
# Analisi
# --------------------------------------------------------------------------- #


class DocumentType(str, Enum):
    INVOICE = "fattura"
    BANK_STATEMENT = "estratto_conto"
    RECEIPT = "ricevuta"
    CONTRACT = "contratto"
    ID_DOCUMENT = "documento_identita"
    LETTER = "lettera"
    REPORT = "report"
    OTHER = "altro"


class MoneyAmount(BaseModel):
    value: float
    currency: str = Field(default="EUR", description="Codice ISO 4217")


class Party(BaseModel):
    name: str
    tax_id: str | None = Field(default=None, description="P.IVA, codice fiscale o equivalente")
    address: str | None = None


class LineItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: MoneyAmount | None = None
    total: MoneyAmount | None = None


class Transaction(BaseModel):
    # Non chiamarlo "date": il nome del campo oscurerebbe il tipo `date`
    # nella valutazione delle annotazioni.
    operation_date: date | None = None
    description: str
    amount: MoneyAmount
    balance_after: MoneyAmount | None = None


class AnalysisResult(BaseModel):
    """Contenitore: dati estratti + tracciabilità di come sono stati prodotti."""

    source: Path
    profile: str
    backend: str
    model: str
    parser: str
    data: dict
    elapsed_seconds: float
    truncated_input: bool = False
