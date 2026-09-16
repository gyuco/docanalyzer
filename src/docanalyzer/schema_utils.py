"""Utilità sugli JSON Schema generati da Pydantic."""

from __future__ import annotations

import copy
from typing import Any


def inline_refs(schema: dict) -> dict:
    """Sostituisce ogni `$ref` con la definizione puntata e rimuove `$defs`.

    Serve perché i motori di constrained decoding (llama.cpp dietro Ollama,
    e diversi endpoint OpenAI-compatibili) gestiscono i riferimenti in modo
    incoerente: uno schema autocontenuto elimina la classe di problemi.
    Gli schemi ricorsivi non sono supportati — nessuno dei nostri lo è.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any, seen: frozenset[str]) -> Any:
        if isinstance(node, list):
            return [resolve(item, seen) for item in node]
        if not isinstance(node, dict):
            return node

        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            key = ref.removeprefix("#/$defs/")
            if key in seen:
                raise ValueError(f"Schema ricorsivo non supportato: {key}")
            if key not in defs:
                return node
            resolved = resolve(copy.deepcopy(defs[key]), seen | {key})
            # Un sibling di $ref (es. "description") ha la precedenza.
            extras = {k: v for k, v in node.items() if k != "$ref"}
            return {**resolved, **extras}

        return {k: resolve(v, seen) for k, v in node.items() if k != "$defs"}

    return resolve(copy.deepcopy(schema), frozenset())


def require_all_properties(schema: dict) -> dict:
    """Marca come `required` ogni proprietà di ogni oggetto dello schema.

    I motori di constrained decoding sono liberi di OMETTERE le chiavi non
    richieste: un modello piccolo prende sistematicamente quella scorciatoia e
    restituisce oggetti quasi vuoti (`seller`, `buyer`, `line_items` mancanti
    anche quando il documento li contiene). Rendendo obbligatoria ogni chiave
    il decoder è costretto a emetterla e il modello a cercarne il valore;
    l'opzionalità resta espressa dal `null` ammesso nell'`anyOf`, quindi la
    validazione Pydantic non cambia.
    """

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {k: walk(v) for k, v in node.items()}
        if out.get("type") == "object" and isinstance(out.get("properties"), dict):
            out["required"] = list(out["properties"])
        return out

    return walk(copy.deepcopy(schema))
