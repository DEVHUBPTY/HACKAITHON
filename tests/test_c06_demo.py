"""C-06 · Base de la demo: snapshot + caso sintético de CU-04 (contradicción abierta), con insignia SINTÉTICO y sin tocar lo real.

Sin red ni LLM. La base de demo se arma en una carpeta temporal con ``scripts.preparar_demo`` (embeddings locales de ``models/``).
``data/senales.duckdb`` y ``data/revision.duckdb`` solo se leen: una prueba comprueba que no cambian.
"""

from __future__ import annotations

import csv
import importlib
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from scripts import preparar_demo
from src import db, exportar
from src import interfaz as ui
from src.configuracion import RAIZ, cargar_interfaz, cargar_normalizacion
from src.revision import Revisiones
from tests.navegacion_ayuda import ir_a_pantalla

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

SNAPSHOT = RAIZ / "data" / "senales.duckdb"
REVISION_REAL = RAIZ / "data" / "revision.duckdb"
FIXTURE = RAIZ / "tests" / "fixtures" / "c06_contradiccion_demo.csv"
APP = RAIZ / "app.py"
IDS = ("SYN-C06-001", "SYN-C06-002")
CFG = cargar_interfaz()
SINTETICO = CFG.textos.sintetico

pytestmark = pytest.mark.skipif(not SNAPSHOT.exists(), reason="no hay snapshot (data/senales.duckdb)")


def _huella(ruta: Path) -> tuple[int, int] | None:
    return (ruta.stat().st_size, ruta.stat().st_mtime_ns) if ruta.exists() else None


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> Path:
    antes = (_huella(SNAPSHOT), _huella(REVISION_REAL))
    destino = tmp_path_factory.mktemp("demo") / "demo.duckdb"
    preparar_demo.preparar(destino)
    assert (_huella(SNAPSHOT), _huella(REVISION_REAL)) == antes     # lo real no se toca
    return destino


@pytest.fixture(scope="module")
def grupo_sintetico(demo) -> str:
    con = duckdb.connect(str(demo), read_only=True)
    try:
        (g,) = {r[0] for r in con.execute("SELECT id_grupo FROM noticias WHERE origen = 'sintetico'").fetchall()}
    finally:
        con.close()
    return g


# ------------------------------------------------------------------ el fixture sintético


def test_el_fixture_son_dos_titulares_sinteticos_de_dos_medios_con_cifras_incompatibles() -> None:
    filas = list(csv.DictReader(FIXTURE.open(encoding="utf-8")))
    assert [f["id_noticia"] for f in filas] == list(IDS)
    assert {f["origen"] for f in filas} == {"sintetico"}
    assert len({f["medio"] for f in filas}) == 2 and all("Sintético" in f["medio"] for f in filas)
    assert len({f["url"].split("/")[2] for f in filas}) == 2                  # dos dominios: dos procedencias
    assert all(f["url"].split("/")[2].endswith(".example") for f in filas)     # dominio reservado: no apunta a nadie real
    assert "36" in filas[0]["titulo"] and "28" in filas[1]["titulo"]
    assert all(f["fecha_deteccion"] >= "2026-10-01" for f in filas)           # dentro de la ventana del snapshot (D-74)


# ------------------------------------------------------------------ la base de la demo


def test_la_demo_tiene_el_caso_sintetico_como_un_grupo_con_contradiccion_abierta(demo, grupo_sintetico) -> None:
    con = duckdb.connect(str(demo), read_only=True)
    try:
        assert grupo_sintetico.startswith("GRP-")
        titulares = con.execute("SELECT id_noticia, origen, medio, es_ruido FROM noticias WHERE id_grupo = ? ORDER BY id_noticia", [grupo_sintetico]).fetchall()
        assert [(i, o, r) for i, o, _, r in titulares] == [(IDS[0], "sintetico", False), (IDS[1], "sintetico", False)]
        assert len({m for _, _, m, _ in titulares}) == 2
        (c,) = con.execute("SELECT id_noticia_a, id_noticia_b, estado, reglas, detalle FROM contradicciones WHERE id_grupo = ?", [grupo_sintetico]).fetchall()
        assert (c[0], c[1], c[2], c[3]) == (*IDS, "verificar", "cifras_distintas")
        assert "36" in c[4] and "28" in c[4]
        (abiertas,) = con.execute("SELECT contradicciones_abiertas FROM evidencia WHERE id_grupo = ?", [grupo_sintetico]).fetchone()
        assert abiertas == 1
        assert con.execute("SELECT count(*) FROM puntajes WHERE id_grupo = ?", [grupo_sintetico]).fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM noticias WHERE origen = 'sintetico' AND id_noticia NOT LIKE 'SYN-%'").fetchone()[0] == 0
    finally:
        con.close()


def test_la_demo_es_el_snapshot_mas_el_caso_sin_cambiar_los_grupos_reales(demo, grupo_sintetico) -> None:
    real, copia = duckdb.connect(str(SNAPSHOT), read_only=True), duckdb.connect(str(demo), read_only=True)
    try:
        assert copia.execute("SELECT count(*) FROM noticias").fetchone()[0] == real.execute("SELECT count(*) FROM noticias").fetchone()[0] + len(IDS)
        grupos_reales = {r[0] for r in real.execute("SELECT id_grupo FROM grupos").fetchall()}
        grupos_demo = {r[0] for r in copia.execute("SELECT id_grupo FROM grupos").fetchall()}
        assert grupos_demo == grupos_reales | {grupo_sintetico}
        assert real.execute("SELECT count(*) FROM noticias WHERE origen = 'sintetico'").fetchone()[0] == 0   # el snapshot no lleva sintéticos
    finally:
        real.close()
        copia.close()


def test_el_caso_sintetico_no_altera_el_puntaje_de_los_grupos_reales(demo, grupo_sintetico) -> None:
    """Auditoría: N, P y el orden de los grupos reales en la demo son los de la base viva; el sintético tiene su propio puntaje."""
    consulta = "SELECT id_grupo, puntaje, novedad, posicion FROM puntajes ORDER BY posicion"
    real, copia = duckdb.connect(str(SNAPSHOT), read_only=True), duckdb.connect(str(demo), read_only=True)
    try:
        viva, en_demo = real.execute(consulta).fetchall(), copia.execute(consulta).fetchall()
    finally:
        real.close()
        copia.close()
    reales = [f for f in en_demo if f[0] != grupo_sintetico]
    assert [(g, p, n) for g, p, n, _ in reales] == [(g, p, n) for g, p, n, _ in viva]      # mismo P, mismo N y mismo orden relativo
    assert any(f[0] == grupo_sintetico and f[1] is not None for f in en_demo)


def test_preparar_es_idempotente(demo, grupo_sintetico, tmp_path) -> None:
    segunda = tmp_path / "demo.duckdb"
    preparar_demo.preparar(segunda)
    for ruta in (demo, segunda):
        con = duckdb.connect(str(ruta), read_only=True)
        try:
            assert con.execute("SELECT count(*) FROM noticias WHERE origen = 'sintetico'").fetchone()[0] == len(IDS)
            assert con.execute("SELECT count(*) FROM contradicciones WHERE estado = 'verificar'").fetchone()[0] == 1
            assert con.execute("SELECT id_grupo FROM noticias WHERE id_noticia = ?", [IDS[0]]).fetchone()[0] == grupo_sintetico
        finally:
            con.close()
    preparar_demo.preparar(segunda)           # sobre una demo existente: la reemplaza, no duplica
    con = duckdb.connect(str(segunda), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM noticias WHERE origen = 'sintetico'").fetchone()[0] == len(IDS)
    finally:
        con.close()


def test_preparar_se_niega_a_pisar_la_base_viva(tmp_path) -> None:
    with pytest.raises(ValueError, match="base viva"):
        preparar_demo.preparar(destino=SNAPSHOT)
    with pytest.raises(ValueError, match="sintéticos"):
        ajeno = tmp_path / "real.csv"
        ajeno.write_text(FIXTURE.read_text(encoding="utf-8").replace("SYN-C06-001", "NOT-0123456789"), encoding="utf-8")
        preparar_demo.preparar(tmp_path / "x.duckdb", fixtures=[ajeno])


# ------------------------------------------------------------------ las métricas se niegan a leer la demo


def test_la_demo_se_reconoce_por_nombre_y_por_su_marca(demo, tmp_path) -> None:
    assert db.es_base_de_demo(demo) and db.es_base_de_demo(RAIZ / "data" / "demo.duckdb")
    renombrada = tmp_path / "otra.duckdb"
    shutil.copy2(demo, renombrada)
    assert db.es_base_de_demo(renombrada)                 # la marca viaja dentro de la base
    assert not db.es_base_de_demo(SNAPSHOT)
    with pytest.raises(db.BaseDeDemo, match="Nunca se usa para calcular métricas"):
        db.exigir_base_real(renombrada)
    db.exigir_base_real(SNAPSHOT)                         # la real pasa


@pytest.mark.parametrize("modulo", [
    "eval.puntaje", "eval.sensibilidad", "eval.ruido", "eval.agrupacion", "eval.ia_vs_baseline",
    "eval.calibrar_clasificacion", "eval.diagnostico_temas", "eval.precision_at_5", "scripts.fichas_trazables",
])
def test_cada_metrica_se_niega_a_leer_la_base_de_la_demo(modulo, demo) -> None:
    mod = importlib.import_module(modulo)
    punto_de_entrada = getattr(mod, "main", None) or getattr(mod, "principal")
    with pytest.raises(SystemExit, match="base de la demo"):
        punto_de_entrada(["--base", str(demo)])


def test_las_etiquetas_de_evaluacion_no_se_arman_desde_la_demo(demo) -> None:
    from eval import etiquetar

    with pytest.raises(db.BaseDeDemo):
        etiquetar.leer_noticias(demo)


# ------------------------------------------------------------------ la app en modo demo


@pytest.fixture
def app_demo(monkeypatch, tmp_path, demo):
    monkeypatch.setattr(ui, "modo_demo", lambda argv=None: True)
    monkeypatch.setattr(ui, "elegir_base", lambda d, c, base_normal=None: (demo, None))
    monkeypatch.setattr(ui, "ruta_de_revision", lambda d, cfg=None: tmp_path / "revision_demo.duckdb")   # nunca la revisión real
    monkeypatch.setattr("sys.argv", ["app.py", "--demo"])
    st.cache_resource.clear()
    st.cache_data.clear()

    def abrir(pantalla: str, grupo: str) -> AppTest:
        at = AppTest.from_file(str(APP), default_timeout=180)
        at.session_state["caso_aplicado"] = "x"          # sin atajo ?caso=: manda la pantalla elegida
        at.session_state["id_grupo"] = grupo
        return ir_a_pantalla(at, pantalla)

    return abrir


def insignias(at: AppTest) -> int:
    return sum(m.value.count(f":orange-badge[{SINTETICO}]") for m in at.markdown)


def tablas_con_origen(at: AppTest, grupo: str) -> int:
    """Tablas donde la fila del grupo sintético lleva «SINTÉTICO» en la columna «Origen»."""
    n = 0
    for d in at.dataframe:
        t = d.value
        if "Origen" in t.columns and "Grupo" in t.columns:
            n += int(((t["Grupo"] == grupo) & (t["Origen"] == SINTETICO)).any())
        elif "Origen" in t.columns and "Titular representativo" in t.columns:     # la bandeja no repite el ID
            n += int((t["Origen"] == SINTETICO).any())
    return n


@pytest.mark.parametrize("pantalla", ["ficha", "paquete", "revision"])
def test_explicar_producir_y_revisar_llevan_la_insignia_del_caso_sintetico(app_demo, grupo_sintetico, pantalla) -> None:
    at = app_demo(pantalla, grupo_sintetico)
    assert not at.exception
    assert insignias(at) >= 1


@pytest.mark.parametrize("pantalla", ["organizar", "contextualizar"])
def test_organizar_y_contextualizar_marcan_el_grupo_sintetico_en_su_tabla(app_demo, grupo_sintetico, pantalla) -> None:
    at = app_demo(pantalla, grupo_sintetico)
    assert not at.exception
    assert tablas_con_origen(at, grupo_sintetico) >= 1


def test_priorizar_marca_el_caso_sintetico_en_la_columna_origen(app_demo, grupo_sintetico) -> None:
    at = app_demo("bandeja", grupo_sintetico)
    at.checkbox(key="bandeja_todas").check().run()
    assert not at.exception
    assert tablas_con_origen(at, grupo_sintetico) >= 1
    reales = [d.value for d in at.dataframe if "Origen" in d.value.columns and "Titular representativo" in d.value.columns]
    assert (reales[0]["Origen"] == SINTETICO).sum() == 1          # solo el caso agregado, ningún real


def test_organizar_marca_el_grupo_y_sus_titulares_al_abrirlo(app_demo, grupo_sintetico) -> None:
    at = app_demo("organizar", grupo_sintetico)
    at.selectbox(key="organizar_grupo").select(grupo_sintetico).run()
    assert insignias(at) >= 1
    detalle = [d.value for d in at.dataframe if "Noticia" in d.value.columns]
    assert detalle and set(detalle[0]["Origen"]) == {SINTETICO} and set(detalle[0]["Noticia"]) == set(IDS)


def test_la_ficha_muestra_ambas_versiones_con_su_cita_y_la_verificacion_pendiente_sin_elegir(app_demo, grupo_sintetico) -> None:
    at = app_demo("ficha", grupo_sintetico)
    texto = "\n".join(m.value for m in at.markdown)
    assert "posible contradicción, verificar" in texto
    assert "Versión A" in texto and "Versión B" in texto
    assert all(i in texto for i in IDS) and "Medio Sintético C" in texto and "Medio Sintético D" in texto
    assert "36 tránsitos" in texto and "28 tránsitos" in texto
    assert "ningún par se cierra solo" in texto            # la verificación queda pendiente de una persona
    for frase in ("es falsa", "es verdadera", "es falso", "fake news", "la cifra correcta es"):
        assert frase not in texto.lower()
    assert all(f"{i} · titulo\\_limpio" in texto or f"{i} · titulo_limpio" in texto for i in IDS)   # cada versión lleva su cita ID + campo


def test_el_snapshot_real_no_muestra_ninguna_insignia(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ui, "ruta_de_revision", lambda d, cfg=None: tmp_path / "revision.duckdb")
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP), default_timeout=180)
    ir_a_pantalla(at, "ficha")
    assert not at.exception and insignias(at) == 0
    assert all("Origen" not in d.value.columns or not (d.value["Origen"] == SINTETICO).any() for d in at.dataframe)


# ------------------------------------------------------------------ la exportación a Notion


def test_la_exportacion_marca_el_caso_sintetico_y_no_marca_uno_real(demo, grupo_sintetico, tmp_path) -> None:
    t = {"n": 0}

    def reloj() -> datetime:
        t["n"] += 1
        return datetime(2026, 10, 8, 14, 0, tzinfo=UTC) + timedelta(minutes=t["n"])

    rev = Revisiones(tmp_path / "revision_demo.duckdb", demo, ahora=reloj, demo=True)
    caso = rev.abrir(grupo_sintetico, "editorial", "Javier Acosta")
    e = exportar.exportar_caso(rev, caso.id_caso, carpeta=tmp_path / "notion", ruta_jsonl=tmp_path / "fichas.jsonl")
    rotulo = f"{SINTETICO} · {CFG.textos.sintetico_ayuda}"
    assert rotulo in e.markdown and e.markdown.index(rotulo) < e.markdown.index("## ")
    assert e.fila["Qué se reporta"].startswith(rotulo)
    assert "BORRADOR" in e.markdown
    assert all(i in e.fila["IDs de fuente"] for i in IDS)
    assert "Versión A" in e.markdown and "Versión B" in e.markdown
    ficha_real = Revisiones(tmp_path / "otra.duckdb", SNAPSHOT, ahora=reloj, demo=True)
    grupo_real = duckdb.connect(str(SNAPSHOT), read_only=True).execute("SELECT id_grupo FROM puntajes ORDER BY posicion LIMIT 1").fetchone()[0]
    caso_real = ficha_real.abrir(grupo_real, "editorial", "Javier Acosta")
    real = exportar.exportar_caso(ficha_real, caso_real.id_caso, carpeta=tmp_path / "notion_real", ruta_jsonl=tmp_path / "fichas_real.jsonl")
    assert SINTETICO not in real.markdown and SINTETICO not in real.fila["Qué se reporta"]


def test_los_prefijos_sinteticos_vienen_de_la_configuracion() -> None:
    assert "SYN-" in cargar_normalizacion().noticias.prefijos_sinteticos
