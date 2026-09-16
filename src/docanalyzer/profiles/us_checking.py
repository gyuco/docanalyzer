"""Estratti conto di banche statunitensi."""

from __future__ import annotations

from pydantic import Field

from docanalyzer.models import MoneyAmount
from docanalyzer.profiles.base import register
from docanalyzer.profiles.core import BankStatementAnalysis


class USCheckingStatement(BankStatementAnalysis):
    """Estratto conto di banca USA: campi assenti dal formato europeo.

    Eredita il tronco comune (intestatario, periodo, saldi, transazioni) e vi
    aggiunge quello che cambia: niente IBAN ma routing number, e le sezioni di
    spese e assegni che sul formato americano stanno in tabelle separate.

    Le `description` non sono commenti: finiscono nello JSON Schema che vincola
    il decoding, quindi dicono al modello *dove guardare* nella pagina.
    """

    account_number: str | None = Field(
        default=None, description="Numero di conto, dopo 'Account #'"
    )
    routing_number: str | None = Field(
        default=None, description="ABA routing number, 9 cifre"
    )
    total_deposits: MoneyAmount | None = Field(
        default=None, description="Totale accrediti del periodo"
    )
    total_withdrawals: MoneyAmount | None = Field(
        default=None, description="Totale addebiti del periodo"
    )
    service_charges: MoneyAmount | None = Field(
        default=None,
        description="Spese, sezione 'Account Service Charges and Fees'",
    )
    checks_paid_count: int | None = Field(
        default=None, description="Numero di assegni nella tabella 'Checks Paid'"
    )


register("us_checking", USCheckingStatement)
