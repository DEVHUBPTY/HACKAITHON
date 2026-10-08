"""D-129 · Hallazgos de la auditoría en el navegador: vínculo forzado, borrador de la caché en Revisar, fechas rotuladas,
panel de un SIS- con unidad, período y limitaciones, y ningún código interno en los títulos visibles.

Reglas y paneles con datos sintéticos y la configuración real; las pantallas con ``AppTest`` sobre el snapshot (se omiten sin él).
Sin red ni LLM.
"""

from __future__ import annotations

import re

import duckdb
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import contexto, db
from src import interfaz as ui
from src.configuracion import RAIZ, cargar_interfaz, cargar_revision, cargar_verificacion, cargar_vinculos
from src.revision import Revisiones
from tests.navegacion_ayuda import ir_a_pantalla

BASE = RAIZ / "data" / "senales.duckdb"
CFG, CFG_VER, VINC = cargar_interfaz(), cargar_verificacion(), cargar_vinculos()
CHINAS = "Exportaciones chinas sostienen la demanda de carga contenerizada pese a la debilidad de EE . UU ."
BANANO = "Exportaciones de banano superan los $17 millones en junio y marcan recuperación"
CODIGO_INTERNO = re.compile(r"\b(?:E\d-\d{2}[a-z]?|D-\d{2,3}|X\d{2}|C-\d{2})\b")
requiere_snapshot = pytest.mark.skipif(not BASE.exists(), reason="no hay snapshot (data/senales.duckdb)")


# ------------------------------------------------------------------ 1 · vínculo forzado de las exportaciones


def test_exportaciones_de_otro_pais_no_se_vinculan_con_las_de_panama() -> None:
    assert contexto.reglas_disparadas([CHINAS], "logistica", VINC) == {}
    vinculo, regla, motivo, _ = contexto.elegir_vinculo("logistica", {}, VINC)
    assert vinculo is None and motivo == "sin_relacion_sustentada" and "no se fuerza" in regla


@pytest.mark.parametrize("titular", [
    "Panamá exporta más: exportaciones de la Zona Libre de Colón suben en septiembre",
    "Exportaciones panameñas de contenedores llegan a un récord",
    "Contenedores en el puerto de Balboa crecen 5 % en septiembre",
])
def test_exportaciones_o_carga_con_marca_panamena_si_se_vinculan(titular: str) -> None:
    assert list(contexto.reglas_disparadas([titular], "logistica", VINC)) == ["exportaciones_logistica"]


def test_el_requisito_se_cumple_en_el_mismo_titular_que_dispara_no_en_otro_del_grupo() -> None:
    d = contexto.reglas_disparadas([CHINAS, "Autoridad del Canal de Panamá anuncia nuevo reglamento"], "logistica", VINC)
    assert d == {}


def test_un_titular_panameno_que_atribuye_las_exportaciones_a_otro_pais_tampoco_se_vincula() -> None:
    assert contexto.reglas_disparadas(["Exportaciones chinas llegan al puerto de Balboa en contenedores"], "logistica", VINC) == {}


def test_el_titular_de_banano_de_un_medio_panameno_sigue_vinculado_por_economia() -> None:
    assert contexto.reglas_disparadas([BANANO], "economia", VINC) == {"comercio_exterior": "exportaciones"}


def test_la_limitacion_de_transitos_y_carga_solo_es_de_la_regla_de_logistica() -> None:
    con_texto = {n for n, r in VINC.reglas_vinculo.items() if "tránsitos" in r.limitacion}
    assert con_texto == {"exportaciones_logistica"}
    assert VINC.reglas_vinculo["exportaciones_logistica"].tema == "logistica"


# ------------------------------------------------------------------ 3 · fechas rotuladas


def _base_minima() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE grupos (id_grupo VARCHAR, titular_central VARCHAR, tema_clasificado VARCHAR, n_titulares INT, n_medios INT, n_procedencias INT)")
    con.execute("CREATE TABLE noticias (id_noticia VARCHAR, titulo_limpio VARCHAR, titulo VARCHAR, medio VARCHAR, fecha_publicacion VARCHAR, fecha_deteccion VARCHAR, procedencia VARCHAR, id_grupo VARCHAR)")
    con.execute("CREATE TABLE procedencias (id_grupo VARCHAR, etiqueta VARCHAR, n_titulares INT, medios VARCHAR, reglas VARCHAR, orden INT)")
    con.execute("INSERT INTO grupos VALUES ('GRP-1', 'Titular A', 'economia', 3, 3, 1)")
    con.execute("INSERT INTO noticias VALUES "
                "('NOT-1', 'Titular A', NULL, 'medio.pa', NULL, '2026-10-02T08:00:00Z', 'P1', 'GRP-1'),"
                "('NOT-2', 'Titular B', NULL, 'rss.pa', '2026-10-02T09:00:00Z', NULL, 'P1', 'GRP-1'),"
                "('NOT-3', 'Titular C', NULL, 'otro.pa', '2026-10-02T10:00:00Z', '2026-10-02T10:30:00Z', 'P1', 'GRP-1')")
    return con


def test_la_tabla_de_titulares_trae_publicacion_y_deteccion_y_nunca_sustituye_una_por_otra() -> None:
    d = ui.detalle_de_grupo(_base_minima(), "GRP-1", {"economia": "Economía"}, CFG_VER)
    por_id = {f["Noticia"]: f for f in d.titulares}
    assert all({"Publicación", "Detección"} <= set(f) for f in d.titulares)
    assert por_id["NOT-1"]["Publicación"] == "sin dato" and "2026-10-02 03:00" in por_id["NOT-1"]["Detección"]   # GDELT: solo detección
    assert "2026-10-02 04:00" in por_id["NOT-2"]["Publicación"] and por_id["NOT-2"]["Detección"] == "sin dato"
    assert "2026-10-02 05:00" in por_id["NOT-3"]["Publicación"] and "2026-10-02 05:30" in por_id["NOT-3"]["Detección"]
    assert all("desconocida" not in f["Publicación"] for f in d.titulares)


# ------------------------------------------------------------------ 4 · panel de un SIS-


def _base_sismos(con_vinculo: bool) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE sismos (id VARCHAR, magnitude DOUBLE, time VARCHAR, place VARCHAR, status VARCHAR, url VARCHAR)")
    con.execute("CREATE TABLE vinculos (id_grupo VARCHAR, id_evidencia VARCHAR, periodo VARCHAR, limitacion VARCHAR)")
    con.execute("INSERT INTO sismos VALUES ('SIS-us1', 5.8, '2024-03-02T10:00:00Z', '83 km S of Boca Chica, Panama', 'reviewed', 'https://earthquake.usgs.gov/x')")
    if con_vinculo:
        lim = " ".join(x.format(periodo="2024") for x in VINC.sismos.contexto_historico.limitaciones)
        con.execute("INSERT INTO vinculos VALUES ('GRP-1', 'SIS-us1', '2024', ?)", [lim])
    return con


def test_el_panel_de_un_sismo_trae_unidad_periodo_lugar_y_limitaciones_del_vinculo() -> None:
    d = ui.detalle_cita(_base_sismos(True), "SIS-us1", "magnitude", CFG, CFG_VER)
    f = dict(d.filas)
    assert d.valor == "5.8 magnitud"
    assert f["Período"] == "2024" and f["Lugar"] == "83 km S of Boca Chica, Panama"
    assert "no equivale al territorio de Panamá" in f["Limitaciones"] and "no informa daños" in f["Limitaciones"]
    assert "no coincide con la fecha de la noticia" in f["Limitaciones"]


def test_sin_vinculo_el_panel_usa_el_ano_del_evento_y_las_limitaciones_fijas_sin_decir_que_es_historico() -> None:
    d = ui.detalle_cita(_base_sismos(False), "SIS-us1", "magnitude", CFG, CFG_VER)
    f = dict(d.filas)
    assert f["Período"] == "2024" and "no informa daños" in f["Limitaciones"]
    assert "no coincide con la fecha de la noticia" not in f["Limitaciones"]


# ------------------------------------------------------------------ 2 · Revisar con el borrador de la caché


def test_un_caso_sin_version_lee_el_borrador_de_la_cache_sin_escribir_ni_llamar_al_llm() -> None:
    llamadas: list[dict] = []

    def generador(id_grupo, modalidad, *, solo_cache=True, **extra):
        llamadas.append({"id_grupo": id_grupo, "solo_cache": solo_cache})
        return {"resumen": "borrador de la caché"}

    en_cache = ui.borrador_en_cache_de_caso(None, "GRP-1", "editorial", CFG, generador=generador)
    assert en_cache == {"resumen": "borrador de la caché"} and llamadas == [{"id_grupo": "GRP-1", "solo_cache": True}]
    assert ui.borrador_en_cache_de_caso(object(), "GRP-1", "editorial", CFG, generador=generador) is None   # ya tiene versión: no se pide
    assert len(llamadas) == 1


def test_sin_borrador_en_cache_no_se_inventa_ninguno() -> None:
    from src.cache import SinBorrador

    def sin_cache(*a, **k):
        raise SinBorrador("no hay")

    assert ui.borrador_en_cache_de_caso(None, "GRP-1", "editorial", CFG, generador=sin_cache) is None


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")   # nunca la revisión real
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120)


def _texto(at: AppTest) -> str:
    partes: list[str] = []
    for tipo in ("markdown", "caption", "header", "subheader", "info", "warning", "success", "error"):
        partes += [str(e.value) for e in at.get(tipo)]
    partes += [e.label for e in at.expander]
    return "\n".join(partes)


@requiere_snapshot
def test_la_pantalla_revisar_muestra_el_borrador_de_la_cache_de_un_caso_sin_version(app, tmp_path) -> None:
    con = duckdb.connect(str(BASE), read_only=True)
    grupo = con.execute("SELECT id_grupo FROM puntajes ORDER BY id_grupo").fetchall()
    con.close()
    elegido = next((g for (g,) in grupo if ui.obtener_paquete(g, "editorial", CFG, ruta_base=BASE).estado == "disponible"), None)
    if elegido is None:
        pytest.skip("la caché no tiene ningún borrador para el snapshot")
    revisor = ui.revisores_de("editorial", cargar_revision())[0]
    caso = Revisiones(tmp_path / "revision.duckdb", BASE).abrir(elegido, "editorial", revisor)   # sin paquete: el caso nace sin versión
    assert Revisiones(tmp_path / "revision.duckdb", BASE).version_actual(caso.id_caso) is None
    app.session_state["id_grupo"] = elegido
    at = ir_a_pantalla(app, "revision")
    assert not at.exception
    t = _texto(at)
    assert "desde la caché" in t and "no tiene borrador" not in t
    assert Revisiones(tmp_path / "revision.duckdb", BASE).version_actual(caso.id_caso) is None   # solo lectura: no escribió una versión


# ------------------------------------------------------------------ 5 · sin códigos internos a la vista


@requiere_snapshot
def test_ningun_titulo_ni_rotulo_visible_lleva_un_codigo_de_tarea_o_decision(app) -> None:
    at = app.run()
    for p in CFG.pantallas:
        at = ir_a_pantalla(at, p.clave)
        assert not at.exception, p.clave
        visibles = [str(e.value) for e in (*at.get("header"), *at.get("subheader"), *at.get("caption"), *at.get("info"), *at.get("warning"))]
        visibles += [e.label for e in at.expander] + [b.label for b in at.button] + [m.label for m in at.metric]
        assert not [v for v in visibles if CODIGO_INTERNO.search(v)], (p.clave, [v for v in visibles if CODIGO_INTERNO.search(v)])


def test_la_configuracion_visible_de_la_interfaz_no_lleva_codigos_internos() -> None:
    textos = [x for p in CFG.pantallas for x in (p.titulo, p.descripcion)]
    textos += [CFG.textos.sin_borrador, CFG.textos.sin_demo, CFG.textos.banca_parcial, CFG.registro_notion.sin_token]
    textos += [p.etiqueta + " " + p.unidad for p in CFG.cargar.arquitectura]
    assert not [t for t in textos if CODIGO_INTERNO.search(t)]
    assert "no son borradores por grupo" in next(p.unidad for p in CFG.cargar.arquitectura if p.medida == "borradores_en_cache")
