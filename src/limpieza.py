"""Limpieza de titulares y marcado de ruido (E1-03b). Marca, no borra.

Entrada: ``data/senales.duckdb`` (la crea ``python -m src.normalizacion``). Agrega a ``noticias``:

* ``titulo_original`` (copia del titular recibido) y ``titulo_limpio`` (sin sufijo del medio, sin entidades HTML,
  con espacios y comillas normalizados). Los embeddings usan el limpio; la interfaz muestra el original.
* ``es_ruido`` y ``motivo_ruido``: ``fuera_de_ventana``, ``no_es_noticia``, ``no_es_panama`` o ``fuera_de_temas``.
  El registro se conserva siempre; el ruido solo queda fuera de la bandeja y del puntaje.
* ``sospechoso_inyeccion`` (D-69): el titular o la descripción tienen patrones de instrucción. No excluye nada.

``duplicado_url`` no se marca aquí: E1-03 ya fusiona las URL canónicas iguales y deja cada duplicado en la tabla
``duplicados_eliminados``; el reporte los cuenta con ese motivo.

La descripción del RSS solo se lee para detectar inyección y nunca se escribe en el reporte (D-31).
Uso: ``poetry run python -m src.limpieza``.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src import db
from src.carga import intervalo_wilson
from src.configuracion import (
    RAIZ,
    ConfigFuentes,
    ConfigNormalizacion,
    ConfigRestricciones,
    ConfigRuido,
    cargar_carga,
    cargar_fuentes,
    cargar_normalizacion,
    cargar_restricciones,
    cargar_ruido,
)
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

MOTIVO_NO_ES_PANAMA = "no_es_panama"
MOTIVO_FUERA_DE_TEMAS = "fuera_de_temas"
MOTIVO_NO_ES_NOTICIA = "no_es_noticia"
MOTIVO_FUERA_DE_VENTANA = "fuera_de_ventana"
MOTIVO_DUPLICADO_URL = "duplicado_url"  # lo registra E1-03 en duplicados_eliminados
MOTIVOS_MARCADOS = (MOTIVO_NO_ES_PANAMA, MOTIVO_FUERA_DE_TEMAS, MOTIVO_NO_ES_NOTICIA, MOTIVO_FUERA_DE_VENTANA)

# Presentación del reporte (no es un parámetro de decisión): decimales de las proporciones y los IC.
DECIMALES_PRESENTACION = 4

Fila = dict[str, Any]


def plano(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar sin distinguir mayúsculas ni acentos."""
    sin_marcas = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return sin_marcas.casefold()


def _alnum(texto: str) -> str:
    return re.sub(r"[\W_]+", "", plano(texto))


def _compilar(patrones: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patrones]


@dataclass(frozen=True)
class Resultado:
    """Lo que la limpieza decide de una noticia."""

    titulo_limpio: str
    es_ruido: bool
    motivo_ruido: str | None
    sospechoso_inyeccion: bool
    alcance_regional: bool = False


class Reglas:
    """Patrones compilados de ``ruido.yaml`` y ``restricciones.yaml`` (se compilan una vez)."""

    def __init__(
        self,
        ruido: ConfigRuido,
        restricciones: ConfigRestricciones,
        fuentes: ConfigFuentes,
        normalizacion: ConfigNormalizacion,
    ) -> None:
        self.ruido = ruido
        self.formato_fecha = normalizacion.fechas.formato_salida
        self.separador_origen = normalizacion.noticias.separador_origen
        self.dias_ventana = fuentes.ventana_noticias.dias_maximo
        self.reemplazos = [(re.compile(par[0]), par[1]) for par in ruido.limpieza.reemplazos]
        self.titulo_generico = _compilar(ruido.no_noticia.titulo_generico)
        self.titulo_promocional = _compilar(ruido.no_noticia.titulo_promocional)
        self.patrones_url = _compilar(ruido.no_noticia.patrones_url)
        self.categorias_rss = {plano(c) for c in ruido.no_noticia.categorias_rss}
        self.falsos = _compilar(ruido.panama.falsos)
        self.menciones = _compilar(ruido.panama.menciones)
        self.deportes = _compilar(ruido.fuera_de_temas.deportes)
        self.farandula = _compilar(ruido.fuera_de_temas.farandula)
        self.cultura = _compilar(ruido.fuera_de_temas.cultura)
        self.politica = _compilar(ruido.fuera_de_temas.politica_partidista)
        self.autopromocion = _compilar(ruido.fuera_de_temas.autopromocion_tvn)
        self.regionales = _compilar(ruido.panama.regionales)
        self.inyeccion = _compilar(restricciones.inyeccion.patrones)

    @classmethod
    def desde_config(cls) -> Reglas:
        return cls(cargar_ruido(), cargar_restricciones(), cargar_fuentes(), cargar_normalizacion())


# ------------------------------------------------------------------ limpieza del titular


def _candidatos_medio(medio: str | None, dominio: str | None) -> list[str]:
    """Formas del nombre del medio contra las que se compara un posible sufijo (solo letras y dígitos)."""
    formas = [medio or "", dominio or ""]
    if dominio:
        partes = dominio.split(".")
        formas.append(".".join(partes[:-1]))  # "dominicantoday.com" -> "dominicantoday"
        if len(partes) >= 2:
            formas.append(partes[-2])
    return [f for f in (_alnum(x) for x in formas) if f]


def quitar_sufijo_medio(titulo: str, medio: str | None, dominio: str | None, reglas: Reglas) -> str:
    """Quita `` - Medio`` / `` | Medio`` del final si el sufijo es el medio de la noticia o uno conocido.

    Un guion cualquiera no es sufijo: podría ser parte del titular.
    """
    cfg = reglas.ruido.limpieza
    separadores = "|".join(re.escape(s) for s in cfg.separadores_sufijo)
    conocidos = [_alnum(m) for m in cfg.medios_conocidos]
    candidatos = [c for c in _candidatos_medio(medio, dominio) if len(c) >= cfg.min_letras_medio]
    for m in re.finditer(rf"\s(?:{separadores})\s", titulo):
        sufijo = titulo[m.end() :].strip()
        cabeza = titulo[: m.start()].rstrip()
        if not cabeza or not sufijo or len(sufijo.split()) > cfg.max_palabras_sufijo:
            continue
        forma = _alnum(sufijo)
        if not forma:
            continue
        es_medio = any(
            forma == c or (len(forma) >= cfg.min_letras_medio and (forma in c or c in forma)) for c in candidatos
        )
        if es_medio or forma in conocidos:
            return cabeza
    return titulo


def limpiar_titulo(titulo: str, medio: str | None, dominio: str | None, reglas: Reglas) -> str:
    """Titular limpio: entidades HTML decodificadas, comillas y espacios normalizados, sin sufijo del medio.

    Si la limpieza dejara el titular vacío se conserva el original (nunca se pierde el texto).
    """
    texto = titulo
    previo = None
    while previo != texto:  # &amp;quot; -> &quot; -> "
        previo, texto = texto, html.unescape(texto)
    texto = unicodedata.normalize("NFC", texto)
    for origen, destino in reglas.ruido.limpieza.comillas.items():
        texto = texto.replace(origen, destino)
    for patron, reemplazo in reglas.reemplazos:
        texto = patron.sub(reemplazo, texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = quitar_sufijo_medio(texto, medio, dominio, reglas)
    return texto.strip() or titulo.strip()


# ------------------------------------------------------------------ ruido


def _coincide(patrones: list[re.Pattern[str]], texto: str) -> bool:
    return any(p.search(texto) for p in patrones)


def _parsear(fecha: str | None, formato: str) -> datetime | None:
    if not fecha:
        return None
    try:
        return datetime.strptime(fecha, formato).replace(tzinfo=UTC)
    except ValueError:
        return None


def fuera_de_ventana(fila: Fila, reglas: Reglas) -> bool:
    """La fecha base (detección; si falta, publicación) cae antes de ``fecha_extraccion - ventana máxima`` (D-74).

    Sin fecha base o sin fecha de extracción no se puede afirmar: no se marca.
    """
    base = _parsear(fila.get("fecha_deteccion"), reglas.formato_fecha) or _parsear(
        fila.get("fecha_publicacion"), reglas.formato_fecha
    )
    referencia = _parsear(fila.get("fecha_extraccion"), reglas.formato_fecha)
    if base is None or referencia is None:
        return False
    return base < referencia - timedelta(days=reglas.dias_ventana)


def es_no_noticia(fila: Fila, titulo_limpio: str, reglas: Reglas) -> bool:
    """Titular sin contenido, promocional o igual al nombre del medio; URL o categoría del RSS que no son notas."""
    plano_titulo = plano(titulo_limpio)
    if _coincide(reglas.titulo_generico, plano_titulo) or _coincide(reglas.titulo_promocional, plano_titulo):
        return True
    if reglas.ruido.no_noticia.titulo_igual_al_medio:
        nombres = _candidatos_medio(fila.get("medio"), fila.get("dominio"))
        if _alnum(titulo_limpio) in nombres:
            return True
    if _coincide(reglas.patrones_url, plano(str(fila.get("url") or ""))):
        return True
    categoria = fila.get("categoria_fuente")
    return bool(categoria) and plano(str(categoria)) in reglas.categorias_rss


def _seccion_tvn(fila: Fila, reglas: Reglas) -> str | None:
    """Primera sección de la ruta de la URL, solo para el dominio de TVN (señal candidata, no decisión)."""
    url = str(fila.get("url_canonica") or fila.get("url") or "")
    partes = urlsplit(url)
    if (partes.hostname or "").lower().removeprefix("www.") != reglas.ruido.panama.dominio_con_seccion:
        return None
    segmentos = [s for s in partes.path.split("/") if s]
    return segmentos[0].lower() if segmentos else None


def _es_seccion_dudosa(fila: Fila, reglas: Reglas) -> bool:
    return (_seccion_tvn(fila, reglas) or "") in reglas.ruido.panama.secciones_dudosas


def _sujeta_al_filtro_de_mencion(fila: Fila, reglas: Reglas) -> bool:
    """El titular debe nombrar a Panamá o algo que lo afecte: GDELT no anclado, o sección dudosa de TVN."""
    cfg = reglas.ruido.panama
    if _es_seccion_dudosa(fila, reglas):
        return True
    origenes = {o.strip() for o in str(fila.get("origen") or "").split(reglas.separador_origen.strip()) if o.strip()}
    if origenes & set(cfg.origenes_exentos) or fila.get("pais_medio") in cfg.paises_medio_exentos:
        return False
    return bool(origenes & set(cfg.origenes_sujetos))


def _fuera_de_temas(texto: str, reglas: Reglas) -> bool:
    grupos = (reglas.deportes, reglas.farandula, reglas.cultura, reglas.politica)
    return any(_coincide(g, texto) for g in grupos)


def clasificar(fila: Fila, titulo_limpio: str, reglas: Reglas) -> tuple[str | None, bool]:
    """``(motivo_ruido, alcance_regional)``. El motivo es el primero que corresponde, en este orden.

    1. ``fuera_de_ventana``; 2. ``no_es_noticia``; 3. falso Panamá (``no_es_panama``); 4. autopromoción de TVN y,
    en una sección dudosa de TVN, deportes/farándula (``fuera_de_temas``: la historia de un panameño en la MLB no
    es "otro país"); 5. sin mención de Panamá en un origen sujeto: ``no_es_panama``, **salvo** que el titular nombre
    la región o un fenómeno regional (D-84: se conserva con ``alcance_regional``); 6. deportes, farándula, cultura
    y política partidista (``fuera_de_temas``).

    Una noticia de otro país que afecta a Panamá (Darién, Canal) nombra algo de ``panama.menciones`` y no es ruido.
    """
    if fuera_de_ventana(fila, reglas):
        return MOTIVO_FUERA_DE_VENTANA, False
    if es_no_noticia(fila, titulo_limpio, reglas):
        return MOTIVO_NO_ES_NOTICIA, False
    texto = plano(titulo_limpio)
    if _coincide(reglas.falsos, texto):
        return MOTIVO_NO_ES_PANAMA, False
    if _coincide(reglas.autopromocion, texto):
        return MOTIVO_FUERA_DE_TEMAS, False
    if _es_seccion_dudosa(fila, reglas) and _fuera_de_temas(texto, reglas):
        return MOTIVO_FUERA_DE_TEMAS, False
    regional = _coincide(reglas.regionales, texto)
    if _sujeta_al_filtro_de_mencion(fila, reglas) and not _coincide(reglas.menciones, texto) and not regional:
        return MOTIVO_NO_ES_PANAMA, False
    if _fuera_de_temas(texto, reglas):
        return MOTIVO_FUERA_DE_TEMAS, False
    return None, regional


def motivo_ruido(fila: Fila, titulo_limpio: str, reglas: Reglas) -> str | None:
    """Solo el motivo de ``clasificar`` (``None`` si no es ruido)."""
    return clasificar(fila, titulo_limpio, reglas)[0]


def sospechoso_inyeccion(fila: Fila, reglas: Reglas) -> bool:
    """Patrones de instrucción en el titular original o en la descripción (D-69). No excluye ni borra."""
    for campo in ("titulo", "descripcion"):
        texto = fila.get(campo)
        if texto and _coincide(reglas.inyeccion, plano(html.unescape(str(texto)))):
            return True
    return False


def evaluar(fila: Fila, reglas: Reglas) -> Resultado:
    """Limpia el titular y decide ruido e inyección de una noticia. No modifica ``fila``."""
    titulo_limpio = limpiar_titulo(str(fila["titulo"]), fila.get("medio"), fila.get("dominio"), reglas)
    motivo, regional = clasificar(fila, titulo_limpio, reglas)
    return Resultado(titulo_limpio, motivo is not None, motivo, sospechoso_inyeccion(fila, reglas), regional)


def limpiar_filas(filas: list[Fila], reglas: Reglas) -> list[Fila]:
    """Devuelve **todas** las filas (mismo número, mismo orden) con las columnas de E1-03b; no borra ninguna."""
    salida = []
    for f in filas:
        r = evaluar(f, reglas)
        salida.append(
            f
            | {
                "titulo_original": f["titulo"],
                "titulo_limpio": r.titulo_limpio,
                "es_ruido": r.es_ruido,
                "motivo_ruido": r.motivo_ruido,
                "sospechoso_inyeccion": r.sospechoso_inyeccion,
                "alcance_regional": r.alcance_regional,
            }
        )
    return salida


# ------------------------------------------------------------------ reporte de calidad


def _proporcion(k: int, n: int, z: float) -> dict[str, Any]:
    """``k`` de ``n`` con intervalo de Wilson al 95 % (``None`` si ``n`` es 0)."""
    ic = intervalo_wilson(k, n, z)
    return {
        "n": k,
        "de": n,
        "proporcion": None if n == 0 else round(k / n, DECIMALES_PRESENTACION),
        "ic95": None if ic is None else [round(ic[0], DECIMALES_PRESENTACION), round(ic[1], DECIMALES_PRESENTACION)],
    }


def construir_reporte(filas: list[Fila], duplicados: list[Fila], z: float) -> dict[str, Any]:
    """Conteo de ruido por motivo (``no_es_panama`` y ``fuera_de_temas`` por separado), con n e IC de Wilson al 95 %.

    Los registros fusionados por URL canónica (E1-03) cuentan como ``duplicado_url``; su base es el total de
    registros recibidos (los que quedaron más los fusionados).
    """
    total = len(filas)
    por_motivo = {m: sum(1 for f in filas if f.get("motivo_ruido") == m) for m in MOTIVOS_MARCADOS}
    ruido = sum(por_motivo.values())
    n_dup = sum(1 for d in duplicados if d["tabla"] == "noticias" and d["motivo"] == MOTIVO_DUPLICADO_URL)
    return {
        "generado_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nota_ic": "IC de Wilson al 95 % descriptivo: el snapshot no es una muestra aleatoria.",
        "noticias_en_base": total,
        "recibidas_antes_de_fusionar_url": total + n_dup,
        "ruido_total": _proporcion(ruido, total, z),
        "utiles_no_ruido": _proporcion(total - ruido, total, z),
        "nota_utiles": (
            "utiles_no_ruido INCLUYE las notas de alcance regional (D-84), que se cuentan aparte en alcance_regional. "
            "Las reglas son palabras clave sobre el titular y NO están medidas: precisión y recall dependen de "
            "eval/etiquetas.csv (E1-06; python -m eval.ruido)."
        ),
        "alcance_regional": _proporcion(sum(1 for f in filas if f.get("alcance_regional")), total, z),
        "por_motivo": {m: _proporcion(k, total, z) for m, k in por_motivo.items()},
        "duplicado_url": _proporcion(n_dup, total + n_dup, z),
        "sospechoso_inyeccion": _proporcion(sum(1 for f in filas if f.get("sospechoso_inyeccion")), total, z),
        "titulos_modificados_por_la_limpieza": _proporcion(
            sum(1 for f in filas if f.get("titulo_limpio") != f.get("titulo_original")), total, z
        ),
    }


def escribir_reporte(ruta: Path, seccion: dict[str, Any]) -> None:
    """Agrega la sección ``ruido`` a ``reporte_calidad.json`` (conserva lo que escribió E1-02)."""
    datos: dict[str, Any] = {}
    if ruta.exists():
        with ruta.open(encoding="utf-8") as f:
            datos = json.load(f)
    datos["ruido"] = seccion
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ------------------------------------------------------------------ DuckDB

COLUMNAS_NUEVAS = ("titulo_original", "titulo_limpio", "es_ruido", "motivo_ruido", "sospechoso_inyeccion", "alcance_regional")


def aplicar_a_base(ruta_base: Path, reglas: Reglas) -> list[Fila]:
    """Llena las columnas de E1-03b en ``noticias`` (UPDATE por ID; no inserta ni borra filas)."""
    con = db.conectar(ruta_base)
    try:
        antes = db.contar_filas(con, "noticias")
        filas = limpiar_filas(db.leer_tabla(con, "noticias", "id_noticia"), reglas)
        con.executemany(
            "UPDATE noticias SET titulo_original = ?, titulo_limpio = ?, es_ruido = ?, motivo_ruido = ?, "
            "sospechoso_inyeccion = ?, alcance_regional = ? WHERE id_noticia = ?",
            [[*(f[c] for c in COLUMNAS_NUEVAS), f["id_noticia"]] for f in filas],
        )
        despues = db.contar_filas(con, "noticias")
        if antes != despues:  # no debería ocurrir: solo hay UPDATE
            raise RuntimeError(f"la limpieza cambió el número de noticias: {antes} -> {despues}")
        return filas
    finally:
        con.close()


def ejecutar(ruta_base: Path, ruta_reporte: Path, reglas: Reglas | None = None) -> dict[str, Any]:
    """Limpia ``noticias`` en la base y escribe la sección ``ruido`` del reporte. Devuelve esa sección."""
    reglas = reglas or Reglas.desde_config()
    filas = aplicar_a_base(ruta_base, reglas)
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        duplicados = db.leer_tabla(con, "duplicados_eliminados")
    finally:
        con.close()
    seccion = construir_reporte(filas, duplicados, cargar_carga().salida.z_intervalo_confianza)
    escribir_reporte(ruta_reporte, seccion)
    return seccion


def main(argv: list[str] | None = None) -> int:
    """CLI: limpia ``data/senales.duckdb`` y agrega el ruido a ``outputs/reporte_calidad.json``."""
    configurar_logging()
    carga = cargar_carga()
    parser = argparse.ArgumentParser(description="E1-03b: limpieza de titulares y filtro de ruido")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--reporte", type=Path, default=RAIZ / "outputs" / carga.salida.reporte)
    args = parser.parse_args(argv)
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero `poetry run python -m src.normalizacion`", args.base)
        return 1
    seccion = ejecutar(args.base, args.reporte)
    logger.info("noticias: %d; ruido: %s; útiles: %s", seccion["noticias_en_base"], seccion["ruido_total"], seccion["utiles_no_ruido"])
    for motivo, p in seccion["por_motivo"].items():
        logger.info("  %s: %d/%d IC95 %s", motivo, p["n"], p["de"], p["ic95"])
    d = seccion["duplicado_url"]
    logger.info("  %s: %d/%d IC95 %s", MOTIVO_DUPLICADO_URL, d["n"], d["de"], d["ic95"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
