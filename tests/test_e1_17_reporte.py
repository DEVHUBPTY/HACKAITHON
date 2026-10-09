"""E1-17: el reporte de pruebas tiene las columnas de la base *Pruebas* de Notion y refleja lo observado."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from eval import reporte_pruebas as rp
from src.configuracion import RAIZ, ErrorDeConfiguracion, cargar_pruebas, validar_todo

PLANTILLA = RAIZ / "notion" / "bases" / "Pruebas.csv"
CORRIDA = {"ejecutado_utc": "2026-10-07T12:00:00Z", "commit": "abc1234"}


def _resultado(total: int = 3, fallidas: int = 0, errores: int = 0, omitidas: int = 0) -> rp.ResultadoPrueba:
    return rp.ResultadoPrueba(total=total, fallidas=fallidas, errores=errores, omitidas=omitidas)


def _todos(**kw: int) -> dict[str, rp.ResultadoPrueba]:
    return {f"T{n:02d}": _resultado(**kw) for n in range(1, 11)}


def test_las_columnas_son_las_de_la_base_de_notion() -> None:
    with PLANTILLA.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == list(rp.COLUMNAS)


def test_la_plantilla_tiene_exactamente_t01_a_t10() -> None:
    assert [f["ID"] for f in rp.leer_plantilla(PLANTILLA)] == [f"T{n:02d}" for n in range(1, 11)]


def test_una_prueba_que_pasa_queda_en_pasa_con_su_evidencia() -> None:
    filas = rp.construir_filas(rp.leer_plantilla(PLANTILLA), _todos(), {}, **CORRIDA)
    t01 = filas[0]
    assert t01["Estado"] == "Pasa" and "3 de 3" in t01["Resultado observado"]
    assert "-m t01" in t01["Evidencia de ejecución"]
    assert t01["Archivo de test"] == "tests/test_t01_carga.py"


def test_una_prueba_que_falla_queda_en_falla_y_nunca_en_pasa() -> None:
    res = _todos() | {"T05": _resultado(total=4, fallidas=1)}
    filas = {f["ID"]: f for f in rp.construir_filas(rp.leer_plantilla(PLANTILLA), res, {}, **CORRIDA)}
    assert filas["T05"]["Estado"] == "Falla" and "1 fallida" in filas["T05"]["Resultado observado"]
    assert filas["T04"]["Estado"] == "Pasa"


def test_un_error_de_coleccion_o_cero_pruebas_no_cuenta_como_pasa() -> None:
    res = _todos() | {"T02": _resultado(total=0), "T03": _resultado(errores=1)}
    filas = {f["ID"]: f for f in rp.construir_filas(rp.leer_plantilla(PLANTILLA), res, {}, **CORRIDA)}
    assert filas["T02"]["Estado"] == "Falla" and filas["T03"]["Estado"] == "Falla"


def test_la_parte_humana_pendiente_deja_la_prueba_en_pendiente_aunque_el_test_pase() -> None:
    pend = {"T10": "ensayo C-04 con Wi-Fi apagado: lo hace una persona"}
    filas = {f["ID"]: f for f in rp.construir_filas(rp.leer_plantilla(PLANTILLA), _todos(), pend, **CORRIDA)}
    assert filas["T10"]["Estado"] == "Pendiente" and "C-04" in filas["T10"]["Resultado observado"]
    assert "3 de 3" in filas["T10"]["Resultado observado"]


def test_una_prueba_omitida_no_cuenta_como_pasada() -> None:
    filas = rp.construir_filas(rp.leer_plantilla(PLANTILLA), _todos(total=3, omitidas=3), {}, **CORRIDA)
    assert filas[0]["Estado"] == "Falla"


def test_el_csv_escrito_se_puede_releer_con_las_mismas_columnas(tmp_path: Path) -> None:
    filas = rp.construir_filas(rp.leer_plantilla(PLANTILLA), _todos(), {}, **CORRIDA)
    destino = tmp_path / "pruebas.csv"
    rp.escribir_csv(filas, destino)
    with destino.open(encoding="utf-8", newline="") as f:
        leidas = list(csv.DictReader(f))
    assert list(leidas[0]) == list(rp.COLUMNAS) and len(leidas) == 10


def test_el_resultado_de_un_junit_se_cuenta_bien(tmp_path: Path) -> None:
    xml = tmp_path / "j.xml"
    xml.write_text('<testsuites><testsuite tests="5" failures="1" errors="1" skipped="1"/></testsuites>', encoding="utf-8")
    assert rp.leer_junit(xml) == rp.ResultadoPrueba(total=5, fallidas=1, errores=1, omitidas=1)
    with pytest.raises(ValueError):
        xml.write_text("<nada/>", encoding="utf-8")
        rp.leer_junit(xml)


def test_la_evidencia_lleva_comando_fecha_utc_y_commit() -> None:
    (t01, *_) = rp.construir_filas(rp.leer_plantilla(PLANTILLA), _todos(), {}, **CORRIDA)
    ev = t01["Evidencia de ejecución"]
    assert "-m t01" in ev and "2026-10-07T12:00:00Z" in ev and "abc1234" in ev


def test_la_fecha_de_ejecucion_es_utc_iso_8601_y_el_commit_es_un_sha() -> None:
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", rp.ahora_utc())
    assert re.fullmatch(r"[0-9a-f]{7,40}(\+sin-confirmar)?", rp.commit_actual())


def test_los_pendientes_salen_de_la_configuracion_y_nombran_su_causa() -> None:
    pend = cargar_pruebas().pendientes
    assert set(pend) == {"T10"} and "ensayo con Wi-Fi apagado" in pend["T10"]  # T09 se cerró con E2-02 (tests/test_t09_borrador.py cubre el boletín bancario)
    assert rp.PENDIENTES == pend


def test_la_configuracion_de_pruebas_prohibe_claves_desconocidas_e_ids_ajenos(tmp_path: Path) -> None:
    (tmp_path / "pruebas.yaml").write_text("pendientes:\n  T09: x\nextra: 1\n", encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion):
        cargar_pruebas(tmp_path)
    (tmp_path / "pruebas.yaml").write_text("pendientes:\n  T99: x\n", encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion):
        cargar_pruebas(tmp_path)


def test_el_yaml_de_pruebas_esta_registrado_en_la_validacion_global() -> None:
    assert "pruebas" in validar_todo()
