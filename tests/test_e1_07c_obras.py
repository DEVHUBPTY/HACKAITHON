"""E1-07c (D-111): subtema ``obras_publicas`` dentro de ``servicios_publicos``. Catálogo, compuerta léxica y alcance de I."""

from __future__ import annotations

from pathlib import Path

import pytest

from src import contexto
from src.baseline import Baseline
from src.configuracion import cargar_reglas, cargar_temas, cargar_verificacion, cargar_vinculos
from src.puntaje import impacto
from tests.prioridad_ayuda import CFG, REGLAS, entrada

RAIZ = Path(__file__).resolve().parent.parent
TEMAS = cargar_temas().temas
SUB = cargar_vinculos().subtema
SERVICIOS = list(TEMAS["servicios_publicos"].subtemas)


def decidir(mas_cercano: str, titular: str) -> tuple[str | None, str | None]:
    return contexto.decidir_subtema([(mas_cercano, 0.83, 0.001)], [titular], SUB, SERVICIOS)


# ------------------------------------------------------------------ catálogo: el subtema vive en los cuatro YAML


def test_el_subtema_esta_en_servicios_publicos_y_en_ningun_otro_tema() -> None:
    assert "obras_publicas" in TEMAS["servicios_publicos"].subtemas
    assert all("obras_publicas" not in t.subtemas for k, t in TEMAS.items() if k != "servicios_publicos")
    assert len(TEMAS) == 6                                       # D-111: ningún tema nuevo


def test_justicia_y_elecciones_no_son_subtemas() -> None:
    todos = {s for t in TEMAS.values() for s in t.subtemas}
    assert not {s for s in todos if any(p in s for p in ("justicia", "corrupcion", "eleccion", "electoral"))}
    assert len(todos) == 39                                       # 38 de antes + obras_publicas


def test_el_subtema_tiene_prototipo_terminos_alcance_y_fuentes_en_el_yaml() -> None:
    assert TEMAS["servicios_publicos"].subtemas["obras_publicas"].prototipo
    assert SUB.terminos_por_subtema["obras_publicas"]
    assert 0 <= cargar_reglas().impacto.alcance_subtema["obras_publicas"] <= 1
    fuentes = cargar_verificacion().fuentes.por_subtema["obras_publicas"]
    assert "Ministerio de Obras Públicas" in fuentes and 1 <= len(fuentes) <= 3


def test_la_descripcion_del_tema_nombra_las_obras_publicas() -> None:
    assert "obras públicas" in TEMAS["servicios_publicos"].descripcion.lower()


def test_la_guia_define_el_subtema_y_su_frontera() -> None:
    guia = (RAIZ / "docs" / "guia_temas.md").read_text(encoding="utf-8").lower()
    assert "obras públicas" in guia and "carreteras" in guia and "puentes" in guia
    assert "justicia" in guia and "elecciones" in guia


# ------------------------------------------------------------------ compuerta léxica (D-92, X41, X53)


@pytest.mark.parametrize(
    "titular",
    [
        "MOP inicia la construcción de un puente vehicular sobre el río",
        "Rehabilitan la carretera Panamericana en el tramo de Darién",
        "Ministerio de Obras Públicas reporta avance de obras viales",
        "Contraloría advierte sobrecostos en obras del corredor",
        "Construcción de acueducto avanza en la comarca",
        "Concluyen las obras de la autopista Arraiján-La Chorrera",
    ],
)
def test_un_titular_que_nombra_una_obra_publica_asigna_el_subtema_aunque_no_sea_el_mas_cercano(titular: str) -> None:
    assert decidir("agua_potable", titular) == ("obras_publicas", "lexico")


@pytest.mark.parametrize(
    "titular",
    [
        "Pagan la factura con un sobrecosto de 20 %",                         # «sobrecosto» sin obra no respalda el subtema
        "Se estrena la obra de teatro en la capital",                          # «obra» suelta no es obra pública
        "La Chorrera proyecta renovar el parque con una inversión de 620 mil dólares",
    ],
)
def test_palabras_sueltas_ambiguas_no_respaldan_el_subtema(titular: str) -> None:
    assert decidir("agua_potable", titular) == (None, None)


def test_sin_termino_no_hay_subtema_aunque_sea_el_mas_cercano() -> None:
    assert contexto.decidir_subtema([("obras_publicas", 0.9, 0.5)], ["Gobierno anuncia plan para la capital"], SUB, SERVICIOS) == (None, None)


def test_obras_y_otro_subtema_en_el_mismo_titular_es_ambiguo() -> None:
    titular = "Policía resguarda la carretera tras un asalto a un camión"     # seguridad ciudadana + obras públicas
    assert decidir("obras_publicas", titular) == (None, None)


def test_el_acueducto_como_servicio_sigue_siendo_agua_potable() -> None:
    assert decidir("agua_potable", "Idaan repara el acueducto y restablece el suministro de agua") == ("agua_potable", "lexico")


def test_el_pedido_de_fondos_del_mop_ya_tiene_subtema_con_sustento() -> None:
    titular = "MOP solicita fondos para pagar compromisos y continuar obras en ejecución"
    assert decidir("agua_potable", titular) == ("obras_publicas", "lexico")


# ------------------------------------------------------------------ I usa el alcance del YAML


def test_i_toma_el_alcance_de_obras_publicas_del_yaml_y_no_es_el_neutro() -> None:
    comp, vacios = impacto(entrada("GRP-a", subtema="obras_publicas"), REGLAS, CFG)
    alcance = REGLAS.impacto.alcance_subtema["obras_publicas"]
    assert comp.explicacion["alcance_subtema"] == alcance
    assert alcance != CFG.impacto.alcance_subtema_desconocido
    assert not [v for v in vacios if v.codigo == "subtema_desconocido"]


def test_provisional_el_alcance_es_el_de_transporte_publico() -> None:
    # Decisión pendiente del dueño (spec E1-07c, pregunta 1): 0.8 provisional, igual que transporte público.
    a = REGLAS.impacto.alcance_subtema
    assert a["obras_publicas"] == a["transporte_publico"] == 0.8


# ------------------------------------------------------------------ baseline: mismas categorías, sin tema nuevo


def test_el_baseline_clasifica_una_obra_publica_en_servicios_publicos() -> None:
    assert Baseline(variante="guia").clasificar("Rehabilitan la carretera y un puente en Chiriquí").principal == "servicios_publicos"
