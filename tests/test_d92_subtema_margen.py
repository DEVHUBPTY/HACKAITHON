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


SUB = CFG.subtema


def decidir(candidatos, titulares):
    return contexto.decidir_subtema(candidatos, titulares, SUB)


def test_margen_diminuto_y_sin_termino_queda_sin_subtema_y_margen_claro_lo_conserva() -> None:
    # caso VSR: agua_potable 0.869 contra salud_publica 0.857 (margen 0.012) y ningún término de agua en el titular
    vsr = "Minsa: Adelantan vacunación contra VSR en embarazadas"
    assert decidir([("agua_potable", 0.869, 0.012)], [vsr]) == (None, None)
    assert decidir([("seguridad_ciudadana", 0.833, 0.040)], ["Asesinan a taxista"]) == ("seguridad_ciudadana", "margen")


def test_un_termino_del_subtema_acepta_aunque_el_margen_sea_chico() -> None:
    assert decidir([("crecimiento_pib", 0.83, 0.005)], ["El PIB de Panamá crece 2,5 % en el trimestre"]) == ("crecimiento_pib", "lexico")
    # con margen suficiente gana el criterio del margen (se registra primero)
    assert decidir([("crecimiento_pib", 0.83, 0.030)], ["El PIB de Panamá crece"]) == ("crecimiento_pib", "margen")
    # un término de OTRO subtema no respalda al subtema más cercano
    assert decidir([("empleo", 0.83, 0.005)], ["El PIB de Panamá crece"]) == (None, None)


def test_los_terminos_coinciden_por_palabra_completa_y_sin_acentos_ni_mayusculas() -> None:
    assert contexto.menciona_termino("Los PIBES juegan", ["pib"]) is False                      # dentro de otra palabra
    assert contexto.menciona_termino("El desempleo sube", ["empleo"]) is False
    assert contexto.menciona_termino("El (PIB) sube", ["pib"]) is True
    assert contexto.menciona_termino("INFLACIÓN de abril", ["inflacion"]) is True              # acento y mayúsculas
    assert contexto.menciona_termino("inflacion de abril", ["inflación"]) is True
    assert contexto.menciona_termino("Comercio   exterior crece", ["comercio exterior"]) is True # espacios
    assert contexto.menciona_termino("sin nada", []) is False


def test_todo_subtema_con_vinculo_tiene_terminos() -> None:
    assert set(CFG.vinculos) <= set(SUB.terminos_por_subtema)
    assert all(SUB.terminos_por_subtema[s] for s in CFG.vinculos)


def test_el_margen_del_grupo_es_el_promedio_y_el_borde_conserva() -> None:
    t = ["titular sin términos"]
    assert decidir([("empleo", 0.8, 0.010), ("empleo", 0.8, 0.020)], t) == ("empleo", "margen")   # promedio 0.015
    assert decidir([("empleo", 0.8, 0.010), ("empleo", 0.8, 0.019)], t) == (None, None)
    assert decidir([], t) == (None, None)


def test_sin_margen_guardado_solo_acepta_el_termino() -> None:
    assert decidir([("sismos", 0.9, None)], ["Fuerte sismo en Chiriquí"]) == ("sismos", "lexico")
    assert decidir([("sismos", 0.9, None)], ["Fuerte movimiento"]) == (None, None)


def _base(tmp_path: Path, margenes: dict[str, float | None], titulares: dict[str, str] | None = None) -> Path:
    ruta = tmp_path / "senales.duckdb"
    base = {"titulo": "t", "url": "u", "url_canonica": "u", "medio": "m", "tipo_firma": "sin firma", "es_ruido": False}
    grupo = {"titular_central": "t", "n_titulares": 1, "n_medios": 1, "n_procedencias": 1, "estimado": True}
    temas = {"GRP-vsr": ("servicios_publicos", "agua_potable"), "GRP-sismo": ("eventos_naturales", "sismos")}
    noticias, grupos, sim = [], [], []
    for i, (g, (tema, sub)) in enumerate(temas.items()):
        nid = f"NOT-{i}"
        titular = (titulares or {}).get(g, "t")
        noticias.append({**base, "titulo": titular, "titulo_limpio": titular, "id_noticia": nid, "fecha_publicacion": "2024-05-10T15:00:00Z", "id_grupo": g})
        grupos.append({**grupo, "id_grupo": g, "id_noticia_central": nid, "ids_noticia": nid, "tema_clasificado": tema})
        sim.append({"id_noticia": nid, "metodo": "B", "tema": tema, "similitud": 0.85, "subtema": sub, "margen_subtema": margenes[g]})
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": grupos, "similitud_tema": sim})
    return ruta


def test_leer_grupos_aplica_el_margen(tmp_path: Path) -> None:
    ruta = _base(tmp_path, {"GRP-vsr": 0.012, "GRP-sismo": 0.040})
    con = db.conectar(ruta, solo_lectura=True)
    try:
        subtemas = {g["id_grupo"]: g["subtema"] for g in contexto.leer_grupos(con, SUB)}
    finally:
        con.close()
    assert subtemas == {"GRP-vsr": None, "GRP-sismo": "sismos"}


def test_leer_grupos_registra_el_criterio_y_acepta_por_termino(tmp_path: Path) -> None:
    ruta = _base(tmp_path, {"GRP-vsr": 0.005, "GRP-sismo": 0.005}, {"GRP-vsr": "Vacuna contra VSR", "GRP-sismo": "Sismo de 4,5 sacude Chiriquí"})
    con = db.conectar(ruta, solo_lectura=True)
    try:
        grupos = {g["id_grupo"]: (g["subtema"], g["criterio_subtema"]) for g in contexto.leer_grupos(con, SUB)}
    finally:
        con.close()
    assert grupos == {"GRP-vsr": (None, None), "GRP-sismo": ("sismos", "lexico")}


def test_la_fila_de_vinculo_guarda_el_criterio_del_subtema() -> None:
    filas = contexto.vincular_grupo("GRP-1", "economia", "crecimiento_pib", "El PIB crece", 2024, [], CFG, criterio_subtema="lexico")
    assert {f["criterio_subtema"] for f in filas} == {"lexico"}


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


def test_los_terminos_se_declaran_solo_para_subtemas_que_existen() -> None:
    from src.configuracion import cargar_temas   # noqa: PLC0415

    existentes = {s for t in cargar_temas().temas.values() for s in t.subtemas}
    assert set(SUB.terminos_por_subtema) <= existentes


def test_el_vinculo_de_sismos_guarda_el_criterio(tmp_path: Path) -> None:
    from tests.test_e1_09b_sismos import escribir_eventos   # noqa: PLC0415

    geojson = escribir_eventos(tmp_path / "eventos.geojson", [{"id": "SIS-us0001", "magnitude": 4.5, "time": "2024-05-10T12:00:00Z"}])
    ruta = _base(tmp_path, {"GRP-vsr": 0.0, "GRP-sismo": 0.005}, {"GRP-sismo": "Fuerte sismo en Chiriquí"})
    _, filas, _ = contexto.aplicar_sismos(ruta, geojson, CFG)
    assert [(f["id_grupo"], f["criterio_subtema"]) for f in filas] == [("GRP-sismo", "lexico")]


def test_precio_suelto_no_respalda_inflacion_pero_el_precio_del_combustible_si() -> None:
    for titular in ("Sube el precio del cobre", "Precios del oro récord", "Precio de la vivienda sube"):
        assert decidir([("inflacion_precios", 0.83, 0.005)], [titular]) == (None, None), titular
    assert decidir([("inflacion_precios", 0.83, 0.005)], ["¿Cómo se fija el precio del combustible en Panamá?"]) == ("inflacion_precios", "lexico")
    assert decidir([("inflacion_precios", 0.83, 0.005)], ["Inflación de septiembre"]) == ("inflacion_precios", "lexico")
    assert decidir([("inflacion_precios", 0.83, 0.005)], ["Sube el costo de la vida en Panamá"]) == ("inflacion_precios", "lexico")


def test_una_base_anterior_a_d92_avisa_que_no_tiene_margen(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    ruta = tmp_path / "vieja.duckdb"
    db.guardar_todo(ruta, {})
    con = db.conectar(ruta)
    con.execute("ALTER TABLE similitud_tema DROP COLUMN margen_subtema")
    with caplog.at_level("WARNING"):
        grupos = contexto.leer_grupos(con, SUB)
    con.close()
    assert grupos == [] and any("margen_subtema" in r.message for r in caplog.records)
