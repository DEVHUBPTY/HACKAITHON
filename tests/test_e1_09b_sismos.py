"""E1-09b: vínculo de grupos de sismos con eventos de USGS. Sin red, sin modelo y sin la base real."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src import contexto_sismos as cs
from src import db
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
    (fila,) = cs.a_filas_vinculo(r)
    assert fila == {
        "id_grupo": "GRP-test", "tipo": "evento", "id_evidencia": "SIS-us0001", "regla": r.regla,
        "limitacion": r.limitacion, "motivo_sin_vinculo": None,
    }
    assert "± 2 días" in r.regla and "magnitud mínima 3" in r.regla


def test_dos_candidatos_se_listan_todos_y_ninguno_se_elige():
    eventos = [evento("SIS-us0001", "2024-05-10T12:00:00Z"), evento("SIS-us0002", "2024-05-11T20:00:00Z", magnitud=3.2)]
    r = vincular([noticia()], eventos)
    assert r.estado == cs.CANDIDATOS_AMBIGUOS == "candidatos_ambiguos"
    assert {c.evento.id for c in r.candidatos} == {"SIS-us0001", "SIS-us0002"}
    filas = cs.a_filas_vinculo(r)
    assert {f["id_evidencia"] for f in filas} == {"SIS-us0001", "SIS-us0002"}
    assert {f["motivo_sin_vinculo"] for f in filas} == {"candidatos_ambiguos"}


@pytest.mark.parametrize("subtema", ["inundaciones_lluvias", "deslizamientos", "alertas_proteccion_civil", "sequia_nino", None])
def test_lluvias_inundaciones_y_danos_nunca_se_vinculan_a_usgs(subtema):
    # hay un evento perfecto el mismo día: aun así, el subtema no lo permite
    assert vincular([noticia()], [evento()], subtema=subtema) is None


def test_noticia_de_2025_es_fuera_de_cobertura():
    r = vincular([noticia("2025-03-02T10:00:00Z")], [evento("SIS-us0001", "2025-03-02T09:00:00Z")])
    assert r.estado == cs.FUERA_DE_COBERTURA == "fuera_de_cobertura"
    assert r.candidatos == ()
    (fila,) = cs.a_filas_vinculo(r)
    assert fila["id_evidencia"] is None and fila["motivo_sin_vinculo"] == "fuera_de_cobertura"


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


def test_subtema_dominante_y_vincular_base(tmp_path: Path):
    ruta = tmp_path / "senales.duckdb"
    con = db.conectar(ruta)
    db.crear_esquema(con)
    con.close()
    base = {"titulo": "t", "url": "u", "url_canonica": "u", "medio": "m", "tipo_firma": "sin firma", "es_ruido": False}
    noticias = [
        {**base, "id_noticia": "NOT-a", "fecha_publicacion": "2024-05-10T15:00:00Z", "subtema_clasificado": "sismos"},
        {**base, "id_noticia": "NOT-b", "fecha_publicacion": "2024-05-10T16:00:00Z", "subtema_clasificado": "inundaciones_lluvias"},
        {**base, "id_noticia": "NOT-c", "fecha_publicacion": "2024-05-10T16:00:00Z", "subtema_clasificado": "inundaciones_lluvias"},
    ]
    assert cs.subtema_dominante(noticias[:2]) == "inundaciones_lluvias"        # empate: orden alfabético
    assert cs.subtema_dominante([{"subtema_clasificado": None}]) is None
    grupo = {"titular_central": "t", "n_titulares": 1, "n_medios": 1, "n_procedencias": 1, "estimado": True}
    grupos = [
        {**grupo, "id_grupo": "GRP-sismo", "id_noticia_central": "NOT-a", "ids_noticia": "NOT-a"},
        {**grupo, "id_grupo": "GRP-lluvia", "id_noticia_central": "NOT-b", "ids_noticia": "NOT-b,NOT-c"},
    ]
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": grupos})
    res = cs.vincular_base(ruta, [evento()], VINCULOS, FUENTES, CAMPOS)
    assert [(r.id_grupo, r.estado) for r in res] == [("GRP-sismo", cs.VINCULADO)]


def test_el_bloque_sismos_prohibe_claves_desconocidas_y_zonas_invalidas(tmp_path: Path):
    import yaml

    datos = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "vinculos.yaml").read_text(encoding="utf-8"))
    for cambio in ({"sobra": 1}, {"zona_horaria": "Marte/Olimpo"}, {"limitaciones": []}):
        malo = {**datos, "sismos": {**datos["sismos"], **cambio}}
        (tmp_path / "vinculos.yaml").write_text(yaml.safe_dump(malo, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ErrorDeConfiguracion):
            cargar_config("vinculos", ConfigVinculos, tmp_path)
