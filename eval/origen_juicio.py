"""Procedencia de los juicios que alimentan una métrica (D-101).

Durante el desarrollo el asistente hace juicios **provisionales** (la selección del editor de E1-19, los veredictos de sustento de
E1-18) que una persona rehace a mano en C-09. Cada archivo de juicios lleva la columna ``origen_juicio`` (``config/origen_juicio.yaml``)
y las métricas la propagan a su JSON y a la consola.

Reglas: sin la columna o con la celda vacía, el juicio es humano (el comportamiento anterior). Basta **una** fila con un origen no
humano para que todo el resultado lleve ese origen: un juicio provisional nunca se rotula como humano. Un valor que no está en la
configuración es un error que lo nombra.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from src.configuracion import ConfigOrigenJuicio, cargar_origen_juicio


class OrigenInvalido(ValueError):
    """La columna de origen trae un valor que la configuración no conoce, o más de un origen no humano."""


def origen_de_filas(filas: Iterable[Mapping[str, Any]], cfg: ConfigOrigenJuicio | None = None) -> str:
    """El origen de un conjunto de juicios: el humano solo si **ninguna** fila declara otro origen."""
    cfg = cfg or cargar_origen_juicio()
    declarados = {" ".join(str(f.get(cfg.columna) or "").lower().split()) for f in filas} - {""}
    desconocidos = sorted(declarados - set(cfg.origenes))
    if desconocidos:
        raise OrigenInvalido(f"{cfg.columna}: valores desconocidos {desconocidos}; se admiten {sorted(cfg.origenes)}")
    no_humanos = sorted(declarados - {cfg.humano})
    if len(no_humanos) > 1:
        raise OrigenInvalido(f"{cfg.columna}: el archivo mezcla orígenes no humanos {no_humanos}; uno por archivo")
    return no_humanos[0] if no_humanos else cfg.humano


def describir(origen: str, cfg: ConfigOrigenJuicio | None = None) -> dict[str, Any]:
    """Los campos que van al JSON de la métrica: la etiqueta del origen y si el juicio es humano."""
    cfg = cfg or cargar_origen_juicio()
    return {"origen_juicio": cfg.origenes[origen], "juicio_humano": origen == cfg.humano}
