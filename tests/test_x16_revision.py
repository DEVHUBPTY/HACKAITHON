"""X16 · Observaciones de la revisión independiente del PR #16 (E1-11)."""

import pytest

from src.consulta import validar_citas
from tests.consulta_fixture import crear_consultor


@pytest.fixture
def consultor(tmp_path):
    return crear_consultor(tmp_path)[0]


@pytest.mark.parametrize(
    "pregunta",
    [
        "¿Cuál fue el desempleo juvenil de Panamá en 2024?",
        "¿Cuál fue el desempleo de las mujeres en Panamá en 2024?",
        "¿Cuál fue el desempleo en la provincia de Colón en 2024?",
        "¿Cuál fue el desempleo en Darién en 2024?",
        "¿Cuál fue el desempleo de la población indígena en 2024?",
    ],
)
def test_x16_un_calificador_que_el_indicador_no_tiene_abstiene_y_ofrece_la_cifra_nacional(consultor, pregunta) -> None:
    r = consultor.responder(pregunta)
    assert r.abstiene and r.motivo == "calificador_no_disponible"
    assert r.afirmaciones == []                              # la cifra nacional no se presenta como la pedida
    assert [c.id for a in r.ultimo_dato_disponible for c in a.citas] == ["IND-PAN-SL.UEM.TOTL.ZS-2024"]
    assert r.falta


def test_x16_el_pib_en_nivel_no_es_el_crecimiento_del_pib(consultor) -> None:
    r = consultor.responder("¿Cuál fue el PIB de Panamá en 2010?")
    assert r.abstiene and r.motivo == "indicador_no_disponible" and r.afirmaciones == []
    assert [c.id for a in r.ultimo_dato_disponible for c in a.citas] == ["IND-PAN-NY.GDP.MKTP.KD.ZG-2010"]
    assert "crecimiento" in r.mensaje


def test_x16_el_crecimiento_del_pib_sigue_respondiendose(consultor) -> None:
    r = consultor.responder("¿Cuánto creció el PIB de Panamá en 2024?")
    assert not r.abstiene and r.afirmaciones[0].citas[0].id == "IND-PAN-NY.GDP.MKTP.KD.ZG-2024"


@pytest.mark.parametrize("pregunta", ["¿Se reportaron otros casos de dengue en Chiriquí?", "¿Qué dijo el periodista de TVN sobre el Canal?"])
def test_x16_la_regla_de_autoria_no_rechaza_preguntas_legitimas(consultor, pregunta) -> None:
    assert not consultor.responder(pregunta).motivo.startswith("regla:autoria")


@pytest.mark.parametrize(
    "pregunta",
    ["¿Qué otros casos judiciales tiene la persona aprehendida?", "¿Quién escribió la nota del Canal?", "¿Quién es el autor de la nota?"],
)
def test_x16_la_regla_de_autoria_sigue_rechazando_autoria_y_perfiles(consultor, pregunta) -> None:
    assert consultor.responder(pregunta).motivo.startswith("regla:autoria")


def test_x16_la_afirmacion_cita_tambien_medio_y_fecha_y_cita_el_titular_original_literal(consultor) -> None:
    a = consultor.responder("¿Qué medios reportaron el presupuesto del Canal de Panamá para 2027?").afirmaciones[0]
    assert {c.campo for c in a.citas} == {"titulo_original", "medio", "fecha_publicacion"}
    assert "«Canal de Panamá aprueba presupuesto para 2027 - Panamá América»" in a.texto
    assert validar_citas([a], consultor.indice.corpus) == []


def test_x16_el_valor_se_muestra_con_decimales_configurados_y_la_cita_conserva_el_crudo(consultor) -> None:
    a = consultor.responder("¿Cuál fue el desempleo de Panamá en 2024?").afirmaciones[0]
    assert "8.40 %" in a.texto
    assert consultor.indice.corpus.por_id[a.citas[0].id].datos["valor"] == 8.4
    pob = consultor.responder("¿Cuál fue la población de Panamá en 2024?").afirmaciones[0]
    assert "4515577 personas" in pob.texto


def test_x16_los_paises_del_mundo_salen_del_corpus_inyectado(consultor) -> None:
    consultor.indice.corpus.paises_del_mundo = (("Narnia", "narnia"),)
    assert consultor.responder("¿Cuál fue el desempleo de Narnia en 2024?").motivo == "pais_sin_datos"
    assert consultor.responder("¿Cuál fue el desempleo de Chile en 2024?").motivo != "pais_sin_datos"
