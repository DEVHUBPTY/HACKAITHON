"""E1-12 · Proveedores LLM: DeepSeek, tope de costo (D-67), cambio por LLM_PROVIDER y registro de tokens y latencia."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from src.configuracion import cargar_generacion, cargar_llm
from src.llm.costo import ProveedorConTope, RegistroCosto, TopeDeCostoAlcanzado
from src.llm.deepseek import ProveedorDeepSeek
from src.llm.ollama import ProveedorOllama
from src.llm.proveedor import ErrorProveedor, crear_proveedor

CLAVE = "sk-prueba-" + "z" * 24


class _Resp:
    def __init__(self, cuerpo: dict[str, Any], estado: int = 200) -> None:
        self.cuerpo, self.estado = cuerpo, estado

    def raise_for_status(self) -> None:
        if self.estado >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.estado}")

    def json(self) -> dict[str, Any]:
        return self.cuerpo


class _Sesion:
    """Simula la API de chat de DeepSeek (compatible con OpenAI) y de Ollama; registra lo enviado."""

    def __init__(self, contenido: str = '{"ok": true}', entrada: int = 1000, salida: int = 500) -> None:
        self.contenido, self.entrada, self.salida = contenido, entrada, salida
        self.enviados: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> _Resp:
        self.enviados.append((url, kwargs.get("json", {}), kwargs.get("headers", {})))
        if url.endswith("/api/chat"):  # Ollama
            return _Resp({"message": {"content": self.contenido}, "prompt_eval_count": self.entrada, "eval_count": self.salida})
        return _Resp({"choices": [{"message": {"content": self.contenido}}], "usage": {"prompt_tokens": self.entrada, "completion_tokens": self.salida}})

    def get(self, url: str, **kwargs: Any) -> _Resp:
        return _Resp({})


def _deepseek(sesion: _Sesion) -> ProveedorDeepSeek:
    return ProveedorDeepSeek(CLAVE, cargar_generacion(), cargar_llm(), sesion)


def test_deepseek_pide_json_con_temperatura_cero_y_la_clave_va_solo_en_el_encabezado() -> None:
    sesion = _Sesion()
    p = _deepseek(sesion)
    assert p.generar_json("SYS json", "USR", {"type": "object"}) == '{"ok": true}'
    ((url, cuerpo, encabezados),) = sesion.enviados
    assert url == "https://api.deepseek.com/chat/completions"
    assert cuerpo["temperature"] == 0 and cuerpo["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in cuerpo["messages"]] == ["system", "user"]
    assert cuerpo["thinking"] == {"type": "disabled"} and cuerpo["model"] == cargar_generacion().deepseek.modelo
    assert "tools" not in cuerpo and "tool_choice" not in cuerpo  # el modelo no tiene herramientas
    assert CLAVE not in json.dumps(cuerpo) and encabezados["Authorization"] == f"Bearer {CLAVE}"


def test_deepseek_respuesta_vacia_o_caida_es_error_de_proveedor_sin_la_clave() -> None:
    with pytest.raises(ErrorProveedor, match="vacía"):
        _deepseek(_Sesion(contenido="")).generar_json("s", "u", {})

    class Caida(_Sesion):
        def post(self, url: str, **kwargs: Any) -> _Resp:
            return _Resp({}, 500)

    with pytest.raises(ErrorProveedor) as e:
        _deepseek(Caida()).generar_json("s", "u", {})
    assert CLAVE not in str(e.value)


def test_cada_llamada_registra_tokens_y_latencia_sin_secretos_ni_prompts(caplog: pytest.LogCaptureFixture) -> None:
    from src.registro import registrar_sensible

    registrar_sensible(CLAVE)
    with caplog.at_level(logging.INFO):
        p = _deepseek(_Sesion(entrada=321, salida=45))
        p.generar_json("SYSTEM-SECRETO-NO-LOGUEAR", "USUARIO-NO-LOGUEAR", {})
        o = ProveedorOllama("localhost:11434", "m", cargar_llm(), _Sesion(entrada=111, salida=22))
        o.generar_json("s", "u", {})
    for uso, (ent, sal) in ((p.ultimo_uso, (321, 45)), (o.ultimo_uso, (111, 22))):
        assert (uso.tokens_entrada, uso.tokens_salida) == (ent, sal) and uso.latencia_s >= 0
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "tokens_entrada=321" in texto and "tokens_salida=22" in texto and "latencia_s=" in texto
    assert CLAVE not in texto and "SYSTEM-SECRETO" not in texto and "USUARIO-NO" not in texto


# ------------------------------------------------------------------ tope de costo (D-67, D-95)


def _con_tope(tmp_path: Path | None, deepseek: _Sesion, tope_tokens: int = 10_000, tope_usd: float = 1.0) -> ProveedorConTope:
    gen = cargar_generacion()
    tope = gen.tope_costo.model_copy(update={"tokens": tope_tokens, "usd": tope_usd})
    registro = RegistroCosto(tmp_path / "costo.json" if tmp_path else None)
    return ProveedorConTope(ProveedorDeepSeek(CLAVE, gen, cargar_llm(), deepseek), registro, tope, gen.deepseek.precio_usd_por_millon_tokens)


def test_bajo_el_tope_se_usa_deepseek_y_se_acumula_el_costo() -> None:
    ds = _Sesion(entrada=1_000_000, salida=1_000_000)
    p = _con_tope(None, ds, tope_tokens=5_000_000, tope_usd=5.0)
    p.generar_json("s", "u", {})
    assert len(ds.enviados) == 1 and p.nombre == "deepseek"
    precios = cargar_generacion().deepseek.precio_usd_por_millon_tokens
    assert p.registro.tokens == 2_000_000 and p.registro.usd == pytest.approx(precios.entrada + precios.salida)


def test_al_superar_el_tope_de_tokens_la_siguiente_llamada_se_detiene_con_un_error_explicito(caplog: pytest.LogCaptureFixture) -> None:
    ds = _Sesion(entrada=900, salida=200)
    p = _con_tope(None, ds, tope_tokens=1000)
    p.generar_json("s", "u", {})  # 1100 tokens: supera el tope
    assert p.registro.agotado(p.tope)
    with caplog.at_level(logging.ERROR), pytest.raises(TopeDeCostoAlcanzado, match="tope de costo") as e:
        p.generar_json("s", "u", {})
    assert len(ds.enviados) == 1  # no se llamó otra vez ni a ningún modelo local
    assert isinstance(e.value, ErrorProveedor) and "1100" in str(e.value) and CLAVE not in str(e.value)
    assert any("tope de costo" in r.getMessage() for r in caplog.records)


def test_al_superar_el_tope_de_usd_tambien_se_detiene() -> None:
    ds = _Sesion(entrada=2_000_000, salida=0)
    p = _con_tope(None, ds, tope_tokens=100_000_000, tope_usd=0.10)  # 2 M tokens de entrada cuestan más de USD 0,10
    p.generar_json("s", "u", {})
    with pytest.raises(TopeDeCostoAlcanzado):
        p.generar_json("s", "u", {})
    assert len(ds.enviados) == 1


def test_el_acumulado_persiste_entre_ejecuciones(tmp_path: Path) -> None:
    _con_tope(tmp_path, _Sesion(entrada=900, salida=200), tope_tokens=1000).generar_json("s", "u", {})
    ds2 = _Sesion()
    segunda = _con_tope(tmp_path, ds2, tope_tokens=1000)
    assert segunda.registro.tokens == 1100
    with pytest.raises(TopeDeCostoAlcanzado):
        segunda.generar_json("s", "u", {})
    assert ds2.enviados == []  # el tope ya estaba alcanzado: no se llamó a DeepSeek


def test_el_tope_esta_configurado() -> None:
    t = cargar_generacion().tope_costo
    assert t.tokens > 0 and t.usd > 0


# ------------------------------------------------------------------ LLM_PROVIDER


def test_cambiar_llm_provider_cambia_el_proveedor_sin_tocar_codigo() -> None:
    base = {"OLLAMA_MODEL": "m:1b", "OLLAMA_HOST": "127.0.0.1:9", "DEEPSEEK_API_KEY": CLAVE}
    assert isinstance(crear_proveedor({**base, "LLM_PROVIDER": "ollama"}), ProveedorOllama)
    ds = crear_proveedor({**base, "LLM_PROVIDER": "deepseek"})
    assert isinstance(ds, ProveedorConTope) and isinstance(ds.principal, ProveedorDeepSeek) and ds.nombre == "deepseek"
    assert not hasattr(ds, "respaldo")  # D-95: sin respaldo local


def test_deepseek_sin_clave_falla_con_un_mensaje_claro() -> None:
    with pytest.raises(ErrorProveedor, match="DEEPSEEK_API_KEY"):
        crear_proveedor({"LLM_PROVIDER": "deepseek"})


def test_un_registro_de_costo_corrupto_falla_cerrado_y_nunca_se_reinicia_en_silencio(tmp_path: Path) -> None:
    ruta = tmp_path / "costo.json"
    for roto in ("{no es json", '{"tokens": "x", "usd": 1}', '{"tokens": 5}', "[]"):
        ruta.write_text(roto, encoding="utf-8")
        with pytest.raises(ErrorProveedor, match="costo_llm|registro de costo"):
            RegistroCosto(ruta)
        assert ruta.read_text(encoding="utf-8") == roto  # no se pisó
    ruta.unlink()
    assert RegistroCosto(ruta).tokens == 0  # sin archivo es un acumulado nuevo
