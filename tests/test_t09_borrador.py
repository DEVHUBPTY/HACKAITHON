"""T09 · Brief editorial: formato útil, citas pertinentes y distinción de hechos e inferencias (PDF sección 8, E1-13).

Todo con un proveedor falso: lo que se prueba es que el validador deja pasar el borrador correcto y que **nada** de lo que el modelo
invente llega al paquete, con cada rechazo registrado en ``outputs/rechazos.jsonl`` (aquí, en una carpeta temporal).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.generacion import Generador, generar
from src.registro import olvidar_sensibles, registrar_sensible
from src.validador import Contexto, RegistroRechazos, Rechazo, calcular_tasas, principal, validar_paquete
from tests.generacion_ayuda import BUENAS, ProveedorGuionado, ficha, modificada, _o


def registro() -> list[dict[str, Any]]:
    ruta = Path(os.environ["RECHAZOS_JSONL"])
    return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()] if ruta.exists() else []


def seccion_vacia(p: Any, nombre: str) -> bool:
    return not getattr(p, nombre) and any(v.referencia == nombre for v in p.vacios)


# ============================================================================================ el borrador correcto


def test_el_borrador_correcto_pasa_el_validador_completo() -> None:
    r = generar(ficha(), ProveedorGuionado())
    p = r.paquete
    assert p is not None and p.brief and p.guion and p.titulares and p.vacios == []
    assert validar_paquete(p, Contexto(ficha(), ("comunes", "editorial"))) == []


def test_el_brief_distingue_hechos_declaraciones_e_inferencias_con_sus_citas() -> None:
    p = generar(ficha(), ProveedorGuionado()).paquete
    por_id = {a.id: a for a in p.afirmaciones}  # type: ignore[union-attr]
    citadas = [por_id[i] for o in p.brief for i in o.afirmaciones]  # type: ignore[union-attr]
    assert {"hecho", "declaración"} <= {a.tipo for a in citadas}
    assert {"inferencia"} <= {por_id[i].tipo for o in p.enfoque for i in o.afirmaciones}  # type: ignore[union-attr]
    assert all(a.citas for a in por_id.values() if a.tipo in ("hecho", "declaración"))
    assert all(a.base for a in por_id.values() if a.tipo in ("inferencia", "hipótesis"))
    assert any("2023" in o.texto for o in p.brief)  # type: ignore[union-attr]


def test_el_validador_detecta_un_paquete_alterado_a_mano() -> None:
    p = generar(ficha(), ProveedorGuionado()).paquete
    ctx = Contexto(ficha(), ("comunes", "editorial"))
    assert validar_paquete(p.model_copy(update={"leyenda_alcance": ""}), ctx)  # type: ignore[union-attr]
    assert validar_paquete(p.model_copy(update={"marca": "FINAL"}), ctx)  # type: ignore[union-attr]
    alterado = p.model_copy(update={"brief": [p.brief[0].model_copy(update={"texto": "La inflación llegará a 15 % en 2027."})]})  # type: ignore[union-attr]
    assert any(r.regla == "cifra_no_coincide" for r in validar_paquete(alterado, ctx))


# ============================================================================================ lo que el modelo inventa no se emite

INVENTOS = {
    "una cifra que no coincide": ("brief", "La inflación llegará a 15 % en 2027.", "A3", "cifra_no_coincide"),
    "causalidad": ("brief", "El plan avanza por culpa de la oposición.", "A1", "causalidad"),
    "fuentes confirmaron": ("brief", "Según TVN Panamá, fuentes oficiales confirmaron el plan.", "A1", "detalle_sin_cita"),
    "declaración sin atribución": ("brief", "Mulino anuncia nuevo plan para el Canal de Panamá.", "A1", "sin_atribucion"),
    "nombre nuevo": ("brief", "Según TVN Panamá, Juan Pérez anuncia el plan.", "A1", "nombre_nuevo"),
    "dato anual sin año": ("brief", "La inflación de Panamá es de 2.9 % anual.", "A3", "ind_sin_anio"),
    "dato anual con «actual»": ("brief", "La inflación actual de Panamá fue de 2.9 % anual en 2023.", "A3", "ind_volatil"),
    "acusación en el cuerpo": ("brief", "TVN Panamá reporta que Mulino es corrupto.", "A1", "acusacion"),
}


@pytest.mark.parametrize("nombre", INVENTOS)
def test_lo_que_el_modelo_inventa_en_el_brief_no_llega_al_paquete(nombre: str) -> None:
    _, texto, cita, regla = INVENTOS[nombre]
    mala = modificada(BUENAS["brief"], lambda d: d["brief"].append(_o(texto, cita)))
    prov = ProveedorGuionado(brief=mala)
    p = generar(ficha(), prov).paquete
    assert seccion_vacia(p, "brief")
    assert texto not in [o.texto for o in p.resumen_web + p.guion + p.enfoque]  # type: ignore[union-attr]
    assert prov.claves.count("brief") == 2  # un reintento, como E1-12
    assert regla in {x["regla"] for x in registro() if x["evento"] == "rechazo" and x["seccion"] == "brief"}, nombre


def test_una_hipotesis_sin_condicional_en_el_cuerpo_no_llega_al_paquete() -> None:
    con_hipotesis = modificada(
        BUENAS["afirmaciones"],
        lambda d: d["afirmaciones"].append({"id": "A5", "tipo": "hipótesis", "texto": "El plan podría bajar los precios, a verificar", "citas": [], "base": ["A1", "A3"]}),
    )
    mala = modificada(BUENAS["brief"], lambda d: d["brief"].append(_o("El plan baja los precios.", "A5")))
    p = generar(ficha(), ProveedorGuionado(afirmaciones=con_hipotesis, brief=mala)).paquete
    assert seccion_vacia(p, "brief")
    assert "hipotesis_sin_condicional" in {x["regla"] for x in registro() if x["evento"] == "rechazo"}


def test_un_hecho_de_acusacion_con_el_conteo_del_grupo_se_descarta_del_paso_1() -> None:
    """Revisión del PR #26: «Mulino robó fondos» tipado hecho y citando un conteo no puede entrar."""
    f = ficha()
    f.registros.append(__import__("src.generacion", fromlist=["RegistroEvidencia"]).RegistroEvidencia(id="GRP-0123456789", campos={"n_titulares": "5"}))
    mala = modificada(
        BUENAS["afirmaciones"],
        lambda d: d["afirmaciones"].append({"id": "A5", "tipo": "hecho", "texto": "Mulino robó fondos del Canal", "citas": [{"id": "GRP-0123456789", "campo": "n_titulares"}], "base": []}),
    )
    r = generar(f, ProveedorGuionado(afirmaciones=mala))
    assert not any("robó" in a.texto for a in r.paquete.afirmaciones)  # type: ignore[union-attr]
    assert any("A5" in d and "acusación" in d for d in r.descartadas)


def test_una_cifra_falsa_en_el_paso_1_se_descarta_con_su_regla() -> None:
    mala = modificada(BUENAS["afirmaciones"], lambda d: d["afirmaciones"][2].update(texto="La inflación de Panamá fue de 9.9 % anual en 2023"))
    r = generar(ficha(), ProveedorGuionado(afirmaciones=mala))
    assert not any("9.9" in a.texto for a in r.paquete.afirmaciones)  # type: ignore[union-attr]
    assert "cifra_no_coincide" in {x["regla"] for x in registro() if x["evento"] == "rechazo"}


def test_si_el_reintento_corrige_el_borrador_sale_y_ambos_intentos_quedan_registrados() -> None:
    mala = modificada(BUENAS["brief"], lambda d: d["brief"].append(_o("El plan avanza por culpa de la oposición.", "A1")))
    p = generar(ficha(), ProveedorGuionado(brief=(mala, BUENAS["brief"]))).paquete
    assert p.brief and p.vacios == []  # type: ignore[union-attr]
    brief = [x for x in registro() if x["evento"] == "evaluacion" and x["seccion"] == "brief"]
    assert [x["resultado"] for x in brief] == ["rechazada", "ok"] and [x["intento"] for x in brief] == [0, 1]


# ============================================================================================ outputs/rechazos.jsonl


def test_cada_rechazo_queda_registrado_con_regla_modelo_caso_seccion_y_hora() -> None:
    mala = modificada(BUENAS["brief"], lambda d: d["brief"].append(_o("El plan avanza por culpa de la oposición.", "A1")))
    generar(ficha(), ProveedorGuionado(brief=mala))
    rechazos = [x for x in registro() if x["evento"] == "rechazo"]
    assert rechazos
    for x in rechazos:
        assert {"regla", "motivo", "fragmento", "proveedor", "modelo", "id_caso", "seccion", "ts", "intento", "unidad", "item"} <= x.keys()
        assert x["proveedor"] == "guionado" and x["modelo"] == "guionado-0" and x["id_caso"] == "CASO-0007" and x["ts"].endswith("Z")


def test_el_registro_permite_calcular_la_tasa_por_regla_y_por_modelo(tmp_path: Path) -> None:
    ruta = tmp_path / "r.jsonl"
    a = RegistroRechazos(ruta, proveedor="deepseek", modelo="m1", id_caso="X")
    b = RegistroRechazos(ruta, proveedor="ollama", modelo="m2", id_caso="X")
    a.evaluacion("afirmacion", "afirmaciones", "A1", [Rechazo("causalidad", "m"), Rechazo("causalidad", "m"), Rechazo("acusacion", "m")])
    a.evaluacion("afirmacion", "afirmaciones", "A2", [])
    a.evaluacion("seccion", "brief", "brief", [])
    b.evaluacion("seccion", "brief", "brief", [Rechazo("causalidad", "m")])
    t = calcular_tasas(ruta)
    assert t["unidades_evaluadas"] == 4
    assert t["por_modelo"]["deepseek/m1"]["tasa"] == pytest.approx(1 / 3) and t["por_modelo"]["deepseek/m1"]["n"] == 3
    assert t["por_modelo"]["ollama/m2"]["tasa"] == 1.0
    c = t["por_regla"]["causalidad"]["deepseek/m1"]["afirmacion"]
    assert c["k"] == 1 and c["n"] == 2 and len(c["ic95"]) == 2  # una vez por unidad aunque dispare dos veces; n = afirmaciones evaluadas
    assert t["por_regla"]["acusacion"]["deepseek/m1"]["afirmacion"]["k"] == 1
    assert t["por_regla"]["causalidad"]["ollama/m2"]["seccion:brief"]["n"] == 1


def test_la_cli_resume_el_registro(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "r.jsonl"
    RegistroRechazos(ruta, proveedor="p", modelo="m").evaluacion("seccion", "brief", "brief", [Rechazo("limite_palabras", "m")])
    assert principal(["--tasas", "--ruta", str(ruta)]) == 0
    assert json.loads(capsys.readouterr().out)["por_modelo"]["p/m"]["k"] == 1


def test_un_registro_inexistente_da_tasas_vacias(tmp_path: Path) -> None:
    assert calcular_tasas(tmp_path / "no.jsonl")["unidades_evaluadas"] == 0


def test_el_registro_nunca_copia_un_secreto_ni_el_system_prompt() -> None:
    secreto = "sk-t09-secreto-" + "z" * 20
    registrar_sensible(secreto)
    try:
        mala = modificada(BUENAS["resumen_web"], lambda d: d["resumen_web"][0].update(texto=f"La clave es {secreto}", afirmaciones=["A1"]))
        generar(ficha(), ProveedorGuionado(resumen_web=mala))
    finally:
        olvidar_sensibles()
    texto = Path(os.environ["RECHAZOS_JSONL"]).read_text(encoding="utf-8")
    assert secreto not in texto and '"regla": "secreto"' in texto


def test_un_registro_que_no_se_puede_escribir_no_tumba_la_generacion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RECHAZOS_JSONL", str(tmp_path / "archivo" / "r.jsonl"))
    (tmp_path / "archivo").write_text("es un archivo, no una carpeta")
    assert generar(ficha(), ProveedorGuionado()).paquete.brief  # type: ignore[union-attr]


def test_las_pruebas_no_tocan_el_registro_real() -> None:
    assert "rechazos.jsonl" in os.environ["RECHAZOS_JSONL"] and "outputs" not in os.environ["RECHAZOS_JSONL"]
    assert Generador(ficha(), None).registro_rechazos.ruta == Path(os.environ["RECHAZOS_JSONL"])
