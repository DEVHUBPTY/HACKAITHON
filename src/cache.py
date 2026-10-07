"""Caché de respuestas del LLM y soporte del modo offline (E1-14, T10; D-44, D-94, D-95, D-97, D-98).

**Qué se guarda.** La respuesta cruda (texto JSON) de cada llamada al proveedor, un archivo por respuesta en
``config/cache.yaml:ruta`` (``data/cache_llm/<clave>.json``). No se guardan prompts, evidencia ni claves: solo la respuesta, el
proveedor, el modelo, la versión del prompt y las cifras de uso. Se guarda también una respuesta inválida (la validación la descarta al leer, igual que al generar).

**Clave determinista** = SHA-256 de: versión de la caché · proveedor · modelo · versión del prompt · temperatura y semilla · mensaje de
sistema · mensaje de usuario (la evidencia) · esquema de salida. Cualquier cambio en la ficha, el prompt, el esquema o el modelo da otra
clave, así que una respuesta vieja nunca se sirve para otra petición. ``version_cache`` invalida todo a mano.

**Por qué en la llamada al proveedor.** Se cachea cada llamada (paso 1, cada grupo del paso 2 y cada reintento), no solo el paquete
final. La validación se vuelve a ejecutar siempre sobre la respuesta cacheada, de modo que un validador más estricto (E1-13) se aplica a
los borradores guardados sin llamar de nuevo al proveedor.

**Offline (T10).** ``ProveedorSoloCache`` nunca abre una conexión: responde desde la caché o lanza ``SinCache``. La interfaz lo usa
siempre; la generación nueva (``solo_cache=False``) solo ocurre si ``red_disponible`` confirma que hay red y no se pidió el modo offline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.configuracion import RAIZ, ConfigCache, cargar_cache, cargar_generacion, cargar_llm, leer_local_env
from src.llm.proveedor import ErrorProveedor, Proveedor, UsoLlm

log = logging.getLogger(__name__)
VALORES_VERDADEROS = {"1", "true", "si", "sí", "yes"}


class SinCache(ErrorProveedor):
    """No hay respuesta guardada para esta petición y no se puede (o no se debe) llamar al proveedor."""


class SinBorrador(Exception):
    """No hay borrador que mostrar para un grupo: sin caché, desajuste de proveedor o una acción de la ficha que no genera borrador.
    El mensaje es para la persona; ``por_accion`` distingue el último caso (no es un fallo de la caché)."""

    def __init__(self, mensaje: str, *, por_accion: bool = False) -> None:
        super().__init__(mensaje)
        self.por_accion = por_accion


def clave_de(
    proveedor: str, modelo: str, version_prompt: str, system: str, usuario: str, esquema: Mapping[str, Any],
    temperatura: float, semilla: int, version_cache: str,
) -> str:
    """SHA-256 (hex) de la petición completa: lo que cambie en cualquiera de sus partes cambia la clave."""
    carga = {
        "version_cache": version_cache, "proveedor": proveedor, "modelo": modelo, "version_prompt": version_prompt,
        "temperatura": temperatura, "semilla": semilla, "system": system, "usuario": usuario, "esquema": esquema,
    }
    texto = json.dumps(carga, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


class CacheLlm:
    """Archivos ``<clave>.json`` en una carpeta. Un archivo ilegible o que no corresponde a su clave cuenta como ausente."""

    def __init__(self, carpeta: Path | None = None, cfg: ConfigCache | None = None) -> None:
        self.cfg = cfg or cargar_cache()
        self.carpeta = carpeta if carpeta is not None else RAIZ / self.cfg.ruta
        self.usadas: set[str] = set()  # claves leídas con éxito: lo que una verificación completa necesita (E1-13, ``podar``)
        self.prompts_usados: set[str] = set()  # X56: nombres de prompt de las lecturas con éxito: el alcance de una poda por modalidad

    def _ruta(self, clave: str) -> Path:
        return self.carpeta / f"{clave}.json"

    def obtener(self, clave: str, prompt: str = "") -> str | None:
        try:
            datos = json.loads(self._ruta(clave).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("entrada de caché ilegible %s…: %s", clave[:12], type(exc).__name__)
            return None
        respuesta = datos.get("respuesta") if isinstance(datos, dict) else None
        if not isinstance(datos, dict) or datos.get("clave") != clave or not isinstance(respuesta, str) or not respuesta.strip():
            log.warning("entrada de caché inválida %s…: se ignora", clave[:12])
            return None
        self.usadas.add(clave)
        if prompt:
            self.prompts_usados.add(prompt)
        return respuesta

    def podar(self, conservar: set[str] | None = None, prompts: set[str] | None = None) -> int:
        """Borra las respuestas que ya nadie usa (de prompts o validadores anteriores): todas las que no estén en ``conservar`` (por defecto,
        las leídas con éxito en esta ejecución). Devuelve cuántas borró.

        X56: con ``prompts`` solo se consideran las entradas cuyo ``prompt`` guardado esté en ese conjunto; las de otros prompts (otra modalidad)
        y las que no registran su prompt (anteriores a X56, no se sabe de quién son) se conservan."""
        conservar = self.usadas if conservar is None else conservar
        borradas = 0
        for archivo in self.carpeta.glob("*.json") if self.carpeta.exists() else []:
            if archivo.stem in conservar:
                continue
            if prompts is not None:
                try:
                    propio = json.loads(archivo.read_text(encoding="utf-8")).get("prompt")
                except (OSError, ValueError, AttributeError):
                    propio = None
                if propio not in prompts:
                    continue
            archivo.unlink()
            borradas += 1
        return borradas

    def guardar(self, clave: str, respuesta: str, meta: Mapping[str, Any]) -> bool:
        """Guarda la respuesta (escritura atómica), sea o no JSON válido: el reintento de la generación depende de que la primera
        respuesta (inválida) se repita igual al leer, o la caché parecería incompleta. ``refrescar`` la reemplaza."""
        if not respuesta.strip():
            return False
        entrada = {"clave": clave, **meta, "creado_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "respuesta": respuesta}
        self.carpeta.mkdir(parents=True, exist_ok=True)
        destino = self._ruta(clave)
        # nombre único en la misma carpeta: dos procesos que escriben la misma clave no se pisan el temporal
        descriptor, nombre = tempfile.mkstemp(dir=self.carpeta, prefix=f"{clave}.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as f:
                f.write(json.dumps(entrada, ensure_ascii=False, indent=1) + "\n")
            os.replace(nombre, destino)
        except BaseException:
            Path(nombre).unlink(missing_ok=True)
            raise
        return True

    def identidades(self) -> set[tuple[str, str]]:
        """``(proveedor, modelo)`` con que se calentaron las entradas legibles de la caché."""
        salida: set[tuple[str, str]] = set()
        for archivo in self.carpeta.glob("*.json") if self.carpeta.exists() else []:
            try:
                datos = json.loads(archivo.read_text(encoding="utf-8"))
                salida.add((str(datos["proveedor"]), str(datos["modelo"])))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return salida

    def __len__(self) -> int:
        return sum(1 for _ in self.carpeta.glob("*.json")) if self.carpeta.exists() else 0


@dataclass(frozen=True)
class Identidad:
    """Proveedor y modelo con que se escribió o se lee la caché (sin crear el proveedor ni tocar la red)."""

    proveedor: str
    modelo: str


def identidad_de(env: Mapping[str, str] | None = None, cfg: ConfigCache | None = None) -> Identidad:
    """Proveedor y modelo con que se lee la caché: ``LLM_PROVIDER`` de ``local.env`` o, si está vacío, ``proveedor_por_defecto`` de
    ``config/cache.yaml`` (D-94, D-95). Lanza ``ErrorProveedor`` si el proveedor elegido no tiene modelo definido."""
    env = leer_local_env() if env is None else env
    nombre = (env.get("LLM_PROVIDER") or "").strip().lower() or (cfg or cargar_cache()).proveedor_por_defecto
    if nombre == "deepseek":
        return Identidad(nombre, (env.get("DEEPSEEK_MODEL") or "").strip() or cargar_generacion().deepseek.modelo)
    if nombre == "ollama":
        modelo = (env.get("OLLAMA_MODEL") or "").strip()
        if modelo:
            return Identidad(nombre, modelo)
    raise ErrorProveedor(f"el proveedor {nombre!r} no tiene modelo definido en local.env")


class _ConClave:
    """Cálculo de la clave compartido por los dos proveedores de caché."""

    def __init__(self, cache: CacheLlm, nombre: str, modelo: str) -> None:
        self.cache, self.nombre, self.modelo = cache, nombre, modelo
        llm = cargar_llm().generacion
        self._temperatura, self._semilla = llm.temperatura, llm.semilla

    def clave(self, version: str, system: str, usuario: str, esquema: Mapping[str, Any]) -> str:
        return clave_de(
            self.nombre, self.modelo, version, system, usuario, esquema, self._temperatura, self._semilla, self.cache.cfg.version_cache
        )


class ProveedorSoloCache(_ConClave):
    """Responde solo desde la caché: nunca abre una conexión. Una petición sin respuesta guardada lanza ``SinCache``."""

    def __init__(self, cache: CacheLlm, identidad: Identidad) -> None:
        super().__init__(cache, identidad.proveedor, identidad.modelo)
        self.ultimo_uso: UsoLlm | None = None
        self.aciertos = 0
        self.fallos = 0

    def generar_json_versionado(self, version: str, system: str, usuario: str, esquema: dict[str, Any], prompt: str = "") -> str:
        respuesta = self.cache.obtener(self.clave(version, system, usuario, esquema), prompt)
        if respuesta is None:
            self.fallos += 1
            raise SinCache(self.cache.cfg.textos.sin_cache)
        self.aciertos += 1
        return respuesta

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        return self.generar_json_versionado("", system, usuario, esquema)


class ProveedorConCache(_ConClave):
    """Envuelve a un proveedor: la segunda petición idéntica sale de la caché y no llega al proveedor."""

    def __init__(self, proveedor: Proveedor, cache: CacheLlm, refrescar: bool = False) -> None:
        super().__init__(cache, proveedor.nombre, proveedor.modelo)
        self.proveedor, self.refrescar = proveedor, refrescar
        self.ultimo_uso: UsoLlm | None = None
        self.aciertos = 0
        self.fallos = 0

    def generar_json_versionado(self, version: str, system: str, usuario: str, esquema: dict[str, Any], prompt: str = "") -> str:
        clave = self.clave(version, system, usuario, esquema)
        if not self.refrescar and (respuesta := self.cache.obtener(clave, prompt)) is not None:
            self.aciertos += 1
            self.ultimo_uso = None
            return respuesta
        self.fallos += 1
        respuesta = self.proveedor.generar_json(system, usuario, esquema)  # un error del proveedor (o el tope) sube sin guardar nada
        uso = getattr(self.proveedor, "ultimo_uso", None)
        self.ultimo_uso = uso
        self.cache.guardar(
            clave, respuesta,
            {
                "proveedor": self.nombre, "modelo": self.modelo, "version_prompt": version, "prompt": prompt, "version_cache": self.cache.cfg.version_cache,
                "tokens_entrada": uso.tokens_entrada if uso else 0, "tokens_salida": uso.tokens_salida if uso else 0,
            },
        )
        return respuesta

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        return self.generar_json_versionado("", system, usuario, esquema)


# ------------------------------------------------------------------ red


def modo_offline(env: Mapping[str, str] | None = None, cfg: ConfigCache | None = None) -> bool:
    """``True`` si ``local.env`` pide el modo offline (``HACKIATHON_OFFLINE=true``): no se llama al proveedor aunque haya red."""
    cfg = cfg or cargar_cache()
    env = leer_local_env() if env is None else env
    return (env.get(cfg.variable_offline) or os.environ.get(cfg.variable_offline) or "").strip().lower() in VALORES_VERDADEROS


def red_disponible(base_url: str | None = None, cfg: ConfigCache | None = None) -> bool:
    """Sondeo corto (``sondeo_red``) al host del proveedor de pago. Cualquier fallo de red o de DNS es «sin red»: nunca bloquea."""
    cfg = cfg or cargar_cache()
    host = urlparse(base_url or cargar_generacion().deepseek.base_url).hostname
    if not host:
        return False
    try:
        with socket.create_connection((host, cfg.sondeo_red.puerto), timeout=cfg.sondeo_red.timeout_segundos):
            return True
    except OSError:
        return False
