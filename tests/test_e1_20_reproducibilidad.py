"""E1-20 · Reproducibilidad de punta a punta: hashes canónicos, comparación con el manifest y orden del pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pytest
import yaml

from scripts import manifest as manifest_mod
from scripts import reproducir as rep
from src.configuracion import CARPETA_CONFIG, RAIZ, ErrorDeConfiguracion, cargar_config, cargar_reproducibilidad
from src.configuracion import ConfigReproducibilidad

CFG = cargar_reproducibilidad()
ORDEN_SPEC = ["validacion", "normalizacion", "limpieza", "clasificacion", "agrupacion", "contexto", "puntaje", "fichas", "benchmark"]


# ------------------------------------------------------------------ hash canónico


def test_la_huella_no_depende_del_orden_de_las_claves() -> None:
    assert rep.huella_canonica({"a": 1, "b": [1, 2]}, 4) == rep.huella_canonica({"b": [1, 2], "a": 1}, 4)


def test_la_huella_redondea_el_ruido_de_flotantes_pero_no_un_cambio_real() -> None:
    base = {"similitud": 0.7887669801712036}
    assert rep.huella_canonica(base, 4) == rep.huella_canonica({"similitud": 0.7887671589851379}, 4)
    assert rep.huella_canonica(base, 4) != rep.huella_canonica({"similitud": 0.7889}, 4)


def test_la_huella_distingue_nulo_de_cero_y_no_redondea_enteros() -> None:
    assert rep.huella_canonica({"v": None}, 4) != rep.huella_canonica({"v": 0}, 4)
    assert rep.redondear({"n": 3, "x": True}, 2) == {"n": 3, "x": True}


def test_las_columnas_json_de_una_tabla_se_redondean_por_dentro() -> None:
    a = rep.redondear({"c": '{"E": {"s": 0.31674081087112427}}'}, 4, parsear_json=True)
    b = rep.redondear({"c": '{"E": {"s": 0.3167406916618347}}'}, 4, parsear_json=True)
    assert a == b


def test_quitar_rutas_excluye_solo_lo_declarado() -> None:
    obj = {"fecha_utc": "x", "latencia": {"consulta": {"p50": 1}, "paquete": {"p50": 2}}, "otro": 3}
    assert rep.quitar_rutas(obj, ["fecha_utc", "latencia.consulta"]) == {"latencia": {"paquete": {"p50": 2}}, "otro": 3}
    assert rep.quitar_rutas(obj, ["no.existe"]) == obj
    assert "fecha_utc" in obj  # no muta la entrada


def test_la_huella_de_una_tabla_no_depende_del_orden_de_insercion(tmp_path: Path) -> None:
    def base(ruta: Path, filas: list[tuple[str, float]]) -> Path:
        con = duckdb.connect(str(ruta))
        con.execute("CREATE TABLE grupos (id VARCHAR, valor DOUBLE)")
        con.executemany("INSERT INTO grupos VALUES (?, ?)", filas)
        con.close()
        return ruta

    filas = [("GRP-b", 0.5), ("GRP-a", 0.25), ("GRP-c", None)]
    h1 = rep.huellas_de_tablas(base(tmp_path / "1.duckdb", filas), ["grupos"], 4)
    h2 = rep.huellas_de_tablas(base(tmp_path / "2.duckdb", filas[::-1]), ["grupos"], 4)
    assert h1 == h2 and set(h1) == {"tabla:grupos"}


def test_una_tabla_ausente_se_declara_en_vez_de_ignorarse(tmp_path: Path) -> None:
    ruta = tmp_path / "v.duckdb"
    duckdb.connect(str(ruta)).close()
    with pytest.raises(rep.ErrorDeReproduccion, match="grupos"):
        rep.huellas_de_tablas(ruta, ["grupos"], 4)


# ------------------------------------------------------------------ comparación con el manifest


def test_comparar_sin_diferencias() -> None:
    reg = {"a": "1", "b": "2"}
    assert rep.comparar(reg, dict(reg)) == []


def test_comparar_reporta_distinto_faltante_y_nuevo() -> None:
    dif = rep.comparar({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "X", "d": "4"})
    por_clave = {d.clave: d.tipo for d in dif}
    assert por_clave == {"b": "distinto", "c": "faltante", "d": "nuevo"}
    assert all(d.clave in str(d) for d in dif)


def test_el_borrador_registrado_completo_que_ya_no_sale_de_la_cache_es_una_diferencia() -> None:
    reg = {"GRP-1": {"estado": "completo", "sha256": "aa"}}
    act = {"GRP-1": {"estado": "sin_cache", "sha256": None}}
    dif, limitaciones = rep.comparar_borradores(reg, act)
    assert [d.clave for d in dif] == ["borrador:GRP-1"] and not limitaciones


def test_el_borrador_sin_cache_en_ambos_lados_es_una_limitacion_no_un_fallo() -> None:
    reg = {"GRP-1": {"estado": "sin_cache", "sha256": None}}
    dif, limitaciones = rep.comparar_borradores(reg, dict(reg))
    assert dif == [] and len(limitaciones) == 1 and "GRP-1" in limitaciones[0]


def test_el_borrador_de_la_cache_con_otro_hash_es_una_diferencia() -> None:
    dif, _ = rep.comparar_borradores({"GRP-1": {"estado": "completo", "sha256": "aa"}}, {"GRP-1": {"estado": "completo", "sha256": "bb"}})
    assert [d.tipo for d in dif] == ["distinto"]


def test_las_entradas_distintas_se_listan_como_aviso() -> None:
    avisos = rep.comparar_entradas(
        {"embeddings": {"revision": "r1"}, "prompts": {"p.txt": "a"}, "commit": "c1"},
        {"embeddings": {"revision": "r2"}, "prompts": {"p.txt": "a"}, "commit": "c2"},
    )
    assert any("embeddings" in a for a in avisos) and not any("prompts" in a for a in avisos)
    assert not any("commit" in a for a in avisos)  # el commit cambia en cada ejecución: se registra, no se compara


# ------------------------------------------------------------------ pipeline


def test_los_pasos_siguen_el_orden_de_la_spec() -> None:
    nombres = [p.nombre for p in CFG.pasos]
    posiciones = [next(i for i, n in enumerate(nombres) if n.startswith(clave)) for clave in ORDEN_SPEC]
    assert posiciones == sorted(posiciones)


def test_ejecutar_pasos_corre_en_orden_y_se_detiene_en_el_primer_fallo() -> None:
    llamados: list[str] = []

    def ejecutor(paso) -> int:  # noqa: ANN001
        llamados.append(paso.nombre)
        return 1 if paso.nombre == "limpieza" else 0

    with pytest.raises(rep.ErrorDeReproduccion, match="limpieza"):
        rep.ejecutar_pasos(CFG.pasos, ejecutor)
    assert llamados[-1] == "limpieza" and llamados == [p.nombre for p in CFG.pasos][: len(llamados)]
    assert "clasificacion" not in llamados


def test_un_paso_de_modulo_se_arma_con_python_m_y_sus_argumentos() -> None:
    paso = next(p for p in CFG.pasos if p.nombre == "puntaje")
    comando = rep.comando_de(paso)
    assert comando[1:3] == ["-m", "src.puntaje"] and "--sin-llm" in comando


def test_la_configuracion_exige_modulo_solo_en_los_pasos_de_modulo() -> None:
    datos = yaml.safe_load((CARPETA_CONFIG / "reproducibilidad.yaml").read_text(encoding="utf-8"))
    datos["pasos"].append({"nombre": "x", "tipo": "modulo"})
    with pytest.raises(ValueError, match="modulo"):
        ConfigReproducibilidad.model_validate(datos)
    datos["pasos"][-1] = {"nombre": "limpieza", "tipo": "modulo", "modulo": "m"}
    with pytest.raises(ValueError, match="repetidos"):
        ConfigReproducibilidad.model_validate(datos)


def test_la_configuracion_no_admite_claves_desconocidas() -> None:
    datos = yaml.safe_load((CARPETA_CONFIG / "reproducibilidad.yaml").read_text(encoding="utf-8"))
    datos["inventada"] = 1
    with pytest.raises(ValueError):
        ConfigReproducibilidad.model_validate(datos)


# ------------------------------------------------------------------ verificación y manifest


def _manifest(tmp_path: Path, repro: dict | None) -> Path:
    cuerpo = {"version": "1.0"} | ({"reproducibilidad": repro} if repro is not None else {})
    ruta = tmp_path / "manifest.json"
    ruta.write_text(json.dumps(cuerpo), encoding="utf-8")
    return ruta


def _estado(salidas: dict[str, str], borradores: dict | None = None) -> dict:
    return {
        "ejecucion": {"commit": "c", "embeddings": {"revision": "r"}},
        "salidas_deterministas": salidas,
        "borradores_cache": borradores or {},
    }


def test_verificar_sale_0_si_coincide_y_1_si_difiere(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    registrado = _estado({"a": "1", "b": "2"})
    ruta = _manifest(tmp_path, registrado)
    assert rep.verificar(ruta, registrado) == 0
    assert rep.verificar(ruta, _estado({"a": "1", "b": "9"})) == 1
    salida = capsys.readouterr().out
    assert "b" in salida and "distinto" in salida


def test_verificar_sin_registro_en_el_manifest_falla_con_un_mensaje_claro(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert rep.verificar(_manifest(tmp_path, None), _estado({"a": "1"})) == 1
    assert "reproducir" in capsys.readouterr().out


def test_registrar_conserva_el_resto_del_manifest(tmp_path: Path) -> None:
    ruta = _manifest(tmp_path, None)
    rep.registrar(ruta, _estado({"a": "1"}))
    cuerpo = json.loads(ruta.read_text(encoding="utf-8"))
    assert cuerpo["version"] == "1.0" and cuerpo["reproducibilidad"]["salidas_deterministas"] == {"a": "1"}


def test_regenerar_el_manifest_no_borra_el_registro_de_reproducibilidad(tmp_path: Path) -> None:
    previo = {"reproducibilidad": {"salidas_deterministas": {"a": "1"}}}
    assert manifest_mod.conservar_reproducibilidad({"version": "x"}, previo) == {"version": "x", **previo}
    assert "reproducibilidad" not in manifest_mod.conservar_reproducibilidad({"version": "x"}, {})


def test_el_manifest_versionado_registra_las_salidas_deterministas() -> None:
    repro = json.loads((RAIZ / "data" / "manifest.json").read_text(encoding="utf-8"))["reproducibilidad"]
    claves = set(repro["salidas_deterministas"])
    assert {"metricas", "fichas"} <= claves and any(c.startswith("tabla:grupos") for c in claves) and any(c.startswith("tabla:puntajes") for c in claves)
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in repro["salidas_deterministas"].values())
    assert set(repro["ejecucion"]) >= {"commit", "embeddings", "llm", "reglas", "prompts", "semillas", "python"}


def test_las_versiones_registradas_salen_de_la_configuracion_y_de_los_archivos() -> None:
    e = rep.registrar_entradas(RAIZ, CFG)
    assert e["embeddings"]["id"] and e["embeddings"]["revision"]
    assert e["reglas"]["version"] == "1.3" and re.fullmatch(r"[0-9a-f]{64}", e["reglas"]["sha256"])
    assert set(e["prompts"]) == {p.name for p in (RAIZ / "prompts").glob("*.txt")}
    assert e["llm"]["temperatura"] == 0.0 and e["llm"]["modelo"]
    assert re.fullmatch(r"[0-9a-f]{40}", e["commit"])


def test_todas_las_semillas_de_config_estan_registradas_y_documentadas() -> None:
    semillas = rep.semillas_de_config(CARPETA_CONFIG)
    assert {"clasificacion.yaml:semilla", "etiquetado.yaml:semilla", "benchmark.yaml:intervalos.semilla", "benchmark.yaml:sustento.semilla"} <= set(semillas)
    docs = (RAIZ / "docs" / "parametros.md").read_text(encoding="utf-8")
    faltan = [k for k in semillas if k not in docs]
    assert not faltan, f"semillas sin documentar en docs/parametros.md: {faltan}"


def test_los_pasos_internos_de_la_config_existen_en_el_script() -> None:
    internos = {p.nombre for p in CFG.pasos if p.tipo == "interno"}
    assert internos == set(rep.PASOS_INTERNOS)


def test_cargar_config_rechaza_un_yaml_roto(tmp_path: Path) -> None:
    (tmp_path / "reproducibilidad.yaml").write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion):
        cargar_config("reproducibilidad", ConfigReproducibilidad, tmp_path)
