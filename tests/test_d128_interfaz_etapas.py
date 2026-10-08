"""D-128 · La barra lateral sigue las siete etapas del PDF (sección 3) y hace visible la arquitectura mínima (sección 8).

Corre con ``AppTest`` sobre el snapshot real (``data/senales.duckdb``), sin red ni LLM: la generación solo lee la caché y la consulta no se usa.
Si el snapshot no existe en esta máquina (es un archivo generado, fuera de git), las pruebas se omiten.
"""

from __future__ import annotations

import re

import duckdb
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import interfaz as ui
from src.cache import CacheLlm
from src.configuracion import RAIZ, cargar_interfaz, cargar_temas

BASE = RAIZ / "data" / "senales.duckdb"
APP = RAIZ / "app.py"
CFG = cargar_interfaz()
MARCA = "BORRADOR · requiere revisión"
GRUPO_CU03 = "GRP-79f3183472"
# Los nombres del PDF (sección 3), tal cual.
ETAPAS_PDF = ["1 · Cargar", "2 · Organizar", "3 · Contextualizar", "4 · Priorizar", "5 · Explicar", "6 · Producir", "7 · Revisar"]
TEMAS_PDF = ["Economía", "Logística/Canal", "Turismo", "Servicios públicos", "Eventos naturales", "Regulación"]

pytestmark = pytest.mark.skipif(not BASE.exists(), reason="no hay snapshot (data/senales.duckdb)")


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")   # nunca la revisión real
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(APP), default_timeout=120)


@pytest.fixture(scope="module")
def datos():
    con = duckdb.connect(str(BASE), read_only=True)
    yield con
    con.close()


def textos(at: AppTest) -> str:
    partes: list[str] = []
    for tipo in ("markdown", "caption", "header", "subheader", "info", "warning", "success", "error", "text"):
        partes += [str(e.value) for e in at.get(tipo)]
    partes += [f"{m.label} {m.value}" for m in at.metric]
    partes += [e.label for e in at.expander]
    return "\n".join(partes)


def ir(at: AppTest, pantalla: str) -> AppTest:
    at.session_state["pantalla"] = pantalla
    return at.run()


def metricas(at: AppTest) -> dict[str, str]:
    return {m.label: str(m.value) for m in at.metric}


def numero(texto: str) -> int:
    return int(re.sub(r"\D", "", texto))


# ------------------------------------------------------------------ barra lateral


def test_la_barra_lateral_tiene_las_siete_etapas_del_pdf_en_orden_y_la_consulta_aparte(app) -> None:
    at = app.run()
    assert not at.exception
    assert list(at.radio(key="pantalla_etapa").options) == ETAPAS_PDF
    assert [b.label for b in at.sidebar.button] == ["Cómo funciona", "Consulta"]            # D-131: la entrada y la consulta no son etapas del reto
    assert at.radio(key="pantalla_etapa").value is None and at.session_state["pantalla"] == "inicio"


def test_las_etapas_llevan_los_nombres_y_las_claves_de_siempre() -> None:
    etapas = [(p.clave, p.titulo) for p in CFG.pantallas if not p.separada]
    assert etapas == list(zip(["calidad", "organizar", "contextualizar", "bandeja", "ficha", "paquete", "revision"], ETAPAS_PDF, strict=True))
    assert [p.clave for p in CFG.pantallas if p.separada] == ["consulta"]


def test_elegir_una_etapa_y_la_consulta_cambia_de_pantalla(app) -> None:
    at = app.run()
    at.radio(key="pantalla_etapa").set_value("contextualizar").run()
    assert at.session_state["pantalla"] == "contextualizar" and not at.exception
    at.sidebar.button(key="pantalla_consulta").click().run()
    assert at.session_state["pantalla"] == "consulta" and at.radio(key="pantalla_etapa").value is None and not at.exception
    at.radio(key="pantalla_etapa").set_value("ficha").run()
    assert at.session_state["pantalla"] == "ficha"


@pytest.mark.parametrize("clave", [p.clave for p in CFG.pantallas])
def test_cada_pantalla_abre_sin_errores_con_su_titulo_y_lo_que_pide_el_pdf(app, clave) -> None:
    at = ir(app.run(), clave)
    assert not at.exception, [e.value for e in at.exception]
    p = next(x for x in CFG.pantallas if x.clave == clave)
    assert at.header[0].value == p.titulo and p.descripcion in textos(at)
    assert MARCA in textos(at)


def test_el_atajo_caso_abre_explicar(app) -> None:
    app.query_params["caso"] = GRUPO_CU03
    at = app.run()
    assert not at.exception
    assert at.session_state["pantalla"] == "ficha" and at.session_state["ficha_grupo"] == GRUPO_CU03
    assert at.radio(key="pantalla_etapa").value == "ficha" and at.header[0].value == "5 · Explicar"


# ------------------------------------------------------------------ 1 · Cargar · arquitectura


def test_la_arquitectura_muestra_los_nueve_pasos_del_pdf_con_las_cuentas_de_los_datos(app, datos) -> None:
    at = ir(app.run(), "calidad")      # D-131: la aplicación abre en «Cómo funciona»; la arquitectura está en «1 · Cargar»
    m = metricas(at)
    pasos = [
        "Fuentes públicas / snapshot", "Validación y normalización", "Almacenamiento", "Búsqueda y agrupación", "Motor de priorización",
        "Generación con evidencias", "Interfaz", "Revisión humana", "Registro en Notion",
    ]
    arq = [(k, v) for k, v in m.items() if re.match(r"^\d · ", k) and k.split(" · ", 1)[1] in pasos]
    assert [k.split(" · ", 1)[1] for k, _ in arq] == pasos
    cuenta = {k.split(" · ", 1)[1]: v for k, v in arq}
    contar = lambda t: datos.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: E731, S608
    reporte = ui.reporte_de_carga(RAIZ / "outputs" / "reporte_calidad.json")
    assert numero(cuenta["Fuentes públicas / snapshot"]) == sum(a["leidas"] for a in reporte["archivos"].values())
    assert numero(cuenta["Validación y normalización"]) == sum(a["validas"] for a in reporte["archivos"].values())
    assert numero(cuenta["Almacenamiento"]) == contar("noticias") + contar("indicadores") + contar("sismos")
    assert numero(cuenta["Búsqueda y agrupación"]) == contar("grupos")
    assert numero(cuenta["Motor de priorización"]) == contar("puntajes")
    assert numero(cuenta["Generación con evidencias"]) == len(CacheLlm())
    assert numero(cuenta["Interfaz"]) == contar("evidencia")
    assert numero(cuenta["Revisión humana"]) == 0           # la revisión de esta prueba es una base vacía aparte
    assert numero(cuenta["Registro en Notion"]) == ui.casos_exportados(False)


def test_cada_paso_de_la_arquitectura_lleva_un_boton_a_la_pantalla_donde_se_ve(app) -> None:
    at = ir(app.run(), "calidad")
    botones = {b.key: b for b in at.button if str(b.key).startswith("arq_")}
    esperado = {f"arq_{i}_{pantalla}" for i, paso in enumerate(CFG.cargar.arquitectura) for pantalla in paso.pantallas}
    assert set(botones) == esperado
    botones["arq_3_organizar"].click().run()
    assert at.session_state["pantalla"] == "organizar" and not at.exception and at.header[0].value == "2 · Organizar"
    at = ir(at, "calidad")
    at.button(key="arq_3_contextualizar").click().run()
    assert at.session_state["pantalla"] == "contextualizar"


# ------------------------------------------------------------------ 2 · Organizar


def test_organizar_cuenta_los_titulares_utiles_de_los_seis_temas_y_nunca_muestra_sin_tema(app, datos) -> None:
    at = ir(app.run(), "organizar")
    assert not at.exception
    m = metricas(at)
    nombres = {k: t.nombre for k, t in cargar_temas().temas.items()}
    assert list(nombres.values()) == TEMAS_PDF
    for clave, nombre in nombres.items():
        esperado = datos.execute("SELECT count(*) FROM noticias WHERE NOT es_ruido AND tema_clasificado = ?", [clave]).fetchone()[0]
        assert numero(m[nombre]) == esperado, nombre
    texto = textos(at).lower()
    assert "sin_tema" not in texto and "sin tema" not in texto
    assert not {c for tabla in at.dataframe for c in tabla.value.columns} & {"sin_tema"}
    assert not any("sin_tema" in str(v) for tabla in at.dataframe for v in tabla.value.to_numpy().ravel())


def test_organizar_muestra_el_ruido_marcado_por_motivo_con_su_cuenta(app, datos) -> None:
    at = ir(app.run(), "organizar")
    ruido = at.dataframe[0].value
    esperado = dict(datos.execute("SELECT motivo_ruido, count(*) FROM noticias WHERE es_ruido GROUP BY 1").fetchall())
    assert dict(zip(ruido["Código"], ruido["Titulares"], strict=True)) == esperado
    assert set(ruido["Motivo"]) == {CFG.organizar.motivos_ruido[c] for c in esperado}
    assert f"{sum(esperado.values())} titulares marcados como ruido" in textos(at)


def test_organizar_lista_todos_los_grupos_y_abre_el_cu03_con_20_titulares_18_medios_y_1_procedencia(app, datos) -> None:
    at = ir(app.run(), "organizar")
    grupos = at.dataframe[1].value
    assert list(grupos.columns) == ["Grupo", "Titular central", "Tema", "Titulares", "Medios", "Procedencias"]
    assert len(grupos) == datos.execute("SELECT count(*) FROM grupos").fetchone()[0] and set(grupos["Tema"]) <= set(TEMAS_PDF)
    at.selectbox(key="organizar_grupo").set_value(GRUPO_CU03).run()
    assert not at.exception
    m = metricas(at)
    assert (m["Titulares"], m["Medios"], m["Procedencias independientes"]) == ("20", "18", "1")
    assert "20 titulares, 18 medios, 1 procedencia." in textos(at)
    procedencias, titulares = at.dataframe[2].value, at.dataframe[3].value
    assert list(procedencias["Procedencia"]) == ["Xinhua + Big News Network"] and len(titulares) == 20
    assert "descripcion" not in {c.lower() for c in titulares.columns}
    at.button(key="organizar_abrir").click().run()
    assert at.session_state["pantalla"] == "ficha" and at.session_state["id_grupo"] == GRUPO_CU03


# ------------------------------------------------------------------ 3 · Contextualizar


def test_contextualizar_muestra_cada_vinculo_con_periodo_unidad_y_limitaciones(app, datos) -> None:
    at = ir(app.run(), "contextualizar")
    assert not at.exception
    tabla = at.dataframe[0].value
    assert len(tabla) == datos.execute("SELECT count(*) FROM vinculos WHERE motivo_sin_vinculo IS NULL AND id_evidencia IS NOT NULL").fetchone()[0] > 0
    for col in ("Grupo", "Titular", "Fuente", "Dato oficial", "Relación", "Valor", "Período", "Limitaciones", "Regla que lo sustenta"):
        assert (tabla[col].astype(str).str.strip() != "").all(), col
    assert set(tabla["Fuente"]) <= {"Banco Mundial", "USGS", "SBP"} and set(tabla["Relación"]) <= {"directa", "indirecta", "evento"}
    indicadores = tabla[tabla["Fuente"] == "Banco Mundial"]
    assert indicadores["Período"].str.endswith("(anual)").all() and indicadores["Valor"].str.contains("%|USD|PIB|[a-z]", regex=True).all()
    assert tabla["Dato oficial"].str.match(r"^(IND|SIS|SBP)-").all()
    assert "Dato anual del Banco Mundial: no describe la situación actual." in textos(at)


def test_contextualizar_no_fuerza_la_relacion_y_agrupa_los_grupos_sin_vinculo_por_motivo(app, datos) -> None:
    at = ir(app.run(), "contextualizar")
    texto = textos(at)
    assert "no se fuerza" in texto.lower()
    for motivo in ("sin_relacion_sustentada", "tema_sin_indicador"):
        n = datos.execute(
            "SELECT count(DISTINCT id_grupo) FROM vinculos WHERE motivo_sin_vinculo = ? AND id_grupo NOT IN (SELECT id_grupo FROM vinculos WHERE motivo_sin_vinculo IS NULL)",
            [motivo],
        ).fetchone()[0]
        assert f"{CFG.contextualizar.motivos_sin_vinculo[motivo]}** · {n} grupos · `{motivo}`" in texto
    sin = {g for g, in datos.execute(
        "SELECT DISTINCT id_grupo FROM vinculos WHERE motivo_sin_vinculo IS NOT NULL AND id_grupo NOT IN (SELECT id_grupo FROM vinculos WHERE motivo_sin_vinculo IS NULL)"
    ).fetchall()}
    mostrados = {g for tabla in at.dataframe[1:] for g in tabla.value["Grupo"]}
    assert mostrados == sin
    assert not mostrados & set(at.dataframe[0].value["Grupo"])           # un grupo con vínculo sustentado no aparece como «sin vínculo»


def test_contextualizar_ofrece_las_citas_clicables_con_id_y_campo(app) -> None:
    at = ir(app.run(), "contextualizar")
    cajas = {p.proto.popover.label: "\n".join(str(m.value) for m in p.markdown) for p in at.get("popover")}
    assert cajas and all(re.match(r"^(IND|SIS|SBP)-.+ · (valor|magnitude)$", k) for k in cajas)
    assert any("Dato anual del Banco Mundial" in v for v in cajas.values())


# ------------------------------------------------------------------ 7 · Revisar · registro en Notion


def test_revisar_nombra_el_paso_como_registro_en_notion_y_nunca_habla_de_publicar(app) -> None:
    at = ir(app.run(), "revision")
    assert not at.exception
    rn = CFG.registro_notion
    assert "crea o actualiza la ficha" in rn.explicacion.lower() and "publicar" not in " ".join(rn.model_dump().values()).lower()
    assert at.header[0].value == "7 · Revisar"
    assert "Notion" in CFG.pantallas[6].descripcion
    assert "Registro en Notion" in textos(at) or "Elija" in textos(at) or at.selectbox            # el paso se rotula cuando hay un caso abierto
