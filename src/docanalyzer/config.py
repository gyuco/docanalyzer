"""Configurazione via env (prefisso DOCANALYZER_) o file .env."""

from __future__ import annotations

from pathlib import Path

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

    # ----------------------------------------------------------------- #
    # Servizio (usati solo da docanalyzer.api)
    # ----------------------------------------------------------------- #

    # Database dei job e file caricati. Un solo posto da montare come volume
    # e da mettere nei backup.
    data_dir: Path = Path("./data")
    # Un PDF oltre questa soglia o è un errore o è un batch travestito.
    max_upload_mb: int = 50
    # Dopo quante ore job e file caricati vengono cancellati. Sono fatture ed
    # estratti conto: la retention è una decisione esplicita, non l'inerzia di
    # una directory che non si svuota mai.
    job_retention_hours: int = 24
    # Chiave condivisa richiesta nell'header X-API-Key. Vuota = nessun
    # controllo: accettabile solo in locale.
    api_key: str = ""
    # Intervallo di polling della coda quando è vuota.
    worker_poll_seconds: float = 1.0
    # Tentativi per job prima di dichiararlo definitivamente fallito. Serve
    # contro il documento-veleno: quello che fa morire il processo di
    # estrazione verrebbe altrimenti ripreso all'infinito.
    max_attempts: int = 2


settings = Settings()
