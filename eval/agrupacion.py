"""Evaluación y calibración de la agrupación por evento (E1-08, D-16): precisión y recall de PARES con ``eval/etiquetas.csv``.

Un par de titulares es **positivo** si las etiquetas humanas les dan el mismo ``grupo`` (columna de E1-06) y se **predice**
si el sistema los deja en el mismo ``GRP-``. Un titular sin ``grupo`` va suelto; uno que el filtro de ruido descartó no
está en ningún grupo (queda suelto). La agrupación se corre sobre **todos** los titulares útiles del snapshot (como en el
pipeline) y se mide solo en los pares entre titulares etiquetados.

* **Modelo:** el de ``agrupacion.modelo`` (``--modelo`` mide otro sin tocar la configuración). El umbral solo vale para el
  modelo con el que se calibró: cada modelo tiene otra escala de similitud.
* **Calibración (D-16):** se barre ``umbral_similitud`` (rango y paso en ``reglas_v1.3.yaml``: ``agrupacion.calibracion``) y
  se elige el de mayor F1 de pares. Regla de desempate fijada de antemano: entre los umbrales con el F1 máximo, la **mitad
  de la meseta contigua más larga** (la mediana inferior): un umbral en el borde de una meseta es frágil. Nunca a ojo.
* **Medición honesta:** las mismas etiquetas calibran y evalúan, así que el F1 con el umbral elegido es **optimista**. Por
  eso se reporta también una validación cruzada determinista (``pliegues``: el pliegue de un titular es el hash de su
  ID): se calibra con los pares de los titulares de los otros pliegues y se mide en los pares del pliegue de prueba.
  El resultado agrupado de los pliegues de prueba es la cifra que no vio la calibración.
* **Incertidumbre:** precisión y recall son proporciones de pares con IC de Wilson al 95 %. Los pares no son independientes
  (un grupo de 20 titulares aporta 190 pares) y casi todos los positivos salen de dos grupos, así que el IC es **demasiado
  estrecho**: léase como cota inferior de la incertidumbre. El conteo por grupo humano lo muestra.
* Línea base: unir solo titulares idénticos (texto normalizado, sin servicio de IA).

Uso: ``poetry run python -m eval.agrupacion [--modelo e5|minilm]`` → ``outputs/agrupacion.json`` y
``outputs/agrupacion_curva.csv``. No escribe en ``config/``: el umbral elegido se pasa a ``reglas_v1.3.yaml`` a mano, con
su justificación en ``docs/calibracion_agrupacion.md``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Iterable, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

from eval import origen_etiquetas as oe
from src import db
from src.agrupacion import agrupar_indices, codificar_titulares, fecha_de
from src.clasificacion import proporcion
from src.configuracion import (
    RAIZ,
    ConfigClasificacion,
    ReglasV13,
    cargar_carga,
    cargar_clasificacion,
    cargar_normalizacion,
    cargar_reglas,
)
from src.embeddings import crear
from src.limpieza import plano

ETIQUETAS = RAIZ / "eval" / "etiquetas.csv"
SALIDA_JSON = RAIZ / "outputs" / "agrupacion.json"
SALIDA_CSV = RAIZ / "outputs" / "agrupacion_curva.csv"
CODIGO_SIN_ETIQUETAS = 2
DECIMALES_UMBRAL = 6        # el barrido se redondea para que 0.55 no sea 0.5500000000000002
DECIMALES_PRESENTACION = 4  # solo presentación
TOLERANCIA_F1 = 1e-12       # dos F1 que difieren menos que esto son el mismo valor
LARGO_HASH_PLIEGUE = 8      # caracteres hexadecimales del SHA-1 del ID que deciden el pliegue


# ------------------------------------------------------------------ etiquetas y pares


def leer_grupos_humanos(ruta: Path = ETIQUETAS, origenes: Iterable[str] = oe.SOLO_HUMANOS) -> dict[str, str | None]:
    """``id_noticia`` -> grupo humano (``None`` = suelto) de los titulares etiquetados por ``origenes`` (por defecto, personas)."""
    return {fila["id_noticia"]: (fila.get("grupo") or "").strip() or None for fila in oe.leer_filas(ruta, origenes)}


def pares_positivos(etiquetas: Sequence[str | None]) -> np.ndarray:
    """Matriz booleana ``m[i, j]`` = mismo grupo (``None`` nunca coincide, ni consigo mismo); diagonal falsa."""
    n = len(etiquetas)
    m = np.zeros((n, n), dtype=bool)
    for i in range(n):
        for j in range(n):
            m[i, j] = i != j and etiquetas[i] is not None and etiquetas[i] == etiquetas[j]
    return m


def conteo_de_pares(real: np.ndarray, predicho: np.ndarray, subconjunto: np.ndarray | None = None) -> tuple[int, int, int]:
    """(TP, FP, FN) sobre los pares ``i < j`` entre los titulares de ``subconjunto`` (máscara booleana; todos si es ``None``)."""
    n = real.shape[0]
    activos = np.ones(n, dtype=bool) if subconjunto is None else subconjunto
    superior = np.triu(np.ones((n, n), dtype=bool), k=1) & activos[:, None] & activos[None, :]
    tp = int((real & predicho & superior).sum())
    fp = int((~real & predicho & superior).sum())
    fn = int((real & ~predicho & superior).sum())
    return tp, fp, fn


def f1_de_pares(tp: int, fp: int, fn: int) -> float | None:
    """F1 = 2·TP / (2·TP + FP + FN); ``None`` si no hay pares positivos ni predichos."""
    d = 2 * tp + fp + fn
    return None if d == 0 else 2 * tp / d


# ------------------------------------------------------------------ barrido y elección


def umbrales_del_barrido(desde: float, hasta: float, paso: float) -> list[float]:
    """``desde``, ``desde + paso``, ... hasta ``hasta`` (incluido), redondeados."""
    k = int(round((hasta - desde) / paso))
    return [round(desde + i * paso, DECIMALES_UMBRAL) for i in range(k + 1) if desde + i * paso <= hasta + paso / 2]


def elegir_umbral(umbrales: Sequence[float], f1: Sequence[float | None]) -> float:
    """Mayor F1; entre los empatados, la mitad (mediana inferior) de la meseta contigua más larga.

    En un empate de longitud, gana la meseta de menor umbral. ``None`` cuenta como -1 (peor que cualquier F1).
    """
    valores = [-1.0 if v is None else v for v in f1]
    mejor = max(valores)
    posiciones = [i for i, v in enumerate(valores) if abs(v - mejor) <= TOLERANCIA_F1]
    mesetas: list[list[int]] = []
    for i in posiciones:
        if mesetas and i == mesetas[-1][-1] + 1:
            mesetas[-1].append(i)
        else:
            mesetas.append([i])
    meseta = max(mesetas, key=lambda m: (len(m), -m[0]))
    return umbrales[meseta[(len(meseta) - 1) // 2]]


def pliegue_de(id_noticia: str, pliegues: int) -> int:
    """Pliegue determinista de un titular: hash de su ID (no depende del orden ni de la semilla)."""
    return int(hashlib.sha1(id_noticia.encode()).hexdigest()[:LARGO_HASH_PLIEGUE], 16) % pliegues


class Barrido:
    """Predicciones de pares de cada umbral, calculadas una vez; cualquier subconjunto se mide sin reagrupar."""

    def __init__(
        self,
        ids_etiquetados: Sequence[str],
        etiquetas: Sequence[str | None],
        filas_utiles: Sequence[dict[str, Any]],
        vectores: np.ndarray,
        reglas: ReglasV13,
        umbrales: Sequence[float],
    ) -> None:
        self.ids = list(ids_etiquetados)
        self.umbrales = list(umbrales)
        self.real = pares_positivos(etiquetas)
        ids_utiles = [str(f["id_noticia"]) for f in filas_utiles]
        campos = reglas.agrupacion.campos_fecha
        fechas = [fecha_de(f, campos) for f in filas_utiles]
        posicion = {i: k for k, i in enumerate(self.ids)}
        self.predicho: dict[float, np.ndarray] = {}
        for u in self.umbrales:
            grupo_de: dict[str, int] = {}
            for g, indices in enumerate(agrupar_indices(vectores, fechas, ids_utiles, u, reglas.agrupacion.ventana_dias)):
                for i in indices:
                    grupo_de[ids_utiles[i]] = g
            asignado = [grupo_de.get(i) for i in self.ids]
            m = np.zeros((len(self.ids), len(self.ids)), dtype=bool)
            for a, b in combinations(range(len(self.ids)), 2):
                if asignado[a] is not None and asignado[a] == asignado[b]:
                    m[a, b] = m[b, a] = True
            self.predicho[u] = m
        self.posicion = posicion

    def curva(self, subconjunto: np.ndarray | None = None) -> list[dict[str, Any]]:
        filas = []
        for u in self.umbrales:
            tp, fp, fn = conteo_de_pares(self.real, self.predicho[u], subconjunto)
            f1 = f1_de_pares(tp, fp, fn)
            filas.append({"umbral": u, "tp": tp, "fp": fp, "fn": fn, "f1": f1})
        return filas


def elegir_de_curva(curva: Sequence[dict[str, Any]]) -> float:
    return elegir_umbral([c["umbral"] for c in curva], [c["f1"] for c in curva])


# ------------------------------------------------------------------ informe


def _presentar(tp: int, fp: int, fn: int, z: float) -> dict[str, Any]:
    f1 = f1_de_pares(tp, fp, fn)
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": proporcion(tp, tp + fp, z),
        "recall": proporcion(tp, tp + fn, z),
        "f1": None if f1 is None else round(f1, DECIMALES_PRESENTACION),
    }


def _pares_con_ids(real: np.ndarray, predicho: np.ndarray, ids: Sequence[str], tipo: str) -> list[list[str]]:
    """Pares (id, id) falsos positivos (``fp``) o falsos negativos (``fn``): los IDs de los fallos que pide el protocolo."""
    sel = (~real & predicho) if tipo == "fp" else (real & ~predicho)
    return [[ids[i], ids[j]] for i, j in zip(*np.nonzero(np.triu(sel, k=1)), strict=True)]


def validacion_cruzada(barrido: Barrido, pliegues: int, z: float) -> dict[str, Any]:
    """Calibra con los titulares de los demás pliegues y mide en los pares del pliegue de prueba; agrupa los resultados."""
    fold = np.array([pliegue_de(i, pliegues) for i in barrido.ids])
    detalle, total = [], [0, 0, 0]
    for k in range(pliegues):
        entrenamiento, prueba = fold != k, fold == k
        umbral = elegir_de_curva(barrido.curva(entrenamiento))
        tp, fp, fn = conteo_de_pares(barrido.real, barrido.predicho[umbral], prueba)
        detalle.append({"pliegue": k, "titulares_de_prueba": int(prueba.sum()), "umbral_elegido_sin_este_pliegue": umbral, **_presentar(tp, fp, fn, z)})
        total = [total[0] + tp, total[1] + fp, total[2] + fn]
    return {
        "pliegues": pliegues,
        "nota": "Los pares entre titulares de pliegues distintos no se cuentan. Cifra agrupada de los pliegues de prueba.",
        "por_pliegue": detalle,
        "agrupado": _presentar(*total, z),
    }


def por_grupo_humano(barrido: Barrido, etiquetas: Sequence[str | None], umbral: float) -> dict[str, Any]:
    """Pares recuperados de cada grupo humano (recall por grupo) con el umbral elegido."""
    salida = {}
    for grupo in sorted({e for e in etiquetas if e}):
        miembros = np.array([e == grupo for e in etiquetas])
        tp, _, fn = conteo_de_pares(barrido.real, barrido.predicho[umbral], miembros)
        salida[grupo] = {"titulares": int(miembros.sum()), "pares": tp + fn, "recuperados": tp}
    return salida


def linea_base_identicos(filas_etiquetadas: Sequence[dict[str, Any] | None], real: np.ndarray, z: float) -> dict[str, Any]:
    """Unir solo titulares útiles (no ruido) con el mismo texto normalizado, sin IA: la línea base que el sistema debe superar."""
    n = len(filas_etiquetadas)
    claves = [plano(str(f["titulo_limpio"])) if f and not f["es_ruido"] else None for f in filas_etiquetadas]
    m = np.zeros((n, n), dtype=bool)
    for i in range(n):
        for j in range(n):
            m[i, j] = i != j and claves[i] is not None and claves[i] == claves[j]
    return _presentar(*conteo_de_pares(real, m), z)


def evaluar(
    ruta_base: Path,
    ruta_etiquetas: Path,
    cfg: ConfigClasificacion,
    reglas: ReglasV13,
    z: float,
    origenes: Iterable[str] = oe.SOLO_HUMANOS,
) -> dict[str, Any]:
    """Calibra y mide la agrupación con el modelo de ``cfg.modelo_activo``. Devuelve el informe completo.

    ``origenes``: por defecto solo los grupos de las personas. Con las ``asistente_provisional`` (D-101) el informe lo
    declara (``usa_etiquetas_provisionales``, ``aviso``).
    """
    origenes = oe.validar_origenes(origenes)
    humanos = leer_grupos_humanos(ruta_etiquetas, origenes)
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        todas = db.leer_tabla(con, "noticias", "id_noticia")
    finally:
        con.close()
    if any(f.get("es_ruido") is None for f in todas):
        raise RuntimeError("noticias sin limpiar: ejecute `poetry run python -m src.limpieza` y `src.clasificacion`")
    por_id = {str(f["id_noticia"]): f for f in todas}
    faltan = sorted(set(humanos) - set(por_id))
    if faltan:
        raise RuntimeError(f"{len(faltan)} etiquetas no están en la base (¿otro snapshot?): {faltan[:5]}")
    utiles = [f for f in todas if not f["es_ruido"]]
    emb = crear(cfg, cfg.modelo_activo)
    vectores = codificar_titulares(utiles, emb, reglas.agrupacion.usar_descripcion)

    ids = sorted(humanos)
    etiquetas = [humanos[i] for i in ids]
    # Un titular que el filtro marcó como ruido no está en ningún grupo; si además es de un grupo humano, es un FN.
    cal = reglas.agrupacion.calibracion
    umbrales = umbrales_del_barrido(cal.barrido_desde, cal.barrido_hasta, cal.barrido_paso)
    barrido = Barrido(ids, etiquetas, utiles, vectores, reglas, umbrales)
    curva = barrido.curva()
    elegido = elegir_de_curva(curva)
    en_curva = next(c for c in curva if c["umbral"] == elegido)
    configurado = reglas.agrupacion.umbral_similitud
    n = len(ids)
    pares_total = n * (n - 1) // 2
    positivos = int(np.triu(barrido.real, k=1).sum())
    return {
        **oe.marcar({}, origenes),
        "modelo": cfg.modelo_activo,
        "titulares_etiquetados": n,
        "titulares_utiles_agrupados": len(utiles),
        "pares_evaluados": pares_total,
        "pares_positivos": positivos,
        "ventana_dias": reglas.agrupacion.ventana_dias,
        "barrido": {"desde": cal.barrido_desde, "hasta": cal.barrido_hasta, "paso": cal.barrido_paso},
        "umbral_elegido": elegido,
        "umbral_configurado": configurado,
        "modelo_configurado": reglas.agrupacion.modelo,
        "configuracion_coincide": configurado == elegido and reglas.agrupacion.modelo == cfg.modelo_activo,
        "regla_de_eleccion": "mayor F1 de pares; entre empatados, la mitad de la meseta contigua más larga",
        "con_el_umbral_elegido": {
            "nota": "Las mismas etiquetas calibran y evalúan: cifra OPTIMISTA. Véase validacion_cruzada.",
            **_presentar(en_curva["tp"], en_curva["fp"], en_curva["fn"], z),
        },
        "validacion_cruzada": validacion_cruzada(barrido, cal.pliegues, z),
        "por_grupo_humano": por_grupo_humano(barrido, etiquetas, elegido),
        "linea_base_titulares_identicos": linea_base_identicos([por_id[i] for i in ids], barrido.real, z),
        "falsos_positivos": _pares_con_ids(barrido.real, barrido.predicho[elegido], ids, "fp"),
        "falsos_negativos": _pares_con_ids(barrido.real, barrido.predicho[elegido], ids, "fn"),
        "nota_ic": (
            "IC de Wilson sobre pares: los pares comparten titulares y casi todos los positivos salen de dos grupos "
            "humanos (el-nino-latam, trump-ayuda-europa-latam), así que el IC es demasiado estrecho."
        ),
        "curva": [
            {**c, "f1": None if c["f1"] is None else round(c["f1"], DECIMALES_PRESENTACION)} for c in curva
        ],
    }


def escribir_salidas(informe: dict[str, Any], ruta_json: Path, ruta_csv: Path) -> None:
    ruta_json.parent.mkdir(parents=True, exist_ok=True)
    with ruta_json.open("w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with ruta_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["umbral", "tp", "fp", "fn", "f1"])
        w.writeheader()
        w.writerows(informe["curva"])


def main(argv: list[str] | None = None) -> int:
    """CLI: calibra y mide la agrupación contra ``eval/etiquetas.csv``."""
    cfg = cargar_clasificacion()
    parser = argparse.ArgumentParser(description="E1-08: precisión y recall de pares de la agrupación (calibración del umbral)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--etiquetas", type=Path, default=ETIQUETAS)
    reglas = cargar_reglas()
    parser.add_argument("--modelo", choices=sorted(cfg.modelos), default=reglas.agrupacion.modelo)
    parser.add_argument("--salida", type=Path, default=SALIDA_JSON)
    parser.add_argument("--curva", type=Path, default=SALIDA_CSV)
    args = parser.parse_args(argv)
    db.base_real_o_salir(args.base)    # C-06: la base de la demo nunca entra en una métrica
    if not args.etiquetas.exists():
        print(f"No existe {args.etiquetas}: sin etiquetas humanas no se calcula ninguna métrica", file=sys.stderr)
        return CODIGO_SIN_ETIQUETAS
    if not args.base.exists():
        print(f"No existe {args.base}: ejecute normalizacion, limpieza y clasificacion", file=sys.stderr)
        return 1
    cfg = cfg.model_copy(update={"modelo_activo": args.modelo})  # aquí "activo" es el modelo que se calibra
    z = cargar_carga().salida.z_intervalo_confianza
    try:
        informe = evaluar(args.base, args.etiquetas, cfg, reglas, z)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    escribir_salidas(informe, args.salida, args.curva)
    base, cv = informe["con_el_umbral_elegido"], informe["validacion_cruzada"]["agrupado"]
    print(f"modelo {informe['modelo']} · {informe['titulares_etiquetados']} titulares · {informe['pares_evaluados']} pares ({informe['pares_positivos']} positivos)")
    print(f"umbral elegido: {informe['umbral_elegido']} (en reglas_v1.3.yaml: {informe['umbral_configurado']}, modelo {informe['modelo_configurado']})")
    for nombre, m in (("con el umbral elegido (optimista)", base), ("validación cruzada (pliegues de prueba)", cv), ("línea base: titulares idénticos", informe["linea_base_titulares_identicos"])):
        print(f"{nombre}: precisión {m['precision']['n']}/{m['precision']['de']} IC95 {m['precision']['ic95']} · recall {m['recall']['n']}/{m['recall']['de']} IC95 {m['recall']['ic95']} · F1 {m['f1']}")
    print(f"falsos positivos: {informe['falsos_positivos']}")
    print(f"falsos negativos: {len(informe['falsos_negativos'])} pares")
    print(f"escrito: {args.salida} y {args.curva}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
