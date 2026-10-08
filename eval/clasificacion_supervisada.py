"""C-10b: modelo supervisado EXPLORATORIO para el tema (regresión logística sobre los embeddings e5), medido por evento.

**No está conectado a producción**: el clasificador de la canalización sigue siendo el método A (``src/clasificacion.py``).
Este módulo solo responde, con las etiquetas humanas que existen, si un modelo entrenado supera al método A y al mejor
baseline por palabras clave, y con qué incertidumbre.

* Entrada: los mismos embeddings e5 de la canalización (``src/embeddings.py``) del texto que usa el clasificador.
* Modelo: ``LogisticRegression`` con pesos de clase balanceados; valores en ``config/clasificacion.yaml`` (``supervisado``).
* Clases: los 6 temas y ``sin_tema``. ``sin_tema`` se trata como una clase más (como en ``eval.clasificacion``, donde una fila
  que la persona marcó como ruido tiene la etiqueta de oro ``sin_tema``); el YAML puede excluirla. Una clase con menos de
  ``min_eventos_por_clase`` eventos **no se entrena ni se evalúa** (no queda un evento para entrenar mientras se prueba otro) y
  se reporta aparte, con el recall del método A y del baseline sobre esas filas.
* Sin fuga: validación cruzada **agrupada por evento** (``diagnostico_temas.pliegues_por_evento``), repetida; ningún evento
  está en el entrenamiento y la prueba de un mismo pliegue (``verificar_sin_fuga`` lo comprueba en cada pliegue).
* Solo etiquetas ``origen = humano`` (D-101); los ejemplos de ``temas.yaml`` no entran.
* Comparación pareada por evento con bootstrap sobre eventos (exactitud, macro-F1 y recall por tema) y el criterio de D-57
  adaptado a eventos: el IC de la diferencia de macro-F1 debe excluir el cero a favor y ningún tema puede empeorar de forma
  significativa (IC del recall por evento enteramente por debajo de cero).

El resultado es **exploratorio**: ≈ 29 eventos, una sola persona etiquetó y las clases pequeñas no se pueden aprender.
Uso: ``HF_HUB_OFFLINE=1 poetry run python -m eval.clasificacion_supervisada`` → ``outputs/clasificacion_supervisada.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression

from eval import clasificacion as evalclas
from eval import clasificacion_por_evento as pe
from eval import diagnostico_temas as dg
from src.baseline import SIN_TEMA
from src.clasificacion import proporcion
from src.configuracion import (
    RAIZ,
    ConfigClasificacion,
    ConfigTemas,
    CriterioAB,
    SupervisadoClasificacion,
    cargar_carga,
    cargar_clasificacion,
    cargar_normalizacion,
    cargar_temas,
)

SALIDA = RAIZ / "outputs" / "clasificacion_supervisada.json"
ADVERTENCIA = (
    "EXPLORATORIO y NO está conectado a producción: la canalización sigue usando el método A. ≈ 29 eventos, una sola persona "
    "etiquetó (D-85), censo del estrato «no ruido» del snapshot anterior; las clases con pocos eventos no se pueden aprender."
)

Ajustar = Callable[[np.ndarray, np.ndarray, np.ndarray, SupervisadoClasificacion], np.ndarray]


# ------------------------------------------------------------------ clases y modelo


def clases_entrenables(y: np.ndarray, eventos: Sequence[str], minimo: int, sin_tema: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """``(incluidas, excluidas)``: una clase con menos de ``minimo`` eventos (o ``sin_tema`` si el YAML la excluye) se reporta aparte."""
    incluidas: list[str] = []
    excluidas: dict[str, dict[str, Any]] = {}
    for c in dict.fromkeys(y):
        filas = [k for k, r in enumerate(y) if r == c]
        n_eventos = len({eventos[k] for k in filas})
        if c == SIN_TEMA and sin_tema == "excluir":
            excluidas[str(c)] = {"filas": len(filas), "eventos": n_eventos, "motivo": "excluida por configuración (supervisado.sin_tema = excluir)"}
        elif n_eventos < minimo:
            excluidas[str(c)] = {"filas": len(filas), "eventos": n_eventos, "motivo": f"menos de {minimo} eventos"}
        else:
            incluidas.append(str(c))
    return incluidas, excluidas


def crear_modelo(s: SupervisadoClasificacion) -> LogisticRegression:
    """Regresión logística con los valores del YAML (``random_state`` = semilla del bloque)."""
    return LogisticRegression(C=s.C, class_weight=s.class_weight, max_iter=s.max_iter, random_state=s.semilla)


def ajustar_y_predecir(x_entrenamiento: np.ndarray, y_entrenamiento: np.ndarray, x_prueba: np.ndarray, s: SupervisadoClasificacion) -> np.ndarray:
    """Entrena con el pliegue de entrenamiento y predice el de prueba. Con una sola clase en el entrenamiento, devuelve esa."""
    clases = np.unique(y_entrenamiento)
    if len(clases) == 1:
        return np.array([clases[0]] * len(x_prueba), dtype=object)
    modelo = crear_modelo(s).fit(x_entrenamiento, y_entrenamiento.astype(str))
    return np.asarray(modelo.predict(x_prueba), dtype=object)


def verificar_sin_fuga(eventos: Sequence[str], entrenamiento: np.ndarray, prueba: np.ndarray) -> None:
    """Lanza ``ValueError`` si algún evento está a la vez en el entrenamiento y en la prueba (fuga entre duplicados)."""
    comunes = {eventos[i] for i in entrenamiento} & {eventos[i] for i in prueba}
    if comunes:
        raise ValueError(f"fuga: {len(comunes)} evento(s) en el entrenamiento y en la prueba a la vez")


def validacion_cruzada(
    X: np.ndarray, y: np.ndarray, eventos: Sequence[str], s: SupervisadoClasificacion, ajustar: Ajustar = ajustar_y_predecir
) -> np.ndarray:
    """Predicciones fuera de muestra, ``repeticiones × filas``: cada repetición parte los EVENTOS de otra manera."""
    predicho = np.empty((s.repeticiones, len(y)), dtype=object)
    for rep in range(s.repeticiones):
        for entrenamiento, prueba in dg.pliegues_por_evento(list(eventos), s.pliegues, s.semilla + rep):
            verificar_sin_fuga(eventos, entrenamiento, prueba)
            predicho[rep, prueba] = ajustar(X[entrenamiento], y[entrenamiento], X[prueba], s)
    return predicho


# ------------------------------------------------------------------ comparación


def mejor_baseline(preds: dict[str, np.ndarray], real: np.ndarray, eventos: Sequence[str], criterio: CriterioAB) -> str:
    """El baseline de mayor exactitud por evento (empate: el primero, ``baseline_guia``). Se elige con las mismas etiquetas: favorece al baseline."""
    mejor, valor = "", -1.0
    for nombre, p in preds.items():
        v = dg.exactitud_por_evento(p == real, list(eventos), criterio)["valor"]
        if v > valor:
            mejor, valor = nombre, v
    return mejor


def criterio_d57(dif_macro_f1: dict[str, Any], dif_por_tema: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    """D-57 adaptado a eventos: el IC de la diferencia de macro-F1 excluye el cero a favor y ningún tema empeora de forma significativa."""
    empeoran = [t for t, d in dif_por_tema.items() if d is not None and d["ic95"] is not None and d["ic95"][1] < 0]
    ic = dif_macro_f1["ic95"]
    a_favor = bool(dif_macro_f1.get("a_favor"))
    if ic is None:
        motivo = "la diferencia de macro-F1 no está definida"
    elif not a_favor:
        motivo = f"el IC 95 % de la diferencia de macro-F1 {ic} no excluye el cero a favor"
    elif empeoran:
        motivo = f"el macro-F1 mejora, pero empeoran de forma significativa: {empeoran}"
    else:
        motivo = f"el IC 95 % de la diferencia de macro-F1 {ic} excluye el cero a favor y ningún tema empeora de forma significativa"
    return {"cumplido": bool(a_favor and not empeoran), "motivo": motivo, "temas_que_empeoran": empeoran}


def _diferencias_por_tema(
    real: np.ndarray, preds_a: np.ndarray, preds_b: np.ndarray, eventos: Sequence[str], clases: Sequence[str], criterio: CriterioAB, min_eventos_ic: int
) -> dict[str, dict[str, Any] | None]:
    salida: dict[str, dict[str, Any] | None] = {}
    for c in clases:
        filas = np.flatnonzero(real == c)
        ev = [eventos[k] for k in filas]
        salida[c] = None
        if len(filas) and len(set(ev)) >= min_eventos_ic:
            salida[c] = dg.diferencia_por_evento((preds_a[:, filas] == c).mean(axis=0), (preds_b[:, filas] == c).mean(axis=0), ev, criterio)
    return salida


def _comparar(
    nombre_b: str, real: np.ndarray, sup_preds: np.ndarray, otro: np.ndarray, sistemas: dict[str, Any], eventos: Sequence[str],
    clases: Sequence[str], entrenadas: Sequence[str], cfg: ConfigClasificacion,
) -> dict[str, Any]:
    """Supervisado − ``otro`` (método A o mejor baseline), pareado por evento."""
    criterio = cfg.criterio_ab
    d_exact = dg.diferencia_por_evento(otro[0] == real, (sup_preds == real).mean(axis=0), list(eventos), criterio)
    d_f1 = pe.diferencia_macro_f1_por_evento(real, otro, sup_preds, eventos, clases, criterio)
    por_tema = _diferencias_por_tema(real, otro, sup_preds, eventos, entrenadas, criterio, cfg.por_evento.min_eventos_ic)
    s, o = sistemas["supervisado"], sistemas[nombre_b]
    return {
        "exactitud_por_evento": d_exact,
        "macro_f1": d_f1,
        "recall_por_tema": por_tema,
        "criterio_d57": criterio_d57(d_f1, por_tema),
        "ic_se_solapan": {
            "exactitud_por_evento": pe.se_solapan(s["exactitud_por_evento"]["ic95"], o["exactitud_por_evento"]["ic95"]),
            "macro_f1": pe.se_solapan(s["macro_f1_por_evento"]["ic95"], o["macro_f1_por_evento"]["ic95"]),
        },
    }


def evaluar_supervisado(conj: pe.Conjunto, cfg: ConfigClasificacion, temas: ConfigTemas, z: float) -> dict[str, Any]:
    """Informe completo (sin escribir nada): supervisado frente al método A activo y al mejor baseline, en los mismos eventos."""
    s, criterio, min_ic = cfg.supervisado, cfg.criterio_ab, cfg.por_evento.min_eventos_ic
    incluidas, excluidas = clases_entrenables(conj.y, conj.eventos, s.min_eventos_por_clase, s.sin_tema)
    todas = pe.predicciones_de_sistemas(conj, cfg, temas)
    clave_a = next(n for n in todas if "(activo)" in n)
    baselines = {n: p for n, p in todas.items() if n.startswith("baseline_")}
    en = np.isin(conj.y, incluidas)
    y = conj.y[en]
    eventos = [e for e, d in zip(conj.eventos, en, strict=True) if d]
    sup_preds = validacion_cruzada(conj.X[en], y, eventos, s)
    pred_a = todas[clave_a][en][None, :]
    mejor = mejor_baseline({n: p[en] for n, p in baselines.items()}, y, eventos, criterio)
    pred_b = baselines[mejor][en][None, :]
    clases = conj.clases
    sistemas = {
        "supervisado": pe.evaluar_sistema(y, sup_preds, eventos, clases, criterio, z, min_ic),
        "metodo_A_activo": pe.evaluar_sistema(y, pred_a, eventos, clases, criterio, z, min_ic),
        mejor: pe.evaluar_sistema(y, pred_b, eventos, clases, criterio, z, min_ic),
    }
    comparaciones = {
        "supervisado_menos_metodo_A_activo": _comparar("metodo_A_activo", y, sup_preds, pred_a, sistemas, eventos, clases, incluidas, cfg),
        "supervisado_menos_mejor_baseline": _comparar(mejor, y, sup_preds, pred_b, sistemas, eventos, clases, incluidas, cfg),
    }
    for c, info in excluidas.items():
        filas = conj.y == c
        info["recall_metodo_A"] = proporcion(int((todas[clave_a][filas] == c).sum()), int(filas.sum()), z)
        info["recall_mejor_baseline"] = proporcion(int((baselines[mejor][filas] == c).sum()), int(filas.sum()), z)
        info["supervisado"] = "no entrenable: sin eventos suficientes para entrenar mientras se prueba otro"
    acierto_rep = (sup_preds == y).mean(axis=1)
    return {
        "modelo": "regresion_logistica",
        "entrada": f"embeddings {cfg.modelo_activo} de la canalización",
        "exploratorio": True,
        "conectado_a_produccion": False,
        "advertencia": ADVERTENCIA,
        "hiperparametros": s.model_dump(),
        "bootstrap": {"remuestreos": criterio.remuestreos, "confianza": criterio.confianza, "semilla": criterio.semilla, "unidad": "evento"},
        "conjunto": {
            "origenes": ["humano"],
            "usa_etiquetas_provisionales": False,
            "filas_totales": len(conj.y),
            "eventos_totales": len(set(conj.eventos)),
            "filas_evaluadas": int(en.sum()),
            "eventos_evaluados": len(set(eventos)),
            "ejemplos_excluidos_descartados": conj.excluidos_descartados,
            "filas_por_tema": dict(Counter(conj.y)),
            "tratamiento_sin_tema": s.sin_tema,
        },
        "clases": {
            "entrenadas": incluidas,
            "excluidas": excluidas,
            "eventos_por_clase": {c: len({eventos[k] for k in np.flatnonzero(y == c)}) for c in incluidas},
        },
        "mejor_baseline": mejor,
        "nota_mejor_baseline": "elegido por exactitud por evento con las mismas etiquetas: favorece al baseline",
        "sistemas": sistemas,
        "comparaciones": comparaciones,
        "variacion_entre_repeticiones": {
            "exactitud_por_fila_minima": round(float(acierto_rep.min()), 4),
            "exactitud_por_fila_maxima": round(float(acierto_rep.max()), 4),
            "repeticiones": s.repeticiones,
        },
    }


# ------------------------------------------------------------------ impresión (solo cifras)


def imprimir(r: dict[str, Any]) -> list[str]:
    c, k = r["conjunto"], r["clases"]
    lineas = [
        f"== Modelo supervisado EXPLORATORIO (no conectado a producción) · {c['filas_evaluadas']} de {c['filas_totales']} filas, {c['eventos_evaluados']} de {c['eventos_totales']} eventos ==",
        r["advertencia"],
        f"Entrenadas: {k['entrenadas']} (eventos {k['eventos_por_clase']}). Excluidas: "
        + "; ".join(f"{t} ({v['filas']} filas, {v['eventos']} eventos; {v['motivo']}; recall A {v['recall_metodo_A']['n']}/{v['recall_metodo_A']['de']}, baseline {v['recall_mejor_baseline']['n']}/{v['recall_mejor_baseline']['de']})" for t, v in k["excluidas"].items()),
    ]
    for n, s in r["sistemas"].items():
        m = s["macro_f1_por_evento"]
        lineas.append(
            f"[{n}] exactitud filas {pe._p(s['exactitud_por_fila'])}; eventos {pe._ic(s['exactitud_por_evento'])}; macro-F1 {m['valor']} IC95 {m['ic95']}"
        )
        for t, v in s["recall_por_tema"].items():
            ic = "sin IC (un evento)" if v["ic95"] is None else f"IC95 {v['ic95']}"
            lineas.append(f"    recall {t}: filas {v['filas']['n']}/{v['filas']['de']}; por evento {v['recall_por_evento']:.3f} {ic} ({v['eventos']} eventos)")
    for n, d in r["comparaciones"].items():
        e, f, d57 = d["exactitud_por_evento"], d["macro_f1"], d["criterio_d57"]
        lineas.append(
            f"{n}: Δ exactitud {e['diferencia']:+} IC95 {e['ic95']} (excluye cero: {e['excluye_cero']}); Δ macro-F1 {f['diferencia']} IC95 {f['ic95']} "
            f"(excluye cero: {f['excluye_cero']}); IC solapados {d['ic_se_solapan']}; D-57 {'CUMPLIDO' if d57['cumplido'] else 'NO cumplido'}: {d57['motivo']}"
        )
        for t, x in d["recall_por_tema"].items():
            lineas.append(f"    Δ recall {t}: " + ("sin IC (menos eventos que el mínimo)" if x is None else f"{x['diferencia']:+} IC95 {x['ic95']} ({x['eventos']} eventos)"))
    v = r["variacion_entre_repeticiones"]
    lineas.append(f"Variación entre {v['repeticiones']} repeticiones (exactitud por fila): {v['exactitud_por_fila_minima']}–{v['exactitud_por_fila_maxima']}")
    return lineas


def main(argv: list[str] | None = None) -> int:
    """CLI: imprime las cifras y escribe ``outputs/clasificacion_supervisada.json``."""
    parser = argparse.ArgumentParser(description="C-10b: modelo supervisado exploratorio con validación cruzada por evento")
    parser.add_argument("--etiquetas", type=Path, default=evalclas.ETIQUETAS)
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    if not args.etiquetas.exists() or not args.base.exists():
        print(f"Faltan {args.etiquetas} o {args.base}: no se calcula nada (no se inventan métricas).", file=sys.stderr)
        return evalclas.CODIGO_SIN_ETIQUETAS
    cfg, temas = cargar_clasificacion(), cargar_temas()
    informe = evaluar_supervisado(pe.cargar_conjunto(args.etiquetas, args.base, cfg, temas), cfg, temas, cargar_carga().salida.z_intervalo_confianza)
    print("\n".join(imprimir(informe)))
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
