"""Conversión de las respuestas crudas (``data/raw/``) al contrato de datos (``data/processed/``).

Todo aquí es determinista y no usa red: el mismo ``raw/`` produce siempre los mismos archivos.
La descripción del RSS y ``socialimage`` de GDELT nunca se copian a ``processed/`` (D-31, D-72).
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from src import configuracion

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent

FORMATO_TS_ARCHIVO = "%Y%m%dT%H%M%SZ"
FORMATO_ISO = "%Y-%m-%dT%H:%M:%SZ"
PATRON_TS_ARCHIVO = re.compile(r"_(\d{8}T\d{6}Z)\.[a-z]+$")
PATRON_ARCHIVO_GDELT = re.compile(
    r"^gdelt_(?P<tema>[a-z_]+)_(?P<ini>\d{14})_(?P<fin>\d{14})_(?P<ts>\d{8}T\d{6}Z)\.json$"
)
PATRON_ARCHIVO_WB = re.compile(r"^wb_(?P<ind>[A-Za-z0-9.]+)_(?P<ts>\d{8}T\d{6}Z)\.json$")

COLUMNAS_NOTICIAS = [
    "id_noticia",
    "titulo",
    "url",
    "medio",
    "idioma",
    "fecha_publicacion",
    "fecha_deteccion",
    "fecha_extraccion",
    "tema",
    "origen",
    "alcance_texto",
]
COLUMNAS_INDICADORES = [
    "id_indicador",
    "pais_iso3",
    "indicador_id",
    "anio",
    "valor",
    "unidad",
    "fuente_url",
    "fecha_extraccion",
    "licencia",
]
CAMPOS_FUENTES = ["dominio", "nombre_legible", "pais", "origen", "condiciones"]
CAMPOS_EVENTO = [
    "id",
    "magnitude",
    "time",
    "updated",
    "longitude",
    "latitude",
    "depth",
    "place",
    "status",
    "url",
]
ORIGEN_RSS = "TVN RSS"
ORIGEN_GDELT = "GDELT"
CONDICIONES_PENDIENTES = "Pendiente de verificar"


# ---------------------------------------------------------------- utilidades


def cargar_config(carpeta: Path | None = None) -> dict[str, Any]:
    """Carga ``config/fuentes.yaml`` validado con ``ConfigFuentes`` (D-79) y lo devuelve como dict."""
    return configuracion.cargar_fuentes(carpeta).model_dump()


def sha256_archivo(ruta: Path) -> str:
    """SHA-256 hexadecimal del contenido de un archivo."""
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


def a_iso(momento: datetime | None) -> str:
    """Formatea un datetime como ISO 8601 UTC con ``Z``; ``None`` queda vacío."""
    if momento is None:
        return ""
    return momento.astimezone(UTC).strftime(FORMATO_ISO)


def desde_iso(texto: str) -> datetime | None:
    """Parsea un ISO 8601 UTC (``...Z``); devuelve ``None`` si es vacío o inválido."""
    if not texto:
        return None
    try:
        return datetime.strptime(texto, FORMATO_ISO).replace(tzinfo=UTC)
    except ValueError:
        return None


def ts_de_archivo(ruta: Path) -> datetime:
    """Marca de tiempo UTC embebida en el nombre de un archivo crudo."""
    m = PATRON_TS_ARCHIVO.search(ruta.name)
    if not m:
        raise ValueError(f"El archivo crudo no lleva marca de tiempo UTC: {ruta.name}")
    return datetime.strptime(m.group(1), FORMATO_TS_ARCHIVO).replace(tzinfo=UTC)


def nombre_con_ts(prefijo: str, momento: datetime, extension: str) -> str:
    """Construye ``<prefijo>_<ts UTC>.<extension>``."""
    return f"{prefijo}_{momento.astimezone(UTC).strftime(FORMATO_TS_ARCHIVO)}.{extension}"


def archivos_crudos(carpeta: Path, patron: str) -> list[Path]:
    """Archivos de ``carpeta`` que cumplen ``patron``, ordenados por nombre (estable)."""
    if not carpeta.is_dir():
        return []
    return sorted(carpeta.glob(patron), key=lambda p: p.name)


def escribir_json(ruta: Path, objeto: Any) -> None:
    """JSON determinista: UTF-8, claves ordenadas, sangría 2 y salto final."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def escribir_csv(ruta: Path, columnas: list[str], filas: list[dict[str, Any]]) -> None:
    """CSV UTF-8 con saltos ``\\n``; los nulos se escriben como celda vacía (nunca como 0)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas, lineterminator="\n")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({c: ("" if fila.get(c) is None else fila[c]) for c in columnas})


# ------------------------------------------------------------- URL e IDs (D-63)


def url_canonica(url: str, config: dict[str, Any]) -> str:
    """URL canónica: esquema fijo, host en minúsculas sin ``www.``, sin fragmento ni rastreo."""
    reglas = config["url_canonica"]
    partes = urlsplit(url.strip())
    host = (partes.hostname or "").lower()
    if reglas.get("quitar_prefijo_www") and host.startswith("www."):
        host = host[4:]
    if partes.port and partes.port not in (80, 443):
        host = f"{host}:{partes.port}"
    quitar = reglas.get("parametros_a_quitar", [])

    def es_rastreo(nombre: str) -> bool:
        n = nombre.lower()
        return any(n == q or (q.endswith("*") and n.startswith(q[:-1])) for q in quitar)

    consulta = sorted(
        (k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True) if not es_rastreo(k)
    )
    ruta = partes.path.rstrip("/") or "/"
    return urlunsplit((reglas["esquema"], host, ruta, urlencode(consulta), ""))


def id_noticia(url: str, config: dict[str, Any]) -> str:
    """``NOT-`` + primeros 10 caracteres del SHA-1 de la URL canónica (D-63)."""
    digest = hashlib.sha1(url_canonica(url, config).encode("utf-8")).hexdigest()
    return f"NOT-{digest[:10]}"


def id_indicador(pais: str, indicador: str, anio: int | str) -> str:
    """``IND-<país>-<indicador>-<año>`` (D-63)."""
    return f"IND-{pais}-{indicador}-{anio}"


def id_sismo(id_usgs: str) -> str:
    """``SIS-<id USGS>`` (D-63)."""
    return f"SIS-{id_usgs}"


def dominio_de(url: str) -> str:
    """Host en minúsculas sin ``www.``."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _nombre_medio(dominio: str, config: dict[str, Any]) -> str:
    conocido = config.get("medios_conocidos", {}).get(dominio)
    return conocido["nombre"] if conocido else dominio


# ------------------------------------------------------------------- noticias


def _seccion_url(url: str) -> str:
    segmentos = [s for s in urlsplit(url).path.split("/") if s]
    return segmentos[0] if len(segmentos) > 1 else "sin_seccion"


def _leer_rss(ruta: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Entradas de un RSS crudo. La descripción se ignora a propósito (D-31, D-72)."""
    feed = feedparser.parse(ruta.read_bytes())
    ts = ts_de_archivo(ruta)
    idioma = (feed.feed.get("language") or config["general"]["idioma_por_defecto"]).lower()[:2]
    entradas = []
    for e in feed.entries:
        publicada = None
        if e.get("published_parsed"):
            publicada = datetime(*e.published_parsed[:6], tzinfo=UTC)
        url = (e.get("link") or "").strip()
        entradas.append(
            {
                "url": url,
                "titulo": (e.get("title") or "").strip(),
                "idioma": idioma,
                "publicacion": publicada,
                "deteccion": None,
                "extraccion": ts,
                "tema": _seccion_url(url) if url else "",
                "origen": ORIGEN_RSS,
                "dominio": dominio_de(url),
                "pais": "",
            }
        )
    return entradas


def _leer_gdelt(ruta: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Artículos de un archivo crudo de GDELT. ``socialimage`` se ignora (D-72)."""
    m = PATRON_ARCHIVO_GDELT.match(ruta.name)
    if not m:
        raise ValueError(f"Nombre de archivo GDELT inesperado: {ruta.name}")
    ts = ts_de_archivo(ruta)
    texto = ruta.read_text(encoding="utf-8")
    datos = json.loads(texto, strict=False) if texto.strip() else {}
    idiomas = config["gdelt"]["idiomas"]
    entradas = []
    for a in datos.get("articles", []):
        url = (a.get("url") or "").strip()
        try:
            deteccion = datetime.strptime(a.get("seendate", ""), FORMATO_TS_ARCHIVO).replace(
                tzinfo=UTC
            )
        except ValueError:
            deteccion = None
        lengua = a.get("language") or ""
        entradas.append(
            {
                "url": url,
                "titulo": (a.get("title") or "").strip(),
                "idioma": idiomas.get(lengua, lengua.lower()),
                "publicacion": None,  # GDELT no trae fecha de publicación
                "deteccion": deteccion,  # seendate → fecha_deteccion, nunca publicación
                "extraccion": ts,
                "tema": m.group("tema"),
                "origen": ORIGEN_GDELT,
                "dominio": (a.get("domain") or dominio_de(url)).lower().removeprefix("www."),
                "pais": a.get("sourcecountry") or "",
            }
        )
    return entradas


def _fusionar(
    entradas: list[dict[str, Any]], config: dict[str, Any], excluidos: list[dict[str, str]]
) -> dict[str, dict[str, Any]]:
    """Deduplica por URL canónica. RSS aporta publicación; GDELT, detección (la más temprana)."""
    unicos: dict[str, dict[str, Any]] = {}
    for e in entradas:
        if not e["url"]:
            excluidos.append({"id_noticia": "", "url": "", "motivo": "sin_url"})
            continue
        canon = url_canonica(e["url"], config)
        nid = id_noticia(e["url"], config)
        if not e["titulo"]:
            excluidos.append({"id_noticia": nid, "url": e["url"], "motivo": "sin_titulo"})
            continue
        r = unicos.get(canon)
        if r is None:
            unicos[canon] = {
                "id_noticia": nid,
                "url": e["url"],
                "titulo": e["titulo"],
                "idioma": e["idioma"],
                "publicacion": e["publicacion"],
                "deteccion": e["deteccion"],
                "extraccion": e["extraccion"],
                "temas": {e["tema"]},
                "origenes": {e["origen"]},
                "dominio": e["dominio"],
                "paises": [e["pais"]] if e["pais"] else [],
                "veces_visto": 1,
            }
            continue
        r["veces_visto"] += 1
        r["temas"].add(e["tema"])
        r["origenes"].add(e["origen"])
        r["extraccion"] = min(r["extraccion"], e["extraccion"])
        if e["pais"]:
            r["paises"].append(e["pais"])
        if e["publicacion"] and not r["publicacion"]:
            r["publicacion"] = e["publicacion"]
        if e["deteccion"] and (not r["deteccion"] or e["deteccion"] < r["deteccion"]):
            r["deteccion"] = e["deteccion"]
        if e["origen"] == ORIGEN_RSS:  # el RSS del propio medio manda en título, URL e idioma
            r.update(titulo=e["titulo"], url=e["url"], idioma=e["idioma"])
    return unicos


def _fecha_referencia(r: dict[str, Any]) -> datetime | None:
    """Fecha para medir la ventana (D-74): detección; si no hay, publicación."""
    return r["deteccion"] or r["publicacion"]


def aplicar_ventana(
    registros: list[dict[str, Any]], fin: datetime, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]], int]:
    """Filtra por ventana de ``dias_base``; amplía a ``dias_maximo`` si no se llega al mínimo.

    Devuelve (incluidos, excluidos con motivo, días aplicados).
    """
    cfg = config["ventana_noticias"]
    minimo = config["volumen_noticias"]["minimo"]
    dias = cfg["dias_base"]

    def dentro(dias_: int) -> list[dict[str, Any]]:
        inicio = fin - timedelta(days=dias_)
        return [
            r for r in registros if (f := _fecha_referencia(r)) is not None and inicio <= f <= fin
        ]

    if len(dentro(dias)) < minimo:
        dias = cfg["dias_maximo"]
    incluidos = dentro(dias)
    ids = {r["id_noticia"] for r in incluidos}
    excluidos = []
    for r in registros:
        if r["id_noticia"] in ids:
            continue
        f = _fecha_referencia(r)
        if f is None:
            motivo = "sin_fecha_valida"
        elif f > fin:
            motivo = "fecha_posterior_a_la_extraccion"
        else:
            motivo = "fuera_de_ventana"
        excluidos.append({"id_noticia": r["id_noticia"], "url": r["url"], "motivo": motivo})
    return incluidos, excluidos, dias


def fallos_gdelt_sin_resolver(carpeta_raw: Path, config: dict[str, Any]) -> list[dict[str, str]]:
    """Rangos de GDELT que fallaron y todavía no tienen crudo (una corrida posterior pudo cubrirlos)."""
    carpeta = carpeta_raw / config["gdelt"]["carpeta_cruda"]
    existentes = {
        (m["tema"], m["ini"], m["fin"])
        for p in archivos_crudos(carpeta, "gdelt_*.json")
        if (m := PATRON_ARCHIVO_GDELT.match(p.name))
    }
    pendientes: dict[tuple[str, str, str], dict[str, str]] = {}
    for ruta in archivos_crudos(carpeta, "fallos_gdelt_*.json"):
        for f in json.loads(ruta.read_text(encoding="utf-8")):
            clave = (f["tema"], f["inicio"], f["fin"])
            if clave not in existentes:
                pendientes[clave] = {k: f[k] for k in ("tema", "inicio", "fin")}
    return [pendientes[k] for k in sorted(pendientes)]


def convertir_noticias(
    carpeta_raw: Path, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Convierte RSS y GDELT crudos a filas de ``noticias.csv`` y registros de ``fuentes.json``.

    Devuelve (filas, fuentes, auditoría). La auditoría documenta la ventana y las exclusiones.
    """
    archivos_rss = archivos_crudos(carpeta_raw / config["rss_tvn"]["carpeta_cruda"], "rss_tvn_*.xml")
    archivos_gdelt = archivos_crudos(carpeta_raw / config["gdelt"]["carpeta_cruda"], "gdelt_*.json")
    entradas: list[dict[str, Any]] = []
    for ruta in archivos_rss:
        entradas += _leer_rss(ruta, config)
    for ruta in archivos_gdelt:
        entradas += _leer_gdelt(ruta, config)

    excluidos: list[dict[str, str]] = []
    unicos = _fusionar(entradas, config, excluidos)
    tiempos = [ts_de_archivo(p) for p in archivos_rss + archivos_gdelt]
    fin = max(tiempos) if tiempos else datetime(1970, 1, 1, tzinfo=UTC)
    incluidos, fuera, dias = aplicar_ventana(list(unicos.values()), fin, config)
    excluidos += fuera

    medio_de: dict[str, str] = {}
    filas = []
    for r in sorted(incluidos, key=lambda x: x["id_noticia"]):
        medio = _nombre_medio(r["dominio"], config)
        medio_de[r["dominio"]] = medio
        orden = [o for o in (ORIGEN_RSS, ORIGEN_GDELT) if o in r["origenes"]]
        filas.append(
            {
                "id_noticia": r["id_noticia"],
                "titulo": r["titulo"],
                "url": r["url"],
                "medio": medio,
                "idioma": r["idioma"],
                "fecha_publicacion": a_iso(r["publicacion"]),
                "fecha_deteccion": a_iso(r["deteccion"]),
                "fecha_extraccion": a_iso(r["extraccion"]),
                "tema": "|".join(sorted(r["temas"])),
                "origen": " · ".join(orden),
                "alcance_texto": config["general"]["alcance_texto"],
            }
        )

    fuentes = _construir_fuentes(incluidos, config)
    auditoria = {
        "ventana": {
            "dias_base": config["ventana_noticias"]["dias_base"],
            "dias_maximo": config["ventana_noticias"]["dias_maximo"],
            "dias_aplicados": dias,
            "ampliada": dias > config["ventana_noticias"]["dias_base"],
            "inicio": a_iso(fin - timedelta(days=dias)),
            "fin": a_iso(fin),
        },
        "registros_crudos_leidos": len(entradas),
        "gdelt_rangos_sin_resolver": fallos_gdelt_sin_resolver(carpeta_raw, config),
        "duplicados_descartados": len(entradas) - len(unicos) - sum(
            1 for x in excluidos if x["motivo"] in ("sin_url", "sin_titulo")
        ),
        "excluidos": sorted(excluidos, key=lambda x: (x["motivo"], x["id_noticia"], x["url"])),
    }
    return filas, fuentes, auditoria


def _construir_fuentes(
    incluidos: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Un registro por medio: dominio, nombre legible, país, origen y condiciones."""
    por_dominio: dict[str, list[dict[str, Any]]] = {}
    for r in incluidos:
        por_dominio.setdefault(r["dominio"], []).append(r)
    fuentes = []
    for dominio in sorted(por_dominio):
        rs = por_dominio[dominio]
        conocido = config.get("medios_conocidos", {}).get(dominio, {})
        paises = Counter(p for r in rs for p in r["paises"])
        pais = conocido.get("pais") or (
            sorted(paises.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if paises else ""
        )
        origenes = sorted({o for r in rs for o in r["origenes"]}, key=[ORIGEN_RSS, ORIGEN_GDELT].index)
        fuentes.append(
            {
                "dominio": dominio,
                "nombre_legible": _nombre_medio(dominio, config),
                "pais": pais or CONDICIONES_PENDIENTES,
                "origen": " · ".join(origenes),
                "condiciones": conocido.get("condiciones", CONDICIONES_PENDIENTES).strip(),
            }
        )
    return fuentes


# ---------------------------------------------------------------- indicadores


def convertir_indicadores(carpeta_raw: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Completa la cuadrícula país × indicador × año; los faltantes quedan nulos, nunca 0."""
    cfg = config["banco_mundial"]
    anios = range(cfg["anio_inicio"], cfg["anio_fin"] + 1)
    carpeta = carpeta_raw / cfg["carpeta_cruda"]
    ultimo: dict[str, Path] = {}
    for ruta in archivos_crudos(carpeta, "wb_*.json"):
        m = PATRON_ARCHIVO_WB.match(ruta.name)
        if m:  # el orden por nombre deja al final la extracción más reciente
            ultimo[m.group("ind")] = ruta
    filas = []
    for ind, meta in cfg["indicadores"].items():
        valores: dict[tuple[str, int], Any] = {}
        ts = None
        if ind in ultimo:
            ts = ts_de_archivo(ultimo[ind])
            cuerpo = json.loads(ultimo[ind].read_text(encoding="utf-8"))
            for reg in cuerpo[1] if len(cuerpo) > 1 and cuerpo[1] else []:
                try:
                    valores[(reg["countryiso3code"], int(reg["date"]))] = reg.get("value")
                except (KeyError, ValueError, TypeError):
                    logger.warning("Registro de Banco Mundial con forma inesperada en %s", ind)
        for pais in cfg["paises"]:
            for anio in anios:
                filas.append(
                    {
                        "id_indicador": id_indicador(pais, ind, anio),
                        "pais_iso3": pais,
                        "indicador_id": ind,
                        "anio": anio,
                        "valor": valores.get((pais, anio)),
                        "unidad": meta["unidad"],
                        "fuente_url": (
                            f"{cfg['base_url']}/country/{pais}/indicator/{ind}"
                            f"?format=json&date={cfg['anio_inicio']}:{cfg['anio_fin']}"
                        ),
                        "fecha_extraccion": a_iso(ts),
                        "licencia": cfg["licencia"],
                    }
                )
    return sorted(filas, key=lambda f: (f["pais_iso3"], f["indicador_id"], f["anio"]))


# -------------------------------------------------------------------- sismos


def convertir_eventos(carpeta_raw: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Convierte el GeoJSON crudo de USGS (el más reciente) al contrato de ``eventos.geojson``."""
    carpeta = carpeta_raw / config["usgs"]["carpeta_cruda"]
    crudos = archivos_crudos(carpeta, "usgs_*.geojson")
    features: list[dict[str, Any]] = []
    extraccion = None
    if crudos:
        extraccion = ts_de_archivo(crudos[-1])
        cuerpo = json.loads(crudos[-1].read_text(encoding="utf-8"))
        for f in cuerpo.get("features", []):
            p = f.get("properties", {})
            lon, lat, prof = (f.get("geometry", {}).get("coordinates") or [None, None, None])[:3]

            def ms_a_iso(ms: int | None) -> str:
                if ms is None:
                    return ""
                return a_iso(datetime.fromtimestamp(ms / 1000, tz=UTC))

            features.append(
                {
                    "type": "Feature",
                    "geometry": f.get("geometry"),
                    "properties": {
                        "id": id_sismo(f["id"]),
                        "magnitude": p.get("mag"),
                        "time": ms_a_iso(p.get("time")),
                        "updated": ms_a_iso(p.get("updated")),
                        "longitude": lon,
                        "latitude": lat,
                        "depth": prof,
                        "place": p.get("place"),
                        "status": p.get("status"),
                        "url": p.get("url"),
                    },
                }
            )
    features.sort(key=lambda x: (x["properties"]["time"], x["properties"]["id"]))
    return {
        "type": "FeatureCollection",
        "fecha_extraccion": a_iso(extraccion),
        "features": features,
    }


# ---------------------------------------------------------------------- todo


def convertir_todo(carpeta_raw: Path, carpeta_processed: Path, config: dict[str, Any]) -> dict:
    """Convierte todo ``raw/`` y escribe los archivos del contrato en ``processed/``."""
    filas, fuentes, auditoria = convertir_noticias(carpeta_raw, config)
    indicadores = convertir_indicadores(carpeta_raw, config)
    eventos = convertir_eventos(carpeta_raw, config)
    escribir_csv(carpeta_processed / "noticias.csv", COLUMNAS_NOTICIAS, filas)
    escribir_json(carpeta_processed / "fuentes.json", fuentes)
    escribir_csv(carpeta_processed / "indicadores.csv", COLUMNAS_INDICADORES, indicadores)
    escribir_json(carpeta_processed / "eventos.geojson", eventos)
    escribir_json(carpeta_processed / "conversion.json", auditoria)
    resumen = {
        "noticias": len(filas),
        "fuentes": len(fuentes),
        "indicadores": len(indicadores),
        "eventos": len(eventos["features"]),
        "ventana_dias": auditoria["ventana"]["dias_aplicados"],
    }
    logger.info("Conversión terminada: %s", resumen)
    return resumen
