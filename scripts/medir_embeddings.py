"""Mide los modelos de embeddings locales para ``docs/modelos.md`` (E1-18, D-67): carga, velocidad, memoria, tamaño y parámetros.

    HF_HUB_OFFLINE=1 poetry run python -m scripts.medir_embeddings            # outputs/medicion_embeddings.json

Cada modelo se mide en **un proceso aparte** (así el RSS máximo es el suyo y no el del anterior). Los textos son los primeros ``--n``
titulares útiles (no ruido) de la base, en orden de ``id_noticia``: solo titulares, nunca la descripción del RSS (D-31). El costo es USD 0
(sentence-transformers en CPU, sin API); el tiempo es de pared en esta máquina y no se generaliza a otra.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from src.configuracion import RAIZ, cargar_clasificacion, cargar_normalizacion

SALIDA = RAIZ / "outputs" / "medicion_embeddings.json"
MAXRSS_A_BYTES = 1 if sys.platform == "darwin" else 1024   # ru_maxrss: bytes en macOS, KiB en Linux


def titulares(base: Path, n: int) -> list[str]:
    from src import db

    con = db.conectar(base, solo_lectura=True)
    try:
        filas = con.execute("SELECT titulo_limpio FROM noticias WHERE NOT es_ruido ORDER BY id_noticia LIMIT ?", [n]).fetchall()
    finally:
        con.close()
    return [f[0] for f in filas]


def tamano_en_disco(carpeta_modelos: Path, id_modelo: str) -> int:
    """Bytes de los archivos reales (los blobs) a los que apunta la instantánea local del modelo."""
    raiz = carpeta_modelos / ("models--" + id_modelo.replace("/", "--")) / "snapshots"
    vistos: set[Path] = set()
    for archivo in raiz.rglob("*") if raiz.exists() else []:
        if archivo.is_file() or archivo.is_symlink():
            vistos.add(archivo.resolve())
    return sum(p.stat().st_size for p in vistos if p.is_file())


def medir(nombre: str, textos: list[str], motor: Any = None) -> dict[str, Any]:
    """Carga el modelo, codifica ``textos`` y devuelve las cifras. ``motor`` se inyecta en las pruebas."""
    from src.embeddings import MotorSentenceTransformers

    cfg = cargar_clasificacion()
    modelo = cfg.modelos[nombre]
    motor = motor or MotorSentenceTransformers(modelo, cfg)
    prefijo = modelo.prefijo_titular
    t0 = time.perf_counter()
    motor.codificar([f"{prefijo}calentamiento"])       # fuerza la carga del modelo
    carga_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    matriz = motor.codificar([f"{prefijo}{t}" for t in textos])
    codificar_s = time.perf_counter() - t1
    st = getattr(motor, "_st", None)
    return {
        "modelo": nombre, "id": modelo.id, "revision": modelo.revision,
        "dimension": int(matriz.shape[1]) if matriz.ndim == 2 and len(matriz) else None,
        "parametros": sum(p.numel() for p in st.parameters()) if st is not None else None,
        "max_seq_length": getattr(st, "max_seq_length", None),
        "carga_s": round(carga_s, 2),
        "n_textos": len(textos), "codificar_s": round(codificar_s, 3),
        "textos_por_s": round(len(textos) / codificar_s, 1) if codificar_s > 0 else None,
        "rss_maximo_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * MAXRSS_A_BYTES,
        "tamano_en_disco_bytes": tamano_en_disco(RAIZ / cfg.carpetas.modelos, modelo.id),
        "dispositivo": cfg.dispositivo, "lote": cfg.lote, "costo_usd": 0.0,
    }


def principal(argv: list[str] | None = None) -> int:
    cfg = cargar_clasificacion()
    parser = argparse.ArgumentParser(description="E1-18: mide los modelos de embeddings locales (docs/modelos.md)")
    parser.add_argument("--n", type=int, default=200, help="titulares a codificar")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    parser.add_argument("--modelo", choices=sorted(cfg.modelos), help="(interno) mide un solo modelo y lo imprime en JSON")
    args = parser.parse_args(argv)
    if args.modelo:
        print(json.dumps(medir(args.modelo, titulares(args.base, args.n))))
        return 0
    medidas = []
    for nombre in sorted(cfg.modelos):
        proc = subprocess.run([sys.executable, "-m", "scripts.medir_embeddings", "--modelo", nombre, "--n", str(args.n), "--base", str(args.base)],
                              capture_output=True, text=True, cwd=RAIZ, check=False)
        if proc.returncode != 0:
            print(f"ERROR midiendo {nombre}: {proc.stderr[-300:]}", file=sys.stderr)
            return 1
        medidas.append(json.loads(proc.stdout.strip().splitlines()[-1]))
    informe = {"entorno": {"sistema": platform.platform(), "procesador": platform.processor(), "python": platform.python_version()}, "modelos": medidas,
               "nota": "Tiempos de pared en una sola máquina, un proceso por modelo; RSS máximo del proceso. Costo USD 0 (local, sin API)."}
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(informe, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
