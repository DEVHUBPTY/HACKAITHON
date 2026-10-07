"""E1-10 · Evaluación del puntaje: ``eval.sensibilidad`` (top 5 ante ±5 de peso y ±20 % de supuestos) y ``eval.puntaje``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eval import puntaje as eval_puntaje
from eval import sensibilidad
from src import embeddings, prioridad
from src.configuracion import ReglasV13
from src.puntaje import COMPONENTES
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, construir_base, entrada, miembro

CORTE = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
Z = 1.959964


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return construir_base(tmp_path / "senales.duckdb")


@pytest.fixture
def emb(tmp_path: Path):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)


@pytest.fixture
def reglas_de_prueba() -> ReglasV13:
    """El codificador de prueba tiene otra escala que MiniLM: el umbral de agrupación se baja para que agrupe algo."""
    return REGLAS.model_copy(update={"agrupacion": REGLAS.agrupacion.model_copy(update={"umbral_similitud": 0.5})})


# ------------------------------------------------------------------ sensibilidad · pesos


def test_cada_peso_se_mueve_cinco_puntos_y_los_demas_se_reescalan_para_sumar_cien() -> None:
    variantes = sensibilidad.variantes_de_pesos(REGLAS, CFG)
    assert len(variantes) == 2 * len(COMPONENTES) == 10
    for v in variantes:
        pesos = {k: getattr(v.reglas.pesos, k) for k in COMPONENTES}
        assert sum(pesos.values()) == pytest.approx(100)
        objetivo = v.ajuste.nombre.split()[-1]
        esperado = getattr(REGLAS.pesos, objetivo) + (CFG.sensibilidad.variacion_peso if v.direccion == "+" else -CFG.sensibilidad.variacion_peso)
        assert pesos[objetivo] == pytest.approx(esperado)
        for k in COMPONENTES:
            if k != objetivo:   # los demás conservan su proporción
                assert pesos[k] / getattr(REGLAS.pesos, k) == pytest.approx((100 - esperado) / (100 - getattr(REGLAS.pesos, objetivo)))
        ReglasV13.model_validate(v.reglas.model_dump())   # sigue siendo una configuración válida


def test_el_reparto_de_un_par_mantiene_la_suma() -> None:
    assert sensibilidad._par(0.5, 0.5, 1.2) == pytest.approx((0.6, 0.4))
    assert sensibilidad._par(0.9, 0.1, 1.2) == pytest.approx((1.0, 0.0))     # se recorta a 1
    reparto = sensibilidad._reparto({"a": 0.5, "b": 0.3, "c": 0.2}, "a", 0.6, 1.0)
    assert sum(reparto.values()) == pytest.approx(1.0) and reparto["b"] / reparto["c"] == pytest.approx(1.5)


# ------------------------------------------------------------------ sensibilidad · supuestos


NOMBRES_ESPERADOS = {
    "Partes de R (foco · temática)", "Foco: otro país que afecta a Panamá", "Foco: Panamá sujeto", "Partes de I (subtema · geográfico)",
    "Alcance geográfico nacional", "Alcance geográfico provincial", "Alcance geográfico local", "Alcance geográfico desconocido",
    "Alcance por subtema (la tabla entera)", "Alcance de I sin subtema", "U: horas con U = 1", "U: días con U = 0",
    "Partes de E: procedencias", "Partes de E: oficial", "Partes de E: identificable", "Tope de procedencias en E", "N del primer grupo",
    "Ventana de agrupación (días)", "Umbral de «mismo texto» (procedencias)",
}


def test_cada_parametro_supuesto_que_cambia_p_se_mueve_arriba_y_abajo() -> None:
    variantes = sensibilidad.variantes_de_supuestos(REGLAS, CFG)
    assert {v.ajuste.nombre for v in variantes} == NOMBRES_ESPERADOS
    assert len(variantes) == 2 * len(NOMBRES_ESPERADOS)
    assert {v.direccion for v in variantes} == {"+", "-"}
    for v in variantes:
        ReglasV13.model_validate(v.reglas.model_dump())          # los pares siguen sumando 1 y los valores en [0, 1]
    assert {v.ajuste.nombre for v in variantes if v.ajuste.reagrupa} == {"Ventana de agrupación (días)", "Umbral de «mismo texto» (procedencias)"}


def test_los_supuestos_se_mueven_un_veinte_por_ciento() -> None:
    por_nombre = {(v.ajuste.nombre, v.direccion): v for v in sensibilidad.variantes_de_supuestos(REGLAS, CFG)}
    v = CFG.sensibilidad.variacion_supuesto
    assert v == 0.2
    arriba = por_nombre[("U: horas con U = 1", "+")].reglas.urgencia.horas_pleno
    abajo = por_nombre[("U: días con U = 0", "-")].reglas.urgencia.dias_nulo
    assert arriba == pytest.approx(REGLAS.urgencia.horas_pleno * 1.2) and abajo == pytest.approx(REGLAS.urgencia.dias_nulo * 0.8)
    assert por_nombre[("Foco: otro país que afecta a Panamá", "+")].reglas.relevancia.foco_otro_pais_afecta == pytest.approx(0.6)
    assert por_nombre[("Foco: Panamá sujeto", "+")].reglas.relevancia.foco_panama_sujeto == 1.0                    # recortado
    assert por_nombre[("Tope de procedencias en E", "+")].reglas.evidencia.tope_procedencias == 4
    assert por_nombre[("Tope de procedencias en E", "-")].reglas.evidencia.tope_procedencias == 2
    assert por_nombre[("Ventana de agrupación (días)", "+")].reglas.agrupacion.ventana_dias == 8
    assert por_nombre[("Ventana de agrupación (días)", "-")].reglas.agrupacion.ventana_dias == 6
    tabla = por_nombre[("Alcance por subtema (la tabla entera)", "-")].reglas.impacto.alcance_subtema
    assert tabla["sismos"] == pytest.approx(0.8) and tabla["destinos_promocion"] == pytest.approx(0.32)
    sin_subtema = por_nombre[("Alcance de I sin subtema", "+")].cfg.impacto.alcance_subtema_desconocido
    assert sin_subtema == pytest.approx(0.6)


def test_comparar_cuenta_cuantos_temas_del_top_cambian() -> None:
    base = ["a", "b", "c", "d", "e"]
    igual = sensibilidad.comparar(base, base)
    assert igual["cambian"] == 0 and igual["mismo_conjunto"] and igual["mismo_orden"]
    otro_orden = sensibilidad.comparar(base, ["b", "a", "c", "d", "e"])
    assert otro_orden["cambian"] == 0 and otro_orden["mismo_conjunto"] and not otro_orden["mismo_orden"]
    cambia = sensibilidad.comparar(base, ["a", "b", "c", "d", "z"])
    assert cambia["cambian"] == 1 and cambia["salen"] == ["e"] and cambia["entran"] == ["z"] and not cambia["mismo_conjunto"]


def test_evaluar_recalcula_el_top_de_todas_las_variantes(base, emb, reglas_de_prueba) -> None:
    r = sensibilidad.evaluar(base, reglas_de_prueba, CFG, CORTE, Z, emb)
    esperadas = len(sensibilidad.variantes_de_pesos(reglas_de_prueba, CFG)) + len(sensibilidad.variantes_de_supuestos(reglas_de_prueba, CFG))
    assert r["variantes"] == esperadas == 10 + 2 * len(NOMBRES_ESPERADOS) == len(r["detalle"])
    assert len(r["top_base"]) == 4                                   # 4 grupos < top 5
    assert r["top_sin_cambio"]["de"] == esperadas and 0 <= r["top_sin_cambio"]["n"] <= esperadas
    assert r["top_sin_cambio"]["n"] + r["con_algun_cambio"]["n"] == esperadas
    assert set(r["top_sin_cambio"]["ic95"]) <= {x / 10_000 for x in range(10_001)}       # IC de Wilson presente
    assert r["por_grupo"]["peso"]["variantes"] == 10
    assert set(r["fuera_del_alcance"]) and "banca" in " ".join(r["fuera_del_alcance"])
    json.dumps(r, ensure_ascii=False)                                  # serializable


def test_mover_los_pesos_puede_cambiar_el_top_y_comparar_lo_detecta() -> None:
    """A gana en relevancia (similitud alta, vieja); B gana en urgencia (reciente, similitud baja): el peso decide quién va primero."""
    a = entrada("GRP-a", [miembro("NOT-a", similitud=0.95, publicado_hace=24 * 20)], n_procedencias=2)
    b = entrada("GRP-b", [miembro("NOT-b", similitud=0.60, publicado_hace=1)], n_procedencias=2)
    solo_r = REGLAS.model_copy(update={"pesos": REGLAS.pesos.model_copy(update={"R": 100.0, "I": 0.0, "U": 0.0, "N": 0.0, "E": 0.0})})
    solo_u = REGLAS.model_copy(update={"pesos": REGLAS.pesos.model_copy(update={"R": 0.0, "I": 0.0, "U": 100.0, "N": 0.0, "E": 0.0})})
    por_r = sensibilidad.top([a, b], solo_r, CFG, AHORA, 1)
    por_u = sensibilidad.top([a, b], solo_u, CFG, AHORA, 1)
    assert por_r == ["GRP-a"] and por_u == ["GRP-b"]
    cambio = sensibilidad.comparar(por_r, por_u)
    assert cambio["cambian"] == 1 and cambio["salen"] == ["GRP-a"] and cambio["entran"] == ["GRP-b"]


def test_el_cli_de_sensibilidad_escribe_el_json(base, emb, tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"fecha_corte_UTC": "2026-10-06T12:00:00Z"}), encoding="utf-8")
    monkeypatch.setattr(sensibilidad, "crear", lambda *a, **k: emb)
    salida = tmp_path / "sens.json"
    assert sensibilidad.main(["--base", str(base), "--manifest", str(manifest), "--salida", str(salida)]) == 0
    assert json.loads(salida.read_text(encoding="utf-8"))["variantes"] == 10 + 2 * len(NOMBRES_ESPERADOS)
    assert sensibilidad.main(["--base", str(tmp_path / "nada.duckdb")]) == 1


# ------------------------------------------------------------------ eval.puntaje


def test_el_resumen_trae_n_minimo_mediana_maximo_y_desviacion() -> None:
    r = eval_puntaje.resumen([0.0, 0.5, 1.0])
    assert (r["n"], r["min"], r["mediana"], r["max"], r["media"]) == (3, 0.0, 0.5, 1.0, 0.5)
    assert r["desviacion"] == pytest.approx(0.4082, abs=1e-4)
    assert eval_puntaje.resumen([])["n"] == 0


def test_un_componente_casi_constante_se_marca() -> None:
    filas = [{"relevancia": x, "impacto": 0.5, "urgencia": 0.5 + e, "novedad": x, "evidencia": 0.3, "puntaje": 50.0}
             for x, e in ((0.1, 0.0), (0.5, 0.001), (0.9, -0.001))]
    c = eval_puntaje.distribucion_de_componentes(filas, CFG)
    assert c["I"]["casi_constante"] is True and c["E"]["casi_constante"] is True and c["U"]["casi_constante"] is True
    assert c["R"]["casi_constante"] is False and c["N"]["casi_constante"] is False


def _unido(id_grupo: str, rango: str, estado: str, posicion: int, puntaje: float = 50.0) -> dict:
    return {"id_grupo": id_grupo, "rango": rango, "estado": estado, "posicion": posicion, "puntaje": puntaje, "accion": "x"}


def test_la_tabla_rango_por_estado_muestra_alto_insuficiente_y_bajo_suficiente() -> None:
    unidos = [_unido("A", "alto", "insuficiente", 1, 80), _unido("B", "bajo", "suficiente", 3, 20), _unido("C", "medio", "parcial", 2), _unido("D", "alto", "insuficiente", 4, 75)]
    t = eval_puntaje.tabla_rango_por_estado(unidos, {"A": "Titular A"}, Z)
    assert len(t["celdas"]) == 9
    assert [c["id_grupo"] for c in t["alto_insuficiente"]] == ["A", "D"] and t["alto_insuficiente"][0]["titular_central"] == "Titular A"
    assert [c["id_grupo"] for c in t["bajo_suficiente"]] == ["B"]
    celda = t["celdas"]["alto|insuficiente"]
    assert (celda["n"], celda["de"], celda["proporcion"]) == (2, 4, 0.5) and celda["ic95"][0] < 0.5 < celda["ic95"][1]
    assert sum(c["n"] for c in t["celdas"].values()) == len(unidos)


def test_evaluar_puntaje_lee_las_tablas_de_la_base(base, emb, tmp_path) -> None:
    prioridad.ejecutar(base, tmp_path / "prioridad.json", CORTE, None, emb=emb)
    r = eval_puntaje.evaluar(base, REGLAS, CFG, Z)
    assert r["grupos"] == 4 and r["version_reglas"] == "1.3" and set(r["componentes"]) == set(COMPONENTES)
    assert sum(c["n"] for c in r["rango_por_estado"]["celdas"].values()) == 4
    assert r["por_rango"]["alto"]["de"] == 4
    json.dumps(r, ensure_ascii=False)


def test_evaluar_puntaje_sin_puntajes_pide_correr_src_puntaje(base) -> None:
    with pytest.raises(RuntimeError, match="src.puntaje"):
        eval_puntaje.evaluar(base, REGLAS, CFG, Z)


def test_el_cli_de_eval_puntaje(base, emb, tmp_path) -> None:
    prioridad.ejecutar(base, tmp_path / "prioridad.json", CORTE, None, emb=emb)
    salida = tmp_path / "puntaje.json"
    assert eval_puntaje.main(["--base", str(base), "--salida", str(salida)]) == 0
    assert json.loads(salida.read_text(encoding="utf-8"))["grupos"] == 4
    assert eval_puntaje.main(["--base", str(tmp_path / "nada.duckdb")]) == 1
