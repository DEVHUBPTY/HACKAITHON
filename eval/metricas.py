"""Métricas de clasificación con numerador, denominador e intervalos de confianza (docs/protocolo_evaluacion.md).

* Precisión y recall por clase: proporciones ``k/n`` con intervalo de Wilson al 95 % (``src.clasificacion.proporcion``).
* F1 por clase = ``2·TP / (2·TP + FP + FN)``; **indefinido** (``None``) si la clase no aparece ni en las etiquetas ni en
  las predicciones: no se rellena con 0.
* Macro-F1 = media de los F1 definidos de las clases fijadas por quien llama (las que tienen soporte en las etiquetas).
* IC de macro-F1 y de las diferencias entre dos clasificadores: **bootstrap percentil pareado** (los mismos titulares
  remuestreados para los dos), con remuestreos, confianza y semilla de ``config/clasificacion.yaml`` (D-57).
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Any

import numpy as np

from src.clasificacion import proporcion
from src.configuracion import CriterioAB


def f1_de(tp: int, fp: int, fn: int) -> float | None:
    """F1 de una clase; ``None`` si no hay ni verdaderos ni predichos de esa clase."""
    denominador = 2 * tp + fp + fn
    return None if denominador == 0 else 2 * tp / denominador


def _indices(y: Sequence[str], clases: Sequence[str]) -> np.ndarray:
    mapa = {c: i for i, c in enumerate(clases)}
    return np.array([mapa[v] for v in y], dtype=np.int64)


def matriz_confusion(y_true: Sequence[str], y_pred: Sequence[str], clases: Sequence[str]) -> list[list[int]]:
    """``m[i][j]`` = titulares de la clase real ``i`` que se predijeron como ``j`` (filas = real, columnas = predicho)."""
    k = len(clases)
    m = np.zeros((k, k), dtype=np.int64)
    for t, p in zip(_indices(y_true, clases), _indices(y_pred, clases), strict=True):
        m[t, p] += 1
    return m.tolist()


def _f1_por_clase(t: np.ndarray, p: np.ndarray, k: int) -> np.ndarray:
    """F1 de cada una de las ``k`` clases (``nan`` si indefinido) para etiquetas ``t`` y predicciones ``p`` enteras."""
    tp = np.bincount(t[t == p], minlength=k)
    soporte = np.bincount(t, minlength=k)
    predichos = np.bincount(p, minlength=k)
    denominador = soporte + predichos            # = 2·TP + FP + FN
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(denominador == 0, np.nan, 2 * tp / denominador)


def _media(valores: np.ndarray) -> float:
    return float(np.nanmean(valores)) if not np.all(np.isnan(valores)) else float("nan")


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str], clases: Sequence[str]) -> float | None:
    """Media de los F1 definidos de ``clases``; ``None`` si ninguno está definido."""
    f1 = _f1_por_clase(_indices(y_true, list(clases)), _indices(y_pred, list(clases)), len(clases))
    resultado = _media(f1)
    return None if np.isnan(resultado) else resultado


def por_clase(y_true: Sequence[str], y_pred: Sequence[str], clases: Sequence[str], z: float) -> dict[str, dict[str, Any]]:
    """Precisión, recall y F1 de cada clase con numerador, denominador e IC de Wilson al 95 %."""
    m = np.array(matriz_confusion(y_true, y_pred, clases))
    salida: dict[str, dict[str, Any]] = {}
    for i, c in enumerate(clases):
        tp, fn, fp = int(m[i, i]), int(m[i].sum() - m[i, i]), int(m[:, i].sum() - m[i, i])
        f1 = f1_de(tp, fp, fn)
        salida[c] = {
            "soporte": tp + fn,
            "predichos": tp + fp,
            "precision": proporcion(tp, tp + fp, z),
            "recall": proporcion(tp, tp + fn, z),
            "f1": None if f1 is None else round(f1, 4),
        }
    return salida


def _remuestras(n: int, criterio: CriterioAB) -> np.ndarray:
    """Índices de cada remuestreo (``remuestreos`` × ``n``): los mismos para todo lo que se compare."""
    rng = np.random.default_rng(criterio.semilla)
    return rng.integers(0, n, size=(criterio.remuestreos, n))


def _percentiles(valores: np.ndarray, criterio: CriterioAB) -> list[float] | None:
    validos = valores[~np.isnan(valores)]
    if len(validos) == 0:
        return None
    alfa = (1 - criterio.confianza) / 2 * 100
    bajo, alto = np.percentile(validos, [alfa, 100 - alfa])
    return [round(float(bajo), 4), round(float(alto), 4)]


def macro_f1_con_ic(y_true: Sequence[str], y_pred: Sequence[str], clases: Sequence[str], criterio: CriterioAB) -> dict[str, Any]:
    """Macro-F1 con su IC de bootstrap percentil y el ``n`` sobre el que se calculó."""
    clases = list(clases)
    t, p = _indices(y_true, clases), _indices(y_pred, clases)
    puntual = macro_f1(y_true, y_pred, clases)
    muestras = _remuestras(len(t), criterio)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        valores = np.array([_media(_f1_por_clase(t[i], p[i], len(clases))) for i in muestras])
    return {
        "n": len(t),
        "macro_f1": None if puntual is None else round(puntual, 4),
        "ic95": _percentiles(valores, criterio),
        "remuestreos": criterio.remuestreos,
    }


def diferencia_con_ic(
    y_true: Sequence[str], y_a: Sequence[str], y_b: Sequence[str], clases: Sequence[str], criterio: CriterioAB
) -> dict[str, Any]:
    """Diferencia B − A de macro-F1 y de F1 por clase, con IC de bootstrap pareado (mismos remuestreos)."""
    clases = list(clases)
    t, a, b = _indices(y_true, clases), _indices(y_a, clases), _indices(y_b, clases)
    k = len(clases)
    muestras = _remuestras(len(t), criterio)
    macro, por_tema = [], []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i in muestras:
            fa, fb = _f1_por_clase(t[i], a[i], k), _f1_por_clase(t[i], b[i], k)
            macro.append(_media(fb) - _media(fa))
            por_tema.append(fb - fa)
        puntual_a, puntual_b = _f1_por_clase(t, a, k), _f1_por_clase(t, b, k)
        puntual = _media(puntual_b) - _media(puntual_a)
    por_tema_arr = np.array(por_tema)
    return {
        "n": len(t),
        "diferencia_macro_f1": None if np.isnan(puntual) else round(float(puntual), 4),
        "ic95": _percentiles(np.array(macro), criterio),
        "por_clase": {
            c: {
                "diferencia_f1": None if np.isnan(puntual_b[j] - puntual_a[j]) else round(float(puntual_b[j] - puntual_a[j]), 4),
                "ic95": _percentiles(por_tema_arr[:, j], criterio),
            }
            for j, c in enumerate(clases)
        },
        "remuestreos": criterio.remuestreos,
    }


def aplicar_criterio(
    y_true: Sequence[str], y_a: Sequence[str], y_b: Sequence[str], clases: Sequence[str], criterio: CriterioAB
) -> dict[str, Any]:
    """Criterio de D-21/D-57 fijado antes de medir: B solo si el IC95 de (macro-F1 B − A) excluye el cero **a favor
    de B** y ningún tema empeora de forma significativa (IC95 de su diferencia de F1 enteramente por debajo de 0).
    Si no, A por ser más simple."""
    d = diferencia_con_ic(y_true, y_a, y_b, clases, criterio)
    ic = d["ic95"]
    excluye_cero = ic is not None and (ic[0] > 0 or ic[1] < 0)
    empeoran = sorted(
        c for c, v in d["por_clase"].items() if v["ic95"] is not None and v["ic95"][1] < 0
    )
    elige_b = bool(ic is not None and ic[0] > 0 and not empeoran)
    if elige_b:
        motivo = "el IC95 de B − A excluye el cero a favor de B y ningún tema empeora de forma significativa"
    elif ic is None:
        motivo = "sin diferencia definida: se usa A"
    elif not excluye_cero:
        motivo = "el IC95 de B − A incluye el cero: no hay evidencia de que B mejore; se usa A por ser más simple"
    elif ic[1] < 0:
        motivo = "el IC95 de B − A excluye el cero pero a favor de A: se usa A"
    else:
        motivo = f"B mejora, pero empeoran significativamente: {', '.join(empeoran)}; se usa A"
    return {**d, "excluye_cero": excluye_cero, "temas_que_empeoran": empeoran, "decision": "B" if elige_b else "A", "motivo": motivo}
