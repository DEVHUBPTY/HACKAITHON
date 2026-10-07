"""E1-15 · Interfaz Streamlit: la lógica de presentación (sin Streamlit) y un recorrido de las seis pantallas con ``AppTest``.

Todo corre sin red ni modelo real: la base es la sintética de E1-10b, los embeddings son el codificador falso y el consultor
usa el corpus de prueba de E1-11.
"""

from __future__ import annotations

import ast
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import streamlit as st
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from src import db, embeddings, interfaz as ui
from src.configuracion import FORMAS_DE_PUBLICAR, RAIZ, ConfigInterfaz, cargar_interfaz, cargar_modalidad, cargar_restricciones, cargar_verificacion
from src.ficha import a_markdown, construir_ficha, escapar_markdown, vista
from tests import consulta_fixture, ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba

CFG = cargar_interfaz()
CFG_VER = cargar_verificacion()
APP = RAIZ / "app.py"
LEYENDA = "basado únicamente en titular/metadatos"
MARCA = "BORRADOR · requiere revisión"
SECRETO = "DESCRIPCION-INTERNA-NO-REDISTRIBUIBLE"
PANTALLAS = [p.clave for p in CFG.pantallas]
ID_SINTETICO = "NOT-c000000002"


# ------------------------------------------------------------------ base de prueba


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base(tmp_path_factory, emb) -> Path:
    """La base de E1-10b más un indicador, un sismo, una noticia sintética y una descripción del RSS que nunca debe verse."""
    ruta = h.construir(tmp_path_factory.mktemp("ui") / "senales.duckdb", emb)
    con = db.conectar(ruta)
    con.execute("UPDATE noticias SET origen = 'sintetico' WHERE id_noticia = ?", [ID_SINTETICO])
    con.execute("UPDATE noticias SET origen = 'TVN RSS', descripcion = ? WHERE id_noticia = 'NOT-c000000001'", [SECRETO])
    db.insertar(con, "indicadores", [{
        "id_indicador": "IND-PAN-FP.CPI.TOTL.ZG-2024", "pais_iso3": "PAN", "indicador_id": "FP.CPI.TOTL.ZG", "anio": 2024, "valor": 0.69322,
        "unidad": "% anual", "fuente_url": "https://api.worldbank.org/v2/country/PAN/indicator/FP.CPI.TOTL.ZG", "fecha_extraccion": "2026-10-06T12:00:00Z",
        "licencia": "CC BY 4.0",
    }, {
        "id_indicador": "IND-PAN-SL.UEM.TOTL.ZS-2023", "pais_iso3": "PAN", "indicador_id": "SL.UEM.TOTL.ZS", "anio": 2023, "valor": None,
        "unidad": "%", "fuente_url": "https://api.worldbank.org/x", "fecha_extraccion": "2026-10-06T12:00:00Z", "licencia": "CC BY 4.0",
    }])
    db.insertar(con, "sismos", [{"id": "SIS-us7000test", "magnitude": 5.1, "time": "2026-10-06T07:30:00Z", "place": "12 km S of Puerto Armuelles, Panama",
                                 "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test"}])
    con.close()
    return ruta


@pytest.fixture(scope="module")
def con(base):
    c = db.conectar(base, solo_lectura=True)
    yield c
    c.close()


# ------------------------------------------------------------------ configuración


def test_la_configuracion_valida_y_ningun_texto_habla_de_publicar() -> None:
    assert [p.clave for p in CFG.pantallas] == ["calidad", "bandeja", "ficha", "consulta", "paquete", "revision"]
    datos = CFG.model_dump()
    datos["textos"]["sin_borrador"] = "Listo para publicar"
    with pytest.raises(ValidationError, match="publicar"):
        ConfigInterfaz.model_validate(datos)


def test_la_configuracion_rechaza_pantallas_repetidas_y_claves_desconocidas() -> None:
    datos = CFG.model_dump()
    datos["pantallas"][1]["clave"] = "calidad"
    with pytest.raises(ValidationError):
        ConfigInterfaz.model_validate(datos)
    with pytest.raises(ValidationError):
        ConfigInterfaz.model_validate({**CFG.model_dump(), "extra": 1})


def _literales(ruta: Path) -> list[str]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(arbol) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


@pytest.mark.parametrize("ruta", [APP, RAIZ / "src" / "interfaz.py"])
def test_ningun_texto_de_la_interfaz_habla_de_publicar(ruta: Path) -> None:
    assert [t for t in _literales(ruta) if FORMAS_DE_PUBLICAR.search(t)] == []


# ------------------------------------------------------------------ hora de Panamá


def test_la_hora_se_muestra_en_panama_y_el_dato_no_cambia() -> None:
    assert ui.hora_panama("2026-10-06T12:00:00Z", CFG_VER) == "2026-10-06 07:00 (hora de Panamá)"
    assert ui.hora_panama(datetime(2026, 10, 7, 3, 30, tzinfo=UTC), CFG_VER, con_zona=False) == "2026-10-06 22:30"
    assert ui.hora_panama(None, CFG_VER) == CFG_VER.presentacion.fecha_desconocida == "desconocida"


def test_una_fecha_sin_zona_se_rechaza_en_lugar_de_adivinar() -> None:
    with pytest.raises(ValueError, match="zona"):
        ui.hora_panama("2026-10-06T12:00:00", CFG_VER)


def test_el_encabezado_de_la_bandeja_trae_version_de_reglas_y_corte_en_hora_de_panama(con, tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"fecha_corte_UTC": "2026-10-06T08:30:00Z"}', encoding="utf-8")
    enc = ui.encabezado_bandeja(con, manifest, CFG_VER)
    assert enc["fecha_corte"] == "2026-10-06 03:30 (hora de Panamá)"
    assert enc["version_reglas"] == con.execute("SELECT version_reglas FROM puntajes LIMIT 1").fetchone()[0]
    assert ui.encabezado_bandeja(con, tmp_path / "no_existe.json", CFG_VER)["fecha_corte"].startswith("desconocida")


# ------------------------------------------------------------------ bandeja


def fila(grupo: str, p: float, u: float = 0.5, posicion: int = 1) -> ui.FilaBandeja:
    return ui.FilaBandeja(posicion, grupo, "tema", "titular", p, "medio", {"R": 0.5, "I": 0.5, "U": u, "N": 0.5, "E": 0.5}, "parcial", "Vigilar")


def test_la_bandeja_leida_de_la_base_es_el_ranking_y_trae_las_columnas_de_la_spec(con) -> None:
    filas = ui.leer_bandeja(con, "editorial")
    assert len(filas) == 11
    assert [f.posicion for f in filas] == list(range(1, 12))
    assert ui.comprobar_orden(filas)
    for f in filas:
        assert set(f.componentes) == set("RIUNE") and all(0 <= v <= 1 for v in f.componentes.values())
        assert f.tema and f.titular and f.accion and f.estado_evidencia in {"suficiente", "parcial", "insuficiente"} and f.rango in {"alto", "medio", "bajo"}
    assert [f.puntaje for f in filas] == sorted((f.puntaje for f in filas), reverse=True)


def test_el_desempate_es_mayor_urgencia_y_luego_menor_id() -> None:
    a, b, c, d = fila("GRP-b", 70, u=0.9), fila("GRP-a", 70, u=0.9), fila("GRP-c", 70, u=0.95), fila("GRP-d", 71, u=0.1)
    assert [f.id_grupo for f in ui.ordenar_bandeja([a, b, c, d])] == ["GRP-d", "GRP-c", "GRP-a", "GRP-b"]


def test_una_diferencia_de_coma_flotante_no_decide_el_empate() -> None:
    a, b = fila("GRP-z", 70.0000000000001, u=0.9), fila("GRP-a", 70.0, u=0.9)
    assert [f.id_grupo for f in ui.ordenar_bandeja([a, b])] == ["GRP-a", "GRP-z"]


def test_un_orden_guardado_distinto_del_ranking_se_detecta() -> None:
    assert not ui.comprobar_orden([fila("GRP-b", 60), fila("GRP-a", 70)])


def test_la_modalidad_sin_puntajes_devuelve_una_bandeja_vacia_y_no_inventa(con) -> None:
    assert ui.leer_bandeja(con, "banca") == []
    assert cargar_modalidad("banca").parcial is True


def test_la_bandeja_marca_los_grupos_con_registros_sinteticos(con) -> None:
    sinteticos = {f.id_grupo for f in ui.leer_bandeja(con, "editorial") if f.sintetico}
    assert sinteticos == {h.G_COMPLETO}


def test_el_atajo_caso_acepta_un_id_o_una_posicion(con) -> None:
    filas = ui.leer_bandeja(con, "editorial")
    assert ui.resolver_caso(filas[2].id_grupo, filas) == filas[2].id_grupo
    assert ui.resolver_caso("1", filas) == filas[0].id_grupo
    for malo in (None, "", "CASO-001", "GRP-no-existe", "999", "1; DROP TABLE grupos"):
        assert ui.resolver_caso(malo, filas) is None


# ------------------------------------------------------------------ ficha


@pytest.mark.parametrize("grupo", [h.G_COMPLETO, h.G_CIFRAS, h.G_SISMO, h.G_INYECCION, h.G_SIN_FECHA])
def test_la_ficha_de_la_app_dice_exactamente_lo_que_la_vista_y_el_markdown(con, emb, grupo) -> None:
    ficha = construir_ficha(grupo, "editorial", con, emb=emb)
    v = vista(ficha, CFG_VER)
    plan = ui.plan_de_ficha(v, CFG)
    esperado = [x.texto for s in v.secciones for x in s.lineas]
    assert Counter(ui.lineas_de_plan(plan)) == Counter(esperado)           # ni una línea de más ni de menos
    assert len(plan.desglose) == 1 and plan.desglose[0].texto.startswith(CFG.ficha.prefijo_desglose)
    md = a_markdown(ficha, CFG_VER)
    assert all(escapar_markdown(t) in md for t in esperado)                 # el Markdown de Notion dice lo mismo


def test_el_resumen_trae_que_se_reporta_estado_y_accion_y_el_detalle_el_resto(con, emb) -> None:
    plan = ui.plan_de_ficha(vista(construir_ficha(h.G_COMPLETO, "editorial", con, emb=emb), CFG_VER), CFG)
    assert [s.clave for s in plan.resumen] == ["que_se_reporta", "accion_recomendada"]
    assert [s.clave for s in plan.detalle] == ["quien_lo_reporta", "respaldado", "falta_comprobar"]
    texto = " ".join(x.texto for s in plan.resumen for x in s.lineas)
    assert "Acción:" in texto and "Estado de evidencia:" in texto and "Titular central" in texto


def test_una_seccion_que_la_interfaz_no_conoce_falla_en_voz_alta(con, emb) -> None:
    v = vista(construir_ficha(h.G_COMPLETO, "editorial", con, emb=emb), CFG_VER)
    chico = CFG.model_copy(update={"ficha": CFG.ficha.model_copy(update={"secciones_desplegables": ["quien_lo_reporta"]})})
    with pytest.raises(ValueError, match="sin ubicar"):
        ui.plan_de_ficha(v, chico)


def test_las_citas_clicables_son_las_de_la_ficha_sin_repetir(con, emb) -> None:
    ficha = construir_ficha(h.G_COMPLETO, "editorial", con, emb=emb)
    citas = ui.citas_de_ficha(ficha)
    claves = [(c.id, c.campo) for c in citas]
    assert claves and len(claves) == len(set(claves))
    assert ("IND-PAN-FP.CPI.TOTL.ZG-2024", "valor") in claves


# ------------------------------------------------------------------ citas


def test_una_cita_de_indicador_muestra_id_campo_valor_fecha_y_url(con) -> None:
    d = ui.detalle_cita(con, "IND-PAN-FP.CPI.TOTL.ZG-2024", "valor", CFG, CFG_VER)
    assert (d.id, d.campo, d.valor, d.encontrada) == ("IND-PAN-FP.CPI.TOTL.ZG-2024", "valor", "0.69322", True)
    assert d.fecha == "2026-10-06 07:00 (hora de Panamá)" and d.url.startswith("https://api.worldbank.org")


def test_una_cita_de_noticia_de_sismo_y_de_grupo_se_resuelve(con) -> None:
    n = ui.detalle_cita(con, "NOT-c000000002", "titulo_limpio", CFG, CFG_VER)
    assert n.valor == "Panamá reporta inflación estable" and n.url and "hora de Panamá" in n.fecha and n.sintetico
    s = ui.detalle_cita(con, "SIS-us7000test", "magnitude", CFG, CFG_VER)
    assert s.valor == "5.1" and s.fecha == "2026-10-06 02:30 (hora de Panamá)" and "usgs" in s.url
    g = ui.detalle_cita(con, h.G_COMPLETO, "n_titulares", CFG, CFG_VER)
    assert g.valor == "3" and g.url is None


def test_un_nulo_es_un_nulo_nunca_cero(con) -> None:
    d = ui.detalle_cita(con, "IND-PAN-SL.UEM.TOTL.ZS-2023", "valor", CFG, CFG_VER)
    assert d.valor == "sin dato" and d.valor != "0"


@pytest.mark.parametrize(("id_registro", "campo"), [
    ("NOT-no-existe", "titulo_limpio"), ("IND-XXX-FOO-1999", "valor"), ("SBP-serie-2026", "valor"), ("OTRO-1", "x"),
    ("NOT-c000000001", "campo_inventado"), ("NOT-c000000001", "titulo_limpio; DROP TABLE noticias"),
])
def test_una_cita_que_no_existe_se_dice_y_no_rompe(con, id_registro, campo) -> None:
    d = ui.detalle_cita(con, id_registro, campo, CFG, CFG_VER)
    assert d.encontrada is False and d.nota and d.valor == ""
    assert con.execute("SELECT count(*) FROM noticias").fetchone()[0] > 0


def test_la_descripcion_del_rss_nunca_se_muestra_ni_aunque_la_cita_la_pida(con) -> None:
    d = ui.detalle_cita(con, "NOT-c000000001", "descripcion", CFG, CFG_VER)
    assert d.encontrada is False and SECRETO not in repr(d)


# ------------------------------------------------------------------ calidad, demo y revisión


def test_el_resumen_de_calidad_cuenta_el_ruido_con_n_e_intervalo(con) -> None:
    r = ui.resumen_de_calidad(con)
    assert r["ruido"].n == r["titulares"] and r["ruido"].k + r["en_bandeja"] == r["titulares"]
    assert r["sinteticos"] == 1 and r["grupos"] == 11
    assert ui.proporcion(0, 0).ic95 is None
    p = ui.proporcion(37, 100)
    assert p.ic95 and p.ic95[0] < 0.37 < p.ic95[1]


def test_el_guion_de_la_demo_sale_de_la_tabla_de_docs_demo_md() -> None:
    pasos = ui.leer_guion(CFG)
    assert len(pasos) >= 4 and pasos[0].tiempo.startswith("0:00")
    texto = "| Tiempo | CU |\n|---|---|\n| 0:00–0:15 | Calidad | Se muestra el reporte | \"Se marca, no se borra\" |\n| otra | fila | sin | tiempo |\n"
    assert ui.pasos_de_demo(texto) == [ui.PasoDemo("0:00–0:15", "Calidad", "Se muestra el reporte", "Se marca, no se borra")]


def test_el_modo_demo_sin_base_de_demo_cae_al_snapshot_y_avisa(tmp_path) -> None:
    assert ui.modo_demo(["--demo"]) is True and ui.modo_demo([]) is False
    ruta, aviso = ui.elegir_base(True, CFG, base_normal=tmp_path / "senales.duckdb")
    assert ruta == tmp_path / "senales.duckdb" and aviso == CFG.textos.sin_demo
    assert ui.elegir_base(False, CFG, base_normal=tmp_path / "senales.duckdb") == (tmp_path / "senales.duckdb", None)


def test_la_revision_solo_se_consulta_hasta_e1_16(con) -> None:
    assert ui.estado_de_revision(con, h.G_COMPLETO, CFG) == "nuevo"
    assert CFG.revision.estados == ["nuevo", "en revisión", "requiere evidencia", "aprobado como borrador", "descartado"]


# ------------------------------------------------------------------ enganche con E1-12


def test_sin_generacion_integrada_la_interfaz_lo_dice_y_no_inventa_un_borrador() -> None:
    sin_funcion = CFG.model_copy(update={"generacion": CFG.generacion.model_copy(update={"funcion": "no_existe"})})
    sin_modulo = CFG.model_copy(update={"generacion": CFG.generacion.model_copy(update={"modulo": "src.no_existe"})})
    for cfg in (sin_funcion, sin_modulo):
        assert ui.cargar_generador(cfg) is None
        e = ui.obtener_paquete("GRP-1", "editorial", cfg)
        assert e.estado == "sin_integrar" and e.paquete is None and e.motivo == "Generación disponible cuando se integre E1-12."


def test_con_generador_se_pide_solo_cache_y_se_aplanan_las_secciones() -> None:
    llamadas: list[tuple[Any, ...]] = []

    def generador(id_grupo: str, modalidad: str, *, solo_cache: bool) -> dict[str, Any]:
        llamadas.append((id_grupo, modalidad, solo_cache))
        return {"titulo_de_trabajo": "Enfoque", "preguntas": ["¿Uno?", "¿Dos?"], "alcance": {"leyenda": LEYENDA}}

    e = ui.obtener_paquete("GRP-1", "editorial", CFG, generador=generador)
    assert e.estado == "disponible" and llamadas == [("GRP-1", "editorial", True)]
    assert ui.secciones_de_paquete(e.paquete) == [("Titulo de trabajo", ["Enfoque"]), ("Preguntas", ["¿Uno?", "¿Dos?"]), ("Alcance", [f"leyenda: {LEYENDA}"])]


def test_un_fallo_del_generador_o_la_falta_de_cache_nunca_rompe_ni_espera() -> None:
    def cae(*a: Any, **k: Any) -> None:
        raise ConnectionError("sin red")

    assert ui.obtener_paquete("GRP-1", "editorial", CFG, generador=cae).estado == "sin_cache"
    assert ui.obtener_paquete("GRP-1", "editorial", CFG, generador=lambda *a, **k: None).estado == "sin_cache"


# ------------------------------------------------------------------ AppTest: las seis pantallas


@pytest.fixture
def app(monkeypatch, base, emb, tmp_path):
    """La app sobre la base de prueba, sin modelo ni red: embeddings y consultor falsos, reporte de carga fijo."""
    consultor, _ = consulta_fixture.crear_consultor(tmp_path / "consulta")
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (base, None))
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)
    monkeypatch.setattr("src.consulta.crear_consultor", lambda ruta, *a, **k: consultor)
    monkeypatch.setattr(ui, "reporte_de_carga", lambda *a, **k: {
        "archivos": {"noticias.csv": {"leidas": 10, "validas": 8, "rechazadas": 2}},
        "distribucion_noticias_validas": {"por_medio": {"TVN Panamá": 5, "La Prensa": 3}},
    })
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(APP), default_timeout=60)


def textos(at: AppTest) -> list[str]:
    """Todo el texto visible de la ejecución (Markdown, títulos, avisos y métricas)."""
    partes: list[str] = []
    for tipo in ("markdown", "caption", "header", "subheader", "info", "warning", "success", "error", "text"):
        partes += [str(e.value) for e in at.get(tipo)]
    partes += [f"{m.label} {m.value}" for m in at.metric]
    partes += [e.label for e in at.expander]
    return partes


def popovers(at: AppTest) -> dict[str, str]:
    """Etiqueta de cada recuadro de cita -> su contenido."""
    return {p.proto.popover.label: "\n".join(str(m.value) for m in p.markdown) for p in at.get("popover")}


def ir(at: AppTest, pantalla: str) -> AppTest:
    at.session_state["pantalla"] = pantalla
    return at.run()


def test_las_seis_pantallas_abren_sin_errores_y_cada_una_lleva_marca_y_leyenda(app) -> None:
    at = app.run()
    assert not at.exception
    for clave in PANTALLAS:
        at = ir(at, clave)
        assert not at.exception, (clave, [e.value for e in at.exception])
        texto = "\n".join(textos(at))
        assert MARCA in texto and LEYENDA in texto, clave


def test_la_barra_lateral_ofrece_las_seis_pantallas_y_la_modalidad(app) -> None:
    at = app.run()
    assert list(at.radio(key="pantalla").options) == [p.titulo for p in CFG.pantallas]
    assert list(at.selectbox(key="modalidad").options) == ["Editorial (TVN)", "Banca (parcial)"]
    assert at.session_state["pantalla"] == CFG.pantalla_inicial


def test_calidad_muestra_el_ruido_con_su_n_y_el_reporte_de_carga(app) -> None:
    at = ir(app.run(), "calidad")
    texto = "\n".join(textos(at))
    assert "Ruido marcado" in texto and "IC 95 %" in texto and "TVN Panamá (5)" in texto
    assert at.dataframe  # reporte de carga y ruido por motivo


def test_la_bandeja_trae_reglas_corte_y_el_ranking_con_las_columnas_de_la_spec(app) -> None:
    at = ir(app.run(), "bandeja")
    assert not at.exception
    texto = "\n".join(textos(at))
    assert "Reglas v" in texto and "Corte del snapshot" in texto and "Una alerta es una invitación a investigar" in texto
    tabla = at.dataframe[0].value
    assert list(tabla.columns) == ["#", "Tema", "Titular representativo", "P", "Rango", "R", "I", "U", "N", "E", "Evidencia", "Acción", "Origen"]
    assert len(tabla) == min(CFG.bandeja.filas_iniciales, 11) and list(tabla["#"]) == list(range(1, len(tabla) + 1))
    todas = at.checkbox(key="bandeja_todas").check().run()
    assert len(todas.dataframe[0].value) == 11
    assert CFG.textos.sintetico in set(todas.dataframe[0].value["Origen"])


def test_abrir_la_ficha_desde_la_bandeja_cambia_de_pantalla_y_conserva_el_grupo(app, con) -> None:
    at = ir(app.run(), "bandeja")
    destino = ui.leer_bandeja(con, "editorial")[2].id_grupo
    at.selectbox(key="bandeja_grupo").select(destino).run()
    at = at.button(key="bandeja_abrir").click().run()
    assert at.session_state["pantalla"] == "ficha" and at.session_state["ficha_grupo"] == destino


def test_la_ficha_pinta_la_vista_completa_y_citas_clicables(app, con, emb) -> None:
    at = app.run()
    at.session_state["id_grupo"] = h.G_COMPLETO
    at = ir(at, "ficha")
    assert not at.exception
    valores = {str(m.value).strip() for m in at.markdown}
    v = vista(construir_ficha(h.G_COMPLETO, "editorial", con, emb=emb), CFG_VER)
    for s in v.secciones:
        for linea in s.lineas:
            assert any(escapar_markdown(linea.texto) in x for x in valores), linea.texto
    cajas = popovers(at)
    assert "Valor:** 0.69322" in cajas["IND-PAN-FP.CPI.TOTL.ZG-2024 · valor"] and "hora de Panamá" in cajas["IND-PAN-FP.CPI.TOTL.ZG-2024 · valor"]
    assert [e.label for e in at.expander][0].startswith("Desglose del puntaje")
    assert CFG.textos.sintetico in "\n".join(valores)           # el grupo trae una noticia sintética


def test_el_atajo_caso_abre_la_ficha_del_grupo(app) -> None:
    app.query_params["caso"] = h.G_SISMO
    at = app.run()
    assert not at.exception
    assert at.session_state["pantalla"] == "ficha" and at.session_state["ficha_grupo"] == h.G_SISMO


def test_el_atajo_caso_con_un_valor_malo_no_rompe_ni_cambia_de_pantalla(app) -> None:
    app.query_params["caso"] = "'; DROP TABLE grupos; --"
    at = app.run()
    assert not at.exception and at.session_state["pantalla"] == "calidad"


def test_la_consulta_responde_con_citas_y_se_abstiene_diciendo_que_falta(app) -> None:
    at = ir(app.run(), "consulta")
    at.text_input(key="consulta_texto").input("¿Cuál fue el desempleo de Panamá en 2023?")
    at = at.button(key="consulta_boton").click().run()
    assert not at.exception
    assert any("Respuesta." in str(s.value) for s in at.success)
    assert "IND-PAN-SL.UEM.TOTL.ZS-2023 · valor" in popovers(at)
    assert LEYENDA in "\n".join(textos(at))
    at.text_input(key="consulta_texto").input("¿Cuál fue el desempleo de Chile en 2024?")
    at = at.button(key="consulta_boton").click().run()
    assert any("Abstención." in str(w.value) for w in at.warning)
    assert any("Haría falta" in str(m.value) for m in at.markdown)


def test_los_ejemplos_de_consulta_se_ejecutan_con_un_clic(app) -> None:
    at = ir(app.run(), "consulta")
    at = at.button(key="consulta_ejemplo_0").click().run()
    assert not at.exception and at.text_input(key="consulta_texto").value == CFG.consulta.ejemplos[0]
    assert at.success or at.warning


def test_una_consulta_vacia_no_llama_al_consultor(app) -> None:
    at = ir(app.run(), "consulta")
    at = at.button(key="consulta_boton").click().run()
    assert not at.exception and not at.success and not at.warning


def test_el_paquete_sin_e1_12_dice_que_no_esta_integrado(app) -> None:
    at = ir(app.run(), "paquete")
    assert not at.exception
    assert any(CFG.textos.sin_borrador == str(i.value) for i in at.info)
    assert "Acción recomendada" in "\n".join(textos(at))


def test_el_paquete_con_generador_muestra_el_borrador_con_marca_y_leyenda(app, monkeypatch) -> None:
    monkeypatch.setattr(ui, "cargar_generador", lambda cfg=None: (lambda id_grupo, modalidad, *, solo_cache: {"titulo_de_trabajo": "Un enfoque", "preguntas": ["¿Qué falta?"]}))
    at = ir(app.run(), "paquete")
    texto = "\n".join(textos(at))
    assert not at.exception and "Un enfoque" in texto and "¿Qué falta?" in texto and MARCA in texto and LEYENDA in texto


def test_la_revision_muestra_los_cinco_estados_sin_ningun_boton_de_accion(app) -> None:
    at = ir(app.run(), "revision")
    assert not at.exception
    assert "Estado actual:** nuevo" in "\n".join(textos(at))
    assert not at.button
    assert list(at.dataframe[0].value["Estados del reto"]) == CFG.revision.estados
    assert "aprobado como borrador" in "\n".join(textos(at))


def test_la_modalidad_banca_se_declara_parcial_y_no_inventa_una_bandeja(app) -> None:
    at = app.run()
    at.selectbox(key="modalidad").select("banca").run()
    at = ir(at, "bandeja")
    assert not at.exception and any(CFG.textos.banca_parcial == str(i.value) for i in at.info)
    assert not at.dataframe


def test_ninguna_pantalla_muestra_la_descripcion_del_rss_ni_un_boton_de_publicar(app) -> None:
    at = app.run()
    for clave in PANTALLAS:
        at = ir(at, clave)
        assert SECRETO not in "\n".join(textos(at)), clave
        etiquetas = [b.label for b in at.button] + [r.label for r in at.radio] + [s.label for s in at.selectbox] + [e.label for e in at.expander]
        assert not [e for e in etiquetas if FORMAS_DE_PUBLICAR.search(e)], clave


def test_la_ficha_nunca_muestra_la_descripcion_aunque_la_cita_la_pida(app) -> None:
    at = app.run()
    at.session_state["id_grupo"] = h.G_COMPLETO
    at = ir(at, "ficha")
    assert SECRETO not in "\n".join(textos(at)) + "\n".join(popovers(at).values())


def test_sin_base_la_app_avisa_y_se_detiene(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (tmp_path / "no_existe.duckdb", None))
    monkeypatch.setattr("sys.argv", ["app.py"])
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert [str(e.value) for e in at.error] == [CFG.textos.sin_base]


def test_el_modo_demo_muestra_la_insignia_y_los_pasos_del_guion(monkeypatch, base, emb, app) -> None:
    monkeypatch.setattr("sys.argv", ["app.py", "--demo"])
    at = app.run()
    assert not at.exception
    lateral = "\n".join(str(m.value) for m in at.sidebar.markdown)
    assert "MODO DEMO" in lateral and ui.leer_guion(CFG)[0].tiempo in lateral


def test_la_app_no_usa_la_red_al_importar_ni_al_pintar(monkeypatch, app) -> None:
    import socket

    def prohibido(*a: Any, **k: Any) -> None:
        raise AssertionError("la interfaz no debe abrir conexiones de red")

    monkeypatch.setattr(socket.socket, "connect", prohibido)
    at = app.run()
    for clave in PANTALLAS:
        at = ir(at, clave)
        assert not at.exception, clave


def test_la_leyenda_de_la_interfaz_es_la_de_restricciones() -> None:
    assert ui.leyenda_de_alcance() == cargar_restricciones().leyendas_alcance.titular_metadatos == LEYENDA

