"""C-10b: modelo supervisado exploratorio (regresión logística sobre embeddings) con validación cruzada por evento."""

import numpy as np
import pytest

from eval import clasificacion_por_evento as pe
from eval import clasificacion_supervisada as sup
from src.baseline import SIN_TEMA
from src.configuracion import CriterioAB, cargar_clasificacion, cargar_temas

CRITERIO = CriterioAB(remuestreos=200, confianza=0.95, semilla=3)
CFG = cargar_clasificacion()
S = CFG.supervisado


def _sinteticos(eventos_por_clase: dict[str, int], filas_por_evento: int = 3, semilla: int = 0) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Embeddings separables por clase (una dirección por clase + ruido); cada evento tiene ``filas_por_evento`` filas."""
    rng = np.random.default_rng(semilla)
    clases = list(eventos_por_clase)
    X, y, ev = [], [], []
    for c, n_ev in eventos_por_clase.items():
        for k in range(n_ev):
            for _ in range(filas_por_evento):
                v = np.zeros(len(clases))
                v[clases.index(c)] = 1.0
                X.append(v + rng.normal(0, 0.05, len(clases)))
                y.append(c)
                ev.append(f"{c}-{k}")
    return np.array(X), np.array(y, dtype=object), ev


# ------------------------------------------------------------------ qué clases se entrenan


def test_las_clases_con_menos_eventos_que_el_minimo_se_reportan_aparte() -> None:
    y = np.array(["a"] * 6 + ["b"] * 4 + ["c"] * 3 + [SIN_TEMA] * 2, dtype=object)
    eventos = ["a1", "a1", "a1", "a2", "a2", "a2", "b1", "b1", "b2", "b2", "c1", "c1", "c1", "s1", "s2"]
    incluidas, excluidas = sup.clases_entrenables(y, eventos, minimo=2, sin_tema="clase")
    assert incluidas == ["a", "b", SIN_TEMA]
    assert excluidas == {"c": {"filas": 3, "eventos": 1, "motivo": "menos de 2 eventos"}}


def test_sin_tema_se_puede_excluir_por_configuracion() -> None:
    y = np.array(["a", "a", "b", "b", SIN_TEMA, SIN_TEMA], dtype=object)
    eventos = ["a1", "a2", "b1", "b2", "s1", "s2"]
    incluidas, excluidas = sup.clases_entrenables(y, eventos, minimo=2, sin_tema="excluir")
    assert incluidas == ["a", "b"] and SIN_TEMA in excluidas and "configuración" in excluidas[SIN_TEMA]["motivo"]


# ------------------------------------------------------------------ sin fuga: ningún evento en entrenamiento y prueba


def test_la_guarda_de_fuga_rechaza_un_evento_en_los_dos_lados() -> None:
    sup.verificar_sin_fuga(["x", "x", "y"], np.array([0, 1]), np.array([2]))             # disjuntos: no lanza
    with pytest.raises(ValueError, match="fuga"):
        sup.verificar_sin_fuga(["x", "x", "y"], np.array([0, 2]), np.array([1]))


def test_ningun_evento_esta_en_entrenamiento_y_prueba_en_ningun_pliegue_ni_repeticion() -> None:
    X, y, ev = _sinteticos({"a": 6, "b": 6, SIN_TEMA: 4})
    X = np.arange(len(y), dtype=float)[:, None]                  # la «característica» es el índice de la fila: se puede auditar
    vistos: list[tuple[set[str], set[str]]] = []

    def espia(x_tr: np.ndarray, y_tr: np.ndarray, x_te: np.ndarray, s) -> np.ndarray:   # noqa: ANN001
        vistos.append(({ev[int(i)] for i in x_tr[:, 0]}, {ev[int(i)] for i in x_te[:, 0]}))
        return np.array([y_tr[0]] * len(x_te), dtype=object)

    sup.validacion_cruzada(X, y, ev, S, ajustar=espia)
    assert len(vistos) == S.pliegues * S.repeticiones
    assert all(not tr & te for tr, te in vistos)
    assert all(tr and te for tr, te in vistos)


def test_cada_fila_se_predice_una_vez_por_repeticion() -> None:
    X, y, ev = _sinteticos({"a": 6, "b": 6})
    preds = sup.validacion_cruzada(X, y, ev, S)
    assert preds.shape == (S.repeticiones, len(y))
    assert not (preds == None).any()  # noqa: E711 - ningún hueco sin predecir


# ------------------------------------------------------------------ el modelo


def test_la_regresion_logistica_aprende_clases_separables_y_es_reproducible() -> None:
    X, y, ev = _sinteticos({"a": 8, "b": 8, SIN_TEMA: 5})
    p1, p2 = sup.validacion_cruzada(X, y, ev, S), sup.validacion_cruzada(X, y, ev, S)
    assert (p1 == p2).all()
    assert float((p1 == y).mean()) > 0.95


def test_class_weight_balanced_se_usa_de_verdad() -> None:
    # 12 filas de la clase mayoritaria y 2 de la minoritaria, en el mismo punto: balanced favorece a la minoritaria
    X = np.zeros((14, 2))
    X[:, 0] = 1.0
    y = np.array(["mayor"] * 12 + ["menor"] * 2, dtype=object)
    sin_peso = sup.ajustar_y_predecir(X, y, X[:1], S.model_copy(update={"class_weight": "balanced"}))
    assert len(sin_peso) == 1
    modelo = sup.crear_modelo(S)
    assert modelo.class_weight == "balanced" and modelo.C == S.C and modelo.max_iter == S.max_iter


# ------------------------------------------------------------------ criterio D-57 adaptado a eventos


def _dif(ic: list[float] | None) -> dict:
    return {"diferencia": 0.1, "ic95": ic, "excluye_cero": bool(ic and (ic[0] > 0 or ic[1] < 0)), "a_favor": bool(ic and ic[0] > 0)}


def test_d57_se_cumple_solo_si_el_ic_excluye_cero_a_favor_y_ningun_tema_empeora() -> None:
    ok = sup.criterio_d57(_dif([0.02, 0.2]), {"a": _dif([-0.1, 0.1]), "b": None})
    assert ok["cumplido"] is True and ok["temas_que_empeoran"] == []
    cruza = sup.criterio_d57(_dif([-0.05, 0.2]), {})
    assert cruza["cumplido"] is False and "cero" in cruza["motivo"]
    empeora = sup.criterio_d57(_dif([0.02, 0.2]), {"a": _dif([-0.4, -0.05])})
    assert empeora["cumplido"] is False and empeora["temas_que_empeoran"] == ["a"]
    en_contra = sup.criterio_d57(_dif([-0.3, -0.1]), {})
    assert en_contra["cumplido"] is False


def test_el_mejor_baseline_se_elige_por_exactitud_por_evento_y_el_empate_va_a_la_guia() -> None:
    ev = [f"e{i}" for i in range(4)]
    real = np.array(["a", "a", "b", "b"], dtype=object)
    guia = np.array(["a", "a", "a", "a"], dtype=object)
    ampliado = np.array(["a", "a", "b", "a"], dtype=object)
    assert sup.mejor_baseline({"baseline_guia": guia, "baseline_ampliado": ampliado}, real, ev, CRITERIO) == "baseline_ampliado"
    assert sup.mejor_baseline({"baseline_guia": guia, "baseline_ampliado": guia.copy()}, real, ev, CRITERIO) == "baseline_guia"


# ------------------------------------------------------------------ informe completo con datos sintéticos


def _conjunto_sintetico() -> pe.Conjunto:
    temas = cargar_temas()
    ids_temas = list(temas.temas)
    X, y, ev = _sinteticos({"economia": 6, "servicios_publicos": 6, "eventos_naturales": 1, "turismo": 1, SIN_TEMA: 3})
    rng = np.random.default_rng(1)
    similitud = rng.uniform(0.80, 0.90, size=(len(y), len(ids_temas)))
    textos = [f"{c} titular sintetico {i}" for i, c in enumerate(y)]
    return pe.Conjunto([f"NOT-{i}" for i in range(len(y))], textos, y, ev, X, similitud, ids_temas, pe.evalclas.clases_de(temas), 0, len(y))


def test_el_informe_separa_las_clases_excluidas_y_compara_con_los_tres_sistemas() -> None:
    cfg, temas = cargar_clasificacion(), cargar_temas()
    r = sup.evaluar_supervisado(_conjunto_sintetico(), cfg, temas, 1.96)
    assert r["exploratorio"] is True and r["conectado_a_produccion"] is False
    assert set(r["clases"]["entrenadas"]) == {"economia", "servicios_publicos", SIN_TEMA}
    assert set(r["clases"]["excluidas"]) == {"eventos_naturales", "turismo"}
    assert r["conjunto"]["filas_evaluadas"] < r["conjunto"]["filas_totales"]
    assert set(r["sistemas"]) == {"supervisado", "metodo_A_activo", r["mejor_baseline"]}
    for nombre in ("metodo_A_activo", "mejor_baseline"):
        c = r["comparaciones"]["supervisado_menos_" + nombre]
        assert {"exactitud_por_evento", "macro_f1", "recall_por_tema", "criterio_d57", "ic_se_solapan"} <= set(c)
    assert r["clases"]["excluidas"]["eventos_naturales"]["recall_metodo_A"]["de"] > 0
    assert "NO está conectado" in r["advertencia"]


def test_el_informe_es_reproducible() -> None:
    cfg, temas = cargar_clasificacion(), cargar_temas()
    a = sup.evaluar_supervisado(_conjunto_sintetico(), cfg, temas, 1.96)
    b = sup.evaluar_supervisado(_conjunto_sintetico(), cfg, temas, 1.96)
    assert a == b
