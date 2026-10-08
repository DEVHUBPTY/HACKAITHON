"""D-121: clasificador temático por regresión logística sobre los embeddings (método ``logistica``). Sin red salvo el
test de calibración, que usa el e5 local (se omite si el modelo no está descargado)."""

from pathlib import Path

import numpy as np
import pytest

from src import clasificacion, clasificacion_logistica, embeddings
from src.baseline import SIN_TEMA
from src.configuracion import (
    METODO_LOGISTICO,
    ConfigClasificacion,
    ErrorDeConfiguracion,
    UmbralesMetodo,
    cargar_clasificacion,
    cargar_config,
    cargar_temas,
)
from src.limpieza import Reglas
from tests.motor_falso import MotorFalso, config_de_prueba, temas_de_prueba

RAIZ = Path(__file__).resolve().parent.parent
REGLAS = Reglas.desde_config()
TITULARES = ["inflacion sube precios", "aprueban ley decreto", "fuerte sismo temblor", "sin agua barrios", "texto sin ninguna palabra conocida"]


@pytest.fixture
def emb(tmp_path):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)


@pytest.fixture
def ref(emb):
    return clasificacion.construir_referencias(emb, temas_de_prueba(), REGLAS, cargar_clasificacion().logistica)


def _copiar_config(tmp_path, reemplazos: dict[str, str]) -> Path:
    carpeta = tmp_path / "config"
    carpeta.mkdir(parents=True)
    texto = (RAIZ / "config" / "clasificacion.yaml").read_text(encoding="utf-8")
    for viejo, nuevo in reemplazos.items():
        assert viejo in texto
        texto = texto.replace(viejo, nuevo)
    (carpeta / "clasificacion.yaml").write_text(texto, encoding="utf-8")
    return carpeta


def test_la_misma_entrada_da_la_misma_salida(emb, tmp_path) -> None:
    cfg = cargar_clasificacion()
    umbrales = clasificacion.umbrales_de(cfg, cfg.modelo_activo, METODO_LOGISTICO)
    corridas = []
    for _ in range(2):
        ref = clasificacion.construir_referencias(emb, temas_de_prueba(), REGLAS, cfg.logistica)
        d = clasificacion.clasificar_textos(TITULARES, emb, ref, METODO_LOGISTICO, umbrales)
        corridas.append([(x.principal, x.similitud, tuple(x.similitudes.values())) for x in d])
    assert corridas[0] == corridas[1]


def test_las_probabilidades_suman_uno_y_siguen_el_orden_de_temas(emb, ref) -> None:
    p = clasificacion.puntuar(emb.codificar(TITULARES, "titular"), ref, METODO_LOGISTICO).similitud
    assert p.shape == (len(TITULARES), len(ref.temas))
    assert np.allclose(p.sum(axis=1), 1.0)
    assert ref.temas[int(p[0].argmax())] == "economia" and ref.temas[int(p[2].argmax())] == "eventos_naturales"


def test_bajo_el_umbral_la_logistica_se_abstiene(emb, ref) -> None:
    cfg = cargar_clasificacion()
    umbrales = clasificacion.umbrales_de(cfg, cfg.modelo_activo, METODO_LOGISTICO)
    assert umbrales.umbral_sin_tema == cfg.logistica.umbral_sin_tema           # el umbral de la logística es el suyo, no el del coseno
    temas = ref.temas
    justo_debajo = np.full(len(temas), (1 - (umbrales.umbral_sin_tema - 0.01)) / (len(temas) - 1))
    justo_debajo[0] = umbrales.umbral_sin_tema - 0.01
    d = clasificacion.decidir(justo_debajo, [None] * len(temas), temas, umbrales)
    assert d.principal == SIN_TEMA and d.similitud < umbrales.umbral_sin_tema
    justo_encima = np.full(len(temas), (1 - (umbrales.umbral_sin_tema + 0.01)) / (len(temas) - 1))
    justo_encima[0] = umbrales.umbral_sin_tema + 0.01
    assert clasificacion.decidir(justo_encima, [None] * len(temas), temas, umbrales).principal == temas[0]
    # de punta a punta: un umbral inalcanzable hace que todo el lote se abstenga
    todos = clasificacion.clasificar_textos(
        TITULARES, emb, ref, METODO_LOGISTICO, UmbralesMetodo(umbral_sin_tema=1.0, margen_secundario=0.0)
    )
    assert all(x.principal == SIN_TEMA or x.similitud >= 1.0 for x in todos)


def test_sin_modelo_ajustado_la_logistica_falla_claro(emb) -> None:
    ref = clasificacion.construir_referencias(emb, temas_de_prueba(), REGLAS)       # sin `logistica`
    with pytest.raises(ValueError, match="logistica"):
        clasificacion.puntuar(emb.codificar(TITULARES, "titular"), ref, METODO_LOGISTICO)


def test_la_configuracion_rechaza_claves_desconocidas_en_logistica(tmp_path) -> None:
    carpeta = _copiar_config(tmp_path, {"  max_iter: 1000\n": "  max_iter: 1000\n  clave_inventada: 1\n"})
    with pytest.raises(ErrorDeConfiguracion, match="clave_inventada"):
        cargar_config("clasificacion", ConfigClasificacion, carpeta)


@pytest.mark.parametrize(
    ("reemplazos", "mensaje"),
    [
        ({"remuestreos: 5000": "remuestreos: 1000\n    extra: 1"}, "extra"),
        ({"remuestreos: 5000": "remuestreos: 1500"}, "remuestreos"),         # el bootstrap pareado exige >= 2000
        ({"regularizacion_c: 1000.0 ": "regularizacion_c: 7.0 "}, "rejilla_c"),  # C fuera de la rejilla
        ({"umbral_sin_tema: 0.472": "umbral_sin_tema: 1.5"}, "umbral_sin_tema"),
    ],
)
def test_la_configuracion_logistica_invalida_se_rechaza(tmp_path, reemplazos, mensaje) -> None:
    carpeta = _copiar_config(tmp_path, reemplazos)
    with pytest.raises(ErrorDeConfiguracion, match=mensaje):
        cargar_config("clasificacion", ConfigClasificacion, carpeta)


def test_el_metodo_se_elige_por_configuracion(tmp_path) -> None:
    carpeta = _copiar_config(tmp_path, {"metodo_activo: A": f"metodo_activo: {METODO_LOGISTICO}"})
    assert cargar_config("clasificacion", ConfigClasificacion, carpeta).metodo_activo == METODO_LOGISTICO
    assert cargar_clasificacion().metodo_activo in {"A", "B", METODO_LOGISTICO}
    carpeta_mala = _copiar_config(tmp_path / "otra", {"metodo_activo: A": "metodo_activo: C"})
    with pytest.raises(ErrorDeConfiguracion, match="metodo_activo"):
        cargar_config("clasificacion", ConfigClasificacion, carpeta_mala)


def test_el_metodo_a_sigue_disponible_y_sin_cambios(emb) -> None:
    ref = clasificacion.construir_referencias(emb, temas_de_prueba(), REGLAS)
    cfg = config_de_prueba()
    umbrales = clasificacion.umbrales_de(cfg, cfg.modelo_activo, "A")
    assert umbrales == cfg.modelos[cfg.modelo_activo].umbrales["A"]
    [d] = clasificacion.clasificar_textos(["inflacion sube precios"], emb, ref, "A", umbrales)
    assert d.principal == "economia"


def test_la_calibracion_es_determinista_y_solo_usa_referencias(emb) -> None:
    cfg = cargar_clasificacion().logistica.model_copy(update={"pliegues": 5})
    X, y = clasificacion.datos_de_entrenamiento(emb, temas_de_prueba(), REGLAS)
    a = clasificacion_logistica.calibrar(X, y, cfg)
    b = clasificacion_logistica.calibrar(X, y, cfg)
    assert a == b and a.n_textos == len(y) == sum(a.textos_por_tema.values())
    assert a.regularizacion_c in cfg.rejilla_c and 0.0 <= a.umbral_sin_tema <= 1.0


def test_el_yaml_guarda_el_resultado_de_la_calibracion_con_e5() -> None:
    """El C, el umbral y el margen de config/clasificacion.yaml son los que produce la validación cruzada (no a mano)."""
    cfg, temas = cargar_clasificacion(), cargar_temas()
    try:
        X, y = clasificacion.datos_de_entrenamiento(embeddings.crear(cfg), temas)
    except (OSError, RuntimeError) as exc:
        pytest.skip(f"modelo {cfg.modelo_activo} no disponible: {exc}")
    c = clasificacion_logistica.calibrar(X, y, cfg.logistica)
    assert c.regularizacion_c == cfg.logistica.regularizacion_c
    assert c.umbral_sin_tema == pytest.approx(cfg.logistica.umbral_sin_tema, abs=1e-9)
    assert c.margen_secundario == pytest.approx(cfg.logistica.margen_secundario, abs=1e-9)
