"""T08 · Caso de prioridad alta (E1-10): componentes, versión de reglas, rango, desempate y reproducibilidad.

Cubre también los componentes R, I, U, N y E de las reglas v1.3 con grupos sintéticos (sin red ni LLM).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.t08

from src import procedencias, puntaje
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, entrada, iso, miembro, vector

import numpy as np


def _calcular(entradas, reglas=REGLAS, ahora=AHORA):
    return {p.id_grupo: p for p in puntaje.calcular_puntajes(entradas, reglas, CFG, ahora)}


def _varios(*extra, n_relleno: int = 4):
    """Grupos de relleno con similitudes más bajas (para que el percentil del grupo de interés llegue a 1)."""
    relleno = [
        entrada(
            f"GRP-relleno{i}",
            [miembro(f"NOT-r{i:09d}", "Relleno sin interés", similitud=0.70 + 0.01 * i, publicado_hace=300 + i, regional=True)],
            vectores=np.stack([vector(1.0, 5.0 + i)]),
            n_procedencias=1,
        )
        for i in range(n_relleno)
    ]
    return [*relleno, *extra]


# ------------------------------------------------------------------ T08


def test_un_grupo_de_prioridad_alta_expone_componentes_version_y_no_habilita_publicacion() -> None:
    fuerte = entrada(
        "GRP-fuerte",
        [
            miembro("NOT-a000000001", "Gobierno anuncia a nivel nacional un decreto", "prensa.com", similitud=0.95, publicado_hace=2),
            miembro("NOT-a000000002", "Ley nueva a nivel nacional", "laestrella.com.pa", similitud=0.95, publicado_hace=3),
            miembro("NOT-a000000003", "Decreto a nivel nacional", "tvn-2.com", similitud=0.95, publicado_hace=4),
        ],
        vectores=np.stack([vector(0.0, 1.0)] * 3),
        subtema="crecimiento_pib",
        n_procedencias=3,
        tiene_oficial=True,
    )
    resultado = _calcular(_varios(fuerte))["GRP-fuerte"]
    assert resultado.puntaje >= 70
    assert resultado.rango == "alto"
    assert set(resultado.componentes) == {"R", "I", "U", "N", "E"}
    for nombre, c in resultado.componentes.items():
        assert 0.0 <= c.valor <= 1.0, nombre
        assert c.explicacion, f"{nombre} no explica de qué valores sale"
    assert resultado.version_reglas == REGLAS.version == "1.3"
    assert resultado.habilita_publicacion is False
    assert "publicar" not in json.dumps(resultado.a_diccionario(), ensure_ascii=False).lower()


def test_el_puntaje_es_la_suma_ponderada_de_los_componentes() -> None:
    grupos = _varios(entrada("GRP-x", [miembro("NOT-x000000001", similitud=0.9)], n_procedencias=2, tiene_oficial=True))
    for p in _calcular(grupos).values():
        esperado = sum(getattr(REGLAS.pesos, k) * c.valor for k, c in p.componentes.items())
        assert p.puntaje == pytest.approx(esperado)
        assert p.rango == puntaje.rango_de(p.puntaje, REGLAS)


def test_los_rangos_no_se_solapan_y_el_limite_va_al_rango_superior() -> None:
    assert puntaje.rango_de(0, REGLAS) == "bajo"
    assert puntaje.rango_de(39.999, REGLAS) == "bajo"
    assert puntaje.rango_de(40, REGLAS) == "medio"
    assert puntaje.rango_de(69.999, REGLAS) == "medio"
    assert puntaje.rango_de(70, REGLAS) == "alto"
    assert puntaje.rango_de(100, REGLAS) == "alto"


# ------------------------------------------------------------------ reproducibilidad y desempate


def test_dos_ejecuciones_producen_el_mismo_ranking() -> None:
    grupos = _varios(
        entrada("GRP-a", [miembro("NOT-a000000001", similitud=0.9, publicado_hace=5)], tiene_oficial=True),
        entrada("GRP-b", [miembro("NOT-b000000001", similitud=0.85, publicado_hace=40)], n_procedencias=3),
    )
    primera = puntaje.calcular_puntajes(grupos, REGLAS, CFG, AHORA)
    segunda = puntaje.calcular_puntajes(list(reversed(grupos)), REGLAS, CFG, AHORA)
    assert [(p.id_grupo, p.posicion, p.puntaje) for p in primera] == [(p.id_grupo, p.posicion, p.puntaje) for p in segunda]
    assert [p.posicion for p in primera] == list(range(1, len(primera) + 1))


def _con(id_grupo: str, p: float, u: float) -> puntaje.Puntaje:
    return puntaje.Puntaje(
        id_grupo=id_grupo,
        posicion=0,
        version_reglas=REGLAS.version,
        fecha_referencia=iso(0),
        componentes={k: puntaje.Componente(u if k == "U" else 0.5, {"prueba": True}) for k in puntaje.COMPONENTES},
        puntaje=p,
        rango=puntaje.rango_de(p, REGLAS),
        vacios=(),
        recirculada=False,
        es_nueva=True,
    )


def test_el_desempate_es_mayor_urgencia_y_luego_menor_id() -> None:
    lista = [_con("GRP-c", 60.0, 0.2), _con("GRP-b", 60.0, 0.9), _con("GRP-a", 60.0, 0.2), _con("GRP-z", 61.0, 0.0)]
    orden = [p.id_grupo for p in puntaje.ordenar(lista, REGLAS, CFG)]
    assert orden == ["GRP-z", "GRP-b", "GRP-a", "GRP-c"]   # P, luego U descendente, luego ID ascendente


def test_un_empate_por_ruido_de_coma_flotante_no_decide_el_orden() -> None:
    lista = [_con("GRP-b", 60.0 + 1e-13, 0.1), _con("GRP-a", 60.0, 0.1)]
    assert [p.id_grupo for p in puntaje.ordenar(lista, REGLAS, CFG)] == ["GRP-a", "GRP-b"]


# ------------------------------------------------------------------ similitudes (D-103: ya no hay percentiles en R ni en N)


def test_r_y_n_quedan_en_el_rango_0_1_y_n_declara_el_umbral_de_agrupacion() -> None:
    """D-103 reemplaza al test de percentiles de D-35: R no usa la similitud temática y N usa el umbral de agrupación."""
    sims = [0.80, 0.81, 0.82, 0.83, 0.84]
    grupos = [
        entrada(
            f"GRP-{i}",
            [miembro(f"NOT-{i:010d}", f"Titular {i}", similitud=s, publicado_hace=100 + 10 * i)],
            vectores=np.stack([vector(1.0, 0.1 * (i + 1))]),
        )
        for i, s in enumerate(sims)
    ]
    resultado = _calcular(grupos)
    assert all(0.0 <= p.componentes[k].valor <= 1.0 for p in resultado.values() for k in ("R", "N"))
    assert {p.componentes["R"].valor for p in resultado.values()} == {REGLAS.relevancia.foco_panama_sujeto}
    assert {p.componentes["N"].explicacion["umbral_similitud"] for p in resultado.values()} == {REGLAS.agrupacion.umbral_similitud}


# ------------------------------------------------------------------ R · foco


def test_noticia_de_otro_pais_que_afecta_a_panama_tiene_foco_medio_y_sobre_panama_foco_pleno() -> None:
    grupos = _varios(
        entrada("GRP-pa", [miembro("NOT-p000000001", "Panamá aprueba presupuesto", regional=False, similitud=0.9)]),
        entrada("GRP-otro", [miembro("NOT-o000000001", "El Niño golpea Centroamérica", regional=True, similitud=0.9)]),
    )
    r = _calcular(grupos)
    assert r["GRP-pa"].componentes["R"].explicacion["foco"] == REGLAS.relevancia.foco_panama_sujeto == 1.0
    assert r["GRP-otro"].componentes["R"].explicacion["foco"] == REGLAS.relevancia.foco_otro_pais_afecta == 0.5
    # D-103: R = peso_foco × foco (sin la parte temática)
    assert r["GRP-pa"].componentes["R"].valor == pytest.approx(REGLAS.relevancia.peso_foco * 1.0)
    assert r["GRP-otro"].componentes["R"].valor == pytest.approx(REGLAS.relevancia.peso_foco * 0.5)


def test_un_grupo_con_un_titular_sobre_panama_tiene_foco_pleno_aunque_otros_sean_regionales() -> None:
    mixto = entrada(
        "GRP-mixto",
        [miembro("NOT-m000000001", "Nota regional", regional=True), miembro("NOT-m000000002", "Nota sobre Panamá", regional=False)],
    )
    assert _calcular(_varios(mixto))["GRP-mixto"].componentes["R"].explicacion["foco"] == 1.0


# ------------------------------------------------------------------ I · alcance geográfico y subtema


@pytest.mark.parametrize(
    ("titulo", "nivel"),
    [
        ("Gobierno decreta alza a nivel nacional", "nacional"),
        ("Sube la factura de luz en todo el país", "nacional"),
        ("Lluvias dejan daños en Chiriquí", "provincial"),
        ("Comarca Ngäbe-Buglé sin agua potable", "provincial"),
        ("Cierran escuela en David", "local"),
        ("Corte de agua en Arraiján", "local"),
        ("Se reúne el comité técnico", "desconocido"),
        ("Presidente de Panamá inaugura una planta", "nacional"),   # «Panamá» es el país, no la provincia (E1-10c, X42: el país da alcance nacional); con un país extranjero nombrado sería `exterior` (D-115)
        ("Corte de agua en la provincia de Panamá", "provincial"),
    ],
)
def test_alcance_geografico_nacional_provincial_local_segun_la_lista_del_yaml(titulo: str, nivel: str) -> None:
    g = puntaje.alcance_geografico([miembro(titulo=titulo)], REGLAS, CFG)
    assert g.nivel == nivel
    assert g.valor == getattr(REGLAS.impacto.alcance_geografico, nivel)


def test_el_alcance_del_grupo_es_el_mas_amplio_de_sus_titulares() -> None:
    g = puntaje.alcance_geografico(
        [miembro("NOT-1", "Cierran escuela en David"), miembro("NOT-2", "Decreto a nivel nacional"), miembro("NOT-3", "Lluvias en Veraguas")], REGLAS, CFG
    )
    assert g.nivel == "nacional"
    assert g.terminos == ("a nivel nacional",) or "a nivel nacional" in g.terminos


def test_i_combina_subtema_y_alcance_geografico_sin_dato_oficial_ni_procedencias() -> None:
    base = dict(miembros=[miembro("NOT-i000000001", "Decreto a nivel nacional")], subtema="crecimiento_pib")
    sin = entrada("GRP-sin", n_procedencias=1, tiene_oficial=False, **base)
    con = entrada("GRP-con", n_procedencias=3, tiene_oficial=True, **base)
    r = _calcular(_varios(sin, con))
    esperado = 0.5 * REGLAS.impacto.alcance_subtema["crecimiento_pib"] + 0.5 * REGLAS.impacto.alcance_geografico.nacional
    assert r["GRP-sin"].componentes["I"].valor == pytest.approx(esperado)
    assert r["GRP-con"].componentes["I"].valor == r["GRP-sin"].componentes["I"].valor   # D-15, D-35


def test_un_grupo_sin_subtema_usa_el_alcance_neutro_y_lo_declara_como_vacio() -> None:
    p = _calcular(_varios(entrada("GRP-ns", subtema=None)))["GRP-ns"]
    assert p.componentes["I"].explicacion["alcance_subtema"] == CFG.impacto.alcance_subtema_desconocido
    assert any(v.codigo == "subtema_desconocido" for v in p.vacios)


# ------------------------------------------------------------------ U · urgencia


def _u(*miembros) -> puntaje.Componente:
    return _calcular([entrada("GRP-u", list(miembros))])["GRP-u"].componentes["U"]


def test_u_es_plena_dentro_de_las_horas_pleno_y_nula_pasados_los_dias_nulos() -> None:
    assert _u(miembro(publicado_hace=REGLAS.urgencia.horas_pleno - 1)).valor == 1.0
    assert _u(miembro(publicado_hace=REGLAS.urgencia.dias_nulo * 24 + 1)).valor == 0.0
    assert _u(miembro(publicado_hace=REGLAS.urgencia.dias_nulo * 24)).valor == 0.0


def test_u_es_lineal_entre_los_dos_extremos() -> None:
    pleno, nulo = REGLAS.urgencia.horas_pleno, REGLAS.urgencia.dias_nulo * 24
    medio = (pleno + nulo) / 2
    assert _u(miembro(publicado_hace=medio)).valor == pytest.approx(0.5)
    assert _u(miembro(publicado_hace=pleno)).valor == pytest.approx(1.0)


def test_u_usa_la_publicacion_original_mas_reciente_del_grupo() -> None:
    c = _u(miembro("NOT-1", publicado_hace=24 * 30), miembro("NOT-2", publicado_hace=3), miembro("NOT-3", publicado_hace=24 * 3))
    assert c.valor == pytest.approx(1 - 3 / (REGLAS.urgencia.dias_nulo * 24))   # D-106: la de 3 h, sin meseta
    assert c.explicacion["fecha_origen"] == "publicacion"
    assert c.explicacion["fecha"] == iso(3)


def test_una_publicacion_posterior_a_la_referencia_no_pasa_de_1() -> None:
    assert _u(miembro(publicado_hace=-5)).valor == 1.0


def test_sin_fecha_de_publicacion_u_usa_la_deteccion_y_agrega_el_vacio() -> None:
    p = _calcular([entrada("GRP-g", [miembro("NOT-1", publicado_hace=None, detectado_hace=10), miembro("NOT-2", publicado_hace=None, detectado_hace=50)])])["GRP-g"]
    c = p.componentes["U"]
    assert c.explicacion["fecha_origen"] == "deteccion"
    assert c.explicacion["fecha"] == iso(10)            # la más reciente
    assert c.valor == pytest.approx(1 - 10 / (REGLAS.urgencia.dias_nulo * 24))   # D-106: la de 10 h, sin meseta
    assert [v.texto for v in p.vacios if v.codigo == "urgencia_sin_publicacion"] == [REGLAS.urgencia.vacio_sin_publicacion]


def test_con_alguna_publicacion_la_deteccion_no_se_mezcla_ni_agrega_vacio() -> None:
    p = _calcular(
        [entrada("GRP-m", [miembro("NOT-1", publicado_hace=24 * 5), miembro("NOT-2", publicado_hace=None, detectado_hace=1)])]
    )["GRP-m"]
    assert p.componentes["U"].explicacion["fecha_origen"] == "publicacion"
    assert p.componentes["U"].valor < 1.0                # la detección reciente NO sustituye a la publicación
    assert not any(v.codigo == "urgencia_sin_publicacion" for v in p.vacios)


def test_un_grupo_sin_ninguna_fecha_no_inventa_urgencia() -> None:
    with pytest.raises(ValueError, match="sin ninguna fecha"):
        _calcular([entrada("GRP-0", [miembro(publicado_hace=None, detectado_hace=None)])])


# ------------------------------------------------------------------ N · novedad


def test_el_primer_grupo_no_tiene_con_que_compararse() -> None:
    r = _calcular(
        [
            entrada("GRP-1", [miembro("NOT-1", publicado_hace=100)], vectores=np.stack([vector(1, 0)])),
            entrada("GRP-2", [miembro("NOT-2", publicado_hace=50)], vectores=np.stack([vector(1, 0.2)])),
        ]
    )
    assert r["GRP-1"].componentes["N"].valor == REGLAS.novedad.sin_grupos_previos
    assert r["GRP-1"].componentes["N"].explicacion["grupos_previos"] == 0


def test_la_duplicacion_no_incrementa_el_puntaje_un_grupo_casi_igual_a_uno_anterior_tiene_menos_novedad() -> None:
    r = _calcular(
        [
            entrada("GRP-a", [miembro("NOT-a", publicado_hace=200)], vectores=np.stack([vector(1, 0)])),
            entrada("GRP-b", [miembro("NOT-b", publicado_hace=150)], vectores=np.stack([vector(0, 1)])),
            entrada("GRP-copia", [miembro("NOT-c", publicado_hace=100)], vectores=np.stack([vector(1, 0.01)])),   # casi igual a GRP-a
            entrada("GRP-nuevo", [miembro("NOT-n", publicado_hace=50)], vectores=np.stack([vector(1, 1)])),
        ]
    )
    assert r["GRP-copia"].componentes["N"].valor < r["GRP-nuevo"].componentes["N"].valor
    assert r["GRP-copia"].componentes["N"].explicacion["grupo_mas_parecido"] == "GRP-a"


def test_n_compara_solo_con_grupos_anteriores_por_fecha_de_publicacion() -> None:
    r = _calcular(
        [
            entrada("GRP-viejo", [miembro("NOT-v", publicado_hace=300)], vectores=np.stack([vector(1, 0)])),
            entrada("GRP-reciente", [miembro("NOT-r", publicado_hace=10)], vectores=np.stack([vector(1, 0.01)])),
        ]
    )
    assert r["GRP-viejo"].componentes["N"].explicacion["grupos_previos"] == 0
    assert r["GRP-reciente"].componentes["N"].explicacion["grupos_previos"] == 1


# ------------------------------------------------------------------ E · evidencia (v1.3, D-56)


def test_e_cuenta_procedencias_no_titulares() -> None:
    tres_copias = entrada("GRP-copias", [miembro(f"NOT-c{i}", f"Despacho {i}") for i in range(3)], n_procedencias=1)
    tres_fuentes = entrada("GRP-fuentes", [miembro(f"NOT-f{i}", f"Despacho {i}") for i in range(3)], n_procedencias=3)
    r = _calcular(_varios(tres_copias, tres_fuentes))
    e_copias, e_fuentes = r["GRP-copias"].componentes["E"], r["GRP-fuentes"].componentes["E"]
    assert e_copias.explicacion["fraccion_procedencias"] == procedencias.fraccion_de_procedencias(1, REGLAS) == pytest.approx(1 / 3)
    assert e_fuentes.explicacion["fraccion_procedencias"] == 1.0
    assert e_copias.valor < e_fuentes.valor
    assert e_copias.explicacion["n_titulares"] == 3 and e_copias.explicacion["n_procedencias"] == 1


def test_dos_grupos_identicos_salvo_por_tener_dato_oficial_tienen_la_misma_i_y_distinta_e() -> None:
    base = dict(miembros=[miembro("NOT-o000000001", "Inflación sube a nivel nacional")], subtema="inflacion_precios", n_procedencias=2)
    r = _calcular(_varios(entrada("GRP-sin", tiene_oficial=False, **base), entrada("GRP-con", tiene_oficial=True, **base)))
    assert r["GRP-con"].componentes["I"].valor == r["GRP-sin"].componentes["I"].valor
    assert r["GRP-con"].componentes["E"].valor > r["GRP-sin"].componentes["E"].valor
    assert r["GRP-con"].componentes["E"].valor - r["GRP-sin"].componentes["E"].valor == pytest.approx(REGLAS.evidencia.peso_oficial)


def test_dos_grupos_identicos_salvo_por_la_proporcion_de_titulares_con_medio_y_fecha_conocidos_tienen_distinta_e() -> None:
    conocidos = [miembro("NOT-k1", "Nota uno", "prensa.com", publicado_hace=2), miembro("NOT-k2", "Nota dos", "tvn-2.com", publicado_hace=3)]
    a_medias = [miembro("NOT-k1", "Nota uno", "prensa.com", publicado_hace=2), miembro("NOT-k2", "Nota dos", "tvn-2.com", publicado_hace=None, detectado_hace=3)]
    r = _calcular(_varios(entrada("GRP-todos", conocidos), entrada("GRP-mitad", a_medias)))
    assert r["GRP-todos"].componentes["E"].explicacion["proporcion_identificables"] == 1.0
    assert r["GRP-mitad"].componentes["E"].explicacion["proporcion_identificables"] == 0.5
    assert r["GRP-todos"].componentes["E"].valor - r["GRP-mitad"].componentes["E"].valor == pytest.approx(REGLAS.evidencia.peso_identificables * 0.5)


def test_un_medio_desconocido_no_cuenta_como_identificable() -> None:
    p = _calcular([entrada("GRP-d", [miembro("NOT-1", medio="desconocido"), miembro("NOT-2", medio="prensa.com")])])["GRP-d"]
    assert p.componentes["E"].explicacion["proporcion_identificables"] == 0.5


# ------------------------------------------------------------------ el tono y el número de titulares no entran


def test_el_tono_y_la_cantidad_de_titulares_no_entran_en_ningun_componente() -> None:
    uno = entrada("GRP-1", [miembro("NOT-1", "Crisis catastrófica: colapsa todo", similitud=0.9)], n_procedencias=1)
    muchos = entrada(
        "GRP-N",
        [miembro(f"NOT-{i}", "Crisis catastrófica: colapsa todo", similitud=0.9) for i in range(10)],
        vectores=np.stack([vector(1.0, 2.0)] * 10),
        n_procedencias=1,
    )
    r = {p.id_grupo: p for p in puntaje.calcular_puntajes([uno], REGLAS, CFG, AHORA)}
    s = {p.id_grupo: p for p in puntaje.calcular_puntajes([muchos], REGLAS, CFG, AHORA)}
    for k in puntaje.COMPONENTES:
        assert r["GRP-1"].componentes[k].valor == s["GRP-N"].componentes[k].valor, k


def test_la_fecha_de_referencia_se_registra_en_utc() -> None:
    p = _calcular([entrada("GRP-1")], ahora=datetime(2026, 10, 6, 12, 0, tzinfo=UTC))["GRP-1"]
    assert p.fecha_referencia == "2026-10-06T12:00:00Z"


# ------------------------------------------------------------------ M2: la geografía ignora tildes, guiones y espacios de más


@pytest.mark.parametrize(
    "titulo",
    ["Sin agua en la comarca Ngäbe Buglé", "Sin agua en Ngabe-Bugle", "Sin agua en la comarca NGÄBE–BUGLÉ", "Sin agua en Emberá Wounaan", "Sin agua en Embera-Wounaan", "Alerta en Guna  Yala", "Alerta en Bocas  del   Toro", "Alerta en Bocas-del-Toro"],
)
def test_m2_la_geografia_normaliza_guiones_espacios_y_tildes(titulo: str) -> None:
    assert puntaje.alcance_geografico([miembro(titulo=titulo)], REGLAS, CFG).nivel == "provincial"


def test_m2_el_guion_no_une_palabras_distintas() -> None:
    assert puntaje.alcance_geografico([miembro(titulo="Corte en Chiriquígrande")], REGLAS, CFG).nivel == "desconocido"


def test_t08_aceptacion_expone_componentes_y_regla_y_la_prioridad_no_habilita_publicacion() -> None:
    """PDF T08: exponer componentes y regla; la prioridad no habilita publicación."""
    fuerte = entrada(
        "GRP-t08",
        [miembro(f"NOT-t08000000{n}", "Gobierno anuncia a nivel nacional un decreto", d, similitud=0.95, publicado_hace=2 + n) for n, d in enumerate(("prensa.com", "laestrella.com.pa", "tvn-2.com"))],
        vectores=np.stack([vector(0.0, 1.0)] * 3), subtema="crecimiento_pib", n_procedencias=3, tiene_oficial=True,
    )
    r = _calcular(_varios(fuerte))["GRP-t08"]
    assert r.rango == "alto" and set(r.componentes) == {"R", "I", "U", "N", "E"} and all(c.explicacion for c in r.componentes.values())
    assert r.version_reglas == REGLAS.version                                # la regla que produjo el puntaje
    assert r.habilita_publicacion is False and "publicar" not in json.dumps(r.a_diccionario(), ensure_ascii=False).lower()
