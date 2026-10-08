"""C-06 · Base de la demo: ``data/demo.duckdb`` = copia del snapshot + casos sintéticos, procesados por el pipeline normal.

La demo necesita un caso que el snapshot real no tiene: una contradicción abierta (CU-04, PDF sección 4). Se agregan los titulares
sintéticos de ``tests/fixtures/c06_contradiccion_demo.csv`` (IDs ``SYN-``, ``origen = sintetico``) a una **copia** de
``data/senales.duckdb`` y se corren limpieza, clasificación, agrupación, contexto y puntaje (sin LLM) sobre esa copia, con los mismos
módulos de siempre. La copia lleva la tabla ``demo_marca``: cualquier métrica que reciba esta base se niega a leerla (``db.exigir_base_real``).

No toca ``data/senales.duckdb``, ``data/revision.duckdb``, ``data/raw`` ni ``data/processed``. Es idempotente: el resultado se arma en un archivo
parcial y reemplaza al anterior solo si todo salió bien. Sin red ni LLM.

    poetry run python -m scripts.preparar_demo
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from src import db, normalizacion
from src.configuracion import RAIZ, cargar_carga, cargar_corrida, cargar_fuentes, cargar_interfaz, cargar_normalizacion

logger = logging.getLogger(__name__)

FIXTURES_DEMO = ("tests/fixtures/c06_contradiccion_demo.csv",)   # los casos sintéticos de la demo (CU-04: contradicción abierta)


def _filas_sinteticas(fixtures: Sequence[Path]) -> list[dict]:
    """Noticias de los fixtures, normalizadas como las de la carga (fechas UTC, URL canónica, ID ``SYN-`` conservado)."""
    crudas = [f for ruta in fixtures for f in normalizacion.leer_csv(ruta)]
    filas = normalizacion.normalizar_noticias(crudas, [], cargar_normalizacion(), cargar_fuentes(), normalizacion.Registro())
    ajenas = [f["id_noticia"] for f in filas if not str(f["id_noticia"]).startswith("SYN-") or f.get("origen") != "sintetico"]
    if ajenas:
        raise ValueError(f"los casos de la demo deben ser sintéticos (ID SYN-, origen sintetico): {ajenas}")
    return filas


def preparar(
    destino: Path | None = None, origen: Path | None = None, fixtures: Sequence[Path] | None = None, raiz: Path = RAIZ,
) -> dict[str, int]:
    """Crea (o recrea) la base de la demo. Devuelve cuentas: ``noticias``, ``sinteticas``, ``grupos`` y ``contradicciones_abiertas``."""
    from src import agrupacion, clasificacion, contexto, limpieza, prioridad   # import tardío: cargan modelos y config pesada

    origen = Path(origen or db.RUTA_BASE)
    destino = Path(destino or raiz / cargar_interfaz().demo.ruta_base)
    if destino.resolve() == origen.resolve():
        raise ValueError("el destino de la demo no puede ser la base viva")
    if not origen.is_file():
        raise FileNotFoundError(f"no existe {origen}: primero la tubería hasta `python -m src.puntaje`")
    filas = _filas_sinteticas(list(fixtures) if fixtures is not None else [raiz / f for f in FIXTURES_DEMO])
    cfg = cargar_corrida()
    with tempfile.TemporaryDirectory(prefix="hackiathon_demo_") as tmp:
        parcial = Path(tmp) / destino.name
        shutil.copy2(origen, parcial)
        reporte = Path(tmp) / "reporte_calidad.json"
        con = db.conectar(parcial)
        try:
            db.asegurar_esquema(con)
            con.execute("DELETE FROM noticias WHERE origen = 'sintetico' AND id_noticia LIKE 'SYN-%'")   # idempotente si el origen ya llevaba alguno
            db.insertar(con, "noticias", filas)
        finally:
            con.close()
        limpieza.ejecutar(parcial, reporte)
        clasificacion.ejecutar(parcial, reporte)
        agrupacion.ejecutar(parcial, reporte)
        eventos = raiz / cfg.insumos.carpeta_procesados / cargar_carga().archivos.eventos
        contexto.ejecutar(parcial, Path(tmp) / contexto.REPORTE, eventos if eventos.exists() else None, raiz / cfg.insumos.series_sbp)
        ahora = prioridad.fecha_de_corte(raiz / cfg.insumos.manifest)
        prioridad.ejecutar(parcial, Path(tmp) / prioridad.REPORTE, ahora, None, cfg.insumos.modalidad)   # sin LLM: el par queda pendiente de verificar
        con = db.conectar(parcial)
        try:
            con.execute(f'CREATE OR REPLACE TABLE "{db.TABLA_MARCA_DEMO}" AS SELECT ? AS motivo, ? AS ids_sinteticos',
                        ["base de demostración (C-06): snapshot + casos sintéticos; nunca para métricas", ", ".join(f["id_noticia"] for f in filas)])
            cuentas = {
                "noticias": con.execute("SELECT count(*) FROM noticias").fetchone()[0],
                "sinteticas": con.execute("SELECT count(*) FROM noticias WHERE origen = 'sintetico'").fetchone()[0],
                "grupos": con.execute("SELECT count(*) FROM grupos").fetchone()[0],
                "contradicciones_abiertas": con.execute("SELECT count(*) FROM contradicciones WHERE estado = 'verificar'").fetchone()[0],
            }
            con.execute("CHECKPOINT")
        finally:
            con.close()
        destino.parent.mkdir(parents=True, exist_ok=True)
        siguiente = destino.with_name(f".{destino.name}.parcial")
        shutil.copy2(parcial, siguiente)
        siguiente.replace(destino)   # solo una base completa tiene el nombre final
    return cuentas


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="C-06: crea data/demo.duckdb (snapshot + casos sintéticos), nunca para métricas")
    parser.add_argument("--origen", type=Path, default=None, help="base de origen (por defecto data/senales.duckdb, solo lectura de hecho: se copia)")
    parser.add_argument("--destino", type=Path, default=None, help="por defecto data/demo.duckdb")
    args = parser.parse_args(argv)
    cuentas = preparar(args.destino, args.origen)
    destino = args.destino or RAIZ / cargar_interfaz().demo.ruta_base
    print(f"Base de demo lista: {destino}")
    for k, v in cuentas.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
