"""Pruebas offline del manifest y de validar_snapshot (E0-04). Sin red."""

import csv
import hashlib
import json
from pathlib import Path

from scripts import conversion, manifest, validar_snapshot
from tests.conftest import escribir_manifest


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def estados(informe: dict) -> dict[str, str]:
    return {c["comprobacion"]: c["estado"] for c in informe["comprobaciones"]}


# ------------------------------------------------------------------ manifest


def test_manifest_dos_corridas_dan_el_mismo_hash(data_sintetica: Path, config) -> None:
    primero = sha(data_sintetica / "manifest.json")
    escribir_manifest(data_sintetica, config)
    assert sha(data_sintetica / "manifest.json") == primero
    escribir_manifest(data_sintetica, config)
    assert sha(data_sintetica / "manifest.json") == primero


def test_manifest_desde_cero_es_reproducible(data_sintetica: Path, config) -> None:
    """Borrar el manifest y regenerarlo desde el mismo raw produce el mismo archivo."""
    primero = sha(data_sintetica / "manifest.json")
    (data_sintetica / "manifest.json").unlink()
    escribir_manifest(data_sintetica, config)
    assert sha(data_sintetica / "manifest.json") == primero


def test_fecha_de_corte_sale_de_los_crudos_no_de_now(data_sintetica: Path) -> None:
    m = json.loads((data_sintetica / "manifest.json").read_text("utf-8"))
    assert m["fecha_corte_UTC"] == "2026-10-06T12:05:00Z"  # el crudo más reciente (GDELT)
    assert m["historial"][0]["fecha"] == m["fecha_corte_UTC"]


def test_manifest_contenido_minimo(data_sintetica: Path) -> None:
    m = json.loads((data_sintetica / "manifest.json").read_text("utf-8"))
    assert m["cantidad_por_archivo"]["noticias.csv"] == 5
    assert m["cantidad_por_archivo"]["eventos.geojson"] == 2
    assert set(m["sha256"]) == {f"processed/{n}" for n in manifest.ARCHIVOS_PROCESSED}
    assert m["sha256"]["processed/noticias.csv"] == sha(data_sintetica / "processed" / "noticias.csv")
    assert "gdelt" in m["consultas"] and "usgs" in m["consultas"]
    assert "inconsistencia" in m["nota_intervalo_seccion_7"].lower()
    cobertura = m["cobertura_efectiva"]
    assert cobertura["fecha_inicial"] == "2026-10-01T01:02:03Z"
    assert cobertura["fecha_final"] == "2026-10-04T09:30:00Z"
    assert cobertura["ventana_dias_aplicada"] == 30
    h = m["historial"][0]
    assert h["version"] == "1.0" and h["registros_excluidos"]["por_motivo"] == {"fuera_de_ventana": 1}


def test_cuadricula_documenta_la_inconsistencia_del_pdf(data_sintetica: Path, config) -> None:
    m = json.loads((data_sintetica / "manifest.json").read_text("utf-8"))
    assert "1350" in m["nota_cuadricula_banco_mundial"] and "= 12" in m["nota_cuadricula_banco_mundial"]
    informe = validar_snapshot.validar(data_sintetica, config)
    assert estados(informe)["cuadricula:pdf_inconsistente"] == "advertencia"


def test_historial_agrega_version_solo_si_el_snapshot_cambia(data_sintetica: Path, config) -> None:
    raw = data_sintetica / "raw"
    (raw / "rss_tvn" / "rss_tvn_20261007T120000Z.xml").write_text(
        (raw / "rss_tvn" / "rss_tvn_20261006T120000Z.xml").read_text("utf-8").replace("Titular dos", "Titular dos bis"),
        encoding="utf-8",
    )
    conversion.convertir_todo(raw, data_sintetica / "processed", config)
    m = escribir_manifest(data_sintetica, config)
    assert [h["version"] for h in m["historial"]] == ["1.0", "1.1"]
    assert m["version"] == "1.1"
    assert m["historial"][1]["cambios_de_fuente"] == ["Cambió el contenido sin cambiar los conteos"]
    assert len(escribir_manifest(data_sintetica, config)["historial"]) == 2  # idempotente


def test_changelog_resume_el_historial(data_sintetica: Path, config) -> None:
    m = json.loads((data_sintetica / "manifest.json").read_text("utf-8"))
    manifest.escribir_changelog(data_sintetica / "CHANGELOG.md", m)
    texto = (data_sintetica / "CHANGELOG.md").read_text("utf-8")
    assert "## v1.0" in texto and m["historial"][0]["hash_snapshot"] in texto


# ---------------------------------------------------------- validar_snapshot


def test_snapshot_sintetico_valido(data_sintetica: Path, config) -> None:
    informe = validar_snapshot.validar(data_sintetica, config)
    assert informe["aprobado"], [c for c in informe["comprobaciones"] if c["estado"] == "error"]
    assert informe["resumen"]["noticias"] == 5 and informe["resumen"]["noticias_tvn"] == 3
    assert informe["resumen"]["indicadores"] == 12


def test_falla_si_el_manifest_no_tiene_historial(data_sintetica: Path, config) -> None:
    ruta = data_sintetica / "manifest.json"
    m = json.loads(ruta.read_text("utf-8"))
    del m["historial"]
    ruta.write_text(json.dumps(m), encoding="utf-8")
    informe = validar_snapshot.validar(data_sintetica, config)
    assert not informe["aprobado"]
    assert estados(informe)["manifest:campos_minimos"] == "error"
    assert estados(informe)["manifest:historial"] == "error"


def test_falla_si_el_historial_esta_vacio(data_sintetica: Path, config) -> None:
    ruta = data_sintetica / "manifest.json"
    m = json.loads(ruta.read_text("utf-8"))
    m["historial"] = []
    ruta.write_text(json.dumps(m), encoding="utf-8")
    assert estados(validar_snapshot.validar(data_sintetica, config))["manifest:historial"] == "error"


def test_falla_si_falta_un_campo_minimo_del_contrato_en_noticias(data_sintetica: Path, config) -> None:
    ruta = data_sintetica / "processed" / "noticias.csv"
    with ruta.open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    columnas = [c for c in filas[0] if c != "fecha_deteccion"]
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    informe = validar_snapshot.validar(data_sintetica, config)
    assert not informe["aprobado"]
    assert estados(informe)["contrato:noticias.csv"] == "error"


def test_falla_si_falta_un_campo_en_indicadores_y_eventos(data_sintetica: Path, config) -> None:
    ruta = data_sintetica / "processed" / "indicadores.csv"
    ruta.write_text(ruta.read_text("utf-8").replace("licencia", "lic", 1), encoding="utf-8")
    ev = data_sintetica / "processed" / "eventos.geojson"
    datos = json.loads(ev.read_text("utf-8"))
    del datos["features"][0]["properties"]["place"]
    ev.write_text(json.dumps(datos), encoding="utf-8")
    e = estados(validar_snapshot.validar(data_sintetica, config))
    assert e["contrato:indicadores.csv"] == "error" and e["contrato:eventos.geojson"] == "error"


def test_falla_si_la_cuadricula_no_esta_completa(data_sintetica: Path, config) -> None:
    ruta = data_sintetica / "processed" / "indicadores.csv"
    lineas = ruta.read_text("utf-8").splitlines()
    ruta.write_text("\n".join(lineas[:-1]) + "\n", encoding="utf-8")
    assert estados(validar_snapshot.validar(data_sintetica, config))["cuadricula:banco_mundial"] == "error"


def test_falla_si_un_sismo_cae_fuera_de_la_caja(data_sintetica: Path, config) -> None:
    ev = data_sintetica / "processed" / "eventos.geojson"
    datos = json.loads(ev.read_text("utf-8"))
    datos["features"][0]["properties"]["latitude"] = 30.0
    ev.write_text(json.dumps(datos), encoding="utf-8")
    assert estados(validar_snapshot.validar(data_sintetica, config))["usgs:caja_y_magnitud"] == "error"


def test_volumenes_minimo_es_error_y_meta_es_advertencia(data_sintetica: Path, config) -> None:
    # 5 noticias, 3 de TVN: sobre el mínimo (3) y bajo la meta (6) -> advertencia
    e = estados(validar_snapshot.validar(data_sintetica, config))
    assert e["volumen:total"] == "advertencia" and e["volumen:tvn"] == "ok"
    config["volumen_noticias"] = {"meta": 6, "minimo": 6, "minimo_tvn": 4}
    informe = validar_snapshot.validar(data_sintetica, config)
    e = estados(informe)
    assert e["volumen:total"] == "error" and e["volumen:tvn"] == "error"
    assert not informe["aprobado"]


def test_falla_si_noticias_trae_descripcion(data_sintetica: Path, config) -> None:
    ruta = data_sintetica / "processed" / "noticias.csv"
    primera, *resto = ruta.read_text("utf-8").splitlines()
    ruta.write_text("\n".join([primera + ",descripcion", *[r + ",x" for r in resto]]) + "\n", encoding="utf-8")
    assert estados(validar_snapshot.validar(data_sintetica, config))["d72:noticias.csv"] == "error"


def test_falla_si_un_archivo_cambia_despues_del_manifest(data_sintetica: Path, config) -> None:
    ruta = data_sintetica / "processed" / "fuentes.json"
    ruta.write_text(ruta.read_text("utf-8") + "\n", encoding="utf-8")
    assert estados(validar_snapshot.validar(data_sintetica, config))["manifest:sha256"] == "error"


def test_cli_escribe_informe_y_devuelve_codigo(data_sintetica: Path, tmp_path: Path, config, monkeypatch) -> None:
    monkeypatch.setattr(conversion, "cargar_config", lambda ruta=None: config)
    salida = tmp_path / "out" / "validacion.json"
    codigo = validar_snapshot.main(["--ruta", str(data_sintetica), "--salida", str(salida)])
    assert codigo == 0 and json.loads(salida.read_text("utf-8"))["aprobado"] is True
    (data_sintetica / "manifest.json").unlink()
    assert validar_snapshot.main(["--ruta", str(data_sintetica), "--salida", str(salida)]) == 1
