"""API HTTP a job.

Gli handler non chiamano mai `analyze_file`: scrivono una riga nella coda e
rispondono in millisecondi. Un'analisi dura da decine di secondi a minuti,
mentre proxy e client HTTP tagliano la connessione ben prima — il risultato
verrebbe calcolato e buttato via.

    POST /jobs        → 202 {id, status: pending}
    GET  /jobs/{id}   → pending | running | done + result | failed + error
"""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from docanalyzer.api.store import Job, JobStatus, JobStore
from docanalyzer.config import settings
from docanalyzer.errors import DocAnalyzerError
from docanalyzer.llm import available_backends, get_backend
from docanalyzer.parsing import available_parsers
from docanalyzer.profiles import all_profiles, available_profiles, get_profile

# Come l'errore classificato diventa uno status code. La pipeline distingue già
# fra colpa del documento (422), dell'ambiente (503) e del modello (502): qui
# la distinzione si limita ad attraversare HTTP.
STATUS_BY_CODE = {
    "unknown_profile": 400,
    "unknown_parser": 400,
    "unknown_backend": 400,
    "unsupported_format": 415,
    "document_not_found": 404,
    "unreadable_document": 422,
    "model_output_invalid": 502,
    "ocr_unavailable": 503,
    "backend_unavailable": 503,
}

CHUNK = 1 << 20


# --------------------------------------------------------------------------- #
# Schemi di risposta
# --------------------------------------------------------------------------- #


class JobError(BaseModel):
    code: str
    message: str


class JobView(BaseModel):
    id: str
    status: JobStatus
    filename: str
    profile: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    attempts: int
    result: dict[str, Any] | None = None
    error: JobError | None = None

    @classmethod
    def of(cls, job: Job) -> JobView:
        return cls(
            id=job.id,
            status=job.status,
            filename=job.filename,
            profile=job.profile,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            attempts=job.attempts,
            result=job.result,
            error=(
                JobError(code=job.error_code, message=job.error_message or "")
                if job.error_code
                else None
            ),
        )


# --------------------------------------------------------------------------- #
# Applicazione
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="docanalyzer",
    description="Analisi di documenti con backend LLM intercambiabili.",
    version="0.1.0",
)

_store: JobStore | None = None


def get_store() -> JobStore:
    global _store
    if _store is None:
        _store = JobStore(settings.data_dir / "jobs.db")
    return _store


StoreDep = Annotated[JobStore, Depends(get_store)]


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Auth minima a chiave condivisa.

    `DOCANALYZER_API_KEY` non impostata disattiva il controllo: comodo in
    sviluppo, da impostare ovunque il servizio sia raggiungibile da altri.
    Il confronto è a tempo costante: un `==` su stringhe esce al primo byte
    diverso e regala la chiave a chi misura i tempi di risposta.
    """
    expected = settings.api_key
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Chiave API mancante o non valida.")


Auth = Depends(require_api_key)


@app.exception_handler(DocAnalyzerError)
async def _docanalyzer_error(_, exc: DocAnalyzerError) -> JSONResponse:
    return JSONResponse(
        status_code=STATUS_BY_CODE.get(exc.code, 500),
        content={"error": {"code": exc.code, "message": str(exc)}},
    )


# --------------------------------------------------------------------------- #
# Job
# --------------------------------------------------------------------------- #


@app.post("/jobs", status_code=202, response_model=JobView, dependencies=[Auth])
async def submit_job(
    store: StoreDep,
    file: Annotated[UploadFile, File(description="Documento da analizzare")],
    profile: Annotated[str, Form()] = "generic",
    backend: Annotated[str | None, Form()] = None,
    model: Annotated[str | None, Form()] = None,
    parser: Annotated[str | None, Form()] = None,
) -> JobView:
    """Accoda un documento. Ritorna subito: il risultato si legge da GET /jobs/{id}."""
    # Validare profilo e parser adesso, non nel worker: un profilo inesistente
    # è un errore del chiamante e deve tornare 400 sulla richiesta che lo
    # contiene, non come job fallito trenta secondi dopo.
    get_profile(profile)
    if parser and parser not in available_parsers():
        raise HTTPException(400, f"Parser sconosciuto: {parser!r}")
    if backend and backend not in available_backends():
        raise HTTPException(400, f"Backend sconosciuto: {backend!r}")

    if not file.filename:
        raise HTTPException(400, "File senza nome.")
    # Solo il suffisso: il nome arriva dal client, e un `../` al suo interno
    # scriverebbe fuori dalla directory degli upload.
    suffix = Path(file.filename).suffix[:16]
    uploads = settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    stored = uploads / f"{secrets.token_hex(16)}{suffix}"
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    # A blocchi, non `await file.read()`: un upload da 2 GB non deve poter
    # riempire la RAM del processo API prima che il limite lo fermi.
    with stored.open("wb") as out:
        while chunk := await file.read(CHUNK):
            written += len(chunk)
            if written > limit:
                out.close()
                stored.unlink(missing_ok=True)
                raise HTTPException(413, f"File oltre {settings.max_upload_mb} MB.")
            out.write(chunk)
    if written == 0:
        stored.unlink(missing_ok=True)
        raise HTTPException(400, "File vuoto.")

    job = store.enqueue(
        filename=file.filename,
        stored_path=stored,
        profile=profile,
        backend=backend,
        model=model,
        parser=parser,
    )
    return JobView.of(job)


@app.get("/jobs", response_model=list[JobView], dependencies=[Auth])
def list_jobs(
    store: StoreDep, status: JobStatus | None = None, limit: int = 50
) -> list[JobView]:
    return [JobView.of(j) for j in store.list(status=status, limit=min(limit, 200))]


@app.get("/jobs/{job_id}", response_model=JobView, dependencies=[Auth])
def get_job(store: StoreDep, job_id: str) -> JobView:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job inesistente o già scaduto.")
    return JobView.of(job)


@app.delete("/jobs/{job_id}", status_code=204, dependencies=[Auth])
def delete_job(store: StoreDep, job_id: str) -> None:
    """Cancella job e documento caricato prima della scadenza naturale."""
    if store.delete(job_id) is None:
        raise HTTPException(404, "Job inesistente o già scaduto.")


# --------------------------------------------------------------------------- #
# Introspezione
# --------------------------------------------------------------------------- #


@app.get("/profiles", dependencies=[Auth])
def profiles() -> dict[str, list[str]]:
    return {name: list(m.model_fields) for name, m in all_profiles().items()}


@app.get("/health")
def health(store: StoreDep) -> JSONResponse:
    """`doctor` in forma HTTP: dice se il backend LLM è davvero raggiungibile.

    Un healthcheck che risponde solo "il processo è vivo" lascia il servizio
    in rotazione mentre ogni job fallisce perché Ollama non risponde.
    """
    try:
        llm = get_backend()
        llm_ok, llm_message = llm.health_check()
        llm_info = {"backend": llm.name, "model": llm.model, "message": llm_message}
    except Exception as exc:  # noqa: BLE001 - l'healthcheck non deve mai alzare
        llm_ok, llm_info = False, {"message": f"{type(exc).__name__}: {exc}"}

    queue = store.counts()
    return JSONResponse(
        status_code=200 if llm_ok else 503,
        content={
            "status": "ok" if llm_ok else "degraded",
            "llm": llm_info | {"ok": llm_ok},
            "queue": queue,
            "profiles": available_profiles(),
            "parsers": available_parsers(),
        },
    )
