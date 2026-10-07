"""E1-12 · Integración con la Ficha real (E1-10b): ``desde_ficha`` y ``fuentes_y_verificaciones``. Sin LLM real."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src import db, embeddings
from src.configuracion import cargar_restricciones
from src.esquemas import Ficha, LineaRespaldo
from src.ficha import construir_ficha
from src.generacion import EntradaFicha, desde_ficha, fuentes_y_verificaciones, generar
from tests import ficha_ayuda as h
from tests.generacion_ayuda import ProveedorGuionado
from tests.motor_falso import MotorFalso, config_de_prueba

GRUPOS = (h.G_COMPLETO, h.G_CIFRAS, h.G_INDIRECTO, h.G_SIN_FECHA, h.G_RECIRCULADA, h.G_INYECCION, h.G_SISMO, h.G_DISCREPANCIA, h.G_SOLO, h.G_PERIODO, h.G_SISMO_REVISADO)


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def con(tmp_path_factory, emb):
    base = h.construir(tmp_path_factory.mktemp("integracion") / "senales.duckdb", emb)
    c = db.conectar(Path(base), solo_lectura=True)
    yield c
    c.close()


def fichas(con, emb) -> list[Ficha]:
    return [construir_ficha(g, "editorial", con, emb=emb) for g in GRUPOS]


def lineas(f: Ficha) -> list[LineaRespaldo]:
    r = f.respaldado
    return [*r.reportes, *r.datos_oficiales, *r.eventos_oficiales, *r.declaraciones]


@pytest.mark.parametrize("grupo", GRUPOS)
def test_toda_cita_de_la_ficha_se_resuelve_en_la_entrada_con_el_mismo_id_y_campo(con, emb, grupo) -> None:
    f = construir_ficha(grupo, "editorial", con, emb=emb)
    e = desde_ficha(f)
    por_id = {r.id: r for r in e.registros}
    for linea in lineas(f):
        for c in linea.citas:
            assert c.id in por_id and c.campo in por_id[c.id].campos, (c.id, c.campo)
    for t in f.quien_lo_reporta.titulares:
        r = por_id[t.id_noticia]
        assert r.campo_texto == t.campo_titular and r.campos[t.campo_titular] == t.titular and r.campos["medio"] == t.medio
        assert r.idioma == t.idioma


def test_el_dato_oficial_lleva_el_nombre_del_indicador_y_el_anio(con, emb) -> None:
    visto = False
    for f in fichas(con, emb):
        e = desde_ficha(f)
        for linea in f.respaldado.datos_oficiales:
            assert linea.indicador, "la ficha debe nombrar el indicador"
            for c in linea.citas:
                reg = next(r for r in e.registros if r.id == c.id)
                assert reg.campos["indicador"] == linea.indicador
                if len(linea.citas) == 1:
                    assert reg.campos["anio"].isdigit()
                visto = True
    assert visto


def test_el_campo_indicador_es_opcional_y_compatible_hacia_atras() -> None:
    from src.esquemas import Cita

    l = LineaRespaldo(tipo="hecho", texto="x", citas=[Cita(id="GRP-a", campo="n_titulares")])
    assert l.indicador is None


@pytest.mark.parametrize("grupo", GRUPOS)
def test_fuentes_y_verificaciones_son_identicas_a_las_de_la_ficha(con, emb, grupo) -> None:
    f = construir_ficha(grupo, "editorial", con, emb=emb)
    e = desde_ficha(f)
    assert e.fuentes_verificaciones == fuentes_y_verificaciones(f)
    esperadas = [v.verificacion for v in [*f.falta_comprobar.principales, *f.falta_comprobar.otros]]
    assert all(any(x in linea for linea in e.fuentes_verificaciones) for x in esperadas)
    assert all(f"Fuente sugerida: {s.nombre}" in e.fuentes_verificaciones for s in f.falta_comprobar.fuentes_sugeridas)
    assert e.fuentes_verificaciones[-1] == f.falta_comprobar.aviso_fuentes
    # y el paquete las entrega sin tocarlas
    p = generar(e.model_copy(update={"accion": "Investigar ya"}), _proveedor_para(e)).paquete
    assert p is not None and p.fuentes_verificaciones == e.fuentes_verificaciones


def test_vacios_accion_alcance_y_contradicciones_salen_de_la_ficha(con, emb) -> None:
    leyendas = cargar_restricciones().leyendas_alcance
    hubo_contradiccion = False
    for f in fichas(con, emb):
        e = desde_ficha(f)
        assert [v.id for v in e.vacios] == [v.codigo for v in [*f.falta_comprobar.principales, *f.falta_comprobar.otros]]
        assert e.accion == f.accion_recomendada.accion and e.id_caso == f.id_grupo
        assert e.uso_descripcion == (f.alcance == leyendas.con_descripcion)
        ids = {r.id for r in e.registros if r.campo_texto in r.campos}
        for c in e.contradicciones:
            hubo_contradiccion = True
            assert {c.id_a, c.id_b} <= ids and c.abierta
            titulos = {r.id: r.campos[r.campo_texto] for r in e.registros if r.campo_texto in r.campos}
            assert c.fragmento_a in titulos[c.id_a] and c.fragmento_b in titulos[c.id_b]
    assert hubo_contradiccion


# ------------------------------------------------------------------ preguntas de investigación con una ficha real


def _proveedor_para(e: EntradaFicha) -> ProveedorGuionado:
    """Un LLM falso que responde sobre la ficha real: una declaración atribuida por titular y una inferencia sin cifras."""
    titulares = [r for r in e.registros if "medio" in r.campos and r.campo_texto in r.campos]
    afirmaciones: list[dict[str, Any]] = [
        {"id": f"A{n}", "tipo": "declaración", "texto": f"{r.campos['medio']} reporta un titular", "citas": [{"id": r.id, "campo": r.campo_texto}], "base": []}
        for n, r in enumerate(titulares, start=1)
    ]
    afirmaciones.append({"id": f"A{len(afirmaciones) + 1}", "tipo": "inferencia", "texto": "El tema podría merecer seguimiento", "citas": [], "base": ["A1"]})
    ids = [v.id for v in e.vacios] or ["SIN"]
    preguntas = [{"texto": f"¿Qué falta para {ids[i % len(ids)]}?", "vacio": ids[i % len(ids)]} for i in range(3)]
    medio = titulares[0].campos["medio"]
    return ProveedorGuionado(
        afirmaciones={"afirmaciones": afirmaciones},
        titulo_trabajo={
            "titulo_trabajo": {"texto": f"{medio} reporta un tema por verificar", "afirmaciones": ["A1"]},
            "enfoque": [{"texto": "El tema podría merecer seguimiento.", "afirmaciones": [f"A{len(afirmaciones)}"]}],
            "preguntas": preguntas,
        },
    )


@pytest.mark.parametrize("grupo", GRUPOS)
def test_cada_pregunta_de_investigacion_referencia_un_vacio_existente_de_la_ficha(con, emb, grupo) -> None:
    f = construir_ficha(grupo, "editorial", con, emb=emb)
    e = desde_ficha(f).model_copy(update={"accion": "Investigar ya"})
    if not e.vacios:
        pytest.skip("la ficha no tiene vacíos: no hay preguntas que derivar")
    r = generar(e, _proveedor_para(e))
    assert r.tipo == "investigacion" and r.paquete is not None and len(r.paquete.preguntas) == 3
    assert all(q.vacio in {v.codigo for v in [*f.falta_comprobar.principales, *f.falta_comprobar.otros]} for q in r.paquete.preguntas)
    assert not any(v.origen == "seccion" for v in r.paquete.vacios)
