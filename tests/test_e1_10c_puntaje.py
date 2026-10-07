"""E1-10c: subtema con sustento (X41), alcance nacional (X42), ruido regional (X44) y D-103 (N y R)."""

from __future__ import annotations

import pytest

from src import contexto
from src.configuracion import cargar_temas, cargar_vinculos

SUB = cargar_vinculos().subtema
TEMAS = cargar_temas().temas
SERVICIOS = list(TEMAS["servicios_publicos"].subtemas)


def decidir(subtema: str, margen: float, titular: str, tema: str = "servicios_publicos") -> tuple[str | None, str | None]:
    return contexto.decidir_subtema([(subtema, 0.83, margen)], [titular], SUB, list(TEMAS[tema].subtemas))


# ------------------------------------------------------------------ X41 · subtema con sustento


@pytest.mark.parametrize(
    ("subtema", "margen", "titular"),
    [
        # el margen pasa (D-92), pero el titular no nombra nada del subtema: obras del MOP no son agua potable
        ("agua_potable", 0.0402, "MOP solicita $43.1 millones para pagar compromisos y continuar obras en ejecución"),
        ("agua_potable", 0.0444, "La Chorrera proyecta renovar el parque Tomás Martín Feuillet con una inversión de 620 mil dólares"),
        ("agua_potable", 0.0152, "Contenido Exclusivo: El metro por la Tumba Muerto"),
    ],
)
def test_x41_el_margen_solo_no_basta_para_afirmar_un_subtema(subtema: str, margen: float, titular: str) -> None:
    assert decidir(subtema, margen, titular) == (None, None)


@pytest.mark.parametrize(
    "titular",
    [
        # nombran a la vez la salud (CSS, hospital) y la seguridad (aprehensión, reclusión): el subtema es ambiguo
        "Aprehenden a Enrique Lau, exdirector de la CSS, por supuesto enriquecimiento injustificado",
        "César Caicedo ahora está recluido en el Hospital Santo Tomás; había sido trasladado a Coiba",
    ],
)
def test_x41_un_titular_que_nombra_dos_subtemas_del_tema_queda_sin_subtema(titular: str) -> None:
    assert decidir("salud_publica", 0.0386, titular) == (None, None)


@pytest.mark.parametrize(
    ("subtema", "titular"),
    [
        ("salud_publica", "Hospital reporta falta de medicamentos"),                      # casos difíciles de docs/guia_temas.md
        ("educacion_publica", "Paro docente deja sin clases a escuelas"),
        ("seguridad_ciudadana", "Policía reporta aumento de homicidios"),
        ("transporte_publico", "Usuarios del Metro y MiBus reportan retrasos"),          # prototipo de temas.yaml
        ("seguridad_ciudadana", "Mujer es aprehendida en Santiago tras hallazgo de 162 paquetes de presunta droga en el vehículo que conducía"),
    ],
)
def test_x41_un_titular_que_nombra_el_subtema_lo_conserva(subtema: str, titular: str) -> None:
    assert decidir(subtema, 0.001, titular) == (subtema, "lexico")


def test_x41_la_configuracion_ya_no_acepta_el_subtema_solo_por_margen() -> None:
    assert SUB.criterios == ["lexico"]


def test_x41_todo_subtema_del_catalogo_tiene_terminos_de_apoyo() -> None:
    faltan = [s for t in TEMAS.values() for s in t.subtemas if not SUB.terminos_por_subtema.get(s)]
    assert faltan == []
