"""E1-07c (D-111, D-125): las obras públicas son del tema ``servicios_publicos``. Descripción, guía y baseline.

D-125 quitó los subtemas (incluido ``obras_publicas``): se conservan las pruebas del baseline (X79, X82) y de la definición.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.baseline import Baseline
from src.configuracion import cargar_temas

RAIZ = Path(__file__).resolve().parent.parent
TEMAS = cargar_temas().temas


def test_las_obras_publicas_no_son_un_tema_nuevo() -> None:
    assert len(TEMAS) == 6                                       # D-111/D-125: ningún tema nuevo


def test_la_descripcion_del_tema_nombra_las_obras_publicas() -> None:
    assert "obras públicas" in TEMAS["servicios_publicos"].descripcion.lower()


def test_la_guia_define_las_obras_publicas_y_su_frontera() -> None:
    guia = (RAIZ / "docs" / "guia_temas.md").read_text(encoding="utf-8").lower()
    assert "obras públicas" in guia and "carreteras" in guia and "puentes" in guia
    assert "justicia" in guia and "elecciones" in guia


# ------------------------------------------------------------------ baseline: mismas categorías, sin tema nuevo


def test_el_baseline_clasifica_una_obra_publica_en_servicios_publicos() -> None:
    assert Baseline(variante="guia").clasificar("Rehabilitan la carretera y un puente en Chiriquí").principal == "servicios_publicos"


@pytest.mark.parametrize(
    "titular",
    ["Habilitan un puente aéreo humanitario hacia Darién", "Gobierno anuncia puente festivo para el fin de semana"],
)
def test_x79_puente_aereo_y_puente_festivo_no_son_una_obra_en_el_baseline(titular: str) -> None:
    assert Baseline(variante="guia").clasificar(titular).principal == "sin_tema"


def test_x79_el_deslizamiento_que_daña_la_carretera_es_evento_natural_en_el_baseline() -> None:
    titular = "Deslizamiento destruye un tramo de la carretera a Boquete"           # regla 5 de la guía
    for variante in ("guia", "ampliado"):
        assert Baseline(variante=variante).clasificar(titular).principal == "eventos_naturales"


@pytest.mark.parametrize(
    "titular",
    [
        "Deslizamiento destruye un tramo de la carretera a Boquete",
        "Puente colapsa por sismo en Darién",
        "Inundación arrasa el puente de acceso a Metetí",
    ],
)
def test_x82_el_fenomeno_que_daña_la_obra_es_evento_natural(titular: str) -> None:
    assert Baseline(variante="guia").clasificar(titular).principal == "eventos_naturales"


@pytest.mark.parametrize(
    "titular",
    [
        "MOP repara la carretera antes de la temporada de lluvias",
        "Rehabilitan la carretera dañada por las lluvias del año pasado",
        "MOP emite alerta por cierre del puente de Las Américas",
    ],
)
def test_x82_la_reparacion_o_planificacion_con_lluvia_o_alerta_sigue_en_servicios_publicos(titular: str) -> None:
    for variante in ("guia", "ampliado"):
        assert Baseline(variante=variante).clasificar(titular).principal == "servicios_publicos"


def test_x82_cede_ante_tiene_su_lista_propia_de_fenomenos_en_el_yaml() -> None:
    from src.configuracion import cargar_clasificacion
    (regla,) = cargar_clasificacion().baseline.cede_ante
    assert regla.fenomenos and "lluvia" not in " ".join(regla.fenomenos)


def test_x79_la_obra_sin_fenomeno_sigue_siendo_servicios_publicos_en_el_baseline() -> None:
    assert Baseline(variante="guia").clasificar("Inauguran el puente sobre el río Chagres").principal == "servicios_publicos"
    assert Baseline(variante="guia").clasificar("MOP rehabilita la carretera Panamericana").principal == "servicios_publicos"
