"""Who separates better, our pipeline or DeepSeek zero-shot, measured against the HUMAN labels (eval/etiquetas.csv, origen=humano)?

Exploratory; DeepSeek output is an LLM judgment (D-101). Usage (repo root): poetry run python <this file> <out_json>
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path.cwd()))
from proponer_etiquetas import LOTE, system, validar  # noqa: E402
from src.llm.proveedor import crear_proveedor  # noqa: E402

TEMAS = ["economia", "logistica", "turismo", "servicios_publicos", "eventos_naturales", "regulacion", "sin_tema"]


def macro_f1(y: list[str], p: list[str]) -> float:
    clases = sorted(set(y) | set(p))
    f1s = []
    for c in clases:
        tp = sum(a == c and b == c for a, b in zip(y, p))
        fp = sum(a != c and b == c for a, b in zip(y, p))
        fn = sum(a == c and b != c for a, b in zip(y, p))
        f1s.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return sum(f1s) / len(f1s)


def wilson(k: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    z, ph = 1.96, k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    m = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(c - m, 4), round(c + m, 4)]


def main() -> None:
    out = Path(sys.argv[1])
    humanas = [r for r in csv.DictReader(open("eval/etiquetas.csv", encoding="utf-8")) if r["origen"] == "humano"]
    c = duckdb.connect("data/senales.duckdb", read_only=True)
    sis = {r[0]: r[1:] for r in c.execute("select id_noticia, es_ruido, tema_clasificado, tema_baseline from noticias").fetchall()}
    humanas = [h for h in humanas if h["id_noticia"] in sis]
    prov = crear_proveedor()
    llm: dict[str, dict] = {}
    for i in range(0, len(humanas), LOTE):
        lote = humanas[i : i + LOTE]
        cuerpo = "\n".join(json.dumps({"id": h["id_noticia"], "titular": h["titulo"]}, ensure_ascii=False) for h in lote)
        resp = json.loads(prov.generar_json(system(), f"<evidencia>\n{cuerpo}\n</evidencia>", {"type": "object"}))
        for e in resp.get("etiquetas", []):
            if e.get("id") in {h["id_noticia"] for h in lote}:
                llm[e["id"]] = validar(e)

    filas = []
    for h in humanas:
        i = h["id_noticia"]
        if i not in llm:
            continue
        es_ruido_h = h["ruido"] not in ("", "ninguno")
        tema_h = h["tema_principal"] or "sin_tema"
        r_sis, tema_sis, tema_base = sis[i]
        filas.append({
            "id": i, "titulo": h["titulo"], "ruido_humano": es_ruido_h, "ruido_sistema": bool(r_sis), "ruido_llm": llm[i]["ruido"] != "ninguno",
            "tema_humano": tema_h, "tema_sistema": tema_sis or "sin_tema", "tema_baseline": tema_base or "sin_tema", "tema_llm": llm[i]["tema_principal"] or "sin_tema",
        })

    n = len(filas)
    ruido = {k: sum(f["ruido_humano"] == f[f"ruido_{k}"] for f in filas) for k in ("sistema", "llm")}
    # Topic: rows the human considers non-noise (same base as the classifier metrics), regardless of each system's noise call.
    base = [f for f in filas if not f["ruido_humano"]]
    y = [f["tema_humano"] for f in base]
    preds = {k: [f[f"tema_{k}"] for f in base] for k in ("sistema", "baseline", "llm")}
    acc = {k: sum(a == b for a, b in zip(y, p)) for k, p in preds.items()}
    f1 = {k: round(macro_f1(y, p), 4) for k, p in preds.items()}
    rng = random.Random(42)
    dif = []
    for _ in range(2000):
        s = [rng.randrange(len(base)) for _ in base]
        ys = [y[k] for k in s]
        dif.append(macro_f1(ys, [preds["llm"][k] for k in s]) - macro_f1(ys, [preds["sistema"][k] for k in s]))
    dif.sort()
    rep = {
        "origen_juicio": "comparación contra etiquetas humanas (eval/etiquetas.csv, origen=humano); tema_llm = DeepSeek zero-shot, exploratorio (D-101)",
        "ruido": {"n": n, **{f"acierto_{k}": {"n": v, "de": n, "proporcion": round(v / n, 4), "ic95": wilson(v, n)} for k, v in ruido.items()}},
        "tema": {
            "n": len(base), "clases_humanas": dict(Counter(y)),
            **{f"exactitud_{k}": {"n": v, "de": len(base), "proporcion": round(v / len(base), 4), "ic95": wilson(v, len(base))} for k, v in acc.items()},
            "macro_f1": f1,
            "diferencia_macro_f1_llm_menos_sistema_ic95": [round(dif[50], 4), round(dif[1949], 4)],
        },
        "filas": filas,
    }
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "filas"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
