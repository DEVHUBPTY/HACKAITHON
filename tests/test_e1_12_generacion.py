"""E1-12 · Generación del paquete editorial en dos pasos (D-41 a D-45, D-51). Nunca se llama a un LLM real."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from pydantic import ValidationError

from src.configuracion import cargar_generacion, cargar_restricciones, cargar_salidas
from src.esquemas import BoletinBanca, PaqueteEditorial, PaqueteInvestigacion
from src.generacion import Generador, RegistroEvidencia, generar
from tests.generacion_ayuda import (
    BUENAS,
    ID_IND,
    ID_PRENSA,
    ID_REUTERS,
    ID_TVN,
    MARCADOR,
    TITULAR_REUTERS,
    ProveedorGuionado,
    contradiccion_abierta,
    ficha,
    modificada,
    registro_prensa,
)

SALIDAS = cargar_salidas().editorial
RESTR = cargar_restricciones()


def palabras(texto: str) -> int:
    return len(re.findall(r"\S+", texto.replace(MARCADOR, "")))


def sin_vacio(p: Any, seccion: str) -> bool:
    return not any(v.origen == "seccion" and v.referencia == seccion for v in p.vacios)


# ------------------------------------------------------------------ qué se genera según la acción (D-42)


def test_producir_borrador_da_el_paquete_completo_con_1_llamada_de_afirmaciones_y_4_de_redaccion() -> None:
    prov = ProveedorGuionado()
    r = generar(ficha("Producir borrador"), prov)
    assert r.tipo == "editorial" and isinstance(r.paquete, PaqueteEditorial)
    assert prov.claves == ["afirmaciones", "titulo", "brief", "guion", "resumen_web"]
    p = r.paquete
    assert p.titulo and len(p.titulares) == 2 and p.brief and p.enfoque and len(p.preguntas) == 3
    assert p.guion and p.resumen_web and p.copy_digital and p.vacios == []
    PaqueteEditorial.model_validate_json(p.model_dump_json())  # la salida valida con el esquema


def test_investigar_ya_y_vigilar_dan_solo_el_paquete_de_investigacion() -> None:
    for accion in ("Investigar ya", "Vigilar"):
        prov = ProveedorGuionado()
        r = generar(ficha(accion), prov)
        assert r.tipo == "investigacion" and isinstance(r.paquete, PaqueteInvestigacion)
        assert prov.claves == ["afirmaciones", "titulo_trabajo"]
        campos = set(r.paquete.model_dump())
        assert not campos & {"guion", "copy_digital", "brief", "titulares", "resumen_web"}
        assert r.paquete.titulo_trabajo and len(r.paquete.preguntas) == 3 and r.paquete.fuentes_verificaciones


def test_archivar_no_genera_nada_ni_llama_al_llm() -> None:
    for accion in ("Archivar", "Archivar como contexto"):
        prov = ProveedorGuionado()
        r = generar(ficha(accion), prov)
        assert r.tipo == "nada" and r.paquete is None and prov.llamadas == [] and r.motivo


def test_la_persona_puede_forzar_el_paquete_completo_y_queda_registrado() -> None:
    r = generar(ficha("Investigar ya"), ProveedorGuionado(), forzar_completo=True)
    assert r.tipo == "editorial" and isinstance(r.paquete, PaqueteEditorial)
    assert r.paquete.forzado is True and r.paquete.accion == "Investigar ya"
    assert generar(ficha("Producir borrador"), ProveedorGuionado()).paquete.forzado is False  # type: ignore[union-attr]


def test_completar_evidencia_y_producir_pone_los_vacios_de_la_ficha_arriba() -> None:
    p = generar(ficha("Completar evidencia y producir"), ProveedorGuionado()).paquete
    assert isinstance(p, PaqueteEditorial)
    assert [v.referencia for v in p.vacios[:3]] == ["V1", "V2", "V3"] and all(v.origen == "ficha" for v in p.vacios[:3])
    assert generar(ficha("Producir borrador"), ProveedorGuionado()).paquete.vacios == []  # type: ignore[union-attr]


def test_una_accion_desconocida_no_genera_nada() -> None:
    prov = ProveedorGuionado()
    r = generar(ficha("Publicar ya"), prov)
    assert r.tipo == "nada" and prov.llamadas == [] and "acción" in (r.motivo or "")


def test_sin_evidencia_se_abstiene_antes_de_llamar_al_llm() -> None:
    prov = ProveedorGuionado()
    r = generar(ficha(registros=[]), prov)
    assert r.tipo == "nada" and prov.llamadas == [] and "evidencia" in (r.motivo or "")


# ------------------------------------------------------------------ secciones sin LLM (D-43)


def test_fuentes_y_verificaciones_coinciden_exactamente_con_la_ficha() -> None:
    f = ficha()
    for accion in ("Producir borrador", "Investigar ya"):
        p = generar(f.model_copy(update={"accion": accion}), ProveedorGuionado()).paquete
        assert p.fuentes_verificaciones == f.fuentes_verificaciones  # type: ignore[union-attr]


def test_cada_pregunta_de_investigacion_referencia_un_vacio_existente() -> None:
    f = ficha()
    for accion in ("Producir borrador", "Investigar ya"):
        p = generar(f.model_copy(update={"accion": accion}), ProveedorGuionado()).paquete
        assert len(p.preguntas) == SALIDAS.preguntas  # type: ignore[union-attr]
        assert all(q.vacio in {v.id for v in f.vacios} for q in p.preguntas)  # type: ignore[union-attr]


def test_una_pregunta_con_un_vacio_inexistente_se_rechaza_y_tras_el_reintento_queda_vacia() -> None:
    mala = modificada(BUENAS["brief"], lambda d: d["preguntas"][0].update(vacio="V99"))
    prov = ProveedorGuionado(brief=mala)
    p = generar(ficha(), prov).paquete
    assert p.preguntas == [] and prov.claves.count("brief") == 2  # type: ignore[union-attr]
    assert any(v.origen == "seccion" and v.referencia == "preguntas" and "V99" in v.motivo for v in p.vacios)  # type: ignore[union-attr]
    assert p.brief and p.enfoque  # las otras secciones del grupo se conservan


def test_menos_de_tres_preguntas_se_rechaza() -> None:
    corta = modificada(BUENAS["brief"], lambda d: d.update(preguntas=d["preguntas"][:2]))
    p = generar(ficha(), ProveedorGuionado(brief=corta)).paquete
    assert p.preguntas == []  # type: ignore[union-attr]


# ------------------------------------------------------------------ cada oración cita afirmaciones validadas (D-22)


def _oraciones(p: PaqueteEditorial) -> list[Any]:
    return [*([p.titulo] if p.titulo else []), *p.titulares, *p.enfoque, *p.brief, *p.guion, *p.resumen_web, *p.copy_digital]


def test_cada_oracion_de_cada_seccion_referencia_al_menos_una_afirmacion_validada() -> None:
    p = generar(ficha(), ProveedorGuionado()).paquete
    assert isinstance(p, PaqueteEditorial)
    validas = {a.id for a in p.afirmaciones}
    for o in _oraciones(p):
        if o.texto == MARCADOR:
            continue
        assert o.afirmaciones and set(o.afirmaciones) <= validas, o.texto


def test_una_oracion_sin_afirmaciones_o_con_un_id_inventado_invalida_su_seccion() -> None:
    for malo in ([], ["A99"]):
        resumen = modificada(BUENAS["resumen_web"], lambda d, m=malo: d["resumen_web"][1].update(afirmaciones=m))
        prov = ProveedorGuionado(resumen_web=resumen)
        p = generar(ficha(), prov).paquete
        assert p.resumen_web == [] and prov.claves.count("resumen_web") == 2  # type: ignore[union-attr]
        assert any(v.referencia == "resumen_web" for v in p.vacios)  # type: ignore[union-attr]


def test_una_seccion_que_falla_no_borra_las_demas_y_el_borrador_es_parcial() -> None:
    p = generar(ficha(), ProveedorGuionado(guion={"guion": []})).paquete
    assert isinstance(p, PaqueteEditorial) and p.guion == [] and p.titulo and p.brief and p.resumen_web
    assert [v.referencia for v in p.vacios] == ["guion"] and p.vacios[0].origen == "seccion" and p.vacios[0].motivo


def test_el_reintento_puede_arreglar_la_seccion() -> None:
    mala = modificada(BUENAS["resumen_web"], lambda d: d["resumen_web"][0].update(afirmaciones=[]))
    prov = ProveedorGuionado(resumen_web=(mala, BUENAS["resumen_web"]))
    p = generar(ficha(), prov).paquete
    assert p.resumen_web and p.vacios == [] and prov.claves.count("resumen_web") == 2  # type: ignore[union-attr]
    # el reintento le dice al modelo qué falló, fuera de <evidencia>
    assert "La respuesta anterior" in prov.llamadas[-1][2] and "La respuesta anterior" not in prov.llamadas[-2][2]
    assert prov.llamadas[-1][2].rsplit("</evidencia>", 1)[1].count("La respuesta anterior") == 1


# ------------------------------------------------------------------ paso 1: afirmaciones validadas


def test_un_hecho_que_cita_solo_un_titular_se_descarta_porque_un_titular_es_una_declaracion() -> None:
    mala = modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"][0].update(tipo="hecho"))
    r = generar(ficha(), ProveedorGuionado(afirmaciones=mala))
    ids = {a.texto for a in r.paquete.afirmaciones}  # type: ignore[union-attr]
    assert "TVN Panamá reporta que Mulino anuncia un nuevo plan para el Canal de Panamá" not in ids
    assert any("declaración" in d or "hecho" in d for d in r.descartadas)


def test_un_hecho_solo_cita_datos_oficiales_o_el_conteo_del_grupo_nunca_titulares_x28() -> None:
    """Decisión D-18/D-68 (X28): un titular es una declaración aunque sean dos; el conteo es del grupo (GRP-)."""
    dos_titulares = modificada(
        BUENAS["afirmaciones"],
        lambda d: d["afirmaciones"].append(
            {"id": "A5", "tipo": "hecho", "texto": "Mulino robó fondos del Canal", "citas": [{"id": ID_TVN, "campo": "titulo"}, {"id": ID_REUTERS, "campo": "titulo"}], "base": []}
        ),
    )
    r = generar(ficha(), ProveedorGuionado(afirmaciones=dos_titulares))
    assert not any("robó" in a.texto for a in r.paquete.afirmaciones)  # type: ignore[union-attr]
    assert any("hecho" in d and "A5" in d for d in r.descartadas)
    mezcla = modificada(
        BUENAS["afirmaciones"],
        lambda d: d["afirmaciones"][2].update(citas=[{"id": ID_IND, "campo": "valor"}, {"id": ID_TVN, "campo": "titulo"}]),
    )
    p = generar(ficha(), ProveedorGuionado(afirmaciones=mezcla)).paquete
    assert not any(a.tipo == "hecho" for a in p.afirmaciones)  # type: ignore[union-attr]
    ok = generar(ficha(registros=[*ficha().registros, RegistroEvidencia(id="GRP-0000000001", campos={"n_titulares": "2 titulares de 2 medios reportan este tema"})]), ProveedorGuionado(
        afirmaciones=modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"].append(
            {"id": "A5", "tipo": "hecho", "texto": "Dos medios reportan este tema", "citas": [{"id": "GRP-0000000001", "campo": "n_titulares"}], "base": []}))
    )).paquete
    assert any(a.texto == "Dos medios reportan este tema" and a.tipo == "hecho" for a in ok.afirmaciones)  # type: ignore[union-attr]


def test_una_acusacion_nunca_es_hecho_el_prompt_lo_prohibe_y_las_reglas_de_tipo_la_dejan_como_declaracion() -> None:
    from src.generacion import cargar_prompt

    _, texto = cargar_prompt("afirmaciones_ficha")
    assert "acusación" in texto and "nunca" in texto.lower() and "NOT-" in texto
    assert "dos o más" not in texto and "contar al menos dos reportes" not in texto


def test_una_cita_con_id_o_campo_inexistente_descarta_la_afirmacion() -> None:
    for cita in ({"id": "NOT-dddddddddd", "campo": "titulo"}, {"id": ID_TVN, "campo": "cuerpo"}):
        mala = modificada(BUENAS["afirmaciones"], lambda d, c=cita: d["afirmaciones"][1].update(citas=[c]))
        r = generar(ficha(), ProveedorGuionado(afirmaciones=mala))
        assert all(ID_REUTERS not in [c.id for c in a.citas] for a in r.paquete.afirmaciones)  # type: ignore[union-attr]
        assert r.descartadas


def test_una_cita_de_dato_oficial_exige_el_anio_y_prohibe_actual() -> None:
    sin_anio = modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"][2].update(texto="La inflación de Panamá es de 2.9 % anual"))
    actual = modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"][2].update(texto="La inflación actual de Panamá en 2023 es de 2.9 %"))
    for mala in (sin_anio, actual):
        p = generar(ficha(), ProveedorGuionado(afirmaciones=mala)).paquete
        assert all(ID_IND not in [c.id for c in a.citas] for a in p.afirmaciones)  # type: ignore[union-attr]


def test_una_inferencia_con_base_inexistente_se_descarta_y_las_validas_se_renumeran() -> None:
    mala = modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"][3].update(base=["A9"]))
    p = generar(ficha(), ProveedorGuionado(afirmaciones=mala)).paquete
    assert [a.tipo for a in p.afirmaciones] == ["declaración", "declaración", "hecho"]  # type: ignore[union-attr]
    assert [a.id for a in p.afirmaciones] == ["A1", "A2", "A3"]  # type: ignore[union-attr]


def test_sin_ninguna_afirmacion_valida_no_se_redacta_nada_y_se_dice_por_que() -> None:
    nada = {"afirmaciones": [{"id": "A1", "tipo": "declaración", "texto": "x", "citas": [{"id": "NOT-dddddddddd", "campo": "titulo"}], "base": []}]}
    prov = ProveedorGuionado(afirmaciones=nada)
    r = generar(ficha(), prov)
    assert prov.claves == ["afirmaciones", "afirmaciones"]  # con un reintento
    assert isinstance(r.paquete, PaqueteEditorial) and r.paquete.titulo is None and r.paquete.brief == []
    assert [v.referencia for v in r.paquete.vacios if v.origen == "seccion"] == ["afirmaciones"]
    assert r.paquete.fuentes_verificaciones  # lo que no usa LLM se entrega igual


def test_una_cita_de_un_titular_en_ingles_se_marca_como_traducida() -> None:
    p = generar(ficha(), ProveedorGuionado()).paquete
    por_id = {a.id: a for a in p.afirmaciones}  # type: ignore[union-attr]
    assert [c.traducido for c in por_id["A2"].citas] == [True]  # Reuters, en inglés
    assert [c.traducido for c in por_id["A1"].citas] == [False] and not any(c.traducido for c in por_id["A3"].citas)
    assert cargar_generacion().traducido.marca == "(traducido)"


def test_las_comillas_deben_ser_literales_del_titular_citado() -> None:
    ok = modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"][0].update(texto='TVN reporta "nuevo plan para el Canal"'))
    inventada = modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"][0].update(texto='TVN reporta que Mulino dijo "esto es histórico"'))
    assert any("nuevo plan" in a.texto for a in generar(ficha(), ProveedorGuionado(afirmaciones=ok)).paquete.afirmaciones)  # type: ignore[union-attr]
    assert not any("histórico" in a.texto for a in generar(ficha(), ProveedorGuionado(afirmaciones=inventada)).paquete.afirmaciones)  # type: ignore[union-attr]


# ------------------------------------------------------------------ JSON inválido y proveedor caído


def test_json_invalido_se_reintenta_una_vez() -> None:
    prov = ProveedorGuionado(guion=("esto no es json", BUENAS["guion"]))
    p = generar(ficha(), prov).paquete
    assert p.guion and prov.claves.count("guion") == 2  # type: ignore[union-attr]


def test_json_invalido_dos_veces_deja_la_seccion_vacia_con_el_motivo() -> None:
    prov = ProveedorGuionado(guion=("no json", '{"guion": "tampoco"}'))
    p = generar(ficha(), prov).paquete
    assert p.guion == [] and prov.claves.count("guion") == 2  # type: ignore[union-attr]
    assert any(v.referencia == "guion" and "inválid" in v.motivo for v in p.vacios)  # type: ignore[union-attr]


def test_un_proveedor_caido_deja_partes_vacias_con_motivo_y_no_rompe() -> None:
    from tests.generacion_ayuda import fallo

    r = generar(ficha(), ProveedorGuionado(titulo=fallo()))
    p = r.paquete
    assert isinstance(p, PaqueteEditorial) and p.titulo is None and p.titulares == [] and p.brief
    assert any(v.referencia in ("titulo", "titulares", "copy_digital") and "no disponible" in v.motivo for v in p.vacios)


# ------------------------------------------------------------------ límites y prohibiciones (docs/salidas.md)


def test_limites_de_palabras_y_cantidades_se_aplican_por_seccion() -> None:
    largo = " ".join(["palabra"] * (SALIDAS.titulo_max_palabras + 1))
    casos = {
        "titulo": modificada(BUENAS["titulo"], lambda d: d["titulo"].update(texto="TVN reporta " + largo)),
        "titulares": modificada(BUENAS["titulo"], lambda d: d.update(titulares=d["titulares"][:1])),
        "copy_digital": modificada(BUENAS["titulo"], lambda d: d["copy_digital"][0].update(texto="TVN informa. #a #b #c")),
    }
    for seccion, mala in casos.items():
        p = generar(ficha(), ProveedorGuionado(titulo=mala)).paquete
        campo = {"titulo": p.titulo, "titulares": p.titulares, "copy_digital": p.copy_digital}[seccion]  # type: ignore[union-attr]
        assert not campo and any(v.referencia == seccion for v in p.vacios), seccion  # type: ignore[union-attr]


def test_el_brief_y_el_resumen_respetan_su_maximo_de_palabras() -> None:
    brief = modificada(BUENAS["brief"], lambda d: d["brief"][0].update(texto="TVN reporta " + " ".join(["palabra"] * SALIDAS.brief_max_palabras)))
    p = generar(ficha(), ProveedorGuionado(brief=brief)).paquete
    assert p.brief == [] and p.enfoque and len(p.preguntas) == 3  # type: ignore[union-attr]


def test_el_guion_respeta_el_rango_de_palabras_las_tres_partes_y_solo_el_marcador_visual() -> None:
    p = generar(ficha(), ProveedorGuionado()).paquete
    assert SALIDAS.guion_palabras_min <= palabras(" ".join(o.texto for o in p.guion)) <= SALIDAS.guion_palabras_max  # type: ignore[union-attr]
    assert {o.parte for o in p.guion} == {"entrada", "desarrollo", "cierre"}  # type: ignore[union-attr]
    assert any(o.texto == MARCADOR and o.afirmaciones == [] for o in p.guion)  # type: ignore[union-attr]
    corto = modificada(BUENAS["guion"], lambda d: d.update(guion=d["guion"][:3]))
    describe = modificada(BUENAS["guion"], lambda d: d["guion"].insert(0, {"texto": "[VISUAL: imagen aérea del Canal]", "afirmaciones": [], "parte": "entrada"}))
    sin_cierre = modificada(BUENAS["guion"], lambda d: d.update(guion=[o for o in d["guion"] if o["parte"] != "cierre"]))
    for mala in (corto, describe, sin_cierre):
        assert generar(ficha(), ProveedorGuionado(guion=mala)).paquete.guion == []  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "frase",
    [
        "Un escándalo sacude al Canal",  # sensacionalista
        "En entrevista con TVN el ministro explicó el plan",  # entrevista inventada
        "En estas imágenes se ve el Canal",  # describe material visual
        "Según el artículo, el plan es amplio",  # lectura simulada
    ],
)
def test_las_frases_prohibidas_de_restricciones_invalidan_la_seccion(frase: str) -> None:
    mala = modificada(BUENAS["resumen_web"], lambda d: d["resumen_web"][0].update(texto=f"TVN reporta. {frase}."))
    p = generar(ficha(), ProveedorGuionado(resumen_web=mala)).paquete
    assert p.resumen_web == [] and any(v.referencia == "resumen_web" for v in p.vacios)  # type: ignore[union-attr]


def test_el_copy_no_admite_emojis() -> None:
    mala = modificada(BUENAS["titulo"], lambda d: d["copy_digital"][0].update(texto="TVN informa del plan 🚨 #Canal"))
    assert generar(ficha(), ProveedorGuionado(titulo=mala)).paquete.copy_digital == []  # type: ignore[union-attr]


def test_un_titulo_que_es_declaracion_lleva_atribucion() -> None:
    sin = modificada(BUENAS["titulo"], lambda d: d["titulo"].update(texto="Mulino anuncia nuevo plan para el Canal"))
    p = generar(ficha(), ProveedorGuionado(titulo=sin)).paquete
    assert p.titulo is None and any(v.referencia == "titulo" for v in p.vacios)  # type: ignore[union-attr]


# ------------------------------------------------------------------ leyenda de alcance (D-51)


def test_toda_salida_lleva_marca_de_borrador_y_leyenda_de_alcance() -> None:
    for accion in ("Producir borrador", "Investigar ya"):
        p = generar(ficha(accion), ProveedorGuionado()).paquete
        assert p.marca == RESTR.marca_borrador and p.leyenda_alcance == RESTR.leyendas_alcance.titular_metadatos  # type: ignore[union-attr]
        assert (p.id_caso, p.version) == ("CASO-0007", 1)  # type: ignore[union-attr]
    con_desc = generar(ficha(uso_descripcion=True), ProveedorGuionado()).paquete
    assert con_desc.leyenda_alcance == RESTR.leyendas_alcance.con_descripcion  # type: ignore[union-attr]


def test_el_system_prompt_prohibe_simular_haber_leido_el_articulo_y_no_tiene_herramientas() -> None:
    prov = ProveedorGuionado()
    generar(ficha(), prov)
    for _, system, _ in prov.llamadas:
        assert "no simules haber leído el artículo completo" in system.lower()
        assert "no tienes herramientas" in system.lower()


# ------------------------------------------------------------------ contradicción abierta: ambas versiones


def _ficha_contradiccion() -> Any:
    f = ficha()
    return f.model_copy(update={"registros": [*f.registros, registro_prensa()], "contradicciones": contradiccion_abierta()})


def test_con_una_contradiccion_abierta_el_borrador_presenta_ambas_versiones() -> None:
    # Ambas versiones entran como afirmaciones (declaraciones) generadas por código; el brief debe citar las dos.
    brief = lambda s, u, n: modificada(  # noqa: E731
        BUENAS["brief"], lambda d: d["brief"].append({"texto": "TVN y La Prensa reportan versiones distintas.", "afirmaciones": _ids_contradiccion(s, u)})
    )
    p = generar(_ficha_contradiccion(), ProveedorGuionado(brief=brief)).paquete
    declaraciones = [a for a in p.afirmaciones if any(c.id in (ID_TVN, ID_PRENSA) for c in a.citas)]  # type: ignore[union-attr]
    assert {c.id for a in declaraciones for c in a.citas} >= {ID_TVN, ID_PRENSA}
    assert p.brief and sin_vacio(p, "brief")


def _ids_contradiccion(system: str, usuario: str) -> list[str]:
    # El mensaje de evidencia lista las afirmaciones como "A<n> [tipo] texto"; las dos versiones son las que citan TVN y La Prensa.
    return re.findall(r"^(A\d+) \[declaración\] .*(?:nuevo plan|sin plan)", usuario, flags=re.M)


def test_un_brief_que_omite_una_de_las_versiones_de_una_contradiccion_se_rechaza() -> None:
    p = generar(_ficha_contradiccion(), ProveedorGuionado()).paquete  # el brief bueno solo cita A1 y A3
    assert p.brief == [] and any(v.referencia == "brief" and "contradicción" in v.motivo for v in p.vacios)  # type: ignore[union-attr]


# ------------------------------------------------------------------ bajo demanda y registro de llamadas (D-44)


def test_cada_grupo_se_genera_solo_cuando_se_pide() -> None:
    prov = ProveedorGuionado()
    g = Generador(ficha(), prov)
    g.generar_grupo("guion")
    assert prov.claves == ["afirmaciones", "guion"]
    p = g.paquete()
    assert p.guion and p.titulo is None and p.brief == []
    g.generar_grupo("guion")  # ya generado: no se vuelve a llamar
    assert prov.claves == ["afirmaciones", "guion"]
    with pytest.raises(ValueError):
        g.generar_grupo("investigacion")  # no corresponde a un paquete completo


def test_cada_llamada_registra_tokens_y_latencia_sin_el_contenido() -> None:
    r = generar(ficha(), ProveedorGuionado())
    assert [c.paso for c in r.llamadas] == ["afirmaciones", "titulos", "brief", "guion", "resumen"]
    for c in r.llamadas:
        assert c.tokens_entrada == 100 and c.tokens_salida == 50 and c.latencia_s >= 0 and c.version_prompt and c.valida
        assert not hasattr(c, "system") and not hasattr(c, "usuario")


def test_los_prompts_estan_versionados_y_la_evidencia_va_en_el_mensaje_de_usuario() -> None:
    from src.generacion import cargar_prompt

    for nombre in (cargar_generacion().prompts.afirmaciones, cargar_generacion().prompts.redaccion):
        version, texto = cargar_prompt(nombre)
        assert re.fullmatch(r"\d+\.\d+", version) and texto.strip()
    prov = ProveedorGuionado()
    generar(ficha(), prov)
    for _, system, usuario in prov.llamadas:
        assert "<evidencia>" not in system.replace("<evidencia>…</evidencia>", "").replace("<evidencia> y </evidencia>", "")
        assert usuario.count("<evidencia>") == 1 and usuario.count("</evidencia>") == 1
        assert "{esquema}" not in system and "{marcador_visual}" not in system


# ------------------------------------------------------------------ esquemas de salida (docs/salidas.md)


def test_los_esquemas_tienen_exactamente_los_campos_de_salidas_md() -> None:
    comunes = {"marca", "id_caso", "version", "leyenda_alcance", "accion", "forzado", "vacios", "afirmaciones"}
    assert set(PaqueteEditorial.model_fields) == comunes | {"titulo", "titulares", "enfoque", "brief", "preguntas", "fuentes_verificaciones", "guion", "resumen_web", "copy_digital"}
    assert set(PaqueteInvestigacion.model_fields) == comunes | {"titulo_trabajo", "enfoque", "preguntas", "fuentes_verificaciones"}
    assert set(BoletinBanca.model_fields) == comunes | {"observaciones", "hipotesis_impacto", "sectores", "horizonte", "evidencia", "preguntas", "aviso"}
    with pytest.raises(ValidationError):
        PaqueteEditorial.model_validate({**json.loads(PaqueteEditorial(marca="m", id_caso="c", version=1, leyenda_alcance="l", accion="a").model_dump_json()), "publicar": True})


def test_el_paquete_investigacion_no_incluye_guion_ni_copy_en_su_esquema() -> None:
    assert not {"guion", "copy_digital", "brief", "titulares", "resumen_web"} & set(PaqueteInvestigacion.model_fields)


def test_una_modalidad_sin_generacion_implementada_no_genera_nada() -> None:
    prov = ProveedorGuionado()
    r = generar(ficha(modalidad="banca"), prov)
    assert r.tipo == "nada" and prov.llamadas == [] and "E2-02" in (r.motivo or "")


def test_al_alcanzar_el_tope_de_costo_la_generacion_se_detiene_y_no_deja_un_paquete_a_medias() -> None:
    from src.llm.costo import TopeDeCostoAlcanzado

    class ConTope(ProveedorGuionado):
        def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
            if len(self.llamadas) == 2:
                raise TopeDeCostoAlcanzado("tope de costo alcanzado")
            return super().generar_json(system, usuario, esquema)

    with pytest.raises(TopeDeCostoAlcanzado):
        generar(ficha(), ConTope())


def test_una_seccion_que_solo_supera_el_maximo_se_recorta_por_oraciones_y_queda_constancia() -> None:
    cuerpo = " ".join(["palabra"] * 30)
    largo = modificada(BUENAS["resumen_web"], lambda d: d.update(resumen_web=[{"texto": f"TVN reporta {cuerpo}.", "afirmaciones": ["A1"]} for _ in range(6)]))
    prov = ProveedorGuionado(resumen_web=largo)
    p = generar(ficha(), prov).paquete
    assert prov.claves.count("resumen_web") == 2  # el reintento se hizo antes de recortar
    assert 0 < len(p.resumen_web) < 6 and sum(palabras(o.texto) for o in p.resumen_web) <= SALIDAS.resumen_web_max_palabras  # type: ignore[union-attr]
    nota = [v for v in p.vacios if v.referencia == "resumen_web"]  # type: ignore[union-attr]
    assert len(nota) == 1 and nota[0].motivo.startswith("recortada")
    assert all(o.texto in {x["texto"] for x in largo["resumen_web"]} for o in p.resumen_web)  # solo oraciones del modelo, sin agregar nada  # type: ignore[union-attr]


def test_el_recorte_no_se_aplica_a_secciones_que_fallan_por_otra_razon() -> None:
    cuerpo = " ".join(["palabra"] * 30)
    mala = modificada(BUENAS["resumen_web"], lambda d: d.update(resumen_web=[{"texto": f"TVN reporta {cuerpo}.", "afirmaciones": ["A99"]} for _ in range(6)]))
    assert generar(ficha(), ProveedorGuionado(resumen_web=mala)).paquete.resumen_web == []  # type: ignore[union-attr]


def test_forzar_el_paquete_completo_no_genera_para_una_accion_desconocida() -> None:
    prov = ProveedorGuionado()
    r = generar(ficha("Publicar ya"), prov, forzar_completo=True)
    assert r.tipo == "nada" and prov.llamadas == [] and "desconocida" in (r.motivo or "")
    assert generar(ficha("Archivar"), ProveedorGuionado(), forzar_completo=True).paquete.forzado is True  # type: ignore[union-attr]  # D-42: la persona puede forzar


def test_el_recorte_nunca_deja_una_contradiccion_con_una_sola_version_ni_toca_la_leyenda() -> None:
    cuerpo = " ".join(["palabra"] * 60)
    f = _ficha_contradiccion()
    pesado = modificada(BUENAS["brief"], lambda d: d.update(brief=[{"texto": f"TVN reporta {cuerpo}.", "afirmaciones": ["A1"]} for _ in range(4)]))
    brief = lambda s, u, n: modificada(pesado, lambda d: d["brief"].append({"texto": "La Prensa y TVN difieren.", "afirmaciones": _ids_contradiccion(s, u)}))  # noqa: E731
    p = generar(f, ProveedorGuionado(brief=brief)).paquete
    assert p.brief == []  # type: ignore[union-attr]  # quitar el final dejaría una sola versión: se entrega vacío, no cortado
    assert p.leyenda_alcance == RESTR.leyendas_alcance.titular_metadatos  # type: ignore[union-attr]


def test_las_listas_de_la_validacion_viven_en_el_yaml() -> None:
    cfg = cargar_generacion()
    assert {"actual", "actualmente", "hoy"} <= set(cfg.volatiles) and cfg.patron_anio_en_id
    assert set(cfg.prefijos.hecho_oficial) == {"IND-", "SIS-", "SBP-"} and cfg.prefijos.hecho_conteo == ["GRP-"]
    assert {"n_titulares", "n_medios", "n_procedencias"} <= set(cfg.campos_conteo)
    fuente = open("src/generacion.py", encoding="utf-8").read()
    assert "PALABRAS_VOLATILES" not in fuente and "def _anio_de(" not in fuente


def test_salidas_md_documenta_los_campos_de_metadatos_como_tales() -> None:
    texto = open("docs/salidas.md", encoding="utf-8").read()
    assert "Metadatos de la generación" in texto
    for campo in ("accion", "forzado", "vacios", "afirmaciones"):
        assert f"`{campo}`" in texto.split("Metadatos de la generación", 1)[1]
