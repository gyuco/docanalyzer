"""CLI: docanalyzer analyze / extract / doctor / profiles"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from docanalyzer.config import settings
from docanalyzer.llm import available_backends, get_backend
from docanalyzer.parsing import available_parsers
from docanalyzer.pipeline import analyze_file, parse_document
from docanalyzer.profiles import all_profiles, available_profiles

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

BackendOpt = Annotated[
    str | None, typer.Option("--backend", "-b", help=f"Uno di: {available_backends()}")
]
ModelOpt = Annotated[str | None, typer.Option("--model", "-m", help="Nome del modello")]
ParserOpt = Annotated[
    str | None, typer.Option("--parser", help="Forza un parser invece dell'automatico")
]


@app.command()
def analyze(
    path: Annotated[Path, typer.Argument(help="File da analizzare")],
    profile: Annotated[
        str, typer.Option("--profile", "-p", help="Schema di estrazione")
    ] = "generic",
    backend: BackendOpt = None,
    model: ModelOpt = None,
    parser: ParserOpt = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Salva il JSON su file")
    ] = None,
) -> None:
    """Analizza un documento e stampa il risultato strutturato."""
    llm = get_backend(backend, model)
    ok, message = llm.health_check()
    if not ok:
        console.print(f"[red]{message}[/red]")
        raise typer.Exit(1)

    with console.status(f"Analisi di {path.name} con {llm.name}/{llm.model}..."):
        try:
            result = analyze_file(path, profile=profile, backend=llm, parser_name=parser)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

    payload = result.model_dump(mode="json")
    if output:
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        console.print(f"[green]Scritto[/green] {output}")
    else:
        console.print(JSON.from_data(payload))

    if result.truncated_input:
        console.print("[yellow]Input troncato: analisi parziale.[/yellow]")
    questions = result.data.get("open_questions") or []
    if questions:
        console.print("\n[yellow]Da verificare a mano:[/yellow]")
        for question in questions:
            console.print(f"  • {question}")


@app.command()
def extract(
    path: Annotated[Path, typer.Argument(help="File da cui estrarre il testo")],
    parser: ParserOpt = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Estrae solo il testo, senza chiamare l'LLM. Utile per capire cosa vede il modello."""
    try:
        # Stesso percorso di `analyze`, fallback OCR incluso: questo comando
        # deve mostrare esattamente il testo che riceverà il modello.
        document = parse_document(path, parser)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if output:
        output.write_text(document.text)
        console.print(f"[green]Scritto[/green] {output}")
    else:
        console.print(document.text)

    console.print(
        f"\n[dim]parser={document.parser} pagine={len(document.pages)} "
        f"caratteri={document.char_count}[/dim]"
    )
    if document.likely_scanned:
        console.print("[yellow]Sembra una scansione: testo poco affidabile.[/yellow]")


@app.command()
def profiles() -> None:
    """Elenca i profili di estrazione e i loro campi."""
    table = Table("Profilo", "Campi")
    for name, schema_model in all_profiles().items():
        table.add_row(name, ", ".join(schema_model.model_fields))
    console.print(table)


@app.command()
def doctor(backend: BackendOpt = None, model: ModelOpt = None) -> None:
    """Verifica la configurazione: backend raggiungibile, modello presente."""
    console.print(f"backend configurato : {settings.backend}")
    console.print(f"modello configurato : {settings.model}")
    console.print(f"parser disponibili  : {', '.join(available_parsers())}")
    console.print(f"profili disponibili : {', '.join(available_profiles())}")

    try:
        llm = get_backend(backend, model)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    ok, message = llm.health_check()
    console.print(f"[{'green' if ok else 'red'}]{message}[/]")
    raise typer.Exit(0 if ok else 1)


if __name__ == "__main__":
    app()
