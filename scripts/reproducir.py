"""E1-20 · Reproducibilidad de punta a punta (D-65, sección 7 del reto).

    poetry run python -m scripts.reproducir                  # reconstruye todo desde data/raw/ y REGISTRA los hashes en data/manifest.json
    poetry run python -m scripts.reproducir --verificar      # reconstruye todo y COMPARA con el manifest; sale con 1 si algo difiere
    poetry run python -m scripts.reproducir --dos-veces      # reconstruye dos veces y compara las dos corridas entre sí (no toca el manifest)
    poetry run python -m scripts.reproducir --sin-ejecutar   # no corre el pipeline: usa las salidas que hay en disco (diagnóstico)

El pipeline y las salidas que se comparan están en ``config/reproducibilidad.yaml``; la justificación de cada exclusión, en
``docs/reproducibilidad.md``.

**Qué es determinista.** ``processed/`` (reconstruido desde ``raw/`` en una carpeta temporal y comparado), las filas de las tablas de
``data/senales.duckdb``, los informes JSON de los pasos, las fichas (``outputs/reproduccion/fichas.jsonl``) y ``outputs/metricas.json``
(sin sus marcas de reloj). Los flotantes se redondean a ``decimales`` antes del hash.

**Qué no.** El texto del LLM: los borradores salen de la caché (``data/cache_llm/``) y se comparan **como tales** (hash del paquete
que se rearma desde la caché). Nunca se llama al proveedor: sin caché el borrador puede variar y se declara como limitación, no como
coincidencia. Las revisiones humanas (``data/revision.duckdb``) son un insumo: este script no las toca.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from scripts import conversion
from src.configuracion import (
    CARPETA_CONFIG,
    RAIZ,
    ConfigReproducibilidad,
    PasoReproduccion,
    cargar_clasificacion,
    cargar_llm,
    cargar_reglas,
    cargar_reproducibilidad,
)
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

RUTA_MANIFEST = RAIZ / "data" / "manifest.json"
CLAVE_MANIFEST = "reproducibilidad"
ENTRADAS_QUE_NO_SE_COMPARAN = frozenset({"commit", "arbol_con_cambios"})  # cambia en cada ejecución: se registra para saber de dónde salió, no se compara
ESTADO_SIN_CACHE = "sin_cache"
ESTADO_NO_GENERA = "no_genera"
LARGO_HASH_EN_PANTALLA = 12
CARACTERES_DE_ERROR_EN_PANTALLA = 4000  # cola de la salida de un paso que falló
CODIGO_FALLO = 1
CODIGO_OK = 0


class ErrorDeReproduccion(RuntimeError):
    """Un paso del pipeline falló o falta algo que la reproducción necesita."""


@dataclass(frozen=True)
class Diferencia:
    """Una salida cuyo hash no coincide con el registrado."""

    clave: str
    tipo: str  # distinto | faltante | nuevo
    registrado: str | None = None
    actual: str | None = None

    def __str__(self) -> str:
        corto = lambda h: "—" if h is None else str(h)[:LARGO_HASH_EN_PANTALLA]  # noqa: E731
        return f"{self.tipo}: {self.clave} (registrado {corto(self.registrado)}, actual {corto(self.actual)})"


@dataclass
class Contexto:
    """Estado compartido entre los pasos internos y el cálculo final de hashes."""

    raiz: Path
    cfg: ConfigReproducibilidad
    reconstruidos: dict[str, str] = field(default_factory=dict)  # processed/ rehecho desde raw/: «reconstruido:<ruta>» -> sha256
    omitidas: set[str] = field(default_factory=set)               # claves que esta máquina no puede calcular (se declaran, no se ignoran)
    limitaciones: list[str] = field(default_factory=list)
    crudos_ausentes: set[str] | None = None  # lo que ``comprobar_crudos`` halló al empezar
    arbol_con_cambios: bool | None = None    # si el árbol de trabajo tenía cambios sin commitear al empezar (antes de que el pipeline escriba)


# ============================================================================================ hash canónico


def redondear(obj: Any, decimales: int, parsear_json: bool = False) -> Any:
    """Copia de ``obj`` con los flotantes redondeados a ``decimales`` (y ``-0.0`` normalizado a ``0.0``).

    ``parsear_json=True`` abre además los textos que son JSON (columnas como ``puntajes.componentes``) para redondear lo de adentro.
    Los enteros, booleanos y nulos no cambian: un nulo nunca se confunde con cero.
    """
    if isinstance(obj, bool) or obj is None or isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return round(obj, decimales) + 0.0
    if isinstance(obj, Mapping):
        return {k: redondear(v, decimales, parsear_json) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redondear(v, decimales, parsear_json) for v in obj]
    if parsear_json and isinstance(obj, str) and obj[:1] in "{[":
        try:
            return redondear(json.loads(obj), decimales, parsear_json)
        except ValueError:
            return obj
    return obj


def huella_canonica(obj: Any, decimales: int, parsear_json: bool = False) -> str:
    """SHA-256 del JSON canónico de ``obj``: claves ordenadas, UTF-8 y flotantes redondeados."""
    texto = json.dumps(redondear(obj, decimales, parsear_json), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def quitar_rutas(obj: Mapping[str, Any], rutas: Sequence[str]) -> dict[str, Any]:
    """Copia de ``obj`` sin las claves de ``rutas`` (con puntos: ``latencia.consulta``). Una ruta que no existe se ignora."""
    copia = copy.deepcopy(dict(obj))
    for ruta in rutas:
        *padres, ultima = ruta.split(".")
        nodo: Any = copia
        for p in padres:
            nodo = nodo.get(p) if isinstance(nodo, dict) else None
            if nodo is None:
                break
        if isinstance(nodo, dict):
            nodo.pop(ultima, None)
    return copia


def huella_muestra(ruta: Path, columnas_humanas: Sequence[str], decimales: int = 0) -> str:
    """Hash de las columnas de **muestra** de ``revision_sustento.csv`` (id, origen, afirmación, citas, evidencia…), sin las que completa una persona.

    Sin esto, otra muestra con los mismos conteos pasaría inadvertida (X46).
    """
    import csv

    with ruta.open(encoding="utf-8", newline="") as f:
        filas = [{k: v for k, v in fila.items() if k not in columnas_humanas} for fila in csv.DictReader(f)]
    return huella_canonica(filas, decimales)


def huella_de_archivo(ruta: Path) -> str:
    return conversion.sha256_archivo(ruta)


# ============================================================================================ huellas de salidas


def huellas_de_tablas(base: Path, tablas: Sequence[str], decimales: int) -> dict[str, str]:
    """``tabla:<nombre>`` -> hash de las filas de la tabla, ordenadas (un archivo DuckDB no es igual byte a byte entre corridas)."""
    from src import db

    con = db.conectar(base, solo_lectura=True)
    try:
        existentes = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        faltan = [t for t in tablas if t not in existentes]
        if faltan:
            raise ErrorDeReproduccion(f"la base {base.name} no tiene la tabla {', '.join(faltan)}: ¿se ejecutó el pipeline?")
        huellas = {}
        for tabla in tablas:
            cursor = con.execute(f'SELECT * FROM "{tabla}"')
            columnas = [d[0] for d in cursor.description]
            filas = [redondear(dict(zip(columnas, fila, strict=True)), decimales, parsear_json=True) for fila in cursor.fetchall()]
            filas.sort(key=lambda f: json.dumps(f, sort_keys=True, ensure_ascii=False, default=str))
            huellas[f"tabla:{tabla}"] = huella_canonica(filas, decimales)
        return huellas
    finally:
        con.close()


def _leer_json(ruta: Path) -> Any:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ErrorDeReproduccion(f"no se pudo leer {ruta}: {exc}") from exc


def calcular_huellas(ctx: Contexto) -> dict[str, str]:
    """Hash de cada salida determinista que declara ``config/reproducibilidad.yaml``."""
    raiz, salidas, decimales = ctx.raiz, ctx.cfg.salidas, ctx.cfg.decimales
    huellas: dict[str, str] = {}
    for patron in salidas.archivos:
        rutas = sorted(p for p in raiz.glob(patron) if p.is_file())
        if not rutas:
            raise ErrorDeReproduccion(f"no hay archivos para «{patron}»: ¿se ejecutó el pipeline?")
        huellas.update({f"archivo:{p.relative_to(raiz).as_posix()}": huella_de_archivo(p) for p in rutas})
    for local in salidas.archivos_locales:
        ruta = raiz / local.archivo
        if ruta.is_file():
            huellas[f"archivo:{local.archivo}"] = huella_de_archivo(ruta)
            continue
        ctx.omitidas |= {f"archivo:{local.archivo}", *local.afecta}
        ctx.limitaciones.append(
            f"falta {local.archivo}: no se versiona (redistribución restringida, D-72) y se regenera con scripts.extraer; "
            f"no se verificó ni su hash ni lo que depende de él ({', '.join(local.afecta)})"
        )
    for informe, excluidas in salidas.informes.items():
        huellas[f"informe:{informe}"] = huella_canonica(quitar_rutas(_leer_json(raiz / informe), excluidas), decimales)
    huellas.update(huellas_de_tablas(raiz / "data" / "senales.duckdb", salidas.tablas, decimales))
    fichas = [json.loads(linea) for linea in (raiz / salidas.fichas).read_text(encoding="utf-8").splitlines() if linea.strip()]
    huellas["fichas"] = huella_canonica(fichas, decimales)
    muestra = salidas.muestra_sustento
    huellas["muestra_sustento"] = huella_muestra(raiz / muestra.archivo, muestra.columnas_humanas, decimales)
    metricas = quitar_rutas(_leer_json(raiz / salidas.metricas), salidas.excluir_de_metricas)
    huellas["metricas"] = huella_canonica(metricas, decimales)
    huellas.update(ctx.reconstruidos)
    return huellas


# ============================================================================================ borradores (desde la caché)


def borradores_de_cache(raiz: Path, cfg: ConfigReproducibilidad) -> dict[str, dict[str, Any]]:
    """Por grupo: ``estado`` y hash del paquete que se **rearma desde la caché** (``solo_cache=True``: nunca llama al proveedor).

    ``sin_cache`` = el grupo no tiene su borrador completo en ``data/cache_llm/`` (la clave de cada respuesta incluye la ficha, el prompt
    y el modelo); ``no_genera`` = la acción de la ficha no produce borrador.
    """
    from scripts.calentar_cache import estado_de, grupos_por_defecto
    from src.cache import CacheLlm, SinBorrador
    from src.generacion import generar_paquete

    base = raiz / "data" / "senales.duckdb"
    cache = CacheLlm()
    resultado: dict[str, dict[str, Any]] = {}
    logging.getLogger("src.generacion").setLevel(logging.WARNING)  # una línea por intento de generación tapa el resumen
    for grupo in grupos_por_defecto(base, cfg.modalidad):
        try:
            paquete = generar_paquete(grupo, cfg.modalidad, solo_cache=True, base=base, cache=cache)
        except SinBorrador as exc:
            resultado[grupo] = {"estado": ESTADO_NO_GENERA if exc.por_accion else ESTADO_SIN_CACHE, "sha256": None}
            continue
        estado = estado_de(grupo, cfg.modalidad, base, cache)
        etiqueta = "completo" if estado == "completo" else "con_vacios" if estado.startswith("con vacíos") else "parcial"
        resultado[grupo] = {"estado": etiqueta, "sha256": huella_canonica(paquete.model_dump(mode="json"), cfg.decimales)}
    return resultado


# ============================================================================================ versiones y semillas


def semillas_de_config(carpeta: Path) -> dict[str, Any]:
    """Toda clave ``semilla`` de ``config/*.yaml``: ``<archivo>:<ruta con puntos>`` -> valor."""
    encontradas: dict[str, Any] = {}

    def recorrer(archivo: str, nodo: Any, ruta: tuple[str, ...]) -> None:
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if clave == "semilla":
                    encontradas[f"{archivo}:{'.'.join((*ruta, clave))}"] = valor
                else:
                    recorrer(archivo, valor, (*ruta, str(clave)))

    for yaml_ in sorted(carpeta.glob("*.yaml")):
        recorrer(yaml_.name, yaml.safe_load(yaml_.read_text(encoding="utf-8")), ())
    return encontradas


def _commit(raiz: Path) -> str:
    try:
        salida = subprocess.run(["git", "rev-parse", "HEAD"], cwd=raiz, capture_output=True, text=True, check=True)  # noqa: S603, S607
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"
    return salida.stdout.strip()


def arbol_con_cambios(raiz: Path) -> bool:
    """``True`` si el árbol de git tiene cambios sin commitear (el commit registrado no describiría entonces lo que se ejecutó)."""
    try:
        salida = subprocess.run(["git", "status", "--porcelain"], cwd=raiz, capture_output=True, text=True, check=True)  # noqa: S603, S607
    except (OSError, subprocess.CalledProcessError):
        return False
    return bool(salida.stdout.strip())


def registrar_entradas(raiz: Path, cfg: ConfigReproducibilidad, con_cambios: bool | None = None) -> dict[str, Any]:
    """Versiones con las que se corre: modelos de embeddings y LLM, reglas, prompts, semillas, commit y entorno."""
    from src.cache import identidad_de

    clasificacion = cargar_clasificacion()
    reglas = cargar_reglas()
    ruta_reglas = raiz / cfg.registro.archivo_reglas
    llm = cargar_llm().generacion
    identidad = identidad_de()

    def modelo(clave: str) -> dict[str, str]:
        m = clasificacion.modelos[clave]
        return {"clave": clave, "id": m.id, "revision": m.revision}

    return {
        "commit": _commit(raiz),
        "arbol_con_cambios": arbol_con_cambios(raiz) if con_cambios is None else con_cambios,
        "python": platform.python_version(),
        "sistema": platform.system(),
        "embeddings": modelo(reglas.agrupacion.modelo),
        "embeddings_clasificacion": modelo(clasificacion.modelo_activo),
        "llm": {"proveedor": identidad.proveedor, "modelo": identidad.modelo, "temperatura": llm.temperatura, "semilla": llm.semilla},
        "reglas": {"version": reglas.version, "archivo": cfg.registro.archivo_reglas, "sha256": huella_de_archivo(ruta_reglas)},
        "prompts": {p.name: huella_de_archivo(p) for p in sorted((raiz / cfg.registro.carpeta_prompts).glob("*.txt"))},
        "semillas": semillas_de_config(CARPETA_CONFIG),
    }


# ============================================================================================ comparación


def comparar(registrado: Mapping[str, str], actual: Mapping[str, str], omitidas: Collection[str] = ()) -> list[Diferencia]:
    """Cada salida distinta, faltante o nueva. ``omitidas`` son claves que esta máquina no puede calcular (se declaran aparte)."""
    dif = []
    for clave in sorted(set(registrado) | set(actual)):
        if clave in omitidas:   # no calculable en esta máquina o dependiente de un archivo local ausente: se declara aparte
            continue
        if clave not in actual:
            dif.append(Diferencia(clave, "faltante", registrado[clave], None))
        elif clave not in registrado:
            dif.append(Diferencia(clave, "nuevo", None, actual[clave]))
        elif registrado[clave] != actual[clave]:
            dif.append(Diferencia(clave, "distinto", registrado[clave], actual[clave]))
    return dif


def comparar_borradores(registrado: Mapping[str, Mapping[str, Any]], actual: Mapping[str, Mapping[str, Any]]) -> tuple[list[Diferencia], list[str]]:
    """Compara los borradores **como salen de la caché**. Devuelve (diferencias, limitaciones).

    * Registrado completo y ahora sin caché (o al revés): diferencia, porque la caché dejó de servir (cambió la ficha, el prompt o el modelo).
    * Sin caché en los dos lados: no hay nada que comparar; se declara como limitación (sin caché el texto del LLM puede variar).
    * Con caché en los dos lados: el paquete debe tener el mismo hash (la validación es determinista).
    """
    dif: list[Diferencia] = []
    limitaciones: list[str] = []
    for grupo in sorted(set(registrado) | set(actual)):
        clave = f"borrador:{grupo}"
        r, a = registrado.get(grupo), actual.get(grupo)
        if r is None or a is None:
            dif.append(Diferencia(clave, "nuevo" if r is None else "faltante", (r or {}).get("sha256"), (a or {}).get("sha256")))
        elif r["estado"] != a["estado"]:
            dif.append(Diferencia(clave, "distinto", f"{r['estado']}:{r.get('sha256')}", f"{a['estado']}:{a.get('sha256')}"))
        elif r["estado"] == ESTADO_SIN_CACHE:
            limitaciones.append(f"{grupo}: sin borrador en la caché; el texto del LLM no es reproducible y no se compara")
        elif r.get("sha256") != a.get("sha256"):
            dif.append(Diferencia(clave, "distinto", r.get("sha256"), a.get("sha256")))
    return dif, limitaciones


def comparar_entradas(registrado: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    """Avisos de entradas distintas (modelo, reglas, prompts, semillas…): explican por qué podrían cambiar los hashes. No son fallos."""
    avisos = []
    for clave in sorted((set(registrado) | set(actual)) - ENTRADAS_QUE_NO_SE_COMPARAN):
        if registrado.get(clave) != actual.get(clave):
            avisos.append(f"{clave}: registrado {json.dumps(registrado.get(clave), ensure_ascii=False, sort_keys=True)}, "
                          f"actual {json.dumps(actual.get(clave), ensure_ascii=False, sort_keys=True)}")
    return avisos


# ============================================================================================ pasos internos


def comprobar_crudos(raiz: Path) -> set[str]:
    """Compara cada crudo de ``data/raw/`` con el SHA-256 del manifest. Devuelve los ausentes; si alguno presente difiere, lanza el error.

    Se llama **antes** de tocar nada (la caché de embeddings, los pasos): un ``raw/`` alterado no debe dejar el estado a medias.
    """
    data = raiz / "data"
    crudos = _leer_json(data / "manifest.json")["crudos"]
    ausentes = {ruta for ruta in crudos if not (data / ruta).exists()}
    alterados = [ruta for ruta, v in crudos.items() if ruta not in ausentes and huella_de_archivo(data / ruta) != v["sha256"]]
    if alterados:
        raise ErrorDeReproduccion(f"data/raw/ es inmutable y estos crudos no coinciden con el manifest: {', '.join(alterados[:5])}")
    return ausentes


def paso_conversion(ctx: Contexto) -> int:
    """Reconstruye ``processed/`` desde ``raw/`` en una carpeta temporal y guarda el hash de cada archivo (no pisa el ``processed/`` versionado).

    Antes comprueba que ``raw/`` sea el registrado: cada crudo del manifest con su SHA-256. RSS y GDELT no se versionan (redistribución
    restringida, D-72): sin ellos no se puede reconstruir y se declara; el pipeline sigue desde el ``processed/`` versionado.
    """
    data = ctx.raiz / "data"
    ausentes = ctx.crudos_ausentes if ctx.crudos_ausentes is not None else comprobar_crudos(ctx.raiz)
    prefijo = "reconstruido:"
    esperadas = claves_reconstruidas()
    if ausentes:
        ctx.omitidas |= esperadas
        ctx.limitaciones.append(
            f"faltan {len(ausentes)} crudos de data/raw/ (RSS, GDELT y SBP no se versionan, D-72; se recuperan con scripts.extraer): "
            "processed/ no se reconstruyó y se usó el versionado"
        )
        return CODIGO_OK
    with tempfile.TemporaryDirectory(prefix="reproducir_processed_") as tmp:
        destino = Path(tmp)
        conversion.convertir_todo(data / "raw", destino, conversion.cargar_config())
        for nombre in manifest_archivos_processed():
            ctx.reconstruidos[f"{prefijo}data/processed/{nombre}"] = huella_de_archivo(destino / nombre)
    return CODIGO_OK


def claves_reconstruidas() -> set[str]:
    """Las claves ``reconstruido:…`` que produce ``paso_conversion`` (una por archivo de ``processed/``)."""
    return {f"reconstruido:data/processed/{n}" for n in manifest_archivos_processed()}


def manifest_archivos_processed() -> list[str]:
    from scripts.manifest import ARCHIVOS_PROCESSED

    return list(ARCHIVOS_PROCESSED)


def paso_fichas(ctx: Contexto) -> int:
    """Arma la ficha de cada grupo de la bandeja (los mismos que usa el benchmark) y las escribe en ``outputs/reproduccion/fichas.jsonl``."""
    from scripts.calentar_cache import grupos_por_defecto
    from src import db
    from src.ficha import a_linea_jsonl, construir_ficha

    base = ctx.raiz / "data" / "senales.duckdb"
    con = db.conectar(base, solo_lectura=True)
    try:
        lineas = [a_linea_jsonl(construir_ficha(g, ctx.cfg.modalidad, con, emb=None)) for g in grupos_por_defecto(base, ctx.cfg.modalidad)]
    finally:
        con.close()
    destino = ctx.raiz / ctx.cfg.salidas.fichas
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    logger.info("%d fichas en %s", len(lineas), destino.relative_to(ctx.raiz))
    return CODIGO_OK


PASOS_INTERNOS: dict[str, Callable[[Contexto], int]] = {"conversion": paso_conversion, "fichas": paso_fichas}


# ============================================================================================ pipeline


def comando_de(paso: PasoReproduccion) -> list[str]:
    """``python -m <módulo> <argumentos>`` con el mismo intérprete (el de Poetry) que corre este script."""
    assert paso.modulo is not None
    return [sys.executable, "-m", paso.modulo, *paso.argumentos]


def ejecutar_pasos(pasos: Sequence[PasoReproduccion], ejecutor: Callable[[PasoReproduccion], int]) -> None:
    """Corre los pasos en orden y se detiene en el primero que falla (con su nombre)."""
    for paso in pasos:
        inicio = time.monotonic()
        print(f"[{paso.nombre}] ...", flush=True)
        codigo = ejecutor(paso)
        if codigo != CODIGO_OK:
            raise ErrorDeReproduccion(f"el paso {paso.nombre!r} terminó con código {codigo}")
        print(f"[{paso.nombre}] ok ({time.monotonic() - inicio:.1f} s)", flush=True)


def _ejecutor_real(ctx: Contexto) -> Callable[[PasoReproduccion], int]:
    def ejecutar(paso: PasoReproduccion) -> int:
        if paso.tipo == "interno":
            return PASOS_INTERNOS[paso.nombre](ctx)
        proceso = subprocess.run(comando_de(paso), cwd=ctx.raiz, capture_output=True, text=True, check=False)  # noqa: S603
        if proceso.returncode != CODIGO_OK:
            print((proceso.stdout + proceso.stderr)[-CARACTERES_DE_ERROR_EN_PANTALLA:], file=sys.stderr)
        return proceso.returncode

    return ejecutar


def reiniciar_cache_de_embeddings(raiz: Path) -> None:
    """Estado de una máquina nueva: sin vectores guardados (regenerables). Ver ``reiniciar_cache_embeddings`` en la configuración."""
    carpeta = raiz / cargar_clasificacion().carpetas.embeddings
    if carpeta.is_dir():
        shutil.rmtree(carpeta)
        logger.info("caché de embeddings reiniciada: %s", carpeta.relative_to(raiz))


def estado_actual(ctx: Contexto) -> dict[str, Any]:
    """Lo que esta ejecución produjo: entradas, hashes de las salidas deterministas y borradores de la caché."""
    return {
        "ejecucion": registrar_entradas(ctx.raiz, ctx.cfg, ctx.arbol_con_cambios),
        "salidas_deterministas": calcular_huellas(ctx),
        "borradores_cache": borradores_de_cache(ctx.raiz, ctx.cfg),
        "decimales_del_hash": ctx.cfg.decimales,
        "excluido_del_hash": {**{i: x for i, x in ctx.cfg.salidas.informes.items() if x}, ctx.cfg.salidas.metricas: list(ctx.cfg.salidas.excluir_de_metricas)},
        "limitaciones": [
            *ctx.limitaciones,
            "el texto de los borradores del LLM se reproduce solo desde data/cache_llm/; sin caché puede variar",
        ],
    }


def reconstruir(raiz: Path, cfg: ConfigReproducibilidad, ejecutar: bool = True) -> tuple[dict[str, Any], Contexto]:
    """Corre el pipeline (salvo ``ejecutar=False``) y devuelve el estado resultante."""
    ctx = Contexto(raiz, cfg, arbol_con_cambios=arbol_con_cambios(raiz))
    if ejecutar:
        ctx.crudos_ausentes = comprobar_crudos(raiz)   # primero: si falla, no se borró ni se escribió nada
        if cfg.reiniciar_cache_embeddings:
            reiniciar_cache_de_embeddings(raiz)
        ejecutar_pasos(cfg.pasos, _ejecutor_real(ctx))
    else:
        ctx.omitidas |= claves_reconstruidas()
        ctx.limitaciones.append("--sin-ejecutar: no se corrió el pipeline ni se reconstruyó processed/; se compararon las salidas que había en disco")
    return estado_actual(ctx), ctx


# ============================================================================================ manifest


def registrar(ruta: Path, estado: Mapping[str, Any]) -> None:
    """Guarda ``estado`` en ``manifest.json`` bajo ``reproducibilidad``; el resto del manifest queda igual."""
    manifest = _leer_json(ruta)
    manifest[CLAVE_MANIFEST] = dict(estado)
    conversion.escribir_json(ruta, manifest)


def verificar(ruta: Path, actual: Mapping[str, Any], omitidas: Collection[str] = ()) -> int:
    """Compara ``actual`` con lo registrado en el manifest e imprime cada diferencia. 0 si coincide, 1 si no."""
    registro = _leer_json(ruta).get(CLAVE_MANIFEST)
    if not registro:
        print("ERROR: el manifest no tiene el registro de reproducibilidad. Corra primero `poetry run python -m scripts.reproducir`.")
        return CODIGO_FALLO
    dif = comparar(registro["salidas_deterministas"], actual["salidas_deterministas"], omitidas)
    dif_borradores, limitaciones = comparar_borradores(registro.get("borradores_cache", {}), actual.get("borradores_cache", {}))
    dif += dif_borradores
    _imprimir_resultado(dif, [*actual.get("limitaciones", []), *limitaciones],
                        comparar_entradas(registro.get("ejecucion", {}), actual.get("ejecucion", {})), len(actual["salidas_deterministas"]))
    return CODIGO_FALLO if dif else CODIGO_OK


def _imprimir_resultado(dif: Sequence[Diferencia], limitaciones: Sequence[str], avisos: Sequence[str], total: int, contra: str = "el manifest") -> None:
    for d in dif:
        print(f"DIFERENCIA  {d}")
    for aviso in avisos:
        print(f"AVISO       entrada distinta a la registrada, {aviso}")
    for lim in limitaciones:
        print(f"LIMITACIÓN  {lim}")
    if dif:
        print(f"\nNO REPRODUCIBLE: {len(dif)} diferencia(s) en {total} salidas deterministas.")
    else:
        print(f"\nREPRODUCIBLE: {total} salidas deterministas coinciden con {contra}.")


# ============================================================================================ CLI


def principal(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E1-20: reconstruye todo desde data/raw/ y comprueba que el resultado es idéntico")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--verificar", action="store_true", help="compara con data/manifest.json; sale con 1 si algo difiere (no escribe el manifest)")
    modo.add_argument("--dos-veces", action="store_true", help="reconstruye dos veces y compara una corrida con la otra (no escribe el manifest)")
    parser.add_argument("--sin-ejecutar", action="store_true", help="no corre el pipeline: usa las salidas que hay en disco")
    parser.add_argument("--manifest", type=Path, default=RUTA_MANIFEST)
    args = parser.parse_args(argv)
    configurar_logging()
    cfg = cargar_reproducibilidad()
    try:
        estado, ctx = reconstruir(RAIZ, cfg, ejecutar=not args.sin_ejecutar)
        if args.dos_veces:
            primera = estado
            segunda, _ = reconstruir(RAIZ, cfg, ejecutar=not args.sin_ejecutar)
            dif = comparar(primera["salidas_deterministas"], segunda["salidas_deterministas"])
            dif_b, limitaciones = comparar_borradores(primera["borradores_cache"], segunda["borradores_cache"])
            _imprimir_resultado([*dif, *dif_b], limitaciones, [], len(segunda["salidas_deterministas"]), "la primera ejecución")
            return CODIGO_FALLO if dif or dif_b else CODIGO_OK
        if args.verificar:
            return verificar(args.manifest, estado, ctx.omitidas)
        registrar(args.manifest, estado)
    except ErrorDeReproduccion as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CODIGO_FALLO
    print(f"Registradas {len(estado['salidas_deterministas'])} salidas deterministas y {len(estado['borradores_cache'])} borradores de la caché en {args.manifest.name}.")
    for lim in estado["limitaciones"]:
        print(f"LIMITACIÓN  {lim}")
    return CODIGO_OK


if __name__ == "__main__":
    sys.exit(principal())
