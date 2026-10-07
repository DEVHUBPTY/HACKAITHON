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
        # E1-07 (los llena src/clasificacion.py; nulos hasta entonces). `tema` de arriba es el de ORIGEN (D-62).
        ("similitud_panama", "DOUBLE"),
        ("ruido_similitud", "BOOLEAN"),
        ("tema_clasificado", "VARCHAR"),
        ("tema_similitud", "DOUBLE"),
        ("subtema_clasificado", "VARCHAR"),
        ("tema_secundario", "VARCHAR"),
        ("tema_secundario_similitud", "DOUBLE"),
        ("tema_baseline", "VARCHAR"),
        # E1-08 (los llena src/agrupacion.py; nulos hasta entonces, y nulos para el ruido, que no entra a la bandeja).
        ("id_grupo", "VARCHAR"),
        ("procedencia", "VARCHAR"),
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
    "similitud_tema": [  # E1-07: similitud de cada noticia con cada tema (explicabilidad), por método (A o B)
        ("id_noticia", "VARCHAR NOT NULL"),
        ("metodo", "VARCHAR NOT NULL"),
        ("tema", "VARCHAR NOT NULL"),
        ("similitud", "DOUBLE NOT NULL"),
        ("subtema", "VARCHAR"),
    ],
    "grupos": [  # E1-08: un grupo por evento; el conteo de procedencias es una ESTIMACIÓN (CU-03)
        ("id_grupo", "VARCHAR PRIMARY KEY"),
        ("titular_central", "VARCHAR NOT NULL"),
        ("id_noticia_central", "VARCHAR NOT NULL"),
        ("n_titulares", "INTEGER NOT NULL"),
        ("n_medios", "INTEGER NOT NULL"),
        ("n_procedencias", "INTEGER NOT NULL"),
        ("fecha_inicio", "VARCHAR"),
        ("fecha_inicio_origen", "VARCHAR"),
        ("fecha_fin", "VARCHAR"),
        ("fecha_fin_origen", "VARCHAR"),
        ("idiomas", "VARCHAR"),
        ("tema_clasificado", "VARCHAR"),
        ("ids_noticia", "VARCHAR NOT NULL"),
        ("estimado", "BOOLEAN NOT NULL"),
    ],
    "procedencias": [  # E1-08: procedencias independientes de cada grupo y por qué se unieron los titulares
        ("id_grupo", "VARCHAR NOT NULL"),
        ("orden", "INTEGER NOT NULL"),
        ("etiqueta", "VARCHAR NOT NULL"),
        ("reglas", "VARCHAR"),
        ("n_titulares", "INTEGER NOT NULL"),
        ("medios", "VARCHAR NOT NULL"),
        ("ids_noticia", "VARCHAR NOT NULL"),
    ],
    "vinculos": [  # E1-09 / E1-09b: contexto oficial de cada grupo (Banco Mundial `indicador`, USGS `usgs`)
        ("id_grupo", "VARCHAR NOT NULL"),
        ("id_evidencia", "VARCHAR"),           # IND-… o SIS-…; NULL si no hay vínculo
        ("tipo", "VARCHAR"),                   # relación: directa · indirecta · evento; NULL si no hay vínculo
        ("regla", "VARCHAR NOT NULL"),         # la regla que generó la fila (también la del "sin vínculo")
        ("limitacion", "VARCHAR"),
        ("motivo_sin_vinculo", "VARCHAR"),     # solo en filas sin vínculo (config/vinculos.yaml)
        ("fuente", "VARCHAR NOT NULL"),        # quién la escribe: `indicador` (src.contexto) o `usgs` (src.contexto_sismos)
        ("rol", "VARCHAR"),                    # panama · comparable · tendencia · evento
        ("subtema", "VARCHAR"),                # subtema más cercano dentro del tema del grupo
        ("pais_iso3", "VARCHAR"),
        ("indicador_id", "VARCHAR"),
        ("anio", "INTEGER"),
        ("unidad", "VARCHAR"),
        ("valor", "DOUBLE"),                   # NULL = sin dato; nunca 0
        ("fecha_extraccion", "VARCHAR"),
        ("cifra_titular", "DOUBLE"),           # solo en la fila `panama`, si el titular trae su propia cifra
        ("anio_titular", "INTEGER"),
        ("comparacion_titular", "VARCHAR"),
        # E1-09b: solo en las filas `usgs` (la magnitud va en `valor`/`unidad`)
        ("place", "VARCHAR"),                  # texto original de USGS, sin traducir
        ("profundidad_km", "DOUBLE"),          # NULL = sin dato; nunca 0
        ("hora_utc", "VARCHAR"),               # ISO 8601 UTC del evento
        ("estado_evento", "VARCHAR"),          # `automatic` o `reviewed`
        ("url_evento", "VARCHAR"),
        ("diferencia_horas", "DOUBLE"),        # distancia a la noticia más cercana del grupo
    ],
    "puntajes": [  # E1-10: R, I, U, N, E y P de cada grupo, con la explicación de cada componente (reglas v1.3)
        ("id_grupo", "VARCHAR PRIMARY KEY"),
        ("posicion", "INTEGER NOT NULL"),      # 1 = el más prioritario (P, luego mayor U, luego menor ID)
        ("version_reglas", "VARCHAR NOT NULL"),
        ("fecha_referencia", "VARCHAR NOT NULL"),   # ISO UTC contra la que se midió U (corte del snapshot)
        ("relevancia", "DOUBLE NOT NULL"),
        ("impacto", "DOUBLE NOT NULL"),
        ("urgencia", "DOUBLE NOT NULL"),
        ("novedad", "DOUBLE NOT NULL"),
        ("evidencia", "DOUBLE NOT NULL"),
        ("puntaje", "DOUBLE NOT NULL"),
        ("rango", "VARCHAR NOT NULL"),
        ("componentes", "VARCHAR NOT NULL"),   # JSON: por componente, su valor y de qué valores sale
        ("vacios", "VARCHAR NOT NULL"),        # JSON: vacíos que nacen del puntaje (urgencia estimada, recirculada, subtema)
        ("recirculada", "BOOLEAN NOT NULL"),
        ("es_nueva", "BOOLEAN NOT NULL"),
    ],
    "evidencia": [  # E1-10: estado de evidencia (independiente de P), vacíos y acción recomendada de la modalidad
        ("id_grupo", "VARCHAR PRIMARY KEY"),
        ("estado", "VARCHAR NOT NULL"),        # insuficiente · parcial · suficiente
        ("n_procedencias", "INTEGER NOT NULL"),
        ("tiene_oficial", "BOOLEAN NOT NULL"),
        ("hay_cifras", "BOOLEAN NOT NULL"),
        ("contradicciones_abiertas", "INTEGER NOT NULL"),
        ("vacios", "VARCHAR NOT NULL"),        # JSON: vacíos de verificación de la evidencia
        ("modalidad", "VARCHAR NOT NULL"),
        ("rango", "VARCHAR NOT NULL"),
        ("accion", "VARCHAR NOT NULL"),        # celda (rango × estado) de la tabla de la modalidad; nunca «publicar»
        ("motivo_accion", "VARCHAR NOT NULL"),
    ],
    "contradicciones": [  # E1-10: pares candidatos por reglas y su comparación (el LLM solo compara; nunca un veredicto)
        ("id_grupo", "VARCHAR NOT NULL"),
        ("id_noticia_a", "VARCHAR NOT NULL"),
        ("id_noticia_b", "VARCHAR NOT NULL"),
        ("medio_a", "VARCHAR"),
        ("medio_b", "VARCHAR"),
        ("titular_a", "VARCHAR NOT NULL"),
        ("titular_b", "VARCHAR NOT NULL"),
        ("fecha_publicacion_a", "VARCHAR"),
        ("fecha_publicacion_b", "VARCHAR"),
        ("reglas", "VARCHAR NOT NULL"),        # cifras_distintas · verbos_opuestos (separadas por coma)
        ("detalle", "VARCHAR NOT NULL"),
        ("estado", "VARCHAR NOT NULL"),        # verificar · pendiente_llm · descartada
        ("etiqueta", "VARCHAR NOT NULL"),      # «posible contradicción, verificar»
        ("fragmento_a", "VARCHAR"),            # fragmento literal del titular A que cita el LLM
        ("fragmento_b", "VARCHAR"),
        ("proveedor", "VARCHAR"),
        ("modelo", "VARCHAR"),
        ("motivo_pendiente", "VARCHAR"),       # solo con estado pendiente_llm
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


def asegurar_esquema(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Agrega, sin tocar los datos, las tablas y columnas del ``ESQUEMA`` que una base anterior no tiene.

    Sirve para una ``senales.duckdb`` creada antes de una tarea nueva. Devuelve lo agregado (``tabla`` o
    ``tabla.columna``). Las columnas nuevas son siempre anulables, así que ``ALTER TABLE`` basta.
    """
    agregado: list[str] = []
    existentes = {fila[0] for fila in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    for tabla, cols in ESQUEMA.items():
        if tabla not in existentes:
            definicion = ", ".join(f'"{c}" {t}' for c, t in cols)
            con.execute(f'CREATE TABLE "{tabla}" ({definicion})')
            agregado.append(tabla)
            continue
        presentes = {
            fila[0]
            for fila in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [tabla]
            ).fetchall()
        }
        for columna, tipo in cols:
            if columna not in presentes:
                con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{columna}" {tipo.replace(" NOT NULL", "")}')
                agregado.append(f"{tabla}.{columna}")
    return agregado


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
