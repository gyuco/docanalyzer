# docanalyzer

Lettura e analisi di documenti (bancari, fatture, contratti) con backend LLM
intercambiabili. Fase 1: documenti con testo nativo. Fase 2: OCR per le scansioni.

## Setup

```bash
uv sync
uv run docanalyzer doctor
```

## Uso

```bash
# Solo estrazione testo: mostra esattamente cosa vedrà il modello
uv run docanalyzer extract samples/fattura_demo.pdf

# Analisi con schema
uv run docanalyzer analyze samples/fattura_demo.pdf --profile invoice
uv run docanalyzer analyze doc.pdf -o risultato.json

# Cambiare backend/modello al volo
uv run docanalyzer analyze doc.pdf --model llama3.2:3b
uv run docanalyzer analyze doc.pdf --backend anthropic

uv run docanalyzer profiles
```

Configurazione persistente via `.env` (prefisso `DOCANALYZER_`):

```
DOCANALYZER_BACKEND=ollama
DOCANALYZER_MODEL=gemma4:e4b
DOCANALYZER_MAX_INPUT_CHARS=60000
```

## Architettura

```
src/docanalyzer/
  parsing/     Parser pluggable, selezionati per estensione
    base.py            protocollo + registry
    pymupdf_parser.py  PDF nativi (default, veloce)
    markitdown_parser.py  Office, email, HTML, CSV
    text_parser.py     txt/md
    docling_parser.py  FASE 2: OCR e tabelle complesse (extra `ocr`)
  llm/         Backend intercambiabili dietro un unico protocollo
    base.py            LLMBackend
    ollama_backend.py  locale, structured output nativo
    anthropic_backend.py / openai_backend.py   (extra opzionali)
  models.py    Schemi Pydantic: profili di estrazione
  pipeline.py  file -> parsing -> prompt -> LLM -> validazione
  cli.py
```

Due punti di estensione, entrambi a costo di un file:

- **nuovo formato** → un parser che implementa `Parser` e chiama `register()`
- **nuovo provider** → una classe che implementa `LLMBackend`, più una voce in
  `llm/__init__.py`

Un **nuovo tipo di documento** costa ancora meno: un modello Pydantic in
`models.py` e una voce in `PROFILES`.

## Scelte di progetto

- **Output strutturato forzato dal provider**, mai parsing di JSON a mano:
  `format` per Ollama, tool use per Claude, `json_schema` per OpenAI.
- **`$ref` inlinati** (`schema_utils.py`) perché i motori di constrained decoding
  li gestiscono in modo incoerente.
- **Nessun framework di orchestrazione.** Non serve finché la pipeline è lineare.
- **`open_questions` in ogni profilo**: c'è sempre un revisore umano, il modello
  deve dirgli dove guardare invece di inventare.
- **Le scansioni falliscono in modo esplicito** invece di produrre analisi vuote.

## Fase 2 — OCR

```bash
uv sync --extra ocr
uv run docanalyzer analyze scansione.pdf --parser docling
```

Il primo avvio scarica ~1 GB di modelli. Da valutare quando si arriverà lì:
Docling contro un VLM (Qwen3-VL via Ollama) che salta l'OCR e legge la pagina
come immagine — più robusto sui layout difficili, molto più lento.

## Test

```bash
uv run pytest
```

I test usano un backend finto: verificano la pipeline, non la qualità del modello.
