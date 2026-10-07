"""E1-13 · Una prueba por regla del validador (spec E1-13): lo rechazado y su contraparte permitida. Todo determinista, sin LLM."""

from __future__ import annotations

import pytest

from src.esquemas import Afirmacion
from src.generacion import ContradiccionFicha
from src.validador import (
    ACUSACION, CAUSALIDAD, CIFRA_NO_COINCIDE, CITA_INEXISTENTE, COMILLAS_NO_LITERALES, CONTRADICCION_UNA_VERSION, EXCESO_TRANSICIONES,
    FECHA_NO_COINCIDE, HECHO_NO_OFICIAL, HIPOTESIS_SIN_CONDICIONAL, IND_SIN_ANIO, IND_VOLATIL, INFERENCIA_SIN_BASE, LEYENDA, LIMITE_PALABRAS,
    MARCADOR_VISUAL, NOMBRE_NUEVO, SIN_ATRIBUCION, TITULAR_SIN_ATRIBUCION, TRANSICION_NO_PERMITIDA, cifras_sin_respaldo, contar_palabras,
    validar_afirmaciones, validar_leyenda, validar_seccion,
)
from tests.validador_ayuda import (
    ID_CITA, ID_ENTREVISTA, ID_GRP, ID_IND, ID_IND_DECIMAL, ID_PRENSA, ID_REUTERS, ID_TVN, LEYENDA as TXT_LEYENDA, LEYENDA_DESCRIPCION, MARCADOR,
    afirmacion, contexto, contradiccion, ctx_con_base, ficha, o, reglas, relleno,
)


ID_LLUVIAS_B = "NOT-1111111111"   # titulares de la ficha bancaria de tests/generacion_ayuda.py
ID_BANANO_B = "NOT-2222222222"


def valida(*afirmaciones: Afirmacion, ctx=None):  # type: ignore[no-untyped-def]
    return validar_afirmaciones(list(afirmaciones), ctx or contexto())


def rechazada(a: Afirmacion, regla: str, ctx=None) -> None:  # type: ignore[no-untyped-def]
    r = valida(a, ctx=ctx)
    assert not r.validas and regla in reglas(r.rechazos), [(x.regla, x.motivo) for x in r.rechazos]


def aceptada(a: Afirmacion, ctx=None) -> None:  # type: ignore[no-untyped-def]
    r = valida(a, ctx=ctx)
    assert [x.id for x in r.validas] == [a.id], [(x.regla, x.motivo) for x in r.rechazos]


# ============================================================================================ citas (PDF sección 7)


def test_cita_a_un_id_inexistente_se_rechaza() -> None:
    rechazada(afirmacion("A1", "hecho", "La inflación fue de 2.9 % anual en 2019", ("IND-PAN-FP.CPI.TOTL.ZG-2019", "valor")), CITA_INEXISTENTE)


def test_cita_a_un_campo_inexistente_se_rechaza() -> None:
    rechazada(afirmacion("A1", "hecho", "La inflación fue de 2.9 % anual en 2023", (ID_IND, "inflacion")), CITA_INEXISTENTE)


def test_una_cita_valida_se_acepta() -> None:
    aceptada(afirmacion("A1", "hecho", "La inflación de Panamá fue de 2.9 % anual en 2023", (ID_IND, "valor")))


# ============================================================================================ cifras (D-45, normalización)


def test_una_cifra_que_no_coincide_con_el_campo_citado_se_rechaza() -> None:
    rechazada(afirmacion("A1", "hecho", "La inflación de Panamá fue de 9.9 % anual en 2023", (ID_IND, "valor")), CIFRA_NO_COINCIDE)


def test_coma_o_punto_decimal_dan_la_misma_cifra() -> None:
    """«1,5 %» coincide con el valor 1.5."""
    aceptada(afirmacion("A1", "hecho", "El crecimiento de Panamá fue de 1,5 % en 2022", (ID_IND_DECIMAL, "valor")))
    assert cifras_sin_respaldo("creció 1,5 %", ["1.5"], contexto().val) == []
    assert cifras_sin_respaldo("creció 1.5 %", ["1,5 %"], contexto().val) == []


def test_el_separador_de_miles_se_normaliza() -> None:
    val = contexto().val
    assert cifras_sin_respaldo("1.234,5 personas", ["1234.5"], val) == []
    assert cifras_sin_respaldo("1,234.5 personas", ["1234,5"], val) == []
    assert cifras_sin_respaldo("2.500 personas", ["2500"], val) == []
    assert cifras_sin_respaldo("2.500 personas", ["2.5"], val) == []
    assert cifras_sin_respaldo("3.000 personas", ["2500"], val) == ["3.000"]


def test_la_cifra_redondeada_se_acepta_y_la_distinta_no() -> None:
    val = contexto().val
    assert cifras_sin_respaldo("2.9 %", ["2.934 % anual"], val) == []
    assert cifras_sin_respaldo("3.0 %", ["2.934 % anual"], val) == ["3.0"]


def test_una_declaracion_con_una_cifra_que_el_titular_no_trae_se_rechaza() -> None:
    rechazada(afirmacion("A1", "declaración", "TVN Panamá reporta un plan de 500 millones para el Canal", (ID_TVN, "titulo")), CIFRA_NO_COINCIDE)


def test_un_conteo_de_reportes_coincide_con_el_campo_del_grupo() -> None:
    aceptada(afirmacion("A1", "hecho", "3 medios reportan el tema", (ID_GRP, "n_medios")))
    rechazada(afirmacion("A1", "hecho", "7 medios reportan el tema", (ID_GRP, "n_medios")), CIFRA_NO_COINCIDE)


# ============================================================================================ año y volátiles


def test_un_dato_oficial_anual_sin_anio_en_el_texto_se_rechaza() -> None:
    rechazada(afirmacion("A1", "hecho", "La inflación de Panamá fue de 2.9 % anual", (ID_IND, "valor")), IND_SIN_ANIO)


@pytest.mark.parametrize("palabra", ["actualmente", "hoy", "actual"])
def test_actualmente_hoy_y_actual_junto_a_un_dato_anual_se_rechazan(palabra: str) -> None:
    rechazada(afirmacion("A1", "hecho", f"La inflación {palabra} es de 2.9 % anual en 2023", (ID_IND, "valor")), IND_VOLATIL)


# ============================================================================================ tipos (D-41, D-18)


def test_un_hecho_apoyado_solo_en_un_titular_se_rechaza() -> None:
    rechazada(afirmacion("A1", "hecho", "Mulino anuncia nuevo plan para el Canal de Panamá", (ID_TVN, "titulo")), HECHO_NO_OFICIAL)
    rechazada(afirmacion("A1", "hecho", "Mulino anuncia nuevo plan", (ID_TVN, "titulo"), (ID_REUTERS, "titulo")), HECHO_NO_OFICIAL)


def test_un_hecho_sin_cita_se_rechaza() -> None:
    sin_cita = Afirmacion.model_construct(id="A1", tipo="hecho", texto="La inflación fue alta", citas=[], base=[])
    r = valida(sin_cita)
    assert "hecho_sin_cita" in reglas(r.rechazos) and not r.validas


def test_una_declaracion_lleva_atribucion_en_el_texto() -> None:
    rechazada(afirmacion("A1", "declaración", "Mulino anuncia nuevo plan para el Canal de Panamá", (ID_TVN, "titulo")), SIN_ATRIBUCION)
    aceptada(afirmacion("A1", "declaración", "TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá", (ID_TVN, "titulo")))
    aceptada(afirmacion("A1", "declaración", "Según TVN, Mulino anuncia nuevo plan para el Canal de Panamá", (ID_TVN, "titulo")))


def test_una_inferencia_sin_afirmaciones_base_se_rechaza() -> None:
    suelta = Afirmacion.model_construct(id="A1", tipo="inferencia", texto="El plan podría importar", citas=[], base=[])
    r = valida(suelta)
    assert INFERENCIA_SIN_BASE in reglas(r.rechazos) and not r.validas


def test_una_inferencia_con_una_cifra_nueva_se_rechaza() -> None:
    base = afirmacion("A1", "hecho", "La inflación de Panamá fue de 2.9 % anual en 2023", (ID_IND, "valor"))
    mala = afirmacion("A2", "inferencia", "La inflación subirá a 4 % por el plan", base=("A1",))
    r = valida(base, mala)
    assert [a.id for a in r.validas] == ["A1"] and CIFRA_NO_COINCIDE in reglas(r.rechazos)
    buena = afirmacion("A2", "inferencia", "Una inflación de 2.9 % pesa en el bolsillo", base=("A1",))
    assert [a.id for a in valida(base, buena).validas] == ["A1", "A2"]


def test_una_inferencia_con_un_nombre_nuevo_se_rechaza() -> None:
    base = afirmacion("A1", "declaración", "TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá", (ID_TVN, "titulo"))
    mala = afirmacion("A2", "inferencia", "El plan interesa a Juan Pérez", base=("A1",))
    r = valida(base, mala)
    assert NOMBRE_NUEVO in reglas(r.rechazos) and [a.id for a in r.validas] == ["A1"]


def test_una_inferencia_con_una_fecha_nueva_se_rechaza() -> None:
    base = afirmacion("A1", "declaración", "TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá", (ID_TVN, "titulo"))
    mala = afirmacion("A2", "inferencia", "El plan se discutirá el 3 de diciembre de 2027", base=("A1",))
    assert FECHA_NO_COINCIDE in reglas(valida(base, mala).rechazos)


def test_una_hipotesis_sin_marcador_condicional_se_rechaza() -> None:
    base = afirmacion("A1", "declaración", "TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá", (ID_TVN, "titulo"))
    r = valida(base, afirmacion("A2", "hipótesis", "El plan afecta los precios", base=("A1",)))
    assert HIPOTESIS_SIN_CONDICIONAL in reglas(r.rechazos)
    for marcador in ("podría afectar los precios", "es posible que afecte los precios", "afecta los precios, a verificar"):
        assert [a.id for a in valida(base, afirmacion("A2", "hipótesis", f"El plan {marcador}", base=("A1",))).validas] == ["A1", "A2"], marcador


def test_la_base_inexistente_arrastra_a_la_inferencia() -> None:
    r = valida(afirmacion("A2", "inferencia", "El plan podría importar", base=("A9",)))
    assert not r.validas and "base_invalida" in reglas(r.rechazos)


# ============================================================================================ D-45: comillas y fechas


def test_las_comillas_no_literales_se_rechazan_y_las_literales_se_aceptan() -> None:
    rechazada(afirmacion("A1", "declaración", 'Panamá América reporta que el ministro afirma "habrá menos retrasos" este lunes', (ID_CITA, "titulo")), COMILLAS_NO_LITERALES)
    aceptada(afirmacion("A1", "declaración", 'Panamá América reporta que el ministro afirma "no habrá más retrasos en la obra"', (ID_CITA, "titulo")))


def test_una_fecha_que_no_coincide_con_la_evidencia_se_rechaza() -> None:
    rechazada(afirmacion("A1", "declaración", "TVN Panamá reporta el 12 de octubre que Mulino anuncia nuevo plan", (ID_TVN, "titulo")), FECHA_NO_COINCIDE)
    rechazada(afirmacion("A1", "declaración", "TVN Panamá reporta en 2025 que Mulino anuncia nuevo plan", (ID_TVN, "titulo")), FECHA_NO_COINCIDE)


def test_una_fecha_que_coincide_con_la_evidencia_se_acepta() -> None:
    aceptada(afirmacion("A1", "declaración", "El 5 de octubre TVN Panamá reporta que Mulino anuncia nuevo plan", (ID_TVN, "titulo")))
    aceptada(afirmacion("A1", "declaración", "El 5 de octubre de 2026 TVN Panamá reporta que Mulino anuncia nuevo plan", (ID_TVN, "titulo")))


# ============================================================================================ D-68: causalidad y acusaciones


def test_causalidad_en_un_hecho_se_rechaza() -> None:
    rechazada(afirmacion("A1", "hecho", "La inflación de Panamá fue de 2.9 % anual en 2023 debido a los combustibles", (ID_IND, "valor")), CAUSALIDAD)


def test_causalidad_literal_del_titular_en_una_declaracion_atribuida_se_permite() -> None:
    aceptada(afirmacion("A1", "declaración", "La Prensa reporta que las inundaciones causaron pérdidas en Chiriquí", (ID_PRENSA, "titulo")))


def test_causalidad_que_el_titular_no_trae_se_rechaza_en_una_declaracion() -> None:
    rechazada(afirmacion("A1", "declaración", "La Prensa reporta que Mulino anunció el plan por culpa de la oposición", (ID_PRENSA, "titulo")), CAUSALIDAD)


def test_causalidad_en_una_inferencia_se_rechaza_y_en_una_hipotesis_condicional_se_permite() -> None:
    base = afirmacion("A1", "declaración", "La Prensa reporta que las inundaciones causaron pérdidas en Chiriquí", (ID_PRENSA, "titulo"))
    inf = afirmacion("A2", "inferencia", "Las pérdidas llegaron debido a la falta de drenajes", base=("A1",))
    assert CAUSALIDAD in reglas(valida(base, inf).rechazos)
    hip = afirmacion("A2", "hipótesis", "Las pérdidas podrían deberse a la falta de drenajes, debido a que falta verificar", base=("A1",))
    assert [a.id for a in valida(base, hip).validas] == ["A1", "A2"]


def test_una_acusacion_como_hecho_se_rechaza() -> None:
    rechazada(afirmacion("A1", "hecho", "Mulino robó fondos del Canal", (ID_GRP, "n_titulares")), ACUSACION)


def test_una_acusacion_como_inferencia_o_hipotesis_se_rechaza() -> None:
    base = afirmacion("A1", "declaración", "La Prensa reporta que la oposición llama corrupto a Mulino", (ID_PRENSA, "titulo"))
    assert ACUSACION in reglas(valida(base, afirmacion("A2", "inferencia", "Mulino es corrupto, por lo que importa", base=("A1",))).rechazos)
    assert ACUSACION in reglas(valida(base, afirmacion("A2", "hipótesis", "Mulino podría ser corrupto", base=("A1",))).rechazos)


def test_una_acusacion_atribuida_a_un_medio_y_literal_del_titular_se_permite() -> None:
    aceptada(afirmacion("A1", "declaración", "La Prensa reporta que la oposición llama corrupto a Mulino", (ID_PRENSA, "titulo")))


def test_una_acusacion_sin_atribucion_o_que_el_titular_no_trae_se_rechaza() -> None:
    rechazada(afirmacion("A1", "declaración", "Mulino es corrupto", (ID_PRENSA, "titulo")), ACUSACION)
    rechazada(afirmacion("A1", "declaración", "La Prensa reporta que Mulino robó dinero", (ID_PRENSA, "titulo")), ACUSACION)


# ============================================================================================ D-53, D-25, D-51: frases prohibidas


def test_una_frase_de_entrevista_inventada_se_rechaza_y_la_literal_de_un_titular_citado_se_permite() -> None:
    rechazada(afirmacion("A1", "declaración", "TVN Panamá reporta que Mulino habló en entrevista con TVN sobre el plan", (ID_TVN, "titulo")), "entrevistas")
    aceptada(afirmacion("A1", "declaración", "Telemetro reporta que un ministro dice en entrevista con Telemetro que habrá nuevo calendario", (ID_ENTREVISTA, "titulo")))


@pytest.mark.parametrize("frase", ["en entrevista con", "declaró a este medio", "consultado por", "en conversación con", "dijo a este medio"])
def test_cada_frase_de_entrevista_de_restricciones_se_rechaza(frase: str) -> None:
    rechazada(afirmacion("A1", "declaración", f"TVN Panamá reporta que Mulino habló {frase} el equipo sobre el plan", (ID_TVN, "titulo")), "entrevistas")


@pytest.mark.parametrize("frase", ["en estas imágenes", "como vemos", "las imágenes muestran", "en el video se ve", "como se aprecia en la foto"])
def test_las_referencias_a_imagenes_concretas_se_rechazan(frase: str) -> None:
    rechazada(afirmacion("A1", "declaración", f"TVN Panamá reporta que Mulino anuncia nuevo plan, {frase} el Canal", (ID_TVN, "titulo")), "imagenes")


@pytest.mark.parametrize(
    "frase",
    ["el artículo señala", "según la nota", "el reportaje detalla", "en el texto se indica", "de acuerdo con el artículo", "según el artículo"],
)
def test_las_frases_de_lectura_simulada_se_rechazan(frase: str) -> None:
    rechazada(afirmacion("A1", "declaración", f"TVN Panamá reporta que Mulino anuncia nuevo plan, {frase} del Canal", (ID_TVN, "titulo")), "lectura_simulada")


@pytest.mark.parametrize("frase", ["fuentes oficiales confirmaron", "fuentes cercanas", "los expertos"])
def test_un_detalle_sin_cita_se_rechaza(frase: str) -> None:
    rechazada(afirmacion("A1", "declaración", f"TVN Panamá reporta que Mulino anuncia nuevo plan; {frase} el monto", (ID_TVN, "titulo")), "detalle_sin_cita")


# ============================================================================================ secciones: límites (D-53)


def _brief(n: int) -> list:  # type: ignore[type-arg]
    return relleno(n)


def test_el_brief_pasa_en_el_limite_y_se_rechaza_si_lo_supera() -> None:
    ctx = ctx_con_base()
    assert not validar_seccion("brief", _brief(250), ctx)
    assert LIMITE_PALABRAS in reglas(validar_seccion("brief", _brief(251), ctx))


def test_el_titulo_admite_14_palabras_y_no_15() -> None:
    ctx = ctx_con_base()
    assert not validar_seccion("titulo", o("TVN reporta " + " ".join(["plan"] * 12), "A1"), ctx)
    assert LIMITE_PALABRAS in reglas(validar_seccion("titulo", o("TVN reporta " + " ".join(["plan"] * 13), "A1"), ctx))


def test_cada_titular_admite_14_palabras_y_la_cantidad_es_de_2_a_3() -> None:
    ctx = ctx_con_base()
    uno = o("TVN reporta nuevo plan", "A1")
    assert not validar_seccion("titulares", [uno, uno], ctx) and not validar_seccion("titulares", [uno, uno, uno], ctx)
    assert "cantidad" in reglas(validar_seccion("titulares", [uno], ctx)) and "cantidad" in reglas(validar_seccion("titulares", [uno] * 4, ctx))
    largo = o("TVN reporta " + " ".join(["plan"] * 13), "A1")
    assert LIMITE_PALABRAS in reglas(validar_seccion("titulares", [uno, largo], ctx))


def test_el_enfoque_es_de_1_a_2_oraciones_y_se_apoya_en_una_inferencia() -> None:
    ctx = ctx_con_base()
    una = o("El plan podría interesar a quien sigue los precios.", "A4")
    assert not validar_seccion("enfoque", [una], ctx) and not validar_seccion("enfoque", [una, una], ctx)
    assert "cantidad" in reglas(validar_seccion("enfoque", [una] * 3, ctx)) and "cantidad" in reglas(validar_seccion("enfoque", [], ctx))
    assert "enfoque_como_hecho" in reglas(validar_seccion("enfoque", [o("La inflación fue de 2.9 % anual en 2023.", "A2")], ctx))


def test_las_preguntas_son_exactamente_3_y_referencian_un_vacio() -> None:
    from src.esquemas import PreguntaInvestigacion

    ctx = ctx_con_base()
    q = lambda v: PreguntaInvestigacion(texto="¿Qué fuente oficial confirma el monto?", vacio=v)  # noqa: E731
    assert not validar_seccion("preguntas", [q("V1"), q("V2"), q("V3")], ctx)
    assert "cantidad" in reglas(validar_seccion("preguntas", [q("V1"), q("V2")], ctx))
    assert "cantidad" in reglas(validar_seccion("preguntas", [q("V1")] * 4, ctx))
    assert "pregunta_sin_vacio" in reglas(validar_seccion("preguntas", [q("V1"), q("V2"), q("V99")], ctx))


def test_el_resumen_web_admite_120_palabras_y_no_121() -> None:
    ctx = ctx_con_base()
    assert not validar_seccion("resumen_web", relleno(120), ctx)
    assert LIMITE_PALABRAS in reglas(validar_seccion("resumen_web", relleno(121), ctx))


def test_el_copy_admite_80_palabras_2_hashtags_y_ningun_emoji() -> None:
    ctx = ctx_con_base()
    assert not validar_seccion("copy_digital", relleno(77) + [o("tema #Canal #Panamá", "A3")], ctx)
    assert LIMITE_PALABRAS in reglas(validar_seccion("copy_digital", relleno(81), ctx))
    assert "copy_hashtags" in reglas(validar_seccion("copy_digital", [o("tema #Canal #Panamá #Plan", "A3")], ctx))
    assert "copy_emojis" in reglas(validar_seccion("copy_digital", [o("tema del día 🔥", "A3")], ctx))


@pytest.mark.parametrize("palabra", ["escándalo", "bombazo", "impactante", "alarmante", "increíble", "aterrador", "caos", "brutal", "explosivo", "devastador", "urgente"])
def test_el_copy_y_los_titulares_sin_palabras_sensacionalistas(palabra: str) -> None:
    ctx = ctx_con_base()
    assert "sensacionalistas" in reglas(validar_seccion("copy_digital", [o(f"Un {palabra} tema del día", "A3")], ctx))
    assert "sensacionalistas" in reglas(validar_seccion("titulo", o(f"TVN reporta {palabra} plan", "A1"), ctx))


def _guion(n: int, extra: list | None = None) -> list:  # type: ignore[type-arg]
    partes = ["entrada", "desarrollo", "cierre"]
    base = relleno(n)
    for i, x in enumerate(base):
        x.parte = partes[min(i * 3 // len(base), 2)]
    return base + (extra or [])


def test_el_guion_se_acepta_entre_110_y_150_palabras_y_se_rechaza_fuera() -> None:
    ctx = ctx_con_base()
    assert not validar_seccion("guion", _guion(110), ctx) and not validar_seccion("guion", _guion(150), ctx)
    assert LIMITE_PALABRAS in reglas(validar_seccion("guion", _guion(109), ctx))
    assert LIMITE_PALABRAS in reglas(validar_seccion("guion", _guion(151), ctx))


def test_el_marcador_visual_no_cuenta_en_el_guion() -> None:
    ctx = ctx_con_base()
    g = _guion(150)
    g.insert(2, o(MARCADOR, parte="entrada"))
    assert not validar_seccion("guion", g, ctx)


def test_el_guion_rechaza_una_referencia_visual_concreta() -> None:
    ctx = ctx_con_base()
    concreto = o("[VISUAL: tomas aéreas del Canal]", parte="desarrollo")
    g = _guion(120)
    g.insert(2, concreto)
    assert MARCADOR_VISUAL in reglas(validar_seccion("guion", g, ctx))
    como = relleno(1)[0]
    como.texto, como.parte = "Como vemos en estas imágenes el tráfico crece.", "desarrollo"
    h = _guion(120)
    h.insert(2, como)
    assert "imagenes" in reglas(validar_seccion("guion", h, ctx))


def test_el_marcador_visual_fuera_del_guion_se_rechaza() -> None:
    ctx = ctx_con_base()
    assert MARCADOR_VISUAL in reglas(validar_seccion("brief", [o(MARCADOR)], ctx))


def test_el_guion_tiene_entrada_desarrollo_y_cierre_en_orden() -> None:
    ctx = ctx_con_base()
    g = _guion(120)
    for x in g:
        x.parte = "desarrollo"
    assert "guion_estructura" in reglas(validar_seccion("guion", g, ctx))


# ============================================================================================ D-41: transiciones y atribución


def test_una_transicion_sin_cifras_ni_nombres_se_permite_y_una_con_cifra_se_rechaza() -> None:
    ctx = ctx_con_base()
    asi = relleno(5)
    assert not validar_seccion("brief", [*asi, o("Veamos qué dicen los datos.")], ctx)
    assert TRANSICION_NO_PERMITIDA in reglas(validar_seccion("brief", [*asi, o("Veamos los 3 datos clave.")], ctx))
    assert TRANSICION_NO_PERMITIDA in reglas(validar_seccion("brief", [*asi, o("Esto ocurrió el 5 de octubre.")], ctx))
    assert TRANSICION_NO_PERMITIDA in reglas(validar_seccion("brief", [*asi, o("Veamos qué dice Mulino al respecto.")], ctx))


def test_mas_transiciones_que_el_maximo_por_seccion_se_rechazan() -> None:
    ctx = ctx_con_base()
    t = lambda: o("Veamos qué dicen los datos.")  # noqa: E731
    assert not validar_seccion("brief", [*relleno(5), t()], ctx)
    assert EXCESO_TRANSICIONES in reglas(validar_seccion("brief", [*relleno(5), t(), t()], ctx))


def test_una_oracion_sin_cita_fuera_de_las_secciones_con_transicion_se_rechaza() -> None:
    ctx = ctx_con_base()
    assert "oracion_sin_afirmacion" in reglas(validar_seccion("copy_digital", [o("Veamos qué dicen los datos.")], ctx))


def test_un_titular_basado_en_una_declaracion_sin_atribucion_se_rechaza() -> None:
    ctx = ctx_con_base()
    assert TITULAR_SIN_ATRIBUCION in reglas(validar_seccion("titulo", o("Nuevo plan para el Canal de Panamá", "A1"), ctx))
    assert TITULAR_SIN_ATRIBUCION in reglas(validar_seccion("titulares", [o("Nuevo plan para el Canal de Panamá", "A1"), o("TVN reporta nuevo plan", "A1")], ctx))
    for t in ("TVN reporta nuevo plan para el Canal de Panamá", "Nuevo plan para el Canal, según TVN", "Reportan nuevo plan para el Canal"):
        assert not validar_seccion("titulo", o(t, "A1"), ctx), t


def test_el_titular_basado_en_un_hecho_no_pide_atribucion() -> None:
    assert not validar_seccion("titulo", o("Inflación de 2.9 % en 2023", "A2"), ctx_con_base())


# ============================================================================================ oraciones del cuerpo (revisión del PR #26)


def test_una_cifra_de_una_oracion_que_la_afirmacion_citada_no_trae_se_rechaza() -> None:
    ctx = ctx_con_base()
    assert CIFRA_NO_COINCIDE in reglas(validar_seccion("brief", [o("La inflación llegará a 15 % en 2027.", "A2")], ctx))
    assert not validar_seccion("brief", [o("La inflación fue de 2,9 % anual en 2023.", "A2")], ctx)


def test_un_dato_oficial_sin_anio_o_con_actual_se_rechaza_en_el_cuerpo() -> None:
    ctx = ctx_con_base()
    assert IND_SIN_ANIO in reglas(validar_seccion("brief", [o("La inflación es de 2.9 % anual.", "A2")], ctx))
    assert IND_VOLATIL in reglas(validar_seccion("brief", [o("La inflación actual fue de 2.9 % anual en 2023.", "A2")], ctx))


def test_un_nombre_que_las_afirmaciones_no_traen_se_rechaza_en_el_cuerpo() -> None:
    assert NOMBRE_NUEVO in reglas(validar_seccion("brief", [o("Según TVN, Juan Pérez anuncia el plan.", "A1")], ctx_con_base()))


def test_causalidad_y_acusacion_en_el_cuerpo_se_rechazan() -> None:
    ctx = ctx_con_base()
    assert CAUSALIDAD in reglas(validar_seccion("brief", [o("El plan avanza por culpa de la oposición.", "A3")], ctx))
    assert ACUSACION in reglas(validar_seccion("brief", [o("TVN reporta que Mulino es corrupto.", "A1")], ctx))


def test_una_declaracion_en_el_cuerpo_sin_atribucion_se_rechaza() -> None:
    ctx = ctx_con_base()
    assert SIN_ATRIBUCION in reglas(validar_seccion("brief", [o("Mulino anuncia nuevo plan para el Canal de Panamá.", "A1")], ctx))
    assert not validar_seccion("brief", [o("TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá.", "A1")], ctx)


def test_una_oracion_basada_en_una_hipotesis_se_redacta_en_condicional() -> None:
    ctx = ctx_con_base()
    assert HIPOTESIS_SIN_CONDICIONAL in reglas(validar_seccion("brief", [o("El plan afecta los precios.", "A5")], ctx))
    assert not validar_seccion("brief", [o("El plan podría afectar los precios.", "A5")], ctx)


def test_una_comilla_inventada_en_el_cuerpo_se_rechaza() -> None:
    ctx = ctx_con_base()
    assert COMILLAS_NO_LITERALES in reglas(validar_seccion("brief", [o('TVN reporta que "el plan es histórico".', "A1")], ctx))


def test_una_cita_a_una_afirmacion_que_no_existe_se_rechaza() -> None:
    assert "afirmacion_desconocida" in reglas(validar_seccion("brief", [o("Un tema.", "A99")], ctx_con_base()))


def test_una_fecha_de_una_oracion_que_la_evidencia_no_trae_se_rechaza() -> None:
    assert FECHA_NO_COINCIDE in reglas(validar_seccion("brief", [o("TVN Panamá reporta el 20 de octubre un nuevo plan.", "A1")], ctx_con_base()))


# ============================================================================================ contradicción abierta


def test_con_una_contradiccion_abierta_el_borrador_presenta_las_dos_versiones() -> None:
    from tests.validador_ayuda import afirmaciones_base, con_afirmaciones, salida

    f = ficha(contradicciones=contradiccion())
    ctx = con_afirmaciones(contexto(f), *afirmaciones_base(), salida("A6", "declaración", "La Prensa reporta que la oposición llama corrupto a Mulino", (ID_PRENSA, "titulo")))
    una = [o("TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá.", "A1")]
    assert CONTRADICCION_UNA_VERSION in reglas(validar_seccion("brief", una, ctx))
    ambas = [*una, o("La Prensa reporta que la oposición llama corrupto a Mulino.", "A6")]
    assert not validar_seccion("brief", ambas, ctx)


def test_una_contradiccion_cerrada_no_exige_las_dos_versiones() -> None:
    c = ContradiccionFicha(id_a=ID_TVN, id_b=ID_PRENSA, fragmento_a="nuevo plan", fragmento_b="corrupto", abierta=False)
    ctx = ctx_con_base(ficha(contradicciones=[c]))
    assert not validar_seccion("brief", [o("TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá.", "A1")], ctx)


# ============================================================================================ D-51: leyenda y lectura simulada


def test_una_salida_sin_leyenda_se_rechaza() -> None:
    assert LEYENDA in reglas(validar_leyenda("Texto del boletín sin leyenda", contexto()))


def test_la_leyenda_correcta_depende_de_si_se_uso_la_descripcion() -> None:
    sin = contexto(ficha(uso_descripcion=False))
    con = contexto(ficha(uso_descripcion=True))
    assert not validar_leyenda(f"Texto. {TXT_LEYENDA}", sin) and validar_leyenda(f"Texto. {TXT_LEYENDA}", con)
    assert not validar_leyenda(f"Texto. {LEYENDA_DESCRIPCION}", con) and validar_leyenda(f"Texto. {LEYENDA_DESCRIPCION}", sin)
    assert LEYENDA in reglas(validar_leyenda(f"{TXT_LEYENDA} {LEYENDA_DESCRIPCION}", sin))


def test_la_leyenda_no_suma_al_conteo_de_palabras() -> None:
    texto = " ".join(["tema"] * 10)
    assert contar_palabras(f"{texto} {TXT_LEYENDA}") == contar_palabras(texto) == 10
    assert contar_palabras(f"{texto} {LEYENDA_DESCRIPCION}") == 10
    ctx = ctx_con_base()
    assert not validar_seccion("brief", [o(f"{' '.join(['tema'] * 250)} {TXT_LEYENDA}", "A3")], ctx)


# ============================================================================================ banca: reglas por modalidad desde YAML


def test_las_reglas_de_banca_vienen_del_yaml() -> None:
    ctx = contexto(grupos=("comunes", "banca"))
    base = afirmacion("A1", "declaración", "La Prensa reporta que las inundaciones causaron pérdidas en Chiriquí", (ID_PRENSA, "titulo"))
    ok = valida(base, ctx=ctx)
    assert [a.id for a in ok.validas] == ["A1"], "una declaración puede citar literalmente «pérdidas»"
    inf = afirmacion("A2", "inferencia", "Habrá pérdidas en la cartera de los bancos", base=("A1",))
    assert "perdidas_en_inferencias" in reglas(valida(base, inf, ctx=ctx).rechazos)
    assert "recomendacion" in reglas(valida(afirmacion("A1", "declaración", "TVN Panamá reporta que Mulino anuncia nuevo plan; conviene invertir", (ID_TVN, "titulo")), ctx=ctx).rechazos)
    hip = afirmacion("A2", "hipótesis", "El plan podría ocurrir sin duda", base=("A1",))
    assert "certeza" in reglas(valida(base, hip, ctx=ctx).rechazos)


# ============================================================================================ banca: el boletín de entorno (E2-02, D-54)


def _ctx_boletin():  # type: ignore[no-untyped-def]
    """Contexto bancario con las afirmaciones del boletín ya validadas (A1 declaración con «pérdidas» literal, A2 hecho, A3 hipótesis, A4 inferencia)."""
    from tests.generacion_ayuda import AFIRMACIONES_BANCA, ficha_banca
    from tests.validador_ayuda import con_afirmaciones, salida

    ctx = contexto(ficha_banca(), grupos=("comunes", "banca"))
    afirmaciones = [
        salida(a["id"], a["tipo"], a["texto"], *[(c["id"], c["campo"]) for c in a["citas"]], base=tuple(a["base"]))
        for a in AFIRMACIONES_BANCA["afirmaciones"]
    ]
    return con_afirmaciones(ctx, *afirmaciones)


def test_una_observacion_basada_en_una_hipotesis_se_rechaza_y_la_de_un_hecho_o_declaracion_no() -> None:
    from src.validador import OBSERVACION_CON_HIPOTESIS

    ctx = _ctx_boletin()
    assert OBSERVACION_CON_HIPOTESIS in reglas(validar_seccion("observaciones", [o("Las lluvias en Chiriquí podrían afectar la actividad agrícola, a verificar.", "A3")], ctx))
    assert OBSERVACION_CON_HIPOTESIS in reglas(validar_seccion("observaciones", [o("La actividad agrícola podría ser un tema a seguir en el entorno económico.", "A4")], ctx))
    assert not validar_seccion("observaciones", [o("Según La Prensa, las lluvias causaron pérdidas en cultivos de Chiriquí.", "A1"), o("En 2023 la inflación anual de Panamá fue de 2.9 %.", "A2")], ctx)


def test_una_hipotesis_de_impacto_sin_condicional_se_rechaza() -> None:
    from src.validador import IMPACTO_SIN_CONDICIONAL

    ctx = _ctx_boletin()
    assert IMPACTO_SIN_CONDICIONAL in reglas(validar_seccion("hipotesis_impacto", [o("La actividad agrícola es un tema a seguir en el entorno económico.", "A4")], ctx))
    assert not validar_seccion("hipotesis_impacto", [o("La actividad agrícola podría ser un tema a seguir en el entorno económico.", "A4")], ctx)
    rechazada(afirmacion("A3", "hipótesis", "Las lluvias afectan la actividad agrícola", base=("A1",)), HIPOTESIS_SIN_CONDICIONAL, ctx=_ctx_boletin())


def test_una_hipotesis_de_impacto_basada_en_un_hecho_o_una_declaracion_se_rechaza() -> None:
    from src.validador import IMPACTO_COMO_HECHO

    ctx = _ctx_boletin()
    assert IMPACTO_COMO_HECHO in reglas(validar_seccion("hipotesis_impacto", [o("Según La Prensa, las lluvias podrían haber causado pérdidas.", "A1")], ctx))


def test_recomendamos_reducir_exposicion_se_rechaza_en_cualquier_tipo_y_bloque() -> None:
    ctx = _ctx_boletin()
    r_hip = reglas(validar_seccion("hipotesis_impacto", [o("Recomendamos reducir exposición si las lluvias podrían afectar la actividad agrícola.", "A3")], ctx))
    r_obs = reglas(validar_seccion("observaciones", [o("Según La Prensa, recomendamos reducir exposición en Chiriquí.", "A1")], ctx))
    assert "recomendacion" in r_hip and "recomendacion" in r_obs
    base = afirmacion("A1", "declaración", "La Prensa reporta que las lluvias causaron pérdidas en cultivos de Chiriquí", (ID_LLUVIAS_B, "titulo"))
    inf = afirmacion("A2", "inferencia", "Recomendamos reducir exposición al sector", base=("A1",))
    assert "recomendacion" in reglas(valida(base, inf, ctx=_ctx_boletin()).rechazos)


def test_podria_generar_perdidas_en_una_hipotesis_se_rechaza_aunque_el_titular_lo_diga() -> None:
    ctx = _ctx_boletin()
    assert "perdidas_en_inferencias" in reglas(validar_seccion("hipotesis_impacto", [o("Las lluvias podrían generar pérdidas en Chiriquí.", "A3")], ctx))
    base = afirmacion("A1", "declaración", "La Prensa reporta que las lluvias causaron pérdidas en cultivos de Chiriquí", (ID_LLUVIAS_B, "titulo"))
    hip = afirmacion("A2", "hipótesis", "Las lluvias podrían generar pérdidas en Chiriquí", base=("A1",))
    r = valida(base, hip, ctx=_ctx_boletin())
    assert [a.id for a in r.validas] == ["A1"] and "perdidas_en_inferencias" in reglas(r.rechazos)


def test_una_declaracion_literal_de_perdidas_se_permite_y_una_que_el_titular_no_trae_no() -> None:
    ctx = _ctx_boletin()
    assert not validar_seccion("observaciones", [o("Según La Prensa, las lluvias causaron pérdidas en cultivos de Chiriquí.", "A1")], ctx)
    aceptada(afirmacion("A1", "declaración", "Según La Prensa, las lluvias causaron pérdidas en cultivos de Chiriquí", (ID_LLUVIAS_B, "titulo")), ctx=_ctx_boletin())
    rechazada(afirmacion("A1", "declaración", "TVN Panamá reporta impagos en las exportaciones de banano", (ID_BANANO_B, "titulo")), "perdidas_en_inferencias", ctx=_ctx_boletin())
    assert "perdidas_en_inferencias" in reglas(validar_seccion("observaciones", [o("En 2023 la inflación anual de Panamá fue de 2.9 % y hubo morosidad.", "A2")], ctx))


def test_el_lenguaje_de_certeza_se_rechaza_en_las_hipotesis_de_impacto() -> None:
    ctx = _ctx_boletin()
    assert "certeza" in reglas(validar_seccion("hipotesis_impacto", [o("La actividad agrícola podría, sin duda, ser un tema a seguir en el entorno económico.", "A4")], ctx))
    rechazada(afirmacion("A3", "inferencia", "La actividad agrícola será inevitable tema del entorno", base=("A1",)), "certeza", ctx=_ctx_boletin())


def test_el_resumen_del_boletin_suma_ambos_bloques_contra_su_limite() -> None:
    from src.validador import validar_conjunto

    ctx = _ctx_boletin()
    maximo = ctx.salidas.banca.resumen_max_palabras
    obs = [o("Según La Prensa, las lluvias causaron pérdidas en " + " ".join(["cultivos"] * (maximo // 2)) + ".", "A1")]
    hip = [o("Las lluvias podrían afectar la actividad " + " ".join(["agrícola"] * (maximo // 2)) + ", a verificar.", "A3")]
    rechazos = validar_conjunto({"observaciones": obs, "hipotesis_impacto": hip}, ctx)
    assert {r.regla for r in rechazos} == {LIMITE_PALABRAS} and {r.seccion for r in rechazos} == {"observaciones", "hipotesis_impacto"}
    assert not validar_conjunto({"observaciones": obs}, ctx) and not validar_conjunto({"brief": obs}, ctx)


def test_las_preguntas_del_boletin_son_exactamente_las_de_salidas_yaml_con_su_vacio() -> None:
    from src.esquemas import PreguntaInvestigacion
    from src.validador import CANTIDAD, PREGUNTA_SIN_VACIO

    ctx = _ctx_boletin()
    tres = [PreguntaInvestigacion(texto=f"¿Pregunta {n}?", vacio=f"V{n}") for n in (1, 2, 3)]
    assert not validar_seccion("preguntas", tres, ctx)
    assert CANTIDAD in reglas(validar_seccion("preguntas", tres[:2], ctx))
    assert PREGUNTA_SIN_VACIO in reglas(validar_seccion("preguntas", [*tres[:2], PreguntaInvestigacion(texto="¿Otra?", vacio="V9")], ctx))


# ---- revisión independiente del PR #38 (X49, X50)


def test_x49_la_excepcion_del_titular_exige_el_fragmento_literal_y_no_solo_la_palabra() -> None:
    """Titular «Lluvias causaron pérdidas en cultivos de Chiriquí»: la palabra sola no basta; el fragmento que la rodea debe ser literal."""
    ctx = _ctx_boletin()
    inventadas = ["Según La Prensa, la banca podría sufrir pérdidas por las lluvias.", "Según La Prensa, los bancos registraron pérdidas por las lluvias."]
    for texto in inventadas:
        assert "perdidas_en_inferencias" in reglas(validar_seccion("observaciones", [o(texto, "A1")], ctx)), texto
        rechazada(afirmacion("A1", "declaración", texto.rstrip("."), (ID_LLUVIAS_B, "titulo")), "perdidas_en_inferencias", ctx=_ctx_boletin())
    literales = ["Según La Prensa, las lluvias causaron pérdidas en cultivos de Chiriquí.", "La Prensa reporta: «Lluvias causaron pérdidas en cultivos de Chiriquí»."]
    for texto in literales:
        assert not validar_seccion("observaciones", [o(texto, "A1")], ctx), texto


def test_x49_la_ventana_literal_viene_del_yaml() -> None:
    from src.configuracion import cargar_validador

    assert cargar_validador().listas["perdidas_en_inferencias"].ventana_literal >= 2


def test_x49_una_observacion_no_se_redacta_en_condicional() -> None:
    from src.validador import OBSERVACION_CONDICIONAL

    ctx = _ctx_boletin()
    assert OBSERVACION_CONDICIONAL in reglas(validar_seccion("observaciones", [o("Según La Prensa, las lluvias podrían haber afectado cultivos de Chiriquí.", "A1")], ctx))
    assert OBSERVACION_CONDICIONAL in reglas(validar_seccion("observaciones", [o("En 2023 la inflación anual de Panamá fue de 2.9 %, a verificar.", "A2")], ctx))
    assert not validar_seccion("observaciones", [o("En 2023 la inflación anual de Panamá fue de 2.9 %.", "A2")], ctx)


X50_LEXICO = ["riesgo crediticio", "riesgos crediticios", "riesgo de crédito", "solvencia", "insolvencia", "mora", "morosos", "morosas", "morosidad",
              "incumplimiento", "incumplimientos", "deterioro crediticio"]


@pytest.mark.parametrize("termino", X50_LEXICO)
def test_x50_lexico_crediticio_rechazado_en_hipotesis(termino: str) -> None:
    ctx = _ctx_boletin()
    texto = f"Las lluvias en Chiriquí podrían elevar la {termino} del sector agrícola, a verificar."
    assert "perdidas_en_inferencias" in reglas(validar_seccion("hipotesis_impacto", [o(texto, "A3")], ctx)), termino


X50_RECOMENDACION = ["Sugerimos reducir créditos al agro", "La entidad sugiere reducir créditos al agro", "Los analistas sugieren reducir créditos al agro",
                     "Los bancos deberían limitar préstamos al agro", "Las entidades deberían reducir créditos al agro", "Deberían aumentar las garantías del agro",
                     "Es aconsejable recortar el crédito al agro", "Conviene recortar el crédito al agro", "Se recomienda recortar el crédito al agro"]


@pytest.mark.parametrize("texto", X50_RECOMENDACION)
def test_x50_formas_de_recomendacion_rechazadas(texto: str) -> None:
    ctx = _ctx_boletin()
    assert "recomendacion" in reglas(validar_seccion("hipotesis_impacto", [o(f"{texto} si las lluvias podrían afectar la actividad agrícola.", "A3")], ctx)), texto


X50_CERTEZA = ["A verificar: la actividad agrícola caerá con seguridad.", "Es seguro que la actividad agrícola caerá, a verificar.",
               "Sin lugar a dudas la actividad agrícola podría caer.", "De seguro la actividad agrícola podría caer.",
               "La actividad agrícola podría caer, y caerá.", "Es posible que la actividad agrícola bajará."]


@pytest.mark.parametrize("texto", X50_CERTEZA)
def test_x50_la_certeza_y_el_futuro_asertivo_se_rechazan_aunque_haya_un_marcador_condicional(texto: str) -> None:
    ctx = _ctx_boletin()
    r = reglas(validar_seccion("hipotesis_impacto", [o(texto, "A3")], ctx))
    assert r & {"certeza", "futuro_asertivo"}, (texto, r)


def test_x50_la_hipotesis_condicional_sin_certeza_sigue_valida() -> None:
    ctx = _ctx_boletin()
    assert not validar_seccion("hipotesis_impacto", [o("Las lluvias en Chiriquí podrían afectar la actividad agrícola, a verificar.", "A3")], ctx)


def test_cada_lista_de_restricciones_tiene_su_regla_en_el_yaml_del_validador() -> None:
    from src.configuracion import cargar_restricciones, cargar_validador

    nombres = {n for g in cargar_restricciones().grupos.values() for n in g}
    assert nombres <= set(cargar_validador().listas)


# ============================================================================================ falsos positivos hallados en la prueba real


def test_una_oracion_solo_de_hashtags_no_pide_atribucion() -> None:
    ctx = ctx_con_base()
    assert not validar_seccion("copy_digital", [o("TVN Panamá reporta un nuevo plan para el Canal.", "A1"), o("#Canal #Panamá", "A1")], ctx)


def test_una_oracion_que_abre_con_un_marcador_de_atribucion_no_es_un_nombre_nuevo() -> None:
    ctx = ctx_con_base()
    assert not validar_seccion("titulo", o("Según TVN Panamá, Mulino anuncia nuevo plan", "A1"), ctx)


def test_una_oracion_que_resume_varios_anios_lleva_al_menos_uno() -> None:
    from tests.validador_ayuda import ID_IND_DECIMAL, con_afirmaciones, contexto, salida

    ctx = con_afirmaciones(
        contexto(),
        salida("A1", "hecho", "La inflación fue de 2.9 % anual en 2023 y el crecimiento de 1.5 % en 2022", (ID_IND, "valor"), (ID_IND_DECIMAL, "valor")),
    )
    assert not validar_seccion("brief", [o("La inflación fue de 2.9 % anual en 2023.", "A1")], ctx)
    assert IND_SIN_ANIO in reglas(validar_seccion("brief", [o("La inflación fue de 2.9 % anual.", "A1")], ctx))


# ---- X57 (D-107): la excepción del titular literal no cubre términos del sector financiero que el titular no trae


def _ctx_boletin_con_titular(titular: str):  # type: ignore[no-untyped-def]
    from src.generacion import RegistroEvidencia
    from tests.generacion_ayuda import ficha_banca

    base = ficha_banca()
    registros = [RegistroEvidencia(id=r.id, idioma=r.idioma, campos={"titulo": titular} if r.id == ID_LLUVIAS_B else r.campos, contexto=r.contexto) for r in base.registros]
    return contexto(ficha_banca(registros=registros), grupos=("comunes", "banca"))


SECTOR_FINANCIERO_AJENO = "sector_financiero_ajeno"
CASOS_X57 = [  # los tres que la segunda revisión del PR #38 mostró que pasaban
    "Según La Prensa, las lluvias causaron pérdidas en cultivos y en la banca",
    "Según La Prensa, para la banca las lluvias causaron pérdidas en cultivos de Chiriquí",
    "La Prensa reporta que bancos temen que lluvias causaron pérdidas en cultivos",
]


@pytest.mark.parametrize("texto", CASOS_X57)
def test_x57_un_termino_financiero_fuera_del_titular_invalida_la_excepcion_literal(texto: str) -> None:
    rechazada(afirmacion("A1", "declaración", texto, (ID_LLUVIAS_B, "titulo")), SECTOR_FINANCIERO_AJENO, ctx=_ctx_boletin())


@pytest.mark.parametrize("texto", CASOS_X57)
def test_x57_las_observaciones_del_boletin_tambien_lo_rechazan(texto: str) -> None:
    assert SECTOR_FINANCIERO_AJENO in reglas(validar_seccion("observaciones", [o(texto + ".", "A1")], _ctx_boletin()))


def test_x57_el_rechazo_es_tipado_con_regla_motivo_y_fragmento() -> None:
    r = valida(afirmacion("A1", "declaración", CASOS_X57[0], (ID_LLUVIAS_B, "titulo")), ctx=_ctx_boletin())
    (x,) = [x for x in r.rechazos if x.regla == SECTOR_FINANCIERO_AJENO]
    assert x.fragmento == "banca" and "banca" in x.motivo


def test_x57_si_el_termino_financiero_esta_en_el_titular_la_excepcion_sigue_valiendo() -> None:
    titular = "Bancos de Chiriquí reportan pérdidas en créditos agrícolas por lluvias"
    ctx = _ctx_boletin_con_titular(titular)
    aceptada(afirmacion("A1", "declaración", "Según La Prensa, bancos de Chiriquí reportan pérdidas en créditos agrícolas por lluvias", (ID_LLUVIAS_B, "titulo")), ctx=ctx)
    # y solo los términos que el titular trae: «cartera» no está
    rechazada(
        afirmacion("A1", "declaración", "Según La Prensa, bancos de Chiriquí reportan pérdidas en créditos agrícolas por lluvias y en la cartera", (ID_LLUVIAS_B, "titulo")),
        SECTOR_FINANCIERO_AJENO, ctx=ctx,
    )


def test_x57_la_comparacion_no_distingue_mayusculas_ni_tildes() -> None:
    from src.validador import plano, terminos_financieros_ajenos

    lista = ["crédito", "créditos", "banca", "entidades financieras"]
    citado = plano("Lluvias dejan pérdidas en CRÉDITOS agrícolas de Chiriquí")
    assert terminos_financieros_ajenos(plano("Según La Prensa, los creditos agrícolas sufrieron pérdidas"), citado, lista) == []
    assert terminos_financieros_ajenos(plano("Según La Prensa, los CRÉDITOS y la BANCA sufrieron pérdidas"), citado, lista) == ["banca"]
    assert terminos_financieros_ajenos(plano("las Entidades Financieras sufrieron pérdidas"), citado, lista) == ["entidades financieras"]
    assert terminos_financieros_ajenos(plano("el bancal sufrió pérdidas"), citado, lista) == []  # palabra completa


def test_x57_la_lista_y_la_marca_viven_en_el_yaml() -> None:
    from src.configuracion import cargar_validador

    v = cargar_validador()
    assert {"banca", "banco", "bancos", "bancario", "crédito", "cartera", "entidades financieras", "sistema financiero"} <= set(v.sector_financiero)
    assert v.listas["perdidas_en_inferencias"].rechaza_sector_financiero_ajeno
