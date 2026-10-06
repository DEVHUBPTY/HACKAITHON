"""T01 · Fechas inválidas y nulos (E1-02): la carga valida en modo lazy y no se detiene."""

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from src import carga
from scripts import conversion, validar_snapshot
from src.configuracion import cargar_carga, cargar_contrato

FIXTURES = Path(__file__).parent / "fixtures"
RAIZ = Path(__file__).resolve().parent.parent
CONFIG = cargar_carga()
CABECERA_IND = "pais_iso3,indicador_id,anio,valor,unidad,fuente_url,fecha_extraccion,licencia\n"
SUFIJO_IND = ",% anual,https://x.example/a,2025-09-30T12:00:00Z,sintetico\n"


@pytest.fixture(scope="module")
def noticias() -> carga.ResultadoArchivo:
    return carga.cargar_noticias(FIXTURES / "t01_noticias_invalidas.csv", CONFIG)


@pytest.fixture(scope="module")
def indicadores() -> carga.ResultadoArchivo:
    return carga.cargar_indicadores(FIXTURES / "t01_indicadores_nulos.csv", CONFIG)


def _esperados() -> pd.DataFrame:
    df = pd.read_csv(FIXTURES / "t01_noticias_invalidas.csv", dtype=str, keep_default_na=False)
    df["fila"] = range(1, len(df) + 1)
    return df


def test_cada_fila_con_error_lleva_exactamente_el_error_esperado(noticias: carga.ResultadoArchivo) -> None:
    por_fila: dict[int, set[str]] = {}
    for e in noticias.errores:
        assert e.fila is not None
        por_fila.setdefault(e.fila, set()).add(e.tipo_error)
    esperados = _esperados()
    con_error = esperados[esperados["error_esperado"] != ""]
    assert len(con_error) == 10
    for _, f in con_error.iterrows():
        assert por_fila.get(f["fila"]) == {f["error_esperado"]}, f"{f['id_noticia'] or '(sin id)'} fila {f['fila']}"


def test_filas_validas_pasan_y_no_se_marcan(noticias: carga.ResultadoArchivo) -> None:
    esperados = _esperados()
    sin_error = esperados[esperados["error_esperado"] == ""]
    marcadas = {e.fila for e in noticias.errores}
    assert not marcadas & set(sin_error["fila"])
    assert set(noticias.validas["id_noticia"]) == set(sin_error["id_noticia"])
    assert len(noticias.validas) == 6 and noticias.rechazadas == 10


def test_carga_parcial_sin_excepcion_y_primera_aparicion_del_id_se_conserva(noticias: carga.ResultadoArchivo) -> None:
    assert noticias.leidas == 16
    assert (noticias.validas["id_noticia"] == "SYN-T01-002").sum() == 1
    conservada = noticias.validas.loc[noticias.validas["id_noticia"] == "SYN-T01-002", "fecha_publicacion"].item()
    assert conservada == "2025-08-31T09:15:00Z"


def test_cada_rechazo_lleva_motivo(noticias: carga.ResultadoArchivo) -> None:
    assert all(e.motivo and e.tipo_error for e in noticias.errores)
    assert noticias.errores_por_tipo() == {
        "fecha_invalida": 3,
        "url_mal_formada": 3,
        "obligatorio_vacio": 3,
        "id_duplicado": 1,
    }


def test_nulos_de_indicadores_se_conservan_y_nunca_son_cero(indicadores: carga.ResultadoArchivo) -> None:
    crudo = pd.read_csv(FIXTURES / "t01_indicadores_nulos.csv")
    assert indicadores.errores == []
    assert len(indicadores.validas) == len(crudo) == 12
    assert indicadores.nulos_leidas["valor"] == int(crudo["valor"].isna().sum()) == 6
    assert indicadores.nulos_validas["valor"] == 6  # mismo conteo antes y después
    assert indicadores.validas["valor"].isna().sum() == 6
    assert not (indicadores.validas["valor"] == 0).any()


def test_valor_no_numerico_se_rechaza_pero_nulo_no(tmp_path: Path) -> None:
    ruta = tmp_path / "ind.csv"
    ruta.write_text(
        CABECERA_IND + "PAN,A,2023,abc" + SUFIJO_IND + "PAN,A,2024," + SUFIJO_IND + "PAN,A,2022,1.5" + SUFIJO_IND,
        "utf-8",
    )
    r = carga.cargar_indicadores(ruta, CONFIG)
    assert [e.tipo_error for e in r.errores] == ["valor_invalido"]
    assert len(r.validas) == 2 and r.nulos_validas["valor"] == 1


def test_clave_repetida_de_indicador_es_id_duplicado(tmp_path: Path) -> None:
    ruta = tmp_path / "ind.csv"
    ruta.write_text(CABECERA_IND + ("PAN,A,2023,1" + SUFIJO_IND) * 2, "utf-8")
    r = carga.cargar_indicadores(ruta, CONFIG)
    assert r.errores_por_tipo() == {"id_duplicado": 1} and len(r.validas) == 1


def test_columna_critica_ausente_rechaza_todo_sin_excepcion(tmp_path: Path) -> None:
    ruta = tmp_path / "n.csv"
    ruta.write_text("id_noticia,titulo,url\nSYN-X-1,hola,https://a.example/x\n", "utf-8")
    r = carga.cargar_noticias(ruta, CONFIG)
    assert len(r.validas) == 0 and "columna_faltante" in r.errores_por_tipo()


def test_linea_mal_formada_se_registra_y_la_carga_sigue(tmp_path: Path) -> None:
    ruta = tmp_path / "n.csv"
    buenas = (FIXTURES / "t01_noticias_invalidas.csv").read_text("utf-8").splitlines()[:3]
    ruta.write_text("\n".join([*buenas, "SYN-X,a,b,c,d,e,f,g,h,i,j,k,l,m"]) + "\n", "utf-8")
    r = carga.cargar_noticias(ruta, CONFIG)
    assert len(r.validas) == 2
    assert "estructura_invalida" in r.errores_por_tipo()
    assert len(r.lineas_mal_formadas) == 1


def test_parser_iso_y_sin_parsers_de_otras_fuentes() -> None:
    """La carga solo lee ISO de processed/; el parseo de GDELT/RSS/USGS vive en scripts/conversion.py (M2)."""
    assert carga.parsear_fecha_iso("2025-02-28T08:00:00Z", CONFIG) is not None
    assert carga.parsear_fecha_iso("2025-02-30T08:00:00Z", CONFIG) is None
    assert carga.parsear_fecha_iso("2025-02-28", CONFIG) is None
    for muerto in ("parsear_fecha_gdelt", "parsear_fecha_rfc822", "parsear_fecha_usgs"):
        assert not hasattr(carga, muerto)
    assert not hasattr(carga, "_CONFIG_ACTUAL")


def test_reporte_incluye_distribucion_por_medio_e_idioma(noticias: carga.ResultadoArchivo) -> None:
    rep = carga.construir_reporte({"t01": noticias}, CONFIG)
    dist = rep["distribucion_noticias_validas"]
    assert sum(dist["por_medio"].values()) == sum(dist["por_idioma"].values()) == 6
    assert dist["por_idioma"]["es"] == 5 and dist["por_idioma"]["en"] == 1
    assert rep["archivos"]["t01"]["validas"] == 6 and rep["archivos"]["t01"]["rechazadas"] == 10
    assert rep["archivos"]["t01"]["nulos_por_campo"]["leidas"]["id_noticia"] == 1


def test_eventos_y_fuentes_con_pydantic(tmp_path: Path) -> None:
    props = {
        "id": "SIS-a", "magnitude": 4.1, "time": "2024-01-07T01:02:08Z", "longitude": -80.0,
        "latitude": 8.0, "url": "https://u.example/a", "place": None,
    }
    malos = [
        {**props, "id": "SIS-b", "time": "2024-13-01T00:00:00Z"},
        {**props, "id": "SIS-c", "latitude": 95},
        {**props, "id": "SIS-a"},
        {k: v for k, v in props.items() if k != "magnitude"} | {"id": "SIS-d"},
    ]
    geo = {"features": [{"properties": p} for p in [props, *malos]]}
    ruta = tmp_path / "e.geojson"
    ruta.write_text(json.dumps(geo), "utf-8")
    r = carga.cargar_eventos(ruta, CONFIG)
    assert len(r.validas) == 1
    assert r.errores_por_tipo() == {
        "fecha_invalida": 1, "valor_invalido": 1, "id_duplicado": 1, "obligatorio_vacio": 1,
    }
    assert r.nulos_validas["place"] == 1  # el nulo opcional se conserva

    fuentes = tmp_path / "f.json"
    fuentes.write_text(
        json.dumps([
            {"dominio": "a.com", "nombre_legible": "A", "pais": None, "origen": "GDELT", "condiciones": "x"},
            {"dominio": "b.com", "nombre_legible": "", "origen": "GDELT"},
        ]),
        "utf-8",
    )
    rf = carga.cargar_fuentes(fuentes, CONFIG)
    assert len(rf.validas) == 1
    assert rf.errores_por_tipo() == {"obligatorio_vacio": 2}  # nombre_legible "" y condiciones ausente
    assert rf.rechazadas == 1  # una fila con dos errores se cuenta una vez


def test_snapshot_real_carga_sin_errores_y_conserva_conteos() -> None:
    procesados = RAIZ / "data" / "processed"
    manifest = json.loads((RAIZ / "data" / "manifest.json").read_text("utf-8"))["cantidad_por_archivo"]
    res = carga.cargar_todo(procesados, CONFIG)
    assert sum(len(r.errores) for r in res.values()) == 0
    for nombre in ("noticias.csv", "indicadores.csv", "eventos.geojson", "fuentes.json"):
        assert res[nombre].leidas == manifest[nombre] == len(res[nombre].validas)
    crudo = pd.read_csv(procesados / "indicadores.csv")
    assert res["indicadores.csv"].nulos_validas["valor"] == int(crudo["valor"].isna().sum())


def test_cli_escribe_errores_y_reporte(tmp_path: Path) -> None:
    assert carga.main(["--procesados", str(RAIZ / "data" / "processed"), "--salida", str(tmp_path), "--validos", str(tmp_path / "v")]) == 0
    reporte = json.loads((tmp_path / "reporte_calidad.json").read_text("utf-8"))
    assert reporte["totales"]["rechazadas"] == 0
    assert (tmp_path / "errores.csv").read_text("utf-8").startswith("archivo,fila,id,campo,tipo_error,motivo,valor")


# ------------------------------------------------------------------ X11 · revisión independiente de E1-02


def _eventos_geojson(tmp_path: Path, props: list[dict]) -> Path:
    ruta = tmp_path / "e.geojson"
    ruta.write_text(json.dumps({"features": [{"properties": p} for p in props]}), "utf-8")
    return ruta


BASE_EVENTO = {
    "id": "SIS-a", "magnitude": 4.1, "time": "2024-01-07T01:02:08Z", "longitude": -80.0,
    "latitude": 8.0, "url": "https://u.example/a",
}


@pytest.mark.parametrize("campo", ["id", "time", "url"])
@pytest.mark.parametrize("vacio", ["", "   "])
def test_a2_evento_con_critico_vacio_o_en_blanco_se_rechaza(tmp_path: Path, campo: str, vacio: str) -> None:
    r = carga.cargar_eventos(_eventos_geojson(tmp_path, [BASE_EVENTO, {**BASE_EVENTO, "id": "SIS-b", campo: vacio}]), CONFIG)
    assert len(r.validas) == 1 and r.rechazadas == 1
    assert {e.campo for e in r.errores} == {campo}


@pytest.mark.parametrize("campo", ["dominio", "nombre_legible", "origen", "condiciones"])
@pytest.mark.parametrize("vacio", ["", "  \t"])
def test_a2_fuente_con_critico_vacio_o_en_blanco_se_rechaza(tmp_path: Path, campo: str, vacio: str) -> None:
    ok = {"dominio": "a.com", "nombre_legible": "A", "pais": None, "origen": "GDELT", "condiciones": "x"}
    ruta = tmp_path / "f.json"
    ruta.write_text(json.dumps([ok, {**ok, "dominio": "b.com", campo: vacio}]), "utf-8")
    r = carga.cargar_fuentes(ruta, CONFIG)
    assert len(r.validas) == 1 and r.errores_por_tipo() == {"obligatorio_vacio": 1}


def test_a2_opcional_vacio_en_fuente_solo_es_nulo(tmp_path: Path) -> None:
    ruta = tmp_path / "f.json"
    ruta.write_text(json.dumps([{"dominio": "a.com", "nombre_legible": "A", "pais": "", "origen": "G", "condiciones": "x"}]), "utf-8")
    assert len(carga.cargar_fuentes(ruta, CONFIG).validas) == 1


def test_a3_columna_critica_ausente_cuenta_dos_leidas_cero_validas_dos_rechazadas_un_error_de_archivo(tmp_path: Path) -> None:
    ruta = tmp_path / "n.csv"
    ruta.write_text("id_noticia,titulo,url\nSYN-X-1,hola,https://a.example/x\nSYN-X-2,chao,https://a.example/y\n", "utf-8")
    r = carga.cargar_noticias(ruta, CONFIG)
    assert (r.leidas, len(r.validas), r.rechazadas) == (2, 0, 2)
    assert len(r.errores_de_archivo) == 1 and r.errores_de_archivo[0].tipo_error == "columna_faltante"
    assert r.lineas_mal_formadas == []
    rep = carga.construir_reporte({"n": r}, CONFIG)["archivos"]["n"]
    assert rep["leidas"] == 2 and rep["validas"] == 0 and rep["rechazadas"] == 2
    assert len(rep["errores_de_archivo"]) == 1 and rep["lineas_mal_formadas"] == 0


def test_a3_linea_mal_formada_cuenta_tres_leidas_dos_validas_una_rechazada(tmp_path: Path) -> None:
    ruta = tmp_path / "n.csv"
    buenas = (FIXTURES / "t01_noticias_invalidas.csv").read_text("utf-8").splitlines()[:3]
    ruta.write_text("\n".join([*buenas, "SYN-X,a,b,c,d,e,f,g,h,i,j,k,l,m"]) + "\n", "utf-8")
    r = carga.cargar_noticias(ruta, CONFIG)
    assert (r.leidas, len(r.validas), r.rechazadas) == (3, 2, 1)
    assert len(r.lineas_mal_formadas) == 1 and r.errores_de_archivo == []
    rep = carga.construir_reporte({"n": r}, CONFIG)["archivos"]["n"]
    assert (rep["leidas"], rep["validas"], rep["rechazadas"], rep["lineas_mal_formadas"]) == (3, 2, 1, 1)


def test_a3_invariante_validas_mas_rechazadas_igual_leidas(noticias: carga.ResultadoArchivo, indicadores: carga.ResultadoArchivo, tmp_path: Path) -> None:
    props = [BASE_EVENTO, {**BASE_EVENTO, "id": "SIS-b", "time": "mal", "url": "x", "latitude": 99}]
    eventos = carga.cargar_eventos(_eventos_geojson(tmp_path, props), CONFIG)
    assert len(eventos.errores) > eventos.rechazadas  # varios errores, una fila
    res = carga.cargar_todo(RAIZ / "data" / "processed", CONFIG)
    for r in [noticias, indicadores, eventos, *res.values()]:
        assert len(r.validas) + r.rechazadas == r.leidas, r.archivo
    rep = carga.construir_reporte({"a": noticias, "e": eventos}, CONFIG)
    for a in rep["archivos"].values():
        assert a["validas"] + a["rechazadas"] == a["leidas"]
    t = rep["totales"]
    assert t["validas"] + t["rechazadas"] == t["leidas"]


def test_low_duplicado_conserva_la_primera_aparicion_valida(tmp_path: Path) -> None:
    ruta = tmp_path / "ind.csv"
    ruta.write_text(CABECERA_IND + "PAN,A,2023,abc" + SUFIJO_IND + "PAN,A,2023,1" + SUFIJO_IND + "PAN,A,2023,2" + SUFIJO_IND, "utf-8")
    r = carga.cargar_indicadores(ruta, CONFIG)
    assert len(r.validas) == 1 and r.validas["valor"].item() == 1.0  # la 2.ª fila es la primera válida
    assert {(e.fila, e.tipo_error) for e in r.errores} == {(1, "valor_invalido"), (3, "id_duplicado")}
    assert len(r.validas) + r.rechazadas == r.leidas


def test_low_duplicado_de_noticia_conserva_la_primera_valida(tmp_path: Path) -> None:
    lineas = (FIXTURES / "t01_noticias_invalidas.csv").read_text("utf-8").splitlines()
    cab = lineas[0].split(",")
    buena = next(l for l in lineas[1:] if l.startswith("SYN-T01-001"))
    mala = buena.replace("https://", "ftp://", 1)  # misma id, URL inválida
    ruta = tmp_path / "n.csv"
    ruta.write_text("\n".join([lineas[0], mala, buena, buena]) + "\n", "utf-8")
    r = carga.cargar_noticias(ruta, CONFIG)
    assert cab and len(r.validas) == 1
    assert {(e.fila, e.tipo_error) for e in r.errores} == {(1, "url_mal_formada"), (3, "id_duplicado")}


def test_low_duplicado_pydantic_conserva_la_primera_valida(tmp_path: Path) -> None:
    malo = {**BASE_EVENTO, "time": "mal"}
    r = carga.cargar_eventos(_eventos_geojson(tmp_path, [malo, BASE_EVENTO, BASE_EVENTO]), CONFIG)
    assert len(r.validas) == 1
    assert {(e.fila, e.tipo_error) for e in r.errores} == {(1, "fecha_invalida"), (3, "id_duplicado")}


def test_low_critico_fuera_del_yaml_de_eventos_ya_no_invalida(tmp_path: Path) -> None:
    sin_url = CONFIG.model_copy(update={"eventos": CONFIG.eventos.model_copy(update={"criticos": [c for c in CONFIG.eventos.criticos if c != "url"]})})
    r = carga.cargar_eventos(_eventos_geojson(tmp_path, [{k: v for k, v in BASE_EVENTO.items() if k != "url"}]), sin_url)
    assert len(r.validas) == 1 and r.rechazadas == 0 and r.nulos_validas["url"] == 1


@pytest.mark.parametrize("anio,valido", [("1959", False), ("1960", True), ("2100", True), ("2101", False), ("20x5", False), ("99999", False)])
def test_low_rango_de_anio(tmp_path: Path, anio: str, valido: bool) -> None:
    ruta = tmp_path / "ind.csv"
    ruta.write_text(CABECERA_IND + f"PAN,A,{anio},1" + SUFIJO_IND, "utf-8")
    assert (len(carga.cargar_indicadores(ruta, CONFIG).validas) == 1) is valido


@pytest.mark.parametrize("campo,valor,valido", [("latitude", 90, True), ("latitude", -90.5, False), ("longitude", 180, True), ("longitude", 181, False)])
def test_low_limites_de_latitud_y_longitud(tmp_path: Path, campo: str, valor: float, valido: bool) -> None:
    r = carga.cargar_eventos(_eventos_geojson(tmp_path, [{**BASE_EVENTO, campo: valor}]), CONFIG)
    assert (len(r.validas) == 1) is valido


def test_low_recorte_del_valor_en_errores(tmp_path: Path) -> None:
    maximo = CONFIG.salida.max_caracteres_valor_en_errores
    ruta = tmp_path / "ind.csv"
    ruta.write_text(CABECERA_IND + "PAN,A,2023," + "9" * (maximo + 50) + "x" + SUFIJO_IND, "utf-8")
    r = carga.cargar_indicadores(ruta, CONFIG)
    assert len(r.errores) == 1 and len(r.errores[0].valor) == maximo + 1  # recortado + "…"


def test_low_criticos_de_indicadores_salen_del_yaml(tmp_path: Path) -> None:
    ruta = tmp_path / "ind.csv"
    ruta.write_text(CABECERA_IND + "PAN,A,2023,1,% anual,https://x.example/a,2025-09-30T12:00:00Z,\n", "utf-8")
    assert carga.cargar_indicadores(ruta, CONFIG).rechazadas == 1  # licencia vacía es crítica
    sin_licencia = CONFIG.model_copy(update={"indicadores": CONFIG.indicadores.model_copy(
        update={"criticos": [c for c in CONFIG.indicadores.criticos if c != "licencia"]})})
    assert carga.cargar_indicadores(ruta, sin_licencia).rechazadas == 0


def test_low_criticos_de_eventos_salen_del_yaml(tmp_path: Path) -> None:
    ruta = _eventos_geojson(tmp_path, [{k: v for k, v in BASE_EVENTO.items() if k != "url"}])
    assert carga.cargar_eventos(ruta, CONFIG).rechazadas == 1
    assert CONFIG.eventos.criticos == ["id", "magnitude", "time", "longitude", "latitude", "url"]


def test_m1_toda_proporcion_lleva_n_e_intervalo_wilson_95(noticias: carga.ResultadoArchivo) -> None:
    assert carga.intervalo_wilson(0, 0, 1.96) is None
    lo, hi = carga.intervalo_wilson(50, 100, 1.96)
    assert round(lo, 4) == 0.4038 and round(hi, 4) == 0.5962
    lo, hi = carga.intervalo_wilson(0, 10, 1.96)
    assert lo == 0.0 and 0.25 < hi < 0.31
    rep = carga.construir_reporte({"t01": noticias}, CONFIG)["distribucion_noticias_validas"]
    for clave in ("concentracion_medios", "concentracion_idiomas"):
        c = rep[clave]
        assert c["n"] == 6 and c["k"] == sum(c["principales"].values())
        assert c["ic95_inferior_pct"] <= c["porcentaje_top_n"] <= c["ic95_superior_pct"]
        assert c["metodo_ic"] == f"Wilson (z={CONFIG.salida.z_intervalo_confianza})" and CONFIG.salida.z_intervalo_confianza == 1.96


def test_m4_contrato_en_un_solo_lugar() -> None:
    c = cargar_contrato()
    assert conversion.COLUMNAS_NOTICIAS == c.noticias
    assert conversion.CAMPOS_FUENTES == c.fuentes
    assert conversion.CAMPOS_EVENTO == c.eventos
    assert conversion.COLUMNAS_INDICADORES == [*c.indicadores_extra, *c.indicadores]
    assert validar_snapshot.COLUMNAS_INDICADORES_CONTRATO == c.indicadores
    assert validar_snapshot.COLUMNAS_NOTICIAS == c.noticias
    assert set(CONFIG.noticias.criticos) <= set(c.noticias)
    assert set(CONFIG.indicadores.criticos) <= set(c.indicadores)
    assert set(CONFIG.eventos.criticos) <= set(c.eventos)
    assert set(CONFIG.fuentes.criticos) <= set(c.fuentes)


def test_m3_config_sin_claves_muertas() -> None:
    assert not hasattr(CONFIG.fechas, "usgs_ms") and not hasattr(CONFIG.fechas, "rss_rfc822")
    assert not hasattr(CONFIG.fechas, "gdelt")
    assert CONFIG.indicadores.patron_anio == r"^\d{4}$"


# ---- A1 · data/processed/validos/ (D-82)


def _hashes(carpeta: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(carpeta.iterdir()) if p.is_file()}


def test_a1_escribe_validos_sin_tocar_el_snapshot(tmp_path: Path) -> None:
    procesados = tmp_path / "processed"
    shutil.copytree(RAIZ / "data" / "processed", procesados)
    antes = _hashes(procesados)
    assert carga.main(["--procesados", str(procesados), "--salida", str(tmp_path / "out")]) == 0
    assert _hashes(procesados) == antes  # el snapshot (y su manifest) quedan intactos
    validos = procesados / "validos"
    assert sorted(p.name for p in validos.iterdir()) == ["eventos.geojson", "fuentes.json", "indicadores.csv", "noticias.csv"]


def test_a1_validos_del_snapshot_real_conservan_todas_las_filas(tmp_path: Path) -> None:
    assert carga.main(["--procesados", str(RAIZ / "data" / "processed"), "--salida", str(tmp_path / "o"), "--validos", str(tmp_path / "v")]) == 0
    manifest = json.loads((RAIZ / "data" / "manifest.json").read_text("utf-8"))["cantidad_por_archivo"]
    assert len(pd.read_csv(tmp_path / "v" / "noticias.csv")) == manifest["noticias.csv"]
    ind = pd.read_csv(tmp_path / "v" / "indicadores.csv")
    assert len(ind) == manifest["indicadores.csv"]
    assert list(ind.columns) == conversion.COLUMNAS_INDICADORES
    assert int(ind["valor"].isna().sum()) == int(pd.read_csv(RAIZ / "data" / "processed" / "indicadores.csv")["valor"].isna().sum())
    assert len(json.loads((tmp_path / "v" / "eventos.geojson").read_text("utf-8"))["features"]) == manifest["eventos.geojson"]
    assert len(json.loads((tmp_path / "v" / "fuentes.json").read_text("utf-8"))) == manifest["fuentes.json"]


def test_a1_validos_solo_contiene_filas_validas_y_es_determinista(tmp_path: Path) -> None:
    rutas = []
    for nombre, lineas in (("a", None), ("b", "invertido")):
        origen = tmp_path / nombre
        origen.mkdir()
        cuerpo = (FIXTURES / "t01_noticias_invalidas.csv").read_text("utf-8").splitlines()
        # Con ids repetidos el orden de entrada cambia cuál es la "primera" aparición; aquí solo importa el orden de salida.
        cuerpo = [cuerpo[0], *(l for l in cuerpo[1:] if l.endswith(","))]
        if lineas:
            cuerpo = [cuerpo[0], *reversed(cuerpo[1:])]
        (origen / "noticias.csv").write_text("\n".join(cuerpo) + "\n", "utf-8")
        (origen / "indicadores.csv").write_text((FIXTURES / "t01_indicadores_nulos.csv").read_text("utf-8"), "utf-8")
        (origen / "eventos.geojson").write_text(json.dumps({"features": [{"properties": BASE_EVENTO}]}), "utf-8")
        (origen / "fuentes.json").write_text(json.dumps([{"dominio": "a.com", "nombre_legible": "A", "pais": None, "origen": "G", "condiciones": "x"}]), "utf-8")
        assert carga.main(["--procesados", str(origen), "--salida", str(origen / "out")]) == 0
        rutas.append(origen / "validos")
    assert _hashes(rutas[0]) == _hashes(rutas[1])  # mismo contenido, otro orden de entrada → mismos bytes
    texto = (rutas[0] / "noticias.csv").read_bytes()
    assert b"\r" not in texto and texto.endswith(b"\n")
    leidas = pd.read_csv(rutas[0] / "noticias.csv", dtype=str)
    assert len(leidas) == 6 and leidas["id_noticia"].is_monotonic_increasing and list(leidas.columns) == cargar_contrato().noticias
    assert not leidas["id_noticia"].duplicated().any()
