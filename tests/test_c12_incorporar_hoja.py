"""C-12: `eval/etiquetar.py --incorporar-hoja` arma `eval/etiquetas_ampliadas.csv` sin tocar sus entradas.

Todo con archivos temporales (sin `data/senales.duckdb`). Las filas de la hoja son sintéticas; la última prueba usa los
archivos reales solo para comprobar el conteo y que lo versionado se puede regenerar byte a byte.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

import pytest

from eval import clasificacion as evalclas
from eval import etiquetar as et
from eval import origen_etiquetas as oe
from src.configuracion import RAIZ, cargar_clasificacion, cargar_etiquetado, cargar_temas

COLUMNAS_HOJA = (
    "id_noticia", "titulo", "bloque", "evento", "id_grupo", "origen", "propuesta_tema", "propuesta_secundario",
    "propuesta_ruido", "propuesta_regional", "propuesta_grupo", "confianza", "dudoso", "motivo_corto",
    "tema_humano", "ruido_humano", "tema_secundario", "grupo", "alcance_regional", "nota", "etiquetado_por",
    "fecha_etiquetado",
)
AMPLIADAS_REAL = RAIZ / "eval" / "etiquetas_ampliadas.csv"
HOJA_REAL = RAIZ / "eval" / "preeti" "quetado" / "hoja_preeti" "quetado.csv"   # el nombre no puede aparecer en un módulo (test de C-11)


def _hash(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _escribir(ruta: Path, columnas: tuple[str, ...], filas: list[dict[str, str]]) -> Path:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows([{c: "" for c in columnas} | fila for fila in filas])
    return ruta


def _leer(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _humana(i: str, tema: str = "economia", peso: str = "2.5", estrato: str = "no_ruido", **extra: str) -> dict[str, str]:
    return {
        "id_noticia": i, "titulo": f"titular sintetico {i}", "tema_principal": tema, "ruido": "ninguno", "etiquetado_por": "Ana Perez",
        "fecha_etiquetado": "2026-10-06T10:00:00Z", "estrato": estrato, "peso_muestreo": peso, "n_etiquetadores": "2", "origen": "humano", **extra,
    }


def _hoja_fila(i: str, tema: str = "servicios_publicos", **extra: str) -> dict[str, str]:
    base = {
        "id_noticia": i, "titulo": f"titular de hoja {i}", "bloque": "A_provisionales", "evento": f"ev-{i}", "origen": "asistente_provisional",
        "tema_humano": tema, "ruido_humano": "", "etiquetado_por": "David", "fecha_etiquetado": "2026-10-07",
        "nota": "Aprobado en bloque por la persona",
    }
    return base | extra


@pytest.fixture
def entradas(tmp_path: Path) -> dict[str, Path]:
    etiquetas = _escribir(
        tmp_path / "etiquetas.csv", et.COLUMNAS_CONSOLIDADO,
        [
            _humana("NOT-h1", "turismo", "3", grupo="ev-h"),
            _humana("NOT-h2", "economia", "", "ruido", ruido="no_es_panama", tema_principal=""),
            _humana("NOT-h3", "regulacion", "1.2"),
            {**_humana("NOT-p1", "economia"), "origen": "asistente_provisional", "etiquetado_por": "asistente provisional"},
            {**_humana("NOT-p2", "turismo"), "origen": "asistente_provisional", "etiquetado_por": "asistente provisional"},
        ],
    )
    hoja = _escribir(
        tmp_path / "hoja.csv", COLUMNAS_HOJA,
        [
            _hoja_fila("NOT-p2", "servicios_publicos", grupo="corte-agua", tema_secundario="economia", alcance_regional="si", nota="revisada una a una"),
            _hoja_fila("NOT-n1", "economia"),
            _hoja_fila("NOT-n2", "sin_tema", ruido_humano="fuera_de_temas"),
            _hoja_fila("NOT-n3", "sin_tema", ruido_humano="no_es_panama"),
        ],
    )
    return {"etiquetas": etiquetas, "hoja": hoja, "salida": tmp_path / "ampliadas.csv"}


def _cli(e: dict[str, Path]) -> int:
    return et.main(["--incorporar-hoja", "--hoja", str(e["hoja"]), "--etiquetas", str(e["etiquetas"]), "--salida", str(e["salida"])])


def _con_hoja(e: dict[str, Path], filas: list[dict[str, str]]) -> None:
    _escribir(e["hoja"], COLUMNAS_HOJA, filas)


# ------------------------------------------------------------------ camino feliz


def test_una_hoja_valida_se_incorpora_completa_tras_las_humanas(entradas: dict[str, Path]) -> None:
    assert _cli(entradas) == 0
    filas = _leer(entradas["salida"])
    assert [f["id_noticia"] for f in filas] == ["NOT-h1", "NOT-h2", "NOT-h3", "NOT-n1", "NOT-n2", "NOT-n3", "NOT-p2"]
    assert tuple(_leer(entradas["salida"])[0]) == et.COLUMNAS_CONSOLIDADO
    assert all(f["origen"] == "humano" for f in filas)


def test_las_filas_originales_se_copian_sin_cambios(entradas: dict[str, Path]) -> None:
    _cli(entradas)
    originales = [f for f in _leer(entradas["etiquetas"]) if f["origen"] == "humano"]
    assert _leer(entradas["salida"])[: len(originales)] == originales


def test_la_fila_nueva_se_mapea_a_las_columnas_consolidadas(entradas: dict[str, Path]) -> None:
    _cli(entradas)
    f = next(x for x in _leer(entradas["salida"]) if x["id_noticia"] == "NOT-p2")
    assert (f["tema_principal"], f["tema_secundario"], f["ruido"], f["grupo"], f["alcance_regional"]) == (
        "servicios_publicos", "economia", "ninguno", "corte-agua", "si"
    )
    assert (f["nota"], f["etiquetado_por"], f["origen"]) == ("revisada una a una", "David", "humano")
    assert f["estrato"] == cargar_clasificacion().ampliado.estrato_hoja == "preeti" "quetado_c11"
    assert f["n_etiquetadores"] == "1"
    assert f["fecha_etiquetado"] == "2026-10-07T00:00:00Z"      # la hoja trae solo el día: se completa a medianoche UTC


def test_la_fecha_con_hora_de_la_hoja_se_conserva(entradas: dict[str, Path]) -> None:
    _con_hoja(entradas, [_hoja_fila("NOT-n1", "economia", fecha_etiquetado="2026-10-07T15:30:00Z")])
    assert _cli(entradas) == 0
    assert _leer(entradas["salida"])[-1]["fecha_etiquetado"] == "2026-10-07T15:30:00Z"


def test_un_titular_de_ruido_lleva_la_convencion_sin_tema(entradas: dict[str, Path]) -> None:
    _cli(entradas)
    ruido = {f["id_noticia"]: f for f in _leer(entradas["salida"]) if f["id_noticia"] in {"NOT-n2", "NOT-n3"}}
    assert {i: (f["ruido"], f["tema_principal"], f["tema_secundario"], f["grupo"], f["alcance_regional"]) for i, f in ruido.items()} == {
        "NOT-n2": ("fuera_de_temas", "", "", "", ""),
        "NOT-n3": ("no_es_panama", "", "", "", ""),
    }
    etiquetas = evalclas.leer_etiquetas(entradas["salida"], "tema_principal", cargar_temas())
    assert etiquetas["NOT-n2"].tema == etiquetas["NOT-n3"].tema == "sin_tema"
    assert et.validar_hoja(entradas["salida"], cargar_etiquetado(), cargar_temas()) == []


def test_un_ruido_con_grupo_pierde_el_grupo_y_queda_avisado(entradas: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _con_hoja(entradas, [_hoja_fila("NOT-n2", "sin_tema", ruido_humano="no_es_panama", grupo="ev-x"), _hoja_fila("NOT-n1", "economia", grupo="ev-x")])
    assert _cli(entradas) == 0
    filas = {f["id_noticia"]: f for f in _leer(entradas["salida"])}
    assert filas["NOT-n2"]["grupo"] == "" and filas["NOT-n1"]["grupo"] == "ev-x"
    err = capsys.readouterr().err
    assert "NOT-n2" in err and "se descarta" in err and "NOT-n1" not in err
    assert et.validar_hoja(entradas["salida"], cargar_etiquetado(), cargar_temas()) == []


# ------------------------------------------------------------------ peso de muestreo


def test_las_filas_nuevas_no_llevan_peso_y_las_originales_conservan_el_suyo(entradas: dict[str, Path]) -> None:
    _cli(entradas)
    filas = {f["id_noticia"]: f for f in _leer(entradas["salida"])}
    assert [filas[i]["peso_muestreo"] for i in ("NOT-h1", "NOT-h2", "NOT-h3")] == ["3", "", "1.2"]
    assert all(filas[i]["peso_muestreo"] == "" for i in ("NOT-n1", "NOT-n2", "NOT-n3", "NOT-p2"))
    pesos = {i: e.peso for i, e in evalclas.leer_etiquetas(entradas["salida"], "tema_principal", cargar_temas()).items()}
    assert pesos["NOT-h1"] == 3.0 and pesos["NOT-h3"] == 1.2           # los pesos originales no cambian
    assert pesos["NOT-n1"] == 1.0                                      # el lector da 1 a lo que no tiene peso (sin inventar población)


# ------------------------------------------------------------------ provisionales fuera


def test_una_provisional_que_no_esta_en_la_hoja_no_entra(entradas: dict[str, Path]) -> None:
    _cli(entradas)
    assert "NOT-p1" not in {f["id_noticia"] for f in _leer(entradas["salida"])}


def test_una_provisional_decidida_en_la_hoja_entra_una_sola_vez_con_la_decision_de_la_persona(entradas: dict[str, Path]) -> None:
    _cli(entradas)
    filas = [f for f in _leer(entradas["salida"]) if f["id_noticia"] == "NOT-p2"]
    assert len(filas) == 1 and filas[0]["origen"] == "humano" and filas[0]["tema_principal"] == "servicios_publicos"
    assert oe.ASISTENTE_PROVISIONAL not in {f["origen"] for f in _leer(entradas["salida"])}


# ------------------------------------------------------------------ todo o nada


def test_una_fila_sin_decidir_aborta_y_no_escribe_nada(entradas: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _con_hoja(entradas, [_hoja_fila("NOT-n1", "economia"), _hoja_fila("NOT-n2", "", etiquetado_por="", fecha_etiquetado="")])
    assert _cli(entradas) == 1
    assert not entradas["salida"].exists() and not entradas["salida"].with_name("ampliadas.csv.tmp").exists()
    assert "NOT-n2" in capsys.readouterr().err


@pytest.mark.parametrize(
    "cambio",
    [
        {"tema_humano": "deportes"},                                                     # tema inexistente
        {"tema_humano": "sin_tema"},                                                     # sin_tema sin motivo de ruido
        {"tema_humano": "economia", "ruido_humano": "no_es_panama"},                     # ruido con tema
        {"ruido_humano": "otro_motivo", "tema_humano": "sin_tema"},                      # motivo desconocido
        {"tema_secundario": "economia", "tema_humano": "economia"},                      # secundario repite el principal
        {"tema_secundario": "deportes"},                                                 # secundario inexistente
        {"etiquetado_por": ""},                                                          # sin quién
        {"etiquetado_por": "Asistente"},                                                 # una herramienta, no una persona
        {"fecha_etiquetado": ""},                                                        # sin fecha
        {"fecha_etiquetado": "07/10/2026"},                                              # fecha que no es ISO
        {"alcance_regional": "quizas"},
        {"grupo": "Con Espacios"},
        {"tema_humano": "sin_tema", "ruido_humano": "no_es_panama", "alcance_regional": "si"},
    ],
)
def test_una_fila_invalida_aborta_toda_la_incorporacion(entradas: dict[str, Path], cambio: dict[str, str]) -> None:
    _con_hoja(entradas, [_hoja_fila("NOT-n1", "economia"), _hoja_fila("NOT-n2", "servicios_publicos", **cambio)])
    assert _cli(entradas) == 1
    assert not entradas["salida"].exists()


def test_un_id_repetido_en_la_hoja_o_ya_humano_aborta(entradas: dict[str, Path]) -> None:
    _con_hoja(entradas, [_hoja_fila("NOT-n1"), _hoja_fila("NOT-n1")])
    assert _cli(entradas) == 1
    _con_hoja(entradas, [_hoja_fila("NOT-h1")])                                           # ya tiene etiqueta humana
    assert _cli(entradas) == 1
    assert not entradas["salida"].exists()


def test_una_hoja_vacia_o_con_otras_columnas_aborta(entradas: dict[str, Path]) -> None:
    _con_hoja(entradas, [])
    assert _cli(entradas) == 1
    _escribir(entradas["hoja"], ("id_noticia", "titulo"), [{"id_noticia": "NOT-n1"}])
    assert _cli(entradas) == 1
    assert not entradas["salida"].exists()


def test_un_fallo_no_borra_una_salida_anterior(entradas: dict[str, Path]) -> None:
    assert _cli(entradas) == 0
    antes = _hash(entradas["salida"])
    _con_hoja(entradas, [_hoja_fila("NOT-n1", "deportes")])
    assert _cli(entradas) == 1
    assert _hash(entradas["salida"]) == antes


# ------------------------------------------------------------------ idempotencia y entradas intactas


def test_correrlo_dos_veces_da_los_mismos_bytes(entradas: dict[str, Path]) -> None:
    assert _cli(entradas) == 0
    primero = entradas["salida"].read_bytes()
    assert _cli(entradas) == 0
    assert entradas["salida"].read_bytes() == primero


def test_el_orden_de_la_hoja_no_cambia_la_salida(entradas: dict[str, Path]) -> None:
    _cli(entradas)
    primero = entradas["salida"].read_bytes()
    _con_hoja(entradas, list(reversed(_leer(entradas["hoja"]))))
    _cli(entradas)
    assert entradas["salida"].read_bytes() == primero


def test_las_entradas_no_se_modifican(entradas: dict[str, Path]) -> None:
    antes = {k: _hash(entradas[k]) for k in ("etiquetas", "hoja")}
    _cli(entradas)
    assert {k: _hash(entradas[k]) for k in ("etiquetas", "hoja")} == antes


def test_se_niega_a_sobrescribir_el_consolidado_o_la_hoja(entradas: dict[str, Path]) -> None:
    antes = {k: _hash(entradas[k]) for k in ("etiquetas", "hoja")}
    for destino in ("etiquetas", "hoja"):
        assert et.main(["--incorporar-hoja", "--hoja", str(entradas["hoja"]), "--etiquetas", str(entradas["etiquetas"]), "--salida", str(entradas[destino])]) == 1
    assert {k: _hash(entradas[k]) for k in ("etiquetas", "hoja")} == antes


def test_se_niega_a_escribir_sobre_el_consolidado_real_aunque_se_llegue_por_otra_ruta(entradas: dict[str, Path]) -> None:
    real = RAIZ / "eval" / "etiquetas.csv"
    antes = _hash(real)
    rodeo = RAIZ / "eval" / ".." / "eval" / "." / "etiquetas.csv"
    for destino in (real, rodeo):
        assert et.main(["--incorporar-hoja", "--hoja", str(entradas["hoja"]), "--etiquetas", str(entradas["etiquetas"]), "--salida", str(destino)]) == 1
    assert _hash(real) == antes


def test_el_modo_exige_la_hoja(entradas: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert et.main(["--incorporar-hoja", "--etiquetas", str(entradas["etiquetas"]), "--salida", str(entradas["salida"])]) == 1
    assert "--hoja" in capsys.readouterr().err and not entradas["salida"].exists()


# ------------------------------------------------------------------ función pura


def test_incorporar_hoja_devuelve_las_filas_sin_escribir(entradas: dict[str, Path]) -> None:
    filas = et.incorporar_hoja(entradas["hoja"], entradas["etiquetas"], cargar_etiquetado(), cargar_temas(), cargar_clasificacion().ampliado)
    assert len(filas) == 7 and not entradas["salida"].exists()


def test_el_error_lista_todos_los_problemas(entradas: dict[str, Path]) -> None:
    _con_hoja(entradas, [_hoja_fila("NOT-a", "deportes"), _hoja_fila("NOT-b", "economia", etiquetado_por="")])
    with pytest.raises(et.ErrorEtiquetado) as exc:
        et.incorporar_hoja(entradas["hoja"], entradas["etiquetas"], cargar_etiquetado(), cargar_temas(), cargar_clasificacion().ampliado)
    assert "NOT-a" in str(exc.value) and "NOT-b" in str(exc.value)


# ------------------------------------------------------------------ medición por subconjunto (eval/clasificacion_por_evento.py)


def _conjunto() -> tuple[Any, dict[str, Any]]:
    import numpy as np

    from eval import clasificacion_por_evento as pe

    ids = ["o1", "o2", "o3", "n1", "n2", "n3"]
    y = np.array(["economia", "economia", "turismo", "servicios_publicos", "servicios_publicos", "sin_tema"], dtype=object)
    eventos = ["ev-a", "ev-a", "ev-b", "ev-a", "NOT-n2", "NOT-n3"]          # n1 comparte el nombre del grupo de o1 y o2
    conj = pe.Conjunto(ids, ["t"] * 6, y, eventos, np.zeros((6, 1)), np.zeros((6, 1)), [], ["economia", "turismo", "servicios_publicos", "sin_tema"], 0, 6)
    preds = {"sistema": np.array(["economia", "turismo", "turismo", "servicios_publicos", "economia", "sin_tema"], dtype=object)}
    return conj, preds


def test_los_subconjuntos_se_miden_por_separado_con_sus_propios_eventos() -> None:
    from eval import clasificacion_por_evento as pe

    conj, preds = _conjunto()
    cfg = cargar_clasificacion()
    r = pe.evaluar_subconjuntos(conj, preds, {"n1", "n2", "n3"}, cfg.criterio_ab, 1.96, cfg.por_evento.min_eventos_ic)
    assert (r["originales"]["filas"], r["originales"]["eventos"]) == (3, 2)
    assert (r["nuevas"]["filas"], r["nuevas"]["eventos"]) == (3, 3)           # n1 es un evento aparte aunque comparta el nombre
    assert r["eventos_nuevos"] == 2                                          # n2 y n3; "ev-a" ya existía
    s_o, s_n = r["originales"]["sistemas"]["sistema"], r["nuevas"]["sistemas"]["sistema"]
    assert (s_o["exactitud_por_fila"]["n"], s_o["exactitud_por_fila"]["de"]) == (2, 3)
    assert (s_n["exactitud_por_fila"]["n"], s_n["exactitud_por_fila"]["de"]) == (2, 3)
    assert r["originales"]["filas_por_tema"] == {"economia": 2, "turismo": 1}


def test_un_subconjunto_vacio_no_inventa_metricas() -> None:
    from eval import clasificacion_por_evento as pe

    conj, preds = _conjunto()
    cfg = cargar_clasificacion()
    r = pe.evaluar_subconjuntos(conj, preds, set(), cfg.criterio_ab, 1.96, cfg.por_evento.min_eventos_ic)
    assert r["nuevas"] == {"filas": 0, "eventos": 0, "filas_por_tema": {}, "sistemas": {}} and r["eventos_nuevos"] == 0


# ------------------------------------------------------------------ con los archivos reales


def _real(tmp_path: Path) -> Path:
    salida = tmp_path / "real.csv"
    assert et.main(["--incorporar-hoja", "--hoja", str(HOJA_REAL), "--etiquetas", str(oe.ETIQUETAS_CONSOLIDADO), "--salida", str(salida)]) == 0
    return salida


def test_la_hoja_real_suma_61_filas_a_las_100_humanas(tmp_path: Path) -> None:
    filas = _leer(_real(tmp_path))
    nuevas = [f for f in filas if f["estrato"] == cargar_clasificacion().ampliado.estrato_hoja]
    assert (len(filas), len(nuevas)) == (161, 61)
    assert {f["origen"] for f in filas} == {"humano"} and {f["etiquetado_por"] for f in nuevas} == {"David"}
    assert len({f["id_noticia"] for f in filas}) == 161


def test_el_archivo_versionado_se_regenera_byte_a_byte(tmp_path: Path) -> None:
    assert AMPLIADAS_REAL.exists(), "falta eval/etiquetas_ampliadas.csv: genérelo con `python -m eval.etiquetar --incorporar-hoja`"
    assert _real(tmp_path).read_bytes() == AMPLIADAS_REAL.read_bytes()


def test_la_configuracion_real_trae_la_seccion_ampliado() -> None:
    a: Any = cargar_clasificacion().ampliado
    assert a.estrato_hoja and a.n_etiquetadores_hoja == 1
