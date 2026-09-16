"""Orchestrazione: file -> parsing -> prompt -> LLM -> risultato validato."""

from __future__ import annotations

import re
import time
from pathlib import Path

from pydantic import ValidationError

from docanalyzer.config import settings
from docanalyzer.errors import (
    DocumentNotFound,
    ModelOutputInvalid,
    OCRUnavailable,
    UnreadableDocument,
)
from docanalyzer.llm import LLMBackend, get_backend
from docanalyzer.models import AnalysisResult, ParsedDocument
from docanalyzer.parsing import get_parser
from docanalyzer.profiles import available_profiles, get_profile
from docanalyzer.parsing.base import SCANNED_CHARS_PER_PAGE
from docanalyzer.schema_utils import inline_refs, require_all_properties

SYSTEM_PROMPT = """Sei un analista documentale. Estrai informazioni da documenti \
aziendali, bancari e fiscali in qualsiasi lingua.

Regole non negoziabili:
- Riporta solo ciò che è scritto nel documento. Non dedurre, non completare, non stimare.
- Se un campo non è presente o non è leggibile, lascialo nullo o vuoto.
- I codici (P.IVA, codice fiscale, IBAN, numero fattura) vanno riportati esattamente come sono scritti, senza spazi o riformattazioni.
- ATTENZIONE ai numeri: in molti documenti europei il punto è il separatore delle MIGLIAIA e la virgola quella dei decimali. "2.750,00" vale duemilasettecentocinquanta (2750.0), non 2.75. "1.220,50" vale 1220.5. Converti sempre in float con il punto decimale, ragionando sull'ordine di grandezza plausibile.
- Le percentuali di imposta non sono importi: nel campo dell'imposta va il valore in valuta (es. 605.00), non l'aliquota (0.22).
- Le date vanno normalizzate in formato ISO (AAAA-MM-GG); se la data è ambigua \
(es. 03/04/2024 senza contesto di formato), lasciala nulla e segnalala in open_questions.
- Ogni voce di dettaglio va con il suo importo: se accanto alla descrizione c'è un numero, quello è il totale della riga.
- Usa open_questions per tutto ciò che un revisore umano deve verificare: campi \
ambigui, testo illeggibile, incoerenze fra totali e voci di dettaglio.
- Il riassunto va scritto nella lingua principale del documento."""


def build_prompt(document: ParsedDocument, max_chars: int) -> tuple[str, bool]:
    text = document.text
    truncated = len(text) > max_chars
    if truncated:
        # Testa e coda: intestazioni e totali sono i punti più informativi
        # e stanno agli estremi nella quasi totalità dei documenti contabili.
        head = max_chars * 2 // 3
        tail = max_chars - head
        text = f"{text[:head]}\n\n[...TESTO OMESSO...]\n\n{text[-tail:]}"

    header = [f"File: {document.source.name}", f"Pagine: {len(document.pages)}"]
    if document.metadata.get("title"):
        header.append(f"Titolo: {document.metadata['title']}")
    if truncated:
        header.append(
            "ATTENZIONE: il documento è stato troncato. Segnala in open_questions "
            "che l'analisi è parziale."
        )

    return (
        "\n".join(header) + "\n\n--- CONTENUTO DEL DOCUMENTO ---\n" + text,
        truncated,
    )


# Parser a cui ricadere quando il parser veloce non trova testo.
OCR_PARSER = "docling"

# Un OCR che gira ma non riconosce nulla restituisce comunque qualcosa: bordi di
# tabella, segnaposto di immagine, frammenti isolati. Sotto questa densità di
# caratteri veri per pagina il risultato non è un documento, è rumore.
OCR_MIN_USEFUL_CHARS_PER_PAGE = SCANNED_CHARS_PER_PAGE

_IMAGE_PLACEHOLDER = re.compile(r"<!--.*?-->", re.S)
_LAYOUT_NOISE = re.compile(r"[|\-:_.\s]+")
_NOT_ALNUM = re.compile(r"[^0-9A-Za-zÀ-ÿ]")


def useful_chars(text: str) -> int:
    """Caratteri che trasportano informazione, scartando l'impalcatura.

    Il markdown di Docling è pieno di `<!-- image -->` e di bordi di tabella:
    contarli come testo maschera un OCR fallito, che è esattamente il caso da
    riconoscere.
    """
    text = _IMAGE_PLACEHOLDER.sub(" ", text)
    text = _LAYOUT_NOISE.sub(" ", text)
    return len(_NOT_ALNUM.sub("", text))


def _ocr_available() -> bool:
    """True se l'extra OCR è installato. L'import di Docling costa secondi,
    quindi si verifica solo la presenza del modulo, senza caricarlo."""
    from importlib.util import find_spec

    return find_spec("docling") is not None


def parse_document(path: Path, parser_name: str | None = None) -> ParsedDocument:
    """Estrae il testo, passando all'OCR se il documento è una scansione.

    La selezione dei parser avviene per estensione, ma fra PyMuPDF e Docling
    non decide il formato: decide il *contenuto*, cioè se il PDF ha un layer di
    testo. È un'informazione che esiste solo dopo aver provato a leggerlo, per
    questo il fallback vive qui e non in `supports()`.

    Un `parser_name` esplicito è una scelta dell'utente e viene rispettato:
    nessun fallback, così `--parser pymupdf` resta un modo per vedere cosa
    estrae davvero il parser veloce.
    """
    document = get_parser(path, preferred=parser_name).parse(path)
    if not document.likely_scanned and document.text.strip():
        return document

    if parser_name:
        raise UnreadableDocument(
            f"{path.name}: il parser {parser_name!r} non ha estratto testo utile."
        )
    if not _ocr_available():
        raise OCRUnavailable(
            f"{path.name}: nessun testo estraibile, è probabilmente una scansione. "
            "Serve l'OCR: installa l'extra con `uv sync --extra ocr` e riprova."
        )

    document = get_parser(path, preferred=OCR_PARSER).parse(path)
    pages = max(len(document.pages), 1)
    density = useful_chars(document.text) // pages
    if density < OCR_MIN_USEFUL_CHARS_PER_PAGE:
        # Meglio un errore che un'analisi dall'aria plausibile costruita su
        # frammenti: il modello riempirebbe lo schema comunque, e a valle nulla
        # distinguerebbe il risultato da un'estrazione riuscita.
        raise UnreadableDocument(
            f"{path.name}: l'OCR ha prodotto testo troppo frammentario "
            f"({density} caratteri utili per pagina, soglia "
            f"{OCR_MIN_USEFUL_CHARS_PER_PAGE}). La scansione è probabilmente "
            "storta, sfocata o a risoluzione insufficiente: raddrizzala e "
            "riacquisiscila a 200-300 dpi."
        )
    return document


def analyze_file(
    path: Path,
    profile: str = "generic",
    backend: LLMBackend | None = None,
    parser_name: str | None = None,
) -> AnalysisResult:
    schema_model = get_profile(profile)
    if not path.is_file():
        raise DocumentNotFound(str(path))

    llm = backend or get_backend()

    document = parse_document(path, parser_name)

    prompt, truncated = build_prompt(document, settings.max_input_chars)
    json_schema = require_all_properties(
        inline_refs(schema_model.model_json_schema())
    )

    started = time.perf_counter()
    raw = llm.complete_json(SYSTEM_PROMPT, prompt, json_schema)
    elapsed = time.perf_counter() - started

    try:
        validated = schema_model.model_validate(raw)
    except ValidationError as exc:
        # L'output è vincolato allo schema, quindi qui finiscono solo gli errori
        # semantici (date impossibili, enum fuori dominio). Meglio farli emergere
        # con il payload grezzo che tentare riparazioni automatiche silenziose.
        raise ModelOutputInvalid(
            f"Output del modello non validabile: {exc}\nPayload: {raw}"
        ) from exc

    return AnalysisResult(
        source=path,
        profile=profile,
        backend=llm.name,
        model=llm.model,
        parser=document.parser,
        data=validated.model_dump(mode="json"),
        elapsed_seconds=round(elapsed, 2),
        truncated_input=truncated,
    )
