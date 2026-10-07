"""E2-03 · D-112 (extiende D-101): el asistente revisa de forma provisional y toda aprobación suya sale rotulada.

El rótulo sale de la bandera ``provisional`` de ``config/revision.yaml``, no de un nombre fijo en ``src/``. Una persona que agrega su fila
sobre el mismo ``CASO-`` pasa a ser la vigente y la exportación deja de decir «provisional»; la fila del asistente queda como historia
rotulada (la tabla ``revisiones`` es de solo agregar).
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from src import embeddings, exportar, interfaz as ui, revision
from src.configuracion import RAIZ, ConfigRevision, cargar_revision
from src.esquemas import RegistroFichasJsonl
from src.revision import Revisiones
from tests import ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba

CFG = cargar_revision()
ASISTENTE = "Asistente (provisional, D-101)"
PERSONA = "Juan Zhou"
MARCA = CFG.textos.marca_provisional


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch, emb):
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)


@pytest.fixture
def rev(tmp_path, emb) -> Revisiones:
    base = h.construir(tmp_path / "senales.duckdb", emb, modalidad="banca")
    t = {"n": 0}

    def ahora() -> datetime:
        t["n"] += 1
        return datetime(2026, 10, 7, 14, 0, tzinfo=UTC) + timedelta(minutes=t["n"])

    return Revisiones(tmp_path / "revision.duckdb", base, ahora=ahora)


def _aprobado_por_el_asistente(rev: Revisiones) -> str:
    caso = rev.abrir(h.G_COMPLETO, "banca", ASISTENTE)
    rev.aceptar(caso.id_caso, ASISTENTE)
    return caso.id_caso


def _exportar(rev: Revisiones, c: str, tmp_path: Path):
    return exportar.exportar_caso(rev, c, tmp_path / "notion", tmp_path / "fichas.jsonl")


def test_la_configuracion_declara_al_asistente_como_provisional_en_las_dos_modalidades() -> None:
    prov = {(r.nombre, r.modalidad, r.rol) for r in CFG.revisores if r.provisional}
    assert prov == {(ASISTENTE, "editorial", "Revisión editorial"), (ASISTENTE, "banca", "Analista")}
    assert not any(r.provisional for r in CFG.revisores if r.nombre == PERSONA)
    assert MARCA == "provisional (D-101)"


def _con(**cambios) -> dict:
    d = yaml.safe_load((RAIZ / "config" / "revision.yaml").read_text(encoding="utf-8"))
    d.update(cambios)
    return d


def test_la_validacion_rechaza_claves_desconocidas_y_configuraciones_incoherentes() -> None:
    ConfigRevision.model_validate(_con())
    malo = _con()
    malo["revisores"] = [{**r, "provisional_x": True} if r["nombre"] == ASISTENTE else r for r in malo["revisores"]]
    with pytest.raises(ValueError):
        ConfigRevision.model_validate(malo)
    solo_editorial = _con()
    solo_editorial["revisores"] = [r for r in solo_editorial["revisores"] if not (r["nombre"] == ASISTENTE and r["modalidad"] == "banca")]
    with pytest.raises(ValueError, match="dos modalidades"):
        ConfigRevision.model_validate(solo_editorial)
    todos = _con()
    todos["revisores"] = [{**r, "provisional": True} for r in todos["revisores"]]
    with pytest.raises(ValueError, match="no provisional"):
        ConfigRevision.model_validate(todos)
    sin_marca = _con()
    sin_marca["textos"] = {k: v for k, v in sin_marca["textos"].items() if k != "marca_provisional"}
    with pytest.raises(ValueError):
        ConfigRevision.model_validate(sin_marca)


def test_la_aprobacion_del_asistente_se_ve_provisional_en_historial_estado_y_pantalla(rev) -> None:
    c = _aprobado_por_el_asistente(rev)
    assert rev.estado(c) == "aprobado como borrador"              # el estado del contrato no cambia
    assert rev.vigente_provisional(c) and rev.estado_rotulado(c) == f"aprobado como borrador · {MARCA}"
    filas = ui.tabla_historial(rev.historial(c), modalidad="banca")
    assert all(MARCA in f["Revisor"] for f in filas) and filas[-1]["Revisor"].startswith(f"{ASISTENTE} (Analista)")


def test_la_cli_muestra_la_marca_en_el_estado_y_en_el_historial(rev, capsys) -> None:
    c = _aprobado_por_el_asistente(rev)
    g = rev.caso(c).id_grupo
    args = ["--revision", str(rev.ruta), "--base", str(rev.base_fichas)]
    assert revision.principal(["--estado", g, "--modalidad", "banca", *args]) == 0
    assert capsys.readouterr().out.strip() == f"aprobado como borrador · {MARCA}"
    assert revision.principal(["--historial", c, *args]) == 0
    lineas = capsys.readouterr().out.strip().splitlines()
    assert len(lineas) == 2 and all(MARCA in l for l in lineas)


def test_la_exportacion_marca_la_aprobacion_provisional_en_markdown_csv_y_jsonl(rev, tmp_path) -> None:
    c = _aprobado_por_el_asistente(rev)
    e = _exportar(rev, c, tmp_path)
    assert f"- Estado de revisión: aprobado como borrador · {MARCA}" in e.markdown
    assert e.markdown.count(MARCA) >= 3                                             # estado + las dos filas del historial
    assert e.fila["Revisor"] == f"{ASISTENTE} · {MARCA}"
    assert e.fila["Estado de revisión"] == "Aprobado como borrador"                 # la opción del select de Notion no se toca
    assert "BORRADOR" in e.markdown
    with (tmp_path / "notion" / "casos_y_evidencias.csv").open(encoding="utf-8", newline="") as f:
        assert MARCA in next(csv.DictReader(f))["Revisor"]
    r = json.loads((tmp_path / "fichas.jsonl").read_text(encoding="utf-8").splitlines()[0])
    RegistroFichasJsonl.model_validate(r)
    assert r["estado_revision"] == "aprobado como borrador" and r["revision_provisional"] is True


def test_una_aprobacion_humana_posterior_es_la_vigente_y_la_exportacion_ya_no_dice_provisional(rev, tmp_path) -> None:
    c = _aprobado_por_el_asistente(rev)
    antes = rev.historial(c)
    rev.reabrir(c, PERSONA, "La persona rehace la aprobación del asistente (C-09)")
    rev.aceptar(c, PERSONA, "Aprobado por una persona")
    assert rev.historial(c)[: len(antes)] == antes                                  # solo agregar: la fila del asistente sigue igual
    assert rev.estado(c) == "aprobado como borrador" and not rev.vigente_provisional(c)
    assert rev.estado_rotulado(c) == "aprobado como borrador"
    e = _exportar(rev, c, tmp_path)
    assert "- Estado de revisión: aprobado como borrador\n" in e.markdown           # el estado vigente ya no es provisional
    assert e.fila["Revisor"] == PERSONA
    filas = [l for l in e.markdown.splitlines() if l.startswith("|") and "Asistente" in l]
    assert len(filas) == 2 and all(MARCA in l for l in filas)                       # la historia del asistente sigue rotulada
    assert not any(MARCA in l for l in e.markdown.splitlines() if l.startswith("|") and PERSONA in l)
    r = json.loads((tmp_path / "fichas.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert r["revision_provisional"] is False


def test_sin_nombres_fijos_en_src() -> None:
    for modulo in ("revision", "exportar", "interfaz", "configuracion"):
        assert "Asistente" not in (RAIZ / "src" / f"{modulo}.py").read_text(encoding="utf-8")


# ============================================================================================ X73 (E1-16): la inferencia cita sus bases


def test_x73_la_inferencia_y_la_hipotesis_muestran_las_afirmaciones_base_en_el_borrador() -> None:
    """CLAUDE.md: una inferencia cita sus afirmaciones base; el texto del borrador (pantalla y exportación) las imprime."""
    afirmaciones = [
        {"id": "A1", "tipo": "hecho", "texto": "Dato oficial.", "citas": [{"id": "IND-X", "campo": "valor"}], "base": []},
        {"id": "A6", "tipo": "inferencia", "texto": "Es posible que importe.", "citas": [], "base": ["A1", "A2"]},
    ]
    textos = ui.secciones_de_paquete({"observaciones": afirmaciones}, {"observaciones": "Observaciones"})[0][1]
    assert "(IND-X · valor)" in textos[0] and "base:" not in textos[0]
    assert textos[1] == "A6 [inferencia] Es posible que importe. (base: A1, A2)"


# ============================================================================================ X72: la marca no se pierde con la configuración


def test_x72_sacar_al_asistente_de_la_configuracion_con_filas_en_el_registro_falla_en_vez_de_perder_la_marca(rev) -> None:
    c = _aprobado_por_el_asistente(rev)
    sin_asistente = ConfigRevision.model_validate(_con(revisores=[r for r in yaml.safe_load((RAIZ / "config" / "revision.yaml").read_text(encoding="utf-8"))["revisores"] if "Asistente" not in r["nombre"]]))
    reabierta = Revisiones(rev.ruta, rev.base_fichas, sin_asistente)
    with pytest.raises(revision.ErrorDeRevision, match="ya no están en config/revision.yaml.*Asistente"):
        reabierta.estado_rotulado(c)
    with pytest.raises(revision.ErrorDeRevision, match="Asistente"):
        reabierta.historial(c)
    assert rev.estado_rotulado(c).endswith(MARCA)  # con la configuración vigente sigue rotulado


def test_x72_una_base_sin_revisiones_o_con_revisores_declarados_abre_sin_error(rev) -> None:
    assert rev.casos() == []
    _aprobado_por_el_asistente(rev)
    assert rev.todas_las_filas()


def test_es_provisional_tiene_una_sola_implementacion() -> None:
    assert ui.es_provisional(ASISTENTE, "banca", CFG) and CFG.es_provisional(ASISTENTE) and not CFG.es_provisional(PERSONA)
    assert not ui.es_provisional("Nadie", None, CFG)
