"""Pruebas offline de la carga de configuración validada (D-79)."""

from pathlib import Path

import pytest
import yaml

from src.configuracion import ConfigFuentes, ErrorDeConfiguracion, cargar_config, cargar_fuentes


@pytest.fixture
def datos() -> dict:
    return yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "fuentes.yaml").read_text("utf-8"))


def escribir(tmp_path: Path, datos: dict) -> Path:
    (tmp_path / "fuentes.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    return tmp_path


def test_fuentes_yaml_real_es_valido() -> None:
    c = cargar_fuentes()
    assert c.banco_mundial.paises == ["PAN", "CRI", "COL", "DOM", "MEX", "GTM"]
    assert c.gdelt.maxrecords == 250


def test_clave_desconocida_falla(tmp_path: Path, datos: dict) -> None:
    datos["gdelt"]["maxrecord"] = 5  # errata
    with pytest.raises(ErrorDeConfiguracion, match=r"fuentes\.yaml.*gdelt\.maxrecord"):
        cargar_fuentes(escribir(tmp_path, datos))


def test_tipo_incorrecto_falla(tmp_path: Path, datos: dict) -> None:
    datos["gdelt"]["maxrecords"] = "250"  # cadena donde va un entero
    with pytest.raises(ErrorDeConfiguracion, match=r"gdelt\.maxrecords"):
        cargar_fuentes(escribir(tmp_path, datos))


def test_trampa_no_yaml_como_booleano_en_codigo_de_pais(tmp_path: Path, datos: dict) -> None:
    ruta = escribir(tmp_path, datos)
    texto = (ruta / "fuentes.yaml").read_text("utf-8").replace("- PAN\n", "- NO\n", 1)
    (ruta / "fuentes.yaml").write_text(texto, encoding="utf-8")
    assert yaml.safe_load(texto)["banco_mundial"]["paises"][0] is False  # YAML 1.1: NO -> False
    with pytest.raises(ErrorDeConfiguracion, match=r"banco_mundial\.paises\.0"):
        cargar_fuentes(ruta)


def test_clave_obligatoria_ausente_falla(tmp_path: Path, datos: dict) -> None:
    del datos["usgs"]["endpoint"]
    with pytest.raises(ErrorDeConfiguracion, match=r"usgs\.endpoint"):
        cargar_fuentes(escribir(tmp_path, datos))


def test_archivo_inexistente_o_yaml_roto(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeConfiguracion, match="no se pudo leer"):
        cargar_config("fuentes", ConfigFuentes, tmp_path)
    (tmp_path / "fuentes.yaml").write_text("a: [sin cerrar", encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match="YAML inválido"):
        cargar_config("fuentes", ConfigFuentes, tmp_path)
