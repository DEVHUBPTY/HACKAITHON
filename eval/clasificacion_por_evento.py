"""C-10b: la clasificación de temas evaluada **por evento**, con y sin abstención (sin tocar el clasificador).

Las filas etiquetadas no son independientes: un mismo hecho aparece en varios titulares (p. ej. 20 de El Niño, 13 de la ayuda
de EE. UU. a América Latina en cuatro idiomas), así que el n efectivo es el número de **eventos** (``grupo`` de la etiqueta, o
la propia noticia si no tiene). Este módulo reutiliza el agrupamiento y el bootstrap de ``eval/diagnostico_temas.py`` y mide,
para el clasificador activo (e5 · método A) y para los dos baselines por palabras clave:

* exactitud y macro-F1 **por evento**, con IC 95 % de bootstrap sobre eventos (los de ``criterio_ab``), y por fila con Wilson;
* con y sin abstención (``sin_tema``): cobertura frente a exactitud entre lo cubierto. Los puntos de la curva son los
  umbrales que **ya están** en ``config/clasificacion.yaml`` (ninguno nuevo; no se calibra nada);
* recall por tema **por evento**, y qué eventos dominan cada cifra por fila (qué significan «Economía 12/26» o
  «Eventos naturales 20/20»).

Solo etiquetas con ``origen = humano`` (D-101); los ejemplos de ``temas.yaml`` no entran. El resultado es **exploratorio**
(≈ 29 eventos, una sola persona etiquetó). No imprime ni guarda ningún titular etiquetado.
Uso: ``HF_HUB_OFFLINE=1 poetry run python -m eval.clasificacion_por_evento`` → ``outputs/clasificacion_por_evento.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from eval import clasificacion as evalclas
from eval import diagnostico_temas as dg
from eval import metricas
from eval import origen_etiquetas as oe
from src import db
from src.baseline import SIN_TEMA, Baseline
from src.clasificacion import METODO_A, construir_referencias, proporcion, puntuar, texto_de_entrada
from src.configuracion import (
    RAIZ,
    ConfigClasificacion,
    ConfigTemas,
    CriterioAB,
    cargar_carga,
    cargar_clasificacion,
    cargar_normalizacion,
    cargar_temas,
)
from src.embeddings import crear
from src.limpieza import Reglas

SALIDA = RAIZ / "outputs" / "clasificacion_por_evento.json"
ADVERTENCIA = (
    "EXPLORATORIO: ≈ 29 eventos y una sola persona etiquetó (D-85); las etiquetas son un censo del estrato «no ruido» del "
    "snapshot anterior, no datos de prueba independientes. Un IC por evento ancho es lo esperable, no un defecto del cálculo."
)


# ------------------------------------------------------------------ lectura: solo humanas, sin ejemplos excluidos


def leer_etiquetas_y_grupos(ruta: Path, temas: ConfigTemas) -> tuple[dict[str, evalclas.EtiquetaHumana], dict[str, str]]:
    """Etiquetas y ``grupo`` (evento) de las filas con ``origen = humano``; las provisionales (D-101) nunca se leen."""
    etiquetas = evalclas.leer_etiquetas(ruta, "tema_principal", temas, oe.SOLO_HUMANOS)
    grupos = dg._leer_grupos(ruta, oe.SOLO_HUMANOS)
    return etiquetas, grupos


def armar_conjunto(
    filas: Sequence[tuple[str, Any, Any]],
    etiquetas: dict[str, evalclas.EtiquetaHumana],
    grupos: dict[str, str],
    excluidos: set[str],
) -> tuple[list[str], np.ndarray, list[str]]:
    """``(ids, tema humano, evento)`` de las filas de la base con etiqueta humana y que no son ejemplo de ``temas.yaml``.

    El evento es el ``grupo`` de la etiqueta o, si no tiene, la propia noticia (igual que ``eval/diagnostico_temas.py``).
    """
    ids = [f[0] for f in filas if f[0] in etiquetas and f[0] not in excluidos]
    y = np.array([etiquetas[i].tema for i in ids], dtype=object)
    eventos = [grupos.get(i) or i for i in ids]
    return ids, y, eventos


@dataclass(frozen=True)
class Conjunto:
    """Filas evaluables (etiqueta humana, no ruido, no ejemplo) con sus embeddings y la similitud del método A."""

    ids: list[str]
    textos: list[str]
    y: np.ndarray
    eventos: list[str]
    X: np.ndarray
    similitud: np.ndarray
    temas: list[str]
    clases: list[str]
    excluidos_descartados: int
    etiquetados_en_csv: int


def cargar_conjunto(
    ruta_etiquetas: Path, ruta_base: Path, cfg: ConfigClasificacion, temas: ConfigTemas, motores: dict[str, Any] | None = None
) -> Conjunto:
    """Mismo conjunto que ``eval.diagnostico_temas`` (humanas, no ruido, sin ejemplos) con los embeddings de la canalización."""
    etiquetas, grupos = leer_etiquetas_y_grupos(ruta_etiquetas, temas)
    excluidos = evalclas.ids_excluidos()
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = con.execute("SELECT id_noticia, titulo_limpio, descripcion FROM noticias WHERE NOT es_ruido ORDER BY id_noticia").fetchall()
    finally:
        con.close()
    ids, y, eventos = armar_conjunto(filas, etiquetas, grupos, excluidos)
    por_id = {f[0]: f for f in filas}
    textos = [texto_de_entrada(por_id[i][1], por_id[i][2], cfg.usar_descripcion) for i in ids]
    emb = crear(cfg, cfg.modelo_activo, motor=(motores or {}).get(cfg.modelo_activo))
    X = emb.codificar(textos, "titular")
    ref = construir_referencias(emb, temas, Reglas.desde_config())
    return Conjunto(
        ids, textos, y, eventos, X, puntuar(X, ref, METODO_A).similitud, list(ref.temas), evalclas.clases_de(temas),
        sum(1 for i in etiquetas if i in excluidos), len(etiquetas),
    )


# ------------------------------------------------------------------ estadística por evento


def _grupos_de_eventos(eventos: Sequence[str]) -> list[np.ndarray]:
    """Índices de las filas de cada evento, en orden de primera aparición."""
    indices: dict[str, list[int]] = {}
    for k, e in enumerate(eventos):
        indices.setdefault(e, []).append(k)
    return [np.array(v) for v in indices.values()]


def _macro_f1_medio(real: np.ndarray, preds: np.ndarray, filas: np.ndarray, clases: Sequence[str]) -> float:
    """Macro-F1 de las filas ``filas``, promediado sobre las repeticiones (``preds`` es repeticiones × filas)."""
    valores = [metricas.macro_f1(list(real[filas]), list(p[filas]), clases) for p in preds]
    definidos = [v for v in valores if v is not None]
    return float(np.mean(definidos)) if definidos else float("nan")


def _remuestras_f1(
    real: np.ndarray, preds: np.ndarray, grupos: list[np.ndarray], clases: Sequence[str], remuestras: np.ndarray
) -> np.ndarray:
    return np.array([_macro_f1_medio(real, preds, np.concatenate([grupos[k] for k in r]), clases) for r in remuestras])


def _percentiles(valores: np.ndarray, criterio: CriterioAB) -> list[float] | None:
    validos = valores[~np.isnan(valores)]
    if len(validos) == 0:
        return None
    alfa = (1 - criterio.confianza) / 2 * 100
    bajo, alto = np.percentile(validos, [alfa, 100 - alfa])
    return [round(float(bajo), 4), round(float(alto), 4)]


def macro_f1_por_evento(real: np.ndarray, preds: np.ndarray, eventos: Sequence[str], clases: Sequence[str], criterio: CriterioAB) -> dict[str, Any]:
    """Macro-F1 (clases con soporte) con IC de bootstrap **sobre eventos**: se remuestrean eventos completos.

    ``preds`` es ``repeticiones × filas`` (una sola fila de predicciones para un sistema determinista).
    """
    preds = np.atleast_2d(preds)
    grupos = _grupos_de_eventos(eventos)
    remuestras = np.random.default_rng(criterio.semilla).integers(0, len(grupos), size=(criterio.remuestreos, len(grupos)))
    puntual = _macro_f1_medio(real, preds, np.arange(len(real)), clases)
    return {
        "valor": None if np.isnan(puntual) else round(puntual, 4),
        "ic95": _percentiles(_remuestras_f1(real, preds, grupos, clases, remuestras), criterio),
        "eventos": len(grupos),
        "filas": len(real),
        "remuestreos": criterio.remuestreos,
    }


def diferencia_macro_f1_por_evento(
    real: np.ndarray, preds_a: np.ndarray, preds_b: np.ndarray, eventos: Sequence[str], clases: Sequence[str], criterio: CriterioAB
) -> dict[str, Any]:
    """Cambio de macro-F1 ``b − a``, pareado: los mismos eventos remuestreados en los dos sistemas. ``a_favor`` = el IC queda sobre cero."""
    preds_a, preds_b = np.atleast_2d(preds_a), np.atleast_2d(preds_b)
    grupos = _grupos_de_eventos(eventos)
    remuestras = np.random.default_rng(criterio.semilla).integers(0, len(grupos), size=(criterio.remuestreos, len(grupos)))
    todas = np.arange(len(real))
    puntual = _macro_f1_medio(real, preds_b, todas, clases) - _macro_f1_medio(real, preds_a, todas, clases)
    ic = _percentiles(_remuestras_f1(real, preds_b, grupos, clases, remuestras) - _remuestras_f1(real, preds_a, grupos, clases, remuestras), criterio)
    return {
        "diferencia": None if np.isnan(puntual) else round(puntual, 4),
        "ic95": ic,
        "excluye_cero": bool(ic is not None and (ic[0] > 0 or ic[1] < 0)),
        "a_favor": bool(ic is not None and ic[0] > 0),
        "eventos": len(grupos),
    }


def se_solapan(a: Sequence[float] | None, b: Sequence[float] | None) -> bool | None:
    """¿Los dos intervalos se tocan? ``None`` si alguno no existe (no se inventa)."""
    if a is None or b is None:
        return None
    return bool(a[0] <= b[1] and b[0] <= a[1])


def _por_evento(valores: np.ndarray, eventos: Sequence[str], criterio: CriterioAB) -> dict[str, Any] | None:
    """Media por evento con IC bootstrap (``diagnostico_temas.exactitud_por_evento``); ``None`` si no hay filas."""
    if len(valores) == 0:
        return None
    return dg.exactitud_por_evento(np.asarray(valores, dtype=float), list(eventos), criterio)


def _recall_por_tema(
    real: np.ndarray, preds: np.ndarray, eventos: Sequence[str], clases: Sequence[str], criterio: CriterioAB, z: float, min_eventos_ic: int
) -> dict[str, Any]:
    salida: dict[str, Any] = {}
    n_rep = preds.shape[0]
    for c in clases:
        filas = np.flatnonzero(real == c)
        if len(filas) == 0:
            continue
        acierta = (preds[:, filas] == c).mean(axis=0)                  # por fila, promediando repeticiones
        ev = [eventos[k] for k in filas]
        medias, _ = dg._por_evento(acierta, ev)
        ic = _por_evento(acierta, ev, criterio)["ic95"] if len(medias) >= min_eventos_ic else None
        salida[c] = {
            "filas": {**proporcion(int(round(float(acierta.sum()))), len(filas), z), "aproximado": n_rep > 1},
            "eventos": len(medias),
            "recall_por_evento": float(medias.mean()),
            "ic95": ic,
            "nota_ic": None if ic is not None else f"menos de {min_eventos_ic} eventos: el IC por evento no es estimable",
        }
    return salida


def evaluar_sistema(
    real: np.ndarray, preds: np.ndarray, eventos: Sequence[str], clases: Sequence[str], criterio: CriterioAB, z: float, min_eventos_ic: int
) -> dict[str, Any]:
    """Métricas de un sistema por fila (Wilson) y por evento (bootstrap sobre eventos), con cobertura y recall por tema.

    ``preds`` es ``repeticiones × filas``. «Cubierta» = el sistema no se abstuvo (``sin_tema``); la exactitud entre cubiertas
    cuenta como error una fila cubierta cuya etiqueta humana es ``sin_tema``.
    """
    preds = np.atleast_2d(preds)
    n_rep, n = preds.shape
    acierta = (preds == real).astype(float)
    cubierta = (preds != SIN_TEMA).astype(float)
    aprox = n_rep > 1
    fila_acierta, fila_cubierta = acierta.mean(axis=0), cubierta.mean(axis=0)
    num, den = (acierta * cubierta).sum(axis=0) / n_rep, cubierta.sum(axis=0) / n_rep
    nombres = list(dict.fromkeys(eventos))
    por_ev = {e: [0.0, 0.0] for e in nombres}
    for k, e in enumerate(eventos):
        por_ev[e][0] += num[k]
        por_ev[e][1] += den[k]
    con_cubiertas = [e for e in nombres if por_ev[e][1] > 0]
    valores_cubiertos = np.array([por_ev[e][0] / por_ev[e][1] for e in con_cubiertas])
    return {
        "exactitud_por_fila": {**proporcion(int(round(fila_acierta.sum())), n, z), "aproximado": aprox},
        "exactitud_por_evento": _por_evento(fila_acierta, eventos, criterio),
        "macro_f1_por_evento": macro_f1_por_evento(real, preds, eventos, clases, criterio),
        "cobertura_por_fila": {**proporcion(int(round(fila_cubierta.sum())), n, z), "aproximado": aprox},
        "cobertura_por_evento": _por_evento(fila_cubierta, eventos, criterio),
        "exactitud_entre_cubiertas_por_fila": {**proporcion(int(round(num.sum())), int(round(den.sum())), z), "aproximado": aprox},
        "exactitud_entre_cubiertas_por_evento": _por_evento(valores_cubiertos, con_cubiertas, criterio),
        "abstenciones": int(round((1 - fila_cubierta).sum())),
        "recall_por_tema": _recall_por_tema(real, preds, eventos, clases, criterio, z, min_eventos_ic),
    }


# ------------------------------------------------------------------ qué eventos dominan


def eventos_dominantes(real: np.ndarray, eventos: Sequence[str], acierta: np.ndarray, n_top: int) -> list[dict[str, Any]]:
    """Los ``n_top`` eventos con más filas: su peso en la exactitud por fila y cuántas acierta el sistema (sin titulares)."""
    total = len(real)
    salida = []
    for e, filas in sorted(((e, np.flatnonzero(np.array(eventos) == e)) for e in dict.fromkeys(eventos)), key=lambda t: -len(t[1]))[:n_top]:
        salida.append(
            {
                "evento": e,
                "filas": len(filas),
                "porcentaje_filas": round(len(filas) / total, 4),
                "tema_humano": Counter(real[filas]).most_common(1)[0][0],
                "aciertos": f"{int(acierta[filas].sum())}/{len(filas)}",
            }
        )
    return salida


def concentracion_por_tema(real: np.ndarray, eventos: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Por tema humano: filas, eventos y cuánto pesa su evento mayor (una fila 20/20 puede ser un solo evento)."""
    salida: dict[str, dict[str, Any]] = {}
    for c in dict.fromkeys(real):
        ev = Counter(e for e, r in zip(eventos, real, strict=True) if r == c)
        mayor = max(ev.values())
        salida[str(c)] = {
            "filas": sum(ev.values()),
            "eventos": len(ev),
            "filas_del_evento_mayor": mayor,
            "porcentaje_evento_mayor": round(mayor / sum(ev.values()), 4),
        }
    return salida


# ------------------------------------------------------------------ sistemas y curva de abstención


def puntos_de_abstencion(cfg: ConfigClasificacion) -> list[tuple[str, float | None]]:
    """``(nombre, umbral)``: sin abstención y cada umbral que YA está en el YAML para el modelo activo (de menor a mayor)."""
    umbrales = cfg.modelos[cfg.modelo_activo].umbrales
    puntos: list[tuple[str, float | None]] = [("sin_abstencion", None)]
    for metodo, u in sorted(umbrales.items(), key=lambda t: t[1].umbral_sin_tema):
        activo = " (activo)" if metodo == cfg.metodo_activo else ""
        puntos.append((f"umbral_del_metodo_{metodo}_{u.umbral_sin_tema}{activo}", u.umbral_sin_tema))
    return puntos


def _nombre_activo(puntos: list[tuple[str, float | None]]) -> str:
    return next(n for n, _ in puntos if "(activo)" in n)


def predicciones_de_sistemas(conj: Conjunto, cfg: ConfigClasificacion, temas: ConfigTemas) -> dict[str, np.ndarray]:
    """Predicciones (una fila de ``n``) del método A en cada punto de la curva y de los dos baselines por palabras clave."""
    salida: dict[str, np.ndarray] = {}
    for nombre, umbral in puntos_de_abstencion(cfg):
        salida[f"{cfg.modelo_activo}/{cfg.metodo_activo}: {nombre}"] = dg.decidir_con_umbral(conj.similitud, conj.temas, -np.inf if umbral is None else umbral)
    for etiqueta, variante in (("baseline_guia", "guia"), ("baseline_ampliado", "ampliado")):
        b = Baseline(cfg, temas, variante)
        salida[etiqueta] = np.array([b.clasificar(t).principal for t in conj.textos], dtype=object)
    return salida


def evaluar_subconjuntos(
    conj: Conjunto, preds: dict[str, np.ndarray], nuevas: set[str], criterio: CriterioAB, z: float, min_eventos_ic: int
) -> dict[str, Any]:
    """C-12: las mismas predicciones, separadas en filas ``originales`` y ``nuevas`` (``nuevas`` = ids de la hoja incorporada).

    Cada subconjunto se mide con sus propios eventos: el evento de una fila nueva se cuenta aparte aunque comparta nombre de grupo
    con uno original. No se vuelve a predecir ni a calibrar nada (las predicciones por fila no dependen de las demás filas).
    ``eventos_nuevos`` = eventos del conjunto ampliado que no existían en el original. Es una descripción de composición, no una
    comparación de métodos ni de versiones del sistema.
    """
    esta = np.array([i in nuevas for i in conj.ids], dtype=bool)
    salida: dict[str, Any] = {}
    for nombre, mascara in (("originales", ~esta), ("nuevas", esta)):
        filas = np.flatnonzero(mascara)
        y, eventos = conj.y[filas], [conj.eventos[k] for k in filas]
        salida[nombre] = {
            "filas": len(filas),
            "eventos": len(set(eventos)),
            "filas_por_tema": dict(Counter(y)),
            "sistemas": (
                {n: evaluar_sistema(y, p[filas][None, :], eventos, conj.clases, criterio, z, min_eventos_ic) for n, p in preds.items()}
                if len(filas)
                else {}
            ),
        }
    de_originales = {conj.eventos[k] for k in np.flatnonzero(~esta)}
    salida["eventos_nuevos"] = len({conj.eventos[k] for k in np.flatnonzero(esta)} - de_originales)
    return salida


def evaluar(conj: Conjunto, cfg: ConfigClasificacion, temas: ConfigTemas, z: float, nuevas: set[str] | None = None) -> dict[str, Any]:
    """Todo el informe por evento (sin escribir nada). Con ``nuevas`` agrega ``por_subconjunto`` (originales y nuevas, C-12)."""
    criterio, min_ic = cfg.criterio_ab, cfg.por_evento.min_eventos_ic
    preds = predicciones_de_sistemas(conj, cfg, temas)
    sistemas = {n: evaluar_sistema(conj.y, p[None, :], conj.eventos, conj.clases, criterio, z, min_ic) for n, p in preds.items()}
    activo = next(n for n in preds if "(activo)" in n)
    comparaciones = {}
    for n, p in preds.items():
        if n == activo:
            continue
        a = sistemas[activo]
        d_exact = dg.diferencia_por_evento(preds[activo] == conj.y, p == conj.y, conj.eventos, criterio)
        d_f1 = diferencia_macro_f1_por_evento(conj.y, preds[activo][None, :], p[None, :], conj.eventos, conj.clases, criterio)
        comparaciones[n] = {
            "exactitud_por_evento_menos_activo": d_exact,
            "macro_f1_menos_activo": d_f1,
            "ic_exactitud_se_solapan": se_solapan(a["exactitud_por_evento"]["ic95"], sistemas[n]["exactitud_por_evento"]["ic95"]),
            "ic_macro_f1_se_solapan": se_solapan(a["macro_f1_por_evento"]["ic95"], sistemas[n]["macro_f1_por_evento"]["ic95"]),
        }
    ev_dom = eventos_dominantes(conj.y, conj.eventos, preds[activo] == conj.y, cfg.por_evento.eventos_dominantes)
    sin_dominante = np.array([e not in {d["evento"] for d in ev_dom[:1]} for e in conj.eventos])
    informe: dict[str, Any] = {
        "modelo": cfg.modelo_activo,
        "metodo": cfg.metodo_activo,
        "sistema_activo": activo,
        "exploratorio": True,
        "advertencia": ADVERTENCIA,
        "conjunto": {
            "origenes": list(oe.SOLO_HUMANOS),
            "usa_etiquetas_provisionales": False,
            "etiquetados_humanos_en_csv": conj.etiquetados_en_csv,
            "ejemplos_excluidos_descartados": conj.excluidos_descartados,
            "filas": len(conj.y),
            "eventos": len(set(conj.eventos)),
            "filas_por_tema": dict(Counter(conj.y)),
            "bootstrap": {"remuestreos": criterio.remuestreos, "confianza": criterio.confianza, "semilla": criterio.semilla, "unidad": "evento"},
        },
        "sistemas": sistemas,
        "comparaciones_con_el_activo": comparaciones,
        "eventos_dominantes_del_activo": ev_dom,
        "concentracion_por_tema": concentracion_por_tema(conj.y, conj.eventos),
        "activo_sin_el_evento_mayor": {
            "filas": int(sin_dominante.sum()),
            "exactitud_por_fila": proporcion(int((preds[activo] == conj.y)[sin_dominante].sum()), int(sin_dominante.sum()), z),
        },
    }
    if nuevas is not None:
        informe["por_subconjunto"] = evaluar_subconjuntos(conj, preds, nuevas, criterio, z, min_ic)
    return informe


# ------------------------------------------------------------------ impresión (solo cifras)


def _ic(d: dict[str, Any] | None) -> str:
    return "n/d" if d is None else f"{d['valor']:.3f} [{d['ic95'][0]:.3f}–{d['ic95'][1]:.3f}] ({d['eventos']} eventos)"


def _p(d: dict[str, Any]) -> str:
    return f"{d['n']}/{d['de']} = {100 * d['proporcion']:.1f} % [{100 * d['ic95'][0]:.1f}–{100 * d['ic95'][1]:.1f}]"


def _lineas_sistemas(sistemas: dict[str, Any]) -> list[str]:
    lineas: list[str] = []
    for n, s in sistemas.items():
        m = s["macro_f1_por_evento"]
        lineas += [
            f"\n[{n}]",
            f"  exactitud: filas {_p(s['exactitud_por_fila'])}; eventos {_ic(s['exactitud_por_evento'])}",
            f"  macro-F1 por evento: {m['valor']} IC95 {m['ic95']} ({m['eventos']} eventos)",
            f"  cobertura: filas {_p(s['cobertura_por_fila'])}; eventos {_ic(s['cobertura_por_evento'])}",
            f"  exactitud entre cubiertas: filas {_p(s['exactitud_entre_cubiertas_por_fila'])}; eventos {_ic(s['exactitud_entre_cubiertas_por_evento'])}",
        ]
        for t, v in s["recall_por_tema"].items():
            ic = "sin IC (un evento)" if v["ic95"] is None else f"IC95 {v['ic95']}"
            lineas.append(f"  recall {t}: filas {v['filas']['n']}/{v['filas']['de']}; por evento {v['recall_por_evento']:.3f} {ic} ({v['eventos']} eventos)")
    return lineas


def _lineas_subconjuntos(sub: dict[str, Any]) -> list[str]:
    lineas = [f"\n== C-12 · por subconjunto (descripción de composición, no comparación de métodos) · eventos nuevos: {sub['eventos_nuevos']} =="]
    for nombre in ("originales", "nuevas"):
        s = sub[nombre]
        lineas += [f"\n-- {nombre}: {s['filas']} filas, {s['eventos']} eventos; filas por tema: {s['filas_por_tema']}", *_lineas_sistemas(s["sistemas"])]
    return lineas


def imprimir(r: dict[str, Any]) -> list[str]:
    c = r["conjunto"]
    lineas = [f"== Clasificación por evento · {r['modelo']}/{r['metodo']} · {c['filas']} filas, {c['eventos']} eventos (solo etiquetas humanas) ==", r["advertencia"]]
    lineas += _lineas_sistemas(r["sistemas"])
    lineas.append("\nComparaciones con el sistema activo (b − activo, pareadas por evento):")
    for n, k in r["comparaciones_con_el_activo"].items():
        e, f = k["exactitud_por_evento_menos_activo"], k["macro_f1_menos_activo"]
        lineas.append(
            f"- {n}: Δ exactitud {e['diferencia']:+} IC95 {e['ic95']} (excluye cero: {e['excluye_cero']}); "
            f"Δ macro-F1 {f['diferencia']} IC95 {f['ic95']} (excluye cero: {f['excluye_cero']}); IC solapados: exactitud {k['ic_exactitud_se_solapan']}, macro-F1 {k['ic_macro_f1_se_solapan']}"
        )
    lineas.append("\nEventos dominantes (activo): " + "; ".join(f"{d['evento']} {d['filas']} filas ({100 * d['porcentaje_filas']:.1f} %, {d['tema_humano']}, aciertos {d['aciertos']})" for d in r["eventos_dominantes_del_activo"]))
    lineas.append("Concentración por tema: " + "; ".join(f"{t} {v['filas']} filas/{v['eventos']} eventos (mayor {v['filas_del_evento_mayor']})" for t, v in r["concentracion_por_tema"].items()))
    s = r["activo_sin_el_evento_mayor"]
    lineas.append(f"Activo sin el evento mayor: {_p(s['exactitud_por_fila'])}")
    if "por_subconjunto" in r:
        lineas += _lineas_subconjuntos(r["por_subconjunto"])
    return lineas


def main(argv: list[str] | None = None) -> int:
    """CLI: imprime las cifras y escribe ``outputs/clasificacion_por_evento.json``."""
    parser = argparse.ArgumentParser(description="C-10b: clasificación por evento, con y sin abstención")
    parser.add_argument("--etiquetas", type=Path, default=evalclas.ETIQUETAS)
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    parser.add_argument(
        "--subconjuntos", action="store_true",
        help="C-12: además del total, mide por separado las filas del estrato de la hoja incorporada (ampliado.estrato_hoja) y las demás",
    )
    args = parser.parse_args(argv)
    if not args.etiquetas.exists() or not args.base.exists():
        print(f"Faltan {args.etiquetas} o {args.base}: no se calcula nada (no se inventan métricas).", file=sys.stderr)
        return evalclas.CODIGO_SIN_ETIQUETAS
    cfg, temas = cargar_clasificacion(), cargar_temas()
    nuevas: set[str] | None = None
    if args.subconjuntos:
        etiquetas, _ = leer_etiquetas_y_grupos(args.etiquetas, temas)
        nuevas = {i for i, e in etiquetas.items() if e.estrato == cfg.ampliado.estrato_hoja}
    informe = evaluar(cargar_conjunto(args.etiquetas, args.base, cfg, temas), cfg, temas, cargar_carga().salida.z_intervalo_confianza, nuevas)
    print("\n".join(imprimir(informe)))
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
