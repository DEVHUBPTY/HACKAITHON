"""Clasificación de titulares en los 6 temas (``tema_clasificado``) o ``sin_tema`` (E1-07, D-21, D-62).

Dos métodos con el mismo código y la misma salida (solo los 6 temas del reto):

* **A** (descripción + ejemplos): cada tema es el centroide de los embeddings de su descripción y de sus titulares de
  ejemplo (``config/temas.yaml``). La similitud con un tema es el coseno con su centroide.
* **B** (prototipos por subtema): cada subtema tiene un prototipo; la similitud con un tema es la del subtema más
  parecido y el resultado sube a su tema. El subtema queda como detalle ("Servicios públicos · agua potable").

Reglas comunes: solo se clasifica ``titulo_limpio`` de los registros con ``es_ruido = false`` (con la descripción del
RSS como texto interno si existe, D-31); el ``tema`` de origen del contrato **nunca** se lee (D-62: sería una fuga de
información); la similitud con cada tema se guarda en ``similitud_tema`` (explicabilidad); si la mayor similitud no
llega al umbral de ``config/clasificacion.yaml`` no hay tema (``sin_tema``); el tema secundario es el segundo mejor si
está a menos de ``margen_secundario`` del principal y supera el mismo umbral. También calcula el baseline de palabras
clave (D-66) y, si ``ruido.yaml`` lo activa, el filtro de ruido por similitud con un prototipo de noticia sobre Panamá
(D-84), que no marca nunca una nota de alcance regional.

Uso: ``poetry run python -m src.clasificacion`` (después de ``src.normalizacion`` y ``src.limpieza``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from src import db
from src.baseline import SIN_TEMA, Baseline
from src.carga import intervalo_wilson
from src.configuracion import (
    RAIZ,
    ConfigClasificacion,
    ConfigRuido,
    ConfigTemas,
    UmbralesMetodo,
    cargar_carga,
    cargar_clasificacion,
    cargar_normalizacion,
    cargar_ruido,
    cargar_temas,
)
from src.embeddings import Embeddings, crear, fijar_semilla
from src.limpieza import Reglas, limpiar_titulo
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

METODO_A = "A"
METODO_B = "B"
MOTIVO_NO_ES_PANAMA = "no_es_panama"
DECIMALES_PRESENTACION = 4  # presentación de proporciones e IC: no afecta ninguna decisión

COLUMNAS_CLASIFICACION = (
    "similitud_panama",
    "ruido_similitud",
    "tema_clasificado",
    "tema_similitud",
    "subtema_clasificado",
    "tema_secundario",
    "tema_secundario_similitud",
    "tema_baseline",
)


# ------------------------------------------------------------------ texto de entrada


def texto_de_entrada(titulo_limpio: str, descripcion: str | None, usar_descripcion: bool) -> str:
    """Texto que se codifica: el titular limpio y, si existe y la configuración lo permite, la descripción (interna)."""
    if usar_descripcion and descripcion and descripcion.strip():
        return f"{titulo_limpio}. {descripcion.strip()}"
    return titulo_limpio


# ------------------------------------------------------------------ referencias de los temas


@dataclass(frozen=True)
class Referencias:
    """Vectores de referencia de los 6 temas: centroides (método A) y prototipos de subtemas (método B)."""

    temas: list[str]                        # ids de temas, en el orden de temas.yaml
    centroides: np.ndarray                  # (temas, d)
    subtemas: list[tuple[str, str]]         # (tema, subtema) por fila de ``prototipos``
    prototipos: np.ndarray                  # (subtemas, d)


def _unitario(vector: np.ndarray) -> np.ndarray:
    norma = float(np.linalg.norm(vector))
    return vector / norma if norma else vector


def textos_de_referencia(temas: ConfigTemas, reglas: Reglas) -> dict[str, list[str]]:
    """Textos del método A por tema: la descripción y los titulares de ejemplo (limpiados como los titulares reales)."""
    return {
        id_tema: [tema.descripcion, *(limpiar_titulo(e.titulo, None, None, reglas) for e in tema.ejemplos)]
        for id_tema, tema in temas.temas.items()
    }


def construir_referencias(emb: Embeddings, temas: ConfigTemas, reglas: Reglas | None = None) -> Referencias:
    """Codifica descripciones, ejemplos y prototipos (rol ``tema``) y arma centroides y prototipos."""
    reglas = reglas or Reglas.desde_config()
    ids = list(temas.temas)
    centroides = []
    for id_tema, textos in textos_de_referencia(temas, reglas).items():
        vectores = emb.codificar(textos, "tema")
        centroides.append(_unitario(vectores.mean(axis=0)))
        logger.debug("Centroide de %s con %d textos", id_tema, len(textos))
    subtemas = [(id_tema, sub) for id_tema, tema in temas.temas.items() for sub in tema.subtemas]
    prototipos = emb.codificar([temas.temas[t].subtemas[s].prototipo for t, s in subtemas], "tema")
    return Referencias(ids, np.stack(centroides), subtemas, prototipos)


# ------------------------------------------------------------------ puntaje y decisión


@dataclass(frozen=True)
class Puntajes:
    """Similitud de cada texto con cada tema. En B, ``subtema[i][j]`` es el subtema más parecido dentro del tema j."""

    similitud: np.ndarray                   # (n, temas)
    subtema: list[list[str | None]]         # (n, temas); None en el método A
    margen: np.ndarray                      # (n, temas): 1.º − 2.º subtema del tema (D-92); NaN en el método A


def puntuar(vectores: np.ndarray, ref: Referencias, metodo: str) -> Puntajes:
    """Similitud coseno de ``vectores`` (ya normalizados) con los 6 temas según el método."""
    n = vectores.shape[0]
    if metodo == METODO_A:
        return Puntajes(vectores @ ref.centroides.T, [[None] * len(ref.temas) for _ in range(n)], np.full((n, len(ref.temas)), np.nan))
    if metodo != METODO_B:
        raise ValueError(f"método desconocido: {metodo!r} (A o B)")
    sims = vectores @ ref.prototipos.T                                     # (n, subtemas)
    similitud = np.full((n, len(ref.temas)), -np.inf, dtype=np.float64)
    margen = np.full((n, len(ref.temas)), np.nan, dtype=np.float64)
    elegido: list[list[str | None]] = [[None] * len(ref.temas) for _ in range(n)]
    for j, id_tema in enumerate(ref.temas):
        columnas = [k for k, (t, _) in enumerate(ref.subtemas) if t == id_tema]
        mejor = np.argmax(sims[:, columnas], axis=1)                       # el primero gana un empate
        if len(columnas) > 1:                                              # con un solo subtema no hay segundo: margen nulo
            ordenadas = np.sort(sims[:, columnas], axis=1)
            margen[:, j] = ordenadas[:, -1] - ordenadas[:, -2]
        similitud[:, j] = sims[np.arange(n), np.array(columnas)[mejor]]
        for i in range(n):
            elegido[i][j] = ref.subtemas[columnas[int(mejor[i])]][1]
    return Puntajes(similitud, elegido, margen)


@dataclass(frozen=True)
class Decision:
    """Resultado de clasificar un titular. ``similitud`` es la mayor, aunque no llegue al umbral (``sin_tema``)."""

    principal: str
    similitud: float
    subtema: str | None
    secundario: str | None
    similitud_secundaria: float | None
    similitudes: dict[str, float]
    segundo_mejor: str | None = None        # el 2.º tema por similitud, aunque no pase el margen (diagnóstico)


def decidir(similitud: np.ndarray, subtemas: list[str | None], temas: list[str], umbrales: UmbralesMetodo) -> Decision:
    """Principal = tema de mayor similitud (``sin_tema`` si no llega al umbral); secundario = segundo si está cerca."""
    orden = sorted(range(len(temas)), key=lambda j: (-float(similitud[j]), j))   # empate: el primero de temas.yaml
    mejor, segundo = orden[0], orden[1]
    s1, s2 = float(similitud[mejor]), float(similitud[segundo])
    por_tema = {t: float(similitud[j]) for j, t in enumerate(temas)}
    if s1 < umbrales.umbral_sin_tema:
        return Decision(SIN_TEMA, s1, None, None, None, por_tema, temas[segundo])
    cerca = s2 >= umbrales.umbral_sin_tema and (s1 - s2) <= umbrales.margen_secundario
    return Decision(
        temas[mejor],
        s1,
        subtemas[mejor],
        temas[segundo] if cerca else None,
        s2 if cerca else None,
        por_tema,
        temas[segundo],
    )


def decidir_todos(puntajes: Puntajes, temas: list[str], umbrales: UmbralesMetodo) -> list[Decision]:
    """``decidir`` para cada fila de ``puntajes``."""
    return [decidir(puntajes.similitud[i], puntajes.subtema[i], temas, umbrales) for i in range(puntajes.similitud.shape[0])]


def clasificar_textos(
    textos: list[str],
    emb: Embeddings,
    ref: Referencias,
    metodo: str,
    umbrales: UmbralesMetodo,
) -> list[Decision]:
    """Clasifica ``textos`` (rol ``titular``) con el método A o B."""
    if not textos:
        return []
    return decidir_todos(puntuar(emb.codificar(textos, "titular"), ref, metodo), ref.temas, umbrales)


def similitud_con_prototipos_panama(textos: list[str], emb: Embeddings, prototipos: list[str]) -> np.ndarray:
    """Mayor similitud coseno de cada texto con los prototipos de noticia sobre Panamá (señal de ruido, D-84)."""
    if not textos:
        return np.zeros(0)
    return (emb.codificar(textos, "titular") @ emb.codificar(prototipos, "tema").T).max(axis=1)


# ------------------------------------------------------------------ reporte


def proporcion(k: int, n: int, z: float) -> dict[str, Any]:
    """``k`` de ``n`` con intervalo de Wilson al 95 % (``None`` si ``n`` es 0)."""
    ic = intervalo_wilson(k, n, z)
    return {
        "n": k,
        "de": n,
        "proporcion": None if n == 0 else round(k / n, DECIMALES_PRESENTACION),
        "ic95": None if ic is None else [round(ic[0], DECIMALES_PRESENTACION), round(ic[1], DECIMALES_PRESENTACION)],
    }


def _resumen(valores: list[float]) -> dict[str, float] | None:
    if not valores:
        return None
    v = np.array(valores)
    return {k: round(float(x), DECIMALES_PRESENTACION) for k, x in (("min", v.min()), ("mediana", np.median(v)), ("max", v.max()))}


def construir_reporte(
    filas: list[dict[str, Any]],
    cfg: ConfigClasificacion,
    ruido: ConfigRuido,
    umbrales: UmbralesMetodo,
    metodo: str,
    z: float,
) -> dict[str, Any]:
    """Distribución de temas con n e IC de Wilson. **No es exactitud**: no hay etiquetas humanas hasta E1-06."""
    clasificadas = [f for f in filas if f.get("tema_clasificado") is not None]
    n = len(clasificadas)
    modelo = cfg.modelos[cfg.modelo_activo]
    temas = sorted({f["tema_clasificado"] for f in clasificadas})
    marcadas = [f for f in filas if f.get("ruido_similitud")]
    return {
        "modelo": {"nombre": cfg.modelo_activo, "id": modelo.id, "revision": modelo.revision},
        "metodo": metodo,
        "semilla": cfg.semilla,
        "umbral_sin_tema": umbrales.umbral_sin_tema,
        "margen_secundario": umbrales.margen_secundario,
        "noticias_en_base": len(filas),
        "clasificadas_no_ruido": n,
        "nota": (
            "Distribución descriptiva sobre noticias no marcadas como ruido; el snapshot no es una muestra aleatoria. "
            "NO es exactitud ni macro-F1: esas métricas requieren eval/etiquetas.csv (E1-06; python -m eval.clasificacion)."
        ),
        "distribucion": {t: proporcion(sum(1 for f in clasificadas if f["tema_clasificado"] == t), n, z) for t in temas},
        "con_tema_secundario": proporcion(sum(1 for f in clasificadas if f.get("tema_secundario")), n, z),
        "concordancia_con_baseline": proporcion(
            sum(1 for f in clasificadas if f["tema_clasificado"] == f["tema_baseline"]), n, z
        ),
        "nota_concordancia": "Acuerdo entre dos métodos automáticos; no mide cuál acierta.",
        "similitud_principal": _resumen([f["tema_similitud"] for f in clasificadas]),
        "ruido_similitud": {
            "activo": ruido.similitud_prototipo.activo,
            "umbral": ruido.similitud_prototipo.umbral,
            "marcadas": proporcion(len(marcadas), len(filas), z),
            "similitud_panama": _resumen([f["similitud_panama"] for f in filas if f.get("similitud_panama") is not None]),
            "nota": (
                "Con activo=false solo se guarda la señal (similitud_panama), sin marcar. Precisión y recall del "
                "filtro: python -m eval.ruido con eval/etiquetas.csv (E1-06)."
            ),
        },
    }


def escribir_seccion(ruta: Path, clave: str, seccion: dict[str, Any]) -> None:
    """Agrega ``seccion`` bajo ``clave`` en el reporte JSON (conserva lo que escribieron las demás tareas)."""
    datos: dict[str, Any] = {}
    if ruta.exists():
        with ruta.open(encoding="utf-8") as f:
            datos = json.load(f)
    datos[clave] = seccion
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ------------------------------------------------------------------ DuckDB


def _reiniciar(con: Any) -> None:
    """Borra lo clasificado antes. Se llama DENTRO de la transacción, después de calcular todo (X15, H8)."""
    asignaciones = ", ".join(f"{c} = NULL" for c in COLUMNAS_CLASIFICACION)
    con.execute(f"UPDATE noticias SET {asignaciones}")
    con.execute("DELETE FROM similitud_tema")


def aplicar_a_base(
    ruta_base: Path,
    cfg: ConfigClasificacion,
    ruido: ConfigRuido,
    temas: ConfigTemas,
    emb: Embeddings,
    metodo: str | None = None,
    reglas: Reglas | None = None,
) -> list[dict[str, Any]]:
    """Calcula y guarda similitud con Panamá, ruido por similitud, tema, subtema, secundario y baseline.

    Devuelve las filas de ``noticias`` ya actualizadas. Solo hace UPDATE por ID sobre ``noticias`` y reemplaza
    ``similitud_tema``: no inserta ni borra noticias (el ruido se marca, no se borra).
    """
    metodo = metodo or cfg.metodo_activo
    umbrales = cfg.modelos[cfg.modelo_activo].umbrales[metodo]
    reglas = reglas or Reglas.desde_config()
    fijar_semilla(cfg.semilla)
    con = db.conectar(ruta_base)
    try:
        db.asegurar_esquema(con)
        antes = db.contar_filas(con, "noticias")
        filas = db.leer_tabla(con, "noticias", "id_noticia")
        # Primero se comprueban los requisitos y se calcula todo; la base no se toca hasta tener el resultado (X15, H8).
        sin_limpiar = [f["id_noticia"] for f in filas if f.get("titulo_limpio") is None or f.get("es_ruido") is None]
        if sin_limpiar:
            raise RuntimeError(f"{len(sin_limpiar)} noticias sin limpiar: ejecute `poetry run python -m src.limpieza`")
        for f in filas:
            if f.get("ruido_similitud"):  # una corrida anterior la marcó por similitud: antes no era ruido (solo se marcan las no-ruido)
                f["es_ruido"], f["motivo_ruido"] = False, None
        for f in filas:
            f["_texto"] = texto_de_entrada(f["titulo_limpio"], f.get("descripcion"), cfg.usar_descripcion)

        # 1) señal de similitud con un prototipo de noticia sobre Panamá (D-84); marca solo si está activa
        similitudes = similitud_con_prototipos_panama([f["_texto"] for f in filas], emb, ruido.similitud_prototipo.prototipos)
        for f, s in zip(filas, similitudes, strict=True):
            f["similitud_panama"] = float(s)
            f["ruido_similitud"] = None
            if (
                ruido.similitud_prototipo.activo
                and not f["es_ruido"]
                and not f.get("alcance_regional")
                and s < ruido.similitud_prototipo.umbral
            ):
                f.update(es_ruido=True, motivo_ruido=MOTIVO_NO_ES_PANAMA, ruido_similitud=True)

        # 2) clasificación de lo que no es ruido; el `tema` de origen no se lee en ningún punto
        utiles = [f for f in filas if not f["es_ruido"]]
        ref = construir_referencias(emb, temas, reglas)
        baseline = Baseline(cfg, temas)
        modelo = cfg.modelos[cfg.modelo_activo]
        vectores = emb.codificar([f["_texto"] for f in utiles], "titular") if utiles else np.zeros((0, ref.centroides.shape[1]))
        puntajes = {m: puntuar(vectores, ref, m) for m in (METODO_A, METODO_B)}
        decisiones = decidir_todos(puntajes[metodo], ref.temas, modelo.umbrales[metodo])
        for f, d in zip(utiles, decisiones, strict=True):
            f.update(
                tema_clasificado=d.principal,
                tema_similitud=d.similitud,
                subtema_clasificado=d.subtema,
                tema_secundario=d.secundario,
                tema_secundario_similitud=d.similitud_secundaria,
                tema_baseline=baseline.clasificar(f["_texto"]).principal,
            )
        # similitud con cada tema, por método (explicabilidad); el subtema solo existe en B
        detalle = [
            [
                f["id_noticia"], m, t, float(puntajes[m].similitud[i, j]), puntajes[m].subtema[i][j],
                None if np.isnan(puntajes[m].margen[i, j]) else float(puntajes[m].margen[i, j]),
            ]
            for m in (METODO_A, METODO_B)
            for i, f in enumerate(utiles)
            for j, t in enumerate(ref.temas)
        ]

        con.begin()  # todo o nada: una falla a mitad de camino deja la corrida anterior intacta
        try:
            _reiniciar(con)
            con.executemany(
                "UPDATE noticias SET es_ruido = ?, motivo_ruido = ?, similitud_panama = ?, ruido_similitud = ?, "
                "tema_clasificado = ?, tema_similitud = ?, subtema_clasificado = ?, tema_secundario = ?, "
                "tema_secundario_similitud = ?, tema_baseline = ? WHERE id_noticia = ?",
                [
                    [
                        f["es_ruido"], f["motivo_ruido"], f["similitud_panama"], f["ruido_similitud"],
                        f.get("tema_clasificado"), f.get("tema_similitud"), f.get("subtema_clasificado"),
                        f.get("tema_secundario"), f.get("tema_secundario_similitud"), f.get("tema_baseline"),
                        f["id_noticia"],
                    ]
                    for f in filas
                ],
            )
            if detalle:
                con.executemany("INSERT INTO similitud_tema VALUES (?, ?, ?, ?, ?, ?)", detalle)
            if db.contar_filas(con, "noticias") != antes:  # no debería ocurrir: solo hay UPDATE
                raise RuntimeError("la clasificación cambió el número de noticias")
            con.commit()
        except BaseException:
            con.rollback()
            raise
        return filas
    finally:
        con.close()


def ejecutar(ruta_base: Path, ruta_reporte: Path, nombre_modelo: str | None = None, metodo: str | None = None) -> dict[str, Any]:
    """Clasifica ``noticias`` en la base y escribe la sección ``clasificacion`` del reporte. Devuelve esa sección."""
    cfg = cargar_clasificacion()
    if nombre_modelo and nombre_modelo != cfg.modelo_activo:
        cfg = cfg.model_copy(update={"modelo_activo": nombre_modelo})
    metodo = metodo or cfg.metodo_activo
    ruido, temas = cargar_ruido(), cargar_temas()
    emb = crear(cfg)
    filas = aplicar_a_base(ruta_base, cfg, ruido, temas, emb, metodo)
    seccion = construir_reporte(filas, cfg, ruido, cfg.modelos[cfg.modelo_activo].umbrales[metodo], metodo, cargar_carga().salida.z_intervalo_confianza)
    seccion["embeddings"] = {"codificados": emb.codificados, "aciertos_cache": emb.aciertos_cache}
    escribir_seccion(ruta_reporte, "clasificacion", seccion)
    return seccion


def main(argv: list[str] | None = None) -> int:
    """CLI: clasifica ``data/senales.duckdb`` y agrega ``clasificacion`` a ``outputs/reporte_calidad.json``."""
    configurar_logging()
    carga = cargar_carga()
    cfg = cargar_clasificacion()
    parser = argparse.ArgumentParser(description="E1-07: embeddings, clasificación temática y baseline")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--reporte", type=Path, default=RAIZ / "outputs" / carga.salida.reporte)
    parser.add_argument("--modelo", choices=sorted(cfg.modelos), default=cfg.modelo_activo)
    parser.add_argument("--metodo", choices=("A", "B"), default=cfg.metodo_activo)
    args = parser.parse_args(argv)
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero `normalizacion` y `limpieza`", args.base)
        return 1
    try:
        s = ejecutar(args.base, args.reporte, args.modelo, args.metodo)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("modelo %s@%s, método %s", s["modelo"]["id"], s["modelo"]["revision"][:8], s["metodo"])
    logger.info("clasificadas (no ruido): %d de %d noticias", s["clasificadas_no_ruido"], s["noticias_en_base"])
    for tema, p in s["distribucion"].items():
        logger.info("  %s: %d/%d IC95 %s", tema, p["n"], p["de"], p["ic95"])
    logger.info("embeddings: %s", s["embeddings"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
