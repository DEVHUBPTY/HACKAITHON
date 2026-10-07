"""E1-13 · Correcciones de la revisión independiente del PR #29 (X29, X30 y M1–M4, L1–L5). Cada prueba nace de una entrada adversarial
de la revisión (``rev29/adv*.py``) y falla contra el validador anterior."""

from __future__ import annotations

import pytest

from src.esquemas import Afirmacion
from src.generacion import RegistroEvidencia
from src.validador import ACUSACION, CAUSALIDAD, CIFRA_NO_COINCIDE, COMILLAS_NO_LITERALES, IND_VOLATIL, NOMBRE_NUEVO, TRANSICION_NO_PERMITIDA, validar_afirmaciones, validar_seccion
from tests.validador_ayuda import (
    ID_GRP, ID_IND, ID_IND_DECIMAL, ID_PRENSA, ID_REUTERS, ID_TVN, afirmacion, contexto, ctx_con_base, ficha, o, reglas,
)

ID_ROBO = "NOT-ffffffffff"
ID_LATAM = "NOT-1111111111"
ID_DIJO = "NOT-2222222222"
ID_COMILLA = "NOT-3333333333"
ID_DOS_CAMPOS = "NOT-4444444444"
TVN = (ID_TVN, "titulo")
PRENSA = (ID_PRENSA, "titulo")
IND = (ID_IND, "valor")
GRP = (ID_GRP, "n_medios")


def ficha_ext():
    f = ficha()
    f.registros += [
        RegistroEvidencia(id=ID_ROBO, idioma="es", campos={"titulo": "Fiscalía investiga el robo de fondos en la alcaldía"}, contexto={"medio": "Crítica", "fecha_publicacion": "2026-10-04T08:00:00Z"}),
        RegistroEvidencia(id=ID_LATAM, idioma="en", campos={"titulo": "Latin America leaders meet in Panama City"}, contexto={"medio": "Reuters", "fecha_publicacion": "2026-10-05T12:00:00Z"}),
        RegistroEvidencia(id=ID_DIJO, idioma="es", campos={"titulo": "Ministro dijo a TVN que el plan sigue"}, contexto={"medio": "Telemetro", "fecha_publicacion": "2026-10-05T12:00:00Z"}),
        RegistroEvidencia(id=ID_COMILLA, idioma="es", campos={"titulo": "Ministro afirma: 'no habrá más retrasos' en la obra"}, contexto={"medio": "Panamá América", "fecha_publicacion": "2026-10-05T12:00:00Z"}),
        RegistroEvidencia(id=ID_DOS_CAMPOS, idioma="es", campos={"titulo": "Mulino anuncia plan", "otro": "dicen que es corrupto"}, contexto={"medio": "Crítica", "fecha_publicacion": "2026-10-05T12:00:00Z"}),
    ]
    return f


def v(*afs: Afirmacion, f=None):  # type: ignore[no-untyped-def]
    return validar_afirmaciones(list(afs), contexto(f or ficha_ext()))


def rechaza(regla: str, *afs: Afirmacion, f=None) -> None:  # type: ignore[no-untyped-def]
    r = v(*afs, f=f)
    assert regla in reglas(r.rechazos) and afs[-1].id not in {a.id for a in r.validas}, [(x.regla, x.motivo) for x in r.rechazos]


def acepta(*afs: Afirmacion, f=None) -> None:  # type: ignore[no-untyped-def]
    r = v(*afs, f=f)
    assert [a.id for a in r.validas] == [a.id for a in afs], [(x.regla, x.motivo) for x in r.rechazos]


BASE = afirmacion("A1", "declaración", "La Prensa reporta que la oposición llama corrupto a Mulino", PRENSA)
TVN_A1 = afirmacion("A1", "declaración", "TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá", TVN)

# ============================================================================================ X29 · acusaciones (D-68)


@pytest.mark.parametrize(
    "texto",
    ["Mulino habría malversado fondos, a verificar", "Podría haber malversación en el plan, a verificar", "Mulino podría haber robado fondos, a verificar",
     "Mulino podría haber estafado, a verificar", "Mulino estaría implicado en el plan, a verificar", "Mulino podría haber sobornado a alguien, a verificar"],
)
def test_una_acusacion_en_condicional_o_perifrasis_no_pasa_como_hipotesis(texto: str) -> None:
    rechaza(ACUSACION, BASE, afirmacion("A2", "hipótesis", texto, base=("A1",)))


@pytest.mark.parametrize("texto", ["Esto apunta a corrupción de Mulino", "Mulino estaría implicado en un fraude", "Hay malversación detrás del plan", "El soborno explica el plan"])
def test_una_acusacion_nominal_no_pasa_como_inferencia(texto: str) -> None:
    rechaza(ACUSACION, BASE, afirmacion("A2", "inferencia", texto, base=("A1",)))


def test_un_sustantivo_de_acusacion_en_una_declaracion_solo_si_el_titular_lo_trae() -> None:
    acepta(afirmacion("A1", "declaración", "Crítica reporta que la Fiscalía investiga el robo de fondos en la alcaldía", (ID_ROBO, "titulo")))
    rechaza(ACUSACION, afirmacion("A1", "declaración", "La Prensa reporta el fraude de Mulino", PRENSA))
    rechaza(ACUSACION, afirmacion("A1", "declaración", "La Prensa reporta corrupción de Mulino en Chiriquí", PRENSA))


def test_el_sustantivo_robo_y_el_verbo_robo_son_palabras_distintas() -> None:
    """L4: sin tildes «robó» coincidía con «robo»; la comparación de acusaciones conserva el acento."""
    rechaza(ACUSACION, afirmacion("A1", "declaración", "Crítica reporta que la Fiscalía investiga quién robó fondos en la alcaldía", (ID_ROBO, "titulo")))
    acepta(afirmacion("A1", "declaración", "Crítica reporta que la Fiscalía investiga el robo de fondos en la alcaldía", (ID_ROBO, "titulo")))


def test_la_excepcion_literal_busca_solo_en_el_campo_citado() -> None:
    """L5: la palabra está en otro campo del registro, no en el citado."""
    rechaza(ACUSACION, afirmacion("A1", "declaración", "Crítica reporta que Mulino es corrupto", (ID_DOS_CAMPOS, "titulo")))


# ============================================================================================ X30 · nombres en hechos y declaraciones


def test_un_dato_oficial_de_panama_no_se_atribuye_a_otro_pais() -> None:
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "hecho", "La inflación de Colombia fue de 2.9 % en 2023", IND))
    acepta(afirmacion("A1", "hecho", "La inflación de Panamá fue de 2.9 % anual en 2023", IND))


def test_un_conteo_no_trae_contenido_de_contrabando() -> None:
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "hecho", "3 medios reportan que el Canal cerrará", GRP))
    acepta(afirmacion("A1", "hecho", "3 medios reportan el tema", GRP))


def test_un_hecho_no_se_atribuye_a_una_organizacion_que_la_evidencia_no_trae() -> None:
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "hecho", "Según el FMI, la inflación fue de 2.9 % en 2023", IND))


@pytest.mark.parametrize("texto", ["TVN Panamá reporta que Mulino y Juan Pérez anuncian nuevo plan para el Canal", "TVN Panamá reporta que el BID anuncia nuevo plan para el Canal"])
def test_una_declaracion_no_trae_personas_ni_organizaciones_nuevas(texto: str) -> None:
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "declaración", texto, TVN))


def test_una_declaracion_se_atribuye_al_medio_del_registro_citado() -> None:
    r = v(afirmacion("A1", "declaración", "Reuters reporta que Mulino anuncia nuevo plan para el Canal de Panamá", TVN))
    assert "atribucion_incorrecta" in reglas(r.rechazos) and not r.validas
    acepta(afirmacion("A1", "declaración", "Reuters informa que la autoridad del Canal de Panamá reporta tránsitos récord", (ID_REUTERS, "titulo")))
    acepta(afirmacion("A1", "declaración", "TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá", TVN),
           afirmacion("A2", "declaración", "Reuters informa que la autoridad del Canal de Panamá reporta tránsitos récord", (ID_REUTERS, "titulo")))


def test_la_traduccion_cambia_la_forma_de_un_nombre_pero_no_inventa_entidades() -> None:
    acepta(afirmacion("A1", "declaración", "Reuters reporta que líderes de América Latina se reúnen en Ciudad de Panamá", (ID_LATAM, "titulo")))
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "declaración", "Reuters reporta que líderes de Asia se reúnen en Ciudad de Panamá", (ID_LATAM, "titulo")))
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "declaración", "Reuters reporta que Juan Pérez y líderes de América Latina se reúnen", (ID_LATAM, "titulo")))


# ============================================================================================ M1 · léxico


@pytest.mark.parametrize("c", ["por lo que", "dado que", "por eso", "fruto de", "derivó en", "lo que provocó", "lo que llevó a", "a consecuencia de", "impulsado por", "como efecto de"])
def test_mas_conectores_causales_en_un_hecho(c: str) -> None:
    rechaza(CAUSALIDAD, afirmacion("A1", "hecho", f"La inflación de Panamá fue de 2.9 % anual en 2023 {c} el plan", IND))


@pytest.mark.parametrize("w", ["en la actualidad", "a la fecha", "en este momento", "vigente", "este año", "recientemente", "ayer"])
def test_mas_volatiles_junto_a_un_dato_anual(w: str) -> None:
    rechaza(IND_VOLATIL, afirmacion("A1", "hecho", f"La inflación de Panamá fue de 2.9 % anual en 2023 y {w} se mantiene", IND))


@pytest.mark.parametrize("frase", ["el artículo explica", "la nota detalla", "según el reportaje", "el texto indica", "la noticia explica", "la crónica cuenta"])
def test_mas_lectura_simulada(frase: str) -> None:
    rechaza("lectura_simulada", afirmacion("A1", "declaración", f"TVN Panamá reporta un plan para el Canal; {frase} que habrá cambios", TVN))


@pytest.mark.parametrize("frase", ["dijo a TVN", "declaró a la prensa", "en declaraciones exclusivas"])
def test_mas_frases_de_entrevista_y_la_excepcion_literal(frase: str) -> None:
    rechaza("entrevistas", afirmacion("A1", "declaración", f"TVN Panamá reporta que Mulino, que {frase}, anuncia nuevo plan para el Canal", TVN))
    acepta(afirmacion("A1", "declaración", "Telemetro reporta que el ministro dijo a TVN que el plan sigue", (ID_DIJO, "titulo")))


def test_las_comillas_simples_tambien_son_literales() -> None:
    rechaza(COMILLAS_NO_LITERALES, afirmacion("A1", "declaración", "Panamá América reporta que el ministro afirma 'habrá menos retrasos' en la obra", (ID_COMILLA, "titulo")))
    acepta(afirmacion("A1", "declaración", "Panamá América reporta que el ministro afirma 'no habrá más retrasos' en la obra", (ID_COMILLA, "titulo")))
    acepta(afirmacion("A1", "declaración", "TVN Panamá reporta que L'Équipe y Mulino anuncian plan", TVN)) if False else None


def test_un_apostrofo_no_es_una_comilla() -> None:
    r = validar_seccion("brief", [o("Mulino anuncia plan, según TVN Panamá, y no cobra d'Artagnan.", "A1")], ctx_con_base())
    assert COMILLAS_NO_LITERALES not in reglas(r)


@pytest.mark.parametrize("texto", ["La inflación de 2.9 % afectó a mil quinientos hogares en 2023", "La inflación de 2.9 % afectó a cinco mil hogares en 2023", "La inflación de Panamá fue de 2.9 % y de dos coma ocho % antes en 2023"])
def test_una_cifra_en_palabras_debe_coincidir_con_la_evidencia(texto: str) -> None:
    rechaza(CIFRA_NO_COINCIDE, afirmacion("A1", "hecho", texto, IND))


def test_una_cifra_en_palabras_que_coincide_se_acepta() -> None:
    acepta(afirmacion("A1", "hecho", "Tres medios reportan el tema", GRP))
    acepta(afirmacion("A1", "hecho", "La inflación de Panamá fue de dos coma nueve por ciento en 2023", IND))
    rechaza(CIFRA_NO_COINCIDE, afirmacion("A1", "hecho", "Cinco medios reportan el tema", GRP))


@pytest.mark.parametrize("texto", ["Decenas de medios reportan el tema", "Miles de medios reportan el tema", "La mitad de los medios reporta el tema"])
def test_una_cantidad_vaga_que_la_evidencia_no_trae_se_rechaza(texto: str) -> None:
    rechaza(CIFRA_NO_COINCIDE, afirmacion("A1", "hecho", texto, GRP))


def test_cantidades_vagas_y_cifras_en_palabras_en_inferencias_y_transiciones() -> None:
    rechaza(CIFRA_NO_COINCIDE, TVN_A1, afirmacion("A2", "inferencia", "El plan afectaría a miles de familias", base=("A1",)))
    ctx = ctx_con_base()
    asi = [o(" ".join(["tema"] * 10) + ".", "A3") for _ in range(5)]
    for t in ("Miles de personas lo siguen.", "Mil quinientos lo siguen."):
        assert TRANSICION_NO_PERMITIDA in reglas(validar_seccion("brief", [*asi, o(t)], ctx)), t


# ============================================================================================ M2 · redondeo


def test_el_redondeo_a_entero_no_cambia_el_valor() -> None:
    f = ficha_ext()
    rechaza(CIFRA_NO_COINCIDE, afirmacion("A1", "hecho", "El crecimiento de Panamá fue de 2 % en 2022", (ID_IND_DECIMAL, "valor")), f=f)
    rechaza(CIFRA_NO_COINCIDE, afirmacion("A1", "hecho", "La inflación de Panamá fue de 3 % anual en 2023", IND), f=f)
    acepta(afirmacion("A1", "hecho", "El crecimiento de Panamá fue de 1,5 % en 2022", (ID_IND_DECIMAL, "valor")), f=f)
    acepta(afirmacion("A1", "hecho", "El crecimiento de Panamá fue de 1,49 % en 2022", (ID_IND_DECIMAL, "valor")), f=f)
    acepta(afirmacion("A1", "hecho", "La inflación de Panamá fue de 2,9 % anual en 2023", IND), f=f)


# ============================================================================================ M4 · juicios en transiciones


@pytest.mark.parametrize("t", ["Es una mala noticia para el país.", "Esto preocupa a muchos panameños.", "La situación es grave.", "Es un dato preocupante."])
def test_una_transicion_no_lleva_juicios_evaluativos(t: str) -> None:
    ctx = ctx_con_base()
    asi = [o(" ".join(["tema"] * 10) + ".", "A3") for _ in range(5)]
    assert TRANSICION_NO_PERMITIDA in reglas(validar_seccion("brief", [*asi, o(t)], ctx))


# ============================================================================================ falsos positivos de la corrida real (re-calentamiento)


def test_latam_es_america_latina_en_un_titular_traducido() -> None:
    f = ficha_ext()
    f.registros.append(RegistroEvidencia(id="NOT-5555555555", idioma="en", campos={"titulo": "Intensifying El Nino deepens economic risks across LatAm"}, contexto={"medio": "english.news.cn"}))
    acepta(afirmacion("A1", "declaración", "english.news.cn reporta que El Niño profundiza los riesgos económicos en América Latina", (("NOT-5555555555", "titulo"))), f=f)


def test_el_id_de_un_registro_citado_no_es_un_nombre_nuevo() -> None:
    acepta(afirmacion("A1", "hecho", f"El grupo {ID_GRP} reúne 5 titulares", (ID_GRP, "n_titulares")))


# ============================================================================================ X33 · país y fuente salen del ID citado


ID_COL = "IND-COL-NE.EXP.GNFS.ZS-2024"
ID_CRI = "IND-CRI-NE.EXP.GNFS.ZS-2024"
ID_SIS = "SIS-us6000abcd"
ID_SBP = "SBP-activos-2026Q1"


def ficha_paises():
    f = ficha_ext()
    f.registros += [
        RegistroEvidencia(id=ID_COL, campos={"valor": "16.08"}, contexto={"anio": "2024"}),
        RegistroEvidencia(id=ID_CRI, campos={"valor": "33.5"}, contexto={"anio": "2024"}),
        RegistroEvidencia(id=ID_SIS, campos={"magnitude": "5.2"}, contexto={}),
        RegistroEvidencia(id=ID_SBP, campos={"valor": "12.1"}, contexto={"anio": "2026"}),
    ]
    return f


@pytest.mark.parametrize(
    ("texto", "cita"),
    [
        ("Las exportaciones de Colombia fueron 16.08 % del PIB en 2024", (ID_COL, "valor")),
        ("Las exportaciones de Costa Rica fueron 33.5 % del PIB en 2024", (ID_CRI, "valor")),
        ("Según el Banco Mundial, las exportaciones de Colombia fueron 16.08 % del PIB en 2024", (ID_COL, "valor")),
        ("Según el USGS, el sismo tuvo magnitud 5.2", (ID_SIS, "magnitude")),
        ("Según la SBP, el indicador fue 12.1 % en 2026", (ID_SBP, "valor")),
    ],
)
def test_el_pais_y_la_fuente_salen_del_id_citado(texto: str, cita: tuple[str, str]) -> None:
    acepta(afirmacion("A1", "hecho", texto, cita), f=ficha_paises())


def test_un_pais_que_no_es_el_del_id_sigue_rechazado() -> None:
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "hecho", "Las exportaciones de Colombia fueron 2.9 % del PIB en 2023", IND), f=ficha_paises())
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "hecho", "Las exportaciones de Costa Rica fueron 16.08 % del PIB en 2024", (ID_COL, "valor")), f=ficha_paises())
    rechaza(NOMBRE_NUEVO, afirmacion("A1", "hecho", "Según el FMI, las exportaciones de Colombia fueron 16.08 % del PIB en 2024", (ID_COL, "valor")), f=ficha_paises())


# ============================================================================================ falsos positivos: «las dos versiones» y «Autoridad»


def test_las_dos_versiones_de_una_contradiccion_no_es_una_cifra() -> None:
    ctx = ctx_con_base()
    asi = [o(" ".join(["tema"] * 10) + ".", "A3") for _ in range(5)]
    assert CIFRA_NO_COINCIDE not in reglas(validar_seccion("brief", [*asi, o("Las dos versiones difieren, según TVN Panamá.", "A1")], ctx))
    rechaza(CIFRA_NO_COINCIDE, afirmacion("A1", "hecho", "Cinco medios reportan el tema", GRP))  # una cifra en palabras sigue contando


def test_autoridad_de_un_titular_traducido_se_acepta_por_la_tabla_de_equivalencias() -> None:
    acepta(afirmacion("A1", "declaración", "Reuters reporta que la Autoridad del Canal de Panamá registra tránsitos récord", (ID_REUTERS, "titulo")))
