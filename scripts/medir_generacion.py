"""Mide la latencia de la generación con un proveedor real (E1-12): primera respuesta y paquete completo, por separado.

- **Primera respuesta** = lo que espera la persona para ver la primera pestaña: el paso 1 (afirmaciones) más el primer grupo
  de redacción (título + titulares + copy).
- **Paquete completo** = el paso 1 más los cuatro grupos (5 llamadas).

Cada repetición parte de cero (un ``Generador`` nuevo). Se descartan las llamadas de calentamiento (carga del modelo en frío).
Resultado: mediana y percentil de ``config/generacion.yaml`` · ``medicion``, con n, y el costo si el proveedor es de pago.
Nunca imprime claves ni prompts (D-69).

    poetry run python -m scripts.medir_generacion --proveedor ollama
    poetry run python -m scripts.medir_generacion --proveedor deepseek --repeticiones 3
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from src.configuracion import RAIZ, cargar_generacion, leer_local_env
from src.generacion import EntradaFicha, Generador
from src.llm.proveedor import ErrorProveedor, crear_proveedor
from src.registro import configurar_logging

FICHA_POR_DEFECTO = RAIZ / "tests" / "fixtures" / "ficha_generacion.json"
SALIDA = RAIZ / "outputs"


def percentil(valores: list[float], p: int) -> float:
    """Percentil por rango más cercano (con n pequeño no se interpola)."""
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p / 100 * len(ordenados)) - 1)]


def resumen(valores: list[float], p: int) -> dict[str, Any]:
    return {"n": len(valores), "mediana_s": round(statistics.median(valores), 2), f"p{p}_s": round(percentil(valores, p), 2), "min_s": round(min(valores), 2), "max_s": round(max(valores), 2)}


def una_repeticion(ficha: EntradaFicha, proveedor: Any) -> dict[str, Any]:
    g = Generador(ficha, proveedor)
    inicio = time.perf_counter()
    g.generar_grupo("titulos")  # incluye el paso 1
    primera = time.perf_counter() - inicio
    for grupo in g.grupos[1:]:
        g.generar_grupo(grupo)
    total = time.perf_counter() - inicio
    paquete = g.paquete()
    assert paquete is not None
    secciones_vacias = [v.referencia for v in paquete.vacios if v.origen == "seccion" and not v.motivo.startswith("recortada")]
    secciones_recortadas = [v.referencia for v in paquete.vacios if v.motivo.startswith("recortada")]
    return {
        "primera_respuesta_s": primera,
        "paquete_completo_s": total,
        "llamadas": len(g.llamadas),
        "tokens_entrada": sum(c.tokens_entrada for c in g.llamadas),
        "tokens_salida": sum(c.tokens_salida for c in g.llamadas),
        "secciones_vacias": secciones_vacias,
        "secciones_recortadas": secciones_recortadas,
        "afirmaciones_validas": len(paquete.afirmaciones),
        "descartadas": len(g.descartadas),
    }


def principal(argv: list[str] | None = None) -> int:
    cfg = cargar_generacion().medicion
    parser = argparse.ArgumentParser(description="Latencia de la generación (E1-12)")
    parser.add_argument("--proveedor", choices=["ollama", "deepseek"], help="sobrescribe LLM_PROVIDER de local.env")
    parser.add_argument("--ficha-json", type=Path, default=FICHA_POR_DEFECTO)
    parser.add_argument("--repeticiones", type=int, default=cfg.repeticiones)
    parser.add_argument("--calentamiento", type=int, default=cfg.calentamiento)
    args = parser.parse_args(argv)
    configurar_logging(logging.WARNING)
    env = dict(leer_local_env())
    if args.proveedor:
        env["LLM_PROVIDER"] = args.proveedor
    try:
        proveedor = crear_proveedor(env)
    except ErrorProveedor as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    ficha = EntradaFicha.model_validate_json(args.ficha_json.read_text(encoding="utf-8"))
    for _ in range(args.calentamiento):
        una_repeticion(ficha, proveedor)
    medidas = [una_repeticion(ficha, proveedor) for _ in range(args.repeticiones)]
    p = cfg.percentil
    salida: dict[str, Any] = {
        "proveedor": proveedor.nombre,
        "modelo": proveedor.modelo,
        "ficha": str(args.ficha_json.relative_to(RAIZ)) if args.ficha_json.is_relative_to(RAIZ) else args.ficha_json.name,
        "repeticiones": args.repeticiones,
        "calentamiento": args.calentamiento,
        "primera_respuesta": resumen([m["primera_respuesta_s"] for m in medidas], p),
        "paquete_completo": resumen([m["paquete_completo_s"] for m in medidas], p),
        "tokens_por_paquete": {"entrada": statistics.median(m["tokens_entrada"] for m in medidas), "salida": statistics.median(m["tokens_salida"] for m in medidas)},
        "llamadas_por_paquete": [m["llamadas"] for m in medidas],
        "secciones_vacias_por_repeticion": [m["secciones_vacias"] for m in medidas],
        "secciones_recortadas_por_repeticion": [m["secciones_recortadas"] for m in medidas],
        "afirmaciones_validas_por_repeticion": [m["afirmaciones_validas"] for m in medidas],
    }
    registro = getattr(proveedor, "registro", None)
    if registro is not None:
        salida["costo_acumulado"] = {"tokens": registro.tokens, "usd": round(registro.usd, 6)}
    SALIDA.mkdir(exist_ok=True)
    ruta = SALIDA / f"latencia_generacion_{proveedor.nombre}.json"
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(salida, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
