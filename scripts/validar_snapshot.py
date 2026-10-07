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

from scripts import conversion, sbp
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
from src.configuracion import cargar_contrato
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

COLUMNAS_INDICADORES_CONTRATO = cargar_contrato().indicadores  # config/contrato.yaml
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

    _validar_temas(inf, filas, config, resumen)
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


def _validar_temas(inf: Informe, filas: list[dict[str, str]], config: dict[str, Any], resumen: dict) -> None:
    """Cada tema de consulta de GDELT debería tener registros; un tema con cero es una advertencia."""
    por_tema = {t: 0 for t in config["gdelt"]["consultas"]}
    for f in filas:
        for t in f["tema"].split("|"):
            if t in por_tema:
                por_tema[t] += 1
    resumen["noticias_por_tema_de_consulta"] = por_tema
    vacios = sorted(t for t, n in por_tema.items() if n == 0)
    if vacios:
        inf.advertencia("temas:sin_registros", f"temas de consulta sin ningún registro en noticias.csv: {vacios}")
    else:
        inf.ok("temas:sin_registros", f"todos los temas de consulta tienen registros: {por_tema}")


def _validar_cobertura_contra_extraccion(inf: Informe, data: Path, config: dict[str, Any], resumen: dict) -> None:
    """Compara las fechas de noticias.csv con la fecha de extracción (``fecha_corte_UTC``) del manifest."""
    ruta_m, ruta_n = data / "manifest.json", data / "processed" / "noticias.csv"
    if not ruta_m.exists() or not ruta_n.exists():
        return
    corte = desde_iso(json.loads(ruta_m.read_text("utf-8")).get("fecha_corte_UTC", ""))
    if corte is None:
        return
    columnas, filas = _leer_csv(ruta_n)
    if not set(COLUMNAS_NOTICIAS) <= set(columnas):
        return  # el error de contrato ya se reportó
    maximo = config["ventana_noticias"]["dias_maximo"]
    fechas = [d for f in filas if (d := desde_iso(f["fecha_deteccion"] or f["fecha_publicacion"]))]
    futuras = [d for d in fechas if d > corte]
    viejas = [d for d in fechas if (corte - d).days > maximo]
    if futuras:
        inf.error("cobertura:posterior_a_la_extraccion", f"{len(futuras)} noticias con fecha posterior a la extracción ({corte:%Y-%m-%dT%H:%M:%SZ})")
    if viejas:
        inf.error("cobertura:anterior_a_la_ventana", f"{len(viejas)} noticias más de {maximo} días antes de la extracción")
    if not futuras and not viejas:
        inf.ok("cobertura:contra_extraccion", f"todas las fechas están entre {maximo} días antes y la extracción")
    por_tema: dict[str, list[Any]] = {}
    for f in filas:
        d = desde_iso(f["fecha_deteccion"] or f["fecha_publicacion"])
        for t in f["tema"].split("|"):
            if d and t in config["gdelt"]["consultas"]:
                por_tema.setdefault(t, []).append(d)
    resumen["cobertura_por_tema"] = {
        t: {"desde": f"{min(v):%Y-%m-%dT%H:%M:%SZ}", "hasta": f"{max(v):%Y-%m-%dT%H:%M:%SZ}", "dias": round((max(v) - min(v)).total_seconds() / 86400, 1)}
        for t, v in sorted(por_tema.items())
    }


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
    declarada = bm.get("cuadricula_declarada_en_pdf")
    if declarada and declarada != esperado:
        inf.advertencia(
            "cuadricula:pdf_inconsistente",
            f"el PDF declara {declarada} filas, pero {len(bm['paises'])} países × "
            f"{len(bm['indicadores'])} indicadores × {bm['anio_fin'] - bm['anio_inicio'] + 1} años = {esperado}",
        )
    _validar_valores_contra_crudos(inf, processed.parent / "raw", config, filas)


def _validar_valores_contra_crudos(
    inf: Informe, raw: Path, config: dict[str, Any], filas: list[dict[str, str]]
) -> None:
    """Cada ``valor`` debe coincidir con el crudo: un 0 solo vale si el crudo traía 0; un nulo no se rellena."""
    crudos = conversion.valores_banco_mundial(raw, config)
    if not any(ts for ts, _ in crudos.values()):
        inf.advertencia(
            "nulos:no_rellenar_con_cero",
            "no hay crudos del Banco Mundial para comparar: no se pudo comprobar que los 0 y nulos sean del origen",
        )
        return
    ceros, relleno, perdidos, distintos = [], [], [], []
    for f in filas:
        if f["indicador_id"] not in crudos:
            continue
        _, valores = crudos[f["indicador_id"]]
        crudo = valores.get((f["pais_iso3"], int(f["anio"])))
        clave = f"{f['pais_iso3']}/{f['indicador_id']}/{f['anio']}"
        if f["valor"] == "":
            if crudo is not None:
                perdidos.append(clave)
            continue
        valor = float(f["valor"])
        if crudo is None:
            relleno.append(clave)  # el crudo era nulo o no existía y el procesado trae un número
        elif valor != float(crudo):
            distintos.append(clave)
        if valor == 0 and (crudo is None or float(crudo) != 0):
            ceros.append(clave)
    problemas = {"cero que el crudo no trae": ceros, "número donde el crudo es nulo": relleno,
                 "nulo donde el crudo trae valor": perdidos, "valor distinto del crudo": distintos}
    malos = {k: v for k, v in problemas.items() if v}
    if malos:
        detalle = "; ".join(f"{k}: {len(v)} (ej. {v[:2]})" for k, v in malos.items())
        inf.error("nulos:no_rellenar_con_cero", f"los valores no coinciden con raw/: {detalle}")
    else:
        inf.ok("nulos:no_rellenar_con_cero", f"{len(filas)} valores coinciden con los crudos (ningún 0 ni nulo inventado)")


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


def _validar_sbp(inf: Informe, processed: Path, config: dict[str, Any], resumen: dict) -> None:
    """Fuente D (E3-02, opcional): las columnas de la spec, 12 períodos por serie y unidad, página y condiciones en cada fila."""
    ruta = processed / sbp.NOMBRE_CSV
    if not ruta.exists():
        inf.advertencia("archivo:sbp_series.csv", "no existe: la fuente D (SBP) es opcional y solo la usa la modalidad banca")
        return
    columnas, filas = _leer_csv(ruta)
    resumen["sbp_series"] = len(filas)
    if columnas != sbp.COLUMNAS_SBP:
        inf.error("contrato:sbp_series.csv", f"columnas {columnas}; se esperaban {sbp.COLUMNAS_SBP}")
        return
    cfg = config["sbp"]
    esperadas = {f"{sbp.PREFIJO_ID}{k}" for k in cfg["series"]}
    periodos: dict[str, set[str]] = {}
    for f in filas:
        periodos.setdefault(f["id_serie"], set()).add(f["periodo"])
    incompletas = {k: len(v) for k, v in periodos.items() if len(v) != cfg["periodos_por_serie"]}
    sin_dato = [f"{f['id_serie']}:{f['periodo']}" for f in filas if not (f["unidad"] and f["pagina"] and f["informe"] and f["condiciones"])]
    if set(periodos) != esperadas or incompletas or len(filas) != len(esperadas) * cfg["periodos_por_serie"]:
        inf.error("sbp:series_y_periodos", f"series {sorted(periodos)}; incompletas {incompletas}; se esperaban {sorted(esperadas)} con {cfg['periodos_por_serie']} períodos")
    else:
        inf.ok("sbp:series_y_periodos", f"{len(esperadas)} series con {cfg['periodos_por_serie']} períodos cada una")
    if sin_dato:
        inf.error("sbp:unidad_pagina_condiciones", f"{len(sin_dato)} filas sin unidad, página, informe o condiciones, ej. {sin_dato[:2]}")
    else:
        inf.ok("sbp:unidad_pagina_condiciones", "todas las filas llevan unidad, página, informe y condiciones")


def _validar_manifest(inf: Informe, data: Path, resumen: dict, config: dict[str, Any] | None = None) -> None:
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
    # D-72 / X84: lo que no se versiona (redistribución restringida) puede faltar en esta máquina: se avisa, no es un error.
    restringidas = {r for rutas in ((config or {}).get("redistribucion_restringida") or {}).values() for r in rutas}
    locales_ausentes = [n for n in (m.get("sha256") or {}) if f"data/{n}" in restringidas and not (data / n).exists()]
    for nombre in locales_ausentes:
        inf.advertencia(f"manifest:sha256:{nombre}", "no está en esta máquina (no se versiona, D-72): su huella no se verificó; se regenera con scripts.extraer")
    diferentes = [
        nombre
        for nombre, huella in (m.get("sha256") or {}).items()
        if nombre not in locales_ausentes and (not (data / nombre).exists() or sha256_archivo(data / nombre) != huella)
    ]
    if diferentes:
        inf.error("manifest:sha256", f"huellas que no coinciden con los archivos: {diferentes}")
    elif m.get("sha256"):
        inf.ok("manifest:sha256", f"{len(m['sha256'])} huellas verificadas")
    cob = m.get("cobertura_efectiva") or {}
    sin_resolver = cob.get("gdelt_rangos_sin_resolver") or []
    if sin_resolver:
        por_tema: dict[str, int] = {}
        for r in sin_resolver:
            por_tema[r.get("tema", "?")] = por_tema.get(r.get("tema", "?"), 0) + 1
        dias = {t: f"{d.get('dias_cubiertos')}/{d.get('dias_esperados')}" for t, d in (cob.get("gdelt_dias_por_tema") or {}).items()}
        historica = {
            t: f"{d.get('dias_cubiertos')}/{d.get('dias_esperados')}"
            for t, d in (cob.get("gdelt_dias_por_tema_consulta_historica") or {}).items()
        }
        aparte = f" Consultas históricas (D-89, aparte): {historica}." if historica else ""
        inf.advertencia(
            "gdelt:rangos_sin_resolver",
            f"{len(sin_resolver)} rango(s) de GDELT sin resolver, por tema: {por_tema}; "
            f"días cubiertos/esperados (consultas vigentes): {dias}. La cobertura de GDELT es incompleta.{aparte}",
        )
    else:
        inf.ok("gdelt:rangos_sin_resolver", "todos los días de la ventana tienen un crudo de GDELT por tema")
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
    _validar_sbp(inf, processed, config, resumen)
    _validar_manifest(inf, data, resumen, config)
    _validar_cobertura_contra_extraccion(inf, data, config, resumen)
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
