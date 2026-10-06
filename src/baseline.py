"""Línea base de clasificación por palabras clave (E1-07, D-66).

Usa **exactamente las mismas categorías** que el clasificador con embeddings: los 6 temas de ``config/temas.yaml`` o
``sin_tema``. Los términos viven en ``config/clasificacion.yaml`` (``baseline.palabras_clave``) en dos grupos por tema:

* ``guia``: solo términos que aparecen literalmente en ``docs/guia_temas.md`` fuera de los casos difíciles (un test lo
  comprueba). Es la variante principal (``variante_activa``).
* ``extension``: vocabulario agregado a mano. Quien lo escribió ya había leído los casos difíciles, así que su uso se
  reporta aparte (variante ``ampliado``, ``baseline_ampliado`` en la evaluación) y no se presenta como independiente.

Un término coincide como palabra completa (con ``s`` o ``es`` final opcional) en el texto en minúsculas y sin tildes. El
puntaje de un tema es la cantidad de términos distintos que coinciden. Gana el mayor; si empatan, el primero en el
orden de ``temas.yaml``; sin coincidencias no hay tema. El segundo con puntaje > 0 es el tema secundario. No entiende
contexto ni las reglas de frontera de ``docs/guia_temas.md``: ahí se espera que los embeddings ganen (o no:
``docs/clasificacion.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.configuracion import ConfigClasificacion, ConfigTemas, cargar_clasificacion, cargar_temas
from src.limpieza import plano

SIN_TEMA = "sin_tema"
VARIANTES = ("guia", "ampliado")


@dataclass(frozen=True)
class ResultadoBaseline:
    """Tema principal y secundario del baseline, con el puntaje de cada tema (términos que coincidieron)."""

    principal: str
    secundario: str | None
    puntajes: dict[str, int]


def patron_de(termino: str) -> re.Pattern[str]:
    """Palabra o frase completa, con ``s``/``es`` final opcional, sobre texto sin tildes y en minúsculas."""
    return re.compile(r"\b" + re.escape(plano(termino)) + r"(?:es|s)?\b")


class Baseline:
    """Patrones compilados una vez; ``clasificar`` es una función pura del texto."""

    def __init__(self, cfg: ConfigClasificacion | None = None, temas: ConfigTemas | None = None, variante: str | None = None) -> None:
        cfg = cfg or cargar_clasificacion()
        temas = temas or cargar_temas()
        variante = variante or cfg.baseline.variante_activa
        if variante not in VARIANTES:
            raise ValueError(f"variante {variante!r} desconocida (use {list(VARIANTES)})")
        self.variante = variante
        self.temas = list(temas.temas)  # el orden de temas.yaml desempata
        self.patrones = {}
        for t in self.temas:
            grupos = cfg.baseline.palabras_clave[t]
            terminos = grupos.guia if variante == "guia" else [*grupos.guia, *grupos.extension]
            self.patrones[t] = [patron_de(x) for x in dict.fromkeys(terminos)]

    def puntuar(self, texto: str) -> dict[str, int]:
        """Cantidad de términos distintos de cada tema que coinciden con ``texto``."""
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
