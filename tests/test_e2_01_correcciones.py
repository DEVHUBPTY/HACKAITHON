"""E2-01 · Correcciones de la revisión independiente: X39 (modalidad guardada), X40 (filas por sector) y menores."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import streamlit as st
import yaml
from streamlit.testing.v1 import AppTest

from src import db, embeddings, generacion, interfaz as ui, prioridad
from src.configuracion import RAIZ, ErrorDeConfiguracion, cargar_interfaz, cargar_modalidad, cargar_prioridad, cargar_verificacion
from src.ficha import construir_ficha
from src.revision import Revisiones
from tests import ficha_ayuda as h
from tests.navegacion_ayuda import ir_a_pantalla
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.test_e2_01_banca import cargar_variante, datos_banca, fila

BANCA = cargar_modalidad("banca")
CFG_UI = cargar_interfaz()


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base_editorial(tmp_path_factory, emb) -> Path:
    return h.construir(tmp_path_factory.mktemp("ed") / "senales.duckdb", emb)


@pytest.fixture(scope="module")
def base_banca(tmp_path_factory, emb) -> Path:
    carpeta = tmp_path_factory.mktemp("bk")
    ruta = h.construir(carpeta / "senales.duckdb", emb)
    prioridad.ejecutar(ruta, carpeta / "p.json", h.CORTE, None, "banca", emb=emb)
    return ruta


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch, emb):
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)


def abrir(ruta: Path):
    return db.conectar(ruta, solo_lectura=True)


# ------------------------------------------------------------------ X39 · la modalidad guardada debe ser la pedida


def test_la_ficha_editorial_sobre_una_corrida_bancaria_falla_con_un_error_claro(base_banca, emb) -> None:
    con = abrir(base_banca)
    with pytest.raises(db.ModalidadDistinta, match=r"src\.puntaje --modalidad editorial") as e:
        construir_ficha(h.G_COMPLETO, "editorial", con, emb=emb)
    assert "banca" in str(e.value) and not isinstance(e.value, LookupError)
    assert construir_ficha(h.G_COMPLETO, "banca", con, emb=emb).modalidad == "banca"
    con.close()


def test_la_ficha_bancaria_sobre_una_corrida_editorial_falla_igual(base_editorial, emb) -> None:
    con = abrir(base_editorial)
    with pytest.raises(db.ModalidadDistinta, match=r"src\.puntaje --modalidad banca"):
        construir_ficha(h.G_COMPLETO, "banca", con, emb=emb)
    con.close()


def test_la_entrada_de_la_generacion_no_mezcla_modalidades(base_banca) -> None:
    with pytest.raises(db.ModalidadDistinta, match="--modalidad editorial"):
        generacion._entrada_desde_grupo(h.G_COMPLETO, "editorial", base_banca)


def test_abrir_un_caso_no_mezcla_modalidades_ni_lo_disfraza_de_grupo_inexistente(base_banca, tmp_path) -> None:
    rev = Revisiones(tmp_path / "revision.duckdb", base_banca)
    with pytest.raises(db.ModalidadDistinta, match="--modalidad editorial"):
        rev.abrir(h.G_COMPLETO, "editorial", "Javier Acosta")
    assert rev.caso_de_grupo(h.G_COMPLETO, "editorial") is None          # no quedó ningún caso ni ficha guardada


def test_la_bandeja_de_otra_modalidad_sigue_vacia_y_no_mezcla(base_banca) -> None:
    con = abrir(base_banca)
    assert ui.leer_bandeja(con, "editorial") == []
    assert ui.leer_bandeja(con, "banca")
    con.close()


# ------------------------------------------------------------------ X40 · filas por sector, no por bandeja


def test_limitar_por_sector_conserva_todos_los_sectores_y_recorta_cada_uno() -> None:
    filas = [fila(f"GRP-e{i}", i, 90 - i, "economía") for i in range(1, 9)] + [fila("GRP-l1", 9, 60, "logística"), fila("GRP-l2", 10, 59, "logística"), fila("GRP-t1", 11, 50, "turismo")]
    bloques = ui.limitar_por_sector(ui.agrupar_por_sector(filas, BANCA), 3)
    assert [b.sector for b in bloques] == ["economía", "logística", "turismo"]          # ningún sector se oculta
    assert [len(b.filas) for b in bloques] == [3, 2, 1] and [b.total for b in bloques] == [8, 2, 1]
    assert [f.id_grupo for f in bloques[0].filas] == ["GRP-e1", "GRP-e2", "GRP-e3"]     # las primeras de E1-10


def test_el_limite_por_sector_vive_en_la_configuracion() -> None:
    assert CFG_UI.bandeja.filas_iniciales_por_sector >= 1


@pytest.fixture
def app_banca(monkeypatch, base_banca, emb, tmp_path):
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (base_banca, None))
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)


def test_la_pantalla_agrupa_primero_y_limita_despues_por_sector(app_banca) -> None:
    at = app_banca.run()
    at.selectbox(key="modalidad").select("banca").run()
    at = ir_a_pantalla(at, "bandeja")
    assert not at.exception
    etiquetas = {BANCA.bandeja.etiquetas_sector[s] for s in ("economía", "logística", "continuidad operativa")}
    assert etiquetas <= {s.value for s in at.subheader}
    assert all(len(t.value) <= CFG_UI.bandeja.filas_iniciales_por_sector for t in at.dataframe)
    horizontes = {x for t in at.dataframe for x in t.value["Horizonte"]}
    assert horizontes and horizontes <= set(BANCA.horizonte.etiquetas.values())          # se muestra la etiqueta del YAML, no el código


# ------------------------------------------------------------------ menores


def test_las_etiquetas_de_sector_y_horizonte_vienen_del_yaml() -> None:
    assert BANCA.horizonte.etiquetas == {"inmediato": "Inmediato", "corto plazo": "Corto plazo", "estructural": "Estructural"}
    assert BANCA.bandeja.etiquetas_sector["continuidad operativa"] == "Continuidad operativa"
    filas = [fila("GRP-a", 1, 80, "logística")]
    assert ui.agrupar_por_sector(filas, BANCA)[0].etiqueta == BANCA.bandeja.etiquetas_sector["logística"]


def test_faltar_una_etiqueta_se_rechaza(tmp_path: Path) -> None:
    d = datos_banca()
    del d["bandeja"]["etiquetas_sector"]["turismo"]
    with pytest.raises(ErrorDeConfiguracion, match="turismo"):
        cargar_variante(tmp_path, d)
    d = datos_banca()
    del d["horizonte"]["etiquetas"]["estructural"]
    with pytest.raises(ErrorDeConfiguracion, match="estructural"):
        cargar_variante(tmp_path, d)


def test_las_lineas_de_la_bandeja_por_sector_salen_de_la_configuracion() -> None:
    filas = [fila("GRP-a", 1, 80, "logística", "corto plazo"), fila("GRP-b", 2, 70, None)]
    texto = "\n".join(ui.lineas_de_bandeja(filas, BANCA))
    assert "Logística" in texto and BANCA.bandeja.sin_sector in texto and "GRP-a" in texto and "Corto plazo" in texto
    assert ui.lineas_de_bandeja(filas, cargar_modalidad("editorial")) is None


def test_la_cli_imprime_la_bandeja_agrupada_por_sector(monkeypatch, base_banca, caplog) -> None:
    reporte = {"grupos": 1, "version_reglas": "1.3", "fecha_referencia": "x", "por_rango": {}, "por_estado_de_evidencia": {},
               "contradicciones": {"por_nota_llm": {}}, "llm": {"estado": "x"}, "ranking": []}
    monkeypatch.setattr(prioridad, "ejecutar", lambda *a, **k: reporte)
    with caplog.at_level(logging.INFO):
        assert prioridad.main(["--base", str(base_banca), "--ahora", "2026-10-06T12:00:00Z", "--modalidad", "banca", "--sin-llm"]) == 0
    texto = caplog.text
    assert "Economía" in texto and "Continuidad operativa" in texto and h.G_COMPLETO in texto


def test_un_grupo_sin_sector_no_reusa_el_texto_del_tema_desconocido() -> None:
    from src.puntaje import impacto
    from tests import prioridad_ayuda as pa
    import dataclasses

    _, vacios = impacto(pa.entrada("GRP-a", tema=None), pa.REGLAS, pa.CFG, BANCA)
    assert [v.codigo for v in vacios] == ["sector_desconocido"]
    assert "tema no determinado" not in vacios[0].texto.lower() and vacios[0].texto != cargar_prioridad().vacios.tema_desconocido
    assert "sector_desconocido" in cargar_verificacion().vacios.catalogo
