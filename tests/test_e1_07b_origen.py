"""E1-07b: procedencia de las etiquetas (humano | asistente_provisional, D-101) y diagnóstico en tres vías."""

import csv
from pathlib import Path
from typing import Any

import pytest

from eval import agrupacion as evagrupacion
from eval import clasificacion as evalclas
from eval import diagnostico_temas as dg
from eval import etiquetar
from eval import origen_etiquetas as oe
from eval import ruido as evruido
from src.configuracion import cargar_temas

COLUMNAS = ("id_noticia", "tema_principal", "ruido", "grupo", "alcance_regional", "origen")


def _csv(ruta: Path, filas: list[dict[str, str]], columnas: tuple[str, ...] = COLUMNAS) -> Path:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    return ruta


MIXTO = [
    {"id_noticia": "NOT-H1", "tema_principal": "economia", "ruido": "ninguno", "grupo": "g-a", "alcance_regional": "si", "origen": "humano"},
    {"id_noticia": "NOT-H2", "tema_principal": "", "ruido": "no_es_panama", "grupo": "", "alcance_regional": "", "origen": "humano"},
    {"id_noticia": "NOT-P1", "tema_principal": "turismo", "ruido": "ninguno", "grupo": "g-p", "alcance_regional": "", "origen": "asistente_provisional"},
    {"id_noticia": "NOT-P2", "tema_principal": "", "ruido": "fuera_de_temas", "grupo": "g-p", "alcance_regional": "", "origen": "asistente_provisional"},
]


# ------------------------------------------------------------------ el lector filtra y valida la procedencia


def test_por_defecto_solo_se_leen_las_etiquetas_humanas(tmp_path: Path) -> None:
    filas = oe.leer_filas(_csv(tmp_path / "e.csv", MIXTO))
    assert [f["id_noticia"] for f in filas] == ["NOT-H1", "NOT-H2"]


def test_se_pueden_pedir_las_provisionales_solas_o_todas(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO)
    assert [f["id_noticia"] for f in oe.leer_filas(ruta, (oe.ASISTENTE_PROVISIONAL,))] == ["NOT-P1", "NOT-P2"]
    assert len(oe.leer_filas(ruta, oe.ORIGENES)) == 4


def test_un_origen_desconocido_se_rechaza_con_el_id(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", [{**MIXTO[0], "origen": "robot"}])
    with pytest.raises(ValueError, match=r"NOT-H1.*robot"):
        oe.leer_filas(ruta)


def test_un_origen_vacio_se_rechaza_si_la_columna_existe(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="origen"):
        oe.leer_filas(_csv(tmp_path / "e.csv", [{**MIXTO[0], "origen": ""}]))


def test_sin_columna_origen_todo_es_humano_pero_no_se_pueden_pedir_provisionales(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO, tuple(c for c in COLUMNAS if c != "origen"))
    assert len(oe.leer_filas(ruta)) == 4
    with pytest.raises(ValueError, match="origen"):
        oe.leer_filas(ruta, (oe.ASISTENTE_PROVISIONAL,))


def test_pedir_un_origen_inexistente_falla() -> None:
    with pytest.raises(ValueError, match="robot"):
        oe.validar_origenes(("robot",))


def test_el_csv_real_marca_todas_sus_filas_y_las_provisionales_son_61() -> None:
    todas = oe.leer_filas(evalclas.ETIQUETAS, oe.ORIGENES)
    cuenta = {o: sum(1 for f in todas if f["origen"] == o) for o in oe.ORIGENES}
    assert cuenta == {oe.HUMANO: 100, oe.ASISTENTE_PROVISIONAL: 61}
    assert len({f["id_noticia"] for f in todas}) == 161


def test_ninguna_etiqueta_usa_un_titular_de_los_ejemplos_excluidos() -> None:
    ids = {f["id_noticia"] for f in oe.leer_filas(evalclas.ETIQUETAS, oe.ORIGENES)}
    assert not ids & evalclas.ids_excluidos()


# ------------------------------------------------------------------ los demás lectores no mezclan provisionales sin pedirlo


def test_leer_etiquetas_de_clasificacion_excluye_provisionales_por_defecto(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO)
    temas = cargar_temas()
    assert set(evalclas.leer_etiquetas(ruta, "tema_principal", temas)) == {"NOT-H1", "NOT-H2"}
    todas = evalclas.leer_etiquetas(ruta, "tema_principal", temas, origenes=oe.ORIGENES)
    assert set(todas) == {"NOT-H1", "NOT-H2", "NOT-P1", "NOT-P2"}


def test_ruido_y_agrupacion_tambien_leen_solo_humanos_por_defecto(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO)
    assert set(evruido.leer_etiquetas(ruta, "ruido")) == {"NOT-H1", "NOT-H2"}
    assert set(evruido.leer_regional(ruta) or {}) == {"NOT-H1", "NOT-H2"}
    assert set(evagrupacion.leer_grupos_humanos(ruta)) == {"NOT-H1", "NOT-H2"}


def test_el_consolidado_de_etiquetar_declara_la_columna_origen() -> None:
    assert "origen" in etiquetar.COLUMNAS_CONSOLIDADO


# ------------------------------------------------------------------ diagnóstico en tres vías


class _Informe(dict):
    pass


def _falso_diagnosticar(monkeypatch: pytest.MonkeyPatch, evaluados: dict[tuple[str, ...], int]) -> list[tuple[str, ...]]:
    llamadas: list[tuple[str, ...]] = []

    def falso(ruta, base, cfg, temas, motores=None, origenes=(oe.HUMANO,)) -> dict[str, Any]:
        llamadas.append(tuple(origenes))
        return {"conjunto": {"evaluados": evaluados[tuple(origenes)], "eventos": 3, "etiquetados_en_csv": 0}, "origenes": list(origenes)}

    monkeypatch.setattr(dg, "diagnosticar", falso)
    return llamadas


def test_el_informe_en_tres_vias_reporta_humano_provisional_y_combinado(monkeypatch: pytest.MonkeyPatch) -> None:
    h, p = (oe.HUMANO,), (oe.ASISTENTE_PROVISIONAL,)
    llamadas = _falso_diagnosticar(monkeypatch, {h: 63, p: 15, h + p: 78})
    informe = dg.diagnosticar_en_tres_vias(Path("e.csv"), Path("b.duckdb"), None, None)
    assert set(informe["vias"]) == {"humano", "asistente_provisional", "combinado"}
    assert llamadas == [h, p, (oe.HUMANO, oe.ASISTENTE_PROVISIONAL)]
    assert informe["vias"]["humano"]["usa_etiquetas_provisionales"] is False
    assert informe["vias"]["asistente_provisional"]["usa_etiquetas_provisionales"] is True
    assert informe["vias"]["combinado"]["usa_etiquetas_provisionales"] is True
    assert "D-101" in informe["vias"]["combinado"]["aviso"] and "D-101" in informe["vias"]["asistente_provisional"]["aviso"]
    assert "D-101" not in informe["vias"]["humano"]["aviso"]


def test_una_via_con_pocas_filas_o_eventos_no_se_calcula_y_lo_dice(monkeypatch: pytest.MonkeyPatch) -> None:
    h, p = (oe.HUMANO,), (oe.ASISTENTE_PROVISIONAL,)
    _falso_diagnosticar(monkeypatch, {h: 63, p: 2, h + p: 65})

    def pocas(ruta, base, cfg, temas, motores=None, origenes=(oe.HUMANO,)):
        if tuple(origenes) == p:
            raise dg.EtiquetasInsuficientes(2, 2)
        return {"conjunto": {"evaluados": 63}}

    monkeypatch.setattr(dg, "diagnosticar", pocas)
    informe = dg.diagnosticar_en_tres_vias(Path("e.csv"), Path("b.duckdb"), None, None)
    via = informe["vias"]["asistente_provisional"]
    assert via["estado"] == "INSUFICIENTE" and via["evaluados"] == 2 and "diagnostico" not in via
    assert informe["vias"]["humano"]["estado"] == "CALCULADO"


def test_validar_hoja_solo_valida_las_filas_humanas_del_consolidado(tmp_path: Path) -> None:
    """Una fila provisional (otro contrato: no es de una persona ni de la muestra de E1-06) no ensucia ``--validar``."""
    cfg, temas = etiquetar.cargar_etiquetado(), cargar_temas()
    humana = {
        "id_noticia": "NOT-H1", "titulo": "t", "tema_principal": "economia", "tema_secundario": "", "ruido": "ninguno", "grupo": "",
        "alcance_regional": "", "nota": "n", "etiquetado_por": "Javier Acosta", "fecha_etiquetado": "2026-10-06T19:03:29Z",
        "estrato": "no_ruido", "peso_muestreo": "1", "n_etiquetadores": "1", "origen": "humano",
    }
    provisional = {**humana, "id_noticia": "NOT-P1", "etiquetado_por": "Asistente provisional", "origen": "asistente_provisional"}
    ruta = _csv(tmp_path / "c.csv", [humana, provisional], etiquetar.COLUMNAS_CONSOLIDADO)
    assert etiquetar.validar_hoja(ruta, cfg, temas, {"NOT-H1"}) == []
