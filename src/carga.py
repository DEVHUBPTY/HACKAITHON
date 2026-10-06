"""Carga y validación lazy de los archivos del snapshot con reporte de calidad (E1-02, T01).

Etapa 1 del flujo. Lee ``noticias.csv`` e ``indicadores.csv`` con pandera en modo *lazy* y
``eventos.geojson`` / ``fuentes.json`` con pydantic (D-19). Reglas:

* Un error no detiene la carga: las filas inválidas se separan con su motivo y el resto sigue.
* Un campo crítico vacío, en blanco o inválido invalida la fila; un campo opcional vacío solo cuenta como nulo.
* Los nulos son nulos: no se rellenan con cero ni con nada (``valor`` nulo en indicadores es válido).
* Si el primer registro de un ID está inválido, se conserva la primera aparición **válida** y las
  demás se marcan ``id_duplicado``.
* Invariante del reporte, por archivo: ``validas + rechazadas == leidas``. Una fila con varios errores
  cuenta una vez; las líneas mal formadas del CSV cuentan como leídas y rechazadas; los errores de
  archivo (columna crítica ausente, archivo ausente) se reportan aparte en ``errores_de_archivo``.
* No se escribe en ``data/raw/`` ni se tocan los archivos de ``data/processed/``: las filas válidas van
  a ``data/processed/validos/`` (D-82) y los rechazos y el reporte a ``outputs/``.
* Esta etapa solo lee fechas ISO 8601 UTC de ``processed/``. El parseo de los formatos de origen (GDELT,
  RSS RFC 822, milisegundos de USGS) vive en ``scripts/conversion.py`` (E0-04).

Ejecutable con ``poetry run python -m src.carga``.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
import pandera.pandas as pa
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError, ValidationInfo, field_validator

from src.configuracion import RAIZ, ConfigCarga, cargar_carga, cargar_contrato
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

# Vocabulario de errores (el de ``error_esperado`` de los fixtures T01 más los propios de la carga).
OBLIGATORIO_VACIO = "obligatorio_vacio"
FECHA_INVALIDA = "fecha_invalida"
ID_DUPLICADO = "id_duplicado"
URL_MAL_FORMADA = "url_mal_formada"
ID_FORMATO_INVALIDO = "id_formato_invalido"
VALOR_INVALIDO = "valor_invalido"
COLUMNA_FALTANTE = "columna_faltante"
ESTRUCTURA_INVALIDA = "estructura_invalida"

CARPETA_PROCESADOS = RAIZ / "data" / "processed"
CARPETA_SALIDA = RAIZ / "outputs"


# ---------------------------------------------------------------- tipos de resultado


@dataclass
class ErrorFila:
    """Un motivo de rechazo. ``fila`` es la posición 1-based del registro dentro del archivo."""

    archivo: str
    fila: int | None
    id: str
    campo: str
    tipo_error: str
    motivo: str
    valor: str


@dataclass
class ResultadoArchivo:
    """Resultado de cargar un archivo: filas válidas, errores y conteos.

    ``leidas`` incluye las líneas mal formadas. ``errores`` solo trae errores de fila; los de archivo
    y las líneas mal formadas van en sus propios campos para que ``validas + rechazadas == leidas``.
    """

    archivo: str
    leidas: int
    validas: pd.DataFrame
    errores: list[ErrorFila] = field(default_factory=list)
    errores_de_archivo: list[ErrorFila] = field(default_factory=list)
    lineas_mal_formadas: list[ErrorFila] = field(default_factory=list)
    nulos_leidas: dict[str, int] = field(default_factory=dict)
    nulos_validas: dict[str, int] = field(default_factory=dict)
    nulos_rechazadas: dict[str, int] = field(default_factory=dict)

    @property
    def rechazadas(self) -> int:
        """Filas rechazadas: cada fila con al menos un error cuenta una vez, más las líneas mal formadas."""
        return len({e.fila for e in self.errores if e.fila is not None}) + len(self.lineas_mal_formadas)

    def errores_por_tipo(self) -> dict[str, int]:
        """Cuenta de errores de fila (incluye líneas mal formadas) por tipo, de mayor a menor."""
        return dict(Counter(e.tipo_error for e in [*self.errores, *self.lineas_mal_formadas]).most_common())


# ---------------------------------------------------------------- parser de fecha (ISO de processed/)


def parsear_fecha_iso(texto: Any, config: ConfigCarga) -> datetime | None:
    """ISO 8601 UTC con ``Z`` (formato de ``data/processed/``). ``None`` si no es una fecha real."""
    if not isinstance(texto, str) or not re.match(config.fechas.iso_utc.patron, texto):
        return None
    try:
        return datetime.strptime(texto, config.fechas.iso_utc.formato).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------- utilidades


def _recortar(valor: Any, maximo: int) -> str:
    texto = "" if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor)
    return texto if len(texto) <= maximo else texto[:maximo] + "…"


def _nulos(df: pd.DataFrame) -> dict[str, int]:
    return {str(c): int(n) for c, n in df.isna().sum().items()}


def _leer_csv(ruta: Path, archivo: str) -> tuple[pd.DataFrame, list[ErrorFila], list[ErrorFila]]:
    """Lee un CSV como texto; vacío = nulo. Devuelve (filas, errores de archivo, líneas mal formadas)."""
    malas: list[int] = []

    def _mala(linea: list[str]) -> None:
        malas.append(len(linea))
        return None

    try:
        df = pd.read_csv(ruta, dtype=str, keep_default_na=False, engine="python", on_bad_lines=_mala)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(), [ErrorFila(archivo, None, "", "", ESTRUCTURA_INVALIDA, "archivo sin encabezado", "")], []
    for col in df.columns:
        df[col] = df[col].str.strip().replace("", pd.NA)
    mal_formadas = [
        ErrorFila(archivo, None, "", "", ESTRUCTURA_INVALIDA, "línea con número de campos distinto al encabezado", "")
        for _ in malas
    ]
    return df.reset_index(drop=True), [], mal_formadas


# ---------------------------------------------------------------- pandera (CSV)


def _check(nombre: str, funcion: Any, descripcion: str) -> pa.Check:
    """Check pandera cuyo nombre es el tipo de error: así el mapeo no depende de texto libre."""
    return pa.Check(funcion, name=nombre, description=descripcion, element_wise=False)


def _esquema_noticias(config: ConfigCarga) -> pa.DataFrameSchema:
    n = config.noticias
    patron_id = re.compile(n.patron_id)
    patron_url = re.compile(config.patron_url)
    columnas: dict[str, pa.Column] = {}
    for c in n.criticos:
        checks: list[pa.Check] = []
        if c == "id_noticia":
            checks = [
                _check(ID_FORMATO_INVALIDO, lambda s: s.map(lambda x: bool(patron_id.match(x))), "id sin prefijo/forma válida"),
            ]
        columnas[c] = pa.Column(str, checks=checks, nullable=False, required=True)
    for c in n.columnas_url:
        columnas[c].checks.append(
            _check(URL_MAL_FORMADA, lambda s: s.map(lambda x: bool(patron_url.match(x))), "URL sin esquema http(s) o sin host")
        )
    for c in n.columnas_fecha:
        columnas[c] = pa.Column(
            str,
            checks=[_check(FECHA_INVALIDA, lambda s: s.map(lambda x: parsear_fecha_iso(x, config) is not None), "no es ISO 8601 UTC real")],
            nullable=True,
            required=c not in n.fecha_opcional,
        )
    for c in n.opcionales:
        columnas[c] = pa.Column(str, nullable=True, required=False)
    alternativas = n.fechas_alternativas
    return pa.DataFrameSchema(
        columnas,
        checks=[
            _check(
                OBLIGATORIO_VACIO,
                lambda df: df[alternativas].notna().any(axis=1),
                "falta al menos una fecha (publicación o detección)",
            )
        ],
        strict=False,  # columnas extra de prueba (p. ej. error_esperado) no son un error
        coerce=False,
    )


def _esquema_indicadores(config: ConfigCarga) -> pa.DataFrameSchema:
    i = config.indicadores
    patron_pais = re.compile(i.patron_pais)
    patron_anio = re.compile(i.patron_anio)
    patron_id = re.compile(i.patron_id)
    patron_url = re.compile(config.patron_url)

    def _es_anio(x: str) -> bool:
        return bool(patron_anio.fullmatch(x)) and i.anio_minimo <= int(x) <= i.anio_maximo

    def _es_numero(x: str) -> bool:
        try:
            return pd.notna(float(x)) and float(x) not in (float("inf"), float("-inf"))
        except ValueError:
            return False

    reglas: dict[str, list[pa.Check]] = {
        "pais_iso3": [_check(VALOR_INVALIDO, lambda s: s.map(lambda x: bool(patron_pais.match(x))), "ISO3 inválido")],
        "anio": [_check(VALOR_INVALIDO, lambda s: s.map(_es_anio), "año fuera de rango o no entero")],
        "fuente_url": [_check(URL_MAL_FORMADA, lambda s: s.map(lambda x: bool(patron_url.match(x))), "URL mal formada")],
        "fecha_extraccion": [
            _check(FECHA_INVALIDA, lambda s: s.map(lambda x: parsear_fecha_iso(x, config) is not None), "no es ISO 8601 UTC real")
        ],
    }
    # Los críticos salen de config/carga.yaml: vacío o inválido invalida la fila.
    columnas: dict[str, pa.Column] = {c: pa.Column(str, reglas.get(c, []), nullable=False) for c in i.criticos}
    # valor nulo es VÁLIDO: solo se rechaza un valor presente que no sea numérico.
    columnas["valor"] = pa.Column(str, [_check(VALOR_INVALIDO, lambda s: s.map(_es_numero), "valor no numérico")], nullable=True)
    # El snapshot real trae id_indicador; el fixture T01 no. Si viene, debe tener la forma del contrato.
    columnas["id_indicador"] = pa.Column(
        str,
        [_check(ID_FORMATO_INVALIDO, lambda s: s.map(lambda x: bool(patron_id.match(x))), "id sin forma IND-<pais>-<indicador>-<anio>")],
        nullable=True,
        required=False,
    )
    return pa.DataFrameSchema(columnas, strict=False, coerce=False)


_CHECKS_A_ERROR = {"not_nullable": OBLIGATORIO_VACIO, "column_in_dataframe": COLUMNA_FALTANTE, "dtype": VALOR_INVALIDO}


def _errores_pandera(
    df: pd.DataFrame,
    esquema: pa.DataFrameSchema,
    archivo: str,
    col_id: str | None,
    maximo: int,
    campos_df: list[str],
) -> tuple[list[ErrorFila], list[ErrorFila]]:
    """Corre el esquema en modo lazy. Devuelve (errores de fila, errores de archivo)."""
    try:
        esquema.validate(df, lazy=True)
        return [], []
    except pa.errors.SchemaErrors as exc:
        casos = exc.failure_cases
    filas: list[ErrorFila] = []
    faltantes: list[str] = []
    otros: list[ErrorFila] = []
    vistos_df: set[tuple[int, str]] = set()
    for caso in casos.itertuples(index=False):
        tipo = _CHECKS_A_ERROR.get(str(caso.check), str(caso.check))
        indice = caso.index
        campo = "" if pd.isna(caso.column) else str(caso.column)
        if pd.isna(indice):  # error de columna o de tabla: afecta a todas las filas
            if tipo == COLUMNA_FALTANTE:
                faltantes.append(str(caso.failure_case))
            else:
                otros.append(ErrorFila(archivo, None, "", campo, tipo, f"columna {campo}: {tipo}", ""))
            continue
        i = int(indice)
        if str(caso.schema_context) == "DataFrameSchema":  # pandera repite un check de tabla por columna: se junta
            if (i, tipo) in vistos_df:
                continue
            vistos_df.add((i, tipo))
            campo = "|".join(campos_df)
        id_fila = "" if col_id is None or col_id not in df.columns or pd.isna(df.at[i, col_id]) else str(df.at[i, col_id])
        valor = "" if campo not in df.columns else _recortar(df.at[i, campo], maximo)
        filas.append(ErrorFila(archivo, i + 1, id_fila, campo, tipo, _motivo(tipo, campo), valor))
    if faltantes:  # un solo error de archivo; los checks de tabla que fallan por la columna ausente son consecuencia
        campo = "|".join(faltantes)
        return filas, [ErrorFila(archivo, None, "", campo, COLUMNA_FALTANTE, f"faltan columnas requeridas del contrato: {campo}", "")]
    return filas, otros


def _motivo(tipo: str, campo: str) -> str:
    plantillas = {
        OBLIGATORIO_VACIO: "campo obligatorio vacío",
        FECHA_INVALIDA: "fecha no válida (se espera ISO 8601 UTC)",
        ID_DUPLICADO: "identificador o clave repetidos; se conserva la primera aparición válida",
        URL_MAL_FORMADA: "URL mal formada",
        ID_FORMATO_INVALIDO: "identificador sin el prefijo o la forma del contrato",
        VALOR_INVALIDO: "valor fuera de dominio",
    }
    return f"{campo}: {plantillas.get(tipo, tipo)}" if campo else plantillas.get(tipo, tipo)


def _marcar_duplicados(
    df: pd.DataFrame, errores: list[ErrorFila], archivo: str, claves: list[list[str]], col_id: str, maximo: int
) -> None:
    """Marca ``id_duplicado`` en las filas cuya clave ya apareció en una fila **válida** anterior.

    Una fila inválida no consume la clave: si la primera aparición es inválida, gana la primera válida.
    """
    malas = {e.fila for e in errores}
    vistos: set[tuple[tuple[str, ...], tuple[Any, ...]]] = set()
    for i in range(len(df)):
        if i + 1 in malas:
            continue
        llaves = [
            (tuple(cols), tuple(df.at[i, c] for c in cols))
            for cols in claves
            if all(c in df.columns for c in cols) and not any(pd.isna(df.at[i, c]) for c in cols)
        ]
        choque = next((cols for cols, valores in llaves if (cols, valores) in vistos), None)
        if choque is not None:
            id_fila = "" if col_id not in df.columns or pd.isna(df.at[i, col_id]) else str(df.at[i, col_id])
            campo = "|".join(choque)
            errores.append(ErrorFila(archivo, i + 1, id_fila, campo, ID_DUPLICADO, _motivo(ID_DUPLICADO, campo), _recortar(df.at[i, choque[0]], maximo)))
        else:
            vistos.update(llaves)


def _consolidar(
    archivo: str,
    df: pd.DataFrame,
    errores: list[ErrorFila],
    de_archivo: list[ErrorFila],
    mal_formadas: list[ErrorFila],
) -> ResultadoArchivo:
    """Separa válidas de rechazadas a partir de los errores y calcula los nulos antes/después."""
    faltantes = [e.campo for e in de_archivo if e.tipo_error == COLUMNA_FALTANTE]
    if faltantes:  # sin una columna crítica ninguna fila puede validarse: cada una lleva el motivo
        con_error = {e.fila for e in errores}
        errores = errores + [
            ErrorFila(archivo, i + 1, "", "|".join(faltantes), COLUMNA_FALTANTE, "falta una columna requerida del contrato", "")
            for i in range(len(df))
            if i + 1 not in con_error
        ]
    errores = sorted(errores, key=lambda e: e.fila or 0)
    malas = {e.fila - 1 for e in errores if e.fila is not None}
    mascara = df.index.isin(malas)
    validas = df.loc[~mascara].reset_index(drop=True)
    return ResultadoArchivo(
        archivo=archivo,
        leidas=len(df) + len(mal_formadas),
        validas=validas,
        errores=errores,
        errores_de_archivo=de_archivo,
        lineas_mal_formadas=mal_formadas,
        nulos_leidas=_nulos(df),
        nulos_validas=_nulos(validas),
        nulos_rechazadas=_nulos(df.loc[mascara]),
    )


def _cargar_csv(
    ruta: Path, config: ConfigCarga, esquema: pa.DataFrameSchema, col_id: str, claves: list[list[str]], campos_df: list[str]
) -> ResultadoArchivo:
    df, de_archivo, mal_formadas = _leer_csv(ruta, ruta.name)
    maximo = config.salida.max_caracteres_valor_en_errores
    filas, de_archivo_esquema = _errores_pandera(df, esquema, ruta.name, col_id, maximo, campos_df)
    de_archivo += de_archivo_esquema
    if not any(e.tipo_error == COLUMNA_FALTANTE for e in de_archivo):
        _marcar_duplicados(df, filas, ruta.name, claves, col_id, maximo)
    return _consolidar(ruta.name, df, filas, de_archivo, mal_formadas)


def cargar_noticias(ruta: Path, config: ConfigCarga | None = None) -> ResultadoArchivo:
    """Carga ``noticias.csv`` (o un fixture con su misma forma) con validación lazy."""
    config = config or cargar_carga()
    return _cargar_csv(ruta, config, _esquema_noticias(config), "id_noticia", [["id_noticia"]], config.noticias.fechas_alternativas)


def cargar_indicadores(ruta: Path, config: ConfigCarga | None = None) -> ResultadoArchivo:
    """Carga ``indicadores.csv``. Un ``valor`` nulo es válido y se conserva nulo (nunca 0)."""
    config = config or cargar_carga()
    clave = config.indicadores.clave
    resultado = _cargar_csv(ruta, config, _esquema_indicadores(config), "id_indicador", [["id_indicador"], clave], clave)
    if "valor" in resultado.validas.columns:  # texto → número; el nulo sigue siendo nulo
        resultado.validas["valor"] = pd.to_numeric(resultado.validas["valor"], errors="raise").astype("Float64")
        resultado.validas["anio"] = resultado.validas["anio"].astype("int64")
    return resultado


# ---------------------------------------------------------------- pydantic (JSON / GeoJSON)


_Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]  # vacío o en blanco = inválido


class _Registro(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=False)


def _config(info: ValidationInfo) -> ConfigCarga:
    """La configuración llega por el contexto de validación (sin estado global)."""
    return info.context["config"]  # type: ignore[index]


class EventoSismico(_Registro):
    """``properties`` de un Feature de ``eventos.geojson`` (contrato sección 7)."""

    id: _Texto
    magnitude: float
    time: _Texto
    updated: str | None = None
    longitude: float
    latitude: float
    depth: float | None = None
    place: str | None = None
    status: str | None = None
    url: _Texto

    @field_validator("time", "updated")
    @classmethod
    def _fecha(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is not None and info.field_name == "updated" and not v.strip():
            return None  # opcional vacío = nulo
        if v is not None and parsear_fecha_iso(v, _config(info)) is None:
            raise ValueError(FECHA_INVALIDA)
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str, info: ValidationInfo) -> str:
        if not re.match(_config(info).patron_url, v):
            raise ValueError(URL_MAL_FORMADA)
        return v

    @field_validator("id")
    @classmethod
    def _id(cls, v: str, info: ValidationInfo) -> str:
        if not re.match(_config(info).eventos.patron_id, v):
            raise ValueError(ID_FORMATO_INVALIDO)
        return v

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v: float, info: ValidationInfo) -> float:
        if abs(v) > _config(info).eventos.latitud_maxima:
            raise ValueError(VALOR_INVALIDO)
        return v

    @field_validator("longitude")
    @classmethod
    def _lon(cls, v: float, info: ValidationInfo) -> float:
        if abs(v) > _config(info).eventos.longitud_maxima:
            raise ValueError(VALOR_INVALIDO)
        return v


class Fuente(_Registro):
    """Un registro de ``fuentes.json``. ``pais`` es nulable (desconocido = ``null``)."""

    dominio: _Texto
    nombre_legible: _Texto
    pais: str | None = None
    origen: _Texto
    condiciones: _Texto


def _tipo_error_pydantic(err: dict[str, Any]) -> str:
    if err["type"] in ("missing", "string_too_short") or (err["type"].endswith("_type") and err.get("input") is None):
        return OBLIGATORIO_VACIO
    if err["type"] == "value_error":
        codigo = str(err.get("ctx", {}).get("error", ""))
        if codigo in {OBLIGATORIO_VACIO, FECHA_INVALIDA, URL_MAL_FORMADA, ID_FORMATO_INVALIDO, VALOR_INVALIDO}:
            return codigo
    return VALOR_INVALIDO


def _validar_registros(
    archivo: str,
    registros: list[dict[str, Any]],
    modelo: type[_Registro],
    col_id: str,
    criticos: list[str],
    config: ConfigCarga,
) -> ResultadoArchivo:
    maximo = config.salida.max_caracteres_valor_en_errores
    errores: list[ErrorFila] = []
    validas: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for i, reg in enumerate(registros):
        fila = i + 1
        id_fila = str(reg.get(col_id) or "")
        previos = len(errores)
        try:
            objeto = modelo.model_validate(reg, context={"config": config})
        except ValidationError as exc:
            for err in exc.errors():
                campo = str(err["loc"][0]) if err["loc"] else ""
                tipo = _tipo_error_pydantic(err)
                if campo not in criticos and tipo == OBLIGATORIO_VACIO:
                    continue  # un opcional vacío solo es nulo
                errores.append(ErrorFila(archivo, fila, id_fila, campo, tipo, _motivo(tipo, campo), _recortar(reg.get(campo), maximo)))
            objeto = modelo.model_construct(**{k: reg.get(k) for k in modelo.model_fields})
        if len(errores) != previos:
            continue
        if id_fila in vistos:  # solo las filas válidas consumen el id: gana la primera válida
            errores.append(ErrorFila(archivo, fila, id_fila, col_id, ID_DUPLICADO, _motivo(ID_DUPLICADO, col_id), id_fila))
            continue
        vistos.add(id_fila)
        validas.append(objeto.model_dump())
    columnas = list(modelo.model_fields)
    df = pd.DataFrame(registros)
    validas_df = pd.DataFrame(validas, columns=columnas)
    malas = {e.fila - 1 for e in errores if e.fila is not None}
    mascara = df.index.isin(malas)
    return ResultadoArchivo(
        archivo=archivo,
        leidas=len(registros),
        validas=validas_df,
        errores=errores,
        nulos_leidas=_nulos(df.reindex(columns=columnas)),
        nulos_validas=_nulos(validas_df),
        nulos_rechazadas=_nulos(df.loc[mascara].reindex(columns=columnas)),
    )


def _leer_json(ruta: Path, clave: str | None) -> tuple[list[Any], list[ErrorFila]]:
    """Lee un JSON y devuelve sus registros; si no se puede, un error de archivo en vez de una excepción."""
    try:
        datos = json.loads(ruta.read_text("utf-8"))
        registros = datos.get(clave, []) if clave else datos
        if not isinstance(registros, list):
            raise ValueError("no es una lista de registros")
    except (ValueError, AttributeError) as exc:
        return [], [ErrorFila(ruta.name, None, "", "", ESTRUCTURA_INVALIDA, f"JSON ilegible: {exc}", "")]
    return registros, []


def cargar_eventos(ruta: Path, config: ConfigCarga | None = None) -> ResultadoArchivo:
    """Carga ``eventos.geojson``: valida las ``properties`` de cada Feature con pydantic."""
    config = config or cargar_carga()
    features, de_archivo = _leer_json(ruta, "features")
    registros = [f.get("properties", {}) if isinstance(f, dict) else {} for f in features]
    resultado = _validar_registros(ruta.name, registros, EventoSismico, "id", config.eventos.criticos, config)
    resultado.errores_de_archivo = de_archivo
    return resultado


def cargar_fuentes(ruta: Path, config: ConfigCarga | None = None) -> ResultadoArchivo:
    """Carga ``fuentes.json`` (un registro por medio)."""
    config = config or cargar_carga()
    registros, de_archivo = _leer_json(ruta, None)
    resultado = _validar_registros(ruta.name, [r if isinstance(r, dict) else {} for r in registros], Fuente, "dominio", config.fuentes.criticos, config)
    resultado.errores_de_archivo = de_archivo
    return resultado


# ---------------------------------------------------------------- reporte


def intervalo_wilson(k: int, n: int, z: float) -> tuple[float, float] | None:
    """Intervalo de Wilson para una proporción ``k/n`` (en 0–1). ``None`` si ``n`` es 0."""
    if n <= 0:
        return None
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centro = (p + z2 / (2 * n)) / denom
    mitad = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    inferior = 0.0 if k == 0 else max(0.0, centro - mitad)
    superior = 1.0 if k == n else min(1.0, centro + mitad)
    return inferior, superior


def _distribucion(serie: pd.Series) -> dict[str, int]:
    cuenta = serie.value_counts(dropna=False)
    return {("(nulo)" if pd.isna(k) else str(k)): int(v) for k, v in cuenta.items()}


def _concentracion(distribucion: dict[str, int], top: int, z: float) -> dict[str, Any]:
    """Peso de los ``top`` principales; la proporción siempre lleva su n y su IC de Wilson."""
    n = sum(distribucion.values())
    principales = dict(list(distribucion.items())[:top])
    k = sum(principales.values())
    ic = intervalo_wilson(k, n, z)
    return {
        "top_n": top,
        "principales": principales,
        "n": n,
        "k": k,
        "porcentaje_top_n": round(100 * k / n, 2) if n else None,
        "ic95_inferior_pct": round(100 * ic[0], 2) if ic else None,
        "ic95_superior_pct": round(100 * ic[1], 2) if ic else None,
        "metodo_ic": f"Wilson (z={z})",
    }


def construir_reporte(resultados: dict[str, ResultadoArchivo], config: ConfigCarga) -> dict[str, Any]:
    """Arma el reporte de calidad: por archivo, errores por tipo, nulos y distribución por medio/idioma."""
    archivos: dict[str, Any] = {}
    for nombre, r in resultados.items():
        archivos[nombre] = {
            "leidas": r.leidas,
            "validas": len(r.validas),
            "rechazadas": r.rechazadas,
            "errores_por_tipo": r.errores_por_tipo(),
            "errores_de_archivo": [
                {"campo": e.campo, "tipo_error": e.tipo_error, "motivo": e.motivo} for e in r.errores_de_archivo
            ],
            "lineas_mal_formadas": len(r.lineas_mal_formadas),
            "nulos_por_campo": {
                "leidas": r.nulos_leidas,
                "validas": r.nulos_validas,
                "rechazadas": r.nulos_rechazadas,
            },
        }
    reporte: dict[str, Any] = {
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totales": {
            "leidas": sum(r.leidas for r in resultados.values()),
            "validas": sum(len(r.validas) for r in resultados.values()),
            "rechazadas": sum(r.rechazadas for r in resultados.values()),
            "errores_de_archivo": sum(len(r.errores_de_archivo) for r in resultados.values()),
            "lineas_mal_formadas": sum(len(r.lineas_mal_formadas) for r in resultados.values()),
            "errores_por_tipo": dict(
                Counter(e.tipo_error for r in resultados.values() for e in [*r.errores, *r.lineas_mal_formadas]).most_common()
            ),
        },
        "archivos": archivos,
    }
    z, top = config.salida.z_intervalo_confianza, config.salida.top_medios_concentracion
    noticias = next((r for r in resultados.values() if "idioma" in r.validas.columns and "medio" in r.validas.columns), None)
    if noticias is not None:
        medios, idiomas = _distribucion(noticias.validas["medio"]), _distribucion(noticias.validas["idioma"])
        reporte["distribucion_noticias_validas"] = {
            "por_medio": medios,
            "por_idioma": idiomas,
            "concentracion_medios": _concentracion(medios, top, z),
            "concentracion_idiomas": _concentracion(idiomas, top, z),
        }
    indicadores = next((r for r in resultados.values() if "indicador_id" in r.validas.columns), None)
    if indicadores is not None:
        reporte["indicadores"] = {
            "valor_nulo_leidos": indicadores.nulos_leidas.get("valor", 0),
            "valor_nulo_en_validas": indicadores.nulos_validas.get("valor", 0),
            "valor_nulo_en_rechazadas": indicadores.nulos_rechazadas.get("valor", 0),
        }
    return reporte


def escribir_errores(resultados: dict[str, ResultadoArchivo], ruta: Path) -> int:
    """Escribe ``errores.csv``: errores de archivo, líneas mal formadas y errores de fila. Devuelve cuántas líneas."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    campos = list(ErrorFila.__dataclass_fields__)
    total = 0
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, lineterminator="\n")
        w.writeheader()
        for r in resultados.values():
            for e in [*r.errores_de_archivo, *r.lineas_mal_formadas, *r.errores]:
                w.writerow(asdict(e))
                total += 1
    return total


# ---------------------------------------------------------------- filas válidas (D-82)


def _texto(valor: Any) -> str:
    """Celda CSV: nulo = vacío (nunca 0); números con su representación más corta que ida y vuelta."""
    if valor is None or valor is pd.NA or (isinstance(valor, float) and math.isnan(valor)):
        return ""
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() and abs(valor) < 1e15 else repr(valor)
    return str(valor)


def _escribir_csv_ordenado(ruta: Path, columnas: list[str], df: pd.DataFrame, orden: list[str]) -> None:
    filas = df.reindex(columns=columnas).sort_values(orden, kind="stable").itertuples(index=False)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columnas)
        for fila in filas:
            w.writerow([_texto(v) for v in fila])


def _escribir_json(ruta: Path, objeto: Any) -> None:
    with ruta.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _nativo(valor: Any) -> Any:
    return None if valor is None or valor is pd.NA or (isinstance(valor, float) and math.isnan(valor)) else valor


def escribir_validos(resultados: dict[str, ResultadoArchivo], carpeta: Path, config: ConfigCarga) -> list[Path]:
    """Escribe solo las filas válidas en ``carpeta`` con los nombres de archivo del contrato (D-82).

    Salida determinista: filas ordenadas por clave, UTF-8, saltos LF, nulos vacíos/``null``. No toca
    ningún archivo fuera de ``carpeta``. Un archivo que no se pudo leer no se escribe.
    """
    contrato = cargar_contrato()
    carpeta.mkdir(parents=True, exist_ok=True)
    escritos: list[Path] = []
    a = config.archivos
    for nombre, r in resultados.items():
        if r.archivo != nombre and not len(r.validas.columns):
            continue
        destino = carpeta / nombre
        v = r.validas
        if nombre == a.noticias and len(v.columns):
            _escribir_csv_ordenado(destino, contrato.noticias, v, ["id_noticia"])
        elif nombre == a.indicadores and len(v.columns):
            columnas = [c for c in contrato.indicadores_extra if c in v.columns] + contrato.indicadores
            _escribir_csv_ordenado(destino, columnas, v, config.indicadores.clave)
        elif nombre == a.eventos and len(v.columns):
            features = []
            for p in sorted((dict(zip(v.columns, fila, strict=True)) for fila in v.itertuples(index=False)), key=lambda x: x["id"]):
                p = {k: _nativo(x) for k, x in p.items()}
                coords = [p["longitude"], p["latitude"]] + ([p["depth"]] if p["depth"] is not None else [])
                features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": coords}, "properties": p})
            _escribir_json(destino, {"type": "FeatureCollection", "features": features})
        elif nombre == a.fuentes and len(v.columns):
            registros = [{k: _nativo(x) for k, x in zip(v.columns, fila, strict=True)} for fila in v.itertuples(index=False)]
            _escribir_json(destino, sorted(registros, key=lambda x: x["dominio"]))
        else:
            logger.warning("%s: no se escribe en validos/ (archivo no cargado)", nombre)
            continue
        escritos.append(destino)
    return escritos


def cargar_todo(procesados: Path, config: ConfigCarga | None = None) -> dict[str, ResultadoArchivo]:
    """Carga los cuatro archivos del snapshot. Un archivo ausente se informa y no detiene el resto."""
    config = config or cargar_carga()
    cargadores = {
        config.archivos.noticias: cargar_noticias,
        config.archivos.indicadores: cargar_indicadores,
        config.archivos.eventos: cargar_eventos,
        config.archivos.fuentes: cargar_fuentes,
    }
    resultados: dict[str, ResultadoArchivo] = {}
    for nombre, cargador in cargadores.items():
        ruta = procesados / nombre
        if not ruta.exists():
            logger.error("No existe %s", ruta)
            resultados[nombre] = ResultadoArchivo(
                nombre, 0, pd.DataFrame(), errores_de_archivo=[ErrorFila(nombre, None, "", "", COLUMNA_FALTANTE, "archivo ausente", "")]
            )
            continue
        resultados[nombre] = cargador(ruta, config)
        r = resultados[nombre]
        logger.info("%s: %d leídas, %d válidas, %d rechazadas", nombre, r.leidas, len(r.validas), r.rechazadas)
    return resultados


def main(argv: list[str] | None = None) -> int:
    """CLI: carga el snapshot y escribe ``validos/``, ``errores.csv`` y ``reporte_calidad.json``."""
    configurar_logging()
    parser = argparse.ArgumentParser(description="E1-02: carga, validación y reporte de calidad")
    parser.add_argument("--procesados", type=Path, default=CARPETA_PROCESADOS, help="carpeta con el snapshot")
    parser.add_argument("--salida", type=Path, default=CARPETA_SALIDA, help="carpeta de errores.csv y reporte")
    parser.add_argument("--validos", type=Path, default=None, help="carpeta de las filas válidas (por defecto <procesados>/validos)")
    args = parser.parse_args(argv)
    config = cargar_carga()
    resultados = cargar_todo(args.procesados, config)
    reporte = construir_reporte(resultados, config)
    validos = args.validos or args.procesados / config.salida.carpeta_validos
    escritos = escribir_validos(resultados, validos, config)
    n_errores = escribir_errores(resultados, args.salida / config.salida.errores)
    ruta_reporte = args.salida / config.salida.reporte
    ruta_reporte.write_text(json.dumps(reporte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t = reporte["totales"]
    logger.info(
        "Total: %d leídas, %d válidas, %d rechazadas, %d errores, %d archivos en %s → %s",
        t["leidas"], t["validas"], t["rechazadas"], n_errores, len(escritos), validos, args.salida,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
