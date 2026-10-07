"""Ayudas de las pruebas de E1-12: una ficha de entrada mínima y un proveedor guionado (nunca se llama a un LLM real)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.generacion import ContradiccionFicha, EntradaFicha, RegistroEvidencia, VacioFicha
from src.llm.proveedor import ErrorProveedor, UsoLlm

ID_TVN = "NOT-aaaaaaaaaa"
ID_REUTERS = "NOT-bbbbbbbbbb"
ID_PRENSA = "NOT-cccccccccc"
ID_IND = "IND-PAN-FP.CPI.TOTL.ZG-2023"
TITULAR_TVN = "Mulino anuncia nuevo plan para el Canal de Panamá"
TITULAR_REUTERS = "Panama Canal authority reports record transits"
MARCADOR = "[VISUAL: a definir por producción]"


def ficha(accion: str = "Producir borrador", **cambios: Any) -> EntradaFicha:
    datos: dict[str, Any] = {
        "id_caso": "CASO-0007",
        "version": 1,
        "modalidad": "editorial",
        "accion": accion,
        "uso_descripcion": False,
        "registros": [
            RegistroEvidencia(id=ID_TVN, idioma="es", campos={"titulo": TITULAR_TVN, "medio": "TVN Panamá", "fecha_publicacion": "2026-10-05T10:00:00Z"}),
            RegistroEvidencia(id=ID_REUTERS, idioma="en", campos={"titulo": TITULAR_REUTERS, "medio": "Reuters", "fecha_publicacion": "2026-10-05T12:00:00Z"}),
            RegistroEvidencia(id=ID_IND, campos={"valor": "2.9", "anio": "2023", "unidad": "% anual"}),
        ],
        "vacios": [
            VacioFicha(id="V1", descripcion="Falta confirmar el monto con una fuente oficial"),
            VacioFicha(id="V2", descripcion="No hay cifra oficial para 2024"),
            VacioFicha(id="V3", descripcion="Solo un medio reporta el calendario"),
        ],
        "fuentes_verificaciones": ["Autoridad del Canal de Panamá: confirmar tránsitos", "MEF: confirmar el monto del plan"],
        "contradicciones": [],
    }
    datos.update(cambios)
    return EntradaFicha(**datos)


def contradiccion_abierta() -> list[ContradiccionFicha]:
    return [ContradiccionFicha(id_a=ID_TVN, id_b=ID_PRENSA, fragmento_a="nuevo plan", fragmento_b="sin plan")]


def registro_prensa() -> RegistroEvidencia:
    return RegistroEvidencia(id=ID_PRENSA, idioma="es", campos={"titulo": "Gobierno asegura que no hay sin plan para el Canal", "medio": "La Prensa", "fecha_publicacion": "2026-10-05T11:00:00Z"})


# ------------------------------------------------------------------ respuestas buenas (una por llamada)


def _cita(id_: str, campo: str) -> dict[str, str]:
    return {"id": id_, "campo": campo}


AFIRMACIONES: dict[str, Any] = {
    "afirmaciones": [
        {"id": "A1", "tipo": "declaración", "texto": "TVN Panamá reporta que Mulino anuncia un nuevo plan para el Canal de Panamá", "citas": [_cita(ID_TVN, "titulo")], "base": []},
        {"id": "A2", "tipo": "declaración", "texto": "Reuters informa que la autoridad del Canal reporta tránsitos récord", "citas": [_cita(ID_REUTERS, "titulo")], "base": []},
        {"id": "A3", "tipo": "hecho", "texto": "La inflación de Panamá fue de 2.9 % anual en 2023", "citas": [_cita(ID_IND, "valor"), _cita(ID_IND, "anio")], "base": []},
        {"id": "A4", "tipo": "inferencia", "texto": "El plan del Canal podría interesar a quien sigue la evolución de los precios", "citas": [], "base": ["A1", "A3"]},
    ]
}


def _o(texto: str, *afirmaciones: str, **extra: Any) -> dict[str, Any]:
    return {"texto": texto, "afirmaciones": list(afirmaciones), **extra}


def _preguntas() -> list[dict[str, str]]:
    return [
        {"texto": "¿Qué fuente oficial confirma el monto del plan?", "vacio": "V1"},
        {"texto": "¿Existe una cifra oficial para 2024?", "vacio": "V2"},
        {"texto": "¿Qué otros medios reportan el calendario?", "vacio": "V3"},
    ]


def _guion() -> list[dict[str, Any]]:
    frase = "Según reporta TVN Panamá, el presidente Mulino anunció un nuevo plan para el Canal de Panamá esta semana"
    partes = ["entrada", "entrada", "desarrollo", "desarrollo", "desarrollo", "desarrollo", "cierre", "cierre"]
    oraciones = [_o(frase + ".", "A1", parte=p) for p in partes]
    oraciones.insert(3, _o(MARCADOR, parte="desarrollo"))
    return oraciones


BUENAS: dict[str, Any] = {
    "afirmaciones": AFIRMACIONES,
    "titulo": {
        "titulo": _o("TVN reporta nuevo plan de Mulino para el Canal", "A1"),
        "titulares": [_o("Mulino anuncia plan para el Canal, según TVN", "A1"), _o("Reuters informa tránsitos récord en el Canal", "A2")],
        "copy_digital": [_o("TVN informa sobre un nuevo plan para el Canal. #Canal #Panamá", "A1")],
    },
    "brief": {
        "brief": [_o("TVN Panamá reporta que Mulino anuncia un nuevo plan para el Canal.", "A1"), _o("En 2023 la inflación anual fue de 2.9 %.", "A3")],
        "enfoque": [_o("El plan podría interesar a quien sigue los precios.", "A4")],
        "preguntas": _preguntas(),
    },
    "guion": {"guion": _guion()},
    "resumen_web": {"resumen_web": [_o("TVN Panamá reporta un nuevo plan para el Canal.", "A1"), _o("Reuters informa tránsitos récord.", "A2")]},
    "titulo_trabajo": {
        "titulo_trabajo": _o("Verificar el nuevo plan para el Canal que reporta TVN", "A1"),
        "enfoque": [_o("El plan podría interesar a quien sigue los precios.", "A4")],
        "preguntas": _preguntas(),
    },
}

CLAVES_SALIDA = ("afirmaciones", "titulo_trabajo", "titulo", "brief", "guion", "resumen_web")


def clave_de(esquema: dict[str, Any]) -> str:
    """Qué llamada es, según los campos del esquema que se pide (el paso 1 pide ``afirmaciones``)."""
    campos = esquema.get("properties", {})
    return next(k for k in CLAVES_SALIDA if k in campos)


class ProveedorGuionado:
    """Cumple ``Proveedor``. Responde según la llamada. Cada valor es una respuesta fija, una **tupla** (una respuesta por
    intento; la última se repite) o una función ``(system, usuario, n_intento)``. Una excepción se lanza."""

    nombre = "guionado"
    modelo = "guionado-0"

    def __init__(self, **respuestas: Any) -> None:
        self.respuestas: dict[str, Any] = {**BUENAS, **respuestas}
        self.llamadas: list[tuple[str, str, str]] = []  # (clave, system, usuario)
        self.ultimo_uso: UsoLlm | None = None

    @property
    def claves(self) -> list[str]:
        return [c for c, _, _ in self.llamadas]

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        clave = clave_de(esquema)
        n = self.claves.count(clave)
        self.llamadas.append((clave, system, usuario))
        r = self.respuestas[clave]
        if isinstance(r, tuple):
            r = r[min(n, len(r) - 1)]
        elif callable(r):
            r = r(system, usuario, n)
        self.ultimo_uso = UsoLlm(self.nombre, self.modelo, 100, 50, 0.01)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)


def fallo() -> ErrorProveedor:
    return ErrorProveedor("proveedor de prueba no disponible")


def modificada(base: dict[str, Any], fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Copia profunda de una respuesta buena con un cambio aplicado por ``fn``."""
    copia = json.loads(json.dumps(base))
    fn(copia)
    return copia
