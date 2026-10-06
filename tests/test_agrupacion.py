"""E1-08: agrupación por evento (GRP-), ventana temporal, IDs estables y escritura en DuckDB. Sin red ni modelo."""

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from src import agrupacion as ag
from src import db, embeddings
from src.configuracion import CalibracionAgrupacion, ReglasV13, cargar_clasificacion, cargar_procedencias, cargar_reglas
from tests.motor_falso import MotorFalso, config_de_prueba

PROC = cargar_procedencias()
UMBRAL = 0.5   # con el codificador de prueba (bolsa de palabras): dos titulares con casi las mismas palabras superan 0.5


def reglas_con(umbral: float | None = UMBRAL, ventana: int = 7, **cambios) -> ReglasV13:
    base = cargar_reglas()
    return base.model_copy(update={"agrupacion": base.agrupacion.model_copy(update={"umbral_similitud": umbral, "ventana_dias": ventana, **cambios})})


def fila(id_, titulo, dominio=None, publicacion=None, deteccion=None, **extra):
    dominio = dominio or f"{id_.lower()}.example"
    return {
        "id_noticia": id_, "titulo": titulo, "titulo_limpio": titulo, "url": f"https://{dominio}/{id_}",
        "url_canonica": f"https://{dominio}/{id_}", "medio": dominio, "dominio": dominio, "tipo_firma": "sin firma",
        "idioma": "es", "fecha_publicacion": publicacion, "fecha_deteccion": deteccion, "es_ruido": False,
        "descripcion": None, "agencia": None, "tema_clasificado": None, **extra,
    }


def vectores_de(filas, tmp_path: Path) -> np.ndarray:
    emb = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)
    return ag.codificar_titulares(filas, emb, usar_descripcion=False)


SISMO = "Fuerte sismo sacude Chiriquí y deja daños en viviendas"
SISMO_AMPLIADO = "Fuerte sismo sacude Chiriquí y deja daños en viviendas de la provincia ayer"   # 0.83 con SISMO: mismo evento, texto distinto
INFLACION = "Inflación sube y precios de la canasta suben en todo el país"


# ------------------------------------------------------------------ IDs y fechas


def test_id_de_grupo_tiene_prefijo_y_no_depende_del_orden() -> None:
    cfg = cargar_reglas().agrupacion
    a = ag.id_de_grupo(["NOT-b", "NOT-a", "NOT-c"], cfg)
    assert a == ag.id_de_grupo(["NOT-c", "NOT-a", "NOT-b"], cfg)
    assert a.startswith(cfg.prefijo_id) and len(a) == len(cfg.prefijo_id) + cfg.largo_hash_id
    assert int(a.removeprefix(cfg.prefijo_id), 16) >= 0


def test_el_prefijo_y_el_largo_del_id_salen_de_la_configuracion() -> None:
    cfg = cargar_reglas().agrupacion.model_copy(update={"prefijo_id": "G-", "largo_hash_id": 6})
    a = ag.id_de_grupo(["NOT-a"], cfg)
    assert a.startswith("G-") and len(a) == len("G-") + 6


def test_un_grupo_con_otros_miembros_tiene_otro_id() -> None:
    cfg = cargar_reglas().agrupacion
    assert ag.id_de_grupo(["NOT-a", "NOT-b"], cfg) != ag.id_de_grupo(["NOT-a", "NOT-b", "NOT-c"], cfg)
    assert ag.id_de_grupo(["NOT-a"], cfg) != ag.id_de_grupo(["NOT-b"], cfg)


def test_la_fecha_es_la_publicacion_y_si_falta_la_deteccion() -> None:
    campos = ["fecha_publicacion", "fecha_deteccion"]
    f = {"fecha_publicacion": "2026-10-01T10:00:00Z", "fecha_deteccion": "2026-10-03T00:00:00Z"}
    assert ag.fecha_de(f, campos) == datetime(2026, 10, 1, 10, tzinfo=UTC)
    assert ag.fecha_de({"fecha_publicacion": None, "fecha_deteccion": "2026-10-03T00:00:00Z"}, campos) == datetime(2026, 10, 3, tzinfo=UTC)
    assert ag.fecha_de({}, campos) is None
    assert ag.fecha_iso_de(f, campos) == "2026-10-01T10:00:00Z"   # el texto original, sin reformatear
    assert ag.fecha_de({"fecha_publicacion": "2026-10-01T10:00:00"}, campos).tzinfo is UTC   # sin zona: el contrato es UTC


# ------------------------------------------------------------------ similitud y ventana


def _agrupar(filas, tmp_path, umbral=UMBRAL, ventana=7):
    v = vectores_de(filas, tmp_path)
    fechas = [ag.fecha_de(f, ["fecha_publicacion", "fecha_deteccion"]) for f in filas]
    return ag.agrupar_indices(v, fechas, [f["id_noticia"] for f in filas], umbral, ventana)


def test_titulares_del_mismo_evento_van_juntos_y_los_de_otro_evento_aparte(tmp_path) -> None:
    filas = [
        fila("NOT-1", SISMO, deteccion="2026-10-01T08:00:00Z"),
        fila("NOT-2", SISMO + " este martes", deteccion="2026-10-01T09:00:00Z"),
        fila("NOT-3", INFLACION, deteccion="2026-10-01T09:00:00Z"),
        fila("NOT-4", SISMO, deteccion="2026-10-01T10:00:00Z"),
    ]
    assert _agrupar(filas, tmp_path) == [[0, 1, 3], [2]]


def test_un_umbral_mas_alto_separa_titulares_parecidos_pero_no_iguales(tmp_path) -> None:
    filas = [fila("NOT-1", SISMO, deteccion="2026-10-01T08:00:00Z"), fila("NOT-2", SISMO + " este martes por la noche", deteccion="2026-10-01T09:00:00Z")]
    assert len(_agrupar(filas, tmp_path, umbral=0.5)) == 1
    assert len(_agrupar(filas, tmp_path, umbral=0.99)) == 2


def test_dos_titulares_a_mas_de_la_ventana_no_se_unen_aunque_sean_identicos(tmp_path) -> None:
    lejos = [fila("NOT-1", SISMO, deteccion="2026-10-01T08:00:00Z"), fila("NOT-2", SISMO, deteccion="2026-10-09T08:00:01Z")]
    cerca = [fila("NOT-1", SISMO, deteccion="2026-10-01T08:00:00Z"), fila("NOT-2", SISMO, deteccion="2026-10-04T08:00:00Z")]
    assert _agrupar(lejos, tmp_path) == [[0], [1]]
    assert _agrupar(cerca, tmp_path) == [[0, 1]]


def test_la_ventana_incluye_su_limite_exacto(tmp_path) -> None:
    filas = [fila("NOT-1", SISMO, deteccion="2026-10-01T08:00:00Z"), fila("NOT-2", SISMO, deteccion="2026-10-08T08:00:00Z")]
    assert _agrupar(filas, tmp_path, ventana=7) == [[0, 1]]
    assert _agrupar(filas, tmp_path, ventana=6) == [[0], [1]]


def test_en_una_cadena_ningun_par_del_grupo_supera_la_ventana(tmp_path) -> None:
    """A-B y B-C están a 5 días, pero A-C a 10: no pueden quedar los tres juntos."""
    filas = [fila(f"NOT-{i}", SISMO, deteccion=f"2026-10-{1 + 5 * i:02d}T08:00:00Z") for i in range(3)]
    grupos = _agrupar(filas, tmp_path, ventana=7)
    fechas = {i: ag.fecha_de(f, ["fecha_deteccion"]) for i, f in enumerate(filas)}
    assert sorted(i for g in grupos for i in g) == [0, 1, 2]
    for g in grupos:
        assert all(abs((fechas[a] - fechas[b]).days) <= 7 for a in g for b in g)
    assert len(grupos) == 2


def test_un_titular_sin_fecha_se_queda_con_su_grupo(tmp_path) -> None:
    filas = [fila("NOT-1", SISMO, deteccion="2026-10-01T08:00:00Z"), fila("NOT-2", SISMO), fila("NOT-3", SISMO, deteccion="2026-10-20T00:00:00Z")]
    grupos = _agrupar(filas, tmp_path)
    assert sorted(i for g in grupos for i in g) == [0, 1, 2]
    assert [0, 1] in grupos


def test_todo_sin_fecha_es_un_solo_grupo_por_similitud(tmp_path) -> None:
    assert _agrupar([fila("NOT-1", SISMO), fila("NOT-2", SISMO)], tmp_path) == [[0, 1]]


def test_uno_o_ningun_titular_no_rompe_el_clustering(tmp_path) -> None:
    assert _agrupar([], tmp_path) == []
    assert _agrupar([fila("NOT-1", SISMO)], tmp_path) == [[0]]


def test_las_longitudes_distintas_se_rechazan() -> None:
    with pytest.raises(ValueError, match="misma longitud"):
        ag.agrupar_indices(np.zeros((2, 3)), [None], ["a", "b"], 0.5, 7)


def test_el_resultado_no_depende_del_orden_de_las_filas(tmp_path) -> None:
    filas = [fila(f"NOT-{i}", t, deteccion="2026-10-01T08:00:00Z") for i, t in enumerate([SISMO, INFLACION, SISMO, INFLACION, SISMO])]
    a = ag.construir_grupos(filas, vectores_de(filas, tmp_path), reglas_con(), PROC)
    mezcladas = [filas[i] for i in (4, 2, 0, 3, 1)]
    b = ag.construir_grupos(mezcladas, vectores_de(mezcladas, tmp_path), reglas_con(), PROC)
    assert [(g.id_grupo, g.ids_noticia) for g in a] == [(g.id_grupo, g.ids_noticia) for g in b]


# ------------------------------------------------------------------ grupos completos


def test_cada_noticia_queda_en_exactamente_un_grupo(tmp_path) -> None:
    filas = [fila(f"NOT-{i}", [SISMO, INFLACION, "Turistas llegan en cruceros al puerto"][i % 3], deteccion=f"2026-10-0{1 + i % 5}T08:00:00Z") for i in range(12)]
    grupos = ag.construir_grupos(filas, vectores_de(filas, tmp_path), reglas_con(), PROC)
    asignadas = [i for g in grupos for i in g.ids_noticia]
    assert sorted(asignadas) == sorted(f["id_noticia"] for f in filas)
    assert len({g.id_grupo for g in grupos}) == len(grupos)
    assert sum(g.n_titulares for g in grupos) == len(filas)


def test_los_campos_del_grupo(tmp_path) -> None:
    filas = [
        fila("NOT-1", SISMO, dominio="a.example", deteccion="2026-10-01T08:00:00Z", idioma="es", tema_clasificado="eventos_naturales"),
        fila("NOT-2", SISMO_AMPLIADO, dominio="b.example", publicacion="2026-09-30T20:00:00Z", deteccion="2026-10-02T08:00:00Z", idioma="en", tema_clasificado="eventos_naturales"),
        fila("NOT-3", SISMO, dominio="a.example", deteccion="2026-10-03T08:00:00Z", idioma="es", tema_clasificado="regulacion"),
    ]
    (g,) = ag.construir_grupos(filas, vectores_de(filas, tmp_path), reglas_con(), PROC)
    assert g.ids_noticia == ("NOT-1", "NOT-2", "NOT-3") and g.n_titulares == 3
    assert g.n_medios == 2
    assert g.idiomas == ("en", "es")
    assert g.tema_clasificado == "eventos_naturales"
    assert (g.fecha_inicio, g.fecha_fin) == ("2026-09-30T20:00:00Z", "2026-10-03T08:00:00Z")
    assert (g.fecha_inicio_origen, g.fecha_fin_origen) == ("publicacion", "deteccion")   # no se mezclan sin decirlo
    assert g.id_noticia_central in g.ids_noticia and g.titular_central in {f["titulo_limpio"] for f in filas}
    assert g.n_procedencias == 2   # a.example publicó dos veces (una procedencia) y b.example es otra


def test_el_titular_central_es_el_mas_parecido_al_resto(tmp_path) -> None:
    filas = [
        fila("NOT-1", "Sismo sacude Chiriquí", deteccion="2026-10-01T08:00:00Z"),
        fila("NOT-2", "Fuerte sismo sacude Chiriquí y deja daños", deteccion="2026-10-01T09:00:00Z"),
        fila("NOT-3", "Sismo fuerte sacude Chiriquí", deteccion="2026-10-01T10:00:00Z"),
    ]
    (g,) = ag.construir_grupos(filas, vectores_de(filas, tmp_path), reglas_con(0.4), PROC)
    assert g.id_noticia_central != "NOT-2"


def test_sin_umbral_calibrado_la_agrupacion_se_niega(tmp_path) -> None:
    filas = [fila("NOT-1", SISMO)]
    with pytest.raises(ag.SinCalibrar, match="eval.agrupacion"):
        ag.construir_grupos(filas, vectores_de(filas, tmp_path), reglas_con(None), PROC)


def test_un_id_repetido_en_la_entrada_se_rechaza(tmp_path) -> None:
    filas = [fila("NOT-1", SISMO), fila("NOT-1", SISMO)]
    with pytest.raises(ValueError, match="repetido"):
        ag.construir_grupos(filas, vectores_de(filas, tmp_path), reglas_con(), PROC)


def test_cinco_titulares_casi_identicos_de_cinco_medios_son_un_grupo_y_una_procedencia(tmp_path) -> None:
    filas = [fila(f"NOT-{i}", SISMO, dominio=f"medio{i}.example", deteccion=f"2026-10-01T0{i}:00:00Z") for i in range(5)]
    (g,) = ag.construir_grupos(filas, vectores_de(filas, tmp_path), reglas_con(), PROC)
    assert (g.n_titulares, g.n_medios, g.n_procedencias) == (5, 5, 1)


# ------------------------------------------------------------------ configuración


def test_el_umbral_real_esta_calibrado_para_su_modelo() -> None:
    r = cargar_reglas().agrupacion
    assert r.umbral_similitud is not None and 0 < r.umbral_similitud < 1
    assert r.modelo in cargar_clasificacion().modelos
    assert r.calibracion.barrido_desde <= r.umbral_similitud <= r.calibracion.barrido_hasta


def test_el_barrido_debe_tener_rango_valido() -> None:
    with pytest.raises(ValueError, match="barrido_desde"):
        CalibracionAgrupacion(barrido_desde=0.9, barrido_hasta=0.5, barrido_paso=0.01, pliegues=2)


# ------------------------------------------------------------------ DuckDB


def _base(tmp_path: Path, filas) -> Path:
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": filas})
    return ruta


def _leer(ruta: Path, sql: str):
    con = db.conectar(ruta, solo_lectura=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


FILAS = [
    fila("NOT-1", SISMO, dominio="a.example", deteccion="2026-10-01T08:00:00Z"),
    fila("NOT-2", SISMO_AMPLIADO, dominio="b.example", deteccion="2026-10-01T09:00:00Z"),
    fila("NOT-3", INFLACION, dominio="c.example", deteccion="2026-10-01T09:00:00Z"),
    fila("NOT-4", SISMO, dominio="d.example", deteccion="2026-10-01T09:30:00Z", es_ruido=True, motivo_ruido="no_es_panama"),
]


def _aplicar(ruta: Path, tmp_path: Path, reglas: ReglasV13 | None = None):
    cfg = config_de_prueba()
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    return ag.aplicar_a_base(ruta, reglas or reglas_con(), PROC, cfg, emb)


def test_aplicar_a_base_guarda_grupos_procedencias_y_asignaciones(tmp_path) -> None:
    ruta = _base(tmp_path, FILAS)
    grupos = _aplicar(ruta, tmp_path)
    assert len(grupos) == 2
    asignadas = dict(_leer(ruta, "SELECT id_noticia, id_grupo FROM noticias"))
    assert asignadas["NOT-1"] == asignadas["NOT-2"] != asignadas["NOT-3"]
    assert asignadas["NOT-4"] is None                                  # el ruido se conserva y no entra en un grupo
    assert _leer(ruta, "SELECT count(*) FROM noticias") == [(4,)]
    (grande,) = _leer(ruta, "SELECT n_titulares, n_medios, n_procedencias, estimado, ids_noticia FROM grupos WHERE n_titulares = 2")
    assert grande == (2, 2, 2, True, "NOT-1,NOT-2")
    assert _leer(ruta, "SELECT count(*) FROM procedencias") == [(3,)]
    assert _leer(ruta, "SELECT DISTINCT procedencia FROM noticias WHERE id_noticia = 'NOT-1'") == [("a.example",)]


def test_correrla_dos_veces_da_los_mismos_ids_y_no_duplica_filas(tmp_path) -> None:
    ruta = _base(tmp_path, FILAS)
    _aplicar(ruta, tmp_path)
    antes = _leer(ruta, "SELECT id_noticia, id_grupo FROM noticias ORDER BY 1")
    _aplicar(ruta, tmp_path)
    assert _leer(ruta, "SELECT id_noticia, id_grupo FROM noticias ORDER BY 1") == antes
    assert _leer(ruta, "SELECT count(*) FROM grupos") == [(2,)]


def test_una_corrida_nueva_reemplaza_los_grupos_anteriores(tmp_path) -> None:
    ruta = _base(tmp_path, [*FILAS, fila("NOT-5", SISMO + " este martes por la noche", dominio="e.example", deteccion="2026-10-01T10:00:00Z")])
    _aplicar(ruta, tmp_path, reglas_con(0.5))
    (viejo,) = _leer(ruta, "SELECT id_grupo FROM grupos WHERE n_titulares = 3")
    _aplicar(ruta, tmp_path, reglas_con(0.99))
    assert _leer(ruta, "SELECT count(*) FROM grupos WHERE id_grupo = ?".replace("?", repr(viejo[0]))) == [(0,)]
    assert _leer(ruta, "SELECT count(*) FROM grupos") == [(4,)]
    assert _leer(ruta, "SELECT count(*) FROM procedencias") == [(4,)]


def test_una_noticia_que_deja_de_ser_ruido_o_pasa_a_serlo_cambia_de_grupo(tmp_path) -> None:
    ruta = _base(tmp_path, FILAS)
    _aplicar(ruta, tmp_path)
    con = db.conectar(ruta)
    con.execute("UPDATE noticias SET es_ruido = TRUE WHERE id_noticia = 'NOT-2'")
    con.execute("UPDATE noticias SET es_ruido = FALSE WHERE id_noticia = 'NOT-4'")
    con.close()
    _aplicar(ruta, tmp_path)
    asignadas = dict(_leer(ruta, "SELECT id_noticia, id_grupo FROM noticias"))
    assert asignadas["NOT-2"] is None and asignadas["NOT-4"] == asignadas["NOT-1"]


def test_sin_limpiar_la_agrupacion_se_niega_y_no_toca_la_base(tmp_path) -> None:
    ruta = _base(tmp_path, [fila("NOT-1", SISMO) | {"es_ruido": None, "titulo_limpio": None}])
    with pytest.raises(RuntimeError, match="sin limpiar"):
        _aplicar(ruta, tmp_path)
    assert _leer(ruta, "SELECT count(*) FROM grupos") == [(0,)]


def test_una_falla_a_mitad_deja_la_corrida_anterior_intacta(tmp_path, monkeypatch) -> None:
    ruta = _base(tmp_path, FILAS)
    _aplicar(ruta, tmp_path)
    antes = _leer(ruta, "SELECT id_noticia, id_grupo FROM noticias ORDER BY 1")
    monkeypatch.setattr(ag, "_filas_de_grupos", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falla")))
    with pytest.raises(RuntimeError, match="falla"):
        _aplicar(ruta, tmp_path)
    assert _leer(ruta, "SELECT id_noticia, id_grupo FROM noticias ORDER BY 1") == antes


def test_el_reporte_cuenta_con_n_e_ic_y_dice_que_es_un_estimado(tmp_path) -> None:
    ruta = _base(tmp_path, FILAS)
    grupos = _aplicar(ruta, tmp_path)
    cfg = config_de_prueba()
    s = ag.construir_reporte(grupos, 4, reglas_con(), PROC, cfg, 1.96)
    assert s["noticias_agrupadas_no_ruido"] == 3 and s["grupos"] == 2
    assert s["grupos_de_un_titular"]["n"] == 1 and s["grupos_de_un_titular"]["de"] == 2
    assert len(s["grupos_de_un_titular"]["ic95"]) == 2
    assert s["nota"].startswith("estimado") and s["mayores"][0]["n_titulares"] == 2
    json.dumps(s)   # serializable


def test_main_sin_base_termina_con_error(tmp_path) -> None:
    assert ag.main(["--base", str(tmp_path / "no_existe.duckdb")]) == 1
