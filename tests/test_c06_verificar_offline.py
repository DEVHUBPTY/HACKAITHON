"""C-06 · ``scripts.verificar_offline``: el chequeo antes del pitch no usa la red y falla si falta algo obligatorio."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from scripts import verificar_offline as vo
from src.configuracion import RAIZ

GUION_EDITORIAL = "GRP-0000000001"
GUION_BANCA = "GRP-0000000002"


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    """Un entorno sano: bases, guion y caché falsos, modelo y app simulados."""
    base = tmp_path / "senales.duckdb"
    demo = tmp_path / "demo.duckdb"
    base.write_bytes(b"")
    demo.write_bytes(b"")
    guion = tmp_path / "demo.md"
    guion.write_text(f"editorial {GUION_EDITORIAL}; banca {GUION_BANCA}", encoding="utf-8")
    bandejas = {"editorial": [GUION_EDITORIAL, "GRP-0000000003"], "banca": [GUION_BANCA, "GRP-0000000004"]}
    estados = {g: "completo" for lista in bandejas.values() for g in lista}
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr(vo, "cargar_modelo_local", lambda: (1, 384))
    monkeypatch.setattr(vo.db, "es_base_de_demo", lambda ruta: Path(ruta).name == "demo.duckdb")
    monkeypatch.setattr(vo.calentar_cache, "modalidades_de_la_base", lambda ruta: ["editorial"])
    monkeypatch.setattr(vo, "comprobar_app", lambda b, d, intentos=None: vo.Resultado("app", True, "simulada"))
    monkeypatch.setattr(vo, "RAIZ", tmp_path)
    monkeypatch.setattr(vo, "CacheLlm", lambda: _CacheFalsa())
    monkeypatch.setattr(vo.corrida, "base_de_modalidad", lambda b, m: b)
    monkeypatch.setattr(vo.calentar_cache, "grupos_por_defecto", lambda b, m: bandejas[m])
    monkeypatch.setattr(vo.calentar_cache, "estado_de", lambda g, m, b, c: estados[g])
    monkeypatch.setattr(vo, "_grupos_del_guion", lambda g: [GUION_EDITORIAL, GUION_BANCA])
    return base, demo, estados


class _CacheFalsa:
    def __len__(self) -> int:
        return 7


def test_todo_en_verde_sale_con_0(entorno, capsys):
    base, demo, _ = entorno
    assert vo.principal(["--base", str(base), "--base-demo", str(demo)]) == 0
    salida = capsys.readouterr().out
    assert "✗" not in salida
    assert salida.count("✓") >= 5
    assert "2 de 2 grupos listos" in salida
    assert ".venv/bin/streamlit run app.py -- --demo" in salida
    assert "Wi-Fi apagado" in salida and "Ollama: no se usa" in salida


def test_falta_el_borrador_de_un_grupo_del_guion_sale_con_1(entorno, capsys):
    base, demo, estados = entorno
    estados[GUION_BANCA] = "sin borrador: no hay borrador en caché"
    assert vo.principal(["--base", str(base), "--base-demo", str(demo)]) == 1
    salida = capsys.readouterr().out
    assert f"✗ borradores (banca)" in salida and GUION_BANCA in salida and "1 de 2 grupos listos" in salida


def test_un_grupo_sin_borrador_fuera_del_guion_no_es_obligatorio(entorno):
    base, demo, estados = entorno
    estados["GRP-0000000003"] = "sin borrador: no hay borrador en caché"
    assert vo.principal(["--base", str(base), "--base-demo", str(demo)]) == 0


def test_sin_base_de_demo_solo_avisa_con_el_comando(entorno, capsys):
    base, demo, _ = entorno
    demo.unlink()
    assert vo.principal(["--base", str(base), "--base-demo", str(demo)]) == 0
    assert "scripts.preparar_demo" in capsys.readouterr().out


def test_la_base_real_no_puede_ser_de_demo(entorno, capsys):
    _, demo, _ = entorno
    assert vo.principal(["--base", str(demo), "--base-demo", str(demo)]) == 1
    assert "es una base de demo" in capsys.readouterr().out


def test_si_el_modelo_no_carga_falla(entorno, monkeypatch, capsys):
    base, demo, _ = entorno

    def fallar() -> tuple[int, ...]:
        raise RuntimeError("no está en models")

    monkeypatch.setattr(vo, "cargar_modelo_local", fallar)
    assert vo.principal(["--base", str(base), "--base-demo", str(demo)]) == 1
    assert "✗ embeddings" in capsys.readouterr().out


def test_fija_las_variables_de_modo_sin_conexion(entorno, monkeypatch):
    base, demo, _ = entorno
    monkeypatch.delenv("HF_HUB_OFFLINE")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE")
    vo.principal(["--base", str(base), "--base-demo", str(demo)])
    import os

    assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_sin_red_bloquea_hosts_no_locales_y_deja_pasar_los_locales(monkeypatch):
    llamadas: list[object] = []
    monkeypatch.setattr(socket.socket, "connect", lambda self, direccion: llamadas.append(direccion))
    with vo.sin_red() as intentos:
        s = socket.socket()
        with pytest.raises(vo.ConexionBloqueada):
            s.connect(("example.com", 443))
        with pytest.raises(vo.ConexionBloqueada):
            s.connect(("8.8.8.8", 53))
        s.connect(("127.0.0.1", 8501))
        s.connect(("localhost", 8501))
        s.close()
    assert intentos == ["('example.com', 443)", "('8.8.8.8', 53)"]
    assert llamadas == [("127.0.0.1", 8501), ("localhost", 8501)]


@pytest.mark.skipif(not (RAIZ / "data" / "demo.duckdb").exists(), reason="requiere data/demo.duckdb")
def test_la_app_real_arranca_sin_ninguna_conexion_no_local():
    intentos: list[str] = []
    resultado = vo.comprobar_app(RAIZ / "data" / "senales.duckdb", RAIZ / "data" / "demo.duckdb", intentos)
    assert resultado.ok, resultado.detalle
    assert intentos == []
