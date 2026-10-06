"""Constructor de consultas de GDELT DOC 2.0 (E0-04, D-62).

Cada tema se consulta con dos "patas" (llamadas separadas por rango), porque la API no permite
anidar bloques ``OR`` ni combinar filtros distintos de país en una sola consulta:

- ``locales``: medios de Panamá (``sourcecountry:panama``) + términos del tema en español.
- ``internacional``: medios de fuera de Panamá (``-sourcecountry:panama``) + frases específicas de
  Panamá. Nunca "Panama" suelto junto a un sustantivo genérico.

Operadores usados (https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/): frase entre comillas,
``(a OR b)`` sin anidar, ``sourcecountry:<nombre|FIPS>``, prefijo ``-`` para excluir.
No hace red: solo arma texto.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

LARGO_MINIMO_TERMINO = 3  # supuesto: GDELT rechaza palabras demasiado cortas
_PROHIBIDOS = re.compile(r"[()\"]")


def _termino(t: str) -> str:
    """Una palabra va suelta; una frase, entre comillas."""
    t = t.strip()
    if not t or _PROHIBIDOS.search(t) or t.upper() == "OR":
        raise ValueError(f"término inválido para GDELT: {t!r}")
    if len(t) < LARGO_MINIMO_TERMINO:
        raise ValueError(f"término demasiado corto para GDELT: {t!r}")
    return f'"{t}"' if " " in t else t


def construir_consulta(pata: dict[str, Any]) -> str:
    """``(t1 OR "frase dos") filtro1 filtro2`` a partir de ``{terminos, filtros}``."""
    terminos = [_termino(t) for t in pata["terminos"]]
    if not terminos:
        raise ValueError("una pata necesita al menos un término")
    bloque = terminos[0] if len(terminos) == 1 else f"({' OR '.join(terminos)})"
    return " ".join([bloque, *pata.get("filtros", [])])


def construir_consultas(consultas: dict[str, Any]) -> list[tuple[str, str | None, str]]:
    """Lista ``(tema, pata, consulta)`` en el orden de la configuración.

    Un valor ``str`` (formato antiguo) es una consulta única, con pata ``None``.
    """
    salida: list[tuple[str, str | None, str]] = []
    for tema, valor in consultas.items():
        if isinstance(valor, str):
            salida.append((tema, None, valor))
            continue
        for nombre, pata in valor.items():
            salida.append((tema, nombre, construir_consulta(pata)))
    return salida


def consultas_por_tema(consultas: dict[str, Any]) -> dict[str, Any]:
    """Forma para el manifest: ``{tema: {pata: consulta}}`` (o ``{tema: consulta}`` si es antigua)."""
    salida: dict[str, Any] = {}
    for tema, pata, q in construir_consultas(consultas):
        if pata is None:
            salida[tema] = q
        else:
            salida.setdefault(tema, {})[pata] = q
    return salida


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar títulos con términos."""
    base = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def titulo_coincide(titulo: str, terminos: list[str]) -> bool:
    """Aproximación offline: algún término (palabra completa o frase) aparece en el título."""
    t = normalizar(titulo)
    return any(re.search(rf"(?<!\w){re.escape(normalizar(x))}(?!\w)", t) for x in terminos)
