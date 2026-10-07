"""Evaluación del puntaje (E1-10): distribución de P y de cada componente y la tabla rango × estado de evidencia.

Lee ``puntajes`` y ``evidencia`` de ``data/senales.duckdb`` (los escribe ``python -m src.puntaje``) y reporta:

* **Distribución de P** y de **cada componente** (R, I, U, N, E): n, mínimo, mediana, máximo y desviación estándar
  poblacional. Un componente con desviación menor a ``puntaje_eval.casi_constante_desviacion`` (``config/prioridad.yaml``)
  se marca **casi constante**: casi no ordena, y su peso en P es en la práctica una constante.
* **Rango × estado de evidencia** (3 × 3): cuántos grupos hay en cada celda, con n e IC de Wilson al 95 %, y la lista de los
  casos **alto + insuficiente** (relevantes pero sin evidencia: «Investigar ya») y **bajo + suficiente** (bien respaldados pero poco
  prioritarios), que muestran que el estado de evidencia es independiente de P.

Es una descripción de los datos del snapshot, no una prueba de que el ranking sea «correcto»: eso se mide con Precision@5 y
con la revisión editorial (``docs/protocolo_evaluacion.md``). La estabilidad del ranking: ``python -m eval.sensibilidad``.

Uso: ``poetry run python -m eval.puntaje [--salida outputs/puntaje.json]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src import db
from src.clasificacion import proporcion
from src.configuracion import RAIZ, ConfigPrioridad, ReglasV13, cargar_carga, cargar_normalizacion, cargar_prioridad, cargar_reglas
from src.evidencia import ESTADO_INSUFICIENTE, ESTADO_PARCIAL, ESTADO_SUFICIENTE
from src.puntaje import COMPONENTES

logger = logging.getLogger(__name__)

SALIDA = RAIZ / "outputs" / "puntaje.json"
DECIMALES = 4          # solo presentación
RANGOS = ("alto", "medio", "bajo")
ESTADOS = (ESTADO_SUFICIENTE, ESTADO_PARCIAL, ESTADO_INSUFICIENTE)
COLUMNA_DE = {"R": "relevancia", "I": "impacto", "U": "urgencia", "N": "novedad", "E": "evidencia"}


def resumen(valores: Sequence[float]) -> dict[str, Any]:
    """n, mínimo, mediana, máximo, media y desviación estándar poblacional."""
    if not valores:
        return {"n": 0, "min": None, "mediana": None, "max": None, "media": None, "desviacion": None}
    r = lambda x: round(float(x), DECIMALES)  # noqa: E731 - redondeo de presentación
    return {
        "n": len(valores), "min": r(min(valores)), "mediana": r(statistics.median(valores)), "max": r(max(valores)),
        "media": r(statistics.fmean(valores)), "desviacion": r(statistics.pstdev(valores)),
    }


def distribucion_de_componentes(puntajes: Sequence[Mapping[str, Any]], cfg: ConfigPrioridad) -> dict[str, Any]:
    """Resumen de cada componente con la marca ``casi_constante`` (desviación < ``casi_constante_desviacion``)."""
    salida: dict[str, Any] = {}
    for k in COMPONENTES:
        r = resumen([float(p[COLUMNA_DE[k]]) for p in puntajes])
        r["casi_constante"] = r["desviacion"] is not None and r["desviacion"] < cfg.puntaje_eval.casi_constante_desviacion
        salida[k] = r
    return salida


def tabla_rango_por_estado(
    unidos: Sequence[Mapping[str, Any]], titulares: Mapping[str, str], z: float
) -> dict[str, Any]:
    """Conteo, proporción con IC y casos de cada celda rango × estado."""
    n = len(unidos)
    celdas: dict[str, Any] = {}
    for rango in RANGOS:
        for estado in ESTADOS:
            grupo = [u for u in unidos if u["rango"] == rango and u["estado"] == estado]
            celdas[f"{rango}|{estado}"] = {
                **proporcion(len(grupo), n, z),
                "casos": [
                    {"id_grupo": u["id_grupo"], "posicion": u["posicion"], "puntaje": round(u["puntaje"], 2), "accion": u["accion"],
                     "titular_central": titulares.get(u["id_grupo"])}
                    for u in sorted(grupo, key=lambda u: u["posicion"])
                ],
            }
    return {
        "filas": list(RANGOS),
        "columnas": list(ESTADOS),
        "celdas": celdas,
        "alto_insuficiente": celdas[f"alto|{ESTADO_INSUFICIENTE}"]["casos"],
        "bajo_suficiente": celdas[f"bajo|{ESTADO_SUFICIENTE}"]["casos"],
    }


def evaluar(ruta_base: Path, reglas: ReglasV13, cfg: ConfigPrioridad, z: float) -> dict[str, Any]:
    """Lee las tablas de E1-10 y arma el reporte. Falla si todavía no se corrió ``src.puntaje``."""
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        existentes = {f[0] for f in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        if not {"puntajes", "evidencia"} <= existentes or db.contar_filas(con, "puntajes") == 0:
            raise RuntimeError("no hay puntajes: ejecute `poetry run python -m src.puntaje`")
        puntajes = db.leer_tabla(con, "puntajes", "posicion")
        evidencia = {e["id_grupo"]: e for e in db.leer_tabla(con, "evidencia")}
        titulares = {g["id_grupo"]: g["titular_central"] for g in db.leer_tabla(con, "grupos")}
    finally:
        con.close()
    unidos = [{**p, "estado": evidencia[p["id_grupo"]]["estado"], "accion": evidencia[p["id_grupo"]]["accion"]} for p in puntajes]
    return {
        "nota": "Descripción de los datos del snapshot; el ranking se valida con Precision@5 y revisión editorial. P es de ordenamiento: no habilita publicación.",
        "version_reglas": reglas.version,
        "grupos": len(puntajes),
        "puntaje": resumen([float(p["puntaje"]) for p in puntajes]),
        "componentes": distribucion_de_componentes(puntajes, cfg),
        "umbral_casi_constante": cfg.puntaje_eval.casi_constante_desviacion,
        "por_rango": {k: proporcion(sum(1 for p in puntajes if p["rango"] == k), len(puntajes), z) for k in RANGOS},
        "por_estado_de_evidencia": {k: proporcion(sum(1 for u in unidos if u["estado"] == k), len(unidos), z) for k in ESTADOS},
        "rango_por_estado": tabla_rango_por_estado(unidos, titulares, z),
    }


def imprimir(r: Mapping[str, Any]) -> None:
    p = r["puntaje"]
    print(f"== P (n = {r['grupos']} grupos, reglas {r['version_reglas']}): min {p['min']} · mediana {p['mediana']} · max {p['max']} · desviación {p['desviacion']} ==")
    print(f"\n== Componentes (casi constante = desviación < {r['umbral_casi_constante']}) ==")
    for k, c in r["componentes"].items():
        marca = "  <- CASI CONSTANTE" if c["casi_constante"] else ""
        print(f"  {k}: min {c['min']} · mediana {c['mediana']} · max {c['max']} · desviación {c['desviacion']}{marca}")
    print("\n== Rango × estado de evidencia (n, proporción, IC95) ==")
    t = r["rango_por_estado"]
    print(f"  {'':8}" + "".join(f"{e:>34}" for e in t["columnas"]))
    for rango in t["filas"]:
        fila = ""
        for estado in t["columnas"]:
            c = t["celdas"][f"{rango}|{estado}"]
            fila += f"{c['n']:>3}/{c['de']} = {c['proporcion']} {c['ic95']}".rjust(34)
        print(f"  {rango:8}{fila}")
    for etiqueta, clave in (("alto + insuficiente", "alto_insuficiente"), ("bajo + suficiente", "bajo_suficiente")):
        casos = t[clave]
        print(f"\n== {etiqueta}: {len(casos)} caso(s) ==")
        for c in casos[:5]:
            print(f"  {c['posicion']:>2}. {c['id_grupo']} · P={c['puntaje']} · {c['accion']} · {(c['titular_central'] or '')[:70]}")
        if len(casos) > 5:
            print(f"  … y {len(casos) - 5} más (en el JSON)")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m eval.puntaje``."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="E1-10: distribución de P y de sus componentes, y rango × estado de evidencia")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero la tubería hasta `python -m src.puntaje`", args.base)
        return 1
    try:
        resultado = evaluar(args.base, cargar_reglas(), cargar_prioridad(), cargar_carga().salida.z_intervalo_confianza)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    imprimir(resultado)
    print(f"\nEscrito: {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
