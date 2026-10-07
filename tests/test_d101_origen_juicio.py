"""D-101 · Procedencia de los juicios: una métrica calculada con juicios provisionales del asistente nunca se rotula como humana.

Cubre la columna ``origen_juicio`` (``config/origen_juicio.yaml``) que leen ``eval.precision_at_5`` (selección del editor, E1-19) y
``eval.sustento`` (veredictos de sustento, E1-18).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from eval import origen_juicio as oj
from eval import precision_at_5 as pa5
from eval import sustento
from src.configuracion import CriterioAB, ConfigOrigenJuicio, cargar_origen_juicio
from tests.test_e1_19_precision import CFG as CFG_PRECISION
from tests.test_e1_19_precision import CORTE, FECHAS, POS, _base

CFG = cargar_origen_juicio()
CRITERIO = CriterioAB(remuestreos=200, confianza=0.95, semilla=7)
ELEGIDOS = [f"GRP-{i:02d}" for i in (1, 2, 3, 9, 10)]
PROVISIONAL = "asistente_provisional"


def _etiqueta_humana() -> str:
    return CFG.origenes[CFG.humano]


# ------------------------------------------------------------------ configuración


def test_config_prohibe_claves_desconocidas() -> None:
    datos = CFG.model_dump() | {"extra": 1}
    with pytest.raises(ValueError):
        ConfigOrigenJuicio.model_validate(datos)


def test_config_el_origen_humano_debe_ser_uno_de_los_origenes() -> None:
    datos = CFG.model_dump() | {"humano": "nadie"}
    with pytest.raises(ValueError, match="humano"):
        ConfigOrigenJuicio.model_validate(datos)


def test_config_la_etiqueta_provisional_cita_la_decision() -> None:
    assert "D-101" in CFG.origenes[PROVISIONAL] and "D-101" in CFG.aviso_provisional


def test_yaml_registrado_en_validar_todo() -> None:
    from src.configuracion import CARGADORES

    assert "origen_juicio" in CARGADORES


# ------------------------------------------------------------------ origen de un archivo


@pytest.mark.parametrize(
    ("valores", "esperado"),
    [
        ([None, None], "humano"),                       # archivo sin la columna: comportamiento anterior
        (["", "  "], "humano"),
        (["humano", "Humano"], "humano"),
        ([PROVISIONAL, PROVISIONAL], PROVISIONAL),
        (["humano", PROVISIONAL], PROVISIONAL),          # una sola fila provisional contamina todo el resultado
        (["", PROVISIONAL], PROVISIONAL),
    ],
)
def test_origen_de_filas(valores: list[str | None], esperado: str) -> None:
    filas = [{} if v is None else {CFG.columna: v} for v in valores]
    assert oj.origen_de_filas(filas, CFG) == esperado


def test_un_origen_desconocido_es_error_y_se_nombra() -> None:
    with pytest.raises(oj.OrigenInvalido, match="robot"):
        oj.origen_de_filas([{CFG.columna: "robot"}], CFG)


def test_describir_provisional_nunca_dice_humano() -> None:
    d = oj.describir(PROVISIONAL, CFG)
    assert d == {"origen_juicio": CFG.origenes[PROVISIONAL], "juicio_humano": False}
    assert d["origen_juicio"] != _etiqueta_humana()


# ------------------------------------------------------------------ Precision@5 (E1-19)


def _seleccion(ruta: Path, origen: str | None) -> None:
    columnas = [*CFG_PRECISION.hoja_ciega.columnas, *([CFG.columna] if origen is not None else [])]
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        for i in range(1, 11):
            gid = f"GRP-{i:02d}"
            fila = {"corte": CORTE, "id_grupo": gid, "tema": "", "titular": "", "fecha_reciente": "",
                    "seleccion": CFG_PRECISION.hoja_ciega.marca if gid in ELEGIDOS else ""}
            w.writerow(fila | ({CFG.columna: origen} if origen is not None else {}))


def test_precision_con_seleccion_provisional_se_rotula_provisional(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    sel, salida = tmp_path / "sel.csv", tmp_path / "out.json"
    _seleccion(sel, PROVISIONAL)
    assert pa5.principal(["--seleccion", str(sel), "--base", str(base), "--salida", str(salida)]) == 0
    texto = capsys.readouterr().out
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["origen_juicio"] == CFG.origenes[PROVISIONAL] and datos["juicio_humano"] is False
    assert datos["exploratoria"] is True
    assert CFG.aviso_provisional in texto


def test_precision_con_origen_humano_se_rotula_humano_y_sin_aviso(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    sel, salida = tmp_path / "sel.csv", tmp_path / "out.json"
    _seleccion(sel, "humano")
    assert pa5.principal(["--seleccion", str(sel), "--base", str(base), "--salida", str(salida)]) == 0
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["origen_juicio"] == _etiqueta_humana() and datos["juicio_humano"] is True
    assert CFG.aviso_provisional not in capsys.readouterr().out


def test_precision_sin_la_columna_sigue_siendo_humana(tmp_path: Path) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    sel, salida = tmp_path / "sel.csv", tmp_path / "out.json"
    _seleccion(sel, None)
    assert pa5.principal(["--seleccion", str(sel), "--base", str(base), "--salida", str(salida)]) == 0
    assert json.loads(salida.read_text(encoding="utf-8"))["juicio_humano"] is True


def test_precision_provisional_no_se_puede_declarar_de_especialista(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    sel, salida = tmp_path / "sel.csv", tmp_path / "out.json"
    _seleccion(sel, PROVISIONAL)
    assert pa5.principal(["--seleccion", str(sel), "--base", str(base), "--salida", str(salida), "--especialista"]) == 2
    assert "especialista" in capsys.readouterr().err and not salida.exists()


def test_precision_origen_desconocido_falla_sin_escribir(tmp_path: Path) -> None:
    base = _base(tmp_path / "s.duckdb", POS, FECHAS)
    sel, salida = tmp_path / "sel.csv", tmp_path / "out.json"
    _seleccion(sel, "robot")
    assert pa5.principal(["--seleccion", str(sel), "--base", str(base), "--salida", str(salida)]) == 2
    assert not salida.exists()


# ------------------------------------------------------------------ validez de sustento (E1-18)


def _revision(ruta: Path, origenes: list[str]) -> None:
    pool = [{"origen": "consulta", "id_unidad": f"Q{i}", "id_afirmacion": "A1", "tipo": "hecho", "texto": f"t{i}",
             "citas": "IND-1 · valor", "evidencia_citada": "e"} for i in range(len(origenes))]
    sustento.escribir_muestra(sustento.muestrear(pool, len(pool), 42), ruta)
    filas = list(csv.DictReader(ruta.open(encoding="utf-8")))
    for f, o in zip(filas, origenes, strict=True):
        f["veredicto"], f[CFG.columna] = "sustentada", o
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)


def test_la_muestra_nueva_trae_la_columna_de_origen_vacia(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    sustento.escribir_muestra(sustento.muestrear([{"origen": "c", "id_unidad": "Q", "id_afirmacion": "A1"}], 30, 42), ruta)
    filas = list(csv.DictReader(ruta.open(encoding="utf-8")))
    assert CFG.columna in filas[0] and {f[CFG.columna] for f in filas} == {""}


def test_sustento_provisional_se_rotula_provisional(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    _revision(ruta, [PROVISIONAL] * 3)
    r = sustento.validez(sustento.leer_revision(ruta), CRITERIO)
    assert r["estado"] == "completa"
    assert r["origen_juicio"] == CFG.origenes[PROVISIONAL] and r["juicio_humano"] is False
    assert r["aviso_origen"] == CFG.aviso_provisional


def test_sustento_mixto_nunca_se_rotula_humano(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    _revision(ruta, ["humano", "humano", PROVISIONAL])
    r = sustento.validez(sustento.leer_revision(ruta), CRITERIO)
    assert r["juicio_humano"] is False and r["origen_juicio"] != _etiqueta_humana()


def test_sustento_humano_se_rotula_humano(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    _revision(ruta, ["humano", "", "humano"])
    r = sustento.validez(sustento.leer_revision(ruta), CRITERIO)
    assert r["origen_juicio"] == _etiqueta_humana() and r["juicio_humano"] is True and "aviso_origen" not in r


def test_sustento_cli_provisional_imprime_el_aviso_y_lo_guarda(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta, salida = tmp_path / "r.csv", tmp_path / "s.json"
    _revision(ruta, [PROVISIONAL] * 3)
    assert sustento.principal(["--archivo", str(ruta), "--salida", str(salida)]) == 0
    assert CFG.aviso_provisional in capsys.readouterr().out
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["origen_juicio"] == CFG.origenes[PROVISIONAL] and datos["juicio_humano"] is False


def test_sustento_cli_origen_desconocido_falla(tmp_path: Path) -> None:
    ruta, salida = tmp_path / "r.csv", tmp_path / "s.json"
    _revision(ruta, ["robot"] * 3)
    assert sustento.principal(["--archivo", str(ruta), "--salida", str(salida)]) == 1
    assert not salida.exists()
