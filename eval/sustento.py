"""Validez de sustento (E1-18, PDF 9.1, ``docs/protocolo_evaluacion.md`` sección 4): la muestra y, cuando una persona la completa, el cálculo.

**El sistema no juzga su propio sustento.** ``muestrear`` elige al azar (semilla fija de ``config/benchmark.yaml``) 30 afirmaciones de
las salidas del benchmark y ``escribir_muestra`` las deja en ``outputs/revision_sustento.csv`` con la columna ``veredicto`` **vacía**. La
revisa una persona del equipo que no escribió el código de generación (``sustentada`` · ``parcial`` · ``no sustentada`` · ``tipo incorrecto``).
Regenerar la muestra **nunca pisa** una revisión empezada (``preparar_muestra``).

Con la revisión completa, ``poetry run python -m eval.sustento`` calcula la validez (solo cuenta «sustentada»), con numerador, denominador,
IC95 de bootstrap y de Wilson y los IDs de lo que no quedó sustentado. Con la revisión vacía o incompleta lo dice y no inventa un número.

**Procedencia (D-101).** La columna ``origen_juicio`` dice quién juzgó (``eval.origen_juicio``). Si alguna fila es del asistente, el
resultado lleva ``origen_juicio`` provisional, ``juicio_humano: false`` y el aviso, en el JSON y en la consola: nunca sale como humano.
Con un juicio no humano la meta se reporta como ``cumple_meta_provisional`` (nunca ``cumple_meta``) y ``meta_validez`` lleva el origen
al lado. El criterio oficial es la estimación puntual (protocolo, sección 4); el límite inferior de Wilson se informa aparte, sin cambiarlo.
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

from eval import origen_juicio
from eval.metricas import proporcion_con_ic
from src.configuracion import RAIZ, ConfigBenchmark, ConfigOrigenJuicio, CriterioAB, cargar_benchmark, cargar_origen_juicio

REVISION = RAIZ / "outputs" / "revision_sustento.csv"
SALIDA = RAIZ / "outputs" / "sustento.json"
COLUMNAS = ["id_muestra", "origen", "id_unidad", "id_afirmacion", "tipo", "texto", "citas", "evidencia_citada", "veredicto", "comentario", "revisor", "origen_juicio"]
CLAVE_ORDEN = ("origen", "id_unidad", "id_afirmacion")
COLUMNAS_REVISOR = ("id_muestra", "veredicto", "comentario", "revisor", "origen_juicio")   # las llena quien revisa


def muestrear(pool: Sequence[dict[str, Any]], n: int, semilla: int) -> list[dict[str, Any]]:
    """``n`` afirmaciones al azar del conjunto (todas si hay menos), reproducibles con la semilla; salen en el orden del conjunto."""
    ordenado = sorted(pool, key=lambda x: tuple(str(x[k]) for k in CLAVE_ORDEN))
    if len(ordenado) <= n:
        return ordenado
    elegidos = sorted(random.Random(semilla).sample(range(len(ordenado)), n))
    return [ordenado[i] for i in elegidos]


def _filas(muestra: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {**{c: str(x.get(c, "")) for c in COLUMNAS if c not in COLUMNAS_REVISOR},
         **{c: "" for c in COLUMNAS_REVISOR}, "id_muestra": f"S{i:02d}"}
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


def meta_validez(sustentadas: dict[str, Any], meta: float) -> dict[str, Any]:
    """La meta contra la estimación puntual (el criterio oficial) y, como información adicional, contra el límite inferior de Wilson."""
    inferior = sustentadas["ic95_wilson"][0]
    return {
        "meta": meta,
        "criterio": "estimación puntual (docs/protocolo_evaluacion.md, sección 4)",
        "estimacion_puntual": sustentadas["proporcion"],
        "cumple_estimacion_puntual": sustentadas["proporcion"] >= meta,
        "limite_inferior_wilson": inferior,
        "cumple_con_limite_inferior_wilson": inferior >= meta,
        "nota_wilson": "información adicional: no reemplaza el criterio oficial",
    }


def linea_meta(r: dict[str, Any]) -> str:
    """Una línea de consola con la meta, siempre con el límite de Wilson y el origen del juicio (y su aviso si no es humano)."""
    m = r["meta_validez"]
    si_no = {True: "cumple", False: "no cumple"}
    linea = (f"Meta ≥ {m['meta']:.0%} (estimación puntual, criterio oficial): {si_no[m['cumple_estimacion_puntual']]} "
             f"({m['estimacion_puntual']:.1%}) · límite inferior Wilson {m['limite_inferior_wilson']:.1%}: "
             f"{si_no[m['cumple_con_limite_inferior_wilson']]} (información adicional) · origen del juicio: {m['origen_juicio']}")
    if "aviso_origen" in r:
        linea += f" · {r['aviso_origen']}"
    return linea


def validez(filas: Sequence[dict[str, str]], criterio: CriterioAB, cfg: ConfigBenchmark | None = None,
            cfg_origen: ConfigOrigenJuicio | None = None) -> dict[str, Any]:
    """Validez de sustento = «sustentada» / revisadas, con IC y los fallos. ``estado``: ``pendiente_revision_humana`` (nadie revisó),
    ``incompleta`` (faltan filas) o ``completa``. Un veredicto fuera de la lista falla con el ``id_muestra``; un origen desconocido
    también (``OrigenInvalido`` es un ``ValueError``). Con al menos un veredicto, el resultado lleva el origen del juicio (D-101)."""
    cfg = cfg or cargar_benchmark()
    cfg_origen = cfg_origen or cargar_origen_juicio()
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
    origen = origen_juicio.origen_de_filas([f for f in filas if f["id_muestra"] in puestos], cfg_origen)
    base |= origen_juicio.describir(origen, cfg_origen)
    if origen != cfg_origen.humano:
        base["aviso_origen"] = cfg_origen.aviso_provisional
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
        "meta_validez": meta_validez(sustentadas, cfg.sustento.meta_validez) | origen_juicio.describir(origen, cfg_origen),
        "revisores": sorted({(f.get("revisor") or "").strip() for f in filas if (f.get("revisor") or "").strip()}),
    }
    clave_meta = "cumple_meta" if origen == cfg_origen.humano else "cumple_meta_provisional"
    resultado[clave_meta] = resultado["meta_validez"]["cumple_estimacion_puntual"]
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
    if "meta_validez" in r:
        print("\n" + linea_meta(r))
    if "aviso_origen" in r:
        print(f"\n{r['aviso_origen']} · origen_juicio: {r['origen_juicio']}")
    if r["estado"] != "completa":
        print(f"\nRevisión {r['estado'].replace('_', ' ')}: no se escribe {args.salida.name}.", file=sys.stderr)
        return 2
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nEscrito: {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
