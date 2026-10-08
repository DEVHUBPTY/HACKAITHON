"""D-124: N continua entre dos anclas (centroides, solo grupos anteriores dentro de la ventana) y U con fecha imputada."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src import puntaje
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, entrada, miembro, vector

BAJA = REGLAS.novedad.ancla_baja
ALTA = REGLAS.agrupacion.umbral_similitud
VENTANA_H = REGLAS.novedad.ventana_dias * 24


def _con_similitud(s: float) -> np.ndarray:
    """Vector cuyo coseno con ``vector(1, 0)`` es exactamente ``s``."""
    return np.stack([vector(s, math.sqrt(1 - s * s))])


def _n_del_nuevo(similitud: float, hace_previo: float = 100, hace_nuevo: float = 10) -> puntaje.Componente:
    entradas = [
        entrada("GRP-previo", [miembro("NOT-p", publicado_hace=hace_previo)], vectores=np.stack([vector(1, 0)])),
        entrada("GRP-nuevo", [miembro("NOT-n", publicado_hace=hace_nuevo)], vectores=_con_similitud(similitud)),
    ]
    return {p.id_grupo: p for p in puntaje.calcular_puntajes(entradas, REGLAS, CFG, AHORA)}["GRP-nuevo"].componentes["N"]


# ------------------------------------------------------------------ N · anclas


def test_las_anclas_son_a_priori_y_la_alta_es_el_umbral_de_agrupacion() -> None:
    assert BAJA < ALTA and puntaje.umbral_novedad(REGLAS) == ALTA


@pytest.mark.parametrize(("similitud", "esperado"), [(0.0, 1.0), (BAJA, 1.0), ((BAJA + ALTA) / 2, 0.5), (ALTA, 0.0), (0.95, 0.0)])
def test_n_es_lineal_entre_ancla_baja_y_alta(similitud: float, esperado: float) -> None:
    assert puntaje.novedad_de(similitud, BAJA, ALTA) == pytest.approx(esperado)
    assert _n_del_nuevo(similitud).valor == pytest.approx(esperado, abs=1e-6)


def test_n_es_monotona_no_creciente_con_la_similitud() -> None:
    valores = [puntaje.novedad_de(s / 100, BAJA, ALTA) for s in range(0, 101)]
    assert all(a >= b for a, b in zip(valores, valores[1:], strict=False))


def test_n_expone_las_anclas_y_la_ventana() -> None:
    e = _n_del_nuevo(0.6).explicacion
    assert (e["ancla_baja"], e["ancla_alta"], e["ventana_dias"]) == (BAJA, ALTA, REGLAS.novedad.ventana_dias)


def test_n_usa_el_centroide_del_grupo_no_un_titular_suelto() -> None:
    # el grupo nuevo tiene un titular idéntico al previo y otro ortogonal: su centroide queda a 45 grados (coseno 0.707 >= ALTA)
    previo = entrada("GRP-previo", [miembro("NOT-p", publicado_hace=100)], vectores=np.stack([vector(1, 0)]))
    mixto = entrada(
        "GRP-mixto", [miembro("NOT-1", publicado_hace=10), miembro("NOT-2", publicado_hace=10)],
        vectores=np.stack([vector(1, 0), vector(0, 1)]),
    )
    c = {p.id_grupo: p for p in puntaje.calcular_puntajes([previo, mixto], REGLAS, CFG, AHORA)}["GRP-mixto"].componentes["N"]
    assert c.explicacion["similitud_maxima"] == pytest.approx(math.sqrt(0.5), abs=1e-6)   # con el máximo por titular daría 1.0
    assert c.valor == puntaje.novedad_de(math.sqrt(0.5), BAJA, ALTA)


# ------------------------------------------------------------------ N · ventana y orden temporal


def test_un_grupo_anterior_fuera_de_la_ventana_no_descuenta() -> None:
    dentro = _n_del_nuevo(0.99, hace_previo=10 + VENTANA_H - 1)
    fuera = _n_del_nuevo(0.99, hace_previo=10 + VENTANA_H + 1)
    assert dentro.valor == pytest.approx(0.0, abs=1e-6) and dentro.explicacion["grupos_previos"] == 1
    assert fuera.valor == REGLAS.novedad.sin_grupos_previos and fuera.explicacion["grupos_previos"] == 0
    assert fuera.explicacion["similitud_maxima"] is None


def test_un_grupo_posterior_nunca_descuenta_al_anterior() -> None:
    entradas = [
        entrada("GRP-viejo", [miembro("NOT-v", publicado_hace=100)], vectores=np.stack([vector(1, 0)])),
        entrada("GRP-reciente", [miembro("NOT-r", publicado_hace=10)], vectores=np.stack([vector(1, 0.001)])),
    ]
    r = {p.id_grupo: p.componentes["N"] for p in puntaje.calcular_puntajes(entradas, REGLAS, CFG, AHORA)}
    assert r["GRP-viejo"].valor == REGLAS.novedad.sin_grupos_previos and r["GRP-viejo"].explicacion["grupos_previos"] == 0
    assert r["GRP-reciente"].valor < 0.01 and r["GRP-reciente"].explicacion["grupo_mas_parecido"] == "GRP-viejo"


def test_una_duplicacion_nunca_sube_n() -> None:
    lejos = _n_del_nuevo(0.2).valor
    assert all(_n_del_nuevo(s).valor <= lejos for s in (0.55, 0.65, 0.8, 0.99))


def test_un_grupo_sintetico_anterior_no_descuenta_la_novedad_de_uno_real_pero_si_la_suya() -> None:
    """C-06: los casos sintéticos de la demo nunca alteran el puntaje de los reales; el sintético sí se puntúa (y ve a los reales)."""
    from dataclasses import replace

    real_previo = entrada("GRP-a-real", [miembro("NOT-p", publicado_hace=100)], vectores=np.stack([vector(1, 0)]))
    sintetico = replace(entrada("GRP-b-syn", [miembro("SYN-1", publicado_hace=50)], vectores=np.stack([vector(1, 0)])), sintetico=True)
    real_nuevo = entrada("GRP-c-real", [miembro("NOT-n", publicado_hace=10)], vectores=np.stack([vector(1, 0)]))
    con = {p.id_grupo: p for p in puntaje.calcular_puntajes([real_previo, sintetico, real_nuevo], REGLAS, CFG, AHORA)}
    sin = {p.id_grupo: p for p in puntaje.calcular_puntajes([real_previo, real_nuevo], REGLAS, CFG, AHORA)}
    assert con["GRP-c-real"].componentes["N"].explicacion["grupos_previos"] == 1                  # solo el real anterior
    assert con["GRP-c-real"].componentes["N"].explicacion["grupo_mas_parecido"] == "GRP-a-real"
    for g in ("GRP-a-real", "GRP-c-real"):
        assert con[g].puntaje == sin[g].puntaje and con[g].componentes["N"].valor == sin[g].componentes["N"].valor
    assert con["GRP-b-syn"].componentes["N"].explicacion["grupo_mas_parecido"] == "GRP-a-real"   # el sintético sí tiene su propio puntaje


# ------------------------------------------------------------------ U · fecha imputada


def _u(*miembros_):
    return puntaje.urgencia(list(miembros_), AHORA, REGLAS)


def test_con_fecha_imputada_u_se_topa_y_lo_dice() -> None:
    c, vacios = _u(miembro("NOT-g", publicado_hace=None, detectado_hace=2))
    sin_tope = 1 - 2 / (REGLAS.urgencia.dias_nulo * 24)
    assert sin_tope > REGLAS.urgencia.tope_fecha_imputada
    assert c.valor == REGLAS.urgencia.tope_fecha_imputada
    e = c.explicacion
    assert e["fecha_imputada"] is True and e["fecha_origen"] == "deteccion" and e["valor_sin_tope"] == pytest.approx(sin_tope)
    assert e["tope_fecha_imputada"] == REGLAS.urgencia.tope_fecha_imputada
    assert any(v.codigo == "urgencia_sin_publicacion" for v in vacios)


def test_el_tope_no_sube_una_u_que_ya_es_menor() -> None:
    c, _ = _u(miembro("NOT-g", publicado_hace=None, detectado_hace=24 * 6))
    assert c.explicacion["fecha_imputada"] is True
    assert c.valor == pytest.approx(c.explicacion["valor_sin_tope"])
    assert c.valor < REGLAS.urgencia.tope_fecha_imputada


def test_con_fecha_de_publicacion_no_hay_tope_ni_bandera() -> None:
    c, vacios = _u(miembro("NOT-p", publicado_hace=2))
    assert c.valor == pytest.approx(1 - 2 / (REGLAS.urgencia.dias_nulo * 24))
    assert c.valor > REGLAS.urgencia.tope_fecha_imputada
    assert c.explicacion["fecha_imputada"] is False and c.explicacion["tope_fecha_imputada"] is None
    assert not vacios


def test_si_algun_titular_trae_publicacion_la_deteccion_no_activa_el_tope() -> None:
    c, _ = _u(miembro("NOT-1", publicado_hace=2), miembro("NOT-2", publicado_hace=None, detectado_hace=1))
    assert c.explicacion["fecha_imputada"] is False and c.explicacion["fecha_origen"] == "publicacion"
