"""Ayudas de las pruebas de E1-10: grupos sintéticos, vectores y un proveedor de LLM falso (nunca se llama a uno real)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np

from pathlib import Path

from src import db
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


# ------------------------------------------------------------------ una base DuckDB mínima (4 grupos)


def fila_noticia(id_noticia: str, titulo: str, dominio: str, grupo: str, horas: float = 3, regional: bool = False, sim: float = 0.8) -> dict:
    publicada = f"2026-10-06T{int(12 - horas):02d}:00:00Z"
    return {
        "id_noticia": id_noticia, "titulo": titulo, "url": f"https://{dominio}/{id_noticia}", "url_canonica": f"https://{dominio}/{id_noticia}",
        "medio": dominio, "dominio": dominio, "tipo_firma": "sin firma", "fecha_publicacion": publicada, "fecha_deteccion": publicada,
        "titulo_limpio": titulo, "es_ruido": False, "alcance_regional": regional, "tema_similitud": sim, "tema_clasificado": "economia",
        "id_grupo": grupo, "descripcion": None,
    }


def fila_grupo(id_grupo: str, ids: list[str], titular: str, n_proc: int) -> dict:
    return {
        "id_grupo": id_grupo, "titular_central": titular, "id_noticia_central": ids[0], "n_titulares": len(ids), "n_medios": len(ids),
        "n_procedencias": n_proc, "idiomas": "es", "tema_clasificado": "economia", "ids_noticia": ",".join(ids), "estimado": True,
    }


def filas_procedencias(id_grupo: str, ids: list[str]) -> list[dict]:
    return [
        {"id_grupo": id_grupo, "orden": i, "etiqueta": f"fuente {i}", "reglas": None, "n_titulares": 1, "medios": "x", "ids_noticia": nid}
        for i, nid in enumerate(ids, start=1)
    ]


def fila_vinculo(id_grupo: str, **campos) -> dict:
    fila = dict.fromkeys(db.columnas("vinculos")) | {"id_grupo": id_grupo, "regla": "prueba", "fuente": "indicador"}
    return fila | campos


def construir_base(ruta: Path) -> Path:
    """Base con cuatro grupos: dos con versiones distintas de una cifra (a, d), uno con dato oficial (b) y uno regional (c)."""
    noticias = [
        fila_noticia("NOT-a000000001", "Cierran 12 escuelas en Veraguas por lluvias", "medio-a.example", "GRP-a", 2, sim=0.9),
        fila_noticia("NOT-a000000002", "Más de 40 escuelas cerradas en Veraguas por lluvias", "medio-b.example", "GRP-a", 3, sim=0.9),
        fila_noticia("NOT-b000000001", "Panamá reporta inflación estable", "medio-c.example", "GRP-b", 1, sim=0.85),
        fila_noticia("NOT-c000000001", "El Niño amenaza a Centroamérica", "medio-d.example", "GRP-c", 5, regional=True, sim=0.7),
        fila_noticia("NOT-d000000001", "Cierran 12 colegios en Chiriquí", "medio-e.example", "GRP-d", 4, sim=0.8),
        fila_noticia("NOT-d000000002", "Cierran 40 colegios en Chiriquí", "medio-f.example", "GRP-d", 4, sim=0.8),
    ]
    grupos = [
        fila_grupo("GRP-a", ["NOT-a000000001", "NOT-a000000002"], "Cierran escuelas", 2),
        fila_grupo("GRP-b", ["NOT-b000000001"], "Inflación estable", 1),
        fila_grupo("GRP-c", ["NOT-c000000001"], "El Niño", 1),
        fila_grupo("GRP-d", ["NOT-d000000001", "NOT-d000000002"], "Cierran colegios", 2),
    ]
    procs = filas_procedencias("GRP-a", ["NOT-a000000001", "NOT-a000000002"]) + filas_procedencias("GRP-b", ["NOT-b000000001"]) + filas_procedencias("GRP-c", ["NOT-c000000001"]) + filas_procedencias("GRP-d", ["NOT-d000000001", "NOT-d000000002"])
    vinculos = [
        fila_vinculo("GRP-b", id_evidencia="IND-PAN-FP.CPI.TOTL.ZG-2024", tipo="directa", rol="panama", valor=0.7, anio=2024),
        fila_vinculo("GRP-c", motivo_sin_vinculo="tema_sin_indicador"),
        fila_vinculo("GRP-a", id_evidencia="SIS-us0001", motivo_sin_vinculo="candidatos_ambiguos", fuente="usgs", valor=4.1),   # ambiguo: no cuenta como dato oficial
    ]
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": grupos, "procedencias": procs, "vinculos": vinculos})
    return ruta


