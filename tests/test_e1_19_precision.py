"""E1-19 · Precision@5 contra la selección de un editor: métrica, baseline por fecha, hoja ciega y camino «pendiente»."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from eval import precision_at_5 as pa5
from src import db
from src.configuracion import ConfigPrecision, cargar_precision

CFG = cargar_precision()
CORTE = "2026-10-07T00:41:03Z"
Z = 1.959964


def _grupo(i: int, fecha: str, tema: str = "economia") -> dict[str, Any]:
    return {
        "id_grupo": f"GRP-{i:02d}", "titular_central": f"Titular {i}", "id_noticia_central": f"NOT-{i:02d}", "n_titulares": 1, "n_medios": 1,
        "n_procedencias": 1, "fecha_fin": fecha, "fecha_fin_origen": "publicacion", "tema_clasificado": tema, "ids_noticia": f"NOT-{i:02d}", "estimado": True,
    }


def _puntaje(i: int, posicion: int, p: float) -> dict[str, Any]:
    return {
        "id_grupo": f"GRP-{i:02d}", "posicion": posicion, "version_reglas": "1.3", "fecha_referencia": CORTE, "relevancia": 0.5, "impacto": 0.5,
        "urgencia": 0.5, "novedad": 0.5, "evidencia": 0.5, "puntaje": p, "rango": "alto", "componentes": "{}", "vacios": "[]",
        "recirculada": False, "es_nueva": True,
    }


DETECCION_RECIENTE = "2026-10-30T00:00:00Z"


def _base(ruta: Path, posiciones: dict[int, int], fechas: dict[int, str], sinteticos: tuple[int, ...] = (), sin_publicacion: tuple[int, ...] = ()) -> Path:
    """Diez grupos: ``posiciones[i]`` es la posición del sistema y ``fechas[i]`` su fecha reciente."""
    grupos = [_grupo(i, DETECCION_RECIENTE if i in sin_publicacion else fechas[i]) | ({"fecha_fin_origen": "deteccion"} if i in sin_publicacion else {}) for i in range(1, 11)]
    puntajes = [_puntaje(i, posiciones[i], 100.0 - posiciones[i]) for i in range(1, 11)]
    noticias = [
        {"id_noticia": f"NOT-{i:02d}", "titulo": f"Titular {i}", "url": f"https://x.example/{i}", "url_canonica": f"https://x.example/{i}", "medio": "m", "tipo_firma": "sin_firma", "id_grupo": f"GRP-{i:02d}", "origen": "sintetico" if i in sinteticos else "rss",
         "fecha_publicacion": None if i in sin_publicacion else fechas[i], "fecha_deteccion": DETECCION_RECIENTE}
        for i in range(1, 11)
    ]
    db.guardar_todo(ruta, {"grupos": grupos, "puntajes": puntajes, "noticias": noticias})
    return ruta


# Sistema: 1,2,3,4,5 arriba. Fechas: 10,9,8,7,6 las más recientes (el baseline elige lo contrario del sistema).
POS = {i: i for i in range(1, 11)}
FECHAS = {i: f"2026-10-{i:02d}T12:00:00Z" for i in range(1, 11)}


@pytest.fixture
def con(tmp_path: Path):
    ruta = _base(tmp_path / "s.duckdb", POS, FECHAS)
    c = db.conectar(ruta, solo_lectura=True)
    yield c
    c.close()


def test_config_hoja_sin_pistas_del_ranking() -> None:
    datos = CFG.model_dump()
    datos["hoja_ciega"]["columnas"] = ["corte", "id_grupo", "puntaje", "seleccion"]
    with pytest.raises(ValueError, match="revelan el ranking"):
        ConfigPrecision.model_validate(datos)


def test_config_prohibe_claves_desconocidas() -> None:
    datos = CFG.model_dump()
    datos["extra"] = 1
    with pytest.raises(ValueError):
        ConfigPrecision.model_validate(datos)


def test_top_sistema_sigue_la_posicion(con) -> None:
    cands = pa5.candidatos(con)
    assert [c.id_grupo for c in pa5.top_sistema(cands, 5)] == [f"GRP-{i:02d}" for i in range(1, 6)]


def test_baseline_ordena_solo_por_fecha_reciente(con) -> None:
    cands = pa5.candidatos(con)
    assert [c.id_grupo for c in pa5.top_baseline(cands, 5)] == [f"GRP-{i:02d}" for i in (10, 9, 8, 7, 6)]


def test_baseline_desempata_por_id_y_no_por_puntaje(tmp_path: Path) -> None:
    mismas = {i: "2026-10-05T00:00:00Z" for i in range(1, 11)}
    ruta = _base(tmp_path / "e.duckdb", {i: 11 - i for i in range(1, 11)}, mismas)
    c = db.conectar(ruta, solo_lectura=True)
    try:
        assert [x.id_grupo for x in pa5.top_baseline(pa5.candidatos(c), 5)] == [f"GRP-{i:02d}" for i in range(1, 6)]
    finally:
        c.close()


def test_los_sinteticos_no_son_candidatos(tmp_path: Path) -> None:
    ruta = _base(tmp_path / "y.duckdb", POS, FECHAS, sinteticos=(1,))
    c = db.conectar(ruta, solo_lectura=True)
    try:
        assert "GRP-01" not in [x.id_grupo for x in pa5.candidatos(c)]
    finally:
        c.close()


@pytest.mark.parametrize(("elegidos", "aciertos"), [((1, 2, 3, 4, 5), 5), ((6, 7, 8, 9, 10), 0), ((1, 2, 3, 9, 10), 3)])
def test_precision_cuenta_coincidencias(elegidos: tuple[int, ...], aciertos: int) -> None:
    top = [f"GRP-{i:02d}" for i in range(1, 6)]
    assert pa5.aciertos(top, {f"GRP-{i:02d}" for i in elegidos}) == aciertos


def test_evaluar_reporta_sistema_y_baseline_con_n_e_ic(con) -> None:
    cands = pa5.candidatos(con)
    elegidos = {f"GRP-{i:02d}" for i in (1, 2, 3, 9, 10)}
    r = pa5.evaluar_corte(cands, elegidos, CORTE, CFG.k, Z)
    assert r["sistema"]["k"] == 3 and r["sistema"]["n"] == 5
    assert r["baseline"]["k"] == 2 and r["baseline"]["n"] == 5
    assert r["sistema"]["proporcion"] == pytest.approx(0.6)
    lo, hi = r["sistema"]["ic95"]
    assert 0 <= lo < 0.6 < hi <= 1
    assert r["sistema"]["ids_fallidos"] == ["GRP-04", "GRP-05"]


def test_resumen_un_corte_es_exploratorio_n1() -> None:
    cortes = [{"corte": CORTE, "sistema": {"k": 3, "n": 5}, "baseline": {"k": 2, "n": 5}}]
    r = pa5.resumir(cortes, CFG, Z)
    assert r["pruebas"] == 1 and r["exploratoria"] is True
    assert r["sistema"]["n"] == 5


def test_resumen_tres_cortes_con_especialista_deja_de_ser_exploratorio_y_junta_n() -> None:
    cortes = [{"corte": f"c{i}", "sistema": {"k": 3, "n": 5}, "baseline": {"k": 1, "n": 5}} for i in range(3)]
    r = pa5.resumir(cortes, CFG, Z, especialista=True)
    assert r["pruebas"] == 3 and r["exploratoria"] is False
    assert (r["sistema"]["k"], r["sistema"]["n"]) == (9, 15)
    assert (r["baseline"]["k"], r["baseline"]["n"]) == (3, 15)


# ------------------------------------------------------------------ hoja ciega


def test_hoja_no_filtra_columnas_del_ranking(con) -> None:
    filas = pa5.hoja_ciega(pa5.candidatos(con), CORTE, CFG)
    assert filas and set(filas[0]) == set(CFG.hoja_ciega.columnas)
    for prohibida in ("puntaje", "posicion", "rango", "relevancia", "impacto", "urgencia", "novedad", "evidencia", "estado", "accion"):
        assert prohibida not in filas[0]
    assert all(f["seleccion"] == "" for f in filas)


def test_orden_de_la_hoja_no_depende_de_p_ni_de_la_fecha(tmp_path: Path) -> None:
    a = _base(tmp_path / "a.duckdb", POS, FECHAS)
    b = _base(tmp_path / "b.duckdb", {i: 11 - i for i in range(1, 11)}, {i: f"2026-09-{i:02d}T00:00:00Z" for i in range(1, 11)})
    ordenes = []
    for ruta in (a, b):
        c = db.conectar(ruta, solo_lectura=True)
        try:
            ordenes.append([f["id_grupo"] for f in pa5.hoja_ciega(pa5.candidatos(c), CORTE, CFG)])
        finally:
            c.close()
    assert ordenes[0] == ordenes[1]
    assert ordenes[0] != sorted(ordenes[0]), "el orden no debe ser alfabético por ID (insinuaría la antigüedad del grupo)"
    # Tampoco es el orden del sistema ni el del baseline.
    assert ordenes[0][:5] != [f"GRP-{i:02d}" for i in range(1, 6)]
    assert ordenes[0][:5] != [f"GRP-{i:02d}" for i in (10, 9, 8, 7, 6)]


def test_hoja_es_reproducible(con) -> None:
    c = pa5.candidatos(con)
    assert pa5.hoja_ciega(c, CORTE, CFG) == pa5.hoja_ciega(list(reversed(c)), CORTE, CFG)


def test_hoja_escrita_en_csv_solo_con_las_columnas_de_la_config(con, tmp_path: Path) -> None:
    ruta = tmp_path / "hoja.csv"
    pa5.escribir_hoja(ruta, pa5.hoja_ciega(pa5.candidatos(con), CORTE, CFG), CFG)
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        assert lector.fieldnames == CFG.hoja_ciega.columnas
        assert len(list(lector)) == 10


# ------------------------------------------------------------------ selección y camino «pendiente»


def _seleccion(ruta: Path, elegidos: list[str], todos: int = 10, corte: str = CORTE) -> None:
    columnas = CFG.hoja_ciega.columnas
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        for gid in sorted({f"GRP-{i:02d}" for i in range(1, todos + 1)} | set(elegidos)):
            w.writerow({"corte": corte, "id_grupo": gid, "tema": "", "titular": "", "fecha_reciente": "", "seleccion": CFG.hoja_ciega.marca if gid in elegidos else ""})


def test_archivo_inexistente_es_error_explicito(tmp_path: Path) -> None:
    with pytest.raises(pa5.SeleccionInvalida, match="no_existe.csv"):
        pa5.leer_seleccion(tmp_path / "no_existe.csv", CFG)


def test_hoja_sin_marcas_esta_pendiente(tmp_path: Path) -> None:
    ruta = tmp_path / "vacia.csv"
    _seleccion(ruta, [])
    assert pa5.leer_seleccion(ruta, CFG) is None


def test_leer_seleccion_agrupa_por_corte(tmp_path: Path) -> None:
    ruta = tmp_path / "s.csv"
    _seleccion(ruta, [f"GRP-{i:02d}" for i in (1, 2, 3, 9, 10)])
    assert pa5.leer_seleccion(ruta, CFG) == {CORTE: {f"GRP-{i:02d}" for i in (1, 2, 3, 9, 10)}}


def test_seleccion_con_menos_de_k_se_rechaza(tmp_path: Path, con) -> None:
    ruta = tmp_path / "s.csv"
    _seleccion(ruta, ["GRP-01", "GRP-02"])
    with pytest.raises(pa5.SeleccionInvalida, match="5"):
        pa5.validar_seleccion(pa5.leer_seleccion(ruta, CFG), pa5.candidatos(con), CFG.k)


def test_seleccion_con_id_desconocido_se_rechaza(tmp_path: Path, con) -> None:
    ruta = tmp_path / "s.csv"
    _seleccion(ruta, ["GRP-01", "GRP-02", "GRP-03", "GRP-04", "GRP-99"])
    with pytest.raises(pa5.SeleccionInvalida, match="GRP-99"):
        pa5.validar_seleccion(pa5.leer_seleccion(ruta, CFG), pa5.candidatos(con), CFG.k)


def test_cli_hoja_sin_marcas_es_pendiente_y_sale_limpio(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    vacia = tmp_path / "vacia.csv"
    _seleccion(vacia, [])
    salida = tmp_path / "out.json"
    codigo = pa5.principal(["--seleccion", str(vacia), "--base", str(base), "--salida", str(salida)])
    texto = capsys.readouterr().out
    assert codigo == 0
    assert CFG.textos.pendiente in texto
    assert "P@5" not in texto and "%" not in texto
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["estado"] == "pendiente" and "sistema" not in datos


def test_cli_sin_el_flag_y_sin_archivo_por_defecto_es_pendiente(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    monkeypatch.setattr(pa5, "RAIZ", tmp_path)
    codigo = pa5.principal(["--base", str(base), "--salida", str(tmp_path / "out.json")])
    assert codigo == 0 and CFG.textos.pendiente in capsys.readouterr().out


def test_cli_seleccion_inexistente_falla_y_no_pisa_una_salida_medida(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    salida = tmp_path / "out.json"
    salida.write_text('{"estado": "medido", "marca": 1}', encoding="utf-8")
    codigo = pa5.principal(["--seleccion", str(tmp_path / "no_existe.csv"), "--base", str(base), "--salida", str(salida)])
    assert codigo != 0
    assert "no_existe.csv" in capsys.readouterr().err
    assert json.loads(salida.read_text(encoding="utf-8")) == {"estado": "medido", "marca": 1}


def test_cli_una_seleccion_faltante_entre_varias_es_error(tmp_path: Path) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    buena = tmp_path / "sel.csv"
    _seleccion(buena, [f"GRP-{i:02d}" for i in range(1, 6)])
    salida = tmp_path / "out.json"
    codigo = pa5.principal(["--seleccion", str(buena), "--seleccion", str(tmp_path / "falta.csv"), "--base", str(base), "--salida", str(salida)])
    assert codigo != 0 and not salida.exists()


def test_pendiente_no_pisa_una_salida_medida(tmp_path: Path) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    vacia = tmp_path / "vacia.csv"
    _seleccion(vacia, [])
    salida = tmp_path / "out.json"
    salida.write_text('{"estado": "medido"}', encoding="utf-8")
    assert pa5.principal(["--seleccion", str(vacia), "--base", str(base), "--salida", str(salida)]) == 0
    assert json.loads(salida.read_text(encoding="utf-8")) == {"estado": "medido"}


def test_cli_con_seleccion_imprime_sistema_y_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    seleccion = tmp_path / "sel.csv"
    _seleccion(seleccion, [f"GRP-{i:02d}" for i in (1, 2, 3, 9, 10)])
    salida = tmp_path / "out.json"
    codigo = pa5.principal(["--seleccion", str(seleccion), "--base", str(base), "--salida", str(salida)])
    texto = capsys.readouterr().out
    assert codigo == 0
    assert "sistema" in texto.lower() and "baseline" in texto.lower() and "ranking por fecha" in texto
    assert "n = 5" in texto and "IC 95" in texto and "exploratoria" in texto
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["estado"] == "medido" and datos["pruebas"] == 1 and datos["exploratoria"] is True


def test_cli_hoja_escribe_la_hoja_y_no_la_seleccion(tmp_path: Path) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    hoja = tmp_path / "hoja.csv"
    codigo = pa5.principal(["--hoja", "--base", str(base), "--hoja-salida", str(hoja), "--corte", CORTE])
    assert codigo == 0 and hoja.exists()
    assert not (tmp_path / "seleccion_editor.csv").exists()


def test_yaml_registrado_en_validar_todo() -> None:
    from src.configuracion import CARGADORES

    assert "precision" in CARGADORES


# ------------------------------------------------------------------ X34: el baseline usa solo la fecha de publicación


def test_x34_grupo_solo_gdelt_no_entra_al_top_del_baseline(tmp_path: Path) -> None:
    """GRP-01 no tiene fecha de publicación y su detección es la más reciente: debe ir al final, no al tope."""
    ruta = _base(tmp_path / "g.duckdb", POS, FECHAS, sin_publicacion=(1,))
    c = db.conectar(ruta, solo_lectura=True)
    try:
        cands = pa5.candidatos(c)
        top = [x.id_grupo for x in pa5.top_baseline(cands, 5)]
        assert "GRP-01" not in top
        assert top == [f"GRP-{i:02d}" for i in (10, 9, 8, 7, 6)]
        assert pa5.top_baseline(cands, 10)[-1].id_grupo == "GRP-01"
        assert next(x for x in cands if x.id_grupo == "GRP-01").fecha_reciente == ""
    finally:
        c.close()


def test_x34_sin_fecha_de_publicacion_desempata_por_id_al_final(tmp_path: Path) -> None:
    ruta = _base(tmp_path / "g.duckdb", POS, FECHAS, sin_publicacion=(3, 2))
    c = db.conectar(ruta, solo_lectura=True)
    try:
        ids = [x.id_grupo for x in pa5.top_baseline(pa5.candidatos(c), 10)]
        assert ids[-2:] == ["GRP-02", "GRP-03"]
    finally:
        c.close()


def test_x34_la_fecha_es_el_maximo_de_las_publicaciones_del_grupo(tmp_path: Path) -> None:
    ruta = _base(tmp_path / "g.duckdb", POS, FECHAS)
    con_w = db.conectar(ruta)
    con_w.execute("INSERT INTO noticias (id_noticia, titulo, url, url_canonica, medio, tipo_firma, id_grupo, origen, fecha_publicacion) "
                  "VALUES ('NOT-x', 't', 'u', 'u', 'm', 's', 'GRP-01', 'rss', '2026-10-25T00:00:00Z')")
    con_w.close()
    c = db.conectar(ruta, solo_lectura=True)
    try:
        assert next(x for x in pa5.candidatos(c) if x.id_grupo == "GRP-01").fecha_reciente == "2026-10-25T00:00:00Z"
    finally:
        c.close()


def test_x34_el_reporte_cuenta_los_grupos_sin_fecha_de_publicacion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS, sin_publicacion=(1, 2))
    seleccion = tmp_path / "sel.csv"
    _seleccion(seleccion, [f"GRP-{i:02d}" for i in (1, 2, 3, 9, 10)])
    salida = tmp_path / "out.json"
    assert pa5.principal(["--seleccion", str(seleccion), "--base", str(base), "--salida", str(salida)]) == 0
    assert "2 grupos sin fecha de publicación" in capsys.readouterr().out
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["cortes"][0]["baseline_sin_fecha_publicacion"] == 2


def test_x34_la_hoja_muestra_solo_la_fecha_de_publicacion(tmp_path: Path) -> None:
    ruta = _base(tmp_path / "g.duckdb", POS, FECHAS, sin_publicacion=(1,))
    c = db.conectar(ruta, solo_lectura=True)
    try:
        filas = {f["id_grupo"]: f for f in pa5.hoja_ciega(pa5.candidatos(c), CORTE, CFG)}
    finally:
        c.close()
    assert filas["GRP-01"]["fecha_reciente"] == ""
    assert DETECCION_RECIENTE not in {f["fecha_reciente"] for f in filas.values()}
    assert filas["GRP-02"]["fecha_reciente"] == FECHAS[2]


# ------------------------------------------------------------------ X36: especialista declarado


def test_x36_sin_especialista_declarado_siempre_es_exploratoria() -> None:
    cortes = [{"corte": f"c{i}", "sistema": {"k": 3, "n": 5}, "baseline": {"k": 1, "n": 5}} for i in range(3)]
    r = pa5.resumir(cortes, CFG, Z)
    assert r["exploratoria"] is True and r["especialista"] is False


def test_x36_con_especialista_y_cortes_suficientes_no_es_exploratoria() -> None:
    cortes = [{"corte": f"c{i}", "sistema": {"k": 3, "n": 5}, "baseline": {"k": 1, "n": 5}} for i in range(3)]
    r = pa5.resumir(cortes, CFG, Z, especialista=True)
    assert r["exploratoria"] is False and r["especialista"] is True


def test_x36_con_especialista_pero_un_corte_sigue_exploratoria() -> None:
    cortes = [{"corte": "c", "sistema": {"k": 3, "n": 5}, "baseline": {"k": 1, "n": 5}}]
    assert pa5.resumir(cortes, CFG, Z, especialista=True)["exploratoria"] is True


def test_x36_el_cli_declara_al_especialista_y_lo_reporta(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    seleccion = tmp_path / "sel.csv"
    _seleccion(seleccion, [f"GRP-{i:02d}" for i in (1, 2, 3, 9, 10)])
    salida = tmp_path / "out.json"
    pa5.principal(["--seleccion", str(seleccion), "--base", str(base), "--salida", str(salida)])
    assert json.loads(salida.read_text(encoding="utf-8"))["especialista"] is False
    assert CFG.textos.sin_especialista in capsys.readouterr().out
    pa5.principal(["--seleccion", str(seleccion), "--base", str(base), "--salida", str(salida), "--especialista"])
    assert json.loads(salida.read_text(encoding="utf-8"))["especialista"] is True


# ------------------------------------------------------------------ menores


def test_id_duplicado_en_un_corte_se_nombra(tmp_path: Path) -> None:
    ruta = tmp_path / "dup.csv"
    _seleccion(ruta, [f"GRP-{i:02d}" for i in range(1, 6)])
    with ruta.open("a", encoding="utf-8", newline="") as f:
        f.write(f"{CORTE},GRP-01,,,,x\n")
    with pytest.raises(pa5.SeleccionInvalida, match="GRP-01"):
        pa5.leer_seleccion(ruta, CFG)


def test_dos_hojas_para_el_mismo_corte_se_rechazan(tmp_path: Path) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    _seleccion(a, [f"GRP-{i:02d}" for i in range(1, 6)])
    _seleccion(b, [f"GRP-{i:02d}" for i in range(6, 11)])
    salida = tmp_path / "out.json"
    codigo = pa5.principal(["--seleccion", str(a), "--seleccion", str(b), "--base", str(base), "--salida", str(salida)])
    assert codigo != 0 and not salida.exists()
