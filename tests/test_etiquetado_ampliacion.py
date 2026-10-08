"""Ampliación de la muestra de etiquetado (2026-10-08): la muestra original no cambia, la ampliación es un censo con estrato
propio y las propuestas de un LLM solo rellenan el formulario (nunca son etiquetas). Todo sintético (``tmp_path``)."""

import csv
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval import etiquetar as et
from src.configuracion import MuestraEtiquetado, cargar_etiquetado, cargar_temas
from tests.test_etiquetado import CFG, TEMAS, _base, _fila, _noticias

ESTRATO = "ampliacion_prueba"


@pytest.fixture(autouse=True)
def _sin_excluidos(tmp_path):
    """La raíz sintética (``tmp_path``) lleva su propio ``ejemplos_excluidos.txt`` vacío."""
    ruta = tmp_path / CFG.archivos.ejemplos_excluidos
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("# sin ejemplos\n", encoding="utf-8")


def _cfg_con_ampliacion(ids_desde: str, peso: float = 1.0, congelada: str | None = None):
    amp = {"nombre": "prueba", "ids_desde": ids_desde, "estrato": ESTRATO, "peso_muestreo": peso}
    muestra = MuestraEtiquetado.model_validate({**CFG.muestra.model_dump(), "ampliaciones": [amp], "congelada": congelada})
    return CFG.model_copy(update={"muestra": muestra})


def _propuestas(ruta: Path, ids: list[str], **extra: str) -> Path:
    cols = list(et.COLUMNAS_PROPUESTA)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for i in ids:
            w.writerow({c: "" for c in cols} | {"id_noticia": i, "titulo": "t", "ruido": "ninguno", "tema_principal": "economia",
                                                "alcance_regional": "False", "propuesto_por": "llm:deepseek:deepseek-flash"} | extra)
    return ruta


def _base_ampliada(tmp_path: Path, n_orig: int = 150, n_nuevas: int = 10) -> tuple[Path, list[str]]:
    """Base con ``n_orig`` noticias y, además, ``n_nuevas`` de una captura nueva (IDs distintos)."""
    from src import db

    tmp_path.mkdir(parents=True, exist_ok=True)
    ruta = _base(tmp_path / "s.duckdb", n_orig)
    nuevas = [{**n, "id_noticia": f"NOT-nueva{i:04d}", "titulo": f"Nueva {i}", "es_ruido": i % 2 == 0} for i, n in enumerate(_noticias(n_nuevas))]
    con = db.conectar(ruta)
    db.insertar(con, "noticias", [{**x, "url_canonica": x["url"], "tipo_firma": "sin_firma"} for x in nuevas])
    con.close()
    return ruta, [n["id_noticia"] for n in nuevas]


# ---------------------------------------------------------------- la muestra original no cambia


def test_la_muestra_original_es_identica_antes_y_despues_de_agregar_titulares(tmp_path):
    base_antes = _base(tmp_path / "a.duckdb", 150)
    original = et.muestra_desde_base(base_antes, CFG, tmp_path)
    ruta_base, ids = _base_ampliada(tmp_path / "b")
    cfg = _cfg_con_ampliacion("propuestas/p.csv")
    _propuestas(tmp_path / "propuestas" / "p.csv", ids)
    despues = et.muestra_desde_base(ruta_base, cfg, tmp_path)
    clave = lambda m: [(x["orden"], x["id_noticia"], x["estrato"], x["peso"], x["doble"]) for x in m]  # noqa: E731
    assert clave(despues[: len(original)]) == clave(original)
    assert {x["id_noticia"] for x in despues[len(original):]} == set(ids)


def test_la_muestra_congelada_no_depende_de_la_poblacion(tmp_path):
    ruta_base, ids = _base_ampliada(tmp_path / "c", n_nuevas=12)
    sorteada = et.muestra_desde_base(_base(tmp_path / "base0.duckdb", 150), CFG, tmp_path)
    et.escribir_csv(tmp_path / "congelada.csv", [
        {"orden": m["orden"], "id_noticia": m["id_noticia"], "estrato": m["estrato"], "poblacion": m["poblacion"],
         "n_estrato": m["n_estrato"], "peso": repr(m["peso"]), "doble": "si" if m["doble"] else "no"} for m in sorteada
    ], ("orden", "id_noticia", "estrato", "poblacion", "n_estrato", "peso", "doble"))
    cfg = _cfg_con_ampliacion("propuestas/p.csv", congelada="congelada.csv")
    _propuestas(tmp_path / "propuestas" / "p.csv", ids)
    muestra = et.muestra_desde_base(ruta_base, cfg, tmp_path)
    assert [m["id_noticia"] for m in muestra[:100]] == [m["id_noticia"] for m in sorteada]   # la base creció y nada se movió
    assert [m["orden"] for m in muestra] == list(range(1, 101 + len(ids)))


def test_sin_congelar_los_ids_de_la_ampliacion_no_entran_al_sorteo_original(tmp_path):
    ruta_base, ids = _base_ampliada(tmp_path / "d")
    _propuestas(tmp_path / "propuestas" / "p.csv", ids)
    muestra = et.muestra_desde_base(ruta_base, _cfg_con_ampliacion("propuestas/p.csv"), tmp_path)
    assert not {m["id_noticia"] for m in muestra[:100]} & set(ids)


# ---------------------------------------------------------------- estrato y peso de la ampliación


def test_las_filas_de_ampliacion_llevan_su_estrato_y_peso_uno_y_no_son_dobles(tmp_path):
    ruta_base, ids = _base_ampliada(tmp_path / "e")
    _propuestas(tmp_path / "propuestas" / "p.csv", ids)
    muestra = et.muestra_desde_base(ruta_base, _cfg_con_ampliacion("propuestas/p.csv"), tmp_path)
    ext = muestra[100:]
    assert len(ext) == len(ids) and {m["estrato"] for m in ext} == {ESTRATO}
    assert {m["peso"] for m in ext} == {1.0} and not any(m["doble"] for m in ext)
    assert any(ESTRATO in linea and "peso 1.000" in linea for linea in et.composicion(muestra))


def test_consolidar_registra_estrato_y_peso_de_la_ampliacion(tmp_path):
    ruta_base, ids = _base_ampliada(tmp_path / "f")
    _propuestas(tmp_path / "propuestas" / "p.csv", ids)
    cfg = _cfg_con_ampliacion("propuestas/p.csv")
    muestra = et.muestra_desde_base(ruta_base, cfg, tmp_path)
    hojas = {"Ana Pérez": [_fila(ids[0], "Ana Pérez")]}
    finales, disputas = et.consolidar(hojas, cfg, muestra)
    assert disputas == [] and finales[0]["estrato"] == ESTRATO and float(finales[0]["peso_muestreo"]) == 1.0
    assert finales[0]["origen"] == "humano"


def test_validar_hoja_acepta_ids_de_la_ampliacion(tmp_path):
    ruta_base, ids = _base_ampliada(tmp_path / "g")
    _propuestas(tmp_path / "propuestas" / "p.csv", ids)
    muestra = et.muestra_desde_base(ruta_base, _cfg_con_ampliacion("propuestas/p.csv"), tmp_path)
    hoja = tmp_path / "ana_perez.csv"
    et.escribir_csv(hoja, [_fila(ids[0], "Ana Pérez")])
    assert et.validar_hoja(hoja, CFG, TEMAS, {m["id_noticia"] for m in muestra}) == []


def test_un_id_de_ampliacion_que_no_esta_en_la_base_falla_en_voz_alta(tmp_path):
    ruta_base, ids = _base_ampliada(tmp_path / "h")
    _propuestas(tmp_path / "propuestas" / "p.csv", [*ids, "NOT-inexistente"])
    with pytest.raises(et.ErrorEtiquetado, match="no están en la base"):
        et.muestra_desde_base(ruta_base, _cfg_con_ampliacion("propuestas/p.csv"), tmp_path)


# ---------------------------------------------------------------- propuestas: rellenan, no guardan


def test_la_propuesta_rellena_el_formulario_sin_guardar_nada(tmp_path):
    carpeta = tmp_path / "eval" / "etiquetas"
    p = {"ruido": "ninguno", "tema_principal": "economia", "tema_secundario": "turismo", "grupo": "Sismo Chiriquí",
         "alcance_regional": "True", "duda": "¿regional?"}
    valores = et.valores_desde_propuesta(p, CFG, TEMAS)
    assert valores == {"ruido": "ninguno", "tema_principal": "economia", "tema_secundario": "turismo", "grupo": "sismo-chiriqui",
                       "alcance_regional": "si", "nota": ""}
    assert not carpeta.exists() and list(tmp_path.rglob("*.csv")) == []   # función pura: ningún archivo


def test_una_propuesta_de_ruido_no_lleva_tema_ni_grupo_y_una_invalida_se_ignora():
    ruido = et.valores_desde_propuesta({"ruido": "no_es_panama", "tema_principal": "economia", "grupo": "x", "alcance_regional": "True"}, CFG, TEMAS)
    assert ruido and ruido["tema_principal"] == "" and ruido["grupo"] == "" and ruido["alcance_regional"] == ""
    assert et.valores_desde_propuesta({"ruido": "inventado"}, CFG, TEMAS) is None
    assert et.valores_desde_propuesta(None, CFG, TEMAS) is None
    tema_malo = et.valores_desde_propuesta({"ruido": "ninguno", "tema_principal": "no_existe"}, CFG, TEMAS)
    assert tema_malo and tema_malo["tema_principal"] == ""


def test_el_proveedor_se_lee_de_propuesto_por():
    assert et.proveedor_propuesta("llm:deepseek:deepseek-flash") == "deepseek"
    assert et.proveedor_propuesta("") == "desconocido"


def test_una_propuesta_sin_revisar_nunca_llega_al_consolidado(tmp_path):
    ruta_base, ids = _base_ampliada(tmp_path / "i")
    _propuestas(tmp_path / "propuestas" / "p.csv", ids)
    cfg = _cfg_con_ampliacion("propuestas/p.csv")
    assert et.leer_propuestas(tmp_path / "propuestas").keys() == set(ids)
    et.escribir_csv(tmp_path / CFG.archivos.carpeta_personas / "ana_perez.csv", [_fila("NOT-0000000001", "Ana Pérez")])
    assert et.leer_hojas(tmp_path, cfg).keys() == {"Ana Pérez"}     # las propuestas no son hojas
    muestra = et.muestra_desde_base(ruta_base, cfg, tmp_path)
    finales, _ = et.consolidar(et.leer_hojas(tmp_path, cfg), cfg, muestra)
    assert not {f["id_noticia"] for f in finales} & set(ids)


def test_la_carpeta_de_propuestas_no_es_la_de_hojas():
    cfg = cargar_etiquetado()
    assert cfg.archivos.carpeta_propuestas != cfg.archivos.carpeta_personas


def test_lo_que_este_en_el_consolidado_real_de_las_propuestas_es_de_una_persona():
    """Si una propuesta del repo ya está en eval/etiquetas.csv es porque una persona la revisó (origen humano)."""
    cfg = cargar_etiquetado()
    propuestas = et.leer_propuestas(et.RAIZ / cfg.archivos.carpeta_propuestas)
    for fila in et.leer_csv(et.RAIZ / cfg.archivos.consolidado):
        if fila["id_noticia"] in propuestas:
            assert fila["origen"] == "humano"
            for persona in fila["etiquetado_por"].split("; "):
                assert et.validar_nombre(persona, cfg) == persona


# ---------------------------------------------------------------- la muestra real congelada


def test_la_muestra_congelada_real_coincide_con_las_100_etiquetas_ya_hechas():
    cfg = cargar_etiquetado()
    congelada = et.leer_csv(et.RAIZ / cfg.muestra.congelada)
    ids = [f["id_noticia"] for f in congelada]
    assert len(ids) == len(set(ids)) == cfg.muestra.tamano
    assert sum(f["doble"] == "si" for f in congelada) == cfg.muestra.tamano_acuerdo
    for f in et.leer_csv(et.RAIZ / cfg.archivos.consolidado):
        if f["origen"] == "humano" and f["estrato"] in ("no_ruido", "ruido"):
            assert f["id_noticia"] in ids
    assert cargar_temas()   # la config completa carga


# ---------------------------------------------------------------- config


def test_la_config_rechaza_claves_desconocidas_y_estratos_repetidos():
    base = CFG.muestra.model_dump()
    amp = {"nombre": "a", "ids_desde": "x.csv", "estrato": "ampl", "peso_muestreo": 1.0}
    MuestraEtiquetado.model_validate({**base, "ampliaciones": [amp]})
    with pytest.raises(ValidationError):
        MuestraEtiquetado.model_validate({**base, "ampliaciones": [{**amp, "clave_rara": 1}]})
    with pytest.raises(ValidationError):
        MuestraEtiquetado.model_validate({**base, "inventada": 1})
    with pytest.raises(ValidationError, match="no puede ser no_ruido"):
        MuestraEtiquetado.model_validate({**base, "ampliaciones": [{**amp, "estrato": "ruido"}]})
    with pytest.raises(ValidationError, match="propios"):
        MuestraEtiquetado.model_validate({**base, "ampliaciones": [amp, {**amp, "nombre": "b"}]})
    with pytest.raises(ValidationError):
        MuestraEtiquetado.model_validate({**base, "ampliaciones": [{**amp, "peso_muestreo": 0}]})
