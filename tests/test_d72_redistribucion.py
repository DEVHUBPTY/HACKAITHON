"""D-72 / X84 · Nada con redistribución restringida entra a git. La lista de rutas vive en ``config/fuentes.yaml``."""

from __future__ import annotations

import copy
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import catalogo, reproducir
from src.configuracion import RAIZ, cargar_fuentes

RUTAS = [(fuente, ruta) for fuente, rutas in cargar_fuentes().redistribucion_restringida.items() for ruta in rutas]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=False)  # noqa: S603, S607


def test_la_configuracion_declara_las_fuentes_restringidas() -> None:
    assert {"rss_tvn", "gdelt", "sbp"} <= set(cargar_fuentes().redistribucion_restringida)
    assert cargar_fuentes().redistribucion_restringida["sbp"] == ["data/raw/sbp/"]   # el CSV agregado se versiona por D-116


@pytest.mark.parametrize(("fuente", "ruta"), RUTAS)
def test_ninguna_ruta_restringida_esta_versionada(fuente: str, ruta: str) -> None:
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("no es un repositorio git")
    versionados = _git("ls-files", "--", ruta).stdout.split()
    assert versionados == [], f"{fuente}: {versionados[:3]} está en git y su fuente restringe la redistribución (D-72)"


@pytest.mark.parametrize(("fuente", "ruta"), RUTAS)
def test_cada_ruta_restringida_esta_en_gitignore(fuente: str, ruta: str) -> None:
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("no es un repositorio git")
    sonda = ruta + "archivo.dat" if ruta.endswith("/") else ruta   # una carpeta se prueba con un archivo hipotético adentro
    assert _git("check-ignore", "-q", sonda).returncode == 0, f"{fuente}: {ruta} no está en .gitignore"


def test_el_catalogo_funciona_sin_el_csv_local_de_la_sbp(tmp_path: Path) -> None:
    """Sin ``sbp_series.csv`` (no se versiona) el catálogo declara los nulos como no verificables en vez de fallar."""
    import json

    manifest = json.loads((RAIZ / "data" / "manifest.json").read_text(encoding="utf-8"))
    copia = tmp_path / "processed"
    shutil.copytree(RAIZ / "data" / "processed", copia, ignore=shutil.ignore_patterns("sbp_series.csv"))
    fila = catalogo.construir_filas(copy.deepcopy(manifest), copia)[3]
    assert "no verificables" in fila["Cobertura"] and "valor" in fila["Campos"]


def test_reproducir_omite_lo_que_depende_de_un_archivo_local_ausente() -> None:
    registrado = {"archivo:data/processed/sbp_series.csv": "a", "tabla:vinculos": "b", "fichas": "c", "tabla:grupos": "d"}
    actual = {"tabla:vinculos": "otro", "fichas": "otro", "tabla:grupos": "d"}
    omitidas = {"archivo:data/processed/sbp_series.csv", "tabla:vinculos", "fichas"}
    assert reproducir.comparar(registrado, actual, omitidas) == []
    assert [d.clave for d in reproducir.comparar(registrado, {**actual, "tabla:grupos": "x"}, omitidas)] == ["tabla:grupos"]

