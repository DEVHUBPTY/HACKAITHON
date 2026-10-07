"""T04 · Contexto del Banco Mundial por subtema (E1-09, CU-02).

Datos sintéticos mínimos (una cuadrícula chica de indicadores), sin red y sin la base real. La configuración es la real
(``config/vinculos.yaml``): los tests verifican que el módulo la cumple, no una copia.
"""

import json
import re
from typing import Any

import pytest
from pydantic import ValidationError

from src import contexto, db
from src.configuracion import ConfigVinculos, cargar_fuentes, cargar_vinculos

CFG = cargar_vinculos()
IND_INFLACION = "FP.CPI.TOTL.ZG"
IND_EXPORTACIONES = "NE.EXP.GNFS.ZS"
EXTRACCION = "2026-10-06T16:03:14Z"
PALABRA_PROHIBIDA = re.compile(r"\bactual\b", re.IGNORECASE)


def grilla(indicador: str, valores: dict[str, dict[int, float | None]], unidad: str = "% anual") -> list[dict[str, Any]]:
    """Filas de ``indicadores`` para ``valores[pais][anio]``; ``None`` = nulo explícito de la cuadrícula."""
    return [
        {
            "id_indicador": f"IND-{pais}-{indicador}-{anio}",
            "pais_iso3": pais,
            "indicador_id": indicador,
            "anio": anio,
            "valor": valor,
            "unidad": unidad,
            "fuente_url": "https://example.org",
            "fecha_extraccion": EXTRACCION,
            "licencia": "CC BY 4.0",
        }
        for pais, serie in valores.items()
        for anio, valor in serie.items()
    ]


def inflacion_2024_nula() -> list[dict[str, Any]]:
    return grilla(
        IND_INFLACION,
        {
            "PAN": {2019: -0.4, 2020: -1.6, 2021: 1.6, 2022: 2.9, 2023: 1.5, 2024: None},
            "COL": {2023: 11.7, 2024: 6.6},
            "CRI": {2023: 0.5, 2024: None},
            "MEX": {2023: 5.5, 2024: 4.7},
        },
    )


def vincular(subtema: str | None, tema: str, titular: str | None = None, anio_pub: int | None = 2026, ind=None):
    return contexto.vincular_grupo("GRP-0000000001", tema, subtema, titular, anio_pub, ind if ind is not None else inflacion_2024_nula(), CFG)


def por_rol(filas: list[dict[str, Any]], rol: str) -> list[dict[str, Any]]:
    return [f for f in filas if f["rol"] == rol]


# ------------------------------------------------------------------ el dato y su forma


def test_el_dato_trae_pais_anio_unidad_id_tipo_y_limitacion_y_nunca_actual() -> None:
    filas = vincular("inflacion_precios", "economia")
    assert filas
    for f in filas:
        for campo in ("pais_iso3", "indicador_id", "anio", "unidad", "id_evidencia", "tipo", "limitacion", "fecha_extraccion", "regla"):
            assert f[campo] is not None, campo
        assert f["id_evidencia"] == f"IND-{f['pais_iso3']}-{f['indicador_id']}-{f['anio']}"
        assert f["tipo"] == "directa"
        assert "anual" in f["limitacion"].lower()
        assert not PALABRA_PROHIBIDA.search(f["limitacion"])


def test_ningun_texto_de_la_configuracion_dice_actual() -> None:
    textos = [v.limitacion for v in (*CFG.vinculos.values(), *CFG.vinculos_por_tema.values())] + list(CFG.notas.model_dump().values())
    assert not [t for t in textos if PALABRA_PROHIBIDA.search(t)]


def test_la_configuracion_rechaza_la_palabra_actual() -> None:
    datos = CFG.model_dump()
    datos["vinculos"]["empleo"]["limitacion"] = "Refleja el estado actual del empleo."
    with pytest.raises(ValidationError, match="prohibida"):
        ConfigVinculos.model_validate(datos)


def test_la_poblacion_no_se_vincula_sola() -> None:
    datos = CFG.model_dump()
    datos["vinculos"]["empleo"]["id"] = "SP.POP.TOTL"
    with pytest.raises(ValidationError, match="solo de contexto"):
        ConfigVinculos.model_validate(datos)


def test_los_indicadores_vinculados_existen_en_las_fuentes() -> None:
    declarados = set(cargar_fuentes().banco_mundial.indicadores)
    ids = {v.id for v in (*CFG.vinculos.values(), *CFG.vinculos_por_tema.values()) if v.id}
    assert ids <= declarados


def test_la_cifra_del_titular_solo_usa_indicadores_vinculados() -> None:
    ids = {v.id for v in (*CFG.vinculos.values(), *CFG.vinculos_por_tema.values()) if v.id}
    assert set(CFG.cifra_titular.palabras_clave) <= ids


# ------------------------------------------------------------------ sin vínculo


@pytest.mark.parametrize(("tema", "subtema"), [("turismo", "hoteleria"), ("regulacion", "leyes_decretos"), ("turismo", None), (None, None)])
def test_turismo_o_regulacion_devuelven_tema_sin_indicador(tema: str | None, subtema: str | None) -> None:
    (fila,) = vincular(subtema, tema)  # type: ignore[arg-type]
    assert fila["motivo_sin_vinculo"] == "tema_sin_indicador"
    assert fila["id_evidencia"] is None and fila["valor"] is None
    assert fila["regla"].startswith(contexto.REGLA_SIN_ENTRADA)


def test_indicador_sin_ningun_valor_es_sin_dato_en_periodo() -> None:
    ind = grilla(IND_INFLACION, {"PAN": {2023: None, 2024: None}, "COL": {2024: 6.6}})
    (fila,) = vincular("inflacion_precios", "economia", ind=ind)
    assert fila["motivo_sin_vinculo"] == "sin_dato_en_periodo"
    assert fila["id_evidencia"] is None and fila["valor"] is None
    assert fila["regla"].startswith(contexto.REGLA_SIN_DATO)


def test_sismos_no_se_vinculan_con_el_banco_mundial() -> None:
    """Los sismos son de USGS (E1-09b): aquí no se inventa un vínculo del Banco Mundial."""
    assert vincular("sismos", "eventos_naturales") is None


# ------------------------------------------------------------------ último año, comparables y tendencia


def test_con_2024_nulo_se_usa_el_ultimo_anio_no_nulo_y_se_declara() -> None:
    (panama,) = por_rol(vincular("inflacion_precios", "economia"), contexto.ROL_PANAMA)
    assert (panama["anio"], panama["valor"]) == (2023, 1.5)
    assert panama["id_evidencia"] == f"IND-PAN-{IND_INFLACION}-2023"
    assert "2023" in panama["limitacion"] and "último año disponible" in panama["limitacion"]
    assert "2024" in panama["limitacion"]  # el año posterior sin valor también se declara


def test_los_comparables_son_del_mismo_anio_que_panama_y_solo_con_dato() -> None:
    filas = vincular("inflacion_precios", "economia")
    comparables = por_rol(filas, contexto.ROL_COMPARABLE)
    assert {f["anio"] for f in comparables} == {2023}
    assert {f["pais_iso3"] for f in comparables} == {"COL", "CRI", "MEX"}
    sin_dato = grilla(IND_INFLACION, {"PAN": {2023: 1.5}, "COL": {2023: 11.7}, "CRI": {2023: None}})
    assert {f["pais_iso3"] for f in por_rol(vincular("inflacion_precios", "economia", ind=sin_dato), contexto.ROL_COMPARABLE)} == {"COL"}
    assert all(f["valor"] is not None for f in comparables)


def test_la_tendencia_son_los_ultimos_cinco_anios_de_panama_y_los_nulos_siguen_nulos() -> None:
    ind = grilla(IND_INFLACION, {"PAN": {2018: 0.8, 2019: -0.4, 2020: -1.6, 2021: None, 2022: 2.9, 2023: 1.5, 2024: None}})
    tendencia = por_rol(vincular("inflacion_precios", "economia", ind=ind), contexto.ROL_TENDENCIA)
    assert [f["anio"] for f in tendencia] == [2019, 2020, 2021, 2022, 2023]
    assert len(tendencia) == CFG.tendencia_anios
    assert [f["valor"] for f in tendencia] == [-0.4, -1.6, None, 2.9, 1.5]  # nunca se rellena con 0


def test_el_vinculo_por_tema_es_indirecto_y_declara_su_regla() -> None:
    ind = grilla(IND_EXPORTACIONES, {"PAN": {2024: 44.4}, "COL": {2024: 17.0}}, unidad="% del PIB")
    filas = vincular("puertos", "logistica", ind=ind)
    assert {f["tipo"] for f in filas} == {"indirecta"}
    assert {f["regla"] for f in filas} == {f"{contexto.REGLA_TEMA}:logistica"}


# ------------------------------------------------------------------ cifra del titular


def titular_con(cifra: str, anio: str = "") -> str:
    return f"La inflación en Panamá fue de {cifra}{' en ' + anio if anio else ''}, informó el INEC"


def comparacion(titular: str, anio_pub: int | None = 2026) -> dict[str, Any]:
    (panama,) = por_rol(vincular("inflacion_precios", "economia", titular, anio_pub), contexto.ROL_PANAMA)
    return panama


def test_misma_anio_con_cifra_distinta_es_posible_discrepancia_y_no_se_corrige_al_medio() -> None:
    p = comparacion(titular_con("3.2%", "2023"))
    assert p["comparacion_titular"] == CFG.cifra_titular.etiquetas.discrepancia == "posible discrepancia, verificar"
    assert (p["cifra_titular"], p["anio_titular"], p["valor"]) == (3.2, 2023, 1.5)  # ambas se conservan


def test_periodo_distinto_no_es_comparable() -> None:
    assert comparacion(titular_con("3.2%", "2021"))["comparacion_titular"] == "período distinto, no comparable"


def test_titular_sin_anio_publicado_despues_del_dato_es_periodo_distinto() -> None:
    assert comparacion(titular_con("3.2%"), anio_pub=2026)["comparacion_titular"] == "período distinto, no comparable"


def test_titular_sin_anio_publicado_el_mismo_anio_no_se_compara() -> None:
    assert comparacion(titular_con("3.2%"), anio_pub=2023)["comparacion_titular"] is None


def test_cifra_coincidente_con_la_oficial_se_etiqueta_como_tal() -> None:
    assert comparacion(titular_con("1.5%", "2023"))["comparacion_titular"] == CFG.cifra_titular.etiquetas.coincide


def test_x17_un_verbo_de_baja_conserva_el_signo_negativo_de_la_cifra() -> None:
    """X17: «El PIB cae 2 % en 2024» es -2, no +2; contra la oficial -2.0 coincide."""
    assert contexto.extraer_cifra_titular("El PIB cae 2 % en 2024", "NY.GDP.MKTP.KD.ZG", CFG) == (-2.0, 2024)
    ind = grilla("NY.GDP.MKTP.KD.ZG", {"PAN": {2024: -2.0}})
    (p,) = por_rol(vincular("crecimiento_pib", "economia", "El PIB cae 2 % en 2024", ind=ind), contexto.ROL_PANAMA)
    assert p["cifra_titular"] == -2.0
    assert p["comparacion_titular"] == CFG.cifra_titular.etiquetas.coincide


def test_x17_un_verbo_de_alza_no_cambia_el_signo() -> None:
    assert contexto.extraer_cifra_titular("El PIB sube 2 % en 2024", "NY.GDP.MKTP.KD.ZG", CFG) == (2.0, 2024)


def test_x17_un_signo_explicito_no_se_invierte_dos_veces() -> None:
    assert contexto.extraer_cifra_titular("El PIB cae -2 % en 2024", "NY.GDP.MKTP.KD.ZG", CFG) == (-2.0, 2024)


@pytest.mark.parametrize("palabra", ["actual", "actualmente", "actualidad", "actuales"])
def test_la_palabra_prohibida_incluye_sus_formas_derivadas(palabra: str) -> None:
    fila = {"id_grupo": "GRP-1", "limitacion": f"Dato {palabra} del indicador.", "comparacion_titular": None, "regla": "r", "motivo_sin_vinculo": None}
    with pytest.raises(ValueError, match="prohibida"):
        contexto.verificar_texto([fila], CFG)
    datos = CFG.model_dump()
    datos["vinculos"]["empleo"]["limitacion"] = f"Refleja la situación {palabra}."
    with pytest.raises(ValidationError, match="prohibida"):
        ConfigVinculos.model_validate(datos)


@pytest.mark.parametrize(
    "titular",
    [
        "Panamá presenta presupuesto y nivel de deuda",  # sin cifra
        "La deuda equivale al 60% del PIB y la inflación preocupa",  # el % no sigue a la palabra clave
        "Inflación de 2.1% y 3.4% según dos fuentes",  # dos cifras: ambiguo
        "La inflación se ubicó en 2.1 por ciento",  # sin % no se extrae
    ],
)
def test_la_extraccion_de_la_cifra_es_conservadora(titular: str) -> None:
    assert contexto.extraer_cifra_titular(titular, IND_INFLACION, CFG) is None


def test_la_cifra_de_otro_indicador_no_se_compara_con_este() -> None:
    assert contexto.extraer_cifra_titular("El PIB crece 3.1% en 2023", IND_INFLACION, CFG) is None
    assert contexto.extraer_cifra_titular("El PIB crece 3.1% en 2023", "NY.GDP.MKTP.KD.ZG", CFG) == (3.1, 2023)


# ------------------------------------------------------------------ regla y subtema


def test_cada_vinculo_guarda_la_regla_que_lo_genero() -> None:
    casos = [
        vincular("inflacion_precios", "economia"),                       # por subtema
        vincular("puertos", "logistica", ind=grilla(IND_EXPORTACIONES, {"PAN": {2024: 44.4}})),  # por tema
        vincular("hoteleria", "turismo"),                                # sin entrada
        vincular("empleo", "economia", ind=[]),                          # sin dato
    ]
    reglas = [{f["regla"] for f in filas} for filas in casos]
    assert reglas == [
        {"vinculo_por_subtema:inflacion_precios"},
        {"vinculo_por_tema:logistica"},
        {"sin_vinculo_en_tabla:turismo/hoteleria"},
        {f"sin_dato_en_periodo:{'SL.UEM.TOTL.ZS'}"},
    ]


def test_el_subtema_gana_por_votos_luego_por_similitud_y_es_determinista() -> None:
    assert contexto.subtema_del_grupo([]) is None
    assert contexto.subtema_del_grupo([("empleo", 0.5), ("crecimiento_pib", 0.4), ("empleo", 0.3)]) == "empleo"
    assert contexto.subtema_del_grupo([("empleo", 0.3), ("crecimiento_pib", 0.6)]) == "crecimiento_pib"
    assert contexto.subtema_del_grupo([("b", 0.5), ("a", 0.5)]) == "a"


# ------------------------------------------------------------------ base y reporte


def _noticia(id_noticia: str, titulo: str, publicacion: str) -> dict[str, Any]:
    return {
        "id_noticia": id_noticia,
        "titulo": titulo,
        "url": f"https://x.test/{id_noticia}",
        "url_canonica": f"https://x.test/{id_noticia}",
        "medio": "x.test",
        "tipo_firma": "sin_firma",
        "fecha_publicacion": publicacion,
        "id_grupo": None,
    }


def _grupo(id_grupo: str, id_noticia: str, titular: str, tema: str) -> dict[str, Any]:
    return {
        "id_grupo": id_grupo,
        "titular_central": titular,
        "id_noticia_central": id_noticia,
        "n_titulares": 1,
        "n_medios": 1,
        "n_procedencias": 1,
        "ids_noticia": id_noticia,
        "estimado": True,
        "tema_clasificado": tema,
    }


def _sim(id_noticia: str, tema: str, subtema: str) -> dict[str, Any]:
    return {"id_noticia": id_noticia, "metodo": "B", "tema": tema, "similitud": 0.7, "subtema": subtema}


@pytest.fixture
def base(tmp_path):
    titular = titular_con("3.2%", "2023")
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(
        ruta,
        {
            "noticias": [
                _noticia("NOT-1", titular, "2026-09-01T00:00:00Z"),
                _noticia("NOT-2", "Hoteles reportan alta ocupación", "2026-09-02T00:00:00Z"),
                _noticia("NOT-3", "Sismo de magnitud 4 sacude Chiriquí", "2026-09-03T00:00:00Z"),
            ],
            "grupos": [
                _grupo("GRP-1", "NOT-1", titular, "economia"),
                _grupo("GRP-2", "NOT-2", "Hoteles reportan alta ocupación", "turismo"),
                _grupo("GRP-3", "NOT-3", "Sismo de magnitud 4 sacude Chiriquí", "eventos_naturales"),
            ],
            "similitud_tema": [
                _sim("NOT-1", "economia", "inflacion_precios"),
                _sim("NOT-2", "turismo", "hoteleria"),
                _sim("NOT-3", "eventos_naturales", "sismos"),
            ],
            "indicadores": inflacion_2024_nula(),
        },
    )
    con = db.conectar(ruta)
    con.execute("UPDATE noticias SET id_grupo = 'GRP-' || substr(id_noticia, 5)")
    con.close()
    return ruta


def _leer(ruta) -> list[dict[str, Any]]:
    con = db.conectar(ruta, solo_lectura=True)
    try:
        return db.leer_tabla(con, "vinculos", "id_grupo, rol, pais_iso3, anio")
    finally:
        con.close()


def test_la_base_guarda_vinculos_con_su_regla_y_delega_los_sismos(base) -> None:
    filas, delegados, total = contexto.aplicar_a_base(base, CFG)
    assert (total, delegados) == (3, ["GRP-3"])
    guardadas = _leer(base)
    assert len(guardadas) == len(filas)
    assert {f["id_grupo"] for f in guardadas} == {"GRP-1", "GRP-2"}
    assert all(f["regla"] and f["fuente"] == "indicador" for f in guardadas)
    assert [f["motivo_sin_vinculo"] for f in guardadas if f["id_grupo"] == "GRP-2"] == ["tema_sin_indicador"]
    (panama,) = [f for f in guardadas if f["id_grupo"] == "GRP-1" and f["rol"] == "panama"]
    assert (panama["subtema"], panama["anio"], panama["comparacion_titular"]) == ("inflacion_precios", 2023, "posible discrepancia, verificar")


def test_volver_a_correr_reemplaza_sus_filas_y_respeta_las_de_usgs(base) -> None:
    contexto.aplicar_a_base(base, CFG)
    con = db.conectar(base)
    db.insertar(con, "vinculos", [{"id_grupo": "GRP-3", "id_evidencia": "SIS-us1", "tipo": "evento", "regla": "ventana", "fuente": "usgs", "rol": "evento"}])
    con.close()
    primera = len(_leer(base))
    contexto.aplicar_a_base(base, CFG)
    segunda = _leer(base)
    assert len(segunda) == primera
    assert [f["id_evidencia"] for f in segunda if f["fuente"] == "usgs"] == ["SIS-us1"]


def test_el_reporte_cuenta_con_y_sin_vinculo_por_motivo(base, tmp_path) -> None:
    ruta = tmp_path / "reporte_vinculos.json"
    r = contexto.ejecutar(base, ruta)
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert guardado == r
    assert (r["grupos_en_base"], r["grupos_del_banco_mundial"], r["grupos_delegados_a_otra_fuente"]) == (3, 2, 1)
    assert (r["con_vinculo"]["n"], r["sin_vinculo"]["n"]) == (1, 1)
    assert r["con_vinculo"]["ic95"] is not None  # toda proporción con n e IC
    assert r["sin_vinculo_por_motivo"] == {"tema_sin_indicador": 1}
    assert r["comparacion_con_cifra_del_titular"] == {"posible discrepancia, verificar": 1}
