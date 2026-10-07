"""E1-10c · D-105: el ranking es el del reto (P, luego mayor U, luego ID) y los empates se muestran; X51 («pese a» no es Pesé)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import precision_at_5 as p5
from src import db, embeddings, interfaz as ui, prioridad, puntaje
from src.configuracion import cargar_interfaz, cargar_modalidad, cargar_prioridad
from src.ficha import construir_ficha, vista
from tests import ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, construir_base
from tests.test_t08_prioridad import _con

INTERFAZ = cargar_interfaz()


def _orden(lista: list[puntaje.Puntaje]) -> list[puntaje.Puntaje]:
    return puntaje.ordenar(lista, REGLAS, CFG)


# ------------------------------------------------------------------ la regla del reto, en todas partes


def test_d105_la_regla_de_desempate_es_la_del_reto() -> None:
    assert REGLAS.desempate == ["u_desc", "id_asc"]   # PDF sección 4: «Empates: mayor urgencia y luego ID»


def test_d105_el_empate_se_decide_con_p_tal_como_se_muestra() -> None:
    # 87.44 y 87.41 se muestran los dos como 87.4: es un empate y lo decide la urgencia, no el decimal oculto
    orden = _orden([_con("GRP-a", 87.44, 0.5), _con("GRP-b", 87.41, 0.9), _con("GRP-c", 87.43, 0.1)])
    assert [p.id_grupo for p in orden] == ["GRP-b", "GRP-a", "GRP-c"]


def test_d105_la_precision_del_empate_es_la_que_muestra_la_bandeja() -> None:
    assert cargar_prioridad().comparacion.decimales_empate == INTERFAZ.bandeja.decimales_puntaje


def test_d105_la_bandeja_de_la_app_usa_la_misma_regla() -> None:
    def fila(g: str, p: float, u: float) -> ui.FilaBandeja:
        return ui.FilaBandeja(1, g, "tema", "titular", p, "alto", {"R": 1, "I": 1, "U": u, "N": 1, "E": 1}, "parcial", "Vigilar")

    filas = [fila("GRP-a", 87.44, 0.5), fila("GRP-b", 87.41, 0.9), fila("GRP-c", 87.43, 0.1)]
    assert [f.id_grupo for f in ui.ordenar_bandeja(filas)] == ["GRP-b", "GRP-a", "GRP-c"]


# ------------------------------------------------------------------ tamaño del empate


def test_d105_cada_puntaje_lleva_cuantos_otros_grupos_empatan_con_el() -> None:
    orden = _orden([_con("GRP-a", 87.4, 0.5), _con("GRP-b", 87.41, 0.9), _con("GRP-c", 87.38, 0.1), _con("GRP-d", 80.0, 1.0)])
    assert {p.id_grupo: p.empate_con for p in orden} == {"GRP-a": 2, "GRP-b": 2, "GRP-c": 2, "GRP-d": 0}
    assert orden[0].a_diccionario()["empate_con"] == 2


@pytest.fixture
def emb(tmp_path: Path):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)


def test_d105_prioridad_json_y_la_tabla_puntajes_guardan_el_empate(tmp_path: Path, emb) -> None:
    base = construir_base(tmp_path / "senales.duckdb")
    reporte = prioridad.ejecutar(base, tmp_path / "prioridad.json", AHORA, None, emb=emb)
    en_json = {f["id_grupo"]: f["empate_con"] for f in json.loads((tmp_path / "prioridad.json").read_text(encoding="utf-8"))["ranking"]}
    con = db.conectar(base, solo_lectura=True)
    try:
        en_tabla = {f["id_grupo"]: f["empate_con"] for f in db.leer_tabla(con, "puntajes")}
        bandeja = {f.id_grupo: f.empate_con for f in ui.leer_bandeja(con, "editorial")}
    finally:
        con.close()
    d = cargar_prioridad().comparacion.decimales_empate
    ps = {f["id_grupo"]: round(f["puntaje"], d) for f in reporte["ranking"]}
    esperado = {g: sum(1 for o, q in ps.items() if o != g and q == p) for g, p in ps.items()}
    assert en_json == en_tabla == bandeja == esperado


# ------------------------------------------------------------------ cómo se muestra


def test_d105_el_texto_del_empate_sale_de_la_configuracion() -> None:
    assert ui.texto_empate(0) == ""
    assert ui.texto_empate(1) == INTERFAZ.textos.empate.uno
    assert ui.texto_empate(9) == INTERFAZ.textos.empate.varios.format(n=9)
    assert "urgencia y luego ID" in ui.texto_empate(9) and "9 grupos" in ui.texto_empate(9)


def test_d105_la_bandeja_por_sector_de_la_cli_marca_el_empate() -> None:
    banca = cargar_modalidad("banca")
    sector = next(iter(banca.bandeja.etiquetas_sector))
    filas = [
        ui.FilaBandeja(1, "GRP-a", "t", "titular a", 87.4, "alto", {k: 1.0 for k in "RIUNE"}, "parcial", "x", sector=sector, empate_con=1),
        ui.FilaBandeja(2, "GRP-b", "t", "titular b", 87.4, "alto", {k: 1.0 for k in "RIUNE"}, "parcial", "x", sector=sector, empate_con=1),
    ]
    lineas = ui.lineas_de_bandeja(filas, banca)
    assert lineas is not None and sum(ui.texto_empate(1) in linea for linea in lineas) == 2


def test_d105_la_ficha_muestra_el_empate(tmp_path: Path, emb) -> None:
    ruta = h.construir(tmp_path / "senales.duckdb", emb)
    con = db.conectar(ruta, solo_lectura=True)
    try:
        f = construir_ficha(h.G_COMPLETO, "editorial", con, emb)
    finally:
        con.close()
    empatada = f.model_copy(update={"puntaje": f.puntaje.model_copy(update={"empate_con": 3})})
    texto = "\n".join(linea.texto for s in vista(empatada).secciones for linea in s.lineas)
    assert ui.texto_empate(3) in texto
    sola = f.model_copy(update={"puntaje": f.puntaje.model_copy(update={"empate_con": 0})})
    prefijo = INTERFAZ.textos.empate.uno.split(" con ")[0]
    assert prefijo not in "\n".join(linea.texto for s in vista(sola).secciones for linea in s.lineas)


# ------------------------------------------------------------------ el corte del top k


def test_d105_el_empate_en_el_corte_se_reporta() -> None:
    assert puntaje.empate_en_el_corte([90, 87.4, 87.4, 87.4, 87.4, 87.4, 87.4, 80], 5) == {
        "valor": 87.4, "empatados": 6, "dentro_del_top": 4, "fuera_del_top": 2,
    }
    assert puntaje.empate_en_el_corte([90, 89, 88, 87, 86, 85], 5) is None
    assert puntaje.empate_en_el_corte([90, 89], 5) is None


def test_d105_precision_at_5_declara_el_empate_en_el_corte_del_sistema_y_del_baseline() -> None:
    ps = [90, 87.4, 87.4, 87.4, 87.4, 87.4, 87.4, 80]
    cands = [
        p5.Candidato(f"GRP-{i}", "tema", "t", "2026-10-06T00:00:00Z" if i < 3 else "2026-10-05T00:00:00Z", i + 1, puntaje=p)
        for i, p in enumerate(ps)
    ]
    r = p5.evaluar_corte(cands, {"GRP-1"}, "2026-10-06T12:00:00Z", 5, 1.96)
    assert r["sistema"]["empate_en_el_corte"] == {"valor": 87.4, "empatados": 6, "dentro_del_top": 4, "fuera_del_top": 2}
    assert r["baseline"]["empate_en_el_corte"]["empatados"] == 5 and r["baseline"]["empate_en_el_corte"]["fuera_del_top"] == 3
    assert "ID" in r["criterio_de_empate"]


# ------------------------------------------------------------------ X60 · una sola precisión para mostrar y comparar


def test_x60_la_cli_muestra_p_con_los_decimales_de_la_bandeja() -> None:
    fila = {"posicion": 1, "id_grupo": "GRP-a", "puntaje": 87.4567, "rango": "alto", "estado_de_evidencia": "parcial", "accion": "Vigilar", "titular_central": "t", "empate_con": 0}
    for d in (1, 2):
        cfg = INTERFAZ.model_copy(update={"bandeja": INTERFAZ.bandeja.model_copy(update={"decimales_puntaje": d})})
        assert f"P={87.4567:.{d}f} " in prioridad.lineas_de_ranking([fila], cfg)[0]


def test_x60_la_coherencia_falla_si_comparar_y_mostrar_difieren(tmp_path: Path) -> None:
    import shutil

    from src.configuracion import CARPETA_CONFIG, validar_coherencia

    for ruta in CARPETA_CONFIG.iterdir():
        if ruta.is_file():
            shutil.copy(ruta, tmp_path / ruta.name)
    assert validar_coherencia(tmp_path) == []
    destino = tmp_path / "prioridad.yaml"
    destino.write_text(destino.read_text("utf-8").replace("decimales_empate: 1", "decimales_empate: 2"), encoding="utf-8")
    assert any("decimales_empate" in p for p in validar_coherencia(tmp_path))
