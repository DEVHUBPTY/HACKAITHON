"""Métricas de clasificación con numerador, denominador e intervalos de confianza (docs/protocolo_evaluacion.md).

* ``clases`` son TODAS las clases posibles (etiquetas y predicciones); una etiqueta o predicción fuera de ellas es
  un error.
* Precisión y recall por clase: proporciones ``k/n`` con intervalo de Wilson al 95 % (``src.clasificacion.proporcion``),
  siempre sin ponderar (el peso de muestreo no es un conteo de titulares).
* F1 por clase = ``2·TP / (2·TP + FP + FN)``; **indefinido** (``None``) si la clase no aparece ni en las etiquetas ni en
  las predicciones: no se rellena con 0.
* Macro-F1 = media de los F1 definidos de las clases **con soporte en las etiquetas**. Una clase que solo se predice no
  entra en el promedio, pero sus falsos positivos ya restaron recall a las clases verdaderas.
* Con ``pesos`` (``peso_muestreo`` de E1-06) cada titular cuenta con su peso; sin ellos, con 1.
* IC de macro-F1 y de las diferencias entre dos clasificadores: **bootstrap percentil pareado** (los mismos titulares
  remuestreados para los dos), con remuestreos, confianza y semilla de ``config/clasificacion.yaml`` (D-57). Las
  decisiones usan los límites **sin redondear** (``ic95_exacto``); ``ic95`` está redondeado solo para mostrarse.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Any

import numpy as np

from src.clasificacion import proporcion
from src.configuracion import CriterioAB

DECIMALES_PRESENTACION = 4  # solo presentación: ninguna decisión usa valores redondeados


def f1_de(tp: float, fp: float, fn: float) -> float | None:
    """F1 de una clase; ``None`` si no hay ni verdaderos ni predichos de esa clase."""
    denominador = 2 * tp + fp + fn
    return None if denominador == 0 else 2 * tp / denominador


def _indices(y: Sequence[str], clases: Sequence[str]) -> np.ndarray:
    mapa = {c: i for i, c in enumerate(clases)}
    desconocidas = sorted({v for v in y if v not in mapa})
    if desconocidas:
        raise ValueError(f"etiquetas o predicciones fuera de clases: {desconocidas} (clases: {list(clases)})")
    return np.array([mapa[v] for v in y], dtype=np.int64)


def matriz_confusion(y_true: Sequence[str], y_pred: Sequence[str], clases: Sequence[str]) -> list[list[int]]:
    """``m[i][j]`` = titulares de la clase real ``i`` que se predijeron como ``j`` (filas = real, columnas = predicho)."""
    k = len(clases)
    m = np.zeros((k, k), dtype=np.int64)
    for t, p in zip(_indices(y_true, clases), _indices(y_pred, clases), strict=True):
        m[t, p] += 1
    return m.tolist()


def _f1_por_clase(t: np.ndarray, p: np.ndarray, k: int, w: np.ndarray | None = None) -> np.ndarray:
    """F1 de cada una de las ``k`` clases (``nan`` si indefinido), con pesos opcionales ``w`` por titular."""
    acierto = t == p
    tp = np.bincount(t[acierto], weights=None if w is None else w[acierto], minlength=k)
    soporte = np.bincount(t, weights=w, minlength=k)
    predichos = np.bincount(p, weights=w, minlength=k)
    denominador = soporte + predichos            # = 2·TP + FP + FN
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(denominador == 0, np.nan, 2 * tp / denominador)


def _media(valores: np.ndarray) -> float:
    return float(np.nanmean(valores)) if not np.all(np.isnan(valores)) else float("nan")


def _con_soporte(t: np.ndarray, k: int) -> np.ndarray:
    """Máscara de las clases que aparecen en las etiquetas de la muestra completa (las del promedio macro)."""
    return np.bincount(t, minlength=k) > 0


def _pesos(pesos: Sequence[float] | None, n: int) -> np.ndarray | None:
    if pesos is None:
        return None
    w = np.asarray(pesos, dtype=float)
    if len(w) != n or np.any(w <= 0) or not np.all(np.isfinite(w)):
        raise ValueError("pesos: uno por titular y todos positivos")
    return w


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str], clases: Sequence[str], pesos: Sequence[float] | None = None) -> float | None:
    """Media de los F1 definidos de las clases con soporte en ``y_true``; ``None`` si ninguno está definido."""
    clases = list(clases)
    t, p = _indices(y_true, clases), _indices(y_pred, clases)
    f1 = _f1_por_clase(t, p, len(clases), _pesos(pesos, len(t)))
    resultado = _media(f1[_con_soporte(t, len(clases))])
    return None if np.isnan(resultado) else resultado


def por_clase(y_true: Sequence[str], y_pred: Sequence[str], clases: Sequence[str], z: float) -> dict[str, dict[str, Any]]:
    """Precisión, recall y F1 de cada clase con numerador, denominador e IC de Wilson al 95 % (sin ponderar)."""
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
            "f1": None if f1 is None else round(f1, DECIMALES_PRESENTACION),
        }
    return salida


def exactitud_ponderada(y_true: Sequence[str], y_pred: Sequence[str], pesos: Sequence[float]) -> dict[str, Any]:
    """Proporción de titulares acertados contando cada uno con su peso (sin IC: el peso no es un conteo)."""
    w = _pesos(pesos, len(y_true))
    acierto = np.array([a == b for a, b in zip(y_true, y_pred, strict=True)])
    total, k = float(w.sum()), float(w[acierto].sum())
    return {
        "suma_pesos_aciertos": round(k, DECIMALES_PRESENTACION),
        "suma_pesos": round(total, DECIMALES_PRESENTACION),
        "proporcion": round(k / total, DECIMALES_PRESENTACION),
        "n": len(w),
    }


def _remuestras(n: int, criterio: CriterioAB) -> np.ndarray:
    """Índices de cada remuestreo (``remuestreos`` × ``n``): los mismos para todo lo que se compare."""
    rng = np.random.default_rng(criterio.semilla)
    return rng.integers(0, n, size=(criterio.remuestreos, n))


def _percentiles_exactos(valores: np.ndarray, criterio: CriterioAB) -> list[float] | None:
    validos = valores[~np.isnan(valores)]
    if len(validos) == 0:
        return None
    alfa = (1 - criterio.confianza) / 2 * 100
    bajo, alto = np.percentile(validos, [alfa, 100 - alfa])
    return [float(bajo), float(alto)]


def _redondear(ic: list[float] | None) -> list[float] | None:
    return None if ic is None else [round(ic[0], DECIMALES_PRESENTACION), round(ic[1], DECIMALES_PRESENTACION)]


def macro_f1_con_ic(
    y_true: Sequence[str], y_pred: Sequence[str], clases: Sequence[str], criterio: CriterioAB, pesos: Sequence[float] | None = None
) -> dict[str, Any]:
    """Macro-F1 (clases con soporte) con su IC de bootstrap percentil y el ``n`` sobre el que se calculó."""
    clases = list(clases)
    t, p = _indices(y_true, clases), _indices(y_pred, clases)
    w = _pesos(pesos, len(t))
    k = len(clases)
    mascara = _con_soporte(t, k)
    puntual = macro_f1(y_true, y_pred, clases, pesos)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        valores = np.array(
            [_media(_f1_por_clase(t[i], p[i], k, None if w is None else w[i])[mascara]) for i in _remuestras(len(t), criterio)]
        )
    exacto = _percentiles_exactos(valores, criterio)
    return {
        "n": len(t),
        "macro_f1": None if puntual is None else round(puntual, DECIMALES_PRESENTACION),
        "ic95": _redondear(exacto),
        "ic95_exacto": exacto,
        "remuestreos": criterio.remuestreos,
        "ponderado": w is not None,
    }


def diferencia_con_ic(
    y_true: Sequence[str], y_a: Sequence[str], y_b: Sequence[str], clases: Sequence[str], criterio: CriterioAB
) -> dict[str, Any]:
    """Diferencia B − A de macro-F1 y de F1 por clase, con IC de bootstrap pareado (mismos remuestreos)."""
    clases = list(clases)
    t, a, b = _indices(y_true, clases), _indices(y_a, clases), _indices(y_b, clases)
    k = len(clases)
    mascara = _con_soporte(t, k)
    macro, por_tema = [], []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i in _remuestras(len(t), criterio):
            fa, fb = _f1_por_clase(t[i], a[i], k), _f1_por_clase(t[i], b[i], k)
            macro.append(_media(fb[mascara]) - _media(fa[mascara]))
            por_tema.append(fb - fa)
        puntual_a, puntual_b = _f1_por_clase(t, a, k), _f1_por_clase(t, b, k)
        puntual = _media(puntual_b[mascara]) - _media(puntual_a[mascara])
    por_tema_arr = np.array(por_tema)
    exacto = _percentiles_exactos(np.array(macro), criterio)
    clases_salida = {}
    for j, c in enumerate(clases):
        ic_clase = _percentiles_exactos(por_tema_arr[:, j], criterio)
        diferencia = puntual_b[j] - puntual_a[j]
        clases_salida[c] = {
            "soporte": bool(mascara[j]),
            "diferencia_f1": None if np.isnan(diferencia) else round(float(diferencia), DECIMALES_PRESENTACION),
            "ic95": _redondear(ic_clase),
            "ic95_exacto": ic_clase,
        }
    return {
        "n": len(t),
        "diferencia_macro_f1": None if np.isnan(puntual) else round(float(puntual), DECIMALES_PRESENTACION),
        "ic95": _redondear(exacto),
        "ic95_exacto": exacto,
        "por_clase": clases_salida,
        "remuestreos": criterio.remuestreos,
    }


def criterio_elige_b(ic_exacto: list[float] | None, empeoran: Sequence[str]) -> bool:
    """Regla de D-21/D-57 sobre límites **sin redondear**: el IC de B − A queda enteramente sobre cero y ningún tema empeora."""
    return bool(ic_exacto is not None and ic_exacto[0] > 0 and not empeoran)


def aplicar_criterio(
    y_true: Sequence[str], y_a: Sequence[str], y_b: Sequence[str], clases: Sequence[str], criterio: CriterioAB
) -> dict[str, Any]:
    """Criterio de D-21/D-57 fijado antes de medir: B solo si el IC95 de (macro-F1 B − A) excluye el cero **a favor
    de B** y ningún tema con soporte empeora de forma significativa (IC95 de su diferencia de F1 enteramente por
    debajo de 0). Si no, A por ser más simple."""
    d = diferencia_con_ic(y_true, y_a, y_b, clases, criterio)
    ic = d["ic95_exacto"]
    excluye_cero = ic is not None and (ic[0] > 0 or ic[1] < 0)
    empeoran = sorted(
        c for c, v in d["por_clase"].items() if v["soporte"] and v["ic95_exacto"] is not None and v["ic95_exacto"][1] < 0
    )
    elige_b = criterio_elige_b(ic, empeoran)
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
