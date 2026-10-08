"""D-127: etapa 3 sin relaciones forzadas. «Si no existe relación sustentada, no forzarla» (PDF, etapa 3).

* La logística ya no recibe las exportaciones por ser logística: solo si un titular habla de exportaciones, comercio exterior o
  carga contenerizada. «Canal» solo no es evidencia.
* USGS: un término sísmico literal en el titular (de cualquier tema) basta para mostrar el catálogo 2024 como contexto histórico
  (`indirecta`), nunca como el evento de la noticia.
* La ficha muestra periodo, unidad y limitaciones de cada vínculo.

Datos sintéticos y la configuración real; sin red ni LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src import contexto, db, embeddings, prioridad
from src.configuracion import cargar_vinculos
from src.ficha import a_markdown, construir_ficha, texto_respaldo, vista
from tests import ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.prioridad_ayuda import fila_grupo, filas_procedencias
from tests.test_e3_02_ficha import csv_sbp

CFG = cargar_vinculos()

CANAL_PRESUPUESTO = "Ejecutivo sanciona la Ley 552 del Presupuesto del Canal de Panamá por $5,555 millones"
CAPITAN_REMOLCADOR = "Inland navigation workers stand with Panama Canal workers after death of tug captain"
SUBADMINISTRADOR = "Miguel Lorenzo Fábrega toma posesión como nuevo subadministrador del Canal de Panamá"
GNL_EEUU = "US LNG Exports Increase in September, Europe Outbids Asia for Cargoes"
UTP_SISMOS = "Universidad Tecnológica evalúa unos 200 edificios para determinar su seguridad ante sismos"
PANDORA = "Caso Pandora: Legalizan aprehensión de exejecutivo bancario señalado por autorizar pagos de créditos fiscales de la DGI"


def disparadas(tema: str, *titulares: str) -> dict[str, str]:
    return contexto.reglas_disparadas(list(titulares), tema, CFG)


# ------------------------------------------------------------------ 1 · la logística no se fuerza


@pytest.mark.parametrize("titular", [CANAL_PRESUPUESTO, CAPITAN_REMOLCADOR, SUBADMINISTRADOR, GNL_EEUU, "Panamá reforzará su presencia marítima en Vietnam"])
def test_un_titular_de_logistica_sin_apoyo_lexico_no_trae_ningun_vinculo_y_dice_por_que(titular: str) -> None:
    d = disparadas("logistica", titular)
    assert d == {}
    vinculo, regla, motivo, _ = contexto.elegir_vinculo("logistica", d, CFG)
    assert vinculo is None and motivo == "sin_relacion_sustentada" and "no se fuerza" in regla
    (fila,) = contexto.vincular_grupo("GRP-1", "logistica", d, titular, 2026, [], CFG)
    assert fila["motivo_sin_vinculo"] == "sin_relacion_sustentada" and fila["id_evidencia"] is None and fila["valor"] is None


@pytest.mark.parametrize(
    ("titular", "termino"),
    [
        ("Exportaciones chinas sostienen la demanda de carga contenerizada pese a la debilidad de EE. UU.", "exportaciones"),
        ("Puerto de Balboa mueve más contenedores en septiembre", "contenedores"),
        ("El Canal registra récord de TEU", "teu"),
        ("Panamá busca más comercio exterior por sus puertos", "comercio exterior"),
    ],
)
def test_un_titular_de_logistica_que_habla_de_exportaciones_o_carga_si_se_vincula_como_indirecto(titular: str, termino: str) -> None:
    d = disparadas("logistica", titular)
    assert d == {"exportaciones_logistica": termino}
    vinculo, regla, motivo, nombre = contexto.elegir_vinculo("logistica", d, CFG)
    assert motivo is None and nombre == "exportaciones_logistica" and vinculo is not None
    assert (vinculo.id, vinculo.relacion) == ("NE.EXP.GNFS.ZS", "indirecta") and termino in regla


@pytest.mark.parametrize("titular", ["Puertos reducen carga por menor demanda", "Aumenta la carga que cruza el Canal", "La carga fiscal de las empresas sube", "Aumenta la carga aérea en Tocumen"])
def test_carga_suelta_no_sustenta_las_exportaciones(titular: str) -> None:
    assert disparadas("logistica", titular) == {}


def test_ya_no_existe_el_vinculo_por_tema() -> None:
    assert not hasattr(CFG, "vinculos_por_tema")
    for tema in ("logistica", "servicios_publicos", "economia"):
        vinculo, _, motivo, _ = contexto.elegir_vinculo(tema, {}, CFG)
        assert vinculo is None and motivo == "sin_relacion_sustentada"
    for tema in ("turismo", "regulacion", "eventos_naturales", None):    # temas sin ninguna regla de indicador
        assert contexto.elegir_vinculo(tema, {}, CFG)[2] == "tema_sin_indicador"


def test_la_ficha_dice_en_palabras_que_no_se_fuerza_la_relacion() -> None:
    from src.configuracion import cargar_prioridad

    textos = cargar_prioridad().vacios.motivos_sin_vinculo
    assert "no se fuerza la relación" in textos["sin_relacion_sustentada"]


# ------------------------------------------------------------------ 2 · USGS como contexto histórico


def _evento(id_: str, magnitud: float | None, hora: str, place: str, estado: str = "reviewed") -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "id": id_, "magnitude": magnitud, "time": hora, "updated": hora, "longitude": -80.1, "latitude": 7.5, "depth": 10.0,
            "place": place, "status": estado, "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{id_.removeprefix('SIS-')}",
        },
        "geometry": {"type": "Point", "coordinates": [-80.1, 7.5, 10.0]},
    }


def geojson(ruta: Path) -> Path:
    eventos = [
        _evento("SIS-us0001", 3.4, "2024-02-01T10:00:00Z", "10 km N of David, Panama"),
        _evento("SIS-us0002", 5.8, "2024-08-26T05:08:44Z", "83 km S of Boca Chica, Panama"),
        _evento("SIS-us0003", 5.8, "2024-09-30T01:00:00Z", "40 km W of Jaco, Costa Rica"),       # empate: gana el más antiguo
        _evento("SIS-us0004", 2.9, "2024-10-01T01:00:00Z", "5 km S of Algo, Panama"),            # bajo el mínimo del reto (3)
        _evento("SIS-us0005", None, "2024-11-01T01:00:00Z", "sin magnitud"),                      # nulo: ni se cuenta ni se rellena
    ]
    ruta.write_text(json.dumps({"type": "FeatureCollection", "features": eventos}), encoding="utf-8")
    return ruta


def _base(tmp_path: Path, casos: dict[str, tuple[str, list[str], str]]) -> Path:
    """``casos``: id_grupo → (tema, titulares, fecha de publicación)."""
    noticias, grupos, procs = [], [], []
    for gid, (tema, titulos, fecha) in casos.items():
        filas = [h.n(f"NOT-{len(noticias) + i:010x}", t, "prensa.example" if i % 2 else "tvn-2.com", gid, tema_clasificado=tema, fecha_publicacion=fecha) for i, t in enumerate(titulos, 1)]
        ids = [x["id_noticia"] for x in filas]
        noticias += filas
        grupos.append(fila_grupo(gid, ids, titulos[0], len(ids)) | {"tema_clasificado": tema, "fecha_inicio": fecha, "fecha_inicio_origen": "publicacion", "fecha_fin": fecha, "fecha_fin_origen": "publicacion"})
        procs += filas_procedencias(gid, ids)
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": grupos, "procedencias": procs, "fuentes": h.FUENTES, "vinculos": [], "indicadores": _indicadores()})
    return ruta


def _indicadores() -> list[dict[str, Any]]:
    return [
        {"id_indicador": f"IND-PAN-FP.CPI.TOTL.ZG-{a}", "pais_iso3": "PAN", "indicador_id": "FP.CPI.TOTL.ZG", "anio": a, "valor": None if a == 2024 else 1.5,
         "unidad": "% anual", "fuente_url": "https://example.org", "fecha_extraccion": "2026-10-06T00:00:00Z", "licencia": "CC BY 4.0"}
        for a in range(2019, 2025)
    ]


def _vinculos(base: Path) -> list[dict[str, Any]]:
    con = db.conectar(base, solo_lectura=True)
    try:
        return db.leer_tabla(con, "vinculos", "id_grupo, fuente, id_evidencia")
    finally:
        con.close()


CASOS = {
    "GRP-utp": ("servicios_publicos", [UTP_SISMOS], "2026-10-06T08:00:00Z"),
    "GRP-sin-sismo": ("eventos_naturales", ["Inundaciones dejan familias evacuadas en Colón"], "2026-10-06T08:00:00Z"),
    "GRP-econ": ("economia", ["Sube el costo de la vida en Panamá"], "2026-10-06T08:00:00Z"),
    "GRP-canal": ("logistica", [CANAL_PRESUPUESTO], "2026-10-06T08:00:00Z"),
    "GRP-pandora": ("regulacion", [PANDORA], "2026-10-06T08:00:00Z"),
}


def test_un_titular_sismico_de_otro_tema_recibe_el_catalogo_2024_como_contexto_historico_y_nada_mas(tmp_path: Path) -> None:
    base = _base(tmp_path, CASOS)
    r = contexto.ejecutar(base, tmp_path / "rep.json", geojson(tmp_path / "eventos.geojson"))
    usgs = [v for v in _vinculos(base) if v["fuente"] == "usgs"]
    assert {v["id_grupo"] for v in usgs} == {"GRP-utp"}                        # solo el titular con un término sísmico literal
    (v,) = usgs
    assert (v["tipo"], v["rol"], v["motivo_sin_vinculo"]) == ("indirecta", "contexto_historico", None)
    assert v["id_evidencia"] == "SIS-us0002"                                   # el mayor (5.8); el empate lo gana el más antiguo
    assert (v["valor"], v["unidad"], v["periodo"], v["anio"]) == (5.8, "magnitud", "2024", 2024)
    assert v["n_eventos"] == 3                                                 # M >= 3: sin el de 2.9 ni el de magnitud nula
    assert v["place"] == "83 km S of Boca Chica, Panama" and v["hora_utc"] == "2024-08-26T05:08:44Z"   # tal como lo da USGS
    for parte in ("no equivale al territorio de Panamá", "Periodo 2024, no coincide con la fecha de la noticia", "no es el evento de la noticia", "no informa daños ni pérdidas"):
        assert parte in v["limitacion"], parte
    assert r["usgs"]["por_resultado"] == {"contexto_historico": 1}
    # el resto de los grupos no se toca: sin término sísmico no hay USGS, aunque el tema sea eventos_naturales
    assert not any(v["fuente"] == "usgs" and v["id_grupo"] in ("GRP-sin-sismo", "GRP-econ", "GRP-canal", "GRP-pandora") for v in _vinculos(base))


@pytest.mark.parametrize("termino", ["sismo", "sismos", "sísmico", "temblor", "terremoto"])
def test_cada_termino_sismico_literal_sustenta_el_contexto(termino: str) -> None:
    assert list(contexto.reglas_contextuales([f"Reportan {termino} en el país"], CFG)) == ["sismos"]


@pytest.mark.parametrize("titular", ["Inundaciones dejan familias evacuadas", "Lluvias y deslizamientos en Chiriquí", "El Canal reduce tránsitos por la sequía", UTP_SISMOS.replace("sismos", "incendios")])
def test_un_titular_sin_terminos_sismicos_nunca_recibe_usgs(titular: str) -> None:
    assert contexto.reglas_contextuales([titular], CFG) == {}


def test_si_un_evento_coincide_en_el_tiempo_sigue_el_vinculo_de_siempre_y_no_el_contexto(tmp_path: Path) -> None:
    base = _base(tmp_path, {"GRP-hoy": ("eventos_naturales", ["Fuerte sismo sacude Chiriquí"], "2024-08-26T07:00:00Z")})
    contexto.ejecutar(base, tmp_path / "rep.json", geojson(tmp_path / "eventos.geojson"))
    (v,) = [v for v in _vinculos(base) if v["fuente"] == "usgs"]
    assert (v["tipo"], v["rol"], v["id_evidencia"]) == ("evento", "evento", "SIS-us0002")


def test_el_contexto_historico_no_cuenta_como_dato_oficial_ni_cambia_el_puntaje(tmp_path: Path) -> None:
    from src import contexto_sismos

    assert CFG.sismos.contexto_historico.relacion == "indirecta"
    from src.configuracion import cargar_prioridad

    assert CFG.sismos.contexto_historico.relacion not in cargar_prioridad().dato_oficial.relaciones_aceptadas
    assert contexto_sismos.CONTEXTO_HISTORICO not in contexto_sismos.ESTADOS_DE_EVENTO


# ------------------------------------------------------------------ 3 · la ficha muestra periodo, unidad y limitaciones


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


def test_la_ficha_muestra_periodo_unidad_y_limitaciones_del_contexto_sismico_y_no_lo_cuenta_como_dato_oficial(tmp_path: Path, emb) -> None:
    base = _base(tmp_path, CASOS)
    contexto.ejecutar(base, tmp_path / "rep.json", geojson(tmp_path / "eventos.geojson"))
    prioridad.ejecutar(base, base.with_name("prioridad.json"), h.CORTE, None, "editorial", emb=emb)
    con = db.conectar(base, solo_lectura=True)
    try:
        ficha = construir_ficha("GRP-utp", "editorial", con, emb=emb)
        sin_vinculo = construir_ficha("GRP-canal", "editorial", con, emb=emb)
    finally:
        con.close()
    assert not ficha.respaldado.eventos_oficiales and not ficha.respaldado.datos_oficiales    # no mide el hecho: va aparte
    (linea,) = ficha.respaldado.contexto_oficial
    assert linea.citas[0].id == "SIS-us0002" and linea.citas[0].campo == "magnitude"
    for parte in ("USGS", "contexto sísmico histórico", "3 eventos", "durante 2024", "magnitud 5.8, lugar", "83 km S of Boca Chica, Panama", "tal como lo da la fuente"):
        assert parte in linea.texto, parte
    texto = texto_respaldo(linea)
    for parte in ("Limitación:", "no equivale al territorio de Panamá", "no coincide con la fecha de la noticia", "no informa daños ni pérdidas", "Hora:", "Cita: SIS-us0002"):
        assert parte in texto, parte
    assert "Contexto oficial (no mide el hecho)" in a_markdown(ficha)
    assert any("solo vínculo indirecto" in v.texto for v in ficha.falta_comprobar.principales + ficha.falta_comprobar.otros)
    # logística sin término: la ficha lo dice sin forzar nada
    assert not sin_vinculo.respaldado.datos_oficiales and not sin_vinculo.respaldado.contexto_oficial
    assert any("no se fuerza la relación" in v.texto for v in sin_vinculo.falta_comprobar.principales + sin_vinculo.falta_comprobar.otros)


def test_cada_vinculo_de_la_ficha_lleva_periodo_unidad_y_limitacion(tmp_path: Path, emb) -> None:
    """PDF, etapa 3: «Mostrar período, unidad y limitaciones»: Banco Mundial (año y unidad), SBP (período y unidad) y USGS."""
    casos = {
        "GRP-econ": ("economia", ["Sube el costo de la vida en Panamá", "Inflación de septiembre preocupa"], "2026-10-06T08:00:00Z"),
        "GRP-banca": ("economia", ["El sistema bancario mantiene su cartera estable"], "2026-10-06T08:00:00Z"),
        "GRP-utp": CASOS["GRP-utp"],
    }
    base = _base(tmp_path, casos)
    contexto.ejecutar(base, tmp_path / "rep.json", geojson(tmp_path / "eventos.geojson"), csv_sbp(tmp_path / "sbp_series.csv"))
    prioridad.ejecutar(base, base.with_name("prioridad.json"), h.CORTE, None, "editorial", emb=emb)
    con = db.conectar(base, solo_lectura=True)
    try:
        fichas = {g: construir_ficha(g, "editorial", con, emb=emb) for g in casos}
    finally:
        con.close()
    lineas = {g: [*f.respaldado.datos_oficiales, *f.respaldado.contexto_oficial, *f.respaldado.eventos_oficiales] for g, f in fichas.items()}
    assert all(lineas.values())
    esperado = {"GRP-econ": ("PAN 2023", "% anual"), "GRP-banca": ("período 2024-12", "millones de balboas"), "GRP-utp": ("durante 2024", "magnitud")}
    for g, (periodo, unidad) in esperado.items():
        for linea in lineas[g]:
            assert periodo in linea.texto, (g, linea.texto)
            assert linea.limitacion, f"{g}: sin limitación"
            assert "Limitación:" in texto_respaldo(linea)
        assert any(periodo in x.texto for x in lineas[g]), (g, periodo)
        assert any(unidad in x.texto for x in lineas[g]), (g, unidad)
    assert vista(fichas["GRP-utp"])  # la vista (app y Markdown) se arma con el contexto sísmico


# ------------------------------------------------------------------ 4 · la banca no se pega al caso penal de Pandora


def test_los_agregados_bancarios_no_se_vinculan_al_caso_penal_pandora(tmp_path: Path) -> None:
    assert disparadas("regulacion", PANDORA) == {}                       # el titular es de regulación: la regla `banca` exige economía
    base = _base(tmp_path, {"GRP-pandora": CASOS["GRP-pandora"]})
    r = contexto.ejecutar(base, tmp_path / "rep.json", None, csv_sbp(tmp_path / "sbp_series.csv"))
    assert r["sbp"]["grupos_de_banca"] == 0
    assert not [v for v in _vinculos(base) if v["fuente"] == "sbp"]
    (v,) = _vinculos(base)
    assert v["motivo_sin_vinculo"] == "tema_sin_indicador" and v["id_evidencia"] is None   # regulación no tiene reglas de indicador
