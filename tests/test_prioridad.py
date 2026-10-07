"""E1-10 · Tubería de prioridad sobre DuckDB: persistencia, reproducibilidad, LLM que degrada y CLI (sin red ni LLM real)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src import db, embeddings, prioridad
from src.configuracion import cargar_reglas
from tests.motor_falso import MotorFalso, config_de_prueba
from tests.prioridad_ayuda import ProveedorFalso, construir_base, fila_grupo, fila_noticia, filas_procedencias

CORTE = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return construir_base(tmp_path / "senales.duckdb")


@pytest.fixture
def emb(tmp_path: Path):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)


def _correr(base: Path, tmp_path: Path, emb, proveedor=None) -> dict:
    return prioridad.ejecutar(base, tmp_path / "prioridad.json", CORTE, proveedor, emb=emb)


def _tabla(base: Path, tabla: str, orden: str) -> list[dict]:
    con = db.conectar(base, solo_lectura=True)
    try:
        return db.leer_tabla(con, tabla, orden)
    finally:
        con.close()


def _par_ids(grupo: str) -> dict:
    return {"id_a": f"NOT-{grupo}000000001", "id_b": f"NOT-{grupo}000000002"}


def _llm(posibles: dict[str, bool]) -> ProveedorFalso:
    """Un proveedor falso que responde a todos los grupos con los pares de ``posibles`` (a, d)."""
    pares = [
        {**_par_ids(g), "posible_contradiccion": v, "fragmento_a": ("12" if g == "a" else "12 colegios") if v else "", "fragmento_b": ("40" if g == "a" else "40 colegios") if v else ""}
        for g, v in posibles.items()
    ]
    return ProveedorFalso({"pares": pares})


# ------------------------------------------------------------------ persistencia


def test_ejecutar_guarda_puntajes_evidencia_y_contradicciones_de_cada_grupo(base, tmp_path, emb) -> None:
    reporte = _correr(base, tmp_path, emb, ProveedorFalso({"pares": []}))
    puntajes = _tabla(base, "puntajes", "posicion")
    assert [p["posicion"] for p in puntajes] == [1, 2, 3, 4]
    assert {p["id_grupo"] for p in puntajes} == {"GRP-a", "GRP-b", "GRP-c", "GRP-d"} == {e["id_grupo"] for e in _tabla(base, "evidencia", "id_grupo")}
    for p in puntajes:
        r, i, u, n, e = (p[k] for k in ("relevancia", "impacto", "urgencia", "novedad", "evidencia"))
        reglas = cargar_reglas()
        assert p["puntaje"] == pytest.approx(30 * r + 25 * i + 20 * u + 15 * n + 10 * e)
        assert p["version_reglas"] == "1.3" and p["fecha_referencia"] == "2026-10-06T12:00:00Z"
        assert set(json.loads(p["componentes"])) == {"R", "I", "U", "N", "E"} and reglas.version == p["version_reglas"]
    assert reporte["grupos"] == 4 and [f["posicion"] for f in reporte["ranking"]] == [1, 2, 3, 4]


def test_el_dato_oficial_ambiguo_no_cuenta_y_el_vinculado_si(base, tmp_path, emb) -> None:
    _correr(base, tmp_path, emb, None)
    e = {x["id_grupo"]: x for x in _tabla(base, "evidencia", "id_grupo")}
    assert e["GRP-b"]["tiene_oficial"] is True
    assert e["GRP-a"]["tiene_oficial"] is False     # el candidato ambiguo de USGS no es evidencia
    assert "tema_sin_indicador" in e["GRP-c"]["vacios"]


def test_dos_corridas_producen_las_mismas_filas_y_el_mismo_ranking(base, tmp_path, emb) -> None:
    _correr(base, tmp_path, emb, None)
    primera = _tabla(base, "puntajes", "posicion")
    _correr(base, tmp_path, emb, None)
    assert _tabla(base, "puntajes", "posicion") == primera


def test_volver_a_correr_reemplaza_las_filas_y_no_las_duplica(base, tmp_path, emb) -> None:
    for _ in range(2):
        _correr(base, tmp_path, emb, _llm({"a": True, "d": False}))
    assert len(_tabla(base, "puntajes", "posicion")) == 4
    assert len(_tabla(base, "contradicciones", "id_grupo")) == 2


# ------------------------------------------------------------------ contradicciones y estado


def test_una_posible_contradiccion_abierta_impide_evidencia_suficiente_y_aparece_con_ambas_versiones(base, tmp_path, emb) -> None:
    _correr(base, tmp_path, emb, _llm({"a": True, "d": False}))
    c = {x["id_grupo"]: x for x in _tabla(base, "contradicciones", "id_grupo")}
    assert c["GRP-a"]["estado"] == "verificar" and c["GRP-a"]["etiqueta"] == "posible contradicción, verificar"
    assert (c["GRP-a"]["medio_a"], c["GRP-a"]["medio_b"]) == ("medio-a.example", "medio-b.example")
    assert c["GRP-d"]["estado"] == "descartada"
    e = {x["id_grupo"]: x for x in _tabla(base, "evidencia", "id_grupo")}
    assert e["GRP-a"]["contradicciones_abiertas"] == 1 and e["GRP-a"]["estado"] == "parcial"   # 2 procedencias pero con contradicción y cifras sin dato oficial
    assert e["GRP-d"]["contradicciones_abiertas"] == 0


def test_si_el_llm_falla_el_puntaje_se_calcula_igual_y_los_pares_quedan_pendientes(base, tmp_path, emb) -> None:
    proveedor = ProveedorFalso(falla=True)
    reporte = _correr(base, tmp_path, emb, proveedor)
    assert len(_tabla(base, "puntajes", "posicion")) == 4
    assert {c["estado"] for c in _tabla(base, "contradicciones", "id_grupo")} == {"pendiente_llm"}
    assert reporte["llm"]["estado"] == "no_disponible" and reporte["contradicciones"]["por_estado"] == {"pendiente_llm": 2}
    assert len(proveedor.llamadas) == 1              # tras el primer fallo no se vuelve a intentar (corte)
    assert all(e["contradicciones_abiertas"] == 1 for e in _tabla(base, "evidencia", "id_grupo") if e["id_grupo"] in ("GRP-a", "GRP-d"))


def test_sin_proveedor_los_pares_quedan_pendientes_y_el_reporte_lo_dice(base, tmp_path, emb) -> None:
    reporte = _correr(base, tmp_path, emb, None)
    assert reporte["llm"] == {"estado": "sin_llm", "proveedor": None, "modelo": None, "motivos_pendientes": {"sin proveedor de LLM configurado": 2}}


def test_sin_pares_candidatos_el_llm_no_se_llama(tmp_path, emb) -> None:
    noticias = [fila_noticia("NOT-z000000001", "Panamá reporta inflación estable", "medio.example", "GRP-z")]
    ruta = tmp_path / "s.duckdb"
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": [fila_grupo("GRP-z", ["NOT-z000000001"], "Inflación", 1)], "procedencias": filas_procedencias("GRP-z", ["NOT-z000000001"])})
    proveedor = ProveedorFalso({"pares": []})
    reporte = prioridad.ejecutar(ruta, tmp_path / "p.json", CORTE, proveedor, emb=emb)
    assert proveedor.llamadas == [] and reporte["llm"]["estado"] == "sin_candidatos"


# ------------------------------------------------------------------ nada habilita publicar


def test_ninguna_salida_persistida_habla_de_publicar(base, tmp_path, emb) -> None:
    reporte = _correr(base, tmp_path, emb, _llm({"a": True, "d": False}))
    assert "habilita publicar" in reporte["nota"]            # la única mención es la advertencia fija
    textos = [json.dumps({k: v for k, v in reporte.items() if k != "nota"}, ensure_ascii=False)]
    for tabla in ("puntajes", "evidencia", "contradicciones"):
        textos += [json.dumps(fila, ensure_ascii=False, default=str) for fila in _tabla(base, tabla, "id_grupo")]
    assert not re.search(r"\bpublic(ar|ala|alo|ado|able|ó|aron)\b", "\n".join(textos), re.IGNORECASE)
    assert all(not e["accion"].lower().startswith("public") for e in _tabla(base, "evidencia", "id_grupo"))


# ------------------------------------------------------------------ CLI


def test_el_cli_corre_con_sin_llm_y_la_fecha_del_manifest(base, tmp_path, emb, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"fecha_corte_UTC": "2026-10-06T12:00:00Z"}), encoding="utf-8")
    monkeypatch.setattr(prioridad, "crear", lambda *a, **k: emb)
    reporte = tmp_path / "salida" / "prioridad.json"
    codigo = prioridad.main(["--base", str(base), "--manifest", str(manifest), "--reporte", str(reporte), "--sin-llm"])
    assert codigo == 0 and json.loads(reporte.read_text(encoding="utf-8"))["fecha_referencia"] == "2026-10-06T12:00:00Z"


def test_el_cli_falla_con_un_mensaje_si_falta_la_base_o_la_fecha_no_tiene_zona(base, tmp_path) -> None:
    assert prioridad.main(["--base", str(tmp_path / "no_existe.duckdb")]) == 1
    assert prioridad.main(["--base", str(base), "--ahora", "2026-10-06T12:00:00", "--sin-llm"]) == 1


def test_la_fecha_de_corte_sale_del_manifest_en_utc(tmp_path) -> None:
    ruta = tmp_path / "m.json"
    ruta.write_text(json.dumps({"fecha_corte_UTC": "2026-10-06T17:07:06Z"}), encoding="utf-8")
    assert prioridad.fecha_de_corte(ruta) == datetime(2026, 10, 6, 17, 7, 6, tzinfo=UTC)
    with pytest.raises(ValueError, match="zona"):
        prioridad.parsear_fecha("2026-10-06T17:07:06")
