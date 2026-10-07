"""E1-18 · D-66: la IA contra su línea base en clasificación, agrupación, búsqueda y ranking, con n e IC95.

Todo número de ``docs/ia_vs_baseline.md`` sale de este módulo (``outputs/ia_vs_baseline.json``); nada se teclea a mano.

* **Clasificación:** línea base de palabras clave (``src/baseline.py``, variante ``guia``) contra el clasificador por
  embeddings activo (modelo y método de ``config/clasificacion.yaml``), sobre las etiquetas humanas de ``eval/etiquetas.csv``.
  Comparación **pareada** (los mismos titulares): macro-F1 y F1 por tema con bootstrap pareado y los casos discordantes
  (la IA acierta y la base falla, y al revés) con sus IDs.
* **Agrupación:** embeddings con umbral calibrado contra «unir solo titulares idénticos», sobre pares. La cifra honesta de la IA
  es la de la **validación cruzada agrupada** (la calibración no vio los pares de prueba); la del umbral elegido sobre las mismas
  etiquetas es optimista. El IC se calcula con **bootstrap por titular** (se remuestrean titulares, no pares), porque los pares
  comparten titulares y los pares de un grupo no son independientes.
* **Búsqueda:** Recall@5 por IDs de la búsqueda semántica contra BM25 sobre el benchmark de desarrollo (las reglas de búsqueda se
  escribieron viendo esas consultas), con bootstrap pareado sobre consultas.
* **Ranking:** el ranking es código determinista (reglas v1.3), no un LLM. Su utilidad (Precision@5 contra la selección de un
  editor independiente) **no se mide aquí**: ``eval/seleccion_editor.csv`` existe pero es una selección **provisional del asistente**
  (D-101; se rehace a mano en C-09) y su Precision@5 está en ``outputs/precision_at_5.json``, rotulada como tal. Aquí solo
  hay hechos descriptivos: solapamiento del top 5 con el de «más reciente primero» y ejemplos de grupos que difieren.

**Veredicto (D-21/D-57):** una diferencia está «demostrada» solo si el IC95 de la diferencia pareada excluye el cero.

Uso: ``poetry run python -m eval.ia_vs_baseline [--salida outputs/ia_vs_baseline.json]``. Sin red y sin LLM (modelos de embeddings locales).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import comb
from pathlib import Path
from typing import Any

import numpy as np

from eval import metricas
from src.configuracion import RAIZ, CriterioAB, cargar_benchmark, cargar_clasificacion

SALIDA = RAIZ / "outputs" / "ia_vs_baseline.json"
EJEMPLOS_POR_CASO = 5          # el spec pide de 3 a 5 ejemplos de cada caso (docs/ia_vs_baseline.md, E1-18)
TAMANO_TOP = 5                 # top del ranking que se compara (el del Precision@5 de E1-19)
SOPORTE_MINIMO_TEMA = 5        # supuesto: un tema con menos titulares humanos no permite un veredicto por tema (un IC con n = 1 se degenera)
LARGO_TEXTO_ID = 110           # caracteres del texto de un registro citado en un ejemplo (solo presentación)
DECIMALES = 4                  # solo presentación

VEREDICTOS = ("gana_ia", "sin_diferencia_demostrable", "pierde_ia", "no_medible")


# ============================================================================================ funciones puras


def veredicto_por_ic(ic: Sequence[float] | None) -> str:
    """Regla de D-21/D-57 sobre límites sin redondear: ``gana_ia`` / ``pierde_ia`` solo si el IC95 de IA − base excluye el cero."""
    if ic is None:
        return "no_medible"
    if ic[0] > 0:
        return "gana_ia"
    if ic[1] < 0:
        return "pierde_ia"
    return "sin_diferencia_demostrable"


def discordantes(ids: Sequence[str], reales: Sequence[str], pred_ia: Sequence[str], pred_base: Sequence[str]) -> dict[str, Any]:
    """Separa los titulares por quién acertó el tema principal: ambos, solo la IA, solo la línea base o ninguno (con IDs)."""
    if not (len(ids) == len(reales) == len(pred_ia) == len(pred_base)):
        raise ValueError("ids, reales y predicciones deben tener la misma longitud")
    grupos: dict[str, list[str]] = {"ambos_aciertan": [], "solo_ia": [], "solo_baseline": [], "ambos_fallan": []}
    for i, real, a, b in zip(ids, reales, pred_ia, pred_base, strict=True):
        clave = {(True, True): "ambos_aciertan", (True, False): "solo_ia", (False, True): "solo_baseline", (False, False): "ambos_fallan"}[
            (a == real, b == real)
        ]
        grupos[clave].append(i)
    return {**grupos, "conteo": {**{k: len(v) for k, v in grupos.items()}, "n": len(ids)}}


def mcnemar_exacto(solo_ia: int, solo_baseline: int) -> float:
    """p bilateral exacto (binomial con p = 0,5) de los casos discordantes; solo informativo: el veredicto usa el IC."""
    n = solo_ia + solo_baseline
    if n == 0:
        return 1.0
    cola = sum(comb(n, k) for k in range(min(solo_ia, solo_baseline) + 1)) / 2**n
    return min(1.0, 2 * cola)


def matriz_identicos(filas: Sequence[Mapping[str, Any] | None]) -> np.ndarray:
    """``m[i, j]`` = los titulares útiles (no ruido) ``i`` y ``j`` tienen el mismo texto normalizado: la línea base de agrupación."""
    from src.limpieza import plano

    claves = [plano(str(f["titulo_limpio"])) if f and not f["es_ruido"] else None for f in filas]
    n = len(claves)
    m = np.zeros((n, n), dtype=bool)
    for i in range(n):
        for j in range(n):
            m[i, j] = i != j and claves[i] is not None and claves[i] == claves[j]
    return m


def _percentiles(valores: np.ndarray, criterio: CriterioAB) -> list[float] | None:
    validos = valores[~np.isnan(valores)]
    if len(validos) == 0:
        return None
    alfa = (1 - criterio.confianza) / 2 * 100
    return [float(x) for x in np.percentile(validos, [alfa, 100 - alfa])]


def _estimacion(punto: float | None, valores: np.ndarray, criterio: CriterioAB) -> dict[str, Any]:
    ic = _percentiles(valores, criterio)
    return {
        "valor": None if punto is None else round(punto, DECIMALES),
        "ic95": None if ic is None else [round(ic[0], DECIMALES), round(ic[1], DECIMALES)],
        "ic95_exacto": ic,
    }


def _razon(num: np.ndarray | float, den: np.ndarray | float) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.asarray(den) == 0, np.nan, np.asarray(num, dtype=float) / np.asarray(den, dtype=float))


def _pares_del_alcance(alcance: np.ndarray, n: int) -> np.ndarray:
    """Máscara de los pares ``i < j`` medidos: ``alcance`` es un vector (titulares incluidos) o una matriz (pares incluidos)."""
    superior = np.triu(np.ones((n, n), dtype=bool), k=1)
    if alcance.ndim == 1:
        return superior & alcance[:, None] & alcance[None, :]
    return superior & alcance


def _metricas_ponderadas(real: np.ndarray, pred: np.ndarray, alcance: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """TP, FP y FN (por remuestreo) con cada titular contado ``m`` veces; los pares son los ``i < j`` dentro del alcance."""
    superior = _pares_del_alcance(alcance, real.shape[0])
    matrices = [(real & pred & superior), (~real & pred & superior), (real & ~pred & superior)]
    return tuple(np.einsum("ri,ij,rj->r", m, u.astype(float), m) for u in matrices)  # type: ignore[return-value]


def _conteos(real: np.ndarray, pred: np.ndarray, alcance: np.ndarray) -> tuple[int, int, int]:
    sup = _pares_del_alcance(alcance, real.shape[0])
    return int((real & pred & sup).sum()), int((~real & pred & sup).sum()), int((real & ~pred & sup).sum())


def _f1(tp: np.ndarray, fp: np.ndarray, fn: np.ndarray) -> np.ndarray:
    return _razon(2 * tp, 2 * tp + fp + fn)


def pares_cluster_bootstrap(
    real: np.ndarray, predichos: Mapping[str, np.ndarray], alcance: np.ndarray, criterio: CriterioAB
) -> dict[str, Any]:
    """Precisión, recall y F1 de pares de dos sistemas (``ia`` y ``baseline``) con **bootstrap por titular** pareado.

    Cada remuestreo toma ``n`` titulares con reposición y cuenta cada par ``(i, j)`` con peso ``m_i · m_j`` (los pares de un
    titular consigo mismo no existen). Es el IC que respeta que los pares comparten titulares. Devuelve conteos puntuales
    exactos (``tp``, ``fp``, ``fn``), cada métrica con su IC y las diferencias ``ia − baseline`` con IC pareado.
    """
    n = real.shape[0]
    rng = np.random.default_rng(criterio.semilla)
    m = rng.multinomial(n, np.full(n, 1.0 / n), size=criterio.remuestreos).astype(float)
    salida: dict[str, Any] = {"n_titulares": n, "unidad_de_remuestreo": "titular", "remuestreos": criterio.remuestreos}
    remuestreados: dict[str, dict[str, np.ndarray]] = {}
    for nombre in ("ia", "baseline"):
        pred = predichos[nombre]
        tp, fp, fn = _conteos(real, pred, alcance)
        rtp, rfp, rfn = _metricas_ponderadas(real, pred, alcance, m)
        r = {"precision": _razon(rtp, rtp + rfp), "recall": _razon(rtp, rtp + rfn), "f1": _f1(rtp, rfp, rfn)}
        remuestreados[nombre] = r
        puntual = {
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        }
        salida[nombre] = {
            "tp": tp, "fp": fp, "fn": fn,
            "pares_predichos": tp + fp, "pares_positivos": tp + fn,
            **{k: _estimacion(puntual[k], r[k], criterio) for k in ("precision", "recall", "f1")},
        }
    dif: dict[str, Any] = {}
    for k in ("precision", "recall", "f1"):
        a, b = salida["ia"][k]["valor"], salida["baseline"][k]["valor"]
        punto = None if a is None or b is None else a - b
        d = _estimacion(punto, remuestreados["ia"][k] - remuestreados["baseline"][k], criterio)
        dif[k] = {**d, "veredicto": veredicto_por_ic(d["ic95_exacto"])}
    salida["diferencia_ia_menos_baseline"] = dif
    return salida


def elegir_ejemplos_pares(pares: Sequence[tuple[str, str]], k: int = EJEMPLOS_POR_CASO) -> list[tuple[str, str]]:
    """Primeros ``k`` pares en orden de ID sin repetir ningún titular (para no mostrar cinco veces el mismo titular)."""
    usados: set[str] = set()
    elegidos: list[tuple[str, str]] = []
    for a, b in sorted(pares):
        if len(elegidos) == k:
            break
        if a in usados or b in usados:
            continue
        usados |= {a, b}
        elegidos.append((a, b))
    return elegidos


def elegir_ejemplos_ids(ids: Sequence[str], k: int = EJEMPLOS_POR_CASO) -> list[str]:
    """Los primeros ``k`` IDs en orden alfabético (selección determinista, sin mirar el resultado)."""
    return sorted(ids)[:k]


def categoria_de_consulta(k_ia: int, k_base: int, n_esperados: int) -> str:
    """Una consulta según los IDs esperados hallados por cada método: gana la IA, gana la base o empate (completo o no)."""
    if k_ia > k_base:
        return "gana_ia"
    if k_ia < k_base:
        return "gana_baseline"
    return "empate_completo" if k_ia == n_esperados else "empate_incompleto"


def ranking_por_fecha(fechas: Mapping[str, str]) -> list[str]:
    """Línea base del ranking (PDF sección 8): grupos por publicación más reciente primero; empate por ID ascendente."""
    return [g for g, _ in sorted(fechas.items(), key=lambda kv: (-datetime.fromisoformat(kv[1]).timestamp(), kv[0]))]


def solapamiento_top(sistema: Sequence[str], baseline: Sequence[str], k: int) -> dict[str, Any]:
    """Cuántos de los ``k`` primeros del sistema están también en los ``k`` primeros de la línea base, con sus IDs."""
    a, b = list(sistema[:k]), list(baseline[:k])
    return {
        "k": k,
        "coinciden": sorted(set(a) & set(b)),
        "solo_sistema": [g for g in a if g not in b],
        "solo_baseline": [g for g in b if g not in a],
        "n_coinciden": len(set(a) & set(b)),
    }


def empates_en_el_corte(fechas: Mapping[str, str], orden: Sequence[str], k: int) -> list[str]:
    """Grupos que comparten fecha con el puesto ``k`` de la línea base y cuyo lugar dentro o fuera del top lo decide solo el ID.

    Vacío si el puesto ``k`` y el ``k + 1`` no tienen la misma fecha (el corte es limpio).
    """
    if len(orden) <= k:
        return []
    fecha = fechas[orden[k - 1]]
    if fechas[orden[k]] != fecha:
        return []
    return sorted(g for g in orden if fechas[g] == fecha)


# ============================================================================================ evaluaciones con datos reales


def _redondear(x: float | None) -> float | None:
    return None if x is None else round(float(x), DECIMALES)


def evaluar_clasificacion(ruta_base: Path) -> dict[str, Any]:
    """Baseline ``guia`` vs. clasificador activo sobre las etiquetas humanas, vista del clasificador (los que pasaron el filtro de ruido)
    y vista del pipeline completo (todos los etiquetados; los que el filtro descartó cuentan ``sin_tema`` para los dos)."""
    from src import db
    from src.baseline import SIN_TEMA
    from src.clasificacion import METODO_A, METODO_B, texto_de_entrada
    from src.configuracion import cargar_carga, cargar_temas
    from src.embeddings import crear
    from src.limpieza import Reglas
    from eval.clasificacion import ETIQUETAS, clases_de, ids_excluidos, leer_etiquetas, predecir

    cfg, temas = cargar_clasificacion(), cargar_temas()
    modelo, metodo = cfg.modelo_activo, cfg.metodo_activo
    etiquetas = leer_etiquetas(ETIQUETAS, "tema_principal", temas)
    excluidos = ids_excluidos()
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = con.execute("SELECT id_noticia, titulo_limpio, descripcion, es_ruido FROM noticias ORDER BY id_noticia").fetchall()
    finally:
        con.close()
    en_base = {f[0]: f for f in filas}
    validos = sorted(i for i in etiquetas if i in en_base and i not in excluidos)
    pasaron = [i for i in validos if not en_base[i][3]]
    clases = clases_de(temas)
    textos = [texto_de_entrada(en_base[i][1], en_base[i][2], cfg.usar_descripcion) for i in pasaron]
    reales = [etiquetas[i].tema for i in pasaron]
    pred = predecir(textos, cfg, temas, modelo, crear(cfg, modelo), Reglas.desde_config())
    base_p = [p.principal for p in pred["baseline"]]
    ia_p = [p.principal for p in pred[METODO_A if metodo == METODO_A else METODO_B]]
    z = cargar_carga().salida.z_intervalo_confianza
    criterio_bench = cargar_benchmark().intervalos

    def comparar(criterio: CriterioAB) -> dict[str, Any]:
        d = metricas.diferencia_con_ic(reales, base_p, ia_p, clases, criterio)
        return {
            "criterio": {"remuestreos": criterio.remuestreos, "confianza": criterio.confianza, "semilla": criterio.semilla},
            "macro_f1_ia": metricas.macro_f1_con_ic(reales, ia_p, clases, criterio),
            "macro_f1_baseline": metricas.macro_f1_con_ic(reales, base_p, clases, criterio),
            "diferencia_macro_f1": {k: d[k] for k in ("n", "diferencia_macro_f1", "ic95", "ic95_exacto")},
            "veredicto": veredicto_por_ic(d["ic95_exacto"]),
            "por_tema": {
                t: {
                    **v,
                    "titulares_humanos": reales.count(t),
                    "veredicto": veredicto_por_ic(v["ic95_exacto"]) if reales.count(t) >= SOPORTE_MINIMO_TEMA else "soporte_insuficiente",
                }
                for t, v in d["por_clase"].items()
            },
        }

    texto_de = {i: en_base[i][1] for i in pasaron}
    disc = discordantes(pasaron, reales, ia_p, base_p)
    conteo = disc["conteo"]
    por_id = {i: {"id": i, "titular": texto_de[i], "humano": reales[k], "baseline": base_p[k], "ia": ia_p[k]} for k, i in enumerate(pasaron)}

    # pipeline completo: el filtro de ruido es el mismo para los dos, así que los descartados cuentan sin_tema en ambos
    lugar = {i: k for k, i in enumerate(pasaron)}
    todos_reales = [etiquetas[i].tema for i in validos]
    base_todos = [base_p[lugar[i]] if i in lugar else SIN_TEMA for i in validos]
    ia_todos = [ia_p[lugar[i]] if i in lugar else SIN_TEMA for i in validos]
    d_pipe = metricas.diferencia_con_ic(todos_reales, base_todos, ia_todos, clases, cfg.criterio_ab)
    disc_pipe = discordantes(validos, todos_reales, ia_todos, base_todos)
    return {
        "modelo": modelo,
        "metodo": metodo,
        "baseline": f"src/baseline.py, variante {cfg.baseline.variante_activa}",
        "clases": clases,
        "vista_clasificador": {
            "n": len(pasaron),
            "exactitud_ia": metricas_proporcion(sum(a == r for a, r in zip(ia_p, reales, strict=True)), len(pasaron), z),
            "exactitud_baseline": metricas_proporcion(sum(a == r for a, r in zip(base_p, reales, strict=True)), len(pasaron), z),
            "con_criterio_de_clasificacion": comparar(cfg.criterio_ab),
            "con_criterio_de_benchmark": comparar(criterio_bench),
            "discordantes": {
                **{k: disc[k] for k in ("solo_ia", "solo_baseline", "ambos_aciertan", "ambos_fallan")},
                "conteo": conteo,
                "p_mcnemar_exacto": round(mcnemar_exacto(conteo["solo_ia"], conteo["solo_baseline"]), DECIMALES),
            },
            "ejemplos_ia_acierta_y_baseline_falla": [por_id[i] for i in elegir_ejemplos_ids(disc["solo_ia"])],
            "ejemplos_baseline_acierta_y_ia_falla": [por_id[i] for i in elegir_ejemplos_ids(disc["solo_baseline"])],
            "por_tema_ia": metricas.por_clase(reales, ia_p, clases, z),
            "por_tema_baseline": metricas.por_clase(reales, base_p, clases, z),
        },
        "vista_pipeline": {
            "n": len(validos),
            "macro_f1_ia": metricas.macro_f1_con_ic(todos_reales, ia_todos, clases, cfg.criterio_ab),
            "macro_f1_baseline": metricas.macro_f1_con_ic(todos_reales, base_todos, clases, cfg.criterio_ab),
            "diferencia_macro_f1": {k: d_pipe[k] for k in ("n", "diferencia_macro_f1", "ic95", "ic95_exacto")},
            "veredicto": veredicto_por_ic(d_pipe["ic95_exacto"]),
            "discordantes_conteo": disc_pipe["conteo"],
        },
    }


def metricas_proporcion(k: int, n: int, z: float) -> dict[str, Any]:
    from src.clasificacion import proporcion

    return proporcion(k, n, z)


def evaluar_agrupacion(ruta_base: Path, referencia: Path = RAIZ / "outputs" / "agrupacion.json") -> dict[str, Any]:
    """Embeddings (umbral calibrado, validación cruzada) vs. titulares idénticos, sobre pares y con IC por titular."""
    from eval import agrupacion as ag
    from src import db
    from src.agrupacion import codificar_titulares
    from src.configuracion import cargar_reglas
    from src.embeddings import crear

    criterio = cargar_benchmark().intervalos
    reglas = cargar_reglas()
    cfg = cargar_clasificacion().model_copy(update={"modelo_activo": reglas.agrupacion.modelo})
    humanos = ag.leer_grupos_humanos()
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        todas = db.leer_tabla(con, "noticias", "id_noticia")
    finally:
        con.close()
    por_id = {str(f["id_noticia"]): f for f in todas}
    utiles = [f for f in todas if not f["es_ruido"]]
    vectores = codificar_titulares(utiles, crear(cfg, cfg.modelo_activo), reglas.agrupacion.usar_descripcion)
    ids = sorted(humanos)
    etiquetas = [humanos[i] for i in ids]
    cal = reglas.agrupacion.calibracion
    umbrales = ag.umbrales_del_barrido(cal.barrido_desde, cal.barrido_hasta, cal.barrido_paso)
    barrido = ag.Barrido(ids, etiquetas, utiles, vectores, reglas, umbrales)
    elegido = ag.elegir_de_curva(barrido.curva())
    base = matriz_identicos([por_id[i] for i in ids])
    n = len(ids)
    todo = np.ones(n, dtype=bool)

    # validación cruzada: cada par de un pliegue de prueba se predice con el umbral calibrado SIN ese pliegue
    pliegue = np.array([ag.pliegue_de(i, cal.pliegues) for i in ids])
    cv = np.zeros((n, n), dtype=bool)
    alcance_cv = np.zeros((n, n), dtype=bool)
    umbral_de_pliegue: dict[int, float] = {}
    for k in range(cal.pliegues):
        u = ag.elegir_de_curva(barrido.curva(pliegue != k))
        umbral_de_pliegue[k] = u
        dentro = pliegue == k
        bloque = dentro[:, None] & dentro[None, :]
        cv |= barrido.predicho[u] & bloque
        alcance_cv |= bloque
    alcance_titulares = np.array([any(alcance_cv[i, j] for j in range(n) if j != i) for i in range(n)])

    texto = {i: str(por_id[i]["titulo_limpio"]) for i in ids}
    pos = {i: k for k, i in enumerate(ids)}

    def pares_de(mascara: np.ndarray) -> list[tuple[str, str]]:
        return [(ids[i], ids[j]) for i, j in zip(*np.nonzero(np.triu(mascara, k=1)), strict=True)]

    def ejemplo(par: tuple[str, str]) -> dict[str, Any]:
        a, b = par
        return {
            "par": [a, b], "titulares": [texto[a], texto[b]], "grupo_humano": [humanos[a], humanos[b]],
            "identicos": base[pos[a], pos[b]],
        }

    real = barrido.real
    ia_in = barrido.predicho[elegido]
    ia_cv_scope = cv & alcance_cv
    base_cv_scope = base & alcance_cv
    pares_validos = real & alcance_cv
    ia_une_base_no = pares_de(pares_validos & ia_cv_scope & ~base_cv_scope)
    fn_cv = pares_de(pares_validos & ~ia_cv_scope)
    fp_cv = pares_de(~real & ia_cv_scope)
    fn_in = pares_de(real & ~ia_in)
    base_une_ia_no = pares_de(pares_validos & base_cv_scope & ~ia_cv_scope)
    referencia_json = json.loads(referencia.read_text(encoding="utf-8")) if referencia.exists() else None
    cv_ref = None if referencia_json is None else referencia_json["validacion_cruzada"]["agrupado"]
    tp_cv, fp_n, fn_n = _conteos(real, cv, alcance_cv)
    return {
        "modelo": cfg.modelo_activo,
        "umbral_elegido_con_todas_las_etiquetas": elegido,
        "umbral_por_pliegue_validacion_cruzada": umbral_de_pliegue,
        "titulares_etiquetados": n,
        "validacion_cruzada_agrupada": {
            "nota": "Cifra honesta de la IA: cada par de prueba se predice con un umbral calibrado sin los titulares de su pliegue. La línea base se mide sobre los mismos pares.",
            "pares_en_alcance": int(np.triu(alcance_cv, k=1).sum()),
            **pares_cluster_bootstrap(real, {"ia": cv, "baseline": base}, alcance_cv, criterio),
        },
        "umbral_elegido_en_la_misma_muestra": {
            "nota": "OPTIMISTA: las mismas etiquetas calibran y evalúan.",
            "pares_en_alcance": int(np.triu(np.ones((n, n), dtype=bool), k=1).sum()),
            **pares_cluster_bootstrap(real, {"ia": ia_in, "baseline": base}, np.ones(n, dtype=bool), criterio),
        },
        "titulares_con_pares_en_cv": int(alcance_titulares.sum()),
        "coincide_con_outputs_agrupacion_json": None if cv_ref is None else (
            [cv_ref["tp"], cv_ref["fp"], cv_ref["fn"]] == [tp_cv, fp_n, fn_n]
        ),
        "conteo_pares": {
            "ia_une_y_baseline_no_cv": len(ia_une_base_no),
            "baseline_une_y_ia_no_cv": len(base_une_ia_no),
            "falsos_negativos_ia_cv": len(fn_cv),
            "falsos_positivos_ia_cv": len(fp_cv),
            "falsos_negativos_ia_umbral_elegido": len(fn_in),
        },
        "ejemplos_ia_une_y_baseline_no": [ejemplo(p) for p in elegir_ejemplos_pares(ia_une_base_no)],
        "ejemplos_falsos_negativos_ia_umbral_elegido": [ejemplo(p) for p in elegir_ejemplos_pares(fn_in)],
        "ejemplos_falsos_positivos_ia_cv": [ejemplo(p) for p in elegir_ejemplos_pares(fp_cv)],
        "ejemplos_baseline_une_y_ia_no_cv": [ejemplo(p) for p in elegir_ejemplos_pares(base_une_ia_no)],
        "por_grupo_humano_ia": ag.por_grupo_humano(barrido, etiquetas, elegido),
    }


def evaluar_busqueda() -> dict[str, Any]:
    """Recall@5 por IDs de la semántica contra BM25 sobre el benchmark de desarrollo, con bootstrap pareado y ejemplos por consulta."""
    from eval.recuperacion import ids_recuperados
    from eval.run_benchmark import BENCHMARK_DEV, crear_consultor_real, leer_consultas

    criterio = cargar_benchmark().intervalos
    consultor = crear_consultor_real()
    consultas = leer_consultas(BENCHMARK_DEV)
    tipos = consultor.cfg.evaluacion.tipos_recuperacion
    base = [c for c in consultas if c["tipo"] in tipos and c["ids_evidencia"]]
    esperados = {c["id"]: c["ids_evidencia"] for c in base}
    texto_de = {c["id"]: c["consulta"] for c in base}
    hall = {m: {i: ids_recuperados(consultor, texto_de[i], m) for i in esperados} for m in ("semantica", "bm25")}
    documentos = {d.id: d.texto for d in consultor.indice.corpus.documentos}

    def describir(i: str) -> str:
        t = documentos.get(i, "")
        return t if len(t) <= LARGO_TEXTO_ID else t[:LARGO_TEXTO_ID] + "…"

    def por_consulta(cid: str) -> dict[str, Any]:
        esp = set(esperados[cid])
        sem, bm = set(hall["semantica"][cid]) & esp, set(hall["bm25"][cid]) & esp
        return {
            "id": cid, "consulta": texto_de[cid], "esperados": sorted(esp),
            "ia_halla": sorted(sem), "baseline_halla": sorted(bm),
            "ia_no_halla": sorted(esp - sem), "baseline_no_halla": sorted(esp - bm),
            "categoria": categoria_de_consulta(len(sem), len(bm), len(esp)),
            "texto_de_los_esperados_que_alguien_no_hallo": {i: describir(i) for i in sorted((esp - sem) | (esp - bm))},
        }

    detalle = [por_consulta(c) for c in sorted(esperados)]
    por_categoria: dict[str, list[str]] = {}
    for d in detalle:
        por_categoria.setdefault(d["categoria"], []).append(d["id"])

    def subconjunto(prefijos: tuple[str, ...]) -> dict[str, Any]:
        esp = {c: [i for i in v if i.startswith(prefijos)] for c, v in esperados.items()}
        esp = {c: v for c, v in esp.items() if v}
        return {
            "n_consultas": len(esp),
            "ia": metricas.recall_con_ic(esp, hall["semantica"], criterio)["por_ids"],
            "baseline": metricas.recall_con_ic(esp, hall["bm25"], criterio)["por_ids"],
            "diferencia_ia_menos_baseline": _con_veredicto(metricas.diferencia_recall(esp, hall["bm25"], hall["semantica"], criterio)),
        }

    return {
        "k": consultor.cfg.recuperacion.top_k,
        "n_consultas": len(esperados),
        "ia": "búsqueda semántica (embeddings)",
        "baseline": "BM25 sobre el mismo corpus e índice",
        "recall_por_ids_ia": metricas.recall_con_ic(esperados, hall["semantica"], criterio),
        "recall_por_ids_baseline": metricas.recall_con_ic(esperados, hall["bm25"], criterio),
        "diferencia_ia_menos_baseline": _con_veredicto(metricas.diferencia_recall(esperados, hall["bm25"], hall["semantica"], criterio)),
        "solo_titulares": subconjunto(("NOT-", "SYN-")),
        "solo_oficiales": subconjunto(("IND-", "SIS-")),
        "consultas_por_categoria": por_categoria,
        "ejemplos_ia_gana": [d for d in detalle if d["categoria"] == "gana_ia"][:EJEMPLOS_POR_CASO],
        "ejemplos_empate_completo": [d for d in detalle if d["categoria"] == "empate_completo"][:EJEMPLOS_POR_CASO],
        "ejemplos_ninguno_gana": [d for d in detalle if d["categoria"] in ("empate_incompleto", "gana_baseline")][:EJEMPLOS_POR_CASO],
        "detalle_por_consulta": detalle,
    }


def _con_veredicto(d: dict[str, Any]) -> dict[str, Any]:
    return {**d, "veredicto": veredicto_por_ic(d.get("ic95_exacto"))}


def evaluar_ranking(ruta_base: Path, sensibilidad: Path = RAIZ / "outputs" / "sensibilidad.json") -> dict[str, Any]:
    """Hechos descriptivos del ranking frente a «más reciente primero». No mide utilidad: eso exige la selección de un editor (E1-19)."""
    from src import db

    from src.prioridad import MODALIDAD_POR_DEFECTO

    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        db.exigir_modalidad_de_la_base(con, MODALIDAD_POR_DEFECTO)      # X48: estas métricas son del ranking editorial
        puntajes = {
            r[0]: r for r in con.execute(
                "SELECT id_grupo, posicion, puntaje, rango, relevancia, impacto, urgencia, novedad, evidencia, componentes, vacios "
                "FROM puntajes ORDER BY posicion"
            ).fetchall()
        }
        grupos = {r[0]: r for r in con.execute("SELECT id_grupo, titular_central, n_titulares, n_medios, n_procedencias FROM grupos").fetchall()}
    finally:
        con.close()
    fechas = {g: json.loads(p[9])["U"]["explicacion"]["fecha"] for g, p in puntajes.items()}
    orden_base = ranking_por_fecha(fechas)
    orden_sistema = list(puntajes)
    sol = solapamiento_top(orden_sistema, orden_base, TAMANO_TOP)
    pos_sistema = {g: i for i, g in enumerate(orden_sistema, start=1)}
    pos_base = {g: i for i, g in enumerate(orden_base, start=1)}
    informe_prioridad = json.loads((RAIZ / "outputs" / "prioridad.json").read_text(encoding="utf-8"))
    estado = {r["id_grupo"]: r for r in informe_prioridad["ranking"]}

    def ficha(g: str) -> dict[str, Any]:
        p = puntajes[g]
        return {
            "id_grupo": g, "titular_central": grupos[g][1], "n_titulares": grupos[g][2], "n_medios": grupos[g][3],
            "posicion_sistema": pos_sistema[g], "posicion_por_fecha": pos_base[g], "fecha_mas_reciente": fechas[g],
            "puntaje": round(p[2], 2), "rango": p[3],
            "componentes": {k: round(v, DECIMALES) for k, v in zip("RIUNE", p[4:9], strict=True)},
            "estado_de_evidencia": estado[g]["estado_de_evidencia"] if g in estado else None,
            "accion": estado[g]["accion"] if g in estado else None,
        }

    sens = json.loads(sensibilidad.read_text(encoding="utf-8")) if sensibilidad.exists() else None
    return {
        "utilidad_medible": False,
        "motivo": "eval/seleccion_editor.csv existe pero es una selección provisional del asistente (D-101), no de un editor; "
                  "su Precision@5 está en outputs/precision_at_5.json y se rehace a mano en C-09.",
        "baseline": "grupos ordenados solo por publicación más reciente (PDF sección 8); empate por ID ascendente",
        "grupos": len(puntajes),
        "top": TAMANO_TOP,
        "top_sistema": orden_sistema[:TAMANO_TOP],
        "top_por_fecha": orden_base[:TAMANO_TOP],
        "solapamiento": sol,
        "empates_de_fecha_en_el_corte": empates_en_el_corte(fechas, orden_base, TAMANO_TOP),
        "ejemplos_solo_sistema": [ficha(g) for g in sol["solo_sistema"]],
        "ejemplos_solo_por_fecha": [ficha(g) for g in sol["solo_baseline"]],
        "top_sistema_detalle": [ficha(g) for g in orden_sistema[:TAMANO_TOP]],
        "estabilidad": None if sens is None else {
            "variantes_con_efecto": sens["variantes_con_efecto"],
            "top_sin_cambio": sens["top_sin_cambio"],
            "con_algun_cambio": sens["con_algun_cambio"],
            "mismo_orden": sens["mismo_orden"],
            "fuente": "outputs/sensibilidad.json",
        },
    }


# ============================================================================================ CLI


def construir_informe(ruta_base: Path) -> dict[str, Any]:
    criterio = cargar_benchmark().intervalos
    informe = {
        "version": 1,
        "criterio_de_veredicto": "una diferencia está demostrada solo si el IC95 de la diferencia pareada excluye el cero (D-21/D-57)",
        "criterio_ic_nuevo": {"remuestreos": criterio.remuestreos, "confianza": criterio.confianza, "semilla": criterio.semilla, "fuente": "config/benchmark.yaml: intervalos"},
        "clasificacion": evaluar_clasificacion(ruta_base),
        "agrupacion": evaluar_agrupacion(ruta_base),
        "busqueda": evaluar_busqueda(),
        "ranking": evaluar_ranking(ruta_base),
    }
    return informe


def resumen(informe: Mapping[str, Any]) -> list[str]:
    c = informe["clasificacion"]["vista_clasificador"]
    k = c["con_criterio_de_benchmark"]   # el mismo criterio (remuestreos) que cita docs/ia_vs_baseline.md
    g = informe["agrupacion"]["validacion_cruzada_agrupada"]
    b = informe["busqueda"]
    r = informe["ranking"]
    dg = g["diferencia_ia_menos_baseline"]
    return [
        f"clasificación (n={c['n']}): macro-F1 IA {k['macro_f1_ia']['macro_f1']} vs base {k['macro_f1_baseline']['macro_f1']}; "
        f"IA − base {k['diferencia_macro_f1']['diferencia_macro_f1']} IC95 {k['diferencia_macro_f1']['ic95']} -> {k['veredicto']}; "
        f"solo IA acierta {c['discordantes']['conteo']['solo_ia']}, solo base acierta {c['discordantes']['conteo']['solo_baseline']}",
        f"agrupación (CV, {g['ia']['pares_positivos']} pares positivos): F1 IA {g['ia']['f1']['valor']} vs base {g['baseline']['f1']['valor']}; "
        f"F1 IA − base {dg['f1']['valor']} IC95 {dg['f1']['ic95']} -> {dg['f1']['veredicto']}; recall {dg['recall']['veredicto']}; precisión {dg['precision']['veredicto']}",
        f"búsqueda (n={b['n_consultas']} consultas): Recall@5 IA {b['recall_por_ids_ia']['por_ids']['proporcion']} vs BM25 {b['recall_por_ids_baseline']['por_ids']['proporcion']}; "
        f"dif {b['diferencia_ia_menos_baseline']['diferencia']} IC95 {b['diferencia_ia_menos_baseline']['ic95']} -> {b['diferencia_ia_menos_baseline']['veredicto']}",
        f"ranking: utilidad no medible (E1-19); top {r['top']} coincide con «más reciente primero» en {r['solapamiento']['n_coinciden']}/{r['top']}",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    from src.configuracion import cargar_normalizacion

    parser = argparse.ArgumentParser(description="E1-18 · D-66: IA vs. línea base en clasificación, agrupación, búsqueda y ranking")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    if not args.base.exists():
        print(f"No existe {args.base}: ejecute normalización, limpieza, clasificación y prioridad primero.", file=sys.stderr)
        return 1
    informe = construir_informe(args.base)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2, default=_serializable) + "\n", encoding="utf-8")
    print("\n".join(resumen(informe)))
    print(f"escrito: {args.salida}")
    return 0


def _serializable(o: Any) -> Any:
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(f"no serializable: {type(o)}")


if __name__ == "__main__":
    sys.exit(main())
