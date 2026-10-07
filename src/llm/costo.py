"""Tope de costo del proveedor de pago (D-67): al alcanzarlo, la siguiente llamada usa el modelo local.

``RegistroCosto`` acumula tokens y USD (y los guarda entre ejecuciones si tiene ruta). ``ProveedorConTope`` envuelve al
proveedor de pago y al local: antes de cada llamada mira el acumulado; si ya alcanzó el tope de tokens o de USD, deriva la
llamada al respaldo local y lo registra. El tope se mide **antes** de llamar, así que una sola llamada puede rebasarlo por su
propio tamaño; el costo real de esa llamada queda contado.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.configuracion import PreciosDeepSeek, TopeCostoConfig
from src.llm.proveedor import ErrorProveedor, Proveedor, UsoLlm

log = logging.getLogger(__name__)
UN_MILLON = 1_000_000


class RegistroCosto:
    """Tokens y USD acumulados del proveedor de pago, con persistencia opcional en JSON."""

    def __init__(self, ruta: Path | None = None) -> None:
        self.ruta = ruta
        self.tokens = 0
        self.usd = 0.0
        if ruta is not None:
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
                self.tokens, self.usd = int(datos["tokens"]), float(datos["usd"])
            except (OSError, ValueError, KeyError, TypeError):
                pass

    def sumar(self, uso: UsoLlm, precios: PreciosDeepSeek) -> None:
        self.tokens += uso.tokens_entrada + uso.tokens_salida
        self.usd += (uso.tokens_entrada * precios.entrada + uso.tokens_salida * precios.salida) / UN_MILLON
        if self.ruta is not None:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps({"tokens": self.tokens, "usd": round(self.usd, 6)}, indent=2) + "\n", encoding="utf-8")

    def agotado(self, tope: TopeCostoConfig) -> bool:
        return self.tokens >= tope.tokens or self.usd >= tope.usd


class ProveedorConTope:
    """Proveedor de pago con respaldo local al alcanzar el tope. ``nombre`` y ``modelo`` son los de la última llamada."""

    def __init__(
        self,
        principal: Any,
        respaldo: Proveedor | None,
        registro: RegistroCosto,
        tope: TopeCostoConfig,
        precios: PreciosDeepSeek,
    ) -> None:
        self.principal, self.respaldo, self.registro, self.tope, self.precios = principal, respaldo, registro, tope, precios
        self._activo: Any = principal
        self.ultimo_uso: UsoLlm | None = None

    @property
    def nombre(self) -> str:
        return str(self._activo.nombre)

    @property
    def modelo(self) -> str:
        return str(self._activo.modelo)

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        if self.registro.agotado(self.tope):
            if self.respaldo is None:
                raise ErrorProveedor("tope de costo alcanzado y no hay modelo local configurado (OLLAMA_MODEL)")
            log.warning(
                "tope de costo alcanzado (tokens=%d de %d, usd=%.4f de %.2f): la llamada usa el modelo local %s",
                self.registro.tokens, self.tope.tokens, self.registro.usd, self.tope.usd, self.respaldo.modelo,
            )
            self._activo = self.respaldo
            texto = self.respaldo.generar_json(system, usuario, esquema)
            self.ultimo_uso = getattr(self.respaldo, "ultimo_uso", None)
            return texto
        self._activo = self.principal
        texto = self.principal.generar_json(system, usuario, esquema)
        self.ultimo_uso = getattr(self.principal, "ultimo_uso", None)
        if self.ultimo_uso is not None:
            self.registro.sumar(self.ultimo_uso, self.precios)
        return texto
