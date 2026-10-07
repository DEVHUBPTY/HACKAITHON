"""X55 · ``scripts.calentar_cache`` ante una base puntuada con otra modalidad (E2-01 X39, E2-02).

``src.puntaje`` guarda una sola modalidad a la vez. Calentar o verificar la otra no debe terminar en un traceback: se dice qué modalidad
tiene la base, qué comando ejecutar y se sale con error. Un pedido mixto (editorial y banca) se resuelve modalidad por modalidad.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from scripts import calentar_cache as cc
from src import db
from src.cache import CacheLlm


def base_de(tmp_path: Path, modalidad: str) -> Path:
    """Una base mínima cuya corrida guardada (tabla ``evidencia``) es de ``modalidad``."""
    ruta = tmp_path / f"base_{modalidad}.duckdb"
    con = duckdb.connect(str(ruta))
    con.execute("CREATE TABLE evidencia (id_grupo VARCHAR, modalidad VARCHAR)")
    con.execute("INSERT INTO evidencia VALUES ('GRP-0000000001', ?)", [modalidad])
    con.close()
    return ruta


def _sin_red_ni_proveedor(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    creados: list[str] = []

    def crear() -> object:
        creados.append("x")
        raise AssertionError("no debe crear un proveedor para una modalidad que la base no tiene")

    monkeypatch.setattr("src.llm.proveedor.crear_proveedor", crear)
    monkeypatch.setattr("src.cache.modo_offline", lambda *a, **k: False)
    monkeypatch.setattr(cc, "red_disponible", lambda *a, **k: True)
    return creados


def test_verificar_otra_modalidad_da_un_error_limpio_con_el_comando(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = base_de(tmp_path, "editorial")
    codigo = cc.principal(["--verificar", "--modalidad", "banca", "--grupos", "GRP-0000000001", "--base", str(base)])
    salida = capsys.readouterr()
    assert codigo != 0
    assert "ERROR:" in salida.err and "poetry run python -m src.puntaje --modalidad banca" in salida.err
    assert "'editorial'" in salida.err and "Traceback" not in salida.err + salida.out


def test_calentar_otra_modalidad_da_un_error_limpio_sin_crear_un_proveedor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    creados = _sin_red_ni_proveedor(monkeypatch)
    base = base_de(tmp_path, "editorial")
    codigo = cc.principal(["--modalidad", "banca", "--grupos", "GRP-0000000001", "--base", str(base)])
    salida = capsys.readouterr()
    assert codigo != 0 and creados == []
    assert "ERROR:" in salida.err and "poetry run python -m src.puntaje --modalidad banca" in salida.err


def test_un_pedido_mixto_verifica_cada_modalidad_y_dice_cual_tiene_la_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vistos: list[tuple[str, str]] = []

    def estado(id_grupo: str, modalidad: str, base: Path, cache: object) -> str:
        vistos.append((id_grupo, modalidad))
        return "completo"

    monkeypatch.setattr(cc, "estado_de", estado)
    base = base_de(tmp_path, "banca")
    codigo = cc.principal(["--verificar", "--modalidad", "editorial", "banca", "--grupos", "GRP-0000000001", "--base", str(base)])
    salida = capsys.readouterr()
    assert vistos == [("GRP-0000000001", "banca")]                         # solo la modalidad que la base tiene
    assert "banca" in salida.out and "GRP-0000000001  completo" in salida.out
    assert "'banca'" in salida.err and "poetry run python -m src.puntaje --modalidad editorial" in salida.err
    assert codigo != 0 and "Traceback" not in salida.err


def test_estado_de_convierte_modalidad_distinta_en_un_estado_legible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def falla(*a: object, **k: object) -> None:
        raise db.ModalidadDistinta("GRP-x: los puntajes de la base son de la modalidad 'editorial', no de 'banca': ejecute `poetry run python -m src.puntaje --modalidad banca` antes de leerlos")

    monkeypatch.setattr("src.generacion.generar_paquete", falla)
    estado = cc.estado_de("GRP-x", "banca", tmp_path / "x.duckdb", object())  # type: ignore[arg-type]
    assert estado.startswith("modalidad distinta:") and "src.puntaje --modalidad banca" in estado


def test_calentar_atrapa_modalidad_distinta_a_mitad_de_camino(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Si la base cambia de modalidad entre la comprobación y la generación (otro proceso corrió src.puntaje), tampoco hay traceback."""
    monkeypatch.setattr("src.llm.proveedor.crear_proveedor", lambda: object())
    monkeypatch.setattr("src.cache.modo_offline", lambda *a, **k: False)
    monkeypatch.setattr(cc, "red_disponible", lambda *a, **k: True)

    def falla(*a: object, **k: object) -> None:
        raise db.ModalidadDistinta("los puntajes de la base son de la modalidad 'editorial', no de 'banca': ejecute `poetry run python -m src.puntaje --modalidad banca` antes de leerlos")

    monkeypatch.setattr("src.generacion.generar_paquete", falla)
    base = base_de(tmp_path, "banca")
    codigo = cc.principal(["--modalidad", "banca", "--grupos", "GRP-0000000001", "--base", str(base)])
    salida = capsys.readouterr()
    assert codigo != 0 and "ERROR:" in salida.err and "src.puntaje --modalidad banca" in salida.err and "Traceback" not in salida.err


# ------------------------------------------------------------------ X56 · --podar no cruza modalidades


def _entrada(carpeta: Path, clave: str, **meta: str) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    datos = {"clave": clave, "respuesta": "{}", **meta}
    (carpeta / f"{clave}.json").write_text(json.dumps(datos), encoding="utf-8")


def test_podar_editorial_no_borra_los_boletines_de_banca_ni_lo_que_no_registra_su_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    carpeta = tmp_path / "cache"
    usada, vieja, banca, antigua = "a" * 64, "b" * 64, "c" * 64, "d" * 64
    _entrada(carpeta, usada, prompt="paquete_editorial")
    _entrada(carpeta, vieja, prompt="paquete_editorial")  # sin uso: de un prompt anterior de la misma modalidad
    _entrada(carpeta, banca, prompt="boletin_banca")  # otra modalidad: no se verifica ahora
    _entrada(carpeta, antigua)  # anterior a X56: no se sabe de quién es
    cache = CacheLlm(carpeta)

    def estado(grupo: str, modalidad: str, base: Path, cache_: CacheLlm) -> str:
        assert cache_.obtener(usada, "paquete_editorial")
        return "completo"

    monkeypatch.setattr(cc, "CacheLlm", lambda: cache)
    monkeypatch.setattr(cc, "estado_de", estado)
    codigo = cc.principal(["--verificar", "--podar", "--grupos", "GRP-0000000001", "--base", str(base_de(tmp_path, "editorial"))])
    assert codigo == 0
    assert {f.stem for f in carpeta.glob("*.json")} == {usada, banca, antigua}
    assert "1 respuestas sin uso borradas" in capsys.readouterr().out


def test_podar_banca_no_borra_las_respuestas_editoriales(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    carpeta = tmp_path / "cache"
    usada, editorial, vieja = "a" * 64, "b" * 64, "c" * 64
    _entrada(carpeta, usada, prompt="boletin_banca")
    _entrada(carpeta, vieja, prompt="boletin_banca")
    _entrada(carpeta, editorial, prompt="paquete_editorial")
    cache = CacheLlm(carpeta)

    def estado(grupo: str, modalidad: str, base: Path, cache_: CacheLlm) -> str:
        assert cache_.obtener(usada, "boletin_banca")
        return "completo"

    monkeypatch.setattr(cc, "CacheLlm", lambda: cache)
    monkeypatch.setattr(cc, "estado_de", estado)
    args = ["--verificar", "--podar", "--modalidad", "banca", "--grupos", "GRP-0000000001", "--base", str(base_de(tmp_path, "banca"))]
    assert cc.principal(args) == 0
    assert {f.stem for f in carpeta.glob("*.json")} == {usada, editorial}
