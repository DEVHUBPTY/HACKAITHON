"""C-02: la página de métricas se genera desde las salidas; sin n/IC o con un origen incoherente, falla."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import pagina_metricas as pm
from src.configuracion import RAIZ, ErrorDeConfiguracion, cargar_pagina_metricas, validar_todo

AHORA = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def raiz(tmp_path: Path) -> Path:
    """Copia de las fuentes de la página en una carpeta temporal (sin git), para alterarlas sin tocar el repo."""
    cfg = cargar_pagina_metricas()
    rutas = list(cfg.fuentes.values()) + [o.ruta for o in cfg.opcionales.values()]
    for r in rutas:
        origen = RAIZ / r
        if origen.exists():
            destino = tmp_path / r
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(origen, destino)
    return tmp_path


def _editar(raiz: Path, ruta: str, cambio) -> None:
    p = raiz / ruta
    datos = json.loads(p.read_text(encoding="utf-8"))
    cambio(datos)
    p.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def _pagina(raiz: Path) -> str:
    return pm.generar(pm.cargar_contexto(raiz), ahora=AHORA)


# ------------------------------------------------------------------ configuración


def test_config_valida_y_registrada():
    assert "pagina_metricas" in validar_todo()
    assert cargar_pagina_metricas().sobreestimacion_contador_costo > 1


def test_config_rechaza_clave_desconocida(tmp_path: Path):
    texto = (RAIZ / "config" / "pagina_metricas.yaml").read_text(encoding="utf-8") + "\nclave_nueva: 1\n"
    (tmp_path / "pagina_metricas.yaml").write_text(texto, encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion):
        cargar_pagina_metricas(tmp_path)


# ------------------------------------------------------------------ proporciones


def test_leer_proporcion_acepta_las_tres_formas():
    a = pm.leer_proporcion({"n": 7, "de": 10, "proporcion": 0.7, "ic95": [0.4, 0.9]}, "a")
    b = pm.leer_proporcion({"k": 7, "n": 10, "proporcion": 0.7, "ic95": [0.4, 0.9]}, "b")
    c = pm.leer_proporcion({"k": 7, "n": 10, "tasa": 0.7, "ic95": [0.4, 0.9]}, "c")
    assert (a.k, a.n) == (b.k, b.n) == (c.k, c.n) == (7, 10)
    assert a.ic == (0.4, 0.9)


@pytest.mark.parametrize(
    "obj",
    [
        {"n": 7, "proporcion": 0.7, "ic95": [0.4, 0.9]},                     # sin denominador
        {"n": 7, "de": 10, "proporcion": 0.7},                               # sin IC
        {"n": 7, "de": 10, "proporcion": 0.7, "ic95": [0.4]},                # IC mal formado
        {"n": 7, "de": 10, "ic95": [0.4, 0.9]},                              # sin proporción
        {"n": 11, "de": 10, "proporcion": 1.1, "ic95": [0.4, 0.9]},          # numerador > denominador
        {"n": True, "de": 10, "proporcion": 0.1, "ic95": [0.0, 0.2]},        # booleano no es entero
        "70 %",
    ],
)
def test_proporcion_incompleta_falla(obj):
    with pytest.raises(pm.ProporcionIncompleta):
        pm.leer_proporcion(obj, "x")


def test_denominador_cero_es_sin_datos_sin_cifra():
    p = pm.leer_proporcion({"k": 0, "n": 0, "proporcion": None, "ic95": None}, "x")
    assert p.sin_datos and p.proporcion is None and p.ic is None


def test_estimacion_exige_n_y_ic():
    assert pm.leer_estimacion({"n": 12, "valor": 1.5, "ic95": [1.0, 2.0]}, "valor", "x") == (12, 1.5, (1.0, 2.0))
    for malo in ({"valor": 1.5, "ic95": [1.0, 2.0]}, {"n": 12, "valor": 1.5}, {"n": 0, "valor": 1.5, "ic95": [1.0, 2.0]}):
        with pytest.raises(pm.ProporcionIncompleta):
            pm.leer_estimacion(malo, "valor", "x")


def test_metrica_sin_n_o_sin_ic_no_existe():
    base = dict(seccion="s", nombre="m", valor="50 %", fuente="f.json", origen=pm.ORIGEN_AUTOMATICO)
    with pytest.raises(pm.ProporcionIncompleta):
        pm.Metrica(**base, n="", ic="1 – 2")
    with pytest.raises(pm.ProporcionIncompleta):
        pm.Metrica(**base, n="1 de 2", ic="")
    assert pm.Metrica(**base, n="n = 0", ic="", sin_datos=True).sin_datos


# ------------------------------------------------------------------ origen del juicio


def test_origen_provisional_nunca_es_humano():
    with pytest.raises(pm.OrigenIncoherente):
        pm.Origen(pm.HUMANO, False)           # el juicio de la fuente es provisional, pero se rotula humano
    with pytest.raises(pm.OrigenIncoherente):
        pm.Origen(pm.PROVISIONAL, True)
    with pytest.raises(pm.OrigenIncoherente):
        pm.Origen(pm.AUTOMATICO, False)
    assert pm.Origen(pm.HUMANO, True).tipo == pm.HUMANO


def test_origen_de_juicio_deriva_de_la_fuente():
    prov = {"juicio_humano": False, "origen_juicio": "asistente_provisional (D-101)"}
    hum = {"juicio_humano": True, "origen_juicio": "humano"}
    assert pm.origen_de_juicio(prov, "x").tipo == pm.PROVISIONAL
    assert pm.origen_de_juicio(hum, "x").tipo == pm.HUMANO
    for malo in ({}, {"juicio_humano": "no"}, {"juicio_humano": True, "origen_juicio": "asistente_provisional (D-101)"},
                 {"juicio_humano": False, "origen_juicio": "humano"}):
        with pytest.raises(pm.OrigenIncoherente):
            pm.origen_de_juicio(malo, "x")


def test_origen_de_etiquetas_y_agrupacion():
    assert pm.origen_de_etiquetas(["humano"], "x").tipo == pm.HUMANO
    assert pm.origen_de_etiquetas(["humano", "asistente_provisional"], "x").tipo == pm.PROVISIONAL
    assert pm.origen_agrupacion({"titulares_etiquetados": 100}, {"humano": 100, "asistente_provisional": 61}).tipo == pm.HUMANO
    assert pm.origen_agrupacion({"titulares_etiquetados": 161}, {"humano": 100, "asistente_provisional": 61}).tipo == pm.PROVISIONAL
    with pytest.raises(pm.OrigenIncoherente):
        pm.origen_agrupacion({"titulares_etiquetados": 80}, {"humano": 100, "asistente_provisional": 61})
    with pytest.raises(pm.OrigenIncoherente):
        pm.origen_clasificacion({"datos_reales": {"origenes": ["humano"], "usa_etiquetas_provisionales": True}})


# ------------------------------------------------------------------ la página


def test_pagina_completa_con_secciones_y_fuentes(raiz: Path):
    texto = _pagina(raiz)
    assert "BORRADOR — métricas provisionales" in texto
    for titulo in ("## Resumen", "## Pruebas de aceptación", "## Eficiencia, tokens y costo", "## Rechazos del validador", "## Reproducibilidad",
                   "## Coherencia entre fuentes", "## Fuentes", "## Limitaciones", "## Preguntas abiertas"):
        assert titulo in texto
    cfg = cargar_pagina_metricas()
    for ruta in cfg.fuentes.values():
        assert f"`{ruta}`" in texto, f"la fuente {ruta} no aparece en la tabla de fuentes"
    for expresion in ("n = 5 temas", "D-116", "C-09", "C-10", "2.6"):
        assert expresion in texto


def test_toda_fila_de_tabla_lleva_n_e_ic(raiz: Path):
    texto = _pagina(raiz)
    filas = [f for f in texto.splitlines() if f.startswith("| ") and f.count("|") == 8 and "Numerador" not in f and "---" not in f]
    assert len(filas) > 40
    for fila in filas:
        _, nombre, valor, n, ic, *_ = [x.strip() for x in fila.split("|")]
        assert n, fila
        if valor == "sin datos":
            assert n == "n = 0"
        else:
            assert ic and ic != "—", fila


def test_las_cifras_salen_de_la_fuente_no_de_la_pagina(raiz: Path):
    def cambiar(d):
        d["abstencion_correcta"]["sin_respuesta"].update(n=3, de=4, proporcion=0.75, ic95=[0.2, 0.9])
    _editar(raiz, "outputs/metricas.json", cambiar)
    texto = _pagina(raiz)
    assert "| Abstención correcta (consultas sin respuesta) | 75.0 % | 3 de 4 | 20.0 % – 90.0 %" in texto


def test_proporcion_sin_intervalo_en_la_fuente_hace_fallar(raiz: Path):
    _editar(raiz, "outputs/metricas.json", lambda d: d["cobertura_de_citas"]["consultas"].pop("ic95"))
    with pytest.raises(pm.ProporcionIncompleta, match="cobertura_de_citas.consultas"):
        _pagina(raiz)


def test_proporcion_sin_denominador_en_la_fuente_hace_fallar(raiz: Path):
    _editar(raiz, "outputs/precision_at_5.json", lambda d: d["sistema"].pop("n"))
    with pytest.raises(pm.ProporcionIncompleta):
        _pagina(raiz)


def test_provisionales_salen_marcados_y_nunca_como_humanos(raiz: Path):
    texto = _pagina(raiz)
    for f in texto.splitlines():
        if f.startswith("| Precision@5") or f.startswith("| Afirmaciones sustentadas"):
            assert "**PROVISIONAL**" in f and "| humano |" not in f, f
        if "PROVISIONAL (asistente)" in f:
            assert "**PROVISIONAL**" in f and "| humano |" not in f, f


def test_fuente_provisional_que_se_declara_humana_hace_fallar(raiz: Path):
    _editar(raiz, "outputs/precision_at_5.json", lambda d: d.update(juicio_humano=True))   # origen_juicio sigue diciendo provisional
    with pytest.raises(pm.OrigenIncoherente):
        _pagina(raiz)


def test_fuente_sin_declaracion_de_juicio_hace_fallar(raiz: Path):
    _editar(raiz, "outputs/metricas.json", lambda d: d["validez_sustento"].pop("juicio_humano"))
    with pytest.raises(pm.OrigenIncoherente):
        _pagina(raiz)


def test_revision_separa_personas_de_provisional(raiz: Path):
    revision = {
        "casos_abiertos": 3, "origen_juicio": "humano", "juicio_humano": True, "casos_decididos": 2,
        "tasas": {k: {"k": 1, "n": 2, "proporcion": 0.5, "ic95": [0.1, 0.9]} for k in ("aceptacion", "correccion", "descarte")},
        "afirmaciones_editadas": {"k": 1, "n": 4, "proporcion": 0.25, "ic95": [0.05, 0.7]},
        "casos_decididos_provisionales": 1,
        "provisionales": {
            "origen_juicio": "asistente_provisional (D-101)", "juicio_humano": False, "aviso_origen": "AVISO", "casos_decididos": 1,
            "tasas": {k: {"k": 1, "n": 1, "proporcion": 1.0, "ic95": [0.2, 1.0]} for k in ("aceptacion", "correccion", "descarte")},
            "afirmaciones_editadas": {"k": 0, "n": 6, "proporcion": 0.0, "ic95": [0.0, 0.4]},
        },
    }
    (raiz / "outputs" / "revision.json").write_text(json.dumps(revision), encoding="utf-8")
    texto = _pagina(raiz)
    personas = [f for f in texto.splitlines() if "· personas |" in f]
    prov = [f for f in texto.splitlines() if "PROVISIONAL (asistente)" in f]
    assert len(personas) == 4 and all("| humano |" in f for f in personas)
    assert len(prov) == 4 and all("**PROVISIONAL**" in f for f in prov)
    revision["provisionales"]["juicio_humano"] = True
    (raiz / "outputs" / "revision.json").write_text(json.dumps(revision), encoding="utf-8")
    with pytest.raises(pm.OrigenIncoherente):
        _pagina(raiz)


def test_revision_ausente_se_declara_no_disponible(raiz: Path):
    (raiz / "outputs" / "revision.json").unlink(missing_ok=True)
    texto = _pagina(raiz)
    assert "Fuente no disponible (outputs/revision.json)" in texto and "eval.revision" in texto


def test_fuente_obligatoria_faltante_falla(raiz: Path):
    (raiz / "outputs" / "puntaje.json").unlink()
    with pytest.raises(pm.FuenteFaltante, match="puntaje.json"):
        pm.cargar_contexto(raiz)


def test_coherencia_avisa_si_los_grupos_difieren(raiz: Path):
    _editar(raiz, "outputs/puntaje.json", lambda d: d.update(grupos=999))
    assert "Distinto número de grupos" in _pagina(raiz)


def test_limitaciones_interpolan_n_de_los_datos(raiz: Path):
    def cambiar(d):
        d["sistema"]["n"] = 8
        d["baseline"]["n"] = 8
    _editar(raiz, "outputs/precision_at_5.json", cambiar)
    assert "n = 8 temas" in _pagina(raiz)


def test_cli_escribe_el_archivo(tmp_path: Path):
    salida = tmp_path / "pagina.md"
    assert pm.principal(["--salida", str(salida)]) == 0
    assert salida.read_text(encoding="utf-8").startswith("# ")


def test_cli_falla_con_codigo_1_si_la_pagina_no_se_puede_generar(monkeypatch, tmp_path: Path, capsys):
    def explota(*_a, **_k):
        raise pm.ProporcionIncompleta("x: falta n")
    monkeypatch.setattr(pm, "generar", explota)
    assert pm.principal(["--salida", str(tmp_path / "p.md")]) == 1
    assert "falta n" in capsys.readouterr().err
    assert not (tmp_path / "p.md").exists()
