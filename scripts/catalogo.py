"""Catálogo de datos para Notion (E1-04): ``outputs/catalogo.csv``, una fila por fuente.

Todo sale de ``data/manifest.json`` (y de los archivos de ``data/processed/`` que el manifest
describe). Es determinista y no usa red: el mismo manifest produce siempre el mismo CSV.
Las columnas son las de la base *Catálogo de datos* de Notion. Lo que no se conoce se escribe
"Pendiente de verificar"; no se inventan licencias ni condiciones.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.conversion import RAIZ, sha256_archivo
from scripts.sbp import COLUMNAS_SBP
from src import configuracion

logger = logging.getLogger(__name__)

COLUMNAS = [
    "Fuente",
    "Archivo",
    "Modalidad",
    "Etapa",
    "URL",
    "Fecha de extracción",
    "Cobertura",
    "Campos",
    "Licencia / condiciones",
    "Transformaciones",
    "Registros válidos",
    "Registros excluidos y motivo",
    "SHA-256",
]
PENDIENTE = "Pendiente de verificar"
PATRON_TS = re.compile(r"_(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z\.[a-z]+$")
PATRON_ANIOS = re.compile(r"date=(\d{4}):(\d{4})")
SIN_REPORTE = "reporte de calidad no generado"
REPORTE_POR_DEFECTO = RAIZ / "outputs" / "reporte_calidad.json"


def _fecha_crudo(ruta: str) -> str | None:
    """Fecha UTC ISO 8601 de la descarga, tomada del nombre del crudo."""
    m = PATRON_TS.search(ruta)
    return None if m is None else "{}-{}-{}T{}:{}:{}Z".format(*m.groups())


def _extraccion(manifest: dict[str, Any], carpeta: str) -> str:
    """Rango (o fecha única) de las descargas de una carpeta de ``raw/``."""
    fechas = sorted(
        f for k in manifest["crudos"] if k.startswith(f"raw/{carpeta}/") and (f := _fecha_crudo(k))
    )
    if not fechas:
        return PENDIENTE
    return fechas[0] if fechas[0] == fechas[-1] else f"{fechas[0]} a {fechas[-1]}"


def _sha(manifest: dict[str, Any], archivo: str) -> str:
    return manifest["sha256"][f"processed/{archivo}"]


def _historial_vigente(manifest: dict[str, Any]) -> dict[str, Any]:
    for entrada in manifest["historial"]:
        if entrada["version"] == manifest["version"]:
            return entrada
    return manifest["historial"][-1]


def _leer_noticias(processed: Path) -> tuple[Counter[str], int]:
    """Noticias por origen y cuántas no tienen fecha_publicacion."""
    with (processed / "noticias.csv").open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    return Counter(f["origen"] for f in filas), sum(1 for f in filas if not f["fecha_publicacion"])


def _versionado(manifest: dict[str, Any]) -> str:
    return (
        f"Snapshot v{manifest['version']} · fecha_corte_UTC {manifest['fecha_corte_UTC']} · "
        f"hash_snapshot {manifest['hash_snapshot']}"
    )


def _validas(reporte: dict[str, Any] | None, manifest: dict[str, Any], archivo: str) -> str:
    """Válidas y leídas según la carga (E1-02); sin reporte, el conteo del manifest."""
    if reporte is None:
        return f"{manifest['cantidad_por_archivo'][archivo]} en el manifest; {SIN_REPORTE}"
    a = reporte["archivos"][archivo]
    return f"{a['validas']} válidas de {a['leidas']} leídas ({archivo})"


def _rechazos(reporte: dict[str, Any] | None, archivo: str) -> str:
    if reporte is None:
        return f"{archivo}: {SIN_REPORTE}"
    a = reporte["archivos"][archivo]
    tipos = ", ".join(f"{t}: {n}" for t, n in sorted(a["errores_por_tipo"].items()))
    return f"{archivo}: {a['rechazadas']} rechazadas por la carga" + (f" ({tipos})" if tipos else "")


def _nulos_indicadores(processed: Path) -> int:
    with (processed / "indicadores.csv").open(encoding="utf-8", newline="") as f:
        return sum(1 for fila in csv.DictReader(f) if fila["valor"] == "")


def _cobertura_noticias(manifest: dict[str, Any], origenes: Counter[str], sin_publicacion: int) -> str:
    c = manifest["cobertura_efectiva"]
    dias = c["gdelt_dias_por_tema"]
    por_tema = "; ".join(
        f"{t} {dias[t]['dias_cubiertos']} de {dias[t]['dias_esperados']}" for t in dias
    )
    sin_cobertura = sorted(t for t in dias if dias[t]["dias_cubiertos"] == 0)
    vol = manifest["volumen_noticias"]
    partes = [
        f"Volumen: {sum(origenes.values())} noticias únicas ({origenes.get('TVN RSS', 0)} de TVN RSS y "
        f"{origenes.get('GDELT', 0)} de GDELT); meta {vol['meta']}, mínimo {vol['minimo']} "
        f"con al menos {vol['minimo_tvn']} de TVN.",
        f"Ventana aplicada (D-74): {c['ventana_dias_aplicada']} días previos a la extracción "
        f"({c['ventana_inicio']} a {c['ventana_fin']}), medida sobre {c['base_de_medicion']}. "
        "Es el filtro de fechas, no la cobertura lograda.",
        f"Los registros de GDELT no traen fecha de publicación ({sin_publicacion} de {sum(origenes.values())} "
        "noticias sin fecha_publicacion); solo tienen fecha_deteccion (seendate).",
        f"Fechas reales: publicación {c['fecha_publicacion_inicial']} a {c['fecha_publicacion_final']}; "
        f"detección {c['fecha_deteccion_inicial']} a {c['fecha_deteccion_final']}.",
        f"Cobertura PARCIAL de las consultas vigentes de GDELT por tema (días cubiertos de los esperados): {por_tema}.",
    ]
    if sin_cobertura:
        partes.append(
            "Sin cobertura de las consultas vigentes de GDELT: " + ", ".join(sin_cobertura) + " (0 días)."
        )
    historica = c.get("gdelt_dias_por_tema_consulta_historica") or {}
    if historica:
        por_tema_h = "; ".join(
            f"{t} {h['dias_cubiertos']} de {h['dias_esperados']}" for t, h in historica.items()
        )
        partes.append(
            "Las noticias de GDELT del snapshot vienen de los crudos de las consultas anteriores a E0-04 (D-89), "
            f"declaradas en el manifest con su consulta histórica; su cobertura va aparte: {por_tema_h}."
        )
    partes.append(
        "El resto de la ventana solo lo aporta el RSS de TVN. Rangos sin resolver (no solicitado, "
        "cobertura parcial o bloqueado por límite de GDELT): ver cobertura_efectiva.gdelt_rangos_sin_resolver "
        "en el manifest. El RSS de TVN no trae firma de autor."
    )
    return " ".join(partes)


def _cobertura_banco_mundial(manifest: dict[str, Any], nulos: int) -> str:
    q = manifest["consultas"]["banco_mundial"]
    paises, indicadores = q["paises"], q["indicadores"]
    m = PATRON_ANIOS.search(q["plantilla_url"])
    if m is None:
        raise ValueError("el manifest no declara el rango de años del Banco Mundial (date=AAAA:AAAA)")
    inicio, fin = int(m.group(1)), int(m.group(2))
    anios = fin - inicio + 1
    filas = manifest["cantidad_por_archivo"]["indicadores.csv"]
    return (
        f"{', '.join(paises)} · {inicio} a {fin} · {len(indicadores)} indicadores · cuadrícula de {filas} combinaciones "
        f"({len(paises)} países x {len(indicadores)} indicadores x {anios} años; D-81). El PDF declara 1.350, pero "
        f"esa cifra no cuadra con esos factores y no se inventaron filas. Valores nulos en el snapshot: {nulos} (los nulos se conservan como nulos, nunca como 0). "
        "Datos anuales: no son actuales."
    )


def _cobertura_usgs(manifest: dict[str, Any]) -> str:
    p = manifest["consultas"]["usgs"]["parametros"]
    return (
        f"{p['starttime'][:10]} a {p['endtime'][:10]} · latitud {p['minlatitude']} a {p['maxlatitude']}, "
        f"longitud {p['minlongitude']} a {p['maxlongitude']} · magnitud >= {p['minmagnitude']} · "
        f"{manifest['cantidad_por_archivo']['eventos.geojson']} eventos. La caja no equivale a Panamá: "
        "se conserva el place original. Solo sirve para hechos sísmicos."
    )


def _transformaciones(manifest: dict[str, Any], prefijos: tuple[str, ...]) -> str:
    return " | ".join(t for t in manifest["transformaciones"] if t.startswith(prefijos))


def _excluidos_noticias(manifest: dict[str, Any], duplicados: int | None, reporte: dict[str, Any] | None) -> str:
    ex = _historial_vigente(manifest)["registros_excluidos"]
    motivos = ", ".join(f"{m}: {n}" for m, n in sorted(ex["por_motivo"].items())) or "sin motivo registrado"
    texto = f"Conversión: {ex['total']} excluidos ({motivos}); detalle en conversion.json."
    if duplicados is not None:
        texto += (
            f" Además {duplicados} duplicados por URL canónica, contados antes de aplicar la ventana "
            "y provenientes de descargas repetidas o solapadas."
        )
    return f"{texto} Carga (E1-02): {_rechazos(reporte, 'noticias.csv')}; {_rechazos(reporte, 'fuentes.json')}."


PATRON_FECHA_SBP = re.compile(r"_(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})\.xlsx$")


def _extraccion_sbp(manifest: dict[str, Any]) -> str:
    """Fechas de las descargas de la SBP, tomadas del nombre de cada crudo (``sbp_<informe>_<YYYYMMDD-HHMMSS>.xlsx``)."""
    fechas = sorted(
        "{}-{}-{}T{}:{}:{}Z".format(*m.groups()) for k in manifest["crudos"] if k.startswith("raw/sbp/") and (m := PATRON_FECHA_SBP.search(k))
    )
    if not fechas:
        return PENDIENTE
    return fechas[0] if fechas[0] == fechas[-1] else f"{fechas[0]} a {fechas[-1]}"


def _fila_sbp(
    manifest: dict[str, Any], processed: Path, reporte: dict[str, Any] | None, lic: dict[str, Any], q: dict[str, Any], cantidad: dict[str, int]
) -> dict[str, str]:
    """Fuente D (E3-02): las series agregadas de la SBP, con la huella del CSV y la de cada .xlsx descargado."""
    sb = q["sbp"]
    series = "; ".join(f"{k} ({v['nombre']}, {v['unidad']})" for k, v in sb["series"].items())
    ruta = processed / "sbp_series.csv"   # no se versiona (D-72, X84): sin el CSV local, los nulos se declaran no verificables
    filas = []
    if ruta.exists():
        with ruta.open(encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
    nulos = sum(1 for x in filas if x["valor"] == "") if filas else "no verificables aquí (el CSV es local)"
    crudos = "; ".join(f"{k.split('/')[-1]}: {v['sha256']}" for k, v in sorted(manifest["crudos"].items()) if k.startswith("raw/sbp/"))
    return {
        "Fuente": "D · SBP (Superintendencia de Bancos de Panamá)",
        "Archivo": "sbp_series.csv",
        "Modalidad": "Banca",
        "Etapa": "Etapa 3",
        "URL": " · ".join(sorted({v["pagina"] for v in sb["informes"].values()})),
        "Fecha de extracción": f"{_extraccion_sbp(manifest)} · {_versionado(manifest)}",
        "Cobertura": f"{len(sb['series'])} series agregadas del sistema bancario, {sb['periodos']}: {series}. "
        f"{cantidad['sbp_series.csv']} filas, {nulos} valores nulos (se conservan como nulos, nunca como 0). "
        "Solo agregados del sistema: nunca información de clientes ni de bancos individuales. Datos mensuales de 2024, no actuales.",
        "Campos": ", ".join(filas[0].keys() if filas else COLUMNAS_SBP),
        "Licencia / condiciones": f"{lic['sbp']}. Solo informativo y sujeto a cambios; la SBP no responde por análisis de terceros; "
        "el análisis es del equipo y no una opinión oficial de la SBP.",
        "Transformaciones": _transformaciones(manifest, ("SBP",)),
        "Registros válidos": f"{cantidad['sbp_series.csv']} filas en el manifest (validadas por scripts.validar_snapshot: columnas, 12 períodos por serie, unidad, página y condiciones)",
        "Registros excluidos y motivo": "Ninguno: la conversión falla si la fila del informe no es la esperada en vez de excluir datos.",
        "SHA-256": f"sbp_series.csv: {_sha(manifest, 'sbp_series.csv')} · crudos (no versionados) {crudos}",
    }


def _fila_sbp_pendiente() -> dict[str, str]:
    """Fuente D sin extraer (snapshot de otra organización o sin banca): queda marcada, sin inventar nada."""
    return {
        "Fuente": "D · SBP (Superintendencia de Bancos de Panamá)",
        "Archivo": "sbp_series.csv (formato propuesto)",
        "Modalidad": "Banca",
        "Etapa": "Etapa 3",
        "URL": "https://www.superbancos.gob.pa",
        "Fecha de extracción": "Pendiente: extracción manual (E3-02)",
        "Cobertura": "Fuente no usada todavía: pendiente de E3-02, solo si se activa banca. 12 informes mensuales de 2024 "
        "o 12 meses documentados; solo series agregadas. No hay datos en el snapshot.",
        "Campos": "id_serie, nombre_serie, periodo, valor (nullable), unidad, informe, pagina, url, "
        "fecha_extraccion, condiciones",
        "Licencia / condiciones": f"{PENDIENTE}. Solo informativo y sujeto a cambios; la SBP no responde por análisis "
        "de terceros; sus opiniones formales están solo en informes oficiales.",
        "Transformaciones": "Extracción manual a CSV con página de origen (E3-02); IDs SBP-<serie>-<período>",
        "Registros válidos": "Fuente no usada todavía: pendiente de E3-02, solo si se activa banca",
        "Registros excluidos y motivo": "Fuente no usada todavía: pendiente de E3-02, solo si se activa banca",
        "SHA-256": "Fuente no usada todavía: pendiente de E3-02, solo si se activa banca",
    }


def construir_filas(
    manifest: dict[str, Any], processed: Path, reporte: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    """Una fila por fuente real (A, B, C) más la pendiente (D), a partir del manifest."""
    cantidad = manifest["cantidad_por_archivo"]
    lic = manifest["licencias"]
    q = manifest["consultas"]
    contrato = configuracion.cargar_contrato()
    origenes, sin_publicacion = _leer_noticias(processed)
    conversion = json.loads((processed / "conversion.json").read_text(encoding="utf-8"))

    noticias = {
        "Fuente": "A · Noticias (TVN RSS + GDELT DOC 2.0)",
        "Archivo": "noticias.csv + fuentes.json",
        "Modalidad": "Común",
        "Etapa": "Etapa 1",
        "URL": f"RSS de TVN: {q['rss_tvn']['url']} · GDELT: {q['gdelt']['endpoint']}",
        "Fecha de extracción": f"RSS de TVN: {_extraccion(manifest, 'rss_tvn')} · "
        f"GDELT: {_extraccion(manifest, 'gdelt')} · {_versionado(manifest)}",
        "Cobertura": _cobertura_noticias(manifest, origenes, sin_publicacion),
        "Campos": ", ".join(contrato.noticias),
        "Licencia / condiciones": f"TVN RSS: {lic['tvn_rss']} GDELT: {lic['gdelt']}",
        "Transformaciones": _transformaciones(
            manifest,
            (
                "RSS de TVN",
                "GDELT",
                "idioma",
                "fuentes.json",
                "Cobertura de GDELT",
                "Deduplicación",
                "id_noticia",
                "tema",
                "Fechas",
                "Ventana",
                "Registros excluidos",
            ),
        ),
        "Registros válidos": f"{_validas(reporte, manifest, 'noticias.csv')} ({origenes.get('TVN RSS', 0)} TVN RSS, "
        f"{origenes.get('GDELT', 0)} GDELT); {_validas(reporte, manifest, 'fuentes.json')}",
        "Registros excluidos y motivo": _excluidos_noticias(manifest, conversion.get("duplicados_descartados"), reporte),
        "SHA-256": f"noticias.csv: {_sha(manifest, 'noticias.csv')} · fuentes.json: {_sha(manifest, 'fuentes.json')} "
        f"· conversion.json: {_sha(manifest, 'conversion.json')}",
    }
    banco = {
        "Fuente": "B · Banco Mundial (Indicators API v2)",
        "Archivo": "indicadores.csv",
        "Modalidad": "Común",
        "Etapa": "Etapa 1",
        "URL": q["banco_mundial"]["plantilla_url"],
        "Fecha de extracción": f"{_extraccion(manifest, 'banco_mundial')} · {_versionado(manifest)}",
        "Cobertura": _cobertura_banco_mundial(manifest, _nulos_indicadores(processed)),
        "Campos": ", ".join([*contrato.indicadores_extra, *contrato.indicadores]),
        "Licencia / condiciones": lic["banco_mundial"],
        "Transformaciones": _transformaciones(manifest, ("Banco Mundial", "indicadores.csv")),
        "Registros válidos": f"{_validas(reporte, manifest, 'indicadores.csv')}; "
        f"{_nulos_indicadores(processed)} con valor nulo",
        "Registros excluidos y motivo": "Manifest: sin exclusiones registradas. Carga (E1-02): "
        f"{_rechazos(reporte, 'indicadores.csv')}. Los nulos se conservan como nulos, nunca como 0.",
        "SHA-256": f"indicadores.csv: {_sha(manifest, 'indicadores.csv')}",
    }
    usgs = {
        "Fuente": "C · USGS eventos sísmicos",
        "Archivo": "eventos.geojson",
        "Modalidad": "Común",
        "Etapa": "Etapa 1",
        "URL": q["usgs"]["endpoint"],
        "Fecha de extracción": f"{_extraccion(manifest, 'usgs')} · {_versionado(manifest)}",
        "Cobertura": _cobertura_usgs(manifest),
        "Campos": ", ".join(contrato.eventos),
        "Licencia / condiciones": lic["usgs"],
        "Transformaciones": _transformaciones(manifest, ("USGS",)),
        "Registros válidos": _validas(reporte, manifest, "eventos.geojson"),
        "Registros excluidos y motivo": "Manifest: sin exclusiones registradas. Carga (E1-02): "
        f"{_rechazos(reporte, 'eventos.geojson')}.",
        "SHA-256": f"eventos.geojson: {_sha(manifest, 'eventos.geojson')}",
    }
    sbp = _fila_sbp(manifest, processed, reporte, lic, q, cantidad) if "sbp_series.csv" in cantidad else _fila_sbp_pendiente()
    return [noticias, banco, usgs, sbp]


def escribir(filas: list[dict[str, str]], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_reporte(ruta: Path, sin_reporte: bool) -> dict[str, Any] | None:
    if sin_reporte:
        return None
    if not ruta.exists():
        raise ValueError(
            f"falta {ruta}: corré primero `poetry run python -m src.carga` (o usá --sin-reporte para marcar "
            f'"{SIN_REPORTE}")'
        )
    return json.loads(ruta.read_text(encoding="utf-8"))


def generar(
    data: Path, destino: Path, reporte: Path = REPORTE_POR_DEFECTO, sin_reporte: bool = False
) -> list[dict[str, str]]:
    """Lee el manifest y el reporte de calidad, comprueba los SHA-256 y escribe el CSV."""
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    for ruta, esperado in manifest["sha256"].items():
        real = sha256_archivo(data / ruta)
        if real != esperado:
            raise ValueError(f"SHA-256 de {ruta} no coincide con el manifest: {real} != {esperado}")
    datos_reporte = _leer_reporte(reporte, sin_reporte)
    filas = construir_filas(manifest, data / "processed", datos_reporte)
    escribir(filas, destino)
    return filas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera outputs/catalogo.csv desde data/manifest.json")
    parser.add_argument("--data", type=Path, default=RAIZ / "data")
    parser.add_argument("--salida", type=Path, default=RAIZ / "outputs" / "catalogo.csv")
    parser.add_argument("--reporte", type=Path, default=REPORTE_POR_DEFECTO, help="reporte de src.carga")
    parser.add_argument("--sin-reporte", action="store_true", help=f'escribe "{SIN_REPORTE}"')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        filas = generar(args.data, args.salida, args.reporte, args.sin_reporte)
    except ValueError as error:
        logger.error("%s", error)
        return 1
    logger.info("%s filas -> %s", len(filas), args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
