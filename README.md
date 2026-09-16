# docanalyzer

Lettura e analisi di documenti (fatture, estratti conto, contratti) con backend
LLM intercambiabili. I PDF nativi passano da un parser veloce; le scansioni
ricadono sull'OCR automaticamente.

## Setup

```bash
uv sync                      # base: PDF nativi, Office, testo
uv sync --extra ocr          # aggiunge l'OCR per le scansioni (~1 GB di modelli)
uv run docanalyzer doctor
```

## Uso

```bash
# Solo estrazione testo: mostra esattamente cosa vedrà il modello
uv run docanalyzer extract fattura.pdf

# Analisi con schema
uv run docanalyzer analyze fattura.pdf --profile invoice
uv run docanalyzer analyze doc.pdf -o risultato.json

# Cambiare backend/modello al volo
uv run docanalyzer analyze doc.pdf --model llama3.2:3b
uv run docanalyzer analyze doc.pdf --backend anthropic

uv run docanalyzer profiles
```

Il repository non include documenti di esempio: sono dati personali. Per
provarlo servono PDF tuoi, oppure si generano scansioni sintetiche (vedi sotto).

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
    docling_parser.py  OCR e tabelle complesse (extra `ocr`)
  profiles/    Schemi di estrazione, uno per file
    base.py            registry
    core.py            generic, invoice, bank_statement — il tronco comune
    personal.py        esempio: fatture Personal (Telecom Argentina)
    us_checking.py     esempio: estratti conto di banche USA
  llm/         Backend intercambiabili dietro un unico protocollo
    base.py            LLMBackend
    ollama_backend.py  locale, structured output nativo
    anthropic_backend.py / openai_backend.py   (extra opzionali)
  models.py    Mattoni condivisi: MoneyAmount, Party, LineItem, ParsedDocument
  pipeline.py  file -> parsing -> prompt -> LLM -> validazione
  cli.py
```

Tre punti di estensione, ciascuno al costo di un file:

- **nuovo formato** → un parser che implementa `Parser` e chiama `register()`
- **nuovo provider** → una classe che implementa `LLMBackend`, più una voce in
  `llm/__init__.py`
- **nuovo tipo di documento** → un modello Pydantic in `profiles/`, che chiama
  `register()`, più una riga nell'import di `profiles/__init__.py`

## Profili

Un profilo è lo schema dei campi da estrarre. Non serve solo a validare la
risposta: viene passato al provider come vincolo di decoding, quindi decide cosa
il modello *può* produrre.

I tre profili in `core.py` funzionano su qualsiasi emittente. Quando il formato
è noto conviene estenderne uno e aggiungere solo ciò che cambia:

```python
# profiles/movistar.py
class MovistarInvoice(InvoiceAnalysis):        # eredita numero, date, totale
    codigo_cliente: str | None = Field(
        default=None,
        description="Codice a 9 cifre dopo 'Nº de cliente'. Non è il numero di fattura.",
    )

register("movistar", MovistarInvoice)
```

Le `description` non sono commenti: finiscono nello JSON Schema e dicono al
modello dove guardare nella pagina. Su un formato noto sono la parte che incide
di più sulla qualità dell'estrazione.

Tenere i profili stretti conviene: ogni campo è obbligatorio per il decoding, e
uno schema ampio peggiora la resa oltre che i tempi.

## Scansioni e OCR

`analyze` sceglie il parser da sé: prova PyMuPDF e, se il PDF non ha un layer di
testo, passa a Docling. Un `--parser` esplicito disattiva il fallback.

Sul PDF nativo PyMuPDF impiega 0,2 secondi contro i 4,4 di Docling, che oltretutto
trascrive anche il rumore grafico: è il motivo per cui l'OCR non è il default.

Dopo l'OCR il testo viene misurato. Sotto i 100 caratteri utili per pagina —
scartati segnaposto di immagine e bordi di tabella — l'analisi si ferma con un
errore. Una scansione storta produce frammenti da cui il modello ricaverebbe uno
schema formalmente valido e privo di senso, indistinguibile da un'estrazione
riuscita.

### Generare scansioni di prova

`make_scan.py` rasterizza un PDF nativo applicando degradazioni realistiche. La
verità di riferimento resta nota — è il testo del PDF di partenza — quindi si può
misurare *quanto* perde l'OCR, non solo se gira.

```bash
uv run python make_scan.py fattura.pdf scan.pdf --dpi 200 --skew 3 --jpeg 60
uv run docanalyzer analyze scan.pdf --profile invoice
```

Opzioni: `--dpi`, `--skew` (gradi), `--jpeg` (qualità), `--blur`, `--noise`, `--gray`.

Misurato su una fattura di 3 pagine: l'inclinazione ha una soglia netta, non una
degradazione graduale — a 4° l'OCR regge, a 5° crolla. Il deskew è quindi il
preprocessing che rende di più. La bassa risoluzione da sola pesa meno del previsto:
72 dpi restano leggibili.

## Scelte di progetto

- **Output strutturato forzato dal provider**, mai parsing di JSON a mano:
  `format` per Ollama, tool use per Claude, `json_schema` per OpenAI.
- **Ogni proprietà è resa obbligatoria** (`require_all_properties`) prima di
  passare lo schema al modello. I motori di constrained decoding possono omettere
  le chiavi non richieste, e un modello piccolo prende sistematicamente quella
  scorciatoia: senza questo passaggio `seller`, `buyer` e `line_items` tornavano
  vuoti anche su documenti che li contenevano.
- **`$ref` inlinati** (`schema_utils.py`) perché i motori di constrained decoding
  li gestiscono in modo incoerente.
- **Nessun framework di orchestrazione.** Non serve finché la pipeline è lineare.
- **`open_questions` in ogni profilo**: c'è sempre un revisore umano, il modello
  deve dirgli dove guardare invece di inventare.
- **I documenti illeggibili falliscono in modo esplicito** invece di produrre
  analisi vuote o inventate.

## Limiti noti

- Il **profilo si sceglie a mano**: non c'è riconoscimento automatico
  dell'emittente.
- Il controllo dopo l'OCR misura la **quantità di testo, non la correttezza**: una
  scansione che produce molto testo con cifre sbagliate passa senza obiezioni.
- Il campo `currency` è una stringa libera e il modello ci mette spesso il simbolo
  (`$`) invece del codice ISO.
- I campi che richiedono **conteggi o somme** sono i meno affidabili.
- Docling va in **segmentation fault** su alcuni input.

## Test

```bash
uv run pytest
```

I test usano un backend finto: verificano la pipeline, non la qualità del modello.
