"""D-123: aprendizaje activo. Separación evaluación/entrenamiento, filtro humano, huella y cola por incertidumbre."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from eval import aprendizaje_activo as aa
from eval.etiquetar import ordenar_cola
from src.configuracion import RAIZ, cargar_clasificacion, cargar_temas

CAMPOS = ["id_noticia", "titulo", "tema_principal", "ruido", "etiquetado_por", "origen"]


def _csv(ruta: Path, filas: list[dict[str, str]]) -> Path:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in CAMPOS})
    return ruta


def _fila(id_: str, tema: str = "economia", origen: str = "humano", por: str = "Javier Acosta", ruido: str = "ninguno") -> dict[str, str]:
    return {"id_noticia": id_, "titulo": "t", "tema_principal": tema, "ruido": ruido, "etiquetado_por": por, "origen": origen}


@pytest.fixture(scope="module")
def temas():
    return cargar_temas()


def test_la_evaluacion_congelada_nunca_entra_al_pool(tmp_path, temas):
    etiquetas = _csv(tmp_path / "e.csv", [_fila("NOT-a"), _fila("NOT-b", "turismo"), _fila("NOT-c", "regulacion")])
    pool = aa.construir_pool(etiquetas, temas, {"NOT-a", "NOT-b"})
    assert pool.ids == ("NOT-c",)
    assert pool.descartadas == {"en_la_evaluacion": 2}


def test_los_evaluados_de_la_corrida_tampoco_entran(tmp_path, temas):
    etiquetas = _csv(tmp_path / "e.csv", [_fila("NOT-a"), _fila("NOT-c")])
    assert aa.construir_pool(etiquetas, temas, set(), evaluados={"NOT-c"}).ids == ("NOT-a",)


def test_la_verificacion_falla_si_un_id_congelado_se_cuela():
    with pytest.raises(aa.ErrorDeSeparacion):
        aa.verificar_separacion(["NOT-a", "NOT-z"], {"NOT-z"})
    aa.verificar_separacion(["NOT-a"], {"NOT-z"})


def test_con_las_etiquetas_reales_ningun_id_de_la_muestra_original_esta_en_el_pool(temas):
    cfg = cargar_clasificacion().logistica.aprendizaje_activo
    congelados = aa.ids_congelados(RAIZ / cfg.muestra_evaluacion)
    assert len(congelados) == 100
    pool = aa.pool_desde_config(RAIZ / "eval" / "etiquetas.csv", temas, cfg.muestra_evaluacion)
    assert not set(pool.ids) & congelados


def test_solo_entran_etiquetas_humanas_con_tema_y_sin_ruido(tmp_path, temas):
    etiquetas = _csv(
        tmp_path / "e.csv",
        [
            _fila("NOT-humana"),
            _fila("NOT-prov", origen="asistente_provisional", por="Asistente provisional"),
            _fila("NOT-sinfirma", por=""),
            _fila("NOT-firmaia", por="aprobado provisionalmente por el asistente"),
            _fila("NOT-ruido", ruido="no_es_panama"),
            _fila("NOT-sintema", tema=""),
            _fila("NOT-temafalso", tema="inventado"),
        ],
    )
    pool = aa.construir_pool(etiquetas, temas, set())
    assert pool.ids == ("NOT-humana",)
    assert pool.descartadas == {"ruido": 1, "sin_firma_de_persona": 2, "sin_tema_valido": 2}


def test_la_huella_es_determinista_y_no_depende_del_orden():
    a = aa.huella_de([("NOT-1", "economia"), ("NOT-2", "turismo")])
    assert a == aa.huella_de([("NOT-2", "turismo"), ("NOT-1", "economia")])
    assert a != aa.huella_de([("NOT-1", "economia"), ("NOT-2", "regulacion")])
    assert len(a) == 64


def test_el_resumen_del_pool_cuenta_por_clase(tmp_path, temas):
    etiquetas = _csv(tmp_path / "e.csv", [_fila("NOT-1"), _fila("NOT-2"), _fila("NOT-3", "turismo")])
    pool = aa.construir_pool(etiquetas, temas, set())
    r = pool.resumen(99)
    assert r["n_pool"] == 3 and r["por_clase_pool"] == {"economia": 2, "turismo": 1} and r["n_referencias"] == 99
    assert r["huella_pool"] == aa.huella_de(zip(pool.ids, pool.temas, strict=True))
    assert pool.solo({"NOT-1"}).descartadas == {"no_estan_en_la_base": 2}


def test_la_cola_ordena_por_menor_probabilidad_maxima_luego_margen_luego_id():
    p = np.array([
        [0.90, 0.05, 0.05],     # segura
        [0.40, 0.35, 0.25],     # la más incierta, margen 0.05
        [0.40, 0.30, 0.30],     # misma máxima, margen 0.10
        [0.40, 0.30, 0.30],     # empate total con el anterior: decide el id
    ])
    ids = ["NOT-d", "NOT-c", "NOT-b", "NOT-a"]
    orden = aa.orden_de_incertidumbre(ids, p)
    assert [i for i, _, _ in orden] == ["NOT-c", "NOT-a", "NOT-b", "NOT-d"]
    assert orden[0][1] == pytest.approx(0.40) and orden[0][2] == pytest.approx(0.05)


def test_la_cola_es_determinista_ante_cualquier_orden_de_entrada():
    rng = np.random.default_rng(0)
    p = rng.dirichlet(np.ones(6), size=30)
    ids = [f"NOT-{k:02d}" for k in range(30)]
    base = aa.orden_de_incertidumbre(ids, p)
    perm = rng.permutation(30)
    otra = aa.orden_de_incertidumbre([ids[k] for k in perm], p[perm])
    assert base == otra
    maximas = [m for _, m, _ in base]
    assert maximas == sorted(maximas)


def test_ordenar_cola_pone_primero_los_pendientes_mas_inciertos_y_al_final_los_hechos():
    mias = [{"id_noticia": i} for i in ("A", "B", "C", "D", "E")]
    cola = {"B": {"posicion": 2}, "C": {"posicion": 1}, "D": {"posicion": 3}}
    assert [m["id_noticia"] for m in ordenar_cola(mias, {"A"}, cola)] == ["C", "B", "D", "E", "A"]


def test_el_logistico_se_entrena_con_el_pool_y_es_determinista(tmp_path):
    from src import clasificacion, embeddings
    from src.configuracion import METODO_LOGISTICO
    from src.limpieza import Reglas
    from tests.motor_falso import MotorFalso, config_de_prueba, temas_de_prueba

    emb = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)
    cfg = cargar_clasificacion().logistica
    temas_p = temas_de_prueba()
    vectores = emb.codificar(["inflacion sube precios", "fuerte sismo temblor"], "titular")
    pool = (vectores, [next(iter(temas_p.temas)), list(temas_p.temas)[-1]])
    reglas = Reglas.desde_config()
    sin = clasificacion.construir_referencias(emb, temas_p, reglas, cfg)
    con1 = clasificacion.construir_referencias(emb, temas_p, reglas, cfg, pool)
    con2 = clasificacion.construir_referencias(emb, temas_p, reglas, cfg, pool)
    p = lambda r: clasificacion.puntuar(vectores, r, METODO_LOGISTICO).similitud  # noqa: E731
    assert np.array_equal(p(con1), p(con2))
    assert not np.array_equal(p(sin), p(con1))
