"""E1-08: calibración y métricas de pares de la agrupación (``eval/agrupacion.py``). Sin red ni modelo."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from eval import agrupacion as ev
from src import db, embeddings
from src.configuracion import cargar_reglas
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.test_agrupacion import INFLACION, SISMO, SISMO_AMPLIADO, fila, reglas_con

# ------------------------------------------------------------------ pares y F1


def test_pares_positivos_ignora_los_sueltos_y_la_diagonal() -> None:
    m = ev.pares_positivos(["a", "a", None, None, "b"])
    assert m[0, 1] and m[1, 0]
    assert not m[2, 3] and not m.diagonal().any() and not m[0, 4]


def test_conteo_de_pares_tp_fp_fn() -> None:
    real = ev.pares_positivos(["a", "a", "a", None])
    predicho = np.zeros((4, 4), dtype=bool)
    predicho[0, 1] = predicho[1, 0] = True       # TP
    predicho[0, 3] = predicho[3, 0] = True       # FP
    assert ev.conteo_de_pares(real, predicho) == (1, 1, 2)   # FN: (0,2) y (1,2)
    assert ev.conteo_de_pares(real, predicho, np.array([True, True, False, False])) == (1, 0, 0)


def test_f1_de_pares() -> None:
    assert ev.f1_de_pares(8, 2, 2) == pytest.approx(0.8)
    assert ev.f1_de_pares(0, 0, 0) is None
    assert ev.f1_de_pares(0, 3, 0) == 0.0


# ------------------------------------------------------------------ barrido y elección del umbral


def test_el_barrido_incluye_los_extremos_y_no_acumula_error() -> None:
    u = ev.umbrales_del_barrido(0.5, 0.99, 0.005)
    assert u[0] == 0.5 and u[-1] == 0.99 and len(u) == 99
    assert 0.55 in u and 0.845 in u


def test_elige_el_mayor_f1() -> None:
    assert ev.elegir_umbral([0.1, 0.2, 0.3], [0.5, 0.9, 0.7]) == 0.2


def test_en_una_meseta_elige_la_mitad_y_nunca_el_borde() -> None:
    umbrales = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    assert ev.elegir_umbral(umbrales, [0.5, 0.9, 0.9, 0.9, 0.9, 0.5]) == 0.3   # mediana inferior de 4 puntos
    assert ev.elegir_umbral(umbrales, [0.5, 0.9, 0.9, 0.9, 0.5, 0.5]) == 0.3   # 3 puntos: el del medio


def test_con_dos_mesetas_gana_la_mas_larga_y_en_empate_la_de_menor_umbral() -> None:
    umbrales = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    assert ev.elegir_umbral(umbrales, [0.9, 0.5, 0.9, 0.9, 0.9, 0.5, 0.9]) == 0.4
    assert ev.elegir_umbral(umbrales, [0.9, 0.9, 0.5, 0.5, 0.5, 0.9, 0.9]) == 0.1


def test_un_f1_indefinido_nunca_gana() -> None:
    assert ev.elegir_umbral([0.1, 0.2], [None, 0.0]) == 0.2


def test_el_pliegue_es_determinista_y_reparte_los_titulares() -> None:
    ids = [f"NOT-{i:04d}" for i in range(200)]
    pliegues = [ev.pliegue_de(i, 2) for i in ids]
    assert pliegues == [ev.pliegue_de(i, 2) for i in reversed(ids)][::-1]
    assert set(pliegues) == {0, 1} and 60 < sum(pliegues) < 140
    assert {ev.pliegue_de(i, 5) for i in ids} == set(range(5))


# ------------------------------------------------------------------ barrido completo con datos sintéticos


def _humanos(tmp_path: Path, grupos: dict[str, str]) -> Path:
    ruta = tmp_path / "etiquetas.csv"
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id_noticia", "titulo", "grupo"])
        w.writeheader()
        w.writerows({"id_noticia": i, "titulo": "x", "grupo": g} for i, g in grupos.items())
    return ruta


def _filas_sinteticas():
    """Dos eventos reales (sismo x4, inflación x3), dos sueltos y un ruido; en tres días."""
    filas = [fila(f"NOT-S{i}", t, dominio=f"s{i}.example", deteccion=f"2026-10-01T0{i}:00:00Z") for i, t in enumerate([SISMO, SISMO, SISMO_AMPLIADO, SISMO])]
    filas += [fila(f"NOT-I{i}", INFLACION, dominio=f"i{i}.example", deteccion=f"2026-10-02T0{i}:00:00Z") for i in range(3)]
    filas += [
        fila("NOT-X1", "Turistas llegan en cruceros al puerto de Colón", deteccion="2026-10-02T09:00:00Z"),
        fila("NOT-X2", "Aprueban ley sobre residuos y reciclaje en la Asamblea", deteccion="2026-10-02T10:00:00Z"),
        fila("NOT-R1", SISMO, dominio="r.example", deteccion="2026-10-01T05:00:00Z", es_ruido=True, motivo_ruido="no_es_panama"),
    ]
    return filas


GRUPOS_HUMANOS = {"NOT-S0": "sismo", "NOT-S1": "sismo", "NOT-S2": "sismo", "NOT-S3": "sismo", "NOT-I0": "inflacion", "NOT-I1": "inflacion",
                  "NOT-I2": "inflacion", "NOT-X1": "", "NOT-X2": "", "NOT-R1": ""}


@pytest.fixture
def base_y_etiquetas(tmp_path, monkeypatch):
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": _filas_sinteticas()})
    monkeypatch.setattr(ev, "crear", lambda cfg, nombre=None, **kw: embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path))
    return ruta, _humanos(tmp_path, GRUPOS_HUMANOS)


def _reglas_de_prueba():
    r = reglas_con(0.5)
    cal = r.agrupacion.calibracion.model_copy(update={"barrido_desde": 0.3, "barrido_hasta": 0.99, "barrido_paso": 0.01})
    return r.model_copy(update={"agrupacion": r.agrupacion.model_copy(update={"calibracion": cal})})


def test_evaluar_calibra_y_mide_pares_con_n_e_ic(base_y_etiquetas) -> None:
    ruta, etiquetas = base_y_etiquetas
    informe = ev.evaluar(ruta, etiquetas, config_de_prueba(), _reglas_de_prueba(), 1.96)
    assert informe["titulares_etiquetados"] == 10 and informe["pares_evaluados"] == 45 and informe["pares_positivos"] == 9
    m = informe["con_el_umbral_elegido"]
    assert m["fn"] == 0 and m["fp"] == 0 and m["f1"] == 1.0          # el barrido encuentra un umbral que separa los dos eventos
    assert (m["precision"]["n"], m["precision"]["de"]) == (9, 9) and len(m["recall"]["ic95"]) == 2
    assert informe["falsos_positivos"] == [] and informe["falsos_negativos"] == []
    assert informe["por_grupo_humano"] == {"inflacion": {"titulares": 3, "pares": 3, "recuperados": 3}, "sismo": {"titulares": 4, "pares": 6, "recuperados": 6}}
    assert informe["validacion_cruzada"]["pliegues"] == 2
    assert informe["regla_de_eleccion"].startswith("mayor F1")
    assert informe["curva"][0]["umbral"] == 0.3
    json.dumps(informe)


def test_la_linea_base_de_titulares_identicos_pierde_los_parafraseados(base_y_etiquetas) -> None:
    ruta, etiquetas = base_y_etiquetas
    informe = ev.evaluar(ruta, etiquetas, config_de_prueba(), _reglas_de_prueba(), 1.96)
    base = informe["linea_base_titulares_identicos"]
    assert base["precision"]["n"] == base["precision"]["de"]      # idénticos nunca son un falso positivo
    assert base["fn"] > 0 and base["f1"] < informe["con_el_umbral_elegido"]["f1"]


def test_el_ruido_que_pertenece_a_un_grupo_humano_cuenta_como_falso_negativo(tmp_path, monkeypatch) -> None:
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": _filas_sinteticas()})
    monkeypatch.setattr(ev, "crear", lambda cfg, nombre=None, **kw: embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path))
    humanos = {**GRUPOS_HUMANOS, "NOT-R1": "sismo"}               # una persona dijo que el ruido era del evento del sismo
    informe = ev.evaluar(ruta, _humanos(tmp_path, humanos), config_de_prueba(), _reglas_de_prueba(), 1.96)
    assert informe["con_el_umbral_elegido"]["fn"] == 4
    assert all("NOT-R1" in par for par in informe["falsos_negativos"])


def test_una_etiqueta_que_no_esta_en_la_base_se_rechaza(base_y_etiquetas, tmp_path) -> None:
    ruta, _ = base_y_etiquetas
    otra = _humanos(tmp_path, {"NOT-NO-EXISTE": "x", "NOT-S0": "x"})
    with pytest.raises(RuntimeError, match="no están en la base"):
        ev.evaluar(ruta, otra, config_de_prueba(), _reglas_de_prueba(), 1.96)


def test_la_validacion_cruzada_mide_en_pares_que_la_calibracion_no_vio(base_y_etiquetas) -> None:
    ruta, etiquetas = base_y_etiquetas
    informe = ev.evaluar(ruta, etiquetas, config_de_prueba(), _reglas_de_prueba(), 1.96)
    cv = informe["validacion_cruzada"]
    total = sum(p["titulares_de_prueba"] for p in cv["por_pliegue"])
    assert total == informe["titulares_etiquetados"]
    por_pliegue = sum(p["tp"] + p["fp"] + p["fn"] for p in cv["por_pliegue"])
    agrupado = cv["agrupado"]
    assert agrupado["tp"] + agrupado["fp"] + agrupado["fn"] == por_pliegue
    assert por_pliegue <= informe["pares_positivos"] + informe["pares_evaluados"]


def test_las_salidas_se_escriben(base_y_etiquetas, tmp_path) -> None:
    ruta, etiquetas = base_y_etiquetas
    informe = ev.evaluar(ruta, etiquetas, config_de_prueba(), _reglas_de_prueba(), 1.96)
    salida, curva = tmp_path / "o" / "agrupacion.json", tmp_path / "o" / "curva.csv"
    ev.escribir_salidas(informe, salida, curva)
    assert json.loads(salida.read_text(encoding="utf-8"))["umbral_elegido"] == informe["umbral_elegido"]
    filas = list(csv.DictReader(curva.open(encoding="utf-8")))
    assert len(filas) == len(informe["curva"]) and set(filas[0]) == {"umbral", "tp", "fp", "fn", "f1"}


def test_sin_etiquetas_no_se_calcula_ninguna_metrica(tmp_path, capsys) -> None:
    assert ev.main(["--etiquetas", str(tmp_path / "no_existe.csv")]) == ev.CODIGO_SIN_ETIQUETAS
    assert "sin etiquetas" in capsys.readouterr().err


# ------------------------------------------------------------------ la configuración real


def test_el_barrido_real_contiene_el_umbral_configurado() -> None:
    cal = cargar_reglas().agrupacion.calibracion
    umbral = cargar_reglas().agrupacion.umbral_similitud
    assert umbral in ev.umbrales_del_barrido(cal.barrido_desde, cal.barrido_hasta, cal.barrido_paso)
