"""Diagnóstico de los errores de tema contra etiquetas humanas (E1-07b), con n e IC y sin tocar el clasificador.

Pregunta: ¿por qué hay grupos del snapshot con el tema equivocado y qué corrección está respaldada por las etiquetas
humanas de ``eval/etiquetas.csv`` (D-85)? El módulo **mide y no corrige**: no escribe ``config/`` ni la base. Reporta:

1. **Descomposición de los errores** del clasificador activo: abstención falsa (tenía tema y se abstuvo), abstención
   omitida (no tenía tema y se asignó uno) y confusión entre temas.
2. **Unidad de análisis.** Las filas se repiten (un mismo hecho en varios titulares, p. ej. 20 titulares de El Niño), así
   que el n efectivo es el número de **eventos** (``grupo`` de la etiqueta, o la propia noticia si no tiene). Cada
   métrica se da por fila (IC de Wilson) y por evento (IC de bootstrap sobre eventos).
3. **¿Se puede abstener por similitud?** AUC de la similitud máxima, del margen y de la similitud con una clase
   «fuera de temas» para separar lo que una persona marcó sin tema (pocos positivos: se dice cuántos).
4. **Calibración del umbral con validación cruzada por evento.** El umbral se elige en los pliegues de entrenamiento y
   se mide en el pliegue que no vio; nunca se reporta una cifra elegida con las mismas etiquetas que la miden.
5. **Opciones** (abstención por margen, clase «fuera de temas», cobertura de Economía regional) con su efecto sobre las
   etiquetas y sobre los titulares útiles del snapshot. Los puntos de corte se definen por **percentil sobre los titulares
   útiles del snapshot** (no usan las etiquetas), y los textos de las referencias exploratorias están escritos aquí, a
   partir de ``docs/guia_temas.md`` y de la regla D-84.

**Tres vías (D-101).** ``diagnosticar_en_tres_vias`` repite el diagnóstico con las etiquetas ``humano`` (las de la persona,
D-85), con las ``asistente_provisional`` solas y con las dos juntas. Estas últimas las propuso un agente y las aprobó
provisionalmente el asistente (riesgo de circularidad, pendientes de la revisión humana C-09): todo resultado que las use se
marca como PROVISIONAL en el JSON y en la impresión, y la conclusión se toma de la vía humana o, con la salvedad, de la combinada.

Limitaciones que el reporte repite: una sola persona etiquetó; las etiquetas son un censo del estrato «no ruido» del
snapshot anterior, así que **no hay datos de prueba independientes** de los que se usaron para diagnosticar; y
``sin_tema`` tiene muy pocos casos. Uso: ``HF_HUB_OFFLINE=1 poetry run python -m eval.diagnostico_temas``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from eval import clasificacion as evalclas
from eval import metricas
from eval import origen_etiquetas as oe
from src import db
from src.baseline import SIN_TEMA
from src.clasificacion import METODO_A, construir_referencias, proporcion, puntuar, texto_de_entrada
from src.configuracion import (
    RAIZ,
    ConfigClasificacion,
    ConfigTemas,
    CriterioAB,
    EjemploTema,
    cargar_carga,
    cargar_clasificacion,
    cargar_normalizacion,
    cargar_temas,
)
from src.embeddings import Embeddings, crear
from src.limpieza import Reglas

SALIDA = RAIZ / "outputs" / "diagnostico_temas.json"

# Procedimiento declarado ANTES de medir (no son parámetros del sistema, como en eval/calibrar_clasificacion.py).
PLIEGUES = 5                    # validación cruzada por evento
REPETICIONES = 20               # particiones aleatorias distintas, para ver cuánto se mueve el resultado
SEMILLA_CV = 20261007
PORCENTAJES_MARGEN = (10, 20, 30)       # abstenerse en el p % de titulares útiles con menor margen
PORCENTAJES_FUERA = (1, 5, 10)          # abstenerse en el p % de titulares útiles más parecidos a «fuera de temas»
OBJETIVOS = ("macro_f1", "exactitud")  # qué se maximiza al elegir el umbral en el entrenamiento
MIN_EVENTOS_POR_VIA = PLIEGUES          # una vía con menos eventos que pliegues no admite validación cruzada: no se calcula
MIN_POSITIVOS_CONFIABLES = 30           # por debajo, una proporción o un AUC son anecdóticos; el reporte lo dice

ADVERTENCIA_BASE = (
    "Una sola persona etiquetó (D-85); las etiquetas son un censo del estrato «no ruido» del snapshot anterior: "
    "no hay datos de prueba independientes de los usados para diagnosticar."
)
ADVERTENCIA_PROVISIONAL = oe.AVISO_PROVISIONAL
ADVERTENCIA_SOLO_PROVISIONAL = "Ninguna persona etiquetó estas filas: las propuso un agente y las aprobó provisionalmente el asistente."
VIAS = {
    "humano": (oe.HUMANO,),
    "asistente_provisional": (oe.ASISTENTE_PROVISIONAL,),
    "combinado": (oe.HUMANO, oe.ASISTENTE_PROVISIONAL),
}

# Referencias EXPLORATORIAS (no son del sistema; no se escribieron mirando los titulares etiquetados, sino a partir de la
# guía: «Fuera de los temas» y la regla D-84 de alcance regional).
REFERENCIAS_FUERA_DE_TEMAS = (
    "Selección nacional de fútbol gana el partido amistoso y avanza en el torneo",
    "Cantante estrena su nuevo videoclip y anuncia una gira de conciertos",
    "Actriz famosa revela detalles de su vida sentimental",
    "Festival internacional de cine y feria del libro abren sus puertas al público",
    "Partido político presenta a su candidato y define la estrategia de la campaña electoral",
    "Primarias de los partidos: aspirantes disputan la nominación presidencial",
    "Panama City, Florida: huracán y turistas en la playa",
    "Empresa extranjera cierra negocios en otro país sin relación con Panamá",
    "Equipo de béisbol de las Grandes Ligas gana la serie",
    "Obra de teatro y exposición de arte inauguran la temporada cultural",
)
ECONOMIA_REGIONAL_DESCRIPCION = (
    " También cubre la economía de la región (Centroamérica y América Latina) y las decisiones económicas externas que "
    "afectan a Panamá: financiamiento multilateral, comercio, inversión extranjera y cooperación."
)
ECONOMIA_REGIONAL_EJEMPLOS = (
    "Banco multilateral aprueba financiamiento para proyectos de infraestructura en América Latina",
    "Tensiones comerciales y aranceles presionan las exportaciones de Centroamérica",
    "Inversión extranjera directa en la región crece en el primer semestre",
    "Organismos internacionales proyectan el crecimiento de las economías latinoamericanas",
    "Misión oficial busca atraer inversión extranjera y firmar acuerdos comerciales",
    "Potencias recortan la cooperación económica y reorientan fondos hacia la región",
)


class EtiquetasInsuficientes(ValueError):
    """La vía tiene menos eventos etiquetados que pliegues de validación cruzada: no se calcula (no se inventan métricas)."""

    def __init__(self, evaluados: int, eventos: int) -> None:
        super().__init__(f"{evaluados} filas en {eventos} eventos: menos de {MIN_EVENTOS_POR_VIA} eventos, no se calcula")
        self.evaluados, self.eventos = evaluados, eventos


# ------------------------------------------------------------------ estadística básica


def auc_mayor(
    positivos: np.ndarray, negativos: np.ndarray, pesos_pos: np.ndarray | None = None, pesos_neg: np.ndarray | None = None
) -> float | None:
    """Probabilidad de que un positivo tenga un valor MAYOR que un negativo (un empate cuenta 0.5); ``None`` sin base.

    Con pesos (1 / filas de su evento) cada evento cuenta una sola vez.
    """
    if len(positivos) == 0 or len(negativos) == 0:
        return None
    wp = np.ones(len(positivos)) if pesos_pos is None else np.asarray(pesos_pos, dtype=float)
    wn = np.ones(len(negativos)) if pesos_neg is None else np.asarray(pesos_neg, dtype=float)
    mayor = (positivos[:, None] > negativos[None, :]).astype(float) + 0.5 * (positivos[:, None] == negativos[None, :])
    return float((mayor * wp[:, None] * wn[None, :]).sum() / (wp.sum() * wn.sum()))


def _por_evento(valores: np.ndarray, eventos: list[str]) -> tuple[np.ndarray, list[str]]:
    """Media de ``valores`` dentro de cada evento (orden de primera aparición) y los nombres de los eventos."""
    nombres = list(dict.fromkeys(eventos))
    indice = {e: k for k, e in enumerate(nombres)}
    suma, cuenta = np.zeros(len(nombres)), np.zeros(len(nombres))
    for v, e in zip(valores.astype(float), eventos, strict=True):
        suma[indice[e]] += v
        cuenta[indice[e]] += 1
    return suma / cuenta, nombres


def _ic_bootstrap(medias: np.ndarray, criterio: CriterioAB) -> list[float]:
    rng = np.random.default_rng(criterio.semilla)
    muestras = rng.integers(0, len(medias), size=(criterio.remuestreos, len(medias)))
    alfa = (1 - criterio.confianza) / 2 * 100
    bajo, alto = np.percentile(medias[muestras].mean(axis=1), [alfa, 100 - alfa])
    return [round(float(bajo), 4), round(float(alto), 4)]


def exactitud_por_evento(aciertos: np.ndarray, eventos: list[str], criterio: CriterioAB) -> dict[str, Any]:
    """Exactitud promediada por evento (cada evento pesa 1) con IC de bootstrap sobre eventos."""
    medias, _ = _por_evento(aciertos, eventos)
    return {"valor": round(float(medias.mean()), 4), "ic95": _ic_bootstrap(medias, criterio), "eventos": len(medias), "remuestreos": criterio.remuestreos}


def diferencia_por_evento(antes: np.ndarray, despues: np.ndarray, eventos: list[str], criterio: CriterioAB) -> dict[str, Any]:
    """Cambio de exactitud por evento (``despues − antes``), pareado, con IC de bootstrap sobre eventos."""
    a, _ = _por_evento(antes, eventos)
    b, _ = _por_evento(despues, eventos)
    ic = _ic_bootstrap(b - a, criterio)
    return {
        "diferencia": round(float((b - a).mean()), 4),
        "ic95": ic,
        "excluye_cero": bool(ic[0] > 0 or ic[1] < 0),
        "eventos": len(a),
        "eventos_que_cambian": int((a != b).sum()),
    }


def descomponer_errores(real: list[str], pred: list[str]) -> dict[str, int]:
    """Aciertos y los tres tipos de error. ``sin_tema`` real = una persona dijo que no corresponde a ningún tema."""
    r: Counter[str] = Counter()
    for a, b in zip(real, pred, strict=True):
        if a == b:
            r["aciertos"] += 1
        elif b == SIN_TEMA:
            r["abstencion_falsa"] += 1
        elif a == SIN_TEMA:
            r["abstencion_omitida"] += 1
        else:
            r["confusion_entre_temas"] += 1
    return {k: r[k] for k in ("aciertos", "abstencion_falsa", "abstencion_omitida", "confusion_entre_temas")} | {"total": len(real)}


# ------------------------------------------------------------------ validación cruzada por evento


def pliegues_por_evento(eventos: list[str], pliegues: int, semilla: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """(entrenamiento, prueba) por pliegue; los eventos completos van a un solo lado (sin fuga entre duplicados)."""
    unicos = list(dict.fromkeys(eventos))
    orden = np.random.default_rng(semilla).permutation(len(unicos))
    partes = np.array_split(orden, min(pliegues, len(unicos)))
    arreglo = np.array(eventos)
    salida = []
    for parte in partes:
        en_prueba = np.isin(arreglo, [unicos[k] for k in parte])
        salida.append((np.flatnonzero(~en_prueba), np.flatnonzero(en_prueba)))
    return salida


def decidir_con_umbral(sims: np.ndarray, temas: list[str], umbral: float) -> np.ndarray:
    """Tema de mayor similitud, o ``sin_tema`` si esa similitud es menor que ``umbral``."""
    mejor, valor = sims.argmax(axis=1), sims.max(axis=1)
    return np.array([temas[j] if v >= umbral else SIN_TEMA for j, v in zip(mejor, valor, strict=True)], dtype=object)


def calibrar_umbral_cv(
    sims: np.ndarray, temas: list[str], real: np.ndarray, eventos: list[str], clases: list[str], pliegues: int, repeticiones: int, semilla: int,
    objetivo: str = "macro_f1",
) -> dict[str, Any]:
    """Elige el umbral de ``sin_tema`` por ``objetivo`` (``macro_f1`` o ``exactitud``) en el entrenamiento y lo mide en el pliegue de prueba (por evento).

    Candidatos (solo del entrenamiento): «nunca abstenerse» y los puntos medios entre similitudes máximas vecinas. Ante un
    empate gana el umbral menor (menos abstención). Devuelve el promedio de las ``repeticiones`` particiones y cuánto varió el umbral elegido.
    """
    if objetivo not in OBJETIVOS:
        raise ValueError(f"objetivo {objetivo!r} desconocido (use {OBJETIVOS})")
    real = np.asarray(real, dtype=object)
    maxima = sims.max(axis=1)
    filas: list[dict[str, float]] = []
    elegidos: list[float] = []
    for rep in range(repeticiones):
        oof = np.empty(len(real), dtype=object)
        for entrenamiento, prueba in pliegues_por_evento(eventos, pliegues, semilla + rep):
            observadas = np.unique(maxima[entrenamiento])          # candidatos SOLO del entrenamiento (sin fuga de la prueba)
            candidatos = np.r_[-np.inf, (observadas[:-1] + observadas[1:]) / 2]   # puntos medios entre similitudes vecinas

            def puntaje(u: float) -> float:
                predicho = decidir_con_umbral(sims[entrenamiento], temas, u)
                if objetivo == "exactitud":
                    return float((predicho == real[entrenamiento]).mean())
                f1 = metricas.macro_f1(list(real[entrenamiento]), list(predicho), clases)
                return -1.0 if f1 is None else f1

            valores = [puntaje(u) for u in candidatos]
            mejor = candidatos[int(np.argmax(valores))]          # argmax devuelve el primero: el umbral menor
            elegidos.append(float(mejor))
            oof[prueba] = decidir_con_umbral(sims[prueba], temas, mejor)
        sin = real == SIN_TEMA
        f1 = metricas.macro_f1(list(real), list(oof), clases)
        filas.append(
            {
                "exactitud": float((oof == real).mean()),
                "macro_f1": 0.0 if f1 is None else f1,
                "abstenciones": float((oof == SIN_TEMA).sum()),
                "abstenciones_correctas": float(((oof == SIN_TEMA) & sin).sum() / sin.sum()) if sin.any() else float("nan"),
                "abstenciones_falsas": float(((oof == SIN_TEMA) & ~sin).sum()),
            }
        )
    finitos = [u for u in elegidos if np.isfinite(u)]
    media = lambda k: round(float(np.nanmean([f[k] for f in filas])), 4)  # noqa: E731
    return {
        "exactitud_fuera_de_muestra": media("exactitud"),
        "macro_f1_fuera_de_muestra": media("macro_f1"),
        "abstenciones_correctas_fuera_de_muestra": media("abstenciones_correctas"),
        "abstenciones_por_corrida": media("abstenciones"),
        "abstenciones_falsas_por_corrida": media("abstenciones_falsas"),
        "umbral_elegido": {
            "veces_sin_abstenerse": int(len(elegidos) - len(finitos)),
            "decisiones": len(elegidos),
            "minimo": None if not finitos else round(min(finitos), 4),
            "mediana": None if not finitos else round(float(np.median(finitos)), 4),
            "maximo": None if not finitos else round(max(finitos), 4),
        },
        "objetivo": objetivo,
        "pliegues": pliegues,
        "repeticiones": repeticiones,
    }


# ------------------------------------------------------------------ datos


def _leer_grupos(ruta: Path, origenes: Iterable[str] = oe.SOLO_HUMANOS) -> dict[str, str]:
    """``id_noticia -> grupo`` de la etiqueta (vacío si no se agrupó), solo de las filas de ``origenes``."""
    return {fila["id_noticia"].strip(): (fila.get("grupo") or "").strip() for fila in oe.leer_filas(ruta, origenes)}


def _variante_economia(temas: ConfigTemas, descripcion: bool, ejemplos: bool) -> ConfigTemas:
    nueva = temas.model_copy(deep=True)
    eco = nueva.temas["economia"]
    nueva.temas["economia"] = eco.model_copy(
        update={
            "descripcion": eco.descripcion.rstrip() + ECONOMIA_REGIONAL_DESCRIPCION if descripcion else eco.descripcion,
            "ejemplos": [*eco.ejemplos, *(EjemploTema(titulo=t, real=False) for t in ECONOMIA_REGIONAL_EJEMPLOS)] if ejemplos else eco.ejemplos,
        }
    )
    return nueva


def _resumen_opcion(
    nombre: str, pred_util: np.ndarray, pred_actual: np.ndarray, etiquetado: np.ndarray, y: np.ndarray, eventos: list[str],
    clases: list[str], cfg: ConfigClasificacion, z: float, pred_ref: np.ndarray,
) -> dict[str, Any]:
    """Métricas de una opción sobre las etiquetas (n, IC) y su efecto sobre los titulares útiles del snapshot."""
    pred = pred_util[etiquetado]
    ok = pred == y
    por_tema = {t: f"{int((pred[y == t] == t).sum())}/{int((y == t).sum())}" for t in clases if (y == t).any()}
    sin = y == SIN_TEMA
    return {
        "opcion": nombre,
        "exactitud_por_fila": proporcion(int(ok.sum()), len(y), z),
        "exactitud_por_evento": exactitud_por_evento(ok, eventos, cfg.criterio_ab),
        "diferencia_por_evento_vs_actual": diferencia_por_evento(pred_ref == y, ok, eventos, cfg.criterio_ab),
        "macro_f1": metricas.macro_f1_con_ic(list(y), list(pred), clases, cfg.criterio_ab),
        "recall_por_tema": por_tema,
        "abstenciones": int((pred == SIN_TEMA).sum()),
        "abstenciones_falsas": int(((pred == SIN_TEMA) & ~sin).sum()),
        "abstenciones_correctas": f"{int(((pred == SIN_TEMA) & sin).sum())}/{int(sin.sum())}",
        "errores": descomponer_errores(list(y), list(pred)),
        "snapshot_titulares_utiles": {
            "total": len(pred_util),
            "pasan_a_sin_tema": int(((pred_util == SIN_TEMA) & (pred_actual != SIN_TEMA)).sum()),
            "salen_de_sin_tema": int(((pred_util != SIN_TEMA) & (pred_actual == SIN_TEMA)).sum()),
            "cambian_de_tema": int(((pred_util != pred_actual) & (pred_util != SIN_TEMA) & (pred_actual != SIN_TEMA)).sum()),
        },
    }


# ------------------------------------------------------------------ diagnóstico completo


def diagnosticar(
    ruta_etiquetas: Path,
    ruta_base: Path,
    cfg: ConfigClasificacion,
    temas: ConfigTemas,
    motores: dict[str, Any] | None = None,
    origenes: Iterable[str] = oe.SOLO_HUMANOS,
) -> dict[str, Any]:
    """Todo el diagnóstico para el modelo y método activos con las etiquetas de ``origenes`` (por defecto, las humanas).

    No modifica la base ni ``config/``. Lanza ``EtiquetasInsuficientes`` si hay menos eventos que pliegues.
    """
    origenes = oe.validar_origenes(origenes)
    nombre = cfg.modelo_activo
    metodo = cfg.metodo_activo
    if metodo != METODO_A:
        raise ValueError("el diagnóstico está escrito para el método A (activo); B quedó descartado en E1-07")
    umbral = cfg.modelos[nombre].umbrales[metodo].umbral_sin_tema
    z = cargar_carga().salida.z_intervalo_confianza
    reglas = Reglas.desde_config()
    etiquetas = evalclas.leer_etiquetas(ruta_etiquetas, "tema_principal", temas, origenes)
    grupos = _leer_grupos(ruta_etiquetas, origenes)
    excluidos = evalclas.ids_excluidos()
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = con.execute(
            "SELECT id_noticia, titulo_limpio, descripcion FROM noticias WHERE NOT es_ruido ORDER BY id_noticia"
        ).fetchall()
        tabla_grupos = con.execute("SELECT id_grupo, tema_clasificado, ids_noticia FROM grupos ORDER BY id_grupo").fetchall()
    finally:
        con.close()
    ids = [f[0] for f in filas]
    emb: Embeddings = crear(cfg, nombre, motor=(motores or {}).get(nombre))
    X = emb.codificar([texto_de_entrada(f[1], f[2], cfg.usar_descripcion) for f in filas], "titular")

    def similitudes(t: ConfigTemas) -> tuple[np.ndarray, list[str]]:
        ref = construir_referencias(emb, t, reglas)
        return puntuar(X, ref, METODO_A).similitud, ref.temas

    P, T = similitudes(temas)
    etiquetado = np.array([i in etiquetas and i not in excluidos for i in ids])
    id_ev = [i for i, e in zip(ids, etiquetado, strict=True) if e]
    y = np.array([etiquetas[i].tema for i in id_ev], dtype=object)
    eventos = [grupos.get(i) or i for i in id_ev]
    if len(set(eventos)) < MIN_EVENTOS_POR_VIA:
        raise EtiquetasInsuficientes(len(id_ev), len(set(eventos)))
    clases = evalclas.clases_de(temas)
    sin = y == SIN_TEMA
    pesos_evento = np.array([1 / Counter(eventos)[e] for e in eventos])

    actual = decidir_con_umbral(P, T, umbral)
    pred_actual_etq = actual[etiquetado]
    maxima, ordenadas = P.max(axis=1), np.sort(P, axis=1)
    margen = ordenadas[:, -1] - ordenadas[:, -2]
    sin_abstencion = decidir_con_umbral(P, T, -np.inf)

    # --- clase «fuera de temas» (referencia exploratoria)
    ref_fuera = emb.codificar(list(REFERENCIAS_FUERA_DE_TEMAS), "tema").mean(axis=0)
    ref_fuera /= np.linalg.norm(ref_fuera)
    brecha_fuera = X @ ref_fuera - maxima

    # --- señales de abstención
    et_max, et_marg, et_fuera = maxima[etiquetado], margen[etiquetado], brecha_fuera[etiquetado]
    correcto_sin_abstencion = sin_abstencion[etiquetado] == y
    senales = {
        "positivos_sin_tema": int(sin.sum()),
        "eventos_con_sin_tema": len({e for e, s in zip(eventos, sin, strict=True) if s}),
        "positivos_suficientes": bool(sin.sum() >= MIN_POSITIVOS_CONFIABLES),
        "auc_sin_tema_tiene_menor_similitud_maxima": auc_mayor(-et_max[sin], -et_max[~sin]),
        "auc_sin_tema_tiene_menor_margen": auc_mayor(-et_marg[sin], -et_marg[~sin]),
        "auc_sin_tema_se_parece_mas_a_fuera_de_temas": auc_mayor(et_fuera[sin], et_fuera[~sin]),
        "auc_acierto_tiene_mayor_similitud_maxima_por_evento": auc_mayor(
            et_max[correcto_sin_abstencion], et_max[~correcto_sin_abstencion],
            pesos_evento[correcto_sin_abstencion], pesos_evento[~correcto_sin_abstencion],
        ),
        "auc_acierto_tiene_mayor_margen_por_evento": auc_mayor(
            et_marg[correcto_sin_abstencion], et_marg[~correcto_sin_abstencion],
            pesos_evento[correcto_sin_abstencion], pesos_evento[~correcto_sin_abstencion],
        ),
        "nota": "AUC 0.5 = la señal no separa. Con 5 positivos cualquier AUC es anecdótico (ver positivos_suficientes).",
    }

    # --- opciones
    def con_margen(p: int) -> np.ndarray:
        corte = np.percentile(margen, p)
        return np.where(margen <= corte, SIN_TEMA, sin_abstencion).astype(object)

    def con_fuera(p: int) -> np.ndarray:
        corte = np.percentile(brecha_fuera, 100 - p)
        return np.where(brecha_fuera >= corte, SIN_TEMA, sin_abstencion).astype(object)

    opciones: dict[str, np.ndarray] = {"actual (umbral del YAML)": actual, "sin abstención por similitud": sin_abstencion}
    opciones.update({f"abstener en el {p} % de menor margen": con_margen(p) for p in PORCENTAJES_MARGEN})
    opciones.update({f"abstener en el {p} % más parecido a «fuera de temas»": con_fuera(p) for p in PORCENTAJES_FUERA})
    for etiqueta, d, e in (("Economía regional: solo descripción", True, False), ("Economía regional: solo ejemplos", False, True), ("Economía regional: descripción y ejemplos", True, True)):
        Pv, Tv = similitudes(_variante_economia(temas, d, e))
        opciones[etiqueta] = decidir_con_umbral(Pv, Tv, umbral)
    resumen = [
        _resumen_opcion(n, p, actual, etiquetado, y, eventos, clases, cfg, z, pred_actual_etq) for n, p in opciones.items()
    ]

    # --- validación cruzada del umbral (solo etiquetados)
    cv = {o: calibrar_umbral_cv(P[etiquetado], T, y, eventos, clases, PLIEGUES, REPETICIONES, SEMILLA_CV, o) for o in OBJETIVOS}

    # --- grupos del snapshot: ¿coincide el tema del grupo con el de las personas?
    por_id = {i: etiquetas[i].tema for i in ids if i in etiquetas and i not in excluidos}
    comparables = coinciden = 0
    detalle_grupos: list[dict[str, Any]] = []
    for id_grupo, tema_grupo, miembros in tabla_grupos:
        humanos = [por_id[m] for m in str(miembros).split(",") if m in por_id] if miembros else []
        if not humanos:
            continue
        comparables += 1
        mayoritario = Counter(humanos).most_common(1)[0][0]
        coinciden += tema_grupo == mayoritario
        detalle_grupos.append({"id_grupo": id_grupo, "tema_del_grupo": tema_grupo, "tema_humano_mayoritario": mayoritario, "etiquetados": len(humanos)})

    return {
        "modelo": nombre,
        "metodo": metodo,
        "umbral_sin_tema_en_yaml": umbral,
        "conjunto": {
            "etiquetados_en_csv": len(etiquetas),
            "ejemplos_excluidos_descartados": sum(1 for i in etiquetas if i in excluidos),
            "evaluados": int(etiquetado.sum()),
            "eventos": len(set(eventos)),
            "por_tema_humano": dict(Counter(y)),
            "titulares_utiles_del_snapshot": len(ids),
            "origenes": list(origenes),
            "usa_etiquetas_provisionales": oe.ASISTENTE_PROVISIONAL in origenes,
            "advertencia": _advertencia(origenes),
        },
        "errores_del_clasificador_activo": {
            "por_fila": descomponer_errores(list(y), list(pred_actual_etq)),
            "por_evento": exactitud_por_evento(pred_actual_etq == y, eventos, cfg.criterio_ab),
        },
        "senales_de_abstencion": senales,
        "calibracion_umbral_validacion_cruzada_por_evento": cv,
        "opciones": resumen,
        "grupos_del_snapshot": {
            "grupos": len(tabla_grupos),
            "con_algun_titular_etiquetado": comparables,
            "tema_del_grupo_igual_al_humano_mayoritario": proporcion(coinciden, comparables, z),
            "detalle": detalle_grupos,
            "nota": "Comparación con etiquetas humanas; los grupos sin ningún titular etiquetado no se pueden evaluar.",
        },
    }


def _advertencia(origenes: Iterable[str]) -> str:
    """El aviso propio de cada combinación de procedencias (no se dice «una persona etiquetó» donde no etiquetó ninguna)."""
    origenes = oe.validar_origenes(origenes)
    if oe.ASISTENTE_PROVISIONAL not in origenes:
        return ADVERTENCIA_BASE
    if oe.HUMANO not in origenes:
        return f"{ADVERTENCIA_PROVISIONAL} {ADVERTENCIA_SOLO_PROVISIONAL}"
    return f"{ADVERTENCIA_PROVISIONAL} Mezcla las 100 etiquetas de una persona (D-85) con las 61 provisionales. {ADVERTENCIA_BASE}"


def avisos_por_via() -> dict[str, str]:
    """El aviso de cada vía del informe en tres vías."""
    return {nombre: _advertencia(origenes) for nombre, origenes in VIAS.items()}


def diagnosticar_en_tres_vias(
    ruta_etiquetas: Path, ruta_base: Path, cfg: ConfigClasificacion, temas: ConfigTemas, motores: dict[str, Any] | None = None
) -> dict[str, Any]:
    """El mismo diagnóstico con las etiquetas humanas, con las provisionales (D-101) solas y con las dos juntas.

    Cada vía dice si usa etiquetas provisionales y lleva su aviso. Una vía con menos eventos que pliegues queda como
    ``INSUFICIENTE`` (con sus conteos) en vez de calcular métricas sin base.
    """
    vias: dict[str, Any] = {}
    for nombre, origenes in VIAS.items():
        provisional = oe.ASISTENTE_PROVISIONAL in origenes
        via: dict[str, Any] = {
            "origenes": list(origenes),
            "usa_etiquetas_provisionales": provisional,
            "aviso": _advertencia(origenes),
        }
        try:
            via["diagnostico"] = diagnosticar(ruta_etiquetas, ruta_base, cfg, temas, motores, origenes)
            via["estado"] = "CALCULADO"
            via["evaluados"] = via["diagnostico"]["conjunto"]["evaluados"]
        except EtiquetasInsuficientes as exc:
            via.update({"estado": "INSUFICIENTE", "evaluados": exc.evaluados, "eventos": exc.eventos, "detalle": str(exc)})
        vias[nombre] = via
    return {"vias": vias}


# ------------------------------------------------------------------ impresión


def _p(d: dict[str, Any]) -> str:
    return f"{d['n']}/{d['de']} = {100 * d['proporcion']:.1f} % [{100 * d['ic95'][0]:.1f}–{100 * d['ic95'][1]:.1f}]"


def imprimir(r: dict[str, Any]) -> list[str]:
    c, e, s = r["conjunto"], r["errores_del_clasificador_activo"], r["senales_de_abstencion"]
    f = e["por_fila"]
    lineas = [
        f"== Diagnóstico de temas · {r['modelo']}/{r['metodo']} · umbral sin_tema {r['umbral_sin_tema_en_yaml']} ==",
        f"Evaluados: {c['evaluados']} filas en {c['eventos']} eventos ({c['por_tema_humano']}); {c['advertencia']}",
        f"\nErrores del activo ({f['total']} filas): aciertos {f['aciertos']}, abstención falsa {f['abstencion_falsa']}, "
        f"abstención omitida {f['abstencion_omitida']}, confusión entre temas {f['confusion_entre_temas']}",
        f"Exactitud por evento: {e['por_evento']['valor']} IC95 {e['por_evento']['ic95']} (eventos = {e['por_evento']['eventos']})",
        f"\nSeñales de abstención (positivos sin_tema = {s['positivos_sin_tema']} en {s['eventos_con_sin_tema']} eventos; suficientes: {s['positivos_suficientes']}):",
    ]
    lineas += [f"  {k}: {None if v is None else round(v, 3)}" for k, v in s.items() if k.startswith("auc_")]
    for objetivo, cv in r["calibracion_umbral_validacion_cruzada_por_evento"].items():
        lineas.append(
            f"\nUmbral por validación cruzada por evento, objetivo {objetivo} ({cv['pliegues']} pliegues × {cv['repeticiones']} repeticiones): "
            f"exactitud fuera de muestra {cv['exactitud_fuera_de_muestra']}, macro-F1 {cv['macro_f1_fuera_de_muestra']}, "
            f"abstenciones correctas {cv['abstenciones_correctas_fuera_de_muestra']}, abstenciones por corrida {cv['abstenciones_por_corrida']} "
            f"(falsas {cv['abstenciones_falsas_por_corrida']}); umbral elegido {cv['umbral_elegido']}"
        )
    lineas.append("\nOpciones (etiquetas humanas; el efecto en el snapshot es sobre sus titulares útiles):")
    for o in r["opciones"]:
        d, sn = o["diferencia_por_evento_vs_actual"], o["snapshot_titulares_utiles"]
        lineas.append(
            f"- {o['opcion']}: filas {_p(o['exactitud_por_fila'])}; eventos {o['exactitud_por_evento']['valor']} {o['exactitud_por_evento']['ic95']}; "
            f"macro-F1 {o['macro_f1']['macro_f1']} {o['macro_f1']['ic95']}; Δ eventos vs actual {d['diferencia']:+} {d['ic95']} "
            f"(cambian {d['eventos_que_cambian']}); abstenciones {o['abstenciones']} (falsas {o['abstenciones_falsas']}, correctas {o['abstenciones_correctas']}); "
            f"recall {o['recall_por_tema']}; snapshot: →sin_tema {sn['pasan_a_sin_tema']}, sin_tema→tema {sn['salen_de_sin_tema']}, cambian de tema {sn['cambian_de_tema']} de {sn['total']}"
        )
    g = r["grupos_del_snapshot"]
    lineas.append(f"\nGrupos del snapshot con titulares etiquetados: {g['con_algun_titular_etiquetado']} de {g['grupos']}; tema del grupo = humano mayoritario: {_p(g['tema_del_grupo_igual_al_humano_mayoritario'])}")
    return lineas


def main(argv: list[str] | None = None) -> int:
    """CLI: imprime el diagnóstico y lo guarda en ``outputs/diagnostico_temas.json``."""
    parser = argparse.ArgumentParser(description="E1-07b: diagnóstico de los errores de tema contra etiquetas humanas")
    parser.add_argument("--etiquetas", type=Path, default=evalclas.ETIQUETAS)
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    if not args.etiquetas.exists() or not args.base.exists():
        print(f"Faltan {args.etiquetas} o {args.base}: no se calcula nada (no se inventan métricas).", file=sys.stderr)
        return evalclas.CODIGO_SIN_ETIQUETAS
    informe = diagnosticar_en_tres_vias(args.etiquetas, args.base, cargar_clasificacion(), cargar_temas())
    for nombre, via in informe["vias"].items():
        marca = " · PROVISIONAL (D-101)" if via["usa_etiquetas_provisionales"] else ""
        print(f"\n######## Vía «{nombre}»{marca} ########")
        print(via["aviso"])
        if via["estado"] == "CALCULADO":
            print("\n".join(imprimir(via["diagnostico"])))
        else:
            print(f"NO SE CALCULA: {via['detalle']}")
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
