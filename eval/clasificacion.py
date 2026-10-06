"""Evaluación de la clasificación temática (E1-07): baseline vs. embeddings (A y B), con n e IC (D-21, D-57, D-66).

Dos fuentes de verdad, nunca mezcladas:

1. **Casos difíciles** de ``docs/guia_temas.md``: 15 titulares escritos para fijar el criterio, con tema principal y
   secundario esperados. Es un conjunto de **prueba**, no de entrenamiento: ninguno puede ser un ejemplo ni un
   prototipo de ``config/temas.yaml`` (``casos_en_referencias`` lo comprueba). n = 15 es muy poco: los IC son anchos y
   no alcanzan para elegir modelo ni método; sirven como prueba de regresión y de los límites del criterio.
2. **Etiquetas humanas** (``eval/etiquetas.csv``, E1-06): macro-F1, F1/precisión/recall por tema, matriz de confusión
   y criterio A vs. B. Si el archivo no existe, **no se calcula ni se inventa ninguna métrica** sobre datos reales.

Nunca se usa el ``tema`` de origen del contrato (D-62) ni como etiqueta ni como entrada, y se excluyen de la evaluación
los titulares de ``config/ejemplos_excluidos.txt``. Uso: ``poetry run python -m eval.clasificacion``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval import metricas
from src import db
from src.baseline import SIN_TEMA, Baseline
from src.clasificacion import (
    METODO_A,
    METODO_B,
    Decision,
    construir_referencias,
    proporcion,
    puntuar,
    decidir_todos,
    texto_de_entrada,
)
from src.configuracion import (
    RAIZ,
    ConfigClasificacion,
    ConfigTemas,
    cargar_carga,
    cargar_clasificacion,
    cargar_normalizacion,
    cargar_temas,
)
from src.embeddings import Embeddings, crear
from src.limpieza import Reglas, limpiar_titulo, plano

GUIA = RAIZ / "docs" / "guia_temas.md"
ETIQUETAS = RAIZ / "eval" / "etiquetas.csv"
EXCLUIDOS = RAIZ / "config" / "ejemplos_excluidos.txt"
SALIDA = RAIZ / "outputs" / "clasificacion.json"
CODIGO_SIN_ETIQUETAS = 2
FUERA_DE_LOS_TEMAS = {"fuera_de_temas", "no_es_panama", SIN_TEMA}   # para evaluar, todo esto es "sin tema"
SIN_SECUNDARIO = {"", "—", "-", "–", "ninguno", "ninguna", "none"}
TITULO_SECCION = "## Casos difíciles"
BASE_JACCARD = 0.8   # un caso difícil con este solapamiento de palabras con un ejemplo cuenta como casi idéntico


# ------------------------------------------------------------------ casos difíciles


@dataclass(frozen=True)
class CasoDificil:
    id: str
    titular: str
    principal: str
    secundario: str | None
    regla: str


def _nombre_a_id(temas: ConfigTemas) -> dict[str, str]:
    mapa = {plano(t.nombre): i for i, t in temas.temas.items()}
    mapa.update({i: i for i in temas.temas})
    mapa.update({k: SIN_TEMA for k in FUERA_DE_LOS_TEMAS})
    return mapa


def tema_a_id(valor: str, temas: ConfigTemas) -> str | None:
    """``"Logística/Canal"`` / ``"`logistica`"`` -> ``"logistica"``; ``"—"`` o vacío -> ``None``; fuera de temas -> ``sin_tema``."""
    limpio = plano(valor.strip().strip("`").strip())
    if limpio in SIN_SECUNDARIO:
        return None
    mapa = _nombre_a_id(temas)
    if limpio not in mapa:
        raise ValueError(f"tema desconocido: {valor!r} (conocidos: {sorted(mapa)})")
    return mapa[limpio]


def leer_casos_dificiles(ruta: Path = GUIA, temas: ConfigTemas | None = None) -> list[CasoDificil]:
    """Lee la tabla de "Casos difíciles" de ``docs/guia_temas.md``: la guía es la única fuente (no se duplica)."""
    temas = temas or cargar_temas()
    texto = ruta.read_text(encoding="utf-8")
    if TITULO_SECCION not in texto:
        raise ValueError(f"{ruta.name}: no tiene la sección {TITULO_SECCION!r}")
    seccion = texto[texto.index(TITULO_SECCION) + len(TITULO_SECCION) :]
    seccion = re.split(r"\n## ", seccion, maxsplit=1)[0]
    casos: list[CasoDificil] = []
    for linea in seccion.splitlines():
        if not linea.startswith("|"):
            continue
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) != 4 or celdas[0] == "Titular" or set(celdas[0]) <= {"-", " "}:
            continue
        principal = tema_a_id(celdas[1], temas)
        if principal is None:
            raise ValueError(f"caso sin tema principal: {celdas[0]!r}")
        casos.append(CasoDificil(f"CD-{len(casos) + 1:02d}", celdas[0], principal, tema_a_id(celdas[2], temas), celdas[3]))
    if not casos:
        raise ValueError(f"{ruta.name}: la tabla de casos difíciles está vacía")
    return casos


def _palabras(texto: str) -> set[str]:
    return set(re.findall(r"\w+", plano(texto)))


def casos_en_referencias(casos: list[CasoDificil], temas: ConfigTemas, reglas: Reglas) -> list[str]:
    """Casos difíciles que son (o casi son) un ejemplo, un prototipo o una descripción de ``temas.yaml``.

    Un caso de prueba que sirve de referencia al clasificador es una fuga: devuelve ``["CD-03: ..."]`` con cada
    coincidencia exacta (sin tildes ni mayúsculas) o con solapamiento de palabras (Jaccard) de ``BASE_JACCARD`` o más.
    """
    referencias: list[tuple[str, str]] = []
    for id_tema, tema in temas.temas.items():
        referencias.append((f"{id_tema}.descripcion", tema.descripcion))
        referencias += [(f"{id_tema}.ejemplo", limpiar_titulo(e.titulo, None, None, reglas)) for e in tema.ejemplos]
        referencias += [(f"{id_tema}.{sub}.prototipo", s.prototipo) for sub, s in tema.subtemas.items()]
    problemas = []
    for caso in casos:
        mias = _palabras(caso.titular)
        for donde, texto in referencias:
            otras = _palabras(texto)
            union = mias | otras
            if plano(caso.titular) == plano(texto) or (union and len(mias & otras) / len(union) >= BASE_JACCARD):
                problemas.append(f"{caso.id}: {caso.titular!r} coincide con {donde}")
    return problemas


# ------------------------------------------------------------------ predicciones


def clases_de(temas: ConfigTemas) -> list[str]:
    """Las clases de la evaluación: los 6 temas y ``sin_tema`` (que incluye fuera_de_temas y no_es_panama)."""
    return [*temas.temas, SIN_TEMA]


@dataclass(frozen=True)
class Prediccion:
    principal: str
    secundario: str | None
    similitud: float | None
    segundo_mejor: str | None = None   # 2.º tema por similitud (sin margen): diagnóstico del tema secundario


def predecir(
    textos: list[str], cfg: ConfigClasificacion, temas: ConfigTemas, nombre_modelo: str, emb: Embeddings, reglas: Reglas
) -> dict[str, list[Prediccion]]:
    """Predicciones de ``baseline`` y del modelo con los métodos A y B (claves ``baseline``, ``A``, ``B``)."""
    baseline = Baseline(cfg, temas)
    salida: dict[str, list[Prediccion]] = {
        "baseline": [Prediccion(r.principal, r.secundario, None, r.secundario) for r in map(baseline.clasificar, textos)]
    }
    ref = construir_referencias(emb, temas, reglas)
    vectores = emb.codificar(textos, "titular")
    for metodo in (METODO_A, METODO_B):
        decisiones: list[Decision] = decidir_todos(
            puntuar(vectores, ref, metodo), ref.temas, cfg.modelos[nombre_modelo].umbrales[metodo]
        )
        salida[metodo] = [Prediccion(d.principal, d.secundario, d.similitud, d.segundo_mejor) for d in decisiones]
    return salida


# ------------------------------------------------------------------ evaluación de una configuración


def evaluar_configuracion(
    ids: list[str],
    textos: list[str],
    reales: list[str],
    secundarios: list[str | None],
    predichas: list[Prediccion],
    clases: list[str],
    cfg: ConfigClasificacion,
    z: float,
) -> dict[str, Any]:
    """Exactitud, macro-F1 (IC bootstrap), F1/precisión/recall por tema, matriz de confusión, secundario y fallos."""
    y_pred = [p.principal for p in predichas]
    aciertos = sum(1 for a, b in zip(reales, y_pred, strict=True) if a == b)
    con_secundario = [i for i, s in enumerate(secundarios) if s is not None]
    sin_secundario = [i for i, s in enumerate(secundarios) if s is None]
    soportadas = [c for c in clases if c in set(reales)]
    return {
        "exactitud_principal": proporcion(aciertos, len(reales), z),
        "macro_f1": metricas.macro_f1_con_ic(reales, y_pred, soportadas, cfg.criterio_ab),
        "clases_en_macro_f1": soportadas,
        "por_tema": metricas.por_clase(reales, y_pred, clases, z),
        "matriz_confusion": {"clases": clases, "filas_real_columnas_predicho": metricas.matriz_confusion(reales, y_pred, clases)},
        "secundario_esperado_acertado": proporcion(
            sum(1 for i in con_secundario if predichas[i].secundario == secundarios[i]), len(con_secundario), z
        ),
        "secundario_esperado_es_el_segundo_mejor": proporcion(
            sum(1 for i in con_secundario if predichas[i].segundo_mejor == secundarios[i]), len(con_secundario), z
        ),
        "secundario_dado_donde_no_se_espera": proporcion(
            sum(1 for i in sin_secundario if predichas[i].secundario is not None), len(sin_secundario), z
        ),
        "fallos": [
            {
                "id": ids[i],
                "titular": textos[i],
                "esperado": reales[i],
                "predicho": y_pred[i],
                "secundario_esperado": secundarios[i],
                "secundario_predicho": predichas[i].secundario,
                "similitud": None if predichas[i].similitud is None else round(predichas[i].similitud, 4),
            }
            for i in range(len(reales))
            if reales[i] != y_pred[i]
        ],
    }


def comparar(
    reales: list[str], predicciones: dict[str, list[Prediccion]], clases: list[str], cfg: ConfigClasificacion
) -> dict[str, Any]:
    """Criterio A vs. B (D-57) y diferencias con el baseline, sobre las mismas etiquetas."""
    soportadas = [c for c in clases if c in set(reales)]
    principal = {k: [p.principal for p in v] for k, v in predicciones.items()}
    return {
        "criterio_A_vs_B": metricas.aplicar_criterio(reales, principal[METODO_A], principal[METODO_B], soportadas, cfg.criterio_ab),
        "A_menos_baseline": metricas.diferencia_con_ic(reales, principal["baseline"], principal[METODO_A], soportadas, cfg.criterio_ab),
        "B_menos_baseline": metricas.diferencia_con_ic(reales, principal["baseline"], principal[METODO_B], soportadas, cfg.criterio_ab),
    }


def evaluar_casos_dificiles(
    cfg: ConfigClasificacion, temas: ConfigTemas, nombres_modelos: list[str], motores: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Baseline y, por modelo, A y B sobre los casos difíciles. ``motores`` permite inyectar un codificador de prueba."""
    reglas = Reglas.desde_config()
    casos = leer_casos_dificiles(GUIA, temas)
    fugas = casos_en_referencias(casos, temas, reglas)
    if fugas:
        raise ValueError("casos difíciles que son referencia del clasificador (fuga): " + "; ".join(fugas))
    z = cargar_carga().salida.z_intervalo_confianza
    clases = clases_de(temas)
    ids, textos = [c.id for c in casos], [c.titular for c in casos]
    reales, secundarios = [c.principal for c in casos], [c.secundario for c in casos]
    resultado: dict[str, Any] = {
        "n": len(casos),
        "fuente": "docs/guia_temas.md, sección 'Casos difíciles' (titulares ilustrativos, no del corpus)",
        "nota": (
            "n = 15: los IC son anchos y NO bastan para elegir modelo (D-20) ni método (D-21); es una prueba de "
            "regresión del criterio de frontera. Ningún caso es ejemplo ni prototipo de temas.yaml (comprobado)."
        ),
        "configuraciones": {},
    }
    for nombre in nombres_modelos:
        emb = crear(cfg, nombre, motor=(motores or {}).get(nombre))
        pred = predecir(textos, cfg, temas, nombre, emb, reglas)
        for etiqueta, preds in (("baseline", pred["baseline"]), (f"{nombre}/A", pred[METODO_A]), (f"{nombre}/B", pred[METODO_B])):
            if etiqueta == "baseline" and "baseline" in resultado["configuraciones"]:
                continue
            resultado["configuraciones"][etiqueta] = evaluar_configuracion(ids, textos, reales, secundarios, preds, clases, cfg, z)
        resultado.setdefault("comparaciones", {})[nombre] = comparar(reales, pred, clases, cfg)
    return resultado


# ------------------------------------------------------------------ datos reales con etiquetas humanas


def ids_excluidos(ruta: Path = EXCLUIDOS) -> set[str]:
    """``id_noticia`` de los titulares usados como ejemplo (nunca entran en la evaluación)."""
    return {
        linea.split("\t", 1)[0].strip()
        for linea in ruta.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.startswith("#")
    }


def leer_etiquetas(ruta: Path, columna: str, temas: ConfigTemas) -> dict[str, str]:
    """``id_noticia -> tema humano`` (id de tema o ``sin_tema``). Falla si falta la columna o hay un tema desconocido."""
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        campos = lector.fieldnames or []
        if "id_noticia" not in campos or columna not in campos:
            raise KeyError(f"{ruta.name} no tiene las columnas id_noticia y {columna!r} (tiene: {campos})")
        etiquetas: dict[str, str] = {}
        for fila in lector:
            valor = tema_a_id(fila[columna] or "", temas)
            if valor is not None:   # una celda vacía es "sin etiquetar", no una etiqueta
                etiquetas[fila["id_noticia"].strip()] = valor
    return etiquetas


def evaluar_etiquetas(
    ruta_etiquetas: Path,
    ruta_base: Path,
    columna: str,
    cfg: ConfigClasificacion,
    temas: ConfigTemas,
    nombres_modelos: list[str],
    motores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Métricas sobre los titulares con etiqueta humana que no son ruido y no son ejemplos de ``temas.yaml``.

    El texto sale de ``titulo_limpio``; las columnas ``tema`` (origen, D-62) y ``tema_clasificado`` no se leen: las
    predicciones se recalculan aquí con cada modelo y método.
    """
    etiquetas = leer_etiquetas(ruta_etiquetas, columna, temas)
    excluidos = ids_excluidos()
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = con.execute(
            "SELECT id_noticia, titulo_limpio, descripcion, es_ruido FROM noticias ORDER BY id_noticia"
        ).fetchall()
    finally:
        con.close()
    en_base = {f[0]: f for f in filas}
    z = cargar_carga().salida.z_intervalo_confianza
    conteo = {
        "etiquetados": len(etiquetas),
        "ejemplos_excluidos": sum(1 for i in etiquetas if i in excluidos),
        "no_estan_en_la_base": sum(1 for i in etiquetas if i not in en_base),
        "marcados_como_ruido_por_el_sistema": sum(1 for i in etiquetas if i in en_base and i not in excluidos and en_base[i][3]),
    }
    usados = sorted(i for i in etiquetas if i in en_base and i not in excluidos and not en_base[i][3])
    conteo["evaluados"] = len(usados)
    if not usados:
        return {"estado": "SIN_FILAS_EVALUABLES", "conteo": conteo}
    reglas = Reglas.desde_config()
    clases = clases_de(temas)
    textos = [texto_de_entrada(en_base[i][1], en_base[i][2], cfg.usar_descripcion) for i in usados]
    reales = [etiquetas[i] for i in usados]
    ninguno: list[str | None] = [None] * len(usados)
    resultado: dict[str, Any] = {"estado": "EVALUADO", "conteo": conteo, "configuraciones": {}, "comparaciones": {}}
    for nombre in nombres_modelos:
        emb = crear(cfg, nombre, motor=(motores or {}).get(nombre))
        pred = predecir(textos, cfg, temas, nombre, emb, reglas)
        for etiqueta, preds in (("baseline", pred["baseline"]), (f"{nombre}/A", pred[METODO_A]), (f"{nombre}/B", pred[METODO_B])):
            if etiqueta not in resultado["configuraciones"]:
                resultado["configuraciones"][etiqueta] = evaluar_configuracion(usados, textos, reales, ninguno, preds, clases, cfg, z)
        resultado["comparaciones"][nombre] = comparar(reales, pred, clases, cfg)
    return resultado


# ------------------------------------------------------------------ impresión


def _p(d: dict[str, Any]) -> str:
    if d["de"] == 0:
        return f"{d['n']}/{d['de']} (sin base)"
    return f"{d['n']}/{d['de']} = {100 * d['proporcion']:.1f} % [IC 95 %: {100 * d['ic95'][0]:.1f}–{100 * d['ic95'][1]:.1f} %]"


def _m(d: dict[str, Any]) -> str:
    if d["macro_f1"] is None or d["ic95"] is None:
        return "sin definir"
    return f"{d['macro_f1']:.3f} [IC 95 % bootstrap: {d['ic95'][0]:.3f}–{d['ic95'][1]:.3f}; n = {d['n']}, {d['remuestreos']} remuestreos]"


def imprimir(titulo: str, bloque: dict[str, Any], clases: list[str]) -> list[str]:
    """Líneas legibles de un bloque de evaluación (casos difíciles o datos reales)."""
    lineas = [f"== {titulo} =="]
    for nombre, c in bloque["configuraciones"].items():
        lineas.append(f"\n[{nombre}]")
        lineas.append(f"  exactitud del tema principal: {_p(c['exactitud_principal'])}")
        lineas.append(f"  macro-F1 (clases con soporte: {', '.join(c['clases_en_macro_f1'])}): {_m(c['macro_f1'])}")
        lineas.append("  por tema (F1 · precisión · recall):")
        for tema, v in c["por_tema"].items():
            f1 = "n/d" if v["f1"] is None else f"{v['f1']:.3f}"
            lineas.append(f"    {tema:18} F1 {f1} · P {_p(v['precision'])} · R {_p(v['recall'])}")
        lineas.append("  matriz de confusión (filas = real, columnas = predicho; orden: " + ", ".join(clases) + ")")
        lineas += ["    " + " ".join(f"{x:3d}" for x in fila) for fila in c["matriz_confusion"]["filas_real_columnas_predicho"]]
        lineas.append(f"  tema secundario esperado acertado: {_p(c['secundario_esperado_acertado'])}")
        lineas.append(f"  tema secundario esperado = 2.º mejor (sin margen): {_p(c['secundario_esperado_es_el_segundo_mejor'])}")
        lineas.append(f"  tema secundario dado donde no se espera: {_p(c['secundario_dado_donde_no_se_espera'])}")
        for fallo in c["fallos"]:
            lineas.append(f"  FALLO {fallo['id']}: «{fallo['titular']}» esperado {fallo['esperado']}, predicho {fallo['predicho']}")
    for modelo, comp in bloque.get("comparaciones", {}).items():
        crit = comp["criterio_A_vs_B"]
        lineas.append(f"\n[{modelo}] criterio A vs. B (D-57): se elige {crit['decision']}. {crit['motivo']}.")
        lineas.append(f"  B − A macro-F1: {crit['diferencia_macro_f1']} IC 95 %: {crit['ic95']}; temas que empeoran: {crit['temas_que_empeoran'] or 'ninguno'}")
        for nombre in ("A_menos_baseline", "B_menos_baseline"):
            lineas.append(f"  {nombre}: macro-F1 {comp[nombre]['diferencia_macro_f1']} IC 95 %: {comp[nombre]['ic95']}")
    return lineas


def main(argv: list[str] | None = None) -> int:
    """CLI: casos difíciles siempre; datos reales solo con ``eval/etiquetas.csv`` (si no, lo dice y no inventa nada)."""
    cfg, temas = cargar_clasificacion(), cargar_temas()
    parser = argparse.ArgumentParser(description="E1-07: macro-F1, F1 por tema y matriz de confusión; IA vs. baseline")
    parser.add_argument("--etiquetas", type=Path, default=ETIQUETAS)
    parser.add_argument("--columna", default="tema_principal", help="columna del tema humano en el CSV (nunca el tema de origen)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--modelos", nargs="+", choices=sorted(cfg.modelos), default=sorted(cfg.modelos))
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    clases = clases_de(temas)
    informe: dict[str, Any] = {
        "modelos": {n: {"id": cfg.modelos[n].id, "revision": cfg.modelos[n].revision} for n in args.modelos},
        "semilla": cfg.semilla,
        "casos_dificiles": evaluar_casos_dificiles(cfg, temas, args.modelos),
    }
    print("\n".join(imprimir("Casos difíciles de docs/guia_temas.md", informe["casos_dificiles"], clases)))
    codigo = 0
    if not args.etiquetas.exists():
        informe["datos_reales"] = {"estado": "PENDIENTE_ETIQUETAS", "detalle": f"no existe {args.etiquetas.name} (E1-06)"}
        print(
            f"\nDATOS REALES: PENDIENTE. No existe {args.etiquetas}. Las crea E1-06 (etiquetado humano); sin ellas no se "
            "calcula exactitud, macro-F1 ni se aplica el criterio A vs. B sobre datos reales (no se inventan números).",
            file=sys.stderr,
        )
        codigo = CODIGO_SIN_ETIQUETAS
    elif not args.base.exists():
        print(f"No existe {args.base}: ejecute normalización, limpieza y clasificación primero.", file=sys.stderr)
        return 1
    else:
        try:
            real = evaluar_etiquetas(args.etiquetas, args.base, args.columna, cfg, temas, args.modelos)
        except (KeyError, ValueError) as exc:
            print(f"ETIQUETAS NO UTILIZABLES: {exc}. No se calcula ninguna métrica sobre datos reales.", file=sys.stderr)
            return CODIGO_SIN_ETIQUETAS
        informe["datos_reales"] = real
        if real["estado"] == "EVALUADO":
            print("\n" + "\n".join(imprimir("Datos reales con etiquetas humanas", real, clases)))
        print(f"\nConteo de datos reales: {real['conteo']}")
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
