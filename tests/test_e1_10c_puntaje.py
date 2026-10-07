"""E1-10c: subtema con sustento (X41), alcance nacional (X42), ruido regional (X44) y D-103 (N y R)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src import contexto, limpieza, puntaje
from src.configuracion import cargar_temas, cargar_vinculos
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, entrada, miembro, vector

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


# ------------------------------------------------------------------ X42 · alcance nacional


def _nivel(*titulares: str) -> str:
    return puntaje.alcance_geografico([miembro(f"NOT-{i}", t) for i, t in enumerate(titulares)], REGLAS, CFG).nivel


@pytest.mark.parametrize(
    "titular",
    [
        "Más de 30 mujeres han muerto de forma violenta en Panamá este año",            # el país nombrado
        "Ejecutivo sanciona la Ley 552 del Presupuesto del Canal de Panamá por $5,555 millones",
        "MOP solicita $43.1 millones para pagar compromisos y continuar obras en ejecución",   # institución nacional
        "Minsa: Adelantan vacunación contra VSR en embarazadas",
        "Déficit de personal limita la capacidad operativa de los bomberos en el país",
        "Obispos panameños presentarán en Roma la realidad de sus diócesis",
    ],
)
def test_x42_el_pais_o_una_institucion_nacional_dan_alcance_nacional(titular: str) -> None:
    assert _nivel(titular) == "nacional"


@pytest.mark.parametrize(
    ("titulares", "nivel"),
    [
        (("Lluvias en Panamá dejan inundaciones en Chepo",), "local"),                    # el lugar concreto manda
        (("Minsa refuerza la vacunación en Chiriquí",), "provincial"),
        (("Corte de agua en la provincia de Panamá",), "provincial"),                      # la provincia no es el país
        (("Tranque en la ciudad de Panamá por obras",), "desconocido"),                    # la ciudad tampoco es el país
        (("Se reúne el comité técnico",), "desconocido"),
        (("Cierran escuela en David", "Gobierno decreta alza a nivel nacional"), "nacional"),   # explícito sigue mandando
    ],
)
def test_x42_un_lugar_concreto_manda_sobre_la_mencion_implicita_del_pais(titulares: tuple[str, ...], nivel: str) -> None:
    assert _nivel(*titulares) == nivel


# ------------------------------------------------------------------ X44 · notas regionales que afectan a Panamá


def _gdelt(titulo: str) -> limpieza.Resultado:
    fila = {
        "titulo": titulo, "url": "https://ejemplo.example/n/1", "url_canonica": "https://ejemplo.example/n/1",
        "medio": "Ejemplo", "dominio": "ejemplo.example", "origen": "GDELT", "pais_medio": None,
        "fecha_deteccion": "2026-10-01T10:00:00Z", "fecha_publicacion": None, "fecha_extraccion": "2026-10-06T10:00:00Z",
        "descripcion": None, "categoria_fuente": None,
    }  # fmt: skip
    return limpieza.evaluar(fila, limpieza.Reglas.desde_config())


@pytest.mark.parametrize(
    "titulo",
    [
        # comercio marítimo y de combustibles que pasa por el Canal o abastece a Panamá (D-84: «rutas marítimas»)
        "Trump threat to ban diesel exports sets off global alarms",
        "Exportaciones chinas sostienen la demanda de carga contenerizada pese a la debilidad de EE. UU.",
        "US LNG Exports Increase in September, Europe Outbids Asia for Cargoes",   # etiqueta humana: logística, regional
        "Suben los fletes marítimos entre Asia y la costa este de EE. UU.",
        "Navieras desvían portacontenedores por la crisis del mar Rojo",
    ],
)
def test_x44_el_comercio_maritimo_y_de_combustibles_es_regional_no_ruido(titulo: str) -> None:
    r = _gdelt(titulo)
    assert (r.motivo_ruido, r.alcance_regional) == (None, True)


@pytest.mark.parametrize(
    "titulo",
    [
        "Trump redirige ayuda a Europa",
        "Emerging Technologies and Maritime Security",
        "Navy destroyer named for late Sen. Ted Stevens will be commissioned in Whittier on Saturday",
        "Carnival to Deploy Adventure, Legend, Spirit to West Coast in 2028",
        "Sin combustible y con menos vuelos, pero a Cuba aún llegan aviones",   # escasez local en otro país, no un flujo comercial
        "El Niño hits Australian wheat",
    ],
)
def test_x44_lo_que_no_es_comercio_maritimo_ni_de_combustibles_sigue_siendo_ruido(titulo: str) -> None:
    r = _gdelt(titulo)
    assert (r.motivo_ruido, r.alcance_regional) == ("no_es_panama", False)


def test_x44_un_falso_panama_con_comercio_maritimo_sigue_siendo_ruido() -> None:
    assert _gdelt("Panama City port sees container shipping growth").motivo_ruido == "no_es_panama"


# ------------------------------------------------------------------ D-103 · N y R


UMBRAL = REGLAS.agrupacion.umbral_similitud


def _con_similitud(s: float) -> np.ndarray:
    """Vector cuyo coseno con ``vector(1, 0)`` es exactamente ``s``."""
    return np.stack([vector(s, math.sqrt(1 - s * s))])


def _n(similitud: float, reglas=REGLAS) -> puntaje.Componente:
    entradas = [
        entrada("GRP-previo", [miembro("NOT-p", publicado_hace=100)], vectores=np.stack([vector(1, 0)])),
        entrada("GRP-nuevo", [miembro("NOT-n", publicado_hace=10)], vectores=_con_similitud(similitud)),
    ]
    return {p.id_grupo: p for p in puntaje.calcular_puntajes(entradas, reglas, CFG, AHORA)}["GRP-nuevo"].componentes["N"]


@pytest.mark.parametrize("similitud", [0.0, 0.3, 0.6, UMBRAL - 0.001])
def test_d103_bajo_el_umbral_de_agrupacion_n_es_1(similitud: float) -> None:
    assert _n(similitud).valor == 1.0


@pytest.mark.parametrize("similitud", [UMBRAL, (UMBRAL + 1) / 2, 0.95, 1.0])
def test_d103_desde_el_umbral_n_descuenta_lineal_hasta_0_con_un_duplicado(similitud: float) -> None:
    c = _n(similitud)
    assert c.valor == pytest.approx((1 - similitud) / (1 - UMBRAL), abs=1e-6)
    assert c.explicacion["umbral_similitud"] == UMBRAL and c.explicacion["similitud_maxima"] == pytest.approx(similitud, abs=1e-6)


def test_d103_el_umbral_de_n_es_el_de_la_agrupacion_no_una_copia() -> None:
    otro = REGLAS.model_copy(update={"agrupacion": REGLAS.agrupacion.model_copy(update={"umbral_similitud": 0.9})})
    assert _n(0.8).valor < 1.0 and _n(0.8, otro).valor == 1.0


def test_d103_r_no_usa_la_confianza_del_clasificador() -> None:
    entradas = [
        entrada("GRP-alta", [miembro("NOT-a", similitud=0.95)], vectores=np.stack([vector(1, 0)])),
        entrada("GRP-baja", [miembro("NOT-b", similitud=0.40)], vectores=np.stack([vector(0, 1)])),
        entrada("GRP-reg", [miembro("NOT-r", similitud=0.95, regional=True)], vectores=np.stack([vector(1, 1)])),
    ]
    r = {p.id_grupo: p.componentes["R"] for p in puntaje.calcular_puntajes(entradas, REGLAS, CFG, AHORA)}
    assert r["GRP-alta"].valor == r["GRP-baja"].valor == REGLAS.relevancia.foco_panama_sujeto
    assert r["GRP-reg"].valor == REGLAS.relevancia.foco_otro_pais_afecta
    assert not any("similitud" in k for k in r["GRP-alta"].explicacion)


def test_d103_los_pesos_de_p_no_cambian() -> None:
    assert (REGLAS.pesos.R, REGLAS.pesos.I, REGLAS.pesos.U, REGLAS.pesos.N, REGLAS.pesos.E) == (30, 25, 20, 15, 10)
