"""E1-10 · Estado de evidencia, vacíos, cifras, acción recomendada (tabla 3×3) y proveedor de LLM por configuración."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

from src import evidencia, puntaje
from src.configuracion import RAIZ, ErrorDeConfiguracion, cargar_modalidad
from src.evidencia import ESTADO_INSUFICIENTE, ESTADO_PARCIAL, ESTADO_SUFICIENTE
from src.llm.ollama import ProveedorOllama
from src.llm.proveedor import ErrorProveedor, crear_proveedor
from tests.prioridad_ayuda import AHORA, CFG, REGLAS, entrada

MODALIDAD = cargar_modalidad("editorial")
RANGOS = ("bajo", "medio", "alto")
ESTADOS = (ESTADO_INSUFICIENTE, ESTADO_PARCIAL, ESTADO_SUFICIENTE)


# ------------------------------------------------------------------ estado de evidencia


@pytest.mark.parametrize(
    ("n", "oficial", "cifras", "abiertas", "esperado"),
    [
        (1, False, False, 0, ESTADO_INSUFICIENTE),   # una sola procedencia y nada oficial
        (0, False, False, 0, ESTADO_INSUFICIENTE),
        (1, True, False, 0, ESTADO_PARCIAL),          # una procedencia + dato oficial
        (1, True, True, 0, ESTADO_PARCIAL),
        (2, False, False, 0, ESTADO_SUFICIENTE),      # dos procedencias, sin cifras ni contradicción
        (3, True, True, 0, ESTADO_SUFICIENTE),        # con cifras, el dato oficial las respalda
        (2, False, True, 0, ESTADO_PARCIAL),          # cifras sin dato oficial: no alcanza «suficiente»
        (2, True, False, 1, ESTADO_PARCIAL),          # contradicción abierta: no es «suficiente»
        (5, True, True, 2, ESTADO_PARCIAL),
        (1, False, False, 3, ESTADO_INSUFICIENTE),
    ],
)
def test_estado_de_evidencia_segun_procedencias_dato_oficial_cifras_y_contradicciones(n, oficial, cifras, abiertas, esperado) -> None:
    assert evidencia.estado_de(n, oficial, cifras, abiertas, REGLAS) == esperado


def test_el_estado_de_evidencia_no_depende_del_puntaje() -> None:
    parametros = set(inspect.signature(evidencia.estado_de).parameters) | set(inspect.signature(evidencia.evaluar_evidencia).parameters)
    assert not parametros & {"p", "puntaje", "rango", "r", "i", "u", "n_novedad"}
    # y el puntaje no mira la evidencia más que por sus entradas: el mismo grupo da el mismo estado con cualquier P
    e = evidencia.evaluar_evidencia(
        n_procedencias=2, tiene_oficial=False, titulares=["Titular sin cifras"], contradicciones_abiertas=0,
        n_identificables=1, motivo_sin_oficial=None, reglas=REGLAS, cfg=CFG,
    )
    assert e.estado == ESTADO_SUFICIENTE


def test_los_vacios_explican_el_estado_y_nombran_el_motivo() -> None:
    e = evidencia.evaluar_evidencia(
        n_procedencias=1, tiene_oficial=False, titulares=["Cierran 12 escuelas", "Sin cifra"], contradicciones_abiertas=2,
        n_identificables=1, motivo_sin_oficial="tema_sin_indicador", reglas=REGLAS, cfg=CFG,
    )
    codigos = [v.codigo for v in e.vacios]
    assert codigos == ["procedencias_insuficientes", "cifras_sin_dato_oficial", "sin_dato_oficial", "contradiccion_abierta", "medios_o_fechas_desconocidos"]
    textos = {v.codigo: v.texto for v in e.vacios}
    assert "1 procedencia" in textos["procedencias_insuficientes"] and "al menos 2" in textos["procedencias_insuficientes"]
    assert "tema_sin_indicador" in textos["sin_dato_oficial"]
    assert textos["contradiccion_abierta"].startswith("posible contradicción, verificar") and "2 par" in textos["contradiccion_abierta"]
    assert "1 de 2 titulares" in textos["medios_o_fechas_desconocidos"]
    assert e.hay_cifras is True and e.estado == ESTADO_INSUFICIENTE


def test_un_grupo_completo_no_tiene_vacios() -> None:
    e = evidencia.evaluar_evidencia(
        n_procedencias=3, tiene_oficial=True, titulares=["Inflación de 3,2 % en 2024"], contradicciones_abiertas=0,
        n_identificables=1, motivo_sin_oficial=None, reglas=REGLAS, cfg=CFG,
    )
    assert e.vacios == () and e.estado == ESTADO_SUFICIENTE


# ------------------------------------------------------------------ cifras


@pytest.mark.parametrize(
    ("titular", "esperado"),
    [
        ("Cierran 12 escuelas en Veraguas", [(12.0, "escue")]),
        ("La inflación llegó a 3,2 % en 2024", [(3.2, "%")]),
        ("El BID moviliza US$84.000 millones", [(84000.0, "millo")]),
        ("Ley 552 del Presupuesto del Canal de Panamá", []),
        ("Se sanciona el 2 de octubre", []),
        ("Panamá en 2026: balance del año", []),
        ("Presidente visita Singapur y Vietnam", []),
        ("Más de 30 mujeres han muerto de forma violenta", [(30.0, "mujer")]),
        ("Crece 5% la carga y 7 por ciento más", [(5.0, "%"), (7.0, "")]),
    ],
)
def test_extraccion_de_cifras_sin_fechas_anios_ni_identificadores(titular, esperado) -> None:
    assert [(c.valor, c.unidad) for c in evidencia.extraer_cifras(titular, CFG)] == esperado


def test_valores_numericos_con_separadores() -> None:
    d = CFG.cifras.digitos_por_grupo_de_miles
    assert evidencia.valor_numerico("84.000", d) == 84000
    assert evidencia.valor_numerico("1.234.567", d) == 1234567
    assert evidencia.valor_numerico("3,2", d) == 3.2
    assert evidencia.valor_numerico("3.5", d) == 3.5
    assert evidencia.valor_numerico("1.234,5", d) == 1234.5
    assert evidencia.valor_numerico("12", d) == 12


def test_hay_cifras_solo_si_algun_titular_trae_una() -> None:
    assert evidencia.hay_cifras(["Sin cifras", "Cierran 12 escuelas"], CFG)
    assert not evidencia.hay_cifras(["Sin cifras", "Ley 552 aprobada el 2 de octubre de 2026"], CFG)


# ------------------------------------------------------------------ tabla 3×3


ACCIONES_ESPERADAS = {
    ("alto", ESTADO_SUFICIENTE): "Producir borrador",
    ("alto", ESTADO_PARCIAL): "Completar evidencia y producir",
    ("alto", ESTADO_INSUFICIENTE): "Investigar ya",
    ("medio", ESTADO_SUFICIENTE): "Borrador opcional",
    ("medio", ESTADO_PARCIAL): "Vigilar",
    ("medio", ESTADO_INSUFICIENTE): "Vigilar",
    ("bajo", ESTADO_SUFICIENTE): "Archivar como contexto",
    ("bajo", ESTADO_PARCIAL): "Archivar",
    ("bajo", ESTADO_INSUFICIENTE): "Archivar",
}


@pytest.mark.parametrize(("rango", "estado"), [(r, e) for r in RANGOS for e in ESTADOS])
def test_cada_celda_de_la_tabla_de_acciones_es_la_del_diseno_y_ninguna_habilita_publicar(rango, estado) -> None:
    a = evidencia.accion_recomendada(rango, estado, MODALIDAD)
    assert a.accion == ACCIONES_ESPERADAS[(rango, estado)]
    assert a.motivo
    texto = f"{a.accion} {a.motivo}"
    assert not re.search(r"public", texto, re.IGNORECASE), texto
    assert not re.search(r"\b(alerta|alertas)\b", texto, re.IGNORECASE)   # ninguna emite una alerta definitiva


def test_la_tabla_tiene_exactamente_nueve_celdas_y_viene_del_yaml_de_la_modalidad() -> None:
    celdas = evidencia.celdas_de_acciones(MODALIDAD)
    assert len(celdas) == 9 and set(celdas) == set(ACCIONES_ESPERADAS)
    crudo = (RAIZ / "config" / "modalidad_editorial.yaml").read_text(encoding="utf-8")
    for accion in ACCIONES_ESPERADAS.values():
        assert accion in crudo


def test_una_celda_que_hable_de_publicar_no_carga() -> None:
    tabla = MODALIDAD.tabla_acciones.model_dump()
    tabla["alto"]["suficiente"]["accion"] = "Publicar ya"
    with pytest.raises(ValueError, match="publicar"):
        type(MODALIDAD).model_validate({**MODALIDAD.model_dump(), "tabla_acciones": tabla})


def test_la_accion_no_cambia_con_el_puntaje_solo_con_el_rango_y_el_estado() -> None:
    assert set(inspect.signature(evidencia.accion_recomendada).parameters) == {"rango", "estado", "modalidad"}


def test_ninguna_salida_de_un_grupo_de_prioridad_alta_contiene_la_accion_publicar() -> None:
    fuerte = entrada("GRP-f", n_procedencias=3, tiene_oficial=True)
    (p,) = puntaje.calcular_puntajes([fuerte], REGLAS, CFG, AHORA)
    e = evidencia.evaluar_evidencia(
        n_procedencias=3, tiene_oficial=True, titulares=["x"], contradicciones_abiertas=0, n_identificables=1, motivo_sin_oficial=None, reglas=REGLAS, cfg=CFG
    )
    accion = evidencia.accion_recomendada(p.rango, e.estado, MODALIDAD)
    salida = json.dumps({"puntaje": p.a_diccionario(), "accion": accion.accion, "motivo": accion.motivo}, ensure_ascii=False)
    assert not re.search(r"public(ar|a|ado|able)\b", salida, re.IGNORECASE) or '"habilita_publicacion": false' in salida.lower()
    assert "Publicar" not in salida and p.habilita_publicacion is False


def test_no_hay_if_modalidad_en_src() -> None:
    for ruta in (RAIZ / "src").rglob("*.py"):
        assert not re.search(r"\bif\s+modalidad\s*(==|!=|in)", ruta.read_text(encoding="utf-8")), ruta


def test_ningun_numero_de_negocio_hardcodeado_en_los_modulos_nuevos() -> None:
    """Los módulos de E1-10 solo usan 0 y 1 (límites de [0, 1]) y constantes con nombre: ningún peso, umbral ni ventana va en el código."""
    for nombre in ("puntaje.py", "evidencia.py", "contradicciones.py", "prioridad.py"):
        ruta = RAIZ / "src" / nombre
        if not ruta.exists():
            continue
        codigo = re.sub(r'"""[\s\S]*?"""', "", ruta.read_text(encoding="utf-8"))
        sin_constantes = "\n".join(linea for linea in codigo.splitlines() if not re.match(r"[A-Z][A-Z_]+\s*(:[^=]+)?=", linea))
        sin_comentarios = re.sub(r"#.*", "", sin_constantes)
        sin_cadenas = re.sub(r"(\"[^\"\n]*\"|'[^'\n]*')", '""', sin_comentarios)
        literales = set(re.findall(r"(?<![\w.\[])(\d+\.\d+|\d{2,})(?![\w])", sin_cadenas))
        assert not literales - {"0.0", "1.0"}, (nombre, literales)


# ------------------------------------------------------------------ proveedor por configuración


def test_sin_llm_provider_en_la_configuracion_no_hay_proveedor() -> None:
    with pytest.raises(ErrorProveedor, match="LLM_PROVIDER"):
        crear_proveedor({})


def test_un_proveedor_desconocido_o_sin_adaptador_falla_con_un_mensaje_claro() -> None:
    with pytest.raises(ErrorProveedor, match="desconocido"):
        crear_proveedor({"LLM_PROVIDER": "otro"})
    with pytest.raises(ErrorProveedor, match="DeepSeek"):
        crear_proveedor({"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "x" * 20})
    with pytest.raises(ErrorProveedor, match="OLLAMA_MODEL"):
        crear_proveedor({"LLM_PROVIDER": "ollama"})


def test_el_proveedor_ollama_sale_de_la_configuracion_y_pide_json_con_temperatura_cero() -> None:
    p = crear_proveedor({"LLM_PROVIDER": "Ollama", "OLLAMA_MODEL": "modelo:1b", "OLLAMA_HOST": "127.0.0.1:9999"})
    assert isinstance(p, ProveedorOllama) and p.modelo == "modelo:1b" and p.cliente.host == "http://127.0.0.1:9999"


class _Respuesta:
    def __init__(self, cuerpo: dict[str, Any]) -> None:
        self.cuerpo = cuerpo

    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, Any]:
        return self.cuerpo


class _Sesion:
    def __init__(self, cuerpo: dict[str, Any]) -> None:
        self.cuerpo, self.enviados = cuerpo, []

    def post(self, url: str, **kwargs: Any) -> _Respuesta:
        self.enviados.append((url, kwargs["json"]))
        return _Respuesta(self.cuerpo)

    def get(self, url: str, **kwargs: Any) -> _Respuesta:
        return _Respuesta({})


def test_ollama_recibe_system_usuario_esquema_temperatura_cero_y_semilla_fija() -> None:
    from src.configuracion import cargar_llm

    cfg = cargar_llm()
    sesion = _Sesion({"message": {"content": '{"pares": []}'}})
    p = ProveedorOllama("localhost:11434", "m", cfg, sesion)
    assert p.generar_json("SYS", "USR", {"type": "object"}) == '{"pares": []}'
    ((url, cuerpo),) = sesion.enviados
    assert url.endswith("/api/chat") and cuerpo["format"] == {"type": "object"} and cuerpo["stream"] is False
    assert cuerpo["options"]["temperature"] == 0 == cfg.generacion.temperatura
    assert cuerpo["options"]["seed"] == cfg.generacion.semilla
    assert [m["role"] for m in cuerpo["messages"]] == ["system", "user"]


def test_ollama_vacio_o_caido_es_un_error_de_proveedor() -> None:
    from src.configuracion import cargar_llm

    cfg = cargar_llm()
    with pytest.raises(ErrorProveedor, match="vacía"):
        ProveedorOllama("h", "m", cfg, _Sesion({"message": {"content": ""}})).generar_json("s", "u", {})

    class Caida(_Sesion):
        def post(self, url: str, **kwargs: Any) -> _Respuesta:
            import requests

            raise requests.ConnectionError("sin conexión")

    with pytest.raises(ErrorProveedor, match="sin conexión"):
        ProveedorOllama("h", "m", cfg, Caida({})).generar_json("s", "u", {})
