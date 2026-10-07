"""E2-01 · Modalidad bancaria: mapeo tema → sector, alcance por sector (I), horizonte y bandeja agrupada por sector.

Todo se decide con ``config/modalidad_banca.yaml``: ninguna prueba ni ninguna línea de ``src/`` mira el nombre de la modalidad.
"""

from __future__ import annotations

import ast
import dataclasses
import shutil
from pathlib import Path
from typing import Any

import pytest
import streamlit as st
import yaml
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from src import db, embeddings, interfaz as ui, prioridad
from src.configuracion import (
    CARPETA_CONFIG,
    FORMAS_DE_PUBLICAR,
    RAIZ,
    ConfigModalidad,
    ErrorDeConfiguracion,
    cargar_interfaz,
    cargar_modalidad,
    cargar_restricciones,
    cargar_temas,
)
from src.puntaje import calcular_puntajes, impacto
from src.sectores import HORIZONTES, horizonte_de, horizonte_de_grupo, sector_de_tema
from tests import ficha_ayuda as h
from tests import prioridad_ayuda as pa
from tests.motor_falso import MotorFalso, config_de_prueba

BANCA = cargar_modalidad("banca")
EDITORIAL = cargar_modalidad("editorial")
CFG_UI = cargar_interfaz()
MAPEO_D11 = {
    "economia": "economía", "logistica": "logística", "turismo": "turismo", "regulacion": "regulación",
    "servicios_publicos": "continuidad operativa", "eventos_naturales": "continuidad operativa",
}


def datos_banca() -> dict[str, Any]:
    return yaml.safe_load((CARPETA_CONFIG / "modalidad_banca.yaml").read_text(encoding="utf-8"))


def cargar_variante(tmp_path: Path, datos: dict[str, Any]) -> ConfigModalidad:
    (tmp_path / "modalidad_banca.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return cargar_modalidad("banca", tmp_path)


# ------------------------------------------------------------------ configuración


def test_la_modalidad_banca_queda_completa() -> None:
    assert BANCA.parcial is False
    assert BANCA.horizonte is not None and BANCA.bandeja is not None


def test_los_seis_temas_quedan_mapeados_a_los_cinco_sectores_de_d11() -> None:
    assert BANCA.sectores_por_tema == MAPEO_D11
    temas = cargar_temas()
    assert set(BANCA.sectores_por_tema) == set(temas.temas)
    assert set(BANCA.sectores_por_tema.values()) == set(temas.sectores_validos)
    assert set(BANCA.alcance_por_sector) == set(temas.sectores_validos)
    assert all(0 <= v <= 1 for v in BANCA.alcance_por_sector.values())


def test_la_editorial_no_declara_sectores_ni_horizonte_ni_bandeja() -> None:
    assert (EDITORIAL.sectores_por_tema, EDITORIAL.alcance_por_sector, EDITORIAL.horizonte, EDITORIAL.bandeja) == ({}, {}, None, None)


def test_un_tema_sin_sector_se_rechaza(tmp_path: Path) -> None:
    d = datos_banca()
    del d["sectores_por_tema"]["turismo"]
    with pytest.raises(ErrorDeConfiguracion, match="turismo"):
        cargar_variante(tmp_path, d)


def test_un_sector_inventado_o_un_alcance_fuera_de_rango_se_rechazan(tmp_path: Path) -> None:
    d = datos_banca()
    d["sectores_por_tema"]["economia"] = "agricultura"
    with pytest.raises(ErrorDeConfiguracion, match="agricultura"):
        cargar_variante(tmp_path, d)
    d = datos_banca()
    d["alcance_por_sector"]["economía"] = 1.2
    with pytest.raises(ErrorDeConfiguracion, match="economía"):
        cargar_variante(tmp_path, d)


def test_o_se_declaran_todos_los_bloques_por_sector_o_ninguno(tmp_path: Path) -> None:
    for bloque in ("horizonte", "bandeja", "alcance_por_sector"):
        d = datos_banca()
        del d[bloque]
        with pytest.raises(ErrorDeConfiguracion, match=bloque):
            cargar_variante(tmp_path, d)


def test_el_horizonte_exige_limites_positivos_y_crecientes(tmp_path: Path) -> None:
    for inmediato, corto in ((0, 56), (7, 7), (30, 7)):
        d = datos_banca()
        d["horizonte"] = {"inmediato_hasta_dias": inmediato, "corto_plazo_hasta_dias": corto}
        with pytest.raises(ErrorDeConfiguracion, match="horizonte"):
            cargar_variante(tmp_path, d)


def test_el_yaml_de_banca_prohibe_claves_desconocidas(tmp_path: Path) -> None:
    d = datos_banca()
    d["bandeja"]["orden_magico"] = 3
    with pytest.raises(ErrorDeConfiguracion, match="orden_magico"):
        cargar_variante(tmp_path, d)


def textos_del_yaml(valor: Any) -> list[str]:
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, dict):
        return [t for v in valor.values() for t in textos_del_yaml(v)]
    if isinstance(valor, list):
        return [t for v in valor for t in textos_del_yaml(v)]
    return []


def test_ningun_texto_de_banca_usa_el_lexico_prohibido_ni_habla_de_publicar() -> None:
    texto = " ".join(textos_del_yaml(datos_banca())).lower()
    prohibidas = [f.lower() for lista in cargar_restricciones().grupos["banca"].values() for f in lista]
    prohibidas += ["pérdida", "perdida", "impago", "morosidad", "exposición", "cartera", "default", "riesgo de crédito", "score", "alerta definitiva"]
    for frase in prohibidas:
        assert frase not in texto, frase
    assert not FORMAS_DE_PUBLICAR.search(texto)


def test_ninguna_parte_de_src_compara_el_nombre_de_la_modalidad() -> None:
    nombres = {"editorial", "banca"}
    hallazgos = []
    for ruta in sorted((RAIZ / "src").rglob("*.py")):
        for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
            if not isinstance(nodo, ast.Compare):
                continue
            lados = [nodo.left, *nodo.comparators]
            alguno_es_modalidad = any(
                (isinstance(x, ast.Name) and x.id.endswith("modalidad")) or (isinstance(x, ast.Attribute) and x.attr == "modalidad") for x in lados
            )
            constantes = {c.value for x in lados for c in ast.walk(x) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            if alguno_es_modalidad and constantes & nombres:
                hallazgos.append(f"{ruta.name}:{nodo.lineno}")
    assert hallazgos == []


# ------------------------------------------------------------------ sector y horizonte


def test_sector_de_tema_sigue_el_mapeo_y_no_inventa() -> None:
    assert {t: sector_de_tema(t, BANCA) for t in MAPEO_D11} == MAPEO_D11
    assert sector_de_tema(None, BANCA) is None and sector_de_tema("sin_tema", BANCA) is None
    assert sector_de_tema("economia", EDITORIAL) is None


def test_el_horizonte_coincide_con_los_limites_del_yaml() -> None:
    inmediato, corto = BANCA.horizonte.inmediato_hasta_dias, BANCA.horizonte.corto_plazo_hasta_dias
    assert HORIZONTES == ("inmediato", "corto plazo", "estructural")
    assert horizonte_de(0.5, BANCA) == "inmediato"                      # evidencia de horas
    assert horizonte_de(inmediato, BANCA) == "inmediato"                # el límite es inclusivo
    assert horizonte_de(inmediato + 0.01, BANCA) == "corto plazo"       # semanas
    assert horizonte_de(corto, BANCA) == "corto plazo"
    assert horizonte_de(corto + 0.01, BANCA) == "estructural"
    assert horizonte_de(None, BANCA) == "estructural"                   # solo datos anuales: ninguna fecha de noticia
    assert horizonte_de(3, EDITORIAL) is None                           # la editorial no tiene horizonte


def test_el_horizonte_de_un_grupo_usa_la_publicacion_mas_reciente_y_su_deteccion_si_falta() -> None:
    m = pa.miembro
    assert horizonte_de_grupo([m(publicado_hace=24 * 40), m(publicado_hace=5)], pa.AHORA, BANCA, pa.REGLAS) == "inmediato"
    assert horizonte_de_grupo([m(publicado_hace=24 * 20)], pa.AHORA, BANCA, pa.REGLAS) == "corto plazo"
    assert horizonte_de_grupo([m(publicado_hace=24 * 400)], pa.AHORA, BANCA, pa.REGLAS) == "estructural"
    assert horizonte_de_grupo([m(publicado_hace=None, detectado_hace=3)], pa.AHORA, BANCA, pa.REGLAS) == "inmediato"
    assert horizonte_de_grupo([m(publicado_hace=None, detectado_hace=None)], pa.AHORA, BANCA, pa.REGLAS) == "estructural"


# ------------------------------------------------------------------ I por sector


def con_tema(id_grupo: str, tema: str | None, subtema: str | None = "inflacion_precios"):
    return dataclasses.replace(pa.entrada(id_grupo, subtema=subtema), tema=tema)


def test_d102_todos_los_sectores_valen_lo_mismo_en_i_y_el_sector_solo_agrupa() -> None:
    assert set(BANCA.alcance_por_sector.values()) == {1.0}
    valores = {impacto(con_tema("GRP-a", t), pa.REGLAS, pa.CFG, BANCA)[0].valor for t in MAPEO_D11}
    assert len(valores) == 1                                            # el sector no cambia I ni, por tanto, el orden


@pytest.fixture
def banca_con_alcances_distintos() -> ConfigModalidad:
    """El mecanismo sigue siendo configurable: una variante con alcances distintos (no es el valor vigente, D-102)."""
    return BANCA.model_copy(update={"alcance_por_sector": {"economía": 1.0, "logística": 0.8, "turismo": 0.6, "regulación": 0.8, "continuidad operativa": 0.8}})


def test_con_alcance_por_sector_i_cambia_solo_por_el_sector(banca_con_alcances_distintos) -> None:
    BANCA = banca_con_alcances_distintos
    geo = impacto(con_tema("GRP-a", "economia"), pa.REGLAS, pa.CFG, BANCA)[0].explicacion["alcance_geografico"]
    for tema, sector in (("economia", "economía"), ("turismo", "turismo"), ("eventos_naturales", "continuidad operativa")):
        comp, vacios = impacto(con_tema("GRP-a", tema), pa.REGLAS, pa.CFG, BANCA)
        esperado = pa.REGLAS.impacto.peso_subtema * BANCA.alcance_por_sector[sector] + pa.REGLAS.impacto.peso_geografico * geo
        assert comp.valor == pytest.approx(esperado)
        assert comp.explicacion["sector"] == sector and comp.explicacion["alcance_sector"] == BANCA.alcance_por_sector[sector]
        assert not vacios
    distintos = {impacto(con_tema("GRP-a", t), pa.REGLAS, pa.CFG, BANCA)[0].valor for t in ("economia", "turismo")}
    assert len(distintos) == 2


def test_con_alcance_por_sector_el_subtema_ya_no_decide_i(banca_con_alcances_distintos) -> None:
    a = impacto(con_tema("GRP-a", "economia", "inflacion_precios"), pa.REGLAS, pa.CFG, banca_con_alcances_distintos)[0].valor
    b = impacto(con_tema("GRP-a", "economia", "inversion"), pa.REGLAS, pa.CFG, banca_con_alcances_distintos)[0].valor
    assert a == pytest.approx(b)


def test_un_grupo_sin_tema_o_sin_sector_usa_el_alcance_neutro_y_lo_dice() -> None:
    for tema in (None, "sin_tema"):
        comp, vacios = impacto(con_tema("GRP-a", tema, None), pa.REGLAS, pa.CFG, BANCA)
        assert comp.explicacion["sector"] is None and comp.explicacion["alcance_sector"] == pa.CFG.impacto.alcance_subtema_desconocido
        assert [v.codigo for v in vacios] == ["sector_desconocido"]


def test_sin_alcance_por_sector_i_es_el_de_siempre() -> None:
    entrada = con_tema("GRP-a", "economia")
    sin_modalidad, con_editorial = impacto(entrada, pa.REGLAS, pa.CFG), impacto(entrada, pa.REGLAS, pa.CFG, EDITORIAL)
    assert sin_modalidad[0] == con_editorial[0]
    assert sin_modalidad[0].explicacion["alcance_subtema"] == pa.REGLAS.impacto.alcance_subtema["inflacion_precios"]


def test_el_ranking_de_la_editorial_no_cambia_por_existir_la_banca() -> None:
    entradas = [pa.entrada("GRP-a"), pa.entrada("GRP-b", subtema="empleo")]
    a = calcular_puntajes(entradas, pa.REGLAS, pa.CFG, pa.AHORA)
    b = calcular_puntajes(entradas, pa.REGLAS, pa.CFG, pa.AHORA, EDITORIAL)
    assert [(p.id_grupo, p.puntaje) for p in a] == [(p.id_grupo, p.puntaje) for p in b]


# ------------------------------------------------------------------ bandeja agrupada


def fila(id_grupo: str, posicion: int, puntaje: float, sector: str | None, horizonte: str | None = "inmediato") -> ui.FilaBandeja:
    return ui.FilaBandeja(
        posicion, id_grupo, "tema", f"titular {id_grupo}", puntaje, "alto", {"R": 0.5, "I": 0.5, "U": 0.5, "N": 0.5, "E": 0.5},
        "parcial", "Seguimiento", sector=sector, horizonte=horizonte,
    )


def test_la_bandeja_se_agrupa_por_sector_y_los_sectores_se_ordenan_por_su_mayor_p() -> None:
    filas = [fila("GRP-d", 1, 99, None), fila("GRP-c", 2, 95, "logística"), fila("GRP-b", 3, 90, "economía"), fila("GRP-a", 4, 80, "logística"), fila("GRP-e", 5, 50, "economía")]
    bloques = ui.agrupar_por_sector(filas, BANCA)
    assert bloques is not None
    assert [b.sector for b in bloques] == ["logística", "economía", None]            # los grupos sin sector, al final aunque tengan el P más alto
    assert [[f.id_grupo for f in b.filas] for b in bloques] == [["GRP-c", "GRP-a"], ["GRP-b", "GRP-e"], ["GRP-d"]]     # orden de E1-10 dentro del sector
    assert bloques[2].etiqueta == BANCA.bandeja.sin_sector
    assert [b.etiqueta for b in bloques[:2]] == ["Logística", "Economía"]


def test_los_sectores_con_el_mismo_p_siguen_el_orden_declarado() -> None:
    filas = [fila("GRP-t", 1, 70, "turismo"), fila("GRP-e", 2, 70, "economía")]
    assert [b.sector for b in ui.agrupar_por_sector(filas, BANCA)] == ["economía", "turismo"]     # `sectores_validos`: economía antes que turismo


def test_la_editorial_no_agrupa_por_sector() -> None:
    assert ui.agrupar_por_sector([fila("GRP-a", 1, 80, None)], EDITORIAL) is None


# ------------------------------------------------------------------ de punta a punta sobre la base de prueba


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base_banca(tmp_path_factory, emb) -> Path:
    """La base de E1-10b con la corrida de E1-10 hecha con la modalidad bancaria (la misma ruta que ``src.puntaje --modalidad banca``)."""
    carpeta = tmp_path_factory.mktemp("banca")
    ruta = h.construir(carpeta / "senales.duckdb", emb)
    prioridad.ejecutar(ruta, carpeta / "prioridad_banca.json", h.CORTE, None, "banca", emb=emb)
    return ruta


@pytest.fixture(scope="module")
def con_banca(base_banca):
    c = db.conectar(base_banca, solo_lectura=True)
    yield c
    c.close()


def test_la_bandeja_bancaria_trae_sector_y_horizonte_de_cada_grupo(con_banca) -> None:
    filas = {f.id_grupo: f for f in ui.leer_bandeja(con_banca, "banca")}
    assert filas[h.G_COMPLETO].sector == "economía" and filas[h.G_COMPLETO].horizonte == "inmediato"
    assert filas[h.G_SISMO].sector == "continuidad operativa"
    assert filas[h.G_CIFRAS].sector == "continuidad operativa"
    assert filas[h.G_INDIRECTO].sector == "logística"
    assert filas[h.G_RECIRCULADA].horizonte == "estructural"                   # publicada en junio, corte en octubre
    assert filas[h.G_SIN_FECHA].horizonte == "inmediato"                        # sin publicación: la detección más reciente
    assert {f.horizonte for f in filas.values()} <= set(HORIZONTES)


def test_la_bandeja_lee_solo_las_filas_de_la_modalidad_de_la_corrida_y_ninguna_accion_habla_de_publicar(con_banca) -> None:
    editorial = ui.leer_bandeja(con_banca, "editorial")
    assert editorial == []                          # la corrida de esta base es la bancaria: la editorial no tiene filas (E1-10)
    base = ui.leer_bandeja(con_banca, "banca")
    assert all(f.accion and "publicar" not in f.accion.lower() for f in base)


def test_i_de_banca_se_guarda_con_el_sector_en_la_explicacion(con_banca) -> None:
    fila_i = con_banca.execute("SELECT componentes FROM puntajes WHERE id_grupo = ?", [h.G_COMPLETO]).fetchone()[0]
    i = yaml.safe_load(fila_i)["I"]["explicacion"]
    assert i["sector"] == "economía" and i["alcance_sector"] == BANCA.alcance_por_sector["economía"]


# ------------------------------------------------------------------ interfaz


@pytest.fixture
def app_banca(monkeypatch, base_banca, emb, tmp_path):
    monkeypatch.setattr(ui, "elegir_base", lambda demo, cfg, base_normal=None: (base_banca, None))
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)
    monkeypatch.setattr("sys.argv", ["app.py"])
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)


def test_la_pantalla_bandeja_de_banca_muestra_un_bloque_por_sector_con_horizonte(app_banca) -> None:
    at = app_banca.run()
    at.selectbox(key="modalidad").select("banca").run()
    at.session_state["pantalla"] = "bandeja"
    at = at.run()
    assert not at.exception, [e.value for e in at.exception]
    subtitulos = [s.value for s in at.subheader]
    for sector in ("Economía", "Logística", "Continuidad operativa"):
        assert sector in subtitulos
    assert len(at.dataframe) == len(subtitulos) >= 3
    for tabla in at.dataframe:
        assert "Horizonte" in tabla.value.columns and "Sector" not in tabla.value.columns
    assert not any(FORMAS_DE_PUBLICAR.search(str(t.value)) for t in at.dataframe)


def test_banca_ya_no_se_ofrece_como_parcial(app_banca) -> None:
    at = app_banca.run()
    assert list(at.selectbox(key="modalidad").options) == ["Editorial (TVN)", "Banca"]
