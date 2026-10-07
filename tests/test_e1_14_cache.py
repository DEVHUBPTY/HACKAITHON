"""E1-14 · Caché de respuestas del LLM: la segunda llamada idéntica no llega al proveedor, la clave invalida ante cualquier cambio,
y ``generar_paquete`` sirve borradores desde la caché sin crear proveedor ni abrir conexiones. Nunca se llama a un LLM real."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src import cache as c
from src import generacion as g
from src import interfaz as ui
from src.cache import CacheLlm, Identidad, ProveedorConCache, ProveedorSoloCache, SinBorrador, SinCache, clave_de
from src.configuracion import cargar_cache, cargar_generacion, cargar_interfaz
from src.llm.costo import SaldoAgotado, TopeDeCostoAlcanzado
from src.llm.proveedor import ErrorProveedor
from tests import generacion_ayuda as ga

ESQUEMA = {"type": "object", "properties": {"afirmaciones": {}}}
ID = Identidad("guionado", "guionado-0")


@pytest.fixture
def cache(tmp_path: Path) -> CacheLlm:
    return CacheLlm(tmp_path / "cache")


@pytest.fixture
def entrada(monkeypatch: pytest.MonkeyPatch):
    """La ficha de prueba como entrada de la generación (la base real no interviene en estas pruebas)."""
    actual = {"ficha": ga.ficha()}
    monkeypatch.setattr(g, "_entrada_desde_grupo", lambda id_grupo, modalidad, base: actual["ficha"])
    monkeypatch.setattr(g, "red_disponible", lambda *a, **k: True)
    monkeypatch.delenv("HACKIATHON_OFFLINE", raising=False)
    monkeypatch.setattr(c, "leer_local_env", lambda *a, **k: {})
    return actual


# ------------------------------------------------------------------ la segunda llamada idéntica no llega al proveedor


def test_la_segunda_llamada_identica_no_llega_al_proveedor(cache: CacheLlm) -> None:
    prov = ga.ProveedorGuionado()
    p = ProveedorConCache(prov, cache)
    a = p.generar_json("SYS", "USR", {"type": "object", "properties": {"afirmaciones": {}}})
    b = p.generar_json("SYS", "USR", {"type": "object", "properties": {"afirmaciones": {}}})
    assert a == b and len(prov.llamadas) == 1 and (p.aciertos, p.fallos) == (1, 1) and len(cache) == 1


def test_la_cache_sobrevive_a_un_proceso_nuevo(tmp_path: Path) -> None:
    prov = ga.ProveedorGuionado()
    ProveedorConCache(prov, CacheLlm(tmp_path)).generar_json("S", "U", ESQUEMA)
    otra = ga.ProveedorGuionado()
    ProveedorConCache(otra, CacheLlm(tmp_path)).generar_json("S", "U", ESQUEMA)
    assert otra.llamadas == []


# ------------------------------------------------------------------ la clave


def _clave(**cambios: Any) -> str:
    base = dict(
        proveedor="deepseek", modelo="m", version_prompt="1.0", system="S", usuario="U", esquema={"a": 1},
        temperatura=0.0, semilla=0, version_cache="1",
    )
    base.update(cambios)
    return clave_de(**base)


def test_la_clave_es_determinista_y_cambia_con_cada_parte_de_la_peticion() -> None:
    assert _clave() == _clave() and len(_clave()) == 64
    cambios = [
        {"proveedor": "ollama"}, {"modelo": "otro"}, {"version_prompt": "1.1"}, {"system": "S2"}, {"usuario": "U2"},
        {"esquema": {"a": 2}}, {"temperatura": 0.5}, {"semilla": 1}, {"version_cache": "2"},
    ]
    claves = {_clave(**x) for x in cambios} | {_clave()}
    assert len(claves) == len(cambios) + 1


def test_la_clave_no_depende_del_orden_de_las_claves_del_esquema() -> None:
    assert _clave(esquema={"a": 1, "b": 2}) == _clave(esquema={"b": 2, "a": 1})


def test_un_cambio_en_la_evidencia_o_en_la_version_del_prompt_es_otra_peticion(cache: CacheLlm) -> None:
    prov = ga.ProveedorGuionado()
    p = ProveedorConCache(prov, cache)
    p.generar_json_versionado("1.0", "S", "evidencia A", ESQUEMA)
    p.generar_json_versionado("1.0", "S", "evidencia B", ESQUEMA)
    p.generar_json_versionado("1.1", "S", "evidencia A", ESQUEMA)
    assert len(prov.llamadas) == 3
    p.generar_json_versionado("1.0", "S", "evidencia A", ESQUEMA)
    assert len(prov.llamadas) == 3


def test_subir_version_cache_invalida_toda_la_cache(tmp_path: Path) -> None:
    cfg = cargar_cache()
    prov = ga.ProveedorGuionado()
    ProveedorConCache(prov, CacheLlm(tmp_path, cfg)).generar_json("S", "U", ESQUEMA)
    nueva = CacheLlm(tmp_path, cfg.model_copy(update={"version_cache": cfg.version_cache + "-nueva"}))
    ProveedorConCache(prov, nueva).generar_json("S", "U", ESQUEMA)
    assert len(prov.llamadas) == 2


# ------------------------------------------------------------------ qué se guarda


def test_lo_guardado_es_la_respuesta_sin_prompts_ni_evidencia_ni_claves(cache: CacheLlm) -> None:
    prov = ga.ProveedorGuionado()
    ProveedorConCache(prov, cache).generar_json("SYSTEM-SECRETO", "EVIDENCIA-USUARIO", ESQUEMA)
    (archivo,) = cache.carpeta.glob("*.json")
    texto = archivo.read_text(encoding="utf-8")
    datos = json.loads(texto)
    assert "SYSTEM-SECRETO" not in texto and "EVIDENCIA-USUARIO" not in texto
    assert set(datos) >= {"clave", "proveedor", "modelo", "version_prompt", "respuesta", "creado_utc"} and archivo.stem == datos["clave"]


def test_una_respuesta_invalida_tambien_se_repite_igual_y_un_error_del_proveedor_no_deja_nada(cache: CacheLlm) -> None:
    prov = ga.ProveedorGuionado(afirmaciones="esto no es json")
    p = ProveedorConCache(prov, cache)
    assert p.generar_json("S", "U", ESQUEMA) == p.generar_json("S", "U", ESQUEMA) == "esto no es json"
    assert len(prov.llamadas) == 1  # el reintento de la generación depende de reproducir la primera respuesta
    roto = ProveedorConCache(ga.ProveedorGuionado(afirmaciones=ga.fallo()), CacheLlm(cache.carpeta.parent / "otra"))
    with pytest.raises(ErrorProveedor):
        roto.generar_json("S", "U", ESQUEMA)
    assert len(roto.cache) == 0


def test_una_entrada_corrupta_o_ajena_cuenta_como_ausente(cache: CacheLlm) -> None:
    prov = ga.ProveedorGuionado()
    p = ProveedorConCache(prov, cache)
    p.generar_json("S", "U", ESQUEMA)
    (archivo,) = cache.carpeta.glob("*.json")
    archivo.write_text("{ roto", encoding="utf-8")
    p.generar_json("S", "U", ESQUEMA)
    assert len(prov.llamadas) == 2
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    datos["clave"] = "otra"
    archivo.write_text(json.dumps(datos), encoding="utf-8")
    assert cache.obtener(archivo.stem) is None


def test_refrescar_vuelve_a_llamar_y_sobrescribe(cache: CacheLlm) -> None:
    prov = ga.ProveedorGuionado()
    ProveedorConCache(prov, cache).generar_json("S", "U", ESQUEMA)
    ProveedorConCache(prov, cache, refrescar=True).generar_json("S", "U", ESQUEMA)
    assert len(prov.llamadas) == 2 and len(cache) == 1


def test_el_proveedor_solo_cache_nunca_llama_y_lo_dice(cache: CacheLlm) -> None:
    p = ProveedorSoloCache(cache, ID)
    with pytest.raises(SinCache):
        p.generar_json("S", "U", ESQUEMA)
    ProveedorConCache(ga.ProveedorGuionado(), cache).generar_json("S", "U", ESQUEMA)
    assert p.generar_json("S", "U", ESQUEMA) and (p.aciertos, p.fallos) == (1, 1)


# ------------------------------------------------------------------ generar_paquete


def _generar(cache: CacheLlm, prov: ga.ProveedorGuionado | None = None, **kw: Any):
    return g.generar_paquete("GRP-x", "editorial", solo_cache=False, proveedor=prov or ga.ProveedorGuionado(), cache=cache, **kw)


def test_generar_paquete_genera_guarda_y_el_modo_cache_lo_reconstruye_igual(entrada, cache: CacheLlm) -> None:
    prov = ga.ProveedorGuionado()
    generado = _generar(cache, prov)
    n = len(prov.llamadas)
    assert n == 5 and generado.titulo is not None and generado.brief and generado.guion and generado.resumen_web
    leido = g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache)
    assert leido == generado
    otra = ga.ProveedorGuionado()
    _generar(cache, otra)
    assert otra.llamadas == []  # ni el paso 1 ni ningún grupo llegan al proveedor


def test_la_cache_cubre_cada_reintento(entrada, cache: CacheLlm) -> None:
    mala = {"brief": [{"texto": "Frase sin cita.", "afirmaciones": []}], "enfoque": [], "preguntas": []}
    prov = ga.ProveedorGuionado(brief=(mala, ga.BUENAS["brief"]))
    primero = _generar(cache, prov, grupos=["brief"])
    llamadas = len(prov.llamadas)
    assert primero.brief and llamadas == 3  # paso 1, brief inválido y reintento
    otra = ga.ProveedorGuionado()
    assert _generar(cache, otra, grupos=["brief"]) == primero and otra.llamadas == []


def test_una_primera_respuesta_invalida_seguida_de_un_reintento_valido_se_reconstruye_desde_la_cache(entrada, cache: CacheLlm) -> None:
    prov = ga.ProveedorGuionado(afirmaciones=("{ no es json", ga.BUENAS["afirmaciones"]))
    generado = _generar(cache, prov, grupos=["brief"])
    assert generado.brief and prov.claves.count("afirmaciones") == 2
    leido = g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache, grupos=["brief"])
    assert leido == generado


def test_un_grupo_sin_cache_queda_vacio_con_su_motivo_y_el_resto_se_muestra(entrada, cache: CacheLlm) -> None:
    _generar(cache, grupos=["titulos"])
    p = g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache)
    assert p.titulo is not None and not p.brief and not p.guion
    motivos = {v.referencia: v.motivo for v in p.vacios if v.origen == "seccion"}
    assert {"brief", "guion", "resumen_web"} <= set(motivos) and "no hay borrador en caché" in motivos["guion"]
    assert p.marca and p.leyenda_alcance


def test_sin_nada_en_cache_no_hay_borrador_y_no_se_llama_a_nadie(entrada, cache: CacheLlm, monkeypatch: pytest.MonkeyPatch) -> None:
    def explota(*a: Any, **k: Any) -> None:
        raise AssertionError("no debe crear un proveedor")

    monkeypatch.setattr("src.llm.proveedor.crear_proveedor", explota)
    with pytest.raises(SinBorrador, match="no hay borrador en caché"):
        g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache)
    assert len(cache) == 0


def test_una_accion_que_no_genera_borrador_lo_dice_en_vez_de_hablar_de_cache(entrada, cache: CacheLlm) -> None:
    entrada["ficha"] = ga.ficha("Archivar")
    with pytest.raises(SinBorrador, match="no genera borrador"):
        g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache)


def test_si_cambia_la_ficha_la_cache_vieja_no_se_sirve(entrada, cache: CacheLlm) -> None:
    _generar(cache)
    entrada["ficha"] = ga.ficha(fuentes_verificaciones=["otra"], vacios=[ga.VacioFicha(id="V1", descripcion="Falta algo distinto")])
    with pytest.raises(SinBorrador):
        g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache)


def test_sin_red_o_en_modo_offline_generar_se_comporta_como_solo_cache(entrada, cache: CacheLlm, monkeypatch: pytest.MonkeyPatch) -> None:
    _generar(cache)
    monkeypatch.setattr(g, "red_disponible", lambda *a, **k: False)
    monkeypatch.setattr("src.llm.proveedor.crear_proveedor", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sin red no se crea proveedor")))
    # sin proveedor inyectado y sin red: lee la caché con la identidad de local.env
    monkeypatch.setattr(g, "identidad_de", lambda: ID)
    leido = g.generar_paquete("GRP-x", "editorial", solo_cache=False, cache=cache)
    assert leido.titulo is not None
    monkeypatch.setattr(g, "red_disponible", lambda *a, **k: True)
    monkeypatch.setenv("HACKIATHON_OFFLINE", "true")
    assert g.generar_paquete("GRP-x", "editorial", solo_cache=False, cache=cache).titulo is not None


def test_sin_red_y_sin_cache_no_hay_borrador(entrada, cache: CacheLlm, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g, "red_disponible", lambda *a, **k: False)
    monkeypatch.setattr(g, "identidad_de", lambda: ID)
    with pytest.raises(SinBorrador):
        g.generar_paquete("GRP-x", "editorial", solo_cache=False, cache=cache)


def test_sin_proveedor_configurado_el_modo_cache_dice_que_no_hay_borrador(entrada, cache: CacheLlm, monkeypatch: pytest.MonkeyPatch) -> None:
    def sin_proveedor() -> Identidad:
        raise ErrorProveedor("LLM_PROVIDER no está definido")

    monkeypatch.setattr(g, "identidad_de", sin_proveedor)
    with pytest.raises(SinBorrador):
        g.generar_paquete("GRP-x", "editorial", solo_cache=True, cache=cache)


def test_el_tope_o_el_saldo_agotado_detienen_la_generacion_y_lo_guardado_sigue_disponible(entrada, cache: CacheLlm) -> None:
    _generar(cache, grupos=["titulos"])
    prov = ga.ProveedorGuionado(brief=SaldoAgotado("Se agotó el saldo"))
    with pytest.raises(TopeDeCostoAlcanzado, match="saldo"):
        _generar(cache, prov, grupos=["brief"])
    p = g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache)
    assert p.titulo is not None and not p.brief


# ------------------------------------------------------------------ interfaz


def test_la_interfaz_pide_solo_cache_y_muestra_el_motivo_de_la_falta_de_borrador() -> None:
    def sin_borrador(id_grupo: str, modalidad: str, *, solo_cache: bool, **_: Any) -> None:
        assert solo_cache is True
        raise SinBorrador("no hay borrador en caché para este grupo: la interfaz no espera al modelo ni usa la red.")

    e = ui.obtener_paquete("GRP-x", "editorial", cargar_interfaz(), generador=sin_borrador, ruta_base=Path("x.duckdb"))
    assert e.estado == "sin_cache" and "no hay borrador en caché" in (e.motivo or "")


def test_la_interfaz_integra_generar_paquete_y_pinta_oraciones_vacios_y_marca(entrada, cache: CacheLlm) -> None:
    _generar(cache, grupos=["titulos"])
    e = ui.obtener_paquete(
        "GRP-x", "editorial", cargar_interfaz(),
        generador=lambda i, m, *, solo_cache, **kw: g.generar_paquete(i, m, solo_cache=solo_cache, proveedor=ga.ProveedorGuionado(), cache=cache, **kw),
    )
    assert e.estado == "disponible"
    secciones = dict(ui.secciones_de_paquete(e.paquete))
    assert secciones["Marca"] and secciones["Leyenda alcance"]
    assert any("[A1]" in t for t in secciones["Titulares"])           # cada oración muestra las afirmaciones en que se apoya
    assert any("no hay borrador en caché" in t for t in secciones["Vacios"])
    assert "Brief" not in secciones


def test_la_funcion_que_espera_la_interfaz_existe_y_acepta_solo_cache() -> None:
    assert cargar_interfaz().generacion.funcion == "generar_paquete"
    assert ui.cargar_generador() is g.generar_paquete


# ------------------------------------------------------------------ D-98: saldo agotado (HTTP 402)


class _Resp402:
    status_code = 402

    def raise_for_status(self) -> None:
        import requests

        raise requests.HTTPError("402 Payment Required: Insufficient Balance", response=self)

    def json(self) -> dict[str, Any]:
        return {"error": {"message": "Insufficient Balance"}}


class _SesionSinSaldo:
    def __init__(self) -> None:
        self.posts = 0

    def post(self, url: str, **kwargs: Any) -> _Resp402:
        self.posts += 1
        return _Resp402()


def test_http_402_es_saldo_agotado_con_mensaje_claro_sin_la_clave_y_sin_reintento(caplog: pytest.LogCaptureFixture) -> None:
    from src.configuracion import cargar_generacion, cargar_llm
    from src.llm.deepseek import MENSAJE_SALDO, ProveedorDeepSeek

    clave = "sk-prueba-" + "q" * 24
    sesion = _SesionSinSaldo()
    p = ProveedorDeepSeek(clave, cargar_generacion(), cargar_llm(), sesion)
    with caplog.at_level("INFO"), pytest.raises(SaldoAgotado) as e:
        p.generar_json("s json", "u", {})
    assert isinstance(e.value, TopeDeCostoAlcanzado) and str(e.value) == MENSAJE_SALDO and "saldo" in MENSAJE_SALDO
    assert clave not in str(e.value) and clave not in " ".join(r.getMessage() for r in caplog.records) and sesion.posts == 1


def test_con_saldo_agotado_la_generacion_se_detiene_sin_reintentar_y_deja_una_cache_utilizable(entrada, cache: CacheLlm) -> None:
    from src.configuracion import cargar_generacion, cargar_llm
    from src.llm.deepseek import ProveedorDeepSeek

    sesion = _SesionSinSaldo()
    real = ProveedorDeepSeek("sk-prueba-" + "w" * 24, cargar_generacion(), cargar_llm(), sesion)
    with pytest.raises(SaldoAgotado, match="saldo"):
        g.generar_paquete("GRP-x", "editorial", solo_cache=False, proveedor=real, cache=cache)
    assert sesion.posts == 1 and len(cache) == 0
    with pytest.raises(SinBorrador):  # lo que muestra la interfaz: la caché (vacía) y el mensaje honesto
        g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=real, cache=cache)


# ------------------------------------------------------------------ revisión del PR #28


def test_con_llm_provider_vacio_se_lee_la_cache_con_el_proveedor_por_defecto(entrada, cache: CacheLlm, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.cache import identidad_de

    assert identidad_de({}).proveedor == cargar_cache().proveedor_por_defecto == "deepseek"
    assert identidad_de({"LLM_PROVIDER": "  "}).proveedor == "deepseek"
    assert identidad_de({"DEEPSEEK_MODEL": "otro"}).modelo == "otro"
    caliente = ga.ProveedorGuionado()
    caliente.nombre, caliente.modelo = "deepseek", cargar_generacion().deepseek.modelo
    _generar(cache, caliente)
    monkeypatch.setattr(c, "leer_local_env", lambda *a, **k: {})  # local.env sin completar
    p = g.generar_paquete("GRP-x", "editorial", solo_cache=True, cache=cache)  # sin proveedor inyectado: identidad de local.env o del YAML
    assert p.titulo is not None


def test_con_otro_proveedor_o_modelo_se_explica_el_desajuste_en_vez_de_decir_que_no_hay_borrador(entrada, cache: CacheLlm, monkeypatch: pytest.MonkeyPatch) -> None:
    caliente = ga.ProveedorGuionado()
    caliente.nombre, caliente.modelo = "deepseek", "deepseek-flash"
    _generar(cache, caliente)
    monkeypatch.setattr(g, "identidad_de", lambda: Identidad("ollama", "qwen"))
    with pytest.raises(SinBorrador, match=r"se calentó con deepseek/deepseek-flash y local\.env pide ollama/qwen") as e:
        g.generar_paquete("GRP-x", "editorial", solo_cache=True, cache=cache)
    assert not e.value.por_accion


def test_verificar_dice_por_que_falla_y_sale_con_error(entrada, cache: CacheLlm, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import calentar_cache as cc

    caliente = ga.ProveedorGuionado()
    caliente.nombre, caliente.modelo = "deepseek", "deepseek-flash"
    _generar(cache, caliente)
    monkeypatch.setattr(g, "identidad_de", lambda: Identidad("ollama", "qwen"))
    estado = cc.estado_de("GRP-x", "editorial", Path("x.duckdb"), cache)
    assert estado.startswith("sin borrador: la caché se calentó con deepseek/deepseek-flash")


def test_un_borrador_guardado_que_ya_no_pasa_la_validacion_se_distingue_de_uno_inexistente(entrada, cache: CacheLlm) -> None:
    mala = {"brief": [{"texto": "Frase sin cita.", "afirmaciones": []}], "enfoque": [], "preguntas": []}
    _generar(cache, ga.ProveedorGuionado(brief=(mala, ga.BUENAS["brief"])), grupos=["brief"])
    buena = json.dumps(ga.BUENAS["brief"], ensure_ascii=False)
    (reintento,) = [a for a in cache.carpeta.glob("*.json") if json.loads(a.read_text(encoding="utf-8"))["respuesta"] == buena]
    reintento.unlink()  # queda guardado el intento que no valida, pero no el que lo corrigió
    textos_ = cargar_cache().textos
    with pytest.raises(SinBorrador) as e:
        g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache, grupos=["brief"])
    assert str(e.value) == textos_.borrador_invalido != textos_.sin_cache


def test_los_temporales_de_escritura_son_unicos_y_no_quedan_restos(cache: CacheLlm) -> None:
    for i in range(5):
        cache.guardar(f"k{i}", "{}", {"proveedor": "p", "modelo": "m"})
    cache.guardar("k0", '{"a": 1}', {"proveedor": "p", "modelo": "m"})
    assert sorted(a.suffix for a in cache.carpeta.iterdir()) == [".json"] * 5 and cache.identidades() == {("p", "m")}


def test_la_pantalla_paquete_usa_las_etiquetas_del_yaml(entrada, cache: CacheLlm) -> None:
    _generar(cache, grupos=["titulos"])
    p = g.generar_paquete("GRP-x", "editorial", solo_cache=True, proveedor=ga.ProveedorGuionado(), cache=cache)
    etiquetas = cargar_interfaz().paquete.etiquetas
    titulos = [t for t, _ in ui.secciones_de_paquete(p, etiquetas)]
    assert {"Caso", "Alcance", "Paquete completo forzado por una persona", "Vacíos y secciones sin redactar"} <= set(titulos)
    assert not {"Id caso", "Version", "Forzado"} & set(titulos)
    campos = set(p.model_dump())
    assert campos <= set(etiquetas)  # todo campo de un paquete editorial tiene su etiqueta
