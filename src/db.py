"""Acceso a DuckDB: esquema, conexión y consultas sobre data/senales.duckdb (E1-03).

Las fechas se guardan como texto ISO 8601 UTC con ``Z`` (el contrato de datos), no como
``TIMESTAMP``: así el valor leído es exactamente el escrito. Los nulos son ``NULL``, nunca 0.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from src.configuracion import RAIZ

logger = logging.getLogger(__name__)

RUTA_BASE = RAIZ / "data" / "senales.duckdb"

# Tabla -> [(columna, tipo)]. El orden es el de la tabla.
ESQUEMA: dict[str, list[tuple[str, str]]] = {
    "noticias": [
        ("id_noticia", "VARCHAR PRIMARY KEY"),
        ("titulo", "VARCHAR NOT NULL"),
        ("url", "VARCHAR NOT NULL"),
        ("url_canonica", "VARCHAR NOT NULL"),
        ("medio", "VARCHAR NOT NULL"),
        ("idioma", "VARCHAR"),
        ("fecha_publicacion", "VARCHAR"),
        ("fecha_deteccion", "VARCHAR"),
        ("fecha_extraccion", "VARCHAR"),
        ("tema", "VARCHAR"),
        ("origen", "VARCHAR"),
        ("alcance_texto", "VARCHAR"),
        ("descripcion", "VARCHAR"),
        ("categoria_fuente", "VARCHAR"),
        ("dominio", "VARCHAR"),
        ("pais_medio", "VARCHAR"),
        ("url_movil", "VARCHAR"),
        ("agencia", "VARCHAR"),
        ("tipo_firma", "VARCHAR NOT NULL"),
        ("es_recirculada", "BOOLEAN"),
        # E1-03b (los llena src/limpieza.py; nulos hasta entonces). Marcar, no borrar.
        ("titulo_original", "VARCHAR"),
        ("titulo_limpio", "VARCHAR"),
        ("es_ruido", "BOOLEAN"),
        ("motivo_ruido", "VARCHAR"),
        ("sospechoso_inyeccion", "BOOLEAN"),
        ("alcance_regional", "BOOLEAN"),
    ],
    "indicadores": [
        ("id_indicador", "VARCHAR PRIMARY KEY"),
        ("pais_iso3", "VARCHAR NOT NULL"),
        ("indicador_id", "VARCHAR NOT NULL"),
        ("anio", "INTEGER NOT NULL"),
        ("valor", "DOUBLE"),
        ("unidad", "VARCHAR"),
        ("fuente_url", "VARCHAR"),
        ("fecha_extraccion", "VARCHAR"),
        ("licencia", "VARCHAR"),
    ],
    "sismos": [
        ("id", "VARCHAR PRIMARY KEY"),
        ("magnitude", "DOUBLE"),
        ("time", "VARCHAR"),
        ("updated", "VARCHAR"),
        ("longitude", "DOUBLE"),
        ("latitude", "DOUBLE"),
        ("depth", "DOUBLE"),
        ("place", "VARCHAR"),
        ("status", "VARCHAR"),
        ("url", "VARCHAR"),
    ],
    "fuentes": [
        ("dominio", "VARCHAR PRIMARY KEY"),
        ("nombre_legible", "VARCHAR NOT NULL"),
        ("pais", "VARCHAR"),
        ("origen", "VARCHAR"),
        ("condiciones", "VARCHAR"),
    ],
    "duplicados_eliminados": [
        ("tabla", "VARCHAR NOT NULL"),
        ("id_conservado", "VARCHAR NOT NULL"),
        ("id_descartado", "VARCHAR NOT NULL"),
        ("clave", "VARCHAR NOT NULL"),
        ("motivo", "VARCHAR NOT NULL"),
    ],
    "registro_normalizacion": [
        ("tabla", "VARCHAR NOT NULL"),
        ("clave", "VARCHAR NOT NULL"),
        ("campo", "VARCHAR NOT NULL"),
        ("valor_original", "VARCHAR"),
        ("motivo", "VARCHAR NOT NULL"),
    ],
}


def columnas(tabla: str) -> list[str]:
    """Nombres de columna de ``tabla`` en orden."""
    return [c for c, _ in ESQUEMA[tabla]]


def conectar(ruta: Path | str = RUTA_BASE, solo_lectura: bool = False) -> duckdb.DuckDBPyConnection:
    """Abre la base DuckDB en ``ruta``."""
    return duckdb.connect(str(ruta), read_only=solo_lectura)


def crear_esquema(con: duckdb.DuckDBPyConnection) -> None:
    """Crea todas las tablas del esquema (las existentes se reemplazan)."""
    for tabla, cols in ESQUEMA.items():
        con.execute(f'DROP TABLE IF EXISTS "{tabla}"')
        definicion = ", ".join(f'"{c}" {t}' for c, t in cols)
        con.execute(f'CREATE TABLE "{tabla}" ({definicion})')


def insertar(con: duckdb.DuckDBPyConnection, tabla: str, filas: Iterable[Mapping[str, Any]]) -> int:
    """Inserta ``filas`` (diccionarios con las columnas de la tabla; ``None`` = NULL). Devuelve cuántas."""
    cols = columnas(tabla)
    datos = [tuple(f.get(c) for c in cols) for f in filas]
    if datos:
        marcas = ", ".join("?" for _ in cols)
        con.executemany(f'INSERT INTO "{tabla}" VALUES ({marcas})', datos)
    return len(datos)


def guardar_todo(ruta: Path, tablas: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, int]:
    """Escribe ``tablas`` en una base nueva y la deja en ``ruta`` de forma atómica.

    Se construye en un archivo temporal y se renombra al final: una falla a medias no deja
    una base truncada. Devuelve el conteo de filas por tabla.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.unlink(missing_ok=True)
    conteos: dict[str, int] = {}
    con = conectar(temporal)
    try:
        crear_esquema(con)
        for tabla in ESQUEMA:
            conteos[tabla] = insertar(con, tabla, tablas.get(tabla, []))
    except BaseException:
        con.close()
        temporal.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(temporal, ruta)
    logger.info("Base escrita en %s: %s", ruta, conteos)
    return conteos


def contar_filas(con: duckdb.DuckDBPyConnection, tabla: str) -> int:
    """Número de filas de ``tabla``."""
    return int(con.execute(f'SELECT count(*) FROM "{tabla}"').fetchone()[0])  # type: ignore[index]


def contar_nulos(con: duckdb.DuckDBPyConnection, tabla: str, campo: str) -> int:
    """Número de filas de ``tabla`` con ``campo`` NULL."""
    return int(con.execute(f'SELECT count(*) FROM "{tabla}" WHERE "{campo}" IS NULL').fetchone()[0])  # type: ignore[index]


def leer_tabla(con: duckdb.DuckDBPyConnection, tabla: str, orden: str | None = None) -> list[dict[str, Any]]:
    """Todas las filas de ``tabla`` como diccionarios, opcionalmente ordenadas por ``orden``."""
    sql = f'SELECT * FROM "{tabla}"' + (f" ORDER BY {orden}" if orden else "")
    cur = con.execute(sql)
    nombres = [d[0] for d in cur.description]
    return [dict(zip(nombres, fila, strict=True)) for fila in cur.fetchall()]
