"""Extracción del snapshot (E0-04): TVN RSS, GDELT DOC 2.0, Banco Mundial y USGS.

Uso::

    poetry run python -m scripts.extraer --todo
    poetry run python -m scripts.extraer --rss      # seguro de correr a diario: agrega, nunca pisa

Las respuestas crudas se guardan sin modificar en ``data/raw/<fuente>/`` con la marca de tiempo UTC
en el nombre. Después se convierte todo ``raw/`` al contrato en ``data/processed/``.
No se descargan cuerpos de artículos, imágenes ni videos.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from scripts import conversion
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

RAIZ = conversion.RAIZ
FORMATO_GDELT = "%Y%m%d%H%M%S"


class ErrorDeExtraccion(RuntimeError):
    """Una fuente no respondió de forma utilizable tras los reintentos."""


def _ahora() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _get(
    url: str, params: dict[str, Any] | None, config: dict[str, Any], espera_429: int | None = None
) -> requests.Response:
    """GET con reintentos corteses ante 429, 5xx y errores de red."""
    gen = config["general"]
    ultimo: Exception | None = None
    for intento in range(1, gen["reintentos"] + 1):
        try:
            resp = requests.get(
                url,
                params=params,
                headers={"User-Agent": gen["agente_http"]},
                timeout=gen["timeout_segundos"],
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                espera = espera_429 if resp.status_code == 429 and espera_429 else None
                espera = espera or gen["espera_reintento_segundos"]
                logger.warning(
                    "HTTP %s en %s (intento %s/%s); espero %s s",
                    resp.status_code,
                    url,
                    intento,
                    gen["reintentos"],
                    espera,
                )
                ultimo = ErrorDeExtraccion(f"HTTP {resp.status_code}")
                time.sleep(espera)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            ultimo = exc
            logger.warning("Error de red en %s (intento %s): %s", url, intento, exc)
            time.sleep(gen["espera_reintento_segundos"])
    raise ErrorDeExtraccion(f"No se pudo obtener {url}: {ultimo}")


def _guardar(carpeta: Path, nombre: str, contenido: bytes) -> Path:
    """Guarda la respuesta cruda sin modificar; nunca sobrescribe un archivo existente."""
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / nombre
    if ruta.exists():
        raise FileExistsError(f"El crudo ya existe y es inmutable: {ruta}")
    ruta.write_bytes(contenido)
    logger.info("Crudo guardado: %s (%s bytes)", ruta.relative_to(RAIZ) if ruta.is_relative_to(RAIZ) else ruta, len(contenido))
    return ruta


# ------------------------------------------------------------------------ RSS


def extraer_rss(raw: Path, config: dict[str, Any]) -> Path:
    """Descarga el RSS de TVN y lo agrega como archivo nuevo con marca de tiempo."""
    cfg = config["rss_tvn"]
    resp = _get(cfg["url"], None, config)
    nombre = conversion.nombre_con_ts("rss_tvn", _ahora(), "xml")
    return _guardar(raw / cfg["carpeta_cruda"], nombre, resp.content)


# ---------------------------------------------------------------------- GDELT


def _rangos(
    hoy: datetime, dias_atras: int, dias_rango: int
) -> list[tuple[datetime, datetime]]:
    """Rangos alineados a una grilla fija de ``dias_rango`` días (días desde 1970), del más reciente al más antiguo.

    Como los límites no dependen de la hora de ejecución, una segunda corrida pide exactamente los
    mismos rangos y puede reutilizar los crudos. Se excluye el día en curso (el RSS lo cubre).
    """
    fin_total = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio = fin_total - timedelta(days=dias_atras)
    epoca = datetime(1970, 1, 1, tzinfo=UTC)
    k0 = (inicio - epoca).days // dias_rango
    k1 = (fin_total - epoca).days // dias_rango
    rangos = []
    for k in range(k1, k0 - 1, -1):
        ini = epoca + timedelta(days=k * dias_rango)
        fin = min(epoca + timedelta(days=(k + 1) * dias_rango), fin_total)
        if ini < fin:
            rangos.append((ini, fin))
    return rangos


def _prefijo_gdelt(tema: str, ini: datetime, fin: datetime) -> str:
    return f"gdelt_{tema}_{ini.strftime(FORMATO_GDELT)}_{fin.strftime(FORMATO_GDELT)}"


def _crudo_existente(raw: Path, config: dict[str, Any], tema: str, ini: datetime, fin: datetime) -> Path | None:
    """Crudo ya descargado para exactamente esta consulta y este rango, si existe."""
    carpeta = raw / config["gdelt"]["carpeta_cruda"]
    coincidencias = conversion.archivos_crudos(carpeta, f"{_prefijo_gdelt(tema, ini, fin)}_*.json")
    return coincidencias[-1] if coincidencias else None


def _pedir_gdelt(params: dict[str, Any], config: dict[str, Any]) -> requests.Response:
    """GET a GDELT con backoff: respeta ``Retry-After``; si no, espera base × 2^intento."""
    cfg = config["gdelt"]
    gen = config["general"]
    ultimo = "sin intentos"
    for intento in range(cfg["max_intentos"]):
        try:
            resp = requests.get(
                cfg["endpoint"],
                params=params,
                headers={"User-Agent": gen["agente_http"]},
                timeout=gen["timeout_segundos"],
            )
        except requests.RequestException as exc:
            ultimo = f"red: {exc}"
            espera = cfg["espera_429_segundos"] * 2**intento
        else:
            if resp.status_code == 200:
                return resp
            ultimo = f"HTTP {resp.status_code}"
            if resp.status_code != 429 and resp.status_code < 500:
                raise ErrorDeExtraccion(f"GDELT respondió {ultimo}")
            retry = resp.headers.get("Retry-After", "")
            espera = int(retry) if retry.isdigit() else cfg["espera_429_segundos"] * 2**intento
        logger.warning("GDELT %s (intento %s/%s); espero %s s", ultimo, intento + 1, cfg["max_intentos"], espera)
        if intento + 1 < cfg["max_intentos"]:
            time.sleep(espera)
    raise ErrorDeExtraccion(f"GDELT sin respuesta tras {cfg['max_intentos']} intentos ({ultimo})")


def _consultar_gdelt(
    tema: str,
    consulta: str,
    ini: datetime,
    fin: datetime,
    raw: Path,
    config: dict[str, Any],
    estado: dict[str, Any],
) -> int:
    """Consulta un rango (una sola llamada por tema y rango); si llega al tope lo divide a la mitad.

    Si ya existe un crudo de esta consulta y rango, no llama a la API (salvo ``estado['forzar']``).
    Devuelve el número de artículos descargados (0 si se reutilizó un crudo).
    """
    cfg = config["gdelt"]
    if not estado.get("forzar") and _crudo_existente(raw, config, tema, ini, fin):
        logger.info("GDELT %s %s..%s: crudo existente, no se vuelve a pedir", tema, ini, fin)
        estado["reutilizados"] = estado.get("reutilizados", 0) + 1
        return 0
    pausa = cfg["pausa_segundos"] - (time.monotonic() - estado.get("ultima", -1e9))
    if pausa > 0:
        time.sleep(pausa)
    params = {
        "query": consulta,
        "mode": cfg["modo"],
        "format": cfg["formato"],
        "maxrecords": cfg["maxrecords"],
        "sort": cfg["orden"],
        "startdatetime": ini.strftime(FORMATO_GDELT),
        "enddatetime": fin.strftime(FORMATO_GDELT),
    }
    try:
        resp = _pedir_gdelt(params, config)
    finally:
        estado["ultima"] = time.monotonic()
    texto = resp.text
    try:
        datos = json.loads(texto, strict=False) if texto.strip() else {}
    except json.JSONDecodeError as exc:
        raise ErrorDeExtraccion(f"GDELT devolvió algo que no es JSON: {texto[:80]!r}") from exc
    n = len(datos.get("articles", []))
    horas = (fin - ini).total_seconds() / 3600
    if n >= cfg["maxrecords"] and horas / 2 >= cfg["rango_minimo_horas"]:
        logger.info("GDELT %s %s..%s llegó al tope (%s); subdivido", tema, ini, fin, n)
        mitad = (ini + (fin - ini) / 2).replace(microsecond=0)
        return _consultar_gdelt(tema, consulta, ini, mitad, raw, config, estado) + _consultar_gdelt(
            tema, consulta, mitad, fin, raw, config, estado
        )
    # Se guarda también la respuesta vacía: así la corrida siguiente no repite la llamada.
    _guardar(
        raw / cfg["carpeta_cruda"],
        conversion.nombre_con_ts(_prefijo_gdelt(tema, ini, fin), _ahora(), "json"),
        texto.encode("utf-8"),
    )
    logger.info("GDELT %s %s..%s: %s artículos", tema, ini, fin, n)
    return n


def _extraer_gdelt_rangos(
    raw: Path, config: dict[str, Any], dias: int, ahora: datetime, forzar: bool
) -> tuple[int, list[dict[str, str]]]:
    cfg = config["gdelt"]
    estado: dict[str, Any] = {"forzar": forzar}
    total = 0
    fallidos: list[dict[str, str]] = []
    for ini, fin in _rangos(ahora, dias, cfg["rango_dias"]):
        for tema, consulta in cfg["consultas"].items():
            try:
                total += _consultar_gdelt(tema, consulta, ini, fin, raw, config, estado)
            except ErrorDeExtraccion as exc:  # un rango fallido no frena a los demás
                logger.error("GDELT %s %s..%s falló: %s", tema, ini, fin, exc)
                fallidos.append(
                    {"tema": tema, "inicio": ini.strftime(FORMATO_GDELT), "fin": fin.strftime(FORMATO_GDELT), "motivo": str(exc)}
                )
    logger.info("GDELT: %s artículos nuevos, %s rangos reutilizados, %s fallidos", total, estado.get("reutilizados", 0), len(fallidos))
    return total, fallidos


def _registrar_fallos(raw: Path, config: dict[str, Any], fallidos: list[dict[str, str]]) -> None:
    """Guarda los rangos sin respuesta como crudo con marca de tiempo; el manifest los reporta."""
    if not fallidos:
        return
    carpeta = raw / config["gdelt"]["carpeta_cruda"]
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = conversion.nombre_con_ts("fallos_gdelt", _ahora(), "json")
    conversion.escribir_json(carpeta / nombre, fallidos)


def extraer_gdelt(raw: Path, config: dict[str, Any], forzar: bool = False) -> int:
    """GDELT en los últimos 30 días; si no se alcanza el mínimo, amplía hasta 90 (D-74).

    Reutiliza los crudos existentes (``forzar=True`` los vuelve a pedir). Los rangos que no
    responden tras el backoff se registran como fallos y se sigue con el resto.
    """
    ventana = config["ventana_noticias"]
    ahora = _ahora()
    total, fallidos = _extraer_gdelt_rangos(raw, config, ventana["dias_base"], ahora, forzar)
    base = copy.deepcopy(config)
    base["ventana_noticias"]["dias_maximo"] = ventana["dias_base"]
    unicas, _, _ = conversion.convertir_noticias(raw, base)
    if len(unicas) < config["volumen_noticias"]["minimo"]:
        logger.warning(
            "Solo %s noticias en %s días (mínimo %s): amplío hasta %s días",
            len(unicas), ventana["dias_base"], config["volumen_noticias"]["minimo"], ventana["dias_maximo"],
        )
        mas, mas_fallidos = _extraer_gdelt_rangos(raw, config, ventana["dias_maximo"], ahora, forzar)
        total += mas
        fallidos = mas_fallidos
    _registrar_fallos(raw, config, fallidos)
    if fallidos:
        raise ErrorDeExtraccion(f"GDELT: {len(fallidos)} consulta(s) sin respuesta (registradas en el crudo de fallos)")
    return total


# -------------------------------------------------------------- Banco Mundial


def extraer_banco_mundial(raw: Path, config: dict[str, Any]) -> list[Path]:
    """Una consulta por indicador, con ``per_page=1000`` para no paginar."""
    cfg = config["banco_mundial"]
    paises = ";".join(cfg["paises"])
    guardados = []
    for i, ind in enumerate(cfg["indicadores"]):
        if i:
            time.sleep(cfg["pausa_segundos"])
        resp = _get(
            f"{cfg['base_url']}/country/{paises}/indicator/{ind}",
            {
                "format": "json",
                "date": f"{cfg['anio_inicio']}:{cfg['anio_fin']}",
                "per_page": cfg["per_page"],
            },
            config,
        )
        cuerpo = resp.json()
        if not (isinstance(cuerpo, list) and len(cuerpo) > 1 and cuerpo[1]):
            raise ErrorDeExtraccion(f"Respuesta inesperada del Banco Mundial para {ind}: {str(cuerpo)[:120]}")
        if cuerpo[0].get("pages", 1) > 1:
            raise ErrorDeExtraccion(f"El Banco Mundial paginó {ind}; subir per_page")
        nombre = conversion.nombre_con_ts(f"wb_{ind}", _ahora(), "json")
        guardados.append(_guardar(raw / cfg["carpeta_cruda"], nombre, resp.content))
    return guardados


# ----------------------------------------------------------------------- USGS


def extraer_usgs(raw: Path, config: dict[str, Any]) -> Path:
    """Una sola consulta al servicio FDSN de USGS."""
    cfg = config["usgs"]
    params = {k: cfg[k] for k in (
        "starttime", "endtime", "minlatitude", "maxlatitude", "minlongitude", "maxlongitude",
        "minmagnitude", "orderby",
    )}
    params["format"] = cfg["formato"]
    resp = _get(cfg["endpoint"], params, config)
    if resp.json().get("type") != "FeatureCollection":
        raise ErrorDeExtraccion("Respuesta inesperada de USGS")
    nombre = conversion.nombre_con_ts("usgs", _ahora(), "geojson")
    return _guardar(raw / cfg["carpeta_cruda"], nombre, resp.content)


# ------------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de ``python -m scripts.extraer``."""
    p = argparse.ArgumentParser(description="Extrae las fuentes A, B y C y las convierte al contrato.")
    p.add_argument("--todo", action="store_true", help="RSS, GDELT, Banco Mundial y USGS")
    p.add_argument("--rss", action="store_true", help="agrega un RSS de TVN nuevo (apto para correr a diario)")
    p.add_argument("--gdelt", action="store_true")
    p.add_argument("--banco-mundial", action="store_true", dest="banco_mundial")
    p.add_argument("--usgs", action="store_true")
    p.add_argument("--forzar", action="store_true", help="vuelve a pedir a GDELT rangos que ya tienen crudo")
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw")
    p.add_argument("--processed", type=Path, default=RAIZ / "data" / "processed")
    p.add_argument("--sin-convertir", action="store_true", help="solo descarga, no genera processed/")
    args = p.parse_args(argv)
    if not (args.todo or args.rss or args.gdelt or args.banco_mundial or args.usgs):
        p.error("indica --todo o al menos una fuente")

    configurar_logging()
    config = conversion.cargar_config()
    fallos: list[str] = []
    pasos = [
        ("rss", args.todo or args.rss, extraer_rss),
        ("gdelt", args.todo or args.gdelt, lambda r, c: extraer_gdelt(r, c, forzar=args.forzar)),
        ("banco_mundial", args.todo or args.banco_mundial, extraer_banco_mundial),
        ("usgs", args.todo or args.usgs, extraer_usgs),
    ]
    for nombre, activo, funcion in pasos:
        if not activo:
            continue
        try:
            funcion(args.raw, config)
        except (ErrorDeExtraccion, OSError, ValueError) as exc:
            logger.error("Falló la fuente %s: %s", nombre, exc)
            fallos.append(nombre)
    if not args.sin_convertir:
        resumen = conversion.convertir_todo(args.raw, args.processed, config)
        print(json.dumps(resumen, ensure_ascii=False, sort_keys=True))
    if fallos:
        print(f"Fuentes con error: {', '.join(fallos)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
