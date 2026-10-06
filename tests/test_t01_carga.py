"""T01 · Fechas inválidas y nulos (E1-02): la carga valida en modo lazy y no se detiene."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src import carga
from src.configuracion import cargar_carga

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


def test_parsers_de_fecha_por_fuente() -> None:
    assert carga.parsear_fecha_iso("2025-02-28T08:00:00Z", CONFIG) is not None
    assert carga.parsear_fecha_iso("2025-02-30T08:00:00Z", CONFIG) is None
    assert carga.parsear_fecha_iso("2025-02-28", CONFIG) is None
    gdelt = carga.parsear_fecha_gdelt("20261001T233000Z", CONFIG)
    assert gdelt is not None and gdelt.isoformat() == "2026-10-01T23:30:00+00:00"
    assert carga.parsear_fecha_gdelt("2026-10-01", CONFIG) is None
    rss = carga.parsear_fecha_rfc822("Mon, 06 Oct 2026 10:00:00 -0500")
    assert rss is not None and rss.isoformat() == "2026-10-06T15:00:00+00:00"
    assert carga.parsear_fecha_rfc822("ayer") is None
    usgs = carga.parsear_fecha_usgs(1704589328000)
    assert usgs is not None and usgs.isoformat() == "2024-01-07T01:02:08+00:00"
    assert carga.parsear_fecha_usgs("1704589328000") is None


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
    assert len(rf.validas) == 1 and rf.errores_por_tipo() == {"obligatorio_vacio": 1}


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
    assert carga.main(["--procesados", str(RAIZ / "data" / "processed"), "--salida", str(tmp_path)]) == 0
    reporte = json.loads((tmp_path / "reporte_calidad.json").read_text("utf-8"))
    assert reporte["totales"]["rechazadas"] == 0
    assert (tmp_path / "errores.csv").read_text("utf-8").startswith("archivo,fila,id,campo,tipo_error,motivo,valor")
