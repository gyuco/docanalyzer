"""Coda dei job su SQLite.

Una tabella in un file, nessun servizio in più da far girare. Regge senza
problemi il carico di un worker singolo, e dà persistenza gratis: al riavvio
della macchina i job in attesa sono ancora lì.

L'interfaccia — prendi un job, aggiornane lo stato — è la stessa di una coda
vera: se un giorno servono più macchine, la sostituzione è meccanica.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    filename      TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    profile       TEXT NOT NULL,
    backend       TEXT,
    model         TEXT,
    parser        TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    result_json   TEXT,
    error_code    TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT
);
-- Il worker cerca sempre "il più vecchio in pending": senza questo indice
-- diventa una scansione completa man mano che lo storico cresce.
CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs (status, created_at);
"""


@dataclass(slots=True)
class Job:
    id: str
    status: JobStatus
    filename: str
    stored_path: Path
    profile: str
    backend: str | None
    model: str | None
    parser: str | None
    attempts: int
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Job:
        return cls(
            id=row["id"],
            status=JobStatus(row["status"]),
            filename=row["filename"],
            stored_path=Path(row["stored_path"]),
            profile=row["profile"],
            backend=row["backend"],
            model=row["model"],
            parser=row["parser"],
            attempts=row["attempts"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    """Accesso alla coda. Una connessione per operazione: le operazioni sono
    brevi e rare, e così API e worker possono essere processi diversi senza
    condividere nulla se non il file."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL: il worker scrive mentre l'API legge, senza bloccarsi a vicenda.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Lato API
    # ------------------------------------------------------------------ #

    def enqueue(
        self,
        *,
        filename: str,
        stored_path: Path,
        profile: str,
        backend: str | None = None,
        model: str | None = None,
        parser: str | None = None,
    ) -> Job:
        job_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, status, filename, stored_path, profile, "
                "backend, model, parser, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    JobStatus.PENDING,
                    filename,
                    str(stored_path),
                    profile,
                    backend,
                    model,
                    parser,
                    _now(),
                ),
            )
        job = self.get(job_id)
        assert job is not None
        return job

    def get(self, job_id: str) -> Job | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.from_row(row) if row else None

    def list(self, *, status: JobStatus | None = None, limit: int = 50) -> list[Job]:
        query = "SELECT * FROM jobs"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [Job.from_row(r) for r in rows]

    def delete(self, job_id: str) -> Job | None:
        """Cancella il job e il file caricato. Il documento è dato personale:
        deve poter sparire su richiesta, non solo alla scadenza."""
        job = self.get(job_id)
        if job is None:
            return None
        job.stored_path.unlink(missing_ok=True)
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return job

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
            ).fetchall()
        return {s: 0 for s in JobStatus} | {r["status"]: r["n"] for r in rows}

    # ------------------------------------------------------------------ #
    # Lato worker
    # ------------------------------------------------------------------ #

    def claim_next(self) -> Job | None:
        """Prende atomicamente il job in attesa più vecchio e lo marca running.

        L'UPDATE condizionato è ciò che rende sicuro avere più worker: il
        secondo trova la riga già in `running` e non aggiorna nulla.
        """
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE jobs SET status = ?, started_at = ?, attempts = attempts + 1 "
                "WHERE id = (SELECT id FROM jobs WHERE status = ? "
                "            ORDER BY created_at LIMIT 1) "
                "RETURNING *",
                (JobStatus.RUNNING, _now(), JobStatus.PENDING),
            ).fetchone()
        return Job.from_row(row) if row else None

    def finish(self, job_id: str, result: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, finished_at = ? "
                "WHERE id = ?",
                (JobStatus.DONE, json.dumps(result, ensure_ascii=False), _now(), job_id),
            )

    def fail(self, job_id: str, code: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error_code = ?, error_message = ?, "
                "finished_at = ? WHERE id = ?",
                (JobStatus.FAILED, code, message, _now(), job_id),
            )

    def requeue(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, started_at = NULL WHERE id = ?",
                (JobStatus.PENDING, job_id),
            )

    def recover_orphans(self, max_attempts: int) -> int:
        """Rimette in coda i job lasciati in `running` da un worker morto.

        Da chiamare all'avvio del worker: se il processo è stato ucciso a metà
        analisi, quei job resterebbero altrimenti `running` per sempre. Quelli
        che hanno già esaurito i tentativi vengono chiusi come falliti: sono
        documenti che fanno morire l'estrazione, non vanno ripresi all'infinito.
        """
        with self._connect() as conn:
            failed = conn.execute(
                "UPDATE jobs SET status = ?, error_code = ?, error_message = ?, "
                "finished_at = ? WHERE status = ? AND attempts >= ?",
                (
                    JobStatus.FAILED,
                    "extraction_crashed",
                    "Il processo di estrazione è morto durante l'analisi.",
                    _now(),
                    JobStatus.RUNNING,
                    max_attempts,
                ),
            ).rowcount
            requeued = conn.execute(
                "UPDATE jobs SET status = ?, started_at = NULL WHERE status = ?",
                (JobStatus.PENDING, JobStatus.RUNNING),
            ).rowcount
        return failed + requeued

    def purge(self, retention_hours: int) -> int:
        """Cancella job conclusi e relativi file oltre la retention."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        ).isoformat(timespec="seconds")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, stored_path FROM jobs "
                "WHERE status IN (?, ?) AND finished_at < ?",
                (JobStatus.DONE, JobStatus.FAILED, cutoff),
            ).fetchall()
            for row in rows:
                Path(row["stored_path"]).unlink(missing_ok=True)
            if rows:
                conn.execute(
                    "DELETE FROM jobs WHERE id IN (%s)"
                    % ",".join("?" * len(rows)),
                    [r["id"] for r in rows],
                )
        return len(rows)
