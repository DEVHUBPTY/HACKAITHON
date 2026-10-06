"""Embeddings locales de titulares para clasificación, agrupación y consulta (E1-07, D-03, D-20).

* Siempre locales: ``sentence-transformers`` con un modelo fijado por id y revisión exactos en
  ``config/clasificacion.yaml``. Nunca se llama a una API de embeddings.
* Sin internet después de la primera descarga: se intenta primero con ``local_files_only`` y solo si el modelo no está
  en la caché local se descarga (una vez). Con ``HF_HUB_OFFLINE=1`` nunca se descarga.
* Los vectores salen normalizados (norma 1), así que el producto punto es la similitud coseno.
* Caché en disco por modelo y revisión: la clave es el SHA-256 del texto con su prefijo; **el texto nunca se
  guarda** (el texto puede incluir la descripción del RSS, de uso solo interno, D-31).
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

from src.configuracion import RAIZ, ConfigClasificacion, ModeloEmbeddings, cargar_clasificacion

logger = logging.getLogger(__name__)

Rol = Literal["titular", "tema"]
ROLES: tuple[Rol, ...] = ("titular", "tema")
LARGO_CLAVE = 32  # caracteres hexadecimales de la clave de caché (128 bits: sin colisiones en la práctica)


class Motor(Protocol):
    """Lo mínimo que se le pide a un codificador: textos (ya con su prefijo) -> matriz sin normalizar."""

    def codificar(self, textos: list[str]) -> np.ndarray: ...


class MotorSentenceTransformers:
    """``sentence-transformers`` en local. El modelo se carga la primera vez que se necesita."""

    def __init__(self, modelo: ModeloEmbeddings, cfg: ConfigClasificacion, raiz: Path = RAIZ) -> None:
        self.modelo = modelo
        self.cfg = cfg
        self.carpeta = raiz / cfg.carpetas.modelos
        self._st = None

    def _cargar(self):  # noqa: ANN202 - tipo de una librería opcional pesada
        from sentence_transformers import SentenceTransformer

        argumentos = {
            "revision": self.modelo.revision,
            "cache_folder": str(self.carpeta),
            "device": self.cfg.dispositivo,
        }
        try:
            return SentenceTransformer(self.modelo.id, local_files_only=True, **argumentos)
        except (OSError, ValueError) as exc:
            if os.environ.get("HF_HUB_OFFLINE") == "1" or os.environ.get("TRANSFORMERS_OFFLINE") == "1":
                raise RuntimeError(
                    f"el modelo {self.modelo.id}@{self.modelo.revision[:8]} no está en {self.carpeta} y el modo "
                    "sin conexión está activo: ejecute una vez con internet para descargarlo"
                ) from exc
            logger.warning("Modelo %s no está en la caché local; se descarga una sola vez", self.modelo.id)
            return SentenceTransformer(self.modelo.id, **argumentos)

    def codificar(self, textos: list[str]) -> np.ndarray:
        if self._st is None:
            fijar_semilla(self.cfg.semilla)
            self._st = self._cargar()
        return np.asarray(
            self._st.encode(textos, batch_size=self.cfg.lote, convert_to_numpy=True, show_progress_bar=False),
            dtype=np.float32,
        )


def fijar_semilla(semilla: int) -> None:
    """Semilla de ``random``, numpy y torch (si está instalado): dos corridas dan los mismos vectores."""
    random.seed(semilla)
    np.random.seed(semilla)  # noqa: NPY002 - semilla global a propósito: la fijan las librerías que la usan
    try:
        import torch

        torch.manual_seed(semilla)
    except ImportError:  # pragma: no cover - torch es dependencia de sentence-transformers
        pass


def normalizar(matriz: np.ndarray) -> np.ndarray:
    """Cada fila con norma 1 (una fila de ceros se deja en ceros)."""
    m = np.asarray(matriz, dtype=np.float32)
    normas = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(normas == 0, 1.0, normas)


def clave_cache(prefijo: str, texto: str) -> str:
    """Clave de caché: hash del texto con su prefijo. No es reversible: el texto no se guarda."""
    return hashlib.sha256(f"{prefijo}{texto}".encode()).hexdigest()[:LARGO_CLAVE]


def _slug(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", texto).strip("-")


class Embeddings:
    """Codifica textos con un modelo y los guarda en disco: pedir el mismo texto otra vez no vuelve a codificarlo."""

    def __init__(
        self,
        modelo: ModeloEmbeddings,
        cfg: ConfigClasificacion,
        motor: Motor | None = None,
        raiz: Path | None = None,
        usar_cache: bool = True,
    ) -> None:
        # Un motor inyectado (pruebas) sin una raíz propia NO toca la caché real: sus vectores no son los del modelo.
        usar_cache = usar_cache and not (motor is not None and raiz is None)
        raiz = raiz or RAIZ
        self.modelo = modelo
        self.motor: Motor = motor or MotorSentenceTransformers(modelo, cfg, raiz)
        self.usar_cache = usar_cache
        self.ruta_cache = raiz / cfg.carpetas.embeddings / f"{_slug(modelo.id)}__{modelo.revision[:12]}.npz"
        self._vectores: dict[str, np.ndarray] = {}
        self.codificados = 0   # cuántos textos pasaron por el motor en esta instancia (para medir la caché)
        self.aciertos_cache = 0
        if usar_cache:
            self._leer_cache()

    # -- caché ---------------------------------------------------------------------------------------

    def _leer_cache(self) -> None:
        if not self.ruta_cache.exists():
            return
        try:
            with np.load(self.ruta_cache, allow_pickle=False) as datos:
                self._vectores = dict(zip(datos["claves"].tolist(), datos["vectores"], strict=True))
        except (OSError, ValueError, KeyError) as exc:  # caché dañada: se descarta, no se confía en ella
            logger.warning("Caché de embeddings ilegible (%s); se vuelve a calcular", exc)
            self._vectores = {}

    def _guardar_cache(self) -> None:
        if not self.usar_cache or not self._vectores:
            return
        self.ruta_cache.parent.mkdir(parents=True, exist_ok=True)
        claves = sorted(self._vectores)
        temporal = self.ruta_cache.with_name(self.ruta_cache.name + ".tmp.npz")
        np.savez_compressed(temporal, claves=np.array(claves), vectores=np.stack([self._vectores[c] for c in claves]))
        os.replace(temporal, self.ruta_cache)

    # -- API -----------------------------------------------------------------------------------------

    def prefijo(self, rol: Rol) -> str:
        """Prefijo del modelo para el rol: el titular es la consulta; la descripción, los ejemplos y los prototipos son los pasajes."""
        if rol == "titular":
            return self.modelo.prefijo_titular
        if rol == "tema":
            return self.modelo.prefijo_tema
        raise ValueError(f"rol desconocido: {rol!r}")

    def codificar(self, textos: Sequence[str], rol: Rol) -> np.ndarray:
        """Matriz ``(len(textos), dimensión)`` de vectores normalizados, en el orden de ``textos``."""
        if not textos:
            return np.zeros((0, 0), dtype=np.float32)
        prefijo = self.prefijo(rol)
        claves = [clave_cache(prefijo, t) for t in textos]
        faltan: dict[str, str] = {}
        for clave, texto in zip(claves, textos, strict=True):
            if clave in self._vectores:
                self.aciertos_cache += 1
            else:
                faltan.setdefault(clave, texto)
        if faltan:
            nuevos = normalizar(self.motor.codificar([f"{prefijo}{t}" for t in faltan.values()]))
            self.codificados += len(faltan)
            self._vectores.update(zip(faltan, nuevos, strict=True))
            self._guardar_cache()
        return np.stack([self._vectores[c] for c in claves])


def crear(
    cfg: ConfigClasificacion | None = None, nombre: str | None = None, motor: Motor | None = None, **kwargs
) -> Embeddings:
    """``Embeddings`` del modelo ``nombre`` (por defecto ``modelo_activo``) de ``config/clasificacion.yaml``."""
    cfg = cfg or cargar_clasificacion()
    return Embeddings(cfg.modelos[nombre or cfg.modelo_activo], cfg, motor=motor, **kwargs)
