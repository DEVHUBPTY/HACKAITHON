"""E3-02 · una ficha bancaria muestra un dato SBP- con período, unidad, página y limitación (vínculo, puntaje y ficha). Sin red ni LLM."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from src import contexto, contexto_sbp, db, embeddings, prioridad
from src.configuracion import ConfigVinculos, cargar_fuentes, cargar_verificacion, cargar_vinculos
from src.ficha import a_markdown, a_registro, construir_ficha
from src.interfaz import citas_de_ficha, vinculos_oficiales_de
from tests import ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.prioridad_ayuda import fila_grupo, filas_procedencias

VINCULOS = cargar_vinculos()
FUENTES = cargar_fuentes()
G_BANCA, G_OTRO = "GRP-banca", "GRP-turismo"
COLUMNAS = list(contexto_sbp.COLUMNAS)


def csv_sbp(ruta: Path, filas: list[dict[str, Any]] | None = None) -> Path:
    """Un ``sbp_series.csv`` con las tres series de 2024 (valor = mes, para reconocerlo)."""
    series = {
        "SBP-MOROSIDAD-SISTEMA": ("Saldo moroso sobre la cartera del sistema bancario", "proporción de la cartera del sistema (0 a 1)", "Morosos", 14),
        "SBP-MOROSOS-SISTEMA": ("Saldo moroso del sistema bancario", "millones de balboas", "Morosos", 6),
        "SBP-PROVISIONES-SISTEMA": ("Provisiones para préstamos del sistema bancario", "millones de balboas", "Provisiones", 6),
    }
    if filas is None:
        filas = []
        for id_serie, (nombre, unidad, hoja, fila) in series.items():
            for mes in range(1, 13):
                filas.append(
                    {
                        "id_serie": id_serie, "nombre_serie": nombre, "periodo": f"2024-{mes:02d}",
                        "valor": 0.1234 + mes / 10000 if "MOROSIDAD" in id_serie else 1000 + mes,
                        "unidad": unidad, "informe": f"Informe {hoja}", "pagina": f"hoja «{hoja}», celda {chr(64 + mes)}{fila}",
                        "url": f"https://www.superbancos.gob.pa/documentos/{hoja}.xlsx", "fecha_extraccion": "2026-10-07T18:53:25Z",
                        "condiciones": "Pendiente de verificar",
                    }
                )
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, lineterminator="\n")
        w.writeheader()
        for fila in filas:
            w.writerow({c: ("" if fila.get(c) is None else fila[c]) for c in COLUMNAS})
    return ruta


def base_de_banca(ruta: Path) -> Path:
    """Dos grupos: uno de banca (subtema ``banca_calificaciones``, con «bancario» en el titular) y uno de turismo."""
    grupos, noticias, procs, sims = [], [], [], []
    for gid, titulos, tema, sub in (
        (G_BANCA, ["El sistema bancario mantiene su cartera estable", "Banca panameña reporta cartera estable"], "economia", "banca_calificaciones"),
        (G_OTRO, ["Llegan más cruceros a Colón"], "turismo", "cruceros"),
    ):
        filas = [h.n(f"NOT-{gid[-1]}00000000{i}", t, "prensa.example" if i % 2 else "tvn-2.com", gid, tema_clasificado=tema) for i, t in enumerate(titulos, 1)]
        ids = [x["id_noticia"] for x in filas]
        noticias += filas
        grupos.append(fila_grupo(gid, ids, titulos[0], len(ids)) | {"tema_clasificado": tema, "fecha_inicio": "2026-10-06T08:00:00Z", "fecha_inicio_origen": "publicacion", "fecha_fin": "2026-10-06T10:00:00Z", "fecha_fin_origen": "publicacion"})
        procs += filas_procedencias(gid, ids)
        sims += h.subtema(gid, ids, sub, tema)
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": grupos, "procedencias": procs, "similitud_tema": sims, "fuentes": h.FUENTES, "vinculos": []})
    return ruta


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


def vincular(base: Path, serie: Path) -> dict[str, Any]:
    return contexto.ejecutar(base, base.with_name("reporte.json"), None, serie)


def filas_sbp(base: Path) -> list[dict[str, Any]]:
    con = db.conectar(base, solo_lectura=True)
    try:
        return db.leer_tabla(con, "vinculos", "id_evidencia")
    finally:
        con.close()


def test_el_subtema_de_banca_vincula_el_ultimo_periodo_de_cada_serie(tmp_path: Path) -> None:
    base = base_de_banca(tmp_path / "s.duckdb")
    r = vincular(base, csv_sbp(tmp_path / "sbp_series.csv"))
    filas = [f for f in filas_sbp(base) if f["fuente"] == "sbp"]
    assert [f["id_evidencia"] for f in filas] == ["SBP-MOROSIDAD-SISTEMA-2024-12", "SBP-MOROSOS-SISTEMA-2024-12", "SBP-PROVISIONES-SISTEMA-2024-12"]
    for f in filas:
        assert f["id_grupo"] == G_BANCA and f["rol"] == "sistema" and f["tipo"] == "indirecta" and f["subtema"] == "banca_calificaciones"
        assert f["periodo"] == "2024-12" and f["unidad"] and f["pagina"].startswith("hoja «") and f["informe"] and f["url_fuente"].startswith("https://")
        assert f["valor"] is not None and "no del mes de la noticia" in f["limitacion"] and "opinión oficial de la SBP" in f["limitacion"]
    assert r["sbp"]["grupos_de_banca"] == 1 and r["sbp"]["con_dato"]["n"] == 1 and r["sbp"]["con_dato"]["de"] == 1
    assert r["sbp"]["series_vinculadas"] == ["SBP-MOROSIDAD-SISTEMA", "SBP-MOROSOS-SISTEMA", "SBP-PROVISIONES-SISTEMA"]


def test_otros_subtemas_nunca_se_vinculan_a_la_sbp(tmp_path: Path) -> None:
    base = base_de_banca(tmp_path / "s.duckdb")
    vincular(base, csv_sbp(tmp_path / "sbp_series.csv"))
    assert not [f for f in filas_sbp(base) if f["id_grupo"] == G_OTRO and f["fuente"] == "sbp"]
    for subtema in ("cruceros", "inflacion_precios", "sismos", None):
        assert contexto_sbp.vincular_grupo("GRP-x", subtema, contexto_sbp.cargar_series(csv_sbp(tmp_path / "o.csv")), VINCULOS, FUENTES) is None


def test_un_valor_nulo_no_se_vincula_ni_se_rellena_con_cero(tmp_path: Path) -> None:
    ruta = csv_sbp(tmp_path / "sbp_series.csv")
    texto = ruta.read_text("utf-8").splitlines()
    nulos = [linea if "SBP-MOROSOS-SISTEMA,Saldo moroso del sistema bancario,2024-12," not in linea else ",".join(linea.split(",")[:3] + [""] + linea.split(",")[4:]) for linea in texto]
    ruta.write_text("\n".join(nulos) + "\n", encoding="utf-8")
    datos = contexto_sbp.cargar_series(ruta)
    assert next(d for d in datos if d.id == "SBP-MOROSOS-SISTEMA-2024-12").valor is None
    ultimos = {d.id_serie: d for d in contexto_sbp.ultimos_por_serie(datos)}
    assert ultimos["SBP-MOROSOS-SISTEMA"].periodo == "2024-11"       # el último período CON valor; el vacío no es 0
    assert ultimos["SBP-MOROSIDAD-SISTEMA"].periodo == "2024-12"


def test_sin_ningun_valor_el_grupo_queda_sin_dato_en_periodo() -> None:
    filas = contexto_sbp.vincular_grupo("GRP-x", "banca_calificaciones", [], VINCULOS, FUENTES)
    assert len(filas) == 1 and filas[0]["id_evidencia"] is None and filas[0]["motivo_sin_vinculo"] == "sin_dato_en_periodo" and filas[0]["fuente"] == "sbp"


def test_sin_el_archivo_se_borran_las_filas_viejas_y_el_reporte_lo_dice(tmp_path: Path) -> None:
    base = base_de_banca(tmp_path / "s.duckdb")
    vincular(base, csv_sbp(tmp_path / "sbp_series.csv"))
    r = vincular(base, tmp_path / "no_existe.csv")
    assert r["sbp"]["estado"] == contexto.ESTADO_SIN_SBP
    assert not [f for f in filas_sbp(base) if f["fuente"] == "sbp"]


def test_volver_a_vincular_no_duplica_ni_toca_las_filas_de_otras_fuentes(tmp_path: Path) -> None:
    base = base_de_banca(tmp_path / "s.duckdb")
    serie = csv_sbp(tmp_path / "sbp_series.csv")
    vincular(base, serie)
    primera = filas_sbp(base)
    vincular(base, serie)
    assert filas_sbp(base) == primera
    assert {f["fuente"] for f in primera} == {"indicador", "sbp"}


def test_un_csv_con_columnas_distintas_falla(tmp_path: Path) -> None:
    ruta = tmp_path / "malo.csv"
    ruta.write_text("id_serie,valor\nSBP-X,1\n", encoding="utf-8")
    with pytest.raises(contexto_sbp.ErrorSbp, match="columnas"):
        contexto_sbp.cargar_series(ruta)


def test_la_configuracion_de_vinculos_pide_los_textos_del_periodo() -> None:
    d = VINCULOS.model_dump()
    d["sbp"]["nota_periodo"] = "sin período"
    with pytest.raises(Exception, match="periodo"):
        ConfigVinculos.model_validate(d)


def test_la_ficha_bancaria_muestra_un_dato_sbp_con_periodo_unidad_pagina_y_limitacion(tmp_path: Path, emb) -> None:
    base = base_de_banca(tmp_path / "s.duckdb")
    vincular(base, csv_sbp(tmp_path / "sbp_series.csv"))
    prioridad.ejecutar(base, base.with_name("prioridad.json"), h.CORTE, None, "banca", emb=emb)
    con = db.conectar(base, solo_lectura=True)
    try:
        ficha = construir_ficha(G_BANCA, "banca", con, emb=emb)
    finally:
        con.close()
    assert not [x for x in ficha.respaldado.datos_oficiales if x.citas[0].id.startswith("SBP-")]   # X91: `indirecta` no mide el hecho
    sbp = ficha.respaldado.contexto_oficial
    assert len(sbp) == 3 and all(x.citas[0].id.startswith("SBP-") for x in sbp)
    linea = next(x for x in sbp if x.citas[0].id == "SBP-MOROSOS-SISTEMA-2024-12")
    assert linea.tipo == "hecho" and linea.citas[0].campo == "valor"
    for parte in ("Superintendencia de Bancos de Panamá", "Saldo moroso del sistema bancario", "período 2024-12", "1,012 millones de balboas", "página: hoja «Morosos», celda L6"):
        assert parte in linea.texto, parte
    assert linea.limitacion and "no del mes de la noticia" in linea.limitacion and "análisis es del equipo y no una opinión oficial de la SBP" in linea.limitacion
    proporcion = next(x for x in sbp if x.citas[0].id == "SBP-MOROSIDAD-SISTEMA-2024-12")
    assert "0.1246 proporción" in proporcion.texto      # 4 decimales: con 2 decimales 0.1246 se vería 0.12 y se perdería el detalle
    markdown = a_markdown(ficha)
    cfg = cargar_verificacion().presentacion
    antes, _, despues = markdown.partition(cfg.titulo_contexto_oficial)
    assert despues and "SBP-MOROSOS-SISTEMA-2024-12" in despues and "SBP-" not in antes.split("Datos oficiales")[-1]   # X91: bajo su propio rótulo
    assert "Sin dato oficial que mida el hecho" in antes            # el rótulo «Datos oficiales» conserva su vacío
    assert "SBP-MOROSOS-SISTEMA-2024-12" in markdown and "Limitación: Series agregadas del sistema bancario" in markdown
    assert "período 2024-12" in markdown and "página: hoja «Morosos», celda L6" in markdown


def test_el_contexto_sbp_sigue_citable_rechazable_y_exportable_x91(tmp_path: Path, emb) -> None:
    """X91: aparte de «Datos oficiales», el contexto conserva sus citas en la app, en el rechazo de vínculos y en `fichas.jsonl`."""
    base = base_de_banca(tmp_path / "s.duckdb")
    vincular(base, csv_sbp(tmp_path / "sbp_series.csv"))
    prioridad.ejecutar(base, base.with_name("prioridad.json"), h.CORTE, None, "banca", emb=emb)
    con = db.conectar(base, solo_lectura=True)
    try:
        ficha = construir_ficha(G_BANCA, "banca", con, emb=emb)
    finally:
        con.close()
    ids = {x.citas[0].id for x in ficha.respaldado.contexto_oficial}
    assert len(ids) == 3
    assert ids <= set(vinculos_oficiales_de(ficha)) and ids <= {c.id for c in citas_de_ficha(ficha)}
    registro = a_registro(ficha)
    assert ids <= set(registro["ids_fuente"]) and ids <= {a["citas"][0]["id"] for a in registro["afirmaciones"]}


def test_el_dato_indirecto_de_la_sbp_no_sube_la_evidencia_ni_el_puntaje(tmp_path: Path, emb) -> None:
    """X89: la relación es `indirecta` (contexto): vincular la SBP no cambia ni la evidencia ni el puntaje de nadie, pero la ficha sí muestra el dato."""
    base = base_de_banca(tmp_path / "antes.duckdb")
    prioridad.ejecutar(base, base.with_name("a.json"), h.CORTE, None, "banca", emb=emb)
    antes = _evidencia(base)
    vincular(base, csv_sbp(tmp_path / "sbp_series.csv"))
    prioridad.ejecutar(base, base.with_name("d.json"), h.CORTE, None, "banca", emb=emb)
    despues = _evidencia(base)
    assert antes[G_OTRO] == despues[G_OTRO]                      # lo que no es banca no cambia
    assert antes[G_BANCA] == despues[G_BANCA]                    # contexto: no suma a E ni al estado de evidencia


def _evidencia(base: Path) -> dict[str, tuple]:
    con = db.conectar(base, solo_lectura=True)
    try:
        cur = con.execute("SELECT id_grupo, evidencia, puntaje FROM puntajes ORDER BY 1")
        return {g: (e, p) for g, e, p in cur.fetchall()}
    finally:
        con.close()
