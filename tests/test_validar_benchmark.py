"""Pruebas del validador del benchmark de desarrollo (E0-06).

Todo es sintético y offline: los archivos se generan en ``tmp_path``.
"""

import csv
import json
from pathlib import Path

import pytest

from eval import validar_benchmark as vb
from src.configuracion import ConfigBenchmark, cargar_benchmark

PROPORCION = {
    "respuesta_sustentada": 20,
    "contradiccion_ambiguedad": 7,
    "sin_respuesta": 7,
    "adversarial": 6,
}


def linea(numero: int, tipo: str, **cambios: object) -> dict[str, object]:
    """Construye una línea válida del tipo dado, con campos sobrescribibles."""
    base: dict[str, object] = {
        "id": f"BDEV-{numero:03d}",
        "tipo": tipo,
        "consulta": f"Consulta sintética {numero}",
        "respuesta_esperada": "Respuesta sintética",
        "ids_evidencia": ["SYN-0001"],
        "debe_abstenerse": False,
        "sintetico": True,
        "etiquetado_por": "Persona de prueba",
    }
    if tipo == "sin_respuesta":
        base.update(respuesta_esperada=None, ids_evidencia=[], debe_abstenerse=True)
    base.update(cambios)
    return base


def lineas_validas(proporcion: dict[str, int] = PROPORCION) -> list[dict[str, object]]:
    lineas: list[dict[str, object]] = []
    for tipo, cantidad in proporcion.items():
        for _ in range(cantidad):
            lineas.append(linea(len(lineas) + 1, tipo))
    return lineas


def escribir(ruta: Path, lineas: list[dict[str, object]]) -> Path:
    ruta.write_text("\n".join(json.dumps(x) for x in lineas) + "\n", encoding="utf-8")
    return ruta


def errores_de(
    lineas: list[dict[str, object]],
    snapshot: set[str] | None = None,
    sinteticos: set[str] | None = None,
) -> list[str]:
    textos = [json.dumps(x) for x in lineas]
    return vb.validar_lineas(textos, cargar_benchmark(), snapshot, sinteticos)[1]


def fixture_sinteticos(ruta: Path, *ids: str) -> Path:
    """Escribe un fixture ``sinteticos.csv`` mínimo con los IDs dados."""
    filas = "".join(f"{i},titular sintético,sintetico\n" for i in ids)
    ruta.write_text("id_noticia,titulo,origen\n" + filas, encoding="utf-8")
    return ruta


def test_metas_del_yaml_son_20_7_7_6() -> None:
    metas = cargar_benchmark()
    assert metas.total == 40
    assert dict(metas.tipos) == PROPORCION


def test_archivo_valido_pasa_e_imprime_conteo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = escribir(tmp_path / "dev.jsonl", lineas_validas())
    sinteticos = fixture_sinteticos(tmp_path / "sinteticos.csv", "SYN-0001")
    assert vb.main(["--ruta", str(ruta), "--sinteticos", str(sinteticos)]) == 0
    salida = capsys.readouterr().out
    for tipo, cantidad in PROPORCION.items():
        assert f"{tipo}: {cantidad} / {cantidad}" in salida
    assert "total: 40 / 40" in salida


def test_proporcion_incorrecta_falla(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mala = {**PROPORCION, "respuesta_sustentada": 21, "adversarial": 5}
    ruta = escribir(tmp_path / "dev.jsonl", lineas_validas(mala))
    assert vb.main(["--ruta", str(ruta)]) == 1
    assert "respuesta_sustentada: 21 distinto de 20" in capsys.readouterr().err


def test_total_incorrecto_falla() -> None:
    assert any("total 39" in e for e in errores_de(lineas_validas()[:-1]))


def test_campo_desconocido_falla() -> None:
    lineas = lineas_validas()
    lineas[0]["extra"] = "x"
    assert any("extra" in e for e in errores_de(lineas))


def test_campo_faltante_falla() -> None:
    lineas = lineas_validas()
    del lineas[0]["sintetico"]
    assert any("sintetico" in e for e in errores_de(lineas))


def test_sin_respuesta_con_respuesta_falla() -> None:
    lineas = lineas_validas()
    indice = next(i for i, x in enumerate(lineas) if x["tipo"] == "sin_respuesta")
    lineas[indice]["respuesta_esperada"] = "Algo"
    assert any("respuesta_esperada=null" in e for e in errores_de(lineas))


def test_sin_respuesta_sin_abstencion_falla() -> None:
    lineas = lineas_validas()
    indice = next(i for i, x in enumerate(lineas) if x["tipo"] == "sin_respuesta")
    lineas[indice]["debe_abstenerse"] = False
    assert any("debe_abstenerse=true" in e for e in errores_de(lineas))


def test_respuesta_sustentada_exige_respuesta_evidencia_y_no_abstenerse() -> None:
    lineas = lineas_validas()
    lineas[0].update(respuesta_esperada=None, ids_evidencia=[], debe_abstenerse=True)
    errores = errores_de(lineas)
    assert any("exige respuesta_esperada" in e for e in errores)
    assert any("ids_evidencia no vacío" in e for e in errores)
    assert any("debe_abstenerse=false" in e for e in errores)


@pytest.mark.parametrize("nombre", ["Claude", "ia", "Asistente", "Claude Code", "ChatGPT"])
def test_etiquetado_por_ia_falla(nombre: str) -> None:
    lineas = lineas_validas()
    lineas[0]["etiquetado_por"] = nombre
    assert any("personas" in e for e in errores_de(lineas))


@pytest.mark.parametrize("texto", ["PENDIENTE_HUMANO", "pendiente", "por asignar", "TBD"])
def test_etiquetado_por_provisorio_falla(texto: str) -> None:
    """Una propuesta sin revisar no cuenta como etiqueta humana."""
    lineas = lineas_validas()
    lineas[0]["etiquetado_por"] = texto
    assert any("pendiente de revisión humana" in e for e in errores_de(lineas))


def test_etiquetado_por_vacio_falla() -> None:
    lineas = lineas_validas()
    lineas[0]["etiquetado_por"] = "  "
    assert errores_de(lineas)


def test_syn_con_sintetico_false_falla() -> None:
    lineas = lineas_validas()
    lineas[0]["sintetico"] = False
    assert any("SYN-" in e for e in errores_de(lineas))


def test_prefijo_de_evidencia_invalido_falla() -> None:
    lineas = lineas_validas()
    lineas[0]["ids_evidencia"] = ["XYZ-1"]
    assert any("prefijo" in e for e in errores_de(lineas))


def test_id_duplicado_y_formato_falla() -> None:
    lineas = lineas_validas()
    lineas[1]["id"] = lineas[0]["id"]
    lineas[2]["id"] = "otro"
    errores = errores_de(lineas)
    assert any("duplicado" in e for e in errores)
    assert any("BDEV-NNN" in e for e in errores)


def test_tipo_desconocido_y_consulta_vacia_fallan() -> None:
    lineas = lineas_validas()
    lineas[0]["tipo"] = "otro"
    lineas[1]["consulta"] = ""
    assert len(errores_de(lineas)) >= 2


def test_tipos_estrictos_no_coaccionan() -> None:
    lineas = lineas_validas()
    lineas[0]["sintetico"] = "true"
    assert any("sintetico" in e for e in errores_de(lineas))


def test_ids_ausentes_del_snapshot_fallan(tmp_path: Path) -> None:
    (tmp_path / "noticias.csv").write_text(
        "id_noticia,titulo\nNOT-aaaaaaaaaa,x\n", encoding="utf-8"
    )
    (tmp_path / "indicadores.csv").write_text(
        "pais_iso3,indicador_id,anio,valor\nPAN,FP.CPI.TOTL.ZG,2023,1.5\n", encoding="utf-8"
    )
    (tmp_path / "eventos.geojson").write_text(
        json.dumps({"features": [{"id": "us7000abcd", "properties": {}}]}), encoding="utf-8"
    )
    snapshot = vb.ids_del_snapshot(tmp_path)
    assert snapshot == {"NOT-aaaaaaaaaa", "IND-PAN-FP.CPI.TOTL.ZG-2023", "SIS-us7000abcd"}

    lineas = lineas_validas()
    lineas[0].update(sintetico=False, ids_evidencia=["NOT-aaaaaaaaaa", "IND-PAN-FP.CPI.TOTL.ZG-2023"])
    assert errores_de(lineas, snapshot) == []

    lineas[0]["ids_evidencia"] = ["NOT-bbbbbbbbbb", "SIS-us7000abcd", "SIS-nope"]
    errores = errores_de(lineas, snapshot)
    assert any("NOT-bbbbbbbbbb" in e for e in errores)
    assert any("SIS-nope" in e for e in errores)
    assert not any("SIS-us7000abcd" in e for e in errores)


def test_snapshot_cli_falla_con_ids_ausentes(tmp_path: Path) -> None:
    carpeta = tmp_path / "snap"
    carpeta.mkdir()
    (carpeta / "noticias.csv").write_text("id_noticia\nNOT-aaaaaaaaaa\n", encoding="utf-8")
    lineas = lineas_validas()
    lineas[0].update(sintetico=False, ids_evidencia=["NOT-zzzzzzzzzz"])
    ruta = escribir(tmp_path / "dev.jsonl", lineas)
    assert vb.main(["--ruta", str(ruta), "--snapshot", str(carpeta)]) == 1


def test_referencia_a_conjunto_reservado_se_detecta(tmp_path: Path) -> None:
    # Se arma por partes para que este archivo no sea, él mismo, una referencia.
    plantada = "benchmark_" + "reservado"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mal.py").write_text(f'RUTA = "{plantada}.jsonl"\n', encoding="utf-8")
    (tmp_path / "src" / "bien.py").write_text("RUTA = 'benchmark/benchmark_dev.jsonl'\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "regla.md").write_text(f"No usar {plantada}\n", encoding="utf-8")
    archivos = ["src/mal.py", "src/bien.py", "docs/regla.md"]
    hallazgos = vb.referencias_reservado(archivos, tmp_path)
    assert len(hallazgos) == 1
    assert hallazgos[0].startswith("src/mal.py:1")


def test_ruta_que_nombra_un_conjunto_reservado_se_detecta(tmp_path: Path) -> None:
    nombre = "benchmark/benchmark_" + "test.jsonl"
    (tmp_path / "benchmark").mkdir()
    (tmp_path / nombre).write_text("{}\n", encoding="utf-8")
    assert vb.referencias_reservado([nombre], tmp_path)


def test_el_repo_no_referencia_un_conjunto_reservado() -> None:
    assert vb.referencias_reservado(vb.archivos_versionados()) == []


def test_syn_debe_existir_en_el_fixture_sintetico() -> None:
    lineas = lineas_validas()
    assert errores_de(lineas, sinteticos={"SYN-0001"}) == []
    errores = errores_de(lineas, sinteticos={"SYN-OTRO-0001"})
    assert any("SYN-0001" in e and "sinteticos.csv" in e for e in errores)


def test_snapshot_acepta_syn_del_fixture(tmp_path: Path) -> None:
    carpeta = tmp_path / "snap"
    carpeta.mkdir()
    (carpeta / "noticias.csv").write_text("id_noticia\nNOT-aaaaaaaaaa\n", encoding="utf-8")
    sinteticos = fixture_sinteticos(tmp_path / "sinteticos.csv", "SYN-0001")
    lineas = lineas_validas()
    lineas[0].update(ids_evidencia=["NOT-aaaaaaaaaa", "SYN-0001"])
    ruta = escribir(tmp_path / "dev.jsonl", lineas)
    args = ["--ruta", str(ruta), "--snapshot", str(carpeta), "--sinteticos", str(sinteticos)]
    assert vb.main(args) == 0
    vacio = fixture_sinteticos(tmp_path / "vacio.csv")
    assert vb.main(args[:-1] + [str(vacio)]) == 1


def test_fixture_sintetico_del_repo_cumple_el_contrato() -> None:
    ruta = vb.RUTA_SINTETICOS
    filas = list(csv.DictReader(ruta.open(encoding="utf-8", newline="")))
    assert "SYN-CAN-0001" in {f["id_noticia"] for f in filas}
    columnas = [
        "id_noticia", "titulo", "url", "medio", "idioma", "fecha_publicacion",
        "fecha_deteccion", "fecha_extraccion", "tema", "origen", "alcance_texto",
    ]
    assert list(filas[0]) == columnas
    for f in filas:
        assert f["id_noticia"].startswith("SYN-") and f["origen"] == "sintetico"
        assert f["url"].startswith("https://") and ".example/" in f["url"]


def test_fixture_con_origen_distinto_de_sintetico_falla(tmp_path: Path) -> None:
    ruta = tmp_path / "sinteticos.csv"
    ruta.write_text(
        "id_noticia,origen\nSYN-A-0001,sintetico\nSYN-A-0002,GDELT\n", encoding="utf-8"
    )
    errores = vb.origenes_no_sinteticos(ruta)
    assert len(errores) == 1 and "SYN-A-0002" in errores[0]
    assert vb.origenes_no_sinteticos(vb.RUTA_SINTETICOS) == []


def test_config_benchmark_exige_los_cuatro_tipos() -> None:
    # E1-18 agregó secciones obligatorias (intervalos, sustento, …): se parte de la configuración real y solo se cambian total y tipos.
    resto = {k: v for k, v in cargar_benchmark().model_dump().items() if k not in ("total", "tipos")}
    with pytest.raises(ValueError, match="cuatro tipos"):
        ConfigBenchmark(total=40, tipos={"respuesta_sustentada": 20, "sin_respuesta": 20}, **resto)
    with pytest.raises(ValueError):
        ConfigBenchmark(total=40, tipos={**PROPORCION, "inventado": 0}, **resto)
