"""E2-03 · CU-05 («¿Qué señales públicas del entorno logístico debo revisar?») de punta a punta sobre un caso real, sin LLM en vivo.

El caso es ``GRP-da35c3dead`` (spec ``specs/E2-03.md``, sección *Caso elegido*). Sus fixtures son un **congelado** de la base del snapshot
(2026-10-07T00:41Z): la ficha de entrada de la generación (``e2_03_cu05_ficha*.json``) y el borrador que entregó la caché de E1-14
(``e2_03_cu05_boletin.json``, ``e2_03_cu05_paquete_editorial.json``). Así la prueba no depende de ``data/senales.duckdb`` (fuera de git) ni de
la red. Son solo metadatos de noticias (titulares, medio, ID): ni descripciones del RSS ni cuerpos (D-31, D-72).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.t09

from src.cache import CacheLlm
from src.configuracion import cargar_generacion, cargar_restricciones, cargar_salidas
from src.esquemas import BoletinBanca, PaqueteEditorial
from src.generacion import EntradaFicha, generar, generar_paquete
from src.validador import Contexto, contar_palabras, plano, validar_paquete

FIXTURES = Path(__file__).parent / "fixtures"
GRUPO = "GRP-da35c3dead"
ACCION_BANCA = "Incluir en el boletín como observación"
ACCION_EDITORIAL = "Producir borrador"


def leer(nombre: str) -> dict[str, Any]:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def entrada(nombre: str = "e2_03_cu05_ficha.json") -> EntradaFicha:
    return EntradaFicha(**leer(nombre))


def boletin() -> BoletinBanca:
    return BoletinBanca(**leer("e2_03_cu05_boletin.json"))


class SoloCache:
    """Cumple lo mínimo de ``Proveedor`` para leer la caché con la identidad con que se calentó (sin red, sin clave, sin llamadas)."""

    nombre = "deepseek"
    modelo = cargar_generacion().deepseek.modelo

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:  # pragma: no cover - no debe llamarse
        raise AssertionError("la caché no debe llamar al proveedor")


def textos(p: BoletinBanca) -> list[str]:
    return [o.texto for o in (*p.observaciones, *p.hipotesis_impacto)]


# ============================================================================================ el congelado es el caso

def test_el_congelado_es_el_caso_elegido_y_su_accion_genera_el_boletin() -> None:
    e = entrada()
    assert e.modalidad == "banca" and e.accion == ACCION_BANCA and e.tema == "logistica"
    assert cargar_generacion().modalidades["banca"] == "boletin" and ACCION_BANCA in cargar_generacion().acciones.completo
    assert {r.id for r in e.registros if r.id.startswith("NOT-")} == {"NOT-1819a7014e", "NOT-33032542b7", "NOT-fbc3efaa5d"}
    assert boletin().id_caso == GRUPO


def test_el_boletin_sale_de_la_cache_con_la_red_apagada_y_es_el_congelado() -> None:
    """E1-14: ``solo_cache=True`` nunca crea proveedor ni abre red. Si cambia un prompt o el validador, la caché deja de servir y esto avisa."""
    p = generar_paquete(GRUPO, "banca", solo_cache=True, proveedor=SoloCache(), cache=CacheLlm(), entrada=entrada())  # type: ignore[arg-type]
    assert isinstance(p, BoletinBanca) and p.vacios == []
    assert p.model_dump(mode="json") == boletin().model_dump(mode="json")


# ============================================================================================ T09 banca sobre el caso real

def test_t09_banca_1_toda_cita_del_boletin_existe_en_la_ficha_y_su_campo_es_valido() -> None:
    p, e = boletin(), entrada()
    campos = {r.id: set(r.campos) for r in e.registros}
    citas = [(c.id, c.campo) for a in p.afirmaciones for c in a.citas]
    assert citas, "el boletín no cita nada"
    assert all(i in campos and campo in campos[i] for i, campo in citas)
    assert validar_paquete(p, Contexto(e, ("comunes", "banca"))) == []
    assert all(a.citas for a in p.afirmaciones if a.tipo in ("hecho", "declaración"))        # hecho y declaración siempre citan
    por_id = {r.id: r for r in e.registros}
    assert all(c.id in por_id for a in p.afirmaciones for c in a.citas)                       # y nunca citan algo fuera de la ficha


def test_t09_banca_2_observacion_y_hipotesis_de_impacto_no_se_mezclan() -> None:
    p = boletin()
    tipos = {a.id: a.tipo for a in p.afirmaciones}
    assert p.observaciones and p.hipotesis_impacto
    assert {tipos[i] for o in p.observaciones for i in o.afirmaciones} <= {"hecho", "declaración"}
    assert {tipos[i] for o in p.hipotesis_impacto for i in o.afirmaciones} <= {"inferencia", "hipótesis"}
    en_observaciones = {i for o in p.observaciones for i in o.afirmaciones}
    en_hipotesis = {i for o in p.hipotesis_impacto for i in o.afirmaciones}
    assert not en_observaciones & en_hipotesis
    assert sum(contar_palabras(t) for t in textos(p)) <= cargar_salidas().banca.resumen_max_palabras


def _con_palabra(texto: str, lista: list[str]) -> list[str]:
    t = plano(texto)
    return [x for x in lista if re.search(rf"(?<!\w){re.escape(plano(x))}(?!\w)", t)]


def test_t09_banca_3_el_lexico_de_d54_no_aparece_fuera_de_una_declaracion_literal() -> None:
    p, e = boletin(), entrada()
    g = cargar_restricciones().grupos["banca"]
    afirmaciones = {a.id: a for a in p.afirmaciones}
    titulares = {r.id: r.campos.get("titulo_limpio", "") for r in e.registros}
    for o in (*p.observaciones, *p.hipotesis_impacto):
        for lista in ("recomendacion", "certeza", "futuro_asertivo"):
            assert _con_palabra(o.texto, g[lista]) == [], f"{lista}: {o.texto}"
        for palabra in _con_palabra(o.texto, g["perdidas_en_inferencias"]):
            ok = all(afirmaciones[i].tipo == "declaración" and plano(palabra) in plano(" ".join(titulares[c.id] for c in afirmaciones[i].citas)) for i in o.afirmaciones)
            assert ok, f"léxico de D-54 fuera de una declaración literal: {palabra} en {o.texto}"
    # el caso real no trae ninguna de esas palabras: el boletín no las inventa en ningún bloque
    assert all(_con_palabra(t, g["perdidas_en_inferencias"]) == [] for t in textos(p))


def test_t09_banca_4_un_dato_anual_no_se_describe_como_actual() -> None:
    """El caso no cita ningún dato oficial anual (sin ``IND-`` en la ficha): el boletín no puede tener uno, ni usar «actual», «hoy»…"""
    p, e = boletin(), entrada()
    assert not any(r.id.startswith("IND-") for r in e.registros)
    assert not any(c.id.startswith("IND-") for a in p.afirmaciones for c in a.citas)
    assert not any(_con_palabra(t, cargar_generacion().volatiles) for t in textos(p))
    assert not any(_con_palabra(t, cargar_generacion().volatiles) for t in p.evidencia)


def test_t09_banca_5_aviso_leyenda_marca_horizonte_sectores_y_preguntas() -> None:
    p, e = boletin(), entrada()
    r = cargar_restricciones()
    assert p.aviso == r.aviso_banca == "No constituye recomendación financiera ni opinión oficial de la SBP."
    assert p.leyenda_alcance == r.leyendas_alcance.titular_metadatos and not e.uso_descripcion
    assert p.marca == r.marca_borrador
    assert p.horizonte == "inmediato" and e.edad_evidencia_dias is not None and e.edad_evidencia_dias <= 7           # E2-01: hasta 7 días
    assert [s.sector for s in p.sectores] == ["logística", "economía"] and all(s.motivo for s in p.sectores)           # tema → sector (D-11)
    assert len(p.preguntas) == 3 and {q.vacio for q in p.preguntas} <= {v.id for v in e.vacios}
    assert len({q.vacio for q in p.preguntas}) == 3                                                                    # cada una con su vacío
    assert p.evidencia and all(any(c.id in linea for linea in p.evidencia) for a in p.afirmaciones for c in a.citas)    # evidencia copiada de la ficha


def test_t09_banca_6_con_modalidad_editorial_el_mismo_grupo_sigue_produciendo_su_paquete_editorial_sin_cambios() -> None:
    e = entrada("e2_03_cu05_ficha_editorial.json")
    assert e.modalidad == "editorial" and e.accion == ACCION_EDITORIAL
    p = generar_paquete(GRUPO, "editorial", solo_cache=True, proveedor=SoloCache(), cache=CacheLlm(), entrada=e)  # type: ignore[arg-type]
    assert isinstance(p, PaqueteEditorial) and not isinstance(p, BoletinBanca)
    assert p.model_dump(mode="json") == leer("e2_03_cu05_paquete_editorial.json")
    assert validar_paquete(p, Contexto(e, ("comunes", "editorial"))) == []


# ============================================================================================ abstención

def test_abstencion_un_caso_banca_con_evidencia_insuficiente_no_inventa_observaciones() -> None:
    """``GRP-f4a44182b1`` (real, 1 procedencia): acción «Seguimiento prioritario» → D-104: sin boletín. No se llama al LLM y la ficha
    conserva qué falta (los dos vacíos), que es lo que la acción entrega."""
    from tests.generacion_ayuda import proveedor_banca

    e = entrada("e2_03_cu05_ficha_abstencion.json")
    assert e.modalidad == "banca" and e.accion == "Seguimiento prioritario"
    prov = proveedor_banca()
    r = generar(e, prov)
    assert r.tipo == "nada" and r.paquete is None and prov.llamadas == []
    assert "Seguimiento prioritario" in (r.motivo or "")                      # el motivo nombra la acción
    assert len(e.vacios) == 2 and any("procedencia" in v.descripcion for v in e.vacios)              # y la ficha dice qué falta
