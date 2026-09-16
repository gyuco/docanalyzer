# docanalyzer

Lettura e analisi di documenti (fatture, estratti conto, contratti) con backend
LLM intercambiabili. I PDF nativi passano da un parser veloce; le scansioni
ricadono sull'OCR automaticamente.

Il nucleo è una libreria: `file → parsing → prompt → LLM → risultato validato`.
Sopra ci sono due modi di usarla, che condividono la stessa pipeline.

- **CLI** — un documento alla volta, output sul terminale. È il modo per capire
  cosa vede il modello e per tarare un profilo nuovo.
- **Servizio HTTP** — API a job più worker, per chiamarlo da un altro
  programma. L'analisi dura minuti, quindi si accoda invece di rispondere
  sincroni.

## Setup

```bash
cp .env.example .env         # obbligatorio: nessun valore ha un default nel codice
uv sync                      # base: PDF nativi, Office, testo
uv sync --extra ocr          # OCR per le scansioni (~1 GB di modelli)
uv sync --extra api          # servizio HTTP (FastAPI + uvicorn)
uv run docanalyzer doctor    # backend LLM raggiungibile? modello presente?
```

`.env.example` è versionato e contiene tutti i valori: copiandolo così com'è si
ottiene la configurazione locale con Ollama. Senza `.env` il programma non parte
e dice quali variabili mancano — meglio di un default silenzioso che fa girare
il sistema con una configurazione che nessuno ha scelto.

## Uso da riga di comando

```bash
# Solo estrazione testo: mostra esattamente cosa vedrà il modello
uv run docanalyzer extract fattura.pdf

# Analisi con schema
uv run docanalyzer analyze fattura.pdf --profile invoice
uv run docanalyzer analyze doc.pdf -o risultato.json

# Cambiare backend/modello al volo (scavalcano il .env per quella sola esecuzione)
uv run docanalyzer analyze doc.pdf --model llama3.2:3b
uv run docanalyzer analyze doc.pdf --backend anthropic --model claude-sonnet-5

uv run docanalyzer profiles
```

Il repository non include documenti di esempio: sono dati personali. Per
provarlo servono PDF tuoi, oppure si generano scansioni sintetiche (vedi sotto).

La configurazione sta tutta nel `.env` (prefisso `DOCANALYZER_`), non nel
codice: `config.py` dichiara i campi, i valori li mette il file.

```
DOCANALYZER_BACKEND=ollama          # ollama | anthropic | openai
DOCANALYZER_MODEL=gemma4:e4b        # vale per il backend scelto, qualunque sia
DOCANALYZER_MAX_INPUT_CHARS=60000
```

`DOCANALYZER_MODEL` è unico per tutti i backend: cambiando `BACKEND` va cambiato
anche il modello, o passato `--model` sulla singola esecuzione. I provider cloud
vogliono in più la propria chiave nell'ambiente — `ANTHROPIC_API_KEY` o
`OPENAI_API_KEY`, senza prefisso — e il rispettivo extra (`uv sync --extra
anthropic`). Con `OPENAI_BASE_URL` il backend `openai` parla anche a un server
locale (vLLM, LM Studio, llama.cpp).

## Servizio HTTP

L'analisi dura da decine di secondi a minuti: troppo per una richiesta sincrona,
che proxy e client HTTP tagliano prima. L'API non chiama mai la pipeline —
salva il file, scrive una riga in coda e risponde in millisecondi. Il lavoro lo
fa il worker, che è un altro processo.

Due programmi da avviare, in due terminali, che devono vedere lo **stesso**
`DATA_DIR` — è lì che stanno la coda e i file caricati, ed è l'unica cosa che
condividono:

```bash
export DOCANALYZER_DATA_DIR=./data

uv run uvicorn docanalyzer.api.app:app --port 8000   # API
uv run docanalyzer-worker                            # worker
```

### Come scorre un documento

```
  POST /jobs ──> [API] salva il file, INSERT in coda, risponde 202
                   │
            ┌──────▼──────┐
            │  jobs.db    │  pending → running → done | failed
            └──────┬──────┘
                   │ claim_next(): UPDATE atomico, un job alla volta
            ┌──────▼──────────────────────┐
            │ [worker]                    │
            │   └─ processo figlio ───────┼──> parsing (PyMuPDF → Docling)
            │      esegue analyze_file    │    └─> LLM (Ollama/Claude/OpenAI)
            └─────────────────────────────┘
                   │ finish(result) oppure fail(code, message)
  GET /jobs/{id} <─┘
```

1. `POST /jobs` valida **subito** profilo, parser e backend: un nome sbagliato è
   un 400 sulla richiesta, non un job fallito trenta secondi dopo. Il file viene
   scritto a blocchi da 1 MB sotto `DATA_DIR/uploads`, con un nome casuale — del
   nome originale si conserva solo il suffisso. Risposta: `202` con l'id.
2. Il worker preleva il job più vecchio in `pending` e lo marca `running` con un
   solo UPDATE condizionato, poi lo esegue in un processo figlio.
3. A fine corsa scrive il risultato (`AnalysisResult` serializzato) o l'errore
   con il suo codice, e passa al job successivo.
4. Il client fa polling su `GET /jobs/{id}` finché lo stato è `done` o `failed`.

Creare un job — il file va come multipart, tutto il resto sono campi form:

```bash
curl -X POST localhost:8000/jobs \
  -F file=@fattura.pdf \
  -F profile=invoice
```

```json
{
  "id": "a3f9c1e04b7d4f28b1c6e5a70d2f8c31",
  "status": "pending",
  "filename": "fattura.pdf",
  "profile": "invoice",
  "created_at": "2026-09-16T10:24:31+00:00",
  "started_at": null,
  "finished_at": null,
  "attempts": 0,
  "result": null,
  "error": null
}
```

La risposta arriva in millisecondi: nessuna analisi è ancora partita. Gli altri
campi sono opzionali e servono a scavalcare la configurazione per quel singolo
job; con `DOCANALYZER_API_KEY` impostata serve anche l'header:

```bash
curl -X POST localhost:8000/jobs \
  -H "X-API-Key: $DOCANALYZER_API_KEY" \
  -F file=@estratto.pdf \
  -F profile=bank_statement \
  -F backend=anthropic \
  -F model=claude-sonnet-5 \
  -F parser=docling            # forza l'OCR, disattiva il fallback
```

Poi si fa polling sull'id fino a `done` o `failed`:

```bash
ID=a3f9c1e04b7d4f28b1c6e5a70d2f8c31

curl -s localhost:8000/jobs/$ID | jq '{status, error}'
# {"status": "running", "error": null}

curl -s localhost:8000/jobs/$ID | jq '.result.data'
# { "document_type": "fattura", "total": {...}, "open_questions": [...] }
```

Per non copiare l'id a mano, in un comando solo:

```bash
ID=$(curl -s -X POST localhost:8000/jobs \
       -F file=@fattura.pdf -F profile=invoice | jq -r .id)

until curl -s localhost:8000/jobs/$ID | jq -e '.status | IN("done","failed")' >/dev/null; do
  sleep 2
done
curl -s localhost:8000/jobs/$ID | jq '{status, error, data: .result.data}'
```

Un fallimento ha la stessa forma, con l'errore al posto del risultato:

```bash
curl -s localhost:8000/jobs/$ID | jq '{status, error}'
# {
#   "status": "failed",
#   "error": {
#     "code": "unreadable_document",
#     "message": "scan.pdf: l'OCR ha prodotto testo troppo frammentario (12
#                 caratteri utili per pagina, soglia 100). La scansione è
#                 probabilmente storta, sfocata o a risoluzione insufficiente…"
#   }
# }
```

### Endpoint

```
POST   /jobs        multipart: file, profile, backend?, model?, parser?
                    → 202 {"id": "a3f…", "status": "pending"}
GET    /jobs/{id}   → {"status": "running"}
                    → {"status": "done",   "result": {…AnalysisResult…}}
                    → {"status": "failed", "error": {"code": "unreadable_document", …}}
GET    /jobs        elenco, filtrabile per stato
DELETE /jobs/{id}   cancella job e documento prima della scadenza
GET    /health      raggiungibilità del backend LLM + conteggi della coda
GET    /profiles
```

Lo stato `failed` porta sempre un `code` stabile (`unreadable_document`,
`ocr_unavailable`, `model_output_invalid`, `extraction_crashed`, `timeout`): è
quello su cui ramificare, il messaggio è per l'umano. `/docs` serve lo schema
OpenAPI completo.

### Quando qualcosa sembra fermo

```bash
curl -s localhost:8000/jobs | jq '.[] | {id, filename, status}'   # tutta la coda
curl -s localhost:8000/health | jq .queue                         # conteggi per stato
```

Un job che resta a lungo in `pending` con `running` a zero non è un'analisi
lenta: è il worker che non sta girando o che non vede lo stesso `DATA_DIR`
dell'API. `/health` risponde `503` anche quando il processo è vivo ma il backend
LLM non risponde — un healthcheck che dicesse solo "sono su" lascerebbe il
servizio in rotazione mentre ogni job fallisce.

**Due isolamenti, per due guai diversi.** L'API è separata dal worker, quindi
resta reattiva mentre gira un'analisi da tre minuti e si può riavviare senza
perdere il lavoro in coda. Il worker è a sua volta separato dall'estrazione, che
gira in un processo figlio: Docling va in segmentation fault su alcuni input, e
un SIGSEGV non è catturabile dentro il processo che muore. Con il figlio, il
crash diventa un job fallito con un codice (`extraction_crashed`) invece del
servizio giù. Il secondo crash sullo stesso documento lo chiude in modo
definitivo: un documento-veleno non deve girare in coda all'infinito.

**Un job alla volta per worker.** Con `num_ctx=32768` su 16 GB di RAM unificata
due analisi concorrenti vanno in swap o falliscono per OOM. La coda non serve
solo a disaccoppiare: è ciò che impedisce l'overload. Per alzare la concorrenza
si avviano più processi worker sullo stesso database — `claim_next` è un UPDATE
condizionato, due worker non prendono mai lo stesso job.

SQLite e non Celery/Redis perché il carico non lo richiede: un file invece di
due servizi da far girare e sorvegliare, con persistenza al riavvio inclusa.
L'interfaccia — prendi un job, aggiornane lo stato — è già quella di una coda
vera, quindi la sostituzione resta meccanica se un giorno servono più macchine.

Configurazione (stesso prefisso `DOCANALYZER_`, stesso `.env`; l'elenco
completo con le spiegazioni è in `.env.example`):

```
DOCANALYZER_DATA_DIR=./data            # database dei job + file caricati
DOCANALYZER_API_KEY=...                # header X-API-Key; vuota = nessun controllo
DOCANALYZER_MAX_UPLOAD_MB=50
DOCANALYZER_JOB_RETENTION_HOURS=24     # dopo quanto job e documenti spariscono
DOCANALYZER_MAX_ATTEMPTS=2
```

I documenti sono dati personali: la retention è esplicita, il worker la applica
da sé una volta l'ora e `DELETE /jobs/{id}` la anticipa.

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
  api/         Servizio HTTP (extra `api`), non usato da libreria e CLI
    store.py           coda dei job su SQLite
    worker.py          prelievo + processo figlio per l'estrazione
    app.py             FastAPI: accoda, non analizza
  errors.py    Gerarchia di eccezioni, un codice stabile per tipo di errore
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

La scelta del parser è automatica e vive nella pipeline, quindi vale sia per
`analyze` sia per i job dell'API: prova PyMuPDF e, se il PDF non ha un layer di
testo, passa a Docling. Un parser esplicito (`--parser`, o il campo `parser` nel
POST) disattiva il fallback.

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
- **Un'eccezione per tipo di errore** (`errors.py`). Da riga di comando un
  `RuntimeError` vale l'altro, da servizio no: "manca l'OCR" è un problema di
  deployment (503), "la scansione è illeggibile" è colpa del documento (422),
  "output non validabile" è colpa del modello (502). Solo il secondo dice
  all'utente di riacquisire la scansione.

## Limiti noti

- Il **profilo si sceglie a mano**: non c'è riconoscimento automatico
  dell'emittente.
- Il controllo dopo l'OCR misura la **quantità di testo, non la correttezza**: una
  scansione che produce molto testo con cifre sbagliate passa senza obiezioni.
- Il campo `currency` è una stringa libera e il modello ci mette spesso il simbolo
  (`$`) invece del codice ISO.
- I campi che richiedono **conteggi o somme** sono i meno affidabili.
- Docling va in **segmentation fault** su alcuni input. Da CLI il comando muore;
  come servizio il crash è confinato al processo figlio e diventa un job
  `failed` con codice `extraction_crashed`.
- Il risultato si recupera in **polling**: niente webhook né SSE.
- L'autenticazione è una **singola chiave condivisa**, senza utenti né quote: i
  job non sono separati per chiamante.

## Test

```bash
uv run pytest
```

I test usano un backend finto: verificano la pipeline, non la qualità del
modello. Girano anche senza `.env` — `conftest.py` popola le variabili prima
dell'import, così la suite non dipende da un file non versionato. `test_api.py` copre la coda (prelievo atomico, recupero dei job orfani,
retention) e il comportamento del worker davanti a un figlio che risponde, che
alza un'eccezione classificata o che muore di segfault.
