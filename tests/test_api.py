"""Test del servizio: coda, ciclo di vita del job, isolamento del crash.

Come i test della pipeline, non verificano la qualità del modello: l'analisi
vera è sostituita da una funzione finta.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from docanalyzer.api.store import JobStatus, JobStore
from docanalyzer.api.worker import Worker
from docanalyzer.errors import UnreadableDocument


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def _enqueue(store: JobStore, tmp_path: Path, name: str = "f.pdf"):
    doc = tmp_path / name
    doc.write_bytes(b"%PDF-1.4 finto")
    return store.enqueue(filename=name, stored_path=doc, profile="generic")


# --------------------------------------------------------------------------- #
# Coda
# --------------------------------------------------------------------------- #


def test_claim_next_e_atomico(store: JobStore, tmp_path: Path) -> None:
    job = _enqueue(store, tmp_path)
    claimed = store.claim_next()
    assert claimed is not None and claimed.id == job.id
    assert claimed.status is JobStatus.RUNNING
    # Un secondo worker non deve poter prendere lo stesso job.
    assert store.claim_next() is None


def test_ordine_fifo(store: JobStore, tmp_path: Path) -> None:
    first = _enqueue(store, tmp_path, "a.pdf")
    _enqueue(store, tmp_path, "b.pdf")
    assert store.claim_next().id == first.id


def test_orfani_rimessi_in_coda(store: JobStore, tmp_path: Path) -> None:
    """Un worker ucciso a metà analisi lascia il job in `running`: al riavvio
    va ripreso, non abbandonato."""
    job = _enqueue(store, tmp_path)
    store.claim_next()
    assert store.recover_orphans(max_attempts=2) == 1
    assert store.get(job.id).status is JobStatus.PENDING


def test_documento_veleno_non_gira_allinfinito(store: JobStore, tmp_path: Path) -> None:
    job = _enqueue(store, tmp_path)
    for _ in range(2):
        store.claim_next()
        store.recover_orphans(max_attempts=2)
    reloaded = store.get(job.id)
    assert reloaded.status is JobStatus.FAILED
    assert reloaded.error_code == "extraction_crashed"


def test_delete_rimuove_anche_il_file(store: JobStore, tmp_path: Path) -> None:
    job = _enqueue(store, tmp_path)
    assert job.stored_path.exists()
    store.delete(job.id)
    assert not job.stored_path.exists()
    assert store.get(job.id) is None


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #


class _FakePool:
    """Sostituisce il ProcessPoolExecutor: il comportamento da verificare è
    quello del worker davanti a un figlio che risponde, alza o muore."""

    def __init__(self, outcome) -> None:
        self.outcome = outcome

    def submit(self, *_args, **_kwargs):
        outcome = self.outcome

        class _Future:
            def result(self, timeout=None):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        return _Future()

    def shutdown(self, **_kwargs) -> None:
        pass


def _worker_with(store: JobStore, outcome) -> Worker:
    worker = Worker(store)
    worker._pool = _FakePool(outcome)
    return worker


def test_job_completato(store: JobStore, tmp_path: Path) -> None:
    payload = {"profile": "generic", "elapsed_seconds": 1.0, "data": {"summary": "ok"}}
    worker = _worker_with(store, payload)
    job = _enqueue(store, tmp_path)
    worker.run_job(store.claim_next())

    done = store.get(job.id)
    assert done.status is JobStatus.DONE
    assert done.result == payload


def test_errore_classificato_arriva_al_client(store: JobStore, tmp_path: Path) -> None:
    worker = _worker_with(store, UnreadableDocument("scansione storta"))
    job = _enqueue(store, tmp_path)
    worker.run_job(store.claim_next())

    failed = store.get(job.id)
    assert failed.status is JobStatus.FAILED
    # Il codice, non il testo: è quello su cui il chiamante può ramificare.
    assert failed.error_code == "unreadable_document"


def test_crash_del_figlio_non_uccide_il_worker(store: JobStore, tmp_path: Path) -> None:
    """Il caso per cui esiste l'isolamento: segfault di Docling."""
    from concurrent.futures import BrokenExecutor

    worker = _worker_with(store, BrokenExecutor("segfault"))
    job = _enqueue(store, tmp_path)
    worker.run_job(store.claim_next())

    # Primo crash: si riprova una volta.
    assert store.get(job.id).status is JobStatus.PENDING
    worker._pool = _FakePool(BrokenExecutor("segfault"))
    worker.run_job(store.claim_next())
    # Secondo: fallisce in modo esplicito, il worker è ancora vivo.
    assert store.get(job.id).error_code == "extraction_crashed"


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fastapi = pytest.importorskip("fastapi", reason="serve l'extra `api`")
    from fastapi.testclient import TestClient

    from docanalyzer.api import app as app_module
    from docanalyzer.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(app_module, "_store", JobStore(tmp_path / "jobs.db"))
    return TestClient(app_module.app)


def test_submit_risponde_subito_con_202(client) -> None:
    response = client.post(
        "/jobs",
        files={"file": ("fattura.pdf", io.BytesIO(b"%PDF-1.4 finto"), "application/pdf")},
        data={"profile": "invoice"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    # Nessuna analisi è partita: l'handler ha solo scritto in coda.
    assert body["result"] is None


def test_profilo_inesistente_fallisce_subito(client) -> None:
    """400 sulla richiesta, non job fallito trenta secondi dopo."""
    response = client.post(
        "/jobs",
        files={"file": ("f.pdf", io.BytesIO(b"x"), "application/pdf")},
        data={"profile": "inesistente"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_profile"


def test_upload_oltre_il_limite(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from docanalyzer.config import settings

    monkeypatch.setattr(settings, "max_upload_mb", 0)
    response = client.post(
        "/jobs", files={"file": ("f.pdf", io.BytesIO(b"x" * 1024), "application/pdf")}
    )
    assert response.status_code == 413


def test_polling_del_risultato(client) -> None:
    job_id = client.post(
        "/jobs", files={"file": ("f.pdf", io.BytesIO(b"x"), "application/pdf")}
    ).json()["id"]

    from docanalyzer.api import app as app_module

    app_module._store.claim_next()
    app_module._store.finish(job_id, {"data": {"summary": "fatto"}})

    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "done"
    assert body["result"]["data"]["summary"] == "fatto"


def test_job_scaduto(client) -> None:
    assert client.get("/jobs/inesistente").status_code == 404


def test_api_key(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from docanalyzer.config import settings

    monkeypatch.setattr(settings, "api_key", "segreto")
    assert client.get("/jobs").status_code == 401
    assert client.get("/jobs", headers={"X-API-Key": "segreto"}).status_code == 200
