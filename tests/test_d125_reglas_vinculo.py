"""D-125: el reto define 6 temas y ningún subtema. Los vínculos oficiales los dispara una regla interna (tema + términos).

Datos sintéticos y la configuración real (``config/vinculos.yaml``): se prueba que el módulo la cumple, no una copia.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src import contexto, db
from src.configuracion import ConfigVinculos, ReglaVinculo, cargar_temas, cargar_vinculos

CFG = cargar_vinculos()
REGLAS = CFG.reglas_vinculo


def disparadas(tema: str | None, *titulares: str) -> dict[str, str]:
    return contexto.reglas_disparadas(list(titulares), tema, CFG)


# ------------------------------------------------------------------ la regla exige el tema y un término


@pytest.mark.parametrize(
    ("tema", "titular", "regla"),
    [
        ("economia", "El PIB de Panamá crece según el último dato", "pib"),
        ("economia", "Inflación de septiembre", "inflacion"),
        ("economia", "Sube el costo de la vida en Panamá", "inflacion"),
        ("economia", "¿Cómo se fija el precio del combustible en Panamá?", "inflacion"),
        ("economia", "Aumenta el desempleo en el país", "empleo"),
        ("economia", "Exportaciones de banano superan los $17 millones", "comercio_exterior"),
        ("economia", "Fitch mantiene el grado de inversión de Panamá", "banca"),
        ("economia", "El sistema bancario mantiene su cartera estable", "banca"),
        ("servicios_publicos", "Falla el INTERNET en la capital", "telecomunicaciones"),
        ("eventos_naturales", "Sismo de 4,5 sacude Chiriquí", "sismos"),
        ("eventos_naturales", "Fuerte Sísmica en el Darién", "sismos"),
    ],
)
def test_una_regla_se_dispara_con_su_tema_y_un_termino_sin_importar_acentos_ni_mayusculas(tema: str, titular: str, regla: str) -> None:
    assert list(disparadas(tema, titular)) == [regla]


@pytest.mark.parametrize(
    "titular",
    ["Sube el precio del cobre", "Precios del oro récord", "Precio de la vivienda sube", "El banco mundial presta fondos"],
)
def test_las_palabras_sueltas_ambiguas_no_disparan_una_regla(titular: str) -> None:
    assert disparadas("economia", titular) == {}              # «precio(s)» y «banco» sueltos no son términos (X41, X53)


def test_el_termino_es_palabra_completa() -> None:
    assert disparadas("economia", "Hay empleados en huelga") == {}
    assert disparadas("economia", "La internet de banda ancha") == {}                 # internet es de servicios públicos, no de economía
    assert disparadas("servicios_publicos", "Llegan las internetes") == {}


@pytest.mark.parametrize("tema", ["turismo", "logistica", "regulacion", "servicios_publicos", "sin_tema", None])
def test_el_mismo_titular_no_dispara_la_regla_de_otro_tema(tema: str | None) -> None:
    assert disparadas(tema, "Inflación y PIB", "Fuerte sismo") == {}


def test_el_termino_que_disparo_se_conserva_para_explicar_la_regla() -> None:
    assert disparadas("economia", "Panamá reporta inflación estable") == {"inflacion": "inflacion"}
    assert disparadas("economia", "Crece el producto interno bruto") == {"pib": "producto interno bruto"}


def test_la_regla_mira_todos_los_titulares_del_grupo() -> None:
    assert list(disparadas("economia", "Sin pistas aquí", "Pero la inflación sube")) == ["inflacion"]


# ------------------------------------------------------------------ exclusiones y patrones


def _regla(**cambios: Any) -> ReglaVinculo:
    base = REGLAS["empleo"].model_dump() | {"terminos": ["obra"], "exclusiones": [], "patrones": []}
    return ReglaVinculo.model_validate(base | cambios)


def test_una_exclusion_en_el_titular_impide_la_regla_solo_en_ese_titular() -> None:
    r = _regla(exclusiones=["juez"])
    assert contexto.termino_que_dispara(["Juez imputa a funcionarios por la obra"], r) is None
    assert contexto.termino_que_dispara(["Juez imputa a funcionarios por la obra", "Avanza la obra"], r) == "obra"


def test_un_patron_dispara_la_regla_sobre_texto_sin_tildes() -> None:
    r = _regla(terminos=["xx"], patrones=[r"(?<!\w)construccion\s+de\s+(?:un\s+)?acueductos?(?!\w)"])
    assert contexto.termino_que_dispara(["Construcción de un acueducto avanza"], r) is not None
    assert contexto.termino_que_dispara(["Reparan el acueducto"], r) is None


def test_la_configuracion_rechaza_reglas_mal_formadas() -> None:
    datos = CFG.model_dump()
    for cambio, mensaje in (
        ({"terminos": []}, "terminos"),
        ({"terminos": ["  "]}, "no vacías"),
        ({"patrones": ["("]}, "expresión regular"),
        ({"clave_inventada": 1}, "clave_inventada"),
    ):
        malo = {**datos, "reglas_vinculo": {**datos["reglas_vinculo"], "empleo": {**datos["reglas_vinculo"]["empleo"], **cambio}}}
        with pytest.raises(ValidationError, match=mensaje):
            ConfigVinculos.model_validate(malo)


def test_el_yaml_ya_no_admite_el_bloque_de_subtemas() -> None:
    datos = CFG.model_dump() | {"subtema": {"criterios": ["lexico"]}}
    with pytest.raises(ValidationError, match="subtema"):
        ConfigVinculos.model_validate(datos)


# ------------------------------------------------------------------ elegir el vínculo


def test_una_regla_disparada_elige_su_vinculo_y_escribe_su_texto() -> None:
    vinculo, regla, motivo, nombre = contexto.elegir_vinculo("economia", {"inflacion": "inflacion"}, CFG)
    assert (vinculo, motivo, nombre) == (REGLAS["inflacion"], None, "inflacion")
    assert regla == "regla inflacion: término «inflacion» en el titular"


def test_sin_regla_el_vinculo_es_el_del_tema_o_tema_sin_indicador() -> None:
    vinculo, regla, motivo, nombre = contexto.elegir_vinculo("logistica", {}, CFG)
    assert (vinculo, regla, motivo, nombre) == (CFG.vinculos_por_tema["logistica"], "vinculo_por_tema:logistica", None, None)
    vinculo, regla, motivo, nombre = contexto.elegir_vinculo("turismo", {}, CFG)
    assert (vinculo, motivo, nombre) == (None, "tema_sin_indicador", None) and regla == "sin_vinculo_en_tabla:turismo"
    assert contexto.elegir_vinculo(None, {}, CFG)[1] == "sin_vinculo_en_tabla:sin_tema"


def test_dos_reglas_del_mismo_tema_son_ambiguas_y_no_se_elige_ninguna_ni_el_vinculo_por_tema() -> None:
    d = disparadas("economia", "El PIB y la inflación de septiembre")
    assert sorted(d) == ["inflacion", "pib"]
    vinculo, regla, motivo, nombre = contexto.elegir_vinculo("economia", d, CFG)
    assert (vinculo, motivo, nombre) == (None, "candidatos_ambiguos", None)
    assert "inflacion, pib" in regla and "economia" in regla
    (fila,) = contexto.vincular_grupo("GRP-1", "economia", d, "El PIB y la inflación", 2024, [], CFG)
    assert fila["motivo_sin_vinculo"] == "candidatos_ambiguos" and fila["id_evidencia"] is None and fila["valor"] is None
    assert fila["subtema"] is None and fila["criterio_subtema"] is None


def test_el_motivo_ambiguo_esta_declarado_en_la_configuracion() -> None:
    assert contexto.MOTIVO_AMBIGUO in CFG.motivos_sin_vinculo


def test_las_filas_de_vinculo_ya_no_guardan_subtema() -> None:
    ind = [{"id_indicador": f"IND-PAN-FP.CPI.TOTL.ZG-{a}", "pais_iso3": "PAN", "indicador_id": "FP.CPI.TOTL.ZG", "anio": a, "valor": 1.0 + a % 7,
            "unidad": "% anual", "fuente_url": "u", "fecha_extraccion": "2026-10-06T00:00:00Z", "licencia": "x"} for a in range(2019, 2025)]
    filas = contexto.vincular_grupo("GRP-1", "economia", {"inflacion": "inflacion"}, "La inflación", 2024, ind, CFG)
    assert filas and {f["subtema"] for f in filas} == {None} and {f["criterio_subtema"] for f in filas} == {None}
    assert {f["regla"] for f in filas} == {"regla inflacion: término «inflacion» en el titular"}


@pytest.mark.parametrize("regla", ["sismos", "banca"])
def test_las_reglas_de_usgs_y_sbp_se_delegan_al_modulo_de_su_fuente(regla: str) -> None:
    tema = REGLAS[regla].tema
    assert contexto.vincular_grupo("GRP-1", tema, {regla: regla}, "t", 2024, [], CFG) is None


# ------------------------------------------------------------------ sobre la base


def _base(tmp_path: Path) -> Path:
    ruta = tmp_path / "senales.duckdb"
    base = {"url": "u", "url_canonica": "u", "medio": "m", "tipo_firma": "sin firma", "es_ruido": False, "fecha_publicacion": "2024-05-10T15:00:00Z"}
    casos = {
        "GRP-pib": ("economia", ["El PIB crece 2 %", "Crece el producto interno"]),
        "GRP-ambiguo": ("economia", ["El PIB y la inflación"]),
        "GRP-otro-tema": ("turismo", ["La inflación no es de turismo"]),
        "GRP-canal": ("logistica", ["El Canal reduce tránsitos"]),
        "GRP-sismo": ("eventos_naturales", ["Sismo sacude Chiriquí"]),
        "GRP-vacio": ("sin_tema", ["Sin tema pero con inflación"]),
    }
    noticias, grupos = [], []
    for g, (tema, titulares) in casos.items():
        ids = []
        for i, t in enumerate(titulares):
            nid = f"NOT-{g}-{i}"
            ids.append(nid)
            noticias.append({**base, "titulo": t, "titulo_limpio": t, "id_noticia": nid, "id_grupo": g})
        grupos.append({"id_grupo": g, "titular_central": titulares[0], "id_noticia_central": ids[0], "n_titulares": len(ids), "n_medios": 1,
                       "n_procedencias": 1, "ids_noticia": ",".join(ids), "estimado": True, "tema_clasificado": tema})
    db.guardar_todo(ruta, {"noticias": noticias, "grupos": grupos})
    return ruta


def test_leer_grupos_trae_las_reglas_de_cada_grupo_sin_necesitar_embeddings_ni_similitud_tema(tmp_path: Path) -> None:
    con = db.conectar(_base(tmp_path), solo_lectura=True)
    try:
        grupos = {g["id_grupo"]: g for g in contexto.leer_grupos(con)}
    finally:
        con.close()
    assert {k: sorted(v["reglas"]) for k, v in grupos.items()} == {
        "GRP-pib": ["pib"], "GRP-ambiguo": ["inflacion", "pib"], "GRP-otro-tema": [], "GRP-canal": [], "GRP-sismo": ["sismos"], "GRP-vacio": [],
    }
    assert all("subtema" not in g and "criterio_subtema" not in g for g in grupos.values())


def test_la_base_guarda_los_vinculos_por_regla_y_ninguna_columna_de_subtema(tmp_path: Path) -> None:
    ruta = _base(tmp_path)
    filas, delegados, total = contexto.aplicar_a_base(ruta, CFG)
    assert total == 6 and delegados == ["GRP-sismo"]
    por_grupo: dict[str, list[dict[str, Any]]] = {}
    for f in filas:
        por_grupo.setdefault(f["id_grupo"], []).append(f)
    assert {f["motivo_sin_vinculo"] for f in por_grupo["GRP-pib"]} == {"sin_dato_en_periodo"}      # no hay indicadores en la base sintética
    assert [f["motivo_sin_vinculo"] for f in por_grupo["GRP-ambiguo"]] == ["candidatos_ambiguos"]
    assert [f["motivo_sin_vinculo"] for f in por_grupo["GRP-otro-tema"]] == ["tema_sin_indicador"]
    assert [f["regla"] for f in por_grupo["GRP-canal"]] == ["sin_dato_en_periodo:NE.EXP.GNFS.ZS"]  # el vínculo por tema de logística
    assert [f["motivo_sin_vinculo"] for f in por_grupo["GRP-vacio"]] == ["tema_sin_indicador"]
    assert all(f["subtema"] is None and f["criterio_subtema"] is None for f in filas)


def test_el_reporte_de_vinculos_ya_no_cuenta_por_subtema(tmp_path: Path) -> None:
    r = contexto.ejecutar(_base(tmp_path), tmp_path / "reporte.json")
    assert "con_vinculo_por_subtema" not in r
    assert {"con_vinculo_por_relacion", "con_vinculo_por_indicador", "sin_vinculo_por_motivo"} <= set(r)
    assert r["sin_vinculo_por_motivo"]["candidatos_ambiguos"] == 1


def test_el_catalogo_de_temas_no_tiene_subtemas_y_las_reglas_apuntan_a_temas_reales() -> None:
    temas = cargar_temas().temas
    assert len(temas) == 6 and not any(hasattr(t, "subtemas") for t in temas.values())
    assert {r.tema for r in REGLAS.values()} <= set(temas)
