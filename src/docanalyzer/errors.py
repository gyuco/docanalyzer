"""Gerarchia di eccezioni della pipeline.

Da riga di comando un `RuntimeError` vale l'altro: si stampa il messaggio e si
esce con 1. Da servizio no. "L'OCR non è installato" è un problema di
deployment, "la scansione è illeggibile" è colpa del documento, "il modello ha
prodotto output non validabile" è colpa del modello: tre cose che il chiamante
deve poter distinguere senza leggere il testo dell'errore, perché solo la
seconda gli dice di riacquisire la scansione.

Ogni classe eredita anche dall'eccezione builtin che sostituisce, così il
`except (RuntimeError, ValueError, FileNotFoundError)` della CLI continua a
funzionare invariato.
"""

from __future__ import annotations


class DocAnalyzerError(Exception):
    """Radice comune. `code` è la forma stabile dell'errore: è quella che
    finisce nella risposta HTTP, mentre il messaggio resta leggibile e libero
    di cambiare."""

    code = "error"


# --------------------------------------------------------------------------- #
# Richiesta malformata: il chiamante ha chiesto qualcosa che non esiste
# --------------------------------------------------------------------------- #


class UnknownProfile(DocAnalyzerError, ValueError):
    code = "unknown_profile"


class UnknownParser(DocAnalyzerError, ValueError):
    code = "unknown_parser"


class UnknownBackend(DocAnalyzerError, ValueError):
    code = "unknown_backend"


class UnsupportedFormat(DocAnalyzerError, ValueError):
    """Nessun parser registrato per questa estensione."""

    code = "unsupported_format"


class DocumentNotFound(DocAnalyzerError, FileNotFoundError):
    code = "document_not_found"


# --------------------------------------------------------------------------- #
# Colpa del documento: rimediabile solo riacquisendolo
# --------------------------------------------------------------------------- #


class UnreadableDocument(DocAnalyzerError, RuntimeError):
    """Il testo estratto non è abbastanza per un'analisi sensata: scansione
    storta, sfocata o a risoluzione insufficiente."""

    code = "unreadable_document"


# --------------------------------------------------------------------------- #
# Colpa dell'ambiente: il documento andrebbe bene, manca un pezzo del servizio
# --------------------------------------------------------------------------- #


class OCRUnavailable(DocAnalyzerError, RuntimeError):
    """Serve l'OCR ma l'extra non è installato."""

    code = "ocr_unavailable"


class BackendUnavailable(DocAnalyzerError, RuntimeError):
    """Il backend LLM non risponde o non ha il modello richiesto."""

    code = "backend_unavailable"


# --------------------------------------------------------------------------- #
# Colpa del modello
# --------------------------------------------------------------------------- #


class ModelOutputInvalid(DocAnalyzerError, RuntimeError):
    """L'output è conforme allo schema come forma ma non come contenuto:
    date impossibili, enum fuori dominio."""

    code = "model_output_invalid"


class ExtractionCrashed(DocAnalyzerError, RuntimeError):
    """Il processo di estrazione è morto senza alzare un'eccezione: segfault
    del parser, OOM, kill esterno. Non è catturabile dentro il processo che
    muore, solo dal padre che lo sorveglia."""

    code = "extraction_crashed"
