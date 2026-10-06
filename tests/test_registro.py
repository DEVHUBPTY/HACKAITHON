"""Pruebas del filtro de redacción de logs (D-69)."""

import io
import logging
from collections.abc import Iterator

import pytest

from src.registro import MARCA_REDACCION, FiltroRedaccion, configurar_logging

SECRETO = "sk-falso-1234567890"


@pytest.fixture
def flujo(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[logging.Logger, io.StringIO]]:
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRETO)
    salida = io.StringIO()
    handler = logging.StreamHandler(salida)
    handler.addFilter(FiltroRedaccion())
    logger = logging.getLogger("prueba_registro")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    yield logger, salida
    logger.removeHandler(handler)


def test_redacta_clave_con_argumentos(flujo) -> None:
    logger, salida = flujo
    logger.info("clave=%s", SECRETO)
    texto = salida.getvalue()
    assert MARCA_REDACCION in texto
    assert SECRETO not in texto


def test_redacta_clave_en_f_string(flujo) -> None:
    logger, salida = flujo
    logger.info(f"clave={SECRETO}")
    texto = salida.getvalue()
    assert MARCA_REDACCION in texto
    assert SECRETO not in texto


def test_redacta_clave_en_excepcion(flujo) -> None:
    logger, salida = flujo
    try:
        raise RuntimeError(f"fallo con {SECRETO}")
    except RuntimeError:
        logger.exception("error")
    texto = salida.getvalue()
    assert "RuntimeError" in texto
    assert MARCA_REDACCION in texto
    assert SECRETO not in texto


def test_no_redacta_variable_no_sensible(
    flujo, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger, salida = flujo
    monkeypatch.setenv("OLLAMA_MODEL", "modelo-local")
    logger.info("modelo=%s", "modelo-local")
    texto = salida.getvalue()
    assert "modelo-local" in texto
    assert MARCA_REDACCION not in texto


def test_variable_sensible_vacia_no_redacta_todo(
    flujo, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger, salida = flujo
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.setenv("OTRO_TOKEN", "")
    logger.info("mensaje normal")
    assert salida.getvalue().strip() == "mensaje normal"


def test_configurar_logging_instala_filtro(monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = logging.getLogger()
    antes = list(raiz.handlers)
    salida = io.StringIO()
    handler = logging.StreamHandler(salida)
    raiz.handlers = [handler]
    try:
        monkeypatch.setenv("DEEPSEEK_API_KEY", SECRETO)
        configurar_logging()
        logging.getLogger("otro").warning("x %s", SECRETO)
        assert SECRETO not in salida.getvalue()
        assert MARCA_REDACCION in salida.getvalue()
    finally:
        raiz.handlers = antes
