"""Calibración del clasificador logístico (D-121): C, umbral ``sin_tema`` y margen por validación cruzada.

Usa SOLO los textos de referencia de ``config/temas.yaml`` (descripción y ejemplos); no lee
``eval/etiquetas.csv``, así que el conjunto de evaluación no interviene en ninguna elección. No escribe ``config/``:
imprime los valores y una persona los pega en ``logistica`` de ``config/clasificacion.yaml``; un test los recalcula.

Uso: ``poetry run python -m eval.calibrar_logistico``.
"""

from __future__ import annotations

import sys

from src.clasificacion import datos_de_entrenamiento
from src.clasificacion_logistica import Calibracion, calibrar
from src.configuracion import cargar_clasificacion, cargar_temas
from src.embeddings import crear


def calcular() -> Calibracion:
    """Calibración con la configuración vigente y los embeddings del modelo activo."""
    cfg, temas = cargar_clasificacion(), cargar_temas()
    X, y = datos_de_entrenamiento(crear(cfg), temas)
    return calibrar(X, y, cfg.logistica)


def main() -> int:
    """CLI: imprime la calibración."""
    c = calcular()
    print(f"textos de entrenamiento: {c.n_textos} por tema {c.textos_por_tema}; pliegues: {c.pliegues}")
    for valor, f1 in c.macro_f1_por_c.items():
        print(f"  C = {valor:g}: macro-F1 de validación cruzada {f1:.4f}")
    print(f"regularizacion_c: {c.regularizacion_c}")
    print(f"umbral_sin_tema: {c.umbral_sin_tema}")
    print(f"margen_secundario: {c.margen_secundario}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
