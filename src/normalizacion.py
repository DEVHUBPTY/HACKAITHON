"""Normalización de los datos válidos y creación de data/senales.duckdb (E1-03).

Entrada: ``data/processed/validos/`` (lo genera ``python -m src.carga``, D-82). Hace, sin tocar
ningún archivo de entrada:

* fechas a ISO 8601 UTC con ``Z``; ``fecha_publicacion`` y ``fecha_deteccion`` **nunca** se
  sustituyen entre sí (si falta una, queda nula);
* cadenas vacías = nulo, igual en CSV que en JSON; los nulos de ``valor`` no se rellenan (nunca 0);
* URL canónica, deduplicación por URL (cada duplicado queda registrado con su motivo) e IDs
  estables con prefijo (D-63) que no dependen del orden de carga;
* procedencia sin datos personales (D-32): solo ``agencia`` y ``tipo_firma``, nunca el nombre.

Uso: ``poetry run python -m src.normalizacion``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src import db
from src.configuracion import (
    RAIZ,
    ConfigFuentes,
    ConfigNormalizacion,
    cargar_carga,
    cargar_fuentes,
    cargar_normalizacion,
)
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

CARPETA_PROCESADOS = RAIZ / "data" / "processed"
CARPETA_DATOS = RAIZ / "data"

Fila = dict[str, Any]

MOTIVO_DUPLICADO_URL = "duplicado_url"
MOTIVO_DUPLICADO_CLAVE = "duplicado_clave"
MOTIVO_DUPLICADO_ID = "duplicado_id"
MOTIVO_DUPLICADO_DOMINIO = "duplicado_dominio"
MOTIVO_FECHA_NO_NORMALIZABLE = "fecha_no_normalizable"
MOTIVO_NUMERO_NO_NORMALIZABLE = "numero_no_normalizable"
MOTIVO_SIN_URL = "sin_url"
MOTIVO_SIN_CLAVE = "sin_clave"


# ------------------------------------------------------------------ nulos y lectura


def vacio_a_none(valor: Any) -> Any:
    """Cadena vacía o solo espacios -> ``None``; el resto se devuelve igual (con strip si es texto)."""
    if isinstance(valor, str):
        limpio = valor.strip()
        return limpio or None
    return valor


def leer_csv(ruta: Path) -> list[Fila]:
    """Lee un CSV UTF-8 como diccionarios; las celdas vacías son ``None``."""
    with ruta.open(encoding="utf-8", newline="") as f:
        return [{k: vacio_a_none(v) for k, v in fila.items() if k is not None} for fila in csv.DictReader(f)]


def leer_json(ruta: Path) -> Any:
    """Lee un JSON UTF-8."""
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


def _limpiar_json(fila: dict[str, Any]) -> Fila:
    """Aplica ``vacio_a_none`` a cada valor de un registro JSON (mismo criterio que el CSV)."""
    return {k: vacio_a_none(v) for k, v in fila.items()}


class Registro:
    """Acumula lo que la normalización cambió o descartó (tabla ``registro_normalizacion`` y duplicados)."""

    def __init__(self) -> None:
        self.cambios: list[Fila] = []
        self.duplicados: list[Fila] = []

    def cambio(self, tabla: str, clave: str, campo: str, original: Any, motivo: str) -> None:
        logger.warning("%s %s: %s (%s)", tabla, clave, motivo, campo)
        self.cambios.append(
            {"tabla": tabla, "clave": clave, "campo": campo, "valor_original": None if original is None else str(original), "motivo": motivo}
        )

    def duplicado(self, tabla: str, conservado: str, descartado: str, clave: str, motivo: str) -> None:
        self.duplicados.append(
            {"tabla": tabla, "id_conservado": conservado, "id_descartado": descartado, "clave": clave, "motivo": motivo}
        )


# ------------------------------------------------------------------ fechas y números


def normalizar_fecha(valor: Any, config: ConfigNormalizacion) -> tuple[str | None, str | None]:
    """Devuelve ``(fecha ISO UTC con Z, motivo)``. Sin valor -> ``(None, None)``.

    Una fecha con zona horaria se convierte a UTC. Una fecha ilegible o sin zona no se adivina:
    queda nula y el motivo lo dice.
    """
    texto = vacio_a_none(valor)
    if texto is None:
        return None, None
    try:
        momento = datetime.fromisoformat(str(texto))
    except ValueError:
        return None, "fecha_ilegible"
    if momento.tzinfo is None:
        return None, "fecha_sin_zona_horaria"
    return momento.astimezone(UTC).strftime(config.fechas.formato_salida), None


def _fecha(
    fila: Fila, campo: str, tabla: str, clave: str, config: ConfigNormalizacion, registro: Registro
) -> str | None:
    iso, problema = normalizar_fecha(fila.get(campo), config)
    if problema:
        registro.cambio(tabla, clave, campo, fila.get(campo), f"{MOTIVO_FECHA_NO_NORMALIZABLE}:{problema}")
    return iso


def _numero(fila: Fila, campo: str, tabla: str, clave: str, registro: Registro) -> float | None:
    """Número de un campo; nulo si falta. Un texto no numérico queda nulo y se registra (nunca 0)."""
    valor = fila.get(campo)
    if valor is None:
        return None
    if isinstance(valor, bool):
        registro.cambio(tabla, clave, campo, valor, MOTIVO_NUMERO_NO_NORMALIZABLE)
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        registro.cambio(tabla, clave, campo, valor, MOTIVO_NUMERO_NO_NORMALIZABLE)
        return None


# ------------------------------------------------------------------ URL, dominio e IDs (D-63)


def url_canonica(url: str, fuentes: ConfigFuentes) -> str:
    """URL canónica: esquema fijo, dominio en minúsculas sin ``www.``, sin ``utm_*``/rastreo, sin barra final ni fragmento."""
    reglas = fuentes.url_canonica
    partes = urlsplit(url.strip())
    host = (partes.hostname or "").lower()
    if reglas.quitar_prefijo_www and host.startswith("www."):
        host = host[4:]
    if partes.port and partes.port not in (80, 443):
        host = f"{host}:{partes.port}"

    def es_rastreo(nombre: str) -> bool:
        n = nombre.lower()
        return any(n == q or (q.endswith("*") and n.startswith(q[:-1])) for q in reglas.parametros_a_quitar)

    consulta = sorted((k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True) if not es_rastreo(k))
    ruta = partes.path.rstrip("/") or "/"
    return urlunsplit((reglas.esquema, host, ruta, urlencode(consulta), ""))


def dominio_de(url_canonica_: str) -> str:
    """Host de una URL canónica (ya sin ``www.``)."""
    return (urlsplit(url_canonica_).hostname or "").lower()


def id_noticia(url_canonica_: str, config: ConfigNormalizacion) -> str:
    """``NOT-`` + primeros caracteres del SHA-1 de la URL canónica (D-63)."""
    digest = hashlib.sha1(url_canonica_.encode("utf-8")).hexdigest()
    return f"{config.noticias.prefijo_id}{digest[: config.noticias.largo_hash_id]}"


def id_indicador(pais: str, indicador: str, anio: int, config: ConfigNormalizacion) -> str:
    """``IND-<país>-<indicador>-<año>`` (D-63)."""
    return f"{config.indicadores.prefijo_id}{pais}-{indicador}-{anio}"


def id_sismo(id_usgs: str, config: ConfigNormalizacion) -> str:
    """``SIS-<id USGS>``; si el id ya trae el prefijo no se duplica (D-63)."""
    prefijo = config.sismos.prefijo_id
    return id_usgs if id_usgs.startswith(prefijo) else f"{prefijo}{id_usgs}"


# ------------------------------------------------------------------ procedencia sin datos personales (D-32)


def derivar_firma(texto: Any, medio: str | None, config: ConfigNormalizacion) -> tuple[str | None, str]:
    """De un texto de autor/firma deriva ``(agencia, tipo_firma)``. **El texto no se conserva.**

    Agencia de la lista del YAML (en cualquier parte del texto, sin distinguir mayúsculas) -> ``agencia``;
    redacción genérica o el propio medio -> ``medio``; cualquier otro texto -> ``persona`` (sin nombre);
    sin texto -> ``sin firma``.
    """
    tipos = config.firma.tipos
    limpio = vacio_a_none(texto)
    if limpio is None:
        return None, tipos.sin_firma
    plano = str(limpio).casefold()
    palabras = {p.strip(".,;:()/-") for p in plano.replace("/", " ").split()}
    for agencia in config.firma.agencias:
        nombre = agencia.casefold()
        encontrada = nombre in plano if " " in nombre else nombre in palabras
        if encontrada:
            return agencia, tipos.agencia
    redaccion = {r.casefold() for r in config.firma.redaccion}
    if plano in redaccion or (medio is not None and plano == medio.casefold()):
        return None, tipos.medio
    return None, tipos.persona


# ------------------------------------------------------------------ fusión de duplicados


def _fusionar(grupo: Sequence[Fila], columnas: Iterable[str]) -> Fila:
    """Una fila por columna con el primer valor no nulo del grupo (ya ordenado de forma determinista)."""
    return {c: next((f[c] for f in grupo if f.get(c) is not None), None) for c in columnas}


def _unir(valores: Iterable[Any], separador: str, orden: list[str] | None = None) -> str | None:
    """Une los componentes únicos de campos con separador; los de ``orden`` van primero, en ese orden."""
    partes = {p.strip() for v in valores if v for p in str(v).split(separador.strip()) if p.strip()}
    if not partes:
        return None
    primeros = [o for o in (orden or []) if o in partes]
    return separador.join(primeros + sorted(partes - set(primeros)))


def _clave_orden(fila: Fila, campos: Sequence[str]) -> tuple[str, ...]:
    return tuple("" if fila.get(c) is None else str(fila[c]) for c in campos)


# ------------------------------------------------------------------ fuentes


def normalizar_fuentes(registros: list[dict[str, Any]], registro: Registro) -> list[Fila]:
    """``fuentes.json``: dominio en minúsculas sin ``www.``, vacíos como nulos, un registro por dominio."""
    filas = []
    for r in registros:
        f = _limpiar_json(r)
        dominio = f.get("dominio")
        if dominio is None:
            registro.cambio("fuentes", "", "dominio", None, MOTIVO_SIN_CLAVE)
            continue
        dominio = str(dominio).lower()
        f["dominio"] = dominio[4:] if dominio.startswith("www.") else dominio
        filas.append(f)
    filas.sort(key=lambda f: _clave_orden(f, ["dominio", "nombre_legible", "origen", "pais", "condiciones"]))
    grupos: dict[str, list[Fila]] = {}
    for f in filas:
        grupos.setdefault(f["dominio"], []).append(f)
    salida = []
    for dominio in sorted(grupos):
        grupo = grupos[dominio]
        for _ in grupo[1:]:
            registro.duplicado("fuentes", dominio, dominio, dominio, MOTIVO_DUPLICADO_DOMINIO)
        salida.append(_fusionar(grupo, ["dominio", "nombre_legible", "pais", "origen", "condiciones"]))
    return salida


# ------------------------------------------------------------------ noticias

_CAMPOS_NOTICIAS_ENTRADA = [
    "id_noticia", "titulo", "url", "medio", "idioma", "fecha_publicacion", "fecha_deteccion", "fecha_extraccion",
    "tema", "origen", "alcance_texto", "descripcion", "categoria_fuente", "dominio", "pais_medio", "url_movil",
]  # fmt: skip


def _es_sintetico(id_: str | None, config: ConfigNormalizacion) -> bool:
    return bool(id_) and any(str(id_).startswith(p) for p in config.noticias.prefijos_sinteticos)


def _es_recirculada(publicacion: str | None, deteccion: str | None, config: ConfigNormalizacion) -> bool | None:
    """Detectada mucho después de publicada. Nula si falta una de las dos fechas (no se sustituyen)."""
    if publicacion is None or deteccion is None:
        return None
    formato = config.fechas.formato_salida
    dias = (datetime.strptime(deteccion, formato) - datetime.strptime(publicacion, formato)).days
    return dias > config.noticias.dias_para_recirculada


def normalizar_noticias(
    filas: list[Fila],
    fuentes_tabla: list[Fila],
    config: ConfigNormalizacion,
    fuentes_cfg: ConfigFuentes,
    registro: Registro,
) -> list[Fila]:
    """Normaliza noticias: fechas UTC, URL canónica, deduplicación por URL, IDs, medio y procedencia.

    El resultado no depende del orden de ``filas``: cada grupo de duplicados se ordena por contenido
    antes de fusionarse y la salida va ordenada por ``id_noticia``.
    """
    por_dominio = {f["dominio"]: f for f in fuentes_tabla}
    separador_tema = config.noticias.separador_tema
    candidatas: list[Fila] = []
    for original in filas:
        f = {k: vacio_a_none(v) for k, v in original.items()}
        if f.get("url") is None:
            registro.cambio("noticias", str(f.get("id_noticia")), "url", None, MOTIVO_SIN_URL)
            continue
        canonica = url_canonica(str(f["url"]), fuentes_cfg)
        ref = str(f.get("id_noticia") or canonica)
        for campo in ("fecha_publicacion", "fecha_deteccion", "fecha_extraccion"):
            f[campo] = _fecha(f, campo, "noticias", ref, config, registro)
        texto_firma = next((f[c] for c in config.noticias.campos_firma if f.get(c) is not None), None)
        f["agencia"], f["tipo_firma"] = derivar_firma(texto_firma, f.get("medio"), config)
        f["url_canonica"] = canonica
        candidatas.append(f)

    grupos: dict[str, list[Fila]] = {}
    for f in candidatas:
        grupos.setdefault(f["url_canonica"], []).append(f)

    orden = ["id_noticia", "url", "titulo", "medio", "fecha_publicacion", "fecha_deteccion", "tema", "origen"]
    salida: list[Fila] = []
    for canonica, grupo in grupos.items():
        grupo.sort(key=lambda f: _clave_orden(f, orden))
        columnas = [*_CAMPOS_NOTICIAS_ENTRADA, "url_canonica"]
        fila = _fusionar(grupo, columnas)
        sinteticos = [f["id_noticia"] for f in grupo if _es_sintetico(f.get("id_noticia"), config)]
        fila["id_noticia"] = sinteticos[0] if sinteticos else id_noticia(canonica, config)
        for descartada in grupo[1:]:
            registro.duplicado(
                "noticias", fila["id_noticia"], str(descartada.get("id_noticia") or descartada["url"]), canonica, MOTIVO_DUPLICADO_URL
            )
        fila["tema"] = _unir((f.get("tema") for f in grupo), separador_tema)
        fila["origen"] = _unir((f.get("origen") for f in grupo), config.noticias.separador_origen, config.noticias.orden_origen)
        extracciones = [f["fecha_extraccion"] for f in grupo if f.get("fecha_extraccion")]
        fila["fecha_extraccion"] = min(extracciones) if extracciones else None
        firmada = next((f for f in grupo if f["tipo_firma"] != config.firma.tipos.sin_firma), grupo[0])
        fila["agencia"], fila["tipo_firma"] = firmada["agencia"], firmada["tipo_firma"]
        dominio = dominio_de(canonica)
        fuente = por_dominio.get(dominio)
        fila["dominio"] = dominio
        if fuente is not None:
            fila["medio"] = fuente["nombre_legible"]
            fila["pais_medio"] = fuente.get("pais")
        fila["es_recirculada"] = _es_recirculada(fila["fecha_publicacion"], fila["fecha_deteccion"], config)
        salida.append(fila)
    salida.sort(key=lambda f: f["id_noticia"])
    return salida


# ------------------------------------------------------------------ indicadores y sismos


def normalizar_indicadores(filas: list[Fila], config: ConfigNormalizacion, registro: Registro) -> list[Fila]:
    """Indicadores: ID ``IND-``, ``valor`` nulo si falta (nunca 0), unidades originales."""
    candidatas: list[Fila] = []
    for original in filas:
        f = {k: vacio_a_none(v) for k, v in original.items()}
        pais, indicador = f.get("pais_iso3"), f.get("indicador_id")
        try:
            anio = int(str(f.get("anio")))
        except ValueError:
            registro.cambio("indicadores", f"{pais}-{indicador}", "anio", f.get("anio"), MOTIVO_SIN_CLAVE)
            continue
        if pais is None or indicador is None:
            registro.cambio("indicadores", f"{pais}-{indicador}-{anio}", "clave", None, MOTIVO_SIN_CLAVE)
            continue
        clave = id_indicador(str(pais), str(indicador), anio, config)
        candidatas.append(
            {
                "id_indicador": clave,
                "pais_iso3": pais,
                "indicador_id": indicador,
                "anio": anio,
                "valor": _numero(f, "valor", "indicadores", clave, registro),
                "unidad": f.get("unidad"),
                "fuente_url": f.get("fuente_url"),
                "fecha_extraccion": _fecha(f, "fecha_extraccion", "indicadores", clave, config, registro),
                "licencia": f.get("licencia"),
            }
        )
    return _deduplicar(candidatas, "id_indicador", "indicadores", MOTIVO_DUPLICADO_CLAVE, registro)


def normalizar_sismos(propiedades: list[dict[str, Any]], config: ConfigNormalizacion, registro: Registro) -> list[Fila]:
    """Sismos: ID ``SIS-``, fechas UTC, ``place`` original sin tocar."""
    candidatas: list[Fila] = []
    for original in propiedades:
        f = _limpiar_json(original)
        if f.get("id") is None:
            registro.cambio("sismos", "", "id", None, MOTIVO_SIN_CLAVE)
            continue
        clave = id_sismo(str(f["id"]), config)
        candidatas.append(
            {
                "id": clave,
                "magnitude": _numero(f, "magnitude", "sismos", clave, registro),
                "time": _fecha(f, "time", "sismos", clave, config, registro),
                "updated": _fecha(f, "updated", "sismos", clave, config, registro),
                "longitude": _numero(f, "longitude", "sismos", clave, registro),
                "latitude": _numero(f, "latitude", "sismos", clave, registro),
                "depth": _numero(f, "depth", "sismos", clave, registro),
                "place": f.get("place"),
                "status": f.get("status"),
                "url": f.get("url"),
            }
        )
    return _deduplicar(candidatas, "id", "sismos", MOTIVO_DUPLICADO_ID, registro)


def _deduplicar(filas: list[Fila], clave: str, tabla: str, motivo: str, registro: Registro) -> list[Fila]:
    """Una fila por clave, fusionando de forma determinista; cada duplicado queda registrado."""
    columnas = db.columnas(tabla)
    filas = sorted(filas, key=lambda f: _clave_orden(f, columnas))
    grupos: dict[str, list[Fila]] = {}
    for f in filas:
        grupos.setdefault(f[clave], []).append(f)
    salida = []
    for k in sorted(grupos):
        grupo = grupos[k]
        for _ in grupo[1:]:
            registro.duplicado(tabla, k, k, k, motivo)
        salida.append(_fusionar(grupo, columnas))
    return salida


# ------------------------------------------------------------------ orquestación


def _propiedades_geojson(ruta: Path) -> list[dict[str, Any]]:
    datos = leer_json(ruta)
    return [dict(f.get("properties") or {}) for f in datos.get("features", [])]


def normalizar_carpeta(entrada: Path, config: ConfigNormalizacion | None = None) -> dict[str, list[Fila]]:
    """Lee los cuatro archivos de ``entrada`` y devuelve las filas normalizadas de cada tabla."""
    config = config or cargar_normalizacion()
    fuentes_cfg = cargar_fuentes()
    nombres = cargar_carga().archivos
    registro = Registro()
    fuentes = normalizar_fuentes(leer_json(entrada / nombres.fuentes), registro)
    noticias = normalizar_noticias(leer_csv(entrada / nombres.noticias), fuentes, config, fuentes_cfg, registro)
    indicadores = normalizar_indicadores(leer_csv(entrada / nombres.indicadores), config, registro)
    sismos = normalizar_sismos(_propiedades_geojson(entrada / nombres.eventos), config, registro)
    duplicados = sorted(registro.duplicados, key=lambda d: (d["tabla"], d["id_conservado"], d["id_descartado"]))
    cambios = sorted(registro.cambios, key=lambda c: (c["tabla"], c["clave"], c["campo"], c["motivo"]))
    return {
        "noticias": noticias,
        "indicadores": indicadores,
        "sismos": sismos,
        "fuentes": fuentes,
        "duplicados_eliminados": duplicados,
        "registro_normalizacion": cambios,
    }


def ejecutar(entrada: Path, destino: Path, config: ConfigNormalizacion | None = None) -> dict[str, int]:
    """Normaliza ``entrada`` y escribe la base en ``destino``. Devuelve el conteo de filas por tabla."""
    tablas = normalizar_carpeta(entrada, config)
    return db.guardar_todo(destino, tablas)


def main(argv: list[str] | None = None) -> int:
    """CLI: normaliza ``data/processed/validos/`` y crea ``data/senales.duckdb``."""
    configurar_logging()
    config = cargar_normalizacion()
    parser = argparse.ArgumentParser(description="E1-03: normalización y almacenamiento en DuckDB")
    parser.add_argument("--entrada", type=Path, default=CARPETA_PROCESADOS / config.entrada.carpeta_validos)
    parser.add_argument("--salida", type=Path, default=CARPETA_DATOS / config.salida.base_de_datos)
    args = parser.parse_args(argv)
    if not args.entrada.is_dir():
        logger.error("No existe %s: ejecute primero `poetry run python -m src.carga` (D-82)", args.entrada)
        return 1
    conteos = ejecutar(args.entrada, args.salida, config)
    for tabla, n in conteos.items():
        logger.info("%s: %d filas", tabla, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
