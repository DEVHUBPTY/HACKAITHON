"""Precisión y recall del filtro de ruido (E1-03b) contra la columna de ruido de ``eval/etiquetas.csv`` (E1-06).

Las etiquetas las hacen personas (E1-06): este módulo **no inventa números**. Si ``eval/etiquetas.csv`` no existe
o no trae la columna de ruido, lo dice y termina con código 2 sin imprimir ninguna métrica.

Formato esperado: ``id_noticia`` y una columna de ruido (por defecto ``ruido``) con ``no_es_panama``,
``fuera_de_temas`` (u otro motivo) o vacío/``ninguno`` para "no es ruido". Cada proporción lleva su n y su
intervalo de Wilson al 95 %. Uso: ``poetry run python -m eval.ruido``.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from src import db
from src.carga import intervalo_wilson
from src.configuracion import RAIZ, cargar_carga, cargar_normalizacion

ETIQUETAS = RAIZ / "eval" / "etiquetas.csv"
SI_REGIONAL = {"si", "sí", "true", "1", "x"}
SIN_RUIDO = {"", "ninguno", "ninguna", "no", "false", "0", "none"}
CODIGO_SIN_ETIQUETAS = 2


def _texto_proporcion(k: int, n: int, z: float) -> str:
    ic = intervalo_wilson(k, n, z)
    if n == 0 or ic is None:
        return f"{k}/{n} (sin base: no se puede calcular)"
    return f"{k}/{n} = {100 * k / n:.1f} % [IC 95 %: {100 * ic[0]:.1f}–{100 * ic[1]:.1f} %]"


def leer_etiquetas(ruta: Path, columna: str) -> dict[str, str | None]:
    """``id_noticia -> motivo humano`` (``None`` si la persona no marcó ruido). Falla si falta la columna."""
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        campos = lector.fieldnames or []
        if "id_noticia" not in campos or columna not in campos:
            raise KeyError(f"{ruta.name} no tiene las columnas id_noticia y {columna!r} (tiene: {campos})")
        etiquetas: dict[str, str | None] = {}
        for fila in lector:
            valor = (fila[columna] or "").strip()
            etiquetas[fila["id_noticia"].strip()] = None if valor.casefold() in SIN_RUIDO else valor
        return etiquetas


def medir(etiquetas: dict[str, str | None], predichas: dict[str, str | None], z: float) -> list[str]:
    """Líneas de reporte: precisión y recall del filtro (ruido sí/no) y por motivo, solo sobre IDs en ambos lados."""
    comunes = sorted(set(etiquetas) & set(predichas))
    lineas = [f"Titulares etiquetados presentes en la base: {len(comunes)} de {len(etiquetas)} etiquetados"]
    humanos = {i: etiquetas[i] is not None for i in comunes}
    modelo = {i: predichas[i] is not None for i in comunes}
    tp = sum(1 for i in comunes if humanos[i] and modelo[i])
    lineas.append("Precisión (marcados que sí son ruido): " + _texto_proporcion(tp, sum(modelo.values()), z))
    lineas.append("Recall (ruido que se marcó): " + _texto_proporcion(tp, sum(humanos.values()), z))
    motivos = sorted({m for m in [*etiquetas.values(), *predichas.values()] if m})
    for motivo in motivos:
        acierto = sum(1 for i in comunes if etiquetas[i] == motivo and predichas[i] == motivo)
        marcados = sum(1 for i in comunes if predichas[i] == motivo)
        reales = sum(1 for i in comunes if etiquetas[i] == motivo)
        lineas.append(f"  {motivo}: precisión {_texto_proporcion(acierto, marcados, z)}; recall {_texto_proporcion(acierto, reales, z)}")
    return lineas


def leer_regional(ruta: Path, columna: str = "alcance_regional") -> dict[str, bool] | None:
    """``id_noticia -> alcance regional marcado por la persona`` (D-84). ``None`` si el CSV no trae la columna."""
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        if columna not in (lector.fieldnames or []):
            return None
        return {fila["id_noticia"].strip(): (fila[columna] or "").strip().casefold() in SI_REGIONAL for fila in lector}


def medir_regional(humanos: dict[str, bool], predichas: dict[str, bool], z: float) -> list[str]:
    """Subconjunto regional (D-84), aparte del ruido: precisión y recall de ``alcance_regional`` del filtro."""
    comunes = sorted(set(humanos) & set(predichas))
    tp = sum(1 for i in comunes if humanos[i] and predichas[i])
    return [
        f"Alcance regional (D-84), aparte del ruido; titulares comparados: {len(comunes)}",
        "  Precisión (marcados regionales que la persona confirma): " + _texto_proporcion(tp, sum(predichas[i] for i in comunes), z),
        "  Recall (regionales según la persona que el filtro marcó): " + _texto_proporcion(tp, sum(humanos[i] for i in comunes), z),
    ]


def regional_de_la_base(ruta_base: Path) -> dict[str, bool]:
    """``id_noticia -> alcance_regional`` según ``python -m src.limpieza``."""
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = con.execute("SELECT id_noticia, alcance_regional FROM noticias").fetchall()
    finally:
        con.close()
    return {i: bool(r) for i, r in filas}


def predichas_de_la_base(ruta_base: Path) -> dict[str, str | None]:
    """``id_noticia -> motivo_ruido`` según ``python -m src.limpieza`` (``None`` si no es ruido)."""
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        filas = con.execute("SELECT id_noticia, motivo_ruido FROM noticias").fetchall()
    finally:
        con.close()
    return {i: m for i, m in filas}


def main(argv: list[str] | None = None) -> int:
    """CLI: imprime precisión y recall del filtro de ruido, o dice con claridad que faltan las etiquetas."""
    parser = argparse.ArgumentParser(description="E1-03b: precisión y recall del filtro de ruido")
    parser.add_argument("--etiquetas", type=Path, default=ETIQUETAS)
    parser.add_argument("--columna", default="ruido", help="columna de ruido en el CSV de etiquetas")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    args = parser.parse_args(argv)
    if not args.etiquetas.exists():
        print(
            f"SIN ETIQUETAS: no existe {args.etiquetas}. Las crea E1-06 (etiquetado humano); "
            "sin ellas no se calcula precisión ni recall (no se inventan números).",
            file=sys.stderr,
        )
        return CODIGO_SIN_ETIQUETAS
    try:
        etiquetas = leer_etiquetas(args.etiquetas, args.columna)
    except KeyError as exc:
        print(f"SIN ETIQUETAS DE RUIDO: {exc.args[0]}. No se calcula ninguna métrica.", file=sys.stderr)
        return CODIGO_SIN_ETIQUETAS
    if not args.base.exists():
        print(f"No existe {args.base}: ejecute normalización y limpieza primero.", file=sys.stderr)
        return 1
    resultado: Any = medir(etiquetas, predichas_de_la_base(args.base), cargar_carga().salida.z_intervalo_confianza)
    print("\n".join(resultado))
    regional = leer_regional(args.etiquetas)
    if regional is None:
        print("Sin columna alcance_regional: no se mide el subconjunto regional (D-84).")
    else:
        z = cargar_carga().salida.z_intervalo_confianza
        print("\n".join(medir_regional(regional, regional_de_la_base(args.base), z)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
