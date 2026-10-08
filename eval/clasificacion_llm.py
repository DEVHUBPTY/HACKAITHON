"""C-10c: clasificación de temas con un LLM, medida UNA sola vez sobre las mismas etiquetas humanas (sin conectarla a producción).

Qué mide: las mismas 64 filas que ``eval/clasificacion.py`` y ``eval/clasificacion_por_evento.py`` (``origen = humano``, no ruido, sin los
ejemplos de ``temas.yaml``; ≈ 30 eventos). Al proveedor solo llega el texto del titular (``src/clasificacion_llm.py``); las 61 etiquetas
provisionales (D-101) ni se leen. Por fila: exactitud (Wilson) y macro-F1 (bootstrap por fila). Por evento: exactitud y macro-F1 con IC
bootstrap sobre eventos (los de ``criterio_ab``). Además recall por tema, abstenciones (``sin_tema``), confusión por tema (solo conteos), la
diferencia **pareada por evento** contra el método A activo y contra el mejor baseline por palabras clave, y el criterio D-57.

**Fuga declarada.** La regla regional D-84 de la guía (que está en el prompt) salió en parte de analizar estas mismas etiquetas. Además,
una sola persona etiquetó y son ≈ 30 eventos: el resultado es exploratorio.

Uso: ``HF_HUB_OFFLINE=1 poetry run python -m eval.clasificacion_llm`` (con red, una vez; escribe ``outputs/clasificacion_llm.json``) y
``HF_HUB_OFFLINE=1 poetry run python -m eval.clasificacion_llm --verificar`` (reproduce las métricas desde la caché, sin red, y las compara
con el JSON; no escribe nada). No imprime ni guarda ningún titular etiquetado.
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
from eval import clasificacion_por_evento as pe
from eval import clasificacion_supervisada as sup
from eval import diagnostico_temas as dg
from eval import metricas
from src import db
from src.cache import CacheLlm, SinCache
from src.clasificacion import proporcion
from src.clasificacion_llm import (
    Clasificacion,
    ClasificadorLlm,
    PromptClasificacion,
    cargar_prompt_clasificacion,
    crear_proveedor_clasificacion,
    titulares_en_prompt,
)
from src.configuracion import (
    RAIZ,
    ConfigClasificacion,
    ConfigClasificacionLlm,
    ConfigTemas,
    PreciosDeepSeek,
    cargar_carga,
    cargar_clasificacion,
    cargar_clasificacion_llm,
    cargar_generacion,
    cargar_normalizacion,
    cargar_temas,
)
from src.llm.costo import UN_MILLON, TopeDeCostoAlcanzado
from src.llm.proveedor import ErrorProveedor
from src.registro import configurar_logging, redactar

CODIGO_BLOQUEADO = 3
CODIGO_DIFERENCIAS = 1
SECCIONES_COMPARABLES = ("conjunto", "tokens", "metricas")   # lo que `--verificar` exige idéntico (la corrida real y la réplica difieren en las llamadas)
SIN_CONFIANZA = "sin_confianza"
ADVERTENCIA = (
    "EXPLORATORIO: ≈ 30 eventos y una sola persona etiquetó (D-85); las etiquetas son un censo del estrato «no ruido» del snapshot anterior, "
    "no datos de prueba independientes. Medición única de un LLM con un prompt congelado antes de medir."
)
FUGA_DECLARADA = (
    "La regla de alcance regional D-84 de docs/guia_temas.md, que está en el prompt, salió en parte de analizar estas mismas etiquetas: "
    "el LLM recibe ese criterio ya informado por ellas, así que su medición no es de datos nunca vistos por quien escribió la regla. "
    "El prompt no contiene ningún titular etiquetado (comprobado antes de llamar)."
)
NOTA_COSTO = (
    "El contador del repositorio multiplica los tokens por la tarifa pico sin descuento por caché y sobreestima ≈ 2,6 veces frente a la "
    "consola de DeepSeek (D-97): el costo real es menor que el estimado."
)


# ------------------------------------------------------------------ filas: las mismas 64 que la evaluación existente


@dataclass(frozen=True)
class FilasLlm:
    """Filas evaluables (etiqueta humana, no ruido, no ejemplo) con su titular, su tema humano y su evento."""

    ids: list[str]
    titulares: list[str]
    y: np.ndarray
    eventos: list[str]
    etiquetados_en_csv: int
    excluidos_descartados: int


def cargar_filas(ruta_etiquetas: Path, ruta_base: Path, temas: ConfigTemas) -> FilasLlm:
    """Misma selección que ``eval.clasificacion_por_evento.cargar_conjunto`` pero sin embeddings, y con el **titular** (``titulo_limpio``).

    Solo etiquetas ``humano``; las provisionales no se leen. La descripción del RSS no se toca (D-31): al proveedor solo llega el titular.
    """
    etiquetas, grupos = pe.leer_etiquetas_y_grupos(ruta_etiquetas, temas)
    excluidos = evalclas.ids_excluidos()
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = con.execute("SELECT id_noticia, titulo_limpio FROM noticias WHERE NOT es_ruido ORDER BY id_noticia").fetchall()
    finally:
        con.close()
    ids, y, eventos = pe.armar_conjunto([(i, t, None) for i, t in filas], etiquetas, grupos, excluidos)
    por_id = dict(filas)
    return FilasLlm(ids, [por_id[i] for i in ids], y, eventos, len(etiquetas), sum(1 for i in etiquetas if i in excluidos))


def clasificar_filas(filas: FilasLlm, clasificador: ClasificadorLlm) -> list[Clasificacion]:
    """Clasifica cada fila pasando **solo su titular** (ningún id, etiqueta, URL ni descripción)."""
    return clasificador.clasificar_todos(filas.titulares)


# ------------------------------------------------------------------ corrida: tokens, costo, caché


def resumen_de_corrida(
    resultados: Sequence[Clasificacion], cfg: ConfigClasificacionLlm, prompt: PromptClasificacion, precios: PreciosDeepSeek
) -> dict[str, Any]:
    """Modelo, versión del prompt, llamadas (reales y de caché), tokens y costo estimado (cota superior: ver ``NOTA_COSTO``).

    Tokens y costo suman **solo las llamadas reales** (``desde_cache`` falso): un acierto de caché repite las cifras guardadas y no gasta nada;
    esas cifras repetidas van aparte en ``tokens_reproducidos_de_cache``.
    """
    reales = [r for r in resultados if not r.desde_cache]
    repetidas = [r for r in resultados if r.desde_cache]
    entrada = sum(r.tokens_entrada for r in reales)
    salida = sum(r.tokens_salida for r in reales)
    de_cache = len(repetidas)
    return {
        "proveedor": cfg.proveedor,
        "modelo": cfg.modelo,
        "version_prompt": cfg.version_prompt,
        "huella_prompt": prompt.huella,
        "temperatura": cfg.temperatura,
        "max_tokens": cfg.max_tokens,
        "llamadas": len(resultados),
        "llamadas_reales": len(resultados) - de_cache,
        "llamadas_de_cache": de_cache,
        "respuestas_mal_formadas": sum(1 for r in resultados if r.malformada),
        "tokens_entrada": entrada,
        "tokens_salida": salida,
        "tokens_reproducidos_de_cache": {"entrada": sum(r.tokens_entrada for r in repetidas), "salida": sum(r.tokens_salida for r in repetidas)},
        "costo_usd_estimado": (entrada * precios.entrada + salida * precios.salida) / UN_MILLON,
        "precios_usd_por_millon_tokens": {"entrada": precios.entrada, "salida": precios.salida},
        "nota_costo": NOTA_COSTO,
    }


def tokens_de_titulares_distintos(titulares: Sequence[str], resultados: Sequence[Clasificacion], precios: PreciosDeepSeek) -> dict[str, Any]:
    """Tokens y costo de **una llamada por titular distinto** (la primera vez que aparece).

    En la corrida real esa primera vez es la llamada real; en la réplica ``--verificar`` es la entrada guardada de la caché. Por eso la cifra
    es la misma en ambas y puede compararse; los titulares repetidos no suman (se sirven de la caché).
    """
    vistos: set[str] = set()
    entrada = salida = 0
    for titular, r in zip(titulares, resultados, strict=True):
        if titular not in vistos:
            vistos.add(titular)
            entrada, salida = entrada + r.tokens_entrada, salida + r.tokens_salida
    return {"entrada": entrada, "salida": salida, "costo_usd_estimado": (entrada * precios.entrada + salida * precios.salida) / UN_MILLON}


# ------------------------------------------------------------------ métricas


def _por_confianza(y: np.ndarray, preds: np.ndarray, resultados: Sequence[Clasificacion], z: float) -> dict[str, Any]:
    """Filas y aciertos (con n e IC de Wilson) por nivel de confianza que declaró el LLM; las mal formadas no declaran ninguna."""
    niveles = [r.confianza or SIN_CONFIANZA for r in resultados]
    salida: dict[str, Any] = {}
    for nivel in dict.fromkeys(niveles):
        filas = [k for k, n in enumerate(niveles) if n == nivel]
        salida[nivel] = {"filas": len(filas), "aciertos": proporcion(int((preds[filas] == y[filas]).sum()), len(filas), z)}
    return salida


def metricas_de_llm(
    y: np.ndarray,
    preds: np.ndarray,
    resultados: Sequence[Clasificacion],
    eventos: Sequence[str],
    clases: Sequence[str],
    comparadores: dict[str, np.ndarray],
    cfg: ConfigClasificacion,
    z: float,
) -> dict[str, Any]:
    """Métricas del LLM por fila y por evento y su diferencia pareada por evento con cada comparador (método A, mejor baseline).

    Reutiliza ``eval.clasificacion_por_evento`` (``evaluar_sistema``, bootstrap por evento) y ``eval.clasificacion_supervisada``
    (``criterio_d57`` y la diferencia de recall por tema). ``preds`` y los comparadores son vectores de ``n`` predicciones.
    """
    criterio, min_ic = cfg.criterio_ab, cfg.por_evento.min_eventos_ic
    sistema = pe.evaluar_sistema(y, preds[None, :], eventos, clases, criterio, z, min_ic)
    sistemas = {n: pe.evaluar_sistema(y, p[None, :], eventos, clases, criterio, z, min_ic) for n, p in comparadores.items()}
    comparaciones: dict[str, Any] = {}
    for nombre, otro in comparadores.items():
        d_exact = dg.diferencia_por_evento(otro == y, preds == y, list(eventos), criterio)
        d_f1 = pe.diferencia_macro_f1_por_evento(y, otro[None, :], preds[None, :], eventos, clases, criterio)
        por_tema = sup._diferencias_por_tema(y, otro[None, :], preds[None, :], eventos, clases, criterio, min_ic)
        comparaciones[nombre] = {
            "diferencia": "LLM − " + nombre,
            "exactitud_por_evento": d_exact,
            "macro_f1": d_f1,
            "recall_por_tema": por_tema,
            "criterio_d57": sup.criterio_d57(d_f1, por_tema),
            "ic_se_solapan": {
                "exactitud_por_evento": pe.se_solapan(sistema["exactitud_por_evento"]["ic95"], sistemas[nombre]["exactitud_por_evento"]["ic95"]),
                "macro_f1": pe.se_solapan(sistema["macro_f1_por_evento"]["ic95"], sistemas[nombre]["macro_f1_por_evento"]["ic95"]),
            },
        }
    return {
        **sistema,
        "macro_f1_por_fila": metricas.macro_f1_con_ic(list(y), list(preds), list(clases), criterio),
        "matriz_confusion": {
            "clases": list(clases),
            "filas_real_columnas_predicho": metricas.matriz_confusion(list(y), list(preds), list(clases)),
        },
        "respuestas_mal_formadas": sum(1 for r in resultados if r.malformada),
        "por_confianza": _por_confianza(y, preds, resultados, z),
        "bootstrap": {"remuestreos": criterio.remuestreos, "confianza": criterio.confianza, "semilla": criterio.semilla, "unidad_por_evento": "evento"},
        "sistemas_comparados": sistemas,
        "comparaciones": comparaciones,
    }


# ------------------------------------------------------------------ informe completo y verificación


def construir_informe(
    filas: FilasLlm, resultados: Sequence[Clasificacion], comparadores: dict[str, np.ndarray], mejor_baseline: str,
    cfg: ConfigClasificacionLlm, prompt: PromptClasificacion, clas: ConfigClasificacion, temas: ConfigTemas, z: float, precios: PreciosDeepSeek,
) -> dict[str, Any]:
    """Todo el informe (sin escribirlo). ``tokens`` (una llamada por titular distinto) y ``conjunto`` salen de los datos y de la caché, así que la réplica los reproduce."""
    preds = np.array([r.tema for r in resultados], dtype=object)
    corrida = resumen_de_corrida(resultados, cfg, prompt, precios)
    return {
        "tarea": "C-10c",
        "exploratorio": True,
        "conectado_a_produccion": False,
        "advertencia": ADVERTENCIA,
        "fuga_declarada": FUGA_DECLARADA,
        "corrida": corrida,
        "tokens": tokens_de_titulares_distintos(filas.titulares, resultados, precios),
        "conjunto": {
            "origenes": ["humano"],
            "usa_etiquetas_provisionales": False,
            "etiquetados_humanos_en_csv": filas.etiquetados_en_csv,
            "ejemplos_excluidos_descartados": filas.excluidos_descartados,
            "filas": len(filas.ids),
            "eventos": len(set(filas.eventos)),
            "filas_por_tema": dict(Counter(filas.y)),
            "mejor_baseline": mejor_baseline,
            "nota_mejor_baseline": "elegido por exactitud por evento con las mismas etiquetas: favorece al baseline",
        },
        "metricas": metricas_de_llm(filas.y, preds, resultados, filas.eventos, evalclas.clases_de(temas), comparadores, clas, z),
    }


def diferencias_de_metricas(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Diferencias entre dos informes en ``SECCIONES_COMPARABLES`` (vacío = las mismas métricas). Lo demás (llamadas reales) puede variar."""
    salida: list[str] = []

    def recorrer(x: Any, y: Any, ruta: str) -> None:
        if isinstance(x, dict) and isinstance(y, dict):
            for clave in sorted(set(x) | set(y)):
                if clave not in x or clave not in y:
                    salida.append(f"{ruta}.{clave}: falta en {'el primero' if clave not in x else 'el segundo'}")
                else:
                    recorrer(x[clave], y[clave], f"{ruta}.{clave}")
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for k, (u, v) in enumerate(zip(x, y, strict=True)):
                recorrer(u, v, f"{ruta}[{k}]")
        elif x != y:
            salida.append(f"{ruta}: {x} != {y}")

    for seccion in SECCIONES_COMPARABLES:
        if seccion in a or seccion in b:
            recorrer(a.get(seccion), b.get(seccion), seccion)
    return salida


# ------------------------------------------------------------------ impresión (solo cifras)


def _p(d: dict[str, Any]) -> str:
    return f"{d['n']}/{d['de']} = {100 * d['proporcion']:.1f} % [{100 * d['ic95'][0]:.1f}–{100 * d['ic95'][1]:.1f}]"


def imprimir(r: dict[str, Any]) -> list[str]:
    c, k, m = r["conjunto"], r["corrida"], r["metricas"]
    f1_fila, f1_ev = m["macro_f1_por_fila"], m["macro_f1_por_evento"]
    lineas = [
        f"== C-10c · Clasificación con LLM (medición única, NO conectada a producción) · {c['filas']} filas, {c['eventos']} eventos (solo etiquetas humanas) ==",
        r["advertencia"],
        f"Fuga declarada: {r['fuga_declarada']}",
        f"Modelo {k['modelo']} · prompt {k['version_prompt']} (huella {k['huella_prompt'][:12]}…) · temperatura {k['temperatura']} · max_tokens {k['max_tokens']}",
        f"Llamadas {k['llamadas']}: reales {k['llamadas_reales']}, de la caché {k['llamadas_de_cache']}; respuestas mal formadas {k['respuestas_mal_formadas']}",
        f"Tokens de las llamadas reales: entrada {k['tokens_entrada']}, salida {k['tokens_salida']}; costo estimado USD {k['costo_usd_estimado']:.4f} (cota superior: {k['nota_costo']})",
        f"Tokens de una llamada por titular distinto (comparables con la réplica): entrada {r['tokens']['entrada']}, salida {r['tokens']['salida']}; "
        f"repetidos desde la caché (no se cobran): entrada {k['tokens_reproducidos_de_cache']['entrada']}, salida {k['tokens_reproducidos_de_cache']['salida']}",
        f"\nExactitud por fila: {_p(m['exactitud_por_fila'])}",
        f"Exactitud por evento: {pe._ic(m['exactitud_por_evento'])}",
        f"Macro-F1 por fila: {f1_fila['macro_f1']} IC95 {f1_fila['ic95']} (n = {f1_fila['n']}, {f1_fila['remuestreos']} remuestreos)",
        f"Macro-F1 por evento: {f1_ev['valor']} IC95 {f1_ev['ic95']} ({f1_ev['eventos']} eventos)",
        f"Abstenciones (sin_tema): {m['abstenciones']} de {c['filas']} (mal formadas incluidas: {m['respuestas_mal_formadas']}); cobertura {_p(m['cobertura_por_fila'])}",
        f"Exactitud entre cubiertas: {_p(m['exactitud_entre_cubiertas_por_fila'])}",
        "Por confianza declarada: " + "; ".join(f"{n} {v['filas']} filas, aciertos {_p(v['aciertos'])}" for n, v in m["por_confianza"].items()),
        "Recall por tema:",
    ]
    for t, v in m["recall_por_tema"].items():
        ic = "sin IC (un evento)" if v["ic95"] is None else f"IC95 {v['ic95']}"
        lineas.append(f"  {t}: filas {_p(v['filas'])}; por evento {v['recall_por_evento']:.3f} {ic} ({v['eventos']} eventos)")
    cm = m["matriz_confusion"]
    lineas.append("Matriz de confusión (filas = real, columnas = predicho; orden: " + ", ".join(cm["clases"]) + ")")
    lineas += ["  " + " ".join(f"{x:3d}" for x in fila) for fila in cm["filas_real_columnas_predicho"]]
    for n, s in m["sistemas_comparados"].items():
        lineas.append(f"[{n}] exactitud filas {_p(s['exactitud_por_fila'])}; eventos {pe._ic(s['exactitud_por_evento'])}; macro-F1 por evento {s['macro_f1_por_evento']['valor']} IC95 {s['macro_f1_por_evento']['ic95']}")
    lineas.append("Diferencias pareadas por evento (LLM − comparador; IC 95 % bootstrap sobre eventos):")
    for n, d in m["comparaciones"].items():
        e, f, d57 = d["exactitud_por_evento"], d["macro_f1"], d["criterio_d57"]
        lineas.append(
            f"- {n}: Δ exactitud {e['diferencia']:+} IC95 {e['ic95']} (excluye cero: {e['excluye_cero']}); Δ macro-F1 {f['diferencia']} IC95 {f['ic95']} "
            f"(excluye cero: {f['excluye_cero']}); IC solapados {d['ic_se_solapan']}; D-57 {'CUMPLIDO' if d57['cumplido'] else 'NO cumplido'}: {d57['motivo']}"
        )
        for t, x in d["recall_por_tema"].items():
            lineas.append(f"    Δ recall {t}: " + ("sin IC (menos eventos que el mínimo)" if x is None else f"{x['diferencia']:+} IC95 {x['ic95']} ({x['eventos']} eventos)"))
    return lineas


# ------------------------------------------------------------------ CLI


def _normalizar(informe: dict[str, Any]) -> dict[str, Any]:
    """El informe tal como queda en el JSON (tuplas a listas, tipos de numpy a nativos), para compararlo con el archivo."""
    resultado: dict[str, Any] = json.loads(json.dumps(informe, ensure_ascii=False, default=_nativo))
    return resultado


def _nativo(valor: Any) -> Any:
    if isinstance(valor, np.generic):
        return valor.item()
    if isinstance(valor, np.ndarray):
        return valor.tolist()
    return str(valor)


def main(argv: list[str] | None = None) -> int:
    """CLI: corrida real única, o ``--verificar`` para reproducir las métricas desde la caché sin red."""
    parser = argparse.ArgumentParser(description="C-10c: clasificación de temas con LLM (medición única)")
    parser.add_argument("--verificar", action="store_true", help="reproduce las métricas desde la caché, sin red, y las compara con el JSON")
    parser.add_argument("--etiquetas", type=Path, default=evalclas.ETIQUETAS)
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--salida", type=Path, default=None)
    args = parser.parse_args(argv)
    configurar_logging()
    cfg, temas, clas = cargar_clasificacion_llm(), cargar_temas(), cargar_clasificacion()
    salida = args.salida or RAIZ / cfg.salida
    if not args.etiquetas.exists() or not args.base.exists():
        print(f"Faltan {args.etiquetas} o {args.base}: no se calcula nada (no se inventan métricas).", file=sys.stderr)
        return evalclas.CODIGO_SIN_ETIQUETAS
    if not args.verificar and salida.exists():
        print(f"Ya existe {salida.name}: la medición de C-10c es única y no se repite. Use --verificar para reproducirla desde la caché.", file=sys.stderr)
        return CODIGO_DIFERENCIAS

    filas = cargar_filas(args.etiquetas, args.base, temas)
    prompt = cargar_prompt_clasificacion(cfg, temas)
    if fugas := titulares_en_prompt(prompt.texto, filas.titulares):
        print(f"FUGA: {len(fugas)} titulares evaluados aparecen en el prompt; no se llama a nadie.", file=sys.stderr)
        return CODIGO_DIFERENCIAS

    # Primero todo lo que puede fallar sin costo (embeddings del método A y baselines); recién después se llama al proveedor.
    conj = pe.cargar_conjunto(args.etiquetas, args.base, clas, temas)
    if conj.ids != filas.ids:
        print("Las filas del LLM y las del método A no coinciden: no se compara.", file=sys.stderr)
        return CODIGO_DIFERENCIAS
    todas = pe.predicciones_de_sistemas(conj, clas, temas)
    clave_a = next(n for n in todas if "(activo)" in n)
    baselines = {n: p for n, p in todas.items() if n.startswith("baseline_")}
    mejor = sup.mejor_baseline(baselines, conj.y, conj.eventos, clas.criterio_ab)
    comparadores = {"metodo_A_activo": todas[clave_a], mejor: baselines[mejor]}

    proveedor = None if args.verificar else crear_proveedor_clasificacion(cfg)
    clasificador = ClasificadorLlm(cfg, temas, proveedor, CacheLlm(RAIZ / cfg.cache.ruta), prompt)
    try:
        resultados = clasificar_filas(filas, clasificador)
    except SinCache as exc:
        print(f"CACHÉ INCOMPLETA: {exc}", file=sys.stderr)
        return CODIGO_DIFERENCIAS
    except (TopeDeCostoAlcanzado, ErrorProveedor) as exc:
        print(f"BLOQUEADO ({type(exc).__name__}): {redactar(str(exc))}", file=sys.stderr)
        return CODIGO_BLOQUEADO

    precios = cargar_generacion().deepseek.precio_usd_por_millon_tokens
    informe = _normalizar(construir_informe(filas, resultados, comparadores, mejor, cfg, prompt, clas, temas, cargar_carga().salida.z_intervalo_confianza, precios))
    print("\n".join(imprimir(informe)))

    if args.verificar:
        if not salida.exists():
            print(f"No existe {salida}: no hay nada que verificar.", file=sys.stderr)
            return evalclas.CODIGO_SIN_ETIQUETAS
        guardado = json.loads(salida.read_text(encoding="utf-8"))
        diferencias = diferencias_de_metricas(guardado, informe)
        if diferencias:
            print("\nVERIFICACIÓN: las métricas reproducidas NO coinciden con " + salida.name + ":\n" + "\n".join(diferencias[:20]), file=sys.stderr)
            return CODIGO_DIFERENCIAS
        print(f"\nVERIFICACIÓN: las métricas reproducidas desde la caché (sin red, {informe['corrida']['llamadas_de_cache']} de {informe['corrida']['llamadas']} llamadas) son idénticas a {salida.name}.")
        return 0

    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nEscrito {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
