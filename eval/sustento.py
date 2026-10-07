"""Validez de sustento (E1-18, PDF 9.1, ``docs/protocolo_evaluacion.md`` sección 4): la muestra y, cuando una persona la completa, el cálculo.

**El sistema no juzga su propio sustento.** ``muestrear`` elige al azar (semilla fija de ``config/benchmark.yaml``) 30 afirmaciones de
las salidas del benchmark y ``escribir_muestra`` las deja en ``outputs/revision_sustento.csv`` con la columna ``veredicto`` **vacía**. La
revisa una persona del equipo que no escribió el código de generación (``sustentada`` · ``parcial`` · ``no sustentada`` · ``tipo incorrecto``).
Regenerar la muestra **nunca pisa** una revisión empezada (``preparar_muestra``).

Con la revisión completa, ``poetry run python -m eval.sustento`` calcula la validez (solo cuenta «sustentada»), con numerador, denominador,
IC95 de bootstrap y de Wilson y los IDs de lo que no quedó sustentado. Con la revisión vacía o incompleta lo dice y no inventa un número.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eval.metricas import proporcion_con_ic
from src.configuracion import RAIZ, ConfigBenchmark, CriterioAB, cargar_benchmark

REVISION = RAIZ / "outputs" / "revision_sustento.csv"
SALIDA = RAIZ / "outputs" / "sustento.json"
COLUMNAS = ["id_muestra", "origen", "id_unidad", "id_afirmacion", "tipo", "texto", "citas", "evidencia_citada", "veredicto", "comentario", "revisor"]
CLAVE_ORDEN = ("origen", "id_unidad", "id_afirmacion")


def muestrear(pool: Sequence[dict[str, Any]], n: int, semilla: int) -> list[dict[str, Any]]:
    """``n`` afirmaciones al azar del conjunto (todas si hay menos), reproducibles con la semilla; salen en el orden del conjunto."""
    ordenado = sorted(pool, key=lambda x: tuple(str(x[k]) for k in CLAVE_ORDEN))
    if len(ordenado) <= n:
        return ordenado
    elegidos = sorted(random.Random(semilla).sample(range(len(ordenado)), n))
    return [ordenado[i] for i in elegidos]


def _filas(muestra: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {**{c: str(x.get(c, "")) for c in COLUMNAS if c not in ("id_muestra", "veredicto", "comentario", "revisor")},
         "id_muestra": f"S{i:02d}", "veredicto": "", "comentario": "", "revisor": ""}
        for i, x in enumerate(muestra, 1)
    ]


def escribir_muestra(muestra: Sequence[dict[str, Any]], ruta: Path) -> None:
    """Escribe la muestra con el veredicto vacío (UTF-8, una fila por afirmación)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(_filas(muestra))


def leer_revision(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def preparar_muestra(muestra: Sequence[dict[str, Any]], ruta: Path) -> str:
    """Escribe la muestra salvo que la persona ya haya empezado a revisarla: ``escrita``, ``reescrita``, ``reescrita_sin_cambios`` o
    ``conservada_con_veredictos`` (en cuyo caso no se toca el archivo)."""
    if not ruta.exists():
        escribir_muestra(muestra, ruta)
        return "escrita"
    if any((f.get("veredicto") or "").strip() for f in leer_revision(ruta)):
        return "conservada_con_veredictos"
    antes = ruta.read_bytes()
    escribir_muestra(muestra, ruta)
    return "reescrita_sin_cambios" if ruta.read_bytes() == antes else "reescrita"


def validez(filas: Sequence[dict[str, str]], criterio: CriterioAB, cfg: ConfigBenchmark | None = None) -> dict[str, Any]:
    """Validez de sustento = «sustentada» / revisadas, con IC y los fallos. ``estado``: ``pendiente_revision_humana`` (nadie revisó),
    ``incompleta`` (faltan filas) o ``completa``. Un veredicto fuera de la lista falla con el ``id_muestra``."""
    cfg = cfg or cargar_benchmark()
    permitidos = list(cfg.sustento.veredictos)
    puestos: dict[str, str] = {}
    invalidos = []
    for f in filas:
        v = " ".join((f.get("veredicto") or "").lower().split())
        if not v:
            continue
        if v not in permitidos:
            invalidos.append(f"{f.get('id_muestra', '?')}: {v!r}")
        puestos[f["id_muestra"]] = v
    if invalidos:
        raise ValueError(f"veredicto fuera de {permitidos}: " + "; ".join(invalidos))
    de, revisadas = len(filas), len(puestos)
    base: dict[str, Any] = {"de": de, "revisadas": revisadas, "meta": cfg.sustento.meta_validez, "muestra_prevista": cfg.sustento.muestra}
    if revisadas == 0:
        return {"estado": "pendiente_revision_humana", **base,
                "nota": "Falta la revisión de una persona que no escribió el código de generación (docs/protocolo_evaluacion.md, sección 4)."}
    conteo = Counter(puestos.values())
    conteo_completo = {v: conteo.get(v, 0) for v in permitidos}
    if revisadas < de:
        return {"estado": "incompleta", **base, "conteo": conteo_completo, "nota": f"Faltan {de - revisadas} afirmaciones por revisar."}
    por_id = {f["id_muestra"]: f for f in filas}
    sustentadas = proporcion_con_ic(conteo_completo["sustentada"], revisadas, criterio)
    resultado: dict[str, Any] = {
        "estado": "completa", **base, "conteo": conteo_completo, "sustentadas": sustentadas,
        "parciales": proporcion_con_ic(conteo_completo["parcial"], revisadas, criterio),
        "tipo_incorrecto": proporcion_con_ic(conteo_completo["tipo incorrecto"], revisadas, criterio),
        "fallos": [
            {"id_muestra": i, "id": f"{por_id[i]['id_unidad']}/{por_id[i]['id_afirmacion']}", "veredicto": v}
            for i, v in puestos.items() if v != "sustentada"
        ],
        "cumple_meta": sustentadas["proporcion"] >= cfg.sustento.meta_validez,
        "revisores": sorted({(f.get("revisor") or "").strip() for f in filas if (f.get("revisor") or "").strip()}),
    }
    if revisadas < cfg.sustento.muestra:
        resultado["nota"] = f"La muestra tiene {revisadas} < {cfg.sustento.muestra} afirmaciones: no se produjeron más (PDF 9.1: «si se producen tantas»)."
    return resultado


def principal(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E1-18: validez de sustento con la revisión humana completada")
    parser.add_argument("--archivo", type=Path, default=REVISION)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    if not args.archivo.exists():
        print(f"ERROR: no existe {args.archivo}: genere la muestra con `poetry run python -m eval.run_benchmark --split dev`", file=sys.stderr)
        return 1
    cfg = cargar_benchmark()
    try:
        r = validez(leer_revision(args.archivo), cfg.intervalos, cfg)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r["estado"] != "completa":
        print(f"\nRevisión {r['estado'].replace('_', ' ')}: no se escribe {args.salida.name}.", file=sys.stderr)
        return 2
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nEscrito: {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
