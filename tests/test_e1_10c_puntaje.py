"""E1-10c: subtema con sustento (X41), alcance nacional (X42), ruido regional (X44) y D-103 (N y R)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src import contexto, limpieza, puntaje
from src.configuracion import cargar_temas, cargar_vinculos
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, entrada, miembro, vector

SUB = cargar_vinculos().subtema
TEMAS = cargar_temas().temas
SERVICIOS = list(TEMAS["servicios_publicos"].subtemas)


def decidir(subtema: str, margen: float, titular: str, tema: str = "servicios_publicos") -> tuple[str | None, str | None]:
    return contexto.decidir_subtema([(subtema, 0.83, margen)], [titular], SUB, list(TEMAS[tema].subtemas))


# ------------------------------------------------------------------ X41 · subtema con sustento


@pytest.mark.parametrize(
    ("subtema", "margen", "titular"),
    [
        # el margen pasa (D-92), pero el titular no nombra nada del subtema: obras del MOP no son agua potable
        ("agua_potable", 0.0402, "MOP solicita $43.1 millones para pagar compromisos y continuar obras en ejecución"),
        ("agua_potable", 0.0444, "La Chorrera proyecta renovar el parque Tomás Martín Feuillet con una inversión de 620 mil dólares"),
    ],
)
def test_x41_el_margen_solo_no_basta_para_afirmar_un_subtema(subtema: str, margen: float, titular: str) -> None:
    assert decidir(subtema, margen, titular) == (None, None)


@pytest.mark.parametrize(
    "titular",
    [
        # nombran a la vez la salud (CSS, hospital) y la seguridad (aprehensión, reclusión): el subtema es ambiguo
        "Aprehenden a Enrique Lau, exdirector de la CSS, por supuesto enriquecimiento injustificado",
        "César Caicedo ahora está recluido en el Hospital Santo Tomás; había sido trasladado a Coiba",
    ],
)
def test_x41_un_titular_que_nombra_dos_subtemas_del_tema_queda_sin_subtema(titular: str) -> None:
    assert decidir("salud_publica", 0.0386, titular) == (None, None)


@pytest.mark.parametrize(
    ("subtema", "titular"),
    [
        ("salud_publica", "Hospital reporta falta de medicamentos"),                      # casos difíciles de docs/guia_temas.md
        ("educacion_publica", "Paro docente deja sin clases a escuelas"),
        ("seguridad_ciudadana", "Policía reporta aumento de homicidios"),
        ("transporte_publico", "Usuarios del Metro y MiBus reportan retrasos"),          # prototipo de temas.yaml
        ("seguridad_ciudadana", "Mujer es aprehendida en Santiago tras hallazgo de 162 paquetes de presunta droga en el vehículo que conducía"),
    ],
)
def test_x41_un_titular_que_nombra_el_subtema_lo_conserva(subtema: str, titular: str) -> None:
    assert decidir(subtema, 0.001, titular) == (subtema, "lexico")


def test_x41_la_configuracion_ya_no_acepta_el_subtema_solo_por_margen() -> None:
    assert SUB.criterios == ["lexico"]


def test_x41_todo_subtema_del_catalogo_tiene_terminos_de_apoyo() -> None:
    faltan = [s for t in TEMAS.values() for s in t.subtemas if not SUB.terminos_por_subtema.get(s)]
    assert faltan == []


# ------------------------------------------------------------------ X42 · alcance nacional


def _nivel(*titulares: str) -> str:
    return puntaje.alcance_geografico([miembro(f"NOT-{i}", t) for i, t in enumerate(titulares)], REGLAS, CFG).nivel


@pytest.mark.parametrize(
    "titular",
    [
        "Más de 30 mujeres han muerto de forma violenta en Panamá este año",            # el país nombrado
        "Ejecutivo sanciona la Ley 552 del Presupuesto del Canal de Panamá por $5,555 millones",   # el país nombrado (Canal de Panamá)
        "Déficit de personal limita la capacidad operativa de los bomberos en el país",
        "Obispos panameños presentarán en Roma la realidad de sus diócesis",
    ],
)
def test_x42_el_pais_o_su_gentilicio_dan_alcance_nacional(titular: str) -> None:
    assert _nivel(titular) == "nacional"


@pytest.mark.parametrize(
    "titular",
    [
        "MOP solicita $43.1 millones para pagar compromisos y continuar obras en ejecución",
        "Minsa: Adelantan vacunación contra VSR en embarazadas",
        "CSS traslada a un asegurado a otro hospital",
        "Ejecutivo sanciona la ley de presupuesto",
        "ACP anuncia nuevo cronograma de tránsito",
        "Contraloría audita el gasto de la AMP",
    ],
)
def test_d108_una_institucion_nacional_sola_da_desconocido(titular: str) -> None:
    assert _nivel(titular) == "desconocido"


@pytest.mark.parametrize(
    ("titulares", "nivel"),
    [
        (("Lluvias en Panamá dejan inundaciones en Chepo",), "local"),                    # el lugar concreto manda
        (("Minsa refuerza la vacunación en Chiriquí",), "provincial"),
        (("Corte de agua en la provincia de Panamá",), "provincial"),                      # la provincia no es el país
        (("Tranque en la ciudad de Panamá por obras",), "local"),                          # la ciudad no es el país: es un lugar (X52)
        (("Se reúne el comité técnico",), "desconocido"),
        (("Cierran escuela en David", "Gobierno decreta alza a nivel nacional"), "nacional"),   # explícito sigue mandando
    ],
)
def test_x42_un_lugar_concreto_manda_sobre_la_mencion_implicita_del_pais(titulares: tuple[str, ...], nivel: str) -> None:
    assert _nivel(*titulares) == nivel


@pytest.mark.parametrize(
    ("titular", "nivel"),
    [
        ("David Beckham visita Panamá", "nacional"),                       # David es el nombre de pila, no el distrito
        ("Lluvias en David dejan calles anegadas", "local"),
        ("Corte de agua en el distrito de David", "local"),
        ("Plan para la provincia de Herrera", "provincial"),
        ("Ministro Herrera anuncia plan del MEF en Panamá", "nacional"),   # Herrera es un apellido
        ("Santiago Peña llega a Panamá", "nacional"),
        ("Accidente en Santiago deja tres heridos", "local"),
        ("Cierran La Mesa de diálogo en Panamá", "nacional"),
        ("Remedios para la gripe escasean en el país", "nacional"),
        ("Inundaciones en Remedios", "local"),
    ],
)
def test_d110_un_nombre_de_lugar_que_es_tambien_nombre_propio_solo_cuenta_con_prefijo_locativo(titular: str, nivel: str) -> None:
    assert _nivel(titular) == nivel


def test_d109_el_alcance_desconocido_vale_lo_mismo_que_el_local() -> None:
    a = REGLAS.impacto.alcance_geografico
    assert (a.desconocido, a.local) == (0.3, 0.3)


# ------------------------------------------------------------------ X44 · notas regionales que afectan a Panamá


def _gdelt(titulo: str) -> limpieza.Resultado:
    fila = {
        "titulo": titulo, "url": "https://ejemplo.example/n/1", "url_canonica": "https://ejemplo.example/n/1",
        "medio": "Ejemplo", "dominio": "ejemplo.example", "origen": "GDELT", "pais_medio": None,
        "fecha_deteccion": "2026-10-01T10:00:00Z", "fecha_publicacion": None, "fecha_extraccion": "2026-10-06T10:00:00Z",
        "descripcion": None, "categoria_fuente": None,
    }  # fmt: skip
    return limpieza.evaluar(fila, limpieza.Reglas.desde_config())


@pytest.mark.parametrize(
    "titulo",
    [
        # comercio marítimo y de combustibles en una ruta que pasa por el Canal (D-84: «rutas marítimas»); X54: con ancla
        "Exportaciones chinas sostienen la demanda de carga contenerizada pese a la debilidad de EE. UU.",
        "US LNG Exports Increase in September, Europe Outbids Asia for Cargoes",   # etiqueta humana: logística, regional
        "Suben los fletes marítimos entre Asia y la costa este de EE. UU.",
        "Navieras desvían portacontenedores al Canal de Suez",
        "US crude exports to Asia rise",                                          # «crude» como «crudo» (X54)
        "Container shipping rates from China to US west coast jump",
        "Container rates on the Asia\u2013US route climb",                          # X59: ruta explícita
        "Shipping lines cut Asia-US capacity",
    ],
)
def test_x44_el_comercio_maritimo_y_de_combustibles_es_regional_no_ruido(titulo: str) -> None:
    r = _gdelt(titulo)
    assert (r.motivo_ruido, r.alcance_regional) == (None, True)


@pytest.mark.parametrize(
    "titulo",
    [
        "Trump redirige ayuda a Europa",
        "Emerging Technologies and Maritime Security",
        "Navy destroyer named for late Sen. Ted Stevens will be commissioned in Whittier on Saturday",
        "Carnival to Deploy Adventure, Legend, Spirit to West Coast in 2028",
        "Sin combustible y con menos vuelos, pero a Cuba aún llegan aviones",   # escasez local en otro país, no un flujo comercial
        "El Niño hits Australian wheat",
    ],
)
def test_x44_lo_que_no_es_comercio_maritimo_ni_de_combustibles_sigue_siendo_ruido(titulo: str) -> None:
    r = _gdelt(titulo)
    assert (r.motivo_ruido, r.alcance_regional) == ("no_es_panama", False)


def test_x44_un_falso_panama_con_comercio_maritimo_sigue_siendo_ruido() -> None:
    assert _gdelt("Panama City port sees container shipping growth").motivo_ruido == "no_es_panama"


# ------------------------------------------------------------------ D-103 · N y R


UMBRAL = REGLAS.agrupacion.umbral_similitud


def _con_similitud(s: float) -> np.ndarray:
    """Vector cuyo coseno con ``vector(1, 0)`` es exactamente ``s``."""
    return np.stack([vector(s, math.sqrt(1 - s * s))])


def _n(similitud: float, reglas=REGLAS) -> puntaje.Componente:
    entradas = [
        entrada("GRP-previo", [miembro("NOT-p", publicado_hace=100)], vectores=np.stack([vector(1, 0)])),
        entrada("GRP-nuevo", [miembro("NOT-n", publicado_hace=10)], vectores=_con_similitud(similitud)),
    ]
    return {p.id_grupo: p for p in puntaje.calcular_puntajes(entradas, reglas, CFG, AHORA)}["GRP-nuevo"].componentes["N"]


@pytest.mark.parametrize("similitud", [0.0, 0.3, 0.6, UMBRAL - 0.001])
def test_d103_bajo_el_umbral_de_agrupacion_n_es_1(similitud: float) -> None:
    assert _n(similitud).valor == 1.0


@pytest.mark.parametrize("similitud", [UMBRAL, (UMBRAL + 1) / 2, 0.95, 1.0])
def test_d103_desde_el_umbral_n_descuenta_lineal_hasta_0_con_un_duplicado(similitud: float) -> None:
    c = _n(similitud)
    assert c.valor == pytest.approx((1 - similitud) / (1 - UMBRAL), abs=1e-6)
    assert c.explicacion["umbral_similitud"] == UMBRAL and c.explicacion["similitud_maxima"] == pytest.approx(similitud, abs=1e-6)


def test_d103_el_umbral_de_n_es_el_de_la_agrupacion_no_una_copia() -> None:
    otro = REGLAS.model_copy(update={"agrupacion": REGLAS.agrupacion.model_copy(update={"umbral_similitud": 0.9})})
    assert _n(0.8).valor < 1.0 and _n(0.8, otro).valor == 1.0


def test_d103_r_no_usa_la_confianza_del_clasificador() -> None:
    entradas = [
        entrada("GRP-alta", [miembro("NOT-a", similitud=0.95)], vectores=np.stack([vector(1, 0)])),
        entrada("GRP-baja", [miembro("NOT-b", similitud=0.40)], vectores=np.stack([vector(0, 1)])),
        entrada("GRP-reg", [miembro("NOT-r", similitud=0.95, regional=True)], vectores=np.stack([vector(1, 1)])),
    ]
    r = {p.id_grupo: p.componentes["R"] for p in puntaje.calcular_puntajes(entradas, REGLAS, CFG, AHORA)}
    assert r["GRP-alta"].valor == r["GRP-baja"].valor == REGLAS.relevancia.foco_panama_sujeto
    assert r["GRP-reg"].valor == REGLAS.relevancia.foco_otro_pais_afecta
    assert not any("similitud" in k for k in r["GRP-alta"].explicacion)


def test_d103_los_pesos_de_p_no_cambian() -> None:
    assert (REGLAS.pesos.R, REGLAS.pesos.I, REGLAS.pesos.U, REGLAS.pesos.N, REGLAS.pesos.E) == (30, 25, 20, 15, 10)


# ------------------------------------------------------------------ X51 · «pese a» no es el distrito de Pesé


def test_x51_la_preposicion_pese_a_no_es_el_distrito() -> None:
    assert _nivel("Exportaciones chinas sostienen la demanda de carga contenerizada pese a la debilidad de EE. UU.") != "local"
    assert _nivel("Pese a la lluvia, sigue el festival") != "local"


@pytest.mark.parametrize("titular", ["Exportaciones crecen pese al alza del petróleo", "Pese al calor, sigue la jornada", "Sigue la obra pese al paro"])
def test_x58_pese_al_tampoco_es_el_distrito(titular: str) -> None:
    assert _nivel(titular) != "local"


@pytest.mark.parametrize("titular", ["Inundaciones en Pesé dejan familias evacuadas", "Productores de Pese reclaman pagos", "PESÉ: corte de agua"])
def test_x51_el_distrito_de_pese_sigue_siendo_local(titular: str) -> None:
    assert _nivel(titular) == "local"


# ------------------------------------------------------------------ X52 · un lugar concreto manda sobre la sigla nacional


@pytest.mark.parametrize(
    "titular",
    ["MOP inaugura obra en Ciudad de Panamá", "Accidente en el distrito de Panamá deja dos heridos", "Minsa vacuna en la ciudad de Panamá"],
)
def test_x52_la_ciudad_o_el_distrito_de_panama_son_un_lugar_concreto(titular: str) -> None:
    assert _nivel(titular) == "local"


# ------------------------------------------------------------------ X53 · el léxico elige el subtema, no solo confirma


@pytest.mark.parametrize(
    ("mas_cercano", "titular", "tema", "esperado"),
    [
        ("agua_potable", "Minsa: Adelantan vacunación contra VSR en embarazadas", "servicios_publicos", "salud_publica"),
        ("agua_potable", "Contenido Exclusivo: El metro por la Tumba Muerto", "servicios_publicos", "transporte_publico"),
        ("inversion", "Fitch mantiene el grado de inversión de Panamá", "economia", "banca_calificaciones"),   # «inversión» va dentro del término más largo
    ],
)
def test_x53_el_subtema_cuyo_termino_aparece_se_asigna_aunque_no_sea_el_mas_cercano(mas_cercano: str, titular: str, tema: str, esperado: str) -> None:
    assert decidir(mas_cercano, 0.001, titular, tema) == (esperado, "lexico")


def test_x53_dos_subtemas_nombrados_siguen_sin_subtema() -> None:
    assert decidir("agua_potable", 0.001, "Aprehenden a Enrique Lau, exdirector de la CSS, por supuesto enriquecimiento injustificado") == (None, None)


@pytest.mark.parametrize(
    ("subtema", "titular", "tema"),
    [
        ("sequia_nino", "Contenido Exclusivo: Coclé, se seca el campo", "eventos_naturales"),         # «seca» no está en la guía
        ("agua_potable", "Lluvias: el agua arrastró vehículos en la vía", "servicios_publicos"),       # «agua» suelta no es el servicio
        ("alertas_proteccion_civil", "Minsa enciende alertas por el dengue", "eventos_naturales"),    # «alerta» suelta no es protección civil
        ("leyes_decretos", "Cumplir la ley de tránsito, piden autoridades", "regulacion"),            # «ley» suelta no es una norma nueva
    ],
)
def test_x53_palabras_sueltas_ambiguas_no_respaldan_el_subtema(subtema: str, titular: str, tema: str) -> None:
    assert decidir(subtema, 0.001, titular, tema) == (None, None)


@pytest.mark.parametrize(
    ("subtema", "titular", "tema"),
    [
        ("agua_potable", "Lluvias dejan sin agua a sectores de San Miguelito", "servicios_publicos"),   # caso difícil de la guía
        ("alertas_proteccion_civil", "Protección Civil declara alerta en Chiriquí", "eventos_naturales"),
        ("leyes_decretos", "Asamblea aprueba proyecto de ley de APP", "regulacion"),
    ],
)
def test_x53_con_contexto_las_mismas_palabras_si_respaldan(subtema: str, titular: str, tema: str) -> None:
    assert decidir(subtema, 0.001, titular, tema) == (subtema, "lexico")


# ------------------------------------------------------------------ X54 · las reglas regionales se quedan dentro de D-84


@pytest.mark.parametrize(
    "titulo",
    [
        "Police seize cocaine in containers at Rotterdam",
        "India fuel imports hit record",
        "Germany imports more LNG from Qatar",
        "Brazil soybean cargoes delayed at Santos",
        "Nigeria boosts crude exports",
        "China fuel imports surge as US sanctions bite Iran",                     # X59: «US» no es la ruta, y «us» no es EE. UU.
        "Japan imports more LNG from Qatar, US analysts say",                     # X59: «US analysts» es el pronombre/adjetivo, no un destino
    ],
)
def test_x54_comercio_maritimo_o_de_combustibles_sin_ancla_de_d84_sigue_siendo_ruido(titulo: str) -> None:
    r = _gdelt(titulo)
    assert (r.motivo_ruido, r.alcance_regional) == ("no_es_panama", False)


# ------------------------------------------------------------------ D-106 · U no se satura dentro de la ventana


def _u(horas: float | None, detectado: float | None = None) -> puntaje.Componente:
    return puntaje.urgencia([miembro("NOT-u", publicado_hace=horas, detectado_hace=detectado)], AHORA, REGLAS)[0]


def test_d106_u_decrece_de_forma_estricta_dentro_de_la_ventana() -> None:
    limite = REGLAS.urgencia.dias_nulo * 24
    edades = [0, 1, 2, 12, 23, 25, 30, 48, 100, limite - 1]
    valores = [_u(h).valor for h in edades]
    assert all(a > b for a, b in zip(valores, valores[1:], strict=False))


def test_d106_una_noticia_de_2_horas_es_mas_urgente_que_una_de_30() -> None:
    assert _u(2).valor > _u(30).valor


def test_d106_u_va_de_1_al_publicar_a_0_al_cerrar_la_ventana() -> None:
    limite = REGLAS.urgencia.dias_nulo * 24
    assert _u(0).valor == 1.0 and _u(-5).valor == 1.0          # una publicación posterior a la referencia no pasa de 1
    assert _u(limite).valor == 0.0 and _u(limite + 50).valor == 0.0
    assert _u(limite / 2).valor == pytest.approx(0.5)            # lineal: la fracción de la ventana que queda
    assert all(0.0 <= _u(h).valor <= 1.0 for h in range(0, int(limite) + 24, 7))


def test_d106_sin_publicacion_sigue_usando_la_deteccion_y_el_vacio() -> None:
    c, vacios = puntaje.urgencia([miembro("NOT-g", publicado_hace=None, detectado_hace=30)], AHORA, REGLAS)
    assert c.explicacion["fecha_origen"] == "deteccion" and c.valor == _u(30).valor
    assert any(v.codigo == "urgencia_sin_publicacion" for v in vacios)
