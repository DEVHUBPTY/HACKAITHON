"""C-11: formato de la hoja de preetiquetado (`eval/preetiquetado/hoja_preetiquetado.csv`).

La hoja es una **propuesta** del asistente para que una persona confirme (D-85, D-101): ningún lector de métricas la
usa y no toca `eval/etiquetas.csv`. Estas pruebas vigilan el formato y esas dos reglas; no juzgan si una propuesta es
correcta (eso lo decide la persona).
"""

from __future__ import annotations

import csv
import hashlib
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
HOJA = RAIZ / "eval" / "preetiquetado" / "hoja_preetiquetado.csv"
GUIA = RAIZ / "docs" / "preetiquetado.md"
ETIQUETAS = RAIZ / "eval" / "etiquetas.csv"
EXCLUIDOS = RAIZ / "config" / "ejemplos_excluidos.txt"
BASE = RAIZ / "data" / "senales.duckdb"

COLUMNAS = (
    "id_noticia", "titulo", "bloque", "evento", "id_grupo", "origen", "propuesta_tema", "propuesta_secundario",
    "propuesta_ruido", "propuesta_regional", "propuesta_grupo", "confianza", "dudoso", "motivo_corto",
    "tema_humano", "ruido_humano", "tema_secundario", "grupo", "alcance_regional", "nota", "etiquetado_por",
    "fecha_etiquetado",
)
COLUMNAS_DE_DECISION = (
    "tema_humano", "ruido_humano", "tema_secundario", "grupo", "alcance_regional", "nota", "etiquetado_por", "fecha_etiquetado",
)
TEMAS = {"economia", "logistica", "turismo", "servicios_publicos", "eventos_naturales", "regulacion"}
RUIDOS = {"no_es_panama", "fuera_de_temas", "no_es_noticia"}
BLOQUES = {"A_provisionales", "B_sin_etiquetar"}
ORIGEN_POR_BLOQUE = {"A_provisionales": "asistente_provisional", "B_sin_etiquetar": "asistente_propuesta"}
PALABRAS_MAX_CITA = 3  # regla de la tarea C-11: ninguna cita literal de más de 3 palabras seguidas de un titular


def _leer(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _ids_excluidos() -> set[str]:
    return {
        linea.split("\t", 1)[0].strip()
        for linea in EXCLUIDOS.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.startswith("#")
    }


def _palabras(texto: str) -> list[str]:
    return re.findall(r"\w+", texto.casefold())


def _cita_larga(texto: str, titulo: str, maximo: int = PALABRAS_MAX_CITA) -> str | None:
    """Primera secuencia de `maximo + 1` palabras seguidas de `texto` que aparece igual en `titulo`, o None."""
    t = _palabras(titulo)
    ventanas = {tuple(t[i : i + maximo + 1]) for i in range(len(t) - maximo)}
    p = _palabras(texto)
    for i in range(len(p) - maximo):
        if tuple(p[i : i + maximo + 1]) in ventanas:
            return " ".join(p[i : i + maximo + 1])
    return None


@pytest.fixture(scope="module")
def filas() -> list[dict[str, str]]:
    assert HOJA.exists(), f"falta {HOJA.relative_to(RAIZ)}"
    return _leer(HOJA)


def test_columnas_exactas_y_en_orden() -> None:
    assert HOJA.exists(), f"falta {HOJA.relative_to(RAIZ)}"
    with HOJA.open(encoding="utf-8", newline="") as f:
        assert tuple(next(csv.reader(f))) == COLUMNAS


def test_ids_unicos_y_con_prefijo(filas: list[dict[str, str]]) -> None:
    ids = [f["id_noticia"] for f in filas]
    assert ids and len(ids) == len(set(ids))
    assert all(re.fullmatch(r"NOT-[0-9a-f]{10}", i) for i in ids)


def test_valores_permitidos(filas: list[dict[str, str]]) -> None:
    for f in filas:
        i = f["id_noticia"]
        assert f["bloque"] in BLOQUES, i
        assert f["origen"] == ORIGEN_POR_BLOQUE[f["bloque"]], i
        assert f["propuesta_tema"] in TEMAS | {"sin_tema"}, i
        assert f["propuesta_secundario"] in TEMAS | {""}, i
        assert f["propuesta_secundario"] != f["propuesta_tema"], i
        assert f["propuesta_ruido"] in RUIDOS | {""}, i
        assert f["propuesta_regional"] in {"", "si"}, i
        assert f["confianza"] in {"alta", "media", "baja"}, i
        assert f["dudoso"] in {"si", "no"}, i
        assert f["motivo_corto"].strip(), i
        assert f["titulo"].strip() and f["evento"].strip(), i


def test_tema_y_ruido_son_coherentes(filas: list[dict[str, str]]) -> None:
    """Un titular con ruido propuesto no lleva tema, secundario ni alcance regional; uno sin ruido, sí lleva tema (D-87)."""
    for f in filas:
        i = f["id_noticia"]
        if f["propuesta_ruido"]:
            assert f["propuesta_tema"] == "sin_tema", i
            assert not f["propuesta_secundario"] and not f["propuesta_regional"], i
        else:
            assert f["propuesta_tema"] in TEMAS, i


def test_columnas_de_decision_humana_vacias(filas: list[dict[str, str]]) -> None:
    for f in filas:
        for c in COLUMNAS_DE_DECISION:
            assert f[c] == "", f"{f['id_noticia']}: {c} debe ir vacía hasta que una persona confirme"


def test_ordenada_por_bloque_y_evento(filas: list[dict[str, str]]) -> None:
    claves = [(f["bloque"], f["evento"]) for f in filas]
    assert claves == sorted(claves)
    # un evento no se parte en dos tramos separados
    tramos = [k for i, k in enumerate(claves) if i == 0 or claves[i - 1] != k]
    assert len(tramos) == len(set(tramos))


def test_un_evento_tiene_un_solo_bloque(filas: list[dict[str, str]]) -> None:
    bloques_por_evento: dict[str, set[str]] = {}
    for f in filas:
        bloques_por_evento.setdefault(f["evento"], set()).add(f["bloque"])
    assert all(len(b) == 1 for b in bloques_por_evento.values())


def test_ningun_id_de_los_ejemplos_excluidos(filas: list[dict[str, str]]) -> None:
    excluidos = _ids_excluidos()
    assert len(excluidos) == 16
    assert not {f["id_noticia"] for f in filas} & excluidos


def test_bloque_a_son_exactamente_las_provisionales(filas: list[dict[str, str]]) -> None:
    provisionales = {f["id_noticia"]: f for f in _leer(ETIQUETAS) if f["origen"] == "asistente_provisional"}
    bloque_a = {f["id_noticia"]: f for f in filas if f["bloque"] == "A_provisionales"}
    assert set(bloque_a) == set(provisionales)
    for i, f in bloque_a.items():  # el bloque A conserva el titular de la propuesta existente
        assert f["titulo"] == provisionales[i]["titulo"], i


def test_bloque_b_no_esta_en_etiquetas_con_ningun_origen(filas: list[dict[str, str]]) -> None:
    etiquetados = {f["id_noticia"] for f in _leer(ETIQUETAS)}
    bloque_b = {f["id_noticia"] for f in filas if f["bloque"] == "B_sin_etiquetar"}
    assert not bloque_b & etiquetados


def test_motivo_corto_no_cita_mas_de_tres_palabras_seguidas(filas: list[dict[str, str]]) -> None:
    for f in filas:
        cita = _cita_larga(f["motivo_corto"], f["titulo"])
        assert cita is None, f"{f['id_noticia']}: el motivo repite {cita!r} del titular"


def test_la_guia_no_cita_mas_de_tres_palabras_de_un_titular(filas: list[dict[str, str]]) -> None:
    assert GUIA.exists(), f"falta {GUIA.relative_to(RAIZ)}"
    texto = GUIA.read_text(encoding="utf-8")
    for f in filas:
        cita = _cita_larga(texto, f["titulo"])
        assert cita is None, f"docs/preetiquetado.md repite {cita!r} de {f['id_noticia']}"


def test_leer_la_hoja_no_modifica_etiquetas() -> None:
    antes = hashlib.sha256(ETIQUETAS.read_bytes()).hexdigest()
    _leer(HOJA)
    assert hashlib.sha256(ETIQUETAS.read_bytes()).hexdigest() == antes
    try:
        r = subprocess.run(["git", "diff", "--quiet", "--", "eval/etiquetas.csv", "eval/etiquetas"], cwd=RAIZ, check=False)
    except FileNotFoundError:
        pytest.skip("git no disponible: solo se comprobó el hash durante la prueba")
    if r.returncode not in (0, 1):
        pytest.skip("no es un repositorio git: solo se comprobó el hash durante la prueba")
    assert r.returncode == 0, "eval/etiquetas.csv o eval/etiquetas/ tienen cambios sin confirmar"


def test_ninguna_metrica_lee_la_hoja() -> None:
    """D-101: lo propuesto no entra en ninguna métrica; ningún módulo de `src/` ni de `eval/` nombra la hoja."""
    lectores = [*(RAIZ / "src").rglob("*.py"), *(RAIZ / "eval").glob("*.py"), *(RAIZ / "scripts").glob("*.py")]
    assert lectores
    nombran = [str(p.relative_to(RAIZ)) for p in lectores if "preetiquetado" in p.read_text(encoding="utf-8")]
    assert nombran == []


# ------------------------------------------------------------ contra la base (se omite sin data/senales.duckdb)


def _ids_de_la_base() -> dict[str, bool]:
    import duckdb

    con = duckdb.connect(str(BASE), read_only=True)
    try:
        return {i: bool(r) for i, r in con.execute("SELECT id_noticia, es_ruido FROM noticias").fetchall()}
    finally:
        con.close()


@pytest.mark.skipif(not BASE.exists(), reason="data/senales.duckdb no existe (se genera con src.carga, src.normalizacion y src.limpieza)")
def test_todos_los_ids_existen_en_la_base_y_el_bloque_b_no_es_ruido(filas: list[dict[str, str]]) -> None:
    en_base = _ids_de_la_base()
    faltan = [f["id_noticia"] for f in filas if f["id_noticia"] not in en_base]
    assert not faltan, f"ids que no están en la base: {faltan}"
    ruido_en_b = [f["id_noticia"] for f in filas if f["bloque"] == "B_sin_etiquetar" and en_base[f["id_noticia"]]]
    assert not ruido_en_b, "el bloque B solo lleva titulares que el filtro del pipeline no marcó como ruido"


@pytest.mark.skipif(not BASE.exists(), reason="data/senales.duckdb no existe (se genera con src.carga, src.normalizacion y src.limpieza)")
def test_bloque_b_es_todo_lo_util_sin_etiquetar() -> None:
    """Completitud: ningún titular útil, sin etiquetar y no excluido queda fuera de la hoja."""
    filas = _leer(HOJA)
    etiquetados = {f["id_noticia"] for f in _leer(ETIQUETAS)}
    esperado = {i for i, ruido in _ids_de_la_base().items() if not ruido and i not in etiquetados and i not in _ids_excluidos()}
    assert {f["id_noticia"] for f in filas if f["bloque"] == "B_sin_etiquetar"} == esperado


def test_resumen_de_bloques_es_legible(filas: list[dict[str, str]]) -> None:
    cuenta = Counter(f["bloque"] for f in filas)
    assert cuenta["A_provisionales"] == 61
