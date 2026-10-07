"""E1-10d: «nacional» suelto (X85), zonas de la capital (X86), léxico de seguridad (X87) y alcance exterior (D-115)."""

from __future__ import annotations

import pytest

from src import contexto, limpieza, puntaje
from src.configuracion import cargar_temas, cargar_vinculos
from tests.prioridad_ayuda import CFG, REGLAS, miembro

SUB = cargar_vinculos().subtema
TEMAS = cargar_temas().temas


def _nivel(*titulares: str) -> str:
    return puntaje.alcance_geografico([miembro(f"NOT-{i}", t) for i, t in enumerate(titulares)], REGLAS, CFG).nivel


# ------------------------------------------------------------------ X85 · «nacional» suelto


@pytest.mark.parametrize(
    ("titular", "nivel"),
    [
        ("Policía Nacional aprehende a sospechoso en Chiriquí", "provincial"),
        ("Guardia Nacional de Texas envía tropas", "desconocido"),
        ("Banco Nacional recibe auditoría en Bocas del Toro", "provincial"),
        ("Policía Nacional realiza operativo", "desconocido"),
    ],
)
def test_x85_nacional_suelto_en_el_nombre_de_una_institucion_no_da_alcance_nacional(titular: str, nivel: str) -> None:
    assert _nivel(titular) == nivel


@pytest.mark.parametrize(
    "titular",
    [
        "A nivel nacional, cierran escuelas",
        "Alerta en todo el país por lluvias",
        "Cortes de luz en todo el territorio",
        "Declaran emergencia en el territorio nacional",
        "Asamblea Nacional aprueba el presupuesto",
        "Gobierno nacional anuncia el plan",
    ],
)
def test_x85_las_frases_nacionales_siguen_dando_alcance_nacional(titular: str) -> None:
    assert _nivel(titular) == "nacional"


def test_x85_una_frase_nacional_manda_sobre_un_lugar_concreto() -> None:
    assert _nivel("Cierran escuela en David", "A nivel nacional, cierran escuelas") == "nacional"


# ------------------------------------------------------------------ X86 · zonas de la capital


@pytest.mark.parametrize(
    "titular",
    [
        "Panamá Norte registra cortes de agua",
        "Inauguran centro de salud en Panamá Pacífico",
        "Tranque en panama pacifico por obras",
    ],
)
def test_x86_panama_norte_y_pacifico_son_un_lugar_concreto_no_el_pais(titular: str) -> None:
    assert _nivel(titular) == "local"


def test_x86_panama_oeste_sigue_siendo_provincia_y_panama_sola_el_pais() -> None:
    assert _nivel("Corte de agua en Panamá Oeste") == "provincial"
    assert _nivel("Minsa: casos en Panamá") == "nacional"


# ------------------------------------------------------------------ X87 · léxico de seguridad ciudadana


def _subtemas(titular: str) -> set[str]:
    return contexto.subtemas_nombrados([titular], list(TEMAS["servicios_publicos"].subtemas), SUB.terminos_por_subtema)


@pytest.mark.parametrize(
    "titular",
    [
        "Más de 30 mujeres han muerto de forma violenta este año",
        "Tres muertes violentas en un fin de semana",
        "Muerte violenta de un joven en la barriada",
        "Dos muertos de forma violenta en el sector",
        "Investigan femicidio en el interior",
        "Suman cinco feminicidios en el año",
        "Disparan contra un vehículo en la vía",
        "Dispararon contra la fachada de una vivienda",
        "Disparos en la barriada dejan un herido",
        "Joven baleada en plena calle",
        "Hombre baleado en un comercio",
        "Reportan balacera en el sector",
        "Apuñalado un taxista tras discusión",
        "Apuñalan a un joven a la salida de un local",
        "Homicidios aumentan en el distrito",
        "Asesinados dos hombres en un local",
        "Asesinaron a un comerciante",
        "Asaltaron un supermercado de la zona",
        "Atracos en la capital dejan un herido",
        "Secuestro de un empresario conmociona al país",
        "Denuncian extorsión a comerciantes",
        "Capturan a presunto sicario",
    ],
)
def test_x87_las_formas_de_homicidio_y_agresion_con_arma_son_seguridad_ciudadana(titular: str) -> None:
    assert _subtemas(titular) == {"seguridad_ciudadana"}


@pytest.mark.parametrize(
    "titular",
    [
        "Disparan cohetes en el desfile",
        "Se disparan los precios del combustible",
    ],
)
def test_x87_disparar_cohetes_o_precios_no_es_seguridad_ciudadana(titular: str) -> None:
    assert "seguridad_ciudadana" not in _subtemas(titular)


def test_x87_el_subtema_se_asigna_con_el_lexico_nuevo() -> None:
    assert contexto.decidir_subtema(
        [("seguridad_ciudadana", 0.8, 0.001)], ["Más de 30 mujeres han muerto de forma violenta este año"], SUB, list(TEMAS["servicios_publicos"].subtemas)
    ) == ("seguridad_ciudadana", "lexico")


# ------------------------------------------------------------------ D-115 · alcance exterior


def test_d115_el_exterior_vale_lo_mismo_que_local_y_desconocido() -> None:
    a = REGLAS.impacto.alcance_geografico
    assert (a.exterior, a.local, a.desconocido) == (0.3, 0.3, 0.3)


@pytest.mark.parametrize(
    "titular",
    [
        "Vigilancia por peste neumónica en Rusia",
        "Obispos panameños presentan en Roma la realidad de sus diócesis",
        "AMP abre oficina en Ho Chi Minh",
        "Panamá y Colombia firman acuerdo en Bogotá",
        "Presidente de Panamá visita Singapur",
        "Plague surveillance in Russia",
        "Brote de dengue en MEXICO",                              # sin tildes ni mayúsculas
        "Accidente aéreo en Santiago de Chile deja heridos",       # el nombre extranjero más largo manda sobre el distrito de Santiago
        "Ciudad de México inaugura línea de metro",
        "Exportaciones a EE. UU. caen en septiembre",
        "Precios del petróleo suben en Nueva York",
    ],
)
def test_d115_un_pais_o_ciudad_extranjeros_sin_lugar_panameno_dan_alcance_exterior(titular: str) -> None:
    alcance = puntaje.alcance_geografico([miembro("NOT-1", titular)], REGLAS, CFG)
    assert (alcance.nivel, alcance.valor, bool(alcance.terminos)) == ("exterior", 0.3, True)


@pytest.mark.parametrize(
    ("titulares", "nivel"),
    [
        (("Minsa: casos en Panamá",), "nacional"),
        (("Lluvias en Chiriquí",), "provincial"),
        (("Inundaciones en Colón y en Miami",), "provincial"),        # el lugar panameño manda sobre el exterior
        (("Cierran escuelas en David por brote en Chile",), "local"),
        (("Alerta en la ciudad de Panamá por lluvias en Costa Rica",), "local"),
        (("Cierran escuelas a nivel nacional por brote en Chile",), "nacional"),   # la frase nacional explícita manda
        (("Brote en Chile", "Minsa: casos en todo el país"), "nacional"),         # también si está en otro titular del grupo
        (("Brote en Rusia", "Lluvias en Chiriquí"), "provincial"),                 # y un lugar panameño de otro titular
        (("Santiago Peña llega a Panamá",), "nacional"),                          # D-110: Santiago sin prefijo no es el distrito, ni el exterior
        (("Accidente en Santiago deja tres heridos",), "local"),                  # con prefijo sigue siendo el distrito
        (("Colón Colombia no existe",), "provincial"),
        (("Cristóbal Colón llegó a América",), "desconocido"),
        (("Compran chilenos y alemanes",), "desconocido"),                        # un gentilicio no es un país
        (("Precios en el supermercado",), "desconocido"),
    ],
)
def test_d115_precedencia_de_lugares_de_panama_frases_nacionales_y_exterior(titulares: tuple[str, ...], nivel: str) -> None:
    assert _nivel(*titulares) == nivel


def test_d115_un_titular_con_alcance_exterior_no_es_ruido() -> None:
    fila = {
        "titulo": "Panamá y Colombia firman acuerdo en Bogotá", "url": "https://ejemplo.example/n/1", "url_canonica": "https://ejemplo.example/n/1",
        "medio": "Ejemplo", "dominio": "ejemplo.example", "origen": "GDELT", "pais_medio": None,
        "fecha_deteccion": "2026-10-01T10:00:00Z", "fecha_publicacion": None, "fecha_extraccion": "2026-10-06T10:00:00Z",
        "descripcion": None, "categoria_fuente": None,
    }  # fmt: skip
    assert limpieza.evaluar(fila, limpieza.Reglas.desde_config()).motivo_ruido is None


def test_d115_el_titular_se_enmascara_sin_perder_tildes_del_resto() -> None:
    nombres, resto = puntaje.exterior_en("Lluvias en Colón y Ámsterdam", REGLAS.geografia.exterior_terminos)
    assert nombres == ["amsterdam"] and resto == "Lluvias en Colón y " + " " * len("Ámsterdam")
