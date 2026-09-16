"""Worker: preleva un job alla volta ed esegue l'analisi in un processo figlio.

I due isolamenti sono distinti e servono entrambi.

Worker separato dall'API: l'API resta reattiva mentre gira un'analisi da tre
minuti, e si può riavviare senza perdere il lavoro in corso.

Estrazione separata dal worker: Docling va in segmentation fault su alcuni
input. Un SIGSEGV non è un'eccezione Python, non si cattura dentro il processo
che muore — si osserva solo dal padre. Eseguendo `analyze_file` in un figlio,
il crash diventa *un job fallito con un messaggio* invece del servizio giù.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor
from pathlib import Path
from typing import Any

from docanalyzer.api.store import Job, JobStore
from docanalyzer.config import settings
from docanalyzer.errors import DocAnalyzerError, ExtractionCrashed

log = logging.getLogger("docanalyzer.worker")


def _analyze(
    path: str, profile: str, backend: str | None, model: str | None, parser: str | None
) -> dict[str, Any]:
    """Eseguito nel processo figlio.

    Deve stare a livello di modulo per essere pickleabile, e non deve
    restituire nulla di più complesso di tipi base: attraversa un confine di
    processo. Gli import pesanti (Docling, Ollama) avvengono qui, così il
    worker padre resta leggero.
    """
    from docanalyzer.llm import get_backend
    from docanalyzer.pipeline import analyze_file

    llm = get_backend(backend, model)
    result = analyze_file(Path(path), profile=profile, backend=llm, parser_name=parser)
    return result.model_dump(mode="json")


class Worker:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self._pool: ProcessPoolExecutor | None = None
        self._running = True
        self._last_purge = 0.0

    # ------------------------------------------------------------------ #

    # Un job alla volta per worker: con num_ctx=32768 su 16 GB di RAM
    # unificata, due analisi concorrenti vanno in swap o falliscono per OOM.
    # Per aumentare la concorrenza si avviano più processi worker sullo stesso
    # database — `claim_next` è atomico, non si contendono lo stesso job.
    def _get_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1)
        return self._pool

    def _reset_pool(self) -> None:
        """Dopo un crash del figlio il pool è inutilizzabile: va ricreato.

        `cancel_futures` evita di restare appesi su un executor già rotto.
        """
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
        self._pool = None

    # ------------------------------------------------------------------ #

    def run_job(self, job: Job) -> None:
        log.info("job %s: analisi di %s (profilo=%s)", job.id, job.filename, job.profile)
        future = self._get_pool().submit(
            _analyze,
            str(job.stored_path),
            job.profile,
            job.backend,
            job.model,
            job.parser,
        )
        try:
            result = future.result(timeout=settings.request_timeout + 120)
        except BrokenExecutor:
            # Il figlio è morto senza alzare nulla: segfault, OOM, kill.
            self._reset_pool()
            if job.attempts >= settings.max_attempts:
                self.store.fail(
                    job.id,
                    ExtractionCrashed.code,
                    f"{job.filename}: l'estrazione è terminata in modo anomalo "
                    f"dopo {job.attempts} tentativi. Il documento fa crashare "
                    "il parser: provare con --parser pymupdf o riacquisirlo.",
                )
                log.error("job %s: crash definitivo", job.id)
            else:
                # Un crash può essere transitorio (memoria occupata da un'altra
                # analisi): un secondo tentativo vale la pena, ma uno solo.
                self.store.requeue(job.id)
                log.warning("job %s: crash, rimesso in coda", job.id)
        except TimeoutError:
            self._reset_pool()
            self.store.fail(
                job.id, "timeout", f"{job.filename}: analisi oltre il tempo massimo."
            )
            log.error("job %s: timeout", job.id)
        except DocAnalyzerError as exc:
            # Errore atteso e classificato: OCR mancante, scansione illeggibile,
            # output del modello non validabile. Il codice arriva al client.
            self.store.fail(job.id, exc.code, str(exc))
            log.info("job %s: fallito (%s)", job.id, exc.code)
        except Exception as exc:  # noqa: BLE001 - la coda non deve mai morire
            self.store.fail(job.id, "internal_error", f"{type(exc).__name__}: {exc}")
            log.exception("job %s: errore non previsto", job.id)
        else:
            self.store.finish(job.id, result)
            log.info("job %s: completato in %ss", job.id, result.get("elapsed_seconds"))

    # ------------------------------------------------------------------ #

    def _maybe_purge(self) -> None:
        """Retention: gira una volta l'ora, non serve un cron a parte."""
        if time.monotonic() - self._last_purge < 3600:
            return
        self._last_purge = time.monotonic()
        removed = self.store.purge(settings.job_retention_hours)
        if removed:
            log.info("retention: rimossi %d job conclusi", removed)

    def stop(self, *_: object) -> None:
        log.info("arresto richiesto: termino il job in corso e esco")
        self._running = False

    def run(self) -> None:
        recovered = self.store.recover_orphans(settings.max_attempts)
        if recovered:
            log.info("recupero: %d job orfani di un worker precedente", recovered)

        log.info("worker avviato (pid %d), coda %s", os.getpid(), self.store.db_path)
        while self._running:
            self._maybe_purge()
            job = self.store.claim_next()
            if job is None:
                time.sleep(settings.worker_poll_seconds)
                continue
            self.run_job(job)
        self._reset_pool()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    worker = Worker(JobStore(settings.data_dir / "jobs.db"))
    # SIGTERM è il segnale di Docker e systemd allo stop: uscire in modo
    # pulito evita di lasciare un job in `running` da recuperare al riavvio.
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()


if __name__ == "__main__":
    main()
