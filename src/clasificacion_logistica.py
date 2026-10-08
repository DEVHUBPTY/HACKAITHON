"""Clasificador temático por regresión logística sobre los embeddings locales (D-121).

El método A (centroides) no puede aprender las fronteras entre economía, regulación y servicios públicos: cada tema es
un promedio. Este método ajusta una ``LogisticRegression`` de scikit-learn sobre los MISMOS embeddings e5.

* **Datos de entrenamiento:** solo los textos de referencia de ``config/temas.yaml`` (descripción y titulares de ejemplo), codificados con el rol ``tema``. Esos titulares están en ``config/ejemplos_excluidos.txt``,
  así que nunca entran en la evaluación. Las etiquetas humanas (``eval/etiquetas.csv``) NO se usan para entrenar,
  ni para elegir C, ni para fijar el umbral: no hay fuga.
* **Abstención:** si la probabilidad máxima no llega a ``umbral_sin_tema``, el resultado es ``sin_tema``.
* **Calibración** (``calibrar``): validación cruzada estratificada con semilla fija sobre los textos de referencia.
  C = la de la rejilla con mayor macro-F1 de validación cruzada (empate: la menor); umbral = percentil
  ``percentil_umbral`` de la probabilidad máxima, fuera de muestra, de los textos que la validación cruzada acierta;
  el margen del tema secundario, el ``percentil_margen`` de la brecha entre las dos mayores probabilidades.
  Los textos de referencia no traen ejemplos de «sin tema», así que el umbral no puede optimizarse contra ellos: es
  un percentil de confianza, igual que el del método A.
* Determinista: lbfgs sin aleatoriedad y pliegues con semilla fija.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedKFold

from src.configuracion import ConfigLogistica


@dataclass(frozen=True)
class ModeloLogistico:
    """Regresión logística ajustada y el orden de sus clases (el de ``temas.yaml``)."""

    modelo: LogisticRegression
    temas: list[str]


@dataclass(frozen=True)
class Calibracion:
    """Resultado de la validación cruzada: C elegida, umbral de abstención y el macro-F1 de cada C de la rejilla."""

    regularizacion_c: float
    umbral_sin_tema: float
    margen_secundario: float
    macro_f1_por_c: dict[float, float]
    n_textos: int
    textos_por_tema: dict[str, int]
    pliegues: int


def _ajustar(X: np.ndarray, y: list[str], c: float, cfg: ConfigLogistica) -> LogisticRegression:
    return LogisticRegression(
        C=c, class_weight=cfg.pesos_de_clase, max_iter=cfg.max_iter, random_state=cfg.semilla
    ).fit(X, y)


def entrenar(X: np.ndarray, y: list[str], temas: list[str], cfg: ConfigLogistica) -> ModeloLogistico:
    """Ajusta el modelo con la C de la configuración. ``y`` son ids de ``temas``; todos deben estar presentes."""
    faltan = sorted(set(temas) - set(y))
    if faltan:
        raise ValueError(f"sin textos de entrenamiento para: {faltan}")
    return ModeloLogistico(_ajustar(X, y, cfg.regularizacion_c, cfg), temas)


def probabilidades(modelo: ModeloLogistico, vectores: np.ndarray) -> np.ndarray:
    """Probabilidad de cada tema, columnas en el orden de ``modelo.temas`` (filas suman 1)."""
    crudas = modelo.modelo.predict_proba(vectores)
    columnas = {c: k for k, c in enumerate(modelo.modelo.classes_)}
    return crudas[:, [columnas[t] for t in modelo.temas]]


def _fuera_de_muestra(X: np.ndarray, y: list[str], c: float, cfg: ConfigLogistica) -> tuple[np.ndarray, np.ndarray]:
    """Probabilidades de cada texto cuando NO está en el entrenamiento (pliegues estratificados) y sus clases."""
    clases = np.array(sorted(set(y)))
    destino = np.zeros((len(y), len(clases)))
    pliegues = StratifiedKFold(n_splits=cfg.pliegues, shuffle=True, random_state=cfg.semilla)
    etiquetas = np.array(y)
    for entrenamiento, prueba in pliegues.split(X, etiquetas):
        m = _ajustar(X[entrenamiento], list(etiquetas[entrenamiento]), c, cfg)
        destino[prueba] = m.predict_proba(X[prueba])
    return destino, clases


def calibrar(X: np.ndarray, y: list[str], cfg: ConfigLogistica) -> Calibracion:
    """Elige C y el umbral ``sin_tema`` por validación cruzada estratificada (ver el docstring del módulo)."""
    macro: dict[float, float] = {}
    for c in cfg.rejilla_c:
        probas, clases = _fuera_de_muestra(X, y, c, cfg)
        macro[c] = float(f1_score(y, clases[probas.argmax(1)], average="macro"))
    mejor = max(macro.values())
    elegida = min(c for c, v in macro.items() if v >= mejor)        # empate: la regularización más fuerte
    probas, clases = _fuera_de_muestra(X, y, elegida, cfg)
    acierta = clases[probas.argmax(1)] == np.array(y)
    umbral = float(np.percentile(probas.max(1)[acierta], cfg.percentil_umbral))
    ordenadas = np.sort(probas[acierta], axis=1)
    margen = float(np.percentile(ordenadas[:, -1] - ordenadas[:, -2], cfg.percentil_margen))
    return Calibracion(
        regularizacion_c=elegida,
        umbral_sin_tema=round(umbral, cfg.decimales_umbral),
        margen_secundario=round(margen, cfg.decimales_umbral),
        macro_f1_por_c=macro,
        n_textos=len(y),
        textos_por_tema={t: int(sum(1 for e in y if e == t)) for t in sorted(set(y))},
        pliegues=cfg.pliegues,
    )
