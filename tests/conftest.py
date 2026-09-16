"""Configurazione dei test.

Nessun campo di `Settings` ha un default nel codice, e `.env` non è versionato:
senza queste variabili la sola importazione di `docanalyzer` fallirebbe su un
clone pulito. I valori qui sotto servono solo a far partire la suite — i test
non chiamano nessun modello.
"""

from __future__ import annotations

import os

_DEFAULTS = {
    "DOCANALYZER_BACKEND": "ollama",
    "DOCANALYZER_MODEL": "gemma4:e4b",
    "DOCANALYZER_OLLAMA_HOST": "http://localhost:11434",
    "DOCANALYZER_TEMPERATURE": "0.0",
    "DOCANALYZER_NUM_CTX": "32768",
    "DOCANALYZER_MAX_INPUT_CHARS": "60000",
    "DOCANALYZER_REQUEST_TIMEOUT": "600",
    "DOCANALYZER_DATA_DIR": "./data",
    "DOCANALYZER_MAX_UPLOAD_MB": "50",
    "DOCANALYZER_JOB_RETENTION_HOURS": "24",
    "DOCANALYZER_API_KEY": "",
    "DOCANALYZER_WORKER_POLL_SECONDS": "1.0",
    "DOCANALYZER_MAX_ATTEMPTS": "2",
}

# Va fatto prima di qualsiasi import di docanalyzer: `settings` viene costruito
# al momento dell'importazione del modulo.
for _key, _value in _DEFAULTS.items():
    os.environ.setdefault(_key, _value)
