"""Interfaccia comune ai backend LLM.

Tutto il resto del sistema parla solo con questo protocollo: cambiare provider
significa aggiungere un file qui, non toccare pipeline o CLI.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, prompt: str, json_schema: dict) -> dict:
        """Restituisce un dict conforme a `json_schema`.

        Il backend è responsabile di forzare l'output strutturato con i mezzi
        nativi del provider (structured output, tool use, grammar), non di
        sperare che il modello produca JSON valido.
        """
        ...

    def health_check(self) -> tuple[bool, str]:
        """(ok, messaggio) — usato dalla CLI per diagnosticare la config."""
        ...
