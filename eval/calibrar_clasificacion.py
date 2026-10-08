"""Valores PROVISIONALES de los umbrales de clasificación (E1-07), con una regla fija y reproducible.

El umbral de "sin tema" y el margen del tema secundario dependen de la escala de similitud de cada modelo y método, y
la calibración correcta usa **etiquetas humanas** (``eval/etiquetas.csv``, E1-06), que todavía no existen. Mientras
tanto este módulo calcula, sobre los titulares **únicos** que el filtro de palabras clave no marcó como ruido
(los duplicados no pesan dos veces), una regla simple y declarada de antemano:

* ``umbral_sin_tema`` = percentil ``PERCENTIL_SIN_TEMA`` de la similitud máxima: el 5 % de titulares menos parecidos a
  cualquier tema se abstiene. Es un **supuesto**, no una medición de qué es "sin tema".
* ``margen_secundario`` = percentil ``PERCENTIL_MARGEN`` de la diferencia entre la mejor y la segunda similitud:
  el 25 % de titulares con la brecha más corta recibe un tema secundario.
* ``ruido_similitud.umbral`` (sugerido) = percentil ``PERCENTIL_SIN_TEMA`` de la similitud con los prototipos de Panamá.

También imprime, como **diagnóstico descriptivo**, el AUC con que esa similitud separa los titulares que el filtro de
palabras clave marcó (``fuera_de_temas`` o ``no_es_panama``) de los demás. Esas marcas son heurísticas por palabras
clave, **no etiquetas humanas**: el AUC dice si la señal podría servir, no cuán precisa es.

No escribe ``config/``: imprime los valores y una persona los pega en ``config/clasificacion.yaml``.
Uso: ``poetry run python -m eval.calibrar_clasificacion``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from src import db
from src.clasificacion import METODO_A, construir_referencias, puntuar, texto_de_entrada
from src.configuracion import RAIZ, cargar_clasificacion, cargar_normalizacion, cargar_ruido, cargar_temas
from src.embeddings import crear
from src.limpieza import Reglas

# Reglas de calibración declaradas aquí (no son parámetros del sistema: son el procedimiento provisional).
PERCENTIL_SIN_TEMA = 5
PERCENTIL_MARGEN = 25


def auc(positivos: np.ndarray, negativos: np.ndarray) -> float | None:
    """Probabilidad de que un positivo tenga MENOR similitud que un negativo (empates cuentan 0.5)."""
    if len(positivos) == 0 or len(negativos) == 0:
        return None
    menor = (positivos[:, None] < negativos[None, :]).sum()
    iguales = (positivos[:, None] == negativos[None, :]).sum()
    return float((menor + 0.5 * iguales) / (len(positivos) * len(negativos)))


def calcular(ruta_base: Path) -> dict[str, dict]:
    """Sugerencia por modelo y método (percentiles sobre titulares únicos no ruido) y AUC descriptivos."""
    cfg, temas, ruido = cargar_clasificacion(), cargar_temas(), cargar_ruido()
    reglas = Reglas.desde_config()
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = db.leer_tabla(con, "noticias", "id_noticia")
    finally:
        con.close()
    if any(f["titulo_limpio"] is None or f["es_ruido"] is None for f in filas):
        raise RuntimeError("ejecute primero `poetry run python -m src.limpieza`")
    unicos: dict[str, dict] = {}
    for f in filas:  # un titular repetido (varias URL) cuenta una vez; el motivo del primero decide su marca
        unicos.setdefault(f["titulo_limpio"], f)
    lista = list(unicos.values())
    textos = [texto_de_entrada(f["titulo_limpio"], f.get("descripcion"), cfg.usar_descripcion) for f in lista]
    utiles = [i for i, f in enumerate(lista) if not f["es_ruido"]]
    fuera = [i for i, f in enumerate(lista) if f["motivo_ruido"] == "fuera_de_temas"]
    no_panama = [i for i, f in enumerate(lista) if f["motivo_ruido"] == "no_es_panama"]
    resultado: dict[str, dict] = {"n": {"titulares_unicos": len(lista), "utiles": len(utiles), "fuera_de_temas": len(fuera), "no_es_panama": len(no_panama)}}
    for nombre in cfg.modelos:
        emb = crear(cfg, nombre)
        ref = construir_referencias(emb, temas, reglas)
        vectores = emb.codificar(textos, "titular")
        por_metodo = {}
        for metodo in (METODO_A,):
            sim = puntuar(vectores, ref, metodo).similitud
            orden = np.sort(sim, axis=1)
            maxima, brecha = orden[:, -1], orden[:, -1] - orden[:, -2]
            por_metodo[metodo] = {
                "umbral_sin_tema": round(float(np.percentile(maxima[utiles], PERCENTIL_SIN_TEMA)), 3),
                "margen_secundario": round(float(np.percentile(brecha[utiles], PERCENTIL_MARGEN)), 3),
                "auc_fuera_de_temas_vs_utiles": auc(maxima[fuera], maxima[utiles]),
            }
        panama = (vectores @ emb.codificar(ruido.similitud_prototipo.prototipos, "tema").T).max(axis=1)
        resultado[nombre] = {
            **por_metodo,
            "ruido_similitud_umbral_sugerido": round(float(np.percentile(panama[utiles], PERCENTIL_SIN_TEMA)), 3),
            "auc_no_es_panama_vs_utiles": auc(panama[no_panama], panama[utiles]),
        }
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E1-07: valores provisionales de umbrales (no escribe config/)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    args = parser.parse_args(argv)
    if not args.base.exists():
        print(f"No existe {args.base}: ejecute normalización y limpieza primero.", file=sys.stderr)
        return 1
    try:
        resultado = calcular(args.base)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"n: {resultado['n']}")
    for nombre, valores in resultado.items():
        if nombre == "n":
            continue
        print(f"\n{nombre}")
        for metodo in (METODO_A,):
            v = valores[metodo]
            auc_v = "n/d" if v["auc_fuera_de_temas_vs_utiles"] is None else f"{v['auc_fuera_de_temas_vs_utiles']:.3f}"
            print(f"  {metodo}: umbral_sin_tema {v['umbral_sin_tema']}  margen_secundario {v['margen_secundario']}  (AUC fuera_de_temas vs útiles {auc_v})")
        auc_p = valores["auc_no_es_panama_vs_utiles"]
        print(f"  ruido por similitud: umbral sugerido {valores['ruido_similitud_umbral_sugerido']}  (AUC no_es_panama vs útiles {'n/d' if auc_p is None else f'{auc_p:.3f}'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
