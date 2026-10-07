"""E1-12 · Integración con la Ficha real (E1-10b): ``desde_ficha`` y ``fuentes_y_verificaciones``. Sin LLM real."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src import db, embeddings
from src.configuracion import cargar_restricciones
from src.esquemas import Ficha, LineaRespaldo, VacioFicha
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
        assert r.campo_texto == t.campo_titular and r.campos == {t.campo_titular: t.titular} and r.contexto["medio"] == t.medio
        assert r.idioma == t.idioma


def test_solo_son_citables_los_campos_que_la_ficha_cita_y_cada_dato_oficial_lleva_su_propio_valor_y_anio(con, emb) -> None:
    visto = False
    for f in fichas(con, emb):
        e = desde_ficha(f)
        citados = {(c.id, c.campo) for linea in lineas(f) for c in linea.citas} | {(t.id_noticia, t.campo_titular) for t in f.quien_lo_reporta.titulares}
        for r in e.registros:
            assert {(r.id, k) for k in r.campos} <= citados, (r.id, r.campos)  # nada citable que la ficha no cite
            assert "indicador" not in r.campos and "anio" not in r.campos
        vistos: set[str] = set()
        for linea in f.respaldado.datos_oficiales:
            assert linea.indicador, "la ficha debe nombrar el indicador"
            for c in linea.citas:
                if c.id in vistos:
                    continue  # un ID citado por dos líneas conserva el valor de la primera
                vistos.add(c.id)
                reg = next(r for r in e.registros if r.id == c.id)
                if c.id.startswith("IND-"):
                    visto = True
                    assert reg.contexto["indicador"] == linea.indicador
                    assert reg.contexto["anio"] == c.id.rsplit("-", 1)[1]  # el año del ID, siempre presente
                    assert reg.campos["valor"] == linea.texto or f"{reg.contexto['anio']}: {reg.campos['valor']}" in linea.texto
    assert visto


def test_cada_id_oficial_tiene_el_valor_de_su_propio_anio_y_no_el_de_toda_la_linea(con, emb) -> None:
    f = construir_ficha(h.G_COMPLETO, "editorial", con, emb=emb)
    e = desde_ficha(f)
    valores = {r.id: r.campos["valor"] for r in e.registros if r.id.startswith("IND-")}
    assert len(valores) >= 3 and valores["IND-COL-FP.CPI.TOTL.ZG-2024"] != valores["IND-PAN-FP.CPI.TOTL.ZG-2024"]
    assert all(";" not in v and "·" not in v for v in valores.values())


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
    titulares = [r for r in e.registros if "medio" in r.contexto and r.campo_texto in r.campos]
    afirmaciones: list[dict[str, Any]] = [
        {"id": f"A{n}", "tipo": "declaración", "texto": f"{r.contexto['medio']} reporta un titular", "citas": [{"id": r.id, "campo": r.campo_texto}], "base": []}
        for n, r in enumerate(titulares, start=1)
    ]
    afirmaciones.append({"id": f"A{len(afirmaciones) + 1}", "tipo": "inferencia", "texto": "El tema podría merecer seguimiento", "citas": [], "base": ["A1"]})
    ids = [v.id for v in e.vacios] or ["SIN"]
    preguntas = [{"texto": f"¿Qué falta para {ids[i % len(ids)]}?", "vacio": ids[i % len(ids)]} for i in range(3)]
    medio = titulares[0].contexto["medio"]
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
    if not [*f.falta_comprobar.principales, *f.falta_comprobar.otros]:       # determinista: una ficha sin vacíos recibe uno fijo, así el caso siempre corre
        fijo = VacioFicha(codigo="V-FIJO", texto="Falta una fuente oficial que confirme el hecho", verificacion="Consultar la fuente oficial")
        f = f.model_copy(update={"falta_comprobar": f.falta_comprobar.model_copy(update={"principales": [fijo]})})
    e = desde_ficha(f).model_copy(update={"accion": "Investigar ya"})
    assert e.vacios
    r = generar(e, _proveedor_para(e))
    assert r.tipo == "investigacion" and r.paquete is not None and len(r.paquete.preguntas) == 3
    assert all(q.vacio in {v.codigo for v in [*f.falta_comprobar.principales, *f.falta_comprobar.otros]} for q in r.paquete.preguntas)
    assert not any(v.origen == "seccion" for v in r.paquete.vacios)
