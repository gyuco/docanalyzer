"""Configurazione via env (prefisso DOCANALYZER_) o file .env.

Nessun campo ha un default: i valori stanno in `.env`, non qui. Parti da
`.env.example`, che li elenca tutti con la spiegazione di ciascuno.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCANALYZER_", env_file=".env", extra="ignore"
    )

    # Backend LLM: "ollama" | "anthropic" | "openai".
    backend: str
    # Nome del modello, nella forma che il backend scelto si aspetta.
    model: str
    ollama_host: str

    temperature: float
    # Finestra di contesto richiesta a Ollama.
    num_ctx: int
    # Limite di caratteri passati al modello, oltre il quale si tronca.
    max_input_chars: int

    request_timeout: int

    # ----------------------------------------------------------------- #
    # Servizio (usati solo da docanalyzer.api)
    # ----------------------------------------------------------------- #

    # Database dei job e file caricati. Un solo posto da montare come volume
    # e da mettere nei backup.
    data_dir: Path
    max_upload_mb: int
    # Dopo quante ore job e file caricati vengono cancellati.
    job_retention_hours: int
    # Chiave condivisa richiesta nell'header X-API-Key. Vuota = nessun
    # controllo: accettabile solo in locale.
    api_key: str
    # Intervallo di polling della coda quando è vuota.
    worker_poll_seconds: float
    # Tentativi per job prima di dichiararlo definitivamente fallito.
    max_attempts: int


def _load() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = sorted(
            f"DOCANALYZER_{err['loc'][0]}".upper()
            for err in exc.errors()
            if err["type"] == "missing"
        )
        if not missing:
            raise
        raise RuntimeError(
            "Configurazione incompleta. Mancano le variabili:\n  "
            + "\n  ".join(missing)
            + "\n\nNessun valore ha un default nel codice: crea il file .env "
            "partendo dall'esempio versionato.\n  cp .env.example .env"
        ) from exc


settings = _load()
