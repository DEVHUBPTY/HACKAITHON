"""D-92 (enmienda a E1-09): el grupo toma el subtema más cercano solo si supera al segundo por el margen mínimo."""

from pathlib import Path

import numpy as np
import pytest

from src import contexto, db
from src.clasificacion import METODO_B, Puntajes, Referencias, puntuar
from src.configuracion import ConfigVinculos, ErrorDeConfiguracion, cargar_config, cargar_vinculos

CFG = cargar_vinculos()
MINIMO = CFG.subtema.margen_minimo


def test_el_margen_minimo_esta_en_la_configuracion_y_no_admite_claves_extra(tmp_path: Path) -> None:
    assert MINIMO == 0.015
    datos = (Path(__file__).parent.parent / "config" / "vinculos.yaml").read_text(encoding="utf-8")
    malo = tmp_path / "vinculos.yaml"
    malo.write_text(datos.replace("margen_minimo: 0.015", "margen_minimo: 0.015\n  otra_clave: 1"), encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion):
        cargar_config("vinculos", ConfigVinculos, tmp_path)
    malo.write_text(datos.replace("margen_minimo: 0.015", "margen_minimo: -0.1"), encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion):
        cargar_config("vinculos", ConfigVinculos, tmp_path)


def test_margen_diminuto_queda_sin_subtema_y_margen_claro_lo_conserva() -> None:
    # caso VSR: agua_potable 0.869 contra salud_publica 0.857 (margen 0.012)
    assert contexto.subtema_con_margen([("agua_potable", 0.869, 0.012)], MINIMO) is None
    assert contexto.subtema_con_margen([("seguridad_ciudadana", 0.833, 0.040)], MINIMO) == "seguridad_ciudadana"


def test_el_margen_del_grupo_es_el_promedio_y_el_borde_conserva() -> None:
    assert contexto.subtema_con_margen([("empleo", 0.8, 0.010), ("empleo", 0.8, 0.020)], MINIMO) == "empleo"   # promedio 0.015
    assert contexto.subtema_con_margen([("empleo", 0.8, 0.010), ("empleo", 0.8, 0.019)], MINIMO) is None
    assert contexto.subtema_con_margen([], MINIMO) is None


def test_sin_margen_guardado_no_se_afirma_subtema() -> None:
    assert contexto.subtema_con_margen([("sismos", 0.9, None)], MINIMO) is None


def _base(tmp_path: Path, margenes: dict[str, float | None]) -> Path:
    ruta = tmp_path / "senales.duckdb"
    base = {"titulo": "t", "url": "u", "url_canonica": "u", "medio": "m", "tipo_firma": "sin firma", "es_ruido": False}
    grupo = {"titular_central": "t", "n_titulares": 1, "n_medios": 1, "n_procedencias": 1, "estimado": True}
    temas = {"GRP-vsr": ("servicios_publicos", "agua_potable"), "GRP-sismo": ("eventos_naturales", "sismos")}
    noticias, grupos, sim = [], [], []
    for i, (g, (tema, sub)) in enumerate(temas.items()):
        nid = f"NOT-{i}"
        noticias.append({**base, "id_noticia": nid, "fecha_publicacion": "2024-05-10T15:00:00Z", "id_grupo": g})
        grupos.append({**grupo, "id_grupo": g, "id_noticia_central": nid, "ids_noticia": nid, "tema_clasificado": tema})
        sim.append({"id_noticia": nid, "metodo": "B", "tema": tema, "similitud": 0.85, "subtema": sub, "margen_subtema": margenes[g]})
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": grupos, "similitud_tema": sim})
    return ruta


def test_leer_grupos_aplica_el_margen(tmp_path: Path) -> None:
    ruta = _base(tmp_path, {"GRP-vsr": 0.012, "GRP-sismo": 0.040})
    con = db.conectar(ruta, solo_lectura=True)
    try:
        subtemas = {g["id_grupo"]: g["subtema"] for g in contexto.leer_grupos(con, MINIMO)}
    finally:
        con.close()
    assert subtemas == {"GRP-vsr": None, "GRP-sismo": "sismos"}


def test_el_grupo_sin_subtema_cae_en_el_vinculo_por_tema_o_tema_sin_indicador(tmp_path: Path) -> None:
    sin_indicador = contexto.vincular_grupo("GRP-vsr", "servicios_publicos", None, "Minsa: vacunación contra VSR", 2024, [], CFG)
    assert [f["motivo_sin_vinculo"] for f in sin_indicador] == ["tema_sin_indicador"]
    assert sin_indicador[0]["regla"] == "sin_vinculo_en_tabla:servicios_publicos/sin_subtema"
    _, regla = contexto.elegir_vinculo("logistica", None, CFG)          # el vínculo por tema no afirma subtema
    assert regla == "vinculo_por_tema:logistica"


def test_el_grupo_de_sismos_con_margen_claro_sigue_vinculado_y_sin_margen_no(tmp_path: Path) -> None:
    from tests.test_e1_09b_sismos import escribir_eventos   # noqa: PLC0415

    geojson = escribir_eventos(tmp_path / "eventos.geojson", [{"id": "SIS-us0001", "magnitude": 4.5, "time": "2024-05-10T12:00:00Z"}])
    ok, _, _ = contexto.aplicar_sismos(_base(tmp_path, {"GRP-vsr": 0.012, "GRP-sismo": 0.040}), geojson, CFG)
    assert [(r.id_grupo, r.subtema) for r in ok] == [("GRP-sismo", "sismos")]
    tmp2 = tmp_path / "b"
    tmp2.mkdir()
    ninguno, _, _ = contexto.aplicar_sismos(_base(tmp2, {"GRP-vsr": 0.012, "GRP-sismo": 0.005}), geojson, CFG)
    assert ninguno == []


def test_puntuar_b_calcula_el_margen_entre_el_primer_y_el_segundo_subtema_del_tema() -> None:
    ref = Referencias(
        temas=["t1", "t2"],
        centroides=np.eye(2),
        subtemas=[("t1", "a"), ("t1", "b"), ("t1", "c"), ("t2", "d"), ("t2", "e")],
        prototipos=np.array([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0], [0.6, 0.8], [0.0, -1.0]]),
    )
    p: Puntajes = puntuar(np.array([[1.0, 0.0]]), ref, METODO_B)
    assert p.subtema[0][0] == "a"
    assert p.margen[0, 0] == pytest.approx(1.0 - 0.8)          # t1: a=1.0, b=0.8, c=0.0
    assert p.margen[0, 1] == pytest.approx(0.6 - 0.0)          # t2: d=0.6, e=0.0
