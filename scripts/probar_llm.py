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
import os
import re
import statistics
import subprocess
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
ETIQUETA_EVIDENCIA = re.compile(r"<\s*/?\s*evidencia\s*>", re.IGNORECASE)
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
        # La evidencia es dato: se neutraliza apertura y cierre de la etiqueta delimitadora,
        # sin distinguir mayúsculas ni espacios.
        campos[campo] = ETIQUETA_EVIDENCIA.sub("", str(valor))
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


def declaraciones_de(llamadas: list[dict[str, Any]]) -> list[str]:
    """Textos de las afirmaciones de tipo declaración en las salidas válidas por esquema."""
    textos: list[str] = []
    for c in llamadas:
        if not c["evaluacion"]["esquema_valido"] or not c.get("respuesta_cruda"):
            continue
        salida = AfirmacionesCitadas.model_validate_json(c["respuesta_cruda"])
        textos.extend(a.texto for a in salida.afirmaciones if a.tipo == "declaración")
    return textos


def sin_atribucion(textos: list[str], marcadores: list[str], medio: str) -> int:
    """Cuántos textos no contienen un verbo de reporte ni el nombre del medio."""
    claves = [m.lower() for m in marcadores] + [medio.lower()]
    return sum(1 for t in textos if not any(k in t.lower() for k in claves))


def salidas_distintas(llamadas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una llamada por cada salida distinta: con temperatura 0 las repeticiones son idénticas."""
    vistas: set[str] = set()
    unicas: list[dict[str, Any]] = []
    for c in llamadas:
        clave = c.get("respuesta_cruda") or f"error:{c['evaluacion'].get('error')}"
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(c)
    return unicas


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
    # n efectivo de la validez: salidas distintas (con temperatura 0 las repeticiones son idénticas).
    distintas = salidas_distintas(llamadas)
    nd = len(distintas)
    kd = sum(1 for c in distintas if c["evaluacion"]["esquema_valido"])
    lod, hid = intervalo_wilson(kd, nd, conf)
    invalidos_por_diez_d = (nd - kd) / nd * 10 if nd else float("nan")
    medio = cfg.prueba.muestra.medio
    decl_todas = declaraciones_de(llamadas)
    decl_distintas = declaraciones_de(distintas)
    marc = cfg.prueba.marcadores_atribucion
    return {
        "n_llamadas": n,
        "json_valido_distintas": {"k": kd, "n": nd, "pct": 100 * kd / nd if nd else None,
                                  "ic_inf_pct": 100 * lod, "ic_sup_pct": 100 * hid,
                                  "confianza": conf, "metodo_ic": "Wilson",
                                  "invalidos_por_diez": invalidos_por_diez_d,
                                  "invalidos_ok": invalidos_por_diez_d <= crit.invalidos_max_por_diez},
        "atribucion": {
            "declaraciones_llamadas": {"n": len(decl_todas),
                                       "sin_atribucion": sin_atribucion(decl_todas, marc, medio)},
            "declaraciones_distintas": {"n": len(decl_distintas),
                                        "sin_atribucion": sin_atribucion(decl_distintas, marc, medio)},
        },
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
            "invalidos_por_diez_distintas": invalidos_por_diez_d,
            "invalidos_ok": invalidos_por_diez_d <= crit.invalidos_max_por_diez,
            "cumple": mediana <= crit.mediana_max_segundos
            and invalidos_por_diez_d <= crit.invalidos_max_por_diez,
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


def rss_servidor_bytes(salida_ps: str | None = None) -> int | None:
    """RSS (bytes) del proceso que sirve el modelo (``llama-server`` / ``ollama runner``).

    ``/api/ps`` puede subcontar (modelos con parte mapeada a disco), así que se contrasta con el
    RSS del proceso. ``salida_ps`` permite inyectar la salida de ``ps -Ao rss,comm`` en pruebas.
    """
    if salida_ps is None:
        try:
            salida_ps = subprocess.run(
                ["ps", "-Ao", "rss,comm"], capture_output=True, text=True, timeout=10, check=True
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
    rss = [
        int(linea.split(None, 1)[0]) * 1024
        for linea in salida_ps.splitlines()[1:]
        if linea.split(None, 1)[0].isdigit()
        and ("llama-server" in linea or "ollama runner" in linea or "ollama_llama_server" in linea)
    ]
    return max(rss) if rss else None


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
    repeticiones: int, num_ctx: int, prompt: str | None = None,
) -> dict[str, Any]:
    """Corre calentamiento + ``repeticiones`` pasadas sobre los titulares y arma el resultado."""
    titulares = seleccionar_titulares(noticias, cfg)
    prompt = prompt or cfg.prueba.prompt
    system = cargar_system(prompt)
    carga_inicio = os.getloadavg()
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
        "prompt": prompt,
        "carga_sistema_1min": {"inicio": carga_inicio[0], "fin": os.getloadavg()[0]},
        "parametros": cfg.generacion.model_dump(),
        "titulares": [t["id_noticia"] for t in titulares],
        "memoria_bytes": memoria,
        "rss_servidor_bytes": rss_servidor_bytes(),
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
    print(f"Ollama: {res['version_ollama']}  num_ctx: {res['num_ctx']}  prompt: {res['prompt']}  "
          f"carga del sistema (1 min): {res['carga_sistema_1min']['inicio']:.1f} → "
          f"{res['carga_sistema_1min']['fin']:.1f}")
    vd, at = r["json_valido_distintas"], r["atribucion"]
    print(f"JSON válido (por llamada, n={v['n']}): {v['k']}/{v['n']} = {v['pct']:.1f} %  "
          f"(IC 95 % Wilson {v['ic_inf_pct']:.1f}–{v['ic_sup_pct']:.1f} %)")
    print(f"JSON válido (salidas DISTINTAS, n efectivo={vd['n']}): {vd['k']}/{vd['n']} = "
          f"{vd['pct']:.1f} %  (IC 95 % Wilson {vd['ic_inf_pct']:.1f}–{vd['ic_sup_pct']:.1f} %)")
    print(f"Declaraciones sin atribución al medio: {at['declaraciones_llamadas']['sin_atribucion']}/"
          f"{at['declaraciones_llamadas']['n']} (todas las llamadas) · "
          f"{at['declaraciones_distintas']['sin_atribucion']}/{at['declaraciones_distintas']['n']} "
          "(salidas distintas)")
    print(f"Citas válidas (sobre salidas válidas): {r['citas_validas']['k']}/{r['citas_validas']['n']}")
    print(f"Latencia: mediana {lat['mediana']:.1f} s · p95 {lat['p95']:.1f} s "
          f"(mín {lat['min']:.1f}, máx {lat['max']:.1f})")
    print(f"Memoria: /api/ps total {gb(mem.get('size'))} · VRAM {gb(mem.get('size_vram'))} · "
          f"RSS del servidor {gb(res.get('rss_servidor_bytes'))}")
    print(f"D-02: mediana ≤ umbral: {d['mediana_ok']} · inválidos "
          f"{d['invalidos_por_diez_distintas']:.1f}/10 sobre salidas distintas "
          f"(ok: {d['invalidos_ok']}) → cumple: {d['cumple']}")


def nombre_archivo(modelo: str, etiqueta: str | None) -> str:
    base = modelo.replace(":", "_").replace("/", "_")
    return f"probar_llm_{base}{'_' + etiqueta if etiqueta else ''}.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modelo", help="tag exacto de Ollama, ej. qwen3.5:9b")
    ap.add_argument("--reanalizar", type=Path, default=None, metavar="ARCHIVO",
                    help="recalcula el resumen de un outputs/probar_llm_*.json sin llamar a Ollama")
    ap.add_argument("--repeticiones", type=int, default=None)
    ap.add_argument("--num-ctx", type=int, default=None, help="variante de optimización")
    ap.add_argument("--prompt", default=None, help="variante de prompt en prompts/ (sin .txt)")
    ap.add_argument("--etiqueta", default=None, help="sufijo del archivo de resultados")
    args = ap.parse_args(argv)

    configurar_logging()
    cfg = cargar_llm()
    if args.reanalizar:
        res = json.loads(args.reanalizar.read_text(encoding="utf-8"))
        res["resumen"] = resumir(res["llamadas"], cfg)
        args.reanalizar.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        imprimir_resumen(res)
        return 0
    if not args.modelo:
        ap.error("--modelo es obligatorio salvo con --reanalizar")
    entorno = leer_local_env()
    host = entorno.get("OLLAMA_HOST") or cfg.ollama.host_por_defecto
    cliente = ClienteOllama(host, cfg.ollama.timeout_segundos)
    log.info("Ollama en %s (claves de local.env: %s)", cliente.host, sorted(entorno))

    noticias = pd.read_csv(RAIZ / "data" / "processed" / "noticias.csv")
    repeticiones = args.repeticiones or cfg.prueba.repeticiones
    num_ctx = args.num_ctx or cfg.generacion.num_ctx
    try:
        res = ejecutar(cliente, args.modelo, cfg, noticias, repeticiones, num_ctx, args.prompt)
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
