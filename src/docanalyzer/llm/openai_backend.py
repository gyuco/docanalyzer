"""Backend OpenAI-compatibile.

Utile anche per i server locali che espongono l'API OpenAI (vLLM, LM Studio,
llama.cpp server): basta impostare OPENAI_BASE_URL.

Installazione:  uv sync --extra openai
"""

from __future__ import annotations

import json
import os

from docanalyzer.config import settings

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIBackend:
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or DEFAULT_MODEL
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "SDK OpenAI non installato. Esegui: uv sync --extra openai"
                ) from exc
            self._client = OpenAI(timeout=settings.request_timeout)
        return self._client

    def complete_json(self, system: str, prompt: str, json_schema: dict) -> dict:
        response = self._get_client().chat.completions.create(
            model=self.model,
            temperature=settings.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "analysis",
                    "schema": json_schema,
                    "strict": False,
                },
            },
        )
        return json.loads(response.choices[0].message.content or "{}")

    def health_check(self) -> tuple[bool, str]:
        if not os.getenv("OPENAI_API_KEY") and not os.getenv("OPENAI_BASE_URL"):
            return False, "OPENAI_API_KEY (o OPENAI_BASE_URL) non impostata"
        try:
            self._get_client()
        except RuntimeError as exc:
            return False, str(exc)
        return True, f"openai/{self.model} pronto"
