"""Línea base de clasificación por palabras clave (E1-07, D-66).

Usa **exactamente las mismas categorías** que el clasificador con embeddings: los 6 temas de ``config/temas.yaml`` o
``sin_tema``. Los patrones viven en ``config/clasificacion.yaml`` (``baseline.palabras_clave``), se aplican al texto en
minúsculas y sin tildes, y el puntaje de un tema es la cantidad de patrones distintos que coinciden. Gana el mayor;
si empatan, el primero en el orden de ``temas.yaml``; sin coincidencias no hay tema. El segundo con puntaje > 0 es el
tema secundario. Es un comparador honesto y simple: no entiende contexto ni las reglas de frontera de
``docs/guia_temas.md``, y ahí es donde se espera que los embeddings ganen (o no: ``docs/ia_vs_baseline.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.configuracion import ConfigClasificacion, ConfigTemas, cargar_clasificacion, cargar_temas
from src.limpieza import plano

SIN_TEMA = "sin_tema"


@dataclass(frozen=True)
class ResultadoBaseline:
    """Tema principal y secundario del baseline, con el puntaje de cada tema (patrones que coincidieron)."""

    principal: str
    secundario: str | None
    puntajes: dict[str, int]


class Baseline:
    """Patrones compilados una vez; ``clasificar`` es una función pura del texto."""

    def __init__(self, cfg: ConfigClasificacion | None = None, temas: ConfigTemas | None = None) -> None:
        cfg = cfg or cargar_clasificacion()
        temas = temas or cargar_temas()
        self.temas = list(temas.temas)  # el orden de temas.yaml desempata
        self.patrones = {t: [re.compile(p) for p in cfg.baseline.palabras_clave[t]] for t in self.temas}

    def puntuar(self, texto: str) -> dict[str, int]:
        """Cantidad de patrones distintos de cada tema que coinciden con ``texto``."""
        limpio = plano(texto)
        return {t: sum(1 for p in self.patrones[t] if p.search(limpio)) for t in self.temas}

    def clasificar(self, texto: str) -> ResultadoBaseline:
        puntajes = self.puntuar(texto)
        # orden estable: mayor puntaje primero y, a igualdad, el orden de temas.yaml
        orden = sorted(self.temas, key=lambda t: (-puntajes[t], self.temas.index(t)))
        if puntajes[orden[0]] == 0:
            return ResultadoBaseline(SIN_TEMA, None, puntajes)
        secundario = orden[1] if puntajes[orden[1]] > 0 else None
        return ResultadoBaseline(orden[0], secundario, puntajes)
