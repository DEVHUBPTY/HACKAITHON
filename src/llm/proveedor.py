"""Interfaz común de proveedores LLM, elegida por configuración (``LLM_PROVIDER`` de ``local.env``, nunca hardcodeada).

El LLM no tiene herramientas ni acciones: solo recibe un mensaje de sistema (reglas) y uno de usuario (la evidencia dentro de
``<evidencia>…</evidencia>`` y como dato, nunca instrucción) y devuelve **texto JSON**, que el llamador valida con pydantic.
Temperatura 0 y semilla fija salen de ``config/llm.yaml``.

Un proveedor que no existe, no está configurado o no responde lanza ``ErrorProveedor``; quien lo usa decide cómo degradar
(``src/contradicciones.py`` deja los candidatos pendientes y sigue).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from src.configuracion import RAIZ, ConfigLlm, cargar_llm, leer_local_env

PROVEEDOR_OLLAMA = "ollama"
PROVEEDOR_DEEPSEEK = "deepseek"

log = logging.getLogger(__name__)


class ErrorProveedor(RuntimeError):
    """El proveedor no está disponible o no devolvió una respuesta utilizable."""


@dataclass(frozen=True)
class UsoLlm:
    """Consumo de una llamada (E1-12): tokens y latencia, sin prompts ni secretos."""

    proveedor: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    latencia_s: float


def registrar_uso(uso: UsoLlm) -> None:
    """Deja en el log una línea por llamada: solo cifras, nunca el contenido del mensaje (D-69)."""
    log.info(
        "llamada llm proveedor=%s modelo=%s tokens_entrada=%d tokens_salida=%d latencia_s=%.2f",
        uso.proveedor, uso.modelo, uso.tokens_entrada, uso.tokens_salida, uso.latencia_s,
    )


class Proveedor(Protocol):
    """Lo mínimo que se le pide a un proveedor: una llamada con salida JSON estructurada."""

    nombre: str
    modelo: str

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        """Texto JSON de la respuesta (sin validar). Lanza ``ErrorProveedor`` si falla el transporte o no hay respuesta."""
        ...


def crear_proveedor(env: Mapping[str, str] | None = None, cfg: ConfigLlm | None = None) -> Proveedor:
    """El proveedor que dice ``LLM_PROVIDER`` en ``local.env`` (``env`` permite inyectarlo en pruebas).

    ``deepseek`` devuelve un ``ProveedorConTope`` (D-67): DeepSeek hasta el tope de costo y, al alcanzarlo, el modelo local de
    Ollama si ``OLLAMA_MODEL`` está definido. Lanza ``ErrorProveedor`` si no hay proveedor configurado, si el nombre no se conoce
    o si falta la configuración del elegido.
    """
    env = leer_local_env() if env is None else env
    cfg = cfg or cargar_llm()
    nombre = (env.get("LLM_PROVIDER") or "").strip().lower()
    if not nombre:
        raise ErrorProveedor("LLM_PROVIDER no está definido en local.env")
    if nombre == PROVEEDOR_OLLAMA:
        from src.llm.ollama import ProveedorOllama

        modelo = (env.get("OLLAMA_MODEL") or "").strip()
        if not modelo:
            raise ErrorProveedor("OLLAMA_MODEL no está definido en local.env")
        return ProveedorOllama(env.get("OLLAMA_HOST") or cfg.ollama.host_por_defecto, modelo, cfg)
    if nombre == PROVEEDOR_DEEPSEEK:
        return _crear_deepseek(env, cfg)
    raise ErrorProveedor(f"LLM_PROVIDER desconocido: {nombre!r}")


def _crear_deepseek(env: Mapping[str, str], cfg: ConfigLlm) -> Proveedor:
    from src.configuracion import cargar_generacion
    from src.llm.costo import ProveedorConTope, RegistroCosto
    from src.llm.deepseek import ProveedorDeepSeek
    from src.llm.ollama import ProveedorOllama

    clave = (env.get("DEEPSEEK_API_KEY") or "").strip()
    if not clave:
        raise ErrorProveedor("DEEPSEEK_API_KEY no está definido en local.env")
    gen = cargar_generacion()
    modelo_local = (env.get("OLLAMA_MODEL") or "").strip()
    respaldo = ProveedorOllama(env.get("OLLAMA_HOST") or cfg.ollama.host_por_defecto, modelo_local, cfg) if modelo_local else None
    registro = RegistroCosto(RAIZ / gen.tope_costo.registro)
    return ProveedorConTope(ProveedorDeepSeek(clave, gen, cfg), respaldo, registro, gen.tope_costo, gen.deepseek.precio_usd_por_millon_tokens)
