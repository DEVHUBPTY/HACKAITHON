"""Prueba de un modelo local de Ollama contra titulares reales (E0-07, criterio D-02).

Uso: ``poetry run python -m scripts.probar_llm --modelo <tag> [--repeticiones N]``

Mide por llamada: latencia de pared, validez del JSON (parseable + esquema pydantic) y si las
citas apuntan a IDs y campos que existen en la evidencia entregada. Reporta además la memoria
(``/api/ps``), el tag exacto, el digest y la versión de Ollama. Guarda el detalle en
``outputs/probar_llm_<tag>.json`` (sin secretos).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
import time
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from src.configuracion import RAIZ, ConfigLlm, cargar_llm, leer_local_env
from src.esquemas import AfirmacionesCitadas, esquema_json_afirmaciones
from src.llm.ollama import ClienteOllama, ErrorOllama
from src.registro import configurar_logging

log = logging.getLogger("probar_llm")

CAMPOS_EVIDENCIA = ("titulo", "medio", "fecha_publicacion", "fecha_deteccion")
CARPETA_PROMPTS = RAIZ / "prompts"
CARPETA_SALIDAS = RAIZ / "outputs"


# ------------------------------------------------------------------ selección y evidencia


def seleccionar_titulares(noticias: pd.DataFrame, cfg: ConfigLlm) -> list[dict[str, Any]]:
    """Selección determinista: del medio e idioma configurados, los ``n`` id más bajos por tema."""
    m = cfg.prueba.muestra
    base = noticias[(noticias["medio"] == m.medio) & (noticias["idioma"] == m.idioma)]
    elegidos: list[dict[str, Any]] = []
    for tema, cantidad in m.titulares_por_tema.items():
        filas = base[base["tema"] == tema].sort_values("id_noticia").head(cantidad)
        if len(filas) < cantidad:
            raise ValueError(f"tema {tema!r}: hay {len(filas)} titulares y se piden {cantidad}")
        elegidos.extend(filas.to_dict("records"))
    return elegidos


def construir_evidencia(fila: dict[str, Any]) -> tuple[str, str, set[str]]:
    """Devuelve (id, texto del mensaje de usuario, campos citables). Los nulos se omiten."""
    id_registro = str(fila["id_noticia"])
    campos: dict[str, str] = {}
    for campo in CAMPOS_EVIDENCIA:
        valor = fila.get(campo)
        if valor is None or (isinstance(valor, float) and math.isnan(valor)) or str(valor) == "":
            continue
        # La evidencia es dato: se neutraliza cualquier cierre de la etiqueta delimitadora.
        campos[campo] = str(valor).replace("</evidencia>", "")
    lineas = "\n".join(f"  {campo}: {valor}" for campo, valor in campos.items())
    texto = (
        "<evidencia>\n"
        f"[{id_registro}]\n{lineas}\n"
        "</evidencia>\n\n"
        "Produce las afirmaciones citadas sobre esta evidencia."
    )
    return id_registro, texto, set(campos)


def cargar_system(nombre: str) -> str:
    """Prompt de sistema con el JSON Schema incrustado (recomendación de Ollama)."""
    plantilla = (CARPETA_PROMPTS / f"{nombre}.txt").read_text(encoding="utf-8")
    esquema = json.dumps(esquema_json_afirmaciones(), ensure_ascii=False)
    return plantilla.replace("{esquema}", esquema)


# ------------------------------------------------------------------ evaluación de una salida


def evaluar_salida(contenido: str, id_registro: str, campos: set[str]) -> dict[str, Any]:
    """Valida una salida: JSON parseable, esquema pydantic y citas contra la evidencia entregada."""
    res: dict[str, Any] = {
        "json_parseable": False,
        "esquema_valido": False,
        "citas_validas": None,
        "bases_validas": None,
        "hecho_sobre_titular": None,
        "error": None,
    }
    try:
        datos = json.loads(contenido)
        res["json_parseable"] = True
    except (json.JSONDecodeError, TypeError) as exc:
        res["error"] = f"JSON no parseable: {exc}"
        return res
    try:
        salida = AfirmacionesCitadas.model_validate(datos)
        res["esquema_valido"] = True
    except ValidationError as exc:
        res["error"] = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]
        )
        return res
    citas = [c for a in salida.afirmaciones for c in a.citas]
    res["citas_validas"] = all(c.id == id_registro and c.campo in campos for c in citas)
    ids = {a.id for a in salida.afirmaciones}
    res["bases_validas"] = all(b in ids for a in salida.afirmaciones for b in a.base)
    # Un titular es una declaración, no un hecho (CLAUDE.md): aquí no hay datos oficiales ni conteos.
    res["hecho_sobre_titular"] = any(a.tipo == "hecho" for a in salida.afirmaciones)
    return res


# ------------------------------------------------------------------ estadística


def percentil(valores: list[float], p: float) -> float:
    """Percentil ``p`` (0-100) por interpolación lineal (igual que numpy por defecto)."""
    if not valores:
        raise ValueError("sin valores")
    orden = sorted(valores)
    pos = (len(orden) - 1) * p / 100
    bajo, alto = math.floor(pos), math.ceil(pos)
    return orden[bajo] + (orden[alto] - orden[bajo]) * (pos - bajo)


def intervalo_wilson(exitos: int, n: int, confianza: float = 0.95) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción."""
    if n == 0:
        return (0.0, 1.0)
    z = statistics.NormalDist().inv_cdf(1 - (1 - confianza) / 2)
    p = exitos / n
    den = 1 + z**2 / n
    centro = (p + z**2 / (2 * n)) / den
    mitad = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return (max(0.0, centro - mitad), min(1.0, centro + mitad))


def resumir(llamadas: list[dict[str, Any]], cfg: ConfigLlm) -> dict[str, Any]:
    """Resumen de las llamadas medidas (sin calentamiento) y evaluación del criterio D-02."""
    n = len(llamadas)
    validas = sum(1 for c in llamadas if c["evaluacion"]["esquema_valido"])
    parseables = sum(1 for c in llamadas if c["evaluacion"]["json_parseable"])
    con_citas = [c for c in llamadas if c["evaluacion"]["esquema_valido"]]
    citas_ok = sum(1 for c in con_citas if c["evaluacion"]["citas_validas"])
    lat = [c["latencia_s"] for c in llamadas]
    conf = cfg.prueba.confianza
    lo, hi = intervalo_wilson(validas, n, conf)
    invalidos_por_diez = (n - validas) / n * 10 if n else float("nan")
    mediana = statistics.median(lat) if lat else float("nan")
    crit = cfg.criterio_d02
    return {
        "n_llamadas": n,
        "json_valido": {"k": validas, "n": n, "pct": 100 * validas / n if n else None,
                        "ic_inf_pct": 100 * lo, "ic_sup_pct": 100 * hi, "confianza": conf,
                        "metodo_ic": "Wilson"},
        "json_parseable_k": parseables,
        "citas_validas": {"k": citas_ok, "n": len(con_citas)},
        "latencia_s": {"mediana": mediana, "p95": percentil(lat, 95) if lat else None,
                       "min": min(lat) if lat else None, "max": max(lat) if lat else None},
        "criterio_d02": {
            "mediana_ok": mediana <= crit.mediana_max_segundos,
            "invalidos_por_diez": invalidos_por_diez,
            "invalidos_ok": invalidos_por_diez <= crit.invalidos_max_por_diez,
            "cumple": mediana <= crit.mediana_max_segundos
            and invalidos_por_diez <= crit.invalidos_max_por_diez,
        },
    }


# ------------------------------------------------------------------ ejecución


def memoria_modelo(cliente: ClienteOllama, modelo: str) -> dict[str, Any] | None:
    """Tamaño en memoria del modelo cargado, según ``/api/ps`` (bytes)."""
    for m in cliente.cargados():
        if m.get("name") == modelo or m.get("model") == modelo:
            return {"size": m.get("size"), "size_vram": m.get("size_vram"),
                    "context_length": m.get("context_length")}
    return None


def una_llamada(
    cliente: ClienteOllama, modelo: str, system: str, esquema: dict[str, Any], cfg: ConfigLlm,
    num_ctx: int, titular: dict[str, Any],
) -> dict[str, Any]:
    id_registro, usuario, campos = construir_evidencia(titular)
    g = cfg.generacion
    opciones = {"temperature": g.temperatura, "seed": g.semilla, "num_ctx": num_ctx,
                "num_predict": g.num_predict}
    inicio = time.perf_counter()
    try:
        resp = cliente.chat(modelo, system, usuario, esquema, opciones, g.pensar,
                            cfg.ollama.keep_alive_durante_prueba)
        latencia = time.perf_counter() - inicio
        msg = resp.get("message", {})
        contenido = msg.get("content", "")
        ev = evaluar_salida(contenido, id_registro, campos)
        extra = {
            "respuesta_cruda": contenido,
            "pensamiento_presente": bool(msg.get("thinking")),
            "done_reason": resp.get("done_reason"),
            "eval_count": resp.get("eval_count"),
            "prompt_eval_count": resp.get("prompt_eval_count"),
            "load_duration_s": (resp.get("load_duration") or 0) / 1e9,
            "total_duration_s": (resp.get("total_duration") or 0) / 1e9,
        }
    except ErrorOllama as exc:
        latencia = time.perf_counter() - inicio
        ev = {"json_parseable": False, "esquema_valido": False, "citas_validas": None,
              "bases_validas": None, "hecho_sobre_titular": None, "error": str(exc)}
        extra = {"respuesta_cruda": None}
    return {"id_noticia": id_registro, "latencia_s": latencia, "evaluacion": ev, **extra}


def ejecutar(
    cliente: ClienteOllama, modelo: str, cfg: ConfigLlm, noticias: pd.DataFrame,
    repeticiones: int, num_ctx: int,
) -> dict[str, Any]:
    """Corre calentamiento + ``repeticiones`` pasadas sobre los titulares y arma el resultado."""
    titulares = seleccionar_titulares(noticias, cfg)
    system = cargar_system(cfg.prueba.prompt)
    esquema = esquema_json_afirmaciones()
    log.info("Modelo %s · %d titulares × %d repeticiones · num_ctx=%d",
             modelo, len(titulares), repeticiones, num_ctx)

    calentamiento = []
    for i in range(cfg.prueba.calentamiento):
        c = una_llamada(cliente, modelo, system, esquema, cfg, num_ctx, titulares[i % len(titulares)])
        calentamiento.append(c)
        log.info("calentamiento %d: %.1f s (carga %.1f s)", i + 1, c["latencia_s"],
                 c.get("load_duration_s", 0.0))

    llamadas: list[dict[str, Any]] = []
    for r in range(repeticiones):
        for t in titulares:
            c = una_llamada(cliente, modelo, system, esquema, cfg, num_ctx, t)
            c["repeticion"] = r + 1
            llamadas.append(c)
            log.info("rep %d %s: %.1f s · válido=%s", r + 1, c["id_noticia"], c["latencia_s"],
                     c["evaluacion"]["esquema_valido"])

    memoria = memoria_modelo(cliente, modelo)
    return {
        "modelo": modelo,
        "digest": cliente.digest(modelo),
        "version_ollama": cliente.version(),
        "num_ctx": num_ctx,
        "parametros": cfg.generacion.model_dump(),
        "titulares": [t["id_noticia"] for t in titulares],
        "memoria_bytes": memoria,
        "calentamiento": calentamiento,
        "llamadas": llamadas,
        "resumen": resumir(llamadas, cfg),
    }


def imprimir_resumen(res: dict[str, Any]) -> None:
    r = res["resumen"]
    v, lat, d = r["json_valido"], r["latencia_s"], r["criterio_d02"]
    mem = res["memoria_bytes"] or {}
    gb = lambda b: f"{b / 1e9:.1f} GB" if b else "n/d"  # noqa: E731
    print(f"Modelo: {res['modelo']}  digest: {res['digest']}")
    print(f"Ollama: {res['version_ollama']}  num_ctx: {res['num_ctx']}")
    print(f"JSON válido: {v['k']}/{v['n']} = {v['pct']:.1f} %  "
          f"(IC 95 % Wilson {v['ic_inf_pct']:.1f}–{v['ic_sup_pct']:.1f} %)")
    print(f"Citas válidas (sobre salidas válidas): {r['citas_validas']['k']}/{r['citas_validas']['n']}")
    print(f"Latencia: mediana {lat['mediana']:.1f} s · p95 {lat['p95']:.1f} s "
          f"(mín {lat['min']:.1f}, máx {lat['max']:.1f})")
    print(f"Memoria: total {gb(mem.get('size'))} · VRAM/GPU {gb(mem.get('size_vram'))}")
    print(f"D-02: mediana ≤ umbral: {d['mediana_ok']} · inválidos {d['invalidos_por_diez']:.1f}/10 "
          f"(ok: {d['invalidos_ok']}) → cumple: {d['cumple']}")


def nombre_archivo(modelo: str, etiqueta: str | None) -> str:
    base = modelo.replace(":", "_").replace("/", "_")
    return f"probar_llm_{base}{'_' + etiqueta if etiqueta else ''}.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modelo", required=True, help="tag exacto de Ollama, ej. qwen3.5:9b")
    ap.add_argument("--repeticiones", type=int, default=None)
    ap.add_argument("--num-ctx", type=int, default=None, help="variante de optimización")
    ap.add_argument("--etiqueta", default=None, help="sufijo del archivo de resultados")
    args = ap.parse_args(argv)

    configurar_logging()
    cfg = cargar_llm()
    entorno = leer_local_env()
    host = entorno.get("OLLAMA_HOST") or cfg.ollama.host_por_defecto
    cliente = ClienteOllama(host, cfg.ollama.timeout_segundos)
    log.info("Ollama en %s (claves de local.env: %s)", cliente.host, sorted(entorno))

    noticias = pd.read_csv(RAIZ / "data" / "processed" / "noticias.csv")
    repeticiones = args.repeticiones or cfg.prueba.repeticiones
    num_ctx = args.num_ctx or cfg.generacion.num_ctx
    try:
        res = ejecutar(cliente, args.modelo, cfg, noticias, repeticiones, num_ctx)
    finally:
        try:
            cliente.descargar(args.modelo)
        except ErrorOllama as exc:
            log.warning("No se pudo descargar el modelo: %s", exc)

    CARPETA_SALIDAS.mkdir(exist_ok=True)
    destino = CARPETA_SALIDAS / nombre_archivo(args.modelo, args.etiqueta)
    destino.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    imprimir_resumen(res)
    print(f"Resultados: {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
