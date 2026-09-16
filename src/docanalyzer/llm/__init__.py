"""Registry dei backend LLM."""

from __future__ import annotations

from docanalyzer.config import settings
from docanalyzer.llm.base import LLMBackend


def get_backend(name: str | None = None, model: str | None = None) -> LLMBackend:
    backend_name = (name or settings.backend).lower()

    if backend_name == "ollama":
        from docanalyzer.llm.ollama_backend import OllamaBackend

        return OllamaBackend(model=model)
    if backend_name == "anthropic":
        from docanalyzer.llm.anthropic_backend import AnthropicBackend

        return AnthropicBackend(model=model)
    if backend_name == "openai":
        from docanalyzer.llm.openai_backend import OpenAIBackend

        return OpenAIBackend(model=model)

    raise ValueError(
        f"Backend sconosciuto: {backend_name!r}. Disponibili: {available_backends()}"
    )


def available_backends() -> list[str]:
    return ["ollama", "anthropic", "openai"]


__all__ = ["LLMBackend", "available_backends", "get_backend"]
