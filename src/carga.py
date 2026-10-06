"""Carga y validación lazy de los archivos del snapshot con reporte de calidad (E1-02, T01).

Etapa 1 del flujo. Lee ``noticias.csv`` e ``indicadores.csv`` con pandera en modo *lazy* y
``eventos.geojson`` / ``fuentes.json`` con pydantic (D-19). Reglas:

* Un error no detiene la carga: las filas inválidas se separan con su motivo y el resto sigue.
* Un campo crítico vacío o inválido invalida la fila; un campo opcional vacío solo cuenta como nulo.
* Los nulos son nulos: no se rellenan con cero ni con nada (``valor`` nulo en indicadores es válido).
* No se escribe en ``data/raw/`` ni en ``data/processed/``: la carga solo lee y devuelve las filas
  válidas; los rechazos y el reporte van a ``outputs/``.

Ejecutable con ``poetry run python -m src.carga``.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from src.configuracion import RAIZ, ConfigCarga, cargar_carga
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
    """Resultado de cargar un archivo: filas válidas, errores y conteos."""

    archivo: str
    leidas: int
    validas: pd.DataFrame
    errores: list[ErrorFila] = field(default_factory=list)
    nulos_leidas: dict[str, int] = field(default_factory=dict)
    nulos_validas: dict[str, int] = field(default_factory=dict)
    nulos_rechazadas: dict[str, int] = field(default_factory=dict)

    @property
    def rechazadas(self) -> int:
        """Cantidad de filas con al menos un error (no de errores)."""
        return len({e.fila for e in self.errores if e.fila is not None}) + sum(
            1 for e in self.errores if e.fila is None
        )

    def errores_por_tipo(self) -> dict[str, int]:
        """Cuenta de errores por tipo, de mayor a menor."""
        return dict(Counter(e.tipo_error for e in self.errores).most_common())


# ---------------------------------------------------------------- parsers de fecha (uno por fuente)


def parsear_fecha_iso(texto: Any, config: ConfigCarga) -> datetime | None:
    """ISO 8601 UTC con ``Z`` (formato de ``data/processed/``). ``None`` si no es una fecha real."""
    if not isinstance(texto, str) or not re.match(config.fechas.iso_utc.patron, texto):
        return None
    try:
        return datetime.strptime(texto, config.fechas.iso_utc.formato).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parsear_fecha_gdelt(texto: Any, config: ConfigCarga) -> datetime | None:
    """``seendate`` de GDELT (``20261001T233000Z``). ``None`` si no es una fecha real."""
    if not isinstance(texto, str):
        return None
    try:
        return datetime.strptime(texto, config.fechas.gdelt.formato).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parsear_fecha_rfc822(texto: Any) -> datetime | None:
    """``pubDate`` del RSS (RFC 822). Se normaliza a UTC; ``None`` si no se puede interpretar."""
    if not isinstance(texto, str):
        return None
    try:
        fecha = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        return None
    if fecha.tzinfo is None:
        return None
    return fecha.astimezone(timezone.utc)


def parsear_fecha_usgs(valor: Any) -> datetime | None:
    """``time`` / ``updated`` de USGS en milisegundos epoch. ``None`` si no es un entero válido."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(valor / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


# ---------------------------------------------------------------- utilidades


def _recortar(valor: Any, maximo: int) -> str:
    texto = "" if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor)
    return texto if len(texto) <= maximo else texto[:maximo] + "…"


def _nulos(df: pd.DataFrame) -> dict[str, int]:
    return {str(c): int(n) for c, n in df.isna().sum().items()}


def _leer_csv(ruta: Path, archivo: str, errores: list[ErrorFila]) -> pd.DataFrame:
    """Lee un CSV como texto; vacío = nulo. Las líneas mal formadas se registran y se saltan."""
    malas: list[int] = []

    def _mala(linea: list[str]) -> None:
        malas.append(len(linea))
        return None

    df = pd.read_csv(ruta, dtype=str, keep_default_na=False, engine="python", on_bad_lines=_mala)
    for col in df.columns:
        df[col] = df[col].str.strip().replace("", pd.NA)
    for _ in malas:
        errores.append(
            ErrorFila(archivo, None, "", "", ESTRUCTURA_INVALIDA, "línea con número de campos distinto al encabezado", "")
        )
    return df.reset_index(drop=True)


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
                _check(ID_DUPLICADO, lambda s: ~s.duplicated(keep="first"), "id repetido (se conserva la primera aparición)"),
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
    patron_id = re.compile(i.patron_id)
    patron_url = re.compile(config.patron_url)

    def _es_anio(x: str) -> bool:
        return bool(re.fullmatch(r"\d{4}", x)) and i.anio_minimo <= int(x) <= i.anio_maximo

    def _es_numero(x: str) -> bool:
        try:
            return pd.notna(float(x)) and float(x) not in (float("inf"), float("-inf"))
        except ValueError:
            return False

    columnas: dict[str, pa.Column] = {
        "pais_iso3": pa.Column(str, [_check(VALOR_INVALIDO, lambda s: s.map(lambda x: bool(patron_pais.match(x))), "ISO3 inválido")], nullable=False),
        "indicador_id": pa.Column(str, nullable=False),
        "anio": pa.Column(str, [_check(VALOR_INVALIDO, lambda s: s.map(_es_anio), "año fuera de rango o no entero")], nullable=False),
        # valor nulo es VÁLIDO: solo se rechaza un valor presente que no sea numérico.
        "valor": pa.Column(str, [_check(VALOR_INVALIDO, lambda s: s.map(_es_numero), "valor no numérico")], nullable=True),
        "unidad": pa.Column(str, nullable=False),
        "fuente_url": pa.Column(str, [_check(URL_MAL_FORMADA, lambda s: s.map(lambda x: bool(patron_url.match(x))), "URL mal formada")], nullable=False),
        "fecha_extraccion": pa.Column(str, [_check(FECHA_INVALIDA, lambda s: s.map(lambda x: parsear_fecha_iso(x, config) is not None), "no es ISO 8601 UTC real")], nullable=False),
        "licencia": pa.Column(str, nullable=False),
        # El snapshot real trae id_indicador; el fixture T01 no. Si viene, debe tener la forma del contrato.
        "id_indicador": pa.Column(
            str,
            [
                _check(ID_FORMATO_INVALIDO, lambda s: s.map(lambda x: bool(patron_id.match(x))), "id sin forma IND-<pais>-<indicador>-<anio>"),
                _check(ID_DUPLICADO, lambda s: ~s.duplicated(keep="first"), "id repetido"),
            ],
            nullable=True,
            required=False,
        ),
    }
    clave = i.clave
    return pa.DataFrameSchema(
        columnas,
        checks=[_check(ID_DUPLICADO, lambda df: ~df.duplicated(subset=clave, keep="first"), "clave (país, indicador, año) repetida")],
        strict=False,
        coerce=False,
    )


_CHECKS_A_ERROR = {"not_nullable": OBLIGATORIO_VACIO, "column_in_dataframe": COLUMNA_FALTANTE, "dtype": VALOR_INVALIDO}


def _errores_pandera(
    df: pd.DataFrame,
    esquema: pa.DataFrameSchema,
    archivo: str,
    col_id: str | None,
    maximo: int,
    campos_df: list[str],
) -> list[ErrorFila]:
    """Corre el esquema en modo lazy y traduce cada ``failure_case`` a un ``ErrorFila``."""
    try:
        esquema.validate(df, lazy=True)
        return []
    except pa.errors.SchemaErrors as exc:
        casos = exc.failure_cases
    errores: list[ErrorFila] = []
    vistos_df: set[tuple[int, str]] = set()
    for caso in casos.itertuples(index=False):
        tipo = _CHECKS_A_ERROR.get(str(caso.check), str(caso.check))
        indice = caso.index
        campo = "" if pd.isna(caso.column) else str(caso.column)
        if pd.isna(indice):  # error de columna: afecta a todas las filas
            errores.append(ErrorFila(archivo, None, "", campo, tipo, f"columna {campo}: {tipo}", ""))
            continue
        i = int(indice)
        if str(caso.schema_context) == "DataFrameSchema":  # pandera repite un check de tabla por columna: se junta
            if (i, tipo) in vistos_df:
                continue
            vistos_df.add((i, tipo))
            campo = "|".join(campos_df)
        id_fila = "" if col_id is None or col_id not in df.columns or pd.isna(df.at[i, col_id]) else str(df.at[i, col_id])
        valor = "" if campo not in df.columns else _recortar(df.at[i, campo], maximo)
        errores.append(ErrorFila(archivo, i + 1, id_fila, campo, tipo, _motivo(tipo, campo), valor))
    return errores


def _motivo(tipo: str, campo: str) -> str:
    plantillas = {
        OBLIGATORIO_VACIO: "campo obligatorio vacío",
        FECHA_INVALIDA: "fecha no válida (se espera ISO 8601 UTC)",
        ID_DUPLICADO: "identificador o clave repetidos; se conserva la primera aparición",
        URL_MAL_FORMADA: "URL mal formada",
        ID_FORMATO_INVALIDO: "identificador sin el prefijo o la forma del contrato",
        VALOR_INVALIDO: "valor fuera de dominio",
    }
    return f"{campo}: {plantillas.get(tipo, tipo)}" if campo else plantillas.get(tipo, tipo)


def _consolidar(
    archivo: str, df: pd.DataFrame, errores: list[ErrorFila]
) -> ResultadoArchivo:
    """Separa válidas de rechazadas a partir de los errores y calcula los nulos antes/después."""
    columna_faltante = any(e.tipo_error == COLUMNA_FALTANTE for e in errores)
    malas = set(range(len(df))) if columna_faltante else {e.fila - 1 for e in errores if e.fila is not None}
    if columna_faltante:  # sin una columna crítica ninguna fila puede validarse: cada una lleva el motivo
        errores = errores + [
            ErrorFila(archivo, i + 1, "", "", COLUMNA_FALTANTE, "falta una columna requerida del contrato", "")
            for i in range(len(df))
            if not any(e.fila == i + 1 for e in errores)
        ]
    mascara = df.index.isin(malas)
    validas = df.loc[~mascara].reset_index(drop=True)
    return ResultadoArchivo(
        archivo=archivo,
        leidas=len(df),
        validas=validas,
        errores=errores,
        nulos_leidas=_nulos(df),
        nulos_validas=_nulos(validas),
        nulos_rechazadas=_nulos(df.loc[mascara]),
    )


def cargar_noticias(ruta: Path, config: ConfigCarga | None = None) -> ResultadoArchivo:
    """Carga ``noticias.csv`` (o un fixture con su misma forma) con validación lazy."""
    config = config or cargar_carga()
    errores: list[ErrorFila] = []
    df = _leer_csv(ruta, ruta.name, errores)
    errores += _errores_pandera(df, _esquema_noticias(config), ruta.name, "id_noticia", config.salida.max_caracteres_valor_en_errores, config.noticias.fechas_alternativas)
    return _consolidar(ruta.name, df, errores)


def cargar_indicadores(ruta: Path, config: ConfigCarga | None = None) -> ResultadoArchivo:
    """Carga ``indicadores.csv``. Un ``valor`` nulo es válido y se conserva nulo (nunca 0)."""
    config = config or cargar_carga()
    errores: list[ErrorFila] = []
    df = _leer_csv(ruta, ruta.name, errores)
    errores += _errores_pandera(df, _esquema_indicadores(config), ruta.name, "id_indicador", config.salida.max_caracteres_valor_en_errores, config.indicadores.clave)
    resultado = _consolidar(ruta.name, df, errores)
    if "valor" in resultado.validas.columns:  # texto → número; el nulo sigue siendo nulo
        resultado.validas["valor"] = pd.to_numeric(resultado.validas["valor"], errors="raise").astype("Float64")
        resultado.validas["anio"] = resultado.validas["anio"].astype("int64")
    return resultado


# ---------------------------------------------------------------- pydantic (JSON / GeoJSON)


class _Registro(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=False)


class EventoSismico(_Registro):
    """``properties`` de un Feature de ``eventos.geojson`` (contrato sección 7)."""

    id: str
    magnitude: float
    time: str
    updated: str | None = None
    longitude: float
    latitude: float
    depth: float | None = None
    place: str | None = None
    status: str | None = None
    url: str

    @field_validator("time", "updated")
    @classmethod
    def _fecha(cls, v: str | None) -> str | None:
        if v is not None and parsear_fecha_iso(v, _CONFIG_ACTUAL[0]) is None:
            raise ValueError(FECHA_INVALIDA)
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not re.match(_CONFIG_ACTUAL[0].patron_url, v):
            raise ValueError(URL_MAL_FORMADA)
        return v

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(OBLIGATORIO_VACIO)
        if not re.match(_CONFIG_ACTUAL[0].eventos.patron_id, v):
            raise ValueError(ID_FORMATO_INVALIDO)
        return v

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v: float) -> float:
        if abs(v) > _CONFIG_ACTUAL[0].eventos.latitud_maxima:
            raise ValueError(VALOR_INVALIDO)
        return v

    @field_validator("longitude")
    @classmethod
    def _lon(cls, v: float) -> float:
        if abs(v) > _CONFIG_ACTUAL[0].eventos.longitud_maxima:
            raise ValueError(VALOR_INVALIDO)
        return v


class Fuente(_Registro):
    """Un registro de ``fuentes.json``. ``pais`` es nulable (desconocido = ``null``)."""

    dominio: str
    nombre_legible: str
    pais: str | None = None
    origen: str
    condiciones: str


# Los validadores de pydantic leen la configuración activa desde aquí; se fija en ``_validar_registros``.
_CONFIG_ACTUAL: list[ConfigCarga] = []


def _tipo_error_pydantic(err: dict[str, Any]) -> str:
    if err["type"] == "missing" or (err["type"].endswith("_type") and err.get("input") is None):
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
    _CONFIG_ACTUAL[:] = [config]
    maximo = config.salida.max_caracteres_valor_en_errores
    errores: list[ErrorFila] = []
    validas: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for i, reg in enumerate(registros):
        fila = i + 1
        id_fila = str(reg.get(col_id) or "")
        previos = len(errores)
        try:
            objeto = modelo.model_validate(reg)
        except ValidationError as exc:
            for err in exc.errors():
                campo = str(err["loc"][0]) if err["loc"] else ""
                tipo = _tipo_error_pydantic(err)
                if campo not in criticos and tipo == OBLIGATORIO_VACIO:
                    continue  # un opcional vacío solo es nulo
                errores.append(ErrorFila(archivo, fila, id_fila, campo, tipo, _motivo(tipo, campo), _recortar(reg.get(campo), maximo)))
        else:
            if id_fila in vistos:
                errores.append(ErrorFila(archivo, fila, id_fila, col_id, ID_DUPLICADO, _motivo(ID_DUPLICADO, col_id), id_fila))
        if len(errores) == previos:
            vistos.add(id_fila)
            validas.append(objeto.model_dump())
    df = pd.DataFrame(registros)
    validas_df = pd.DataFrame(validas, columns=list(modelo.model_fields))
    malas = {e.fila - 1 for e in errores if e.fila is not None}
    mascara = df.index.isin(malas)
    return ResultadoArchivo(
        archivo=archivo,
        leidas=len(registros),
        validas=validas_df,
        errores=errores,
        nulos_leidas=_nulos(df.reindex(columns=list(modelo.model_fields))),
        nulos_validas=_nulos(validas_df),
        nulos_rechazadas=_nulos(df.loc[mascara].reindex(columns=list(modelo.model_fields))),
    )


def cargar_eventos(ruta: Path, config: ConfigCarga | None = None) -> ResultadoArchivo:
    """Carga ``eventos.geojson``: valida las ``properties`` de cada Feature con pydantic."""
    config = config or cargar_carga()
    features = json.loads(ruta.read_text("utf-8")).get("features", [])
    registros = [f.get("properties", {}) if isinstance(f, dict) else {} for f in features]
    criticos = ["id", "magnitude", "time", "longitude", "latitude", "url"]
    return _validar_registros(ruta.name, registros, EventoSismico, "id", criticos, config)


def cargar_fuentes(ruta: Path, config: ConfigCarga | None = None) -> ResultadoArchivo:
    """Carga ``fuentes.json`` (un registro por medio)."""
    config = config or cargar_carga()
    registros = json.loads(ruta.read_text("utf-8"))
    return _validar_registros(ruta.name, registros, Fuente, "dominio", config.fuentes.criticos, config)


# ---------------------------------------------------------------- reporte


def _distribucion(serie: pd.Series) -> dict[str, int]:
    cuenta = serie.value_counts(dropna=False)
    return {("(nulo)" if pd.isna(k) else str(k)): int(v) for k, v in cuenta.items()}


def _concentracion(distribucion: dict[str, int], top: int) -> dict[str, Any]:
    total = sum(distribucion.values())
    principales = dict(list(distribucion.items())[:top])
    return {
        "top_n": top,
        "principales": principales,
        "porcentaje_top_n": round(100 * sum(principales.values()) / total, 2) if total else None,
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
            "errores_por_tipo": dict(
                Counter(e.tipo_error for r in resultados.values() for e in r.errores).most_common()
            ),
        },
        "archivos": archivos,
    }
    noticias = next((r for r in resultados.values() if "idioma" in r.validas.columns and "medio" in r.validas.columns), None)
    if noticias is not None:
        medios, idiomas = _distribucion(noticias.validas["medio"]), _distribucion(noticias.validas["idioma"])
        reporte["distribucion_noticias_validas"] = {
            "por_medio": medios,
            "por_idioma": idiomas,
            "concentracion_medios": _concentracion(medios, config.salida.top_medios_concentracion),
            "concentracion_idiomas": _concentracion(idiomas, config.salida.top_medios_concentracion),
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
    """Escribe ``errores.csv`` (una línea por motivo de rechazo). Devuelve cuántas líneas."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    campos = list(ErrorFila.__dataclass_fields__)
    total = 0
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for r in resultados.values():
            for e in r.errores:
                w.writerow(asdict(e))
                total += 1
    return total


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
                nombre, 0, pd.DataFrame(), [ErrorFila(nombre, None, "", "", COLUMNA_FALTANTE, "archivo ausente", "")]
            )
            continue
        resultados[nombre] = cargador(ruta, config)
        r = resultados[nombre]
        logger.info("%s: %d leídas, %d válidas, %d rechazadas", nombre, r.leidas, len(r.validas), r.rechazadas)
    return resultados


def main(argv: list[str] | None = None) -> int:
    """CLI: carga el snapshot y escribe ``errores.csv`` y ``reporte_calidad.json``."""
    configurar_logging()
    parser = argparse.ArgumentParser(description="E1-02: carga, validación y reporte de calidad")
    parser.add_argument("--procesados", type=Path, default=CARPETA_PROCESADOS, help="carpeta con el snapshot")
    parser.add_argument("--salida", type=Path, default=CARPETA_SALIDA, help="carpeta de errores.csv y reporte")
    args = parser.parse_args(argv)
    config = cargar_carga()
    resultados = cargar_todo(args.procesados, config)
    reporte = construir_reporte(resultados, config)
    n_errores = escribir_errores(resultados, args.salida / config.salida.errores)
    ruta_reporte = args.salida / config.salida.reporte
    ruta_reporte.write_text(json.dumps(reporte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t = reporte["totales"]
    logger.info(
        "Total: %d leídas, %d válidas, %d rechazadas, %d errores → %s",
        t["leidas"], t["validas"], t["rechazadas"], n_errores, args.salida,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
