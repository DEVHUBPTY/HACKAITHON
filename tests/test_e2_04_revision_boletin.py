"""E2-04 · Revisión humana del boletín bancario: se corrigen los bloques *Observaciones* e *Hipótesis de impacto* (D-48).

Cada corrección pasa por ``revalidar_correccion`` (única entrada a ``src/validador.py`` de la revisión) con las reglas de banca de E2-02, la persona
confirma cada advertencia y todo queda en el registro de solo agregar. El caso es el congelado de E2-03 (``GRP-da35c3dead``): sin LLM en vivo
ni ``data/senales.duckdb``.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src import embeddings, exportar, interfaz as ui, revision as rv
from src.configuracion import cargar_interfaz
from src.generacion import EntradaFicha
from src.revision import AdvertenciasSinConfirmar, Revisiones, aplicar_ediciones, elementos_editables, revalidar_correccion
from tests import ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba

FIXTURES = Path(__file__).parent / "fixtures"
ANALISTA = "Juan Zhou"
OBS = "observaciones"
HIP = "hipotesis_impacto"
# Una observación válida y una hipótesis válida distintas de las del congelado.
OBS_VALIDA = "Según laestrella.com.pa, Mulino viajará a Asia para suscribir convenios bilaterales con Singapur y Vietnam."
HIP_VALIDA = "Es posible que la gira presidencial por Asia sea relevante para el comercio exterior, a verificar con fuentes adicionales."


def _leer(nombre: str) -> dict[str, Any]:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def entrada() -> EntradaFicha:
    return EntradaFicha(**_leer("e2_03_cu05_ficha.json"))


def boletin() -> dict[str, Any]:
    return _leer("e2_03_cu05_boletin.json")


def avisos(clave_texto: dict[str, str], contenido: dict[str, Any] | None = None, ent: EntradaFicha | None = None) -> list[rv.Advertencia]:
    """Lo que ve la persona al corregir ``contenido`` (el congelado por defecto) con esos textos."""
    antes = contenido or boletin()
    return revalidar_correccion(ent or entrada(), antes, aplicar_ediciones(antes, clave_texto), clave_texto)


def reglas(lista: list[rv.Advertencia]) -> set[str]:
    return {a.mensaje.split("]")[0].lstrip("[") for a in lista}


# ============================================================================================ lo editable

def test_el_boletin_expone_sus_dos_bloques_y_no_lo_que_pone_la_regla_o_la_ficha() -> None:
    claves = set(elementos_editables(boletin()))
    assert {f"{OBS}.0", f"{OBS}.4", f"{HIP}.0", "preguntas.0", "afirmaciones.A1", "afirmaciones.A6"} <= claves
    assert not {c for c in claves if c.split(".")[0] in ("sectores", "horizonte", "evidencia", "aviso", "marca", "leyenda_alcance")}


def test_el_paquete_editorial_conserva_sus_elementos_editables() -> None:
    editorial = _leer("e2_03_cu05_paquete_editorial.json")
    claves = elementos_editables(editorial)
    assert not any(c.startswith((f"{OBS}.", f"{HIP}.")) for c in claves)
    assert {"titulo", "enfoque.0", "brief.0", "resumen_web.0", "preguntas.0", "afirmaciones.A1"} <= set(claves)


# ============================================================================================ reglas de banca sobre cada bloque

def test_una_observacion_corregida_con_texto_valido_no_trae_advertencias() -> None:
    assert avisos({f"{OBS}.1": OBS_VALIDA}) == []


def test_una_hipotesis_corregida_con_texto_valido_no_trae_advertencias() -> None:
    assert avisos({f"{HIP}.0": HIP_VALIDA}) == []


@pytest.mark.parametrize(
    ("clave", "texto", "regla"),
    [
        (f"{OBS}.1", "Según laestrella.com.pa, Mulino podría viajar a Asia y suscribir convenios con Singapur y Vietnam.", "observacion_condicional"),
        (f"{HIP}.0", "La cobertura de una gira presidencial por Asia es relevante para el comercio exterior.", "impacto_sin_condicional"),
        (f"{HIP}.0", "Es posible que la gira atraiga 500 millones en inversiones, a verificar con fuentes adicionales.", "cifra_no_coincide"),
        (f"{HIP}.0", "La gira podría generar pérdidas en el comercio exterior, a verificar.", "perdidas_en_inferencias"),
        (f"{HIP}.0", "La gira ocurrirá sin duda y afectará al comercio exterior.", "certeza"),
        (f"{OBS}.0", "Recomendamos reducir exposición: el medio prensa-latina.cu reporta que el Presidente panameño visitará Singapur y Vietnam.", "recomendacion"),
        ("afirmaciones.A6", "Es posible que haya pérdidas en el entorno del comercio exterior, a verificar.", "perdidas_en_inferencias"),
    ],
)
def test_cada_regla_de_banca_rechaza_su_correccion_con_su_regla(clave: str, texto: str, regla: str) -> None:
    lista = avisos({clave: texto})
    assert regla in reglas(lista), [a.id for a in lista]
    assert all(a.clave == clave for a in lista if a.clave != HIP)        # la advertencia nombra el texto que se corrigió


def _con_citas(bloque: str, i: int, citas: list[str]) -> dict[str, Any]:
    d = boletin()
    d[bloque][i]["afirmaciones"] = citas
    return d


def test_una_observacion_que_cita_una_hipotesis_se_rechaza() -> None:
    antes = boletin()
    despues = aplicar_ediciones(_con_citas(OBS, 0, ["A6"]), {f"{OBS}.0": antes[OBS][0]["texto"] + " "})
    lista = revalidar_correccion(entrada(), antes, despues, {f"{OBS}.0"})
    assert "observacion_con_hipotesis" in reglas(lista)


def test_una_hipotesis_de_impacto_que_cita_un_hecho_se_rechaza() -> None:
    antes = boletin()
    despues = aplicar_ediciones(_con_citas(HIP, 0, ["A4"]), {f"{HIP}.0": HIP_VALIDA})
    assert "impacto_como_hecho" in reglas(revalidar_correccion(entrada(), antes, despues, {f"{HIP}.0"}))


def test_editar_el_texto_nunca_cambia_las_citas_ni_el_bloque() -> None:
    antes = boletin()
    despues = aplicar_ediciones(antes, {f"{OBS}.1": OBS_VALIDA, f"{HIP}.0": HIP_VALIDA})
    assert [o["afirmaciones"] for o in despues[OBS]] == [o["afirmaciones"] for o in antes[OBS]]
    assert [o["afirmaciones"] for o in despues[HIP]] == [o["afirmaciones"] for o in antes[HIP]]
    assert antes == boletin()                                              # el original no se toca


def test_el_resumen_se_limita_entre_los_dos_bloques_juntos() -> None:
    """Cada bloque cabe solo en 250 palabras; los dos juntos no: la regla cruzada (``validar_conjunto``) lo ve."""
    relleno = " ".join(["palabra"] * 125)
    cambios = {f"{OBS}.0": f"El medio prensa-latina.cu reporta que el Presidente panameño visitará Singapur y Vietnam. {relleno}", f"{HIP}.0": f"{HIP_VALIDA} {relleno}"}
    lista = avisos(cambios)
    mensajes = [a.mensaje for a in lista]
    assert any("el resumen (observaciones e hipótesis de impacto)" in m for m in mensajes), mensajes
    assert not any(m.startswith("[limite_palabras] observaciones tiene") or m.startswith("[limite_palabras] hipotesis_impacto tiene") for m in mensajes)


# ============================================================================================ D-54 y D-107 (declaración literal)

def _lluvias() -> tuple[dict[str, Any], EntradaFicha]:
    """El congelado con un titular que dice «pérdidas»: la excepción de la declaración literal de D-54 sí aplica."""
    d, e = boletin(), _leer("e2_03_cu05_ficha.json")
    titular = "Las lluvias causaron pérdidas en cultivos de Chiriquí"
    for r in e["registros"]:
        if r["id"] == "NOT-33032542b7":
            r["campos"]["titulo_limpio"] = titular
    texto = "Según laestrella.com.pa, las lluvias causaron pérdidas en cultivos de Chiriquí."
    d["afirmaciones"][1]["texto"] = texto
    d[OBS][1]["texto"] = texto
    return d, EntradaFicha(**e)


def test_una_declaracion_literal_con_perdidas_sigue_permitida() -> None:
    d, e = _lluvias()
    lista = avisos({f"{OBS}.1": "Según el medio laestrella.com.pa, las lluvias causaron pérdidas en cultivos de Chiriquí."}, d, e)
    assert lista == [], [a.id for a in lista]


def test_el_termino_financiero_ajeno_al_titular_se_rechaza_aunque_la_palabra_este_en_el_titular() -> None:
    d, e = _lluvias()
    lista = avisos({f"{OBS}.1": "Según laestrella.com.pa, las lluvias causaron pérdidas en cultivos de Chiriquí y en la banca."}, d, e)
    assert "sector_financiero_ajeno" in reglas(lista), [a.id for a in lista]


def test_perdidas_en_una_observacion_que_el_titular_no_dice_se_rechaza() -> None:
    d, e = _lluvias()
    lista = avisos({f"{OBS}.1": "Según laestrella.com.pa, la gira dejó pérdidas en el comercio."}, d, e)
    assert "perdidas_en_inferencias" in reglas(lista)


# ============================================================================================ el registro (solo agregar, versiones, regenerar)


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch, emb):
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)


@pytest.fixture
def rev(tmp_path, emb) -> Revisiones:
    base = h.construir(tmp_path / "senales.duckdb", emb, modalidad="banca")
    t = {"n": 0}

    def ahora() -> datetime:
        t["n"] += 1
        return datetime(2026, 10, 7, 15, 0, tzinfo=UTC) + timedelta(minutes=t["n"])

    return Revisiones(tmp_path / "revision.duckdb", base, ahora=ahora)


def _caso(rev: Revisiones) -> str:
    """Un caso bancario abierto con el boletín congelado como versión 1."""
    return rev.abrir(h.G_COMPLETO, "banca", ANALISTA, paquete=boletin()).id_caso


def _filas(rev: Revisiones, c: str) -> list[tuple]:
    return [(f.id_revision, f.accion, f.estado_nuevo, f.version, f.revisor, json.dumps(f.diferencias), json.dumps(f.detalle)) for f in rev.historial(c)]


def test_corregir_una_observacion_valida_crea_una_version_y_conserva_la_original(rev) -> None:
    c = _caso(rev)
    v = rev.corregir(c, ANALISTA, {f"{OBS}.1": OBS_VALIDA}, entrada=entrada())
    assert v.version == 2 and v.origen == "corregida" and v.version_base == 1
    versiones = rev.versiones(c)
    assert versiones[0].contenido[OBS][1]["texto"] == boletin()[OBS][1]["texto"]
    assert versiones[1].contenido[OBS][1]["texto"] == OBS_VALIDA
    assert versiones[1].contenido[HIP] == versiones[0].contenido[HIP]            # solo cambió lo corregido
    assert rev.estado(c) == "en revisión"
    f = rev.historial(c)[-1]
    assert f.accion == "corregir" and f.diferencias == [{"clave": f"{OBS}.1", "antes": boletin()[OBS][1]["texto"], "despues": OBS_VALIDA}]


def test_corregir_una_hipotesis_valida_se_guarda_y_pasa_por_el_validador(rev) -> None:
    c = _caso(rev)
    assert rev.revisar_correccion(c, {f"{HIP}.0": HIP_VALIDA}, entrada()) == []
    rev.corregir(c, ANALISTA, {f"{HIP}.0": HIP_VALIDA}, entrada=entrada())
    assert rev.version_actual(c).contenido[HIP][0]["texto"] == HIP_VALIDA


def test_una_advertencia_sin_confirmar_no_escribe_nada_y_confirmada_queda_registrada(rev) -> None:
    c = _caso(rev)
    texto = "La cobertura de una gira presidencial por Asia es relevante para el comercio exterior."
    antes = _filas(rev, c)
    with pytest.raises(AdvertenciasSinConfirmar) as exc:
        rev.corregir(c, ANALISTA, {f"{HIP}.0": texto}, entrada=entrada())
    assert any("impacto_sin_condicional" in a.id for a in exc.value.advertencias)
    assert _filas(rev, c) == antes and len(rev.versiones(c)) == 1             # ni versión ni fila a medias
    pendientes = [a.id for a in rev.revisar_correccion(c, {f"{HIP}.0": texto}, entrada())]
    rev.corregir(c, ANALISTA, {f"{HIP}.0": texto}, confirmadas=pendientes, comentario="la persona lo confirma", entrada=entrada())
    f = rev.historial(c)[-1]
    assert f.detalle["advertencias_confirmadas"] == pendientes and f.comentario == "la persona lo confirma"
    assert rev.version_actual(c).contenido[HIP][0]["texto"] == texto


def test_la_tabla_de_revisiones_solo_crece_al_corregir_los_bloques(rev) -> None:
    c = _caso(rev)
    rev.corregir(c, ANALISTA, {f"{OBS}.1": OBS_VALIDA}, entrada=entrada())
    previas = _filas(rev, c)
    rev.corregir(c, ANALISTA, {f"{HIP}.0": HIP_VALIDA}, entrada=entrada())
    ahora = _filas(rev, c)
    assert ahora[: len(previas)] == previas and len(ahora) == len(previas) + 1       # ninguna fila previa cambió
    assert rev.estado(c) == "en revisión" and rev.historial(c)[-1].estado_anterior == "en revisión"


def test_corregir_un_caso_aprobado_exige_reabrirlo_con_motivo(rev) -> None:
    c = _caso(rev)
    rev.aceptar(c, ANALISTA)
    with pytest.raises(rv.TransicionNoPermitida):
        rev.corregir(c, ANALISTA, {f"{OBS}.1": OBS_VALIDA}, entrada=entrada())
    rev.reabrir(c, ANALISTA, "corregir la redacción de una observación")
    rev.corregir(c, ANALISTA, {f"{OBS}.1": OBS_VALIDA}, entrada=entrada())
    rev.aceptar(c, ANALISTA)
    assert rev.estado(c) == "aprobado como borrador"


def test_regenerar_despues_de_corregir_un_bloque_no_pisa_la_version_corregida(rev) -> None:
    c = _caso(rev)
    rev.corregir(c, ANALISTA, {f"{OBS}.1": OBS_VALIDA}, entrada=entrada())
    regenerado = rev.regenerar(c, ANALISTA, generador=lambda *a, **k: boletin())
    assert regenerado.version == 3 and regenerado.origen == "generada" and regenerado.version_base == 2
    versiones = rev.versiones(c)
    assert versiones[1].origen == "corregida" and versiones[1].contenido[OBS][1]["texto"] == OBS_VALIDA      # la corregida sigue ahí
    assert versiones[2].contenido[OBS][1]["texto"] == boletin()[OBS][1]["texto"]


# ============================================================================================ exportación


def test_la_exportacion_muestra_la_version_corregida_con_marca_aviso_y_correcciones(rev, tmp_path) -> None:
    c = _caso(rev)
    rev.corregir(c, ANALISTA, {f"{OBS}.1": OBS_VALIDA, f"{HIP}.0": HIP_VALIDA}, entrada=entrada())
    rev.aceptar(c, ANALISTA)
    md = exportar.exportar_caso(rev, c, tmp_path / "notion", tmp_path / "fichas.jsonl").markdown
    original = boletin()
    assert "BORRADOR · requiere revisión" in md and "aprobado como borrador" in md
    assert "No constituye recomendación financiera ni opinión oficial de la SBP" in md
    assert "basado únicamente en titular/metadatos" in md
    i_obs, i_hip = md.index("Resumen · Observaciones"), md.index("Resumen · Hipótesis de impacto")
    assert i_obs < md.index(OBS_VALIDA.replace("*", "")) < i_hip < md.index(HIP_VALIDA)           # cada texto corregido en su bloque
    bloques = md[i_obs : md.index("### Sectores potencialmente relacionados")]
    assert original[OBS][1]["texto"] not in bloques and original[HIP][0]["texto"] not in bloques    # los bloques del borrador vigente son los corregidos
    assert "Correcciones (antes y después)" in md and original[OBS][1]["texto"] in md.split("Correcciones (antes y después)")[1]
    assert "horizonte" in md.lower() and "inmediato" in md


# ============================================================================================ pantalla (lógica pura de src/interfaz.py)


def test_el_selector_de_correccion_rotula_el_bloque_y_cuenta_desde_uno() -> None:
    et = cargar_interfaz().paquete.etiquetas
    assert ui.etiqueta_de_elemento(f"{OBS}.0", "Texto de la observación", 70, et) == "Resumen · Observaciones · 1 · Texto de la observación"
    assert ui.etiqueta_de_elemento(f"{HIP}.2", "x" * 10, 5, et) == "Resumen · Hipótesis de impacto · 3 · xxxxx…"
    assert ui.etiqueta_de_elemento("afirmaciones.A1", "t", 70, et) == "Afirmaciones validadas · A1 · t"
    assert ui.etiqueta_de_elemento("titulo", "T", 70, et) == "Título · T"
    assert ui.etiqueta_de_elemento("observaciones.0", "t", 70) == "observaciones.0 · t"             # sin rótulos conserva la clave


def test_todo_elemento_editable_del_boletin_tiene_rotulo_en_la_configuracion() -> None:
    et = cargar_interfaz().paquete.etiquetas
    assert {c.split(".")[0] for c in elementos_editables(boletin())} <= set(et)
    assert copy.deepcopy(boletin()) == boletin()


def test_el_borrador_muestra_las_observaciones_antes_que_la_hipotesis_de_impacto() -> None:
    """Una versión guardada ordena sus claves alfabéticamente; la pantalla y la exportación siguen el orden de ``config/interfaz.yaml``."""
    guardado = dict(sorted(boletin().items()))                                                  # como sale de ``versiones`` (sort_keys)
    titulos = [t for t, _ in ui.secciones_de_paquete(guardado, cargar_interfaz().paquete.etiquetas)]
    assert titulos.index("Resumen · Observaciones") < titulos.index("Resumen · Hipótesis de impacto") < titulos.index("Sectores potencialmente relacionados")
    assert titulos.index("Horizonte temporal") < titulos.index("Evidencia") < titulos.index("Aviso")
    sin = [t for t, _ in ui.secciones_de_paquete(guardado)]
    assert sin.index("Hipotesis impacto") < sin.index("Observaciones")                           # sin rótulos, el orden de entrada


# ============================================================================================ X74 · una advertencia ya confirmada no cubre otra oración

OBS_CONDICIONAL_1 = "Según laestrella.com.pa, Mulino podría viajar a Asia y suscribir convenios con Singapur y Vietnam."
OBS_CONDICIONAL_2 = "El medio revistaeyn.com reporta que el Presidente de Panamá podría visitar Singapur y Vietnam en busca de inversiones."
HIP_PERDIDAS_1 = "La gira podría generar pérdidas en el comercio exterior, a verificar."
HIP_PERDIDAS_2 = "La gira podría generar pérdidas en la banca, a verificar."


def _con_dos_hipotesis(contenido: dict[str, Any]) -> dict[str, Any]:
    nuevo = copy.deepcopy(contenido)
    nuevo[HIP].append(copy.deepcopy(nuevo[HIP][0]))
    return nuevo


def test_la_misma_regla_en_otra_observacion_pide_confirmacion_otra_vez() -> None:
    previo = aplicar_ediciones(boletin(), {f"{OBS}.1": OBS_CONDICIONAL_1})          # la persona ya confirmó el «podría» de la observación 2
    assert "observacion_condicional" in reglas(avisos({f"{OBS}.2": OBS_CONDICIONAL_2}, previo))


def test_la_misma_regla_en_otra_hipotesis_pide_confirmacion_otra_vez() -> None:
    previo = _con_dos_hipotesis(aplicar_ediciones(boletin(), {f"{HIP}.0": HIP_PERDIDAS_1}))
    assert "perdidas_en_inferencias" in reglas(avisos({f"{HIP}.1": HIP_PERDIDAS_2}, previo))


def test_reescribir_la_misma_oracion_con_otro_texto_y_la_misma_marca_pide_confirmacion() -> None:
    previo = aplicar_ediciones(boletin(), {f"{OBS}.1": OBS_CONDICIONAL_1})
    assert "observacion_condicional" in reglas(avisos({f"{OBS}.1": "Según laestrella.com.pa, Mulino podría firmar convenios con Vietnam."}, previo))
    previo_h = aplicar_ediciones(boletin(), {f"{HIP}.0": HIP_PERDIDAS_1})
    assert "perdidas_en_inferencias" in reglas(avisos({f"{HIP}.0": HIP_PERDIDAS_2}, previo_h))


def test_una_advertencia_previa_de_una_oracion_que_no_se_toca_no_vuelve_a_aparecer() -> None:
    previo = aplicar_ediciones(boletin(), {f"{OBS}.1": OBS_CONDICIONAL_1})
    assert avisos({f"{HIP}.0": HIP_VALIDA}, previo) == []                              # la observación 2 conserva su «podría» y no se toca
    assert avisos({f"{OBS}.3": boletin()[OBS][3]["texto"] + " "}, previo) == []


def test_corregir_otra_oracion_con_la_misma_regla_no_se_guarda_sin_confirmar(rev) -> None:
    c = _caso(rev)
    e = entrada()
    t1 = {f"{OBS}.1": OBS_CONDICIONAL_1}
    rev.corregir(c, ANALISTA, t1, confirmadas=[a.id for a in rev.revisar_correccion(c, t1, e)], comentario="confirmo", entrada=e)
    t2 = {f"{OBS}.2": OBS_CONDICIONAL_2}
    assert rev.revisar_correccion(c, t2, e)
    antes = _filas(rev, c)
    with pytest.raises(AdvertenciasSinConfirmar):
        rev.corregir(c, ANALISTA, t2, confirmadas=(), entrada=e)
    assert _filas(rev, c) == antes and len(rev.versiones(c)) == 2
    t3 = {f"{OBS}.1": "Según laestrella.com.pa, Mulino podría firmar convenios con Vietnam."}   # la misma oración, otro texto
    with pytest.raises(AdvertenciasSinConfirmar):
        rev.corregir(c, ANALISTA, t3, confirmadas=(), entrada=e)


# ============================================================================================ X75 · el límite del resumen se avisa una vez


def test_el_limite_del_resumen_se_avisa_una_sola_vez_y_en_la_oracion_editada() -> None:
    relleno = " ".join(["palabra"] * 170)
    lista = avisos({f"{OBS}.0": f"El medio prensa-latina.cu reporta que el Presidente panameño visitará Singapur y Vietnam. {relleno}"})
    limites = [a for a in lista if a.mensaje.startswith("[limite_palabras]")]
    assert len(limites) == 1, limites
    assert limites[0].clave == f"{OBS}.0"
    lista = avisos({f"{HIP}.0": f"{HIP_VALIDA} {relleno}"})
    limites = [a for a in lista if a.mensaje.startswith("[limite_palabras]")]
    assert [a.clave for a in limites] == [f"{HIP}.0"]


# ============================================================================================ el historial muestra el rótulo de la sección


def test_el_historial_exportado_rotula_el_texto_corregido_como_el_selector(rev) -> None:
    c = _caso(rev)
    rev.corregir(c, ANALISTA, {f"{HIP}.0": HIP_VALIDA}, entrada=entrada())
    md = exportar.a_markdown(rev, c, rev.ficha_del_caso(rev.caso(c)))
    rotulo = ui.rotulo_de_elemento(f"{HIP}.0", cargar_interfaz().paquete.etiquetas)
    assert rotulo == "Resumen · Hipótesis de impacto · 1"
    assert f"Versión 2 · {rotulo}" in md
    assert "hipotesis\\_impacto.0" not in md and "hipotesis_impacto.0" not in md
