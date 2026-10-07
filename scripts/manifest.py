"""Genera ``data/manifest.json`` y ``data/CHANGELOG.md`` (E0-04, D-63).

El manifest es **determinista**: ``fecha_corte_UTC`` sale de las marcas de tiempo de los crudos
(no de ``now()``), las claves van ordenadas y el historial solo crece cuando el snapshot cambia.
Dos corridas sobre el mismo ``raw/`` producen el mismo archivo, byte a byte.

Uso: ``poetry run python -m scripts.manifest [--data data]``
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from scripts import conversion
from scripts.conversion import RAIZ, a_iso, sha256_archivo, ts_de_archivo
from src import consultas_gdelt
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

ARCHIVOS_PROCESSED = [
    "conversion.json",
    "eventos.geojson",
    "fuentes.json",
    "indicadores.csv",
    "noticias.csv",
]


def nota_intervalo_pdf(config: dict[str, Any]) -> str:
    """Documenta la inconsistencia entre las secciones 6 y 7 del PDF (D-74)."""
    desde, hasta = config["ventana_noticias"]["intervalo_pdf_seccion_7_no_aplicado"]
    return (
        "Inconsistencia del PDF (D-74): la sección 6 pide noticias de los 30 días previos a la "
        "extracción (ampliable a 90) y la sección 7 pide excluir lo que quede fuera del intervalo "
        f"[{desde}, {hasta}). Ese intervalo no se aplica porque es imposible de extraer hoy: "
        "GDELT DOC solo cubre ~3 meses hacia atrás y el RSS de TVN no conserva todo el histórico. "
        "Se aplica la ventana de la sección 6, medida sobre "
        f"{config['ventana_noticias']['base_de_medicion']} (fecha_publicacion si el registro no pasó por GDELT)."
    )


TRANSFORMACIONES = [
    "RSS de TVN: feedparser; la descripción se usa solo en crudo y no se copia a processed/ (D-31, D-72).",
    "GDELT: seendate -> fecha_deteccion (nunca fecha_publicacion); socialimage descartado (D-72).",
    "idioma: código ISO 639-1; GDELT entrega el nombre del idioma y se traduce con la tabla gdelt.idiomas de config/fuentes.yaml.",
    "fuentes.json: pais = sourcecountry de GDELT traducido al español con paises_es (nulo si no se conoce); "
    "'Pendiente de verificar' solo aplica a condiciones.",
    "Cobertura de GDELT: un día cuenta como cubierto solo si un crudo con articles lo contiene completo; un {} "
    "no prueba ausencia de resultados y queda como vacio_sospechoso (ver cobertura_efectiva).",
    "GDELT sin fecha de publicación: fecha_publicacion queda vacía salvo que la misma URL esté en el RSS.",
    "Deduplicación por URL canónica (esquema https, sin www, sin fragmento ni parámetros de rastreo).",
    "id_noticia = NOT- + primeros 10 caracteres del SHA-1 de la URL canónica (D-63).",
    "tema = tema de origen: clave de consulta de GDELT o primera sección de la URL del RSS (D-62); "
    "si una URL aparece en varios temas se unen con '|'.",
    "Fechas ISO 8601 UTC con sufijo Z; la hora de Panamá solo se muestra en la interfaz.",
    "Ventana de noticias: 30 días previos a la extracción; si hay menos del mínimo, hasta 90 días (D-74).",
    "Banco Mundial: una consulta por indicador; cuadrícula completada con todas las combinaciones país × indicador × año (540; el PDF dice 1.350, ver nota_cuadricula_banco_mundial), valor vacío (nulo), nunca 0.",
    "indicadores.csv: id_indicador = IND-<país>-<indicador>-<año>; unidad tomada de config/fuentes.yaml.",
    "USGS: id = SIS-<id USGS>; time y updated de milisegundos epoch a ISO 8601 UTC; longitude, latitude y depth de la geometría.",
    "Registros excluidos (sin título, sin URL, sin fecha válida, fuera de ventana) se listan en conversion.json.",
]


def _transformaciones(auditoria: dict[str, Any]) -> list[str]:
    """Transformaciones fijas más la alerta de idiomas que no tienen código ISO en la configuración."""
    sin_mapeo = auditoria.get("idiomas_sin_mapeo") or {}
    extra = (
        [
            "idioma sin código ISO 639-1 en gdelt.idiomas (se conservó el nombre en minúsculas): "
            + ", ".join(f"{k} ({v})" for k, v in sin_mapeo.items())
        ]
        if sin_mapeo
        else []
    )
    return [*TRANSFORMACIONES, *extra]


def nota_cuadricula(config: dict[str, Any]) -> str:
    """Documenta la diferencia entre la cuadrícula declarada por el PDF y la aritmética real."""
    bm = config["banco_mundial"]
    p, i, a = len(bm["paises"]), len(bm["indicadores"]), bm["anio_fin"] - bm["anio_inicio"] + 1
    return (
        f"El PDF (secciones 6 y 7) declara {bm['cuadricula_declarada_en_pdf']} combinaciones "
        f"país × indicador × año, pero {p} países × {i} indicadores × {a} años = {p * i * a}. "
        f"El snapshot contiene las {p * i * a} combinaciones reales, con nulos explícitos; no se "
        "inventan filas para llegar a la cifra del PDF."
    )


def _contar_filas_csv(ruta: Path) -> int:
    with ruta.open(encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def _cantidad_por_archivo(processed: Path) -> dict[str, int]:
    cantidades = {
        "noticias.csv": _contar_filas_csv(processed / "noticias.csv"),
        "indicadores.csv": _contar_filas_csv(processed / "indicadores.csv"),
    }
    cantidades["fuentes.json"] = len(json.loads((processed / "fuentes.json").read_text("utf-8")))
    cantidades["eventos.geojson"] = len(
        json.loads((processed / "eventos.geojson").read_text("utf-8"))["features"]
    )
    cantidades["conversion.json"] = len(
        json.loads((processed / "conversion.json").read_text("utf-8"))["excluidos"]
    )
    return dict(sorted(cantidades.items()))


def _crudos(raw: Path) -> dict[str, dict[str, Any]]:
    """Huella de cada respuesta cruda de la API (los de RSS y GDELT no se versionan, pero su hash sí se registra)."""
    crudos = {}
    for ruta in sorted(p for p in raw.rglob("*") if p.is_file() and not p.name.startswith(".")):
        crudos[ruta.relative_to(raw.parent).as_posix()] = {
            "bytes": ruta.stat().st_size,
            "sha256": sha256_archivo(ruta),
        }
    return crudos


def _registro_extraccion(data: Path, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Huella y origen de cada archivo de ``registro_extraccion/`` (fallos y notas; no son respuestas de API)."""
    carpeta = data / config["general"]["carpeta_registro"]
    if not carpeta.is_dir():
        return {}
    registro = {}
    for ruta in sorted(p for p in carpeta.glob("*.json") if p.is_file()):
        cuerpo = json.loads(ruta.read_text("utf-8"))
        origen = "" if isinstance(cuerpo, list) else cuerpo.get("origen", "")
        registro[ruta.relative_to(data).as_posix()] = {
            "bytes": ruta.stat().st_size,
            "sha256": sha256_archivo(ruta),
            "origen": origen or "sin origen declarado",
        }
    return registro


def _es_respuesta_de_api(ruta: Path) -> bool:
    """Las respuestas de la API llevan marca de tiempo y no son registros de fallos."""
    return not ruta.name.startswith(("fallos_", ".")) and conversion.PATRON_TS_ARCHIVO.search(ruta.name) is not None


def _fecha_corte(raw: Path) -> str:
    """Marca de tiempo más reciente entre las respuestas reales de la API (nunca fallos ni notas)."""
    marcas = [ts_de_archivo(p) for p in raw.rglob("*") if p.is_file() and _es_respuesta_de_api(p)]
    return a_iso(max(marcas)) if marcas else ""


def _cobertura(processed: Path, auditoria: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Fechas reales de la bandeja A: primera y última sobre la base de medición de la ventana."""
    with (processed / "noticias.csv").open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    referencia = [r["fecha_deteccion"] or r["fecha_publicacion"] for r in filas]
    referencia = [x for x in referencia if x]
    publicacion = [r["fecha_publicacion"] for r in filas if r["fecha_publicacion"]]
    deteccion = [r["fecha_deteccion"] for r in filas if r["fecha_deteccion"]]
    return {
        "base_de_medicion": f"{config['ventana_noticias']['base_de_medicion']}; fecha_publicacion si el registro no tiene detección",
        "fecha_inicial": min(referencia, default=""),
        "fecha_final": max(referencia, default=""),
        "fecha_deteccion_inicial": min(deteccion, default=""),
        "fecha_deteccion_final": max(deteccion, default=""),
        "fecha_publicacion_inicial": min(publicacion, default=""),
        "fecha_publicacion_final": max(publicacion, default=""),
        "ventana_dias_aplicada": auditoria["ventana"]["dias_aplicados"],
        "nota_ventana": (
            "ventana_dias_aplicada es el filtro de fechas de las noticias, no la cobertura lograda: GDELT cubre "
            "solo los días de gdelt_dias_por_tema.dias_cubiertos y el resto de la ventana, salvo lo que aporta "
            "el RSS de TVN, está en gdelt_rangos_sin_resolver."
        ),
        "gdelt_dias_por_tema": auditoria.get("gdelt_cobertura_por_tema", {}),
        "gdelt_dias_por_tema_consulta_historica": auditoria.get("gdelt_cobertura_historica_por_tema", {}),
        "nota_cobertura_historica": (
            "gdelt_dias_por_tema mide solo las consultas vigentes (E0-04, dos patas por tema). Los crudos de las "
            "consultas anteriores a E0-04 alimentan noticias.csv (D-89) y su cobertura se informa aparte en "
            "gdelt_dias_por_tema_consulta_historica; no se suma a la de las consultas vigentes."
        ),
        "ventana_ampliada_a_90": auditoria["ventana"]["ampliada"],
        "ventana_inicio": auditoria["ventana"]["inicio"],
        "ventana_fin": auditoria["ventana"]["fin"],
        "gdelt_rangos_sin_resolver": auditoria.get("gdelt_rangos_sin_resolver", []),
    }


def _consultas(config: dict[str, Any]) -> dict[str, Any]:
    g, bm, u = config["gdelt"], config["banco_mundial"], config["usgs"]
    return {
        "rss_tvn": {
            "url": config["rss_tvn"]["url"],
            "nota": "URL tomada del hipervínculo de la referencia [2] del PDF; se descarga a diario y se acumula.",
        },
        "gdelt": {
            "endpoint": g["endpoint"],
            "modo": g["modo"],
            "formato": g["formato"],
            "maxrecords": g["maxrecords"],
            "orden": g["orden"],
            "rango_dias_inicial": g["rango_dias"],
            "consultas_por_tema": consultas_gdelt.consultas_por_tema(g["consultas"], g["largo_minimo_termino"]),
            "consultas_historicas": g["consultas_historicas"],
            "motivo_cambio_consultas": g["motivo_cambio_consultas"],
            "ampliar_ventana_si_no_alcanza_minimo": config["ventana_noticias"]["ampliar_si_no_alcanza_minimo"],
        },
        "banco_mundial": {
            "plantilla_url": (
                f"{bm['base_url']}/country/{';'.join(bm['paises'])}/indicator/{{indicador}}"
                f"?format=json&date={bm['anio_inicio']}:{bm['anio_fin']}&per_page={bm['per_page']}"
            ),
            "indicadores": {k: v["nombre"] for k, v in bm["indicadores"].items()},
            "paises": bm["paises"],
        },
        "usgs": {
            "endpoint": u["endpoint"],
            "parametros": {
                k: u[k]
                for k in (
                    "starttime", "endtime", "minlatitude", "maxlatitude", "minlongitude",
                    "maxlongitude", "minmagnitude", "orderby",
                )
            }
            | {"format": u["formato"]},
        },
    }


def _licencias(config: dict[str, Any]) -> dict[str, str]:
    return {
        "banco_mundial": config["banco_mundial"]["licencia"],
        "gdelt": (
            "La API de GDELT no transfiere derechos de los medios enlazados; solo metadatos "
            "(socialimage no se guarda)."
        ),
        "tvn_rss": config["medios_conocidos"][config["medio_tvn_dominio"]]["condiciones"].strip(),
        "usgs": config["usgs"]["licencia"],
    }


def _revisiones_banco_mundial(raw: Path, config: dict[str, Any]) -> list[str]:
    """Detecta valores que cambiaron entre dos extracciones del mismo indicador."""
    carpeta = raw / config["banco_mundial"]["carpeta_cruda"]
    por_indicador: dict[str, list[Path]] = {}
    for ruta in conversion.archivos_crudos(carpeta, "wb_*.json"):
        m = conversion.PATRON_ARCHIVO_WB.match(ruta.name)
        if m:
            por_indicador.setdefault(m.group("ind"), []).append(ruta)
    revisiones = []
    for ind, rutas in sorted(por_indicador.items()):
        if len(rutas) < 2:
            continue

        def valores(ruta: Path) -> dict[tuple[str, str], Any]:
            cuerpo = json.loads(ruta.read_text(encoding="utf-8"))
            return {(r["countryiso3code"], r["date"]): r.get("value") for r in cuerpo[1] or []}

        antes, despues = valores(rutas[-2]), valores(rutas[-1])
        cambios = sum(1 for k in antes.keys() & despues.keys() if antes[k] != despues[k])
        if cambios:
            revisiones.append(
                f"{ind}: {cambios} valores cambiaron entre {rutas[-2].name} y {rutas[-1].name}"
            )
    return revisiones


def _contar_por(items: list[dict[str, Any]], clave: str) -> dict[str, int]:
    cuenta: dict[str, int] = {}
    for x in items:
        cuenta[x[clave]] = cuenta.get(x[clave], 0) + 1
    return dict(sorted(cuenta.items()))


def _historial(
    previo: list[dict[str, Any]],
    fecha: str,
    hash_snapshot: str,
    cantidades: dict[str, int],
    auditoria: dict[str, Any],
    revisiones: list[str],
    config: dict[str, Any],
    sha: dict[str, str] | None = None,
    motivo: str | None = None,
) -> list[dict[str, Any]]:
    """Agrega una versión solo si el snapshot cambió; si no, devuelve el historial intacto.

    ``motivo`` describe el cambio con palabras del equipo. Si el snapshot no cambió,
    se agrega como nota a la última versión (sin duplicarse), para poder explicar
    un cambio ya registrado con un texto genérico.
    """
    sha = sha or {}
    if previo and previo[-1]["hash_snapshot"] == hash_snapshot:
        if motivo and motivo not in previo[-1].get("notas", []):
            ultima = {**previo[-1], "notas": [*previo[-1].get("notas", []), motivo]}
            return [*previo[:-1], ultima]
        return previo
    motivos: dict[str, int] = {}
    for x in auditoria["excluidos"]:
        motivos[x["motivo"]] = motivos.get(x["motivo"], 0) + 1
    if previo:
        anterior = previo[-1]["cantidad_por_archivo"]
        sha_previo = previo[-1].get("sha256_por_archivo", {})
        cambios = [
            f"{k}: {anterior.get(k, 0)} -> {v}" for k, v in cantidades.items() if anterior.get(k) != v
        ]
        cambios += [
            f"Contenido distinto en {k} (mismo conteo)"
            for k in sorted(sha)
            if sha_previo and sha_previo.get(k) != sha[k] and k.split("/")[-1] not in
            {c.split(":")[0] for c in cambios}
        ]
        if motivo:
            cambios.insert(0, motivo)
        cambios = cambios or ["Cambió el contenido sin cambiar los conteos"]
    else:
        cambios = [
            "Snapshot inicial construido por el equipo con la receta de scripts.extraer (D-74).",
            f"URL del RSS de TVN: {config['rss_tvn']['url']} (tomada del hipervínculo [2] del PDF).",
        ]
    entrada = {
        "version": f"1.{len(previo)}",
        "fecha": fecha,
        "nota_fecha": "fecha de corte de los datos (último crudo real), no la fecha en que se generó la versión",
        "hash_snapshot": hash_snapshot,
        "sha256_por_archivo": sha,
        "cambios_de_fuente": cambios,
        "revisiones_de_datos": revisiones,
        "fallos_de_extraccion": auditoria.get("gdelt_rangos_sin_resolver", []),
        "crudos_consulta_historica": {
            "total": len(auditoria.get("crudos_consulta_historica", [])),
            "por_tema": _contar_por(auditoria.get("crudos_consulta_historica", []), "tema"),
        },
        "registros_excluidos": {"total": len(auditoria["excluidos"]), "por_motivo": dict(sorted(motivos.items()))},
        "cantidad_por_archivo": cantidades,
    }
    return [*previo, entrada]


def conservar_reproducibilidad(manifest: dict[str, Any], previo: dict[str, Any]) -> dict[str, Any]:
    """Regenerar el manifest no borra el registro de ``scripts.reproducir`` (E1-20): lo escribe otro script y se conserva tal cual."""
    if "reproducibilidad" in previo:
        return {**manifest, "reproducibilidad": previo["reproducibilidad"]}
    return manifest


def construir_manifest(data: Path, config: dict[str, Any], motivo: str | None = None) -> dict[str, Any]:
    """Arma el manifest a partir de ``data/raw`` y ``data/processed`` (y del manifest previo)."""
    raw, processed = data / "raw", data / "processed"
    auditoria = json.loads((processed / "conversion.json").read_text("utf-8"))
    sha = {f"processed/{n}": sha256_archivo(processed / n) for n in ARCHIVOS_PROCESSED}
    hash_snapshot = hashlib.sha256(json.dumps(sha, sort_keys=True).encode()).hexdigest()
    cantidades = _cantidad_por_archivo(processed)
    fecha = _fecha_corte(raw)
    ruta_previa = data / "manifest.json"
    previo = json.loads(ruta_previa.read_text("utf-8")).get("historial", []) if ruta_previa.exists() else []
    consultas = _consultas(config)
    if ruta_previa.exists():
        antes = json.loads(ruta_previa.read_text("utf-8")).get("consultas", {}).get("gdelt", {})
        if antes.get("consultas_por_tema") != consultas["gdelt"]["consultas_por_tema"]:
            cambio = f"Consultas de GDELT modificadas: {config['gdelt']['motivo_cambio_consultas']}"
            motivo = f"{motivo} | {cambio}" if motivo else cambio
    historial = _historial(
        previo, fecha, hash_snapshot, cantidades, auditoria, _revisiones_banco_mundial(raw, config), config,
        sha, motivo,
    )
    manifest = {
        "version": historial[-1]["version"],
        "fecha_corte_UTC": fecha,
        "hash_snapshot": hash_snapshot,
        "consultas": consultas,
        "cantidad_por_archivo": cantidades,
        "licencias": _licencias(config),
        "sha256": sha,
        "transformaciones": _transformaciones(auditoria),
        "cobertura_efectiva": _cobertura(processed, auditoria, config),
        "volumen_noticias": config["volumen_noticias"],
        "nota_intervalo_seccion_7": nota_intervalo_pdf(config),
        "nota_cuadricula_banco_mundial": nota_cuadricula(config),
        "crudos": _crudos(raw),
        "crudos_consulta_historica": auditoria.get("crudos_consulta_historica", []),
        "registro_extraccion": _registro_extraccion(data, config),
        "historial": historial,
    }
    previo_completo = json.loads(ruta_previa.read_text("utf-8")) if ruta_previa.exists() else {}
    return conservar_reproducibilidad(manifest, previo_completo)


def escribir_changelog(ruta: Path, manifest: dict[str, Any]) -> None:
    """Resumen en texto del historial (D-63), de la versión más nueva a la más antigua."""
    lineas = [
        "# Historial del snapshot",
        "",
        "Generado por `python -m scripts.manifest` a partir del historial de `manifest.json`.",
        "No editar a mano.",
        "",
    ]
    for h in reversed(manifest["historial"]):
        lineas += [f"## v{h['version']} · {h['fecha']}", "", f"- Hash del snapshot: `{h['hash_snapshot']}`"]
        lineas += [f"- Cambio de fuente: {c}" for c in h["cambios_de_fuente"]]
        lineas += [f"- Revisión de datos: {r}" for r in h["revisiones_de_datos"]] or []
        lineas += [f"- Nota: {n}" for n in h.get("notas", [])]
        ex = h["registros_excluidos"]
        lineas.append(f"- Registros excluidos: {ex['total']} {ex['por_motivo'] or ''}".rstrip())
        lineas.append(
            "- Cantidad por archivo: "
            + ", ".join(f"{k} {v}" for k, v in h["cantidad_por_archivo"].items())
        )
        lineas.append("")
    ruta.write_text("\n".join(lineas), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de ``python -m scripts.manifest``."""
    p = argparse.ArgumentParser(description="Escribe data/manifest.json y data/CHANGELOG.md.")
    p.add_argument("--data", type=Path, default=RAIZ / "data")
    p.add_argument("--motivo", help="Descripción del cambio con palabras del equipo (D-63).")
    args = p.parse_args(argv)
    configurar_logging()
    config = conversion.cargar_config()
    manifest = construir_manifest(args.data, config, args.motivo)
    conversion.escribir_json(args.data / "manifest.json", manifest)
    escribir_changelog(args.data / "CHANGELOG.md", manifest)
    logger.info("Manifest v%s escrito (corte %s)", manifest["version"], manifest["fecha_corte_UTC"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
