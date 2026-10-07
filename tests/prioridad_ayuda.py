"""Ayudas de las pruebas de E1-10: grupos sintéticos, vectores y un proveedor de LLM falso (nunca se llama a uno real)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np

from src.configuracion import cargar_prioridad, cargar_reglas
from src.llm.proveedor import ErrorProveedor
from src.puntaje import EntradaGrupo

AHORA = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
REGLAS = cargar_reglas()
CFG = cargar_prioridad()


def iso(horas_antes: float) -> str:
    """Fecha ISO 8601 UTC ``horas_antes`` horas antes de ``AHORA``."""
    from datetime import timedelta

    return (AHORA - timedelta(hours=horas_antes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def miembro(
    id_noticia: str = "NOT-0000000001",
    titulo: str = "Titular de prueba",
    medio: str = "prensa.com",
    publicado_hace: float | None = 2,
    detectado_hace: float | None = None,
    regional: bool = False,
    similitud: float = 0.8,
    recirculada: bool | None = None,
) -> dict[str, Any]:
    """Una fila de ``noticias`` con los campos que usa el puntaje."""
    return {
        "id_noticia": id_noticia,
        "titulo_limpio": titulo,
        "medio": medio,
        "dominio": medio,
        "fecha_publicacion": None if publicado_hace is None else iso(publicado_hace),
        "fecha_deteccion": None if detectado_hace is None else iso(detectado_hace),
        "es_recirculada": recirculada,
        "alcance_regional": regional,
        "tema_similitud": similitud,
    }


def vector(*valores: float) -> np.ndarray:
    """Un vector de norma 1."""
    v = np.array(valores, dtype=np.float32)
    return v / np.linalg.norm(v)


def entrada(
    id_grupo: str,
    miembros: list[dict[str, Any]] | None = None,
    vectores: np.ndarray | None = None,
    subtema: str | None = "inflacion_precios",
    n_procedencias: int = 2,
    tiene_oficial: bool = False,
    motivo_sin_oficial: str | None = None,
) -> EntradaGrupo:
    miembros = miembros or [miembro()]
    if vectores is None:
        vectores = np.stack([vector(1.0, float(i + 1)) for i in range(len(miembros))])
    return EntradaGrupo(
        id_grupo=id_grupo,
        miembros=tuple(miembros),
        vectores=vectores,
        subtema=subtema,
        n_procedencias=n_procedencias,
        tiene_oficial=tiene_oficial,
        motivo_sin_oficial=motivo_sin_oficial,
    )


class ProveedorFalso:
    """Cumple ``src.llm.proveedor.Proveedor``; devuelve una respuesta fija y registra lo que recibe."""

    nombre = "falso"
    modelo = "falso-0"

    def __init__(self, respuesta: str | dict[str, Any] | None = None, falla: bool = False) -> None:
        self.respuesta = json.dumps(respuesta) if isinstance(respuesta, dict) else respuesta
        self.falla = falla
        self.llamadas: list[tuple[str, str]] = []

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        self.llamadas.append((system, usuario))
        if self.falla:
            raise ErrorProveedor("proveedor de prueba no disponible")
        assert self.respuesta is not None
        return self.respuesta
