"""Interfaz común de proveedores LLM, elegida por configuración (``LLM_PROVIDER`` de ``local.env``, nunca hardcodeada).

El LLM no tiene herramientas ni acciones: solo recibe un mensaje de sistema (reglas) y uno de usuario (la evidencia dentro de
``<evidencia>…</evidencia>`` y como dato, nunca instrucción) y devuelve **texto JSON**, que el llamador valida con pydantic.
Temperatura 0 y semilla fija salen de ``config/llm.yaml``.

Un proveedor que no existe, no está configurado o no responde lanza ``ErrorProveedor``; quien lo usa decide cómo degradar
(``src/contradicciones.py`` deja los candidatos pendientes y sigue).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from src.configuracion import ConfigLlm, cargar_llm, leer_local_env

PROVEEDOR_OLLAMA = "ollama"
PROVEEDOR_DEEPSEEK = "deepseek"


class ErrorProveedor(RuntimeError):
    """El proveedor no está disponible o no devolvió una respuesta utilizable."""


class Proveedor(Protocol):
    """Lo mínimo que se le pide a un proveedor: una llamada con salida JSON estructurada."""

    nombre: str
    modelo: str

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        """Texto JSON de la respuesta (sin validar). Lanza ``ErrorProveedor`` si falla el transporte o no hay respuesta."""
        ...


def crear_proveedor(env: Mapping[str, str] | None = None, cfg: ConfigLlm | None = None) -> Proveedor:
    """El proveedor que dice ``LLM_PROVIDER`` en ``local.env`` (``env`` permite inyectarlo en pruebas).

    Lanza ``ErrorProveedor`` si no hay proveedor configurado, si el nombre no se conoce o si el adaptador no existe todavía.
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
        raise ErrorProveedor("el adaptador de DeepSeek todavía no existe (respaldo provisional con tope de costo, D-67 y D-80)")
    raise ErrorProveedor(f"LLM_PROVIDER desconocido: {nombre!r}")
