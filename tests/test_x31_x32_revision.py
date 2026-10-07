"""X31 y X32 · Observaciones de la revisión independiente del PR #30 (E1-16).

B1: la demo exporta aparte. B2/M2: lo aprobado queda guardado y se exporta desde ahí (un caso huérfano no tumba nada). M1: un CASO- nunca
se reutiliza. L1 y L3: la concurrencia y «pedir evidencia» sin vacíos. L4/L5: el procedimiento de Notion está documentado.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import exportar, interfaz as ui
from src import revision as rv
from src.configuracion import RAIZ, cargar_revision
from src.esquemas import Ficha
from src.revision import ErrorDeRevision, MotivoObligatorio, Revisiones
from tests import ficha_ayuda as h
from tests.test_e1_16_revision import (  # noqa: F401 - fixtures compartidas
    EDITORIAL,
    _reloj,
    _sin_modelo,
    abrir,
    base,
    emb,
    generador_de_prueba,
    rev,
)

CFG = cargar_revision()
APP = RAIZ / "app.py"


def huella(carpeta: Path) -> dict[str, str]:
    return {str(p.relative_to(carpeta)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(carpeta.rglob("*")) if p.is_file()}


@pytest.fixture
def raiz_falsa(tmp_path, monkeypatch) -> Path:
    """Las exportaciones por defecto (reales y de demo) caen en una raíz temporal, nunca en el repositorio."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    monkeypatch.setattr(exportar, "RAIZ", raiz)
    return raiz


@pytest.fixture
def base_huerfana(tmp_path, base) -> Path:
    """La base de prueba sin el grupo ``GRP-sismo`` (el pipeline volvió a correr y su hash cambió)."""
    ruta = tmp_path / "senales_nueva.duckdb"
    shutil.copy(base, ruta)
    con = duckdb.connect(str(ruta))
    con.execute("DELETE FROM grupos WHERE id_grupo = ?", [h.G_SISMO])
    con.close()
    return ruta


# ------------------------------------------------------------------ X31 (B1): la demo exporta aparte


def test_la_configuracion_da_rutas_de_exportacion_propias_a_la_demo() -> None:
    e = CFG.exportacion
    assert e.carpeta_demo != e.carpeta and e.fichas_jsonl_demo != e.fichas_jsonl
    assert e.carpeta_demo.startswith("outputs/demo/") and e.fichas_jsonl_demo.startswith("outputs/demo/")


def test_exportar_desde_la_demo_deja_identicos_las_salidas_reales(tmp_path, base, raiz_falsa) -> None:
    real = Revisiones(tmp_path / "real.duckdb", base, ahora=_reloj())
    c = abrir(real, h.G_COMPLETO).id_caso
    abrir(real, h.G_CIFRAS, con_borrador=False)
    exportar.exportar_caso(real, c)
    antes = huella(raiz_falsa / "outputs")
    demo = Revisiones(tmp_path / "demo.duckdb", base, ahora=_reloj(), demo=True)
    cd = abrir(demo, h.G_SISMO, con_borrador=False).id_caso
    assert cd == c                                                            # la demo numera desde CASO-001, como la real
    exportar.exportar_caso(demo, cd)
    despues = huella(raiz_falsa / "outputs")
    assert all(despues[k] == v for k, v in antes.items())                      # lo real: byte a byte igual
    nuevos = set(despues) - set(antes)
    assert nuevos and all(k.startswith("demo/") for k in nuevos)               # y lo de la demo, solo bajo outputs/demo/
    assert (raiz_falsa / CFG.exportacion.fichas_jsonl_demo).exists() and (raiz_falsa / CFG.exportacion.carpeta_demo / f"{cd}.md").exists()


def test_la_cli_de_exportar_en_modo_demo_usa_las_rutas_de_la_demo(tmp_path, base, raiz_falsa) -> None:
    demo = Revisiones(tmp_path / "demo.duckdb", base, demo=True)
    c = abrir(demo, h.G_COMPLETO, con_borrador=False).id_caso
    assert exportar.principal(["--demo", "--caso", c, "--revision", str(demo.ruta), "--base", str(base)]) == 0
    assert (raiz_falsa / CFG.exportacion.carpeta_demo / f"{c}.md").exists() and not (raiz_falsa / CFG.exportacion.carpeta).exists()


# ------------------------------------------------------------------ X32 (B2, M2): se exporta lo que se revisó


def test_la_ficha_revisada_queda_guardada_al_abrir_y_al_aprobar(rev) -> None:
    c = abrir(rev).id_caso
    primera = rev.ficha_revisada(c)
    assert isinstance(primera, Ficha) and primera.id_grupo == h.G_COMPLETO
    rev.rechazar_vinculo(c, EDITORIAL, "IND-COL-FP.CPI.TOTL.ZG-2024", "otro país")
    rev.aceptar(c, EDITORIAL)
    aprobada = rev.ficha_revisada(c)
    assert "IND-COL-FP.CPI.TOTL.ZG-2024" not in json.dumps(aprobada.respaldado.model_dump(mode="json"))     # lo que se aprobó, sin el vínculo rechazado
    assert aprobada != primera
    instantaneas = rev.instantaneas(c)
    assert len(instantaneas) >= 2 and instantaneas[0].ficha == primera                                     # la primera no se pisó


def test_exportar_no_lee_senales_duckdb_sino_la_ficha_guardada(rev, tmp_path, raiz_falsa) -> None:
    c = abrir(rev).id_caso
    rev.aceptar(c, EDITORIAL)
    con_base = exportar.exportar_caso(rev, c, tmp_path / "a", tmp_path / "a.jsonl").markdown
    sin_base = Revisiones(rev.ruta, tmp_path / "no_existe.duckdb", ahora=_reloj())
    e = exportar.exportar_caso(sin_base, c, tmp_path / "b", tmp_path / "b.jsonl")
    assert e.markdown.splitlines()[:6] == con_base.splitlines()[:6] and "aprobado como borrador" in e.markdown
    assert json.loads((tmp_path / "b.jsonl").read_text(encoding="utf-8"))["estado_revision"] == "aprobado como borrador"


def test_un_caso_huerfano_no_tumba_la_exportacion_de_los_demas(tmp_path, base, base_huerfana, raiz_falsa) -> None:
    r = Revisiones(tmp_path / "r.duckdb", base, ahora=_reloj())
    c1, c2 = abrir(r, h.G_COMPLETO).id_caso, abrir(r, h.G_SISMO, con_borrador=False).id_caso
    nueva = Revisiones(r.ruta, base_huerfana, ahora=_reloj())                  # el pipeline corrió otra vez: GRP-sismo ya no existe
    e1 = exportar.exportar_caso(nueva, c1)
    e2 = exportar.exportar_caso(nueva, c2)                                     # el huérfano tampoco se rompe: sale de su ficha guardada
    lineas = [json.loads(x) for x in (raiz_falsa / CFG.exportacion.fichas_jsonl).read_text(encoding="utf-8").splitlines()]
    assert [x["id_caso"] for x in lineas] == [c1, c2] and e1.id_caso == c1 and h.G_SISMO in e2.markdown


def test_abrir_o_regenerar_un_caso_huerfano_dice_la_verdad(tmp_path, base, base_huerfana) -> None:
    r = Revisiones(tmp_path / "r.duckdb", base, ahora=_reloj())
    c = abrir(r, h.G_SISMO, con_borrador=False).id_caso
    nueva = Revisiones(r.ruta, base_huerfana, ahora=_reloj())
    filas = len(nueva.todas_las_filas())
    with pytest.raises(ErrorDeRevision, match="ya no existe"):
        nueva.regenerar(c, EDITORIAL, generador=generador_de_prueba())
    with pytest.raises(ErrorDeRevision, match="ya no existe"):
        nueva.abrir("GRP-inexistente", "editorial", EDITORIAL)
    assert len(nueva.todas_las_filas()) == filas and nueva.casos() == r.casos()
    nueva.descartar(c, EDITORIAL, "Duplicado de otro caso")                    # lo que no necesita la ficha viva sigue funcionando
    assert nueva.estado(c) == "descartado"


def test_la_tabla_de_fichas_guardadas_tambien_es_de_solo_agregar(rev) -> None:
    c = abrir(rev).id_caso
    antes = rev.instantaneas(c)
    rev.rechazar_vinculo(c, EDITORIAL, "IND-COL-FP.CPI.TOTL.ZG-2024", "otro país")
    rev.aceptar(c, EDITORIAL)
    despues = rev.instantaneas(c)
    assert despues[: len(antes)] == antes and len(despues) > len(antes)


# ------------------------------------------------------------------ M1: un CASO- no se reutiliza


def test_borrar_la_base_de_revisiones_no_reutiliza_los_id(tmp_path, base) -> None:
    ruta = tmp_path / "revision.duckdb"
    r = Revisiones(ruta, base, ahora=_reloj())
    assert r.abrir(h.G_COMPLETO, "editorial", EDITORIAL).id_caso == "CASO-001"
    assert r.abrir(h.G_CIFRAS, "editorial", EDITORIAL).id_caso == "CASO-002"
    ruta.unlink()
    nueva = Revisiones(ruta, base, ahora=_reloj())
    assert nueva.abrir(h.G_SISMO, "editorial", EDITORIAL).id_caso == "CASO-003"      # el registro persistido lo recuerda


def test_sin_base_ni_registro_los_archivos_exportados_tambien_cuentan(tmp_path, base, raiz_falsa) -> None:
    ruta = tmp_path / "revision.duckdb"
    r = Revisiones(ruta, base, ahora=_reloj(), huellas=[raiz_falsa / CFG.exportacion.carpeta, raiz_falsa / CFG.exportacion.fichas_jsonl])
    c = abrir(r, h.G_COMPLETO, con_borrador=False).id_caso
    exportar.exportar_caso(r, c)
    ruta.unlink()
    r.ruta.with_suffix(".casos.csv").unlink()
    nueva = Revisiones(ruta, base, ahora=_reloj(), huellas=[raiz_falsa / CFG.exportacion.carpeta, raiz_falsa / CFG.exportacion.fichas_jsonl])
    assert nueva.abrir(h.G_CIFRAS, "editorial", EDITORIAL).id_caso == "CASO-002"


def test_el_registro_de_casos_es_un_csv_de_solo_agregar(tmp_path, base) -> None:
    r = Revisiones(tmp_path / "revision.duckdb", base, ahora=_reloj())
    r.abrir(h.G_COMPLETO, "editorial", EDITORIAL)
    r.abrir(h.G_CIFRAS, "banca", "Juan Zhou")
    with r.ruta.with_suffix(".casos.csv").open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    assert [(x["id_caso"], x["id_grupo"], x["modalidad"]) for x in filas] == [("CASO-001", h.G_COMPLETO, "editorial"), ("CASO-002", h.G_CIFRAS, "banca")]


# ------------------------------------------------------------------ L1 y L3


def test_un_conflicto_de_concurrencia_se_traduce_a_un_aviso_honesto(rev, monkeypatch) -> None:
    c = abrir(rev).id_caso

    def choca(*a: Any, **k: Any) -> None:
        raise duckdb.TransactionException("PRIMARY KEY or UNIQUE constraint violation")

    monkeypatch.setattr(Revisiones, "_insertar", choca)
    with pytest.raises(rv.ConflictoDeConcurrencia, match="(?i)otra persona") as e:
        rev.aceptar(c, EDITORIAL)
    assert isinstance(e.value, ErrorDeRevision)


def test_abrir_a_la_vez_el_mismo_grupo_devuelve_el_caso_que_ya_existe(rev, monkeypatch) -> None:
    ganador = rev.abrir(h.G_COMPLETO, "editorial", EDITORIAL)
    originales = Revisiones.caso_de_grupo
    llamadas = {"n": 0}

    def primero_no_lo_ve(self: Revisiones, g: str, m: str):
        llamadas["n"] += 1
        return None if llamadas["n"] == 1 else originales(self, g, m)

    monkeypatch.setattr(Revisiones, "caso_de_grupo", primero_no_lo_ve)
    assert rev.abrir(h.G_COMPLETO, "editorial", EDITORIAL).id_caso == ganador.id_caso


@pytest.mark.parametrize("vacios", [[], None])
def test_pedir_evidencia_exige_al_menos_un_vacio(rev, vacios) -> None:
    c = abrir(rev).id_caso
    with pytest.raises(MotivoObligatorio, match="vacío"):
        rev.pedir_evidencia(c, EDITORIAL, vacios or [])
    assert rev.estado(c) == "en revisión"


def test_pedir_evidencia_sin_vacios_acepta_un_motivo_escrito(rev) -> None:
    c = abrir(rev).id_caso
    with pytest.raises(MotivoObligatorio):
        rev.pedir_evidencia(c, EDITORIAL, [], motivo="   ")
    f = rev.pedir_evidencia(c, EDITORIAL, [], motivo="Falta una fuente oficial que la ficha no detecta")
    assert (f.estado_nuevo, f.motivo, f.detalle) == ("requiere evidencia", "Falta una fuente oficial que la ficha no detecta", {"vacios": []})


def test_la_ui_pide_evidencia_con_un_motivo_cuando_la_ficha_no_tiene_vacios(app, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["app.py"])
    at = _abrir_en_ui(app)                                                     # GRP-completo no tiene vacíos
    assert at.button(key="revision_pedir").disabled
    at.text_input(key="revision_motivo_evidencia").input("Falta confirmar con el MEF").run()
    at = at.button(key="revision_pedir").click().run()
    assert not at.exception and "Estado actual:** requiere evidencia" in "\n".join(str(m.value) for m in at.markdown)


def test_un_conflicto_al_abrir_no_deja_ninguna_fila_en_el_registro(tmp_path, base, monkeypatch) -> None:
    r = Revisiones(tmp_path / "revision.duckdb", base, ahora=_reloj())
    r.abrir(h.G_COMPLETO, "editorial", EDITORIAL)
    antes = r.registro.read_text(encoding="utf-8")
    monkeypatch.setattr(Revisiones, "_insertar", lambda *a, **k: (_ for _ in ()).throw(duckdb.TransactionException("conflicto")))
    with pytest.raises(rv.ConflictoDeConcurrencia):
        r.abrir(h.G_CIFRAS, "editorial", EDITORIAL)
    assert r.registro.read_text(encoding="utf-8") == antes and [c.id_grupo for c in r.casos()] == [h.G_COMPLETO]
    monkeypatch.undo()
    assert r.abrir(h.G_CIFRAS, "editorial", EDITORIAL).id_caso == "CASO-002"        # y el número no quedó gastado


# ------------------------------------------------------------------ L4 y L5: el procedimiento de Notion


def test_el_procedimiento_de_importacion_a_notion_esta_documentado() -> None:
    t = (RAIZ / "docs" / "notion.md").read_text(encoding="utf-8")
    for frase in ("agrega filas", "actualiza", "Caso de uso", "E3-03", "CASO-"):
        assert frase in t, frase


# ------------------------------------------------------------------ UI: la demo y los errores de exportación


@pytest.fixture
def app(monkeypatch, base, emb, tmp_path, raiz_falsa):
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (base, None))
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / ("demo.duckdb" if demo else "revision.duckdb"))
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)
    monkeypatch.setattr(ui, "obtener_paquete", lambda *a, **k: ui.EstadoPaquete("sin_cache", motivo="sin caché"))
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(APP), default_timeout=60)


def _abrir_en_ui(at: AppTest) -> AppTest:
    at.session_state["id_grupo"] = h.G_COMPLETO
    at.session_state["pantalla"] = "revision"
    at = at.run()
    at.selectbox(key="revision_revisor").select(EDITORIAL).run()
    return at.button(key="revision_abrir").click().run()


def test_el_boton_exportar_de_la_demo_escribe_en_outputs_demo(app, monkeypatch, raiz_falsa) -> None:
    monkeypatch.setattr("sys.argv", ["app.py", "--demo"])
    at = _abrir_en_ui(app)
    at = at.button(key="revision_exportar").click().run()
    assert not at.exception and (raiz_falsa / CFG.exportacion.carpeta_demo / "CASO-001.md").exists()
    assert not (raiz_falsa / CFG.exportacion.carpeta).exists() and not (raiz_falsa / CFG.exportacion.fichas_jsonl).exists()


def test_un_error_al_exportar_se_muestra_sin_traceback(app, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["app.py"])
    at = _abrir_en_ui(app)

    def falla(*a: Any, **k: Any) -> None:
        raise LookupError("GRP-x: no existe en la tabla grupos")

    monkeypatch.setattr(exportar, "exportar_caso", falla)
    at = at.button(key="revision_exportar").click().run()
    assert not at.exception and any("No se pudo exportar" in str(e.value) for e in at.error)


def test_la_pantalla_abre_un_caso_huerfano_con_su_ficha_guardada(app, monkeypatch, tmp_path, base, base_huerfana) -> None:
    monkeypatch.setattr("sys.argv", ["app.py"])
    r = Revisiones(tmp_path / "revision.duckdb", base)
    r.abrir(h.G_SISMO, "editorial", EDITORIAL)
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (base_huerfana, None))
    app.session_state["pantalla"] = "revision"
    at = app.run()
    assert not at.exception and "CASO-001" in "\n".join(str(w.value) for w in list(at.warning) + list(at.info))
