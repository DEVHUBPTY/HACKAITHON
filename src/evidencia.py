"""Estado de evidencia, vacíos de verificación y acción recomendada de cada grupo · E1-10, T08, PDF sección 4.

El **estado de evidencia es independiente del puntaje** (PDF sección 4): no recibe P ni el rango. Con las reglas v1.3:

* ``suficiente``: ``procedencias_suficiente`` o más procedencias independientes (estimadas), **sin contradicción abierta** y,
  si los titulares traen cifras, con dato oficial vinculado.
* ``parcial``: ``procedencias_suficiente`` o más procedencias que no cumplen lo anterior, o ``procedencias_parcial_con_oficial``
  procedencia con dato (o evento) oficial.
* ``insuficiente``: lo demás.

Una contradicción abierta es todo par de titulares con versiones distintas que detectaron las reglas
(«posible contradicción, verificar», ``src/contradicciones.py``). El LLM solo la anota: no la cierra ni cambia este estado (X21).

La **acción recomendada** sale de la tabla 3×3 (rango × estado) de la modalidad (``config/modalidad_<modalidad>.yaml``):
nunca del LLM y ninguna celda habilita publicar (``Accion`` lo valida al cargar y aquí se vuelve a comprobar).

Este módulo también extrae las **cifras** de un titular (``extraer_cifras``): de ahí sale «¿el grupo trae cifras?» y los
candidatos a contradicción por cifras distintas.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from src.configuracion import FORMAS_DE_PUBLICAR, Accion, ConfigModalidad, ConfigPrioridad, ReglasV13
from src.limpieza import plano

ESTADO_SUFICIENTE, ESTADO_PARCIAL, ESTADO_INSUFICIENTE = "suficiente", "parcial", "insuficiente"
ULTIMA_PALABRA = re.compile(r"(\w+)\W*$")
UNIDAD_PORCENTAJE = "%"


@dataclass(frozen=True)
class Vacio:
    """Un vacío de verificación para la ficha: código estable y texto legible."""

    codigo: str
    texto: str


@dataclass(frozen=True)
class Cifra:
    """Una cifra de un titular: valor numérico, unidad normalizada (``%`` o la raíz de la palabra que la sigue) y el texto."""

    valor: float
    unidad: str
    texto: str


@dataclass(frozen=True)
class Evidencia:
    """Estado de evidencia de un grupo y los vacíos que lo explican."""

    estado: str
    n_procedencias: int
    tiene_oficial: bool
    hay_cifras: bool
    contradicciones_abiertas: int
    vacios: tuple[Vacio, ...]


# ------------------------------------------------------------------ cifras


def valor_numerico(texto: str, digitos_por_grupo_de_miles: int) -> float:
    """Número de un titular: ``84.000`` es 84 mil; ``3,2`` y ``3.5`` son decimales; con ambos separadores gana el último como decimal."""
    if "," in texto and "." in texto:
        decimal = "," if texto.rfind(",") > texto.rfind(".") else "."
        miles = "." if decimal == "," else ","
        return float(texto.replace(miles, "").replace(decimal, "."))
    if "," in texto:
        partes = texto.split(",")
        return float("".join(partes)) if len(partes) > 2 else float(texto.replace(",", "."))
    if "." in texto:
        partes = texto.split(".")
        todas_de_miles = all(len(p) == digitos_por_grupo_de_miles for p in partes[1:])
        return float("".join(partes)) if todas_de_miles else float(texto)
    return float(texto)


@lru_cache(maxsize=None)
def _patron(texto: str) -> re.Pattern[str]:
    return re.compile(texto, re.IGNORECASE)


def extraer_cifras(titulo: str, cfg: ConfigPrioridad) -> list[Cifra]:
    """Cifras de un titular, sin fechas («2 de octubre»), años, ni identificadores («Ley 552»).

    La unidad es ``%`` o la raíz (``raiz_unidad_caracteres``) de la palabra siguiente, sin las de ``unidades_ignoradas``.
    """
    c = cfg.cifras
    sin_fechas = _patron(c.patron_fecha).sub(" ", titulo)
    cifras: list[Cifra] = []
    for m in _patron(c.patron).finditer(sin_fechas):
        crudo, unidad = m.group("numero"), (m.group("unidad") or "")
        try:
            valor = valor_numerico(crudo, c.digitos_por_grupo_de_miles)
        except ValueError:
            continue
        if unidad != UNIDAD_PORCENTAJE and valor.is_integer() and c.anio_desde <= valor <= c.anio_hasta and "." not in crudo and "," not in crudo:
            continue   # un año
        previa = ULTIMA_PALABRA.search(plano(sin_fechas[: m.start()]))
        if previa and previa.group(1) in c.palabras_previas_no_cifra:
            continue
        clave = unidad if unidad == UNIDAD_PORCENTAJE else plano(unidad)
        if clave in c.unidades_ignoradas:
            clave = ""
        elif clave != UNIDAD_PORCENTAJE:
            clave = clave[: c.raiz_unidad_caracteres]
        cifras.append(Cifra(valor, clave, m.group(0).strip()))
    return cifras


def hay_cifras(titulares: Sequence[str], cfg: ConfigPrioridad) -> bool:
    """¿Algún titular del grupo trae una cifra?"""
    return any(extraer_cifras(t, cfg) for t in titulares)


# ------------------------------------------------------------------ estado


def estado_de(
    n_procedencias: int, tiene_oficial: bool, trae_cifras: bool, contradicciones_abiertas: int, reglas: ReglasV13
) -> str:
    """``suficiente``, ``parcial`` o ``insuficiente`` (ver el docstring del módulo). No recibe P: es independiente del puntaje."""
    e = reglas.estado_evidencia
    necesita_oficial = e.oficial_obligatorio_si_hay_cifras and trae_cifras
    hay_contradiccion = e.sin_contradiccion_abierta_para_suficiente and contradicciones_abiertas > 0
    suficientes = n_procedencias >= e.procedencias_suficiente
    if suficientes and not hay_contradiccion and (tiene_oficial or not necesita_oficial):
        return ESTADO_SUFICIENTE
    if suficientes or (n_procedencias >= e.procedencias_parcial_con_oficial and tiene_oficial):
        return ESTADO_PARCIAL
    return ESTADO_INSUFICIENTE


def evaluar_evidencia(
    *,
    n_procedencias: int,
    tiene_oficial: bool,
    titulares: Sequence[str],
    contradicciones_abiertas: int,
    n_identificables: int,
    motivo_sin_oficial: str | None,
    reglas: ReglasV13,
    cfg: ConfigPrioridad,
) -> Evidencia:
    """Estado de evidencia del grupo y su lista de vacíos (orden fijo: procedencias, oficial, contradicción, identificables)."""
    trae_cifras = hay_cifras(titulares, cfg)
    estado = estado_de(n_procedencias, tiene_oficial, trae_cifras, contradicciones_abiertas, reglas)
    v = cfg.vacios
    vacios: list[Vacio] = []
    minimo = reglas.estado_evidencia.procedencias_suficiente
    if n_procedencias < minimo:
        vacios.append(Vacio("procedencias_insuficientes", v.procedencias_insuficientes.format(n=n_procedencias, minimo=minimo)))
    if not tiene_oficial:
        if trae_cifras and reglas.estado_evidencia.oficial_obligatorio_si_hay_cifras:
            vacios.append(Vacio("cifras_sin_dato_oficial", v.cifras_sin_dato_oficial))
        vacios.append(Vacio("sin_dato_oficial", v.sin_dato_oficial.format(motivo=motivo_sin_oficial or v.motivo_sin_dato_oficial_por_defecto)))
    if contradicciones_abiertas:
        vacios.append(Vacio("contradiccion_abierta", v.contradiccion_abierta.format(n=contradicciones_abiertas)))
    if n_identificables < len(titulares):
        vacios.append(
            Vacio("medios_o_fechas_desconocidos", v.medios_o_fechas_desconocidos.format(n=len(titulares) - n_identificables, total=len(titulares)))
        )
    return Evidencia(estado, n_procedencias, tiene_oficial, trae_cifras, contradicciones_abiertas, tuple(vacios))


# ------------------------------------------------------------------ acción


def accion_recomendada(rango: str, estado: str, modalidad: ConfigModalidad) -> Accion:
    """Acción de la celda (rango × estado) de la tabla de la modalidad. Nunca habilita publicar."""
    fila: Any = getattr(modalidad.tabla_acciones, rango)
    accion: Accion = getattr(fila, estado)
    if FORMAS_DE_PUBLICAR.search(f"{accion.accion} {accion.motivo}"):
        raise ValueError(f"la acción de ({rango}, {estado}) habla de publicar")
    return accion


def celdas_de_acciones(modalidad: ConfigModalidad) -> Mapping[tuple[str, str], Accion]:
    """Las 9 celdas de la tabla: ``(rango, estado) -> Accion``."""
    return {(r, e): accion_recomendada(r, e, modalidad) for r in ("bajo", "medio", "alto") for e in (ESTADO_INSUFICIENTE, ESTADO_PARCIAL, ESTADO_SUFICIENTE)}


if __name__ == "__main__":
    import sys

    from src.prioridad import main

    sys.exit(main())
