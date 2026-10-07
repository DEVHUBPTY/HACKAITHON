"""E2-02 · Boletín de entorno bancario (docs/salidas.md §2): mismo flujo de dos pasos que E1-12, con un proveedor guionado.

Nunca se llama a un LLM real. Lo que se prueba: qué se genera según la acción, los campos exactos del boletín, que observaciones e
hipótesis de impacto no se mezclan, el léxico bancario (D-54), el horizonte y los sectores por regla, el aviso fijo y la leyenda (D-51).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from src.configuracion import CARPETA_CONFIG, cargar_generacion, cargar_modalidad, cargar_restricciones, cargar_salidas, cargar_temas
from src.esquemas import BoletinBanca
from src.generacion import Generador, cargar_prompt, generar, principal
from src.validador import Contexto, contar_palabras, validar_paquete
from tests.generacion_ayuda import AFIRMACIONES_BANCA, BOLETIN, ID_LLUVIAS, _o, ficha_banca, modificada, proveedor_banca

BANCA = cargar_modalidad("banca")
RESTRICCIONES = cargar_restricciones()


def boletin(**cambios: Any) -> BoletinBanca:
    p = generar(ficha_banca(**cambios), proveedor_banca()).paquete
    assert isinstance(p, BoletinBanca)
    return p


def ctx_banca(**cambios: Any) -> Contexto:
    return Contexto(ficha_banca(**cambios), BANCA.grupos_restricciones)


def reglas_registradas(seccion: str) -> set[str]:
    """Reglas que rechazaron algo de ``seccion`` según ``outputs/rechazos.jsonl`` (aquí, el de la carpeta temporal de la prueba)."""
    ruta = Path(os.environ["RECHAZOS_JSONL"])
    lineas = [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()] if ruta.exists() else []
    return {x["regla"] for x in lineas if x["evento"] == "rechazo" and x["seccion"] == seccion}


# ============================================================================================ qué se genera (D-42 en banca)


def test_la_banca_genera_un_boletin_valido_con_los_campos_de_salidas_md() -> None:
    r = generar(ficha_banca(), prov := proveedor_banca())
    p = r.paquete
    assert r.tipo == "boletin" and isinstance(p, BoletinBanca)
    assert p.observaciones and p.hipotesis_impacto and len(p.preguntas) == 3 and p.vacios == []
    assert prov.claves == ["afirmaciones", "observaciones"]  # paso 1 y una sola llamada de redacción
    assert validar_paquete(p, ctx_banca()) == []
    assert BoletinBanca.model_validate_json(p.model_dump_json()) == p


@pytest.mark.parametrize("accion", ["Incluir en el boletín como observación", "Incluir como contexto"])
def test_las_acciones_de_inclusion_generan_el_boletin_sin_los_vacios_de_la_ficha(accion: str) -> None:
    p = boletin(accion=accion)
    assert p.accion == accion and not any(v.origen == "ficha" for v in p.vacios)


def test_una_senal_a_confirmar_genera_el_boletin_con_los_vacios_de_la_ficha_a_la_vista() -> None:
    p = boletin(accion="Incluir como señal a confirmar")
    assert {v.referencia for v in p.vacios if v.origen == "ficha"} == {"V1", "V2", "V3"}


@pytest.mark.parametrize("accion", ["Seguimiento prioritario", "Seguimiento", "Archivar"])
def test_seguimiento_y_archivar_no_generan_ni_llaman_al_llm(accion: str) -> None:
    prov = proveedor_banca()
    r = generar(ficha_banca(accion=accion), prov)
    assert r.tipo == "nada" and r.paquete is None and prov.llamadas == [] and accion in (r.motivo or "")


def test_forzar_el_paquete_completo_en_banca_da_el_boletin_y_queda_registrado() -> None:
    r = generar(ficha_banca(accion="Seguimiento prioritario"), proveedor_banca(), forzar_completo=True)
    assert r.tipo == "boletin" and isinstance(r.paquete, BoletinBanca) and r.paquete.forzado is True


def test_sin_evidencia_se_abstiene_antes_de_llamar_al_llm() -> None:
    prov = proveedor_banca()
    r = generar(ficha_banca(registros=[]), prov)
    assert r.tipo == "nada" and prov.llamadas == [] and "evidencia" in (r.motivo or "")


def test_una_modalidad_fuera_de_la_tabla_de_generacion_no_genera_nada() -> None:
    prov = proveedor_banca()
    r = generar(ficha_banca(modalidad="otra"), prov)
    assert r.tipo == "nada" and prov.llamadas == [] and "otra" in (r.motivo or "")


# ============================================================================================ campos por regla: aviso, leyenda, sectores, horizonte


def test_el_aviso_fijo_la_leyenda_y_la_marca_estan_presentes() -> None:
    p = boletin()
    assert p.aviso == RESTRICCIONES.aviso_banca == "No constituye recomendación financiera ni opinión oficial de la SBP."
    assert p.leyenda_alcance == RESTRICCIONES.leyendas_alcance.titular_metadatos
    assert p.marca == RESTRICCIONES.marca_borrador
    assert boletin(uso_descripcion=True).leyenda_alcance == RESTRICCIONES.leyendas_alcance.con_descripcion


def test_el_validador_rechaza_un_boletin_sin_aviso_o_sin_leyenda() -> None:
    p, ctx = boletin(), ctx_banca()
    assert "aviso_banca" in {r.regla for r in validar_paquete(p.model_copy(update={"aviso": ""}), ctx)}
    assert "aviso_banca" in {r.regla for r in validar_paquete(p.model_copy(update={"aviso": "Recomendación oficial."}), ctx)}
    assert "leyenda_alcance" in {r.regla for r in validar_paquete(p.model_copy(update={"leyenda_alcance": ""}), ctx)}


def test_los_sectores_salen_del_tema_principal_y_del_secundario_con_su_motivo() -> None:
    p = boletin()
    temas = cargar_temas().temas
    assert [s.sector for s in p.sectores] == ["economía", "continuidad operativa"]
    assert temas["economia"].nombre in p.sectores[0].motivo and temas["eventos_naturales"].nombre in p.sectores[1].motivo
    assert all(s.motivo for s in p.sectores)


def test_un_secundario_del_mismo_sector_no_repite_el_sector_y_sin_tema_no_se_inventa() -> None:
    assert [s.sector for s in boletin(tema_secundario="servicios_publicos", tema="eventos_naturales").sectores] == ["continuidad operativa"]
    sin = boletin(tema=None, tema_secundario=None)
    assert sin.sectores == [] and any(v.referencia == "sectores" for v in sin.vacios)


@pytest.mark.parametrize(
    ("edad", "esperado"),
    [(0.5, "inmediato"), (2.0, "inmediato"), (20.0, "corto plazo"), (45.0, "corto plazo"), (120.0, "estructural"), (None, "estructural")],
)
def test_el_horizonte_coincide_con_la_regla_para_dias_semanas_y_solo_anual(edad: float | None, esperado: str) -> None:
    assert boletin(edad_evidencia_dias=edad).horizonte == esperado


def test_el_horizonte_coincide_en_cada_limite_con_el_yaml() -> None:
    h = BANCA.horizonte
    assert h is not None
    assert boletin(edad_evidencia_dias=float(h.inmediato_hasta_dias)).horizonte == "inmediato"
    assert boletin(edad_evidencia_dias=h.inmediato_hasta_dias + 0.01).horizonte == "corto plazo"
    assert boletin(edad_evidencia_dias=float(h.corto_plazo_hasta_dias)).horizonte == "corto plazo"
    assert boletin(edad_evidencia_dias=h.corto_plazo_hasta_dias + 0.01).horizonte == "estructural"


def test_la_evidencia_se_copia_de_la_ficha_sin_llm() -> None:
    p = boletin()
    assert p.evidencia == ficha_banca().evidencia and ID_LLUVIAS in p.evidencia[0]


# ============================================================================================ observaciones e hipótesis de impacto


def test_las_observaciones_solo_citan_hechos_y_declaraciones_y_las_hipotesis_solo_inferencias() -> None:
    p = boletin()
    tipos = {a.id: a.tipo for a in p.afirmaciones}
    assert {tipos[i] for o in p.observaciones for i in o.afirmaciones} <= {"hecho", "declaración"}
    assert {tipos[i] for o in p.hipotesis_impacto for i in o.afirmaciones} <= {"inferencia", "hipótesis"}


def test_una_observacion_que_cita_una_hipotesis_no_llega_al_boletin() -> None:
    malo = modificada(BOLETIN, lambda d: d["observaciones"].append(_o("Las lluvias en Chiriquí podrían afectar la actividad agrícola, a verificar.", "A3")))
    p = generar(ficha_banca(), proveedor_banca(observaciones=malo)).paquete
    assert p.observaciones == [] and any(v.referencia == "observaciones" for v in p.vacios)  # type: ignore[union-attr]
    assert "observacion_con_hipotesis" in reglas_registradas("observaciones")


def test_una_hipotesis_de_impacto_sin_condicional_no_llega_al_boletin() -> None:
    malo = modificada(BOLETIN, lambda d: d["hipotesis_impacto"].append(_o("La actividad agrícola es un tema a seguir en el entorno económico.", "A4")))
    p = generar(ficha_banca(), proveedor_banca(observaciones=malo)).paquete
    assert p.hipotesis_impacto == [] and any(v.referencia == "hipotesis_impacto" for v in p.vacios)  # type: ignore[union-attr]
    assert "impacto_sin_condicional" in reglas_registradas("hipotesis_impacto")


def test_una_hipotesis_que_infiere_perdidas_no_llega_al_boletin_aunque_el_titular_las_diga() -> None:
    malo = modificada(BOLETIN, lambda d: d["hipotesis_impacto"].append(_o("Las lluvias podrían generar pérdidas en Chiriquí.", "A3")))
    p = generar(ficha_banca(), proveedor_banca(observaciones=malo)).paquete
    assert p.hipotesis_impacto == []  # type: ignore[union-attr]
    assert "perdidas_en_inferencias" in reglas_registradas("hipotesis_impacto")


def test_una_recomendacion_no_llega_al_boletin_en_ningun_bloque() -> None:
    malo = modificada(BOLETIN, lambda d: d["observaciones"].append(_o("Según La Prensa, recomendamos reducir exposición en Chiriquí.", "A1")))
    p = generar(ficha_banca(), proveedor_banca(observaciones=malo)).paquete
    assert p.observaciones == []  # type: ignore[union-attr]
    assert {"recomendacion", "perdidas_en_inferencias"} <= reglas_registradas("observaciones")


def test_el_resumen_suma_observaciones_e_hipotesis_y_no_pasa_de_250_palabras() -> None:
    maximo = cargar_salidas().banca.resumen_max_palabras
    largo = " ".join(["cultivos"] * 60)
    malo = modificada(BOLETIN, lambda d: d.update(
        observaciones=[_o(f"Según La Prensa, las lluvias causaron pérdidas en {largo}.", "A1") for _ in range(3)],
        hipotesis_impacto=[_o(f"Las lluvias podrían afectar la actividad agrícola {largo}, a verificar.", "A3")],
    ))
    p = generar(ficha_banca(), proveedor_banca(observaciones=malo)).paquete
    total = sum(contar_palabras(o.texto) for o in [*p.observaciones, *p.hipotesis_impacto])  # type: ignore[union-attr]
    assert total <= maximo and any(v.referencia in ("observaciones", "hipotesis_impacto") for v in p.vacios)  # type: ignore[union-attr]
    corto = generar(ficha_banca(), proveedor_banca()).paquete
    assert 0 < sum(contar_palabras(o.texto) for o in [*corto.observaciones, *corto.hipotesis_impacto]) <= maximo  # type: ignore[union-attr]


def test_exactamente_tres_preguntas_cada_una_con_su_vacio() -> None:
    p = boletin()
    assert len(p.preguntas) == cargar_salidas().banca.preguntas == 3
    assert {q.vacio for q in p.preguntas} <= {"V1", "V2", "V3"}
    dos = modificada(BOLETIN, lambda d: d["preguntas"].pop())
    assert generar(ficha_banca(), proveedor_banca(observaciones=dos)).paquete.preguntas == []  # type: ignore[union-attr]


def test_una_afirmacion_de_recomendacion_o_de_perdidas_inferidas_se_descarta_en_el_paso_1() -> None:
    malas = modificada(AFIRMACIONES_BANCA, lambda d: d["afirmaciones"].extend([
        {"id": "A5", "tipo": "inferencia", "texto": "Recomendamos reducir exposición al sector agrícola", "citas": [], "base": ["A1"]},
        {"id": "A6", "tipo": "hipótesis", "texto": "Las lluvias podrían generar pérdidas a los bancos", "citas": [], "base": ["A1"]},
    ]))
    r = generar(ficha_banca(), proveedor_banca(afirmaciones=malas))
    assert {a.id for a in r.paquete.afirmaciones} == {"A1", "A2", "A3", "A4"}  # type: ignore[union-attr]
    assert any(d.startswith("A5") and "recomendacion" in d for d in r.descartadas)
    assert any(d.startswith("A6") and "perdidas_en_inferencias" in d for d in r.descartadas)


# ============================================================================================ prompt, evidencia delimitada y sin código por modalidad


def test_el_prompt_del_boletin_esta_versionado_y_la_evidencia_va_en_el_mensaje_de_usuario() -> None:
    nombre = cargar_generacion().prompts.paquetes["boletin"]
    version, texto = cargar_prompt(nombre)
    assert nombre == "boletin_banca" and re.fullmatch(r"\d+\.\d+", version) and "## afirmaciones" in texto and "## grupo boletin" in texto
    prov = proveedor_banca()
    generar(ficha_banca(), prov)
    for _, system, usuario in prov.llamadas:
        assert "<evidencia>" not in system.replace("<evidencia>…</evidencia>", "").replace("<evidencia> y </evidencia>", "")
        assert usuario.count("<evidencia>") == 1 and usuario.count("</evidencia>") == 1
        assert "{esquema}" not in system
    assert "boletín" in prov.llamadas[0][1].lower() and "paquete editorial" not in prov.llamadas[1][1].lower()


def test_las_llamadas_registran_la_version_del_prompt_del_boletin() -> None:
    version, _ = cargar_prompt("boletin_banca")
    r = generar(ficha_banca(), proveedor_banca())
    assert [c.version_prompt for c in r.llamadas] == [version, version]


def test_ninguna_parte_de_src_compara_el_nombre_de_la_modalidad() -> None:
    raiz = Path(__file__).resolve().parents[1] / "src"
    patron = re.compile(r"""(==|!=)\s*["'](editorial|banca)["']|["'](editorial|banca)["']\s*(==|!=)|modalidad\s+in\s*\(""")
    culpables = [f"{p.name}:{n}" for p in raiz.rglob("*.py") for n, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if patron.search(l)]
    assert culpables == []


def test_los_textos_de_configuracion_del_boletin_no_usan_el_lexico_prohibido() -> None:
    import yaml

    datos = yaml.safe_load((CARPETA_CONFIG / "generacion.yaml").read_text(encoding="utf-8"))["boletin"]
    texto = json.dumps(datos, ensure_ascii=False).lower()
    prohibidas = [f.lower() for lista in RESTRICCIONES.grupos["banca"].values() for f in lista]
    assert not [f for f in prohibidas if re.search(rf"(?<!\w){re.escape(f)}(?!\w)", texto)]


# ============================================================================================ CLI


def test_la_cli_produce_un_boletin_valido(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "ficha.json"
    ruta.write_text(ficha_banca().model_dump_json(), encoding="utf-8")
    assert principal(["--ficha-json", str(ruta)], crear=proveedor_banca) == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida["tipo"] == "boletin"
    p = BoletinBanca.model_validate(salida["paquete"])
    assert p.aviso and p.horizonte == "inmediato" and p.observaciones


def test_el_generador_no_reemite_grupos_del_paquete_editorial_en_banca() -> None:
    g = Generador(ficha_banca(), proveedor_banca())
    assert g.grupos == ["boletin"]
    with pytest.raises(ValueError):
        g.generar_grupo("guion")


# ============================================================================================ integración con la ficha real (E1-10b)


@pytest.fixture(scope="module")
def con_banca(tmp_path_factory):
    from src import db, embeddings
    from tests import ficha_ayuda as h
    from tests.motor_falso import MotorFalso, config_de_prueba

    emb = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))
    base = h.construir(tmp_path_factory.mktemp("banca") / "senales.duckdb", emb, modalidad="banca")
    c = db.conectar(Path(base), solo_lectura=True)
    yield c, emb
    c.close()


def test_desde_ficha_trae_la_evidencia_los_temas_y_la_edad_que_usa_el_horizonte(con_banca) -> None:
    from src.ficha import construir_ficha, texto_respaldo
    from src.generacion import desde_ficha
    from tests import ficha_ayuda as h

    con, emb = con_banca
    f = construir_ficha(h.G_COMPLETO, "banca", con, emb=emb)
    e = desde_ficha(f)
    r = f.respaldado
    assert e.evidencia == [texto_respaldo(x) for x in (*r.reportes, *r.datos_oficiales, *r.eventos_oficiales, *r.declaraciones)] and e.evidencia
    assert e.tema == "economia" and e.modalidad == "banca"
    # la publicación más reciente del grupo es 2026-10-06T09:00Z y el corte del puntaje, h.CORTE (12:00Z): 3 horas
    assert e.edad_evidencia_dias == pytest.approx(3 / 24)
    sin_fecha = desde_ficha(construir_ficha(h.G_SIN_FECHA, "banca", con, emb=emb))
    # sin publicación: la detección más reciente (cobertura.fecha_fin del grupo, 10:00Z en la base de prueba) → 2 horas
    assert sin_fecha.edad_evidencia_dias == pytest.approx(2 / 24)


def test_el_tema_secundario_del_grupo_es_el_mas_frecuente_distinto_del_principal() -> None:
    from src.sectores import tema_secundario_de_grupo

    temas = {"economia", "logistica", "turismo", "eventos_naturales"}
    miembros = [
        {"tema_clasificado": "economia", "tema_secundario": "logistica"},
        {"tema_clasificado": "economia", "tema_secundario": "turismo"},
        {"tema_clasificado": "logistica", "tema_secundario": None},
        {"tema_clasificado": "sin_tema", "tema_secundario": "economia"},
    ]
    assert tema_secundario_de_grupo(miembros, "economia", temas) == "logistica"
    assert tema_secundario_de_grupo([{"tema_clasificado": "economia"}], "economia", temas) is None
    assert tema_secundario_de_grupo([{"tema_secundario": "turismo"}, {"tema_secundario": "eventos_naturales"}], "economia", temas) == "eventos_naturales"


def test_la_pantalla_paquete_muestra_el_boletin_con_sus_etiquetas() -> None:
    from src import interfaz as ui

    etiquetas = ui.cargar_interfaz().paquete.etiquetas
    secciones = dict(ui.secciones_de_paquete(boletin(), etiquetas))
    assert {etiquetas[k] for k in ("observaciones", "hipotesis_impacto", "sectores", "horizonte", "evidencia", "aviso")} <= set(secciones)
    assert secciones[etiquetas["sectores"]][0].startswith("economía: ") and secciones[etiquetas["aviso"]] == [RESTRICCIONES.aviso_banca]
