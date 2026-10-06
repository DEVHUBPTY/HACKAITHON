"""Pruebas offline de la descarga de GDELT: reutilización de crudos y backoff (E0-04). Sin red."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import conversion, extraer


class Respuesta:
    def __init__(self, codigo: int = 200, texto: str = '{"articles": []}', cabeceras: dict | None = None):
        self.status_code = codigo
        self.text = texto
        self.headers = cabeceras or {}


@pytest.fixture
def cfg(config: dict) -> dict:
    config["gdelt"].update(consultas={"economia": "Panama (economia OR economy)"}, rango_dias=1, max_intentos=3, pausa_segundos=0)
    config["ventana_noticias"].update(dias_base=2, dias_maximo=2)
    config["volumen_noticias"]["minimo"] = 0
    return config


@pytest.fixture
def red(monkeypatch: pytest.MonkeyPatch):
    """Sustituye requests.get y time.sleep; registra llamadas y esperas."""
    estado = {"llamadas": [], "esperas": [], "respuestas": []}

    def falso_get(url, params=None, headers=None, timeout=None):
        estado["llamadas"].append(params)
        r = estado["respuestas"].pop(0) if estado["respuestas"] else Respuesta()
        return r

    monkeypatch.setattr(extraer.requests, "get", falso_get)
    monkeypatch.setattr(extraer.time, "sleep", lambda s: estado["esperas"].append(s))
    return estado


def test_rangos_alineados_no_dependen_de_la_hora() -> None:
    a = extraer._rangos(datetime(2026, 10, 6, 3, 0, tzinfo=UTC), 30, 10)
    b = extraer._rangos(datetime(2026, 10, 6, 23, 59, tzinfo=UTC), 30, 10)
    assert a == b
    assert a[0][1] == datetime(2026, 10, 6, tzinfo=UTC)  # no incluye el día en curso
    assert a[-1][0] <= datetime(2026, 9, 6, tzinfo=UTC)  # cubre la ventana completa


def test_crudo_existente_no_llama_a_la_api(tmp_path: Path, cfg: dict, red: dict) -> None:
    ini, fin = datetime(2026, 10, 4, tzinfo=UTC), datetime(2026, 10, 5, tzinfo=UTC)
    carpeta = tmp_path / "gdelt"
    carpeta.mkdir()
    (carpeta / f"{extraer._prefijo_gdelt('economia', ini, fin)}_20261006T120000Z.json").write_text('{"articles": []}')
    estado: dict = {}
    n = extraer._consultar_gdelt("economia", "q", ini, fin, tmp_path, cfg, estado)
    assert n == 0 and red["llamadas"] == [] and estado["reutilizados"] == 1


def test_forzar_vuelve_a_pedir(tmp_path: Path, cfg: dict, red: dict) -> None:
    ini, fin = datetime(2026, 10, 4, tzinfo=UTC), datetime(2026, 10, 5, tzinfo=UTC)
    carpeta = tmp_path / "gdelt"
    carpeta.mkdir()
    (carpeta / f"{extraer._prefijo_gdelt('economia', ini, fin)}_20261006T120000Z.json").write_text("{}")
    extraer._consultar_gdelt("economia", "q", ini, fin, tmp_path, cfg, {"forzar": True})
    assert len(red["llamadas"]) == 1


def test_segunda_corrida_no_repite_llamadas(tmp_path: Path, cfg: dict, red: dict) -> None:
    extraer.extraer_gdelt(tmp_path, cfg)
    primera = len(red["llamadas"])
    assert primera == 2  # 2 días × 1 tema
    extraer.extraer_gdelt(tmp_path, cfg)
    assert len(red["llamadas"]) == primera  # incluso las respuestas vacías quedaron como crudo


def test_429_con_retry_after_espera_ese_valor(tmp_path: Path, cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(429, "slow down", {"Retry-After": "7"}), Respuesta()]
    resp = extraer._pedir_gdelt({"query": "x"}, cfg)
    assert resp.status_code == 200 and red["esperas"] == [7]


def test_429_sin_retry_after_usa_backoff_exponencial(cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(429), Respuesta(429), Respuesta()]
    extraer._pedir_gdelt({"query": "x"}, cfg)
    base = cfg["gdelt"]["espera_429_segundos"]
    assert red["esperas"] == [base, base * 2]


def test_agotar_intentos_registra_el_fallo_y_continua(tmp_path: Path, cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(429)] * 3  # agota el primer rango (3 intentos)
    # el segundo rango responde bien (la cola se vacía y el falso devuelve 200)
    with pytest.raises(extraer.ErrorDeExtraccion):
        extraer.extraer_gdelt(tmp_path, cfg)
    assert len(red["llamadas"]) == 3 + 1  # 3 intentos fallidos + el rango siguiente
    fallos = list((tmp_path / "gdelt").glob("fallos_gdelt_*.json"))
    assert len(fallos) == 1
    registrado = json.loads(fallos[0].read_text("utf-8"))
    assert len(registrado) == 1 and registrado[0]["tema"] == "economia"
    pendientes = conversion.fallos_gdelt_sin_resolver(tmp_path, cfg)
    assert len(pendientes) == 1
    # el manifest lo reporta en su cobertura
    _, _, auditoria = conversion.convertir_noticias(tmp_path, cfg)
    assert auditoria["gdelt_rangos_sin_resolver"] == pendientes


def test_un_fallo_resuelto_despues_deja_de_reportarse(tmp_path: Path, cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(429)] * 3
    with pytest.raises(extraer.ErrorDeExtraccion):
        extraer.extraer_gdelt(tmp_path, cfg)
    extraer.extraer_gdelt(tmp_path, cfg)  # solo pide el rango que faltaba
    assert conversion.fallos_gdelt_sin_resolver(tmp_path, cfg) == []
