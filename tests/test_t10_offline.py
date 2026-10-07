"""T10 · Sin internet durante la demo: el recorrido carga → bandeja → ficha → paquete funciona con la red simulada caída.

Los sockets (salvo localhost) lanzan un error en cuanto alguien intenta conectarse: ni el proveedor, ni el sondeo de red, ni la
interfaz pueden depender de internet. El borrador sale de una caché poblada antes con un proveedor falso. Nada llama a un LLM real.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from src import cache as c
from src import db, interfaz as ui
from src import generacion as g
from src.cache import CacheLlm, Identidad, SinBorrador
from src.configuracion import RAIZ, cargar_interfaz
from src.ficha import construir_ficha
from tests import generacion_ayuda as ga
from tests.test_interfaz import PANTALLAS, app, base, emb, ir, textos  # noqa: F401  (fixtures y ayudas de la prueba de la interfaz)

ID = Identidad("guionado", "guionado-0")
LOCAL = {"localhost", "127.0.0.1", "::1"}


@pytest.fixture
def sin_red(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Simula la red caída: cualquier conexión a un host que no sea local falla y queda registrada."""
    intentos: list[str] = []

    def host(direccion: Any) -> str:
        return str(direccion[0]) if isinstance(direccion, tuple) else str(direccion)

    def connect(self: socket.socket, direccion: Any) -> None:
        if host(direccion) not in LOCAL and self.family != socket.AF_UNIX:
            intentos.append(host(direccion))
            raise OSError("red simulada caída")
        raise OSError("sin servidores locales en la prueba")

    def create_connection(direccion: Any, *a: Any, **k: Any) -> None:
        intentos.append(host(direccion))
        raise OSError("red simulada caída")

    def getaddrinfo(nombre: str, *a: Any, **k: Any) -> None:
        if nombre not in LOCAL:
            intentos.append(nombre)
            raise socket.gaierror("red simulada caída")
        return None

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return intentos


@pytest.fixture
def cache_poblada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CacheLlm:
    """La caché de demo: se puebla con un proveedor falso (con red «arriba») y queda donde la busca la interfaz."""
    monkeypatch.setattr(c, "RAIZ", tmp_path)
    monkeypatch.setattr(g, "_entrada_desde_grupo", lambda id_grupo, modalidad, base: ga.ficha())
    monkeypatch.setattr(g, "identidad_de", lambda: ID)
    monkeypatch.setattr(c, "leer_local_env", lambda *a, **k: {})
    cache = CacheLlm()
    assert cache.carpeta == tmp_path / "data" / "cache_llm"
    g.generar_paquete("GRP-x", "editorial", solo_cache=False, proveedor=ga.ProveedorGuionado(), cache=cache)
    assert len(cache) == 5
    return cache


def test_el_sondeo_de_red_dice_que_no_hay_red_sin_bloquear(sin_red: list[str]) -> None:
    assert c.red_disponible() is False and sin_red == ["api.deepseek.com"]


def test_recorrido_completo_sin_red_carga_bandeja_ficha_y_paquete(base: Path, emb: Any, cache_poblada: CacheLlm, sin_red: list[str]) -> None:
    con = db.conectar(base, solo_lectura=True)
    try:
        calidad = ui.resumen_de_calidad(con)                                   # carga
        bandeja = ui.leer_bandeja(con, "editorial")                            # bandeja
        assert calidad and bandeja
        ficha = construir_ficha(bandeja[0].id_grupo, "editorial", con, emb=emb)  # ficha
        assert ficha.accion_recomendada.accion
        paquete = g.generar_paquete(bandeja[0].id_grupo, "editorial", solo_cache=True, base=base)  # paquete
    finally:
        con.close()
    assert paquete.titulo is not None and paquete.brief and paquete.guion and paquete.resumen_web and paquete.copy_digital
    assert paquete.marca and paquete.leyenda_alcance and not paquete.vacios
    assert sin_red == []                                                       # ni una conexión externa


def test_la_pantalla_paquete_muestra_el_borrador_de_la_cache_sin_red(app: Any, cache_poblada: CacheLlm, sin_red: list[str]) -> None:
    at = app.run()
    for clave in PANTALLAS:
        at = ir(at, clave)
        assert not at.exception, clave
    at = ir(at, "paquete")
    texto = "\n".join(textos(at))
    assert "BORRADOR · requiere revisión" in texto and "TVN reporta nuevo plan de Mulino" in texto
    assert [e.label for e in at.expander if e.label == "Guion"] == ["Guion"]
    assert not at.warning and not at.error and sin_red == []


def test_sin_borrador_en_cache_la_pantalla_lo_dice_y_no_intenta_la_red(app: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sin_red: list[str]) -> None:
    monkeypatch.setattr(c, "RAIZ", tmp_path)
    monkeypatch.setattr(g, "identidad_de", lambda: ID)
    at = ir(app.run(), "paquete")
    assert not at.exception and any("no hay borrador en caché" in str(w.value) or "no genera borrador" in str(w.value) for w in at.warning)
    assert sin_red == []


def test_generar_sin_red_degrada_a_la_cache_y_nunca_crea_un_proveedor(cache_poblada: CacheLlm, sin_red: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm.proveedor.crear_proveedor", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sin red no se crea proveedor")))
    p = g.generar_paquete("GRP-x", "editorial", solo_cache=False, cache=cache_poblada)
    assert p.titulo is not None
    assert sin_red == ["api.deepseek.com"]                                     # solo el sondeo, que falló rápido


def test_sin_cache_y_sin_red_el_paquete_no_existe_y_no_bloquea(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sin_red: list[str]) -> None:
    monkeypatch.setattr(g, "_entrada_desde_grupo", lambda id_grupo, modalidad, base: ga.ficha())
    monkeypatch.setattr(g, "identidad_de", lambda: ID)
    with pytest.raises(SinBorrador, match="no hay borrador en caché"):
        g.generar_paquete("GRP-x", "editorial", solo_cache=False, cache=CacheLlm(tmp_path / "vacia"))


def test_la_clave_de_la_peticion_no_depende_del_orden_de_hash_del_proceso() -> None:
    """La caché calentada en un proceso debe servir en otro: la petición (y su clave) es idéntica con cualquier PYTHONHASHSEED."""
    codigo = (
        "from src.generacion import Generador\n"
        "from src.cache import clave_de\n"
        "from tests import generacion_ayuda as ga\n"
        "g = Generador(ga.ficha(contradicciones=ga.contradiccion_abierta(), registros=[*ga.ficha().registros, ga.registro_prensa()]), None)\n"
        "print(clave_de('p', 'm', '1', 'S', g._mensaje_ficha(), {}, 0.0, 0, '1'))\n"
    )
    claves = set()
    for semilla in ("1", "2", "3"):
        r = subprocess.run(
            [sys.executable, "-c", codigo], cwd=RAIZ, env={**os.environ, "PYTHONHASHSEED": semilla, "HF_HUB_OFFLINE": "1"},
            capture_output=True, text=True, check=True,
        )
        claves.add(r.stdout.strip())
    assert len(claves) == 1


def test_la_configuracion_de_la_interfaz_pide_solo_cache() -> None:
    assert cargar_interfaz().generacion.solo_cache is True
