"""Fatture Personal (Telecom Argentina)."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from docanalyzer.models import MoneyAmount
from docanalyzer.profiles.base import register
from docanalyzer.profiles.core import InvoiceAnalysis


class PersonalInvoice(InvoiceAnalysis):
    """Fattura Personal (Telecom Argentina).

    Eredita da InvoiceAnalysis tutto ciò che vale per qualsiasi fattura —
    numero, date, parti, voci, totale — e aggiunge solo ciò che è proprio di
    questo emittente. Il totale non si ridefinisce: è già nel profilo padre.
    """

    cae: str | None = Field(
        default=None,
        description="Codice CAE AFIP, dopo 'C.A.E. Nº'. Solo cifre.",
    )
    cae_expiry: date | None = Field(
        default=None, description="Data dopo 'Fecha Vto. C.A.E.'"
    )
    referente_de_pago: str | None = Field(
        default=None,
        description="Codice a 16 cifre dopo 'Referente de Pago'. Non è il numero di fattura.",
    )
    seller_cuit: str | None = Field(
        default=None, description="C.U.I.T dell'emittente, formato 99-99999999-9"
    )
    periodo_abono: str | None = Field(
        default=None, description="Intervallo dopo 'Periodo de Abono', es. '14/09 al 13/10'"
    )
    periodo_consumo: str | None = Field(
        default=None, description="Intervallo dopo 'Periodo de Consumo'"
    )
    proximo_vencimiento: date | None = Field(
        default=None, description="Data dopo 'Próximo Vencimiento Estimado'"
    )
    saldo_anterior: MoneyAmount | None = Field(
        default=None, description="Voce 'Saldo Anterior'"
    )
    pagos_recibidos: MoneyAmount | None = Field(
        default=None, description="Voce 'Pagos al ...', di norma negativa"
    )
    metodo_pago: str | None = Field(
        default=None, description="Dopo 'Método de pago', es. 'Debito Automático'"
    )


register("personal", PersonalInvoice)
