"""Tope de costo del proveedor de pago (D-67, D-95): al alcanzarlo, la generación se detiene con un error explícito.

``RegistroCosto`` acumula tokens y USD (y los guarda entre ejecuciones si tiene ruta). ``ProveedorConTope`` envuelve al
proveedor de pago: antes de cada llamada mira el acumulado; si ya alcanzó el tope de tokens o de USD, no llama y lanza
``TopeDeCostoAlcanzado`` (D-95: DeepSeek es el único proveedor de generación; no hay respaldo local). El tope se mide **antes** de llamar, así que una sola llamada puede rebasarlo por su
propio tamaño; el costo real de esa llamada queda contado.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.configuracion import PreciosDeepSeek, TopeCostoConfig
from src.llm.proveedor import ErrorProveedor, UsoLlm

log = logging.getLogger(__name__)
UN_MILLON = 1_000_000


class TopeDeCostoAlcanzado(ErrorProveedor):
    """Se alcanzó el tope de costo (D-67): no se hacen más llamadas al proveedor de pago hasta que una persona lo suba."""


class SaldoAgotado(TopeDeCostoAlcanzado):
    """DeepSeek respondió «Insufficient Balance» (HTTP 402, D-98): no queda saldo en la cuenta. No se reintenta; la generación se detiene."""


class RegistroCosto:
    """Tokens y USD acumulados del proveedor de pago, con persistencia opcional en JSON."""

    def __init__(self, ruta: Path | None = None) -> None:
        self.ruta = ruta
        self.tokens = 0
        self.usd = 0.0
        if ruta is not None:
            try:
                texto = ruta.read_text(encoding="utf-8")
            except FileNotFoundError:
                return  # primer uso: acumulado en cero
            except OSError as exc:
                raise ErrorProveedor(f"no se pudo leer el registro de costo {ruta.name}: {exc}") from exc
            try:
                datos = json.loads(texto)
                self.tokens, self.usd = int(datos["tokens"]), float(datos["usd"])
            except (ValueError, KeyError, TypeError) as exc:
                # Falla cerrado: reiniciar el acumulado en silencio permitiría gastar por encima del tope (D-67).
                raise ErrorProveedor(
                    f"el registro de costo {ruta.name} está corrupto ({type(exc).__name__}); revíselo o bórrelo a mano para reiniciar el acumulado"
                ) from exc

    def sumar(self, uso: UsoLlm, precios: PreciosDeepSeek) -> None:
        self.tokens += uso.tokens_entrada + uso.tokens_salida
        self.usd += (uso.tokens_entrada * precios.entrada + uso.tokens_salida * precios.salida) / UN_MILLON
        if self.ruta is not None:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps({"tokens": self.tokens, "usd": round(self.usd, 6)}, indent=2) + "\n", encoding="utf-8")

    def agotado(self, tope: TopeCostoConfig) -> bool:
        return self.tokens >= tope.tokens or self.usd >= tope.usd


class ProveedorConTope:
    """Proveedor de pago con tope de costo. Al alcanzarlo lanza ``TopeDeCostoAlcanzado`` y no llama."""

    def __init__(self, principal: Any, registro: RegistroCosto, tope: TopeCostoConfig, precios: PreciosDeepSeek) -> None:
        self.principal, self.registro, self.tope, self.precios = principal, registro, tope, precios
        self.ultimo_uso: UsoLlm | None = None

    @property
    def nombre(self) -> str:
        return str(self.principal.nombre)

    @property
    def modelo(self) -> str:
        return str(self.principal.modelo)

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        if self.registro.agotado(self.tope):
            log.error(
                "tope de costo alcanzado (tokens=%d de %d, usd=%.4f de %.2f): la generación se detiene",
                self.registro.tokens, self.tope.tokens, self.registro.usd, self.tope.usd,
            )
            raise TopeDeCostoAlcanzado(
                f"Se alcanzó el tope de costo de generación ({self.registro.tokens} de {self.tope.tokens} tokens; "
                f"USD {self.registro.usd:.4f} de {self.tope.usd:.2f}). No se hacen más llamadas hasta que una persona suba el tope "
                "en config/generacion.yaml o reinicie outputs/costo_llm.json."
            )
        texto = self.principal.generar_json(system, usuario, esquema)
        self.ultimo_uso = getattr(self.principal, "ultimo_uso", None)
        if self.ultimo_uso is not None:
            self.registro.sumar(self.ultimo_uso, self.precios)
        return texto
