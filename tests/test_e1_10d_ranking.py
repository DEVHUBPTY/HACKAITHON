"""E1-10d: «nacional» suelto (X85), zonas de la capital (X86), léxico de seguridad (X87) y alcance exterior (D-115)."""

from __future__ import annotations

import pytest

from src import contexto, puntaje
from src.configuracion import cargar_temas, cargar_vinculos
from tests.prioridad_ayuda import CFG, REGLAS, miembro

SUB = cargar_vinculos().subtema
TEMAS = cargar_temas().temas


def _nivel(*titulares: str) -> str:
    return puntaje.alcance_geografico([miembro(f"NOT-{i}", t) for i, t in enumerate(titulares)], REGLAS, CFG).nivel


# ------------------------------------------------------------------ X85 · «nacional» suelto


@pytest.mark.parametrize(
    ("titular", "nivel"),
    [
        ("Policía Nacional aprehende a sospechoso en Chiriquí", "provincial"),
        ("Guardia Nacional de Texas envía tropas", "desconocido"),
        ("Banco Nacional recibe auditoría en Bocas del Toro", "provincial"),
        ("Policía Nacional realiza operativo", "desconocido"),
    ],
)
def test_x85_nacional_suelto_en_el_nombre_de_una_institucion_no_da_alcance_nacional(titular: str, nivel: str) -> None:
    assert _nivel(titular) == nivel


@pytest.mark.parametrize(
    "titular",
    [
        "A nivel nacional, cierran escuelas",
        "Alerta en todo el país por lluvias",
        "Cortes de luz en todo el territorio",
        "Declaran emergencia en el territorio nacional",
        "Asamblea Nacional aprueba el presupuesto",
        "Gobierno nacional anuncia el plan",
    ],
)
def test_x85_las_frases_nacionales_siguen_dando_alcance_nacional(titular: str) -> None:
    assert _nivel(titular) == "nacional"


def test_x85_una_frase_nacional_manda_sobre_un_lugar_concreto() -> None:
    assert _nivel("Cierran escuela en David", "A nivel nacional, cierran escuelas") == "nacional"


# ------------------------------------------------------------------ X86 · zonas de la capital


@pytest.mark.parametrize(
    "titular",
    [
        "Panamá Norte registra cortes de agua",
        "Inauguran centro de salud en Panamá Pacífico",
        "Tranque en panama pacifico por obras",
    ],
)
def test_x86_panama_norte_y_pacifico_son_un_lugar_concreto_no_el_pais(titular: str) -> None:
    assert _nivel(titular) == "local"


def test_x86_panama_oeste_sigue_siendo_provincia_y_panama_sola_el_pais() -> None:
    assert _nivel("Corte de agua en Panamá Oeste") == "provincial"
    assert _nivel("Minsa: casos en Panamá") == "nacional"
