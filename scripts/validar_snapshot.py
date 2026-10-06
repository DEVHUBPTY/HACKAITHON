"""Valida un snapshot (propio o de la organización) contra la receta de la sección 6 (E0-04).

Uso::

    poetry run python -m scripts.validar_snapshot [--ruta data] [--salida outputs/validacion_snapshot.json]

``--ruta`` es la carpeta que contiene ``processed/`` y ``manifest.json``. Sale con código distinto de
cero si falla alguna comprobación dura (error). Los faltantes frente a la meta son advertencias; los
mínimos operativos (100 noticias, 20 de TVN) son errores.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import conversion
from scripts.conversion import (
    CAMPOS_EVENTO,
    CAMPOS_FUENTES,
    COLUMNAS_NOTICIAS,
    RAIZ,
    desde_iso,
    dominio_de,
    id_noticia,
    sha256_archivo,
)
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

COLUMNAS_INDICADORES_CONTRATO = [
    "pais_iso3", "indicador_id", "anio", "valor", "unidad", "fuente_url", "fecha_extraccion", "licencia",
]
CAMPOS_MANIFEST = [
    "version", "fecha_corte_UTC", "consultas", "cantidad_por_archivo", "licencias", "sha256",
    "transformaciones", "historial",
]
CAMPOS_HISTORIAL = [
    "version", "fecha", "cambios_de_fuente", "revisiones_de_datos", "registros_excluidos",
]
COLUMNAS_PROHIBIDAS = {"descripcion", "description", "socialimage", "summary"}


class Informe:
    """Acumula comprobaciones con su estado (ok · advertencia · error)."""

    def __init__(self) -> None:
        self.comprobaciones: list[dict[str, str]] = []

    def agregar(self, nombre: str, estado: str, detalle: str) -> None:
        self.comprobaciones.append({"comprobacion": nombre, "estado": estado, "detalle": detalle})

    def ok(self, nombre: str, detalle: str) -> None:
        self.agregar(nombre, "ok", detalle)

    def error(self, nombre: str, detalle: str) -> None:
        self.agregar(nombre, "error", detalle)

    def advertencia(self, nombre: str, detalle: str) -> None:
        self.agregar(nombre, "advertencia", detalle)

    def como_dict(self, resumen: dict[str, Any]) -> dict[str, Any]:
        errores = [c for c in self.comprobaciones if c["estado"] == "error"]
        avisos = [c for c in self.comprobaciones if c["estado"] == "advertencia"]
        return {
            "aprobado": not errores,
            "errores": len(errores),
            "advertencias": len(avisos),
            "resumen": resumen,
            "comprobaciones": self.comprobaciones,
        }


def _leer_csv(ruta: Path) -> tuple[list[str], list[dict[str, str]]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        return list(lector.fieldnames or []), list(lector)


def _revisar_campos(inf: Informe, nombre: str, presentes: list[str], requeridos: list[str]) -> bool:
    faltan = [c for c in requeridos if c not in presentes]
    if faltan:
        inf.error(f"contrato:{nombre}", f"faltan campos del contrato: {faltan}")
        return False
    inf.ok(f"contrato:{nombre}", "todos los campos del contrato presentes")
    return True


def _validar_noticias(inf: Informe, processed: Path, config: dict[str, Any], resumen: dict) -> None:
    ruta = processed / "noticias.csv"
    if not ruta.exists():
        inf.error("archivo:noticias.csv", "no existe")
        return
    columnas, filas = _leer_csv(ruta)
    resumen["noticias"] = len(filas)
    if not _revisar_campos(inf, "noticias.csv", columnas, COLUMNAS_NOTICIAS):
        return
    prohibidas = COLUMNAS_PROHIBIDAS & {c.lower() for c in columnas}
    if prohibidas:
        inf.error("d72:noticias.csv", f"columnas con redistribución restringida: {sorted(prohibidas)}")
    else:
        inf.ok("d72:noticias.csv", "sin descripción del RSS ni socialimage")

    vol = config["volumen_noticias"]
    total = len({f["url"] for f in filas})
    ids = [f["id_noticia"] for f in filas]
    if len(set(ids)) != len(ids):
        inf.error("noticias:ids_unicos", "hay id_noticia repetidos")
    malos = [f["url"] for f in filas if f["id_noticia"] != id_noticia(f["url"], config)]
    if malos:
        inf.error("noticias:id_estable", f"{len(malos)} id_noticia no son SHA-1 de la URL canónica (D-63)")
    else:
        inf.ok("noticias:id_estable", "todos los NOT- coinciden con el SHA-1 de la URL canónica")

    if total < vol["minimo"]:
        inf.error("volumen:total", f"{total} noticias únicas < mínimo operativo {vol['minimo']}")
    elif total < vol["meta"]:
        inf.advertencia("volumen:total", f"{total} noticias únicas: sobre el mínimo {vol['minimo']}, bajo la meta {vol['meta']}")
    else:
        inf.ok("volumen:total", f"{total} noticias únicas (meta {vol['meta']})")

    tvn = sum(1 for f in filas if dominio_de(f["url"]) == config["medio_tvn_dominio"])
    resumen["noticias_tvn"] = tvn
    resumen["noticias_gdelt"] = sum(1 for f in filas if "GDELT" in f["origen"])
    if tvn < vol["minimo_tvn"]:
        inf.error("volumen:tvn", f"{tvn} noticias de TVN < mínimo {vol['minimo_tvn']} (acumular el RSS a diario)")
    else:
        inf.ok("volumen:tvn", f"{tvn} noticias de TVN (mínimo {vol['minimo_tvn']})")

    fechas_malas = [
        f["id_noticia"]
        for f in filas
        for c in ("fecha_publicacion", "fecha_deteccion", "fecha_extraccion")
        if f[c] and desde_iso(f[c]) is None
    ]
    if fechas_malas:
        inf.error("noticias:fechas_iso_utc", f"{len(fechas_malas)} fechas no son ISO 8601 UTC con Z")
    else:
        inf.ok("noticias:fechas_iso_utc", "fechas ISO 8601 UTC")
    gdelt_con_pub = [f["id_noticia"] for f in filas if f["origen"] == "GDELT" and f["fecha_publicacion"]]
    if gdelt_con_pub:
        inf.error("noticias:publicacion_no_es_deteccion", f"{len(gdelt_con_pub)} registros solo-GDELT con fecha_publicacion")
    else:
        inf.ok("noticias:publicacion_no_es_deteccion", "los registros solo-GDELT no tienen fecha_publicacion")

    referencia = [f["fecha_deteccion"] or f["fecha_publicacion"] for f in filas]
    referencia = sorted(x for x in referencia if x)
    if referencia:
        inicial, final = desde_iso(referencia[0]), desde_iso(referencia[-1])
        if inicial and final:
            dias = (final - inicial).total_seconds() / 86400
            resumen["cobertura_efectiva"] = {"fecha_inicial": referencia[0], "fecha_final": referencia[-1], "dias": round(dias, 2)}
            maximo = config["ventana_noticias"]["dias_maximo"]
            if dias > maximo:
                inf.error("cobertura:efectiva", f"cobertura de {dias:.1f} días excede la ventana máxima de {maximo}")
            else:
                inf.ok("cobertura:efectiva", f"{referencia[0]} a {referencia[-1]} ({dias:.1f} días, máximo {maximo})")
    else:
        inf.error("cobertura:efectiva", "no hay fechas para calcular la cobertura")

    ruta_fuentes = processed / "fuentes.json"
    if not ruta_fuentes.exists():
        inf.error("archivo:fuentes.json", "no existe")
        return
    fuentes = json.loads(ruta_fuentes.read_text("utf-8"))
    resumen["fuentes"] = len(fuentes)
    incompletas = [f for f in fuentes if any(c not in f for c in CAMPOS_FUENTES)]
    if incompletas:
        inf.error("contrato:fuentes.json", f"{len(incompletas)} registros sin los campos {CAMPOS_FUENTES}")
    else:
        inf.ok("contrato:fuentes.json", "un registro por medio con todos los campos")
    nombres = {f.get("nombre_legible") for f in fuentes}
    sin_ficha = sorted({f["medio"] for f in filas} - nombres)
    if sin_ficha:
        inf.error("fuentes:cobertura_de_medios", f"medios sin registro en fuentes.json: {sin_ficha[:5]}")
    else:
        inf.ok("fuentes:cobertura_de_medios", "todos los medios de noticias.csv están en fuentes.json")


def _validar_indicadores(inf: Informe, processed: Path, config: dict[str, Any], resumen: dict) -> None:
    ruta = processed / "indicadores.csv"
    if not ruta.exists():
        inf.error("archivo:indicadores.csv", "no existe")
        return
    columnas, filas = _leer_csv(ruta)
    resumen["indicadores"] = len(filas)
    if not _revisar_campos(inf, "indicadores.csv", columnas, COLUMNAS_INDICADORES_CONTRATO):
        return
    bm = config["banco_mundial"]
    esperado = len(bm["paises"]) * len(bm["indicadores"]) * (bm["anio_fin"] - bm["anio_inicio"] + 1)
    claves = {(f["pais_iso3"], f["indicador_id"], f["anio"]) for f in filas}
    completa = {
        (p, i, str(a))
        for p in bm["paises"]
        for i in bm["indicadores"]
        for a in range(bm["anio_inicio"], bm["anio_fin"] + 1)
    }
    if len(filas) != esperado or claves != completa:
        inf.error("cuadricula:banco_mundial", f"{len(filas)} filas; se esperaban {esperado} combinaciones país × indicador × año")
    else:
        nulos = sum(1 for f in filas if f["valor"] == "")
        resumen["indicadores_nulos"] = nulos
        inf.ok("cuadricula:banco_mundial", f"{esperado} filas completas ({nulos} valores nulos explícitos)")
    ceros_sospechosos = [f for f in filas if f["valor"] in ("0", "0.0") and f["indicador_id"] == "SP.POP.TOTL"]
    if ceros_sospechosos:
        inf.error("nulos:no_rellenar_con_cero", "población con valor 0: parece relleno de nulos")


def _validar_eventos(inf: Informe, processed: Path, config: dict[str, Any], resumen: dict) -> None:
    ruta = processed / "eventos.geojson"
    if not ruta.exists():
        inf.error("archivo:eventos.geojson", "no existe")
        return
    features = json.loads(ruta.read_text("utf-8")).get("features", [])
    resumen["eventos"] = len(features)
    u = config["usgs"]
    inicio, fin = datetime.fromisoformat(u["starttime"]), datetime.fromisoformat(u["endtime"])
    faltan: list[str] = []
    fuera_caja: list[str] = []
    fuera_fecha: list[str] = []
    for f in features:
        p = f.get("properties", {})
        faltan += [f"{p.get('id')}:{c}" for c in CAMPOS_EVENTO if c not in p]
        lat, lon = p.get("latitude"), p.get("longitude")
        if lat is None or lon is None or not (
            u["minlatitude"] <= lat <= u["maxlatitude"] and u["minlongitude"] <= lon <= u["maxlongitude"]
        ):
            fuera_caja.append(str(p.get("id")))
        t = desde_iso(p.get("time", ""))
        if t is None or not (inicio <= t.replace(tzinfo=None) <= fin):
            fuera_fecha.append(str(p.get("id")))
        if (p.get("magnitude") is None) or p["magnitude"] < u["minmagnitude"]:
            fuera_caja.append(f"{p.get('id')}:magnitud")
    if faltan:
        inf.error("contrato:eventos.geojson", f"faltan campos en {len(faltan)} casos, ej. {faltan[:3]}")
    else:
        inf.ok("contrato:eventos.geojson", f"{len(features)} eventos con todos los campos")
    if fuera_caja:
        inf.error("usgs:caja_y_magnitud", f"{len(fuera_caja)} eventos fuera de la caja o bajo la magnitud mínima")
    else:
        inf.ok("usgs:caja_y_magnitud", "todos dentro de la caja regional y con magnitud >= mínima")
    if fuera_fecha:
        inf.error("usgs:fechas", f"{len(fuera_fecha)} eventos fuera de {u['starttime']}..{u['endtime']}")
    else:
        inf.ok("usgs:fechas", f"todos entre {u['starttime']} y {u['endtime']}")
    if not features:
        inf.error("usgs:volumen", "sin eventos")


def _validar_manifest(inf: Informe, data: Path, resumen: dict) -> None:
    ruta = data / "manifest.json"
    if not ruta.exists():
        inf.error("archivo:manifest.json", "no existe")
        return
    m = json.loads(ruta.read_text("utf-8"))
    faltan = [c for c in CAMPOS_MANIFEST if c not in m]
    if faltan:
        inf.error("manifest:campos_minimos", f"faltan campos: {faltan}")
    else:
        inf.ok("manifest:campos_minimos", "version, fecha_corte_UTC, consultas, cantidad, licencias, sha256, transformaciones")
    historial = m.get("historial")
    if not isinstance(historial, list) or not historial:
        inf.error("manifest:historial", "el manifest no tiene historial de versiones (D-63)")
    else:
        incompletos = [h for h in historial if any(c not in h for c in CAMPOS_HISTORIAL)]
        if incompletos:
            inf.error("manifest:historial", f"entradas sin los campos {CAMPOS_HISTORIAL}")
        else:
            inf.ok("manifest:historial", f"{len(historial)} versión(es) con cambios, revisiones y excluidos")
    if m.get("fecha_corte_UTC") and desde_iso(m["fecha_corte_UTC"]) is None:
        inf.error("manifest:fecha_corte", "fecha_corte_UTC no es ISO 8601 UTC")
    diferentes = [
        nombre
        for nombre, huella in (m.get("sha256") or {}).items()
        if not (data / nombre).exists() or sha256_archivo(data / nombre) != huella
    ]
    if diferentes:
        inf.error("manifest:sha256", f"huellas que no coinciden con los archivos: {diferentes}")
    elif m.get("sha256"):
        inf.ok("manifest:sha256", f"{len(m['sha256'])} huellas verificadas")
    if "cobertura_efectiva" not in m:
        inf.advertencia("manifest:cobertura_efectiva", "el manifest no registra la cobertura efectiva")
    resumen["manifest_version"] = m.get("version")


def validar(data: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Valida el snapshot de ``data`` (``processed/`` + ``manifest.json``) y devuelve el informe."""
    inf = Informe()
    resumen: dict[str, Any] = {}
    processed = data / "processed"
    _validar_noticias(inf, processed, config, resumen)
    _validar_indicadores(inf, processed, config, resumen)
    _validar_eventos(inf, processed, config, resumen)
    _validar_manifest(inf, data, resumen)
    return inf.como_dict(resumen)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de ``python -m scripts.validar_snapshot``."""
    p = argparse.ArgumentParser(description="Valida un snapshot contra la receta de la sección 6.")
    p.add_argument("--ruta", type=Path, default=RAIZ / "data")
    p.add_argument("--salida", type=Path, default=RAIZ / "outputs" / "validacion_snapshot.json")
    args = p.parse_args(argv)
    configurar_logging()
    informe = validar(args.ruta, conversion.cargar_config())
    conversion.escribir_json(args.salida, informe)
    for c in informe["comprobaciones"]:
        if c["estado"] != "ok":
            print(f"[{c['estado'].upper()}] {c['comprobacion']}: {c['detalle']}")
    print(
        f"Snapshot {'APROBADO' if informe['aprobado'] else 'RECHAZADO'}: "
        f"{informe['errores']} error(es), {informe['advertencias']} advertencia(s). "
        f"Informe en {args.salida}"
    )
    return 0 if informe["aprobado"] else 1


if __name__ == "__main__":
    sys.exit(main())
