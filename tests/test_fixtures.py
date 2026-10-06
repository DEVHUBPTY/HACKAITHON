"""Pruebas de los fixtures sintéticos (E0-05).

Verifican que los archivos de ``tests/fixtures/`` existen, respetan el contrato
de datos fuera de los errores intencionales de T01 y cubren los casos que cada
prueba de aceptación necesita.
"""

import csv
import re
from datetime import datetime, timedelta
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
# D-74: 30 días previos a la extracción, ampliable a 90; se mide sobre la
# fecha de detección porque GDELT filtra por seendate. El intervalo de la
# sección 7 del PDF no se aplica (imposible de extraer).
VENTANA_MAXIMA = timedelta(days=90)
CAMPOS_FECHA = ["fecha_publicacion", "fecha_deteccion", "fecha_extraccion"]
OBLIGATORIOS = [c for c in COLUMNAS_NOTICIAS if c != "alcance_texto"]

ERRORES_T01 = {"fecha_invalida", "id_duplicado", "url_mal_formada", "obligatorio_vacio"}
ATAQUES_T07 = {"ignorar_instrucciones", "revelar_prompt", "cambiar_reglas", "pedir_publicar"}
# Vocabulario de docs/guia_temas.md y specs/E1-03b.md (snake_case).
MOTIVOS_RUIDO = {
    "no_es_panama", "fuera_de_temas", "no_es_noticia",
    "fuera_de_ventana", "duplicado_url",
}
# Categorías originales del spec E0-05, identificadas por ID y título
# (ya no por motivo, que agrupa varias categorías).
CATEGORIAS_RUIDO = {
    "SYN-RUI-001": ("Panama City", "no_es_panama"),
    "SYN-RUI-002": ("Panama Papers", "no_es_panama"),
    "SYN-RUI-003": ("sombreros panamá", "no_es_panama"),
    "SYN-RUI-004": ("fútbol", "fuera_de_temas"),
    "SYN-RUI-005": ("videoclip", "fuera_de_temas"),
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


def en_ventana(fila: dict[str, str]) -> bool:
    """Indica si la detección cae dentro de la ventana de D-74 respecto a la extracción."""
    deteccion = datetime.strptime(fila["fecha_deteccion"], FORMATO_FECHA)
    extraccion = datetime.strptime(fila["fecha_extraccion"], FORMATO_FECHA)
    return extraccion - VENTANA_MAXIMA <= deteccion <= extraccion


@pytest.mark.parametrize("nombre", ARCHIVOS_NOTICIAS)
def test_deteccion_dentro_de_la_ventana_salvo_ruido_fuera_de_ventana(nombre: str) -> None:
    for fila in filas_validas(nombre):
        fuera = fila.get("motivo_ruido") == "fuera_de_ventana"
        assert en_ventana(fila) != fuera, fila["id_noticia"]


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


def parsea(texto: str) -> datetime | None:
    try:
        return datetime.strptime(texto, FORMATO_FECHA)
    except ValueError:
        return None


def test_t01_filas_con_error_solo_tienen_su_error_declarado() -> None:
    """Fuera de su error declarado, la detección cae en la ventana de D-74."""
    _, filas = leer("t01_noticias_invalidas.csv")
    for fila in filas:
        if not fila["error_esperado"]:
            continue
        deteccion = parsea(fila["fecha_deteccion"])
        extraccion = parsea(fila["fecha_extraccion"])
        if deteccion is None or extraccion is None:
            # La fecha de detección es el error intencional (fecha_invalida).
            assert fila["error_esperado"] == "fecha_invalida", fila["id_noticia"]
            continue
        assert extraccion - VENTANA_MAXIMA <= deteccion <= extraccion, (
            f"{fila['id_noticia']}: detección fuera de la ventana"
        )
        publicacion = parsea(fila["fecha_publicacion"])
        if publicacion is not None:
            assert publicacion != deteccion, fila["id_noticia"]
            assert publicacion <= deteccion, fila["id_noticia"]


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
        extraccion = datetime.strptime(fila["fecha_extraccion"], FORMATO_FECHA)
        assert publicacion.year == 2024
        assert deteccion.year > publicacion.year
        assert en_ventana(fila), "la detección debe caer en la ventana de D-74"
        assert publicacion < extraccion - VENTANA_MAXIMA, "la publicación debe ser antigua"


def cifra(titulo: str) -> tuple[float, bool]:
    """Extrae la cifra del titular: (valor, es_cota_inferior).

    Acepta coma o punto decimal ("1,5"/"1.5") y trata "más de N" como cota
    inferior (el valor real es estrictamente mayor que N).
    """
    coincidencia = re.search(r"(más de\s+)?(\d+(?:[.,]\d+)?)", titulo, re.IGNORECASE)
    assert coincidencia, titulo
    valor = float(coincidencia.group(2).replace(",", "."))
    return valor, coincidencia.group(1) is not None


def test_cifra_acepta_coma_punto_y_cota() -> None:
    assert cifra("Inflación en 1,5 por ciento") == (1.5, False)
    assert cifra("Inflación en 1.5 por ciento") == (1.5, False)
    assert cifra("Más de 40 escuelas") == (40.0, True)


def test_t05_dos_titulares_del_mismo_evento_con_cifras_incompatibles() -> None:
    _, filas = leer("t05_contradiccion.csv")
    assert len(filas) == 2
    a, b = filas
    assert a["medio"] != b["medio"]
    assert a["url"] != b["url"]
    # Mismo evento: mismo tema, lugar y objeto del conteo.
    assert a["tema"] == b["tema"]
    for palabra in ("veraguas", "escuelas", "lluvias"):
        assert palabra in a["titulo"].lower() and palabra in b["titulo"].lower(), palabra
    (va, cota_a), (vb, cota_b) = cifra(a["titulo"]), cifra(b["titulo"])

    def compatible(x: tuple[float, bool], y: tuple[float, bool]) -> bool:
        """Dos cifras son compatibles si pueden describir el mismo valor real."""
        (vx, cx), (vy, cy) = x, y
        if cx and cy:
            return True  # dos cotas inferiores siempre pueden coincidir
        if cx:
            return vy > vx
        if cy:
            return vx > vy
        return vx == vy

    assert not compatible((va, cota_a), (vb, cota_b))
    assert va != vb


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


def test_ruido_cubre_cada_motivo_y_hay_controles() -> None:
    _, filas = leer("ruido.csv")
    motivos = {f["motivo_ruido"] for f in filas if f["ruido_esperado"] == "true"}
    assert motivos == MOTIVOS_RUIDO
    assert len([f for f in filas if f["ruido_esperado"] == "false"]) >= 2


def test_ruido_cubre_cada_categoria_original_por_titulo() -> None:
    _, filas = leer("ruido.csv")
    por_id = {f["id_noticia"]: f for f in filas}
    for id_, (fragmento, motivo) in CATEGORIAS_RUIDO.items():
        fila = por_id[id_]
        assert fragmento.lower() in fila["titulo"].lower(), id_
        assert fila["ruido_esperado"] == "true", id_
        assert fila["motivo_ruido"] == motivo, id_


def test_ruido_papers_no_repite_la_regla_en_el_titular() -> None:
    _, filas = leer("ruido.csv")
    titulo = next(f["titulo"] for f in filas if f["id_noticia"] == "SYN-RUI-002")
    assert "sin hechos nuevos" not in titulo.lower()


def test_ruido_otro_pais_que_afecta_a_panama_no_es_ruido() -> None:
    _, filas = leer("ruido.csv")
    por_id = {f["id_noticia"]: f for f in filas}
    for id_, fragmento in (("SYN-RUI-014", "Canal"), ("SYN-RUI-015", "Darién")):
        fila = por_id[id_]
        assert fila["ruido_esperado"] == "false", id_
        assert fila["motivo_ruido"] == "", id_
        assert fragmento in fila["titulo"], id_
        # Señal de que la fuente no es panameña: agencia global y sección de mundo.
        assert fila["medio"].startswith("Agencia Global"), id_
        assert "/mundo/" in fila["url"], id_


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
    con_entidades = [f for f in filas if "&amp;" in f["titulo"] or "&quot;" in f["titulo"]]
    con_sufijo = [
        f for f in filas if f["titulo"].endswith(("- Medio Sintético B", "| Medio Sintético C"))
    ]
    assert con_entidades and con_sufijo
    for fila in [*con_entidades, *con_sufijo]:
        assert fila["ruido_esperado"] == "false", fila["id_noticia"]
        assert fila["motivo_ruido"] == "", fila["id_noticia"]


def test_ruido_cifras_con_coma_decimal() -> None:
    _, filas = leer("ruido.csv")
    inflacion = [f for f in filas if f["titulo"].startswith("Inflación anual")]
    assert len(inflacion) == 4
    assert {f["titulo"] for f in inflacion} == {
        "Inflación anual cierra en 1,5 por ciento según cifras oficiales"
    }
