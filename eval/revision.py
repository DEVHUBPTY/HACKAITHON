"""Métricas de la revisión humana (E1-16): tasas de aceptación, corrección y descarte, motivos, tiempo y % de afirmaciones editadas.

Todo sale de la tabla ``revisiones`` (de solo agregar) y de ``versiones``; nada se inventa. **Hoy casi no hay datos reales**: las
revisiones las hace una persona durante el evento (etapa 7, docs/REVISION.md). Con ``n = 0`` cada métrica dice «sin datos» y no
lleva cifra ni intervalo. La demo (``data/revision_demo.duckdb``) y las bases de prueba nunca entran aquí.

* **Caso decidido:** el que terminó «aprobado como borrador» o «descartado» (su última fila). Las tres tasas se calculan sobre los
  casos decididos: aceptación = aprobados / decididos; descarte = descartados / decididos; corrección = decididos con al menos una
  corrección / decididos. Cada proporción lleva su ``n`` y su intervalo de Wilson del 95 % (z de ``config/carga.yaml``).
* **Tiempo de revisión por caso:** minutos entre la fila ``abrir`` y la última decisión (aprobar o descartar), en los casos decididos.
  Es tiempo de reloj entre registros, no esfuerzo: la persona puede haber dejado el caso abierto.
* **% de afirmaciones editadas:** afirmaciones distintas corregidas / afirmaciones del primer borrador de los casos decididos con
  borrador. Las afirmaciones de un mismo caso no son independientes: el intervalo es orientativo y se declara así.
* **Motivos de descarte:** conteo por motivo de la lista de ``config/revision.yaml``.
* **Descartes administrativos (X107):** los de ``motivos_administrativos`` (el reemplazo de D-118) no son un juicio editorial: no entran a
  ninguna tasa ni a los casos decididos y se cuentan aparte en ``descartes_administrativos``.

Uso: ``poetry run python -m eval.revision [--revision data/revision.duckdb] [--salida outputs/revision.json]``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from src.carga import intervalo_wilson
from eval import origen_juicio
from src.configuracion import RAIZ, cargar_carga, cargar_origen_juicio, cargar_revision
from src.revision import FORMATO_FECHA, Revisiones

SALIDA = RAIZ / "outputs" / "revision.json"
DECIMALES = 4          # solo presentación
ESTADOS_FINALES = ("aprobado como borrador", "descartado")
SEGUNDOS_POR_MINUTO = 60.0


def _proporcion(k: int, n: int, z: float) -> dict[str, Any]:
    ic = intervalo_wilson(k, n, z)
    return {"k": k, "n": n, "proporcion": (k / n) if n else None, "ic95": [ic[0], ic[1]] if ic else None}


def _minutos(desde: str, hasta: str) -> float:
    a, b = datetime.strptime(desde, FORMATO_FECHA), datetime.strptime(hasta, FORMATO_FECHA)
    return (b - a).total_seconds() / SEGUNDOS_POR_MINUTO


def _metricas(rev: Revisiones, ids: list[str], z: float) -> dict[str, Any]:
    """Las tasas, motivos, tiempos y afirmaciones editadas de los casos decididos ``ids`` (todos con la misma procedencia)."""
    prefijo = f"{rev.cfg.correccion.prefijo_afirmaciones}."
    descartados: Counter[str] = Counter()
    corregidos = 0
    editadas = total_afirmaciones = 0
    tiempos: list[float] = []
    aprobados = 0
    for id_caso in ids:
        historial = rev.historial(id_caso)
        if historial[-1].estado_nuevo == "descartado":
            descartados[historial[-1].motivo or "sin motivo"] += 1
        else:
            aprobados += 1
        correcciones = [f for f in historial if f.accion == "corregir"]
        corregidos += bool(correcciones)
        versiones = rev.versiones(id_caso)
        if versiones:
            total_afirmaciones += len(versiones[0].contenido.get("afirmaciones") or [])
            editadas += len({x["clave"] for f in correcciones for x in f.diferencias if x["clave"].startswith(prefijo)})
        apertura = next(f for f in historial if f.accion == "abrir")
        tiempos.append(_minutos(apertura.fecha_utc, historial[-1].fecha_utc))
    n = len(ids)
    return {
        "casos_decididos": n,
        "tasas": {
            "aceptacion": _proporcion(aprobados, n, z),
            "correccion": _proporcion(corregidos, n, z),
            "descarte": _proporcion(n - aprobados, n, z),
        },
        "motivos_descarte": dict(descartados.most_common()),
        "tiempo_por_caso_min": {
            "n": len(tiempos),
            "mediana": statistics.median(tiempos) if tiempos else None,
            "media": statistics.fmean(tiempos) if tiempos else None,
        },
        "afirmaciones_editadas": _proporcion(editadas, total_afirmaciones, z),
    }


def calcular(rev: Revisiones) -> dict[str, Any]:
    """Las métricas de la revisión, separadas por quién decidió (X71, D-101/D-112).

    El resultado principal cuenta **solo** los casos cuya decisión vigente la tomó una persona (``juicio_humano: true``). Los casos que
    decidió un revisor provisional (el asistente) nunca se mezclan: van aparte en ``provisionales``, con su propio n e intervalo, con
    ``juicio_humano: false`` y el aviso de ``config/origen_juicio.yaml``. «Decidió» es el revisor de la última fila del caso.
    """
    z = cargar_carga().salida.z_intervalo_confianza
    cfg_origen = cargar_origen_juicio()
    casos = rev.casos()
    humanos: list[str] = []
    provisionales: list[str] = []
    administrativos: Counter[str] = Counter()
    for caso in casos:
        historial = rev.historial(caso.id_caso)
        if not historial or historial[-1].estado_nuevo not in ESTADOS_FINALES:
            continue
        if historial[-1].estado_nuevo == "descartado" and historial[-1].motivo in rev.cfg.motivos_administrativos:
            administrativos[historial[-1].motivo] += 1       # X107: no es un juicio editorial: se cuenta aparte y no entra a ninguna tasa
            continue
        (provisionales if rev.es_provisional(historial[-1].revisor, caso.modalidad) else humanos).append(caso.id_caso)
    resultado: dict[str, Any] = {
        "casos_abiertos": len(casos),
        **origen_juicio.describir(cfg_origen.humano, cfg_origen),
        **_metricas(rev, humanos, z),
        "casos_decididos_provisionales": len(provisionales),
        "descartes_administrativos": {"n": sum(administrativos.values()), "motivos": dict(administrativos.most_common()), "nota": "Descartes administrativos (no son un juicio editorial): fuera de todas las tasas."},
        "nota": "Las afirmaciones de un caso no son independientes: el intervalo de afirmaciones editadas es orientativo.",
    }
    if provisionales:
        no_humano = next(k for k in cfg_origen.origenes if k != cfg_origen.humano)
        resultado["provisionales"] = {
            **origen_juicio.describir(no_humano, cfg_origen),
            "aviso_origen": cfg_origen.aviso_provisional,
            **_metricas(rev, provisionales, z),
        }
    return resultado


def _texto(p: dict[str, Any], sin_datos: str) -> str:
    if not p["n"]:
        return f"{sin_datos} (n = 0)"
    lo, hi = p["ic95"]
    return f"{p['proporcion']:.1%} ({p['k']}/{p['n']}, n = {p['n']}, IC 95 % {lo:.1%}–{hi:.1%})"


def _bloque(r: dict[str, Any], sd: str, titulo: str) -> list[str]:
    t = r["tiempo_por_caso_min"]
    return [
        titulo,
        f"  Tasa de aceptación (aprobados como borrador): {_texto(r['tasas']['aceptacion'], sd)}",
        f"  Tasa de corrección (con al menos una corrección): {_texto(r['tasas']['correccion'], sd)}",
        f"  Tasa de descarte: {_texto(r['tasas']['descarte'], sd)}",
        f"  Afirmaciones editadas: {_texto(r['afirmaciones_editadas'], sd)}",
        "  Tiempo de revisión por caso: " + (f"mediana {t['mediana']:.1f} min · media {t['media']:.1f} min (n = {t['n']})" if t["n"] else f"{sd} (n = 0)"),
        "  Motivos de descarte: " + (" · ".join(f"{m} ({n})" for m, n in r["motivos_descarte"].items()) or sd),
    ]


def formatear(r: dict[str, Any], sin_datos: str | None = None) -> str:
    """El reporte como texto: cada proporción con su n e intervalo; sin casos, «sin datos». Lo provisional va aparte y rotulado (X71)."""
    sd = sin_datos or cargar_revision().textos.sin_datos
    lineas = _bloque(r, sd, f"Revisión humana · casos abiertos: {r['casos_abiertos']} · decididos por una persona: {r['casos_decididos']}")
    lineas.append(f"  {r['nota']}")
    adm = r.get("descartes_administrativos")
    if adm and adm["n"]:
        lineas.append(f"  Descartes administrativos (fuera de las tasas): {adm['n']} · " + " · ".join(f"{m} ({n})" for m, n in adm["motivos"].items()))
    if r.get("provisionales"):
        p = r["provisionales"]
        lineas += ["", *_bloque(p, sd, f"Revisión PROVISIONAL del asistente (no es juicio humano) · decididos: {p['casos_decididos']}"), f"  {p['aviso_origen']}"]
    return "\n".join(lineas)


def principal(argv: list[str] | None = None) -> int:
    cfg = cargar_revision()
    parser = argparse.ArgumentParser(description="E1-16: métricas de la revisión humana")
    parser.add_argument("--revision", type=Path, default=RAIZ / cfg.almacen.base)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    r = calcular(Revisiones(args.revision, None, cfg))
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(formatear(r, cfg.textos.sin_datos))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
