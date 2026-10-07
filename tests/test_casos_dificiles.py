"""E1-07: los casos difíciles de ``docs/guia_temas.md`` como prueba del clasificador real (modelo local, sin red).

Los fallos **no se ocultan**: cada caso que el clasificador activo (``config/clasificacion.yaml``: modelo y método)
no resuelve está declarado abajo como limitación conocida con ``xfail(strict=True)``, y la misma lista está en
``docs/clasificacion.md``. Si un cambio de configuración arregla uno (o rompe otro), esta prueba falla y obliga a
actualizar la lista y el documento: ni una mejora ni un empeoramiento pasan en silencio.
"""

from pathlib import Path

import pytest

from eval import clasificacion as evalclas
from src import limpieza
from src.baseline import SIN_TEMA
from src.configuracion import cargar_clasificacion, cargar_temas
from src.embeddings import crear
from src.limpieza import Reglas

RAIZ = Path(__file__).resolve().parent.parent
CFG = cargar_clasificacion()
TEMAS = cargar_temas()
CASOS = evalclas.leer_casos_dificiles()

# Limitaciones conocidas con el modelo y método activos (e5 · A), medidas el 2026-10-06 y actualizadas en E1-07c (D-111: CD-12 se resolvió
# y CD-04 pasó de Servicios públicos a Economía al nombrar las obras públicas en la descripción de Servicios públicos). Ver docs/clasificacion.md.
LIMITACIONES_PRINCIPAL = {
    "CD-02": "regla 4 (falla de un servicio): se predice Eventos naturales en lugar de Servicios públicos",
    "CD-04": "regla 2 (norma nueva): se predice Economía en lugar de Regulación (E1-07c: antes Servicios públicos)",
    "CD-08": "regla 6 (carga aérea): se predice Turismo en lugar de Logística/Canal",
    "CD-15": "fuera de temas: la similitud máxima (0.844) supera el umbral de 'sin tema' de e5; "
    "en el pipeline lo descarta antes el filtro de ruido (test_el_futbol_se_descarta_antes_...)",
}
LIMITACIONES_SECUNDARIO = {
    "CD-02": "el principal ya está mal: el 2.º mejor es Servicios públicos, no Eventos naturales",
    "CD-14": "el segundo mejor es Logística/Canal, no Economía",
}


@pytest.fixture(scope="module")
def predicciones():
    try:
        emb = crear(CFG)
        return evalclas.predecir([c.titular for c in CASOS], CFG, TEMAS, CFG.modelo_activo, emb, Reglas.desde_config())
    except (OSError, RuntimeError) as exc:  # modelo no descargado y sin internet: no se puede medir aquí
        pytest.skip(f"modelo {CFG.modelo_activo} no disponible: {exc}")


def _marcar(caso_id: str, limitaciones: dict[str, str]):
    return pytest.mark.xfail(strict=True, reason=limitaciones[caso_id]) if caso_id in limitaciones else ()


def test_hay_quince_casos_y_ninguno_es_referencia_del_clasificador() -> None:
    assert len(CASOS) == 15
    assert evalclas.casos_en_referencias(CASOS, TEMAS, Reglas.desde_config()) == []


@pytest.mark.parametrize("caso", [pytest.param(c, id=c.id, marks=_marcar(c.id, LIMITACIONES_PRINCIPAL)) for c in CASOS])
def test_tema_principal_de_cada_caso_dificil(caso, predicciones) -> None:
    indice = CASOS.index(caso)
    pred = predicciones[CFG.metodo_activo][indice]
    assert pred.principal == caso.principal, f"{caso.titular!r} (regla {caso.regla}): {pred.principal} != {caso.principal}"


@pytest.mark.parametrize(
    "caso",
    [pytest.param(c, id=c.id, marks=_marcar(c.id, LIMITACIONES_SECUNDARIO)) for c in CASOS if c.secundario],
)
def test_el_tema_secundario_esperado_es_el_segundo_mejor(caso, predicciones) -> None:
    pred = predicciones[CFG.metodo_activo][CASOS.index(caso)]
    assert pred.segundo_mejor == caso.secundario, f"{caso.titular!r}: 2.º mejor {pred.segundo_mejor} != {caso.secundario}"


def test_las_limitaciones_estan_documentadas() -> None:
    """Cada limitación de este archivo aparece, con su ID, en docs/clasificacion.md (no se ocultan)."""
    doc = (RAIZ / "docs" / "clasificacion.md").read_text(encoding="utf-8")
    for caso_id in {*LIMITACIONES_PRINCIPAL, *LIMITACIONES_SECUNDARIO}:
        assert caso_id in doc, f"{caso_id} no está en docs/clasificacion.md"
    assert "limitaciones conocidas" in doc.lower()


def test_el_conteo_de_aciertos_coincide_con_la_lista_de_limitaciones(predicciones) -> None:
    aciertos = sum(1 for c, p in zip(CASOS, predicciones[CFG.metodo_activo], strict=True) if p.principal == c.principal)
    assert aciertos == len(CASOS) - len(LIMITACIONES_PRINCIPAL)


def test_el_baseline_y_el_modelo_se_comparan_sobre_los_mismos_casos_y_categorias(predicciones) -> None:
    permitidos = {*TEMAS.temas, SIN_TEMA}
    for clave in ("baseline", "A", "B"):
        assert len(predicciones[clave]) == 15
        assert {p.principal for p in predicciones[clave]} <= permitidos


def test_los_casos_dificiles_dan_lo_mismo_dos_veces(predicciones) -> None:
    otra = evalclas.predecir([c.titular for c in CASOS], CFG, TEMAS, CFG.modelo_activo, crear(CFG, usar_cache=False), Reglas.desde_config())
    assert [p.principal for p in otra[CFG.metodo_activo]] == [p.principal for p in predicciones[CFG.metodo_activo]]
    assert [p.principal for p in otra["baseline"]] == [p.principal for p in predicciones["baseline"]]


def test_el_futbol_se_descarta_antes_por_el_filtro_de_ruido() -> None:
    """CD-15 es 'fuera_de_temas': el filtro de palabras clave (E1-03b) lo marca ruido y nunca llega al clasificador."""
    caso = next(c for c in CASOS if c.principal == SIN_TEMA)
    fila = {
        "titulo": caso.titular, "medio": "TVN", "dominio": "tvn-2.com", "url": "https://www.tvn-2.com/nacionales/x_1_1.html",
        "origen": "TVN RSS", "categoria_fuente": None, "pais_medio": "Panamá",
    }
    r = limpieza.evaluar(fila, Reglas.desde_config())
    assert (r.es_ruido, r.motivo_ruido) == (True, "fuera_de_temas")


# Tema secundario GUARDADO (el que sale de `decidir` con el margen provisional de e5 · A), por caso. Solo 3 de los 15 casos
# lo reciben y solo 2 de los 7 que lo esperan coinciden (CD-04, CD-05); CD-12 recibe uno que no se espera. El margen es un supuesto: ver docs/clasificacion.md.
SECUNDARIO_GUARDADO = {"CD-04": "servicios_publicos", "CD-05": "economia", "CD-12": "eventos_naturales"}   # CD-12: secundario no esperado (E1-07c)


@pytest.mark.parametrize("caso", [pytest.param(c, id=c.id) for c in CASOS])
def test_el_tema_secundario_guardado_de_cada_caso_esta_fijado(caso, predicciones) -> None:
    pred = predicciones[CFG.metodo_activo][CASOS.index(caso)]
    assert pred.secundario == SECUNDARIO_GUARDADO.get(caso.id), f"{caso.id}: {pred.secundario}"


def test_el_secundario_esperado_se_acierta_en_2_de_7_con_el_margen_provisional(predicciones) -> None:
    esperados = [(c, p) for c, p in zip(CASOS, predicciones[CFG.metodo_activo], strict=True) if c.secundario]
    assert len(esperados) == 7
    assert sum(1 for c, p in esperados if p.secundario == c.secundario) == 2
