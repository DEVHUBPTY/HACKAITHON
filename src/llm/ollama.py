"""Adaptador del proveedor primario: Ollama local.

Cliente HTTP mínimo (``/api/chat``, ``/api/ps``, ``/api/tags``, ``/api/version``). El host sale de
``local.env`` (``OLLAMA_HOST``), nunca de la variable de entorno del shell. El cliente HTTP se
inyecta para poder simularlo en las pruebas.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

import requests

from src.configuracion import ConfigLlm
from src.llm.proveedor import ErrorProveedor, UsoLlm, registrar_uso

log = logging.getLogger(__name__)


class SesionHttp(Protocol):
    """Subconjunto de ``requests.Session`` que usa el cliente."""

    def get(self, url: str, **kwargs: Any) -> Any: ...

    def post(self, url: str, **kwargs: Any) -> Any: ...


class ErrorOllama(RuntimeError):
    """Fallo de transporte o respuesta no 2xx de Ollama."""


def normalizar_host(host: str) -> str:
    """``127.0.0.1:11434`` o ``http://localhost:11434/`` → URL base sin barra final."""
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host


class ClienteOllama:
    """Cliente de la API HTTP de Ollama."""

    def __init__(
        self,
        host: str,
        timeout_segundos: float,
        sesion: SesionHttp | None = None,
    ) -> None:
        self.host = normalizar_host(host)
        self.timeout = timeout_segundos
        self.sesion: SesionHttp = sesion or requests.Session()

    def _pedir(self, metodo: str, ruta: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.host}{ruta}"
        try:
            resp = getattr(self.sesion, metodo)(url, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ErrorOllama(f"{metodo.upper()} {ruta}: {exc}") from exc

    def version(self) -> str:
        return str(self._pedir("get", "/api/version").get("version", "desconocida"))

    def modelos(self) -> list[dict[str, Any]]:
        return list(self._pedir("get", "/api/tags").get("models", []))

    def digest(self, modelo: str) -> str | None:
        """Digest del modelo descargado (``None`` si no está)."""
        for m in self.modelos():
            if m.get("name") == modelo or m.get("model") == modelo:
                return m.get("digest")
        return None

    def cargados(self) -> list[dict[str, Any]]:
        """Modelos en memoria (``/api/ps``): incluye ``size`` y ``size_vram`` en bytes."""
        return list(self._pedir("get", "/api/ps").get("models", []))

    def chat(
        self,
        modelo: str,
        system: str,
        usuario: str,
        esquema: dict[str, Any],
        opciones: dict[str, Any],
        pensar: bool,
        keep_alive: str | int,
    ) -> dict[str, Any]:
        """Una llamada a ``/api/chat`` sin streaming, con salida estructurada (``format``)."""
        cuerpo = {
            "model": modelo,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": usuario},
            ],
            "format": esquema,
            "think": pensar,
            "stream": False,
            "options": opciones,
            "keep_alive": keep_alive,
        }
        return self._pedir("post", "/api/chat", json=cuerpo)

    def descargar(self, modelo: str) -> None:
        """Saca el modelo de memoria (``keep_alive`` 0)."""
        self._pedir("post", "/api/generate", json={"model": modelo, "keep_alive": 0})
        log.info("Modelo descargado de memoria: %s", modelo)


class ProveedorOllama:
    """``Proveedor`` sobre Ollama local: salida estructurada (``format``), temperatura y semilla de ``config/llm.yaml``."""

    nombre = "ollama"

    def __init__(self, host: str, modelo: str, cfg: ConfigLlm, sesion: SesionHttp | None = None) -> None:
        self.modelo = modelo
        self.cfg = cfg
        self.cliente = ClienteOllama(host, cfg.ollama.timeout_segundos, sesion)
        self.ultimo_uso: UsoLlm | None = None

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        g = self.cfg.generacion
        opciones = {"temperature": g.temperatura, "seed": g.semilla, "num_ctx": g.num_ctx, "num_predict": g.num_predict}
        inicio = time.perf_counter()
        try:
            resp = self.cliente.chat(self.modelo, system, usuario, esquema, opciones, g.pensar, self.cfg.ollama.keep_alive_durante_prueba)
        except ErrorOllama as exc:
            raise ErrorProveedor(str(exc)) from exc
        self.ultimo_uso = UsoLlm(
            self.nombre, self.modelo, int(resp.get("prompt_eval_count") or 0), int(resp.get("eval_count") or 0), time.perf_counter() - inicio
        )
        registrar_uso(self.ultimo_uso)
        contenido = resp.get("message", {}).get("content")
        if not isinstance(contenido, str) or not contenido.strip():
            raise ErrorProveedor("Ollama devolvió una respuesta vacía")
        return contenido
