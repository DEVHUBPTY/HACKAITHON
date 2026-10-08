"""D-122: un subtema nombrado corrige el tema del grupo (determinista, sin embeddings)."""

from __future__ import annotations

import pytest

from src import db
from src.agrupacion import Grupo, _filas_de_grupos
from src.configuracion import CorreccionTema, cargar_temas, cargar_vinculos
from src.contexto import tema_por_subtema_nombrado

CFG = cargar_vinculos().subtema
CATALOGO = {t: list(d.subtemas) for t, d in cargar_temas().temas.items()}


def corregir(titulares: list[str], tema: str | None, cfg=CFG) -> str | None:
    return tema_por_subtema_nombrado(titulares, tema, CATALOGO, cfg)


def test_un_unico_tema_distinto_corrige() -> None:
    titular = "Comisión de Presupuesto tramita traslados y créditos por casi $100 millones entre seis instituciones"
    assert corregir([titular], "regulacion") == "economia"


def test_otro_caso_real_de_lista_internacional() -> None:
    assert corregir(["Panamá apunta a salir de la lista fiscal de la Unión Europea, pero aún enfrenta una revisión"], "economia") == "regulacion"


def test_el_tema_ya_correcto_no_cambia() -> None:
    assert corregir(["Comisión de Presupuesto tramita traslados y créditos"], "economia") is None


def test_dos_temas_nombrados_no_cambian_nada() -> None:
    titular = "Ejecutivo sanciona la Ley 552 del Presupuesto del Canal"   # finanzas_publicas (economía) + leyes_decretos (regulación)
    assert corregir([titular], "logistica") is None


def test_dos_titulares_con_temas_distintos_no_cambian_nada() -> None:
    assert corregir(["Comisión de Presupuesto tramita traslados", "Panamá apunta a salir de la lista fiscal de la Unión Europea"], "logistica") is None


def test_sin_subtema_nombrado_no_cambia() -> None:
    assert corregir(["Festival Navideño City of Stars 2026 llega a la ciudad"], "turismo") is None


def test_una_exclusion_impide_la_correccion() -> None:
    subtema, marcadores = next((s, m) for s, m in CFG.exclusiones_por_subtema.items() if m and CFG.terminos_por_subtema.get(s))
    tema = next(t for t, subs in CATALOGO.items() if subtema in subs)
    otro = next(t for t in CATALOGO if t != tema)
    termino = CFG.terminos_por_subtema[subtema][0]
    solo = CFG.model_copy(
        update={"terminos_por_subtema": {subtema: [termino]}, "patrones_por_subtema": {}, "exclusiones_por_subtema": {subtema: [marcadores[0]]}}
    )
    assert corregir([f"{termino} en el país"], otro, solo) == tema
    assert corregir([f"{termino} en el país {marcadores[0]}"], otro, solo) is None


def test_presupuesto_del_canal_sigue_en_logistica() -> None:
    assert corregir(["Ejecutivo sanciona la Ley 552 del Presupuesto del Canal de Panamá"], "logistica") is None


def test_sin_tema_depende_del_interruptor() -> None:
    titular = "Comisión de Presupuesto tramita traslados y créditos"
    assert corregir([titular], "sin_tema") == "economia"
    assert corregir([titular], None) == "economia"
    apagado = CFG.model_copy(update={"correccion_tema": CorreccionTema(activa=True, corregir_sin_tema=False, criterio="subtema_nombrado")})
    assert corregir([titular], "sin_tema", apagado) is None
    assert corregir([titular], "regulacion", apagado) == "economia"


def test_interruptor_general_apagado() -> None:
    apagado = CFG.model_copy(update={"correccion_tema": CorreccionTema(activa=False, corregir_sin_tema=True, criterio="subtema_nombrado")})
    assert corregir(["Comisión de Presupuesto tramita traslados y créditos"], "regulacion", apagado) is None


def test_el_yaml_activa_la_correccion_con_su_criterio() -> None:
    assert CFG.correccion_tema.activa and CFG.correccion_tema.criterio == "subtema_nombrado"


def test_las_filas_de_grupos_siguen_el_esquema_y_guardan_el_tema_de_origen() -> None:
    g = Grupo("GRP-x", ("NOT-1",), "NOT-1", "t", 1, (), None, None, None, None, (), "economia", "regulacion", "subtema_nombrado")
    fila = _filas_de_grupos([g], estimado=True)[0][0]
    cols = db.columnas("grupos")
    assert len(fila) == len(cols)
    assert fila[cols.index("tema_origen_clasificador")] == "regulacion" and fila[cols.index("criterio_tema")] == "subtema_nombrado"


@pytest.mark.parametrize("campo", ["activa", "corregir_sin_tema"])
def test_la_configuracion_prohibe_claves_desconocidas(campo: str) -> None:
    with pytest.raises(ValueError):
        CorreccionTema(activa=True, corregir_sin_tema=True, criterio="x", **{campo + "_extra": 1})
