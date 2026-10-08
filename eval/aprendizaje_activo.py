"""Aprendizaje activo con una persona en el circuito (D-123).

El clasificador logístico (D-121) se entrena con los textos de referencia de ``temas.yaml``. Este módulo le agrega un
**pool** de etiquetas humanas, con una separación estricta:

* **Evaluación = la muestra original congelada** (``eval/muestra_original.csv``, ``logistica.aprendizaje_activo`` en
  ``config/clasificacion.yaml``). Esos IDs no entran al pool bajo ninguna circunstancia (``construir_pool`` los excluye y
  ``ErrorDeSeparacion`` salta si alguno se cuela).
* **Pool = etiquetas con origen ``humano`` y firmadas por una persona**, sobre titulares fuera de la evaluación (las
  ampliaciones y las que vengan). Nunca las ``asistente_provisional`` (D-101) ni las propuestas de un LLM
  (``eval/propuestas/``, que ningún lector de ``eval/`` abre). Una fila marcada como ruido no entra: el clasificador solo
  aprende los 6 temas y la abstención sale del umbral.
* **Huella** del pool (sha256 sobre ``id<TAB>tema`` ordenados) y conteo por clase: cada métrica dice con qué entrenamiento
  se produjo.

Revisión editorial (E1-16): sus acciones no incluyen cambiar el tema de un grupo (``config/revision.yaml`` y
``src/revision.py`` solo editan el borrador y el texto), así que **no hay correcciones de tema de esa vía** que usar. Es un
hueco declarado, no un dato inventado.

La cola de etiquetado ordena los titulares sin etiquetar por incertidumbre (``ordenar_por_incertidumbre``): primero la
menor probabilidad máxima, luego el menor margen entre la 1.ª y la 2.ª y, al final, el ``id_noticia``. Es determinista y
solo propone un orden: la decisión de la persona sigue siendo obligatoria («Guardar y seguir»).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from eval import origen_etiquetas as oe
from src.configuracion import RAIZ, ConfigTemas

COLUMNA_TEMA = "tema_principal"
COLUMNA_RUIDO = "ruido"
SIN_RUIDO = {"", "ninguno", "ninguna", "no", "none", "false", "0"}


class ErrorDeSeparacion(ValueError):
    """Un ID de la evaluación congelada intentó entrar al entrenamiento."""


@dataclass(frozen=True)
class Pool:
    """Etiquetas humanas de entrenamiento: ``ids`` y ``temas`` alineados y ordenados por id."""

    ids: tuple[str, ...]
    temas: tuple[str, ...]
    descartadas: dict[str, int]

    @property
    def n(self) -> int:
        return len(self.ids)

    @property
    def por_clase(self) -> dict[str, int]:
        return dict(sorted(Counter(self.temas).items()))

    @property
    def huella(self) -> str:
        return huella_de(zip(self.ids, self.temas, strict=True))

    def solo(self, presentes: Iterable[str]) -> Pool:
        """El pool sin los IDs que no están en ``presentes`` (p. ej. la base); los quita y los cuenta."""
        quedan = set(presentes)
        pares = [(i, t) for i, t in zip(self.ids, self.temas, strict=True) if i in quedan]
        faltan = self.n - len(pares)
        descartadas = {**self.descartadas, **({"no_estan_en_la_base": faltan} if faltan else {})}
        return Pool(tuple(i for i, _ in pares), tuple(t for _, t in pares), dict(sorted(descartadas.items())))

    def resumen(self, n_referencias: int | None = None) -> dict[str, Any]:
        """Lo que todo informe del método logístico declara sobre su entrenamiento."""
        r: dict[str, Any] = {"n_pool": self.n, "por_clase_pool": self.por_clase, "huella_pool": self.huella, "descartadas": self.descartadas}
        if n_referencias is not None:
            r["n_referencias"] = n_referencias
        return r


def huella_de(pares: Iterable[tuple[str, str]]) -> str:
    """sha256 sobre ``id<TAB>tema`` ordenados: no depende del orden de entrada."""
    cuerpo = "\n".join(f"{i}\t{t}" for i, t in sorted(pares))
    return hashlib.sha256(cuerpo.encode("utf-8")).hexdigest()


def referencias_por_clase(temas: ConfigTemas) -> dict[str, int]:
    """Textos de referencia por tema (descripción + ejemplos) con que entrena el logístico."""
    return {t: 1 + len(tema.ejemplos) for t, tema in temas.temas.items()}


def ids_congelados(ruta: Path) -> set[str]:
    """``id_noticia`` de la muestra de evaluación congelada."""
    import csv

    with ruta.open(encoding="utf-8", newline="") as f:
        return {(fila.get("id_noticia") or "").strip() for fila in csv.DictReader(f) if (fila.get("id_noticia") or "").strip()}


def _firmada_por_persona(fila: dict[str, str]) -> bool:
    firma = " ".join((fila.get("etiquetado_por") or "").casefold().split())
    return bool(firma) and not any(m in firma for m in oe.FIRMAS_PROVISIONALES)


def construir_pool(
    ruta_etiquetas: Path, temas: ConfigTemas, congelados: Iterable[str], evaluados: Iterable[str] = ()
) -> Pool:
    """Pool de entrenamiento: etiquetas humanas con tema, fuera de ``congelados`` y de ``evaluados``.

    ``evaluados`` son los IDs que esta corrida evalúa además (p. ej. con etiquetas provisionales): tampoco entran.
    """
    prohibidos = set(congelados) | set(evaluados)
    descartadas: Counter[str] = Counter()
    elegidas: dict[str, str] = {}
    for fila in oe.leer_filas(ruta_etiquetas, oe.SOLO_HUMANOS):
        id_ = (fila.get("id_noticia") or "").strip()
        if id_ in prohibidos:
            descartadas["en_la_evaluacion"] += 1
        elif not _firmada_por_persona(fila):
            descartadas["sin_firma_de_persona"] += 1
        elif (fila.get(COLUMNA_RUIDO) or "").strip().casefold() not in SIN_RUIDO:
            descartadas["ruido"] += 1
        elif (fila.get(COLUMNA_TEMA) or "").strip() not in temas.temas:
            descartadas["sin_tema_valido"] += 1
        else:
            elegidas[id_] = fila[COLUMNA_TEMA].strip()
    ids = tuple(sorted(elegidas))
    pool = Pool(ids, tuple(elegidas[i] for i in ids), dict(sorted(descartadas.items())))
    verificar_separacion(pool.ids, prohibidos)
    return pool


def verificar_separacion(ids_entrenamiento: Iterable[str], congelados: Iterable[str]) -> None:
    """Falla si algún ID de entrenamiento está en la evaluación congelada."""
    cruce = sorted(set(ids_entrenamiento) & set(congelados))
    if cruce:
        raise ErrorDeSeparacion(f"{len(cruce)} IDs de la evaluación congelada están en el entrenamiento: {cruce[:3]}")


def pool_desde_config(
    ruta_etiquetas: Path, temas: ConfigTemas, muestra_evaluacion: str, raiz: Path = RAIZ, evaluados: Iterable[str] = ()
) -> Pool:
    return construir_pool(ruta_etiquetas, temas, ids_congelados(raiz / muestra_evaluacion), evaluados)


# ------------------------------------------------------------------ cola por incertidumbre


def orden_de_incertidumbre(ids: Sequence[str], probabilidades: np.ndarray) -> list[tuple[str, float, float]]:
    """``(id, probabilidad máxima, margen)`` de menos a más seguro: menor máxima, menor margen y, al final, el id."""
    if len(ids) != len(probabilidades):
        raise ValueError("ids y probabilidades deben tener la misma longitud")
    ordenadas = np.sort(probabilidades, axis=1) if len(ids) else np.zeros((0, 2))
    maxima = ordenadas[:, -1] if len(ids) else []
    margen = (ordenadas[:, -1] - ordenadas[:, -2]) if len(ids) and ordenadas.shape[1] > 1 else np.zeros(len(ids))
    filas = [(i, float(m), float(g)) for i, m, g in zip(ids, maxima, margen, strict=True)]
    return sorted(filas, key=lambda f: (f[1], f[2], f[0]))


def cola_por_incertidumbre(
    ids: Sequence[str], ruta_base: Path, pool: Pool, emb: Any, cfg: Any, temas: ConfigTemas
) -> dict[str, dict[str, Any]]:
    """Cola ordenada de ``ids`` según el logístico entrenado con referencias + ``pool``.

    Devuelve ``id -> {posicion, p_maxima, margen, tema}`` (``tema`` = el más probable). Lee solo ``titulo_limpio`` y
    ``descripcion`` (interna, D-31) de la base; no escribe nada.
    """
    from src import db
    from src.clasificacion import construir_referencias, puntuar, texto_de_entrada
    from src.configuracion import METODO_LOGISTICO

    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = {r[0]: r for r in con.execute("SELECT id_noticia, titulo_limpio, descripcion FROM noticias").fetchall()}
    finally:
        con.close()
    pedidos = [i for i in ids if i in filas]
    if not pedidos:
        return {}
    ref = construir_referencias(emb, temas, None, cfg.logistica, vectores_del_pool(pool, ruta_base, emb, cfg))
    textos = [texto_de_entrada(filas[i][1], filas[i][2], cfg.usar_descripcion) for i in pedidos]
    p = puntuar(emb.codificar(textos, "titular"), ref, METODO_LOGISTICO).similitud
    orden = orden_de_incertidumbre(pedidos, p)
    mejor = {i: ref.temas[int(np.argmax(p[k]))] for k, i in enumerate(pedidos)}
    return {i: {"posicion": n + 1, "p_maxima": m, "margen": g, "tema": mejor[i]} for n, (i, m, g) in enumerate(orden)}


def vectores_del_pool(pool: Pool, ruta_base: Path, emb: Any, cfg: Any) -> tuple[np.ndarray, list[str]] | None:
    """Vectores (rol ``titular``) de los titulares del pool que están en la base; ``None`` si no hay."""
    from src import db
    from src.clasificacion import texto_de_entrada

    if not pool.n:
        return None
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = {r[0]: r for r in con.execute("SELECT id_noticia, titulo_limpio, descripcion FROM noticias").fetchall()}
    finally:
        con.close()
    pares = [(i, t) for i, t in zip(pool.ids, pool.temas, strict=True) if i in filas]
    if not pares:
        return None
    textos = [texto_de_entrada(filas[i][1], filas[i][2], cfg.usar_descripcion) for i, _ in pares]
    return emb.codificar(textos, "titular"), [t for _, t in pares]
