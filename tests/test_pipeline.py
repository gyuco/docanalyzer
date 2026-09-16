from pathlib import Path

import pytest

from docanalyzer.models import PageContent, ParsedDocument
from docanalyzer.profiles.core import GenericAnalysis
from docanalyzer import pipeline
from docanalyzer.pipeline import analyze_file, build_prompt
from docanalyzer.schema_utils import inline_refs


class FakeBackend:
    """Backend deterministico: isola la pipeline dal modello."""

    name = "fake"
    model = "fake-1"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.last_prompt: str | None = None
        self.last_schema: dict | None = None

    def complete_json(self, system, prompt, json_schema):
        self.last_prompt = prompt
        self.last_schema = json_schema
        return self.payload

    def health_check(self):
        return True, "ok"


@pytest.fixture
def sample_txt(tmp_path: Path) -> Path:
    path = tmp_path / "nota.txt"
    path.write_text("Fattura 42 del 2024-03-01. Totale 1.220,00 EUR.")
    return path


def _payload() -> dict:
    return {
        "document_type": "fattura",
        "language": "it",
        "summary": "Fattura numero 42.",
        "key_facts": ["Totale 1220 EUR"],
        "parties": [{"name": "Acme Srl", "tax_id": "IT01234567890"}],
        "dates": ["2024-03-01"],
        "amounts": [{"value": 1220.0, "currency": "EUR"}],
        "open_questions": [],
    }


def test_analyze_file_valida_e_traccia(sample_txt: Path) -> None:
    backend = FakeBackend(_payload())
    result = analyze_file(sample_txt, backend=backend)

    assert result.backend == "fake"
    assert result.parser == "text"
    assert result.truncated_input is False
    assert result.data["parties"][0]["tax_id"] == "IT01234567890"
    assert "Fattura 42" in (backend.last_prompt or "")


def test_output_non_conforme_solleva(sample_txt: Path) -> None:
    payload = _payload() | {"document_type": "non_esiste"}
    with pytest.raises(RuntimeError, match="non validabile"):
        analyze_file(sample_txt, backend=FakeBackend(payload))


def test_profilo_sconosciuto(sample_txt: Path) -> None:
    with pytest.raises(ValueError, match="Profilo sconosciuto"):
        analyze_file(sample_txt, profile="inesistente", backend=FakeBackend({}))


def test_prompt_tronca_conservando_testa_e_coda() -> None:
    document = ParsedDocument(
        source=Path("grande.txt"),
        parser="text",
        pages=[PageContent(number=1, text="A" * 500 + "B" * 500 + "C" * 500)],
    )
    prompt, truncated = build_prompt(document, max_chars=300)

    assert truncated is True
    assert "TESTO OMESSO" in prompt
    assert "A" in prompt and "C" in prompt


def _pdf_vuoto(tmp_path: Path) -> Path:
    """PDF con una pagina senza testo: indistinguibile da una scansione."""
    import pymupdf

    path = tmp_path / "vuoto.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


def test_scansione_senza_ocr_suggerisce_extra(tmp_path: Path, monkeypatch) -> None:
    # Senza l'extra installato non c'è fallback possibile: l'errore deve dire
    # come procurarselo.
    monkeypatch.setattr(pipeline, "_ocr_available", lambda: False)

    with pytest.raises(RuntimeError, match="uv sync --extra ocr"):
        analyze_file(_pdf_vuoto(tmp_path), backend=FakeBackend(_payload()))


def test_parser_esplicito_non_ricade_su_ocr(tmp_path: Path, monkeypatch) -> None:
    # Una scelta esplicita dell'utente va rispettata: se `--parser pymupdf` non
    # trova testo, il risultato è un errore, non un fallback silenzioso.
    chiamate: list[str] = []
    monkeypatch.setattr(
        pipeline, "_ocr_available", lambda: chiamate.append("ocr") or True
    )

    with pytest.raises(RuntimeError, match="non ha estratto testo utile"):
        analyze_file(
            _pdf_vuoto(tmp_path),
            backend=FakeBackend(_payload()),
            parser_name="pymupdf",
        )
    assert chiamate == []


def test_inline_refs_rimuove_defs() -> None:
    schema = inline_refs(GenericAnalysis.model_json_schema())
    dumped = repr(schema)

    assert "$defs" not in dumped
    assert "$ref" not in dumped
    # La definizione di Party deve essere stata copiata dentro l'array.
    assert schema["properties"]["parties"]["items"]["properties"]["name"]


def test_useful_chars_scarta_impalcatura() -> None:
    # Il markdown di Docling su una pagina non riconosciuta: segnaposto e bordi.
    rumore = "<!-- image -->\n\n| --- | --- |\n| ... | ... |\n<!-- image -->"

    assert pipeline.useful_chars(rumore) == 0
    assert pipeline.useful_chars("Totale 1.234,56 EUR") == len("Totale123456EUR")


def test_ocr_frammentario_e_un_errore(tmp_path: Path, monkeypatch) -> None:
    # Un OCR che riconosce solo briciole non deve arrivare al modello: produrrebbe
    # uno schema compilato e valido, indistinguibile da un'estrazione riuscita.
    briciole = ParsedDocument(
        source=tmp_path / "storta.pdf",
        parser="docling",
        pages=[PageContent(number=n, text="<!-- image -->\n\nPAGO") for n in (1, 2)],
        # Fa scattare il fallback: e il risultato dell'OCR che va respinto.
        likely_scanned=True,
    )
    monkeypatch.setattr(pipeline, "_ocr_available", lambda: True)
    monkeypatch.setattr(
        pipeline,
        "get_parser",
        lambda path, preferred=None: _ParserFinto(briciole),
    )

    with pytest.raises(RuntimeError, match="frammentario"):
        pipeline.parse_document(tmp_path / "storta.pdf")


class _ParserFinto:
    name = "finto"

    def __init__(self, document: ParsedDocument) -> None:
        self._document = document

    def supports(self, path: Path) -> bool:
        return True

    def parse(self, path: Path) -> ParsedDocument:
        return self._document


def test_registry_profili() -> None:
    from docanalyzer.profiles import available_profiles, get_profile
    from docanalyzer.profiles.core import InvoiceAnalysis

    # I profili specifici si registrano al solo import del package.
    assert {"generic", "invoice", "personal"} <= set(available_profiles())
    # Un profilo per emittente estende il tronco: eredita i campi comuni.
    assert issubclass(get_profile("personal"), InvoiceAnalysis)
    assert "total" in get_profile("personal").model_fields

    with pytest.raises(ValueError, match="Profilo sconosciuto"):
        get_profile("inesistente")
