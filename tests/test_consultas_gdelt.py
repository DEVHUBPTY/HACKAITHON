"""Consultas de GDELT por tema y pata (E0-04, seguimiento). Sin red: solo arma y compara texto."""

import json
from pathlib import Path

import pytest
import requests

from scripts import estimar_consultas_gdelt
from src import configuracion, consultas_gdelt

PATA_LOCAL = {"filtros": ["sourcecountry:panama"], "terminos": ["puerto", "Zona Libre"]}
PATA_INTER = {"filtros": ["-sourcecountry:panama"], "terminos": ["Panama Canal", "Canal de Panamá"]}


def test_or_en_parentesis_frases_entre_comillas_y_filtro() -> None:
    assert consultas_gdelt.construir_consulta(PATA_LOCAL) == '(puerto OR "Zona Libre") sourcecountry:panama'
    assert (
        consultas_gdelt.construir_consulta(PATA_INTER)
        == '("Panama Canal" OR "Canal de Panamá") -sourcecountry:panama'
    )


def test_un_solo_termino_no_lleva_parentesis() -> None:
    assert consultas_gdelt.construir_consulta({"filtros": [], "terminos": ["Sinaproc"]}) == "Sinaproc"


@pytest.mark.parametrize("malo", ["", "OR", "a (b)", 'dos "comillas"', "ab"])
def test_terminos_invalidos_se_rechazan(malo: str) -> None:
    with pytest.raises(ValueError):
        consultas_gdelt.construir_consulta({"filtros": [], "terminos": [malo]})


def test_url_codifica_comillas_parentesis_y_operadores(config: dict) -> None:
    q = consultas_gdelt.construir_consulta(PATA_INTER)
    params = {"query": q, "mode": "ArtList", "format": "json", "startdatetime": "20261001000000"}
    url = requests.Request("GET", config["gdelt"]["endpoint"], params=params).prepare().url
    assert "%22Panama+Canal%22" in url and "%28" in url and "-sourcecountry%3Apanama" in url
    assert '"' not in url and " " not in url


def test_cada_tema_tiene_pata_local_con_sourcecountry_y_pata_internacional_que_la_excluye(config: dict) -> None:
    for tema, patas in config["gdelt"]["consultas"].items():
        assert set(patas) == {"locales", "internacional"}, tema
        assert patas["locales"]["filtros"] == ["sourcecountry:panama"]
        assert patas["internacional"]["filtros"] == ["-sourcecountry:panama"]


def test_la_pata_internacional_nunca_usa_panama_suelto_con_un_sustantivo_generico(config: dict) -> None:
    for patas in config["gdelt"]["consultas"].values():
        for t in patas["internacional"]["terminos"]:
            assert " " in t, f"{t!r}: debe ser una frase"
            assert t.lower() != "panama", t


def test_dos_patas_por_tema_son_pocas_llamadas(config: dict) -> None:
    armadas = consultas_gdelt.construir_consultas(config["gdelt"]["consultas"])
    assert len(armadas) == 2 * len(config["gdelt"]["consultas"])
    assert {t for t, _, _ in armadas} == {"logistica", "turismo", "economia", "eventos_naturales"}  # D-62


def test_formato_antiguo_sigue_siendo_una_consulta_sin_pata() -> None:
    assert consultas_gdelt.construir_consultas({"economia": "Panama economy"}) == [("economia", None, "Panama economy")]
    assert consultas_gdelt.consultas_por_tema({"economia": "q"}) == {"economia": "q"}


def test_el_modelo_estricto_rechaza_un_termino_invalido(tmp_path: Path) -> None:
    import yaml

    datos = yaml.safe_load((configuracion.CARPETA_CONFIG / "fuentes.yaml").read_text("utf-8"))
    datos["gdelt"]["consultas"]["turismo"]["locales"]["terminos"].append("a (b OR c)")
    (tmp_path / "fuentes.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), "utf-8")
    with pytest.raises(configuracion.ErrorDeConfiguracion, match="término inválido"):
        configuracion.cargar_fuentes(tmp_path)


def test_titulo_coincide_ignora_tildes_y_exige_palabra_completa() -> None:
    assert consultas_gdelt.titulo_coincide("Reabre el CANAL DE PANAMA al tráfico", ["Canal de Panamá"])
    assert not consultas_gdelt.titulo_coincide("Panama City Beach hotel", ["Panama tourism"])
    assert not consultas_gdelt.titulo_coincide("Transporte de cargas", ["carga"])


def test_estimacion_offline_sobre_crudos_sinteticos(tmp_path: Path, config: dict) -> None:
    arts = [
        {"url": "u1", "title": "Panama Canal reopens", "sourcecountry": "United States"},
        {"url": "u2", "title": "Panama City Beach port closed", "sourcecountry": "United States"},
        {"url": "u3", "title": "Nuevo puerto en Colón", "sourcecountry": "Panama"},
        {"url": "u3", "title": "Nuevo puerto en Colón", "sourcecountry": "Panama"},  # duplicado
    ]
    (tmp_path / "gdelt_logistica_20261004000000_20261006000000_20261006T165223Z.json").write_text(
        json.dumps({"articles": arts}), "utf-8"
    )
    res = estimar_consultas_gdelt.estimar(
        estimar_consultas_gdelt.leer_articulos(tmp_path), config["gdelt"]["consultas"]
    )["logistica"]
    assert res["n_articulos_unicos"] == 3
    assert res["habrian_pasado_aprox"] == 2  # u1 (frase internacional) y u3 (medio de Panamá + 'puerto')
    assert res["fraccion_que_habria_pasado"] == pytest.approx(2 / 3, abs=1e-3)
