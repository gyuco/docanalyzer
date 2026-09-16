"""Il tronco comune: profili che funzionano su qualsiasi emittente.

Cambiano di rado e sono la base da cui ereditano i profili specifici.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from docanalyzer.models import DocumentType, LineItem, MoneyAmount, Party, Transaction
from docanalyzer.profiles.base import register


class GenericAnalysis(BaseModel):
    """Profilo di default: funziona su qualsiasi documento."""

    document_type: DocumentType
    language: str = Field(description="Lingua principale, codice ISO 639-1 (es. 'it')")
    summary: str = Field(description="Riassunto in 2-4 frasi, nella lingua del documento")
    key_facts: list[str] = Field(
        default_factory=list, description="Fatti salienti, uno per riga, massimo 10"
    )
    parties: list[Party] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list, description="Date rilevanti in formato ISO")
    amounts: list[MoneyAmount] = Field(default_factory=list)
    open_questions: list[str] = Field(
        default_factory=list,
        description="Punti ambigui o illeggibili che richiedono verifica umana",
    )


class InvoiceAnalysis(BaseModel):
    document_type: DocumentType = DocumentType.INVOICE
    invoice_number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    seller: Party | None = None
    buyer: Party | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: MoneyAmount | None = None
    tax: MoneyAmount | None = None
    total: MoneyAmount | None = None
    payment_terms: str | None = None
    open_questions: list[str] = Field(default_factory=list)


class BankStatementAnalysis(BaseModel):
    document_type: DocumentType = DocumentType.BANK_STATEMENT
    account_holder: Party | None = None
    iban: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    opening_balance: MoneyAmount | None = None
    closing_balance: MoneyAmount | None = None
    transactions: list[Transaction] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


register("generic", GenericAnalysis)
register("invoice", InvoiceAnalysis)
register("bank_statement", BankStatementAnalysis)
