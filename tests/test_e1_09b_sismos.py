"""E1-09b: vínculo de grupos de sismos con eventos de USGS. Sin red, sin modelo y sin la base real."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src import contexto, db
from src import contexto_sismos as cs
from src.configuracion import ConfigVinculos, ErrorDeConfiguracion, cargar_config, cargar_fuentes, cargar_reglas, cargar_vinculos

VINCULOS = cargar_vinculos()
FUENTES = cargar_fuentes()
CAMPOS = cargar_reglas().agrupacion.campos_fecha


def evento(id_="SIS-us0001", hora="2024-05-10T12:00:00Z", magnitud=4.5, place="22 km S of Puerto Armuelles, Panama", estado="reviewed", depth=35.2):
    return cs.EventoUsgs(
        id=id_, magnitud=magnitud, profundidad_km=depth, place=place,
        hora_utc=datetime.fromisoformat(hora.replace("Z", "+00:00")), estado=estado, url=f"https://earthquake.usgs.gov/{id_}",
    )


def noticia(publicacion="2024-05-10T15:00:00Z", deteccion=None, id_="NOT-0000000001"):
    return {"id_noticia": id_, "fecha_publicacion": publicacion, "fecha_deteccion": deteccion}


def vincular(noticias, eventos, subtema="sismos"):
    return cs.vincular_grupo("GRP-test", subtema, noticias, eventos, VINCULOS, FUENTES, CAMPOS)


def test_un_evento_coincidente_da_vinculo_sis_con_todos_los_campos():
    r = vincular([noticia()], [evento()])
    assert r.estado == cs.VINCULADO and r.motivo_sin_vinculo is None
    (c,) = r.candidatos
    ficha = cs.ficha_de_evento(c, VINCULOS)
    assert ficha["id"].startswith("SIS-")
    assert ficha["place"] == "22 km S of Puerto Armuelles, Panama"   # tal como lo da USGS
    assert ficha["magnitud"] == 4.5 and ficha["profundidad_km"] == 35.2 and ficha["estado"] == "reviewed"
    assert ficha["hora_utc"] == "2024-05-10T12:00:00Z"
    assert ficha["hora_panama"] == "2024-05-10 07:00"                  # UTC-5, sin horario de verano
    assert ficha["diferencia_horas"] == 3.0
    assert r.limitacion == " ".join(VINCULOS.sismos.limitaciones)
    for parte in ("fuera de territorio panameño", "no informa daños", "automático puede cambiar"):
        assert parte in r.limitacion
    (fila,) = cs.a_filas_vinculo(r, VINCULOS)
    assert fila["id_grupo"] == "GRP-test" and fila["id_evidencia"] == "SIS-us0001" and fila["motivo_sin_vinculo"] is None
    assert (fila["fuente"], fila["rol"], fila["tipo"], fila["subtema"]) == ("usgs", "evento", "evento", "sismos")
    assert (fila["valor"], fila["unidad"], fila["profundidad_km"], fila["estado_evento"]) == (4.5, "magnitud", 35.2, "reviewed")
    assert fila["place"] == "22 km S of Puerto Armuelles, Panama" and fila["hora_utc"] == "2024-05-10T12:00:00Z"
    assert fila["regla"] == r.regla and fila["limitacion"] == r.limitacion
    assert "± 2 días" in r.regla and "magnitud mínima 3" in r.regla


def test_dos_candidatos_se_listan_todos_y_ninguno_se_elige():
    eventos = [evento("SIS-us0001", "2024-05-10T12:00:00Z"), evento("SIS-us0002", "2024-05-11T20:00:00Z", magnitud=3.2)]
    r = vincular([noticia()], eventos)
    assert r.estado == cs.CANDIDATOS_AMBIGUOS == "candidatos_ambiguos"
    assert {c.evento.id for c in r.candidatos} == {"SIS-us0001", "SIS-us0002"}
    filas = cs.a_filas_vinculo(r, VINCULOS)
    assert {f["id_evidencia"] for f in filas} == {"SIS-us0001", "SIS-us0002"}
    assert {f["motivo_sin_vinculo"] for f in filas} == {"candidatos_ambiguos"} and {f["tipo"] for f in filas} == {"evento"}


@pytest.mark.parametrize("subtema", ["inundaciones_lluvias", "deslizamientos", "alertas_proteccion_civil", "sequia_nino", None])
def test_lluvias_inundaciones_y_danos_nunca_se_vinculan_a_usgs(subtema):
    # hay un evento perfecto el mismo día: aun así, el subtema no lo permite
    assert vincular([noticia()], [evento()], subtema=subtema) is None


def test_noticia_de_2025_es_fuera_de_cobertura():
    r = vincular([noticia("2025-03-02T10:00:00Z")], [evento("SIS-us0001", "2025-03-02T09:00:00Z")])
    assert r.estado == cs.FUERA_DE_COBERTURA == "fuera_de_cobertura"
    assert r.candidatos == ()
    (fila,) = cs.a_filas_vinculo(r, VINCULOS)
    assert fila["id_evidencia"] is None and fila["motivo_sin_vinculo"] == "fuera_de_cobertura"
    assert fila["tipo"] is None and fila["fuente"] == "usgs" and fila["rol"] == "evento"   # NULL si no hay vínculo


def test_la_cobertura_sale_de_fuentes_y_no_esta_fija_en_2024():
    inicio, fin = cs.cobertura(FUENTES)
    assert (inicio.year, fin.year) == (2024, 2024)
    nuevas = FUENTES.model_copy(update={"usgs": FUENTES.usgs.model_copy(update={"endtime": "2025-12-31T23:59:59"})})
    r = cs.vincular_grupo("GRP-t", "sismos", [noticia("2025-03-02T10:00:00Z")], [evento(hora="2025-03-02T09:00:00Z")], VINCULOS, nuevas, CAMPOS)
    assert r.estado == cs.VINCULADO


def test_sin_evento_dentro_de_la_ventana_o_bajo_la_magnitud_minima():
    lejos = evento(hora="2024-05-13T15:00:01Z")                      # 3 días y 1 s después: fuera de ± 2 días
    debil = evento("SIS-us0009", magnitud=2.9)
    r = vincular([noticia()], [lejos, debil])
    assert r.estado == cs.SIN_EVENTO == "sin_evento_coincidente" and r.candidatos == ()


def test_el_borde_de_la_ventana_es_inclusivo_en_horas():
    justo = evento(hora="2024-05-12T15:00:00Z")                      # exactamente 48 h después
    assert vincular([noticia()], [justo]).estado == cs.VINCULADO


def test_noticia_sin_fecha_es_sin_dato_en_periodo():
    r = vincular([noticia(None, None)], [evento()])
    assert r.estado == cs.SIN_DATO_EN_PERIODO and "sin_dato_en_periodo" in VINCULOS.motivos_sin_vinculo


def test_fecha_de_deteccion_solo_si_falta_la_de_publicacion_y_queda_declarado():
    con_pub = vincular([noticia()], [evento()])
    assert con_pub.origenes_fecha == ("publicacion",) and VINCULOS.sismos.nota_fecha_deteccion not in con_pub.regla
    solo_det = vincular([noticia(None, "2024-05-10T15:00:00Z")], [evento()])
    assert solo_det.estado == cs.VINCULADO and solo_det.origenes_fecha == ("deteccion",)
    assert VINCULOS.sismos.nota_fecha_deteccion in solo_det.regla


def test_la_publicacion_no_se_sustituye_por_la_deteccion_cuando_existe():
    # publicación lejos del evento; detección cerca: se usa la publicación, así que no coincide
    r = vincular([noticia("2024-08-01T00:00:00Z", "2024-05-10T15:00:00Z")], [evento()])
    assert r.estado == cs.SIN_EVENTO


def test_un_grupo_usa_la_noticia_mas_cercana_y_ignora_las_de_fuera_de_cobertura():
    noticias = [noticia("2023-12-31T10:00:00Z", id_="NOT-1"), noticia("2024-05-10T15:00:00Z", id_="NOT-2")]
    r = vincular(noticias, [evento()])
    assert r.estado == cs.VINCULADO and r.candidatos[0].diferencia_horas == 3.0


def test_profundidad_nula_se_conserva_nula(tmp_path: Path):
    ruta = tmp_path / "eventos.geojson"
    props = {"id": "SIS-us1", "magnitude": 3.1, "time": "2024-02-01T00:00:00Z", "place": None, "status": "automatic",
             "url": "https://earthquake.usgs.gov/e/us1", "depth": None, "latitude": 8.0, "longitude": -80.0}
    ruta.write_text(json.dumps({"features": [{"properties": props}]}), encoding="utf-8")
    (e,) = cs.cargar_eventos(ruta)
    assert e.profundidad_km is None and e.place is None and e.estado == "automatic"
    assert e.hora_utc == datetime(2024, 2, 1, tzinfo=UTC)


def test_eventos_reales_del_snapshot_se_cargan_ordenados():
    ruta = Path(__file__).resolve().parents[1] / "data" / "processed" / "eventos.geojson"
    if not ruta.exists():
        pytest.skip("sin snapshot local")
    eventos = cs.cargar_eventos(ruta)
    assert eventos and all(e.id.startswith("SIS-") for e in eventos)
    assert [e.hora_utc for e in eventos] == sorted(e.hora_utc for e in eventos)


def base_metodo_a(tmp_path: Path) -> Path:
    """Base clasificada como el método A activo: ``subtema_clasificado`` nulo; el subtema solo está en ``similitud_tema`` (B)."""
    ruta = tmp_path / "senales.duckdb"
    base = {"titulo": "t", "url": "u", "url_canonica": "u", "medio": "m", "tipo_firma": "sin firma", "es_ruido": False, "subtema_clasificado": None}
    noticias = [
        # E1-10c (X41): el subtema exige que el titular lo nombre (el margen solo ya no basta)
        {**base, "titulo": "Sismo de 4,5 sacude Chiriquí", "id_noticia": "NOT-a", "fecha_publicacion": "2024-05-10T15:00:00Z", "id_grupo": "GRP-sismo"},
        {**base, "titulo": "Lluvias inundan calles de Colón", "id_noticia": "NOT-b", "fecha_publicacion": "2024-05-10T16:00:00Z", "id_grupo": "GRP-lluvia"},
    ]
    grupo = {"titular_central": "t", "n_titulares": 1, "n_medios": 1, "n_procedencias": 1, "estimado": True, "tema_clasificado": "eventos_naturales"}
    grupos = [
        {**grupo, "id_grupo": "GRP-sismo", "id_noticia_central": "NOT-a", "ids_noticia": "NOT-a"},
        {**grupo, "id_grupo": "GRP-lluvia", "id_noticia_central": "NOT-b", "ids_noticia": "NOT-b"},
    ]
    sim = [
        {"id_noticia": "NOT-a", "metodo": "B", "tema": "eventos_naturales", "similitud": 0.7, "subtema": "sismos", "margen_subtema": 0.05},
        {"id_noticia": "NOT-b", "metodo": "B", "tema": "eventos_naturales", "similitud": 0.7, "subtema": "inundaciones_lluvias", "margen_subtema": 0.05},
    ]
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": grupos, "similitud_tema": sim})
    return ruta


def escribir_eventos(ruta: Path, eventos: list[dict]) -> Path:
    rasgos = [
        {"properties": {"id": e["id"], "magnitude": e.get("magnitude"), "time": e["time"], "place": "Panama", "status": "reviewed",
                        "url": "https://earthquake.usgs.gov/e", "depth": 10.0, "latitude": 8.0, "longitude": -80.0}}
        for e in eventos
    ]
    ruta.write_text(json.dumps({"features": rasgos}), encoding="utf-8")
    return ruta


def test_x18_un_grupo_de_sismos_se_vincula_con_la_base_del_metodo_a(tmp_path: Path):
    geojson = escribir_eventos(tmp_path / "eventos.geojson", [{"id": "SIS-us0001", "magnitude": 4.5, "time": "2024-05-10T12:00:00Z"}])
    resultados, filas, _ = contexto.aplicar_sismos(base_metodo_a(tmp_path), geojson, VINCULOS)
    assert [(r.id_grupo, r.subtema, r.estado) for r in resultados] == [("GRP-sismo", "sismos", cs.VINCULADO)]   # lluvias: ausente
    assert [f["id_evidencia"] for f in filas] == ["SIS-us0001"]


def test_las_filas_de_usgs_entran_en_el_esquema_y_el_reproceso_respeta_las_de_indicador(tmp_path: Path):
    ruta = base_metodo_a(tmp_path)
    geojson = escribir_eventos(tmp_path / "eventos.geojson", [{"id": "SIS-us0001", "magnitude": 4.5, "time": "2024-05-10T12:00:00Z"}])
    con = db.conectar(ruta)
    db.insertar(con, "vinculos", [{"id_grupo": "GRP-x", "id_evidencia": "IND-PAN-X-2023", "tipo": "directa", "regla": "r", "fuente": "indicador", "rol": "panama"}])
    con.close()
    for _ in range(2):   # reproceso: no duplica las de USGS ni toca las del Banco Mundial
        contexto.aplicar_sismos(ruta, geojson, VINCULOS)
    con = db.conectar(ruta, solo_lectura=True)
    try:
        filas = db.leer_tabla(con, "vinculos", "fuente, id_grupo")
    finally:
        con.close()
    assert [(f["fuente"], f["id_grupo"]) for f in filas] == [("indicador", "GRP-x"), ("usgs", "GRP-sismo")]
    usgs = filas[1]
    assert (usgs["id_evidencia"], usgs["rol"], usgs["tipo"], usgs["subtema"], usgs["valor"], usgs["place"]) == ("SIS-us0001", "evento", "evento", "sismos", 4.5, "Panama")


def test_el_cli_escribe_los_resultados_de_usgs_en_el_reporte(tmp_path: Path):
    ruta = base_metodo_a(tmp_path)
    geojson = escribir_eventos(tmp_path / "eventos.geojson", [{"id": "SIS-us0001", "magnitude": 4.5, "time": "2024-05-10T12:00:00Z"}])
    reporte = tmp_path / "reporte.json"
    r = contexto.ejecutar(ruta, reporte, geojson)
    assert json.loads(reporte.read_text(encoding="utf-8")) == r
    assert r["usgs"]["grupos_de_sismos"] == 1 and r["usgs"]["por_resultado"] == {"vinculado": 1}
    assert r["usgs"]["vinculados"]["n"] == 1 and r["usgs"]["vinculados"]["ic95"] is not None
    assert "usgs" not in contexto.ejecutar(ruta, tmp_path / "otro.json")   # sin eventos no toca USGS


def test_magnitud_nula_no_rompe_la_carga_ni_coincide_y_se_cuenta(tmp_path: Path):
    geojson = escribir_eventos(
        tmp_path / "eventos.geojson",
        [{"id": "SIS-us0001", "magnitude": None, "time": "2024-05-10T12:00:00Z"}, {"id": "SIS-us0002", "magnitude": 4.0, "time": "2024-05-10T13:00:00Z"}],
    )
    eventos = cs.cargar_eventos(geojson)
    assert cs.contar_sin_magnitud(eventos) == 1
    r = vincular([noticia()], eventos)
    assert [c.evento.id for c in r.candidatos] == ["SIS-us0002"]
    _, _, sin_magnitud = contexto.aplicar_sismos(base_metodo_a(tmp_path), geojson, VINCULOS)
    assert sin_magnitud == 1


def test_el_bloque_sismos_prohibe_claves_desconocidas_y_zonas_invalidas(tmp_path: Path):
    import yaml

    datos = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "vinculos.yaml").read_text(encoding="utf-8"))
    for cambio in ({"sobra": 1}, {"zona_horaria": "Marte/Olimpo"}, {"limitaciones": []}, {"decimales_horas": -1}):
        malo = {**datos, "sismos": {**datos["sismos"], **cambio}}
        (tmp_path / "vinculos.yaml").write_text(yaml.safe_dump(malo, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ErrorDeConfiguracion):
            cargar_config("vinculos", ConfigVinculos, tmp_path)


# ------------------------------------------------------------------ seguimiento PR #18 (m2, m3, m4)


def _filas_vinculos(ruta: Path) -> list[tuple[str, str]]:
    con = db.conectar(ruta, solo_lectura=True)
    try:
        return [(f["fuente"], f["id_grupo"]) for f in db.leer_tabla(con, "vinculos", "fuente, id_grupo")]
    finally:
        con.close()


def _sembrar_usgs(ruta: Path) -> None:
    con = db.conectar(ruta)
    db.insertar(con, "vinculos", [{"id_grupo": "GRP-sismo", "id_evidencia": "SIS-viejo", "tipo": "evento", "regla": "r", "fuente": "usgs", "rol": "evento"}])
    con.close()


def test_m2_sin_eventos_geojson_se_borran_las_filas_usgs_y_el_reporte_lo_dice(tmp_path: Path, caplog):
    ruta = base_metodo_a(tmp_path)
    _sembrar_usgs(ruta)
    r = contexto.ejecutar(ruta, tmp_path / "reporte.json", tmp_path / "no_existe.geojson")
    assert all(f != "usgs" for f, _ in _filas_vinculos(ruta))   # tabla y reporte coherentes
    assert r["usgs"]["estado"] == "no ejecutado: falta eventos.geojson" and r["usgs"]["filas_en_vinculos"] == 0
    assert json.loads((tmp_path / "reporte.json").read_text(encoding="utf-8")) == r


def test_m3_la_reescritura_es_atomica_si_usgs_falla_no_cambia_nada(tmp_path: Path, monkeypatch):
    ruta = base_metodo_a(tmp_path)
    con = db.conectar(ruta)   # estado previo: una fila de indicador que la reescritura borraría
    db.insertar(con, "vinculos", [{"id_grupo": "GRP-viejo", "id_evidencia": "IND-PAN-X-2020", "tipo": "directa", "regla": "r", "fuente": "indicador", "rol": "panama"}])
    con.close()
    _sembrar_usgs(ruta)
    antes = _filas_vinculos(ruta)
    assert antes   # hay filas de indicador y de usgs

    def falla(_ruta):
        raise ValueError("geojson corrupto")

    monkeypatch.setattr(cs, "cargar_eventos", falla)
    geojson = escribir_eventos(tmp_path / "eventos.geojson", [])
    with pytest.raises(ValueError, match="corrupto"):
        contexto.ejecutar(ruta, tmp_path / "r1.json", geojson)
    assert _filas_vinculos(ruta) == antes
    assert not (tmp_path / "r1.json").exists()


def test_m4_la_ruta_por_defecto_del_cli_vincula_usgs_si_existe_eventos_geojson(tmp_path: Path, monkeypatch):
    ruta = base_metodo_a(tmp_path)
    geojson = escribir_eventos(tmp_path / "eventos.geojson", [{"id": "SIS-us0001", "magnitude": 4.5, "time": "2024-05-10T12:00:00Z"}])
    monkeypatch.setattr(contexto, "RAIZ", tmp_path)
    monkeypatch.setattr(contexto, "EVENTOS", Path("eventos.geojson"))
    (tmp_path / "data").mkdir()
    geojson.rename(tmp_path / "data" / "eventos.geojson")
    reporte = tmp_path / "reporte.json"
    assert contexto.main(["--base", str(ruta), "--reporte", str(reporte)]) == 0   # sin --eventos
    assert ("usgs", "GRP-sismo") in _filas_vinculos(ruta)
    assert json.loads(reporte.read_text(encoding="utf-8"))["usgs"]["por_resultado"] == {"vinculado": 1}
