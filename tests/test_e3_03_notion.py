"""E3-03 · Sincronización de fichas con Notion. La API se simula: ninguna prueba usa la red ni escribe en el Notion real."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
import requests

from src import embeddings, exportar, notion
from src.configuracion import cargar_notion, cargar_revision, validar_coherencia
from src.notion import ClienteNotion, ErrorNotion, SinConexion, bloques_de_markdown, propiedad, propiedades_de_fila
from src.registro import FiltroRedaccion, olvidar_sensibles, registrar_sensible
from src.revision import Revisiones
from tests import ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.test_e1_16_revision import EDITORIAL, _reloj, abrir

CFG = cargar_notion()
REV = cargar_revision()
TOKEN = "secret_tokenDePrueba1234567890abcdef"


class Resp:
    def __init__(self, estado: int = 200, datos: dict[str, Any] | None = None, cabeceras: dict[str, str] | None = None) -> None:
        self.status_code, self._datos, self.headers = estado, datos if datos is not None else {}, cabeceras or {}

    def json(self) -> dict[str, Any]:
        return self._datos


class NotionFalso:
    """Un Notion en memoria: una base con páginas y cuerpos; registra cada llamada."""

    def __init__(self, paginas: list[dict[str, Any]] | None = None) -> None:
        self.paginas: dict[str, dict[str, Any]] = {p["id"]: {**p, "hijos": ["viejo-1", "viejo-2"]} for p in (paginas or [])}
        self.llamadas: list[tuple[str, str, dict[str, Any] | None]] = []
        self.cabeceras: list[dict[str, str]] = []
        self.respuestas_forzadas: list[Resp] = []
        self.n = 0

    def request(self, metodo: str, url: str, json: dict[str, Any] | None = None, params: Any = None, headers: Any = None, timeout: Any = None) -> Resp:
        ruta = url.removeprefix(CFG.api.base_url).strip("/")
        self.llamadas.append((metodo, ruta, json))
        self.cabeceras.append(headers)
        if self.respuestas_forzadas:
            return self.respuestas_forzadas.pop(0)
        if metodo == "POST" and ruta == f"databases/{CFG.base_de_datos.id}/query":
            titulo = json["filter"]["title"]["equals"]
            hallados = [p for p in self.paginas.values() if p["titulo"] == titulo]
            return Resp(200, {"results": [{"id": p["id"], "archived": False} for p in hallados]})
        if metodo == "POST" and ruta == "pages":
            self.n += 1
            pid = f"nueva-{self.n}"
            self.paginas[pid] = {"id": pid, "titulo": json["properties"]["ID caso"]["title"][0]["text"]["content"], "props": json["properties"], "hijos": []}
            return Resp(200, {"id": pid, "url": f"https://notion.so/{pid}"})
        if metodo == "PATCH" and ruta.startswith("pages/"):
            pid = ruta.split("/")[1]
            self.paginas[pid]["props"] = json["properties"]
            return Resp(200, {"id": pid, "url": f"https://notion.so/{pid}"})
        if metodo == "GET" and ruta.endswith("/children"):
            pid = ruta.split("/")[1]
            return Resp(200, {"results": [{"id": b} for b in self.paginas[pid]["hijos"]], "has_more": False})
        if metodo == "DELETE" and ruta.startswith("blocks/"):
            for p in self.paginas.values():
                if ruta.split("/")[1] in p["hijos"]:
                    p["hijos"].remove(ruta.split("/")[1])
            return Resp(200, {})
        if metodo == "PATCH" and ruta.endswith("/children"):
            pid = ruta.split("/")[1]
            self.paginas[pid]["hijos"] += [f"b{i}-{len(self.paginas[pid]['hijos'])}" for i, _ in enumerate(json["children"])]
            self.paginas[pid].setdefault("bloques", []).extend(json["children"])
            return Resp(200, {})
        return Resp(404, {"code": "object_not_found", "message": "no existe"})


def cliente(falso: NotionFalso, esperas: list[float] | None = None) -> ClienteNotion:
    return ClienteNotion(TOKEN, CFG, falso, dormir=(esperas if esperas is not None else []).append)


@pytest.fixture(autouse=True)
def _token_registrado():
    registrar_sensible(TOKEN)
    yield
    olvidar_sensibles()


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(scope="module")
def base(tmp_path_factory, emb) -> Path:
    return h.construir(tmp_path_factory.mktemp("rev") / "senales.duckdb", emb)


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch, emb):
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)


@pytest.fixture
def exportado(tmp_path, base) -> exportar.Exportacion:
    rev = Revisiones(tmp_path / "revision.duckdb", base, ahora=_reloj())
    c = abrir(rev).id_caso
    rev.aceptar(c, EDITORIAL, "ok")
    return exportar.exportar_caso(rev, c, tmp_path / "n", tmp_path / "f.jsonl")


# ------------------------------------------------------------------ configuración


def test_las_propiedades_de_notion_son_exactamente_las_columnas_exportadas() -> None:
    assert set(CFG.propiedades) == set(REV.exportacion.columnas)
    assert validar_coherencia() == []


# ------------------------------------------------------------------ conversión


def test_cada_valor_se_convierte_al_tipo_de_propiedad_de_notion() -> None:
    assert propiedad("titulo", "CASO-001", 2000) == {"title": [{"type": "text", "text": {"content": "CASO-001"}}]}
    assert propiedad("numero", "4.5", 2000) == {"number": 4.5}
    assert propiedad("numero", "", 2000) == {"number": None}                  # los nulos son nulos: nunca cero
    assert propiedad("seleccion", "", 2000) == {"select": None}
    assert propiedad("seleccion", "Aprobado como borrador", 2000) == {"select": {"name": "Aprobado como borrador"}}
    with pytest.raises(ErrorNotion, match="no numérico"):
        propiedad("numero", "n/d", 2000)                                       # error de la API de Notion, no una traza de ValueError
    assert propiedad("fecha", "2026-10-07T12:00:00Z", 2000) == {"date": {"start": "2026-10-07T12:00:00Z"}}
    largo = propiedad("texto", "x" * 4500, 2000)["rich_text"]
    assert [len(t["text"]["content"]) for t in largo] == [2000, 2000, 500]


PROVISIONAL = "Asistente (provisional, D-101)"


def test_la_fila_enviada_es_la_del_csv_con_la_marca_provisional(tmp_path, base) -> None:
    rev = Revisiones(tmp_path / "revision.duckdb", base, ahora=_reloj())
    c = abrir(rev, revisor=PROVISIONAL).id_caso
    rev.aceptar(c, PROVISIONAL, "ok")
    exportado = exportar.exportar_caso(rev, c, tmp_path / "n", tmp_path / "f.jsonl")
    falso = NotionFalso()
    cliente(falso).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    pagina = next(iter(falso.paginas.values()))
    en_revisor = pagina["props"]["Revisor"]["rich_text"][0]["text"]["content"]
    en_cuerpo = "\n".join(t["text"]["content"] for b in pagina["bloques"] for t in b[b["type"]]["rich_text"])
    assert PROVISIONAL in en_revisor and "provisional (D-101)" in en_revisor       # D-112: la marca viaja en la propiedad...
    assert "provisional (D-101)" in en_cuerpo                                      # ...y en el cuerpo
    props = propiedades_de_fila(exportado.fila, CFG)
    assert set(props) == set(REV.exportacion.columnas)
    revisor = props["Revisor"]["rich_text"][0]["text"]["content"]
    assert revisor == exportado.fila["Revisor"]
    assert all(len(t["text"]["content"]) <= 2000 for p in props.values() for t in p.get("rich_text", []))
    with pytest.raises(ErrorNotion):
        propiedades_de_fila({"ID caso": "CASO-001"}, CFG)


def test_el_markdown_pasa_a_bloques_literales(exportado) -> None:
    bloques = bloques_de_markdown(exportado.markdown, CFG)
    tipos = {b["type"] for b in bloques}
    assert {"heading_1", "heading_2", "bulleted_list_item", "paragraph"} <= tipos
    assert bloques[0]["heading_1"]["rich_text"][0]["text"]["content"].startswith("CASO-")
    assert all(len(t["text"]["content"]) <= 2000 for b in bloques for t in b[b["type"]]["rich_text"])
    assert all("link" not in t["text"] for b in bloques for t in b[b["type"]]["rich_text"])


# ------------------------------------------------------------------ sincronización idempotente


def test_un_caso_nuevo_crea_una_pagina_con_propiedades_y_cuerpo(exportado) -> None:
    falso = NotionFalso()
    s = cliente(falso).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert s.creada and s.bloques > 5 and len(falso.paginas) == 1
    pagina = falso.paginas[s.id_pagina]
    assert pagina["props"]["ID caso"]["title"][0]["text"]["content"] == exportado.id_caso
    assert len(pagina["bloques"]) == s.bloques
    assert "P" not in pagina["props"] and "Rango" not in pagina["props"]       # fórmulas de Notion


def test_resincronizar_actualiza_la_misma_pagina_y_no_duplica(exportado) -> None:
    falso = NotionFalso()
    c = cliente(falso)
    a = c.sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    b = c.sincronizar(exportado.id_caso, {**exportado.fila, "Comentario del revisor": "nuevo"}, exportado.markdown)
    d = c.sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert a.creada and not b.creada and not d.creada
    assert a.id_pagina == b.id_pagina == d.id_pagina and len(falso.paginas) == 1
    assert [m for m, r, _ in falso.llamadas if (m, r) == ("POST", "pages")] == ["POST"]       # se crea una sola vez
    assert len(falso.paginas[a.id_pagina]["hijos"]) == a.bloques                                # el cuerpo se reemplaza, no se acumula


def test_una_pagina_existente_de_una_importacion_previa_se_actualiza(exportado) -> None:
    falso = NotionFalso([{"id": "previa", "titulo": exportado.id_caso, "props": {}}])
    s = cliente(falso).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert not s.creada and s.id_pagina == "previa" and falso.paginas["previa"]["hijos"][:2] != ["viejo-1", "viejo-2"]


def test_con_paginas_duplicadas_se_detiene_sin_escribir(exportado) -> None:
    falso = NotionFalso([{"id": "a", "titulo": exportado.id_caso}, {"id": "b", "titulo": exportado.id_caso}])
    with pytest.raises(ErrorNotion, match="2 páginas"):
        cliente(falso).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert all(m == "POST" and r.endswith("/query") for m, r, _ in falso.llamadas)             # solo la búsqueda


def test_la_fila_de_otro_caso_se_rechaza(exportado) -> None:
    with pytest.raises(ErrorNotion):
        cliente(NotionFalso()).sincronizar("CASO-099", exportado.fila, exportado.markdown)


# ------------------------------------------------------------------ red, límites y errores


def test_el_429_se_reintenta_de_forma_acotada(exportado) -> None:
    falso, esperas = NotionFalso(), []
    falso.respuestas_forzadas = [Resp(429, {}, {"Retry-After": "2"}), Resp(200, {"results": []})]
    assert cliente(falso, esperas).buscar_paginas("CASO-001") == [] and esperas == [2.0]
    falso.respuestas_forzadas = [Resp(429)] * (CFG.api.reintentos + 1)
    with pytest.raises(ErrorNotion, match="HTTP 429"):
        cliente(falso, esperas).buscar_paginas("CASO-001")
    assert len(falso.llamadas) == 2 + CFG.api.reintentos + 1


def test_un_error_4xx_no_se_reintenta_y_no_filtra_el_token() -> None:
    falso = NotionFalso()
    falso.respuestas_forzadas = [Resp(401, {"code": "unauthorized", "message": f"API token is invalid {TOKEN}"})]
    with pytest.raises(ErrorNotion) as e:
        cliente(falso).buscar_paginas("CASO-001")
    assert "HTTP 401" in str(e.value) and TOKEN not in str(e.value) and len(falso.llamadas) == 1


def test_el_token_solo_viaja_en_la_cabecera(exportado) -> None:
    falso = NotionFalso()
    cliente(falso).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert all(c["Authorization"] == f"Bearer {TOKEN}" and c["Notion-Version"] == CFG.api.version for c in falso.cabeceras)
    assert TOKEN not in json.dumps([c for _, _, c in falso.llamadas], default=str)


class SinRed:
    def request(self, *a: Any, **k: Any) -> Any:
        raise requests.ConnectionError(f"fallo con {TOKEN}")


def test_sin_red_se_lanza_sin_conexion_sin_filtrar_el_token() -> None:
    with pytest.raises(SinConexion) as e:
        ClienteNotion(TOKEN, CFG, SinRed()).buscar_paginas("CASO-001")
    assert TOKEN not in str(e.value) and e.value.__cause__ is None


# ------------------------------------------------------------------ integración con la CLI de exportación


def test_sin_token_la_exportacion_local_queda_y_se_avisa(exportado, capsys) -> None:
    assert exportar.sincronizar_con_notion(exportado, env={}) == 0
    err = capsys.readouterr().err
    assert "No se sincronizó con Notion" in err and "NOTION_TOKEN" in err and exportado.ruta_markdown.exists() and exportado.ruta_csv.exists()


def test_sin_red_la_exportacion_local_queda_y_se_avisa(exportado, capsys) -> None:
    c = ClienteNotion(TOKEN, CFG, SinRed())
    assert exportar.sincronizar_con_notion(exportado, cliente=c) == 0
    err = capsys.readouterr().err
    assert "no hay conexión" in err and TOKEN not in err


def test_un_error_de_la_api_devuelve_1_sin_imprimir_el_token(exportado, capsys) -> None:
    falso = NotionFalso()
    falso.respuestas_forzadas = [Resp(403, {"code": "restricted_resource", "message": "sin acceso"})]
    assert exportar.sincronizar_con_notion(exportado, cliente=cliente(falso)) == 1
    err = capsys.readouterr().err
    assert "HTTP 403" in err and TOKEN not in err


def test_la_sincronizacion_exitosa_informa_la_pagina(exportado, capsys) -> None:
    assert exportar.sincronizar_con_notion(exportado, cliente=cliente(NotionFalso())) == 0
    out = capsys.readouterr().out
    assert f"{exportado.id_caso}: creada en Notion" in out and "https://notion.so/nueva-1" in out


def test_demo_con_notion_se_rechaza(capsys) -> None:
    assert exportar.principal(["--caso", "CASO-001", "--demo", "--notion"]) == 1
    assert "--demo" in capsys.readouterr().err


def test_la_cli_con_notion_sin_token_exporta_y_avisa(tmp_path, base, monkeypatch, capsys) -> None:
    rev = Revisiones(tmp_path / "revision.duckdb", base, ahora=_reloj())
    c = abrir(rev).id_caso
    rev.aceptar(c, EDITORIAL, "ok")
    monkeypatch.setattr(exportar, "leer_local_env", lambda: {})
    argv = ["--caso", c, "--revision", str(rev.ruta), "--base", str(rev.base_fichas), "--salida", str(tmp_path / "n"), "--fichas", str(tmp_path / "f.jsonl"), "--notion"]
    assert exportar.principal(argv) == 0
    cap = capsys.readouterr()
    assert f"{c}: exportado" in cap.out and "No se sincronizó con Notion" in cap.err and (tmp_path / "n" / f"{c}.md").exists()


def test_el_filtro_de_logging_redacta_el_token(caplog) -> None:
    caplog.set_level(logging.WARNING)
    registro = logging.LogRecord("x", logging.WARNING, __file__, 1, f"cabecera Bearer {TOKEN}", (), None)
    FiltroRedaccion().filter(registro)
    assert TOKEN not in registro.msg


def test_el_modulo_no_tiene_numeros_magicos_de_red() -> None:
    codigo = Path(notion.__file__).read_text(encoding="utf-8")
    assert "2000" not in codigo and "api.notion.com" not in codigo
    assert '"page_size": 10' not in codigo and '"page_size": 100' not in codigo      # X98: viven en config/notion.yaml


def test_los_tamanos_de_pagina_salen_de_la_configuracion(exportado) -> None:
    falso = NotionFalso([{"id": "p", "titulo": exportado.id_caso}])
    tamanos: list[Any] = []
    real = falso.request

    def req(m: str, url: str, json: Any = None, params: Any = None, **k: Any) -> Resp:
        tamanos.append((json or {}).get("page_size") or (params or {}).get("page_size"))
        return real(m, url, json=json, params=params, **k)

    cliente_ = ClienteNotion(TOKEN, CFG, type("S", (), {"request": staticmethod(req)})(), dormir=lambda s: None)
    cliente_.sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert {CFG.api.tamano_pagina_busqueda, CFG.api.tamano_pagina_hijos} <= set(tamanos)


# ------------------------------------------------------------------ revisión independiente PR #46 (X95-X97)


def _con_fallo(falso: NotionFalso, cuando, efecto):
    """Sesión que delega en ``falso`` salvo cuando ``cuando(metodo, ruta, n)`` es cierto: ahí devuelve/lanza ``efecto``. ``n`` cuenta esa ruta."""
    real, cuenta = falso.request, {}

    def req(m: str, url: str, **k: Any):
        ruta = url.removeprefix(CFG.api.base_url).strip("/")
        cuenta[(m, ruta.split("/")[-1])] = cuenta.get((m, ruta.split("/")[-1]), 0) + 1
        if cuando(m, ruta, cuenta[(m, ruta.split("/")[-1])]):
            r = efecto(real, m, url, k)
            if isinstance(r, Exception):
                raise r
            return r
        return real(m, url, **k)

    return type("S", (), {"request": staticmethod(req)})()


def test_x95_si_falla_al_agregar_el_cuerpo_anterior_se_conserva(exportado, capsys) -> None:
    falso = NotionFalso([{"id": "p1", "titulo": exportado.id_caso}])
    s = _con_fallo(falso, lambda m, r, n: m == "PATCH" and r.endswith("/children"), lambda *a: Resp(400, {"code": "validation_error", "message": "body failed"}))
    assert exportar.sincronizar_con_notion(exportado, cliente=ClienteNotion(TOKEN, CFG, s, dormir=lambda x: None)) == 1
    assert falso.paginas["p1"]["hijos"] == ["viejo-1", "viejo-2"]                     # nunca queda vacía
    assert not [1 for m, _, _ in falso.llamadas if m == "DELETE"]                      # no se borró nada antes de agregar


def test_x95_el_cuerpo_viejo_se_borra_solo_despues_de_agregar_el_nuevo(exportado) -> None:
    falso = NotionFalso([{"id": "p1", "titulo": exportado.id_caso}])
    cliente(falso).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    orden = [m for m, r, _ in falso.llamadas if r.endswith("/children") and m == "PATCH" or m == "DELETE"]
    assert orden.index("DELETE") > max(i for i, m in enumerate(orden) if m == "PATCH")
    assert not {"viejo-1", "viejo-2"} & set(falso.paginas["p1"]["hijos"])


def test_x96_un_corte_despues_de_escribir_es_sincronizacion_incompleta_con_codigo_1(exportado, capsys) -> None:
    falso = NotionFalso([{"id": "p1", "titulo": exportado.id_caso}])
    s = _con_fallo(falso, lambda m, r, n: m == "PATCH" and r.endswith("/children"), lambda *a: requests.Timeout(f"t {TOKEN}"))
    assert exportar.sincronizar_con_notion(exportado, cliente=ClienteNotion(TOKEN, CFG, s, dormir=lambda x: None)) == 1
    err = capsys.readouterr().err
    assert "Sincronización incompleta" in err and exportado.id_caso in err and "no hay conexión" not in err and TOKEN not in err
    assert exportado.ruta_markdown.exists() and exportado.ruta_csv.exists()


def test_x96_un_corte_antes_de_escribir_sigue_siendo_sin_conexion_con_codigo_0(exportado, capsys) -> None:
    falso = NotionFalso()
    s = _con_fallo(falso, lambda m, r, n: r.endswith("/query"), lambda *a: requests.ConnectionError("x"))
    assert exportar.sincronizar_con_notion(exportado, cliente=ClienteNotion(TOKEN, CFG, s, dormir=lambda x: None)) == 0
    assert "no hay conexión" in capsys.readouterr().err and not falso.paginas


def test_x97_un_502_tras_crear_no_duplica_la_pagina(exportado) -> None:
    falso = NotionFalso()
    s = _con_fallo(falso, lambda m, r, n: m == "POST" and r == "pages" and n == 1, lambda real, m, url, k: (real(m, url, **k), Resp(502, {}))[1])   # Notion crea y la respuesta se pierde
    r = ClienteNotion(TOKEN, CFG, s, dormir=lambda x: None).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert len(falso.paginas) == 1 and [m for m, rt, _ in falso.llamadas if (m, rt) == ("POST", "pages")] == ["POST"]
    assert falso.paginas[r.id_pagina]["bloques"]                                       # y la página quedó completa


def test_x97_un_502_sin_que_se_haya_creado_reintenta_la_creacion_una_vez_confirmada_su_ausencia(exportado) -> None:
    falso = NotionFalso()
    s = _con_fallo(falso, lambda m, r, n: m == "POST" and r == "pages" and n == 1, lambda *a: Resp(502, {}))
    ClienteNotion(TOKEN, CFG, s, dormir=lambda x: None).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert len(falso.paginas) == 1


def test_x97_el_append_de_bloques_no_se_reintenta_ante_5xx_pero_si_ante_429(exportado) -> None:
    falso = NotionFalso([{"id": "p1", "titulo": exportado.id_caso}])
    s = _con_fallo(falso, lambda m, r, n: m == "PATCH" and r.endswith("/children") and n == 1, lambda *a: Resp(503, {}))
    with pytest.raises(ErrorNotion):
        ClienteNotion(TOKEN, CFG, s, dormir=lambda x: None).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert sum(1 for m, r, _ in falso.llamadas if m == "PATCH" and r.endswith("/children")) == 0     # el 503 cortó antes de llegar al fake: 1 intento
    falso2, esperas = NotionFalso([{"id": "p1", "titulo": exportado.id_caso}]), []
    s2 = _con_fallo(falso2, lambda m, r, n: m == "PATCH" and r.endswith("/children") and n == 1, lambda *a: Resp(429, {}, {"Retry-After": "1"}))
    ClienteNotion(TOKEN, CFG, s2, dormir=esperas.append).sincronizar(exportado.id_caso, exportado.fila, exportado.markdown)
    assert esperas == [1.0] and falso2.paginas["p1"]["bloques"]
