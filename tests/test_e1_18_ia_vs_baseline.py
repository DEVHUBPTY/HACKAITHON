"""E1-18 · D-66: funciones puras de ``eval/ia_vs_baseline.py`` (sin modelo, sin red, entradas sintéticas)."""

from __future__ import annotations

import numpy as np
import pytest

from eval import ia_vs_baseline as iv
from src.configuracion import CriterioAB

CRITERIO = CriterioAB(remuestreos=300, confianza=0.95, semilla=7)


# ------------------------------------------------------------------ veredicto (regla de D-21/D-57)


@pytest.mark.parametrize(
    ("ic", "esperado"),
    [
        ([0.01, 0.4], "gana_ia"),
        ([-0.4, -0.01], "pierde_ia"),
        ([-0.1, 0.3], "sin_diferencia_demostrable"),
        ([0.0, 0.3], "sin_diferencia_demostrable"),    # el cero en el borde NO excluye el cero
        ([-0.3, 0.0], "sin_diferencia_demostrable"),
        (None, "no_medible"),
    ],
)
def test_veredicto_solo_si_el_ic_excluye_el_cero(ic: list[float] | None, esperado: str) -> None:
    assert iv.veredicto_por_ic(ic) == esperado


# ------------------------------------------------------------------ discordantes


def test_discordantes_separa_los_cuatro_casos_con_ids() -> None:
    ids = ["a", "b", "c", "d", "e"]
    reales = ["x", "x", "y", "y", "z"]
    ia = ["x", "x", "y", "z", "z"]      # acierta a, b, c, e
    base = ["x", "y", "z", "y", "y"]    # acierta a, d
    d = iv.discordantes(ids, reales, ia, base)
    assert d["ambos_aciertan"] == ["a"]
    assert d["solo_ia"] == ["b", "c", "e"]
    assert d["solo_baseline"] == ["d"]
    assert d["ambos_fallan"] == []
    assert d["conteo"] == {"ambos_aciertan": 1, "solo_ia": 3, "solo_baseline": 1, "ambos_fallan": 0, "n": 5}


def test_discordantes_exige_la_misma_longitud() -> None:
    with pytest.raises(ValueError):
        iv.discordantes(["a"], ["x", "y"], ["x"], ["x"])


def test_mcnemar_exacto_simetrico_y_sin_discordantes() -> None:
    assert iv.mcnemar_exacto(0, 0) == 1.0
    assert iv.mcnemar_exacto(5, 5) == 1.0
    assert iv.mcnemar_exacto(10, 0) == pytest.approx(2 * 0.5**10)
    assert iv.mcnemar_exacto(3, 9) == iv.mcnemar_exacto(9, 3)


# ------------------------------------------------------------------ baseline de titulares idénticos


def test_matriz_identicos_ignora_ruido_mayusculas_y_tildes() -> None:
    filas = [
        {"titulo_limpio": "Canal de Panamá", "es_ruido": False},
        {"titulo_limpio": "canal de panama", "es_ruido": False},
        {"titulo_limpio": "Canal de Panamá", "es_ruido": True},     # ruido: no se une
        {"titulo_limpio": "Otro titular", "es_ruido": False},
        None,                                                       # fila ausente
    ]
    m = iv.matriz_identicos(filas)
    assert m[0, 1] and m[1, 0]
    assert not m[0, 2] and not m[0, 3] and not m[4].any()
    assert not np.diag(m).any()


# ------------------------------------------------------------------ bootstrap por titular (pares)


def _escenario() -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]:
    """6 titulares; real = {0-1, 0-2, 1-2, 3-4}; A (IA) los recupera todos y añade un FP 4-5; B (identicos) solo 0-1."""
    n = 6
    real = np.zeros((n, n), dtype=bool)
    for i, j in [(0, 1), (0, 2), (1, 2), (3, 4)]:
        real[i, j] = real[j, i] = True
    ia = real.copy()
    ia[4, 5] = ia[5, 4] = True
    base = np.zeros((n, n), dtype=bool)
    base[0, 1] = base[1, 0] = True
    alcance = np.ones(n, dtype=bool)
    return real, {"ia": ia, "baseline": base}, alcance


def test_bootstrap_por_titular_trae_conteos_puntuales_exactos() -> None:
    real, pred, alcance = _escenario()
    r = iv.pares_cluster_bootstrap(real, pred, alcance, CRITERIO)
    assert (r["ia"]["tp"], r["ia"]["fp"], r["ia"]["fn"]) == (4, 1, 0)
    assert (r["baseline"]["tp"], r["baseline"]["fp"], r["baseline"]["fn"]) == (1, 0, 3)
    assert r["ia"]["precision"]["valor"] == pytest.approx(0.8)
    assert r["baseline"]["recall"]["valor"] == pytest.approx(0.25)
    assert r["ia"]["f1"]["valor"] == pytest.approx(2 * 4 / (2 * 4 + 1 + 0), abs=1e-4)
    assert r["n_titulares"] == 6
    assert r["unidad_de_remuestreo"] == "titular"


def test_bootstrap_por_titular_es_reproducible_y_pareado() -> None:
    real, pred, alcance = _escenario()
    a = iv.pares_cluster_bootstrap(real, pred, alcance, CRITERIO)
    b = iv.pares_cluster_bootstrap(real, pred, alcance, CRITERIO)
    assert a == b
    dif = a["diferencia_ia_menos_baseline"]
    assert dif["recall"]["valor"] == pytest.approx(1.0 - 0.25)
    lo, hi = dif["recall"]["ic95"]
    assert lo <= dif["recall"]["valor"] <= hi + 1e-9


def test_bootstrap_respeta_el_alcance() -> None:
    real, pred, _ = _escenario()
    alcance = np.array([True, True, True, False, False, False])     # solo los pares entre 0, 1 y 2
    r = iv.pares_cluster_bootstrap(real, pred, alcance, CRITERIO)
    assert (r["ia"]["tp"], r["ia"]["fp"], r["ia"]["fn"]) == (3, 0, 0)
    assert (r["baseline"]["tp"], r["baseline"]["fn"]) == (1, 2)


# ------------------------------------------------------------------ ejemplos deterministas


def test_ejemplos_de_pares_no_repiten_titulares_y_siguen_el_orden() -> None:
    pares = [("n3", "n1"), ("n1", "n2"), ("n1", "n4"), ("n5", "n6"), ("n2", "n7")]
    elegidos = iv.elegir_ejemplos_pares(pares, 3)
    assert elegidos == [("n1", "n2"), ("n5", "n6")]
    usados = [x for p in elegidos for x in p]
    assert len(usados) == len(set(usados))
    assert iv.elegir_ejemplos_pares(pares, 3) == elegidos            # determinista
    assert iv.elegir_ejemplos_pares([], 3) == []


def test_ejemplos_de_ids_son_los_primeros_ordenados() -> None:
    assert iv.elegir_ejemplos_ids(["c", "a", "b", "d"], 2) == ["a", "b"]


# ------------------------------------------------------------------ búsqueda por consulta


@pytest.mark.parametrize(
    ("k_ia", "k_base", "n", "esperado"),
    [
        (2, 1, 2, "gana_ia"),
        (1, 2, 2, "gana_baseline"),
        (2, 2, 2, "empate_completo"),
        (1, 1, 2, "empate_incompleto"),
        (0, 0, 3, "empate_incompleto"),
    ],
)
def test_categoria_de_consulta(k_ia: int, k_base: int, n: int, esperado: str) -> None:
    assert iv.categoria_de_consulta(k_ia, k_base, n) == esperado


# ------------------------------------------------------------------ ranking: baseline por fecha


def test_ranking_por_fecha_ordena_reciente_primero_y_desempata_por_id() -> None:
    grupos = {
        "GRP-b": "2026-10-05T10:00:00Z",
        "GRP-a": "2026-10-05T10:00:00Z",
        "GRP-c": "2026-10-06T08:00:00Z",
        "GRP-d": "2026-10-01T00:00:00Z",
    }
    assert iv.ranking_por_fecha(grupos) == ["GRP-c", "GRP-a", "GRP-b", "GRP-d"]


def test_solapamiento_del_top() -> None:
    s = iv.solapamiento_top(["a", "b", "c", "d"], ["b", "x", "a", "y"], 3)
    assert s == {"k": 3, "coinciden": ["a", "b"], "solo_sistema": ["c"], "solo_baseline": ["x"], "n_coinciden": 2}


def test_empates_en_el_corte_cuenta_los_grupos_con_la_misma_fecha_del_puesto_k() -> None:
    grupos = {"g1": "2026-10-06T08:00:00Z", "g2": "2026-10-05T00:00:00Z", "g3": "2026-10-05T00:00:00Z", "g4": "2026-10-05T00:00:00Z"}
    orden = iv.ranking_por_fecha(grupos)
    assert iv.empates_en_el_corte(grupos, orden, 2) == ["g2", "g3", "g4"]
    assert iv.empates_en_el_corte(grupos, orden, 1) == []


def test_alcance_puede_ser_una_matriz_de_pares() -> None:
    real, pred, _ = _escenario()
    alcance = np.zeros((6, 6), dtype=bool)
    alcance[0, 1] = alcance[1, 0] = alcance[3, 4] = alcance[4, 3] = alcance[4, 5] = alcance[5, 4] = True
    r = iv.pares_cluster_bootstrap(real, pred, alcance, CRITERIO)
    assert (r["ia"]["tp"], r["ia"]["fp"], r["ia"]["fn"]) == (2, 1, 0)
    assert (r["baseline"]["tp"], r["baseline"]["fp"], r["baseline"]["fn"]) == (1, 0, 1)


def test_la_consola_usa_el_mismo_numero_de_remuestreos_que_el_documento() -> None:
    import json

    informe = json.loads((iv.RAIZ / "outputs" / "ia_vs_baseline.json").read_text(encoding="utf-8"))
    ic = informe["clasificacion"]["vista_clasificador"]["con_criterio_de_benchmark"]["diferencia_macro_f1"]["ic95"]
    assert str(ic) in iv.resumen(informe)[0]
