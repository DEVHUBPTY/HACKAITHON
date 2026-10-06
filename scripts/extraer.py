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
from src import consultas_gdelt
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

RAIZ = conversion.RAIZ
FORMATO_GDELT = conversion.FORMATO_GDELT
ORIGEN_REGISTRO_HERRAMIENTA = "generado por scripts.extraer"


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


_rangos = conversion.rangos_gdelt
_clasificar_respuesta = conversion.clasificar_respuesta


def _prefijo_gdelt(tema: str, ini: datetime, fin: datetime, pata: str | None = None) -> str:
    sufijo = f"__{pata}" if pata else ""
    return f"gdelt_{tema}{sufijo}_{ini.strftime(FORMATO_GDELT)}_{fin.strftime(FORMATO_GDELT)}"


def _pedir_gdelt(params: dict[str, Any], config: dict[str, Any], etiqueta: str = "") -> requests.Response:
    """GET a GDELT con backoff: respeta ``Retry-After``; si no, espera base × 2^intento.

    Un ``{}`` (o cuerpo vacío) se devuelve tal cual, **sin repetir la llamada**: no prueba que no haya
    resultados (GDELT lo devolvió para rangos que sí tenían artículos), así que quien llama lo registra
    como cobertura sin resolver. Solo se reintentan 429, 5xx, errores de red y cuerpos que no son JSON de GDELT.
    """
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
                if _clasificar_respuesta(resp.text) in ("ok", "vacio"):
                    return resp
                ultimo = f"cuerpo que no es JSON de GDELT: {resp.text[:60]!r}"
                espera = cfg["espera_429_segundos"] * 2**intento
            else:
                ultimo = f"HTTP {resp.status_code}"
                if resp.status_code != 429 and resp.status_code < 500:
                    raise ErrorDeExtraccion(f"GDELT respondió {ultimo}")
                retry = resp.headers.get("Retry-After", "")
                espera = int(retry) if retry.isdigit() else cfg["espera_429_segundos"] * 2**intento
        logger.warning("GDELT %s %s (intento %s/%s); espero %s s", etiqueta, ultimo, intento + 1, cfg["max_intentos"], espera)
        if intento + 1 < cfg["max_intentos"]:
            time.sleep(espera)
    raise ErrorDeExtraccion(f"GDELT sin respuesta tras {cfg['max_intentos']} intentos ({ultimo})")


def _guardar_gdelt(
    raw: Path, config: dict[str, Any], tema: str, ini: datetime, fin: datetime, texto: str, pata: str | None = None
) -> Path:
    return _guardar(
        raw / config["gdelt"]["carpeta_cruda"],
        conversion.nombre_con_ts(_prefijo_gdelt(tema, ini, fin, pata), _ahora(), "json"),
        texto.encode("utf-8"),
    )


def _consultar_gdelt(
    tema: str,
    consulta: str,
    ini: datetime,
    fin: datetime,
    raw: Path,
    config: dict[str, Any],
    estado: dict[str, Any],
    pata: str | None = None,
) -> int:
    """Consulta un rango: una sola llamada por tema, pata y rango en toda la corrida; si llega al tope lo divide a la mitad.

    No llama a la API si crudos ``ok`` ya cubren el rango (de cualquier alineación; salvo
    ``estado['forzar']``) ni si el rango ya se pidió en esta corrida. Un ``{}`` se guarda como crudo y se
    anota en ``estado['sospechosos']``: es cobertura sin resolver, apta para reintentar en otra corrida.
    Devuelve el número de artículos descargados (0 si se reutilizó o se omitió).
    """
    cfg = config["gdelt"]
    intentados: set[tuple[str, str | None, datetime, datetime]] = estado.setdefault("intentados", set())
    if (tema, pata, ini, fin) in intentados:
        return 0
    if not estado.get("forzar") and conversion.rango_cubierto(raw, config, tema, ini, fin, pata):
        logger.info("GDELT %s/%s %s..%s: ya cubierto por crudos existentes, no se vuelve a pedir", tema, pata, ini, fin)
        estado["reutilizados"] = estado.get("reutilizados", 0) + 1
        return 0
    intentados.add((tema, pata, ini, fin))
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
        resp = _pedir_gdelt(params, config, f"{tema}/{pata}")
    finally:
        estado["ultima"] = time.monotonic()
    texto = resp.text
    # Toda respuesta válida se guarda sin modificar, también la que se subdivide o viene vacía.
    _guardar_gdelt(raw, config, tema, ini, fin, texto, pata)
    if _clasificar_respuesta(texto) == "vacio":
        logger.warning("GDELT %s/%s %s..%s: respuesta {}; cobertura sin resolver (no es un vacío confirmado)", tema, pata, ini, fin)
        estado.setdefault("sospechosos", []).append(
            {
                "tema": tema,
                "pata": pata,
                "inicio": ini.strftime(FORMATO_GDELT),
                "fin": fin.strftime(FORMATO_GDELT),
                "tipo": "vacio_sospechoso",
                "motivo": "respuesta {} o vacía: no prueba que no haya resultados",
            }
        )
        return 0
    n = len(json.loads(texto, strict=False).get("articles") or [])
    if n >= cfg["maxrecords"] and conversion.rango_divisible(ini, fin, config):
        logger.info("GDELT %s/%s %s..%s llegó al tope (%s); subdivido", tema, pata, ini, fin, n)
        mitad = (ini + (fin - ini) / 2).replace(microsecond=0)
        return n + _consultar_gdelt(tema, consulta, ini, mitad, raw, config, estado, pata) + _consultar_gdelt(
            tema, consulta, mitad, fin, raw, config, estado, pata
        )
    logger.info("GDELT %s/%s %s..%s: %s artículos", tema, pata, ini, fin, n)
    return n


def _extraer_gdelt_rangos(
    raw: Path, config: dict[str, Any], dias: int, ahora: datetime, estado: dict[str, Any]
) -> tuple[int, list[dict[str, str]]]:
    cfg = config["gdelt"]
    total = 0
    fallidos: list[dict[str, str]] = []
    for ini, fin in _rangos(ahora, dias, cfg["rango_dias"]):
        for tema, pata, consulta in consultas_gdelt.construir_consultas(cfg["consultas"], cfg["largo_minimo_termino"]):
            try:
                total += _consultar_gdelt(tema, consulta, ini, fin, raw, config, estado, pata)
            except ErrorDeExtraccion as exc:  # un rango fallido no frena a los demás
                logger.error("GDELT %s/%s %s..%s falló: %s", tema, pata, ini, fin, exc)
                fallidos.append(
                    {
                        "tema": tema,
                        "pata": pata,
                        "inicio": ini.strftime(FORMATO_GDELT),
                        "fin": fin.strftime(FORMATO_GDELT),
                        "tipo": "bloqueado",
                        "motivo": str(exc),
                    }
                )
    logger.info("GDELT: %s artículos nuevos, %s rangos reutilizados, %s fallidos", total, estado.get("reutilizados", 0), len(fallidos))
    return total, fallidos


def _registrar_fallos(raw: Path, config: dict[str, Any], anotaciones: list[dict[str, str]]) -> None:
    """Anota los rangos sin resolver en ``registro_extraccion/`` (fuera de ``raw/``: no son respuestas de la API)."""
    if not anotaciones:
        return
    carpeta = raw.parent / config["general"]["carpeta_registro"]
    nombre = conversion.nombre_con_ts("fallos_gdelt", _ahora(), "json")
    conversion.escribir_json(carpeta / nombre, {"origen": ORIGEN_REGISTRO_HERRAMIENTA, "fallos": anotaciones})


def extraer_gdelt(raw: Path, config: dict[str, Any], forzar: bool = False) -> int:
    """GDELT en los últimos 30 días; si no se alcanza el mínimo, amplía hasta 90 (D-74).

    No repite llamadas: reutiliza lo ya cubierto por crudos (``forzar=True`` lo vuelve a pedir) y no pide
    dos veces el mismo rango en una corrida. Los rangos sin respuesta tras el backoff y los ``{}`` se anotan
    en ``registro_extraccion/`` y se sigue con el resto; los primeros hacen fallar la fuente.
    """
    ventana = config["ventana_noticias"]
    ahora = _ahora()
    estado: dict[str, Any] = {"forzar": forzar}
    total, fallidos = _extraer_gdelt_rangos(raw, config, ventana["dias_base"], ahora, estado)
    base = copy.deepcopy(config)
    base["ventana_noticias"]["dias_maximo"] = ventana["dias_base"]
    unicas, _, _ = conversion.convertir_noticias(raw, base)
    if len(unicas) < config["volumen_noticias"]["minimo"] and not ventana["ampliar_si_no_alcanza_minimo"]:
        logger.warning(
            "Solo %s noticias en %s días (mínimo %s) y ampliar_si_no_alcanza_minimo=false: no se amplía",
            len(unicas), ventana["dias_base"], config["volumen_noticias"]["minimo"],
        )
    elif len(unicas) < config["volumen_noticias"]["minimo"]:
        logger.warning(
            "Solo %s noticias en %s días (mínimo %s): amplío hasta %s días",
            len(unicas), ventana["dias_base"], config["volumen_noticias"]["minimo"], ventana["dias_maximo"],
        )
        mas, mas_fallidos = _extraer_gdelt_rangos(raw, config, ventana["dias_maximo"], ahora, estado)
        total += mas
        fallidos += mas_fallidos
    _registrar_fallos(raw, config, fallidos + estado.get("sospechosos", []))
    if fallidos:
        raise ErrorDeExtraccion(f"GDELT: {len(fallidos)} consulta(s) sin respuesta (anotadas en el registro de extracción)")
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
