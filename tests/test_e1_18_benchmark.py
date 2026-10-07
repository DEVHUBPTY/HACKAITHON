"""E1-18: benchmark y métricas con numerador, denominador, IC bootstrap y fallos; muestra de sustento; ejecución offline.

Sin red ni modelo: el consultor es el de ``tests/consulta_fixture.py`` (codificador de bolsa de palabras). La ejecución
que simula la evaluación reservada (``--archivo``) se prueba con ``tests/fixtures/benchmark_ejemplo.jsonl``, sintético.
"""

from __future__ import annotations

import csv
import json
import socket
from pathlib import Path

import pytest

from eval import metricas, run_benchmark, sustento
from src.configuracion import CriterioAB, cargar_benchmark
from tests.consulta_fixture import crear_consultor

FIXTURE = Path(__file__).parent / "fixtures" / "benchmark_ejemplo.jsonl"
CRITERIO = CriterioAB(remuestreos=500, confianza=0.95, semilla=7)


# ------------------------------------------------------------------ proporciones, percentiles y recall con bootstrap


def test_proporcion_con_ic_trae_numerador_denominador_y_dos_intervalos() -> None:
    p = metricas.proporcion_con_ic(7, 10, CRITERIO)
    assert (p["n"], p["de"], p["proporcion"]) == (7, 10, 0.7)
    assert 0.0 <= p["ic95"][0] <= 0.7 <= p["ic95"][1] <= 1.0
    assert 0.0 <= p["ic95_wilson"][0] < p["ic95_wilson"][1] <= 1.0
    assert p["remuestreos"] == 500
    assert metricas.proporcion_con_ic(7, 10, CRITERIO) == p   # semilla fija: reproducible


def test_proporcion_con_denominador_cero_no_inventa_un_valor() -> None:
    p = metricas.proporcion_con_ic(0, 0, CRITERIO)
    assert (p["n"], p["de"], p["proporcion"], p["ic95"], p["ic95_wilson"]) == (0, 0, None, None, None)


def test_el_bootstrap_degenerado_se_avisa_y_wilson_no_lo_es() -> None:
    p = metricas.proporcion_con_ic(10, 10, CRITERIO)
    assert p["ic95"] == [1.0, 1.0] and p["bootstrap_degenerado"] is True
    assert p["ic95_wilson"][0] < 1.0


def test_percentil_con_ic_reporta_n_y_el_punto_exacto() -> None:
    r = metricas.percentil_con_ic(list(range(1, 101)), 50, CRITERIO)
    assert r["n"] == 100 and r["valor"] == 50.5
    assert r["ic95"][0] <= 50.5 <= r["ic95"][1]
    p95 = metricas.percentil_con_ic(list(range(1, 101)), 95, CRITERIO)
    assert p95["valor"] == pytest.approx(95.05) and p95["ic95"][1] <= 100


def test_percentil_sin_datos_es_nulo() -> None:
    assert metricas.percentil_con_ic([], 50, CRITERIO) == {"n": 0, "valor": None, "ic95": None, "remuestreos": 500}


def test_recall_con_ic_cuenta_ids_y_lista_los_fallos() -> None:
    esperados = {"Q1": ["A", "B"], "Q2": ["C"], "Q3": ["D", "E", "F"]}
    hallados = {"Q1": ["A", "B", "X"], "Q2": ["Y"], "Q3": ["D", "F"]}
    r = metricas.recall_con_ic(esperados, hallados, CRITERIO)
    assert (r["por_ids"]["n"], r["por_ids"]["de"]) == (4, 6)
    assert (r["consultas_completas"]["n"], r["consultas_completas"]["de"]) == (1, 3)
    assert r["fallos"] == {"Q2": ["C"], "Q3": ["E"]}


def test_diferencia_de_recall_es_pareada() -> None:
    esperados = {f"Q{i}": ["A"] for i in range(10)}
    a = {f"Q{i}": ["A"] for i in range(10)}
    b = {f"Q{i}": ["A"] if i < 4 else [] for i in range(10)}
    d = metricas.diferencia_recall(esperados, a, b, CRITERIO)
    assert d["diferencia"] == pytest.approx(-0.6) and d["ic95"][1] < 0 and d["n_consultas"] == 10


# ------------------------------------------------------------------ lectura del benchmark (el mismo formato del jurado)


def test_leer_consultas_acepta_el_fixture_y_cuenta_los_tipos() -> None:
    consultas = run_benchmark.leer_consultas(FIXTURE)
    assert len(consultas) == 6 and consultas[0]["id"] == "BDEV-901"
    assert {c["tipo"] for c in consultas} == {"respuesta_sustentada", "contradiccion_ambiguedad", "sin_respuesta", "adversarial"}


def test_leer_consultas_rechaza_lineas_invalidas_con_su_numero(tmp_path: Path) -> None:
    ruta = tmp_path / "malo.jsonl"
    ruta.write_text('{"id": "X-1", "tipo": "inventado", "consulta": "?", "debe_abstenerse": false}\nno es json\n', encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        run_benchmark.leer_consultas(ruta)
    assert "línea 1" in str(exc.value) and "línea 2" in str(exc.value)


# ------------------------------------------------------------------ métricas de las consultas


@pytest.fixture
def evaluado(tmp_path: Path):
    consultor, _ = crear_consultor(tmp_path)
    consultas = run_benchmark.leer_consultas(FIXTURE)
    return run_benchmark.evaluar_consultas(consultor, consultas, CRITERIO)


def test_cada_consulta_queda_registrada_con_su_latencia_y_su_veredicto(evaluado) -> None:
    registros, _ = evaluado
    assert [r["id"] for r in registros] == [f"BDEV-90{i}" for i in range(1, 7)]
    assert all(r["latencia_s"] >= 0 and "respuesta" in r and isinstance(r["correcta"], bool) for r in registros)
    por_id = {r["id"]: r for r in registros}
    assert por_id["BDEV-901"]["respuesta"]["estado"] == "responde" and por_id["BDEV-901"]["correcta"]
    assert por_id["BDEV-904"]["respuesta"]["estado"] == "abstencion" and por_id["BDEV-904"]["correcta"]


def test_abstencion_correcta_e_incorrecta_traen_numerador_denominador_e_ids(evaluado) -> None:
    _, m = evaluado
    ok = m["abstencion_correcta"]["sin_respuesta"]
    assert (ok["n"], ok["de"]) == (2, 2) and ok["fallos"] == []
    todas = m["abstencion_correcta"]["todas_las_que_debian"]
    assert todas["de"] == 3 and "ic95" in todas
    mal = m["abstenciones_incorrectas"]["sustentadas"]
    assert mal["de"] == 2 and mal["n"] == len(mal["ids"])


def test_la_cobertura_de_citas_cuenta_afirmaciones_emitidas_y_cita_valida(evaluado) -> None:
    _, m = evaluado
    c = m["cobertura_de_citas"]["consultas"]
    assert c["de"] >= 3 and c["n"] == c["de"] and c["fallos"] == []
    assert c["proporcion"] == 1.0 and "ic95" in c and "ic95_wilson" in c


def test_una_cita_inexistente_baja_la_cobertura_y_se_nombra() -> None:
    from src.esquemas import Afirmacion, Cita

    buena = Afirmacion(id="A1", tipo="hecho", texto="x", citas=[Cita(id="IND-PAN-SL.UEM.TOTL.ZS-2024", campo="valor")])
    mala = Afirmacion(id="A2", tipo="hecho", texto="y", citas=[Cita(id="IND-PAN-SL.UEM.TOTL.ZS-1900", campo="valor")])
    campo_malo = Afirmacion(id="A3", tipo="hecho", texto="z", citas=[Cita(id="IND-PAN-SL.UEM.TOTL.ZS-2024", campo="inventado")])
    ids = {"IND-PAN-SL.UEM.TOTL.ZS-2024": {"valor"}}
    assert run_benchmark.cita_valida(buena, ids) and not run_benchmark.cita_valida(mala, ids) and not run_benchmark.cita_valida(campo_malo, ids)
    assert not run_benchmark.cita_valida(Afirmacion.model_construct(id="A4", tipo="hecho", texto="s", citas=[], base=[]), ids)


def test_la_latencia_reporta_p50_p95_y_n(evaluado) -> None:
    _, m = evaluado
    lat = m["latencia"]["consulta"]
    assert lat["n"] == 6 and lat["p50"]["valor"] <= lat["p95"]["valor"] and lat["p50"]["ic95"] is not None


def test_las_consultas_no_gastan_tokens_ni_dinero(evaluado) -> None:
    _, m = evaluado
    tc = m["tokens_y_costo"]["consulta"]
    assert tc["tokens_por_consulta"] == 0 and tc["usd_por_consulta"] == 0.0 and "sin LLM" in tc["nota"]


def test_la_busqueda_compara_semantica_y_bm25_con_diferencia_pareada(evaluado) -> None:
    _, m = evaluado
    b = m["busqueda"]
    assert set(b["metodos"]) == {"semantica", "bm25", "sistema"} and b["n_consultas"] == 2
    assert b["semantica_menos_bm25"]["n_consultas"] == 2


# ------------------------------------------------------------------ análisis del umbral sin evaluar sobre lo calibrado


def test_el_analisis_del_umbral_deja_uno_afuera_y_no_toca_la_configuracion(tmp_path: Path) -> None:
    consultor, _ = crear_consultor(tmp_path)
    antes = dict(consultor.cfg.abstencion.umbral_similitud)
    consultas = run_benchmark.leer_consultas(FIXTURE)
    a = run_benchmark.analisis_umbral(consultor, consultas, CRITERIO)
    assert a["metodo"] == "validacion_cruzada_dejando_uno_afuera"
    assert a["umbral_configurado"] == antes["semantica"] and dict(consultor.cfg.abstencion.umbral_similitud) == antes
    assert {"abstencion_correcta_sin_respuesta", "abstenciones_incorrectas_sustentadas"} <= set(a["validacion_cruzada"])
    assert all({"umbral", "sin_respuesta_rechazadas", "sustentadas_rechazadas"} <= set(f) for f in a["sensibilidad"])
    assert "no es" in a["nota"]   # la curva es descriptiva y el texto lo dice


# ------------------------------------------------------------------ muestra de sustento y su validez (revisión humana)


def _pool(n: int) -> list[dict]:
    return [{"origen": "consulta", "id_unidad": f"Q{i}", "id_afirmacion": "A1", "tipo": "hecho", "texto": f"t{i}", "citas": "IND-1 · valor", "evidencia_citada": "e"} for i in range(n)]


def test_la_muestra_es_aleatoria_reproducible_y_de_tamano_fijo() -> None:
    a = sustento.muestrear(_pool(100), 30, 42)
    assert len(a) == 30 and a == sustento.muestrear(_pool(100), 30, 42)
    assert a != sustento.muestrear(_pool(100), 30, 43)
    assert len({x["id_unidad"] for x in a}) == 30


def test_con_menos_afirmaciones_que_la_muestra_se_toman_todas() -> None:
    assert len(sustento.muestrear(_pool(12), 30, 42)) == 12


def test_la_muestra_trae_veredicto_vacio_para_una_persona(tmp_path: Path) -> None:
    ruta = tmp_path / "revision.csv"
    sustento.escribir_muestra(sustento.muestrear(_pool(40), 30, 42), ruta)
    filas = list(csv.DictReader(ruta.open(encoding="utf-8")))
    assert len(filas) == 30 and {f["veredicto"] for f in filas} == {""} and "revisor" in filas[0] and "comentario" in filas[0]
    assert [f["id_muestra"] for f in filas] == [f"S{i:02d}" for i in range(1, 31)]


def _rellenar(ruta: Path, veredictos: list[str]) -> None:
    filas = list(csv.DictReader(ruta.open(encoding="utf-8")))
    for f, v in zip(filas, veredictos, strict=False):
        f["veredicto"] = v
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)


def test_la_validez_sin_revisar_queda_pendiente_y_no_se_inventa(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    sustento.escribir_muestra(sustento.muestrear(_pool(30), 30, 42), ruta)
    r = sustento.validez(sustento.leer_revision(ruta), CRITERIO)
    assert r["estado"] == "pendiente_revision_humana" and r["revisadas"] == 0 and r["de"] == 30 and "validez" not in r


def test_la_validez_solo_cuenta_sustentada_y_reporta_aparte_parcial_y_tipo(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    sustento.escribir_muestra(sustento.muestrear(_pool(30), 30, 42), ruta)
    _rellenar(ruta, ["sustentada"] * 25 + ["parcial"] * 2 + ["tipo incorrecto"] * 2 + ["no sustentada"])
    r = sustento.validez(sustento.leer_revision(ruta), CRITERIO)
    assert r["estado"] == "completa"
    assert (r["sustentadas"]["n"], r["sustentadas"]["de"]) == (25, 30)
    assert r["conteo"] == {"sustentada": 25, "parcial": 2, "no sustentada": 1, "tipo incorrecto": 2}
    assert len(r["fallos"]) == 5 and r["meta"] == 0.9 and r["cumple_meta"] is False
    assert r["sustentadas"]["ic95_wilson"][0] < 25 / 30 < r["sustentadas"]["ic95_wilson"][1]


def test_una_revision_parcial_se_declara_incompleta_y_un_veredicto_invalido_falla(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    sustento.escribir_muestra(sustento.muestrear(_pool(30), 30, 42), ruta)
    _rellenar(ruta, ["sustentada"] * 10)
    r = sustento.validez(sustento.leer_revision(ruta), CRITERIO)
    assert r["estado"] == "incompleta" and r["revisadas"] == 10
    _rellenar(ruta, ["bien"])
    with pytest.raises(ValueError, match="veredicto"):
        sustento.validez(sustento.leer_revision(ruta), CRITERIO)


def test_el_veredicto_acepta_mayusculas_y_la_variante_sin_tilde(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    sustento.escribir_muestra(sustento.muestrear(_pool(30), 30, 42), ruta)
    _rellenar(ruta, ["Sustentada", " PARCIAL ", "tipo incorrecto", "No sustentada"])
    assert sustento.validez(sustento.leer_revision(ruta), CRITERIO)["conteo"]["sustentada"] == 1


def test_regenerar_no_pisa_una_revision_ya_empezada(tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    muestra = sustento.muestrear(_pool(30), 30, 42)
    assert sustento.preparar_muestra(muestra, ruta) == "escrita"
    assert sustento.preparar_muestra(muestra, ruta) == "reescrita_sin_cambios"
    _rellenar(ruta, ["sustentada"])
    assert sustento.preparar_muestra(sustento.muestrear(_pool(40), 30, 1), ruta) == "conservada_con_veredictos"
    assert list(csv.DictReader(ruta.open(encoding="utf-8")))[0]["veredicto"] == "sustentada"


# ------------------------------------------------------------------ el comando completo: offline y sin tocar el repositorio


def test_el_comando_del_jurado_corre_sin_red_y_escribe_solo_en_la_carpeta_pedida(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consultor, _ = crear_consultor(tmp_path)
    monkeypatch.setattr(run_benchmark, "crear_consultor_real", lambda: consultor)

    def sin_red(*_a, **_k):
        raise AssertionError("la evaluación reservada no puede abrir conexiones")

    monkeypatch.setattr(socket, "create_connection", sin_red)
    monkeypatch.setattr(socket.socket, "connect", sin_red)
    salida = tmp_path / "eval"
    assert run_benchmark.main(["--archivo", str(FIXTURE), "--salida", str(salida)]) == 0
    m = json.loads((salida / "metricas.json").read_text(encoding="utf-8"))
    assert m["benchmark"]["n"] == 6 and m["benchmark"]["archivo"] == "benchmark_ejemplo.jsonl" and len(m["benchmark"]["sha256"]) == 64
    assert "/" not in m["benchmark"]["archivo"] and m["abstencion_correcta"]["sin_respuesta"]["de"] == 2
    assert (salida / "consultas.jsonl").exists() and len((salida / "consultas.jsonl").read_text().splitlines()) == 6
    assert m["validez_sustento"]["estado"] == "pendiente_revision_humana"
    assert m["tokens_y_costo"]["borradores"]["estado"] == "no_corrido"
    assert {p.name for p in salida.iterdir()} == {"consultas.jsonl", "metricas.json", "revision_sustento.csv"}   # solo la carpeta pedida, sin copiar el archivo


def test_archivo_exige_salida_y_split_dev_no_la_necesita(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        run_benchmark.main(["--archivo", str(FIXTURE)])
    assert "--salida" in capsys.readouterr().err


def test_la_configuracion_del_benchmark_trae_intervalos_y_muestra() -> None:
    cfg = cargar_benchmark()
    assert cfg.intervalos.remuestreos >= 1000 and cfg.intervalos.confianza == 0.95
    assert cfg.sustento.muestra == 30 and cfg.sustento.meta_validez == 0.9
    assert cfg.sustento.veredictos == ["sustentada", "parcial", "no sustentada", "tipo incorrecto"]
