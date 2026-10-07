"""Procedencia de las etiquetas de ``eval/etiquetas.csv`` (E1-07b): ``humano`` o ``asistente_provisional`` (D-101).

Las etiquetas «provisionales» las propuso un agente y las aprobó **provisionalmente el asistente**, no una persona (decisión
D-101, pendiente de la revisión humana C-09). Como el agente que propuso la etiqueta y el que la aprobó son del mismo tipo
que el clasificador que se mide, hay **riesgo de circularidad**: por eso todo lector del CSV usa solo las humanas, salvo que
el llamador pida las otras de forma explícita (``origenes=``). Un valor desconocido de ``origen`` falla con el ID.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

COLUMNA_ORIGEN = "origen"
HUMANO = "humano"
ASISTENTE_PROVISIONAL = "asistente_provisional"
ORIGENES = (HUMANO, ASISTENTE_PROVISIONAL)
SOLO_HUMANOS = (HUMANO,)


def validar_origenes(origenes: Iterable[str]) -> tuple[str, ...]:
    """Devuelve ``origenes`` como tupla; falla con el valor si alguno no es ``humano`` ni ``asistente_provisional``."""
    pedidos = tuple(origenes)
    for o in pedidos:
        if o not in ORIGENES:
            raise ValueError(f"origen {o!r} desconocido (use {' o '.join(ORIGENES)})")
    return pedidos


def leer_filas(ruta: Path, origenes: Iterable[str] = SOLO_HUMANOS) -> list[dict[str, str]]:
    """Filas del CSV cuyo ``origen`` está en ``origenes`` (por defecto solo las humanas).

    * Si la columna existe, cada fila debe traer un ``origen`` válido (si no, ``ValueError`` con el ID de la fila).
    * Si el CSV no tiene la columna (consolidados anteriores a E1-07b), todas las filas son humanas; pedir las
      provisionales en ese caso es un error, no una lista vacía silenciosa.
    """
    pedidos = validar_origenes(origenes)
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        con_columna = COLUMNA_ORIGEN in (lector.fieldnames or [])
        if not con_columna and ASISTENTE_PROVISIONAL in pedidos:
            raise ValueError(f"{ruta.name} no tiene la columna {COLUMNA_ORIGEN!r}: no se pueden pedir etiquetas provisionales")
        filas: list[dict[str, str]] = []
        for fila in lector:
            origen = (fila.get(COLUMNA_ORIGEN) or "").strip() if con_columna else HUMANO
            if origen not in ORIGENES:
                raise ValueError(f"{(fila.get('id_noticia') or '?').strip()}: {COLUMNA_ORIGEN} {origen!r} desconocido (use {' o '.join(ORIGENES)})")
            if origen in pedidos:
                filas.append({**fila, COLUMNA_ORIGEN: origen})
    return filas
