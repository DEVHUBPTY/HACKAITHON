"""D-135: el foco de R es graduado por lo que dicen los titulares (Panamá sujeto 1.0 · implícito 0.7 · contexto 0.5).

Solo lee el texto, el medio y la marca regional: nunca la confianza del clasificador (D-103). El grupo toma el foco de su mejor titular.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from src import puntaje
from src.configuracion import Relevancia
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, entrada, miembro, vector

REL = REGLAS.relevancia


def _nivel(titulo: str, **campos) -> str:
    return puntaje.nivel_de_foco(miembro(titulo=titulo, **campos), REGLAS, CFG)[0]


def _r(miembros, id_grupo: str = "GRP-x", **campos):
    e = entrada(id_grupo, miembros, vectores=np.stack([vector(1.0, float(i + 1)) for i in range(len(miembros))]), **campos)
    return {p.id_grupo: p for p in puntaje.calcular_puntajes([e], REGLAS, CFG, AHORA)}[id_grupo].componentes["R"]


@pytest.mark.parametrize(
    "titulo",
    [
        "Panamá aprueba el presupuesto",
        "Cobre Panamá: gobierno de Canadá negocia",   # nombre propio con el país
        "Chiriquí | Investigan incendio en calle Quinta",   # provincia
        "Aprehenden a 10 personas en San Miguelito",   # distrito
        "Minsa enciende alarmas por diagnósticos",   # institución de panama_actores
        "Presidente panameño visitará Singapur y Vietnam",   # gentilicio, aun nombrando al exterior (C-10 D6)
        "Panamá reforzará su presencia marítima en Vietnam",
    ],
)
def test_nombrar_a_panama_un_lugar_o_un_actor_panameno_es_sujeto(titulo: str) -> None:
    assert _nivel(titulo) == puntaje.NIVEL_PANAMA_SUJETO


def test_un_medio_de_panama_sin_nombre_panameno_es_implicito() -> None:
    assert _nivel("Contenido exclusivo: El metro por la Tumba Muerto") == puntaje.NIVEL_PANAMA_IMPLICITO
    assert _nivel("Contenido exclusivo", pais_medio=None) == puntaje.NIVEL_PANAMA_IMPLICITO   # medio sin país: no se acusa de extranjero


def test_regional_o_medio_de_otro_pais_sin_nombrar_a_panama_es_contexto() -> None:
    assert _nivel("El Niño golpea Centroamérica", regional=True) == puntaje.NIVEL_OTRO_PAIS
    assert _nivel("US LNG exports increase in September", pais_medio="Estados Unidos") == puntaje.NIVEL_OTRO_PAIS


def test_un_lugar_extranjero_con_el_nombre_del_pais_no_cuenta_como_panama() -> None:
    assert _nivel("Hurricane hits Panama City Beach, Florida", pais_medio="Estados Unidos") == puntaje.NIVEL_OTRO_PAIS
    assert _nivel("Hurricane hits Panama City, Florida", regional=True) == puntaje.NIVEL_OTRO_PAIS
    assert puntaje.nivel_de_foco(miembro(titulo="Panama City recibe a la presidenta de Panamá"), REGLAS, CFG)[0] == puntaje.NIVEL_PANAMA_SUJETO


def test_ciudad_de_panama_es_un_lugar_de_panama_y_no_el_pais_pero_sigue_siendo_sujeto() -> None:
    nivel, nombres = puntaje.nivel_de_foco(miembro(titulo="Alerta en Ciudad de Panamá por lluvias"), REGLAS, CFG)
    assert nivel == puntaje.NIVEL_PANAMA_SUJETO and "Ciudad de Panamá" in nombres


def test_los_nombres_de_lugares_ambiguos_no_cuentan_sin_su_prefijo() -> None:
    assert _nivel("David Beckham visita el estadio") == puntaje.NIVEL_PANAMA_IMPLICITO   # «David» solo es lugar con prefijo locativo
    assert _nivel("Corte de energía en David") == puntaje.NIVEL_PANAMA_SUJETO


def test_el_grupo_toma_el_foco_de_su_mejor_titular() -> None:
    valor, detalle = puntaje.foco_de(
        [miembro("NOT-1", "El Niño golpea Centroamérica", regional=True), miembro("NOT-2", "Contenido exclusivo"), miembro("NOT-3", "Minsa informa")],
        REGLAS,
        CFG,
    )
    assert valor == REL.foco_panama_sujeto and detalle["foco_motivo"] == "panama_sujeto" and detalle["foco_titular"] == "NOT-3"
    assert detalle["titulares_por_nivel"] == {"panama_sujeto": 1, "panama_implicito": 1, "otro_pais_afecta": 1}
    valor, detalle = puntaje.foco_de([miembro("NOT-1", "El Niño golpea Centroamérica", regional=True), miembro("NOT-2", "Contenido exclusivo")], REGLAS, CFG)
    assert valor == REL.foco_panama_implicito and detalle["foco_motivo"] == "panama_implicito" and detalle["foco_titular"] == "NOT-2"


def test_un_grupo_sin_titulares_no_tiene_evidencia_de_tratar_de_panama() -> None:
    valor, detalle = puntaje.foco_de([], REGLAS, CFG)
    assert valor == REL.foco_otro_pais_afecta and detalle["foco_titular"] is None


def test_r_es_foco_graduado_por_pertenencia_y_la_explicacion_dice_por_que() -> None:
    c = _r([miembro("NOT-1", "Minsa enciende alarmas", tema="servicios_publicos")])
    assert c.valor == pytest.approx(1.0) and c.explicacion["foco_motivo"] == "panama_sujeto"
    assert c.explicacion["foco_terminos"] == ["Minsa"] and "Minsa enciende alarmas" in c.explicacion["foco_texto"]
    c = _r([miembro("NOT-1", "Contenido exclusivo", tema="economia")])
    assert c.valor == pytest.approx(REL.foco_panama_implicito) == pytest.approx(0.7) and "medio de Panamá" in c.explicacion["foco_texto"]
    c = _r([miembro("NOT-1", "El Niño golpea Centroamérica", regional=True, tema=None)])
    assert c.valor == pytest.approx(REL.foco_otro_pais_afecta * REGLAS.relevancia.pertenencia_tematica.sin_tema)


def test_r_no_lee_la_confianza_del_clasificador() -> None:
    bajas = _r([miembro(titulo="Contenido exclusivo", similitud=0.05)])
    altas = _r([miembro(titulo="Contenido exclusivo", similitud=0.99)])
    assert bajas.valor == altas.valor and bajas.explicacion == altas.explicacion


def test_un_grupo_sintetico_puntua_igual_y_no_cambia_a_los_reales() -> None:
    """Lo sintético (SYN-) se puntúa con la misma regla, pero R de un grupo no depende de los demás."""
    real = entrada("GRP-real", [miembro("NOT-1", "Contenido exclusivo")], vectores=np.stack([vector(1.0, 1.0)]))
    sintetico = replace(entrada("GRP-syn", [miembro("SYN-1", "Panamá anuncia una medida")], vectores=np.stack([vector(1.0, 2.0)])), sintetico=True)
    solo = {p.id_grupo: p.componentes["R"] for p in puntaje.calcular_puntajes([real], REGLAS, CFG, AHORA)}
    junto = {p.id_grupo: p.componentes["R"] for p in puntaje.calcular_puntajes([real, sintetico], REGLAS, CFG, AHORA)}
    assert solo["GRP-real"] == junto["GRP-real"]
    assert junto["GRP-syn"].explicacion["foco_motivo"] == "panama_sujeto"


def test_la_configuracion_exige_foco_monotono_y_actores_sin_vacios() -> None:
    base = {"peso_foco": 1.0, "foco_panama_sujeto": 1.0, "foco_panama_implicito": 0.7, "foco_otro_pais_afecta": 0.5, "panama_actores": ["ACP"],
            "pertenencia_tematica": REL.pertenencia_tematica.model_dump()}
    assert Relevancia(**base)
    with pytest.raises(ValueError, match="foco_panama_sujeto >= foco_panama_implicito"):
        Relevancia(**{**base, "foco_panama_implicito": 1.0, "foco_panama_sujeto": 0.9})
    with pytest.raises(ValueError, match="foco_panama_sujeto >= foco_panama_implicito"):
        Relevancia(**{**base, "foco_panama_implicito": 0.4})
    with pytest.raises(ValueError, match="repetidos"):
        Relevancia(**{**base, "panama_actores": ["ACP", "acp"]})
    with pytest.raises(ValueError, match="vacío"):
        Relevancia(**{**base, "panama_actores": ["ACP", " "]})
    with pytest.raises(ValueError):
        Relevancia(**{**base, "confianza": 0.5})
