"""Pruebas offline del catálogo de datos (E1-04). Leen el snapshot versionado; sin red."""

import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts import catalogo
from src import carga

DATA = Path(__file__).resolve().parent.parent / "data"
COLUMNAS_NOTION = [
    "Fuente", "Archivo", "Modalidad", "Etapa", "URL", "Fecha de extracción", "Cobertura", "Campos",
    "Licencia / condiciones", "Transformaciones", "Registros válidos", "Registros excluidos y motivo", "SHA-256",
]  # fmt: skip


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def reporte_ruta(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Reporte de calidad real, generado con src.carga en una carpeta temporal."""
    salida = tmp_path_factory.mktemp("carga")
    carga.main(["--salida", str(salida), "--validos", str(salida / "validos")])
    return salida / "reporte_calidad.json"


@pytest.fixture()
def filas(tmp_path: Path, reporte_ruta: Path) -> list[dict[str, str]]:
    destino = tmp_path / "catalogo.csv"
    catalogo.generar(DATA, destino, reporte_ruta)
    with destino.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        assert lector.fieldnames == COLUMNAS_NOTION
        return list(lector)


def test_columnas_exactas_y_una_fila_por_fuente(filas: list[dict[str, str]]) -> None:
    assert catalogo.COLUMNAS == COLUMNAS_NOTION
    assert [f["Fuente"][0] for f in filas] == ["A", "B", "C", "D"]
    assert all(set(f) == set(COLUMNAS_NOTION) and all(f.values()) for f in filas)


def test_sha256_coincide_con_manifest_y_con_el_archivo(filas: list[dict[str, str]], manifest: dict) -> None:
    esperados = [["noticias.csv", "fuentes.json", "conversion.json"], ["indicadores.csv"], ["eventos.geojson"]]
    for fila, archivos in zip(filas[:3], esperados, strict=True):
        for archivo in archivos:
            sha = manifest["sha256"][f"processed/{archivo}"]
            assert f"{archivo}: {sha}" in fila["SHA-256"]
            assert hashlib.sha256((DATA / "processed" / archivo).read_bytes()).hexdigest() == sha


def test_versionado_en_filas_a_b_c(filas: list[dict[str, str]], manifest: dict) -> None:
    for fila in filas[:3]:
        assert f"Snapshot v{manifest['version']}" in fila["Fecha de extracción"]
        assert manifest["fecha_corte_UTC"] in fila["Fecha de extracción"]
        assert manifest["hash_snapshot"] in fila["Fecha de extracción"]


def test_validos_y_excluidos_vienen_del_reporte_y_el_manifest(
    filas: list[dict[str, str]], manifest: dict, reporte_ruta: Path
) -> None:
    reporte = json.loads(reporte_ruta.read_text(encoding="utf-8"))
    for fila, archivo in zip(filas[:3], ["noticias.csv", "indicadores.csv", "eventos.geojson"], strict=True):
        a = reporte["archivos"][archivo]
        assert f"{a['validas']} válidas de {a['leidas']} leídas ({archivo})" in fila["Registros válidos"]
        assert f"{archivo}: {a['rechazadas']} rechazadas por la carga" in fila["Registros excluidos y motivo"]
    ex = next(h for h in manifest["historial"] if h["version"] == manifest["version"])["registros_excluidos"]
    motivo, n = next(iter(ex["por_motivo"].items()))
    assert f"{ex['total']} excluidos" in filas[0]["Registros excluidos y motivo"]
    assert f"{motivo}: {n}" in filas[0]["Registros excluidos y motivo"]
    conversion = json.loads((DATA / "processed" / "conversion.json").read_text(encoding="utf-8"))
    assert f"{conversion['duplicados_descartados']} duplicados" in filas[0]["Registros excluidos y motivo"]
    assert "descargas repetidas o solapadas" in filas[0]["Registros excluidos y motivo"]


def test_rechazos_por_tipo_se_listan(manifest: dict) -> None:
    reporte = {
        "archivos": {
            a: {"leidas": 5, "validas": 3, "rechazadas": 2, "errores_por_tipo": {"fecha_invalida": 2}}
            for a in manifest["cantidad_por_archivo"]
        }
    }
    filas = catalogo.construir_filas(manifest, DATA / "processed", reporte)
    assert "noticias.csv: 2 rechazadas por la carga (fecha_invalida: 2)" in filas[0]["Registros excluidos y motivo"]
    assert "3 válidas de 5 leídas (eventos.geojson)" in filas[2]["Registros válidos"]


def test_cobertura_honesta_desde_el_manifest(filas: list[dict[str, str]], manifest: dict) -> None:
    noticias = filas[0]["Cobertura"]
    assert "PARCIAL" in noticias and "D-74" in noticias and "no trae firma" in noticias
    for tema, d in manifest["cobertura_efectiva"]["gdelt_dias_por_tema"].items():
        assert f"{tema} {d['dias_cubiertos']} de {d['dias_esperados']}" in noticias
        if d["dias_cubiertos"] == 0:
            sin = noticias.split("Sin cobertura de las consultas vigentes de GDELT: ")[1].split(" (0 días)")[0]
            assert tema in sin.split(", ")
    if manifest["cobertura_efectiva"].get("gdelt_dias_por_tema_consulta_historica"):
        assert "anteriores a E0-04 (D-89)" in noticias
    sin_pub = sum(1 for r in csv.DictReader((DATA / "processed" / "noticias.csv").open(encoding="utf-8")) if not r["fecha_publicacion"])
    assert f"{sin_pub} de {manifest['cantidad_por_archivo']['noticias.csv']} noticias sin fecha_publicacion" in noticias
    assert "D-81" in filas[1]["Cobertura"]
    assert f"{manifest['cantidad_por_archivo']['indicadores.csv']} combinaciones" in filas[1]["Cobertura"]
    assert "no equivale a Panamá" in filas[2]["Cobertura"]


def test_licencias_sin_inventar(filas: list[dict[str, str]], manifest: dict) -> None:
    assert manifest["licencias"]["banco_mundial"] == filas[1]["Licencia / condiciones"]
    assert manifest["licencias"]["usgs"] == filas[2]["Licencia / condiciones"]
    assert "Pendiente de verificar" in filas[3]["Licencia / condiciones"]


def test_sbp_fuente_d_con_su_hash(filas: list[dict[str, str]], manifest: dict) -> None:
    """E3-02: la fuente D ya está en el snapshot, con la huella del CSV y las de los .xlsx que no se versionan."""
    sbp = filas[3]
    assert sbp["Etapa"] == "Etapa 3" and sbp["Modalidad"] == "Banca" and sbp["Archivo"] == "sbp_series.csv"
    assert manifest["sha256"]["processed/sbp_series.csv"] in sbp["SHA-256"]
    assert "Fuente no usada todavía" not in " ".join(sbp.values())
    assert "2026-" in sbp["Fecha de extracción"]


def test_sbp_sin_datos_queda_marcada_como_pendiente(manifest: dict, tmp_path: Path) -> None:
    sin = copy.deepcopy(manifest)
    sin["cantidad_por_archivo"].pop("sbp_series.csv")
    fila = catalogo.construir_filas(sin, DATA / "processed")[3]
    for columna in ("Cobertura", "Registros válidos", "Registros excluidos y motivo", "SHA-256"):
        assert "Fuente no usada todavía: pendiente de E3-02, solo si se activa banca" in fila[columna]


def test_valores_siguen_al_manifest(manifest: dict) -> None:
    """Si cambia el manifest, cambia el catálogo: nada va escrito a mano."""
    otro = copy.deepcopy(manifest)
    otro["sha256"]["processed/eventos.geojson"] = "0" * 64
    otro["cobertura_efectiva"]["gdelt_dias_por_tema"]["turismo"]["dias_cubiertos"] = 9
    otro["version"] = "9.9"
    otro["consultas"]["banco_mundial"]["plantilla_url"] = otro["consultas"]["banco_mundial"]["plantilla_url"].replace(
        "2010:2024", "2010:2020"
    )
    filas = catalogo.construir_filas(otro, DATA / "processed", None)
    assert "0" * 64 in filas[2]["SHA-256"]
    assert "turismo 9 de 30" in filas[0]["Cobertura"]
    assert "Snapshot v9.9" in filas[0]["Fecha de extracción"]
    assert "2010 a 2020" in filas[1]["Cobertura"] and "11 años" in filas[1]["Cobertura"]


def test_sin_reporte_lo_dice(tmp_path: Path) -> None:
    destino = tmp_path / "c.csv"
    catalogo.generar(DATA, destino, tmp_path / "no_existe.json", sin_reporte=True)
    filas = list(csv.DictReader(destino.open(encoding="utf-8")))
    assert "reporte de calidad no generado" in filas[0]["Registros válidos"]
    assert "reporte de calidad no generado" in filas[1]["Registros excluidos y motivo"]


def test_falta_el_reporte_falla_con_mensaje_claro(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"src\.carga"):
        catalogo.generar(DATA, tmp_path / "c.csv", tmp_path / "no_existe.json")
    assert catalogo.main(["--reporte", str(tmp_path / "no_existe.json"), "--salida", str(tmp_path / "c.csv")]) == 1
    assert not (tmp_path / "c.csv").exists()


def test_salida_determinista(tmp_path: Path, reporte_ruta: Path) -> None:
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    catalogo.generar(DATA, a, reporte_ruta)
    catalogo.generar(DATA, b, reporte_ruta)
    assert a.read_bytes() == b.read_bytes()


def test_sha_distinto_aborta(tmp_path: Path, manifest: dict, reporte_ruta: Path) -> None:
    datos = tmp_path / "data"
    (datos / "processed").mkdir(parents=True)
    for ruta in manifest["sha256"]:
        (datos / ruta).write_bytes(b"x")
    (datos / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="no coincide"):
        catalogo.generar(datos, tmp_path / "c.csv", reporte_ruta)
