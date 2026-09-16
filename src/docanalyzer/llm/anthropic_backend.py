"""Backend Claude. Output strutturato ottenuto via tool use forzato.

Installazione:  uv sync --extra anthropic
Richiede ANTHROPIC_API_KEY nell'ambiente.
"""

from __future__ import annotations

import os

from docanalyzer.config import settings

_TOOL_NAME = "record_analysis"


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import Anthropic
            except ImportError as exc:
                raise RuntimeError(
                    "SDK Anthropic non installato. Esegui: uv sync --extra anthropic"
                ) from exc
            self._client = Anthropic(timeout=settings.request_timeout)
        return self._client

    def complete_json(self, system: str, prompt: str, json_schema: dict) -> dict:
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=8192,
            temperature=settings.temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": _TOOL_NAME,
                    "description": "Registra l'analisi strutturata del documento.",
                    "input_schema": json_schema,
                }
            ],
            # Forza il modello a rispondere attraverso lo schema del tool.
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == _TOOL_NAME:
                return block.input
        raise RuntimeError("Nessun tool_use nella risposta del modello")

    def health_check(self) -> tuple[bool, str]:
        if not os.getenv("ANTHROPIC_API_KEY"):
            return False, "ANTHROPIC_API_KEY non impostata"
        try:
            self._get_client()
        except RuntimeError as exc:
            return False, str(exc)
        return True, f"anthropic/{self.model} pronto"
