"""T02 · Tres registros del mismo evento (E1-08, CU-03): 1 grupo, 3 fuentes conservadas y el puntaje no se triplica.

Datos: ``tests/fixtures/t02_mismo_evento.csv`` (sintéticos, tres medios que citan a EFE). Codificador de prueba, sin red.
"""

from pathlib import Path

import pytest

from src import agrupacion, db, embeddings, limpieza, normalizacion, procedencias
from src.configuracion import cargar_normalizacion, cargar_procedencias, cargar_fuentes, cargar_reglas
from tests.motor_falso import MotorFalso, config_de_prueba

FIXTURE = Path(__file__).parent / "fixtures" / "t02_mismo_evento.csv"
UMBRAL_DE_PRUEBA = 0.5   # el real (reglas_v1.3.yaml) es de MiniLM; el codificador de prueba tiene otra escala
IDS = ["SYN-T02-001", "SYN-T02-002", "SYN-T02-003"]
REGLAS = cargar_reglas()
PROC = cargar_procedencias()


@pytest.fixture
def filas() -> list[dict]:
    """El fixture normalizado y limpiado como lo hace el pipeline (los sintéticos conservan su ID, D-63)."""
    crudas = normalizacion.leer_csv(FIXTURE)
    normalizadas = normalizacion.normalizar_noticias(crudas, [], cargar_normalizacion(), cargar_fuentes(), normalizacion.Registro())
    return limpieza.limpiar_filas(normalizadas, limpieza.Reglas.desde_config())


@pytest.fixture
def reglas():
    a = REGLAS.agrupacion
    return REGLAS.model_copy(update={"agrupacion": a.model_copy(update={"umbral_similitud": UMBRAL_DE_PRUEBA})})


def _grupos(filas: list[dict], reglas, tmp_path: Path):
    emb = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)
    vectores = agrupacion.codificar_titulares(filas, emb, usar_descripcion=False)
    return agrupacion.construir_grupos(filas, vectores, reglas, PROC)


def test_el_fixture_son_tres_registros_validos_de_tres_medios(filas) -> None:
    assert [f["id_noticia"] for f in filas] == IDS
    assert not any(f["es_ruido"] for f in filas)
    assert len({f["dominio"] for f in filas}) == 3


def test_tres_registros_del_mismo_evento_forman_un_grupo(filas, reglas, tmp_path) -> None:
    grupos = _grupos(filas, reglas, tmp_path)
    assert len(grupos) == 1
    assert grupos[0].id_grupo.startswith("GRP-")
    assert grupos[0].ids_noticia == tuple(IDS)


def test_las_tres_fuentes_se_conservan(filas, reglas, tmp_path) -> None:
    (g,) = _grupos(filas, reglas, tmp_path)
    assert (g.n_titulares, g.n_medios) == (3, 3)
    assert sorted(i for p in g.procedencias for i in p.ids_noticia) == IDS   # ninguna fuente se pierde en las procedencias
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": filas})
    emb = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)
    agrupacion.aplicar_a_base(ruta, reglas, PROC, config_de_prueba(), emb)
    con = db.conectar(ruta, solo_lectura=True)
    try:
        assert con.execute("SELECT count(*), count(DISTINCT id_grupo) FROM noticias WHERE id_grupo IS NOT NULL").fetchone() == (3, 1)
        assert con.execute("SELECT count(*) FROM noticias").fetchone() == (3,)
    finally:
        con.close()


def test_el_puntaje_no_se_triplica(filas, reglas, tmp_path) -> None:
    """Tres titulares de la misma agencia son UNA procedencia: la parte de E que aportan no crece con las copias."""
    (g,) = _grupos(filas, reglas, tmp_path)
    assert g.n_procedencias == 1
    ingenuo = procedencias.fraccion_de_procedencias(g.n_titulares, REGLAS)   # contar titulares: 3 de tope 3 = 1.0
    correcto = procedencias.fraccion_de_procedencias(g.n_procedencias, REGLAS)
    assert correcto == pytest.approx(1 / REGLAS.evidencia.tope_procedencias)
    assert correcto < ingenuo
    assert correcto * 3 == pytest.approx(ingenuo)   # el contrato de la spec: no se triplica
    (p,) = g.procedencias
    assert p.etiqueta == "EFE" and procedencias.REGLA_AGENCIA_MENCIONADA in p.reglas


def test_el_resultado_se_presenta_como_estimado(filas, reglas, tmp_path) -> None:
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": filas})
    emb = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)
    agrupacion.aplicar_a_base(ruta, reglas, PROC, config_de_prueba(), emb)
    con = db.conectar(ruta, solo_lectura=True)
    try:
        assert con.execute("SELECT estimado FROM grupos").fetchall() == [(True,)]
    finally:
        con.close()
    assert PROC.etiqueta_estimado.startswith("estimado")


def test_mismo_snapshot_y_mismas_reglas_dan_los_mismos_ids(filas, reglas, tmp_path) -> None:
    primero = [g.id_grupo for g in _grupos(filas, reglas, tmp_path)]
    otra_vez = [g.id_grupo for g in _grupos(list(reversed(filas)), reglas, tmp_path)]
    assert primero == otra_vez
    assert primero == [agrupacion.id_de_grupo(IDS, REGLAS.agrupacion)]
