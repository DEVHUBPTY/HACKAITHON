"""E2-01 · Últimos ajustes de la segunda revisión: X48 (las evaluaciones también exigen la modalidad), mensajes y configuración."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from eval import ia_vs_baseline, precision_at_5 as pa5, puntaje as eval_puntaje
from src import db, embeddings, interfaz as ui, prioridad
from src.configuracion import RAIZ, cargar_interfaz, cargar_modalidad, cargar_prioridad, cargar_reglas
from src.ficha import construir_ficha
from src.revision import principal as revision_main
from tests import ficha_ayuda as h
from tests.navegacion_ayuda import ir_a_pantalla
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.test_e2_01_banca import fila

CFG_UI = cargar_interfaz()
BANCA = cargar_modalidad("banca")


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base_editorial(tmp_path_factory, emb) -> Path:
    return h.construir(tmp_path_factory.mktemp("ed") / "senales.duckdb", emb)


@pytest.fixture(scope="module")
def base_banca(tmp_path_factory, emb) -> Path:
    return h.construir(tmp_path_factory.mktemp("bk") / "senales.duckdb", emb, modalidad="banca")


# ------------------------------------------------------------------ X48


def test_la_evaluacion_del_ranking_exige_una_base_editorial(base_banca, base_editorial) -> None:
    with pytest.raises(db.ModalidadDistinta, match=r"src\.puntaje --modalidad editorial"):
        ia_vs_baseline.evaluar_ranking(base_banca)
    assert ia_vs_baseline.evaluar_ranking(base_editorial)


def test_precision_at_5_exige_una_base_editorial(base_banca, base_editorial) -> None:
    con = db.conectar(base_banca, solo_lectura=True)
    with pytest.raises(db.ModalidadDistinta, match=r"src\.puntaje --modalidad editorial"):
        pa5.corte_de_base(con)
    with pytest.raises(db.ModalidadDistinta, match=r"src\.puntaje --modalidad editorial"):
        pa5.candidatos(con)
    con.close()
    con = db.conectar(base_editorial, solo_lectura=True)
    assert pa5.corte_de_base(con) and pa5.candidatos(con)
    con.close()


def test_la_evaluacion_del_puntaje_exige_una_base_editorial(base_banca) -> None:
    with pytest.raises(db.ModalidadDistinta, match=r"src\.puntaje --modalidad editorial"):
        eval_puntaje.evaluar(base_banca, cargar_reglas(), cargar_prioridad(), 1.96)


def test_ninguna_lectura_directa_de_puntajes_en_eval_ni_scripts_se_salta_la_verificacion() -> None:
    sin_verificar = []
    for carpeta in ("eval", "scripts"):
        for ruta in sorted((RAIZ / carpeta).glob("*.py")):
            texto = ruta.read_text(encoding="utf-8")
            if ("FROM puntajes" in texto or "JOIN puntajes" in texto or 'leer_tabla(con, "puntajes"' in texto) and "exigir_modalidad_de_la_base" not in texto:
                sin_verificar.append(ruta.name)
    assert sin_verificar == []


# ------------------------------------------------------------------ ficha de banca = tabla puntajes


def test_la_ficha_de_banca_coincide_con_la_tabla_puntajes(base_banca, emb, monkeypatch) -> None:
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)
    con = db.conectar(base_banca, solo_lectura=True)
    filas = con.execute("SELECT id_grupo, puntaje, rango, posicion FROM puntajes").fetchall()
    assert len(filas) == 11
    for id_grupo, puntaje, rango, posicion in filas:
        f = construir_ficha(id_grupo, "banca", con, emb=emb)
        assert (f.puntaje.puntaje, f.puntaje.rango, f.puntaje.posicion) == (pytest.approx(puntaje), rango, posicion), id_grupo
        assert f.accion_recomendada.rango == rango
    con.close()


# ------------------------------------------------------------------ CLI de revisión y app


def test_la_cli_de_revision_imprime_una_linea_de_error_y_no_un_traceback(base_banca, tmp_path, capsys) -> None:
    codigo = revision_main(["--abrir", h.G_COMPLETO, "--revisor", "Javier Acosta", "--modalidad", "editorial", "--base", str(base_banca), "--revision", str(tmp_path / "r.duckdb")])
    err = capsys.readouterr().err
    assert codigo == 1 and err.startswith("ERROR: ") and "src.puntaje --modalidad editorial" in err and "Traceback" not in err


@pytest.fixture
def app_editorial(monkeypatch, base_editorial, emb, tmp_path):
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (base_editorial, None))
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)


def test_banca_se_calcula_sola_en_una_copia_de_sesion_y_el_mensaje_conserva_el_comando(app_editorial) -> None:
    """D-132: la base guarda una modalidad; la app puntúa la otra en una copia de sesión, así que ya no pide correr el comando.

    El comando sigue en el texto de ``sin_puntajes`` (para una modalidad sin puntajes); aquí se prueba que la bandeja se llena y se avisa.
    """
    from src.configuracion import cargar_corrida

    assert "poetry run python -m src.puntaje --modalidad {modalidad}" in CFG_UI.textos.sin_puntajes
    at = app_editorial.run()
    at.selectbox(key="modalidad").select("banca").run()
    at = ir_a_pantalla(at, "bandeja")
    assert not at.exception
    aviso = cargar_corrida().textos.aviso_copia_modalidad.format(modalidad="Banca")
    assert any(aviso in str(c.value) for c in at.caption)
    assert not any("poetry run python -m src.puntaje" in str(i.value) for i in at.info)
    assert len(at.dataframe) > 0


# ------------------------------------------------------------------ configuración


def test_el_ancho_del_titular_impreso_vive_en_la_configuracion() -> None:
    ancho = CFG_UI.bandeja.ancho_titular_cli
    assert ancho >= 10
    larga = fila("GRP-a", 1, 80, "logística")
    larga = larga.__class__(**{**larga.__dict__, "titular": "x" * (ancho + 30)})
    lineas = ui.lineas_de_bandeja([larga], BANCA)
    assert lineas[1].endswith("x" * ancho) and not lineas[1].endswith("x" * (ancho + 1))
    assert not hasattr(ui, "ANCHO_TITULAR_EN_LINEA")
