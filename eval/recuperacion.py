"""Evaluación de la consulta (E1-11): Recall@5 y abstención, búsqueda semántica vs. BM25, con n e IC (D-66).

Sobre el benchmark de **desarrollo** (``benchmark/benchmark_dev.jsonl``, 40 consultas aprobadas por una persona):

* **Recall@5** de los ``ids_evidencia`` esperados en las consultas ``respuesta_sustentada``: por IDs (micro: IDs hallados /
  IDs esperados, con IC de Wilson) y por consulta (macro). Tres filas: ``bm25`` y ``semantica`` buscan en todo el
  corpus (titulares útiles, indicadores y sismos) con el mismo índice; ``sistema`` es la búsqueda semántica más la
  consulta exacta de cifras oficiales (país, indicador, año) que usa la consulta real.
* **Abstención** de cada método (reglas previas + umbral de similitud de su método): ``sin_respuesta`` rechazadas / 7
  (la métrica del protocolo, meta ≥ 80 %), todas las que ``debe_abstenerse`` y las abstenciones incorrectas
  (respondibles rechazadas).

**Calibración y evaluación.** El umbral de similitud se calibra con una regla fija (percentil de la similitud máxima de
las consultas respondibles de la mitad de calibración) y se evalúa en la otra mitad: la división es determinista por la
paridad del número del id (``config/consulta.yaml``). Con n = 40 las mitades son de 20 y los IC son muy anchos: se
reportan las dos mitades y el total, y el total NO es independiente (el umbral y las reglas por patrón se escribieron
viendo estas mismas consultas). Nunca se lee ni se menciona el conjunto reservado del jurado.

Uso: ``poetry run python -m eval.recuperacion [--calibrar] [--salida outputs/recuperacion.json]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

from src.carga import intervalo_wilson
from src.configuracion import RAIZ, ConfigConsulta, cargar_carga, cargar_consulta
from src.consulta import METODOS, RUTA_SINTETICOS, Consultor, crear_consultor

logger = logging.getLogger(__name__)

BENCHMARK_DEV = RAIZ / "benchmark" / "benchmark_dev.jsonl"
SALIDA = RAIZ / "outputs" / "recuperacion.json"
DECIMALES = 4          # solo presentación
DECIMALES_UMBRAL = 3   # el umbral se trunca (no se redondea hacia arriba) a este número de decimales
MITADES = ("calibracion", "evaluacion")


def leer_benchmark(ruta: Path = BENCHMARK_DEV) -> list[dict[str, Any]]:
    """Las consultas del benchmark, una por línea JSON."""
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines() if linea.strip()]


def mitad_de(id_consulta: str, cfg: ConfigConsulta) -> str:
    """``calibracion`` o ``evaluacion`` según la paridad del número del id (``BDEV-NNN``): determinista y sin azar."""
    numero = int(re.search(r"(\d+)$", id_consulta).group(1))  # type: ignore[union-attr]
    par = numero % 2 == 0
    return "calibracion" if par == (cfg.evaluacion.calibracion == "pares") else "evaluacion"


def proporcion(k: int, n: int, z: float) -> dict[str, Any]:
    """``k`` de ``n`` con IC de Wilson al 95 % (``None`` si ``n`` es 0)."""
    ic = intervalo_wilson(k, n, z)
    return {
        "n": k, "de": n, "proporcion": None if n == 0 else round(k / n, DECIMALES),
        "ic95": None if ic is None else [round(ic[0], DECIMALES), round(ic[1], DECIMALES)],
    }


def truncar(valor: float, decimales: int = DECIMALES_UMBRAL) -> float:
    """Hacia abajo: así el umbral nunca queda por encima del percentil calibrado."""
    f = 10**decimales
    return math.floor(valor * f) / f


# ------------------------------------------------------------------ calibración


def similitudes_maximas(consultor: Consultor, consultas: list[dict[str, Any]], metodo: str) -> dict[str, float]:
    """Similitud máxima de cada consulta con el corpus (sobre la consulta ya saneada)."""
    salida = {}
    for c in consultas:
        an = consultor.decidir_previa(c["consulta"])[0]
        salida[c["id"]] = consultor.indice.buscar(an.limpia, metodo, 1)[0].puntaje
    return salida


def llega_a_la_similitud(consultor: Consultor, consulta: str) -> bool:
    """``True`` si la consulta pasa las reglas previas y no se resuelve con una cifra oficial exacta: solo esas
    atraviesan el umbral de similitud, así que solo ellas lo calibran."""
    _, previa, oficial = consultor.decidir_previa(consulta)
    return previa is None and not (oficial and oficial.registros)


def calibrar(consultor: Consultor, consultas: list[dict[str, Any]]) -> dict[str, Any]:
    """Umbral por método = percentil ``percentil_umbral`` de la similitud máxima de las consultas respondibles de la
    mitad de calibración que llegan a la puerta de similitud (las de cifra oficial exacta no la cruzan)."""
    cfg = consultor.cfg
    base = [
        c for c in consultas
        if c["tipo"] in cfg.evaluacion.tipos_con_respuesta and mitad_de(c["id"], cfg) == "calibracion"
        and llega_a_la_similitud(consultor, c["consulta"])
    ]
    salida: dict[str, Any] = {"n_calibracion": len(base), "ids": [c["id"] for c in base],
                              "percentil": cfg.abstencion.percentil_umbral, "umbrales": {}}
    for metodo in METODOS:
        sims = similitudes_maximas(consultor, base, metodo)
        valores = np.array(list(sims.values()))
        salida["umbrales"][metodo] = {
            "umbral": truncar(float(np.percentile(valores, cfg.abstencion.percentil_umbral))),
            "minimo": round(float(valores.min()), DECIMALES), "mediana": round(float(np.median(valores)), DECIMALES),
        }
    return salida


# ------------------------------------------------------------------ evaluación


def ids_recuperados(consultor: Consultor, consulta: str, metodo: str) -> list[str]:
    """Los IDs del top-k del método sobre el corpus completo, sin resolutor de cifras."""
    an = consultor.decidir_previa(consulta)[0]
    return [r.documento.id for r in consultor.indice.buscar(an.limpia, metodo)]


def ids_del_sistema(consultor: Consultor, consulta: str) -> list[str]:
    """Top-k del sistema: primero los registros exactos de la cifra oficial pedida y luego la búsqueda semántica."""
    an, _, oficial = consultor.decidir_previa(consulta)
    k = consultor.cfg.recuperacion.top_k
    exactos = [d.id for d in oficial.registros] if oficial and oficial.registros else []
    resto = [r.documento.id for r in consultor.indice.buscar(an.limpia, "semantica")]
    return list(dict.fromkeys([*exactos, *resto]))[:k]


def recall(esperados: dict[str, list[str]], hallados: dict[str, list[str]], z: float, k: int) -> dict[str, Any]:
    """Recall@k por IDs (micro, con Wilson) y por consulta (macro), con los fallos listados.

    ``por_ids_acotado`` usa como denominador ``min(k, IDs esperados)`` de cada consulta: una consulta con más de ``k`` IDs
    esperados (por ejemplo «cuáles son los N medios que replicaron…») no puede pasar de ``k`` aciertos en el top-k.
    """
    k_ok = n_tot = k_acotado = 0
    por_consulta: dict[str, float] = {}
    fallos: dict[str, list[str]] = {}
    for cid, exp in esperados.items():
        halladas = set(exp) & set(hallados[cid])
        k_ok += len(halladas)
        n_tot += len(exp)
        k_acotado += min(k, len(exp))
        por_consulta[cid] = len(halladas) / len(exp)
        if len(halladas) < len(exp):
            fallos[cid] = sorted(set(exp) - halladas)
    completas = sum(1 for v in por_consulta.values() if v == 1.0)
    return {
        "por_ids": proporcion(k_ok, n_tot, z),
        "por_ids_acotado": proporcion(k_ok, k_acotado, z),
        "consultas_completas": proporcion(completas, len(por_consulta), z),
        "macro_recall": None if not por_consulta else round(sum(por_consulta.values()) / len(por_consulta), DECIMALES),
        "fallos": fallos,
    }


def evaluar_recuperacion(consultor: Consultor, consultas: list[dict[str, Any]], z: float) -> dict[str, Any]:
    cfg = consultor.cfg
    base = [c for c in consultas if c["tipo"] in cfg.evaluacion.tipos_recuperacion and c["ids_evidencia"]]
    salida: dict[str, Any] = {"k": cfg.recuperacion.top_k, "n_consultas": len(base), "filas": {}}
    metodos = {m: {c["id"]: ids_recuperados(consultor, c["consulta"], m) for c in base} for m in METODOS}
    metodos["sistema"] = {c["id"]: ids_del_sistema(consultor, c["consulta"]) for c in base}
    for nombre, hallados in metodos.items():
        fila: dict[str, Any] = {"total": recall({c["id"]: c["ids_evidencia"] for c in base}, hallados, z, salida["k"])}
        for etiqueta, prefijos in (("titulares", ("NOT-", "SYN-")), ("oficiales", ("IND-", "SIS-"))):
            esp = {c["id"]: [i for i in c["ids_evidencia"] if i.startswith(prefijos)] for c in base}
            esp = {k: v for k, v in esp.items() if v}
            fila[etiqueta] = recall(esp, hallados, z, salida["k"])
        salida["filas"][nombre] = fila
    return salida


def evaluar_abstencion(consultor: Consultor, consultas: list[dict[str, Any]], metodo: str, z: float) -> dict[str, Any]:
    """Abstención de un método por mitad (calibración / evaluación / total): correctas, incorrectas y los fallos."""
    cfg = consultor.cfg
    respuestas = {c["id"]: consultor.responder(c["consulta"], metodo) for c in consultas}
    salida: dict[str, Any] = {"metodo": metodo, "umbral": cfg.abstencion.umbral_similitud[metodo], "por_mitad": {}}
    for mitad in (*MITADES, "total"):
        sel = [c for c in consultas if mitad == "total" or mitad_de(c["id"], cfg) == mitad]

        def contar(pred: Any, abstiene: bool, sel: list[dict[str, Any]] = sel) -> dict[str, Any]:
            grupo = [c for c in sel if pred(c)]
            mal = [c["id"] for c in grupo if respuestas[c["id"]].abstiene != abstiene]
            return {**proporcion(len(grupo) - len(mal), len(grupo), z), "fallos": mal}

        salida["por_mitad"][mitad] = {
            "abstencion_correcta_sin_respuesta": contar(lambda c: c["tipo"] == "sin_respuesta", True),
            "abstencion_correcta_todas": contar(lambda c: c["debe_abstenerse"], True),
            "abstencion_incorrecta_sustentada": _incorrecta(sel, respuestas, z, lambda c: c["tipo"] == "respuesta_sustentada"),
            "abstencion_incorrecta_todas": _incorrecta(sel, respuestas, z, lambda c: not c["debe_abstenerse"]),
        }
    salida["motivos"] = _motivos(respuestas)
    # Ablación: lo que rechazaría el umbral de similitud SOLO, sin las reglas previas (la parte que no depende de patrones).
    sin = [c for c in consultas if c["tipo"] == "sin_respuesta"]
    sims = similitudes_maximas(consultor, sin, metodo)
    bajo = [c["id"] for c in sin if sims[c["id"]] < cfg.abstencion.umbral_similitud[metodo]]
    salida["solo_umbral_sin_respuesta"] = {**proporcion(len(bajo), len(sin), z), "ids": bajo}
    return salida


def _incorrecta(sel: list[dict[str, Any]], respuestas: dict[str, Any], z: float, pred: Any) -> dict[str, Any]:
    grupo = [c for c in sel if pred(c)]
    mal = [c["id"] for c in grupo if respuestas[c["id"]].abstiene]
    return {**proporcion(len(mal), len(grupo), z), "ids": mal}


def _motivos(respuestas: dict[str, Any]) -> dict[str, list[str]]:
    motivos: dict[str, list[str]] = {}
    for cid, r in respuestas.items():
        motivos.setdefault(r.motivo, []).append(cid)
    return {k: sorted(v) for k, v in sorted(motivos.items())}


def evaluar(consultor: Consultor, consultas: list[dict[str, Any]], z: float) -> dict[str, Any]:
    cfg = consultor.cfg
    return {
        "benchmark": "benchmark/benchmark_dev.jsonl", "n_consultas": len(consultas),
        "division": {
            "regla": f"{cfg.evaluacion.calibracion} calibran, el resto evalúa (paridad del número del id)",
            **{m: sum(1 for c in consultas if mitad_de(c["id"], cfg) == m) for m in MITADES},
        },
        "recuperacion": evaluar_recuperacion(consultor, consultas, z),
        "abstencion": {m: evaluar_abstencion(consultor, consultas, m, z) for m in METODOS},
        "umbrales_de_config": dict(cfg.abstencion.umbral_similitud),
        "aviso": ("El umbral se calibra con la mitad de calibración y se evalúa en la otra; las reglas por patrón se "
                  "escribieron viendo las 40 consultas, así que 'total' es optimista y no independiente."),
    }


# ------------------------------------------------------------------ presentación


def _fmt(p: dict[str, Any]) -> str:
    return f"{p['n']}/{p['de']} = {p['proporcion']} IC95 {p['ic95']}"


def imprimir(res: dict[str, Any]) -> None:
    r = res["recuperacion"]
    print(f"== Recall@{r['k']} (n = {r['n_consultas']} consultas respuesta_sustentada, IDs esperados no vacíos) ==")
    for nombre, fila in r["filas"].items():
        print(f"  {nombre:9} IDs {_fmt(fila['total']['por_ids'])} · acotado {_fmt(fila['total']['por_ids_acotado'])} · consultas completas {_fmt(fila['total']['consultas_completas'])}"
              f" · macro {fila['total']['macro_recall']}")
        for etiqueta in ("titulares", "oficiales"):
            print(f"      {etiqueta:9} IDs {_fmt(fila[etiqueta]['por_ids'])}")
        if fila["total"]["fallos"]:
            print(f"      fallos: {fila['total']['fallos']}")
    print(f"\n== Abstención ({res['division']['regla']}; umbrales {res['umbrales_de_config']}) ==")
    for metodo, a in res["abstencion"].items():
        print(f"  {metodo} (umbral {a['umbral']})")
        for mitad, m in a["por_mitad"].items():
            print(f"    {mitad:12} sin_respuesta rechazadas {_fmt(m['abstencion_correcta_sin_respuesta'])} fallos {m['abstencion_correcta_sin_respuesta']['fallos']}")
            print(f"    {'':12} todas las que debían rechazarse {_fmt(m['abstencion_correcta_todas'])} fallos {m['abstencion_correcta_todas']['fallos']}")
            print(f"    {'':12} abstenciones incorrectas: sustentadas {_fmt(m['abstencion_incorrecta_sustentada'])} {m['abstencion_incorrecta_sustentada']['ids']}"
                  f" · respondibles {_fmt(m['abstencion_incorrecta_todas'])}")
        print(f"    motivos: {a['motivos']}")
        print(f"    solo el umbral (sin reglas previas) rechaza {_fmt(a['solo_umbral_sin_respuesta'])} {a['solo_umbral_sin_respuesta']['ids']}")
    print(f"\nAviso: {res['aviso']}")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m eval.recuperacion``."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="E1-11: Recall@5 y abstención, semántica vs. BM25")
    parser.add_argument("--benchmark", type=Path, default=BENCHMARK_DEV)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    parser.add_argument("--calibrar", action="store_true", help="solo calcula los umbrales de la mitad de calibración")
    args = parser.parse_args(argv)
    consultas = leer_benchmark(args.benchmark)
    try:
        # Los casos alterados del benchmark (SYN-) viven en su fixture, solo para evaluar: nunca en la base ni en el demo.
        consultor = crear_consultor(sinteticos=RUTA_SINTETICOS)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    z = cargar_carga().salida.z_intervalo_confianza
    if args.calibrar:
        cal = calibrar(consultor, consultas)
        print(json.dumps(cal, ensure_ascii=False, indent=2))
        return 0
    res = evaluar(consultor, consultas, z)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    imprimir(res)
    print(f"\nEscrito: {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
