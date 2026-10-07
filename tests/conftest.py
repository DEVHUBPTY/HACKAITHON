"""Fixtures compartidas: un snapshot sintético pequeño, sin red (E0-04)."""

import copy
import json
from pathlib import Path

import pytest

from scripts import conversion, manifest

SELLO = "20261006T120000Z"  # marca de tiempo UTC fija de los crudos sintéticos
DESCRIPCION_SECRETA = "DESCRIPCION-INTERNA-NO-REDISTRIBUIBLE"
IMAGEN_SECRETA = "https://cdn.ejemplo.test/IMAGEN-SOCIAL-PROHIBIDA.jpg"


def _item(titulo: str, url: str, fecha: str) -> str:
    return (
        f"<item><title><![CDATA[{titulo}]]></title><link><![CDATA[{url}]]></link>"
        f"<description><![CDATA[{DESCRIPCION_SECRETA}]]></description>"
        f"<pubDate><![CDATA[{fecha}]]></pubDate></item>"
    )


def rss_sintetico(items: list[tuple[str, str, str]]) -> str:
    cuerpo = "".join(_item(*i) for i in items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<title>Tvn Panamá - Portada</title><language>es</language>"
        f"{cuerpo}</channel></rss>"
    )


RSS_ITEMS = [
    ("Titular uno", "https://www.tvn-2.com/nacionales/uno_1_1.html", "Mon, 05 Oct 2026 10:00:00 +0000"),
    ("Titular dos", "https://www.tvn-2.com/economia/dos_1_2.html", "Sun, 04 Oct 2026 09:30:00 +0000"),
    ("Titular tres", "https://www.tvn-2.com/deportes/tres_1_3.html", "Sat, 03 Oct 2026 08:00:00 +0000"),
    ("Titular viejo", "https://www.tvn-2.com/nacionales/viejo_1_4.html", "Fri, 01 May 2026 08:00:00 +0000"),
]

GDELT_ARTICULOS = [
    {  # misma URL que "Titular uno" pero con http, www y rastreo: debe deduplicarse
        "url": "http://www.tvn-2.com/nacionales/uno_1_1.html?utm_source=x",
        "title": "Titular uno (GDELT)",
        "seendate": "20261004T070000Z",
        "socialimage": IMAGEN_SECRETA,
        "domain": "tvn-2.com",
        "language": "Spanish",
        "sourcecountry": "Panama",
    },
    {
        "url": "https://www.ejemplo.test/a/",
        "title": "Noticia externa A",
        "seendate": "20261002T150000Z",
        "socialimage": IMAGEN_SECRETA,
        "domain": "ejemplo.test",
        "language": "English",
        "sourcecountry": "United States",
    },
    {  # duplicada de la anterior (barra final)
        "url": "https://ejemplo.test/a",
        "title": "Noticia externa A",
        "seendate": "20261003T150000Z",
        "socialimage": "",
        "domain": "ejemplo.test",
        "language": "English",
        "sourcecountry": "United States",
    },
    {
        "url": "https://otro.test/b",
        "title": "Noticia externa B",
        "seendate": "20261001T010203Z",
        "socialimage": "",
        "domain": "otro.test",
        "language": "Spanish",
        "sourcecountry": "Mexico",
    },
]


def usgs_sintetico() -> dict:
    def feature(id_: str, lon: float, lat: float, ms: int) -> dict:
        return {
            "type": "Feature",
            "id": id_,
            "properties": {
                "mag": 4.2,
                "place": "10 km al sur de Algún Lugar, Panama",
                "time": ms,
                "updated": ms + 3600000,
                "status": "reviewed",
                "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{id_}",
            },
            "geometry": {"type": "Point", "coordinates": [lon, lat, 12.5]},
        }

    return {
        "type": "FeatureCollection",
        "features": [
            feature("us7000aaaa", -80.1, 8.2, 1705312800000),  # 2024-01-15T10:00:00Z
            feature("us7000bbbb", -79.9, 9.0, 1717236000000),  # 2024-06-01T10:00:00Z
        ],
    }


def wb_sintetico(indicador: str, valores: dict[tuple[str, int], float | None]) -> list:
    return [
        {"page": 1, "pages": 1, "per_page": 1000, "total": len(valores)},
        [
            {
                "indicator": {"id": indicador, "value": "x"},
                "country": {"id": "PA", "value": "Panama"},
                "countryiso3code": pais,
                "date": str(anio),
                "value": valor,
            }
            for (pais, anio), valor in valores.items()
        ],
    ]


@pytest.fixture
def config() -> dict:
    """Configuración real recortada a un snapshot pequeño (misma lógica, menos volumen)."""
    c = copy.deepcopy(conversion.cargar_config())
    c["banco_mundial"]["paises"] = ["PAN", "CRI"]
    c["banco_mundial"]["anio_inicio"] = 2022
    c["banco_mundial"]["anio_fin"] = 2024
    c["banco_mundial"]["indicadores"] = {
        k: v
        for k, v in c["banco_mundial"]["indicadores"].items()
        if k in ("NY.GDP.MKTP.KD.ZG", "SP.POP.TOTL")
    }
    c["volumen_noticias"] = {"meta": 6, "minimo": 3, "minimo_tvn": 2}
    return c


@pytest.fixture
def data_sintetica(tmp_path: Path, config: dict) -> Path:
    """Crea ``raw/`` sintético, lo convierte y escribe el manifest. Devuelve la carpeta ``data``."""
    data = tmp_path / "data"
    raw = data / "raw"
    (raw / "rss_tvn").mkdir(parents=True)
    (raw / "gdelt").mkdir(parents=True)
    (raw / "banco_mundial").mkdir(parents=True)
    (raw / "usgs").mkdir(parents=True)
    (raw / "rss_tvn" / f"rss_tvn_{SELLO}.xml").write_text(rss_sintetico(RSS_ITEMS), encoding="utf-8")
    for pata in ("locales", "internacional"):  # un tema solo se da por cubierto si lo cubren todas sus patas
        (raw / "gdelt" / f"gdelt_economia__{pata}_20260930000000_20261006120000_20261006T120500Z.json").write_text(
            json.dumps({"articles": GDELT_ARTICULOS if pata == "locales" else []}), encoding="utf-8"
        )
    pib = {("PAN", 2022): 10.8, ("PAN", 2023): 7.3, ("PAN", 2024): None}
    pob = {("PAN", 2022): 4400000, ("PAN", 2023): 4450000, ("PAN", 2024): 4500000, ("CRI", 2022): 5100000}
    (raw / "banco_mundial" / "wb_NY.GDP.MKTP.KD.ZG_20261006T120100Z.json").write_text(
        json.dumps(wb_sintetico("NY.GDP.MKTP.KD.ZG", pib)), encoding="utf-8"
    )
    (raw / "banco_mundial" / "wb_SP.POP.TOTL_20261006T120200Z.json").write_text(
        json.dumps(wb_sintetico("SP.POP.TOTL", pob)), encoding="utf-8"
    )
    (raw / "usgs" / "usgs_20261006T120300Z.geojson").write_text(json.dumps(usgs_sintetico()), encoding="utf-8")
    conversion.convertir_todo(raw, data / "processed", config)
    escribir_manifest(data, config)
    return data


def escribir_manifest(data: Path, config: dict) -> dict:
    m = manifest.construir_manifest(data, config)
    conversion.escribir_json(data / "manifest.json", m)
    return m


@pytest.fixture(autouse=True)
def _registro_de_rechazos_aislado(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ninguna prueba escribe en ``outputs/rechazos.jsonl`` (E1-13): el registro va a una carpeta temporal."""
    monkeypatch.setenv("RECHAZOS_JSONL", str(tmp_path_factory.mktemp("rechazos") / "rechazos.jsonl"))
