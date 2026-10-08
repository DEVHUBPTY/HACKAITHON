"""E1-16 · La pantalla Revisión (``app.py``) como flujo de trabajo, con ``AppTest``: sin red, sin modelo y sin tocar la base real."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import db, embeddings, exportar, interfaz as ui
from src.configuracion import FORMAS_DE_PUBLICAR, RAIZ, cargar_revision
from src.ficha import construir_ficha
from src.generacion import Generador, desde_ficha
from src.revision import Revisiones
from tests import ficha_ayuda as h
from tests import generacion_ayuda as ga
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.test_e1_16_revision import AFIRMACIONES, ID_OFICIAL

APP = RAIZ / "app.py"
CFG_REV = cargar_revision()
REVISOR = "Javier Acosta"
MARCA = "BORRADOR · requiere revisión"


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base(tmp_path_factory, emb) -> Path:
    return h.construir(tmp_path_factory.mktemp("ui16") / "senales.duckdb", emb)


def _paquete(entrada: Any):
    g = Generador(entrada, ga.ProveedorGuionado(afirmaciones=AFIRMACIONES))
    g.generar_todo()
    return g.paquete()


@pytest.fixture
def app(monkeypatch, base, emb, tmp_path):
    ruta_rev = tmp_path / "revision.duckdb"
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (base, None))
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: ruta_rev)
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)
    monkeypatch.setattr("sys.argv", ["app.py"])
    # el borrador de la caché: el que arma el proveedor guionado sobre la ficha real del grupo (nunca un LLM)
    def disponible(id_grupo, modalidad, cfg=None, generador=None, ruta_base=None):
        con = db.conectar(base, solo_lectura=True)
        try:
            entrada = desde_ficha(construir_ficha(id_grupo, modalidad, con, emb=emb))
        finally:
            con.close()
        return ui.EstadoPaquete("disponible", _paquete(entrada))

    monkeypatch.setattr(ui, "obtener_paquete", disponible)
    monkeypatch.setattr(exportar, "RAIZ", tmp_path)                                  # nada se exporta dentro del repositorio
    monkeypatch.setattr("src.revision.huellas_de_exportacion", lambda demo, cfg=None, raiz=tmp_path: [tmp_path / "notion", tmp_path / "fichas.jsonl"])  # la numeración no lee las exportaciones reales del repo
    original = exportar.exportar_caso
    monkeypatch.setattr(exportar, "exportar_caso", lambda rev, id_caso, **k: original(rev, id_caso, carpeta=tmp_path / "notion", ruta_jsonl=tmp_path / "fichas.jsonl", **k))
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["id_grupo"] = h.G_COMPLETO
    at.session_state["pantalla"] = "revision"
    return at


def ruta_de(app: AppTest) -> Path:
    return ui.ruta_de_revision(False)


def textos(at: AppTest) -> str:
    partes: list[str] = []
    for tipo in ("markdown", "caption", "header", "subheader", "info", "warning", "success", "error"):
        partes += [str(e.value) for e in at.get(tipo)]
    return "\n".join(partes)


def abrir_caso(at: AppTest) -> AppTest:
    at = at.run()
    at.selectbox(key="revision_revisor").select(REVISOR).run()
    return at.button(key="revision_abrir").click().run()


def test_el_revisor_sale_de_la_lista_del_yaml_y_no_hay_ninguno_elegido(app) -> None:
    at = app.run()
    assert not at.exception
    caja = at.selectbox(key="revision_revisor")
    assert list(caja.options) == ui.revisores_de("editorial", CFG_REV) == ["David Fen", "Javier Acosta", "Juan Zhou", "Asistente (provisional, D-101)"] and caja.value is None   # D-112: el asistente va en la lista, rotulado
    assert "Sin autenticación" in textos(at)                                       # la limitación declarada (D-49)
    assert at.button(key="revision_abrir").disabled


def test_abrir_crea_el_caso_y_ofrece_el_boton_aprobar_como_borrador(app) -> None:
    at = abrir_caso(app)
    assert not at.exception
    assert "Estado actual:** en revisión · **Caso:** CASO-001" in textos(at)
    assert at.button(key="revision_aceptar").label == "Aprobar como borrador"
    assert [b.label for b in at.button if b.key in {"revision_aceptar", "revision_pedir", "revision_descartar", "revision_reabrir", "revision_regenerar", "revision_exportar"}] == [
        "Aprobar como borrador", "Pedir evidencia", "Descartar", "Reabrir", "Regenerar borrador", "Registro en Notion: exportar la ficha",
    ]
    assert at.button(key="revision_reabrir").disabled and not at.button(key="revision_aceptar").disabled        # las transiciones salen del yaml
    assert len(at.dataframe[-1].value) == 1 and MARCA in textos(at)


def test_aprobar_como_borrador_conserva_la_marca_y_ya_no_se_puede_repetir(app) -> None:
    at = abrir_caso(app)
    at = at.button(key="revision_aceptar").click().run()
    assert "Estado actual:** aprobado como borrador" in textos(at) and MARCA in textos(at)
    assert at.button(key="revision_aceptar").disabled and not at.button(key="revision_reabrir").disabled
    historial = at.dataframe[-1].value
    assert list(historial["Acción"]) == ["abrir", "aceptar"] and "hora de Panamá" in historial["Fecha"][0]
    assert not any(FORMAS_DE_PUBLICAR.search(b.label) for b in at.button)


def test_descartar_sin_motivo_se_rechaza_y_con_motivo_queda_registrado(app) -> None:
    at = abrir_caso(app)
    at = at.button(key="revision_descartar").click().run()
    assert "exige un motivo" in textos(at) and "Estado actual:** en revisión" in textos(at)
    at.selectbox(key="revision_motivo_descarte").select("Duplicado de otro caso").run()
    at = at.button(key="revision_descartar").click().run()
    assert "Estado actual:** descartado" in textos(at)
    assert list(at.dataframe[-1].value["Motivo"])[-1] == "Duplicado de otro caso"


def test_una_correccion_con_advertencia_exige_confirmarla_y_crea_otra_version(app) -> None:
    at = abrir_caso(app)
    at.selectbox(key="revision_elemento").select("afirmaciones.A2").run()
    caja = at.text_area(key="revision_texto_1_afirmaciones.A2")
    caja.set_value("TVN Panamá reporta inflación estable y 77 comercios cerrados").run()
    at = at.button(key="revision_revisar_correccion").click().run()
    assert "advertencias" in textos(at) and at.checkbox(key="revision_confirmar_0") is not None
    at = at.button(key="revision_guardar_correccion").click().run()                    # sin confirmar: no se guarda
    assert "Falta confirmar" in textos(at) and len(Revisiones(ruta_de(app)).versiones("CASO-001")) == 1
    at.selectbox(key="revision_elemento").select("afirmaciones.A2").run()
    at.text_area(key="revision_texto_1_afirmaciones.A2").set_value("TVN Panamá reporta inflación estable y 77 comercios cerrados").run()
    at = at.button(key="revision_revisar_correccion").click().run()
    at.checkbox(key="revision_confirmar_0").check().run()
    at = at.button(key="revision_guardar_correccion").click().run()
    rev = Revisiones(ruta_de(app))
    assert [(v.version, v.origen) for v in rev.versiones("CASO-001")] == [(1, "generada"), (2, "corregida")]
    assert rev.historial("CASO-001")[-1].detalle["advertencias_confirmadas"] and "Corrección guardada" in textos(at)


def test_el_boton_de_exportar_escribe_el_markdown_y_la_fila(app, tmp_path) -> None:
    at = abrir_caso(app)
    at = at.button(key="revision_exportar").click().run()
    assert not at.exception and "CASO-001: exportado" in textos(at)
    assert (tmp_path / "notion" / "CASO-001.md").exists() and (tmp_path / "notion" / "casos_y_evidencias.csv").exists()
    at = at.button(key="revision_exportar").click().run()
    assert "CASO-001: actualizado" in textos(at)


def test_rechazar_un_vinculo_lo_registra_y_ofrece_restaurarlo(app) -> None:
    at = abrir_caso(app)
    at.text_input(key="revision_motivo_vinculo").input("mide otro período").run()
    botones = [b for b in at.button if b.key and b.key.startswith("revision_rechazar_")]
    assert botones and all(b.label == "Rechazar vínculo oficial" for b in botones)
    at = botones[0].click().run()
    rev = Revisiones(ruta_de(app))
    assert len(rev.vinculos_rechazados("CASO-001")) == 1 and rev.historial("CASO-001")[-1].accion == "rechazar_vinculo"
    assert rev.historial("CASO-001")[-1].motivo == "mide otro período"
    assert any(b.key.startswith("revision_restaurar_") for b in at.button if b.key)


def test_rechazar_un_vinculo_sin_motivo_se_rechaza(app) -> None:
    at = abrir_caso(app)
    botones = [b for b in at.button if b.key and b.key.startswith("revision_rechazar_")]
    at = botones[0].click().run()
    assert "exige un motivo" in textos(at) and Revisiones(ruta_de(app)).vinculos_rechazados("CASO-001") == set()


def test_regenerar_sin_borrador_en_cache_lo_dice_y_no_escribe(app, monkeypatch) -> None:
    from src.cache import SinBorrador

    def sin_cache(*a: Any, **k: Any) -> Any:
        raise SinBorrador("No hay borrador en caché para este grupo")

    monkeypatch.setattr("src.generacion.generar_paquete", sin_cache)
    at = abrir_caso(app)
    n = len(Revisiones(ruta_de(app)).todas_las_filas())
    at = at.button(key="revision_regenerar").click().run()
    assert not at.exception and "No hay borrador en caché" in textos(at) and len(Revisiones(ruta_de(app)).todas_las_filas()) == n


def test_regenerar_crea_una_version_nueva_sin_pisar_la_corregida(app, monkeypatch) -> None:
    monkeypatch.setattr("src.generacion.generar_paquete", lambda id_grupo, modalidad, *, entrada, **_: _paquete(entrada))
    at = abrir_caso(app)
    at.selectbox(key="revision_elemento").select("afirmaciones.A2").run()
    at.text_area(key="revision_texto_1_afirmaciones.A2").set_value("TVN Panamá reporta que el país mantiene la inflación estable").run()
    at = at.button(key="revision_guardar_correccion").click().run()
    at = at.button(key="revision_regenerar").click().run()
    assert [(v.version, v.origen) for v in Revisiones(ruta_de(app)).versiones("CASO-001")] == [(1, "generada"), (2, "corregida"), (3, "generada")]
    assert "Borrador regenerado como una versión nueva" in textos(at)


def test_el_atajo_caso_acepta_un_id_caso(app) -> None:
    abrir_caso(app)
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.query_params["caso"] = "CASO-001"
    at.run()
    assert not at.exception and at.session_state["pantalla"] == "ficha" and at.session_state["ficha_grupo"] == h.G_COMPLETO


def test_la_pantalla_de_revision_tiene_marca_y_leyenda_en_todos_los_estados(app) -> None:
    at = app.run()
    assert MARCA in textos(at) and "basado" in textos(at)


def test_la_pantalla_rotula_la_aprobacion_del_asistente_como_provisional_y_la_de_una_persona_no(app) -> None:
    """D-112: el estado y el historial de la pantalla dicen «provisional (D-101)» mientras la fila vigente sea del asistente."""
    marca = CFG_REV.textos.marca_provisional
    asistente = "Asistente (provisional, D-101)"
    at = app.run()
    at.selectbox(key="revision_revisor").select(asistente).run()
    assert marca in textos(at) and "una persona rehace la aprobación." in textos(at)
    at = at.button(key="revision_abrir").click().run()
    at = at.button(key="revision_aceptar").click().run()
    assert not at.exception
    assert f"**Estado actual:** aprobado como borrador · **{marca}**" in textos(at)
    historial = [r for df in at.dataframe for r in df.value.to_dict("records") if "Revisor" in r]
    assert historial and all(marca in r["Revisor"] for r in historial)
