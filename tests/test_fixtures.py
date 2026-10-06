"""Pruebas de los fixtures sintéticos (E0-05).

Verifican que los archivos de ``tests/fixtures/`` existen, respetan el contrato
de datos fuera de los errores intencionales de T01 y cubren los casos que cada
prueba de aceptación necesita.
"""

import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

CARPETA = Path(__file__).resolve().parent / "fixtures"

COLUMNAS_NOTICIAS = [
    "id_noticia", "titulo", "url", "medio", "idioma", "fecha_publicacion",
    "fecha_deteccion", "fecha_extraccion", "tema", "origen", "alcance_texto",
]
COLUMNAS_INDICADORES = [
    "pais_iso3", "indicador_id", "anio", "valor", "unidad", "fuente_url",
    "fecha_extraccion", "licencia",
]
EXTRAS = {
    "t01_noticias_invalidas.csv": ["error_esperado"],
    "t03_recirculada.csv": [],
    "t05_contradiccion.csv": [],
    "t07_inyeccion.csv": ["descripcion", "tipo_ataque"],
    "ruido.csv": ["ruido_esperado", "motivo_ruido"],
}
ARCHIVOS_NOTICIAS = list(EXTRAS)
ARCHIVOS = [*ARCHIVOS_NOTICIAS, "t01_indicadores_nulos.csv"]

FORMATO_FECHA = "%Y-%m-%dT%H:%M:%SZ"
VENTANA_INICIO = datetime(2024, 1, 1)
VENTANA_FIN = datetime(2025, 10, 1)  # intervalo [inicio, fin)
CAMPOS_FECHA = ["fecha_publicacion", "fecha_deteccion", "fecha_extraccion"]
OBLIGATORIOS = [c for c in COLUMNAS_NOTICIAS if c != "alcance_texto"]

ERRORES_T01 = {"fecha_invalida", "id_duplicado", "url_mal_formada", "obligatorio_vacio"}
ATAQUES_T07 = {"ignorar_instrucciones", "revelar_prompt", "cambiar_reglas", "pedir_publicar"}
MOTIVOS_RUIDO = {
    "falso_panama", "deportes", "farandula", "no_es_noticia",
    "fuera_de_ventana", "duplicado_url",
}


def leer(nombre: str) -> tuple[list[str], list[dict[str, str]]]:
    """Lee un fixture como texto, sin convertir nulos ni tipos."""
    with (CARPETA / nombre).open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        return list(lector.fieldnames or []), list(lector)


def fecha_valida(texto: str) -> bool:
    try:
        datetime.strptime(texto, FORMATO_FECHA)
    except ValueError:
        return False
    return True


def url_valida(texto: str) -> bool:
    partes = urlsplit(texto)
    return partes.scheme in {"http", "https"} and bool(partes.netloc)


def canonica(url: str) -> str:
    """Canonicaliza una URL: https, sin ``m.``/``www.`` y sin ``/amp``."""
    partes = urlsplit(url)
    host = partes.netloc.removeprefix("m.").removeprefix("www.")
    ruta = partes.path.removesuffix("/amp").rstrip("/")
    return f"{host}{ruta}"


def filas_validas(nombre: str) -> list[dict[str, str]]:
    _, filas = leer(nombre)
    return [f for f in filas if not f.get("error_esperado")]


@pytest.mark.parametrize("nombre", ARCHIVOS)
def test_existe_cada_fixture(nombre: str) -> None:
    assert (CARPETA / nombre).is_file()
    assert (CARPETA / "README.md").is_file()


@pytest.mark.parametrize("nombre", ARCHIVOS_NOTICIAS)
def test_columnas_noticias_exactas(nombre: str) -> None:
    columnas, filas = leer(nombre)
    assert columnas == COLUMNAS_NOTICIAS + EXTRAS[nombre]
    assert filas


def test_columnas_indicadores_exactas() -> None:
    columnas, filas = leer("t01_indicadores_nulos.csv")
    assert columnas == COLUMNAS_INDICADORES
    assert filas


@pytest.mark.parametrize("nombre", ARCHIVOS_NOTICIAS)
def test_ids_sinteticos_y_origen(nombre: str) -> None:
    _, filas = leer(nombre)
    for fila in filas:
        assert fila["origen"] == "sintetico"
        if fila["id_noticia"]:  # el ID vacío es un error intencional de T01
            assert fila["id_noticia"].startswith("SYN-")
        else:
            assert nombre == "t01_noticias_invalidas.csv"
            assert fila["error_esperado"] == "obligatorio_vacio"


@pytest.mark.parametrize("nombre", ARCHIVOS_NOTICIAS)
def test_filas_sin_error_cumplen_el_contrato(nombre: str) -> None:
    filas = filas_validas(nombre)
    assert filas
    for fila in filas:
        for campo in OBLIGATORIOS:
            assert fila[campo].strip(), f"{fila['id_noticia']}: {campo} vacío"
        for campo in CAMPOS_FECHA:
            assert fecha_valida(fila[campo]), f"{fila['id_noticia']}: {campo}"
        assert url_valida(fila["url"]), fila["id_noticia"]
        assert fila["idioma"] in {"es", "en"}
        assert fila["alcance_texto"].startswith("basado ")
    ids = [f["id_noticia"] for f in filas]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("nombre", ARCHIVOS_NOTICIAS)
def test_publicacion_distinta_de_deteccion(nombre: str) -> None:
    for fila in filas_validas(nombre):
        assert fila["fecha_publicacion"] != fila["fecha_deteccion"], fila["id_noticia"]


@pytest.mark.parametrize("nombre", ARCHIVOS_NOTICIAS)
def test_fechas_dentro_de_la_ventana_salvo_ruido_fuera_de_ventana(nombre: str) -> None:
    for fila in filas_validas(nombre):
        if fila.get("motivo_ruido") == "fuera_de_ventana":
            continue
        for campo in ("fecha_publicacion", "fecha_deteccion"):
            fecha = datetime.strptime(fila[campo], FORMATO_FECHA)
            assert VENTANA_INICIO <= fecha < VENTANA_FIN, (fila["id_noticia"], campo)


def test_t01_cada_error_esta_presente_y_es_real() -> None:
    _, filas = leer("t01_noticias_invalidas.csv")
    por_error: dict[str, list[dict[str, str]]] = {}
    for fila in filas:
        if fila["error_esperado"]:
            por_error.setdefault(fila["error_esperado"], []).append(fila)
    assert set(por_error) == ERRORES_T01

    for fila in por_error["fecha_invalida"]:
        assert not all(fecha_valida(fila[c]) for c in CAMPOS_FECHA), fila["id_noticia"]
    for fila in por_error["url_mal_formada"]:
        assert not url_valida(fila["url"]), fila["id_noticia"]
    for fila in por_error["obligatorio_vacio"]:
        assert any(not fila[c].strip() for c in OBLIGATORIOS), fila["id_noticia"]
    for fila in por_error["id_duplicado"]:
        repetidos = [f for f in filas if f["id_noticia"] == fila["id_noticia"]]
        assert len(repetidos) >= 2


def test_t01_mezcla_filas_validas_e_invalidas() -> None:
    _, filas = leer("t01_noticias_invalidas.csv")
    validas = [f for f in filas if not f["error_esperado"]]
    invalidas = [f for f in filas if f["error_esperado"]]
    assert validas
    assert len(invalidas) >= len(ERRORES_T01)


def test_indicadores_nulos_son_nulos_reales() -> None:
    _, filas = leer("t01_indicadores_nulos.csv")
    nulos = [f for f in filas if f["valor"] == ""]
    con_valor = [f for f in filas if f["valor"] != ""]
    assert nulos and con_valor
    for fila in con_valor:
        float(fila["valor"])  # numérico válido
    # Nulo = celda vacía: nunca "0", "0.0", "NA", etc.
    assert not [f for f in filas if f["valor"].strip() in {"0", "0.0", "NA", "NaN", "null"}]
    claves = [(f["pais_iso3"], f["indicador_id"], f["anio"]) for f in filas]
    assert len(claves) == len(set(claves))
    for fila in filas:
        assert len(fila["pais_iso3"]) == 3
        assert fila["anio"].isdigit()
        assert fila["unidad"].strip()
        assert url_valida(fila["fuente_url"])
        assert fecha_valida(fila["fecha_extraccion"])
        assert fila["licencia"] == "sintetico"
        assert "/sintetico/" in fila["fuente_url"]


def test_t03_publicacion_antigua_y_deteccion_reciente() -> None:
    _, filas = leer("t03_recirculada.csv")
    for fila in filas:
        publicacion = datetime.strptime(fila["fecha_publicacion"], FORMATO_FECHA)
        deteccion = datetime.strptime(fila["fecha_deteccion"], FORMATO_FECHA)
        assert publicacion.year == 2024
        assert deteccion.year > publicacion.year


def test_t05_dos_titulares_del_mismo_evento_con_cifras_distintas() -> None:
    _, filas = leer("t05_contradiccion.csv")
    assert len(filas) == 2
    assert len({f["medio"] for f in filas}) == 2
    assert len({f["url"] for f in filas}) == 2
    cifras = []
    for fila in filas:
        numeros = [p for p in fila["titulo"].split() if p.isdigit()]
        assert len(numeros) == 1, fila["titulo"]
        cifras.append(int(numeros[0]))
    assert cifras[0] != cifras[1]
    assert {f["tema"] for f in filas} == {filas[0]["tema"]}


def test_t07_cubre_ambos_idiomas_y_los_cuatro_ataques() -> None:
    _, filas = leer("t07_inyeccion.csv")
    assert {f["tipo_ataque"] for f in filas} == ATAQUES_T07
    assert {f["idioma"] for f in filas} == {"es", "en"}
    combinaciones = {(f["tipo_ataque"], f["idioma"]) for f in filas}
    assert combinaciones == {(a, i) for a in ATAQUES_T07 for i in ("es", "en")}
    for fila in filas:
        assert fila["descripcion"].strip()
        assert "descripción del RSS" in fila["alcance_texto"]


def test_ruido_columnas_y_valores() -> None:
    _, filas = leer("ruido.csv")
    for fila in filas:
        assert fila["ruido_esperado"] in {"true", "false"}
        if fila["ruido_esperado"] == "true":
            assert fila["motivo_ruido"] in MOTIVOS_RUIDO, fila["id_noticia"]
        else:
            assert fila["motivo_ruido"] == "", fila["id_noticia"]


def test_ruido_cubre_cada_categoria_y_hay_controles() -> None:
    _, filas = leer("ruido.csv")
    motivos = {f["motivo_ruido"] for f in filas if f["ruido_esperado"] == "true"}
    assert motivos == MOTIVOS_RUIDO
    controles = [f for f in filas if f["ruido_esperado"] == "false"]
    assert len(controles) >= 2
    assert any(f["medio"] != "Medio Sintético A" and "Canal" in f["titulo"] for f in controles)


def test_ruido_variantes_de_url_colapsan_a_la_misma_canonica() -> None:
    _, filas = leer("ruido.csv")
    duplicados = [f for f in filas if f["motivo_ruido"] == "duplicado_url"]
    variantes = {
        "amp": any(f["url"].endswith("/amp") for f in duplicados),
        "movil": any(urlsplit(f["url"]).netloc.startswith("m.") for f in duplicados),
        "http": any(urlsplit(f["url"]).scheme == "http" for f in duplicados),
    }
    assert all(variantes.values()), variantes
    original = next(f for f in filas if f["id_noticia"] == "SYN-RUI-008")
    for fila in duplicados:
        assert canonica(fila["url"]) == canonica(original["url"])


def test_ruido_titulos_con_sufijo_y_entidades_html() -> None:
    _, filas = leer("ruido.csv")
    titulos = [f["titulo"] for f in filas]
    assert any("&amp;" in t or "&quot;" in t for t in titulos)
    assert any(t.endswith(("- Medio Sintético B", "| Medio Sintético C")) for t in titulos)
