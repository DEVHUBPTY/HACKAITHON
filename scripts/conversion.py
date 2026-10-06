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
    r"^gdelt_(?P<tema>[a-z]+(?:_[a-z]+)*?)(?:__(?P<pata>[a-z]+))?_(?P<ini>\d{14})_(?P<fin>\d{14})_(?P<ts>\d{8}T\d{6}Z)\.json$"
)
PATRON_ARCHIVO_WB = re.compile(r"^wb_(?P<ind>[A-Za-z0-9.]+)_(?P<ts>\d{8}T\d{6}Z)\.json$")

# Los campos del contrato viven en config/contrato.yaml (única fuente; también la usan la carga y la validación).
_CONTRATO = configuracion.cargar_contrato()
COLUMNAS_NOTICIAS = _CONTRATO.noticias
COLUMNAS_INDICADORES = [*_CONTRATO.indicadores_extra, *_CONTRATO.indicadores]
CAMPOS_FUENTES = _CONTRATO.fuentes
CAMPOS_EVENTO = _CONTRATO.eventos
FORMATO_GDELT = "%Y%m%d%H%M%S"
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


def normalizar_idioma(nombre: str, config: dict[str, Any]) -> str:
    """Nombre de idioma de GDELT -> ISO 639-1 (sin distinguir mayúsculas); si no se conoce, el nombre en minúsculas."""
    tabla = {k.lower(): v for k, v in config["gdelt"]["idiomas"].items()}
    return tabla.get(nombre.strip().lower(), nombre.strip().lower())


def _nombre_medio(dominio: str, config: dict[str, Any]) -> str:
    conocido = config.get("medios_conocidos", {}).get(dominio)
    return conocido["nombre"] if conocido else dominio


# ------------------------------------------------------------------- noticias


def _seccion_url(url: str, config: dict[str, Any]) -> str:
    """Primera sección de la ruta; ``tema_sin_seccion`` si la ruta tiene menos segmentos que el mínimo."""
    cfg = config["rss_tvn"]
    segmentos = [s for s in urlsplit(url).path.split("/") if s]
    return segmentos[0] if len(segmentos) >= cfg["segmentos_minimos_para_seccion"] else cfg["tema_sin_seccion"]


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
                "tema": _seccion_url(url, config) if url else "",
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
                "idioma": normalizar_idioma(lengua, config),
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


# ------------------------------------------------------------ cobertura de GDELT


def rangos_gdelt(hoy: datetime, dias_atras: int, dias_rango: int) -> list[tuple[datetime, datetime]]:
    """Rangos alineados a una grilla fija de ``dias_rango`` días (días desde 1970), del más reciente al más antiguo.

    Como los límites no dependen de la hora de ejecución, una segunda corrida pide los mismos
    rangos. El más antiguo se recorta al inicio de la ventana (nunca pide fechas más atrás de
    ``dias_atras``, para no salirse de la cobertura de GDELT). Se excluye el día en curso (lo cubre el RSS).
    """
    fin_total = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio = fin_total - timedelta(days=dias_atras)
    epoca = datetime(1970, 1, 1, tzinfo=UTC)
    k0 = (inicio - epoca).days // dias_rango
    k1 = (fin_total - epoca).days // dias_rango
    rangos = []
    for k in range(k1, k0 - 1, -1):
        ini = max(epoca + timedelta(days=k * dias_rango), inicio)
        fin = min(epoca + timedelta(days=(k + 1) * dias_rango), fin_total)
        if ini < fin:
            rangos.append((ini, fin))
    return rangos


def clasificar_respuesta(texto: str) -> str:
    """``ok`` = JSON de GDELT con la clave ``articles``; ``vacio`` = ``{}`` o cuerpo vacío; ``invalido`` = lo demás.

    Un ``{}`` NO prueba que no haya resultados: GDELT lo devolvió para un rango que sí tenía
    artículos (2026-10-06). Por eso un vacío es cobertura sin resolver, nunca un vacío confirmado.
    """
    if not texto.strip():
        return "vacio"
    try:
        datos = json.loads(texto, strict=False)
    except json.JSONDecodeError:
        return "invalido"
    if isinstance(datos, dict) and "articles" in datos:
        return "ok"
    return "vacio" if datos == {} else "invalido"


def rango_divisible(ini: datetime, fin: datetime, config: dict[str, Any]) -> bool:
    """True si la mitad del rango sigue siendo >= ``rango_minimo_horas`` (se puede subdividir)."""
    return (fin - ini).total_seconds() / 3600 / 2 >= config["gdelt"]["rango_minimo_horas"]


MOTIVO_CONSULTA_REEMPLAZADA = "consulta reemplazada (D-83)"


def separar_crudos_gdelt(carpeta_raw: Path, config: dict[str, Any]) -> tuple[list[Path], list[dict[str, Any]]]:
    """Separa los crudos de GDELT en vigentes y reemplazados (D-83).

    Vigente = su (tema, pata) existe en ``gdelt.consultas``. El resto (p. ej. los anteriores a E0-04, sin pata)
    queda intacto en ``raw/`` pero no alimenta el snapshot: se devuelve como excluido, con su consulta histórica.
    """
    cfg = config["gdelt"]
    vigentes_ok = {(t, p) for t, patas in cfg["consultas"].items() for p in patas}
    historicas = cfg.get("consultas_historicas", {})
    vigentes: list[Path] = []
    excluidos: list[dict[str, Any]] = []
    for ruta in archivos_crudos(carpeta_raw / cfg["carpeta_cruda"], "gdelt_*.json"):
        m = PATRON_ARCHIVO_GDELT.match(ruta.name)
        if m and (m["tema"], m["pata"]) in vigentes_ok:
            vigentes.append(ruta)
            continue
        if not m:
            raise ValueError(f"nombre de crudo GDELT no reconocido: {ruta.name}")
        tema = m["tema"]
        excluidos.append(
            {
                "archivo": ruta.name,
                "tema": tema,
                "pata": m["pata"],
                "motivo": MOTIVO_CONSULTA_REEMPLAZADA,
                "consulta_historica": historicas.get(tema),
            }
        )
    return vigentes, excluidos


def crudos_gdelt(carpeta_raw: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Clasifica cada crudo ``gdelt_*.json``.

    Clases: ``ok`` (cubre su rango), ``vacio`` (``{}``: cobertura sin resolver), ``truncado`` (llegó al
    tope de ``maxrecords`` y el rango se podía subdividir: solo cubren sus mitades) e ``invalido``.
    """
    carpeta = carpeta_raw / config["gdelt"]["carpeta_cruda"]
    tope = config["gdelt"]["maxrecords"]
    salida = []
    for ruta in archivos_crudos(carpeta, "gdelt_*.json"):
        m = PATRON_ARCHIVO_GDELT.match(ruta.name)
        if not m:
            continue
        texto = ruta.read_text(encoding="utf-8")
        clase = clasificar_respuesta(texto)
        ini = datetime.strptime(m["ini"], FORMATO_GDELT).replace(tzinfo=UTC)
        fin = datetime.strptime(m["fin"], FORMATO_GDELT).replace(tzinfo=UTC)
        if clase == "ok":
            n = len(json.loads(texto, strict=False).get("articles") or [])
            if n >= tope and rango_divisible(ini, fin, config):
                clase = "truncado"
        salida.append({"tema": m["tema"], "pata": m["pata"], "ini": ini, "fin": fin, "clase": clase, "archivo": ruta.name})
    return salida


def _fusionar_intervalos(intervalos: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Une intervalos que se solapan o se tocan."""
    unidos: list[list[datetime]] = []
    for a, b in sorted(intervalos):
        if unidos and a <= unidos[-1][1]:
            unidos[-1][1] = max(unidos[-1][1], b)
        else:
            unidos.append([a, b])
    return [(a, b) for a, b in unidos]


def rango_cubierto(
    carpeta_raw: Path, config: dict[str, Any], tema: str, ini: datetime, fin: datetime, pata: str | None = None
) -> bool:
    """True si crudos ``ok`` de ese tema y pata (de cualquier alineación) cubren por completo ``[ini, fin]``.

    Los crudos sin pata (consultas anteriores a E0-04) no cubren ninguna pata nueva.
    """
    cubiertos = _fusionar_intervalos(
        [
            (c["ini"], c["fin"])
            for c in crudos_gdelt(carpeta_raw, config)
            if c["tema"] == tema and c["pata"] == pata and c["clase"] == "ok"
        ]
    )
    return any(a <= ini and fin <= b for a, b in cubiertos)


def registro_extraccion(carpeta_raw: Path, config: dict[str, Any]) -> list[dict[str, str]]:
    """Fallos anotados en ``registro_extraccion/`` (generados por la herramienta o escritos a mano).

    No son respuestas de la API: nunca viven en ``raw/`` ni definen la fecha de corte.
    """
    carpeta = carpeta_raw.parent / config["general"]["carpeta_registro"]
    entradas = []
    for ruta in archivos_crudos(carpeta, "*.json"):
        cuerpo = json.loads(ruta.read_text(encoding="utf-8"))
        fallos = cuerpo if isinstance(cuerpo, list) else cuerpo.get("fallos", [])
        origen = "" if isinstance(cuerpo, list) else cuerpo.get("origen", "")
        for f in fallos:
            entradas.append({**f, "archivo": ruta.name, "origen": origen})
    return entradas


def _solapa(a: datetime, b: datetime, desde: datetime, hasta: datetime) -> bool:
    return a < hasta and b > desde


def _fecha_registro(texto: str) -> datetime | None:
    try:
        return datetime.strptime(texto, FORMATO_GDELT).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _motivo_dia(
    dia: datetime, propios: list[dict[str, Any]], registro: list[dict[str, str]]
) -> tuple[str, str]:
    """Por qué un día de la ventana no está cubierto: (motivo, detalle)."""
    hasta = dia + timedelta(days=1)
    en_dia = [c for c in propios if _solapa(c["ini"], c["fin"], dia, hasta)]
    fallos = []
    for r in registro:
        a, b = _fecha_registro(r.get("inicio", "")), _fecha_registro(r.get("fin", ""))
        if a and b and _solapa(a, b, dia, hasta):
            fallos.append(r)
    vacios = [c for c in en_dia if c["clase"] == "vacio"]
    vacios_anotados = [r for r in fallos if r.get("tipo") == "vacio_sospechoso"]
    if vacios or vacios_anotados:
        return (
            "vacio_sospechoso",
            "respuesta {} o vacía: no prueba que no haya resultados; cobertura sin resolver, reintentar",
        )
    if fallos:
        return "bloqueado", "; ".join(sorted({r.get("motivo", "") for r in fallos}))
    if any(c["clase"] == "truncado" for c in en_dia):
        return "truncado_sin_resolver", "respuesta al tope de maxrecords y sin las mitades del rango"
    if any(c["clase"] == "ok" for c in en_dia):
        return "cobertura_parcial", "un crudo cubre solo una parte de este día"
    return "no_solicitado", "ningún crudo ni intento registrado para este día"


def cobertura_gdelt(carpeta_raw: Path, config: dict[str, Any], fin: datetime, dias: int) -> dict[str, Any]:
    """Cobertura real de GDELT por tema sobre los días de la ventana aplicada.

    Un día cuenta como cubierto solo si un crudo ``ok`` (o la unión de varios contiguos, de
    cualquier alineación) lo contiene completo. El resto se lista como rangos sin resolver, con motivo
    (``no_solicitado``, ``bloqueado``, ``vacio_sospechoso``, ``cobertura_parcial``, ``truncado_sin_resolver``).
    """
    crudos = crudos_gdelt(carpeta_raw, config)
    registro = registro_extraccion(carpeta_raw, config)
    fin_total = fin.replace(hour=0, minute=0, second=0, microsecond=0)
    ventana = [fin_total - timedelta(days=dias - i) for i in range(dias)]
    por_tema: dict[str, dict[str, int]] = {}
    sin_resolver: list[dict[str, Any]] = []
    for tema, definicion in config["gdelt"]["consultas"].items():
        # Un día cuenta como cubierto solo si lo cubren TODAS las patas del tema (E0-04).
        patas: list[str] = list(definicion)
        por_pata = {}
        for pata in patas:
            propios = [c for c in crudos if c["tema"] == tema and c["pata"] == pata]
            cubiertos = _fusionar_intervalos([(c["ini"], c["fin"]) for c in propios if c["clase"] == "ok"])
            regs = [r for r in registro if r.get("tema") == tema and r.get("pata") == pata]
            por_pata[pata] = (propios, cubiertos, regs)
        pendientes: list[tuple[datetime, str, str]] = []
        for dia in ventana:
            for pata, (propios, cubiertos, regs) in por_pata.items():
                if any(a <= dia and dia + timedelta(days=1) <= b for a, b in cubiertos):
                    continue
                motivo, detalle = _motivo_dia(dia, propios, regs)
                pendientes.append((dia, motivo, f"[{pata}] {detalle}"))
                break
        por_tema[tema] = {"dias_esperados": len(ventana), "dias_cubiertos": len(ventana) - len(pendientes)}
        corridas: list[dict[str, Any]] = []
        for dia, motivo, detalle in pendientes:
            if corridas and corridas[-1]["fin"] == dia and (corridas[-1]["motivo"], corridas[-1]["detalle"]) == (motivo, detalle):
                corridas[-1]["fin"] = dia + timedelta(days=1)
            else:
                corridas.append({"inicio": dia, "fin": dia + timedelta(days=1), "motivo": motivo, "detalle": detalle})
        for c in corridas:
            sin_resolver.append(
                {
                    "tema": tema,
                    "inicio": c["inicio"].strftime(FORMATO_GDELT),
                    "fin": c["fin"].strftime(FORMATO_GDELT),
                    "dias": (c["fin"] - c["inicio"]).days,
                    "motivo": c["motivo"],
                    "detalle": c["detalle"],
                }
            )
    return {"por_tema": por_tema, "sin_resolver": sorted(sin_resolver, key=lambda x: (x["tema"], x["inicio"]))}


def convertir_noticias(
    carpeta_raw: Path, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Convierte RSS y GDELT crudos a filas de ``noticias.csv`` y registros de ``fuentes.json``.

    Devuelve (filas, fuentes, auditoría). La auditoría documenta la ventana y las exclusiones.
    """
    archivos_rss = archivos_crudos(carpeta_raw / config["rss_tvn"]["carpeta_cruda"], "rss_tvn_*.xml")
    archivos_gdelt, crudos_excluidos = separar_crudos_gdelt(carpeta_raw, config)
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
    conocidos = set(config["gdelt"]["idiomas"].values()) | {config["general"]["idioma_por_defecto"]}
    sin_mapeo = Counter(f["idioma"] for f in filas if f["idioma"] and f["idioma"] not in conocidos)
    cobertura = cobertura_gdelt(carpeta_raw, config, fin, dias)
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
        "crudos_excluidos": crudos_excluidos,
        "gdelt_cobertura_por_tema": cobertura["por_tema"],
        "gdelt_rangos_sin_resolver": cobertura["sin_resolver"],
        "idiomas_sin_mapeo": dict(sorted(sin_mapeo.items())),
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
            config["paises_es"].get(sorted(paises.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]) if paises else None
        )
        origenes = sorted({o for r in rs for o in r["origenes"]}, key=[ORIGEN_RSS, ORIGEN_GDELT].index)
        fuentes.append(
            {
                "dominio": dominio,
                "nombre_legible": _nombre_medio(dominio, config),
                "pais": pais or None,  # nulo si no se conoce; "Pendiente de verificar" es solo para condiciones
                "origen": " · ".join(origenes),
                "condiciones": conocido.get("condiciones", CONDICIONES_PENDIENTES).strip(),
            }
        )
    return fuentes


# ---------------------------------------------------------------- indicadores


def valores_banco_mundial(
    carpeta_raw: Path, config: dict[str, Any]
) -> dict[str, tuple[datetime | None, dict[tuple[str, int], Any]]]:
    """Por indicador: (marca de tiempo, {(país, año): valor}) del crudo más reciente; ``None`` si no hay crudo."""
    cfg = config["banco_mundial"]
    carpeta = carpeta_raw / cfg["carpeta_cruda"]
    ultimo: dict[str, Path] = {}
    for ruta in archivos_crudos(carpeta, "wb_*.json"):
        m = PATRON_ARCHIVO_WB.match(ruta.name)
        if m:  # el orden por nombre deja al final la extracción más reciente
            ultimo[m.group("ind")] = ruta
    salida: dict[str, tuple[datetime | None, dict[tuple[str, int], Any]]] = {}
    for ind in cfg["indicadores"]:
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
        salida[ind] = (ts, valores)
    return salida


def convertir_indicadores(carpeta_raw: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Completa la cuadrícula país × indicador × año; los faltantes quedan nulos, nunca 0."""
    cfg = config["banco_mundial"]
    anios = range(cfg["anio_inicio"], cfg["anio_fin"] + 1)
    crudos = valores_banco_mundial(carpeta_raw, config)
    filas = []
    for ind, meta in cfg["indicadores"].items():
        ts, valores = crudos[ind]
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
