"""D-132 · La modalidad Banca funciona en toda la interfaz, la fuente D (SBP) es solo de la banca y cada cambio de etapa sube al inicio.

Corre sobre el snapshot real (``data/senales.duckdb``) sin red ni LLM. Nada escribe en los archivos vivos: la copia de sesión, las bases con
vínculos de la SBP y la revisión viven en carpetas temporales.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest
import streamlit as st
import yaml
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from src import contexto, contexto_sbp, corrida as co, db, interfaz as ui, prioridad
from src.configuracion import RAIZ, ConfigModalidad, cargar_corrida, cargar_fuentes, cargar_modalidad, cargar_vinculos
from src.ficha import construir_ficha, leer_datos
from tests.navegacion_ayuda import ir_a_pantalla

BASE = RAIZ / "data" / "senales.duckdb"
APP = RAIZ / "app.py"
GRUPO = "GRP-da35c3dead"
ID_SBP = "SBP-MOROSIDAD-SISTEMA-2024-12"

requiere_snapshot = pytest.mark.skipif(not BASE.exists(), reason="no hay snapshot (data/senales.duckdb)")


def huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


@pytest.fixture
def temporal(monkeypatch, tmp_path):
    """Las copias de sesión van a una carpeta temporal de la prueba, no a la del sistema."""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "sistema"))
    return tmp_path


@pytest.fixture
def base_con_sbp(tmp_path) -> Path:
    """Copia del snapshot con vínculos de la SBP en un grupo (el snapshot real no dispara la regla ``banca``)."""
    destino = tmp_path / "con_sbp.duckdb"
    shutil.copy2(BASE, destino)
    series = contexto_sbp.cargar_series(RAIZ / "data" / "processed" / "sbp_series.csv")
    filas = contexto_sbp.vincular_grupo(GRUPO, "banca", series, cargar_vinculos(), cargar_fuentes())
    assert filas, "la regla banca debe producir filas de la SBP"
    con = db.conectar(destino)
    try:
        contexto._reemplazar(con, "sbp", filas, True)
    finally:
        con.close()
    return destino


# ------------------------------------------------------------------ configuración


def test_cada_modalidad_declara_sus_fuentes_oficiales() -> None:
    assert cargar_modalidad("editorial").fuentes_oficiales == ["indicador", "usgs"]
    assert cargar_modalidad("banca").fuentes_oficiales == ["indicador", "usgs", "sbp"]
    assert not cargar_modalidad("editorial").permite_fuente("sbp") and cargar_modalidad("banca").permite_fuente("sbp")


def test_el_modelo_exige_las_fuentes_y_rechaza_una_desconocida() -> None:
    datos = yaml.safe_load((RAIZ / "config" / "modalidad_editorial.yaml").read_text(encoding="utf-8"))
    for malo in ({"fuentes_oficiales": ["indicador", "twitter"]}, {"fuentes_oficiales": []}):
        with pytest.raises(ValidationError):
            ConfigModalidad.model_validate({**datos, **malo})
    del datos["fuentes_oficiales"]
    with pytest.raises(ValidationError):
        ConfigModalidad.model_validate(datos)


def test_filtrar_vinculos_deja_solo_las_fuentes_permitidas() -> None:
    filas = [{"fuente": "indicador"}, {"fuente": "usgs"}, {"fuente": "sbp"}]
    assert [f["fuente"] for f in cargar_modalidad("editorial").filtrar_vinculos(filas)] == ["indicador", "usgs"]
    assert [f["fuente"] for f in cargar_modalidad("banca").filtrar_vinculos(filas)] == ["indicador", "usgs", "sbp"]


# ------------------------------------------------------------------ fuente D solo en banca


@requiere_snapshot
def test_un_vinculo_de_la_sbp_no_aparece_en_la_ficha_editorial_y_si_en_la_de_banca(base_con_sbp, temporal) -> None:
    con = db.conectar(base_con_sbp, solo_lectura=True)
    try:
        assert {v["fuente"] for v in leer_datos(con, GRUPO, "editorial").vinculos} <= {"indicador", "usgs"}
        ficha_editorial = json.dumps(construir_ficha(GRUPO, "editorial", con).model_dump(mode="json"), ensure_ascii=False)
    finally:
        con.close()
    assert ID_SBP not in ficha_editorial and "SBP-" not in ficha_editorial
    copia = co.base_de_modalidad(base_con_sbp, "banca")
    con = db.conectar(copia, solo_lectura=True)
    try:
        assert "sbp" in {v["fuente"] for v in leer_datos(con, GRUPO, "banca").vinculos}
        assert ID_SBP in json.dumps(construir_ficha(GRUPO, "banca", con).model_dump(mode="json"), ensure_ascii=False)
    finally:
        con.close()


@requiere_snapshot
def test_la_pantalla_contextualizar_filtra_por_modalidad(base_con_sbp, temporal) -> None:
    con = db.conectar(base_con_sbp, solo_lectura=True)
    try:
        nombres = {}
        editorial, sin_e = ui.vinculos_oficiales(con, nombres, modalidad="editorial")
        todos, _ = ui.vinculos_oficiales(con, nombres)
        banca, _ = ui.vinculos_oficiales(con, nombres, modalidad="banca")
    finally:
        con.close()
    assert not [v for v in editorial if v.id_grupo == GRUPO and v.id_evidencia.startswith("SBP-")]
    assert len(banca) == len(todos) > len(editorial)
    assert any(v.id_evidencia == ID_SBP for v in banca)
    assert GRUPO in {g.id_grupo for g in sin_e} or any(v.id_grupo == GRUPO for v in editorial)    # sin su único vínculo, el grupo queda «sin vínculo» para editorial


@requiere_snapshot
def test_el_puntaje_editorial_no_cambia_por_los_vinculos_de_la_sbp(base_con_sbp, tmp_path) -> None:
    """La SBP en la base no altera los puntajes editoriales: mismo puntaje, estado y acción que sin ella."""
    sin = tmp_path / "sin.duckdb"
    shutil.copy2(BASE, sin)
    ahora = prioridad.fecha_de_corte(RAIZ / "data" / "manifest.json")
    resultados = []
    for base in (sin, base_con_sbp):
        prioridad.ejecutar(base, tmp_path / f"{base.stem}.json", ahora, None, "editorial")
        con = db.conectar(base, solo_lectura=True)
        try:
            resultados.append(con.execute("SELECT p.id_grupo, p.puntaje, e.estado, e.accion FROM puntajes p JOIN evidencia e USING (id_grupo) ORDER BY 1").fetchall())
        finally:
            con.close()
    assert resultados[0] == resultados[1] and len(resultados[0]) > 0


# ------------------------------------------------------------------ copia de sesión de otra modalidad


@requiere_snapshot
def test_la_copia_de_banca_tiene_puntajes_de_banca_y_no_toca_la_base_viva(temporal) -> None:
    antes = huella(BASE)
    assert co.modalidad_puntuada(BASE) == "editorial"
    copia = co.base_de_modalidad(BASE, "banca")
    assert copia != BASE and copia.is_relative_to(temporal) and co.modalidad_puntuada(copia) == "banca"
    assert co.base_de_modalidad(BASE, "banca") == copia                        # se reutiliza: una sola vez por base y modalidad
    assert co.base_de_modalidad(BASE, "editorial") == BASE                     # la modalidad de la base vuelve a la base viva
    con = db.conectar(copia, solo_lectura=True)
    try:
        filas = ui.leer_bandeja(con, "banca")
        assert filas and {f.accion for f in filas} & {"Seguimiento prioritario", "Incluir como contexto"}
        assert ui.agrupar_por_sector(filas, cargar_modalidad("banca"))
    finally:
        con.close()
    assert huella(BASE) == antes


@requiere_snapshot
def test_la_ficha_de_banca_se_arma_sobre_la_copia_y_sobre_la_viva_sigue_fallando(temporal) -> None:
    copia = co.base_de_modalidad(BASE, "banca")
    con = db.conectar(copia, solo_lectura=True)
    try:
        ficha = construir_ficha(GRUPO, "banca", con)
        assert ficha.accion_recomendada.accion in {"Incluir como contexto", "Incluir como señal a confirmar", "Seguimiento", "Seguimiento prioritario", "Archivar",
                                                    "Incluir en el boletín como observación"}
    finally:
        con.close()
    con = db.conectar(BASE, solo_lectura=True)
    try:
        with pytest.raises(db.ModalidadDistinta):
            construir_ficha(GRUPO, "banca", con)
    finally:
        con.close()


@requiere_snapshot
def test_cambiar_el_archivo_de_la_base_recalcula_la_copia(temporal, tmp_path) -> None:
    base = tmp_path / "base.duckdb"
    shutil.copy2(BASE, base)
    primera = co.base_de_modalidad(base, "banca")
    base.touch()
    segunda = co.base_de_modalidad(base, "banca")
    assert primera != segunda and segunda.exists() and not primera.exists()    # la huella cambió: la copia anterior se descarta


def test_la_carpeta_de_las_copias_sale_de_la_configuracion() -> None:
    assert cargar_corrida().corridas.subcarpeta_modalidades == "modalidades"
    assert "{modalidad}" in cargar_corrida().textos.aviso_copia_modalidad


# ------------------------------------------------------------------ interfaz


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")     # nunca la revisión real
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "sistema"))
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(APP), default_timeout=180)


def textos(at: AppTest) -> str:
    return "\n".join(str(x.value) for tipo in ("markdown", "caption", "subheader", "header", "info", "warning") for x in at.get(tipo) if hasattr(x, "value") and x.value)


@requiere_snapshot
def test_banca_muestra_priorizar_explicar_y_producir_con_puntajes_de_banca_y_editorial_al_volver(app) -> None:
    antes = huella(BASE)
    at = app
    ir_a_pantalla(at, "bandeja")
    assert not at.exception
    assert "calculados para esta sesión" not in textos(at)
    editorial = [str(f.value) for f in at.dataframe]
    at.session_state["modalidad"] = "banca"
    for pantalla in ("bandeja", "ficha", "paquete"):
        at.session_state["id_grupo"] = GRUPO
        ir_a_pantalla(at, pantalla)
        assert not at.exception, (pantalla, [e.value for e in at.exception])
        assert not [e for e in at.error], (pantalla, [e.value for e in at.error])
        assert "Puntajes de Banca calculados para esta sesión sobre una copia de la base" in textos(at)
    ir_a_pantalla(at, "bandeja")
    assert "Continuidad operativa" in textos(at) + " ".join(str(x.label) for x in at.get("expander") if hasattr(x, "label"))
    at.session_state["modalidad"] = "editorial"
    at.run()
    assert not at.exception and "calculados para esta sesión" not in textos(at)
    assert [str(f.value) for f in at.dataframe] == editorial
    assert huella(BASE) == antes                                              # la base viva no se tocó


# ------------------------------------------------------------------ desplazamiento


def test_el_script_sube_al_inicio_sin_recursos_externos() -> None:
    js = ui.script_ir_arriba("bandeja")
    assert "scrollTo" in js and "http" not in js and "bandeja" in js and js.startswith("<script>")
    assert ui.script_ir_arriba("ficha") != js


def test_solo_hay_que_subir_cuando_cambia_la_etapa() -> None:
    assert not ui.etapa_cambio(None, "ficha")       # primera carga o enlace directo
    assert not ui.etapa_cambio("ficha", "ficha")
    assert ui.etapa_cambio("inicio", "calidad")


@requiere_snapshot
def test_el_script_se_emite_al_cambiar_de_etapa_y_no_al_volver_a_dibujar(app) -> None:
    at = app
    at.run()
    assert not [h for h in at.get("html") if "scrollTo" in str(h.proto)]       # primera carga: no
    ir_a_pantalla(at, "bandeja")
    assert [h for h in at.get("html") if "ir arriba: bandeja" in str(h.proto)]
    at.run()                                                                   # mismo dibujo: no se repite
    assert not [h for h in at.get("html") if "scrollTo" in str(h.proto)]
    at.session_state["modalidad"] = "banca"                                    # cambiar de modalidad no es cambiar de etapa
    at.run()
    assert not [h for h in at.get("html") if "scrollTo" in str(h.proto)]
