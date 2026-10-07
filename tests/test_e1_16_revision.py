"""E1-16 · Revisión humana, versiones y exportación a Notion (D-46 a D-50).

Todo corre sin red ni modelo real: la base es la sintética de E1-10b, los embeddings son el codificador falso y el LLM es un
proveedor guionado. Una prueba por cada punto de «Listo cuando» de ``specs/E1-16.md``.
"""

from __future__ import annotations

import ast
import csv
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eval import revision as eval_revision
from src import db, embeddings, exportar
from src.configuracion import FORMAS_DE_PUBLICAR, RAIZ, cargar_revision
from src.esquemas import ESTADOS_DE_REVISION, RegistroFichasJsonl
from src.generacion import Generador, generar
from src.revision import (
    AdvertenciasSinConfirmar,
    ErrorDeRevision,
    MotivoObligatorio,
    RevisorDesconocido,
    Revisiones,
    TransicionNoPermitida,
    aplicar_ediciones,
    elementos_editables,
)
from tests import ficha_ayuda as h
from tests import generacion_ayuda as ga
from tests.motor_falso import MotorFalso, config_de_prueba

CFG = cargar_revision()
ID_OFICIAL = "IND-PAN-FP.CPI.TOTL.ZG-2024"
ID_COL = "IND-COL-FP.CPI.TOTL.ZG-2024"
EDITORIAL = "Javier Acosta"
ROL_EDITORIAL = "Revisión editorial"
# Propiedades de la base «Casos y evidencias» de Notion (colección 69e5689f-…), menos las fórmulas P y Rango. Leídas de Notion el 2026-10-06.
COLUMNAS_NOTION = [
    "ID caso", "Modalidad", "Tema", "Caso de uso", "Estado de revisión", "Estado de evidencia", "Acción recomendada", "R", "I", "U", "N", "E",
    "Versión de reglas", "Versión del borrador", "Alcance del texto", "Qué se reporta", "Quién lo reporta", "Qué está respaldado",
    "Qué falta comprobar", "IDs de fuente", "Revisor", "Comentario del revisor", "Fecha de revisión", "Última exportación",
]
PROPIEDADES_NOTION = {*COLUMNAS_NOTION, "P", "Rango"}


# ------------------------------------------------------------------ base y proveedor de prueba


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base(tmp_path_factory, emb) -> Path:
    return h.construir(tmp_path_factory.mktemp("rev") / "senales.duckdb", emb)


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch, emb):
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)


def _reloj():
    t = {"n": 0}

    def ahora() -> datetime:
        t["n"] += 1
        return datetime(2026, 10, 6, 14, 0, tzinfo=UTC) + timedelta(minutes=t["n"])

    return ahora


@pytest.fixture
def rev(tmp_path, base) -> Revisiones:
    return Revisiones(tmp_path / "revision.duckdb", base, ahora=_reloj())


def _cita(id_: str, campo: str) -> dict[str, str]:
    return {"id": id_, "campo": campo}


AFIRMACIONES = {"afirmaciones": [
    {"id": "A1", "tipo": "declaración", "texto": "La Prensa Ejemplo reporta que la inflación se mantiene estable en Panamá", "citas": [_cita("NOT-c000000001", "titulo_limpio")], "base": []},
    {"id": "A2", "tipo": "declaración", "texto": "TVN Panamá reporta inflación estable", "citas": [_cita("NOT-c000000002", "titulo_limpio")], "base": []},
    {"id": "A3", "tipo": "hecho", "texto": "La inflación de Panamá fue de 0.69 % anual en 2024", "citas": [_cita(ID_OFICIAL, "valor")], "base": []},
    {"id": "A4", "tipo": "inferencia", "texto": "Lo que reportan los medios es consistente con el dato anual de 0.69 % de 2024", "citas": [], "base": ["A1", "A3"]},
]}


FRASE = "Según reporta La Prensa Ejemplo, la inflación se mantiene estable en Panamá esta semana"
SECCIONES = {
    "titulo": {
        "titulo": ga._o("TVN Panamá reporta inflación estable", "A2"),
        "titulares": [ga._o("TVN Panamá reporta inflación estable en Panamá", "A2"), ga._o("La Prensa Ejemplo reporta inflación estable", "A1")],
        "copy_digital": [ga._o("TVN Panamá reporta inflación estable. #Panamá", "A2")],
    },
    "brief": {
        "brief": [ga._o("La Prensa Ejemplo reporta que la inflación se mantiene estable en Panamá.", "A1"), ga._o("La inflación de Panamá fue de 0.69 % anual en 2024.", "A3")],
        "enfoque": [ga._o("Lo que reportan los medios podría ser consistente con el dato anual de 0.69 % de 2024.", "A4")],
        "preguntas": [],
    },
    "guion": {"guion": [
        *(ga._o(FRASE + ".", "A1", parte=p) for p in ("entrada", "entrada", "desarrollo")),
        ga._o(ga.MARCADOR, parte="desarrollo"),
        *(ga._o(FRASE + ".", "A1", parte=p) for p in ("desarrollo", "desarrollo", "desarrollo", "cierre", "cierre")),
    ]},
    "resumen_web": {"resumen_web": [ga._o("TVN Panamá reporta inflación estable.", "A2"), ga._o("La Prensa Ejemplo reporta que la inflación se mantiene estable en Panamá.", "A1")]},
}


def proveedor() -> ga.ProveedorGuionado:
    return ga.ProveedorGuionado(afirmaciones=AFIRMACIONES, **SECCIONES)


def generador_de_prueba(registro: list[Any] | None = None):
    """Cumple el contrato de ``generar_paquete``: arma el paquete con el proveedor guionado sobre la ``entrada`` que le pasa la revisión."""

    def generar_paquete(id_grupo: str, modalidad: str, *, solo_cache: bool = True, entrada: Any = None, **_: Any):
        if registro is not None:
            registro.append(entrada)
        g = Generador(entrada, proveedor())
        g.generar_todo()
        paquete = g.paquete()
        assert paquete is not None
        return paquete

    return generar_paquete


def abrir(rev: Revisiones, grupo: str = h.G_COMPLETO, con_borrador: bool = True, modalidad: str = "editorial", revisor: str = EDITORIAL):
    caso = rev.abrir(grupo, modalidad, revisor)
    if con_borrador:
        rev.regenerar(caso.id_caso, revisor, generador=generador_de_prueba())
    return caso


def contenido(rev: Revisiones, id_caso: str) -> dict[str, Any]:
    return rev.version_actual(id_caso).contenido


# ------------------------------------------------------------------ configuración


def test_la_configuracion_define_los_cinco_estados_y_ninguno_despues_de_aprobar() -> None:
    assert CFG.estados == list(ESTADOS_DE_REVISION) == ["nuevo", "en revisión", "requiere evidencia", "aprobado como borrador", "descartado"]
    assert CFG.acciones["aceptar"].etiqueta == "Aprobar como borrador" and CFG.acciones["aceptar"].hacia == "aprobado como borrador"
    assert not [a for a in CFG.acciones if FORMAS_DE_PUBLICAR.search(a) or FORMAS_DE_PUBLICAR.search(CFG.acciones[a].etiqueta)]
    assert not any(FORMAS_DE_PUBLICAR.search(e) for e in CFG.estados)
    assert all(a.hacia != "nuevo" for a in CFG.acciones.values())          # nadie vuelve a «nuevo»: el único estado sin fila


def test_las_transiciones_salen_solo_del_yaml() -> None:
    t = CFG.transiciones()
    assert t["abrir"] == {("nuevo", "en revisión")}
    assert t["aceptar"] == {("en revisión", "aprobado como borrador")}
    assert t["pedir_evidencia"] == {("en revisión", "requiere evidencia")}
    assert t["descartar"] == {("en revisión", "descartado"), ("requiere evidencia", "descartado")}
    assert t["corregir"] == {("en revisión", "en revisión")}
    assert {a for (a, _) in t["reabrir"]} == {"requiere evidencia", "aprobado como borrador", "descartado"}


def test_el_revisor_se_elige_de_la_lista_con_su_rol_y_la_limitacion_se_declara() -> None:
    roles = {(r.nombre, r.modalidad): r.rol for r in CFG.revisores}
    assert roles[(EDITORIAL, "editorial")] == ROL_EDITORIAL and roles[(EDITORIAL, "banca")] == "Analista"
    assert "Sin autenticación" in CFG.limitacion_revisor


# ------------------------------------------------------------------ casos: GRP- -> CASO- estable y persistente (D-63)


def test_abrir_un_grupo_crea_un_caso_correlativo_y_estable_que_persiste_entre_corridas(tmp_path, base) -> None:
    ruta = tmp_path / "revision.duckdb"
    a = Revisiones(ruta, base, ahora=_reloj())
    c1 = a.abrir(h.G_COMPLETO, "editorial", EDITORIAL)
    c2 = a.abrir(h.G_CIFRAS, "editorial", EDITORIAL)
    assert (c1.id_caso, c2.id_caso) == ("CASO-001", "CASO-002")
    otra = Revisiones(ruta, base, ahora=_reloj())                                  # otra corrida: la misma base en disco
    assert otra.abrir(h.G_COMPLETO, "editorial", EDITORIAL).id_caso == "CASO-001"  # abrir de nuevo devuelve el mismo caso
    assert otra.abrir(h.G_SISMO, "editorial", EDITORIAL).id_caso == "CASO-003"
    assert [c.id_grupo for c in otra.casos()] == [h.G_COMPLETO, h.G_CIFRAS, h.G_SISMO]
    assert len(otra.historial("CASO-001")) == 1                                    # reabrir el mismo grupo no agrega filas


def test_un_grupo_sin_caso_esta_en_nuevo(rev) -> None:
    assert rev.estado_de_grupo(h.G_COMPLETO, "editorial") == "nuevo" and rev.casos() == [] and not rev.ruta.exists()
    caso = rev.abrir(h.G_COMPLETO, "editorial", EDITORIAL)
    assert rev.estado_de_grupo(h.G_COMPLETO, "editorial") == "en revisión" and rev.estado(caso.id_caso) == "en revisión"


def test_el_revisor_fuera_de_la_lista_se_rechaza(rev) -> None:
    with pytest.raises(RevisorDesconocido):
        rev.abrir(h.G_COMPLETO, "editorial", "Alguien Más")
    assert rev.casos() == []


# ------------------------------------------------------------------ Listo cuando 1: acciones -> estados y transiciones


def test_cada_accion_produce_el_estado_correcto(rev) -> None:
    c = abrir(rev).id_caso
    assert rev.estado(c) == "en revisión"
    rev.corregir(c, EDITORIAL, {"afirmaciones.A2": "TVN Panamá reporta que la inflación se mantiene estable"})
    assert rev.estado(c) == "en revisión"                                            # corregir: nueva versión, sigue en revisión
    rev.pedir_evidencia(c, EDITORIAL, ["sin_dato_oficial"], "falta el dato")
    assert rev.estado(c) == "requiere evidencia"
    assert rev.historial(c)[-1].detalle == {"vacios": ["sin_dato_oficial"]}           # con vínculo a los vacíos
    rev.reabrir(c, EDITORIAL, "llegó el dato oficial")
    assert rev.estado(c) == "en revisión"
    rev.aceptar(c, EDITORIAL)
    assert rev.estado(c) == "aprobado como borrador"
    rev.reabrir(c, EDITORIAL, "una cifra estaba mal")
    rev.descartar(c, EDITORIAL, "Sin evidencia suficiente")
    assert rev.estado(c) == "descartado"
    rev.reabrir(c, EDITORIAL, "se reconsidera")
    assert [f.estado_nuevo for f in rev.historial(c)][-1] == "en revisión"


def _aplicar(rev: Revisiones, c: str, accion: str) -> Any:
    """Cada acción con argumentos válidos, para probar solo la transición."""
    return {
        "abrir": lambda: rev.abrir(h.G_COMPLETO, "editorial", EDITORIAL),
        "aceptar": lambda: rev.aceptar(c, EDITORIAL),
        "corregir": lambda: rev.corregir(c, EDITORIAL, {"afirmaciones.A2": "TVN Panamá reporta que el país mantiene la inflación estable"}),
        "regenerar": lambda: rev.regenerar(c, EDITORIAL, generador=generador_de_prueba()),
        "pedir_evidencia": lambda: rev.pedir_evidencia(c, EDITORIAL, ["sin_dato_oficial"]),
        "descartar": lambda: rev.descartar(c, EDITORIAL, "Duplicado de otro caso"),
        "reabrir": lambda: rev.reabrir(c, EDITORIAL, "motivo"),
        "rechazar_vinculo": lambda: rev.rechazar_vinculo(c, EDITORIAL, ID_COL, "mal aplicado"),
        "restaurar_vinculo": lambda: rev.restaurar_vinculo(c, EDITORIAL, ID_COL, "se restaura"),
    }[accion]()


def _llevar_a(rev: Revisiones, estado: str) -> str:
    c = abrir(rev).id_caso
    if estado == "requiere evidencia":
        rev.pedir_evidencia(c, EDITORIAL, ["sin_dato_oficial"])
    elif estado == "aprobado como borrador":
        rev.aceptar(c, EDITORIAL)
    elif estado == "descartado":
        rev.descartar(c, EDITORIAL, "Duplicado de otro caso")
    assert rev.estado(c) == estado
    return c


CASOS_NO_PERMITIDOS = [
    (accion, estado)
    for accion, a in CFG.acciones.items() if accion != "abrir"
    for estado in CFG.estados[1:] if estado not in a.desde
]


@pytest.mark.parametrize(("accion", "estado"), CASOS_NO_PERMITIDOS)
def test_las_transiciones_que_no_estan_en_el_yaml_se_rechazan_sin_escribir_nada(rev, accion, estado) -> None:
    c = _llevar_a(rev, estado)
    antes = rev.historial(c)
    versiones = len(rev.versiones(c))
    with pytest.raises(TransicionNoPermitida):
        _aplicar(rev, c, accion)
    assert rev.historial(c) == antes and len(rev.versiones(c)) == versiones and rev.estado(c) == estado


def test_el_estado_nuevo_solo_admite_abrir(rev) -> None:
    c = rev.abrir(h.G_COMPLETO, "editorial", EDITORIAL).id_caso
    assert all(("nuevo", a.hacia) not in {(d, a.hacia) for d in a.desde} for n, a in CFG.acciones.items() if n != "abrir")
    assert rev.estado(c) == "en revisión"


# ------------------------------------------------------------------ Listo cuando 2: descartar sin motivo


@pytest.mark.parametrize("motivo", [None, "", "   ", "porque sí", "sin evidencia suficiente"])
def test_descartar_sin_motivo_de_la_lista_se_rechaza(rev, motivo) -> None:
    c = abrir(rev).id_caso
    antes = rev.historial(c)
    with pytest.raises(MotivoObligatorio):
        rev.descartar(c, EDITORIAL, motivo)
    assert rev.historial(c) == antes and rev.estado(c) == "en revisión"


def test_descartar_con_motivo_de_la_lista_queda_registrado_y_otro_exige_comentario(rev) -> None:
    c = abrir(rev).id_caso
    with pytest.raises(MotivoObligatorio):
        rev.descartar(c, EDITORIAL, "Otro")
    with pytest.raises(MotivoObligatorio):
        rev.descartar(c, EDITORIAL, "Otro", "   ")
    f = rev.descartar(c, EDITORIAL, "Otro", "No es del alcance de este tramo")
    assert (f.motivo, f.estado_nuevo, f.comentario) == ("Otro", "descartado", "No es del alcance de este tramo")
    assert {m for m in CFG.motivos_descarte} >= {"Sin evidencia suficiente", "Duplicado de otro caso"}


def test_reabrir_sin_motivo_se_rechaza(rev) -> None:
    c = abrir(rev).id_caso
    rev.aceptar(c, EDITORIAL)
    with pytest.raises(MotivoObligatorio):
        rev.reabrir(c, EDITORIAL, " ")
    assert rev.estado(c) == "aprobado como borrador"


# ------------------------------------------------------------------ Listo cuando 3: el registro solo crece (D-47)


def test_la_tabla_revisiones_solo_crece_y_ninguna_fila_se_modifica(rev) -> None:
    c = rev.abrir(h.G_COMPLETO, "editorial", EDITORIAL).id_caso
    rev.regenerar(c, EDITORIAL, generador=generador_de_prueba())
    pasos = [
        lambda: rev.corregir(c, EDITORIAL, {"afirmaciones.A2": "TVN Panamá reporta que el país mantiene la inflación estable"}),
        lambda: rev.pedir_evidencia(c, EDITORIAL, ["sin_dato_oficial"]),
        lambda: rev.reabrir(c, EDITORIAL, "llegó el dato"),
        lambda: rev.rechazar_vinculo(c, EDITORIAL, ID_COL, "otro país"),
        lambda: rev.aceptar(c, EDITORIAL, "ok"),
        lambda: rev.reabrir(c, EDITORIAL, "revisar de nuevo"),
        lambda: rev.descartar(c, EDITORIAL, "Duplicado de otro caso"),
    ]
    anteriores = rev.todas_las_filas()
    versiones_previas = rev.versiones(c)
    for paso in pasos:
        paso()
        ahora = rev.todas_las_filas()
        assert len(ahora) == len(anteriores) + 1                                     # solo crece, de a una fila
        assert ahora[: len(anteriores)] == anteriores                                # y ninguna fila previa cambió
        assert [f.id_revision for f in ahora] == list(range(1, len(ahora) + 1))
        anteriores = ahora
    assert rev.versiones(c)[: len(versiones_previas)] == versiones_previas           # las versiones tampoco se editan
    assert rev.estado(c) == anteriores[-1].estado_nuevo == "descartado"              # el estado es la última fila


def test_una_accion_rechazada_no_deja_ni_una_fila_a_medias(rev) -> None:
    c = abrir(rev).id_caso
    n_filas, n_versiones = len(rev.todas_las_filas()), len(rev.versiones(c))
    with pytest.raises(AdvertenciasSinConfirmar):
        rev.corregir(c, EDITORIAL, {"afirmaciones.A2": "TVN Panamá reporta que hubo 77 incidentes"})
    assert (len(rev.todas_las_filas()), len(rev.versiones(c))) == (n_filas, n_versiones)


def test_la_api_no_tiene_ni_una_sentencia_de_modificar_o_borrar() -> None:
    """El registro es de solo agregar a nivel de la API: ningún SQL de ``src/revision.py`` ni ``src/exportar.py`` actualiza ni borra."""
    prohibidas = re.compile(r"^\s*(UPDATE|DELETE|DROP|TRUNCATE|ALTER|REPLACE|INSERT OR REPLACE)\b", re.IGNORECASE)
    for nombre in ("revision.py", "exportar.py"):
        arbol = ast.parse((RAIZ / "src" / nombre).read_text(encoding="utf-8"))
        cadenas = [n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        sql = [
            n.args[0].value for n in ast.walk(arbol)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"execute", "executemany"}
            and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
        ]
        assert (sql or nombre == "exportar.py") and not [s for s in [*sql, *cadenas] if prohibidas.search(s)], nombre
    publicos = {n for n in dir(Revisiones) if not n.startswith("_")}
    assert not {n for n in publicos if re.match(r"(editar|modificar|actualizar|borrar|eliminar|update|delete|remove)", n)}


# ------------------------------------------------------------------ Listo cuando 4: corrección revalidada (D-48)


def test_una_correccion_con_un_dato_sin_cita_genera_advertencia_y_queda_registrada_si_se_confirma(rev) -> None:
    c = abrir(rev).id_caso
    v1 = contenido(rev, c)
    ediciones = {"afirmaciones.A2": "TVN Panamá reporta inflación estable y 77 comercios cerrados"}
    avisos = rev.revisar_correccion(c, ediciones)
    assert [a.clave for a in avisos] == ["afirmaciones.A2"] and "77" in avisos[0].mensaje        # el dato sin cita
    with pytest.raises(AdvertenciasSinConfirmar) as e:
        rev.corregir(c, EDITORIAL, ediciones)                                                    # sin confirmar: se rechaza
    assert [a.id for a in e.value.advertencias] == [a.id for a in avisos] and len(rev.versiones(c)) == 1
    v2 = rev.corregir(c, EDITORIAL, ediciones, confirmadas=[a.id for a in avisos], comentario="la editora lo confirma")
    assert (v2.version, v2.origen, v2.version_base) == (2, "corregida", 1)
    fila = rev.historial(c)[-1]
    assert fila.accion == "corregir" and fila.version == 2 and fila.estado_nuevo == "en revisión"
    assert fila.detalle["advertencias_confirmadas"] == [a.id for a in avisos]                   # la confirmación queda registrada
    assert fila.diferencias == [{"clave": "afirmaciones.A2", "antes": "TVN Panamá reporta inflación estable", "despues": ediciones["afirmaciones.A2"]}]
    assert (fila.detalle["afirmaciones_editadas"], fila.detalle["n_afirmaciones"]) == (1, 4)
    assert contenido(rev, c) != v1 and rev.versiones(c)[0].contenido == v1                       # se guardan la original y la corregida
    assert contenido(rev, c)["version"] == 2 and contenido(rev, c)["id_caso"] == c


def test_una_correccion_sin_advertencias_no_pide_confirmacion(rev) -> None:
    c = abrir(rev).id_caso
    ediciones = {"afirmaciones.A2": "TVN Panamá reporta que el país mantiene la inflación estable"}
    assert rev.revisar_correccion(c, ediciones) == []
    v = rev.corregir(c, EDITORIAL, ediciones)
    assert v.version == 2 and rev.historial(c)[-1].detalle["advertencias_confirmadas"] == []


@pytest.mark.parametrize(
    ("clave", "texto", "esperado"),
    [
        ("afirmaciones.A1", "La Prensa Ejemplo reporta que «la inflación se disparó sin control»", "comillas"),          # comilla inventada
        ("afirmaciones.A3", "La inflación de Panamá fue de 0.69 % anual", "año"),                                       # dato anual sin su año
        ("afirmaciones.A2", "TVN Panamá reporta un impactante dato de inflación estable", "frase prohibida"),           # léxico prohibido (D-25)
        ("afirmaciones.A4", "Lo que reportan los medios es consistente con el 5 % de 2024", "cifra"),                  # una inferencia no trae cifras nuevas
        ("afirmaciones.A1", "Según DEEPSEEK_API_KEY la inflación está estable", None),                                  # no debe romper
    ],
)
def test_la_revalidacion_usa_las_reglas_del_validador(rev, clave, texto, esperado) -> None:
    c = abrir(rev).id_caso
    avisos = rev.revisar_correccion(c, {clave: texto})
    if esperado is None:
        return
    assert avisos and esperado in " ".join(a.mensaje for a in avisos).lower()


def test_corregir_una_afirmacion_revisa_tambien_las_que_se_apoyan_en_ella(rev) -> None:
    c = abrir(rev).id_caso
    avisos = rev.revisar_correccion(c, {"afirmaciones.A3": "La inflación de Panamá fue de 9.99 % anual en 2024"})
    assert {a.clave for a in avisos} >= {"afirmaciones.A3", "afirmaciones.A4"}


def test_una_correccion_sin_cambios_o_con_clave_desconocida_se_rechaza(rev) -> None:
    c = abrir(rev).id_caso
    actual = elementos_editables(contenido(rev, c))["afirmaciones.A2"].texto
    with pytest.raises(ErrorDeRevision):
        rev.corregir(c, EDITORIAL, {"afirmaciones.A2": actual})
    with pytest.raises(ErrorDeRevision):
        rev.corregir(c, EDITORIAL, {"afirmaciones.A99": "x"})
    with pytest.raises(AdvertenciasSinConfirmar):
        rev.corregir(c, EDITORIAL, {"afirmaciones.A2": "  "})                          # un texto vacío tampoco pasa sin confirmar
    assert len(rev.versiones(c)) == 1


def test_sin_borrador_no_hay_nada_que_corregir(rev) -> None:
    c = rev.abrir(h.G_COMPLETO, "editorial", EDITORIAL).id_caso
    with pytest.raises(ErrorDeRevision, match="borrador"):
        rev.corregir(c, EDITORIAL, {"afirmaciones.A1": "x"})


def test_el_original_no_se_toca_al_aplicar_ediciones(rev) -> None:
    c = abrir(rev).id_caso
    original = contenido(rev, c)
    nuevo = aplicar_ediciones(original, {"afirmaciones.A1": "otro texto"})
    assert nuevo != original and elementos_editables(original)["afirmaciones.A1"].texto != "otro texto"


def test_las_oraciones_del_paquete_tambien_se_corrigen_y_se_revalidan(rev) -> None:
    c = abrir(rev).id_caso
    editables = elementos_editables(contenido(rev, c))
    assert {"titulo", "titulares.0", "brief.0", "guion.0"} <= set(editables) and not any(e.texto.startswith("[VISUAL") for e in editables.values())
    avisos = rev.revisar_correccion(c, {"titulares.0": "TVN Panamá reporta inflación estable en Panamá, con 123 barcos"})
    assert [a.clave for a in avisos] == ["titulares.0"] and "cifra_no_coincide" in avisos[0].mensaje and "123" in avisos[0].mensaje   # el rechazo del validador
    nuevo = "TVN Panamá reporta que la inflación sigue estable en Panamá"
    assert rev.revisar_correccion(c, {"titulares.0": nuevo}) == []
    v = rev.corregir(c, EDITORIAL, {"titulares.0": nuevo})
    assert v.contenido["titulares"][0]["texto"] == nuevo and v.contenido["titulares"][0]["afirmaciones"] == ["A2"]
    assert rev.historial(c)[-1].detalle["afirmaciones_editadas"] == 0                                 # editó una oración, no una afirmación


def test_la_revalidacion_llama_al_validador_y_no_a_las_funciones_privadas_de_la_generacion() -> None:
    codigo = (RAIZ / "src" / "revision.py").read_text(encoding="utf-8")
    assert "validador" in codigo and "validar_afirmaciones" in codigo and "validar_seccion" in codigo
    assert "_errores_de_afirmacion" not in codigo and "_Contexto" not in codigo and "TODO(E1-13)" not in codigo
    assert "advertencia_numero" not in (RAIZ / "config" / "revision.yaml").read_text(encoding="utf-8")       # ya no hay regla local de cifras


def test_las_advertencias_son_los_rechazos_del_validador_con_su_regla(rev) -> None:
    c = abrir(rev).id_caso
    avisos = rev.revisar_correccion(c, {"afirmaciones.A3": "La inflación de Panamá fue de 9.99 % anual en 2024"})
    assert any(a.clave == "afirmaciones.A3" and a.mensaje.startswith("[cifra_no_coincide]") for a in avisos)
    assert any(a.clave == "afirmaciones.A4" for a in avisos)                       # la inferencia que se apoya en A3 ya no cabe


def test_las_oraciones_se_revalidan_con_las_frases_prohibidas(rev) -> None:
    c = abrir(rev).id_caso
    avisos = rev.revisar_correccion(c, {"brief.0": "TVN Panamá reporta un escándalo en el Canal"})
    assert any("frase prohibida" in a.mensaje for a in avisos)


def test_el_marcador_visual_del_guion_no_se_edita(rev) -> None:
    c = abrir(rev).id_caso
    guion = contenido(rev, c)["guion"]
    i = next(i for i, o in enumerate(guion) if o["texto"].startswith("[VISUAL"))
    with pytest.raises(ErrorDeRevision):
        rev.corregir(c, EDITORIAL, {f"guion.{i}": "[VISUAL: un video que inventé]"})


# ------------------------------------------------------------------ Listo cuando 5: regenerar no pisa lo corregido


def test_regenerar_despues_de_corregir_crea_una_version_nueva_y_conserva_la_corregida(rev) -> None:
    c = abrir(rev).id_caso
    rev.corregir(c, EDITORIAL, {"afirmaciones.A2": "TVN Panamá reporta que el país mantiene la inflación estable"})
    corregida = rev.version_actual(c)
    assert corregida.version == 2
    v3 = rev.regenerar(c, EDITORIAL, generador=generador_de_prueba())
    assert (v3.version, v3.origen, v3.version_base) == (3, "generada", 2)
    versiones = rev.versiones(c)
    assert [(v.version, v.origen) for v in versiones] == [(1, "generada"), (2, "corregida"), (3, "generada")]
    assert versiones[1] == corregida                                                  # la corregida sigue intacta
    assert elementos_editables(versiones[1].contenido)["afirmaciones.A2"].texto == "TVN Panamá reporta que el país mantiene la inflación estable"
    assert elementos_editables(versiones[2].contenido)["afirmaciones.A2"].texto == "TVN Panamá reporta inflación estable"
    assert [f.accion for f in rev.historial(c)] == ["abrir", "regenerar", "corregir", "regenerar"]
    assert versiones[2].contenido["id_caso"] == c and versiones[2].contenido["version"] == 3


def test_regenerar_sin_borrador_en_cache_no_escribe_nada(rev) -> None:
    from src.cache import SinBorrador

    c = abrir(rev, con_borrador=False).id_caso
    filas = len(rev.todas_las_filas())

    def sin_cache(*a: Any, **k: Any) -> Any:
        raise SinBorrador("no hay borrador en caché")

    with pytest.raises(SinBorrador):
        rev.regenerar(c, EDITORIAL, generador=sin_cache)
    assert len(rev.todas_las_filas()) == filas and rev.versiones(c) == []


# ------------------------------------------------------------------ Listo cuando 6: vínculo oficial rechazado


def test_un_vinculo_rechazado_no_aparece_en_el_borrador_regenerado(rev) -> None:
    c = abrir(rev).id_caso
    assert any(ID_OFICIAL in str(a["citas"]) for a in contenido(rev, c)["afirmaciones"])        # antes: la afirmación del dato oficial existe
    rev.rechazar_vinculo(c, EDITORIAL, ID_OFICIAL, "mide otro período", "el dato no corresponde al hecho")
    f = rev.historial(c)[-1]
    assert (f.accion, f.estado_nuevo, f.detalle, f.motivo) == ("rechazar_vinculo", "en revisión", {"id_evidencia": ID_OFICIAL}, "mide otro período")
    assert rev.vinculos_rechazados(c) == {ID_OFICIAL}
    entradas: list[Any] = []
    v = rev.regenerar(c, EDITORIAL, generador=generador_de_prueba(entradas))
    assert ID_OFICIAL not in {r.id for r in entradas[0].registros}                               # ni la ficha ni la entrada lo traen
    assert all(ID_OFICIAL not in json.dumps(a, ensure_ascii=False) for a in v.contenido["afirmaciones"])
    assert ID_OFICIAL not in json.dumps({k: x for k, x in v.contenido.items() if k != "vacios"}, ensure_ascii=False)
    assert any("A3" not in a["id"] for a in v.contenido["afirmaciones"]) and len(v.contenido["afirmaciones"]) < 4
    assert ID_OFICIAL in json.dumps(rev.versiones(c)[0].contenido, ensure_ascii=False)          # la versión anterior se conserva tal cual
    assert f.detalle and rev.historial(c)[-1].detalle["vinculos_excluidos"] == [ID_OFICIAL]
    ficha = rev.ficha_del_caso(rev.caso(c))
    assert ID_OFICIAL not in json.dumps(ficha.respaldado.model_dump(mode="json"))
    assert ficha.falta_comprobar.principales[0].codigo == CFG.vinculo_rechazado.codigo           # y la ficha dice por qué falta ese dato


def test_se_puede_restaurar_un_vinculo_rechazado_y_queda_en_el_registro(rev) -> None:
    c = abrir(rev).id_caso
    rev.rechazar_vinculo(c, EDITORIAL, ID_OFICIAL, "mal aplicado")
    rev.restaurar_vinculo(c, EDITORIAL, ID_OFICIAL, "fue un error")
    assert rev.vinculos_rechazados(c) == set() and [f.accion for f in rev.historial(c)][-2:] == ["rechazar_vinculo", "restaurar_vinculo"]
    with pytest.raises(ErrorDeRevision):
        rev.restaurar_vinculo(c, EDITORIAL, ID_OFICIAL, "otra vez")
    with pytest.raises(MotivoObligatorio):
        rev.rechazar_vinculo(c, EDITORIAL, ID_OFICIAL, "")
    with pytest.raises(ErrorDeRevision):
        rev.rechazar_vinculo(c, EDITORIAL, "NOT-c000000001", "un titular no es un vínculo oficial")


# ------------------------------------------------------------------ banca: la misma lógica, el revisor es el analista


def test_banca_usa_la_misma_logica_con_el_analista_como_revisor(tmp_path, emb) -> None:
    base_banca = h.construir(tmp_path / "banca.duckdb", emb, modalidad="banca")      # una base solo guarda una modalidad a la vez (X39)
    rev = Revisiones(tmp_path / "revision_banca.duckdb", base_banca, ahora=_reloj())
    caso = rev.abrir(h.G_COMPLETO, "banca", "Juan Zhou")
    assert rev.historial(caso.id_caso)[0].rol == "Analista"
    with pytest.raises(db.ModalidadDistinta):
        rev.abrir(h.G_COMPLETO, "editorial", "Juan Zhou")
    rev.aceptar(caso.id_caso, "Juan Zhou")
    assert rev.estado(caso.id_caso) == "aprobado como borrador"
    with pytest.raises(TransicionNoPermitida):
        rev.aceptar(caso.id_caso, "Juan Zhou")


# ------------------------------------------------------------------ Listo cuando 7: fichas.jsonl


def test_cada_linea_de_fichas_jsonl_valida_contra_el_esquema_del_contrato(rev, tmp_path) -> None:
    c1 = abrir(rev).id_caso
    c2 = abrir(rev, h.G_CIFRAS, con_borrador=False).id_caso
    rev.aceptar(c1, EDITORIAL)
    rev.descartar(c2, EDITORIAL, "Sin evidencia suficiente")
    ruta = tmp_path / "fichas.jsonl"
    assert exportar.escribir_fichas_jsonl(rev, ruta) == 2
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 2
    for linea, c, estado in zip(lineas, (c1, c2), ("aprobado como borrador", "descartado"), strict=True):
        r = json.loads(linea)
        RegistroFichasJsonl.model_validate(r)
        for campo in ("id_caso", "modalidad", "ids_fuente", "afirmaciones", "citas", "puntaje", "componentes", "estado_evidencia", "borrador", "estado_revision"):
            assert campo in r
        assert (r["id_caso"], r["estado_revision"], r["borrador"]) == (c, estado, True)
        assert r["estado_revision"] == rev.estado(c) == rev.historial(c)[-1].estado_nuevo               # estado = última fila de revisiones
        assert r["alcance"] and "basado" in r["alcance"] and r["ficha"]["marca_borrador"] == "BORRADOR · requiere revisión"


def test_el_esquema_del_contrato_rechaza_lo_que_no_es_del_contrato(rev, tmp_path) -> None:
    from pydantic import ValidationError

    c = abrir(rev).id_caso
    ficha = rev.ficha_del_caso(rev.caso(c))
    bueno = exportar.registro_jsonl(rev, c, ficha)
    RegistroFichasJsonl.model_validate(bueno)
    for malo in (
        {**bueno, "id_caso": "GRP-completo"}, {**bueno, "id_caso": None}, {**bueno, "estado_revision": None}, {**bueno, "estado_revision": "publicado"},
        {**bueno, "borrador": False}, {**bueno, "campo_inventado": 1}, {k: v for k, v in bueno.items() if k != "citas"}, {**bueno, "estado_evidencia": "alto"},
        {**bueno, "componentes": {"R": 0.5}},
    ):
        with pytest.raises(ValidationError):
            RegistroFichasJsonl.model_validate(malo)


def test_el_estado_del_esquema_son_los_del_yaml() -> None:
    assert list(ESTADOS_DE_REVISION) == CFG.estados


# ------------------------------------------------------------------ Listo cuando 8: exportación a Notion (D-50)


def test_las_columnas_del_csv_son_las_de_la_base_casos_y_evidencias_de_notion() -> None:
    assert CFG.exportacion.columnas == COLUMNAS_NOTION and len(set(COLUMNAS_NOTION) | {"P", "Rango"}) == len(PROPIEDADES_NOTION) == 26


def test_exportar_genera_markdown_y_fila_csv_con_version_historial_y_leyenda(rev, tmp_path) -> None:
    c = abrir(rev).id_caso
    rev.corregir(c, EDITORIAL, {"afirmaciones.A2": "TVN Panamá reporta que el país mantiene la inflación estable"}, comentario="se afinó la redacción")
    rev.aceptar(c, EDITORIAL, "listo como borrador")
    e = exportar.exportar_caso(rev, c, tmp_path / "notion", tmp_path / "fichas.jsonl")
    md = e.ruta_markdown.read_text(encoding="utf-8")
    assert e.ruta_markdown.name == f"{c}.md" and md == e.markdown and md.startswith(f"# {c} · Ficha de evidencia")
    assert "BORRADOR · requiere revisión" in md and "Estado de revisión: aprobado como borrador" in md        # aprobada y todavía BORRADOR
    assert "Versión del borrador: versión 2 (corregida)" in md
    for seccion in ("1 · Qué se reporta", "2 · Quién lo reporta", "3 · Qué está respaldado", "4 · Qué falta comprobar", "5 · Acción recomendada", "## Historial de revisión"):
        assert seccion in md
    assert "basado únicamente en titular/metadatos" in md                                                     # la leyenda de alcance (D-51)
    assert all(a in md for a in ("abrir", "regenerar", "corregir", "aceptar")) and "listo como borrador" in md and "Javier Acosta (Revisión editorial)" in md
    assert "Antes: TVN Panamá reporta inflación estable" in md and "Después: TVN Panamá reporta que el país mantiene la inflación estable" in md
    assert "hora de Panamá" in md and "Z" not in re.findall(r"\| \d+ \| ([^|]+) \|", md)[0]                     # el historial se lee en hora de Panamá
    with e.ruta_csv.open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
        f.seek(0)
        assert next(csv.reader(f)) == COLUMNAS_NOTION
    assert len(filas) == 1
    fila = filas[0]
    assert (fila["ID caso"], fila["Modalidad"], fila["Estado de revisión"], fila["Estado de evidencia"]) == (c, "Editorial", "Aprobado como borrador", "Suficiente")
    assert fila["Versión del borrador"] == "versión 2 (corregida)" and fila["Revisor"] == EDITORIAL and fila["Comentario del revisor"] == "listo como borrador"
    assert fila["Alcance del texto"] == "basado únicamente en titular/metadatos" and fila["Tema"] == "Economía"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", fila["Última exportación"]) and fila["Fecha de revisión"] == rev.historial(c)[-1].fecha_utc
    assert {k: float(fila[k]) for k in "RIUNE"} and ID_OFICIAL in fila["IDs de fuente"] and "NOT-c000000001" in fila["IDs de fuente"]
    assert fila["Qué se reporta"].startswith("Titular central:") and "Cita: IND-PAN-FP.CPI.TOTL.ZG-2024 · valor" in fila["Qué está respaldado"]


def test_exportar_dos_veces_actualiza_la_fila_y_no_la_duplica(rev, tmp_path) -> None:
    c = abrir(rev).id_caso
    otro = abrir(rev, h.G_CIFRAS, con_borrador=False).id_caso
    carpeta, jsonl = tmp_path / "notion", tmp_path / "fichas.jsonl"
    a = exportar.exportar_caso(rev, c, carpeta, jsonl)
    exportar.exportar_caso(rev, otro, carpeta, jsonl)
    assert a.actualizada is False
    rev.aceptar(c, EDITORIAL, "ahora sí")
    b = exportar.exportar_caso(rev, c, carpeta, jsonl)
    assert b.actualizada is True
    with b.ruta_csv.open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    assert [x["ID caso"] for x in filas] == [c, otro]                                                       # una fila por caso, en su sitio
    assert filas[0]["Estado de revisión"] == "Aprobado como borrador" and filas[0]["Comentario del revisor"] == "ahora sí"
    assert sorted(p.name for p in carpeta.iterdir()) == sorted([f"{c}.md", f"{otro}.md", "casos_y_evidencias.csv"])
    assert len(jsonl.read_text(encoding="utf-8").splitlines()) == 2


def test_exportar_un_caso_sin_abrir_se_rechaza(rev, tmp_path) -> None:
    with pytest.raises(ErrorDeRevision):
        exportar.exportar_caso(rev, "CASO-009", tmp_path / "n", tmp_path / "f.jsonl")


def test_el_markdown_escapa_los_textos_de_los_datos_y_del_revisor(rev, tmp_path) -> None:
    c = abrir(rev).id_caso
    rev.aceptar(c, EDITORIAL, "<script>alert(1)</script> | **negrita** [x](http://malo)")
    md = exportar.exportar_caso(rev, c, tmp_path / "n", tmp_path / "f.jsonl").markdown
    assert "<script>" not in md and "\\<script\\>" in md and "\\*\\*negrita\\*\\*" in md


def test_las_propiedades_largas_se_recortan_para_notion(rev, tmp_path) -> None:
    c = abrir(rev).id_caso
    e = exportar.exportar_caso(rev, c, tmp_path / "n", tmp_path / "f.jsonl")
    assert all(len(v) <= CFG.exportacion.max_caracteres_texto for v in e.fila.values())


def test_la_cli_exporta_el_caso(rev, tmp_path, capsys) -> None:
    c = abrir(rev).id_caso
    argv = ["--caso", c, "--revision", str(rev.ruta), "--base", str(rev.base_fichas), "--salida", str(tmp_path / "n"), "--fichas", str(tmp_path / "f.jsonl")]
    assert exportar.principal(argv) == 0
    assert f"{c}: exportado" in capsys.readouterr().out and (tmp_path / "n" / f"{c}.md").exists() and (tmp_path / "n" / "casos_y_evidencias.csv").exists()
    assert exportar.principal(argv) == 0 and "actualizado" in capsys.readouterr().out
    assert exportar.principal([*argv[:1], "CASO-099", *argv[2:]]) == 1


# ------------------------------------------------------------------ eval.revision


def _historia(rev: Revisiones) -> None:
    """Cinco casos: 2 aprobados (uno corregido), 2 descartados (motivos distintos) y 1 sin decidir."""
    g = [h.G_COMPLETO, h.G_CIFRAS, h.G_SISMO, h.G_SOLO, h.G_PERIODO]
    c = [abrir(rev, x, con_borrador=(x == h.G_COMPLETO)).id_caso for x in g]
    rev.corregir(c[0], EDITORIAL, {"afirmaciones.A2": "TVN Panamá reporta que el país mantiene la inflación estable"})
    rev.aceptar(c[0], EDITORIAL)
    rev.aceptar(c[1], EDITORIAL)
    rev.descartar(c[2], EDITORIAL, "Sin evidencia suficiente")
    rev.descartar(c[3], EDITORIAL, "Otro", "no aplica")


def test_eval_sin_datos_lo_dice_y_no_inventa_cifras(tmp_path) -> None:
    r = eval_revision.calcular(Revisiones(tmp_path / "vacia.duckdb", None, ahora=_reloj()))
    assert r["casos_abiertos"] == 0 and r["casos_decididos"] == 0
    for tasa in ("aceptacion", "correccion", "descarte"):
        assert r["tasas"][tasa]["n"] == 0 and r["tasas"][tasa]["proporcion"] is None and r["tasas"][tasa]["ic95"] is None
    assert r["afirmaciones_editadas"]["proporcion"] is None and r["motivos_descarte"] == {} and r["tiempo_por_caso_min"]["n"] == 0
    assert eval_revision.formatear(r).count(CFG.textos.sin_datos) >= 4


def test_eval_calcula_tasas_con_n_e_intervalo_y_los_motivos(rev) -> None:
    _historia(rev)
    r = eval_revision.calcular(rev)
    assert (r["casos_abiertos"], r["casos_decididos"]) == (5, 4)
    acep, desc, corr = r["tasas"]["aceptacion"], r["tasas"]["descarte"], r["tasas"]["correccion"]
    assert (acep["k"], acep["n"], acep["proporcion"]) == (2, 4, 0.5) and (desc["k"], desc["n"]) == (2, 4) and (corr["k"], corr["n"]) == (1, 4)
    assert 0 < acep["ic95"][0] < 0.5 < acep["ic95"][1] < 1                                                   # Wilson del 95 %
    assert r["motivos_descarte"] == {"Sin evidencia suficiente": 1, "Otro": 1}
    e = r["afirmaciones_editadas"]
    assert (e["k"], e["n"]) == (1, 4) and e["proporcion"] == 0.25 and e["ic95"] is not None
    t = r["tiempo_por_caso_min"]
    assert t["n"] == 4 and t["mediana"] > 0 and t["media"] > 0


def test_eval_la_cli_escribe_el_json_y_la_tabla(rev, tmp_path, capsys) -> None:
    _historia(rev)
    salida = tmp_path / "revision.json"
    assert eval_revision.principal(["--revision", str(rev.ruta), "--salida", str(salida)]) == 0
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["tasas"]["aceptacion"]["n"] == 4
    texto = capsys.readouterr().out
    assert "aceptación" in texto.lower() and "n = 4" in texto and "IC 95" in texto and "Sin evidencia suficiente" in texto


# ------------------------------------------------------------------ nada de publicar en el código nuevo


def test_ningun_archivo_nuevo_habla_de_publicar() -> None:
    for ruta in ("src/revision.py", "src/exportar.py", "templates/caso.md.j2", "config/revision.yaml", "eval/revision.py"):
        texto = (RAIZ / ruta).read_text(encoding="utf-8")
        assert not FORMAS_DE_PUBLICAR.search(re.sub(r"(nunca|ninguna|ningún|no existe|nada se)[^\n]*publicar[^\n]*", "", texto, flags=re.IGNORECASE)), ruta


def test_la_base_de_senales_no_cambia_al_revisar(rev, base) -> None:
    antes = db.contar_filas(db.conectar(base, solo_lectura=True), "grupos")
    abrir(rev)
    assert db.contar_filas(db.conectar(base, solo_lectura=True), "grupos") == antes
    assert rev.ruta.name == "revision.duckdb" and rev.ruta != base


def test_x71_eval_no_cuenta_la_aprobacion_del_asistente_como_juicio_humano(rev, tmp_path, capsys) -> None:
    """D-101/D-112: los casos que decidió un revisor provisional van aparte, con juicio_humano false y el aviso; nunca en la tasa humana."""
    asistente = "Asistente (provisional, D-101)"
    solo = eval_revision.calcular(_con_un_caso(rev, h.G_COMPLETO, asistente))
    assert solo["juicio_humano"] is True and solo["casos_decididos"] == 0 and solo["tasas"]["aceptacion"]["proporcion"] is None
    assert solo["casos_abiertos"] == 1 and solo["casos_decididos_provisionales"] == 1
    p = solo["provisionales"]
    assert p["juicio_humano"] is False and p["origen_juicio"].startswith("asistente_provisional") and "NO HUMANO" in p["aviso_origen"]
    assert (p["tasas"]["aceptacion"]["k"], p["tasas"]["aceptacion"]["n"]) == (1, 1) and p["tasas"]["aceptacion"]["ic95"] is not None
    texto = eval_revision.formatear(solo)
    assert texto.count("n = 0") >= 4 and "PROVISIONAL" in texto and "NO HUMANO" in texto
    assert "decididos por una persona: 0" in texto

    mixto = eval_revision.calcular(_con_un_caso(rev, h.G_CIFRAS, EDITORIAL))
    assert (mixto["casos_decididos"], mixto["casos_decididos_provisionales"]) == (1, 1)
    assert mixto["tasas"]["aceptacion"]["n"] == 1 and mixto["provisionales"]["tasas"]["aceptacion"]["n"] == 1 and mixto["juicio_humano"] is True

    salida = tmp_path / "revision.json"
    eval_revision.principal(["--revision", str(rev.ruta), "--salida", str(salida)])
    assert json.loads(salida.read_text(encoding="utf-8"))["provisionales"]["juicio_humano"] is False
    capsys.readouterr()


def test_x71_una_persona_que_reabre_y_decide_pasa_a_contar_como_humana(rev) -> None:
    asistente = "Asistente (provisional, D-101)"
    c = _con_un_caso(rev, h.G_COMPLETO, asistente)
    id_caso = rev.casos()[0].id_caso
    rev.reabrir(id_caso, EDITORIAL, "Rehecha por una persona")
    rev.aceptar(id_caso, EDITORIAL)
    r = eval_revision.calcular(c)
    assert r["casos_decididos"] == 1 and r["casos_decididos_provisionales"] == 0 and "provisionales" not in r


def _con_un_caso(rev: Revisiones, grupo: str, revisor: str) -> Revisiones:
    caso = abrir(rev, grupo, revisor=revisor)
    rev.aceptar(caso.id_caso, revisor)
    return rev
