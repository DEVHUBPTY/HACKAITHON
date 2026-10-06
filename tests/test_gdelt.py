"""Pruebas offline de la descarga de GDELT: reutilización de crudos y backoff (E0-04). Sin red."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import conversion, extraer


PATA_UNICA = {"descripcion": "d", "filtros": ["sourcecountry:panama"], "terminos": ["economía", "economy"]}


class Respuesta:
    def __init__(self, codigo: int = 200, texto: str = '{"articles": []}', cabeceras: dict | None = None):
        self.status_code = codigo
        self.text = texto
        self.headers = cabeceras or {}


@pytest.fixture
def cfg(config: dict) -> dict:
    config["gdelt"].update(consultas={"economia": {"locales": PATA_UNICA}}, rango_dias=1, max_intentos=3, pausa_segundos=0)
    config["ventana_noticias"].update(dias_base=2, dias_maximo=2)
    config["volumen_noticias"]["minimo"] = 0
    return config


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    """``raw/`` dentro de ``tmp_path``: el registro de extracción queda en ``tmp_path/registro_extraccion``."""
    return tmp_path / "raw"


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


def _escribir(
    raw: Path, tema: str, ini: datetime, fin: datetime, texto: str, ts: str = "20261006T120000Z", pata: str | None = None
) -> None:
    carpeta = raw / "gdelt"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{extraer._prefijo_gdelt(tema, ini, fin, pata)}_{ts}.json").write_text(texto)


def _dia(d: int, h: int = 0, m: int = 0) -> datetime:
    return datetime(2026, 10, d, h, m, tzinfo=UTC)


def test_rangos_alineados_no_dependen_de_la_hora() -> None:
    a = extraer._rangos(datetime(2026, 10, 6, 3, 0, tzinfo=UTC), 30, 10)
    b = extraer._rangos(datetime(2026, 10, 6, 23, 59, tzinfo=UTC), 30, 10)
    assert a == b
    assert a[0][1] == datetime(2026, 10, 6, tzinfo=UTC)  # no incluye el día en curso
    assert a[-1][0] == datetime(2026, 9, 6, tzinfo=UTC)  # cubre la ventana completa


@pytest.mark.parametrize("dias", [30, 90])
def test_el_rango_mas_antiguo_se_recorta_al_inicio_de_la_ventana(dias: int) -> None:
    """H5: la ampliación a 90 días nunca pide fechas más atrás de la ventana (GDELT solo cubre ~3 meses)."""
    hoy = datetime(2026, 10, 6, 15, tzinfo=UTC)
    rangos = extraer._rangos(hoy, dias, 10)
    assert rangos[-1][0] == datetime(2026, 10, 6, tzinfo=UTC) - timedelta(days=dias)
    assert all(a[0] == b[1] for a, b in zip(rangos, rangos[1:], strict=False))
    assert sum((f - i).days for i, f in rangos) == dias


def test_crudo_existente_no_llama_a_la_api(raw: Path, cfg: dict, red: dict) -> None:
    _escribir(raw, "economia", _dia(4), _dia(5), '{"articles": []}')
    estado: dict = {}
    n = extraer._consultar_gdelt("economia", "q", _dia(4), _dia(5), raw, cfg, estado)
    assert n == 0 and red["llamadas"] == [] and estado["reutilizados"] == 1


def test_un_crudo_no_alineado_cubre_los_rangos_que_contiene(raw: Path, cfg: dict, red: dict) -> None:
    """Los crudos viejos (límites con hora) evitan volver a pedir el rango alineado que contienen."""
    _escribir(raw, "economia", _dia(1, 16, 18), _dia(6, 16, 18), '{"articles": []}')
    assert extraer._consultar_gdelt("economia", "q", _dia(4), _dia(5), raw, cfg, {}) == 0
    assert red["llamadas"] == []
    extraer._consultar_gdelt("economia", "q", _dia(1), _dia(2), raw, cfg, {})  # solo parcialmente cubierto
    assert len(red["llamadas"]) == 1


def test_forzar_vuelve_a_pedir(raw: Path, cfg: dict, red: dict) -> None:
    _escribir(raw, "economia", _dia(4), _dia(5), '{"articles": []}')
    extraer._consultar_gdelt("economia", "q", _dia(4), _dia(5), raw, cfg, {"forzar": True})
    assert len(red["llamadas"]) == 1


def test_segunda_corrida_no_repite_llamadas(raw: Path, cfg: dict, red: dict) -> None:
    extraer.extraer_gdelt(raw, cfg)
    primera = len(red["llamadas"])
    assert primera == 2  # 2 días × 1 tema
    extraer.extraer_gdelt(raw, cfg)
    # Las respuestas con la clave `articles` (aunque sea lista vacía) quedan como crudo y cuentan como cobertura.
    assert len(red["llamadas"]) == primera


def test_un_vacio_real_no_se_repite_ni_cuenta_como_cobertura(raw: Path, cfg: dict, red: dict, monkeypatch) -> None:
    """H3: un `{}` real se pide una sola vez, queda como crudo y como vacio_sospechoso; no es un vacío confirmado."""
    relojes = iter(_dia(6, 12, m) for m in range(10))  # un reloj distinto por crudo guardado
    monkeypatch.setattr(extraer, "_ahora", lambda: next(relojes))
    red["respuestas"] += [Respuesta(200, "{}")]
    estado: dict = {}
    assert extraer._consultar_gdelt("economia", "q", _dia(4), _dia(5), raw, cfg, estado) == 0
    assert len(red["llamadas"]) == 1 and red["esperas"] == []  # sin reintento y sin esperar
    assert len(list((raw / "gdelt").glob("gdelt_economia_*.json"))) == 1  # el crudo se guarda
    assert estado["sospechosos"][0]["tipo"] == "vacio_sospechoso"
    assert not conversion.rango_cubierto(raw, cfg, "economia", _dia(4), _dia(5))
    # apto para reintentar en otra corrida
    extraer._consultar_gdelt("economia", "q", _dia(4), _dia(5), raw, cfg, {})
    assert len(red["llamadas"]) == 2


def test_la_ampliacion_a_90_dias_no_repite_un_rango_ya_pedido(raw: Path, cfg: dict, red: dict, monkeypatch) -> None:
    monkeypatch.setattr(extraer, "_ahora", lambda: _dia(6, 12))
    cfg["ventana_noticias"].update(dias_base=1, dias_maximo=2)
    cfg["volumen_noticias"]["minimo"] = 10  # fuerza la ampliación
    red["respuestas"] += [Respuesta(200, "{}"), Respuesta(200, "{}")]
    extraer.extraer_gdelt(raw, cfg)
    assert [p["startdatetime"] for p in red["llamadas"]] == ["20261005000000", "20261004000000"]  # 10-05 una vez
    registro = json.loads(next((raw.parent / "registro_extraccion").glob("fallos_gdelt_*.json")).read_text("utf-8"))
    assert registro["origen"] == extraer.ORIGEN_REGISTRO_HERRAMIENTA
    assert {f["tipo"] for f in registro["fallos"]} == {"vacio_sospechoso"} and len(registro["fallos"]) == 2


def test_rango_al_tope_guarda_la_respuesta_original_y_se_subdivide(raw: Path, cfg: dict, red: dict) -> None:
    """H4: la respuesta que llega al tope se guarda sin modificar y no cubre sola; sus mitades sí."""
    cfg["gdelt"].update(maxrecords=2, rango_minimo_horas=12)
    tope = json.dumps({"articles": [{"url": "https://a.test/1", "title": "a"}, {"url": "https://a.test/2", "title": "b"}]})
    red["respuestas"] += [Respuesta(200, tope)]  # las mitades responden con el valor por defecto (sin artículos)
    n = extraer._consultar_gdelt("economia", "q", _dia(4), _dia(5), raw, cfg, {})
    assert n == 2
    assert [p["startdatetime"] + "-" + p["enddatetime"] for p in red["llamadas"]] == [
        "20261004000000-20261005000000",
        "20261004000000-20261004120000",
        "20261004120000-20261005000000",
    ]
    clases = {c["archivo"][:60]: c["clase"] for c in conversion.crudos_gdelt(raw, cfg)}
    assert sorted(clases.values()) == ["ok", "ok", "truncado"]
    original = next(p for p in (raw / "gdelt").glob("gdelt_economia_20261004000000_20261005000000_*.json"))
    assert original.read_text("utf-8") == tope  # sin modificar
    assert conversion.rango_cubierto(raw, cfg, "economia", _dia(4), _dia(5))  # por sus mitades
    llamadas = len(red["llamadas"])
    extraer._consultar_gdelt("economia", "q", _dia(4), _dia(5), raw, cfg, {})
    assert len(red["llamadas"]) == llamadas  # la segunda vez no pide nada


def test_respuesta_al_tope_sin_mitades_no_cubre_el_rango(raw: Path, cfg: dict) -> None:
    cfg["gdelt"].update(maxrecords=1, rango_minimo_horas=12)
    _escribir(raw, "economia", _dia(4), _dia(5), json.dumps({"articles": [{"url": "https://a.test/1"}]}))
    assert not conversion.rango_cubierto(raw, cfg, "economia", _dia(4), _dia(5))
    cfg["gdelt"]["rango_minimo_horas"] = 24  # ya no se puede subdividir: es lo mejor que hay
    assert conversion.rango_cubierto(raw, cfg, "economia", _dia(4), _dia(5))


def test_cobertura_por_tema_lista_cada_rango_sin_resolver_con_su_motivo(raw: Path, cfg: dict) -> None:
    cfg["gdelt"]["consultas"] = {t: {"locales": PATA_UNICA} for t in ("economia", "turismo", "logistica", "eventos_naturales")}
    _escribir(raw, "economia", _dia(1, 16, 18), _dia(6, 16, 18), '{"articles": []}', pata="locales")  # no alineado: días 2..5
    _escribir(raw, "logistica", _dia(4), _dia(6), "{}", pata="locales")  # un {} no cubre
    carpeta_registro = raw.parent / cfg["general"]["carpeta_registro"]
    carpeta_registro.mkdir()
    conversion.escribir_json(
        carpeta_registro / "registro_manual_20261006T171832Z.json",
        {"origen": "x", "fallos": [{"tema": "turismo", "pata": "locales", "inicio": "20261004000000", "fin": "20261006000000", "motivo": "HTTP 429", "tipo": "bloqueado"}]},
    )
    cob = conversion.cobertura_gdelt(raw, cfg, _dia(6, 12), 6)  # días 10-01 .. 10-05
    assert cob["por_tema"] == {
        "economia": {"dias_esperados": 6, "dias_cubiertos": 4},
        "turismo": {"dias_esperados": 6, "dias_cubiertos": 0},
        "logistica": {"dias_esperados": 6, "dias_cubiertos": 0},
        "eventos_naturales": {"dias_esperados": 6, "dias_cubiertos": 0},
    }
    pendientes = {(r["tema"], r["inicio"][:8], r["fin"][:8]): r["motivo"] for r in cob["sin_resolver"]}
    assert pendientes[("economia", "20261001", "20261002")] == "cobertura_parcial"
    assert pendientes[("economia", "20260930", "20261001")] == "no_solicitado"
    assert pendientes[("logistica", "20261004", "20261006")] == "vacio_sospechoso"
    assert pendientes[("turismo", "20261004", "20261006")] == "bloqueado"
    assert pendientes[("turismo", "20260930", "20261004")] == "no_solicitado"
    assert pendientes[("eventos_naturales", "20260930", "20261006")] == "no_solicitado"


def test_429_con_retry_after_espera_ese_valor(tmp_path: Path, cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(429, "slow down", {"Retry-After": "7"}), Respuesta()]
    resp = extraer._pedir_gdelt({"query": "x"}, cfg)
    assert resp.status_code == 200 and red["esperas"] == [7]


def test_429_sin_retry_after_usa_backoff_exponencial(cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(429), Respuesta(429), Respuesta()]
    extraer._pedir_gdelt({"query": "x"}, cfg)
    base = cfg["gdelt"]["espera_429_segundos"]
    assert red["esperas"] == [base, base * 2]


def test_agotar_intentos_registra_el_fallo_y_continua(raw: Path, cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(429)] * 3  # agota el primer rango (3 intentos)
    # el segundo rango responde bien (la cola se vacía y el falso devuelve 200)
    with pytest.raises(extraer.ErrorDeExtraccion):
        extraer.extraer_gdelt(raw, cfg)
    assert len(red["llamadas"]) == 3 + 1  # 3 intentos fallidos + el rango siguiente
    # H1: el registro de fallos vive fuera de raw/ (raw solo guarda respuestas de la API)
    assert list((raw / "gdelt").glob("fallos_*")) == []
    fallos = list((raw.parent / "registro_extraccion").glob("fallos_gdelt_*.json"))
    assert len(fallos) == 1
    registrado = json.loads(fallos[0].read_text("utf-8"))
    assert registrado["origen"] == "generado por scripts.extraer"
    assert len(registrado["fallos"]) == 1 and registrado["fallos"][0]["tema"] == "economia"
    # la cobertura lo reporta como bloqueado
    _, _, auditoria = conversion.convertir_noticias(raw, cfg)
    assert [r["motivo"] for r in auditoria["gdelt_rangos_sin_resolver"]] == ["bloqueado"]


def test_un_fallo_resuelto_despues_deja_de_reportarse(raw: Path, cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(429)] * 3
    with pytest.raises(extraer.ErrorDeExtraccion):
        extraer.extraer_gdelt(raw, cfg)
    extraer.extraer_gdelt(raw, cfg)  # solo pide el rango que faltaba
    _, _, auditoria = conversion.convertir_noticias(raw, cfg)
    assert auditoria["gdelt_rangos_sin_resolver"] == []
    assert auditoria["gdelt_cobertura_por_tema"]["economia"]["dias_cubiertos"] == 2


def test_cuerpo_que_no_es_json_de_gdelt_no_se_guarda_y_se_reintenta(raw: Path, cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(200, "<html>limite de solicitudes</html>"), Respuesta()]
    extraer._consultar_gdelt("economia", "q", _dia(4), _dia(5), raw, cfg, {})
    assert len(red["llamadas"]) == 2 and red["esperas"] == [cfg["gdelt"]["espera_429_segundos"]]
    guardados = list((raw / "gdelt").glob("gdelt_*.json"))
    assert len(guardados) == 1 and "html" not in guardados[0].read_text("utf-8")


def test_pedir_gdelt_devuelve_el_vacio_sin_repetir_la_llamada(cfg: dict, red: dict) -> None:
    red["respuestas"] += [Respuesta(200, "{}"), Respuesta(200, "{}")]
    assert extraer._pedir_gdelt({"query": "x"}, cfg).text == "{}"
    assert len(red["llamadas"]) == 1


def test_clasificar_respuesta() -> None:
    c = extraer._clasificar_respuesta
    assert c('{"articles": []}') == "ok" and c('{"articles": [{"url": "x"}]}') == "ok"
    assert c("{}") == "vacio" and c("") == "vacio" and c("   ") == "vacio"
    assert c("limite de solicitudes") == "invalido" and c('{"error": "x"}') == "invalido"


# ------------------------------------------------- E0-04 seguimiento: patas por tema y bandera de ampliación

PATAS = {
    "economia": {
        "locales": {"descripcion": "d", "filtros": ["sourcecountry:panama"], "terminos": ["economía", "inflación"]},
        "internacional": {"descripcion": "d", "filtros": ["-sourcecountry:panama"], "terminos": ["Panama economy", "Panama GDP"]},
    }
}


def test_cada_pata_hace_una_llamada_con_su_consulta_y_guarda_su_crudo(raw: Path, cfg: dict, red: dict, monkeypatch) -> None:
    monkeypatch.setattr(extraer, "_ahora", lambda: _dia(6, 12))
    cfg["gdelt"]["consultas"] = PATAS
    cfg["ventana_noticias"].update(dias_base=1, dias_maximo=1)
    extraer.extraer_gdelt(raw, cfg)
    assert [p["query"] for p in red["llamadas"]] == [
        "(economía OR inflación) sourcecountry:panama",
        '("Panama economy" OR "Panama GDP") -sourcecountry:panama',
    ]
    nombres = sorted(p.name.split("_2026")[0] for p in (raw / "gdelt").glob("gdelt_*.json"))
    assert nombres == ["gdelt_economia__internacional", "gdelt_economia__locales"]
    assert all(c["tema"] == "economia" for c in conversion.crudos_gdelt(raw, cfg))  # D-62: tema = tema


def test_un_crudo_de_una_pata_no_cubre_a_la_otra(raw: Path, cfg: dict) -> None:
    cfg["gdelt"]["consultas"] = PATAS
    _escribir(raw, "economia", _dia(4), _dia(5), '{"articles": []}')  # sin pata: consulta anterior a E0-04
    assert not conversion.rango_cubierto(raw, cfg, "economia", _dia(4), _dia(5), "locales")
    nombre = extraer._prefijo_gdelt("economia", _dia(4), _dia(5), "locales")
    (raw / "gdelt" / f"{nombre}_20261006T120000Z.json").write_text('{"articles": []}')
    assert conversion.rango_cubierto(raw, cfg, "economia", _dia(4), _dia(5), "locales")
    assert not conversion.rango_cubierto(raw, cfg, "economia", _dia(4), _dia(5), "internacional")
    cob = conversion.cobertura_gdelt(raw, cfg, _dia(5, 12), 1)
    assert cob["por_tema"]["economia"] == {"dias_esperados": 1, "dias_cubiertos": 0}
    assert cob["sin_resolver"][0]["detalle"].startswith("[internacional]")


@pytest.mark.parametrize("bandera, llamadas", [(True, ["20261005000000", "20261004000000"]), (False, ["20261005000000"])])
def test_la_ampliacion_a_90_dias_depende_de_la_bandera(raw: Path, cfg: dict, red: dict, monkeypatch, bandera, llamadas) -> None:
    monkeypatch.setattr(extraer, "_ahora", lambda: _dia(6, 12))
    cfg["ventana_noticias"].update(dias_base=1, dias_maximo=2, ampliar_si_no_alcanza_minimo=bandera)
    cfg["volumen_noticias"]["minimo"] = 10
    extraer.extraer_gdelt(raw, cfg)
    assert [p["startdatetime"] for p in red["llamadas"]] == llamadas
