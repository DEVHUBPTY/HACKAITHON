"""D-133 · Cada pantalla tiene su propia URL: navegar de verdad (atrás/adelante, recarga, enlaces) y conservar el estado.

Corre con ``AppTest`` sobre la base sintética de E1-10b, sin red ni modelo real (consultor y embeddings falsos).
"""

from __future__ import annotations

import copy

import pytest
import streamlit as st
import yaml
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from src import db, embeddings, interfaz as ui
from src.configuracion import RAIZ, ConfigInterfaz, cargar_interfaz
from tests import consulta_fixture, ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.navegacion_ayuda import ir_a_pantalla, seguir, url_actual

CFG = cargar_interfaz()
APP = RAIZ / "app.py"
URLS = {"inicio": "", "calidad": "cargar", "organizar": "organizar", "contextualizar": "contextualizar", "bandeja": "priorizar",
        "ficha": "explicar", "paquete": "producir", "revision": "revisar", "consulta": "consulta"}
PREGUNTA = "¿Cuál fue el desempleo de Panamá en 2023?"


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base(tmp_path_factory, emb):
    ruta = h.construir(tmp_path_factory.mktemp("d133") / "senales.duckdb", emb)
    con = db.conectar(ruta)
    db.insertar(con, "indicadores", [{
        "id_indicador": "IND-PAN-SL.UEM.TOTL.ZS-2023", "pais_iso3": "PAN", "indicador_id": "SL.UEM.TOTL.ZS", "anio": 2023, "valor": None,
        "unidad": "%", "fuente_url": "https://api.worldbank.org/x", "fecha_extraccion": "2026-10-06T12:00:00Z", "licencia": "CC BY 4.0",
    }])
    con.close()
    return ruta


@pytest.fixture
def app(monkeypatch, base, emb, tmp_path):
    consultor, _ = consulta_fixture.crear_consultor(tmp_path / "consulta")
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (base, None))
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)
    monkeypatch.setattr("src.consulta.crear_consultor", lambda ruta, *a, **k: consultor)
    monkeypatch.setattr(ui, "reporte_de_carga", lambda *a, **k: {
        "archivos": {"noticias.csv": {"leidas": 10, "validas": 8, "rechazadas": 2}},
        "distribucion_noticias_validas": {"por_medio": {"TVN Panamá": 5, "La Prensa": 3}},
    })
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(APP), default_timeout=90)


# ------------------------------------------------------------------ configuración y ayudas puras


def test_el_mapa_de_urls_es_el_acordado_y_se_puede_invertir() -> None:
    assert {k: ui.url_de_pantalla(CFG, k) for k in URLS} == URLS
    assert all(ui.clave_de_url(CFG, u) == k for k, u in URLS.items())
    assert ui.clave_de_url(CFG, "no-existe") == "inicio"      # una ruta desconocida cae en «Cómo funciona»


def test_dos_pantallas_no_pueden_compartir_url_ni_repetir_la_raiz() -> None:
    datos = yaml.safe_load((RAIZ / "config" / "interfaz.yaml").read_text(encoding="utf-8"))
    repetida = copy.deepcopy(datos)
    repetida["pantallas"][1]["url_path"] = repetida["pantallas"][0]["url_path"]
    with pytest.raises(ValidationError, match="URL distinta"):
        ConfigInterfaz.model_validate(repetida)
    mayuscula = copy.deepcopy(datos)
    mayuscula["pantallas"][0]["url_path"] = "Cargar"
    with pytest.raises(ValidationError):
        ConfigInterfaz.model_validate(mayuscula)


def test_solo_se_conservan_los_widgets_declarados() -> None:
    sesion = ["consulta_texto", "peso_R", "revision_texto_2_x", "consulta_boton", "consulta_ejemplo_0", "pantalla", "revision_abrir", "id_grupo"]
    assert ui.claves_a_conservar(CFG, sesion) == ["consulta_texto", "peso_R", "revision_texto_2_x"]      # los botones nunca se tocan


# ------------------------------------------------------------------ cada página tiene su URL y abre


@pytest.mark.parametrize("clave", list(URLS))
def test_cada_pagina_abre_sin_errores_en_su_url(app, clave) -> None:
    at = ir_a_pantalla(app, clave)
    assert not at.exception, [e.value for e in at.exception]
    assert url_actual(at) == URLS[clave] and at.session_state["pantalla"] == clave
    esperado = CFG.inicio.titulo if clave == "inicio" else next(p.titulo for p in CFG.pantallas if p.clave == clave)
    assert at.header[0].value == esperado


def test_la_barra_lateral_conserva_su_forma(app) -> None:
    at = ir_a_pantalla(app, "bandeja")
    assert [b.label for b in at.sidebar.button] == ["Cómo funciona", "Consulta"]
    assert at.radio(key="pantalla_etapa").value == "bandeja"
    assert at.sidebar.selectbox[0].label == "Modalidad"


# ------------------------------------------------------------------ navegar cambia la URL


def test_los_botones_de_etapa_anterior_y_siguiente_cambian_la_url(app) -> None:
    at = ir_a_pantalla(app, "contextualizar")
    at = seguir(at.button(key="nav_siguiente").click().run())
    assert url_actual(at) == "priorizar" and not at.exception and at.header[0].value == "4 · Priorizar"
    at = at.button(key="nav_anterior").click().run()
    assert url_actual(at) == "contextualizar"


def test_el_indicador_de_etapas_y_la_barra_lateral_cambian_la_url(app) -> None:
    at = ir_a_pantalla(app, "organizar")
    at = seguir(at.button(key="paso_revision").click().run())
    assert url_actual(at) == "revisar"
    at = seguir(at.radio(key="pantalla_etapa").set_value("ficha").run())
    assert url_actual(at) == "explicar"
    at = seguir(at.sidebar.button(key="pantalla_consulta").click().run())
    assert url_actual(at) == "consulta" and at.radio(key="pantalla_etapa").value is None
    at = seguir(at.sidebar.button(key="pantalla_inicio").click().run())
    assert url_actual(at) == ""


def test_los_botones_abrir_y_las_tarjetas_de_arquitectura_llevan_a_su_url(app) -> None:
    at = ir_a_pantalla(app, "inicio")
    at = seguir(at.button(key="inicio_contextualizar").click().run())
    assert url_actual(at) == "contextualizar"
    at = seguir(ir_a_pantalla(at, "inicio").button(key="inicio_arquitectura").click().run())
    assert url_actual(at) == "cargar"
    destino = next(b for b in at.button if str(b.key).startswith("arq_"))
    at = destino.click().run()
    assert url_actual(at) == ui.url_de_pantalla(CFG, str(destino.key).rsplit("_", 1)[1])


def test_abrir_ficha_desde_la_bandeja_va_a_explicar_con_ese_grupo(app) -> None:
    at = ir_a_pantalla(app, "bandeja")
    at.selectbox(key="bandeja_grupo").select(h.G_SISMO).run()
    at = seguir(at.button(key="bandeja_abrir").click().run())
    assert url_actual(at) == "explicar" and at.session_state["id_grupo"] == h.G_SISMO and at.session_state["ficha_grupo"] == h.G_SISMO


# ------------------------------------------------------------------ enlaces directos


def test_el_enlace_con_caso_en_la_raiz_abre_explicar(app) -> None:
    app.query_params["caso"] = h.G_SISMO
    at = app.run()
    assert not at.exception and url_actual(at) == "explicar"
    assert at.session_state["id_grupo"] == h.G_SISMO and at.session_state["ficha_grupo"] == h.G_SISMO
    assert at.query_params["caso"] == [h.G_SISMO] or at.query_params["caso"] == h.G_SISMO


@pytest.mark.parametrize("clave", ["ficha", "paquete", "revision"])
def test_el_enlace_con_caso_se_queda_en_explicar_producir_o_revisar(app, clave) -> None:
    at = ir_a_pantalla(app, clave)
    at.query_params["caso"] = h.G_SISMO
    at = at.run()
    assert not at.exception and url_actual(at) == URLS[clave] and at.session_state["id_grupo"] == h.G_SISMO


def test_elegir_otro_grupo_lo_guarda_en_la_sesion_sin_reescribir_la_url(app) -> None:
    """Reescribir ?caso= agregaba entradas al historial y «Atrás» pedía tres clics (auditoría en Chrome): el grupo vive en la sesión."""
    at = ir_a_pantalla(app, "ficha")
    at = at.selectbox(key="ficha_grupo").select(h.G_SISMO).run()
    assert at.session_state["id_grupo"] == h.G_SISMO
    assert "caso" not in at.query_params
    at = ir_a_pantalla(at, "paquete")      # el grupo elegido sobrevive al cambio de página
    assert at.session_state["id_grupo"] == h.G_SISMO


# ------------------------------------------------------------------ consulta en la URL


def test_la_consulta_con_q_en_la_url_se_vuelve_a_ejecutar(app) -> None:
    at = ir_a_pantalla(app, "consulta")
    at.query_params["q"] = PREGUNTA
    at = at.run()
    assert not at.exception and at.text_input(key="consulta_texto").value == PREGUNTA
    assert any("Respuesta." in str(s.value) for s in at.success)


def test_consultar_guarda_la_pregunta_en_la_url_y_los_ejemplos_siguen(app) -> None:
    at = ir_a_pantalla(app, "consulta")
    at = at.button(key="consulta_ejemplo_0").click().run()
    assert at.query_params["q"] in (CFG.consulta.ejemplos[0], [CFG.consulta.ejemplos[0]])
    at.text_input(key="consulta_texto").input(PREGUNTA)
    at = at.button(key="consulta_boton").click().run()
    assert at.query_params["q"] in (PREGUNTA, [PREGUNTA])


def test_la_consulta_guarda_y_restaura_el_metodo_en_la_url(app) -> None:
    at = ir_a_pantalla(app, "consulta")
    at.text_input(key="consulta_texto").input(PREGUNTA)
    at.selectbox(key="consulta_metodo").select("bm25")
    at = at.button(key="consulta_boton").click().run()
    assert at.query_params["m"] in ("bm25", ["bm25"])
    otro = ir_a_pantalla(app, "consulta")
    otro.query_params["q"] = PREGUNTA
    otro.query_params["m"] = "bm25"
    otro = otro.run()
    assert not otro.exception and otro.selectbox(key="consulta_metodo").value == "bm25"


def test_el_texto_de_la_ultima_respuesta_viene_de_la_configuracion() -> None:
    assert "{pregunta}" in CFG.consulta.texto_ultima_respuesta
    assert "Respuesta a la última pregunta consultada" not in (RAIZ / "app.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------ el estado sobrevive al cambio de página


def test_modalidad_grupo_y_pesos_sobreviven_al_cambio_de_pagina(app) -> None:
    at = ir_a_pantalla(app, "bandeja")
    at.selectbox(key="modalidad").select("banca").run()
    at.session_state["id_grupo"] = h.G_SISMO
    at = ir_a_pantalla(at, "paquete")
    assert url_actual(at) == "producir" and at.session_state["modalidad"] == "banca"
    at = ir_a_pantalla(at, "ficha")
    assert at.session_state["modalidad"] == "banca" and at.session_state["ficha_grupo"] == at.session_state["id_grupo"]
    at = ir_a_pantalla(at, "bandeja")
    assert at.selectbox(key="modalidad").value == "banca"


def test_los_valores_de_widgets_sobreviven_a_otra_pagina(app) -> None:
    at = ir_a_pantalla(app, "bandeja")
    oficial = at.number_input(key="peso_R").value
    at.number_input(key="peso_R").set_value(oficial + 1).run()
    at = ir_a_pantalla(at, "consulta")
    at.text_input(key="consulta_texto").input(PREGUNTA)
    at = at.button(key="consulta_boton").click().run()
    assert any("Respuesta." in str(s.value) for s in at.success)
    at = ir_a_pantalla(at, "ficha")      # otra página: el texto y la última respuesta no se pierden al volver
    at = ir_a_pantalla(at, "bandeja")
    assert at.number_input(key="peso_R").value == oficial + 1
    at = ir_a_pantalla(at, "consulta")
    assert at.text_input(key="consulta_texto").value == PREGUNTA
    assert any("Respuesta." in str(s.value) for s in at.success)
