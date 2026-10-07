"""Procedencia de las etiquetas de ``eval/etiquetas.csv`` (E1-07b): ``humano`` o ``asistente_provisional`` (D-101).

Las etiquetas «provisionales» las propuso un agente y las aprobó **provisionalmente el asistente**, no una persona (decisión
D-101, pendiente de la revisión humana C-09). Como el agente que propuso la etiqueta y el que la aprobó son del mismo tipo
que el clasificador que se mide, hay **riesgo de circularidad**: por eso todo lector del CSV usa solo las humanas, salvo que
el llamador pida las otras de forma explícita (``origenes=``), y todo informe que las use lo declara (``marcar``).

El encabezado de la columna se compara sin espacios a los lados y sin distinguir mayúsculas (``Origen`` vale). Uno que se le
**parece** pero no es igual (``origen_``, ``orígen``, ``o rigen``) o dos columnas de origen son un error (X47): si se
ignorara el encabezado, las 61 provisionales contarían como humanas sin aviso. Un valor desconocido o vacío también falla, con
el ID. Sin la columna: en ``eval/etiquetas.csv`` (que ya la tiene) es un error; en otro CSV (de prueba o anterior a E1-07b)
todas las filas son humanas y no se pueden pedir provisionales. Mismo criterio que ``eval/origen_juicio.py`` (PR #35); cuando
ese PR se integre conviene unificar los dos módulos de procedencia.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.configuracion import RAIZ

COLUMNA_ORIGEN = "origen"
HUMANO = "humano"
ASISTENTE_PROVISIONAL = "asistente_provisional"
ORIGENES = (HUMANO, ASISTENTE_PROVISIONAL)
SOLO_HUMANOS = (HUMANO,)
ETIQUETAS_CONSOLIDADO = RAIZ / "eval" / "etiquetas.csv"      # el consolidado versionado: aquí la columna es obligatoria
AVISO_PROVISIONAL = (
    "PROVISIONAL (D-101). Usa etiquetas que propuso un agente y aprobó provisionalmente el asistente: riesgo de circularidad, "
    "pendientes de la revisión humana C-09; no son una verdad de referencia."
)


def normalizar_origen(valor: Any) -> str:
    """Un valor de ``origen`` sin espacios a los lados ni mayúsculas (así lo leen el lector y el validador)."""
    return " ".join(str(valor or "").casefold().split())


def _esqueleto(nombre: str) -> str:
    """Solo letras sin tilde y dígitos: lo que queda de un encabezado si se le quitan separadores, espacios y acentos."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", nombre.casefold()) if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", "", sin_tildes)


def validar_origenes(origenes: Iterable[str] | str) -> tuple[str, ...]:
    """``origenes`` como tupla (un texto suelto vale como uno solo); falla con el valor si alguno no existe."""
    pedidos = (origenes,) if isinstance(origenes, str) else tuple(origenes)
    for o in pedidos:
        if o not in ORIGENES:
            raise ValueError(f"origen {o!r} desconocido (use {' o '.join(ORIGENES)})")
    return pedidos


def usa_provisionales(origenes: Iterable[str] | str) -> bool:
    return ASISTENTE_PROVISIONAL in validar_origenes(origenes)


def marcar(informe: dict[str, Any], origenes: Iterable[str] | str) -> dict[str, Any]:
    """Agrega al informe de qué procedencia son las etiquetas; con provisionales, el aviso PROVISIONAL (D-101)."""
    pedidos = validar_origenes(origenes)
    informe["origenes"] = list(pedidos)
    informe["usa_etiquetas_provisionales"] = usa_provisionales(pedidos)
    if informe["usa_etiquetas_provisionales"]:
        informe["aviso"] = AVISO_PROVISIONAL
    return informe


def columna_de_origen(encabezados: Iterable[str]) -> str | None:
    """El encabezado real de la columna de origen, o ``None`` si no hay. Uno parecido pero distinto, o repetido, es error."""
    exactos, parecidos = [], []
    for nombre in dict.fromkeys(e for e in encabezados if e is not None):
        if nombre.strip().casefold() == COLUMNA_ORIGEN:
            exactos.append(nombre)
        elif _esqueleto(nombre) == COLUMNA_ORIGEN:
            parecidos.append(nombre)
    if parecidos:
        raise ValueError(f"encabezado {parecidos[0]!r} se parece a {COLUMNA_ORIGEN!r} pero no es igual: corregir el nombre de la columna")
    if len(exactos) > 1:
        raise ValueError(f"la columna {COLUMNA_ORIGEN!r} aparece más de una vez: {exactos}")
    return exactos[0] if exactos else None


def tiene_columna_origen(ruta: Path) -> bool:
    """¿El CSV declara la columna de origen? Un encabezado parecido pero distinto es un error (ver ``columna_de_origen``)."""
    with ruta.open(encoding="utf-8", newline="") as f:
        return columna_de_origen(csv.DictReader(f).fieldnames or []) is not None


def leer_filas(ruta: Path, origenes: Iterable[str] | str = SOLO_HUMANOS) -> list[dict[str, str]]:
    """Filas del CSV cuyo ``origen`` está en ``origenes`` (por defecto solo las humanas); ``origen`` sale normalizado.

    Con la columna, cada fila debe traer un ``origen`` válido (si no, ``ValueError`` con el ID). Sin la columna, ver el
    docstring del módulo.
    """
    pedidos = validar_origenes(origenes)
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        columna = columna_de_origen(lector.fieldnames or [])
        if columna is None:
            if ASISTENTE_PROVISIONAL in pedidos:
                raise ValueError(f"{ruta.name} no tiene la columna {COLUMNA_ORIGEN!r}: no se pueden pedir etiquetas provisionales")
            if ruta.resolve() == ETIQUETAS_CONSOLIDADO.resolve():
                raise ValueError(f"{ruta.name} no tiene la columna {COLUMNA_ORIGEN!r}: sin ella no se sabe cuáles filas son provisionales")
        filas: list[dict[str, str]] = []
        for fila in lector:
            origen = normalizar_origen(fila.get(columna)) if columna is not None else HUMANO
            if origen not in ORIGENES:
                raise ValueError(f"{(fila.get('id_noticia') or '?').strip()}: {COLUMNA_ORIGEN} {origen!r} desconocido (use {' o '.join(ORIGENES)})")
            if origen in pedidos:
                filas.append({**fila, COLUMNA_ORIGEN: origen})
    return filas
