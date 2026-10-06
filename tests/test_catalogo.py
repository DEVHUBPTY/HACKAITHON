"""Pruebas offline del catálogo de datos (E1-04). Leen el snapshot versionado; sin red."""

import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts import catalogo

DATA = Path(__file__).resolve().parent.parent / "data"
COLUMNAS_NOTION = [
    "Fuente", "Archivo", "Modalidad", "Etapa", "URL", "Fecha de extracción", "Cobertura", "Campos",
    "Licencia / condiciones", "Transformaciones", "Registros válidos", "Registros excluidos y motivo", "SHA-256",
]  # fmt: skip


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture()
def filas(tmp_path: Path) -> list[dict[str, str]]:
    destino = tmp_path / "catalogo.csv"
    catalogo.generar(DATA, destino)
    with destino.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        assert lector.fieldnames == COLUMNAS_NOTION
        return list(lector)


def test_columnas_exactas_y_una_fila_por_fuente(filas: list[dict[str, str]]) -> None:
    assert catalogo.COLUMNAS == COLUMNAS_NOTION
    assert [f["Fuente"][0] for f in filas] == ["A", "B", "C", "D"]
    assert all(set(f) == set(COLUMNAS_NOTION) and all(f.values()) for f in filas)


def test_sha256_coincide_con_manifest_y_con_el_archivo(filas: list[dict[str, str]], manifest: dict) -> None:
    for fila, archivos in zip(filas[:3], [["noticias.csv", "fuentes.json"], ["indicadores.csv"], ["eventos.geojson"]]):
        for archivo in archivos:
            esperado = manifest["sha256"][f"processed/{archivo}"]
            assert f"{archivo}: {esperado}" in fila["SHA-256"]
            assert hashlib.sha256((DATA / "processed" / archivo).read_bytes()).hexdigest() == esperado


def test_conteos_y_excluidos_vienen_del_manifest(filas: list[dict[str, str]], manifest: dict) -> None:
    cantidad = manifest["cantidad_por_archivo"]
    assert str(cantidad["noticias.csv"]) in filas[0]["Registros válidos"]
    assert str(cantidad["indicadores.csv"]) in filas[1]["Registros válidos"]
    assert str(cantidad["eventos.geojson"]) in filas[2]["Registros válidos"]
    assert "fuera_de_ventana: 97" in filas[0]["Registros excluidos y motivo"]


def test_cobertura_honesta(filas: list[dict[str, str]]) -> None:
    noticias = filas[0]["Cobertura"]
    assert "PARCIAL" in noticias
    assert "economia 4 de 30" in noticias
    assert "eventos_naturales" in noticias and "0 días" in noticias
    assert "D-74" in noticias and "no trae firma" in noticias
    assert "D-81" in filas[1]["Cobertura"] and "540" in filas[1]["Cobertura"]
    assert "no equivale a Panamá" in filas[2]["Cobertura"]


def test_licencias_sin_inventar(filas: list[dict[str, str]], manifest: dict) -> None:
    assert manifest["licencias"]["banco_mundial"] == filas[1]["Licencia / condiciones"]
    assert manifest["licencias"]["usgs"] == filas[2]["Licencia / condiciones"]
    assert "Pendiente de verificar" in filas[3]["Licencia / condiciones"]


def test_sbp_pendiente_manual(filas: list[dict[str, str]]) -> None:
    sbp = filas[3]
    assert sbp["Etapa"] == "Etapa 3" and sbp["Modalidad"] == "Banca"
    for columna in ("Fecha de extracción", "Registros válidos", "SHA-256"):
        assert "Pendiente" in sbp[columna]


def test_valores_siguen_al_manifest(manifest: dict) -> None:
    """Si cambia el manifest, cambia el catálogo: nada va escrito a mano."""
    otro = copy.deepcopy(manifest)
    otro["cantidad_por_archivo"]["eventos.geojson"] = 7
    otro["sha256"]["processed/eventos.geojson"] = "0" * 64
    otro["cobertura_efectiva"]["gdelt_dias_por_tema"]["turismo"]["dias_cubiertos"] = 9
    filas = catalogo.construir_filas(otro, DATA / "processed")
    assert "7 eventos" in filas[2]["Registros válidos"] and "0" * 64 in filas[2]["SHA-256"]
    assert "turismo 9 de 30" in filas[0]["Cobertura"]


def test_salida_determinista(tmp_path: Path) -> None:
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    catalogo.generar(DATA, a)
    catalogo.generar(DATA, b)
    assert a.read_bytes() == b.read_bytes()


def test_sha_distinto_aborta(tmp_path: Path, manifest: dict) -> None:
    datos = tmp_path / "data"
    (datos / "processed").mkdir(parents=True)
    for ruta in manifest["sha256"]:
        (datos / ruta).write_bytes(b"x")
    (datos / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="no coincide"):
        catalogo.generar(datos, tmp_path / "c.csv")
