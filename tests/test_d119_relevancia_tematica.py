"""D-119: R = peso_foco × foco × pertenencia temática.

La pertenencia es DISCRETA y sale de la ETIQUETA del clasificador (``tema_clasificado`` / ``tema_secundario``) frente a los
temas de la modalidad, nunca de su confianza (``tema_similitud``): la guarda de D-103 sigue vigente.
"""

from __future__ import annotations

import numpy as np
import pytest

from src import puntaje
from src.configuracion import PertenenciaTematica, Relevancia, cargar_temas
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, entrada, vector
from tests.prioridad_ayuda import miembro as _miembro

TEMAS = frozenset(cargar_temas().temas)
VALORES = REGLAS.relevancia.pertenencia_tematica

REGIONAL = "El Niño golpea Centroamérica"   # nota regional que no nombra a Panamá: foco otro_pais_afecta (D-84, D-135)


def miembro(*args, **campos):
    """Un titular que nombra a Panamá (foco 1): estas pruebas miden la pertenencia, no el foco graduado de D-135."""
    campos.setdefault("titulo", "Panamá anuncia una medida")
    return _miembro(*args, **campos)


def _r(miembros, reglas=REGLAS, temas=None):
    e = entrada("GRP-x", miembros, vectores=np.stack([vector(1.0, float(i + 1)) for i in range(len(miembros))]))
    return {p.id_grupo: p for p in puntaje.calcular_puntajes([e], reglas, CFG, AHORA, temas=temas)}["GRP-x"].componentes["R"]


def test_tema_principal_vale_el_maximo() -> None:
    valor, detalle = puntaje.pertenencia_de([miembro(tema="economia")], TEMAS, REGLAS)
    assert valor == VALORES.tema_principal == 1.0
    assert detalle["pertenencia_motivo"] == "tema_principal" and detalle["temas_coincidentes"] == ["economia"]


def test_solo_secundario_vale_menos() -> None:
    valor, detalle = puntaje.pertenencia_de([miembro(tema="no_es_panama", tema_secundario="economia")], TEMAS, REGLAS)
    assert valor == VALORES.solo_secundario == 0.6
    assert detalle["pertenencia_motivo"] == "solo_secundario" and detalle["temas_coincidentes"] == ["economia"]


@pytest.mark.parametrize("etiqueta", [None, "no_es_panama", "fuera_de_temas", "no_es_noticia", "inventado"])
def test_sin_tema_de_la_modalidad_vale_lo_minimo(etiqueta) -> None:
    valor, detalle = puntaje.pertenencia_de([miembro(tema=etiqueta, tema_secundario=etiqueta)], TEMAS, REGLAS)
    assert valor == VALORES.sin_tema == 0.3
    assert detalle["pertenencia_motivo"] == "sin_tema" and detalle["temas_coincidentes"] == []


def test_basta_un_titular_con_tema_principal_aunque_otros_no_lo_tengan() -> None:
    miembros = [miembro("NOT-1", tema="fuera_de_temas"), miembro("NOT-2", tema="turismo"), miembro("NOT-3", tema=None, tema_secundario="economia")]
    valor, detalle = puntaje.pertenencia_de(miembros, TEMAS, REGLAS)
    assert valor == VALORES.tema_principal and detalle["temas_coincidentes"] == ["turismo"]


def test_r_es_foco_por_pertenencia() -> None:
    regional = [miembro(regional=True, tema=None, titulo=REGIONAL)]
    c = _r(regional)
    assert c.valor == pytest.approx(REGLAS.relevancia.foco_otro_pais_afecta * VALORES.sin_tema) == pytest.approx(0.5 * 0.3)
    assert c.explicacion["foco"] == 0.5 and c.explicacion["pertenencia"] == 0.3
    assert _r([miembro(regional=False, tema="economia")]).valor == pytest.approx(1.0)
    assert _r([miembro(regional=False, tema=None)]).valor == pytest.approx(0.3)
    assert _r([miembro(regional=True, tema="no_es_panama", tema_secundario="economia", titulo=REGIONAL)]).valor == pytest.approx(0.5 * 0.6)


def test_r_no_lee_la_confianza_del_clasificador() -> None:
    bajas = _r([miembro(similitud=0.05, tema="economia", tema_secundario="turismo")])
    altas = _r([miembro(similitud=0.99, tema="economia", tema_secundario="turismo")])
    assert bajas.valor == altas.valor and bajas.explicacion == altas.explicacion
    assert not any("similitud" in k for k in altas.explicacion)
    sin_tema_alta = _r([miembro(similitud=0.99, tema=None)])
    assert sin_tema_alta.valor == VALORES.sin_tema


def test_los_valores_salen_de_la_configuracion() -> None:
    otros = PertenenciaTematica(tema_principal=0.9, solo_secundario=0.5, sin_tema=0.1)
    reglas = REGLAS.model_copy(update={"relevancia": REGLAS.relevancia.model_copy(update={"pertenencia_tematica": otros})})
    assert _r([miembro(tema=None)], reglas).valor == pytest.approx(0.1)
    assert _r([miembro(tema="economia")], reglas).valor == pytest.approx(0.9)
    assert _r([miembro(tema=None, tema_secundario="economia")], reglas).valor == pytest.approx(0.5)


def test_los_temas_de_la_modalidad_se_pasan_por_parametro() -> None:
    assert _r([miembro(tema="economia")], temas={"turismo"}).valor == VALORES.sin_tema
    assert _r([miembro(tema="economia")], temas={"economia"}).valor == VALORES.tema_principal


def test_la_configuracion_exige_valores_en_0_1_y_monotonos() -> None:
    with pytest.raises(ValueError):
        PertenenciaTematica(tema_principal=1.2, solo_secundario=0.6, sin_tema=0.3)
    with pytest.raises(ValueError, match="tema_principal >= solo_secundario >= sin_tema"):
        PertenenciaTematica(tema_principal=0.3, solo_secundario=0.6, sin_tema=1.0)
    with pytest.raises(ValueError):
        PertenenciaTematica(tema_principal=1.0, solo_secundario=0.6, sin_tema=0.3, confianza=0.5)
    with pytest.raises(ValueError):
        Relevancia(peso_foco=1.0, foco_panama_sujeto=1.0, foco_panama_implicito=0.7, foco_otro_pais_afecta=0.5, panama_actores=["ACP"])  # falta pertenencia_tematica
