"""Sector y horizonte de la modalidad bancaria · E2-01, D-11, PDF sección 3 (salida bancaria).

Funciones puras y deterministas: todo lo que deciden viene de ``config/modalidad_<modalidad>.yaml``
(``sectores_por_tema`` y ``horizonte``), nunca del nombre de la modalidad. Una modalidad que no declara esos bloques
(la editorial) recibe ``None``. E2-02 reutiliza ambas funciones para el boletín.

* **Sector:** el del tema del grupo (D-11). Un tema desconocido o sin sector no tiene sector: nunca se inventa uno.
* **Tema secundario del grupo (E2-02):** el tema más frecuente entre los titulares del grupo, distinto del principal, contando el
  ``tema_secundario`` de cada titular y su ``tema_clasificado``; el boletín muestra el sector de ambos temas.
* **Horizonte:** *inmediato* (evidencia de días), *corto plazo* (semanas) o *estructural*, según la edad de la
  publicación más reciente del grupo frente al corte del snapshot (la misma fecha que usa U: publicación y, si falta,
  detección). Sin ninguna fecha de noticia (solo datos anuales) es *estructural*.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any

from src.agrupacion import fecha_de
from src.configuracion import CODIGOS_DE_HORIZONTE, ConfigModalidad, ReglasV13

HORIZONTES = CODIGOS_DE_HORIZONTE
SEGUNDOS_POR_DIA = 86400


def sector_de_tema(tema: str | None, modalidad: ConfigModalidad) -> str | None:
    """Sector del ``tema`` según la modalidad; ``None`` si no hay tema, no tiene sector o la modalidad no puntúa por sector."""
    return modalidad.sectores_por_tema.get(tema) if tema else None


def horizonte_de(edad_dias: float | None, modalidad: ConfigModalidad) -> str | None:
    """Horizonte según la edad en días de la evidencia más reciente (``None``: sin fechas de noticia). ``None`` sin escala en la modalidad."""
    escala = modalidad.horizonte
    if escala is None:
        return None
    if edad_dias is None:
        return HORIZONTES[2]
    if edad_dias <= escala.inmediato_hasta_dias:
        return HORIZONTES[0]
    return HORIZONTES[1] if edad_dias <= escala.corto_plazo_hasta_dias else HORIZONTES[2]


def edad_en_dias(miembros: Sequence[Mapping[str, Any]], ahora: datetime, reglas: ReglasV13) -> float | None:
    """Días entre la publicación más reciente (o la detección, si ningún titular trae publicación) y ``ahora``; ``None`` sin fechas."""
    for campo in ("fecha_publicacion", reglas.urgencia.fecha_sin_publicacion):
        fechas = [f for f in (fecha_de(m, [campo]) for m in miembros) if f is not None]
        if fechas:
            return (ahora - max(fechas)).total_seconds() / SEGUNDOS_POR_DIA
    return None


def horizonte_de_grupo(miembros: Sequence[Mapping[str, Any]], ahora: datetime, modalidad: ConfigModalidad, reglas: ReglasV13) -> str | None:
    """Horizonte de un grupo a partir de sus titulares (filas de ``noticias``)."""
    return horizonte_de(edad_en_dias(miembros, ahora, reglas), modalidad)


def tema_secundario_de_grupo(miembros: Sequence[Mapping[str, Any]], principal: str | None, temas: Collection[str]) -> str | None:
    """Tema secundario de un grupo (E2-02): el más frecuente entre el ``tema_secundario`` y el ``tema_clasificado`` de sus titulares,
    sin contar el principal ni lo que no es uno de los ``temas`` (``sin_tema``). Empate: orden alfabético, como el tema dominante.
    ``None`` si no hay ninguno."""
    conteo = Counter(
        t for m in miembros for t in (m.get("tema_secundario"), m.get("tema_clasificado")) if t and t != principal and t in temas
    )
    if not conteo:
        return None
    mayor = max(conteo.values())
    return sorted(t for t, c in conteo.items() if c == mayor)[0]
