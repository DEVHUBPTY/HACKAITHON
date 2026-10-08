"""D-131 · La interfaz explica cómo funciona y separa las etapas: «Cómo funciona» como entrada, indicador de etapas, guía por pantalla y navegación.

Corre con ``AppTest`` sobre el snapshot real (``data/senales.duckdb``), sin red ni LLM. Los textos salen de ``config/interfaz.yaml``.
"""

from __future__ import annotations

import copy
import re
import tomllib

import duckdb
import pytest
import streamlit as st
import yaml
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from src import interfaz as ui
from src.configuracion import RAIZ, ConfigInterfaz, cargar_interfaz
from tests.navegacion_ayuda import ir_a_pantalla

BASE = RAIZ / "data" / "senales.duckdb"
APP = RAIZ / "app.py"
CFG = cargar_interfaz()
ETAPAS = [p for p in CFG.pantallas if not p.separada]
GRUPO_CU03 = "GRP-79f3183472"
TODO_MAYUSCULAS = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9 ·.:/-]{4,}$")

requiere_snapshot = pytest.mark.skipif(not BASE.exists(), reason="no hay snapshot (data/senales.duckdb)")


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")   # nunca la revisión real
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(APP), default_timeout=120)


def ir(at: AppTest, pantalla: str) -> AppTest:
    return ir_a_pantalla(at, pantalla)


def datos_de_config() -> dict:
    return yaml.safe_load((RAIZ / "config" / "interfaz.yaml").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ configuración (sin snapshot)


def test_la_configuracion_trae_todos_los_textos_de_la_guia_y_de_la_entrada() -> None:
    assert CFG.pantalla_inicial == "inicio" and CFG.inicio.titulo == "Cómo funciona"
    assert len(ETAPAS) == 7 and all(p.guia.medida and p.guia.unidad_cuenta for p in ETAPAS)
    assert all(p.guia.que_hace and p.guia.como_leer and p.guia.caso_de_uso and p.guia.entra and p.guia.sale for p in CFG.pantallas)
    assert len(CFG.inicio.modalidades) == 3 and len(CFG.inicio.reglas) == 3
    assert {"{titulo}"} <= {m for t in (CFG.navegacion.anterior, CFG.navegacion.siguiente) for m in re.findall(r"\{\w+\}", t)}


def test_el_modelo_rechaza_claves_desconocidas_en_las_secciones_nuevas() -> None:
    for ruta in (("inicio",), ("navegacion",), ("estilo",), ("pantallas", 0, "guia")):
        datos = copy.deepcopy(datos_de_config())
        destino = datos
        for k in ruta:
            destino = destino[k]
        destino["clave_inventada"] = "x"
        with pytest.raises(ValidationError):
            ConfigInterfaz.model_validate(datos)


def test_cada_etapa_necesita_su_guia_y_su_cuenta() -> None:
    datos = copy.deepcopy(datos_de_config())
    del datos["pantallas"][0]["guia"]["que_hace"]
    with pytest.raises(ValidationError):
        ConfigInterfaz.model_validate(datos)
    datos = copy.deepcopy(datos_de_config())
    del datos["pantallas"][0]["guia"]["medida"], datos["pantallas"][0]["guia"]["unidad_cuenta"]
    with pytest.raises(ValidationError):
        ConfigInterfaz.model_validate(datos)


def test_ningun_texto_nuevo_habla_de_publicar_y_el_css_no_usa_recursos_externos() -> None:
    datos = copy.deepcopy(datos_de_config())
    datos["inicio"]["proposito"] = "Se puede publicar el borrador."
    with pytest.raises(ValidationError):
        ConfigInterfaz.model_validate(datos)
    datos = copy.deepcopy(datos_de_config())
    datos["estilo"]["css"] += "\n@import url('https://fonts.googleapis.com/css?family=X');"
    with pytest.raises(ValidationError):
        ConfigInterfaz.model_validate(datos)
    css = ui.css_de_la_interfaz(CFG)
    assert "${" not in css and "http" not in css and CFG.estilo.acento in css


def test_el_tema_de_streamlit_coincide_con_los_colores_de_la_configuracion() -> None:
    tema = tomllib.loads((RAIZ / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]
    e = CFG.estilo
    assert tema["base"] == "light"
    assert (tema["primaryColor"], tema["textColor"], tema["backgroundColor"], tema["secondaryBackgroundColor"]) == (e.acento, e.tinta, e.papel, e.papel_secundario)
    assert "http" not in tema.get("font", "")      # fuente del sistema: sin recursos externos


def test_los_textos_nuevos_de_la_interfaz_no_son_etiquetas_en_mayusculas() -> None:
    textos = [CFG.inicio.titulo, CFG.inicio.titulo_modalidades, CFG.inicio.titulo_etapas, CFG.inicio.titulo_reglas, CFG.inicio.etiqueta_entra,
              CFG.inicio.etiqueta_sale, CFG.inicio.boton_arquitectura, *(r.titulo for r in CFG.inicio.reglas), CFG.navegacion.que_hace,
              CFG.navegacion.como_leer, CFG.navegacion.caso_de_uso, CFG.navegacion.anterior, CFG.navegacion.siguiente, *CFG.paquete.lectores.values()]
    assert not [t for t in textos if TODO_MAYUSCULAS.match(t)]


def test_las_vecinas_de_cada_etapa_respetan_los_extremos() -> None:
    assert ui.vecinas_de_etapa(CFG, "calidad") == (None, ETAPAS[1])
    assert ui.vecinas_de_etapa(CFG, "bandeja") == (ETAPAS[2], ETAPAS[4])
    assert ui.vecinas_de_etapa(CFG, "revision") == (ETAPAS[5], None)
    assert ui.vecinas_de_etapa(CFG, "consulta") == (None, None) and ui.vecinas_de_etapa(CFG, "inicio") == (None, None)


def test_cada_seccion_del_paquete_dice_a_quien_sirve_segun_la_configuracion() -> None:
    e = CFG.paquete.etiquetas
    quien = lambda modalidad, campo: ui.usuario_de_seccion(CFG, modalidad, e[campo])      # noqa: E731
    for campo in ("brief", "preguntas", "titulo", "enfoque", "fuentes_verificaciones"):
        assert quien("editorial", campo) == "Editor/a y periodista", campo
    for campo in ("titulares", "resumen_web", "copy_digital"):
        assert quien("editorial", campo) == "Productor/a digital (TVN · digital)", campo
    assert quien("editorial", "guion") == "Producción"        # columna «Lector» de docs/salidas.md
    for campo in ("observaciones", "hipotesis_impacto", "sectores", "horizonte", "evidencia", "preguntas"):
        assert quien("banca", campo) == "Analista (banca)", campo
    assert ui.usuario_de_seccion(CFG, "editorial", "Sección que no existe") is None


def test_el_modelo_rechaza_un_lector_no_declarado() -> None:
    datos = copy.deepcopy(datos_de_config())
    datos["paquete"]["usuarios"]["editorial"]["brief"] = "lector_inventado"
    with pytest.raises(ValidationError):
        ConfigInterfaz.model_validate(datos)


# ------------------------------------------------------------------ «Cómo funciona»


@requiere_snapshot
def test_la_aplicacion_abre_en_como_funciona_con_las_siete_etapas_en_orden_y_sus_cuentas(app) -> None:
    at = app.run()
    assert not at.exception and at.session_state["pantalla"] == "inicio" and at.header[0].value == "Cómo funciona"
    assert [m.label for m in at.metric] == [p.titulo for p in ETAPAS]
    con = duckdb.connect(str(BASE), read_only=True)
    try:
        esperado = {
            "organizar": con.execute("SELECT count(*) FROM grupos").fetchone()[0],
            "bandeja": con.execute("SELECT count(*) FROM puntajes").fetchone()[0],
            "ficha": con.execute("SELECT count(*) FROM evidencia").fetchone()[0],
            "contextualizar": con.execute("SELECT count(*) FROM vinculos WHERE motivo_sin_vinculo IS NULL AND id_evidencia IS NOT NULL").fetchone()[0],
        }
    finally:
        con.close()
    valores = {p.clave: m.value for p, m in zip(ETAPAS, at.metric, strict=True)}
    for clave, n in esperado.items():
        assert valores[clave].replace(" ", "") == str(n), clave
    texto = "\n".join(str(m.value) for m in at.markdown) + "\n".join(str(c.value) for c in at.caption)
    for p in ETAPAS:       # cada etapa dice qué entra y qué sale, tal cual la configuración
        assert p.guia.entra in texto and p.guia.sale in texto, p.clave


@requiere_snapshot
def test_como_funciona_explica_las_tres_modalidades_el_reto_y_las_tres_reglas(app) -> None:
    at = app.run()
    texto = "\n".join(str(m.value) for m in at.markdown)
    assert "El equipo elegirá una modalidad" in texto and "PDF sección 3" in texto
    for m in CFG.inicio.modalidades:
        assert m.nombre in texto and m.alcance in texto, m.nombre
    assert "fuente D" in texto and "extensión" in texto
    for r in CFG.inicio.reglas:
        assert r.titulo in texto and r.texto in texto


@requiere_snapshot
def test_cada_tarjeta_de_como_funciona_abre_su_etapa(app) -> None:
    at = app.run()
    at.button(key="inicio_contextualizar").click().run()
    assert at.session_state["pantalla"] == "contextualizar" and not at.exception
    at = ir(at, "inicio")
    at.button(key="inicio_arquitectura").click().run()
    assert at.session_state["pantalla"] == "calidad"


@requiere_snapshot
def test_la_barra_lateral_abre_en_como_funciona_y_vuelve_a_el(app) -> None:
    at = app.run()
    assert [b.label for b in at.sidebar.button] == ["Cómo funciona", "Consulta"] and at.radio(key="pantalla_etapa").value is None
    at.radio(key="pantalla_etapa").set_value("organizar").run()
    assert at.session_state["pantalla"] == "organizar"
    at.sidebar.button(key="pantalla_inicio").click().run()
    assert at.session_state["pantalla"] == "inicio" and at.radio(key="pantalla_etapa").value is None


# ------------------------------------------------------------------ cada etapa: indicador, guía y navegación


@requiere_snapshot
@pytest.mark.parametrize("i", range(7))
def test_cada_etapa_muestra_el_indicador_la_guia_y_sus_botones_de_navegacion(app, i: int) -> None:
    etapa = ETAPAS[i]
    at = ir(app.run(), etapa.clave)
    assert not at.exception and at.header[0].value == etapa.titulo
    pasos = [b for b in at.button if str(b.key).startswith("paso_")]
    assert [b.label for b in pasos] == [p.titulo for p in ETAPAS]
    assert [b.key for b in pasos if b.proto.type == "primary"] == [f"paso_{etapa.clave}"]      # solo la etapa actual va resaltada
    markdown = "\n".join(str(m.value) for m in at.markdown)
    nav, g = CFG.navegacion, etapa.guia
    for rotulo, texto in ((nav.que_hace, g.que_hace), (nav.como_leer, g.como_leer), (nav.caso_de_uso, g.caso_de_uso)):
        assert f"**{rotulo}.** {texto}" in markdown
    assert etapa.descripcion in "\n".join(str(c.value) for c in at.caption)      # el requisito del PDF se conserva
    etiquetas = {b.key: b.label for b in at.button if str(b.key).startswith("nav_")}
    if i == 0:
        assert "nav_anterior" not in etiquetas
    else:
        assert etiquetas["nav_anterior"] == nav.anterior.format(titulo=ETAPAS[i - 1].titulo)
    if i == 6:
        assert "nav_siguiente" not in etiquetas
    else:
        assert etiquetas["nav_siguiente"] == nav.siguiente.format(titulo=ETAPAS[i + 1].titulo)
    assert not [b.label for b in at.button if b.label.rstrip().endswith(("→", "->"))]       # sin flechas pegadas al texto
    visibles = [b.label for b in at.button] + [str(h.value) for h in at.header] + [str(c.value) for c in at.caption]
    assert not [v for v in visibles if TODO_MAYUSCULAS.match(v)]


@requiere_snapshot
def test_siguiente_en_la_etapa_3_lleva_a_la_4_y_anterior_vuelve(app) -> None:
    at = ir(app.run(), "contextualizar")
    at.button(key="nav_siguiente").click().run()
    assert not at.exception and at.session_state["pantalla"] == "bandeja" and at.header[0].value == "4 · Priorizar"
    at.button(key="nav_anterior").click().run()
    assert at.session_state["pantalla"] == "contextualizar"


@requiere_snapshot
def test_el_indicador_de_etapas_salta_a_cualquier_etapa(app) -> None:
    at = ir(app.run(), "organizar")
    at.button(key="paso_revision").click().run()
    assert not at.exception and at.session_state["pantalla"] == "revision" and at.header[0].value == "7 · Revisar"


@requiere_snapshot
def test_navegar_entre_etapas_conserva_el_grupo_elegido(app) -> None:
    at = app.run()
    at.query_params["caso"] = GRUPO_CU03
    at = at.run()
    assert at.session_state["pantalla"] == "ficha" and at.session_state["id_grupo"] == GRUPO_CU03
    for clave in ("nav_siguiente", "nav_siguiente", "nav_anterior"):      # ficha → paquete → revisión → paquete
        at.button(key=clave).click().run()
        assert not at.exception and at.session_state["id_grupo"] == GRUPO_CU03


@requiere_snapshot
def test_el_atajo_caso_sigue_abriendo_explicar(app) -> None:
    app.query_params["caso"] = GRUPO_CU03
    at = app.run()
    assert not at.exception and at.session_state["pantalla"] == "ficha" and at.session_state["ficha_grupo"] == GRUPO_CU03
    assert at.header[0].value == "5 · Explicar" and GRUPO_CU03 in "\n".join(str(m.value) for m in at.markdown)


@requiere_snapshot
def test_la_consulta_lleva_guia_pero_no_forma_parte_de_la_secuencia(app) -> None:
    at = ir(app.run(), "consulta")
    assert not at.exception and at.header[0].value == "Consulta"
    assert not [b for b in at.button if str(b.key).startswith(("paso_", "nav_"))]
    g = next(p.guia for p in CFG.pantallas if p.clave == "consulta")
    assert f"**{CFG.navegacion.caso_de_uso}.** {g.caso_de_uso}" in "\n".join(str(m.value) for m in at.markdown)


@requiere_snapshot
def test_producir_rotula_cada_seccion_con_su_usuario(app, monkeypatch) -> None:
    paquete = {"titulo": "T", "brief": "B", "preguntas": ["¿Uno?"], "guion": "G", "titulares": ["H"], "resumen_web": "R", "copy_digital": "C"}
    monkeypatch.setattr(ui, "obtener_paquete", lambda *a, **k: ui.EstadoPaquete("disponible", paquete))
    at = ir(app.run(), "paquete")
    assert not at.exception and len(at.expander) == len(paquete)
    rotulos = {e.label: next(str(c.value) for c in e.caption) for e in at.expander}
    et = CFG.paquete.etiquetas
    para = lambda lector: CFG.paquete.etiqueta_usuario.format(usuario=CFG.paquete.lectores[lector])      # noqa: E731
    assert rotulos[et["brief"]] == para("editor") and rotulos[et["preguntas"]] == para("editor")
    assert rotulos[et["guion"]] == para("produccion")
    assert all(rotulos[et[c]] == para("digital") for c in ("titulares", "resumen_web", "copy_digital"))
