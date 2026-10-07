"""Fuente D (E3-02): series agregadas del sistema bancario de la SBP, de los .xlsx públicos a ``sbp_series.csv``.

Cada serie es **una fila** de un informe (la del «Sistema Bancario»); nunca se lee una fila por banco ni por cliente. La fila
se verifica por su etiqueta (``etiqueta_fila`` de ``config/fuentes.yaml``): si la SBP mueve filas, la conversión falla en vez
de leer otra cosa. Los nulos son nulos (celda vacía), nunca 0; la unidad es la original del informe.

Todo es determinista y sin red: el mismo ``raw/sbp/`` produce el mismo CSV. La descarga vive en ``scripts.extraer``.
Los .xlsx crudos no se versionan (el aviso legal de la SBP restringe su redistribución; ``.gitignore``): el CSV conserva solo
los 36 valores agregados, con su página de origen y las condiciones de reutilización.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter

COLUMNAS_SBP = [
    "id_serie",
    "nombre_serie",
    "periodo",
    "valor",
    "unidad",
    "informe",
    "pagina",
    "url",
    "fecha_extraccion",
    "condiciones",
]
PREFIJO_ID = "SBP-"
NOMBRE_CSV = "sbp_series.csv"
PATRON_ARCHIVO_SBP = re.compile(r"^sbp_(?P<informe>[a-z]+)_(?P<fecha>\d{8}-\d{6})\.xlsx$")
FORMATO_FECHA_ARCHIVO = "%Y%m%d-%H%M%S"
FORMATO_ISO = "%Y-%m-%dT%H:%M:%SZ"
COLUMNA_ETIQUETAS = 1          # las etiquetas de fila están en la columna A del informe


class ErrorSbp(ValueError):
    """El informe de la SBP no tiene la forma que la configuración espera."""


def nombre_crudo(informe: str, momento: datetime) -> str:
    """``sbp_<informe>_<YYYYMMDD-HHMMSS>.xlsx`` (sin el patrón ``…T…Z`` de las respuestas de API: el corte del snapshot no se mueve)."""
    return f"sbp_{informe}_{momento.astimezone(UTC).strftime(FORMATO_FECHA_ARCHIVO)}.xlsx"


def fecha_de_crudo(ruta: Path) -> datetime:
    """Fecha de extracción UTC embebida en el nombre del crudo."""
    m = PATRON_ARCHIVO_SBP.match(ruta.name)
    if not m:
        raise ErrorSbp(f"el crudo de la SBP no lleva fecha de extracción en el nombre: {ruta.name}")
    return datetime.strptime(m.group("fecha"), FORMATO_FECHA_ARCHIVO).replace(tzinfo=UTC)


def crudo_mas_reciente(carpeta: Path, informe: str) -> Path | None:
    """El crudo más reciente del informe (los anteriores se conservan: raw/ es inmutable)."""
    candidatos = sorted(p for p in carpeta.glob(f"sbp_{informe}_*.xlsx") if PATRON_ARCHIVO_SBP.match(p.name))
    return candidatos[-1] if candidatos else None


def id_dato(id_serie: str, periodo: str) -> str:
    """``SBP-<serie>-<período>`` (``id_serie`` ya lleva el prefijo ``SBP-``)."""
    return f"{id_serie}-{periodo}"


def _etiqueta(valor: Any) -> str:
    return " ".join(str(valor or "").replace("*", "").split()).casefold()


def _periodo(celda: Any) -> str | None:
    """``YYYY-MM`` de un encabezado de fecha; los encabezados de texto de años viejos («Feb. 2010 (p)») no son de este rango."""
    return celda.strftime("%Y-%m") if isinstance(celda, datetime) else None


def _numero(valor: Any, donde: str) -> float | None:
    if valor is None or valor == "":
        return None                      # un nulo es nulo, nunca 0
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorSbp(f"{donde}: se esperaba un número y hay {valor!r}")
    return float(valor)


def leer_serie(ruta: Path, id_serie: str, cfg: dict[str, Any], informe: dict[str, Any]) -> list[dict[str, Any]]:
    """Los ``periodos_por_serie`` valores de una serie, uno por mes del rango, con su celda de origen."""
    serie = cfg["series"][id_serie]
    libro = openpyxl.load_workbook(ruta, read_only=False, data_only=True)
    try:
        if informe["hoja"] not in libro.sheetnames:
            raise ErrorSbp(f"{ruta.name}: no tiene la hoja {informe['hoja']!r}")
        hoja = libro[informe["hoja"]]
        etiqueta = hoja.cell(row=serie["fila"], column=COLUMNA_ETIQUETAS).value
        if _etiqueta(etiqueta) != _etiqueta(serie["etiqueta_fila"]):
            raise ErrorSbp(
                f"{id_serie}: la fila {serie['fila']} de {ruta.name} se llama {etiqueta!r} y se esperaba {serie['etiqueta_fila']!r}"
            )
        por_periodo: dict[str, tuple[int, Any]] = {}
        for columna in range(COLUMNA_ETIQUETAS + 1, hoja.max_column + 1):
            periodo = _periodo(hoja.cell(row=cfg["fila_de_encabezados"], column=columna).value)
            if periodo is not None and cfg["periodo_inicio"] <= periodo <= cfg["periodo_fin"]:
                if periodo in por_periodo:
                    raise ErrorSbp(f"{ruta.name}: el período {periodo} aparece en dos columnas")
                por_periodo[periodo] = (columna, hoja.cell(row=serie["fila"], column=columna).value)
    finally:
        libro.close()
    if len(por_periodo) != cfg["periodos_por_serie"]:
        raise ErrorSbp(f"{id_serie}: {len(por_periodo)} períodos en {ruta.name} y se esperaban {cfg['periodos_por_serie']}")
    filas = []
    for periodo in sorted(por_periodo):
        columna, valor = por_periodo[periodo]
        celda = f"{get_column_letter(columna)}{serie['fila']}"
        filas.append({"periodo": periodo, "valor": _numero(valor, f"{id_serie} {periodo}"), "celda": celda})
    return filas


def convertir_sbp(carpeta_raw: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Filas de ``sbp_series.csv`` desde ``raw/sbp/``. Sin ningún crudo devuelve ``[]`` (la fuente D es opcional); si falta alguno de los informes, falla nombrando el que falta.

    La URL de cada informe sale del registro de extracción que dejó ``scripts.extraer`` junto al crudo (clave ``url`` del crudo).
    """
    cfg = config["sbp"]
    carpeta = carpeta_raw / cfg["carpeta_cruda"]
    filas: list[dict[str, Any]] = []
    rutas = {clave: crudo_mas_reciente(carpeta, clave) if carpeta.is_dir() else None for clave in cfg["informes"]}
    if not any(rutas.values()):
        return []
    faltan = [f"{cfg['informes'][clave]['nombre']} ({clave})" for clave, ruta in rutas.items() if ruta is None]
    if faltan:   # X90: con un solo informe no se publica una fuente a medias ni se descarta en silencio
        raise ErrorSbp(f"falta el crudo de {', '.join(faltan)} en {carpeta}; corré `scripts.extraer --sbp` o borrá los demás crudos de la SBP")
    for id_serie, serie in cfg["series"].items():
        clave = serie["informe"]
        informe = cfg["informes"][clave]
        ruta = rutas[clave]
        assert ruta is not None
        extraccion = fecha_de_crudo(ruta).strftime(FORMATO_ISO)
        url = _url_registrada(carpeta_raw, ruta, cfg, informe)
        for dato in leer_serie(ruta, id_serie, cfg, informe):
            filas.append(
                {
                    "id_serie": f"{PREFIJO_ID}{id_serie}",
                    "nombre_serie": serie["nombre"],
                    "periodo": dato["periodo"],
                    "valor": dato["valor"],
                    "unidad": serie["unidad"],
                    "informe": informe["nombre"],
                    "pagina": f"hoja «{informe['hoja']}», celda {dato['celda']}",
                    "url": url,
                    "fecha_extraccion": extraccion,
                    "condiciones": " ".join(cfg["condiciones"].split()),
                }
            )
    return sorted(filas, key=lambda f: (f["id_serie"], f["periodo"]))


def _url_registrada(carpeta_raw: Path, ruta: Path, cfg: dict[str, Any], informe: dict[str, Any]) -> str:
    """URL del archivo descargado, tomada del registro de extracción; si falta, la página donde la SBP publica el enlace."""
    registro = carpeta_raw.parent / "registro_extraccion" / f"{ruta.stem}.json"
    if registro.is_file():
        url = json.loads(registro.read_text("utf-8")).get("url")
        if url:
            return str(url)
    return cfg["sitio"] + informe["pagina"]
