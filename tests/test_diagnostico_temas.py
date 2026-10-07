"""E1-07b: diagnóstico de los errores de tema con etiquetas humanas (sin red, sin modelo salvo donde se indica)."""

from pathlib import Path

import numpy as np
import pytest

from eval import diagnostico_temas as dg
from src import limpieza
from src.baseline import SIN_TEMA
from src.configuracion import CriterioAB, cargar_clasificacion, cargar_temas
from src.embeddings import crear
from src.limpieza import Reglas

CRITERIO = CriterioAB(remuestreos=400, confianza=0.95, semilla=7)
RAIZ = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ AUC


def test_auc_mide_la_probabilidad_de_que_un_positivo_supere_a_un_negativo() -> None:
    assert dg.auc_mayor(np.array([3.0, 4.0]), np.array([1.0, 2.0])) == 1.0
    assert dg.auc_mayor(np.array([1.0]), np.array([1.0])) == 0.5       # un empate vale la mitad
    assert dg.auc_mayor(np.array([1.0, 3.0]), np.array([2.0])) == 0.5
    assert dg.auc_mayor(np.array([]), np.array([1.0])) is None         # sin positivos no hay AUC (no se inventa)


def test_auc_ponderado_cuenta_un_evento_una_vez() -> None:
    # un positivo repetido 3 veces (mismo evento) pesa 1/3 cada uno: el resultado es el del evento, no el de las filas
    positivos, pesos_pos = np.array([5.0, 5.0, 5.0, 0.0]), np.array([1 / 3, 1 / 3, 1 / 3, 1.0])
    negativos, pesos_neg = np.array([1.0]), np.array([1.0])
    assert dg.auc_mayor(positivos, negativos) == pytest.approx(0.75)
    assert dg.auc_mayor(positivos, negativos, pesos_pos, pesos_neg) == pytest.approx(0.5)


# ------------------------------------------------------------------ eventos (el n efectivo no es el número de filas)


def test_el_ic_por_evento_no_deja_que_un_evento_repetido_domine() -> None:
    # 20 filas del mismo evento acertadas y 1 fila de otro evento fallada: por fila 95 %, por evento 50 %
    aciertos = np.array([True] * 20 + [False])
    eventos = ["el-nino"] * 20 + ["otro"]
    r = dg.exactitud_por_evento(aciertos, eventos, CRITERIO)
    assert r["eventos"] == 2 and r["valor"] == 0.5
    assert r["ic95"][0] <= r["valor"] <= r["ic95"][1]
    assert r == dg.exactitud_por_evento(aciertos, eventos, CRITERIO)    # reproducible


def test_la_diferencia_por_evento_con_un_solo_evento_cambiado_no_es_significativa() -> None:
    eventos = [f"e{i}" for i in range(8)]
    antes = np.array([True, True, True, True, False, False, False, False])
    despues = antes.copy()
    despues[4] = True                                                    # mejora en 1 de 8 eventos
    r = dg.diferencia_por_evento(antes, despues, eventos, CRITERIO)
    assert r["diferencia"] == pytest.approx(1 / 8)
    assert r["ic95"][0] <= 0 <= r["ic95"][1] and r["excluye_cero"] is False


# ------------------------------------------------------------------ descomposición de errores


def test_los_errores_se_separan_en_abstencion_falsa_omitida_y_confusion() -> None:
    real = ["economia", "economia", SIN_TEMA, SIN_TEMA, "turismo", "turismo"]
    pred = [SIN_TEMA, "regulacion", "regulacion", SIN_TEMA, "turismo", "servicios_publicos"]
    r = dg.descomponer_errores(real, pred)
    assert r == {
        "aciertos": 2,
        "abstencion_falsa": 1,         # tenía tema y el sistema se abstuvo
        "abstencion_omitida": 1,       # no tenía tema y el sistema asignó uno (asignación forzada)
        "confusion_entre_temas": 2,    # tenía tema y el sistema eligió otro
        "total": 6,
    }


# ------------------------------------------------------------------ calibración del umbral con validación cruzada por evento


TEMAS_FALSOS = ["a", "b"]


def _similitudes(n_por_clase: int, separables: bool, semilla: int = 0) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Similitudes con dos temas; los ``sin_tema`` tienen similitud baja si ``separables`` y igual a los demás si no."""
    rng = np.random.default_rng(semilla)
    sims, real, eventos = [], [], []
    for k in range(n_por_clase):
        for tema in TEMAS_FALSOS:
            base = 0.9 if tema == "a" else 0.1
            sims.append([base + rng.normal(0, 0.01), 0.5 + rng.normal(0, 0.01)] if tema == "a" else [0.5 + rng.normal(0, 0.01), 0.9 + rng.normal(0, 0.01)])
            real.append(tema)
            eventos.append(f"{tema}{k}")
        sims.append([0.3 + rng.normal(0, 0.01), 0.3 + rng.normal(0, 0.01)] if separables else [0.9 + rng.normal(0, 0.01), 0.5 + rng.normal(0, 0.01)])
        real.append(SIN_TEMA)
        eventos.append(f"s{k}")
    return np.array(sims), np.array(real), eventos


def test_la_calibracion_cv_encuentra_el_umbral_si_la_senal_existe() -> None:
    sims, real, eventos = _similitudes(10, separables=True)
    r = dg.calibrar_umbral_cv(sims, TEMAS_FALSOS, real, eventos, [*TEMAS_FALSOS, SIN_TEMA], pliegues=5, repeticiones=3, semilla=1)
    assert r["abstenciones_correctas_fuera_de_muestra"] == pytest.approx(1.0)
    assert r["exactitud_fuera_de_muestra"] == pytest.approx(1.0)


def test_la_calibracion_cv_no_inventa_senal_donde_no_la_hay() -> None:
    """Si el ``sin_tema`` no se distingue por similitud, el umbral elegido no abstiene bien fuera de muestra."""
    sims, real, eventos = _similitudes(10, separables=False)
    r = dg.calibrar_umbral_cv(sims, TEMAS_FALSOS, real, eventos, [*TEMAS_FALSOS, SIN_TEMA], pliegues=5, repeticiones=3, semilla=1)
    assert r["abstenciones_correctas_fuera_de_muestra"] < 0.5
    assert r == dg.calibrar_umbral_cv(sims, TEMAS_FALSOS, real, eventos, [*TEMAS_FALSOS, SIN_TEMA], pliegues=5, repeticiones=3, semilla=1)


def test_un_evento_nunca_esta_en_el_entrenamiento_y_en_la_prueba_a_la_vez() -> None:
    eventos = ["x"] * 6 + ["y"] * 6 + ["z"] * 6 + ["w"] * 6
    for entrenamiento, prueba in dg.pliegues_por_evento(eventos, pliegues=2, semilla=3):
        assert not {eventos[i] for i in entrenamiento} & {eventos[i] for i in prueba}
        assert len(entrenamiento) + len(prueba) == len(eventos)


# ------------------------------------------------------------------ el comportamiento que la tarea protege (pipeline real)


def _fila(titulo: str) -> dict:
    return {
        "titulo": titulo, "medio": "TVN", "dominio": "tvn-2.com", "url": "https://www.tvn-2.com/nacionales/x_1_1.html",
        "origen": "TVN RSS", "categoria_fuente": None, "pais_medio": "Panamá",
    }


@pytest.mark.parametrize(
    "titulo",
    [
        "Panamá derrota 2-1 a Costa Rica en un partido amistoso de fútbol",
        "Equipo de béisbol gana el torneo nacional con un jonrón en la final",
        "La selección mayor se prepara para las eliminatorias del Mundial",
    ],
)
def test_un_titular_de_deportes_es_ruido_fuera_de_temas_y_no_se_borra(titulo: str) -> None:
    """Se marca, no se borra: sale de la bandeja con su motivo (CLAUDE.md, «Ruido: marcar, no borrar»)."""
    r = limpieza.evaluar(_fila(titulo), Reglas.desde_config())
    assert (r.es_ruido, r.motivo_ruido) == (True, "fuera_de_temas")


def test_un_titular_claramente_economico_se_conserva_y_se_clasifica_como_economia() -> None:
    titulo = "Inflación de Panamá cierra en 1,5 % mientras el PIB crece 3 % en el trimestre"
    r = limpieza.evaluar(_fila(titulo), Reglas.desde_config())
    assert r.es_ruido is False
    cfg, temas = cargar_clasificacion(), cargar_temas()
    try:
        emb = crear(cfg)
    except (OSError, RuntimeError) as exc:                                # sin modelo local y sin red
        pytest.skip(f"modelo {cfg.modelo_activo} no disponible: {exc}")
    from src.clasificacion import clasificar_textos, construir_referencias

    ref = construir_referencias(emb, temas, Reglas.desde_config())
    umbrales = cfg.modelos[cfg.modelo_activo].umbrales[cfg.metodo_activo]
    [d] = clasificar_textos([r.titulo_limpio], emb, ref, cfg.metodo_activo, umbrales)
    assert d.principal == "economia"


def test_con_objetivo_exactitud_sin_senal_la_calibracion_no_gana_nada_fuera_de_muestra() -> None:
    """Sin señal (sin_tema indistinguible por similitud) la exactitud fuera de muestra no supera a no abstenerse nunca."""
    sims, real, eventos = _similitudes(30, separables=False)
    clases = [*TEMAS_FALSOS, SIN_TEMA]
    sin_abstenerse = float((dg.decidir_con_umbral(sims, TEMAS_FALSOS, -np.inf) == real).mean())      # 2/3: sin_tema siempre falla
    r = dg.calibrar_umbral_cv(sims, TEMAS_FALSOS, real, eventos, clases, pliegues=5, repeticiones=3, semilla=1, objetivo="exactitud")
    assert r["objetivo"] == "exactitud"
    assert r["exactitud_fuera_de_muestra"] <= sin_abstenerse + 0.01


def test_un_objetivo_desconocido_se_rechaza() -> None:
    sims, real, eventos = _similitudes(3, separables=True)
    with pytest.raises(ValueError, match="objetivo"):
        dg.calibrar_umbral_cv(sims, TEMAS_FALSOS, real, eventos, [*TEMAS_FALSOS, SIN_TEMA], 2, 1, 1, objetivo="f2")
