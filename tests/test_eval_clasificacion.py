"""E1-07: métricas con n e IC, criterio A vs. B (D-57) y evaluación con etiquetas humanas (sin red, sin modelo)."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from eval import calibrar_clasificacion, clasificacion as evalclas, metricas
from src.baseline import SIN_TEMA
from src.configuracion import CriterioAB, cargar_clasificacion, cargar_temas
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.test_clasificacion import FILAS, _base

CRITERIO = CriterioAB(remuestreos=300, confianza=0.95, semilla=7)
Z = 1.96


# ------------------------------------------------------------------ métricas


def test_f1_precision_y_recall_con_valores_conocidos() -> None:
    real = ["a", "a", "a", "b", "b", "c"]
    pred = ["a", "a", "b", "b", "b", "a"]
    m = metricas.por_clase(real, pred, ["a", "b", "c"], Z)
    assert (m["a"]["precision"]["n"], m["a"]["precision"]["de"]) == (2, 3)      # 2 de 3 predichos "a" lo son
    assert (m["a"]["recall"]["n"], m["a"]["recall"]["de"]) == (2, 3)            # 2 de 3 reales "a" se hallaron
    assert m["a"]["f1"] == pytest.approx(2 * 2 / (2 * 2 + 1 + 1), abs=1e-4)
    assert m["b"]["f1"] == pytest.approx(2 * 2 / (2 * 2 + 1 + 0), abs=1e-4)
    assert m["c"]["f1"] == 0.0 and m["c"]["precision"]["de"] == 0              # nunca predicha: precisión sin base
    assert metricas.macro_f1(real, pred, ["a", "b", "c"]) == pytest.approx((0.6667 + 0.8 + 0.0) / 3, abs=1e-3)


def test_la_matriz_de_confusion_cuenta_filas_reales_y_columnas_predichas() -> None:
    m = metricas.matriz_confusion(["a", "a", "b"], ["a", "b", "b"], ["a", "b"])
    assert m == [[1, 1], [0, 1]]
    assert sum(map(sum, m)) == 3


def test_una_clase_sin_soporte_ni_predicciones_queda_indefinida_no_cero() -> None:
    assert metricas.f1_de(0, 0, 0) is None
    m = metricas.por_clase(["a", "a"], ["a", "a"], ["a", "b"], Z)
    assert m["b"]["f1"] is None
    assert metricas.macro_f1(["a", "a"], ["a", "a"], ["a", "b"]) == 1.0          # solo promedia lo definido


def test_el_ic_de_bootstrap_es_reproducible_y_contiene_el_valor_puntual() -> None:
    rng = np.random.default_rng(0)
    clases = ["a", "b", "c"]
    real = list(rng.choice(clases, 60))
    pred = [r if rng.random() < 0.7 else str(rng.choice(clases)) for r in real]
    r1 = metricas.macro_f1_con_ic(real, pred, clases, CRITERIO)
    r2 = metricas.macro_f1_con_ic(real, pred, clases, CRITERIO)
    assert r1 == r2 and r1["n"] == 60 and r1["remuestreos"] == 300
    assert r1["ic95"][0] <= r1["macro_f1"] <= r1["ic95"][1]
    otro = metricas.macro_f1_con_ic(real, pred, clases, CriterioAB(remuestreos=300, confianza=0.95, semilla=8))
    assert otro["macro_f1"] == r1["macro_f1"]                                      # la semilla solo mueve el IC


def test_ic_mas_ancho_con_menos_datos() -> None:
    clases = ["a", "b"]
    grande = (["a", "b"] * 50, ["a", "b"] * 45 + ["b", "a"] * 5)
    chico = (["a", "b"] * 5, ["a", "b"] * 4 + ["b", "a"])
    anchura = lambda r: r["ic95"][1] - r["ic95"][0]  # noqa: E731
    assert anchura(metricas.macro_f1_con_ic(*chico, clases, CRITERIO)) > anchura(metricas.macro_f1_con_ic(*grande, clases, CRITERIO))


def test_criterio_elige_b_si_el_ic_de_la_diferencia_excluye_el_cero_y_nadie_empeora() -> None:
    clases = ["a", "b", "c"]
    real = ["a", "b", "c"] * 40
    pred_a = [r if i % 3 else "b" for i, r in enumerate(real)]       # A falla mucho
    pred_b = list(real)                                             # B perfecto
    c = metricas.aplicar_criterio(real, pred_a, pred_b, clases, CRITERIO)
    assert c["decision"] == "B" and c["excluye_cero"] and c["ic95"][0] > 0 and c["temas_que_empeoran"] == []


def test_criterio_elige_a_si_el_ic_incluye_el_cero() -> None:
    clases = ["a", "b"]
    real = ["a", "b"] * 10
    pred_a = list(real)
    pred_b = list(real)
    pred_b[0] = "b"                                                  # una diferencia de ruido
    c = metricas.aplicar_criterio(real, pred_a, pred_b, clases, CRITERIO)
    assert c["decision"] == "A" and "incluye el cero" in c["motivo"]


def test_criterio_elige_a_si_b_empeora_un_tema_de_forma_significativa() -> None:
    clases = ["a", "b", "c"]
    real = ["a"] * 60 + ["b"] * 60 + ["c"] * 6
    pred_a = [("b" if i < 30 else "a") if r == "a" else r for i, r in enumerate(real)]   # A confunde la mitad de "a"
    pred_b = [("a" if r == "b" else r) for r in real]                                       # B pierde todo "b"
    c = metricas.aplicar_criterio(real, pred_a, pred_b, clases, CRITERIO)
    assert "b" in c["temas_que_empeoran"] and c["decision"] == "A"


def test_criterio_elige_a_si_b_es_significativamente_peor() -> None:
    clases = ["a", "b"]
    real = ["a", "b"] * 30
    c = metricas.aplicar_criterio(real, list(real), ["b", "a"] * 30, clases, CRITERIO)
    assert c["decision"] == "A" and c["ic95"][1] < 0 and "a favor de A" in c["motivo"]


# ------------------------------------------------------------------ casos difíciles: lectura y fuga


def test_los_casos_dificiles_se_leen_de_la_guia() -> None:
    casos = evalclas.leer_casos_dificiles()
    assert len(casos) == 15
    por_id = {c.id: c for c in casos}
    assert (por_id["CD-01"].principal, por_id["CD-01"].secundario) == ("logistica", "eventos_naturales")
    assert (por_id["CD-03"].principal, por_id["CD-03"].secundario) == ("eventos_naturales", None)
    assert (por_id["CD-15"].principal, por_id["CD-15"].secundario) == (SIN_TEMA, None)
    assert sum(1 for c in casos if c.secundario) == 7
    assert {c.principal for c in casos} == {*cargar_temas().temas, SIN_TEMA}


def test_ningun_caso_dificil_es_ejemplo_ni_prototipo_ni_descripcion() -> None:
    """Son casos de prueba: si sirven de referencia al clasificador, la medición es una fuga."""
    from src.limpieza import Reglas

    assert evalclas.casos_en_referencias(evalclas.leer_casos_dificiles(), cargar_temas(), Reglas.desde_config()) == []


def test_el_detector_de_fuga_encuentra_un_ejemplo_copiado_o_casi_copiado() -> None:
    from src.limpieza import Reglas

    temas = cargar_temas()
    ejemplo = temas.temas["turismo"].ejemplos[3].titulo
    casos = [evalclas.CasoDificil("CD-X", ejemplo.upper(), "turismo", None, "6"), evalclas.CasoDificil("CD-Y", ejemplo + " hoy", "turismo", None, "6")]
    problemas = evalclas.casos_en_referencias(casos, temas, Reglas.desde_config())
    assert any(p.startswith("CD-X") for p in problemas) and any(p.startswith("CD-Y") for p in problemas)


def test_la_evaluacion_se_niega_a_correr_si_hay_fuga(monkeypatch) -> None:
    caso = evalclas.CasoDificil("CD-X", cargar_temas().temas["turismo"].ejemplos[3].titulo, "turismo", None, "6")
    monkeypatch.setattr(evalclas, "leer_casos_dificiles", lambda *a, **k: [caso])
    with pytest.raises(ValueError, match="fuga"):
        evalclas.evaluar_casos_dificiles(cargar_clasificacion(), cargar_temas(), ["e5"], {"e5": MotorFalso()})


def test_tema_a_id_acepta_nombres_ids_y_fuera_de_temas() -> None:
    t = cargar_temas()
    assert evalclas.tema_a_id("Logística/Canal", t) == "logistica"
    assert evalclas.tema_a_id("`fuera_de_temas`", t) == SIN_TEMA
    assert evalclas.tema_a_id("no_es_panama", t) == SIN_TEMA
    assert evalclas.tema_a_id("—", t) is None and evalclas.tema_a_id("", t) is None
    with pytest.raises(ValueError, match="desconocido"):
        evalclas.tema_a_id("Deportes", t)


def test_la_evaluacion_de_casos_dificiles_reporta_todo_lo_que_pide_la_spec(tmp_path) -> None:
    cfg = config_de_prueba()
    r = evalclas.evaluar_casos_dificiles(cfg, cargar_temas(), ["e5"], {"e5": MotorFalso()})
    assert set(r["configuraciones"]) == {"baseline", "e5/A", "e5/B"} and r["n"] == 15
    for c in r["configuraciones"].values():
        assert c["exactitud_principal"]["de"] == 15 and len(c["exactitud_principal"]["ic95"]) == 2
        assert c["macro_f1"]["n"] == 15 and c["macro_f1"]["ic95"] is not None and c["macro_f1"]["remuestreos"] == cfg.criterio_ab.remuestreos
        assert set(c["por_tema"]) == set(evalclas.clases_de(cargar_temas()))
        for v in c["por_tema"].values():
            assert {"precision", "recall", "f1", "soporte"} <= set(v) and "de" in v["precision"] and "ic95" in v["recall"]
        m = np.array(c["matriz_confusion"]["filas_real_columnas_predicho"])
        assert m.shape == (7, 7) and m.sum() == 15
    crit = r["comparaciones"]["e5"]["criterio_A_vs_B"]
    assert crit["decision"] in {"A", "B"} and "motivo" in crit and "ic95" in crit
    assert {"A_menos_baseline", "B_menos_baseline"} <= set(r["comparaciones"]["e5"])


# ------------------------------------------------------------------ etiquetas humanas


def _escribir_etiquetas(ruta: Path, filas: list[dict], columnas=("id_noticia", "tema_principal", "tema_secundario")) -> Path:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)
    return ruta


ETIQUETAS_OK = [
    {"id_noticia": "NOT-1", "tema_principal": "economia", "tema_secundario": ""},
    {"id_noticia": "NOT-2", "tema_principal": "Logística/Canal", "tema_secundario": ""},
    {"id_noticia": "NOT-3", "tema_principal": "turismo", "tema_secundario": ""},
    {"id_noticia": "NOT-4", "tema_principal": "eventos_naturales", "tema_secundario": ""},
    {"id_noticia": "NOT-5", "tema_principal": "regulacion", "tema_secundario": ""},
    {"id_noticia": "NOT-6", "tema_principal": "servicios_publicos", "tema_secundario": ""},
    {"id_noticia": "NOT-7", "tema_principal": "fuera_de_temas", "tema_secundario": ""},     # el sistema lo marcó ruido
]


def _evaluar(tmp_path, etiquetas=ETIQUETAS_OK, filas=FILAS, columna="tema_principal", excluidos=None, monkeypatch=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    ruta_etiquetas = _escribir_etiquetas(tmp_path / "etiquetas.csv", etiquetas)
    ruta_base = _base(tmp_path, filas)
    cfg = config_de_prueba()
    temas = cargar_temas()
    if monkeypatch is not None and excluidos is not None:
        monkeypatch.setattr(evalclas, "ids_excluidos", lambda *a, **k: excluidos)
    return evalclas.evaluar_etiquetas(ruta_etiquetas, ruta_base, columna, cfg, temas, ["e5"], {"e5": MotorFalso()})


def test_con_etiquetas_se_evalua_solo_lo_que_no_es_ruido_y_se_cuenta_lo_demas(tmp_path) -> None:
    r = _evaluar(tmp_path)
    assert r["estado"] == "EVALUADO"
    assert r["conteo"] == {"etiquetados": 7, "ejemplos_excluidos": 0, "no_estan_en_la_base": 0, "marcados_como_ruido_por_el_sistema": 1, "evaluados": 6}
    assert r["configuraciones"]["baseline"]["exactitud_principal"]["de"] == 6
    assert set(r["configuraciones"]) == {"baseline", "e5/A", "e5/B"}


def test_los_ejemplos_excluidos_no_entran_en_la_evaluacion(tmp_path, monkeypatch) -> None:
    r = _evaluar(tmp_path, excluidos={"NOT-1", "NOT-2"}, monkeypatch=monkeypatch)
    assert r["conteo"]["ejemplos_excluidos"] == 2 and r["conteo"]["evaluados"] == 4
    assert r["configuraciones"]["e5/A"]["exactitud_principal"]["de"] == 4


def test_los_ids_excluidos_reales_son_los_de_temas_yaml() -> None:
    reales = {e.id_noticia for t in cargar_temas().temas.values() for e in t.ejemplos if e.real}
    assert evalclas.ids_excluidos() == reales and reales


def test_nunca_se_usa_el_tema_de_origen_ni_como_etiqueta_ni_como_entrada(tmp_path) -> None:
    """D-62: con el ``tema`` de origen envenenado, las métricas no cambian; y una columna de etiquetas inexistente falla."""
    base = _evaluar(tmp_path / "a")
    envenenadas = _evaluar(tmp_path / "b", filas=[dict(f, tema="regulacion") for f in FILAS])
    assert json.dumps(base, sort_keys=True) == json.dumps(envenenadas, sort_keys=True)
    ruta = _escribir_etiquetas(tmp_path / "x.csv", ETIQUETAS_OK)
    with pytest.raises(KeyError, match="tema"):
        evalclas.leer_etiquetas(ruta, "tema", cargar_temas())      # no hay columna "tema": no se cae al origen por defecto


def test_una_etiqueta_con_tema_desconocido_se_rechaza(tmp_path) -> None:
    malas = [dict(ETIQUETAS_OK[0], tema_principal="deportes")]
    with pytest.raises(ValueError, match="desconocido"):
        _evaluar(tmp_path, malas)


def test_sin_filas_evaluables_no_hay_metricas(tmp_path) -> None:
    r = _evaluar(tmp_path, etiquetas=[{"id_noticia": "NOT-99", "tema_principal": "economia", "tema_secundario": ""}])
    assert r["estado"] == "SIN_FILAS_EVALUABLES" and "configuraciones" not in r


def test_las_celdas_vacias_son_sin_etiquetar_no_sin_tema(tmp_path) -> None:
    r = _evaluar(tmp_path, etiquetas=[*ETIQUETAS_OK[:5], {"id_noticia": "NOT-6", "tema_principal": "", "tema_secundario": ""}])
    assert r["conteo"]["etiquetados"] == 5 and r["conteo"]["evaluados"] == 5


def test_main_sin_etiquetas_no_inventa_metricas_reales(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(evalclas, "evaluar_casos_dificiles", lambda *a, **k: {"n": 0, "configuraciones": {}, "comparaciones": {}})
    salida = tmp_path / "salida.json"
    codigo = evalclas.main(["--etiquetas", str(tmp_path / "no_existe.csv"), "--salida", str(salida)])
    err = capsys.readouterr().err
    assert codigo == evalclas.CODIGO_SIN_ETIQUETAS and "PENDIENTE" in err and "no se inventan" in err
    informe = json.loads(salida.read_text(encoding="utf-8"))
    assert informe["datos_reales"]["estado"] == "PENDIENTE_ETIQUETAS" and "configuraciones" not in informe["datos_reales"]


# ------------------------------------------------------------------ calibración provisional


def test_el_auc_mide_cuanto_separa_la_similitud() -> None:
    assert calibrar_clasificacion.auc(np.array([0.1, 0.2]), np.array([0.8, 0.9])) == 1.0
    assert calibrar_clasificacion.auc(np.array([0.8]), np.array([0.1])) == 0.0
    assert calibrar_clasificacion.auc(np.array([0.5]), np.array([0.5])) == 0.5
    assert calibrar_clasificacion.auc(np.array([]), np.array([0.5])) is None


def test_los_umbrales_del_yaml_son_provisionales_y_estan_documentados() -> None:
    texto = (Path(__file__).resolve().parent.parent / "config" / "clasificacion.yaml").read_text(encoding="utf-8")
    assert "PROVISIONALES" in texto and "eval.calibrar_clasificacion" in texto
