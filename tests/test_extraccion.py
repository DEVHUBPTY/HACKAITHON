"""Pruebas offline de la conversión raw -> contrato (E0-04). Sin red."""

import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import conversion, extraer
from tests.conftest import DESCRIPCION_SECRETA, IMAGEN_SECRETA, RSS_ITEMS, SELLO, rss_sintetico


def leer(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_id_noticia_es_sha1_de_la_url_canonica(config) -> None:
    url = "http://www.Ejemplo.test/a/b/?utm_source=x&z=1&a=2#frag"
    canonica = "https://ejemplo.test/a/b?a=2&z=1"
    assert conversion.url_canonica(url, config) == canonica
    esperado = "NOT-" + hashlib.sha1(canonica.encode()).hexdigest()[:10]
    assert conversion.id_noticia(url, config) == esperado
    assert conversion.id_noticia(canonica, config) == esperado  # estable


def test_ids_de_indicador_y_sismo() -> None:
    assert conversion.id_indicador("PAN", "FP.CPI.TOTL.ZG", 2023) == "IND-PAN-FP.CPI.TOTL.ZG-2023"
    assert conversion.id_sismo("us7000abcd") == "SIS-us7000abcd"


def test_seendate_va_a_fecha_deteccion_y_no_a_publicacion(data_sintetica: Path) -> None:
    filas = {f["titulo"]: f for f in leer(data_sintetica / "processed" / "noticias.csv")}
    solo_gdelt = filas["Noticia externa B"]
    assert solo_gdelt["fecha_deteccion"] == "2026-10-01T01:02:03Z"
    assert solo_gdelt["fecha_publicacion"] == ""
    assert solo_gdelt["origen"] == "GDELT"
    assert solo_gdelt["idioma"] == "es"
    # La misma URL en RSS y GDELT conserva ambas fechas, distintas.
    fusion = filas["Titular uno"]
    assert fusion["fecha_publicacion"] == "2026-10-05T10:00:00Z"
    assert fusion["fecha_deteccion"] == "2026-10-04T07:00:00Z"
    assert fusion["origen"] == "TVN RSS · GDELT"
    assert fusion["alcance_texto"] == "basado únicamente en titular/metadatos"


def test_deduplica_por_url_y_filtra_ventana(data_sintetica: Path) -> None:
    filas = leer(data_sintetica / "processed" / "noticias.csv")
    titulos = {f["titulo"] for f in filas}
    assert len(filas) == len({f["id_noticia"] for f in filas}) == 5
    assert "Titular viejo" not in titulos
    assert "Noticia externa A" in titulos
    auditoria = json.loads((data_sintetica / "processed" / "conversion.json").read_text("utf-8"))
    assert [(x["motivo"]) for x in auditoria["excluidos"]] == ["fuera_de_ventana"]
    assert auditoria["duplicados_descartados"] == 2


def test_descripcion_y_socialimage_no_llegan_a_processed(data_sintetica: Path) -> None:
    for ruta in (data_sintetica / "processed").iterdir():
        texto = ruta.read_text(encoding="utf-8")
        assert DESCRIPCION_SECRETA not in texto, ruta.name
        assert IMAGEN_SECRETA not in texto, ruta.name
        assert "socialimage" not in texto.lower(), ruta.name


def test_columnas_del_contrato_en_cada_archivo(data_sintetica: Path) -> None:
    p = data_sintetica / "processed"
    assert set(conversion.COLUMNAS_NOTICIAS) == {
        "id_noticia", "titulo", "url", "medio", "idioma", "fecha_publicacion",
        "fecha_deteccion", "fecha_extraccion", "tema", "origen", "alcance_texto",
    }
    assert list(leer(p / "noticias.csv")[0]) == conversion.COLUMNAS_NOTICIAS
    contrato_ind = {"pais_iso3", "indicador_id", "anio", "valor", "unidad", "fuente_url", "fecha_extraccion", "licencia"}
    assert contrato_ind <= set(leer(p / "indicadores.csv")[0])
    fuentes = json.loads((p / "fuentes.json").read_text("utf-8"))
    assert all(set(conversion.CAMPOS_FUENTES) <= set(f) for f in fuentes)
    eventos = json.loads((p / "eventos.geojson").read_text("utf-8"))["features"]
    assert all(set(conversion.CAMPOS_EVENTO) <= set(e["properties"]) for e in eventos)
    manifest = json.loads((data_sintetica / "manifest.json").read_text("utf-8"))
    for campo in ("version", "fecha_corte_UTC", "consultas", "cantidad_por_archivo", "licencias", "sha256", "transformaciones", "historial"):
        assert campo in manifest


def test_fuentes_un_registro_por_medio_con_condiciones(data_sintetica: Path) -> None:
    fuentes = {f["dominio"]: f for f in json.loads((data_sintetica / "processed" / "fuentes.json").read_text("utf-8"))}
    assert set(fuentes) == {"ejemplo.test", "otro.test", "tvn-2.com"}
    assert fuentes["ejemplo.test"]["condiciones"] == "Pendiente de verificar"
    assert fuentes["ejemplo.test"]["pais"] == "Estados Unidos"  # sourcecountry traducido al español
    assert fuentes["otro.test"]["pais"] == "México"
    assert fuentes["tvn-2.com"]["pais"] == "Panamá"
    assert fuentes["tvn-2.com"]["nombre_legible"] == "TVN Panamá"


def test_cuadricula_completa_con_nulos_explicitos_no_ceros(data_sintetica: Path) -> None:
    filas = leer(data_sintetica / "processed" / "indicadores.csv")
    assert len(filas) == 2 * 2 * 3  # países × indicadores × años
    por = {(f["pais_iso3"], f["indicador_id"], f["anio"]): f for f in filas}
    assert por[("PAN", "NY.GDP.MKTP.KD.ZG", "2024")]["valor"] == ""  # nulo del Banco Mundial
    assert por[("CRI", "NY.GDP.MKTP.KD.ZG", "2022")]["valor"] == ""  # combinación ausente
    assert por[("CRI", "SP.POP.TOTL", "2023")]["valor"] == ""
    assert por[("PAN", "NY.GDP.MKTP.KD.ZG", "2022")]["valor"] == "10.8"
    assert all(f["valor"] != "0" for f in filas)
    assert por[("PAN", "SP.POP.TOTL", "2022")]["id_indicador"] == "IND-PAN-SP.POP.TOTL-2022"
    assert por[("PAN", "SP.POP.TOTL", "2022")]["unidad"] == "personas"


def test_eventos_a_contrato_con_fechas_utc(data_sintetica: Path) -> None:
    eventos = json.loads((data_sintetica / "processed" / "eventos.geojson").read_text("utf-8"))["features"]
    p = eventos[0]["properties"]
    assert p["id"] == "SIS-us7000aaaa"
    assert p["time"] == "2024-01-15T10:00:00Z" and p["updated"] == "2024-01-15T11:00:00Z"
    assert (p["longitude"], p["latitude"], p["depth"]) == (-80.1, 8.2, 12.5)
    assert p["place"].endswith("Panama")


def _registro(dias_atras: int, fin: datetime, n: int) -> dict:
    momento = fin - timedelta(days=dias_atras)
    return {"id_noticia": f"NOT-{n:010d}", "url": f"https://x.test/{n}", "deteccion": momento, "publicacion": None}


def test_ventana_base_se_mantiene_si_se_alcanza_el_minimo(config) -> None:
    fin = datetime(2026, 10, 6, tzinfo=UTC)
    config["volumen_noticias"]["minimo"] = 4
    registros = [_registro(d, fin, i) for i, d in enumerate([1, 5, 10, 29, 45, 80, 120])]
    incluidos, excluidos, dias = conversion.aplicar_ventana(registros, fin, config)
    assert dias == 30 and len(incluidos) == 4
    assert {x["motivo"] for x in excluidos} == {"fuera_de_ventana"} and len(excluidos) == 3


def test_ventana_se_amplia_a_90_y_excluye_lo_mas_viejo(config) -> None:
    fin = datetime(2026, 10, 6, tzinfo=UTC)
    config["volumen_noticias"]["minimo"] = 5
    registros = [_registro(d, fin, i) for i, d in enumerate([1, 5, 10, 45, 80, 120])]
    incluidos, excluidos, dias = conversion.aplicar_ventana(registros, fin, config)
    assert dias == 90 and len(incluidos) == 5
    assert [x["motivo"] for x in excluidos] == ["fuera_de_ventana"]


def test_ventana_no_aplica_el_intervalo_de_la_seccion_7(config) -> None:
    """Un registro de 2024 queda fuera aunque caiga en [2024-01-01, 2025-10-01) del PDF."""
    fin = datetime(2026, 10, 6, tzinfo=UTC)
    viejo = {"id_noticia": "NOT-0", "url": "https://x.test/0", "deteccion": datetime(2024, 6, 1, tzinfo=UTC), "publicacion": None}
    _, excluidos, _ = conversion.aplicar_ventana([viejo], fin, config)
    assert excluidos[0]["motivo"] == "fuera_de_ventana"


def test_rss_se_acumula_y_deduplica_entre_archivos(data_sintetica: Path, config) -> None:
    raw = data_sintetica / "raw"
    nuevo = rss_sintetico(
        [RSS_ITEMS[0], ("Titular cuatro", "https://www.tvn-2.com/nacionales/cuatro_1_5.html", "Tue, 06 Oct 2026 06:00:00 +0000")]
    )
    (raw / "rss_tvn" / "rss_tvn_20261007T120000Z.xml").write_text(nuevo, encoding="utf-8")
    filas, _, _ = conversion.convertir_noticias(raw, config)
    por = {f["titulo"]: f for f in filas}
    assert len(filas) == 6 and "Titular cuatro" in por
    assert por["Titular uno"]["fecha_extraccion"] == "2026-10-06T12:00:00Z"  # la primera vez que se vio
    assert por["Titular cuatro"]["fecha_extraccion"] == "2026-10-07T12:00:00Z"


def test_guardar_crudo_nunca_sobrescribe(tmp_path: Path) -> None:
    extraer._guardar(tmp_path, f"rss_tvn_{SELLO}.xml", b"uno")
    with pytest.raises(FileExistsError):
        extraer._guardar(tmp_path, f"rss_tvn_{SELLO}.xml", b"dos")
    assert (tmp_path / f"rss_tvn_{SELLO}.xml").read_bytes() == b"uno"


def test_rangos_de_fechas_cubren_la_ventana_sin_huecos() -> None:
    hoy = datetime(2026, 10, 6, 15, tzinfo=UTC)
    rangos = extraer._rangos(hoy, 12, 5)
    assert rangos[0][1] == datetime(2026, 10, 6, tzinfo=UTC)
    assert rangos[-1][0] <= datetime(2026, 10, 6, tzinfo=UTC) - timedelta(days=12)
    assert all(a[0] == b[1] for a, b in zip(rangos, rangos[1:], strict=False))
    assert all(r[1] - r[0] <= timedelta(days=5) for r in rangos)


# ---------------------------------------------------- H6/H7/H10: idioma, país y sección


def _gdelt_extra(data: Path, articulos: list[dict]) -> None:
    (data / "raw" / "gdelt" / "gdelt_turismo_20260930000000_20261006000000_20261006T121000Z.json").write_text(
        json.dumps({"articles": articulos}), encoding="utf-8"
    )


def _articulo(n: int, lengua: str, pais: str) -> dict:
    return {
        "url": f"https://extra{n}.test/n", "title": f"Extra {n}", "seendate": "20261003T100000Z",
        "domain": f"extra{n}.test", "language": lengua, "sourcecountry": pais,
    }


def test_idioma_normalizado_a_iso_639_1_y_desconocidos_marcados(data_sintetica: Path, config) -> None:
    from scripts import manifest

    _gdelt_extra(data_sintetica, [_articulo(1, "Russian", "Russia"), _articulo(2, "SPANISH", ""), _articulo(3, "Klingon", "")])
    filas, _, auditoria = conversion.convertir_noticias(data_sintetica / "raw", config)
    idiomas = {f["titulo"]: f["idioma"] for f in filas}
    assert idiomas["Extra 1"] == "ru" and idiomas["Extra 2"] == "es"  # sin distinguir mayúsculas
    assert idiomas["Extra 3"] == "klingon"  # se conserva en minúsculas...
    assert auditoria["idiomas_sin_mapeo"] == {"klingon": 1}  # ...y queda marcado
    assert any("klingon" in t for t in manifest._transformaciones(auditoria))
    assert not any("sin código ISO" in t for t in manifest._transformaciones({"idiomas_sin_mapeo": {}}))


def test_todos_los_idiomas_de_gdelt_tienen_codigo_de_dos_letras(config) -> None:
    idiomas = config["gdelt"]["idiomas"]
    assert len(idiomas) >= 60
    assert all(len(v) == 2 and v.islower() for v in idiomas.values()), idiomas
    assert idiomas["Norwegian"] == "no"  # trampa de YAML 1.1: sin comillas sería False


def test_pais_de_la_fuente_en_espanol_o_nulo_no_pendiente(data_sintetica: Path, config) -> None:
    _gdelt_extra(data_sintetica, [_articulo(1, "English", "Atlantis"), _articulo(2, "English", "")])
    _, fuentes, _ = conversion.convertir_noticias(data_sintetica / "raw", config)
    por = {f["dominio"]: f for f in fuentes}
    assert por["extra1.test"]["pais"] is None and por["extra2.test"]["pais"] is None
    assert por["extra1.test"]["condiciones"] == "Pendiente de verificar"  # solo las condiciones son "pendientes"
    assert por["ejemplo.test"]["pais"] == "Estados Unidos"


def test_seccion_de_la_url_sale_de_la_configuracion(config) -> None:
    assert conversion._seccion_url("https://www.tvn-2.com/economia/nota_1.html", config) == "economia"
    assert conversion._seccion_url("https://www.tvn-2.com/nota_1.html", config) == "sin_seccion"
    config["rss_tvn"]["segmentos_minimos_para_seccion"] = 1
    assert conversion._seccion_url("https://www.tvn-2.com/nota_1.html", config) == "nota_1.html"
    config["rss_tvn"]["tema_sin_seccion"] = "otro"
    config["rss_tvn"]["segmentos_minimos_para_seccion"] = 5
    assert conversion._seccion_url("https://www.tvn-2.com/a/b", config) == "otro"
