"""Configurazione via env (prefisso DOCANALYZER_) o file .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCANALYZER_", env_file=".env", extra="ignore"
    )

    # Backend LLM: "ollama" | "anthropic" | "openai"
    backend: str = "ollama"
    # Modello locale di default. Multilingua e buono su output strutturato.
    model: str = "gemma4:e4b"
    ollama_host: str = "http://localhost:11434"

    temperature: float = 0.0
    # Finestra di contesto richiesta a Ollama. 32k su 16 GB di RAM unificata
    # è già oneroso: alzalo solo se il modello ci sta.
    num_ctx: int = 32768
    # Limite di caratteri passati al modello, oltre il quale si tronca.
    # ~4 char/token, quindi 60k char ≈ 15k token: lascia spazio a prompt e output.
    max_input_chars: int = 60_000

    request_timeout: int = 600


settings = Settings()
