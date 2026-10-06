"""Pruebas offline de la exploración (E0-09). Sin red; el snapshot sintético sale de conftest."""

from pathlib import Path

import pandas as pd
import pytest

from scripts import explorar
from src.configuracion import RAIZ, ErrorDeConfiguracion, cargar_exploracion
from tests.conftest import DESCRIPCION_SECRETA, IMAGEN_SECRETA


@pytest.fixture
def cfg():
    return cargar_exploracion()


def test_exploracion_yaml_valido(cfg) -> None:
    assert cfg.estadistica.z_95 == 1.96
    assert set(cfg.temas_palabras) == {
        "economia", "logistica", "turismo", "servicios_publicos", "eventos_naturales", "regulacion"
    }


def test_clave_desconocida_en_exploracion_falla(tmp_path: Path) -> None:
    (tmp_path / "exploracion.yaml").write_text("version: 1\nextra: 2\n", encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match=r"exploracion\.yaml"):
        cargar_exploracion(tmp_path)


def test_wilson_es_un_intervalo_valido() -> None:
    lo, hi = explorar.wilson(5, 10, 1.96)
    assert 0 < lo < 0.5 < hi < 1
    lo0, hi0 = explorar.wilson(0, 20, 1.96)
    assert lo0 == 0.0 and 0 < hi0 < 0.2


def test_toda_proporcion_lleva_n_e_intervalo() -> None:
    texto = explorar.prop(3, 12, 1.96)
    assert "3/12" in texto and "IC 95 %" in texto
    assert "sin datos" in explorar.prop(0, 0, 1.96)


def test_coincidencia_por_inicio_de_palabra() -> None:
    assert explorar.coincide("Viaja a Panamá hoy", ["panam"])
    assert not explorar.coincide("Un campo de golf", ["amp"])  # «amp» no debe salir de «campo»


def test_duplicados_agrupa_sufijos_y_contencion(cfg) -> None:
    nt = pd.DataFrame(
        {
            "id_noticia": ["NOT-1", "NOT-2", "NOT-3", "NOT-4"],
            "titulo": [
                "Intensifying El Nino deepens economic risks across LatAm",
                "World Insights : Intensifying El Nino deepens economic risks across LatAm - Xinhua",
                "Intensifying El Nino deepens economic risks across LatAm",
                "Otro titular distinto que no se repite en ningún lado",
            ],
            "medio": ["a.com", "b.com", "c.com", "d.com"],
            "idioma": ["en"] * 4,
            "tema": ["economia"] * 4,
        }
    )
    grupos = explorar.duplicados(nt, cfg)
    assert len(grupos) == 1 and grupos[0]["n"] == 3 and grupos[0]["medios"] == 3


def test_ruido_marca_pero_no_borra(cfg) -> None:
    nt = pd.DataFrame(
        {
            "titulo": ["newsroomamerica . com", "PCB Tourism has grown nearly 7 %", "Minsa adelanta vacunación"],
            "origen": ["GDELT", "GDELT", "TVN RSS"],
        }
    )
    r = explorar.candidatos_ruido(nt, cfg)
    assert len(r) == len(nt)
    assert bool(r.loc[0, "generico"]) and bool(r.loc[1, "falso_panama"])
    assert not bool(r.loc[2, "sospechoso"])  # TVN con término panameño: no es candidato


def test_informe_offline_sobre_snapshot_sintetico(data_sintetica: Path) -> None:
    informe, _ = explorar.generar(data_sintetica.parent)
    assert "¿GDELT trae fecha de publicación?" in informe
    assert "¿El RSS de TVN trae autor o firma?" in informe
    assert "**No.**" in informe
    for seccion in ("Por medio", "Por idioma", "Por país del medio", "Por categoría del RSS"):
        assert seccion in informe
    assert DESCRIPCION_SECRETA not in informe and IMAGEN_SECRETA not in informe
    muestra = data_sintetica.parent / "data" / "exploracion"
    assert (muestra / "candidatos_ruido.csv").exists()


def test_firma_del_rss_no_guarda_nombres(tmp_path: Path, cfg) -> None:
    carpeta = tmp_path / cfg.rss.carpeta_cruda
    carpeta.mkdir(parents=True)
    items = "".join(
        f"<item><title>T{i}</title><link>https://www.tvn-2.com/nacionales/t{i}_1_{i}.html</link>"
        f"<dc:creator>{c}</dc:creator></item>"
        for i, c in enumerate(["Juan Pérez Secreto", "EFE", "Redacción", ""], 1)
    )
    xml = (
        '<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>'
        f"<title>x</title>{items}</channel></rss>"
    )
    (carpeta / "rss_tvn_20261006T120000Z.xml").write_text(xml, encoding="utf-8")
    perfil = explorar.datos_rss_crudo(tmp_path, cfg)
    assert perfil is not None and perfil["n"] == 4
    assert perfil["tipos"]["agencia"] == 1 and perfil["tipos"]["sin firma"] == 1
    assert perfil["tipos"]["persona (nombre no guardado)"] == 1
    assert "Secreto" not in str(perfil)


def test_sin_rss_crudo_se_declara_no_verificable(tmp_path: Path, cfg) -> None:
    assert explorar.datos_rss_crudo(tmp_path, cfg) is None


def test_revision_manual_rechaza_tema_o_id_invalido(data_sintetica: Path, cfg) -> None:
    raiz = data_sintetica.parent
    (raiz / "docs").mkdir()
    (raiz / cfg.revision_manual.archivo).write_text(
        "id_noticia,tema_propuesto,ambiguo,ejemplo,nota\nNOT-nope,inventado,no,no,\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="revisión manual inválida"):
        explorar.seccion_revision(explorar.cargar_datos(raiz), cfg, raiz)


def test_revision_real_cubre_todo_el_snapshot_y_ejemplos_estan_excluidos(cfg) -> None:
    rev = pd.read_csv(RAIZ / cfg.revision_manual.archivo, dtype=str, keep_default_na=False)
    noticias = pd.read_csv(RAIZ / "data" / "processed" / "noticias.csv", dtype=str)
    assert set(rev["id_noticia"]) == set(noticias["id_noticia"])
    assert set(rev["tema_propuesto"]) <= set(cfg.revision_manual.temas_validos)
    lineas = (RAIZ / cfg.salida.ejemplos_excluidos).read_text("utf-8").splitlines()
    excluidos = {l.split("\t")[0] for l in lineas if l and not l.startswith("#")}
    assert set(rev[rev["ejemplo"] == "si"]["id_noticia"]) <= excluidos


def test_escribir_ejemplos_es_idempotente(tmp_path: Path) -> None:
    ruta = tmp_path / "ejemplos.txt"
    explorar.escribir_ejemplos(ruta, ["NOT-1\tTitular uno"])
    explorar.escribir_ejemplos(ruta, ["NOT-1\tTitular uno", "NOT-2\tTitular dos"])
    ids = [l.split("\t")[0] for l in ruta.read_text("utf-8").splitlines() if not l.startswith("#")]
    assert ids == ["NOT-1", "NOT-2"]
