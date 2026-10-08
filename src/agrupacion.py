"""Agrupación de titulares por evento (GRP-) a partir de similitud y ventanas de tiempo · E1-08, CU-03, T02.

Cada titular que no es ruido queda en **exactamente un grupo**: ninguna fuente se pierde, y los duplicados y las
republicaciones se cuentan como titulares de un grupo, no como eventos distintos.

* **Similitud:** ``sklearn.cluster.AgglomerativeClustering(metric='cosine', linkage='average', distance_threshold=...)``
  sobre los embeddings locales del titular (``src/embeddings.py``). ``distance_threshold = 1 - umbral_similitud``: se unen
  dos conjuntos mientras su similitud coseno **promedio** sea al menos el umbral (``reglas_v1.3.yaml``, calibrado con
  ``eval/etiquetas.csv``: ``python -m eval.agrupacion``, D-16). El grupo cruza idiomas si el modelo es multilingüe.
* **Ventana temporal:** ``agrupacion.ventana_dias``. Después de agrupar por similitud se parte todo grupo cuyos titulares
  se separan más que la ventana (voraz por fecha: cada subgrupo empieza en su titular más antiguo y no pasa de la
  ventana), de modo que **dos titulares a más de la ventana nunca comparten grupo**. La fecha es ``fecha_publicacion`` y,
  si falta, ``fecha_deteccion`` (``campos_fecha``); un titular sin ninguna fecha no se puede separar y queda con su grupo.
* **ID:** ``GRP-`` + hash de los ``NOT-`` ordenados (D-63): mismo snapshot y mismas reglas dan los mismos grupos con los
  mismos IDs. Un grupo que cambia de miembros cambia de ID.
* **Procedencias** (``src/procedencias.py``): ``n_procedencias`` es una **estimación** (``estimado = true``).

Uso: ``poetry run python -m src.agrupacion`` (después de ``src.normalizacion``, ``src.limpieza`` y ``src.clasificacion``).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from src import db
from src.clasificacion import escribir_seccion, proporcion, texto_de_entrada
from src.configuracion import (
    RAIZ,
    Agrupacion,
    ConfigClasificacion,
    ConfigProcedencias,
    ReglasV13,
    SubtemaVinculo,
    cargar_carga,
    cargar_clasificacion,
    cargar_normalizacion,
    cargar_procedencias,
    cargar_reglas,
    cargar_temas,
    cargar_vinculos,
)
from src.embeddings import Embeddings, crear, fijar_semilla
from src.procedencias import Procedencia, dominio_normalizado, estimar_procedencias
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

SEPARADOR_LISTA = ","      # listas dentro de una columna de texto (ids_noticia, idiomas, medios)
SEGUNDOS_POR_DIA = 86_400
PREFIJO_CAMPO_FECHA = "fecha_"  # ``fecha_publicacion`` -> ``publicacion``
GRUPOS_EN_REPORTE = 5       # cuántos grupos más grandes se listan en el reporte

class SinCalibrar(RuntimeError):
    """``umbral_similitud`` es ``null``: ``python -m eval.agrupacion`` lo calibra con las etiquetas humanas."""


# ------------------------------------------------------------------ fechas e IDs


def id_de_grupo(ids_noticia: Sequence[str], cfg: Agrupacion) -> str:
    """Prefijo + SHA-1 de los ``NOT-`` ordenados (prefijo, largo y separador de ``agrupacion`` en ``reglas_v1.3.yaml``, D-63)."""
    resumen = hashlib.sha1(cfg.separador_ids.join(sorted(ids_noticia)).encode()).hexdigest()
    return f"{cfg.prefijo_id}{resumen[: cfg.largo_hash_id]}"


def fecha_de(fila: Mapping[str, Any], campos: Sequence[str]) -> datetime | None:
    """Primera fecha ISO 8601 UTC presente según ``campos`` (publicación antes que detección); ``None`` si no hay ninguna."""
    for campo in campos:
        valor = fila.get(campo)
        if valor:
            fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
            return fecha if fecha.tzinfo else fecha.replace(tzinfo=UTC)  # el contrato es UTC
    return None


def fecha_iso_de(fila: Mapping[str, Any], campos: Sequence[str]) -> str | None:
    """El texto ISO original del campo del que sale ``fecha_de`` (no se reformatea ni se convierte)."""
    return next((str(fila[c]) for c in campos if fila.get(c)), None)


def origen_de_fecha(fila: Mapping[str, Any], campos: Sequence[str]) -> str | None:
    """De qué campo sale la fecha: ``publicacion`` o ``deteccion`` (el nombre del campo sin ``fecha_``); ``None`` sin fecha."""
    campo = next((c for c in campos if fila.get(c)), None)
    return None if campo is None else campo.removeprefix(PREFIJO_CAMPO_FECHA)


# ------------------------------------------------------------------ agrupación


def _agrupar_por_similitud(vectores: np.ndarray, umbral: float) -> list[list[int]]:
    """Clústeres aglomerativos (coseno, enlace promedio) cortados en ``1 - umbral``; ordenados por su menor índice."""
    n = vectores.shape[0]
    if n == 0:
        return []
    if n == 1:
        return [[0]]
    modelo = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=1.0 - umbral,
    )
    etiquetas = modelo.fit_predict(vectores)
    grupos: dict[int, list[int]] = {}
    for i, etiqueta in enumerate(etiquetas):
        grupos.setdefault(int(etiqueta), []).append(i)
    return sorted(grupos.values(), key=lambda g: g[0])


def _partir_por_ventana(
    indices: list[int], fechas: Sequence[datetime | None], ids: Sequence[str], ventana_dias: int
) -> list[list[int]]:
    """Parte un grupo para que ningún par supere ``ventana_dias``; los titulares sin fecha quedan en el primer subgrupo."""
    con_fecha = sorted((i for i in indices if fechas[i] is not None), key=lambda i: (fechas[i], ids[i]))
    sin_fecha = [i for i in indices if fechas[i] is None]
    subgrupos: list[list[int]] = []
    inicio: datetime | None = None
    for i in con_fecha:
        fecha = fechas[i]
        assert fecha is not None
        if inicio is None or (fecha - inicio).total_seconds() > ventana_dias * SEGUNDOS_POR_DIA:
            subgrupos.append([])
            inicio = fecha
        subgrupos[-1].append(i)
    if not subgrupos:
        return [sorted(sin_fecha)]
    subgrupos[0].extend(sin_fecha)
    return [sorted(g) for g in subgrupos]


def agrupar_indices(
    vectores: np.ndarray,
    fechas: Sequence[datetime | None],
    ids: Sequence[str],
    umbral_similitud: float,
    ventana_dias: int,
) -> list[list[int]]:
    """Grupos de posiciones (cada posición en exactamente un grupo) por similitud y ventana temporal.

    ``vectores`` deben estar normalizados (el coseno es el producto punto). El resultado no depende del orden de las
    filas salvo por el de los grupos, que se ordenan por su menor ID de noticia.
    """
    if not (vectores.shape[0] == len(fechas) == len(ids)):
        raise ValueError("vectores, fechas e ids deben tener la misma longitud")
    partidos = [
        sub
        for grupo in _agrupar_por_similitud(vectores, umbral_similitud)
        for sub in _partir_por_ventana(grupo, fechas, ids, ventana_dias)
    ]
    return sorted((sorted(g, key=lambda i: ids[i]) for g in partidos), key=lambda g: ids[g[0]])


# ------------------------------------------------------------------ grupos completos


@dataclass(frozen=True)
class Grupo:
    """Un evento: sus titulares, su titular central y sus procedencias independientes (estimadas)."""

    id_grupo: str
    ids_noticia: tuple[str, ...]            # ordenados
    id_noticia_central: str
    titular_central: str
    n_medios: int
    procedencias: tuple[Procedencia, ...]
    fecha_inicio: str | None
    fecha_inicio_origen: str | None         # ``publicacion`` o ``deteccion``: nunca se mezclan sin decirlo
    fecha_fin: str | None
    fecha_fin_origen: str | None
    idiomas: tuple[str, ...]
    tema_clasificado: str | None
    tema_origen_clasificador: str | None = None   # D-122: tema del clasificador si un subtema nombrado lo corrigió
    criterio_tema: str | None = None              # D-122: ``subtema_nombrado`` si se corrigió

    @property
    def n_titulares(self) -> int:
        return len(self.ids_noticia)

    @property
    def n_procedencias(self) -> int:
        return len(self.procedencias)


def _central(indices: list[int], vectores: np.ndarray, fechas: Sequence[datetime | None], ids: Sequence[str]) -> int:
    """Titular más parecido al resto (similitud media con los demás); empate: el más antiguo y luego el menor ID."""
    if len(indices) == 1:
        return indices[0]
    sub = vectores[indices]
    medias = (sub @ sub.T).sum(axis=1)
    mejor = max(medias)
    candidatos = [i for i, m in zip(indices, medias, strict=True) if m >= mejor - np.finfo(np.float32).eps * len(indices)]
    sin_fecha = datetime.max.replace(tzinfo=UTC)
    return min(candidatos, key=lambda i: (fechas[i] or sin_fecha, ids[i]))


def _tema_dominante(filas: Sequence[Mapping[str, Any]]) -> str | None:
    temas = Counter(f["tema_clasificado"] for f in filas if f.get("tema_clasificado"))
    if not temas:
        return None
    mayor = max(temas.values())
    return sorted(t for t, c in temas.items() if c == mayor)[0]


def construir_grupos(
    filas: Sequence[Mapping[str, Any]],
    vectores: np.ndarray,
    reglas: ReglasV13,
    proc: ConfigProcedencias,
    cfg_subtema: SubtemaVinculo | None = None,
    subtemas_por_tema: Mapping[str, Sequence[str]] | None = None,
) -> list[Grupo]:
    """Agrupa ``filas`` (titulares que no son ruido, con ``vectores`` en el mismo orden) y estima sus procedencias.

    Con ``cfg_subtema`` y ``subtemas_por_tema`` aplica D-122: el subtema nombrado corrige el tema del grupo (aquí, un único punto
    que ven contexto, puntaje, ficha y la interfaz). Falla con ``SinCalibrar`` si ``umbral_similitud`` es ``null``. Verifica que cada titular quede en un solo grupo.
    """
    umbral = reglas.agrupacion.umbral_similitud
    if umbral is None:
        raise SinCalibrar("agrupacion.umbral_similitud es null: ejecute `poetry run python -m eval.agrupacion` y fíjelo")
    ids = [str(f["id_noticia"]) for f in filas]
    if len(set(ids)) != len(ids):
        raise ValueError("id_noticia repetido en la entrada")
    campos = reglas.agrupacion.campos_fecha
    fechas = [fecha_de(f, campos) for f in filas]
    iso = [fecha_iso_de(f, campos) for f in filas]
    origen = [origen_de_fecha(f, campos) for f in filas]
    from src.contexto import tema_por_subtema_nombrado   # import tardío: contexto → contexto_sismos → agrupacion

    grupos: list[Grupo] = []
    for indices in agrupar_indices(vectores, fechas, ids, umbral, reglas.agrupacion.ventana_dias):
        miembros = [filas[i] for i in indices]
        fechadas = [i for i in indices if fechas[i] is not None]
        primera = min(fechadas, key=lambda i: fechas[i]) if fechadas else -1
        ultima = max(fechadas, key=lambda i: fechas[i]) if fechadas else -1
        central = _central(indices, vectores, fechas, ids)
        tema = _tema_dominante(miembros)
        tema_origen = criterio_tema = None
        if cfg_subtema is not None and subtemas_por_tema is not None:
            corregido = tema_por_subtema_nombrado([str(f["titulo_limpio"]) for f in miembros], tema, subtemas_por_tema, cfg_subtema)
            if corregido is not None:
                tema_origen, criterio_tema, tema = tema, cfg_subtema.correccion_tema.criterio, corregido
        procedencias = estimar_procedencias(
            miembros, vectores[indices], proc, reglas, [iso[i] for i in indices]
        )
        grupos.append(
            Grupo(
                id_grupo=id_de_grupo([ids[i] for i in indices], reglas.agrupacion),
                ids_noticia=tuple(ids[i] for i in indices),
                id_noticia_central=ids[central],
                titular_central=str(filas[central]["titulo_limpio"]),
                n_medios=len({dominio_normalizado(f) for f in miembros}),
                procedencias=tuple(procedencias),
                fecha_inicio=iso[primera] if fechadas else None,
                fecha_inicio_origen=origen[primera] if fechadas else None,
                fecha_fin=iso[ultima] if fechadas else None,
                fecha_fin_origen=origen[ultima] if fechadas else None,
                idiomas=tuple(sorted({str(f["idioma"]) for f in miembros if f.get("idioma")})),
                tema_clasificado=tema,
                tema_origen_clasificador=tema_origen,
                criterio_tema=criterio_tema,
            )
        )
    asignados = [i for g in grupos for i in g.ids_noticia]
    if sorted(asignados) != sorted(ids) or len({g.id_grupo for g in grupos}) != len(grupos):
        raise RuntimeError("la agrupación perdió o duplicó una noticia, o repitió un id_grupo")
    return grupos


# ------------------------------------------------------------------ DuckDB


def _filas_de_grupos(grupos: Sequence[Grupo], estimado: bool) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    """Filas de ``grupos``, de ``procedencias`` y pares (procedencia, id_noticia) para actualizar ``noticias``."""
    filas_grupos, filas_proc, asignaciones = [], [], []
    for g in grupos:
        filas_grupos.append(
            [
                g.id_grupo, g.titular_central, g.id_noticia_central, g.n_titulares, g.n_medios, g.n_procedencias,
                g.fecha_inicio, g.fecha_inicio_origen, g.fecha_fin, g.fecha_fin_origen, SEPARADOR_LISTA.join(g.idiomas), g.tema_clasificado,
                SEPARADOR_LISTA.join(g.ids_noticia), estimado,
                g.tema_origen_clasificador, g.criterio_tema,
            ]
        )
        for orden, p in enumerate(g.procedencias, start=1):
            filas_proc.append(
                [g.id_grupo, orden, p.etiqueta, SEPARADOR_LISTA.join(p.reglas) or None, len(p.ids_noticia),
                 SEPARADOR_LISTA.join(p.medios), SEPARADOR_LISTA.join(p.ids_noticia)]
            )
            asignaciones.extend([g.id_grupo, p.etiqueta, i] for i in p.ids_noticia)
    return filas_grupos, filas_proc, asignaciones


def _insertar(tabla: str) -> str:
    """INSERT con columnas por nombre: una base creada antes de una columna nueva la tiene al final (``asegurar_esquema``)."""
    cols = db.columnas(tabla)
    return f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"


def codificar_titulares(filas: Sequence[Mapping[str, Any]], emb: Embeddings, usar_descripcion: bool) -> np.ndarray:
    """Embeddings (rol ``titular``) del texto de cada fila: el titular limpio y, si se permite, la descripción interna."""
    textos = [texto_de_entrada(f["titulo_limpio"], f.get("descripcion"), usar_descripcion) for f in filas]
    return emb.codificar(textos, "titular") if textos else np.zeros((0, 0), dtype=np.float32)


def aplicar_a_base(
    ruta_base: Path,
    reglas: ReglasV13,
    proc: ConfigProcedencias,
    cfg: ConfigClasificacion,
    emb: Embeddings,
) -> list[Grupo]:
    """Agrupa los titulares que no son ruido y guarda ``noticias.id_grupo``, ``grupos`` y ``procedencias``.

    El ruido se marca, no se borra (``id_grupo`` queda nulo: no entra en la bandeja). Solo hace UPDATE por ID sobre
    ``noticias`` y reemplaza ``grupos`` y ``procedencias``, en una transacción: una falla deja la corrida anterior.
    """
    fijar_semilla(cfg.semilla)
    con = db.conectar(ruta_base)
    try:
        db.asegurar_esquema(con)
        antes = db.contar_filas(con, "noticias")
        todas = db.leer_tabla(con, "noticias", "id_noticia")
        sin_limpiar = [f["id_noticia"] for f in todas if f.get("titulo_limpio") is None or f.get("es_ruido") is None]
        if sin_limpiar:
            raise RuntimeError(f"{len(sin_limpiar)} noticias sin limpiar: ejecute `poetry run python -m src.limpieza`")
        utiles = [f for f in todas if not f["es_ruido"]]
        vectores = codificar_titulares(utiles, emb, reglas.agrupacion.usar_descripcion)
        grupos = construir_grupos(
            utiles, vectores, reglas, proc, cargar_vinculos().subtema, {t: list(d.subtemas) for t, d in cargar_temas().temas.items()}
        )
        filas_grupos, filas_proc, asignaciones = _filas_de_grupos(grupos, estimado=True)
        con.begin()
        try:
            con.execute("UPDATE noticias SET id_grupo = NULL, procedencia = NULL")
            con.execute("DELETE FROM procedencias")
            con.execute("DELETE FROM grupos")
            if filas_grupos:
                con.executemany(_insertar("grupos"), filas_grupos)
                con.executemany(_insertar("procedencias"), filas_proc)
                con.executemany("UPDATE noticias SET id_grupo = ?, procedencia = ? WHERE id_noticia = ?", asignaciones)
            if db.contar_filas(con, "noticias") != antes:
                raise RuntimeError("la agrupación cambió el número de noticias")
            con.commit()
        except BaseException:
            con.rollback()
            raise
        return grupos
    finally:
        con.close()


# ------------------------------------------------------------------ reporte


def construir_reporte(
    grupos: Sequence[Grupo], total_noticias: int, reglas: ReglasV13, proc: ConfigProcedencias, cfg: ConfigClasificacion, z: float
) -> dict[str, Any]:
    """Resumen descriptivo con n e IC de Wilson. La precisión y el recall contra etiquetas humanas: ``eval.agrupacion``."""
    n = sum(g.n_titulares for g in grupos)
    en_grupo = sum(g.n_titulares for g in grupos if g.n_titulares > 1)
    mayores = sorted(grupos, key=lambda g: (-g.n_titulares, g.id_grupo))[:GRUPOS_EN_REPORTE]
    tamanos = [g.n_titulares for g in grupos]
    return {
        "modelo": reglas.agrupacion.modelo,
        "umbral_similitud": reglas.agrupacion.umbral_similitud,
        "ventana_dias": reglas.agrupacion.ventana_dias,
        "nota": proc.etiqueta_estimado,
        "noticias_en_base": total_noticias,
        "noticias_agrupadas_no_ruido": n,
        "grupos": len(grupos),
        "grupos_de_un_titular": proporcion(sum(1 for t in tamanos if t == 1), len(grupos), z),
        "titulares_en_grupos_de_2_o_mas": proporcion(en_grupo, n, z),
        "tamano_maximo": max(tamanos, default=0),
        "grupos_con_2_o_mas_procedencias": proporcion(sum(1 for g in grupos if g.n_procedencias >= 2), len(grupos), z),
        "mayores": [
            {
                "id_grupo": g.id_grupo,
                "titular_central": g.titular_central,
                "n_titulares": g.n_titulares,
                "n_medios": g.n_medios,
                "n_procedencias": g.n_procedencias,
                "procedencias": [{"etiqueta": p.etiqueta, "n_titulares": len(p.ids_noticia), "reglas": list(p.reglas)} for p in g.procedencias],
            }
            for g in mayores
        ],
    }


def ejecutar(ruta_base: Path, ruta_reporte: Path) -> dict[str, Any]:
    """Agrupa la base y escribe la sección ``agrupacion`` del reporte. Devuelve esa sección."""
    reglas, proc, cfg = cargar_reglas(), cargar_procedencias(), cargar_clasificacion()
    emb = crear(cfg, reglas.agrupacion.modelo)
    grupos = aplicar_a_base(ruta_base, reglas, proc, cfg, emb)
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        total = db.contar_filas(con, "noticias")
    finally:
        con.close()
    seccion = construir_reporte(grupos, total, reglas, proc, cfg, cargar_carga().salida.z_intervalo_confianza)
    escribir_seccion(ruta_reporte, "agrupacion", seccion)
    return seccion


def main(argv: list[str] | None = None) -> int:
    """CLI: agrupa ``data/senales.duckdb`` y agrega ``agrupacion`` a ``outputs/reporte_calidad.json``."""
    configurar_logging()
    parser = argparse.ArgumentParser(description="E1-08: grupos por evento y procedencias independientes (estimadas)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--reporte", type=Path, default=RAIZ / "outputs" / cargar_carga().salida.reporte)
    args = parser.parse_args(argv)
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero `normalizacion`, `limpieza` y `clasificacion`", args.base)
        return 1
    try:
        s = ejecutar(args.base, args.reporte)
    except (RuntimeError, SinCalibrar) as exc:
        logger.error("%s", exc)
        return 1
    logger.info("%d titulares en %d grupos (umbral %s, ventana %d días)", s["noticias_agrupadas_no_ruido"], s["grupos"], s["umbral_similitud"], s["ventana_dias"])
    logger.info("%s", s["nota"])
    for g in s["mayores"]:
        logger.info("  %s · %d titulares · %d medios · %d procedencias · %s", g["id_grupo"], g["n_titulares"], g["n_medios"], g["n_procedencias"], g["titular_central"][:70])
    return 0


if __name__ == "__main__":
    sys.exit(main())
