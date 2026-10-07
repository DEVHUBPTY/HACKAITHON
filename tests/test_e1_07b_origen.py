"""E1-07b: procedencia de las etiquetas (humano | asistente_provisional, D-101) y diagnóstico en tres vías."""

import csv
from pathlib import Path
from typing import Any

import pytest

from eval import agrupacion as evagrupacion
from eval import clasificacion as evalclas
from eval import diagnostico_temas as dg
from eval import etiquetar
from eval import origen_etiquetas as oe
from eval import ruido as evruido
from src.configuracion import cargar_temas

COLUMNAS = ("id_noticia", "tema_principal", "ruido", "grupo", "alcance_regional", "origen")


def _csv(ruta: Path, filas: list[dict[str, str]], columnas: tuple[str, ...] = COLUMNAS) -> Path:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    return ruta


MIXTO = [
    {"id_noticia": "NOT-H1", "tema_principal": "economia", "ruido": "ninguno", "grupo": "g-a", "alcance_regional": "si", "origen": "humano"},
    {"id_noticia": "NOT-H2", "tema_principal": "", "ruido": "no_es_panama", "grupo": "", "alcance_regional": "", "origen": "humano"},
    {"id_noticia": "NOT-P1", "tema_principal": "turismo", "ruido": "ninguno", "grupo": "g-p", "alcance_regional": "", "origen": "asistente_provisional"},
    {"id_noticia": "NOT-P2", "tema_principal": "", "ruido": "fuera_de_temas", "grupo": "g-p", "alcance_regional": "", "origen": "asistente_provisional"},
]


# ------------------------------------------------------------------ el lector filtra y valida la procedencia


def test_por_defecto_solo_se_leen_las_etiquetas_humanas(tmp_path: Path) -> None:
    filas = oe.leer_filas(_csv(tmp_path / "e.csv", MIXTO))
    assert [f["id_noticia"] for f in filas] == ["NOT-H1", "NOT-H2"]


def test_se_pueden_pedir_las_provisionales_solas_o_todas(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO)
    assert [f["id_noticia"] for f in oe.leer_filas(ruta, (oe.ASISTENTE_PROVISIONAL,))] == ["NOT-P1", "NOT-P2"]
    assert len(oe.leer_filas(ruta, oe.ORIGENES)) == 4


def test_un_origen_desconocido_se_rechaza_con_el_id(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", [{**MIXTO[0], "origen": "robot"}])
    with pytest.raises(ValueError, match=r"NOT-H1.*robot"):
        oe.leer_filas(ruta)


def test_un_origen_vacio_se_rechaza_si_la_columna_existe(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="origen"):
        oe.leer_filas(_csv(tmp_path / "e.csv", [{**MIXTO[0], "origen": ""}]))


def test_sin_columna_origen_todo_es_humano_pero_no_se_pueden_pedir_provisionales(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO, tuple(c for c in COLUMNAS if c != "origen"))
    assert len(oe.leer_filas(ruta)) == 4
    with pytest.raises(ValueError, match="origen"):
        oe.leer_filas(ruta, (oe.ASISTENTE_PROVISIONAL,))


def test_pedir_un_origen_inexistente_falla() -> None:
    with pytest.raises(ValueError, match="robot"):
        oe.validar_origenes(("robot",))


def test_el_csv_real_marca_todas_sus_filas_y_las_provisionales_son_61() -> None:
    todas = oe.leer_filas(evalclas.ETIQUETAS, oe.ORIGENES)
    cuenta = {o: sum(1 for f in todas if f["origen"] == o) for o in oe.ORIGENES}
    assert cuenta == {oe.HUMANO: 100, oe.ASISTENTE_PROVISIONAL: 61}
    assert len({f["id_noticia"] for f in todas}) == 161


def test_ninguna_etiqueta_usa_un_titular_de_los_ejemplos_excluidos() -> None:
    ids = {f["id_noticia"] for f in oe.leer_filas(evalclas.ETIQUETAS, oe.ORIGENES)}
    assert not ids & evalclas.ids_excluidos()


# ------------------------------------------------------------------ los demás lectores no mezclan provisionales sin pedirlo


def test_leer_etiquetas_de_clasificacion_excluye_provisionales_por_defecto(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO)
    temas = cargar_temas()
    assert set(evalclas.leer_etiquetas(ruta, "tema_principal", temas)) == {"NOT-H1", "NOT-H2"}
    todas = evalclas.leer_etiquetas(ruta, "tema_principal", temas, origenes=oe.ORIGENES)
    assert set(todas) == {"NOT-H1", "NOT-H2", "NOT-P1", "NOT-P2"}


def test_ruido_y_agrupacion_tambien_leen_solo_humanos_por_defecto(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO)
    assert set(evruido.leer_etiquetas(ruta, "ruido")) == {"NOT-H1", "NOT-H2"}
    assert set(evruido.leer_regional(ruta) or {}) == {"NOT-H1", "NOT-H2"}
    assert set(evagrupacion.leer_grupos_humanos(ruta)) == {"NOT-H1", "NOT-H2"}


def test_el_consolidado_de_etiquetar_declara_la_columna_origen() -> None:
    assert "origen" in etiquetar.COLUMNAS_CONSOLIDADO


# ------------------------------------------------------------------ diagnóstico en tres vías


class _Informe(dict):
    pass


def _falso_diagnosticar(monkeypatch: pytest.MonkeyPatch, evaluados: dict[tuple[str, ...], int]) -> list[tuple[str, ...]]:
    llamadas: list[tuple[str, ...]] = []

    def falso(ruta, base, cfg, temas, motores=None, origenes=(oe.HUMANO,)) -> dict[str, Any]:
        llamadas.append(tuple(origenes))
        return {"conjunto": {"evaluados": evaluados[tuple(origenes)], "eventos": 3, "etiquetados_en_csv": 0}, "origenes": list(origenes)}

    monkeypatch.setattr(dg, "diagnosticar", falso)
    return llamadas


def test_el_informe_en_tres_vias_reporta_humano_provisional_y_combinado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h, p = (oe.HUMANO,), (oe.ASISTENTE_PROVISIONAL,)
    llamadas = _falso_diagnosticar(monkeypatch, {h: 63, p: 15, h + p: 78})
    informe = dg.diagnosticar_en_tres_vias(_csv(tmp_path / "e.csv", MIXTO), Path("b.duckdb"), None, None)
    assert set(informe["vias"]) == {"humano", "asistente_provisional", "combinado"}
    assert llamadas == [h, p, (oe.HUMANO, oe.ASISTENTE_PROVISIONAL)]
    assert informe["vias"]["humano"]["usa_etiquetas_provisionales"] is False
    assert informe["vias"]["asistente_provisional"]["usa_etiquetas_provisionales"] is True
    assert informe["vias"]["combinado"]["usa_etiquetas_provisionales"] is True
    assert "D-101" in informe["vias"]["combinado"]["aviso"] and "D-101" in informe["vias"]["asistente_provisional"]["aviso"]
    assert "D-101" not in informe["vias"]["humano"]["aviso"]


def test_una_via_con_pocas_filas_o_eventos_no_se_calcula_y_lo_dice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h, p = (oe.HUMANO,), (oe.ASISTENTE_PROVISIONAL,)
    _falso_diagnosticar(monkeypatch, {h: 63, p: 2, h + p: 65})

    def pocas(ruta, base, cfg, temas, motores=None, origenes=(oe.HUMANO,)):
        if tuple(origenes) == p:
            raise dg.EtiquetasInsuficientes(2, 2)
        return {"conjunto": {"evaluados": 63}}

    monkeypatch.setattr(dg, "diagnosticar", pocas)
    informe = dg.diagnosticar_en_tres_vias(_csv(tmp_path / "e.csv", MIXTO), Path("b.duckdb"), None, None)
    via = informe["vias"]["asistente_provisional"]
    assert via["estado"] == "INSUFICIENTE" and via["evaluados"] == 2 and "diagnostico" not in via
    assert informe["vias"]["humano"]["estado"] == "CALCULADO"


def test_validar_hoja_solo_valida_las_filas_humanas_del_consolidado(tmp_path: Path) -> None:
    """Una fila provisional (otro contrato: no es de una persona ni de la muestra de E1-06) no ensucia ``--validar``."""
    cfg, temas = etiquetar.cargar_etiquetado(), cargar_temas()
    humana = {
        "id_noticia": "NOT-H1", "titulo": "t", "tema_principal": "economia", "tema_secundario": "", "ruido": "ninguno", "grupo": "",
        "alcance_regional": "", "nota": "n", "etiquetado_por": "Javier Acosta", "fecha_etiquetado": "2026-10-06T19:03:29Z",
        "estrato": "no_ruido", "peso_muestreo": "1", "n_etiquetadores": "1", "origen": "humano",
    }
    provisional = {**humana, "id_noticia": "NOT-P1", "etiquetado_por": "Asistente provisional", "origen": "asistente_provisional"}
    ruta = _csv(tmp_path / "c.csv", [humana, provisional], etiquetar.COLUMNAS_CONSOLIDADO)
    assert etiquetar.validar_hoja(ruta, cfg, temas, {"NOT-H1"}) == []


# ================================================================== X47 y observaciones de la revisión independiente (PR #37)

import shutil  # noqa: E402

from src import db, embeddings  # noqa: E402
from tests.motor_falso import MotorFalso, config_de_prueba  # noqa: E402
from tests.test_agrupacion import INFLACION, SISMO, SISMO_AMPLIADO, fila  # noqa: E402,F401
from tests.test_clasificacion import FILAS, _base  # noqa: E402
from tests.test_eval_agrupacion import GRUPOS_HUMANOS, _filas_sinteticas, _reglas_de_prueba  # noqa: E402


def _csv_con_encabezado(tmp_path: Path, nombre: str) -> Path:
    """El CSV real con la columna ``origen`` renombrada a ``nombre`` (como la dejaría una hoja de cálculo o Notion)."""
    ruta = tmp_path / "e.csv"
    texto = evalclas.ETIQUETAS.read_text(encoding="utf-8").replace(",origen\n", f",{nombre}\n", 1)
    assert texto != evalclas.ETIQUETAS.read_text(encoding="utf-8")
    ruta.write_text(texto, encoding="utf-8")
    return ruta


@pytest.mark.parametrize("nombre", ["Origen", " origen", "ORIGEN", "origen ", "  Origen  "])
def test_x47_el_encabezado_se_normaliza_y_las_provisionales_siguen_siendo_61(tmp_path: Path, nombre: str) -> None:
    ruta = _csv_con_encabezado(tmp_path, nombre)
    assert len(oe.leer_filas(ruta)) == 100                                  # antes: 161 (todas «humanas»)
    assert len(oe.leer_filas(ruta, (oe.ASISTENTE_PROVISIONAL,))) == 61


@pytest.mark.parametrize("nombre", ["origen_", "origen-", "orígen", "o rigen", "Origen:", "ORIGEN."])
def test_x47_un_encabezado_parecido_pero_distinto_es_un_error_que_lo_nombra(tmp_path: Path, nombre: str) -> None:
    ruta = _csv_con_encabezado(tmp_path, nombre)
    with pytest.raises(ValueError, match="parece"):
        oe.leer_filas(ruta)


def test_x47_dos_columnas_de_origen_son_un_error(tmp_path: Path) -> None:
    ruta = tmp_path / "e.csv"
    ruta.write_text("id_noticia,origen,Origen\nNOT-1,humano,humano\n", encoding="utf-8")
    with pytest.raises(ValueError, match="más de una vez"):
        oe.leer_filas(ruta)


def test_x47_sin_columna_en_el_consolidado_real_es_un_error_no_todo_humano(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ruta = tmp_path / "etiquetas.csv"
    ruta.write_text("id_noticia,tema_principal,ruido\nNOT-1,economia,ninguno\n", encoding="utf-8")
    assert len(oe.leer_filas(ruta)) == 1                                    # un CSV ajeno (de prueba, anterior) sigue siendo humano
    monkeypatch.setattr(oe, "ETIQUETAS_CONSOLIDADO", ruta)
    with pytest.raises(ValueError, match="origen"):
        oe.leer_filas(ruta)
    with pytest.raises(ValueError, match="origen"):
        evalclas.leer_etiquetas(ruta, "tema_principal", cargar_temas())


def test_un_origen_en_texto_simple_se_acepta_y_uno_invalido_da_un_error_claro(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO)
    assert [f["id_noticia"] for f in oe.leer_filas(ruta, "humano")] == ["NOT-H1", "NOT-H2"]
    with pytest.raises(ValueError, match=r"'robot'"):
        oe.leer_filas(ruta, "robot")


def test_los_valores_de_origen_se_normalizan_igual_en_lector_y_validador(tmp_path: Path) -> None:
    filas = [{**MIXTO[0], "origen": " Humano "}, {**MIXTO[2], "origen": "ASISTENTE_PROVISIONAL"}]
    ruta = _csv(tmp_path / "e.csv", filas)
    assert [f["origen"] for f in oe.leer_filas(ruta, oe.ORIGENES)] == ["humano", "asistente_provisional"]
    assert oe.normalizar_origen(" Asistente_Provisional ") == oe.ASISTENTE_PROVISIONAL


def test_validar_hoja_descarta_una_provisional_aunque_traiga_espacios_o_mayusculas(tmp_path: Path) -> None:
    cfg, temas = etiquetar.cargar_etiquetado(), cargar_temas()
    humana = {
        "id_noticia": "NOT-H1", "titulo": "t", "tema_principal": "economia", "tema_secundario": "", "ruido": "ninguno", "grupo": "",
        "alcance_regional": "", "nota": "n", "etiquetado_por": "Javier Acosta", "fecha_etiquetado": "2026-10-06T19:03:29Z",
        "estrato": "no_ruido", "peso_muestreo": "1", "n_etiquetadores": "1", "origen": "humano",
    }
    provisional = {**humana, "id_noticia": "NOT-P1", "etiquetado_por": "Asistente provisional", "origen": " Asistente_Provisional "}
    ruta = _csv(tmp_path / "c.csv", [humana, provisional], etiquetar.COLUMNAS_CONSOLIDADO)
    assert etiquetar.validar_hoja(ruta, cfg, temas, {"NOT-H1"}) == []


# ------------------------------------------------------------------ --consolidar no borra las provisionales


def test_consolidar_conserva_las_filas_provisionales_del_consolidado_existente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from tests.test_etiquetado import CFG, _base as _base_etq, _fila as _fila_etq

    ruta_base = _base_etq(tmp_path / "s.duckdb")
    muestra = etiquetar.muestra_desde_base(ruta_base, CFG)
    carpeta = tmp_path / CFG.archivos.carpeta_personas
    etiquetar.escribir_csv(carpeta / "ana.csv", [_fila_etq(muestra[0]["id_noticia"], "Ana")])
    consolidado = tmp_path / CFG.archivos.consolidado
    previo = {c: "" for c in etiquetar.COLUMNAS_CONSOLIDADO} | {
        "id_noticia": "NOT-PROV1", "titulo": "t", "tema_principal": "economia", "ruido": "ninguno", "origen": "asistente_provisional",
        "etiquetado_por": "Asistente provisional", "peso_muestreo": "1", "estrato": "no_ruido", "n_etiquetadores": "1",
    }
    etiquetar.escribir_csv(consolidado, [previo], etiquetar.COLUMNAS_CONSOLIDADO)
    assert etiquetar.main(["--consolidar", "--forzar", "--base", str(ruta_base), "--raiz", str(tmp_path)]) == 0
    filas = oe.leer_filas(consolidado, oe.ORIGENES)
    assert {f["id_noticia"]: f["origen"] for f in filas} == {muestra[0]["id_noticia"]: "humano", "NOT-PROV1": "asistente_provisional"}
    assert "provisionales" in capsys.readouterr().out


# ------------------------------------------------------------------ todo informe con provisionales lo declara


def _etiquetas_con_origen(tmp_path: Path) -> Path:
    filas = [{**f, "origen": "humano" if i < 4 else "asistente_provisional"} for i, f in enumerate(
        [
            {"id_noticia": "NOT-1", "tema_principal": "economia", "tema_secundario": "", "ruido": "", "peso_muestreo": "2.5"},
            {"id_noticia": "NOT-2", "tema_principal": "Logística/Canal", "tema_secundario": "", "ruido": "", "peso_muestreo": "2.5"},
            {"id_noticia": "NOT-3", "tema_principal": "turismo", "tema_secundario": "", "ruido": "", "peso_muestreo": "2.5"},
            {"id_noticia": "NOT-4", "tema_principal": "eventos_naturales", "tema_secundario": "", "ruido": "", "peso_muestreo": "2.5"},
            {"id_noticia": "NOT-5", "tema_principal": "regulacion", "tema_secundario": "", "ruido": "", "peso_muestreo": "1"},
            {"id_noticia": "NOT-6", "tema_principal": "servicios_publicos", "tema_secundario": "", "ruido": "", "peso_muestreo": "1"},
            {"id_noticia": "NOT-7", "tema_principal": "", "tema_secundario": "", "ruido": "fuera_de_temas", "peso_muestreo": "1"},
        ]
    )]
    return _csv(tmp_path / "e.csv", filas, ("id_noticia", "tema_principal", "tema_secundario", "ruido", "peso_muestreo", "origen"))


def _evaluar_clasificacion(tmp_path: Path, **kw: Any) -> dict[str, Any]:
    ruta = _etiquetas_con_origen(tmp_path)
    return evalclas.evaluar_etiquetas(ruta, _base(tmp_path, FILAS), "tema_principal", config_de_prueba(), cargar_temas(), ["e5"], {"e5": MotorFalso()}, **kw)


def test_el_informe_de_clasificacion_con_provisionales_se_marca_y_no_mezcla_pesos(tmp_path: Path) -> None:
    r = _evaluar_clasificacion(tmp_path, origenes=oe.ORIGENES)
    assert r["usa_etiquetas_provisionales"] is True and "PROVISIONAL (D-101)" in r["aviso"]
    assert r["conteo"]["etiquetados"] == 7
    assert all("ponderado" not in c for c in r["configuraciones"].values())
    for c in r["pipeline"]["configuraciones"].values():
        assert c["ponderado"]["estado"] == "NO_APLICA" and "peso_muestreo" in c["ponderado"]["motivo"]
    lineas = evalclas.imprimir("Datos reales", r, evalclas.clases_de(cargar_temas()))
    assert "PROVISIONAL (D-101)" in lineas[0]


def test_el_informe_de_clasificacion_solo_humano_no_lleva_marca_y_conserva_los_pesos(tmp_path: Path) -> None:
    r = _evaluar_clasificacion(tmp_path)
    assert r["usa_etiquetas_provisionales"] is False and "aviso" not in r
    assert r["conteo"]["etiquetados"] == 4
    assert all("ponderado" in c for c in r["configuraciones"].values())


def test_el_informe_de_ruido_con_provisionales_empieza_con_la_marca(tmp_path: Path) -> None:
    ruta = _etiquetas_con_origen(tmp_path)
    prov = evruido.leer_etiquetas(ruta, "ruido", oe.ORIGENES)
    lineas = evruido.medir(prov, {i: None for i in prov}, 1.96, origenes=oe.ORIGENES)
    assert "PROVISIONAL (D-101)" in lineas[0]
    regional = evruido.medir_regional({i: False for i in prov}, {i: False for i in prov}, 1.96, origenes=oe.ORIGENES)
    assert "PROVISIONAL (D-101)" in regional[0]
    assert "PROVISIONAL" not in evruido.medir({"NOT-1": None}, {"NOT-1": None}, 1.96)[0]


def test_el_informe_de_agrupacion_con_provisionales_se_marca(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": _filas_sinteticas()})
    monkeypatch.setattr(evagrupacion, "crear", lambda cfg, nombre=None, **kw: embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path))
    filas = [{"id_noticia": i, "grupo": g, "origen": "asistente_provisional" if i in {"NOT-I2", "NOT-X2"} else "humano"} for i, g in GRUPOS_HUMANOS.items()]
    etiquetas = _csv(tmp_path / "e.csv", filas, ("id_noticia", "grupo", "origen"))
    solo = evagrupacion.evaluar(ruta, etiquetas, config_de_prueba(), _reglas_de_prueba(), 1.96)
    con = evagrupacion.evaluar(ruta, etiquetas, config_de_prueba(), _reglas_de_prueba(), 1.96, origenes=oe.ORIGENES)
    assert solo["usa_etiquetas_provisionales"] is False and solo["titulares_etiquetados"] == 8
    assert con["usa_etiquetas_provisionales"] is True and "PROVISIONAL (D-101)" in con["aviso"] and con["titulares_etiquetados"] == 10


# ------------------------------------------------------------------ avisos propios de cada vía, nota de NOT-94e9865b40


def test_el_aviso_de_la_via_provisional_no_dice_que_una_persona_etiqueto() -> None:
    assert "Una sola persona" not in dg.avisos_por_via()["asistente_provisional"]
    assert "Una sola persona" in dg.avisos_por_via()["humano"]
    mixto = dg.avisos_por_via()["combinado"]
    assert "PROVISIONAL (D-101)" in mixto and "100" in mixto and "61" in mixto


def test_la_nota_de_la_audiencia_suntracs_declara_el_cambio_provisional_y_su_motivo() -> None:
    [fila] = [f for f in oe.leer_filas(evalclas.ETIQUETAS, oe.ORIGENES) if f["id_noticia"] == "NOT-94e9865b40"]
    assert fila["tema_principal"] == "servicios_publicos" and fila["ruido"] == "ninguno"
    assert "Cambio del asistente (D-101)" in fila["nota"] and "Enrique Lau" in fila["nota"] and "fuera_de_temas" in fila["nota"]


def test_las_provisionales_con_alcance_regional_llevan_su_ic_en_los_docs() -> None:
    texto = (Path(__file__).resolve().parent.parent / "docs" / "clasificacion.md").read_text(encoding="utf-8")
    assert "Esa fila hay que corregirla" not in texto


# ================================================================== segunda pasada de la revisión independiente (PR #37)


@pytest.mark.parametrize("encabezado", ["id_noticia,origen,origen", "id_noticia,origen,Origen", "id_noticia,origen, ORIGEN "])
def test_x47_dos_columnas_de_origen_son_un_error_tambien_si_se_llaman_igual(tmp_path: Path, encabezado: str) -> None:
    """El lector del CSV se queda con la última columna repetida: antes, la segunda (toda «humano») ocultaba las provisionales."""
    ruta = tmp_path / "e.csv"
    ruta.write_text(f"{encabezado}\nNOT-1,asistente_provisional,humano\nNOT-2,humano,humano\n", encoding="utf-8")
    with pytest.raises(ValueError, match="más de una vez"):
        oe.leer_filas(ruta)
    with pytest.raises(ValueError, match="más de una vez"):
        oe.leer_filas(ruta, oe.ORIGENES)
    with pytest.raises(ValueError, match="más de una vez"):
        oe.tiene_columna_origen(ruta)


@pytest.mark.parametrize("firma", ["Asistente provisional", "asistente  PROVISIONAL", "aprobada provisionalmente por el asistente (D-101)"])
def test_sin_columna_pero_con_una_firma_provisional_falla_en_cualquier_ruta(tmp_path: Path, firma: str) -> None:
    ruta = _csv(tmp_path / "otro.csv", [{**MIXTO[0], "etiquetado_por": "Javier Acosta"}, {**MIXTO[2], "etiquetado_por": firma}],
                ("id_noticia", "tema_principal", "ruido", "etiquetado_por"))
    with pytest.raises(ValueError, match="provisional"):
        oe.leer_filas(ruta)


def test_sin_columna_y_firmas_humanas_sigue_siendo_humano(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "otro.csv", [{**MIXTO[0], "etiquetado_por": "Javier Acosta"}], ("id_noticia", "tema_principal", "ruido", "etiquetado_por"))
    assert len(oe.leer_filas(ruta)) == 1


def test_el_informe_de_ruido_se_marca_por_los_datos_sin_repetir_origenes(tmp_path: Path) -> None:
    ruta = _etiquetas_con_origen(tmp_path)
    prov = evruido.leer_etiquetas(ruta, "ruido", oe.ORIGENES)
    assert "PROVISIONAL (D-101)" in evruido.medir(prov, {i: None for i in prov}, 1.96)[0]
    regional = evruido.leer_regional(ruta, origenes=oe.ORIGENES) or {}
    assert regional == {} or "PROVISIONAL (D-101)" in evruido.medir_regional(regional, dict(regional), 1.96)[0]
    humanas = evruido.leer_etiquetas(ruta, "ruido")
    assert "PROVISIONAL" not in "\n".join(evruido.medir(humanas, {i: None for i in humanas}, 1.96))


def test_el_regional_leido_con_provisionales_marca_el_informe(tmp_path: Path) -> None:
    filas = [{**MIXTO[0]}, {**MIXTO[2], "alcance_regional": "si"}]
    ruta = _csv(tmp_path / "e.csv", filas)
    regional = evruido.leer_regional(ruta, origenes=oe.ORIGENES)
    assert regional is not None and "PROVISIONAL (D-101)" in evruido.medir_regional(regional, dict(regional), 1.96)[0]


def test_los_conteos_del_aviso_combinado_salen_de_los_datos(tmp_path: Path) -> None:
    ruta = _csv(tmp_path / "e.csv", MIXTO)                   # 2 humanas y 2 provisionales
    aviso = dg.avisos_por_via(ruta)["combinado"]
    assert "2 etiquetas de una persona" in aviso and "2 provisionales" in aviso and "100" not in aviso and "61" not in aviso
    real = dg.avisos_por_via()["combinado"]
    assert "100 etiquetas de una persona" in real and "61 provisionales" in real
