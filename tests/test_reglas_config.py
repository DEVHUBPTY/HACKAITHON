"""Pruebas offline de los YAML de E1-05: reglas v1.3, temas, vínculos, modalidades, salidas y restricciones."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.configuracion import (
    CARPETA_CONFIG,
    ESTADOS,
    RANGOS,
    ErrorDeConfiguracion,
    cargar_modalidad,
    cargar_reglas,
    cargar_restricciones,
    cargar_salidas,
    cargar_temas,
    cargar_vinculos,
    principal,
    validar_coherencia,
)
from src.puntaje import puntaje_total, rango_de

COMPONENTES = {"R": 0.8, "I": 0.6, "U": 0.5, "N": 1.0, "E": 0.4}


def leer(nombre: str) -> dict:
    return yaml.safe_load((CARPETA_CONFIG / f"{nombre}.yaml").read_text("utf-8"))


def escribir(tmp_path: Path, nombre: str, datos: dict) -> Path:
    (tmp_path / f"{nombre}.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp_path


CARGADORES = {
    "reglas_v1.3": cargar_reglas,
    "temas": cargar_temas,
    "vinculos": cargar_vinculos,
    "salidas": cargar_salidas,
    "restricciones": cargar_restricciones,
    "modalidad_editorial": lambda c=None: cargar_modalidad("editorial", c),
}


@pytest.mark.parametrize("nombre", CARGADORES)
def test_yaml_real_carga_y_tiene_version(nombre: str) -> None:
    assert CARGADORES[nombre]().version


@pytest.mark.parametrize("nombre", CARGADORES)
def test_clave_desconocida_en_la_raiz_falla(nombre: str, tmp_path: Path) -> None:
    datos = leer(nombre)
    datos["clave_con_errata"] = 1
    with pytest.raises(ErrorDeConfiguracion, match="clave_con_errata"):
        CARGADORES[nombre](escribir(tmp_path, nombre, datos))


@pytest.mark.parametrize("nombre", CARGADORES)
def test_version_obligatoria(nombre: str, tmp_path: Path) -> None:
    datos = leer(nombre)
    del datos["version"]
    with pytest.raises(ErrorDeConfiguracion, match="version"):
        CARGADORES[nombre](escribir(tmp_path, nombre, datos))


def test_clave_desconocida_anidada_y_tipo_incorrecto(tmp_path: Path) -> None:
    datos = leer("reglas_v1.3")
    datos["urgencia"]["horas_plenos"] = 24  # errata
    with pytest.raises(ErrorDeConfiguracion, match=r"urgencia\.horas_plenos"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    datos = leer("reglas_v1.3")
    datos["agrupacion"]["ventana_dias"] = "7"  # cadena donde va un entero
    with pytest.raises(ErrorDeConfiguracion, match=r"agrupacion\.ventana_dias"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))


def test_trampas_de_yaml(tmp_path: Path) -> None:
    datos = leer("reglas_v1.3")
    datos["version"] = 1.3  # sin comillas YAML lo lee como número
    with pytest.raises(ErrorDeConfiguracion, match="version"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    texto = (CARPETA_CONFIG / "reglas_v1.3.yaml").read_text("utf-8").replace("[EFE, AFP,", "[no, AFP,", 1)
    assert yaml.safe_load(texto)["agencias"][0] is False  # YAML 1.1: no -> False
    (tmp_path / "reglas_v1.3.yaml").write_text(texto, encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match=r"agencias\.0"):
        cargar_reglas(tmp_path)


def test_pesos_que_no_suman_100_se_rechazan(tmp_path: Path) -> None:
    datos = leer("reglas_v1.3")
    datos["pesos"]["R"] = 35
    with pytest.raises(ErrorDeConfiguracion, match="los pesos deben sumar 100"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))


def test_cambiar_un_peso_en_un_yaml_temporal_cambia_p_sin_tocar_codigo(tmp_path: Path) -> None:
    base = cargar_reglas()
    p_base = puntaje_total(COMPONENTES, base)
    assert p_base == pytest.approx(30 * 0.8 + 25 * 0.6 + 20 * 0.5 + 15 * 1.0 + 10 * 0.4)
    datos = leer("reglas_v1.3")
    datos["pesos"]["R"], datos["pesos"]["N"] = 25, 20  # sigue sumando 100
    otras = cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))
    assert puntaje_total(COMPONENTES, otras) != pytest.approx(p_base)
    assert puntaje_total(COMPONENTES, otras) == pytest.approx(25 * 0.8 + 25 * 0.6 + 20 * 0.5 + 20 * 1.0 + 10 * 0.4)


def test_partes_de_r_i_y_e_deben_sumar_uno(tmp_path: Path) -> None:
    for seccion, clave in (("relevancia", "peso_foco"), ("impacto", "peso_subtema"), ("evidencia", "peso_oficial")):
        datos = leer("reglas_v1.3")
        datos[seccion][clave] = 0.9
        with pytest.raises(ErrorDeConfiguracion, match="deben sumar"):
            cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))


def test_rangos_son_los_del_pdf_y_deben_ser_contiguos(tmp_path: Path) -> None:
    reglas = cargar_reglas()
    assert [rango_de(p, reglas) for p in (0, 39.99, 40, 69.99, 70, 100)] == ["bajo", "bajo", "medio", "medio", "alto", "alto"]
    datos = leer("reglas_v1.3")
    datos["rangos"]["medio"]["desde"] = 45
    with pytest.raises(ErrorDeConfiguracion, match="contiguos"):
        cargar_reglas(escribir(tmp_path, "reglas_v1.3", datos))


def test_formulas_de_la_spec_estan_en_el_yaml() -> None:
    r = cargar_reglas()
    assert r.desempate == ["u_desc", "id_asc"]
    assert (r.relevancia.foco_panama_sujeto, r.relevancia.foco_otro_pais_afecta) == (1.0, 0.5)
    ag = r.impacto.alcance_geografico
    assert (ag.nacional, ag.provincial, ag.local, ag.desconocido) == (1.0, 0.6, 0.3, 0.3)   # D-109: desconocido = local
    e = r.evidencia
    assert (e.peso_procedencias, e.peso_oficial, e.peso_identificables, e.tope_procedencias) == (0.5, 0.3, 0.2, 3)
    assert r.agrupacion.ventana_dias == 7
    assert r.urgencia.vacio_sin_publicacion == "urgencia estimada: fecha de publicación desconocida"


def test_geografia_tiene_provincias_comarcas_y_distritos_sin_repetir() -> None:
    g = cargar_reglas().geografia
    assert len(g.provincias) == 10 and len(g.comarcas) >= 3
    for lugar in ("San Miguelito", "La Chorrera", "David", "Penonomé"):
        assert lugar in g.distritos
    todos = g.provincias + g.comarcas + g.distritos
    assert len(todos) == len(set(todos))


def test_temas_son_seis_con_subtemas_y_ejemplos() -> None:
    t = cargar_temas()
    assert set(t.temas) == {"economia", "logistica", "turismo", "servicios_publicos", "eventos_naturales", "regulacion"}
    for tema in t.temas.values():
        assert tema.descripcion and tema.subtemas and len(tema.ejemplos) >= 7
        assert all(s.prototipo for s in tema.subtemas.values())


def test_un_septimo_tema_se_rechaza(tmp_path: Path) -> None:
    datos = leer("temas")
    datos["temas"]["deportes"] = datos["temas"]["turismo"]
    with pytest.raises(ErrorDeConfiguracion, match="cantidad_temas"):
        cargar_temas(escribir(tmp_path, "temas", datos))


def test_ejemplo_real_exige_id_e_ilustrativo_no(tmp_path: Path) -> None:
    datos = leer("temas")
    datos["temas"]["turismo"]["ejemplos"].append({"titulo": "x", "real": True})
    with pytest.raises(ErrorDeConfiguracion, match="ejemplo real lleva id_noticia"):
        cargar_temas(escribir(tmp_path, "temas", datos))


def test_ejemplos_reales_son_exactamente_los_excluidos_de_la_evaluacion() -> None:
    assert validar_coherencia() == []
    reales = {e.id_noticia for t in cargar_temas().temas.values() for e in t.ejemplos if e.real}
    texto = (CARPETA_CONFIG / "ejemplos_excluidos.txt").read_text("utf-8")
    assert reales == {linea.split("\t")[0] for linea in texto.splitlines() if linea and not linea.startswith("#")}


def test_la_coherencia_detecta_un_subtema_sin_alcance_y_un_indicador_inexistente(tmp_path: Path) -> None:
    for nombre in ("fuentes", "reglas_v1.3", "temas", "vinculos", "modalidad_editorial", "restricciones"):
        escribir(tmp_path, nombre, leer(nombre))
    (tmp_path / "ejemplos_excluidos.txt").write_text((CARPETA_CONFIG / "ejemplos_excluidos.txt").read_text("utf-8"), encoding="utf-8")
    assert validar_coherencia(tmp_path) == []
    reglas = leer("reglas_v1.3")
    del reglas["impacto"]["alcance_subtema"]["sismos"]
    escribir(tmp_path, "reglas_v1.3", reglas)
    vinc = leer("vinculos")
    vinc["vinculos"]["empleo"]["id"] = "XX.NO.EXISTE"
    escribir(tmp_path, "vinculos", vinc)
    problemas = " | ".join(validar_coherencia(tmp_path))
    assert "sismos" in problemas and "XX.NO.EXISTE" in problemas


def test_vinculos_apuntan_a_indicadores_de_fuentes_y_a_usgs() -> None:
    v = cargar_vinculos()
    assert v.vinculos["sismos"].fuente == "usgs" and v.vinculos["sismos"].id is None
    assert v.vinculos["inflacion_precios"].id == "FP.CPI.TOTL.ZG"
    assert all(x.limitacion for x in v.vinculos.values())


def test_vinculo_con_relacion_no_declarada_falla(tmp_path: Path) -> None:
    datos = leer("vinculos")
    datos["vinculos"]["empleo"]["relacion"] = "causa"
    with pytest.raises(ErrorDeConfiguracion, match="relaciones no declaradas"):
        cargar_vinculos(escribir(tmp_path, "vinculos", datos))


def test_tabla_de_acciones_tiene_las_9_celdas_y_medio_de_referencia() -> None:
    m = cargar_modalidad("editorial")
    assert len([getattr(getattr(m.tabla_acciones, r), e) for r in RANGOS for e in ESTADOS]) == 9
    assert m.medio_referencia is not None and m.medio_referencia.dominio == "tvn-2.com"


def test_una_celda_que_dice_publicar_se_rechaza(tmp_path: Path) -> None:
    datos = leer("modalidad_editorial")
    datos["tabla_acciones"]["alto"]["suficiente"]["accion"] = "Publicar ya"
    with pytest.raises(ErrorDeConfiguracion, match="publicar"):
        cargar_modalidad("editorial", escribir(tmp_path, "modalidad_editorial", datos))


def test_falta_una_celda_de_la_tabla(tmp_path: Path) -> None:
    datos = leer("modalidad_editorial")
    del datos["tabla_acciones"]["bajo"]["parcial"]
    with pytest.raises(ErrorDeConfiguracion, match=r"tabla_acciones\.bajo\.parcial"):
        cargar_modalidad("editorial", escribir(tmp_path, "modalidad_editorial", datos))


def test_un_archivo_de_modalidad_con_otra_modalidad_falla(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeConfiguracion, match="declara modalidad"):
        cargar_modalidad("banca", escribir(tmp_path, "modalidad_banca", leer("modalidad_editorial")))


def test_guion_marcador_y_palabras_prohibidas_estan_en_yaml() -> None:
    s, r = cargar_salidas().editorial, cargar_restricciones()
    assert (s.guion_segundos_min, s.guion_segundos_max, s.guion_palabras_min, s.guion_palabras_max) == (45, 60, 110, 150)
    assert r.marcador_visual == "[VISUAL: a definir por producción]"
    assert r.leyendas_alcance.titular_metadatos == "basado únicamente en titular/metadatos"
    assert "escándalo" in r.grupos["comunes"]["sensacionalistas"]
    assert "en entrevista con" in r.grupos["editorial"]["entrevistas"]
    assert "las imágenes muestran" in r.grupos["editorial"]["imagenes"]


def test_guion_con_minimo_mayor_al_maximo_falla(tmp_path: Path) -> None:
    datos = leer("salidas")
    datos["editorial"]["guion_palabras_min"] = 200
    with pytest.raises(ErrorDeConfiguracion, match="mínimo supera"):
        cargar_salidas(escribir(tmp_path, "salidas", datos))


def test_cli_validar(capsys: pytest.CaptureFixture[str]) -> None:
    assert principal(["--validar"]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_validar_falla_con_config_rota(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for p in CARPETA_CONFIG.iterdir():
        (tmp_path / p.name).write_text(p.read_text("utf-8"), encoding="utf-8")
    datos = leer("reglas_v1.3")
    datos["pesos"]["R"] = 1
    escribir(tmp_path, "reglas_v1.3", datos)
    assert principal(["--validar", "--config", str(tmp_path)]) == 1
    assert "pesos" in capsys.readouterr().err
