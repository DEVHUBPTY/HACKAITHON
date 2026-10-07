"""E1-10b · Ficha de evidencia común a ambas modalidades: cinco partes, citas, vacíos, fuentes sugeridas y exportaciones."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from src import db, embeddings, ficha as modulo
from src.configuracion import (
    FORMAS_DE_PUBLICAR,
    CARGADORES,
    ErrorDeConfiguracion,
    cargar_modalidad,
    cargar_restricciones,
    cargar_verificacion,
    validar_todo,
)
from src.esquemas import Ficha
from src.ficha import Linea, a_linea_jsonl, a_markdown, escapar_markdown, construir_ficha, elegir_titular_central, fuentes_sugeridas, vista
from tests import ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.prioridad_ayuda import ProveedorFalso, fila_grupo

PARTES = ("que_se_reporta", "quien_lo_reporta", "respaldado", "falta_comprobar", "accion_recomendada")
MODALIDADES = ("editorial", "banca")
GRUPOS = (h.G_COMPLETO, h.G_CIFRAS, h.G_INDIRECTO, h.G_SIN_FECHA, h.G_RECIRCULADA, h.G_INYECCION, h.G_SISMO, h.G_DISCREPANCIA, h.G_SOLO, h.G_PERIODO, h.G_SISMO_REVISADO)
CFG = cargar_verificacion()


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base(tmp_path_factory, emb) -> Path:
    return h.construir(tmp_path_factory.mktemp("ficha") / "senales.duckdb", emb)


@pytest.fixture(scope="module")
def base_banca(tmp_path_factory, emb) -> Path:
    """La misma base con la corrida de E1-10 hecha con la modalidad bancaria: una base solo guarda una modalidad a la vez (X39)."""
    return h.construir(tmp_path_factory.mktemp("ficha_banca") / "senales.duckdb", emb, modalidad="banca")


class PorModalidad:
    """La conexión editorial (``con.execute`` va a ella) y, con ``.de(modalidad)``, la de la corrida de esa modalidad."""

    def __init__(self, editorial, banca) -> None:
        self._base = editorial
        self._por_modalidad = {"editorial": editorial, "banca": banca}

    def de(self, modalidad: str):
        return self._por_modalidad[modalidad]

    def __getattr__(self, nombre: str):
        return getattr(self._base, nombre)


@pytest.fixture(scope="module")
def con(base, base_banca):
    editorial, banca = db.conectar(base, solo_lectura=True), db.conectar(base_banca, solo_lectura=True)
    yield PorModalidad(editorial, banca)
    editorial.close()
    banca.close()


def hacer(con, emb, grupo: str, modalidad: str = "editorial") -> Ficha:
    return construir_ficha(grupo, modalidad, con.de(modalidad) if isinstance(con, PorModalidad) else con, emb=emb)


def codigos(f: Ficha) -> set[str]:
    return {v.codigo for v in (*f.falta_comprobar.principales, *f.falta_comprobar.otros)}


def lineas_de_markdown(md: str) -> list[str]:
    return [m.group(2) for m in (re.match(r"^( *)- (.*)$", linea) for linea in md.splitlines()) if m]


# ------------------------------------------------------------------ las cinco partes


@pytest.mark.parametrize("modalidad", MODALIDADES)
@pytest.mark.parametrize("grupo", GRUPOS)
def test_las_cinco_partes_estan_siempre_en_ambas_modalidades(con, emb, grupo, modalidad) -> None:
    f = hacer(con, emb, grupo, modalidad)
    for parte in PARTES:
        assert getattr(f, parte) is not None
    v = vista(f)
    assert [s.clave for s in v.secciones] == list(PARTES)
    assert all(s.lineas for s in v.secciones)
    md = a_markdown(f)
    assert [m for m in re.findall(r"^## (.*)$", md, flags=re.M)] == [s.titulo for s in v.secciones]


@pytest.mark.parametrize("parte", PARTES)
def test_el_modelo_rechaza_una_ficha_sin_alguna_de_las_cinco_partes(con, emb, parte) -> None:
    datos = hacer(con, emb, h.G_COMPLETO).model_dump()
    del datos[parte]
    with pytest.raises(ValidationError, match=parte):
        Ficha.model_validate(datos)


def test_el_modelo_rechaza_una_parte_vacia_o_con_campos_de_mas(con, emb) -> None:
    datos = hacer(con, emb, h.G_COMPLETO).model_dump()
    with pytest.raises(ValidationError):
        Ficha.model_validate({**datos, "respaldado": {}})
    with pytest.raises(ValidationError):
        Ficha.model_validate({**datos, "autor": "Fulano"})


def test_la_ficha_no_usa_el_llm(con, emb, monkeypatch) -> None:
    import src.llm.proveedor as proveedor

    def prohibido(*a: Any, **k: Any) -> None:
        raise AssertionError("la ficha no llama al LLM (D-36)")

    monkeypatch.setattr(proveedor, "crear_proveedor", prohibido)
    assert hacer(con, emb, h.G_CIFRAS).falta_comprobar.principales


# ------------------------------------------------------------------ qué se reporta


def test_la_leyenda_de_alcance_esta_en_la_ficha_el_markdown_y_el_jsonl(con, emb) -> None:
    leyenda = cargar_restricciones().leyendas_alcance.titular_metadatos
    f = hacer(con, emb, h.G_COMPLETO)
    assert f.alcance == leyenda == "basado únicamente en titular/metadatos"
    assert leyenda in a_markdown(f) and json.loads(a_linea_jsonl(f))["alcance"] == leyenda
    assert "BORRADOR" in a_markdown(f) and f.borrador is True


def test_la_cobertura_dice_titulares_medios_y_rango_de_fechas_en_hora_de_panama(con, emb) -> None:
    f = hacer(con, emb, h.G_COMPLETO)
    c = f.que_se_reporta.cobertura
    assert (c.n_titulares, c.n_medios) == (3, 3)
    assert (c.fecha_inicio, c.fecha_fin) == ("2026-10-06T08:00:00Z", "2026-10-06T10:00:00Z")      # los datos, en ISO UTC
    linea = next(x.texto for x in vista(f).secciones[0].lineas if x.texto.startswith("Cobertura"))
    assert "3 titulares" in linea and "3 medios" in linea
    assert "2026-10-06 03:00" in linea and "2026-10-06 05:00" in linea and "hora de Panamá" in linea   # UTC-5 solo al mostrar


def test_el_titular_central_prefiere_espanol_y_medio_panameno_entre_los_mas_centrales() -> None:
    miembros = [
        {"id_noticia": "NOT-a", "idioma": "en", "pais_medio": "Estados Unidos"},
        {"id_noticia": "NOT-b", "idioma": "es", "pais_medio": "Argentina"},
        {"id_noticia": "NOT-c", "idioma": "es", "pais_medio": "Panamá"},
        {"id_noticia": "NOT-d", "idioma": "es", "pais_medio": "Panamá"},
    ]
    v = np.array([[0.7, 0.7], [0.9, 0.44], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    # el inglés es el más cercano al centroide; entre los 3 más centrales (a, b, c) gana el español de un medio panameño
    assert miembros[elegir_titular_central(miembros, v, CFG)]["id_noticia"] == "NOT-c"
    # sin nadie en español y panameño entre los candidatos, gana el español; sin español, el más cercano
    assert miembros[elegir_titular_central(miembros[:2], v[:2], CFG)]["id_noticia"] == "NOT-b"
    assert miembros[elegir_titular_central(miembros[:1], v[:1], CFG)]["id_noticia"] == "NOT-a"


def test_el_titular_central_es_determinista_ante_empates() -> None:
    miembros = [{"id_noticia": f"NOT-{i}", "idioma": "es", "pais_medio": "Panamá"} for i in "cab"]
    v = np.array([[1.0, 0.0]] * 3, dtype=np.float32)
    assert miembros[elegir_titular_central(miembros, v, CFG)]["id_noticia"] == "NOT-a"


def test_el_criterio_del_subtema_se_muestra_si_el_vinculo_lo_trae(con, emb) -> None:
    f = hacer(con, emb, h.G_COMPLETO)
    assert f.que_se_reporta.criterio_subtema is None            # la base sintética no lo trae
    v = vista(f.model_copy(update={"que_se_reporta": f.que_se_reporta.model_copy(update={"criterio_subtema": "margen"})}))
    assert any("(criterio: margen)" in l.texto for l in v.secciones[0].lineas)


def test_la_ficha_usa_embeddings_cacheados_y_no_carga_el_modelo(con, emb) -> None:
    antes = emb.codificados
    hacer(con, emb, h.G_COMPLETO)
    hacer(con, emb, h.G_COMPLETO)
    assert emb.codificados == antes           # los titulares ya estaban en la caché (la tubería de E1-10 los codificó)


def test_una_posible_contradiccion_muestra_ambas_versiones_con_su_fuente_y_la_etiqueta_fija(con, emb) -> None:
    f = hacer(con, emb, h.G_CIFRAS)
    (c,) = f.que_se_reporta.contradicciones
    assert c.etiqueta == "posible contradicción, verificar"
    assert {c.version_a.id, c.version_b.id} == {"NOT-d000000001", "NOT-d000000002"}
    assert {c.version_a.medio, c.version_b.medio} == {"La Prensa Ejemplo", "English Example News"}
    assert "12 escuelas" in c.version_a.titular and "40 escuelas" in c.version_b.titular
    assert c.nota_llm == "pendiente"        # sin LLM: sigue abierta y se dice
    texto = "\n".join(x.texto for x in vista(f).secciones[0].lineas)
    assert "posible contradicción, verificar" in texto and "12 escuelas" in texto and "40 escuelas" in texto


def test_el_llm_solo_anota_la_contradiccion_y_nunca_la_cierra(tmp_path, emb) -> None:
    par = {"id_a": "NOT-d000000001", "id_b": "NOT-d000000002", "posible_contradiccion": False, "fragmento_a": "", "fragmento_b": ""}
    base = h.construir(tmp_path / "s.duckdb", emb, ProveedorFalso({"pares": [par]}))
    c = db.conectar(base, solo_lectura=True)
    try:
        f = hacer(c, emb, h.G_CIFRAS)
    finally:
        c.close()
    (x,) = f.que_se_reporta.contradicciones
    assert x.nota_llm == "compatible" and x.etiqueta == "posible contradicción, verificar"     # la nota no cambia la etiqueta
    assert "contradiccion_abierta" in codigos(f)
    assert any("Nota del LLM" in l.texto and "no cierra" in l.texto for l in vista(f).secciones[0].lineas)


def test_un_titular_sospechoso_de_inyeccion_muestra_la_advertencia_en_la_ficha(con, emb) -> None:
    f = hacer(con, emb, h.G_INYECCION)
    assert CFG.presentacion.advertencia_inyeccion in f.que_se_reporta.advertencias
    assert any(CFG.presentacion.advertencia_inyeccion in l.texto and l.texto.startswith("Advertencia") for l in vista(f).secciones[0].lineas)
    assert CFG.presentacion.advertencia_inyeccion in a_markdown(f)
    assert [t.sospechoso_inyeccion for t in f.quien_lo_reporta.titulares].count(True) == 1
    assert not hacer(con, emb, h.G_COMPLETO).que_se_reporta.advertencias


def test_una_noticia_recirculada_no_se_presenta_como_nueva(con, emb) -> None:
    f = hacer(con, emb, h.G_RECIRCULADA)
    assert f.que_se_reporta.recirculada and CFG.presentacion.advertencia_recirculada in f.que_se_reporta.advertencias
    assert not hacer(con, emb, h.G_COMPLETO).que_se_reporta.recirculada


# ------------------------------------------------------------------ quién lo reporta


def test_cada_titular_trae_medio_pais_agencia_firma_fecha_y_enlace_pero_nunca_un_autor(con, emb) -> None:
    f = hacer(con, emb, h.G_COMPLETO)
    por_id = {t.id_noticia: t for t in f.quien_lo_reporta.titulares}
    ingles = por_id["NOT-c000000003"]
    assert (ingles.medio, ingles.pais_medio, ingles.agencia, ingles.tipo_firma) == ("English Example News", "Estados Unidos", "Reuters", "agencia")
    assert ingles.fecha_publicacion == "2026-10-06T09:00:00Z" and ingles.url == "https://english.example/NOT-c000000003"
    assert por_id["NOT-c000000002"].medio == "TVN Panamá"          # nombre legible, no el dominio
    for grupo in GRUPOS:
        volcado = json.dumps(hacer(con, emb, grupo).model_dump(), ensure_ascii=False).lower()
        assert not re.search(r'"(autor|author|byline|firmante|periodista)\w*":', volcado)


def test_la_fecha_desconocida_se_dice_y_nunca_se_sustituye_por_la_deteccion(con, emb) -> None:
    f = hacer(con, emb, h.G_SIN_FECHA)
    assert all(t.fecha_publicacion is None for t in f.quien_lo_reporta.titulares)
    lineas = [l.texto for l in vista(f).secciones[1].lineas]
    assert all("desconocida" in l for l in lineas if l.startswith("«"))
    assert "2026-10-06 04:00" not in "\n".join(lineas)          # la detección (09:00Z) no ocupa el lugar de la publicación


def test_las_procedencias_se_explican_como_estimadas(con, emb) -> None:
    p = hacer(con, emb, h.G_COMPLETO).quien_lo_reporta.procedencias
    assert p.n == 3 and p.estimado is True and "estimada" in p.explicacion and "3 titular" in p.explicacion
    assert [x.orden for x in p.detalle] == [1, 2, 3]


def test_el_medio_de_referencia_solo_aparece_si_la_modalidad_lo_define(con, emb) -> None:
    e = hacer(con, emb, h.G_COMPLETO, "editorial").quien_lo_reporta.medio_referencia
    assert e is not None and e.nombre == "TVN Panamá" and e.cubrio is True and e.n_titulares == 1 and e.ids_noticia == ["NOT-c000000002"]
    sin = hacer(con, emb, h.G_CIFRAS, "editorial").quien_lo_reporta.medio_referencia
    assert sin is not None and sin.cubrio is False and "no se afirma" in sin.texto
    assert hacer(con, emb, h.G_COMPLETO, "banca").quien_lo_reporta.medio_referencia is None
    assert not any("TVN" in l.texto and "referencia" in l.texto.lower() for l in vista(hacer(con, emb, h.G_COMPLETO, "banca")).secciones[1].lineas)


# ------------------------------------------------------------------ qué está respaldado


@pytest.mark.parametrize("modalidad", MODALIDADES)
@pytest.mark.parametrize("grupo", GRUPOS)
def test_toda_linea_de_respaldado_tiene_una_cita_id_mas_campo(con, emb, grupo, modalidad) -> None:
    f = hacer(con, emb, grupo, modalidad)
    lineas = [*f.respaldado.reportes, *f.respaldado.datos_oficiales, *f.respaldado.eventos_oficiales, *f.respaldado.declaraciones]
    assert lineas
    patron = re.compile(r"^(NOT-[0-9a-f]{10}|GRP-\S+|IND-[A-Z]{3}-\S+-\d{4}|SIS-\S+|SBP-\S+) · [a-z_]+$")
    for linea in lineas:
        assert linea.citas
        assert all(patron.match(c.formato()) for c in linea.citas), linea
    # y en el texto que ve la persona (vista y Markdown) cada línea lleva sus citas
    visibles = [l.texto for l in vista(f).secciones[2].lineas if l.nivel == 1]
    for linea in lineas:
        assert any(all(c.formato() in v for c in linea.citas) for v in visibles), linea


def test_los_reportes_son_conteos_tipo_hecho_con_cita_al_grupo(con, emb) -> None:
    f = hacer(con, emb, h.G_COMPLETO)
    textos = {l.texto: l for l in f.respaldado.reportes}
    assert all(l.tipo == "hecho" for l in textos.values())
    assert any("3 titulares" in t and "3 medios" in t for t in textos)
    assert any("3 procedencias" in t and "estimada" in t for t in textos)
    assert {c.campo for l in textos.values() for c in l.citas} == {"n_titulares", "n_medios", "n_procedencias"}


def test_el_dato_oficial_lleva_anio_unidad_cita_y_limitacion_sin_decir_actual(con, emb) -> None:
    f = hacer(con, emb, h.G_COMPLETO)
    oficiales = f.respaldado.datos_oficiales
    panama = next(l for l in oficiales if any(c.id == "IND-PAN-FP.CPI.TOTL.ZG-2024" for c in l.citas))
    assert panama.tipo == "hecho" and [c.formato() for c in panama.citas] == ["IND-PAN-FP.CPI.TOTL.ZG-2024 · valor"]
    assert "2024" in panama.texto and "0.69" in panama.texto and "% anual" in panama.texto and panama.limitacion == "Dato anual de 2024; puede revisarse."
    assert any(c.id == "IND-COL-FP.CPI.TOTL.ZG-2024" for l in oficiales for c in l.citas)        # comparable
    assert {c.id for l in oficiales for c in l.citas} >= {"IND-PAN-FP.CPI.TOTL.ZG-2022", "IND-PAN-FP.CPI.TOTL.ZG-2023"}   # tendencia
    assert not re.search(r"\b(actual|actuales|actualmente|hoy)\b", json.dumps(f.respaldado.model_dump(), ensure_ascii=False), re.I)


def test_los_datos_oficiales_se_agrupan_por_rol_sin_perder_ninguna_cita_ni_repetir_la_limitacion(con, emb) -> None:
    oficiales = hacer(con, emb, h.G_COMPLETO).respaldado.datos_oficiales
    assert [len(l.citas) for l in oficiales] == [1, 1, 3]            # Panamá, comparables, tendencia (3 años)
    assert all(l.limitacion for l in oficiales)
    tendencia = oficiales[-1]
    assert [c.id for c in tendencia.citas] == [f"IND-PAN-FP.CPI.TOTL.ZG-{a}" for a in (2024, 2023, 2022)]
    assert all(str(a) in tendencia.texto for a in (2024, 2023, 2022))


def test_el_evento_oficial_muestra_el_lugar_original_y_su_limitacion(con, emb) -> None:
    f = hacer(con, emb, h.G_SISMO)
    (ev,) = f.respaldado.eventos_oficiales
    assert ev.tipo == "hecho" and [c.formato() for c in ev.citas] == ["SIS-us7000test · magnitude"]
    assert "12 km S of Puerto Armuelles, Panama" in ev.texto and "5.1" in ev.texto
    assert "no es Panamá" in (ev.limitacion or "") and f.respaldado.datos_oficiales == []


def test_lo_que_dicen_los_titulares_es_declaracion_atribuida_con_cita_al_titular(con, emb) -> None:
    f = hacer(con, emb, h.G_COMPLETO)
    assert len(f.respaldado.declaraciones) == 3
    for d in f.respaldado.declaraciones:
        assert d.tipo == "declaración" and d.atribucion and d.atribucion in d.texto
        assert [c.campo for c in d.citas] == ["titulo_limpio"] and d.citas[0].id.startswith("NOT-")
    assert any("TVN Panamá" in d.texto and "Panamá reporta inflación estable" in d.texto for d in f.respaldado.declaraciones)


def test_un_vinculo_indirecto_no_es_dato_oficial_x22(con, emb) -> None:
    f = hacer(con, emb, h.G_INDIRECTO)
    assert f.respaldado.datos_oficiales == [] and f.respaldado.eventos_oficiales == []


def test_el_modelo_rechaza_respaldo_sin_cita_o_declaracion_sin_atribucion(con, emb) -> None:
    datos = hacer(con, emb, h.G_COMPLETO).model_dump()
    sin_cita = json.loads(json.dumps(datos))
    sin_cita["respaldado"]["reportes"][0]["citas"] = []
    with pytest.raises(ValidationError):
        Ficha.model_validate(sin_cita)
    sin_atribucion = json.loads(json.dumps(datos))
    sin_atribucion["respaldado"]["declaraciones"][0]["atribucion"] = None
    with pytest.raises(ValidationError):
        Ficha.model_validate(sin_atribucion)
    hecho_de_titular = json.loads(json.dumps(datos))
    hecho_de_titular["respaldado"]["declaraciones"][0]["tipo"] = "hecho"      # un titular nunca es un hecho
    with pytest.raises(ValidationError):
        Ficha.model_validate(hecho_de_titular)


# ------------------------------------------------------------------ qué falta comprobar


# Cada tipo de vacío con los grupos donde su condición se cumple; en los demás no debe aparecer.
ESPERADOS: dict[str, set[str]] = {
    "contradiccion_abierta": {h.G_CIFRAS},
    "cifra_discrepante": {h.G_DISCREPANCIA},
    "cifras_sin_dato_oficial": {h.G_CIFRAS},
    "sin_dato_oficial": {h.G_CIFRAS},
    "solo_vinculo_indirecto": {h.G_INDIRECTO},
    "procedencias_insuficientes": {h.G_INDIRECTO, h.G_SOLO},
    "noticia_recirculada": {h.G_RECIRCULADA},
    "evento_sin_revisar": {h.G_SISMO},
    "cifra_periodo_distinto": {h.G_PERIODO},
    "medios_o_fechas_desconocidos": {h.G_SIN_FECHA},
    "urgencia_sin_publicacion": {h.G_SIN_FECHA},
    "subtema_desconocido": {h.G_CIFRAS},
    "sector_desconocido": set(),       # solo en una corrida bancaria con un tema sin sector (ningún grupo de la base lo tiene)
}


def test_el_catalogo_de_la_prueba_cubre_todos_los_tipos_de_vacio_de_la_configuracion() -> None:
    assert set(ESPERADOS) == set(CFG.vacios.catalogo) == set(CFG.vacios.orden_importancia)


@pytest.mark.parametrize("codigo", sorted(ESPERADOS))
def test_cada_tipo_de_vacio_aparece_cuando_se_cumple_su_condicion_y_no_cuando_no(con, emb, codigo) -> None:
    con_vacio = {g for g in GRUPOS if codigo in codigos(hacer(con, emb, g))}
    assert con_vacio == ESPERADOS[codigo]


def test_el_grupo_completo_no_tiene_ningun_vacio(con, emb) -> None:
    f = hacer(con, emb, h.G_COMPLETO)
    assert codigos(f) == set() and f.falta_comprobar.principales == [] and f.falta_comprobar.otros == []


def test_solo_vinculo_indirecto_tiene_su_propio_texto_y_reemplaza_a_sin_vinculo_en_la_tabla(con, emb) -> None:
    f = hacer(con, emb, h.G_INDIRECTO)
    texto = next(v.texto for v in (*f.falta_comprobar.principales, *f.falta_comprobar.otros) if v.codigo == "solo_vinculo_indirecto")
    assert "solo vínculo indirecto: no mide el hecho" in texto
    assert "sin_dato_oficial" not in codigos(f) and "sin vínculo en la tabla de contexto" not in json.dumps(f.model_dump(), ensure_ascii=False)
    # un grupo sin ningún vínculo conserva el vacío original
    g = hacer(con, emb, h.G_CIFRAS)
    assert "sin dato oficial vinculado (el tema no tiene un indicador oficial asignado)" in [v.texto for v in (*g.falta_comprobar.principales, *g.falta_comprobar.otros)]


def test_los_tres_vacios_mas_importantes_van_arriba_en_el_orden_de_la_configuracion(con, emb) -> None:
    f = hacer(con, emb, h.G_CIFRAS)
    orden = CFG.vacios.orden_importancia
    todos = [v.codigo for v in (*f.falta_comprobar.principales, *f.falta_comprobar.otros)]
    assert todos == sorted(todos, key=orden.index)
    assert len(f.falta_comprobar.principales) == CFG.vacios.principales == 3
    assert todos[:3] == [v.codigo for v in f.falta_comprobar.principales] and [v.codigo for v in f.falta_comprobar.otros] == ["subtema_desconocido"]
    desplegable = [l for l in vista(f).secciones[3].lineas if l.desplegable]
    assert desplegable and all(l.nivel >= 1 for l in desplegable)


def test_cada_vacio_trae_su_verificacion_sugerida(con, emb) -> None:
    f = hacer(con, emb, h.G_CIFRAS)
    for v in (*f.falta_comprobar.principales, *f.falta_comprobar.otros):
        assert v.verificacion == CFG.vacios.catalogo[v.codigo].verificacion and v.texto


# ------------------------------------------------------------------ fuentes sugeridas


def test_las_fuentes_sugeridas_salen_del_subtema_y_nunca_son_evidencia(con, emb) -> None:
    f = hacer(con, emb, h.G_COMPLETO)
    nombres = [s.nombre for s in f.falta_comprobar.fuentes_sugeridas]
    assert nombres == CFG.fuentes.por_subtema["inflacion_precios"]
    assert f.falta_comprobar.aviso_fuentes == CFG.fuentes.nota
    for grupo in GRUPOS:
        for modalidad in MODALIDADES:
            x = hacer(con, emb, grupo, modalidad)
            sugeridas = {s.nombre for s in x.falta_comprobar.fuentes_sugeridas}
            respaldo = json.dumps(x.respaldado.model_dump(), ensure_ascii=False)
            assert not any(s in respaldo for s in sugeridas), (grupo, modalidad)
            assert not any(s.nombre in c.formato() for s in x.falta_comprobar.fuentes_sugeridas for l in x.respaldado.declaraciones for c in l.citas)
            md_lineas = lineas_de_markdown(a_markdown(x))
            assert not any(re.search(r"\b(IND|SIS|SBP|NOT|GRP)-\S+ · ", l) for l in md_lineas if any(s in l for s in sugeridas))     # sin formato de cita (D-37)


def test_sin_subtema_solo_hay_fuentes_del_tema_d92(con, emb) -> None:
    f = hacer(con, emb, h.G_CIFRAS)
    assert [s.nombre for s in f.falta_comprobar.fuentes_sugeridas] == CFG.fuentes.por_tema["servicios_publicos"]
    assert {s.origen for s in f.falta_comprobar.fuentes_sugeridas} == {"tema"}


@pytest.mark.parametrize("subtema", [None, "sin_subtema", "subtema_que_no_existe"])
def test_fuentes_sugeridas_sin_subtema_conocido_usan_solo_el_tema(subtema) -> None:
    mod = cargar_modalidad("editorial")
    assert [s.nombre for s in fuentes_sugeridas("logistica", subtema, mod, CFG)] == CFG.fuentes.por_tema["logistica"]
    assert fuentes_sugeridas(None, None, mod, CFG) == []                  # ni tema ni subtema: ninguna, y el vacío ya lo dice


def test_la_banca_agrega_sus_fuentes_extra_al_final_y_sin_repetir() -> None:
    e = fuentes_sugeridas("economia", "banca_calificaciones", cargar_modalidad("editorial"), CFG)
    b = fuentes_sugeridas("economia", "banca_calificaciones", cargar_modalidad("banca"), CFG)
    assert b[: len(e)] == e and [s.nombre for s in b[len(e):]] == ["Contraloría General de la República (INEC)"]    # SBP y MEF ya estaban
    assert [s.origen for s in b[len(e):]] == ["modalidad"]


# ------------------------------------------------------------------ acción recomendada


@pytest.mark.parametrize("modalidad", MODALIDADES)
@pytest.mark.parametrize("grupo", GRUPOS)
def test_la_accion_sale_de_la_tabla_de_la_modalidad_y_nunca_habilita_publicar(con, emb, grupo, modalidad) -> None:
    f = hacer(con, emb, grupo, modalidad)
    celda = getattr(getattr(cargar_modalidad(modalidad).tabla_acciones, f.accion_recomendada.rango), f.accion_recomendada.estado_evidencia)
    assert (f.accion_recomendada.accion, f.accion_recomendada.motivo) == (celda.accion, celda.motivo)
    assert f.accion_recomendada.habilita_publicar is False
    accion = "\n".join(l.texto for l in vista(f).secciones[4].lineas)      # la acción y sus pasos; «publicada» puede estar en el texto de un vacío
    assert accion and not FORMAS_DE_PUBLICAR.search(accion) and "habilita" not in accion.replace("no aprueba", "")


def test_los_siguientes_pasos_se_derivan_de_los_vacios_mas_importantes(con, emb) -> None:
    f = hacer(con, emb, h.G_CIFRAS)
    esperados = [CFG.vacios.catalogo[v.codigo].verificacion for v in f.falta_comprobar.principales][: CFG.siguientes_pasos.maximo]
    assert f.accion_recomendada.siguientes_pasos == esperados and esperados
    assert hacer(con, emb, h.G_COMPLETO).accion_recomendada.siguientes_pasos == []


def test_la_ficha_no_modifica_el_puntaje_ni_el_estado_calculados_por_e1_10(con, emb) -> None:
    f = hacer(con, emb, h.G_CIFRAS)
    p = con.execute("SELECT puntaje, rango, posicion FROM puntajes WHERE id_grupo = ?", [h.G_CIFRAS]).fetchone()
    e = con.execute("SELECT estado FROM evidencia WHERE id_grupo = ?", [h.G_CIFRAS]).fetchone()
    assert (f.puntaje.puntaje, f.puntaje.rango, f.puntaje.posicion) == p and f.accion_recomendada.estado_evidencia == e[0]
    assert set(f.puntaje.componentes) == {"R", "I", "U", "N", "E"} and f.puntaje.habilita_publicacion is False


# ------------------------------------------------------------------ misma ficha, distinta modalidad


def _sin(d: Any, *claves: str) -> Any:
    d = json.loads(json.dumps(d))
    for ruta in claves:
        *padre, hoja = ruta.split(".")
        x = d
        for k in padre:
            x = x[k]
        x.pop(hoja)
    return d


@pytest.mark.parametrize("grupo", GRUPOS)
def test_misma_ficha_distinta_modalidad_solo_cambian_accion_medio_de_referencia_y_fuentes_extra(con, emb, grupo) -> None:
    e, b = hacer(con, emb, grupo, "editorial"), hacer(con, emb, grupo, "banca")
    # E2-01: el puntaje se calcula por modalidad (I usa el alcance por sector en banca), así que P, el rango y el desglose de I pueden diferir;
    # R, U, N y E no dependen de la modalidad.
    saca = ("modalidad", "accion_recomendada.accion", "accion_recomendada.motivo", "accion_recomendada.rango", "quien_lo_reporta.medio_referencia",
            "falta_comprobar.fuentes_sugeridas", "puntaje")
    de, db_ = _sin(e.model_dump(), *saca), _sin(b.model_dump(), *saca)
    for d in (de, db_):          # «subtema no determinado» habla del alcance del subtema, que en banca no entra en I (usa el sector): solo lo emite la editorial
        for lista in ("principales", "otros"):
            d["falta_comprobar"][lista] = [v for v in d["falta_comprobar"][lista] if v["codigo"] != "subtema_desconocido"]
    assert de == db_
    assert "subtema_desconocido" not in codigos(b)
    assert {k: v.model_dump() for k, v in e.puntaje.componentes.items() if k != "I"} == {k: v.model_dump() for k, v in b.puntaje.componentes.items() if k != "I"}
    assert e.modalidad == "editorial" and b.modalidad == "banca"
    assert b.quien_lo_reporta.medio_referencia is None
    base_e = [s for s in e.falta_comprobar.fuentes_sugeridas]
    assert [s for s in b.falta_comprobar.fuentes_sugeridas if s.origen != "modalidad"] == base_e and all(s.origen != "modalidad" for s in base_e)


def test_la_accion_de_cada_modalidad_sale_del_rango_de_su_propia_corrida_y_el_estado_es_el_mismo(con, emb) -> None:
    e, b = hacer(con, emb, h.G_CIFRAS, "editorial"), hacer(con, emb, h.G_CIFRAS, "banca")
    assert e.accion_recomendada.accion != b.accion_recomendada.accion
    assert e.accion_recomendada.estado_evidencia == b.accion_recomendada.estado_evidencia
    assert e.accion_recomendada.rango == e.puntaje.rango and b.accion_recomendada.rango == b.puntaje.rango      # cada acción sale del rango de su propia corrida


def test_no_hay_if_modalidad_en_el_codigo_de_la_ficha() -> None:
    raiz = Path(__file__).resolve().parent.parent
    for ruta in (raiz / "src" / "ficha.py", raiz / "src" / "esquemas.py"):
        assert not re.search(r"if\s+[^\n]*modalidad\s*(==|!=|in)\s*[\"'(\[]", ruta.read_text(encoding="utf-8")), ruta


# ------------------------------------------------------------------ Markdown, vista y fichas.jsonl


@pytest.mark.parametrize("modalidad", MODALIDADES)
@pytest.mark.parametrize("grupo", GRUPOS)
def test_el_markdown_exportado_contiene_exactamente_lo_mismo_que_la_ficha_de_la_app(con, emb, grupo, modalidad) -> None:
    f = hacer(con, emb, grupo, modalidad)
    v = vista(f)
    md = a_markdown(f)
    esperadas = [escapar_markdown(l.texto) for s in v.secciones for l in s.lineas]
    assert lineas_de_markdown(md) == esperadas                                       # mismas líneas, mismo orden, nada de más (con el Markdown de los datos escapado)
    sin_vinetas = [l for l in md.splitlines() if l.strip() and not re.match(r"^ *- ", l)]
    assert sin_vinetas == [f"# Ficha de evidencia · {escapar_markdown(v.id_grupo)}", f"**{v.marca}**", *[f"## {s.titulo}" for s in v.secciones]]
    assert a_markdown(f) == md                                                      # determinista


def test_ninguna_linea_de_la_vista_tiene_saltos_de_linea(con, emb) -> None:
    for g in GRUPOS:
        assert all("\n" not in l.texto for s in vista(hacer(con, emb, g)).secciones for l in s.lineas)


@pytest.mark.parametrize("modalidad", MODALIDADES)
def test_la_linea_de_fichas_jsonl_trae_los_campos_del_contrato(con, emb, modalidad) -> None:
    f = hacer(con, emb, h.G_COMPLETO, modalidad)
    linea = a_linea_jsonl(f)
    assert "\n" not in linea
    r = json.loads(linea)
    for campo in ("id_caso", "modalidad", "ids_fuente", "afirmaciones", "citas", "puntaje", "componentes", "estado_evidencia", "borrador", "estado_revision"):
        assert campo in r
    assert r["modalidad"] == modalidad and r["borrador"] is True and r["id_caso"] is None and r["estado_revision"] is None   # E1-16 los asigna
    assert r["estado_evidencia"] == f.accion_recomendada.estado_evidencia and r["puntaje"] == f.puntaje.puntaje
    assert set(r["componentes"]) == {"R", "I", "U", "N", "E"}
    assert {"NOT-c000000001", "IND-PAN-FP.CPI.TOTL.ZG-2024"} <= set(r["ids_fuente"])
    assert all(set(c) == {"id", "campo"} for c in r["citas"]) and r["afirmaciones"]
    assert Ficha.model_validate(r["ficha"]) == f                                    # lo que se guarda reconstruye la ficha


# ------------------------------------------------------------------ CLI


@pytest.mark.parametrize("modalidad", MODALIDADES)
def test_la_cli_imprime_la_ficha_con_las_cinco_partes(base, base_banca, emb, capsys, modalidad, monkeypatch) -> None:
    monkeypatch.setattr(modulo, "_embeddings", lambda: emb)
    base = {"editorial": base, "banca": base_banca}[modalidad]
    assert modulo.main(["--grupo", h.G_CIFRAS, "--modalidad", modalidad, "--base", str(base)]) == 0
    salida = capsys.readouterr().out
    for titulo in [s.titulo for s in vista(construir_ficha(h.G_CIFRAS, modalidad, db.conectar(base, solo_lectura=True), emb=emb)).secciones]:
        assert f"## {titulo}" in salida
    assert h.G_CIFRAS in salida and "basado únicamente en titular/metadatos" in salida


def test_la_cli_con_un_grupo_inexistente_falla_con_mensaje(base, emb, capsys, monkeypatch) -> None:
    monkeypatch.setattr(modulo, "_embeddings", lambda: emb)
    assert modulo.main(["--grupo", "GRP-no-existe", "--base", str(base)]) == 1
    assert "GRP-no-existe" in capsys.readouterr().err


def test_la_cli_rechaza_una_modalidad_desconocida(base, capsys) -> None:
    with pytest.raises(SystemExit):
        modulo.main(["--grupo", h.G_CIFRAS, "--modalidad", "otra", "--base", str(base)])


def test_la_cli_con_formato_jsonl_imprime_una_sola_linea_valida(base, emb, capsys, monkeypatch) -> None:
    monkeypatch.setattr(modulo, "_embeddings", lambda: emb)
    assert modulo.main(["--grupo", h.G_COMPLETO, "--formato", "jsonl", "--base", str(base)]) == 0
    (linea,) = capsys.readouterr().out.strip().splitlines()
    assert json.loads(linea)["ficha"]["id_grupo"] == h.G_COMPLETO


def test_construir_ficha_con_un_grupo_sin_puntaje_pide_correr_src_puntaje(tmp_path, emb) -> None:
    ruta = tmp_path / "vacia.duckdb"
    db.guardar_todo(ruta, {"grupos": [fila_grupo("GRP-x", ["NOT-x000000001"], "Titular", 1)]})
    c = db.conectar(ruta, solo_lectura=True)
    try:
        with pytest.raises(LookupError, match="src.puntaje"):
            construir_ficha("GRP-x", "editorial", c, emb=emb)
    finally:
        c.close()


# ------------------------------------------------------------------ configuración


def test_la_modalidad_banca_esta_completa_y_usa_el_mismo_modelo_que_la_editorial() -> None:
    e, b = cargar_modalidad("editorial"), cargar_modalidad("banca")
    assert type(e) is type(b) and b.parcial is False and e.parcial is False and b.medio_referencia is None
    celdas = [getattr(getattr(b.tabla_acciones, r), s) for r in ("bajo", "medio", "alto") for s in ("insuficiente", "parcial", "suficiente")]
    assert len(celdas) == 9 and not any(FORMAS_DE_PUBLICAR.search(f"{c.accion} {c.motivo}") for c in celdas)
    texto = " ".join(f"{c.accion} {c.motivo}" for c in celdas).lower()
    for prohibida in (*cargar_restricciones().grupos["banca"].get("recomendacion", []), "pérdida", "impago", "exposición", "cartera", "alerta"):
        assert prohibida not in texto, prohibida
    assert getattr(b.tabla_acciones.alto, "suficiente").accion == "Incluir en el boletín como observación"
    assert b.fuentes_sugeridas_extra and e.fuentes_sugeridas_extra == []


def test_verificacion_yaml_esta_registrado_y_la_configuracion_completa_valida() -> None:
    assert "verificacion" in CARGADORES and "verificacion" in validar_todo()


def test_verificacion_cubre_todos_los_subtemas_y_temas() -> None:
    from src.configuracion import cargar_temas

    temas = cargar_temas()
    assert set(CFG.fuentes.por_tema) == set(temas.temas)
    assert set(CFG.fuentes.por_subtema) == {s for t in temas.temas.values() for s in t.subtemas}


def test_verificacion_rechaza_claves_desconocidas_y_un_orden_que_no_coincide_con_el_catalogo(tmp_path) -> None:
    import shutil

    import yaml

    from src.configuracion import cargar_verificacion as cargar

    datos = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "verificacion.yaml").read_text(encoding="utf-8"))

    def con(cambio) -> Path:
        d = json.loads(json.dumps(datos))
        cambio(d)
        carpeta = tmp_path / str(len(list(tmp_path.iterdir())))
        carpeta.mkdir()
        (carpeta / "verificacion.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        return carpeta

    with pytest.raises(ErrorDeConfiguracion, match="no_existe"):
        cargar(con(lambda d: d["vacios"].update(no_existe=1)))
    with pytest.raises(ErrorDeConfiguracion, match="orden_importancia"):
        cargar(con(lambda d: d["vacios"]["orden_importancia"].pop()))
    with pytest.raises(ErrorDeConfiguracion, match="publicar"):
        cargar(con(lambda d: d["vacios"]["catalogo"]["sin_dato_oficial"].update(verificacion="Publicar el dato ya.")))
    shutil.rmtree(tmp_path)


def test_la_coherencia_detecta_un_subtema_sin_fuentes(tmp_path) -> None:
    import shutil

    import yaml

    from src.configuracion import CARPETA_CONFIG, validar_coherencia

    carpeta = tmp_path / "config"
    shutil.copytree(CARPETA_CONFIG, carpeta)
    datos = yaml.safe_load((carpeta / "verificacion.yaml").read_text(encoding="utf-8"))
    del datos["fuentes"]["por_subtema"]["sismos"]
    datos["fuentes"]["por_subtema"]["subtema_falso"] = ["X"]
    (carpeta / "verificacion.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    problemas = " | ".join(validar_coherencia(carpeta))
    assert "sin fuentes sugeridas para el subtema sismos" in problemas and "subtema inexistente" in problemas and "subtema_falso" in problemas


# ------------------------------------------------------------------ revisión del PR #24 (X23, X24, M1, M2, m3, m4)


def _copia_editable(base: Path, tmp_path: Path) -> Path:
    ruta = tmp_path / "copia.duckdb"
    shutil.copy(base, ruta)
    return ruta


def _construir_desde(ruta: Path, emb, grupo: str = h.G_SOLO) -> Ficha:
    c = db.conectar(ruta, solo_lectura=True)
    try:
        return construir_ficha(grupo, "editorial", c, emb=emb)
    finally:
        c.close()


@pytest.mark.parametrize("grupo", GRUPOS)
def test_x23_el_texto_entre_comillas_de_una_declaracion_es_igual_al_campo_citado(con, emb, grupo) -> None:
    f = hacer(con, emb, grupo)
    for d in f.respaldado.declaraciones:
        (cita,) = d.citas
        (valor,) = con.execute(f'SELECT "{cita.campo}" FROM noticias WHERE id_noticia = ?', [cita.id]).fetchone()
        (citado,) = re.findall(r"«(.*)»", d.texto)
        assert citado == valor, (cita.formato(), citado, valor)


def test_x23_cuando_titulo_limpio_difiere_de_titulo_se_cita_titulo_limpio(tmp_path, base, emb) -> None:
    ruta = _copia_editable(base, tmp_path)
    c = db.conectar(ruta)
    c.execute("UPDATE noticias SET titulo = 'Combustible  -  Xinhua', titulo_limpio = 'Combustible' WHERE id_noticia = 'NOT-5000000001'")
    c.close()
    (d,) = _construir_desde(ruta, emb).respaldado.declaraciones
    assert d.citas[0].campo == "titulo_limpio" and "«Combustible»" in d.texto


def test_x24_la_linea_de_conteo_no_llama_hecho_a_lo_que_reportan_los_titulares(con, emb) -> None:
    for g in GRUPOS:
        f = hacer(con, emb, g)
        textos = [x.texto for x in (*f.respaldado.reportes, *f.respaldado.declaraciones)] + [l.texto for s in vista(f).secciones for l in s.lineas]
        assert not any("este hecho" in t for t in textos), g
        assert any(re.search(r"reportan? este tema", t) for t in (x.texto for x in f.respaldado.reportes))


def test_m1_una_linea_no_puede_tener_saltos_de_linea() -> None:
    assert Linea("uno\ndos\r\n\n## 5 · Acción recomendada").texto == "uno dos ## 5 · Acción recomendada"


def test_m1_un_titular_con_enlace_html_y_salto_de_linea_no_inyecta_markdown(tmp_path, base, emb) -> None:
    malo = "Sube [clic aquí](https://evil.example) <img src=x onerror=1> *negrita*\n## 5 · Acción recomendada\n- Acción: Producir borrador"
    ruta = _copia_editable(base, tmp_path)
    c = db.conectar(ruta)
    c.execute("UPDATE noticias SET titulo_limpio = ?, titulo = ? WHERE id_noticia = 'NOT-5000000001'", [malo, malo])
    c.close()
    f = _construir_desde(ruta, emb)
    md = a_markdown(f)
    assert len(re.findall(r"^## 5 ", md, flags=re.M)) == 1                     # solo el encabezado verdadero
    assert not re.search(r"(?<!\\)\]\(", md) and not re.search(r"(?<!\\)<", md)    # ningún enlace ni HTML activo: los corchetes y < quedan escapados
    assert "\\[clic aquí\\](" in md and "\\<img" in md
    permitido = re.compile(r"^(# Ficha de evidencia · .*|\*\*.*\*\*|## \d · .*| *- .*|)$")
    assert all(permitido.match(l) for l in md.splitlines())
    assert all(l.startswith(("  ", "- ", "#", "**")) or not l for l in md.splitlines())
    assert not [l for l in md.splitlines() if l.startswith("- Acción: Producir")]


def test_m2_los_vacios_de_la_ficha_son_los_que_guardo_e1_10_sin_recalcular(con, emb) -> None:
    for g in GRUPOS:
        f = hacer(con, emb, g)
        guardados = {}
        for tabla in ("puntajes", "evidencia"):
            (js,) = con.execute(f"SELECT vacios FROM {tabla} WHERE id_grupo = ?", [g]).fetchone()
            guardados.update({x["codigo"]: x["texto"] for x in json.loads(js)})
        en_ficha = {v.codigo: v.texto for v in (*f.falta_comprobar.principales, *f.falta_comprobar.otros)}
        assert en_ficha == guardados, g


def test_m2_los_cuatro_vacios_nuevos_estan_en_la_tabla_evidencia(con) -> None:
    def en(grupo: str) -> set[str]:
        (js,) = con.execute("SELECT vacios FROM evidencia WHERE id_grupo = ?", [grupo]).fetchone()
        return {x["codigo"] for x in json.loads(js)}

    assert "solo_vinculo_indirecto" in en(h.G_INDIRECTO) and "sin_dato_oficial" not in en(h.G_INDIRECTO)
    assert "cifra_discrepante" in en(h.G_DISCREPANCIA) and "cifra_periodo_distinto" in en(h.G_PERIODO)
    assert "evento_sin_revisar" in en(h.G_SISMO) and "evento_sin_revisar" not in en(h.G_SISMO_REVISADO)


def test_m2_una_discrepancia_abierta_entre_el_titular_y_el_dato_oficial_impide_suficiente(con, emb) -> None:
    f = hacer(con, emb, h.G_DISCREPANCIA)
    assert f.accion_recomendada.estado_evidencia == "parcial"          # 2 procedencias y dato oficial directo, pero la cifra discrepa
    assert hacer(con, emb, h.G_PERIODO).accion_recomendada.estado_evidencia == "suficiente"     # «período distinto» no bloquea
    assert hacer(con, emb, h.G_COMPLETO).accion_recomendada.estado_evidencia == "suficiente"


def test_m3_la_leyenda_declara_la_descripcion_si_se_uso_al_clasificar_o_agrupar(tmp_path, base, emb, monkeypatch) -> None:
    leyendas = cargar_restricciones().leyendas_alcance
    assert _construir_desde(base, emb).alcance == leyendas.titular_metadatos            # sin descripciones, nada que declarar
    ruta = _copia_editable(base, tmp_path)
    c = db.conectar(ruta)
    c.execute("UPDATE noticias SET descripcion = 'texto interno del RSS' WHERE id_noticia = 'NOT-5000000001'")
    c.close()
    assert _construir_desde(ruta, emb).alcance == leyendas.con_descripcion               # clasificacion.yaml usar_descripcion: true
    from src.configuracion import cargar_clasificacion

    sin = cargar_clasificacion().model_copy(update={"usar_descripcion": False})
    monkeypatch.setattr(modulo, "cargar_clasificacion", lambda *a, **k: sin)
    assert _construir_desde(ruta, emb).alcance == leyendas.titular_metadatos             # si no se usó, no se declara
    assert "texto interno del RSS" not in a_markdown(_construir_desde(ruta, emb))        # y nunca se muestra (D-31)


def test_m4_ningun_vacio_muestra_un_codigo_interno_ni_plurales_entre_parentesis(con, emb) -> None:
    for g in GRUPOS:
        f = hacer(con, emb, g)
        for v in (*f.falta_comprobar.principales, *f.falta_comprobar.otros):
            assert not re.search(r"\b[a-z]+_[a-z_]+\b", v.texto), v.texto
            assert "(s)" not in v.texto, v.texto
    assert "el tema no tiene un indicador oficial asignado" in " ".join(v.texto for v in hacer(con, emb, h.G_CIFRAS).falta_comprobar.principales)


def test_m4_los_siguientes_pasos_no_se_repiten_ni_son_casi_iguales(con, emb) -> None:
    for g in GRUPOS:
        pasos = hacer(con, emb, g).accion_recomendada.siguientes_pasos
        assert len(pasos) == len(set(pasos))
    todos = [hacer(con, emb, h.G_SIN_FECHA).accion_recomendada.siguientes_pasos]
    assert sum("Abrir el enlace" in p for p in todos[0]) == 1


@pytest.mark.parametrize(("valor", "decimales", "esperado"), [
    (3628535.0, 2, "3,628,535"),            # X109: antes «3.62854e+06»
    (3628535.456, 2, "3,628,535.46"),
    (0.69322, 2, "0.69"),
    (0.0000004, 2, "0"),                    # pequeño: sin notación científica
    (0.01741113516302623, 4, "0.0174"),
    (-1.55, 2, "-1.55"),
    (-1234567.891, 2, "-1,234,567.89"),
    (-0.001, 2, "0"),                       # nunca «-0»
    (30.0, 2, "30"),
    (2.5, 2, "2.5"),
    (999.999, 2, "1,000"),
])
def test_x109_formatear_cifra_sin_notacion_cientifica_con_miles_agrupados(valor, decimales, esperado) -> None:
    assert modulo.formatear_cifra(valor, decimales, ",") == esperado
    assert "e" not in modulo.formatear_cifra(valor, decimales, ",").lower()


def test_x109_el_separador_de_miles_viene_de_la_configuracion() -> None:
    assert modulo.formatear_cifra(1234567.0, 2, " ") == "1 234 567"
