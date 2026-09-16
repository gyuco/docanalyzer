"""Backend Ollama: modelli locali, output strutturato via parametro `format`."""

from __future__ import annotations

import json

from ollama import Client, ResponseError

from docanalyzer.config import settings


class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self.model = model or settings.model
        self._client = Client(
            host=host or settings.ollama_host, timeout=settings.request_timeout
        )

    def complete_json(self, system: str, prompt: str, json_schema: dict) -> dict:
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            # Ollama vincola il decoding al JSON Schema: l'output è sempre
            # sintatticamente valido, resta da validarlo semanticamente con Pydantic.
            format=json_schema,
            options={
                "temperature": settings.temperature,
                "num_ctx": settings.num_ctx,
            },
        )
        try:
            # Il reasoning va disattivato: su estrazione strutturata allunga i
            # tempi senza migliorare la resa, e i modelli piccoli ci si perdono.
            response = self._client.chat(**kwargs, think=False)
        except ResponseError:
            # Il modello non espone il reasoning: la chiamata normale va bene.
            response = self._client.chat(**kwargs)
        content = response.message.content or "{}"
        return json.loads(content)

    def health_check(self) -> tuple[bool, str]:
        try:
            installed = {m.model for m in self._client.list().models}
        except Exception as exc:
            return False, f"Ollama non raggiungibile su {settings.ollama_host}: {exc}"
        if self.model not in installed:
            return False, (
                f"Modello {self.model!r} non installato. "
                f"Esegui: ollama pull {self.model}"
            )
        return True, f"ollama/{self.model} pronto"
