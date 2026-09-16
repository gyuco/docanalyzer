"""Protocollo dei profili e registry per selezione in base al nome.

Stessa forma del registry dei parser (`parsing/base.py`): ogni profilo vive nel
suo file e si registra all'import, così aggiungerne uno non tocca nulla di
esistente.
"""

from __future__ import annotations

from pydantic import BaseModel

_REGISTRY: dict[str, type[BaseModel]] = {}


def register(name: str, schema: type[BaseModel]) -> type[BaseModel]:
    if name in _REGISTRY:
        raise ValueError(f"Profilo già registrato: {name!r}")
    _REGISTRY[name] = schema
    return schema


def get_profile(name: str) -> type[BaseModel]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Profilo sconosciuto: {name!r}. Disponibili: {available_profiles()}"
        ) from None


def available_profiles() -> list[str]:
    return sorted(_REGISTRY)


def all_profiles() -> dict[str, type[BaseModel]]:
    """Copia del registry, per i comandi che devono elencarli tutti."""
    return dict(_REGISTRY)
