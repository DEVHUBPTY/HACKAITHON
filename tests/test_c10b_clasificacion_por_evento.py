"""C-10b: clasificación evaluada por evento (sin red ni modelo: solo lógica, datos sintéticos y la configuración)."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from eval import clasificacion_por_evento as pe
from eval import origen_etiquetas as oe
from src.baseline import SIN_TEMA
from src.configuracion import CriterioAB, EvaluacionPorEvento, SupervisadoClasificacion, cargar_clasificacion, cargar_temas

CRITERIO = CriterioAB(remuestreos=300, confianza=0.95, semilla=7)
Z = 1.96
CLASES = ["economia", "turismo", SIN_TEMA]


# ------------------------------------------------------------------ configuración (sin números mágicos)


def test_la_configuracion_real_trae_las_secciones_de_c10b() -> None:
    cfg = cargar_clasificacion()
    assert cfg.por_evento.eventos_dominantes >= 1 and cfg.por_evento.min_eventos_ic >= 2
    s = cfg.supervisado
    assert s.pliegues >= 2 and s.repeticiones >= 1 and s.C > 0 and s.min_eventos_por_clase >= 2
    assert s.class_weight == "balanced" and s.sin_tema in ("clase", "excluir")


@pytest.mark.parametrize(
    "cambio",
    [{"pliegues": 1}, {"repeticiones": 0}, {"C": 0.0}, {"C": -1.0}, {"max_iter": 0}, {"min_eventos_por_clase": 1}, {"class_weight": "ninguno"}, {"sin_tema": "otra"}],
)
def test_el_modelo_supervisado_rechaza_valores_invalidos(cambio: dict) -> None:
    base = cargar_clasificacion().supervisado.model_dump()
    with pytest.raises(ValidationError):
        SupervisadoClasificacion.model_validate({**base, **cambio})


def test_el_modelo_supervisado_y_por_evento_prohiben_claves_desconocidas() -> None:
    with pytest.raises(ValidationError):
        SupervisadoClasificacion.model_validate({**cargar_clasificacion().supervisado.model_dump(), "extra": 1})
    with pytest.raises(ValidationError):
        EvaluacionPorEvento.model_validate({"eventos_dominantes": 0, "min_eventos_ic": 2})
    with pytest.raises(ValidationError):
        EvaluacionPorEvento.model_validate({"eventos_dominantes": 3, "min_eventos_ic": 1})


# ------------------------------------------------------------------ lectura: solo etiquetas humanas, sin ejemplos excluidos


def _csv(ruta: Path) -> Path:
    ruta.write_text(
        "id_noticia,tema_principal,ruido,grupo,origen,etiquetado_por\n"
        "NOT-H1,Economía,ninguno,ev-a,humano,Persona\n"
        "NOT-H2,Economía,ninguno,ev-a,humano,Persona\n"
        "NOT-H3,Turismo,ninguno,,humano,Persona\n"
        "NOT-P1,Economía,ninguno,ev-p,asistente_provisional,asistente provisional\n"
        "NOT-X1,Turismo,ninguno,ev-x,humano,Persona\n",
        encoding="utf-8",
    )
    return ruta


def test_las_filas_provisionales_nunca_se_leen(tmp_path: Path) -> None:
    etiquetas, grupos = pe.leer_etiquetas_y_grupos(_csv(tmp_path / "e.csv"), cargar_temas())
    assert "NOT-P1" not in etiquetas and "NOT-P1" not in grupos
    assert set(etiquetas) == {"NOT-H1", "NOT-H2", "NOT-H3", "NOT-X1"}
    assert grupos["NOT-H1"] == "ev-a" and grupos["NOT-H3"] == ""


def test_el_conjunto_excluye_ejemplos_provisionales_y_agrupa_por_evento(tmp_path: Path) -> None:
    etiquetas, grupos = pe.leer_etiquetas_y_grupos(_csv(tmp_path / "e.csv"), cargar_temas())
    filas = [("NOT-H1", "t1", None), ("NOT-H2", "t2", None), ("NOT-H3", "t3", None), ("NOT-P1", "t4", None), ("NOT-X1", "t5", None), ("NOT-Z", "t6", None)]
    ids, y, eventos = pe.armar_conjunto(filas, etiquetas, grupos, excluidos={"NOT-X1"})
    assert ids == ["NOT-H1", "NOT-H2", "NOT-H3"]                 # sin el provisional, sin el ejemplo excluido, sin el no etiquetado
    assert list(y) == ["economia", "economia", "turismo"]
    assert eventos == ["ev-a", "ev-a", "NOT-H3"]                 # sin grupo, el evento es la propia noticia


def test_el_csv_consolidado_real_no_mezcla_provisionales() -> None:
    etiquetas, _ = pe.leer_etiquetas_y_grupos(oe.ETIQUETAS_CONSOLIDADO, cargar_temas())
    provisionales = {f["id_noticia"].strip() for f in oe.leer_filas(oe.ETIQUETAS_CONSOLIDADO, oe.ASISTENTE_PROVISIONAL)}
    assert provisionales and not provisionales & set(etiquetas)


# ------------------------------------------------------------------ estadística por evento


def test_un_evento_repetido_no_domina_el_macro_f1_por_evento() -> None:
    # 20 filas de un evento economía acertadas; 2 eventos de turismo de 1 fila, ambos fallados
    real = np.array(["economia"] * 20 + ["turismo", "turismo"], dtype=object)
    pred = np.array(["economia"] * 20 + ["economia", "economia"], dtype=object)
    eventos = ["grande"] * 20 + ["t1", "t2"]
    r = pe.macro_f1_por_evento(real, pred[None, :], eventos, CLASES, CRITERIO)
    assert r["eventos"] == 3 and r["valor"] is not None
    assert r == pe.macro_f1_por_evento(real, pred[None, :], eventos, CLASES, CRITERIO)       # reproducible
    assert 0.0 <= r["ic95"][0] <= r["ic95"][1] <= 1.0
    # por evento hay 3 eventos (1 acertado, 2 fallados): el evento de 20 filas pesa lo mismo que los de 1 fila
    por_fila_f1 = pe.macro_f1_por_evento(real, pred[None, :], ["x"] * 20 + ["t1", "t2"], CLASES, CRITERIO)
    assert por_fila_f1["eventos"] == 3


def test_la_diferencia_de_macro_f1_pareada_por_evento_detecta_una_mejora_clara() -> None:
    eventos = [f"e{i}" for i in range(20)]
    real = np.array(["economia"] * 10 + ["turismo"] * 10, dtype=object)
    malo = np.array(["economia"] * 20, dtype=object)
    bueno = real.copy()
    d = pe.diferencia_macro_f1_por_evento(real, malo[None, :], bueno[None, :], eventos, CLASES, CRITERIO)
    assert d["diferencia"] > 0 and d["excluye_cero"] is True and d["a_favor"] is True
    nada = pe.diferencia_macro_f1_por_evento(real, bueno[None, :], bueno[None, :], eventos, CLASES, CRITERIO)
    assert nada["diferencia"] == 0 and nada["excluye_cero"] is False and nada["a_favor"] is False


def test_el_macro_f1_acepta_varias_repeticiones_y_promedia() -> None:
    eventos = [f"e{i}" for i in range(6)]
    real = np.array(["economia"] * 3 + ["turismo"] * 3, dtype=object)
    perfecta, mala = real.copy(), np.array(["economia"] * 6, dtype=object)
    r = pe.macro_f1_por_evento(real, np.stack([perfecta, mala]), eventos, CLASES, CRITERIO)
    uno = pe.macro_f1_por_evento(real, perfecta[None, :], eventos, CLASES, CRITERIO)["valor"]
    otro = pe.macro_f1_por_evento(real, mala[None, :], eventos, CLASES, CRITERIO)["valor"]
    assert r["valor"] == pytest.approx((uno + otro) / 2, abs=1e-3)


def test_se_solapan_dice_la_verdad_sobre_los_intervalos() -> None:
    assert pe.se_solapan([0.1, 0.5], [0.4, 0.9]) is True
    assert pe.se_solapan([0.1, 0.3], [0.4, 0.9]) is False
    assert pe.se_solapan(None, [0.4, 0.9]) is None


# ------------------------------------------------------------------ evaluación de un sistema (cobertura, abstención y recall por tema)


def _caso() -> tuple[np.ndarray, np.ndarray, list[str]]:
    # evento a (3 filas economía): 2 acierta, 1 se abstiene; evento b (1 economía): confunde; evento c (1 turismo): acierta
    real = np.array(["economia", "economia", "economia", "economia", "turismo"], dtype=object)
    pred = np.array(["economia", "economia", SIN_TEMA, "turismo", "turismo"], dtype=object)
    return real, pred, ["a", "a", "a", "b", "c"]


def test_la_cobertura_y_la_exactitud_entre_cubiertas_se_separan() -> None:
    real, pred, eventos = _caso()
    r = pe.evaluar_sistema(real, pred[None, :], eventos, CLASES, CRITERIO, Z, min_eventos_ic=2)
    assert r["exactitud_por_fila"]["n"] == 3 and r["exactitud_por_fila"]["de"] == 5
    assert r["cobertura_por_fila"]["n"] == 4 and r["cobertura_por_fila"]["de"] == 5
    assert r["exactitud_entre_cubiertas_por_fila"]["n"] == 3 and r["exactitud_entre_cubiertas_por_fila"]["de"] == 4
    assert r["exactitud_por_evento"]["eventos"] == 3
    assert r["cobertura_por_evento"]["eventos"] == 3


def test_el_recall_por_tema_se_mide_por_evento_y_sin_ic_si_hay_un_solo_evento() -> None:
    real, pred, eventos = _caso()
    r = pe.evaluar_sistema(real, pred[None, :], eventos, CLASES, CRITERIO, Z, min_eventos_ic=2)
    eco, tur = r["recall_por_tema"]["economia"], r["recall_por_tema"]["turismo"]
    assert (eco["filas"]["n"], eco["filas"]["de"], eco["eventos"]) == (2, 4, 2)
    assert eco["recall_por_evento"] == pytest.approx((2 / 3 + 0) / 2) and eco["ic95"] is not None
    assert (tur["eventos"], tur["recall_por_evento"], tur["ic95"]) == (1, 1.0, None)       # un evento: no es estimable
    assert "SIN_TEMA" not in r["recall_por_tema"] and SIN_TEMA not in r["recall_por_tema"]  # sin soporte, no se inventa


def test_eventos_dominantes_y_concentracion_por_tema() -> None:
    real = np.array(["economia"] * 6 + ["turismo", "economia"], dtype=object)
    eventos = ["grande"] * 6 + ["chico", "otro"]
    acierta = np.array([True] * 6 + [False, False])
    dom = pe.eventos_dominantes(real, eventos, acierta, 1)
    assert dom == [{"evento": "grande", "filas": 6, "porcentaje_filas": 0.75, "tema_humano": "economia", "aciertos": "6/6"}]
    conc = pe.concentracion_por_tema(real, eventos)
    assert conc["economia"] == {"filas": 7, "eventos": 2, "filas_del_evento_mayor": 6, "porcentaje_evento_mayor": round(6 / 7, 4)}
    assert conc["turismo"]["eventos"] == 1


def test_los_puntos_de_la_curva_salen_de_los_umbrales_ya_configurados() -> None:
    cfg = cargar_clasificacion()
    puntos = pe.puntos_de_abstencion(cfg)
    umbrales = {m: u.umbral_sin_tema for m, u in cfg.modelos[cfg.modelo_activo].umbrales.items()}
    assert puntos[0][1] is None                                                     # sin abstención
    assert {u for _, u in puntos[1:]} == set(umbrales.values())                    # ningún valor nuevo
    assert [u for _, u in puntos[1:]] == sorted(umbrales.values())
    activos = [n for n, u in puntos if u == umbrales[cfg.metodo_activo]]
    assert len(activos) == 1 and "activo" in activos[0]
