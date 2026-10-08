"""C-10 (T2): Panamá como parte del hecho (D3, D6) y estados o provincias extranjeras no ambiguas (D7).

Decisiones del dueño, C-10, 2026-10-07. No se ajusta ningún peso ni umbral (D-101).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import puntaje
from src.configuracion import ErrorDeConfiguracion, cargar_reglas
from tests.prioridad_ayuda import CFG, REGLAS, miembro
from tests.test_reglas_config import escribir, leer


def _alcance(*titulares: str) -> puntaje.Alcance:
    return puntaje.alcance_geografico([miembro(f"NOT-{i}", t) for i, t in enumerate(titulares)], REGLAS, CFG)


# ------------------------------------------------------------------ D3 · nombres propios con «Panamá»


def test_d3_la_lista_de_nombres_propios_trae_el_canal_y_cobre_panama() -> None:
    nombres = {puntaje.normalizar_geografia(n) for n in REGLAS.geografia.panama_nombres_propios}
    assert {"canal de panama", "cobre panama"} <= nombres


@pytest.mark.parametrize(
    "titular",
    [
        "Cobre Panamá: gobierno de Canadá negocia",
        "Canal de Panamá recibe barco de China",
        "canal de panama recibe barco de china",   # sin tildes ni mayúsculas
    ],
)
def test_d3_un_nombre_propio_con_panama_cuenta_como_mencion_del_pais_y_no_es_exterior(titular: str) -> None:
    alcance = _alcance(titular)
    assert alcance.nivel == "nacional" and alcance.valor == REGLAS.impacto.alcance_geografico.nacional


def test_d3_ciudad_de_panama_sigue_siendo_local_y_no_el_pais() -> None:
    assert _alcance("Alerta en Ciudad de Panamá por lluvias").nivel == "local"
    assert _alcance("Alerta en la ciudad de Panamá por lluvias en Costa Rica").nivel == "local"


def test_d3_ciudad_de_panama_no_cuenta_como_mencion_del_pais() -> None:
    # Si «Ciudad de Panamá» contara como el país, la primera daría True; el prefijo excluido la deja en False.
    assert not puntaje.nombra_al_pais("Alerta en Ciudad de Panamá por lluvias", REGLAS, CFG)
    assert puntaje.nombra_al_pais("Alerta en Panamá por lluvias", REGLAS, CFG)


# ------------------------------------------------------------------ D6 · Panamá como parte del hecho manda sobre el exterior


@pytest.mark.parametrize(
    "titular",
    [
        "Panamá y Colombia firman acuerdo en Bogotá",
        "Panamá firma tratado con Costa Rica",
        "Presidente de Panamá visita Singapur",
    ],
)
def test_d6_panama_nombrado_como_parte_del_hecho_manda_sobre_el_lugar_o_la_contraparte_extranjera(titular: str) -> None:
    alcance = _alcance(titular)
    assert alcance.nivel == "nacional"
    assert "Panamá" in alcance.terminos


def test_d6_el_grupo_recibe_el_nivel_que_tendria_sin_la_contraparte_extranjera() -> None:
    sin = _alcance("Panamá firma tratado")
    con = _alcance("Panamá firma tratado con Costa Rica")
    assert (con.nivel, con.valor) == (sin.nivel, sin.valor)


def test_d6_un_lugar_panameno_sigue_mandando_sobre_la_mencion_del_pais() -> None:
    assert _alcance("Panamá firma acuerdo con Colombia en Chiriquí").nivel == "provincial"


@pytest.mark.parametrize(
    "titular",
    [
        "Policía Nacional de Colombia capturó a un sospechoso",
        "Obispos panameños presentan en Roma la realidad de sus diócesis",   # el gentilicio no es el país nombrado (D-115)
        "Vigilancia por peste neumónica en Rusia",
    ],
)
def test_d6_sin_mencion_de_panama_el_lugar_extranjero_sigue_siendo_exterior(titular: str) -> None:
    assert _alcance(titular).nivel == "exterior"


def test_d6_la_mencion_de_panama_vale_por_titular_y_no_borra_el_exterior_de_otro_titular_del_grupo() -> None:
    assert _alcance("Panamá firma tratado con Costa Rica", "Brote de dengue en México").nivel == "exterior"


@pytest.mark.parametrize(
    "titular",
    ["Hurricane hits Panama City, Florida", "Tormenta golpea Panama City Beach", "Hurricane hits Panamá City"],
)
def test_d6_un_lugar_extranjero_con_el_nombre_del_pais_no_es_una_mencion_del_pais(titular: str) -> None:
    assert not puntaje.nombra_al_pais(titular, REGLAS, CFG)
    assert _alcance(titular).nivel == "exterior"


def test_d6_panama_city_florida_es_exterior_pero_panama_city_con_panama_sigue_nombrando_al_pais() -> None:
    assert _alcance("Hurricane hits Panama City, Florida").nivel == "exterior"
    assert puntaje.nombra_al_pais("Panama City recibe a la presidenta de Panamá", REGLAS, CFG)
    assert _alcance("Panamá firma tratado con Costa Rica").nivel == "nacional"
    assert _alcance("Canal de Panamá recibe barco de China").nivel == "nacional"


def test_d6_la_configuracion_valida_los_nombres_extranjeros_con_el_pais(tmp_path: Path) -> None:
    datos = leer("reglas_v1.3")
    datos["geografia"]["panama_nombres_extranjeros"] = ["Panama City", "panama city"]
    with pytest.raises(ErrorDeConfiguracion, match="repetidos"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    datos = leer("reglas_v1.3")
    datos["geografia"]["panama_nombres_extranjeros"] = ["Panama City", ""]
    with pytest.raises(ErrorDeConfiguracion, match="vacío"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    datos = leer("reglas_v1.3")
    datos["geografia"]["panama_nombres_extranjeros"] = ["Springfield"]
    with pytest.raises(ErrorDeConfiguracion, match="no contiene el país"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    datos = leer("reglas_v1.3")
    del datos["geografia"]["panama_nombres_extranjeros"]
    with pytest.raises(ErrorDeConfiguracion):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))


# ------------------------------------------------------------------ D7 · estados y provincias extranjeras no ambiguos


ESTADOS = ["Texas", "California", "Arizona", "Quebec", "Ontario", "Alberta", "Cataluña", "Catalonia", "Andalucía", "Baviera", "Bavaria", "Jalisco", "Sicilia", "Sicily"]


@pytest.mark.parametrize("estado", ESTADOS)
def test_d7_cada_estado_o_provincia_extranjera_agregada_da_alcance_exterior(estado: str) -> None:
    alcance = _alcance(f"Inundaciones dejan daños en {estado}")
    assert (alcance.nivel, alcance.valor) == ("exterior", REGLAS.impacto.alcance_geografico.exterior)


def test_d7_guardia_nacional_de_texas_ya_es_exterior() -> None:
    assert _alcance("Guardia Nacional de Texas envía tropas").nivel == "exterior"


def test_d7_un_lugar_de_panama_manda_sobre_un_estado_extranjero() -> None:
    assert _alcance("Inundaciones en Colón y en Texas").nivel == "provincial"


AMBIGUOS = ["Georgia", "Washington", "Santiago"]   # siguen fuera: Georgia Meloni es persona; Washington es apellido o el gobierno de EE. UU.
RESTAURADOS = ["India", "Ghana", "Guinea", "Mali", "Jordania", "Lima"]   # decisión del dueño, 2026-10-07: vuelven a la lista


@pytest.mark.parametrize("nombre", AMBIGUOS)
def test_d7_los_nombres_ambiguos_no_estan_en_la_lista_del_exterior(nombre: str) -> None:
    normalizados = {puntaje.normalizar_geografia(t) for t in REGLAS.geografia.exterior_terminos}
    assert puntaje.normalizar_geografia(nombre) not in normalizados


@pytest.mark.parametrize("nombre", RESTAURADOS)
def test_d7_los_nombres_restaurados_estan_en_la_lista_del_exterior(nombre: str) -> None:
    normalizados = {puntaje.normalizar_geografia(t) for t in REGLAS.geografia.exterior_terminos}
    assert puntaje.normalizar_geografia(nombre) in normalizados


@pytest.mark.parametrize("nombre", RESTAURADOS)
def test_d7_cada_nombre_restaurado_da_alcance_exterior(nombre: str) -> None:
    assert _alcance(f"Brote de dengue en {nombre}").nivel == "exterior"


@pytest.mark.parametrize(
    "titular",
    ["Georgia Meloni presenta su libro", "Washington Pérez inaugura obra"],
)
def test_d7_un_nombre_ambiguo_de_persona_no_da_alcance_exterior(titular: str) -> None:
    # Sin «Panamá» en el titular: si Georgia o Washington volvieran a la lista, el alcance sería `exterior`.
    assert _alcance(titular).nivel == "desconocido"


# ------------------------------------------------------------------ validación de la configuración


def test_d3_la_configuracion_valida_la_lista_de_nombres_propios(tmp_path: Path) -> None:
    datos = leer("reglas_v1.3")
    datos["geografia"]["panama_nombres_propios"] = ["Canal de Panamá", "canal de panama"]
    with pytest.raises(ErrorDeConfiguracion, match="repetidos"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    datos = leer("reglas_v1.3")
    datos["geografia"]["panama_nombres_propios"] = ["Canal de Panamá", ""]
    with pytest.raises(ErrorDeConfiguracion, match="vacío"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    datos = leer("reglas_v1.3")
    datos["geografia"]["panama_nombres_propios"] = ["Canal de Suez"]
    with pytest.raises(ErrorDeConfiguracion, match="no contiene el país"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    datos = leer("reglas_v1.3")
    del datos["geografia"]["panama_nombres_propios"]
    with pytest.raises(ErrorDeConfiguracion):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))


def test_d6_la_configuracion_exige_al_menos_un_nombre_del_pais(tmp_path: Path) -> None:
    datos = leer("reglas_v1.3")
    datos["geografia"]["pais_terminos"] = []
    with pytest.raises(ErrorDeConfiguracion):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
