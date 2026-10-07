"""Adaptador del proveedor de pago DeepSeek (respaldo provisional, D-80), siempre detrás de un tope de costo (D-67).

API compatible con OpenAI: ``POST {base_url}/chat/completions``. Salida JSON con ``response_format`` (el esquema va en el
system prompt, que debe nombrar «JSON»), temperatura de ``config/llm.yaml`` y sin herramientas. La clave viaja solo en el
encabezado ``Authorization`` y nunca se registra ni aparece en los errores (D-69). El cliente HTTP se inyecta para las pruebas.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from src.configuracion import ConfigGeneracionBorrador, ConfigLlm
from src.llm.ollama import SesionHttp
from src.llm.proveedor import ErrorProveedor, UsoLlm, registrar_uso
from src.registro import redactar


class ProveedorDeepSeek:
    """``Proveedor`` sobre la API de DeepSeek."""

    nombre = "deepseek"

    def __init__(self, clave: str, gen: ConfigGeneracionBorrador, cfg: ConfigLlm, sesion: SesionHttp | None = None) -> None:
        self._clave = clave
        self.modelo = gen.deepseek.modelo
        self._gen, self._cfg = gen, cfg
        self.sesion: SesionHttp = sesion or requests.Session()
        self.ultimo_uso: UsoLlm | None = None

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        d = self._gen.deepseek
        cuerpo = {
            "model": d.modelo,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": usuario}],
            "temperature": self._cfg.generacion.temperatura,
            "max_tokens": d.max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        inicio = time.perf_counter()
        try:
            resp = self.sesion.post(
                f"{d.base_url.rstrip('/')}/chat/completions",
                json=cuerpo,
                headers={"Authorization": f"Bearer {self._clave}", "Content-Type": "application/json"},
                timeout=d.timeout_segundos,
            )
            resp.raise_for_status()
            datos = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ErrorProveedor(redactar(f"DeepSeek: {exc}").replace(self._clave, "[REDACTADO]")) from exc
        try:
            contenido = datos["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ErrorProveedor("DeepSeek devolvió una respuesta sin contenido") from exc
        if not isinstance(contenido, str) or not contenido.strip():
            raise ErrorProveedor("DeepSeek devolvió una respuesta vacía")
        uso = datos.get("usage") or {}
        self.ultimo_uso = UsoLlm(
            self.nombre, self.modelo, int(uso.get("prompt_tokens") or 0), int(uso.get("completion_tokens") or 0), time.perf_counter() - inicio
        )
        registrar_uso(self.ultimo_uso)
        return contenido
