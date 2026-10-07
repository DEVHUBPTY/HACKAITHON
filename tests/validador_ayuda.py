"""Ayudas de las pruebas del validador (E1-13): una ficha con titulares, un dato anual y un conteo, y constructores de afirmaciones."""

from __future__ import annotations

from typing import Any

from src.esquemas import Afirmacion, AfirmacionSalida, Cita, CitaSalida, Oracion
from src.generacion import ContradiccionFicha, EntradaFicha, RegistroEvidencia, VacioFicha
from src.validador import Contexto

ID_TVN = "NOT-aaaaaaaaaa"
ID_REUTERS = "NOT-bbbbbbbbbb"
ID_PRENSA = "NOT-cccccccccc"
ID_ENTREVISTA = "NOT-dddddddddd"
ID_CITA = "NOT-eeeeeeeeee"
ID_IND = "IND-PAN-FP.CPI.TOTL.ZG-2023"
ID_IND_DECIMAL = "IND-PAN-NY.GDP.MKTP.KD.ZG-2022"
ID_GRP = "GRP-0123456789"
MARCADOR = "[VISUAL: a definir por producción]"
LEYENDA = "basado únicamente en titular/metadatos"
LEYENDA_DESCRIPCION = "basado en titular, descripción del RSS y metadatos; no se leyó el artículo completo"

TITULAR_TVN = "Mulino anuncia nuevo plan para el Canal de Panamá"
TITULAR_PRENSA = "Inundaciones causaron pérdidas en Chiriquí, según autoridades; la oposición llama corrupto a Mulino"
TITULAR_ENTREVISTA = "Ministro dice en entrevista con Telemetro que habrá nuevo calendario"
TITULAR_CITA = 'Ministro afirma: "no habrá más retrasos en la obra" este lunes'


def ficha(**cambios: Any) -> EntradaFicha:
    datos: dict[str, Any] = {
        "id_caso": "GRP-0123456789",
        "accion": "Producir borrador",
        "uso_descripcion": False,
        "registros": [
            RegistroEvidencia(id=ID_TVN, idioma="es", campos={"titulo": TITULAR_TVN}, contexto={"medio": "TVN Panamá", "fecha_publicacion": "2026-10-05T10:00:00Z"}),
            RegistroEvidencia(id=ID_REUTERS, idioma="en", campos={"titulo": "Panama Canal authority reports record transits"}, contexto={"medio": "Reuters", "fecha_publicacion": "2026-10-05T12:00:00Z"}),
            RegistroEvidencia(id=ID_PRENSA, idioma="es", campos={"titulo": TITULAR_PRENSA}, contexto={"medio": "La Prensa", "fecha_publicacion": "2026-10-04T08:00:00Z"}),
            RegistroEvidencia(id=ID_ENTREVISTA, idioma="es", campos={"titulo": TITULAR_ENTREVISTA}, contexto={"medio": "Telemetro", "fecha_publicacion": "2026-10-03T08:00:00Z"}),
            RegistroEvidencia(id=ID_CITA, idioma="es", campos={"titulo": TITULAR_CITA}, contexto={"medio": "Panamá América", "fecha_publicacion": "2026-10-03T09:00:00Z"}),
            RegistroEvidencia(id=ID_IND, campos={"valor": "2.9 % anual"}, contexto={"anio": "2023", "indicador": "Inflación"}),
            RegistroEvidencia(id=ID_IND_DECIMAL, campos={"valor": "1.5 %"}, contexto={"anio": "2022", "indicador": "Crecimiento"}),
            RegistroEvidencia(id=ID_GRP, campos={"n_titulares": "5", "n_medios": "3", "n_procedencias": "2"}),
        ],
        "vacios": [VacioFicha(id="V1", descripcion="Falta confirmar el monto"), VacioFicha(id="V2", descripcion="No hay cifra oficial para 2024"), VacioFicha(id="V3", descripcion="Solo un medio reporta el calendario")],
        "fuentes_verificaciones": [],
        "contradicciones": [],
    }
    datos.update(cambios)
    return EntradaFicha(**datos)


def contexto(f: EntradaFicha | None = None, grupos: tuple[str, ...] = ("comunes", "editorial")) -> Contexto:
    return Contexto(f or ficha(), grupos)


def afirmacion(id_: str, tipo: str, texto: str, *citas: tuple[str, str], base: tuple[str, ...] = ()) -> Afirmacion:
    return Afirmacion.model_validate({"id": id_, "tipo": tipo, "texto": texto, "citas": [{"id": i, "campo": c} for i, c in citas], "base": list(base)})


def salida(id_: str, tipo: str, texto: str, *citas: tuple[str, str], base: tuple[str, ...] = ()) -> AfirmacionSalida:
    return AfirmacionSalida(id=id_, tipo=tipo, texto=texto, citas=[CitaSalida(id=i, campo=c) for i, c in citas], base=list(base))  # type: ignore[arg-type]


def con_afirmaciones(ctx: Contexto, *afirmaciones: AfirmacionSalida) -> Contexto:
    ctx.afirmaciones = {a.id: a for a in afirmaciones}
    return ctx


# Un juego de afirmaciones ya validadas que las pruebas de secciones reutilizan.
A_DECL = ("A1", "declaración", "TVN Panamá reporta que Mulino anuncia nuevo plan para el Canal de Panamá", (ID_TVN, "titulo"))
A_IND = ("A2", "hecho", "La inflación de Panamá fue de 2.9 % anual en 2023", (ID_IND, "valor"))
A_CONTEO = ("A3", "hecho", "3 medios reportan el tema", (ID_GRP, "n_medios"))
A_INF = ("A4", "inferencia", "El plan podría interesar a quien sigue la evolución de los precios", None)
A_HIP = ("A5", "hipótesis", "El plan podría afectar los precios, a verificar", None)


def afirmaciones_base() -> list[AfirmacionSalida]:
    return [
        salida("A1", "declaración", A_DECL[2], (ID_TVN, "titulo")),
        salida("A2", "hecho", A_IND[2], (ID_IND, "valor")),
        salida("A3", "hecho", A_CONTEO[2], (ID_GRP, "n_medios")),
        salida("A4", "inferencia", A_INF[2], base=("A1", "A2")),
        salida("A5", "hipótesis", A_HIP[2], base=("A1", "A2")),
    ]


def ctx_con_base(f: EntradaFicha | None = None) -> Contexto:
    return con_afirmaciones(contexto(f), *afirmaciones_base())


def o(texto: str, *afirmaciones: str, parte: str | None = None) -> Oracion:
    return Oracion(texto=texto, afirmaciones=list(afirmaciones), parte=parte)  # type: ignore[arg-type]


def relleno(n: int, *afirmaciones: str, por_oracion: int = 10) -> list[Oracion]:
    """``n`` palabras en oraciones de ``por_oracion`` palabras que citan afirmaciones sin cifras ni nombres (A3 por defecto)."""
    cita = afirmaciones or ("A3",)
    oraciones: list[Oracion] = []
    while n > 0:
        k = min(por_oracion, n)
        oraciones.append(o(" ".join(["tema"] * k) + ".", *cita))
        n -= k
    return oraciones


def reglas(rechazos: list[Any]) -> set[str]:
    return {r.regla for r in rechazos}


def contradiccion() -> list[ContradiccionFicha]:
    return [ContradiccionFicha(id_a=ID_TVN, id_b=ID_PRENSA, fragmento_a="nuevo plan", fragmento_b="llama corrupto")]
