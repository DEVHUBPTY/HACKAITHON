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
ORDEN_TEMAS = ["economia", "logistica", "turismo", "eventos_naturales"]


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


def _conteo_origen(processed: Path) -> Counter[str]:
    with (processed / "noticias.csv").open(encoding="utf-8", newline="") as f:
        return Counter(fila["origen"] for fila in csv.DictReader(f))


def _nulos_indicadores(processed: Path) -> int:
    with (processed / "indicadores.csv").open(encoding="utf-8", newline="") as f:
        return sum(1 for fila in csv.DictReader(f) if fila["valor"] == "")


def _cobertura_noticias(manifest: dict[str, Any], origenes: Counter[str]) -> str:
    c = manifest["cobertura_efectiva"]
    dias = c["gdelt_dias_por_tema"]
    por_tema = "; ".join(
        f"{t} {dias[t]['dias_cubiertos']} de {dias[t]['dias_esperados']}" for t in ORDEN_TEMAS if t in dias
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
        f"Fechas reales: publicación {c['fecha_publicacion_inicial']} a {c['fecha_publicacion_final']}; "
        f"detección {c['fecha_deteccion_inicial']} a {c['fecha_deteccion_final']}.",
        f"Cobertura PARCIAL de GDELT por tema (días cubiertos de los esperados): {por_tema}.",
    ]
    if sin_cobertura:
        partes.append(
            "Sin cobertura de GDELT: " + ", ".join(sin_cobertura) + " (0 días; no hay noticias de GDELT de ese tema)."
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
    filas = manifest["cantidad_por_archivo"]["indicadores.csv"]
    return (
        f"{', '.join(paises)} · 2010 a 2024 · {len(indicadores)} indicadores · cuadrícula de {filas} combinaciones "
        f"({len(paises)} países x {len(indicadores)} indicadores x 15 años; D-81). El PDF declara 1.350, pero "
        f"esa cifra no cuadra con esos factores y no se inventaron filas. {nulos} valores nulos explícitos. "
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


def _excluidos_noticias(manifest: dict[str, Any], duplicados: int | None) -> str:
    ex = _historial_vigente(manifest)["registros_excluidos"]
    motivos = ", ".join(f"{m}: {n}" for m, n in sorted(ex["por_motivo"].items())) or "sin motivo registrado"
    texto = f"{ex['total']} excluidos ({motivos}); detalle en conversion.json."
    if duplicados is not None:
        texto += f" Además {duplicados} duplicados por URL canónica descartados."
    return texto


def construir_filas(manifest: dict[str, Any], processed: Path) -> list[dict[str, str]]:
    """Una fila por fuente real (A, B, C) más la pendiente (D), a partir del manifest."""
    cantidad = manifest["cantidad_por_archivo"]
    lic = manifest["licencias"]
    q = manifest["consultas"]
    contrato = configuracion.cargar_contrato()
    origenes = _conteo_origen(processed)
    conversion = json.loads((processed / "conversion.json").read_text(encoding="utf-8"))

    noticias = {
        "Fuente": "A · Noticias (TVN RSS + GDELT DOC 2.0)",
        "Archivo": "noticias.csv + fuentes.json",
        "Modalidad": "Común",
        "Etapa": "Etapa 1",
        "URL": f"RSS de TVN: {q['rss_tvn']['url']} · GDELT: {q['gdelt']['endpoint']}",
        "Fecha de extracción": f"RSS de TVN: {_extraccion(manifest, 'rss_tvn')} · GDELT: {_extraccion(manifest, 'gdelt')}",
        "Cobertura": _cobertura_noticias(manifest, origenes),
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
        "Registros válidos": f"{cantidad['noticias.csv']} noticias ({origenes.get('TVN RSS', 0)} TVN RSS, "
        f"{origenes.get('GDELT', 0)} GDELT) y {cantidad['fuentes.json']} medios en fuentes.json",
        "Registros excluidos y motivo": _excluidos_noticias(manifest, conversion.get("duplicados_descartados")),
        "SHA-256": f"noticias.csv: {_sha(manifest, 'noticias.csv')} · fuentes.json: {_sha(manifest, 'fuentes.json')} "
        f"· conversion.json: {_sha(manifest, 'conversion.json')}",
    }
    banco = {
        "Fuente": "B · Banco Mundial (Indicators API v2)",
        "Archivo": "indicadores.csv",
        "Modalidad": "Común",
        "Etapa": "Etapa 1",
        "URL": q["banco_mundial"]["plantilla_url"],
        "Fecha de extracción": _extraccion(manifest, "banco_mundial"),
        "Cobertura": _cobertura_banco_mundial(manifest, _nulos_indicadores(processed)),
        "Campos": ", ".join([*contrato.indicadores_extra, *contrato.indicadores]),
        "Licencia / condiciones": lic["banco_mundial"],
        "Transformaciones": _transformaciones(manifest, ("Banco Mundial", "indicadores.csv")),
        "Registros válidos": f"{cantidad['indicadores.csv']} filas (incluye nulos explícitos)",
        "Registros excluidos y motivo": "0: no hay exclusiones registradas en el manifest; "
        "los nulos se conservan como nulos, nunca como 0.",
        "SHA-256": f"indicadores.csv: {_sha(manifest, 'indicadores.csv')}",
    }
    usgs = {
        "Fuente": "C · USGS eventos sísmicos",
        "Archivo": "eventos.geojson",
        "Modalidad": "Común",
        "Etapa": "Etapa 1",
        "URL": q["usgs"]["endpoint"],
        "Fecha de extracción": _extraccion(manifest, "usgs"),
        "Cobertura": _cobertura_usgs(manifest),
        "Campos": ", ".join(contrato.eventos),
        "Licencia / condiciones": lic["usgs"],
        "Transformaciones": _transformaciones(manifest, ("USGS",)),
        "Registros válidos": f"{cantidad['eventos.geojson']} eventos",
        "Registros excluidos y motivo": "0: no hay exclusiones registradas en el manifest.",
        "SHA-256": f"eventos.geojson: {_sha(manifest, 'eventos.geojson')}",
    }
    sbp = {
        "Fuente": "D · SBP (Superintendencia de Bancos de Panamá)",
        "Archivo": "sbp_series.csv (formato propuesto)",
        "Modalidad": "Banca",
        "Etapa": "Etapa 3",
        "URL": "https://www.superbancos.gob.pa",
        "Fecha de extracción": "Pendiente: extracción manual (E3-02)",
        "Cobertura": "Pendiente (E3-02): 12 informes mensuales de 2024 o 12 meses documentados; solo series agregadas. "
        "Aún no hay datos en el snapshot; no se cuenta como fuente usada.",
        "Campos": "id_serie, nombre_serie, periodo, valor (nullable), unidad, informe, pagina, url, "
        "fecha_extraccion, condiciones",
        "Licencia / condiciones": f"{PENDIENTE}. Solo informativo y sujeto a cambios; la SBP no responde por análisis "
        "de terceros; sus opiniones formales están solo en informes oficiales.",
        "Transformaciones": "Extracción manual a CSV con página de origen (E3-02); IDs SBP-<serie>-<período>",
        "Registros válidos": "Pendiente (E3-02)",
        "Registros excluidos y motivo": "Pendiente (E3-02)",
        "SHA-256": "Pendiente (E3-02)",
    }
    return [noticias, banco, usgs, sbp]


def escribir(filas: list[dict[str, str]], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(filas)


def generar(data: Path, destino: Path) -> list[dict[str, str]]:
    """Lee el manifest, comprueba los SHA-256 contra los archivos y escribe el CSV."""
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    for ruta, esperado in manifest["sha256"].items():
        real = sha256_archivo(data / ruta)
        if real != esperado:
            raise ValueError(f"SHA-256 de {ruta} no coincide con el manifest: {real} != {esperado}")
    filas = construir_filas(manifest, data / "processed")
    escribir(filas, destino)
    return filas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera outputs/catalogo.csv desde data/manifest.json")
    parser.add_argument("--data", type=Path, default=RAIZ / "data")
    parser.add_argument("--salida", type=Path, default=RAIZ / "outputs" / "catalogo.csv")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        filas = generar(args.data, args.salida)
    except ValueError as error:
        logger.error("%s", error)
        return 1
    logger.info("%s filas -> %s", len(filas), args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
