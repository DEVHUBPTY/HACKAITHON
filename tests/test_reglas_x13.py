"""X13: la revisión independiente de E1-05 contra el diseño (Notion 'Diseño de solución'), guia_temas y salidas."""

from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import Path

import pytest
import yaml

from src.configuracion import (
    CARPETA_CONFIG,
    RAIZ,
    ErrorDeConfiguracion,
    cargar_modalidad,
    cargar_reglas,
    cargar_restricciones,
    cargar_temas,
    cargar_vinculos,
    validar_todo,
)

EDITORIAL = {
    "alto": ("Producir borrador", "Completar evidencia y producir", "Investigar ya"),
    "medio": ("Borrador opcional", "Vigilar", "Vigilar"),
    "bajo": ("Archivar como contexto", "Archivar", "Archivar"),
}
BANCA = {
    "alto": ("Incluir en el boletín como observación", "Incluir como señal a confirmar", "Seguimiento prioritario"),
    "medio": ("Incluir como contexto", "Seguimiento", "Seguimiento"),
    "bajo": ("Archivar", "Archivar", "Archivar"),
}
ESTADOS = ("suficiente", "parcial", "insuficiente")  # columnas del diseño


def leer(nombre: str) -> dict:
    return yaml.safe_load((CARPETA_CONFIG / f"{nombre}.yaml").read_text("utf-8"))


def escribir(tmp_path: Path, nombre: str, datos: dict) -> Path:
    (tmp_path / f"{nombre}.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp_path


def acciones(modalidad) -> dict[str, tuple[str, ...]]:
    return {r: tuple(getattr(getattr(modalidad.tabla_acciones, r), e).accion for e in ESTADOS) for r in ("alto", "medio", "bajo")}


def banca_fixture(tmp_path: Path):
    d = leer("modalidad_editorial")
    d.update(modalidad="banca", nombre="Banca", usuario="Analista", medio_referencia=None,
             fuentes_sugeridas_extra=["SBP", "MEF", "INEC"], grupos_restricciones=["comunes", "banca"],
             sectores_por_tema={"economia": "economía", "logistica": "logística", "turismo": "turismo", "regulacion": "regulación",
                                "servicios_publicos": "continuidad operativa", "eventos_naturales": "continuidad operativa"},
             alcance_por_sector={"economía": 1.0, "logística": 0.8, "turismo": 0.6, "regulación": 0.8, "continuidad operativa": 0.8},
             horizonte={"inmediato_hasta_dias": 7, "corto_plazo_hasta_dias": 56, "etiquetas": {"inmediato": "I", "corto plazo": "C", "estructural": "E"}},
             bandeja={"sin_sector": "Sin sector asignado", "etiquetas_sector": {s: s for s in ("economía", "logística", "turismo", "regulación", "continuidad operativa")}})
    for rango, textos in BANCA.items():
        for estado, texto in zip(ESTADOS, textos, strict=True):
            d["tabla_acciones"][rango][estado]["accion"] = texto
    return cargar_modalidad("banca", escribir(tmp_path, "modalidad_banca", d)), d


# 1 · tabla de acciones exacta del diseño (D-35, D-38)
def test_tabla_editorial_fija_las_9_celdas_del_diseno() -> None:
    assert acciones(cargar_modalidad("editorial")) == EDITORIAL


def test_tabla_banca_fija_las_9_celdas_del_diseno(tmp_path: Path) -> None:
    banca, _ = banca_fixture(tmp_path)
    assert acciones(banca) == BANCA
    assert banca.fuentes_sugeridas_extra == ["SBP", "MEF", "INEC"]


# 2 · vínculos exactos del diseño
def test_vinculos_son_exactamente_los_del_diseno() -> None:
    v = cargar_vinculos()
    por_regla = {k: (x.tema, x.fuente, x.id, x.relacion) for k, x in v.reglas_vinculo.items()}
    # D-125: las reglas internas heredan los vínculos por subtema del diseño, ahora con el tema del grupo como condición.
    assert por_regla == {
        "pib": ("economia", "indicador", "NY.GDP.MKTP.KD.ZG", "directa"),
        "inflacion": ("economia", "indicador", "FP.CPI.TOTL.ZG", "directa"),
        "empleo": ("economia", "indicador", "SL.UEM.TOTL.ZS", "directa"),
        "comercio_exterior": ("economia", "indicador", "NE.EXP.GNFS.ZS", "directa"),
        "telecomunicaciones": ("servicios_publicos", "indicador", "IT.NET.USER.ZS", "directa"),
        # D-127: sin tema; un término sísmico literal sustenta el contexto de USGS en cualquier tema.
        "sismos": (None, "usgs", None, "evento"),
        # E3-02 (X89): la banca vincula las series agregadas de la SBP; no está en el diseño original.
        "banca": ("economia", "sbp", None, "indirecta"),
        # D-127: la logística ya no recibe las exportaciones por tema: solo si un titular las sustenta con un término.
        "exportaciones_logistica": ("logistica", "indicador", "NE.EXP.GNFS.ZS", "indirecta"),
    }
    log = v.reglas_vinculo["exportaciones_logistica"]
    assert "tránsitos" in log.limitacion
    assert not hasattr(v, "vinculos_por_tema")
    assert set(v.tipos_relacion) == {"directa", "indirecta", "evento"}
    assert v.motivos_sin_vinculo == ["tema_sin_indicador", "sin_dato_en_periodo", "sin_evento_coincidente", "fuera_de_cobertura", "candidatos_ambiguos", "sin_relacion_sustentada"]
    assert v.motivo_sin_relacion == "sin_relacion_sustentada"
    assert v.motivo_por_defecto == "tema_sin_indicador"


# 3 · fuga de evaluación: ningún ejemplo es un caso difícil de la guía (tests de E1-07)
def normalizar(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def casos_dificiles() -> list[str]:
    texto = (RAIZ / "docs" / "guia_temas.md").read_text("utf-8")
    seccion = texto.split("## Casos difíciles", 1)[1].split("\n## ", 1)[0]
    filas = [linea.split("|")[1].strip() for linea in seccion.splitlines() if linea.startswith("| ") and not linea.startswith("| Titular") and not linea.startswith("|---")]
    assert len(filas) >= 15
    return filas


def test_ningun_ejemplo_es_un_caso_dificil_de_la_guia() -> None:
    casos = [normalizar(c) for c in casos_dificiles()]
    textos = [e.titulo for t in cargar_temas().temas.values() for e in t.ejemplos]
    for texto in textos:
        for caso in casos:
            assert difflib.SequenceMatcher(None, normalizar(texto), caso).ratio() < 0.8, f"{texto!r} se parece a un caso difícil: {caso!r}"


def test_cada_tema_conserva_ejemplos_reales_e_ilustrativos() -> None:
    for tema in cargar_temas().temas.values():
        assert sum(e.real for e in tema.ejemplos) >= 1 and len(tema.ejemplos) >= 7


# 4 · frases prohibidas por grupo, referenciadas desde la modalidad
def test_restricciones_separan_comunes_editorial_y_banca() -> None:
    g = cargar_restricciones().grupos
    assert set(g) == {"comunes", "editorial", "banca"}
    assert set(g["comunes"]) == {"lectura_simulada", "sensacionalistas"}
    assert set(g["editorial"]) == {"entrevistas", "imagenes"}
    assert set(g["banca"]) == {"recomendacion", "certeza", "perdidas_en_inferencias", "futuro_asertivo"}  # X50 (E2-02) agrega el futuro asertivo


def test_la_modalidad_declara_que_grupos_de_restricciones_aplican(tmp_path: Path) -> None:
    assert cargar_modalidad("editorial").grupos_restricciones == ["comunes", "editorial"]
    banca, d = banca_fixture(tmp_path)
    assert banca.grupos_restricciones == ["comunes", "banca"]
    d["grupos_restricciones"] = ["comunes", "inexistente"]
    escribir(tmp_path, "modalidad_banca", d)
    from src.configuracion import validar_coherencia

    for nombre in ("fuentes", "reglas_v1.3", "temas", "vinculos", "restricciones"):
        escribir(tmp_path, nombre, leer(nombre))
    (tmp_path / "ejemplos_excluidos.txt").write_text((CARPETA_CONFIG / "ejemplos_excluidos.txt").read_text("utf-8"), encoding="utf-8")
    assert "inexistente" in " ".join(validar_coherencia(tmp_path))


# 5 · estado de evidencia según el diseño
def test_suficiente_exige_sin_contradiccion_abierta(tmp_path: Path) -> None:
    e = cargar_reglas().estado_evidencia
    assert e.sin_contradiccion_abierta_para_suficiente is True
    d = leer("reglas_v1.3")
    d["estado_evidencia"]["sin_contradiccion_abierta_para_suficiente"] = False
    with pytest.raises(ErrorDeConfiguracion, match="sin_contradiccion_abierta_para_suficiente"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", d))


def test_d103_ya_no_hay_percentiles_ni_parte_tematica_en_r() -> None:
    """D-103 reemplaza al percentil de D-35: R no usa percentiles ni la confianza del clasificador y N usa el umbral de agrupación.

    D-135 agregó el nivel implícito del foco y ``panama_actores``. D-119 agregó ``pertenencia_tematica`` a R: es pertenencia DISCRETA según la etiqueta, no confianza. Por eso el conjunto de
    campos creció en ese solo bloque; la guarda contra percentiles o similitudes se mantiene.
    """
    reglas = cargar_reglas()
    campos = set(type(reglas.relevancia).model_fields)
    assert not hasattr(reglas, "percentil") and campos == {"peso_foco", "foco_panama_sujeto", "foco_panama_implicito", "foco_otro_pais_afecta", "panama_actores", "pertenencia_tematica"}
    assert not any("similitud" in c or "percentil" in c or "confianza" in c for c in campos | set(type(reglas.relevancia.pertenencia_tematica).model_fields))
    assert reglas.relevancia.peso_foco == 1.0


# 6 · banca: sectores de D-11 y alcance por sector
def test_banca_valida_temas_y_sectores_de_d11(tmp_path: Path) -> None:
    banca, d = banca_fixture(tmp_path)
    assert banca.sectores_por_tema["eventos_naturales"] == "continuidad operativa"
    assert set(banca.alcance_por_sector) == set(banca.sectores_por_tema.values())
    d["sectores_por_tema"]["deportes"] = "economía"
    with pytest.raises(ErrorDeConfiguracion, match="deportes"):
        cargar_modalidad("banca", escribir(tmp_path, "modalidad_banca", d))
    _, d = banca_fixture(tmp_path)
    d["sectores_por_tema"]["economia"] = "agricultura"
    with pytest.raises(ErrorDeConfiguracion, match="agricultura"):
        cargar_modalidad("banca", escribir(tmp_path, "modalidad_banca", d))
    _, d = banca_fixture(tmp_path)
    d["alcance_por_sector"]["minería"] = 0.5
    with pytest.raises(ErrorDeConfiguracion, match="minería"):
        cargar_modalidad("banca", escribir(tmp_path, "modalidad_banca", d))


# 7 · --validar cubre todos los YAML de config/
def test_validar_cubre_todos_los_yaml_de_config() -> None:
    assert sorted(validar_todo()) == sorted(p.stem for p in CARPETA_CONFIG.glob("*.yaml"))


def test_un_yaml_sin_modelo_registrado_hace_fallar_validar(tmp_path: Path) -> None:
    for p in CARPETA_CONFIG.iterdir():
        (tmp_path / p.name).write_text(p.read_text("utf-8"), encoding="utf-8")
    (tmp_path / "huerfano.yaml").write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match="huerfano"):
        validar_todo(tmp_path)


# 8 · endurecimiento
def test_el_filtro_de_publicar_no_rechaza_publico_ni_publica(tmp_path: Path) -> None:
    d = leer("modalidad_editorial")
    d["tabla_acciones"]["alto"]["suficiente"]["motivo"] = "Servicio público con respaldo; atención pública alta."
    assert cargar_modalidad("editorial", escribir(tmp_path, "modalidad_editorial", d))
    for malo in ("Publicar ya", "Listo para publicado", "se publicará"):
        d["tabla_acciones"]["alto"]["suficiente"]["accion"] = malo
        with pytest.raises(ErrorDeConfiguracion, match="publicar"):
            cargar_modalidad("editorial", escribir(tmp_path, "modalidad_editorial", d))


def test_rangos_empiezan_en_0_y_terminan_en_100(tmp_path: Path) -> None:
    for clave, valor in (("bajo", ("desde", 5)), ("alto", ("hasta", 90))):
        d = leer("reglas_v1.3")
        d["rangos"][clave][valor[0]] = valor[1]
        if clave == "bajo":
            pass
        with pytest.raises(ErrorDeConfiguracion, match="rangos"):
            cargar_reglas(escribir(tmp_path, "reglas_v1.3", d))


def test_desempate_no_vacio_y_sin_repetidos(tmp_path: Path) -> None:
    for valor in ([], ["u_desc", "u_desc"]):
        d = leer("reglas_v1.3")
        d["desempate"] = valor
        with pytest.raises(ErrorDeConfiguracion, match="desempate"):
            cargar_reglas(escribir(tmp_path, "reglas_v1.3", d))


def test_la_cantidad_de_temas_sale_del_yaml(tmp_path: Path) -> None:
    assert cargar_temas().cantidad_temas == 6
    d = leer("temas")
    d["cantidad_temas"] = 7
    with pytest.raises(ErrorDeConfiguracion, match="cantidad_temas"):
        cargar_temas(escribir(tmp_path, "temas", d))


import pytest as _pytest

from src.configuracion import FORMAS_DE_PUBLICAR


@_pytest.mark.parametrize("texto", ["Publicar el borrador", "publíquese hoy", "publicarlo ya", "se publicó", "listo para publicarse"])
def test_filtro_detecta_formas_de_publicar(texto: str) -> None:
    assert FORMAS_DE_PUBLICAR.search(texto)


@_pytest.mark.parametrize("texto", ["Sin fecha de publicación conocida", "afecta la salud pública", "salud publica sin tilde", "interés público"])
def test_filtro_no_rechaza_palabras_legitimas(texto: str) -> None:
    assert not FORMAS_DE_PUBLICAR.search(texto)
