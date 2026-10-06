"""Procedencias independientes de cada grupo (agencia y tipo_firma, nunca el nombre del autor) · E1-08, CU-03, D-32.

Una **procedencia** es un origen editorial. Cinco medios que replican un mismo despacho de agencia son UNA procedencia:
contar titulares como fuentes inflaría la evidencia (``puntaje.py``: E usa procedencias, no titulares).

Dos titulares de un grupo comparten procedencia si se cumple **cualquiera** de estas reglas (todas con su dato en
``config/procedencias.yaml`` y ``config/reglas_v1.3.yaml``; el RSS no trae firma, así que no se puede depender de ella):

* ``mismo_medio``: el mismo dominio (un medio es una sola procedencia aunque publique dos veces).
* ``agencia_campo``: el mismo campo ``agencia`` de ``noticias`` (lo deriva ``normalizacion`` de la firma, si existe).
* ``agencia_dominio``: el dominio es de una agencia (p. ej. ``english.news.cn`` es Xinhua) y el otro titular es de esa
  agencia por cualquier vía.
* ``agencia_mencionada``: el titular nombra a la misma agencia ("... - Xinhua", "según Reuters").
* ``misma_red``: los dos dominios pertenecen a la misma red de sindicación (Big News Network).
* ``texto_casi_identico``: titulares de medios distintos con similitud coseno >= ``umbral_mismo_texto``.

La relación es transitiva (A~B y B~C implica A~C): las procedencias son las componentes conexas. **Es una estimación**
y así se presenta (``etiqueta_estimado``): una traducción independiente del mismo despacho cuenta como otra procedencia,
porque ninguna regla puede saber que comparten origen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.configuracion import ConfigProcedencias, ReglasV13
from src.limpieza import plano

REGLA_MISMO_MEDIO = "mismo_medio"
REGLA_AGENCIA_CAMPO = "agencia_campo"
REGLA_AGENCIA_DOMINIO = "agencia_dominio"
REGLA_AGENCIA_MENCIONADA = "agencia_mencionada"
REGLA_MISMA_RED = "misma_red"
REGLA_TEXTO = "texto_casi_identico"
CAMPO_TEXTO_MENCION = "titulo"   # el titular tal como llegó: ``titulo_limpio`` ya le quitó el sufijo "- Xinhua"


@dataclass(frozen=True)
class Procedencia:
    """Un origen independiente dentro de un grupo."""

    etiqueta: str                    # agencia o red si se conoce; si no, el medio más antiguo del conjunto
    ids_noticia: tuple[str, ...]     # ordenados
    medios: tuple[str, ...]          # ordenados, sin repetir
    reglas: tuple[str, ...]          # reglas que unieron a sus titulares (vacío si es un solo titular)


# ------------------------------------------------------------------ señales de cada titular


def dominio_normalizado(fila: Mapping[str, Any]) -> str:
    """Dominio en minúsculas y sin ``www.``; si falta ``dominio``, se usa ``medio``."""
    texto = str(fila.get("dominio") or fila.get("medio") or "").strip().lower()
    return texto.removeprefix("www.")


def _es_del_dominio(dominio: str, dominios: Sequence[str]) -> bool:
    return any(dominio == d or dominio.endswith("." + d) for d in dominios)


def _formas_de(agencia: str, alias: Mapping[str, list[str]]) -> list[str]:
    return [agencia, *alias.get(agencia, [])]


def _menciona(texto: str, forma: str) -> bool:
    """Palabra completa. Las siglas (EFE, AFP, AP...) distinguen mayúsculas: "ap" no es la agencia AP."""
    if forma.isupper():
        return re.search(rf"(?<!\w){re.escape(forma)}(?!\w)", texto) is not None
    return re.search(rf"(?<!\w){re.escape(plano(forma))}(?!\w)", plano(texto)) is not None


@dataclass(frozen=True)
class Senales:
    """Lo que se sabe del origen de un titular sin mirar a los demás."""

    dominio: str
    red: str | None                  # id de la red de sindicación a la que pertenece su dominio
    agencia_campo: str | None        # campo ``agencia`` de noticias
    agencia_dominio: str | None      # agencia dueña del dominio
    agencias_mencionadas: frozenset[str]

    @property
    def agencias(self) -> frozenset[str]:
        propias = {a for a in (self.agencia_campo, self.agencia_dominio) if a}
        return frozenset(propias | self.agencias_mencionadas)


def senales_de(fila: Mapping[str, Any], cfg: ConfigProcedencias, reglas: ReglasV13) -> Senales:
    """Calcula las señales de procedencia de un titular (agencia por campo, dominio y mención en el titular)."""
    dominio = dominio_normalizado(fila)
    red = next((i for i, r in cfg.redes_sindicacion.items() if _es_del_dominio(dominio, r.dominios)), None)
    agencia_dominio = next((a for a, ds in cfg.agencias_por_dominio.items() if _es_del_dominio(dominio, ds)), None)
    campo = fila.get("agencia")
    agencia_campo = campo if campo in reglas.agencias else None
    texto = str(fila.get(CAMPO_TEXTO_MENCION) or "")
    mencionadas = frozenset(
        a for a in reglas.agencias if any(_menciona(texto, f) for f in _formas_de(a, cfg.alias_agencias))
    )
    return Senales(dominio, red, agencia_campo, agencia_dominio, mencionadas)


# ------------------------------------------------------------------ relación entre dos titulares


def reglas_que_unen(
    a: Senales,
    b: Senales,
    similitud: float | None,
    umbral_mismo_texto: float,
) -> set[str]:
    """Reglas por las que dos titulares comparten procedencia (vacío = independientes)."""
    unen: set[str] = set()
    if a.dominio and a.dominio == b.dominio:
        unen.add(REGLA_MISMO_MEDIO)
    if a.agencia_campo and a.agencia_campo == b.agencia_campo:
        unen.add(REGLA_AGENCIA_CAMPO)
    if a.agencia_dominio and a.agencia_dominio in b.agencias:
        unen.add(REGLA_AGENCIA_DOMINIO)
    elif b.agencia_dominio and b.agencia_dominio in a.agencias:
        unen.add(REGLA_AGENCIA_DOMINIO)
    if a.agencias_mencionadas & b.agencias_mencionadas:
        unen.add(REGLA_AGENCIA_MENCIONADA)
    if a.red and a.red == b.red:
        unen.add(REGLA_MISMA_RED)
    if a.dominio != b.dominio and similitud is not None and similitud >= umbral_mismo_texto:
        unen.add(REGLA_TEXTO)
    return unen


class _Conjuntos:
    """Unión-búsqueda con compresión de caminos; la raíz es siempre el menor índice (resultado determinista)."""

    def __init__(self, n: int) -> None:
        self.padre = list(range(n))

    def raiz(self, i: int) -> int:
        while self.padre[i] != i:
            self.padre[i] = self.padre[self.padre[i]]
            i = self.padre[i]
        return i

    def unir(self, i: int, j: int) -> None:
        ri, rj = self.raiz(i), self.raiz(j)
        if ri != rj:
            self.padre[max(ri, rj)] = min(ri, rj)


# ------------------------------------------------------------------ procedencias de un grupo


def estimar_procedencias(
    miembros: Sequence[Mapping[str, Any]],
    vectores: np.ndarray | None,
    cfg: ConfigProcedencias,
    reglas: ReglasV13,
    fechas: Sequence[str | None] | None = None,
) -> list[Procedencia]:
    """Procedencias independientes de un grupo (estimado). Cada titular cae en exactamente una.

    ``vectores`` son los embeddings normalizados de los miembros (misma posición); sin ellos la regla de texto casi
    idéntico no se aplica. ``fechas`` (opcional) sirve para nombrar una procedencia sin agencia ni red con el medio
    más antiguo.
    """
    n = len(miembros)
    if n == 0:
        return []
    senales = [senales_de(m, cfg, reglas) for m in miembros]
    conjuntos = _Conjuntos(n)
    aristas: list[tuple[int, int, set[str]]] = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = float(vectores[i] @ vectores[j]) if vectores is not None else None
            unen = reglas_que_unen(senales[i], senales[j], sim, reglas.agrupacion.umbral_mismo_texto)
            if unen:
                conjuntos.unir(i, j)
                aristas.append((i, j, unen))
    componentes: dict[int, list[int]] = {}
    for i in range(n):
        componentes.setdefault(conjuntos.raiz(i), []).append(i)
    fechas = fechas or [None] * n
    salida = []
    for indices in componentes.values():
        usadas = {r for i, j, unen in aristas if conjuntos.raiz(i) == conjuntos.raiz(indices[0]) for r in unen}
        ids = tuple(sorted(str(miembros[i]["id_noticia"]) for i in indices))
        medios = tuple(sorted({str(miembros[i].get("medio") or senales[i].dominio) for i in indices}))
        salida.append(Procedencia(_etiqueta(indices, senales, miembros, fechas, cfg, reglas), ids, medios, tuple(sorted(usadas))))
    return sorted(salida, key=lambda p: p.ids_noticia)


def _etiqueta(
    indices: list[int],
    senales: list[Senales],
    miembros: Sequence[Mapping[str, Any]],
    fechas: Sequence[str | None],
    cfg: ConfigProcedencias,
    reglas: ReglasV13,
) -> str:
    """Agencias (en el orden de ``reglas.agencias``) y redes del conjunto; si no hay, el medio más antiguo."""
    agencias = {a for i in indices for a in senales[i].agencias}
    redes = {senales[i].red for i in indices if senales[i].red}
    nombres = [a for a in reglas.agencias if a in agencias] + [cfg.redes_sindicacion[r].nombre for r in sorted(redes)]
    if nombres:
        return cfg.separador_etiqueta.join(nombres)
    primero = min(indices, key=lambda i: (fechas[i] or "", str(miembros[i]["id_noticia"])))
    return str(miembros[primero].get("medio") or senales[primero].dominio)


def fraccion_de_procedencias(n_procedencias: int, reglas: ReglasV13) -> float:
    """Parte de E que aportan las procedencias: ``min(n, tope) / tope`` (``evidencia.tope_procedencias``).

    Cuenta procedencias, nunca titulares: tres copias de una agencia valen 1/tope, no tope/tope.
    """
    tope = reglas.evidencia.tope_procedencias
    return min(max(n_procedencias, 0), tope) / tope
