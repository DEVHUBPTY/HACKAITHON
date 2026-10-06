"""Configuración de logging con redacción de valores sensibles (D-69).

Cualquier valor de una variable de entorno cuyo nombre termine en ``_KEY``,
``_TOKEN`` o ``_SECRET`` se reemplaza por ``[REDACTADO]`` en mensajes y en
el texto de excepciones.
"""

from __future__ import annotations

import logging
import os

MARCA_REDACCION = "[REDACTADO]"
SUFIJOS_SENSIBLES = ("_KEY", "_TOKEN", "_SECRET")


def valores_sensibles() -> list[str]:
    """Devuelve los valores no vacíos de las variables sensibles, del más largo al más corto."""
    valores = {
        valor
        for nombre, valor in os.environ.items()
        if valor and nombre.upper().endswith(SUFIJOS_SENSIBLES)
    }
    return sorted(valores, key=len, reverse=True)


def redactar(texto: str) -> str:
    """Reemplaza en ``texto`` cada valor sensible por la marca de redacción."""
    for valor in valores_sensibles():
        texto = texto.replace(valor, MARCA_REDACCION)
    return texto


class FiltroRedaccion(logging.Filter):
    """Filtro que redacta valores sensibles en el mensaje y en las excepciones."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redactar(record.getMessage())
        record.args = ()
        if record.exc_info:
            texto = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redactar(texto)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redactar(record.exc_text)
        if record.stack_info:
            record.stack_info = redactar(record.stack_info)
        return True


def configurar_logging(nivel: int = logging.INFO) -> None:
    """Instala el filtro de redacción en los handlers del logger raíz (crea uno si no hay)."""
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    if not raiz.handlers:
        raiz.addHandler(logging.StreamHandler())
    for handler in raiz.handlers:
        if not any(isinstance(f, FiltroRedaccion) for f in handler.filters):
            handler.addFilter(FiltroRedaccion())
