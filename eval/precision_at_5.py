"""Precision@5 del ranking contra la selección independiente de un editor (E1-19, PDF 9.1 y 11).

**Qué mide.** De los ``k`` (5) temas que elige el editor, cuántos están en el top ``k`` del sistema y cuántos en el top ``k`` del
baseline «ranking por fecha» (PDF sección 8: solo la fecha de **publicación** más reciente del grupo; los grupos sin ella van al final y se cuentan; desempate por ID; no mira P). Cada proporción
lleva su numerador, su n y su intervalo de Wilson del 95 % (z de ``config/carga.yaml``). Un tema es un grupo ``GRP-`` de la base
(sin los sintéticos de la demo). No infiere audiencia, rentabilidad ni reducción de riesgo.

**Hoja ciega.** ``--hoja`` escribe ``eval/hoja_editor_ciega.csv``: los mismos candidatos, **sin P, posición, rango, componentes,
estado de evidencia ni acción**, y en un orden que no depende de nada de eso. El orden es SHA-256 de ``semilla|id_grupo``
(``config/precision.yaml``): es reproducible, no es alfabético (el ID es un hash, pero un orden por ID se vería ordenado) y no
usa la fecha, así que tampoco insinúa el baseline. El editor marca con ``x`` la columna ``seleccion`` de sus ``k`` temas y guarda el
archivo como ``eval/seleccion_editor.csv``.

**Sin selección no hay resultado.** Si el archivo no existe o no tiene marcas, se imprime «pendiente de selección humana» y se
sale con código 0; nunca se simula al editor.

**Cortes.** Cada selección lleva su ``corte`` (la ``fecha_referencia`` de la base que se le mostró). Con ``--base`` repetido se
mide cada corte contra su base. Con menos de ``cortes_minimos`` cortes el resultado se declara exploratorio (D-57, D-74). El total
junta los aciertos de todos los cortes (k·n temas); los temas de un mismo corte no son independientes, así que el intervalo es
orientativo.

Uso: ``poetry run python -m eval.precision_at_5 --hoja`` y luego ``--seleccion eval/seleccion_editor.csv``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import db
from src.carga import intervalo_wilson
from src.configuracion import RAIZ, ConfigPrecision, cargar_carga, cargar_precision, cargar_temas

ORIGEN_SINTETICO = "sintetico"
DECIMALES = 4          # solo presentación
ESTADO_PENDIENTE, ESTADO_MEDIDO = "pendiente", "medido"
NOTA = (
    "Los temas de un mismo corte no son independientes: el intervalo es orientativo. "
    "No se infiere audiencia, rentabilidad ni reducción de riesgo."
)


class SeleccionInvalida(ValueError):
    """La selección del editor no se puede usar (cantidad, IDs o columnas)."""


@dataclass(frozen=True)
class Candidato:
    """Un tema candidato: lo que ve el editor y lo que usan el sistema y el baseline (esto último nunca va a la hoja)."""

    id_grupo: str
    tema: str
    titular: str
    fecha_reciente: str
    posicion: int

    @property
    def sin_fecha_publicacion(self) -> bool:
        return not self.fecha_reciente


# ------------------------------------------------------------------ candidatos, sistema y baseline


def corte_de_base(con: Any) -> str:
    """``fecha_referencia`` de los puntajes: el corte del snapshot con el que se calculó el ranking."""
    fila = con.execute("SELECT MIN(fecha_referencia) FROM puntajes").fetchone()
    if not fila or fila[0] is None:
        raise SeleccionInvalida("la base no tiene puntajes: correr python -m src.puntaje")
    return str(fila[0])


def candidatos(con: Any) -> list[Candidato]:
    """Los grupos con puntaje de la base, sin los que tienen noticias sintéticas.

    ``fecha_reciente`` es **solo** el máximo de ``fecha_publicacion`` de las noticias del grupo (X34). La fecha de detección de GDELT no
    sustituye a la de publicación (reglas de datos): un grupo sin ninguna fecha de publicación queda con ``""``.
    """
    nombres = {k: t.nombre for k, t in cargar_temas().temas.items()}
    filas = con.execute(
        "SELECT g.id_grupo, g.tema_clasificado, g.titular_central, "
        "(SELECT MAX(n.fecha_publicacion) FROM noticias n WHERE n.id_grupo = g.id_grupo) AS fecha_publicacion, p.posicion "
        "FROM grupos g JOIN puntajes p USING (id_grupo) "
        "WHERE NOT EXISTS (SELECT 1 FROM noticias n WHERE n.id_grupo = g.id_grupo AND n.origen = ?) "
        "ORDER BY p.posicion",
        [ORIGEN_SINTETICO],
    ).fetchall()
    return [
        Candidato(i, nombres.get(t, t or ""), titular, fecha or "", int(pos))
        for i, t, titular, fecha, pos in filas
    ]


def top_sistema(cands: Sequence[Candidato], k: int) -> list[Candidato]:
    """Los ``k`` primeros por la posición que guardó E1-10 (P, luego mayor U, luego menor ID)."""
    return sorted(cands, key=lambda c: c.posicion)[:k]


def top_baseline(cands: Sequence[Candidato], k: int) -> list[Candidato]:
    """Baseline «ranking por fecha»: fecha de publicación reciente descendente; los grupos sin ella van al final; el empate lo decide el ID.

    No mira P, la posición ni la fecha de detección.
    """
    por_id = sorted(cands, key=lambda c: c.id_grupo)
    return sorted(por_id, key=lambda c: c.fecha_reciente, reverse=True)[:k]   # estable: conserva el orden por ID en los empates


def aciertos(top: Sequence[str], elegidos: set[str]) -> int:
    """Temas del ``top`` que el editor también eligió."""
    return sum(1 for i in top if i in elegidos)


# ------------------------------------------------------------------ métricas


def _proporcion(k: int, n: int, z: float) -> dict[str, Any]:
    ic = intervalo_wilson(k, n, z)
    return {
        "k": k,
        "n": n,
        "proporcion": None if n == 0 else round(k / n, DECIMALES),
        "ic95": None if ic is None else [round(ic[0], DECIMALES), round(ic[1], DECIMALES)],
    }


def evaluar_corte(cands: Sequence[Candidato], elegidos: set[str], corte: str, k: int, z: float) -> dict[str, Any]:
    """P@k del sistema y del baseline en un corte, con los IDs del top que el editor no eligió."""
    resultado: dict[str, Any] = {"corte": corte, "candidatos": len(cands), "elegidos": sorted(elegidos)}
    for nombre, top in (("sistema", top_sistema(cands, k)), ("baseline", top_baseline(cands, k))):
        ids = [c.id_grupo for c in top]
        resultado[nombre] = _proporcion(aciertos(ids, elegidos), k, z) | {"top": ids, "ids_fallidos": [i for i in ids if i not in elegidos]}
    resultado["baseline_sin_fecha_publicacion"] = sum(1 for c in cands if c.sin_fecha_publicacion)
    return resultado


def resumir(cortes: Sequence[Mapping[str, Any]], cfg: ConfigPrecision, z: float) -> dict[str, Any]:
    """Junta los cortes: aciertos y n sumados, y si el resultado es exploratorio (menos de ``cortes_minimos`` cortes)."""
    resumen: dict[str, Any] = {"pruebas": len(cortes), "exploratoria": len(cortes) < cfg.cortes_minimos, "cortes_minimos": cfg.cortes_minimos}
    for nombre in ("sistema", "baseline"):
        resumen[nombre] = _proporcion(sum(c[nombre]["k"] for c in cortes), sum(c[nombre]["n"] for c in cortes), z)
    return resumen


# ------------------------------------------------------------------ hoja ciega


def _clave_ciega(semilla: str, id_grupo: str) -> str:
    return hashlib.sha256(f"{semilla}|{id_grupo}".encode()).hexdigest()


def hoja_ciega(cands: Sequence[Candidato], corte: str, cfg: ConfigPrecision) -> list[dict[str, str]]:
    """Filas para el editor: solo las columnas de la config, en un orden que no depende de P, la posición ni la fecha."""
    ordenados = sorted(cands, key=lambda c: (_clave_ciega(cfg.hoja_ciega.semilla, c.id_grupo), c.id_grupo))
    visibles = {"corte": corte, "tema": None, "titular": None, "fecha_reciente": None, "seleccion": ""}
    filas = []
    for c in ordenados:
        datos = visibles | {"id_grupo": c.id_grupo, "tema": c.tema, "titular": c.titular, "fecha_reciente": c.fecha_reciente}
        filas.append({col: datos[col] for col in cfg.hoja_ciega.columnas})
    return filas


def escribir_hoja(ruta: Path, filas: Sequence[Mapping[str, str]], cfg: ConfigPrecision) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cfg.hoja_ciega.columnas)
        w.writeheader()
        w.writerows(filas)


# ------------------------------------------------------------------ selección del editor


def leer_seleccion(ruta: Path, cfg: ConfigPrecision) -> dict[str, set[str]] | None:
    """``corte -> IDs marcados``; ``None`` si el archivo no existe o no tiene ninguna marca (selección pendiente)."""
    if not ruta.exists():
        return None
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        faltan = {"corte", "id_grupo", "seleccion"} - set(lector.fieldnames or [])
        if faltan:
            raise SeleccionInvalida(f"{ruta}: faltan las columnas {sorted(faltan)}")
        marca = cfg.hoja_ciega.marca.lower()
        porcorte: dict[str, set[str]] = {}
        for fila in lector:
            if (fila["seleccion"] or "").strip().lower() == marca:
                porcorte.setdefault(fila["corte"].strip(), set()).add(fila["id_grupo"].strip())
    return porcorte or None


def validar_seleccion(seleccion: Mapping[str, set[str]] | None, cands: Sequence[Candidato], k: int) -> None:
    """Cada corte debe traer exactamente ``k`` temas y todos deben ser candidatos de la base."""
    conocidos = {c.id_grupo for c in cands}
    for corte, ids in (seleccion or {}).items():
        if len(ids) != k:
            raise SeleccionInvalida(f"corte {corte}: el editor marcó {len(ids)} temas y deben ser exactamente {k}")
        desconocidos = sorted(ids - conocidos)
        if desconocidos:
            raise SeleccionInvalida(f"corte {corte}: IDs que no son candidatos de la base: {desconocidos}")


# ------------------------------------------------------------------ reporte


def _texto(p: Mapping[str, Any]) -> str:
    lo, hi = p["ic95"]
    return f"{p['proporcion']:.1%} ({p['k']}/{p['n']}, n = {p['n']}, IC 95 % {lo:.1%}–{hi:.1%})"


def formatear(r: Mapping[str, Any], cfg: ConfigPrecision) -> str:
    """El reporte como texto: P@k del sistema y del baseline por corte y en total, siempre con n e IC."""
    lineas = [f"Precision@{cfg.k} · pruebas (fechas de corte): {r['pruebas']}"]
    for c in r["cortes"]:
        lineas += [
            f"  Corte {c['corte']} · {c['candidatos']} candidatos · baseline: {c['baseline_sin_fecha_publicacion']} grupos sin fecha de publicación (van al final)",
            f"    P@{cfg.k} sistema: {_texto(c['sistema'])} · fallos: {', '.join(c['sistema']['ids_fallidos']) or 'ninguno'}",
            f"    P@{cfg.k} baseline 'ranking por fecha': {_texto(c['baseline'])} · fallos: {', '.join(c['baseline']['ids_fallidos']) or 'ninguno'}",
        ]
    if r["pruebas"] > 1:
        lineas += [f"  Total sistema: {_texto(r['sistema'])}", f"  Total baseline 'ranking por fecha': {_texto(r['baseline'])}"]
    if r["exploratoria"]:
        lineas.append("  Resultado " + cfg.textos.exploratoria.format(pruebas=r["pruebas"], cortes_minimos=cfg.cortes_minimos))
        lineas.append("  " + cfg.textos.sin_especialista)
    lineas.append("  " + NOTA)
    return "\n".join(lineas)


def _escribir_json(ruta: Path, datos: Mapping[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _abrir(base: Path) -> Any:
    return db.conectar(base, solo_lectura=True)


def principal(argv: list[str] | None = None) -> int:
    cfg = cargar_precision()
    parser = argparse.ArgumentParser(description="E1-19: Precision@5 contra la selección de un editor y hoja ciega")
    parser.add_argument("--seleccion", type=Path, action="append", help=f"hoja marcada por el editor (por defecto {cfg.archivos.seleccion}); se puede repetir")
    parser.add_argument("--base", type=Path, action="append", help="base DuckDB de cada corte (por defecto data/senales.duckdb); se puede repetir")
    parser.add_argument("--salida", type=Path, default=RAIZ / cfg.archivos.salida)
    parser.add_argument("--hoja", action="store_true", help="escribe la hoja ciega para el editor y termina")
    parser.add_argument("--hoja-salida", type=Path, default=RAIZ / cfg.archivos.hoja)
    parser.add_argument("--corte", default=None, help="corte que lleva la hoja (por defecto, el de la base)")
    args = parser.parse_args(argv)
    bases = args.base or [db.RUTA_BASE]
    selecciones = args.seleccion or [RAIZ / cfg.archivos.seleccion]

    if args.hoja:
        con = _abrir(bases[0])
        try:
            filas = hoja_ciega(candidatos(con), args.corte or corte_de_base(con), cfg)
        finally:
            con.close()
        escribir_hoja(args.hoja_salida, filas, cfg)
        print(f"Hoja ciega con {len(filas)} temas en {args.hoja_salida} (sin P, posición ni evidencia). "
              f"Marcar con '{cfg.hoja_ciega.marca}' la columna 'seleccion' de {cfg.k} temas y guardar como {cfg.archivos.seleccion}.")
        return 0

    try:
        marcadas: dict[str, set[str]] = {}
        for ruta in selecciones:
            for corte, ids in (leer_seleccion(ruta, cfg) or {}).items():
                marcadas.setdefault(corte, set()).update(ids)
        if not marcadas:
            _escribir_json(args.salida, {"estado": ESTADO_PENDIENTE, "mensaje": cfg.textos.pendiente})
            print(f"Precision@{cfg.k}: {cfg.textos.pendiente}. Generar la hoja con --hoja; el editor la marca sin ver el ranking.")
            return 0
        z = cargar_carga().salida.z_intervalo_confianza
        por_corte: dict[str, tuple[Path, list[Candidato]]] = {}
        for base in bases:
            con = _abrir(base)
            try:
                por_corte[corte_de_base(con)] = (base, candidatos(con))
            finally:
                con.close()
        cortes = []
        for corte in sorted(marcadas):
            if corte not in por_corte:
                raise SeleccionInvalida(f"no hay base para el corte {corte}: pasar su base con --base (cortes disponibles: {sorted(por_corte)})")
            cands = por_corte[corte][1]
            validar_seleccion({corte: marcadas[corte]}, cands, cfg.k)
            cortes.append(evaluar_corte(cands, marcadas[corte], corte, cfg.k, z))
    except SeleccionInvalida as exc:
        print(f"Selección inválida: {exc}", file=sys.stderr)
        return 2
    resultado = {"estado": ESTADO_MEDIDO, "k": cfg.k, "cortes": cortes, "nota": NOTA} | resumir(cortes, cfg, z)
    _escribir_json(args.salida, resultado)
    print(formatear(resultado, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
