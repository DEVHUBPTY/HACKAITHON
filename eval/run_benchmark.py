"""E1-18 · Benchmark y métricas de la sección 9.1 del reto (D-57, D-71).

    poetry run python -m eval.run_benchmark --split dev                              # benchmark/benchmark_dev.jsonl → outputs/benchmark/ + outputs/metricas.json
    poetry run python -m eval.run_benchmark --archivo <ruta> --salida <carpeta>      # evaluación reservada: el archivo lo trae el jurado

**Evaluación reservada.** ``--archivo`` acepta cualquier ``.jsonl`` con el formato de ``benchmark/README.md`` (obligatorios: ``id``, ``tipo``,
``consulta`` y ``debe_abstenerse``; el resto es opcional). Corre **sin internet** (el modelo de embeddings es local y la consulta no usa
LLM), solo **lee** el archivo —nunca lo copia al repositorio— y solo **escribe** en ``--salida``. En ``metricas.json`` el archivo se
identifica por su nombre y su SHA-256, nunca por su ruta. Nada de este módulo lee ni referencia el conjunto reservado.

**Qué mide.**

* *Cobertura de citas*: afirmaciones factuales emitidas con cita válida (ID existente + campo citable) / afirmaciones factuales emitidas,
  en las consultas y en los borradores. Aparte, cuántas pasan además el validador completo.
* *Abstención correcta* (``sin_respuesta`` rechazadas / ``sin_respuesta``, meta ≥ 80 %), *abstenciones incorrectas* (respondibles rechazadas)
  y la búsqueda (Recall@5, semántica vs. BM25 con diferencia pareada).
* *Latencia* p50 y p95 con n e IC; *tokens y costo*. La consulta no usa LLM (tokens 0, USD 0); el costo y la latencia del LLM son los del
  **borrador completo** y salen de una corrida real (``--medir-llm``), guardada en ``medicion_llm.json``.
* *Validez de sustento*: solo se **genera la muestra** (``outputs/revision_sustento.csv``); la juzga una persona (``eval.sustento``).
* *Análisis del umbral* (solo desarrollo): validación cruzada dejando uno afuera y curva descriptiva; nunca cambia la configuración.

Toda proporción lleva numerador, denominador, IC95 de bootstrap y de Wilson y los IDs de los fallos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from eval import metricas, sustento
from eval.recuperacion import ids_del_sistema, ids_recuperados, llega_a_la_similitud, truncar
from src.configuracion import RAIZ, CriterioAB, cargar_benchmark
from src.consulta import CAMPOS_CITABLES, RUTA_SINTETICOS, Consultor, RespuestaConsulta, crear_consultor, sanear, validar_citas
from src.embeddings import clave_cache
from src.esquemas import Afirmacion

logger = logging.getLogger(__name__)

BENCHMARK_DEV = RAIZ / "benchmark" / "benchmark_dev.jsonl"
SALIDA_DEV = RAIZ / "outputs" / "benchmark"
METRICAS_DEV = RAIZ / "outputs" / "metricas.json"
REVISION_DEV = RAIZ / "outputs" / "revision_sustento.csv"
TIPOS = ("respuesta_sustentada", "contradiccion_ambiguedad", "sin_respuesta", "adversarial")
VERSION_METRICAS = 1
_ARRANQUE_S = [0.0]   # segundos desde crear el consultor (índice y carga del modelo de embeddings) hasta el primer vector, en la última corrida


# ============================================================================================ lectura


def leer_consultas(ruta: Path) -> list[dict[str, Any]]:
    """Las consultas del archivo. Obligatorios ``id``, ``tipo`` (uno de los cuatro), ``consulta`` y ``debe_abstenerse`` (booleano); lo demás es opcional
    (``ids_evidencia`` por defecto vacío). Un error nombra **todas** las líneas inválidas."""
    consultas: list[dict[str, Any]] = []
    errores: list[str] = []
    vistos: set[str] = set()
    for n, linea in enumerate(Path(ruta).read_text(encoding="utf-8").splitlines(), 1):
        if not linea.strip():
            continue
        try:
            c = json.loads(linea)
        except ValueError:
            errores.append(f"línea {n}: no es JSON")
            continue
        problemas = []
        if not isinstance(c, dict):
            errores.append(f"línea {n}: no es un objeto JSON")
            continue
        if not isinstance(c.get("id"), str) or not c["id"].strip():
            problemas.append("falta id")
        elif c["id"] in vistos:
            problemas.append(f"id repetido {c['id']}")
        if c.get("tipo") not in TIPOS:
            problemas.append(f"tipo {c.get('tipo')!r} fuera de {list(TIPOS)}")
        if not isinstance(c.get("consulta"), str) or not c["consulta"].strip():
            problemas.append("consulta vacía")
        if not isinstance(c.get("debe_abstenerse"), bool):
            problemas.append("debe_abstenerse debe ser booleano")
        if not isinstance(c.get("ids_evidencia", []), list):
            problemas.append("ids_evidencia debe ser una lista")
        if problemas:
            errores.append(f"línea {n}: " + "; ".join(problemas))
            continue
        vistos.add(c["id"])
        consultas.append({**c, "ids_evidencia": list(c.get("ids_evidencia", []))})
    if errores:
        raise ValueError("benchmark inválido: " + " | ".join(errores))
    if not consultas:
        raise ValueError("benchmark vacío: no hay ninguna consulta")
    return consultas


def crear_consultor_real() -> Consultor:
    """El consultor con el corpus de la base local y los casos alterados de ``benchmark/sinteticos.csv`` (solo para evaluar)."""
    return crear_consultor(sinteticos=RUTA_SINTETICOS if RUTA_SINTETICOS.exists() else None)


# ============================================================================================ citas


def cita_valida(a: Any, campos_por_id: Mapping[str, Any]) -> bool:
    """Cita válida = toda cita de la afirmación es (ID que existe, campo citable de ese registro); y hay al menos una."""
    citas = getattr(a, "citas", None) or []
    return bool(citas) and all(c.id in campos_por_id and c.campo in campos_por_id[c.id] for c in citas)


def _campos_del_corpus(consultor: Consultor) -> dict[str, frozenset[str]]:
    return {i: CAMPOS_CITABLES[d.tipo] for i, d in consultor.indice.corpus.por_id.items()}


def _texto_evidencia(doc: Any, campo: str) -> str:
    d = doc.datos
    if doc.tipo == "noticia":
        return f"{campo}: «{d.get(campo)}» (medio: {d.get('medio')}; fecha_publicacion: {d.get('fecha_publicacion')})"
    if doc.tipo == "indicador":
        return f"{campo}: {d.get(campo)} (indicador {d.get('indicador_id')}, {d.get('pais_iso3')}, año {d.get('anio')}, unidad {d.get('unidad')})"
    return f"{campo}: {d.get(campo)} (lugar: {d.get('place')}; hora: {d.get('time')})"


def _citas_texto(a: Any) -> str:
    return "; ".join(f"{c.id} · {c.campo}" for c in a.citas)


# ============================================================================================ consultas


def _respuestas_a_registros(consultor: Consultor, consultas: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], RespuestaConsulta]]:
    emb = consultor.indice.emb
    emb.usar_cache = False   # nada de lo que se consulta aquí se persiste: la evaluación solo escribe en la carpeta de salida
    salida = []
    for c in consultas:
        # latencia en frío: el vector de la consulta (ya saneada) se descarta de la memoria para que el modelo la codifique de verdad
        emb._vectores.pop(clave_cache(emb.prefijo("titular"), sanear(c["consulta"], consultor.cfg).limpia), None)
        inicio = time.perf_counter()
        r = consultor.responder(c["consulta"])
        latencia = time.perf_counter() - inicio
        citados = sorted({e.id for e in r.evidencia})
        esperados = set(c["ids_evidencia"])
        registro = {
            "id": c["id"], "tipo": c["tipo"], "consulta": c["consulta"], "debe_abstenerse": c["debe_abstenerse"],
            "respuesta": r.model_dump(), "latencia_s": round(latencia, 6), "correcta": r.abstiene == c["debe_abstenerse"],
            "ids_evidencia_esperados": sorted(esperados), "evidencia_citada": citados,
            "esperada_citada": {"n": len(esperados & set(citados)), "de": len(esperados)},
        }
        salida.append((registro, r))
    return salida


def _prop_con_ids(pred_ok: list[bool], ids: list[str], criterio: CriterioAB, clave_ids: str = "fallos") -> dict[str, Any]:
    fallos = [i for i, ok in zip(ids, pred_ok, strict=True) if not ok]
    return {**metricas.proporcion_con_ic(len(ids) - len(fallos), len(ids), criterio), clave_ids: fallos}


def evaluar_consultas(
    consultor: Consultor, consultas: Sequence[dict[str, Any]], criterio: CriterioAB
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Corre cada consulta (método semántico, el del sistema) y calcula las métricas que dependen solo de ellas."""
    pares = _respuestas_a_registros(consultor, consultas)
    registros = [p[0] for p in pares]
    campos = _campos_del_corpus(consultor)
    por_id = {c["id"]: c for c in consultas}

    def seleccion(pred: Any) -> list[tuple[dict[str, Any], RespuestaConsulta]]:
        return [p for p in pares if pred(por_id[p[0]["id"]])]

    sin = seleccion(lambda c: c["tipo"] == "sin_respuesta")
    deben = seleccion(lambda c: c["debe_abstenerse"])
    sustentadas = seleccion(lambda c: c["tipo"] == "respuesta_sustentada")
    respondibles = seleccion(lambda c: not c["debe_abstenerse"])

    def abstencion(grupo: list[tuple[dict[str, Any], RespuestaConsulta]]) -> dict[str, Any]:
        return _prop_con_ids([r.abstiene for _, r in grupo], [reg["id"] for reg, _ in grupo], criterio)

    def incorrecta(grupo: list[tuple[dict[str, Any], RespuestaConsulta]]) -> dict[str, Any]:
        ids = [reg["id"] for reg, r in grupo if r.abstiene]
        return {**metricas.proporcion_con_ic(len(ids), len(grupo), criterio), "ids": ids,
                "motivos": {reg["id"]: r.motivo for reg, r in grupo if r.abstiene}}

    afirmaciones = [(reg["id"], a) for reg, r in pares for a in [*r.afirmaciones, *r.ultimo_dato_disponible]]
    ids_a = [f"{i}/{a.id}" for i, a in afirmaciones]
    validas = [cita_valida(a, campos) for _, a in afirmaciones]
    pasan = [not validar_citas([a], consultor.indice.corpus) for _, a in afirmaciones]
    esperados = {c["id"]: c["ids_evidencia"] for c in consultas if c["tipo"] in consultor.cfg.evaluacion.tipos_recuperacion and c["ids_evidencia"]}
    hallados = {
        "semantica": {i: ids_recuperados(consultor, por_id[i]["consulta"], "semantica") for i in esperados},
        "bm25": {i: ids_recuperados(consultor, por_id[i]["consulta"], "bm25") for i in esperados},
        "sistema": {i: ids_del_sistema(consultor, por_id[i]["consulta"]) for i in esperados},
    }
    latencias = [reg["latencia_s"] for reg in registros]
    m = {
        "por_tipo": dict(Counter(c["tipo"] for c in consultas)),
        "abstencion_correcta": {
            "sin_respuesta": abstencion(sin), "todas_las_que_debian": abstencion(deben),
            "meta": cargar_benchmark().metas.abstencion_correcta, "nota": "Numerador: consultas rechazadas; denominador: las que debían rechazarse. «todas_las_que_debian» suma las adversariales con debe_abstenerse.",
        },
        "abstenciones_incorrectas": {"sustentadas": incorrecta(sustentadas), "respondibles": incorrecta(respondibles),
                                     "nota": "Numerador: respondibles rechazadas; denominador: respondibles. Se reporta; no tiene meta."},
        "cobertura_de_citas": {
            "consultas": _prop_con_ids(validas, ids_a, criterio),
            "consultas_con_validador_de_citas": _prop_con_ids(pasan, ids_a, criterio),
            "nota": "Afirmaciones emitidas (respuestas y «último dato disponible» de las abstenciones). Cita válida = ID existente en el corpus + campo citable.",
        },
        "busqueda": {
            "k": consultor.cfg.recuperacion.top_k, "n_consultas": len(esperados),
            "metodos": {n: metricas.recall_con_ic(esperados, h, criterio) for n, h in hallados.items()},
            "semantica_menos_bm25": metricas.diferencia_recall(esperados, hallados["bm25"], hallados["semantica"], criterio),
            "sistema_menos_bm25": metricas.diferencia_recall(esperados, hallados["bm25"], hallados["sistema"], criterio),
            "nota": "Recall@5 por IDs sobre las consultas respuesta_sustentada con evidencia esperada; IC de bootstrap sobre consultas. «sistema» = búsqueda semántica más la cifra oficial exacta.",
        },
        "latencia": {"consulta": {"n": len(latencias), "unidad": "s", "p50": metricas.percentil_con_ic(latencias, 50, criterio),
                                  "p95": metricas.percentil_con_ic(latencias, 95, criterio),
                                  "arranque_modelo_s": _ARRANQUE_S[0],
                                  "nota": "consulta de punta a punta en frío (el vector de la consulta se codifica de verdad, sin caché) con el modelo de embeddings local ya cargado; sin red. arranque_modelo_s es el arranque en frío del proceso (armar el consultor y cargar el modelo hasta el primer vector) y no entra en la latencia"}},
        "tokens_y_costo": {"consulta": {"tokens_por_consulta": 0, "usd_por_consulta": 0.0,
                                        "nota": "La consulta no usa LLM (sin LLM): el único modelo es el de embeddings, local (USD 0)."}},
    }
    return registros, m


# ============================================================================================ umbral


def analisis_umbral(consultor: Consultor, consultas: Sequence[dict[str, Any]], criterio: CriterioAB) -> dict[str, Any]:
    """Cómo se comporta la puerta de similitud **sin evaluar sobre lo que calibró el umbral**.

    * *Validación cruzada dejando uno afuera*: para cada consulta que llega a la puerta, el umbral se recalcula con la misma regla de la
      configuración (percentil de la similitud máxima de las respondibles que llegan) **sin esa consulta**, y se evalúa solo en ella.
    * *Sensibilidad*: lo que rechazaría cada umbral de una rejilla. Es **descriptiva**: mirar la curva sobre las mismas consultas y elegir
      el mejor punto sería ajustar sobre la prueba, así que no se usa para cambiar la configuración.
    Las reglas por patrón y los demás rechazos no cambian: se toma lo que decidió el sistema. La configuración no se modifica.
    """
    cfg = consultor.cfg
    umbral_cfg = cfg.abstencion.umbral_similitud["semantica"]
    pct = cfg.abstencion.percentil_umbral
    datos = []
    for c in consultas:
        an, previa, oficial = consultor.decidir_previa(c["consulta"])
        llega = llega_a_la_similitud(consultor, c["consulta"])
        sim = consultor.indice.buscar(an.limpia, "semantica", 1)[0].puntaje if llega else None
        r = consultor.responder(c["consulta"])
        datos.append({"c": c, "llega": llega, "sim": sim, "abstiene": r.abstiene, "calibra": llega and c["tipo"] in cfg.evaluacion.tipos_con_respuesta})
    pool = [d["sim"] for d in datos if d["calibra"]]

    def con_umbral(d: dict[str, Any], umbral: float) -> bool:
        if not d["llega"]:
            return bool(d["abstiene"])      # decidido antes de la puerta (reglas, inyección, cifra oficial): no depende del umbral
        return bool(d["sim"] < umbral)

    def tablas(abstiene: list[bool]) -> dict[str, Any]:
        sel = lambda f: [(d, a) for d, a in zip(datos, abstiene, strict=True) if f(d["c"])]  # noqa: E731
        sin, sust = sel(lambda c: c["tipo"] == "sin_respuesta"), sel(lambda c: c["tipo"] == "respuesta_sustentada")
        return {
            "abstencion_correcta_sin_respuesta": {**metricas.proporcion_con_ic(sum(a for _, a in sin), len(sin), criterio),
                                                   "fallos": [d["c"]["id"] for d, a in sin if not a]},
            "abstenciones_incorrectas_sustentadas": {**metricas.proporcion_con_ic(sum(a for _, a in sust), len(sust), criterio),
                                                      "ids": [d["c"]["id"] for d, a in sust if a]},
        }

    loo = []
    umbrales_loo = {}
    for d in datos:
        if d["llega"]:
            resto = list(pool)
            if d["calibra"]:
                resto.remove(d["sim"])
            u = truncar(float(np.percentile(resto, pct))) if resto else umbral_cfg
            umbrales_loo[d["c"]["id"]] = u
            loo.append(con_umbral(d, u))
        else:
            loo.append(bool(d["abstiene"]))
    configurado = [con_umbral(d, umbral_cfg) for d in datos]
    paso = cargar_benchmark().analisis_umbral
    rejilla = np.arange(paso.desde, paso.hasta + paso.paso / 2, paso.paso)
    sensibilidad = []
    for u in rejilla:
        t = tablas([con_umbral(d, float(u)) for d in datos])
        sensibilidad.append({
            "umbral": round(float(u), 3),
            "sin_respuesta_rechazadas": {k: t["abstencion_correcta_sin_respuesta"][k] for k in ("n", "de", "fallos")},
            "sustentadas_rechazadas": {k: t["abstenciones_incorrectas_sustentadas"][k] for k in ("n", "de", "ids")},
        })
    valores = list(umbrales_loo.values())
    return {
        "metodo": "validacion_cruzada_dejando_uno_afuera", "umbral_configurado": umbral_cfg, "percentil": pct,
        "n_en_la_puerta": sum(d["llega"] for d in datos), "n_calibran": len(pool),
        "umbral_loo": {"minimo": min(valores), "maximo": max(valores)} if valores else None,
        "validacion_cruzada": tablas(loo), "con_el_umbral_configurado": tablas(configurado), "sensibilidad": sensibilidad,
        "nota": ("La validación cruzada recalcula solo el umbral; las reglas por patrón se escribieron viendo estas consultas, así que la cifra "
                 "sigue siendo optimista en lo que dependen de ellas. La sensibilidad es una curva descriptiva: no es una calibración y "
                 "no se usa para elegir el umbral sobre las mismas consultas."),
    }


# ============================================================================================ borradores


def _afirmaciones_borrador(g: Any, paquete: Any, id_grupo: str, criterio: CriterioAB) -> list[dict[str, Any]]:
    """Las afirmaciones del paquete con su evidencia y dos comprobaciones: cita válida y validador completo."""
    from src.validador import validar_afirmaciones

    crudas = [Afirmacion.model_validate({"id": a.id, "tipo": a.tipo, "texto": a.texto, "citas": [{"id": c.id, "campo": c.campo} for c in a.citas], "base": a.base})
              for a in paquete.afirmaciones]
    pasan = {a.id for a in validar_afirmaciones(crudas, g.ctx).validas}
    filas = []
    textos = {a.id: a.texto for a in paquete.afirmaciones}
    for a in paquete.afirmaciones:
        evidencia = []
        for c in a.citas:
            r = g.ctx.registros.get(c.id)
            valor = r.campos.get(c.campo) if r else None
            ctx_txt = "; ".join(f"{k}: {v}" for k, v in (r.contexto if r else {}).items())
            evidencia.append(f"{c.id} · {c.campo}: «{valor}»" + (f" ({ctx_txt})" if ctx_txt else "") if valor is not None else f"{c.id} · {c.campo}: (no existe)")
        if not a.citas and a.base:   # inferencia o hipótesis: la «evidencia» son las afirmaciones en que se apoya
            evidencia = [f"{b}: «{textos.get(b, '(no existe)')}»" for b in a.base]
        existe = bool(a.citas) and all(c.id in g.ctx.registros and c.campo in g.ctx.registros[c.id].campos for c in a.citas)
        filas.append({
            "origen": "borrador", "id_unidad": id_grupo, "id_afirmacion": a.id, "tipo": a.tipo, "texto": a.texto,
            "citas": "; ".join(f"{c.id} · {c.campo}" for c in a.citas) or f"(base: {', '.join(a.base)})",
            "evidencia_citada": " | ".join(evidencia), "factual": a.tipo in ("hecho", "declaración"),
            "base": list(a.base), "cita_valida": existe, "pasa_validador": a.id in pasan,
        })
    return filas


def correr_borradores(
    grupos: Sequence[str], modalidad: str, base: Path, modo: str, criterio: CriterioAB, ruta_rechazos: Path
) -> dict[str, Any]:
    """Genera (``cache``: solo desde ``data/cache_llm/``; ``real``: llama a DeepSeek con una caché vacía temporal) el paquete de cada grupo.

    Devuelve por grupo el estado, las afirmaciones con sus comprobaciones y, por cada llamada, tokens y latencia. Los rechazos del
    validador quedan en ``ruta_rechazos`` (se reinicia en cada corrida)."""
    from src import cache as cache_mod
    from src.configuracion import cargar_generacion
    from src.generacion import Generador, _entrada_desde_grupo
    from src.llm.costo import TopeDeCostoAlcanzado
    from src.llm.proveedor import ErrorProveedor, crear_proveedor
    from src.validador import ENV_REGISTRO

    ruta_rechazos.parent.mkdir(parents=True, exist_ok=True)
    ruta_rechazos.write_text("", encoding="utf-8")
    previo = os.environ.get(ENV_REGISTRO)
    os.environ[ENV_REGISTRO] = str(ruta_rechazos)
    temporal = tempfile.TemporaryDirectory(prefix="benchmark_llm_")
    try:
        if modo == "real":
            proveedor: Any = cache_mod.ProveedorConCache(crear_proveedor(), cache_mod.CacheLlm(Path(temporal.name)), refrescar=False)
        else:
            proveedor = cache_mod.ProveedorSoloCache(cache_mod.CacheLlm(), cache_mod.identidad_de())
        resultados = []
        for id_grupo in grupos:
            entrada = _entrada_desde_grupo(id_grupo, modalidad, base)
            g = Generador(entrada, proveedor)
            fila: dict[str, Any] = {"id_grupo": id_grupo, "accion": entrada.accion, "estado": "", "afirmaciones": [], "llamadas": []}
            if g.plan.tipo == "nada":
                resultados.append({**fila, "estado": "no_genera", "motivo": g.plan.motivo})
                continue
            inicio = time.perf_counter()
            try:
                g.generar_afirmaciones()
                t_afirmaciones = time.perf_counter() - inicio
                for grupo in g.grupos:
                    g.generar_grupo(grupo)
            except cache_mod.SinCache:
                resultados.append({**fila, "estado": "sin_cache"})
                continue
            except TopeDeCostoAlcanzado as exc:
                resultados.append({**fila, "estado": "tope_de_costo", "motivo": str(exc)})
                break
            except ErrorProveedor as exc:
                resultados.append({**fila, "estado": "error_proveedor", "motivo": type(exc).__name__})
                continue
            total = time.perf_counter() - inicio
            paquete = g.paquete()
            vacias = [v.referencia for v in paquete.vacios if v.origen == "seccion"] if paquete else []
            resultados.append({
                **fila, "estado": "con_vacios" if vacias else "completo", "secciones_vacias": vacias, "tipo_paquete": g.plan.tipo,
                "latencia_primera_respuesta_s": round(t_afirmaciones, 3), "latencia_paquete_s": round(total, 3),
                "llamadas": [{"paso": c.paso, "intento": c.intento, "tokens_entrada": c.tokens_entrada, "tokens_salida": c.tokens_salida,
                              "latencia_s": round(c.latencia_s, 3)} for c in g.llamadas],
                "afirmaciones": _afirmaciones_borrador(g, paquete, id_grupo, criterio) if paquete else [],
            })
        return {"modo": modo, "proveedor": getattr(proveedor, "nombre", ""), "modelo": getattr(proveedor, "modelo", ""),
                "grupos": resultados, "precios": cargar_generacion().deepseek.precio_usd_por_millon_tokens.model_dump()}
    finally:
        if previo is None:
            os.environ.pop(ENV_REGISTRO, None)
        else:
            os.environ[ENV_REGISTRO] = previo
        temporal.cleanup()


def resumen_cobertura_borradores(grupos: Sequence[Mapping[str, Any]], criterio: CriterioAB) -> dict[str, Any]:
    filas = [(f"{g['id_grupo']}/{a['id_afirmacion']}", a) for g in grupos for a in g["afirmaciones"]]
    factuales = [(i, a) for i, a in filas if a["factual"]]
    derivadas = [(i, a) for i, a in filas if not a["factual"]]
    valida_por_id = {i: a["cita_valida"] for i, a in filas}

    def base_valida(a: Mapping[str, Any], grupo: str) -> bool:
        return all(valida_por_id.get(f"{grupo}/{b}", False) for b in a["base"]) and bool(a["base"])

    def prop(sel: list[tuple[str, Mapping[str, Any]]], clave: str) -> dict[str, Any]:
        ok = [bool(a[clave]) for _, a in sel]
        return _prop_con_ids(ok, [i for i, _ in sel], criterio)

    derivadas_ok = [(i, {**a, "base_ok": base_valida(a, i.split("/")[0])}) for i, a in derivadas]
    return {
        "factuales_con_cita_valida": prop(factuales, "cita_valida"),
        "factuales_que_pasan_el_validador": prop(factuales, "pasa_validador"),
        "derivadas_con_base_valida": prop(derivadas_ok, "base_ok"),
        "nota": "Factuales = hecho y declaración (citan registros). Derivadas = inferencia e hipótesis (citan afirmaciones base).",
    }


def resumen_medicion_llm(corrida: Mapping[str, Any], criterio: CriterioAB, ruta_rechazos: Path) -> dict[str, Any]:
    """Latencia, tokens y costo del paquete completo a partir de una corrida real (``modo = real``)."""
    from src.validador import calcular_tasas

    ok = [g for g in corrida["grupos"] if g["estado"] in ("completo", "con_vacios")]
    precios = corrida["precios"]
    llamadas = [c for g in ok for c in g["llamadas"]]

    def usd(entrada: float, salida: float) -> float:
        return (entrada * precios["entrada"] + salida * precios["salida"]) / 1_000_000

    por_paquete = [
        {"id_grupo": g["id_grupo"], "tokens_entrada": sum(c["tokens_entrada"] for c in g["llamadas"]),
         "tokens_salida": sum(c["tokens_salida"] for c in g["llamadas"]), "llamadas": len(g["llamadas"])}
        for g in ok
    ]
    usd_paquetes = [usd(p["tokens_entrada"], p["tokens_salida"]) for p in por_paquete]
    return {
        "fecha_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "proveedor": corrida["proveedor"], "modelo": corrida["modelo"],
        "grupos": [{k: g[k] for k in ("id_grupo", "estado", "accion", "tipo_paquete") if k in g} | {"secciones_vacias": g.get("secciones_vacias", []),
                   "latencia_primera_respuesta_s": g.get("latencia_primera_respuesta_s"), "latencia_paquete_s": g.get("latencia_paquete_s")}
                   for g in corrida["grupos"]],
        "n_grupos": len(corrida["grupos"]), "n_paquetes_medidos": len(ok),
        "latencia": {
            "primera_respuesta": {"n": len(ok), "unidad": "s", "p50": metricas.percentil_con_ic([g["latencia_primera_respuesta_s"] for g in ok], 50, criterio),
                                  "p95": metricas.percentil_con_ic([g["latencia_primera_respuesta_s"] for g in ok], 95, criterio)},
            "paquete_completo": {"n": len(ok), "unidad": "s", "p50": metricas.percentil_con_ic([g["latencia_paquete_s"] for g in ok], 50, criterio),
                                 "p95": metricas.percentil_con_ic([g["latencia_paquete_s"] for g in ok], 95, criterio)},
            "por_tipo_de_paquete": {
                tipo: {"n": len(sel), "unidad": "s", "p50": metricas.percentil_con_ic([g["latencia_paquete_s"] for g in sel], 50, criterio),
                       "p95": metricas.percentil_con_ic([g["latencia_paquete_s"] for g in sel], 95, criterio)}
                for tipo in sorted({g["tipo_paquete"] for g in ok}) for sel in [[g for g in ok if g["tipo_paquete"] == tipo]]
            },
            "por_llamada": {"n": len(llamadas), "unidad": "s", "p50": metricas.percentil_con_ic([c["latencia_s"] for c in llamadas], 50, criterio),
                            "p95": metricas.percentil_con_ic([c["latencia_s"] for c in llamadas], 95, criterio)},
        },
        "tokens_por_paquete": {"entrada": metricas.percentil_con_ic([p["tokens_entrada"] for p in por_paquete], 50, criterio),
                               "salida": metricas.percentil_con_ic([p["tokens_salida"] for p in por_paquete], 50, criterio),
                               "llamadas_por_paquete": metricas.percentil_con_ic([p["llamadas"] for p in por_paquete], 50, criterio), "estadistico": "mediana"},
        "tokens_totales": {"entrada": sum(p["tokens_entrada"] for p in por_paquete), "salida": sum(p["tokens_salida"] for p in por_paquete)},
        "costo_usd": {
            "por_paquete_mediana": metricas.percentil_con_ic(usd_paquetes, 50, criterio),
            "total_estimado": round(sum(usd_paquetes), 6), "precios_usd_por_millon_tokens": precios,
            "nota": "Cota superior (D-97): tokens de la API × el precio pico, sin descuento por caché. La consola de DeepSeek marcó ≈ 2,6 veces menos en una comparación (docs/parametros.md).",
        },
        "rechazos_del_validador": calcular_tasas(ruta_rechazos),
        "paquetes": por_paquete,
    }


# ============================================================================================ ensamblado y salida


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _pool_sustento(registros_pares: Sequence[tuple[dict[str, Any], RespuestaConsulta]], consultor: Consultor, borradores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    pool = []
    corpus = consultor.indice.corpus
    for reg, r in registros_pares:
        for a in r.afirmaciones:
            ev = " | ".join(f"{c.id} · {c.campo}: " + (_texto_evidencia(corpus.por_id[c.id], c.campo) if c.id in corpus.por_id else "(no existe)") for c in a.citas)
            pool.append({"origen": "consulta", "id_unidad": reg["id"], "id_afirmacion": a.id, "tipo": a.tipo, "texto": a.texto,
                         "citas": _citas_texto(a), "evidencia_citada": ev})
    for g in borradores:
        for a in g["afirmaciones"]:
            pool.append({k: a[k] for k in ("origen", "id_unidad", "id_afirmacion", "tipo", "texto", "citas", "evidencia_citada")})
    return pool


def ids_esperados_inexistentes(consultor: Consultor, consultas: Sequence[dict[str, Any]]) -> dict[str, list[str]]:
    """Por consulta, los IDs de ``ids_evidencia`` que no están en el corpus: un typo o un corpus distinto bajaría el recall sin explicación."""
    corpus = consultor.indice.corpus.por_id
    faltan = {c["id"]: [i for i in c["ids_evidencia"] if i not in corpus] for c in consultas}
    return {c: ids for c, ids in faltan.items() if ids}


def _ejecutar(args: argparse.Namespace) -> int:
    cfg = cargar_benchmark()
    criterio = cfg.intervalos
    dev = args.split == "dev"
    archivo = BENCHMARK_DEV if dev else Path(args.archivo)
    salida = SALIDA_DEV if dev else Path(args.salida)
    ruta_metricas = Path(args.metricas) if args.metricas else (METRICAS_DEV if dev else salida / "metricas.json")
    ruta_revision = Path(args.revision) if args.revision else (REVISION_DEV if dev else salida / "revision_sustento.csv")
    if not archivo.is_file():
        print(f"ERROR: no existe el archivo del benchmark: {archivo.name}", file=sys.stderr)
        return 1
    try:
        consultas = leer_consultas(archivo)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        arranque = time.perf_counter()
        consultor = crear_consultor_real()
        emb = consultor.indice.emb
        emb.motor.codificar([f"{emb.prefijo('titular')}calentamiento"])   # fuerza la carga del modelo si el índice vino de la caché
        _ARRANQUE_S[0] = round(time.perf_counter() - arranque, 3)         # arranque en frío del proceso: armar el consultor y cargar el modelo
    except Exception as exc:  # noqa: BLE001 - falta la base o el modelo local: se dice qué hacer y no se muestra una traza
        print(f"ERROR: no se pudo preparar la consulta ({type(exc).__name__}: {str(exc)[:200]}). Haga falta la base data/senales.duckdb y el modelo de "
              "embeddings local en models/ (se descarga una sola vez con red: HF_HUB_OFFLINE=0 poetry run python -m src.consulta \"prueba\").", file=sys.stderr)
        return 1
    salida.mkdir(parents=True, exist_ok=True)
    registros, m = evaluar_consultas(consultor, consultas, criterio)
    pares = [(r, consultor.responder(r["consulta"])) for r in registros]   # las respuestas (objetos) para la muestra de sustento
    with (salida / "consultas.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in registros)

    modo_borradores = args.borradores or ("cache" if dev else "no")
    borradores: list[dict[str, Any]] = []
    medicion: dict[str, Any] | None = None
    avisos_corrida: list[str] = []
    base = RAIZ / "data" / "senales.duckdb"
    if modo_borradores != "no" or args.medir_llm:
        from scripts.calentar_cache import grupos_por_defecto

        grupos = args.grupos or grupos_por_defecto(base, cfg.llm.modalidad)
        if modo_borradores != "no":
            corrida = correr_borradores(grupos, cfg.llm.modalidad, base, "cache", criterio, salida / "rechazos.jsonl")
            borradores = corrida["grupos"]
            with (salida / "borradores.jsonl").open("w", encoding="utf-8") as f:
                f.writelines(json.dumps(g, ensure_ascii=False) + "\n" for g in borradores)
        if args.medir_llm:
            real = correr_borradores(grupos, cfg.llm.modalidad, base, "real", criterio, salida / "rechazos_medicion_llm.jsonl")
            medicion = resumen_medicion_llm(real, criterio, salida / "rechazos_medicion_llm.jsonl")
            (salida / "medicion_llm.json").write_text(json.dumps(medicion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if medicion is None and (salida / "medicion_llm.json").exists():
        medicion = json.loads((salida / "medicion_llm.json").read_text(encoding="utf-8"))

    if borradores:
        estados = Counter(g["estado"] for g in borradores)
        m["cobertura_de_citas"]["borradores"] = resumen_cobertura_borradores(borradores, criterio)
        m["borradores"] = {"modo": "cache", "grupos": len(borradores), "estados": dict(estados),
                           "fallos": [g["id_grupo"] for g in borradores if g["estado"] not in ("completo", "con_vacios")]}
        from src.validador import calcular_tasas

        m["rechazos_previos"] = {"fuente": "re-validación de las respuestas guardadas en data/cache_llm/ con el validador actual",
                                 "tasas": calcular_tasas(salida / "rechazos.jsonl")}
    meta_s = cfg.metas.latencia_mediana_s
    if medicion:
        m["latencia"]["paquete_completo"] = medicion["latencia"]["paquete_completo"]
        m["latencia"]["primera_respuesta_borrador"] = medicion["latencia"]["primera_respuesta"]
        m["latencia"]["llamada_llm"] = medicion["latencia"]["por_llamada"]
        m["latencia"]["paquete_por_tipo"] = medicion["latencia"]["por_tipo_de_paquete"]
        m["latencia"]["meta_sugerida"] = {
            "mediana_s": meta_s, "consulta_cumple": m["latencia"]["consulta"]["p50"]["valor"] <= meta_s,
            "paquete_cumple_por_tipo": {t: v["p50"]["valor"] is not None and v["p50"]["valor"] <= meta_s for t, v in medicion["latencia"]["por_tipo_de_paquete"].items()},
            "nota": "El paquete editorial es más largo (más secciones, más llamadas) que el de investigación: se reporta por tipo y con su n.",
        }
        m["tokens_y_costo"]["borradores"] = {
            "estado": "medido", "fecha_utc": medicion["fecha_utc"], "proveedor": medicion["proveedor"], "modelo": medicion["modelo"],
            "n_paquetes": medicion["n_paquetes_medidos"], "tokens_por_paquete": medicion["tokens_por_paquete"],
            "costo_usd": medicion["costo_usd"], "tokens_totales": medicion["tokens_totales"], "fuente": "medicion_llm.json (corrida real con --medir-llm)",
        }
    else:
        m["latencia"]["paquete_completo"] = {"estado": "no_corrido", "nota": "Ejecute con --medir-llm (requiere red y DeepSeek) para medir el borrador completo."}
        m["tokens_y_costo"]["borradores"] = {"estado": "no_corrido"}
        avisos_corrida.append(f"No existe {salida.name}/medicion_llm.json: la latencia, los tokens y el costo del borrador quedan «no_corrido». "
                              "Ejecute con --medir-llm (requiere red y DeepSeek) para medirlos.")

    inexistentes = ids_esperados_inexistentes(consultor, consultas)
    if inexistentes:
        m["ids_esperados_inexistentes"] = inexistentes
        avisos_corrida.append("Hay IDs esperados que no existen en el corpus (se cuentan como no hallados): "
                              + "; ".join(f"{c}: {', '.join(i)}" for c, i in inexistentes.items()))
    for aviso in avisos_corrida:
        print(f"ADVERTENCIA: {aviso}", file=sys.stderr)

    pool = _pool_sustento(pares, consultor, borradores)
    muestra = sustento.muestrear(pool, cfg.sustento.muestra, cfg.sustento.semilla)
    estado_muestra = sustento.preparar_muestra(muestra, ruta_revision)
    revision = sustento.validez(sustento.leer_revision(ruta_revision), criterio, cfg)
    m["validez_sustento"] = {**revision, "archivo": ruta_revision.name, "muestra": {"n": len(muestra), "pool": len(pool), "semilla": cfg.sustento.semilla,
                                                                                    "estado_del_archivo": estado_muestra,
                                                                                    "origenes": dict(Counter(x["origen"] for x in muestra))}}
    if estado_muestra == "conservada_con_veredictos" and {(x["origen"], x["id_unidad"], x["id_afirmacion"]) for x in muestra} != {
        (f["origen"], f["id_unidad"], f["id_afirmacion"]) for f in sustento.leer_revision(ruta_revision)
    }:
        m["validez_sustento"]["aviso"] = "La muestra revisada ya no coincide con la que daría esta corrida (cambió el conjunto de salidas); se conserva la revisada."
    if args.analisis_umbral or (dev and args.analisis_umbral is None):
        m["analisis_umbral"] = analisis_umbral(consultor, consultas, criterio)

    cabecera = {
        "version": VERSION_METRICAS, "fecha_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "benchmark": {"archivo": archivo.name, "sha256": _sha256(archivo), "n": len(consultas), "por_tipo": m.pop("por_tipo"), "split": "dev" if dev else "archivo"},
        "entorno": {"python": platform.python_version(), "sistema": platform.system(), "embeddings": consultor.indice.emb.__class__.__name__,
                    "metodo": "semantica", "umbral_similitud": consultor.cfg.abstencion.umbral_similitud["semantica"],
                    "consulta_sin_llm": True, "internet_necesario": False if modo_borradores != "real" and not args.medir_llm else True},
        "intervalos": {"remuestreos": criterio.remuestreos, "confianza": criterio.confianza, "semilla": criterio.semilla, "metodo": "bootstrap percentil (y Wilson aparte)"},
    }
    avisos = [
        "El benchmark de desarrollo se construyó con el equipo y las reglas por patrón de la consulta se redactaron viendo esas mismas consultas: las cifras de abstención son optimistas, no independientes.",
        "n es pequeño (decenas de consultas): los intervalos son anchos y las metas son orientativas.",
    ] if dev else ["Evaluación sobre un archivo externo: las cifras no incluyen ajuste previo con estas consultas."]
    resultado = {**cabecera, **m, "avisos": [*avisos, *avisos_corrida]}
    ruta_metricas.parent.mkdir(parents=True, exist_ok=True)
    ruta_metricas.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if salida != ruta_metricas.parent:
        (salida / "metricas.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    imprimir(resultado)
    print(f"\nEscrito: {ruta_metricas} · {salida}/ · revisión de sustento: {ruta_revision} ({estado_muestra})")
    return 0


def _f(p: Mapping[str, Any]) -> str:
    if p.get("proporcion") is None:
        return f"{p.get('n')}/{p.get('de')}"
    return f"{p['n']}/{p['de']} = {p['proporcion']} IC95 boot {p['ic95']} · Wilson {p.get('ic95_wilson')}"


def imprimir(r: Mapping[str, Any]) -> None:
    b = r["benchmark"]
    print(f"== Benchmark {b['archivo']} (n = {b['n']}, {b['por_tipo']}) ==")
    a = r["abstencion_correcta"]
    print(f"Abstención correcta, sin_respuesta : {_f(a['sin_respuesta'])} fallos {a['sin_respuesta']['fallos']}")
    print(f"Abstención correcta, todas         : {_f(a['todas_las_que_debian'])} fallos {a['todas_las_que_debian']['fallos']}")
    i = r["abstenciones_incorrectas"]
    print(f"Abstenciones incorrectas, sustent. : {_f(i['sustentadas'])} {i['sustentadas']['ids']}")
    print(f"Abstenciones incorrectas, respond. : {_f(i['respondibles'])} {i['respondibles']['ids']}")
    c = r["cobertura_de_citas"]
    print(f"Cobertura de citas, consultas      : {_f(c['consultas'])} fallos {c['consultas']['fallos']}")
    if "borradores" in c:
        print(f"Cobertura de citas, borradores     : {_f(c['borradores']['factuales_con_cita_valida'])} fallos {c['borradores']['factuales_con_cita_valida']['fallos']}")
    for nombre, fila in r["busqueda"]["metodos"].items():
        print(f"Recall@{r['busqueda']['k']} {nombre:9}: {_f({**fila['por_ids'], 'ic95_wilson': None})} fallos {sorted(fila['fallos'])}")
    lat = r["latencia"]["consulta"]
    print(f"Latencia consulta                  : p50 {lat['p50']['valor']} s IC {lat['p50']['ic95']} · p95 {lat['p95']['valor']} s IC {lat['p95']['ic95']} (n = {lat['n']})")
    pc = r["latencia"]["paquete_completo"]
    if "p50" in pc:
        print(f"Latencia borrador completo         : p50 {pc['p50']['valor']} s IC {pc['p50']['ic95']} · p95 {pc['p95']['valor']} s (n = {pc['n']})")
    for tipo, fila in r["latencia"].get("paquete_por_tipo", {}).items():
        p50, p95 = fila["p50"], fila["p95"]
        marca = " · IC degenerado con n = 1" if fila["n"] == 1 else ""
        print(f"  paquete {tipo:13}: p50 {p50['valor']} s IC {p50['ic95']} · p95 {p95['valor']} s (n = {fila['n']}){marca}")
    v = r["validez_sustento"]
    print(f"Validez de sustento                : {v['estado']} ({v['revisadas']}/{v['de']} revisadas)")


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")        # el modelo de embeddings es local: nunca hay descarga (evaluación sin internet)
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    parser = argparse.ArgumentParser(description="E1-18: benchmark y métricas de la sección 9.1 (offline)")
    origen = parser.add_mutually_exclusive_group(required=True)
    origen.add_argument("--split", choices=["dev"], help="el benchmark de desarrollo (benchmark/benchmark_dev.jsonl) → outputs/benchmark/")
    origen.add_argument("--archivo", type=Path, help="otro archivo con el mismo formato (la evaluación reservada del jurado); exige --salida")
    parser.add_argument("--salida", type=Path, help="carpeta donde se escribe todo (obligatoria con --archivo)")
    parser.add_argument("--metricas", type=Path, help="dónde escribir metricas.json (por defecto outputs/metricas.json con --split dev; <salida>/metricas.json con --archivo)")
    parser.add_argument("--revision", type=Path, help="dónde escribir la muestra de sustento (por defecto outputs/revision_sustento.csv con --split dev)")
    parser.add_argument("--borradores", choices=["no", "cache"], help="con «cache» arma los borradores desde data/cache_llm/ (por defecto con --split dev)")
    parser.add_argument("--medir-llm", action="store_true", help="llama de verdad a DeepSeek (caché temporal vacía) para medir latencia, tokens y costo del borrador")
    parser.add_argument("--grupos", nargs="*", help="GRP-… a usar en los borradores (por defecto el top de la bandeja y los del guion de la demo)")
    parser.add_argument("--analisis-umbral", action=argparse.BooleanOptionalAction, default=None, help="validación cruzada y curva del umbral (por defecto con --split dev)")
    args = parser.parse_args(argv)
    if args.archivo and not args.salida:
        parser.error("--archivo exige --salida <carpeta>")
    return _ejecutar(args)


if __name__ == "__main__":
    sys.exit(main())
