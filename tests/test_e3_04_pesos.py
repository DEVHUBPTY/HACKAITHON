"""E3-04 · Pesos editables: el escenario de sesión recalcula la bandeja, la compara con la oficial y nunca escribe nada."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from src import interfaz as ui
from src.configuracion import ConfigInterfaz, cargar_interfaz, cargar_modalidad, cargar_prioridad, cargar_reglas
from src.evidencia import accion_recomendada
from src.puntaje import puntaje_total, rango_de

CFG = cargar_interfaz().pesos_editables
REGLAS = cargar_reglas()
MODALIDAD = cargar_modalidad("editorial")
OFICIAL = ui.pesos_oficiales(REGLAS)


def fila(grupo: str, c: Mapping[str, float], estado: str = "parcial") -> ui.FilaBandeja:
    """Una fila con P oficial calculado con los pesos oficiales (posición provisional: ``oficial`` la reordena)."""
    p = puntaje_total(dict(c), REGLAS)
    rango = rango_de(p, REGLAS)
    return ui.FilaBandeja(0, grupo, f"tema {grupo}", f"titular {grupo}", p, rango, dict(c), estado, accion_recomendada(rango, estado, MODALIDAD).accion)


def oficial(*filas: ui.FilaBandeja) -> list[ui.FilaBandeja]:
    from dataclasses import replace

    return [replace(f, posicion=i) for i, f in enumerate(ui.ordenar_bandeja(filas), start=1)]


# R, I, U, N, E
URGENTE = {"R": 0.4, "I": 0.4, "U": 1.0, "N": 0.4, "E": 0.4}
RELEVANTE = {"R": 1.0, "I": 0.5, "U": 0.3, "N": 0.5, "E": 0.5}
IMPACTANTE = {"R": 0.5, "I": 1.0, "U": 0.4, "N": 0.4, "E": 0.5}
FLOJO = {"R": 0.1, "I": 0.1, "U": 0.1, "N": 0.1, "E": 0.1}
FILAS = oficial(fila("GRP-a", URGENTE), fila("GRP-b", RELEVANTE), fila("GRP-c", IMPACTANTE), fila("GRP-d", FLOJO))


def con_pesos(**cambios: float) -> dict[str, float]:
    return {**OFICIAL, **cambios}


# ------------------------------------------------------------------ configuración


def test_los_pesos_oficiales_salen_de_reglas_y_suman_100() -> None:
    assert OFICIAL == {"R": 30, "I": 25, "U": 20, "N": 15, "E": 10}
    assert sum(OFICIAL.values()) == 100
    assert CFG.minimo <= min(OFICIAL.values()) and max(OFICIAL.values()) <= CFG.maximo


def test_el_rango_configurado_debe_permitir_sumar_100() -> None:
    datos = cargar_interfaz().model_dump()
    datos["pesos_editables"]["maximo"] = 10          # 5 × 10 = 50 < 100
    with pytest.raises(ValidationError, match="sumar 100"):
        ConfigInterfaz.model_validate(datos)
    datos["pesos_editables"].update(maximo=50, minimo=60)
    with pytest.raises(ValidationError, match="minimo"):
        ConfigInterfaz.model_validate(datos)


# ------------------------------------------------------------------ validación


def test_los_pesos_oficiales_son_validos_y_se_reconocen_como_oficiales() -> None:
    assert ui.validar_pesos(OFICIAL, CFG) == [] and ui.es_oficial(OFICIAL)
    assert not ui.es_oficial(con_pesos(R=35, I=20))


def test_una_suma_distinta_de_100_se_rechaza_con_el_texto_configurado() -> None:
    errores = ui.validar_pesos(con_pesos(R=35), CFG)
    assert errores == [CFG.textos.suma.format(suma="105", objetivo="100")]


def test_un_peso_fuera_del_rango_se_rechaza_aunque_la_suma_sea_100() -> None:
    fuera = con_pesos(R=CFG.maximo + 1, I=OFICIAL["I"] - (CFG.maximo + 1 - OFICIAL["R"]))
    errores = ui.validar_pesos(fuera, CFG)
    assert any("R" in e and "entre" in e for e in errores) and not any("suman" in e for e in errores)
    cero = con_pesos(E=0, R=OFICIAL["R"] + OFICIAL["E"])
    assert any("E" in e for e in ui.validar_pesos(cero, CFG))      # con minimo > 0, anular un componente no se permite


def test_faltan_pesos() -> None:
    assert ui.validar_pesos({"R": 100}, CFG) == ["Faltan pesos: I, U, N, E."]


def test_el_escenario_con_pesos_invalidos_lanza_valueerror() -> None:
    with pytest.raises(ValueError, match="suman"):
        ui.escenario_de_pesos(FILAS, con_pesos(R=99), MODALIDAD)


# ------------------------------------------------------------------ escenario


def test_con_los_pesos_oficiales_el_escenario_reproduce_el_ranking_oficial() -> None:
    esc = ui.escenario_de_pesos(FILAS, OFICIAL, MODALIDAD)
    assert [(f.id_grupo, f.posicion, f.rango, f.accion) for f in esc] == [(f.id_grupo, f.posicion, f.rango, f.accion) for f in FILAS]
    assert [round(f.puntaje, 9) for f in esc] == [round(f.puntaje, 9) for f in FILAS]
    comp = ui.comparar_con_oficial(FILAS, esc)
    assert comp.sin_diferencias and comp.entran_al_top == () and comp.salen_del_top == () and not comp.cambia_el_orden_del_top


def test_cambiar_pesos_reordena_y_recalcula_p_con_la_formula_oficial() -> None:
    pesos = con_pesos(U=45, R=5)      # la urgencia pasa a mandar
    esc = ui.escenario_de_pesos(FILAS, pesos, MODALIDAD)
    por_id = {f.id_grupo: f for f in esc}
    esperado = sum(pesos[k] * URGENTE[k] for k in "RIUNE")
    assert por_id["GRP-a"].puntaje == pytest.approx(esperado)
    assert [f.posicion for f in esc] == [1, 2, 3, 4]
    assert esc[0].id_grupo == "GRP-a"
    assert [f.id_grupo for f in esc] != [f.id_grupo for f in FILAS]


def test_el_escenario_no_toca_las_filas_oficiales_ni_el_estado_de_evidencia() -> None:
    antes = [(f.id_grupo, f.posicion, f.puntaje, f.rango, f.accion) for f in FILAS]
    esc = ui.escenario_de_pesos(FILAS, con_pesos(U=45, R=5), MODALIDAD)
    assert antes == [(f.id_grupo, f.posicion, f.puntaje, f.rango, f.accion) for f in FILAS]
    assert {f.id_grupo: f.estado_evidencia for f in esc} == {f.id_grupo: f.estado_evidencia for f in FILAS}
    assert {f.id_grupo: dict(f.componentes) for f in esc} == {f.id_grupo: dict(f.componentes) for f in FILAS}


def test_el_rango_y_la_accion_se_recalculan_con_la_tabla_de_la_modalidad() -> None:
    pesos = con_pesos(U=45, R=5)
    esc = {f.id_grupo: f for f in ui.escenario_de_pesos(FILAS, pesos, MODALIDAD)}
    for f in esc.values():
        assert f.rango == rango_de(f.puntaje, REGLAS)
        assert f.accion == accion_recomendada(f.rango, f.estado_evidencia, MODALIDAD).accion


def test_d105_el_empate_en_p_mostrado_se_sigue_declarando_y_lo_decide_mayor_u_luego_id() -> None:
    # a y b empatan en todo (decide el ID); con otros pesos c los supera
    a = fila("GRP-b", {"R": 0.5, "I": 0.5, "U": 0.5, "N": 0.5, "E": 0.5})
    b = fila("GRP-a", {"R": 0.5, "I": 0.5, "U": 0.5, "N": 0.5, "E": 0.5})
    c = fila("GRP-c", {"R": 0.4, "I": 0.5, "U": 0.7, "N": 0.5, "E": 0.5})   
    esc = ui.escenario_de_pesos(oficial(a, b), con_pesos(R=31, I=24), MODALIDAD)
    assert [f.id_grupo for f in esc] == ["GRP-a", "GRP-b"] and [f.empate_con for f in esc] == [1, 1]
    con_c = ui.escenario_de_pesos(oficial(a, b, c), con_pesos(R=20, U=30), MODALIDAD)      # R=20, U=30: c vale 0.4*20+0.7*30 = 29 y a/b 25
    assert [f.id_grupo for f in con_c][0] == "GRP-c" and [f.empate_con for f in con_c] == [0, 1, 1]


# ------------------------------------------------------------------ comparación


def test_la_comparacion_cuenta_puestos_rangos_y_el_top() -> None:
    esc = ui.escenario_de_pesos(FILAS, con_pesos(U=45, R=5), MODALIDAD)
    comp = ui.comparar_con_oficial(FILAS, esc, tamano_top=2)
    assert comp.tamano_top == 2 and comp.se_mueven > 0
    por_id = {m.id_grupo: m for m in comp.movimientos}
    assert all(m.puestos == m.posicion_oficial - m.posicion_escenario for m in comp.movimientos)
    assert sum(m.puestos for m in comp.movimientos) == 0
    top_of = {f.id_grupo for f in FILAS[:2]}
    top_es = {f.id_grupo for f in esc[:2]}
    assert set(comp.entran_al_top) == top_es - top_of and set(comp.salen_del_top) == top_of - top_es
    assert por_id["GRP-a"].posicion_escenario == 1
    assert comp.cambia_el_orden_del_top


def test_el_tamano_del_top_por_defecto_es_el_de_la_sensibilidad() -> None:
    esc = ui.escenario_de_pesos(FILAS, con_pesos(U=45, R=5), MODALIDAD)
    assert ui.comparar_con_oficial(FILAS, esc).tamano_top == cargar_prioridad().sensibilidad.tamano_ranking


def test_comparar_exige_los_mismos_grupos() -> None:
    with pytest.raises(ValueError, match="mismos grupos"):
        ui.comparar_con_oficial(FILAS, FILAS[:-1])


def test_los_mayores_movimientos_excluyen_a_los_que_no_se_mueven_y_respetan_el_limite() -> None:
    esc = ui.escenario_de_pesos(FILAS, con_pesos(U=45, R=5), MODALIDAD)
    comp = ui.comparar_con_oficial(FILAS, esc)
    mov = ui.mayores_movimientos(comp, 1)
    assert len(mov) == 1 and mov[0].puestos != 0
    assert all(m.puestos != 0 for m in ui.mayores_movimientos(comp))


def test_el_empate_en_el_corte_del_top_se_declara_en_el_escenario() -> None:
    iguales = oficial(*[fila(f"GRP-{i}", {"R": 0.5, "I": 0.5, "U": 0.5, "N": 0.5, "E": 0.5}) for i in "abcd"])
    esc = ui.escenario_de_pesos(iguales, con_pesos(R=31, I=24), MODALIDAD)
    comp = ui.comparar_con_oficial(iguales, esc, tamano_top=2)
    assert comp.empate_en_el_corte and comp.empate_en_el_corte["empatados"] == 4 and comp.empate_en_el_corte["fuera_del_top"] == 2


# ------------------------------------------------------------------ propuesta descargable


def test_la_propuesta_lleva_pesos_justificacion_y_efecto_y_se_declara_no_oficial() -> None:
    pesos = con_pesos(U=45, R=5)
    comp = ui.comparar_con_oficial(FILAS, ui.escenario_de_pesos(FILAS, pesos, MODALIDAD))
    p = ui.propuesta_de_pesos(pesos, "  La urgencia pesa más\npara la mesa de noticias del día.  ", comp)
    assert p["estado"] == CFG.textos.propuesta_estado and "no oficial" in p["estado"]
    assert p["version_reglas_base"] == REGLAS.version
    assert p["pesos_oficiales"] == OFICIAL and p["pesos_propuestos"]["U"] == 45
    assert p["justificacion"] == "La urgencia pesa más para la mesa de noticias del día."
    assert p["efecto"]["grupos_que_se_mueven"] == comp.se_mueven
    assert json.loads(ui.propuesta_a_json(p)) == p


@pytest.mark.parametrize("justificacion", ["", "   ", "corta"])
def test_sin_justificacion_suficiente_no_hay_propuesta(justificacion: str) -> None:
    with pytest.raises(ValueError, match="justificación"):
        ui.propuesta_de_pesos(con_pesos(U=45, R=5), justificacion)


def test_los_pesos_oficiales_o_invalidos_no_generan_propuesta() -> None:
    with pytest.raises(ValueError, match="oficiales"):
        ui.propuesta_de_pesos(OFICIAL, "x" * 50)
    with pytest.raises(ValueError, match="suman"):
        ui.propuesta_de_pesos(con_pesos(R=99), "x" * 50)


def test_el_escenario_no_escribe_en_config_ni_en_disco(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.configuracion import RAIZ

    antes = {p: p.read_bytes() for p in (RAIZ / "config").glob("*.yaml")}
    monkeypatch.chdir(tmp_path)
    esc = ui.escenario_de_pesos(FILAS, con_pesos(U=45, R=5), MODALIDAD)
    ui.propuesta_a_json(ui.propuesta_de_pesos(con_pesos(U=45, R=5), "justificación suficiente", ui.comparar_con_oficial(FILAS, esc)))
    assert {p: p.read_bytes() for p in (RAIZ / "config").glob("*.yaml")} == antes
    assert list(tmp_path.iterdir()) == []


def test_el_codigo_del_escenario_no_tiene_numeros_magicos_ni_condicionales_de_modalidad() -> None:
    import inspect

    fuente = inspect.getsource(ui.escenario_de_pesos) + inspect.getsource(ui.comparar_con_oficial) + inspect.getsource(ui.validar_pesos)
    assert "modalidad ==" not in fuente and "== 100" not in fuente
