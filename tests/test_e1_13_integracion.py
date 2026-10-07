"""E1-13 · Integración (revisión del PR #29): compuerta final del paquete, leyenda en la consulta, tasas por tipo de unidad y caché ordenada."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import calentar_cache
from src import consulta
from src.cache import CacheLlm
from src.configuracion import cargar_consulta, cargar_restricciones
from src.esquemas import Oracion, Vacio
from src.generacion import Generador
from src.validador import RegistroRechazos, Rechazo, calcular_tasas
from tests.generacion_ayuda import ProveedorGuionado, ficha

# ============================================================================================ M3 · compuerta y leyenda


def generador_listo() -> Generador:
    g = Generador(ficha(), ProveedorGuionado())
    g.generar_todo()
    return g


def test_el_paquete_pasa_por_la_compuerta_final_y_lo_invalido_no_sale() -> None:
    g = generador_listo()
    assert g.paquete().brief  # type: ignore[union-attr]
    g._secciones["brief"] = [Oracion(texto="La inflación llegará a 15 % en 2027.", afirmaciones=["A3"])]  # una sección que se coló sin validar
    p = g.paquete()
    assert p.brief == [] and any(v.referencia == "brief" and "cifra" in v.motivo for v in p.vacios)  # type: ignore[union-attr]
    assert p.guion and p.titulares  # type: ignore[union-attr]  # lo demás sigue


def test_validar_leyenda_texto_acepta_la_correcta_y_rechaza_la_otra() -> None:
    from src.validador import validar_leyenda_texto

    r = cargar_restricciones()
    assert validar_leyenda_texto(r.leyendas_alcance.titular_metadatos, False) == []
    assert validar_leyenda_texto(r.leyendas_alcance.con_descripcion, True) == []
    assert validar_leyenda_texto(r.leyendas_alcance.con_descripcion, False)
    assert validar_leyenda_texto("sin leyenda", False)


def test_el_consultor_exige_una_leyenda_valida() -> None:
    mala = cargar_restricciones()
    mala = mala.model_copy(update={"leyendas_alcance": mala.leyendas_alcance.model_copy(update={"titular_metadatos": "texto cualquiera"})})
    with pytest.raises(ValueError, match="leyenda"):
        consulta.Consultor(None, cargar_consulta(), mala)  # type: ignore[arg-type]


def test_el_docstring_de_consulta_ya_no_dice_que_el_validador_esta_pendiente() -> None:
    assert "el validador completo" not in " ".join((consulta.__doc__ or "").split())


# ============================================================================================ L2 · tasas por tipo de unidad


def test_la_tasa_por_regla_usa_el_denominador_de_su_tipo_de_unidad(tmp_path: Path) -> None:
    ruta = tmp_path / "r.jsonl"
    r = RegistroRechazos(ruta, proveedor="p", modelo="m", id_caso="X")
    for i in range(4):
        r.evaluacion("afirmacion", "afirmaciones", f"A{i}", [])
    r.evaluacion("seccion", "enfoque", "enfoque", [Rechazo("enfoque_como_hecho", "m")])
    r.evaluacion("seccion", "enfoque", "enfoque", [])
    r.evaluacion("seccion", "brief", "brief", [])
    t = calcular_tasas(ruta)
    x = t["por_regla"]["enfoque_como_hecho"]["p/m"]["seccion:enfoque"]
    assert (x["k"], x["n"]) == (1, 2) and x["tasa"] == 0.5
    assert t["por_unidad"]["p/m"]["afirmacion"]["n"] == 4 and t["por_unidad"]["p/m"]["seccion:brief"]["n"] == 1


# ============================================================================================ L1 y caché ordenada


def test_un_grupo_con_una_seccion_vacia_por_validacion_no_se_dice_completo(monkeypatch: pytest.MonkeyPatch) -> None:
    g = generador_listo()
    p = g.paquete()
    assert calentar_cache.estado_de.__doc__ and "con vacíos" in calentar_cache.estado_de.__doc__
    p2 = p.model_copy(update={"enfoque": [], "vacios": [Vacio(origen="seccion", referencia="enfoque", motivo="el enfoque se apoya en una inferencia")]})
    monkeypatch.setattr("src.generacion.generar_paquete", lambda *a, **k: p2)
    estado = calentar_cache.estado_de("GRP-x", "editorial", Path("x"), CacheLlm(Path("nada")))
    assert estado.startswith("con vacíos") and "enfoque" in estado
    monkeypatch.setattr("src.generacion.generar_paquete", lambda *a, **k: p)
    assert calentar_cache.estado_de("GRP-x", "editorial", Path("x"), CacheLlm(Path("nada"))) == "completo"


def test_la_cache_registra_lo_usado_y_poda_lo_demas(tmp_path: Path) -> None:
    c = CacheLlm(tmp_path)
    meta: dict[str, Any] = {"proveedor": "p", "modelo": "m", "version_prompt": "1", "version_cache": 1}
    c.guardar("a" * 64, json.dumps({"x": 1}), meta)
    c.guardar("b" * 64, json.dumps({"x": 2}), meta)
    assert c.obtener("a" * 64) and "a" * 64 in c.usadas and "b" * 64 not in c.usadas
    assert c.podar() == 1 and len(c) == 1 and c.obtener("a" * 64) and c.obtener("b" * 64) is None


# ============================================================================================ rendimiento: reintento si no sobrevive ninguna inferencia


def _sin_inferencia_valida() -> dict[str, Any]:
    from tests.generacion_ayuda import BUENAS, modificada

    return modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"][3].update(texto="El plan interesa a la población porque sube los precios"))


def test_si_ninguna_inferencia_sobrevive_el_paso_1_se_reintenta_con_el_motivo() -> None:
    from src.generacion import generar
    from tests.generacion_ayuda import BUENAS

    prov = ProveedorGuionado(afirmaciones=(_sin_inferencia_valida(), BUENAS["afirmaciones"]))
    p = generar(ficha(), prov).paquete
    assert prov.claves.count("afirmaciones") == 2 and "causalidad" in prov.llamadas[1][2]  # el aviso del reintento dice qué falló
    assert any(a.tipo == "inferencia" for a in p.afirmaciones) and p.enfoque  # type: ignore[union-attr]


def test_si_el_reintento_tampoco_trae_inferencia_se_conservan_las_afirmaciones_validas() -> None:
    from src.generacion import generar

    prov = ProveedorGuionado(afirmaciones=_sin_inferencia_valida())
    p = generar(ficha(), prov).paquete
    assert prov.claves.count("afirmaciones") == 2 and p.afirmaciones and p.brief  # type: ignore[union-attr]
    assert not any(v.referencia == "afirmaciones" for v in p.vacios)  # type: ignore[union-attr]
