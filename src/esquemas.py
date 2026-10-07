"""Esquemas pydantic de las salidas del LLM y de los paquetes (editorial, investigación, boletín).

Por ahora solo existe el BORRADOR del paso 1 de la generación (afirmaciones citadas, E0-07).
Se completa en E1-12: citas por campo validadas contra la ficha, reglas por tipo (D-41) y los
límites de ``docs/salidas.md``.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.configuracion import FORMAS_DE_PUBLICAR

TipoAfirmacion = Literal["hecho", "declaración", "inferencia", "hipótesis"]

# Prefijos de ID estables (CLAUDE.md, D-63). El patrón se valida en código y no en el JSON Schema
# que se pasa a Ollama, para no depender del soporte de ``pattern`` en su gramática.
PATRON_ID_REGISTRO = re.compile(r"^(NOT-[0-9a-f]{10}|IND-[A-Z]{3}-[^\s]+-\d{4}|SIS-\S+|SBP-\S+|GRP-\S+|CASO-\d+|SYN-\S+)$")


class Cita(BaseModel):
    """Cita válida = ID del registro + campo (ej. ``IND-PAN-FP.CPI.TOTL.ZG-2023`` · ``valor``)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="ID del registro de evidencia, exacto")
    campo: str = Field(min_length=1, description="Campo del registro, exacto")

    def formato(self) -> str:
        """La cita como la ve la persona: ``ID · campo``."""
        return f"{self.id} · {self.campo}"

    @field_validator("id")
    @classmethod
    def _id_con_prefijo(cls, valor: str) -> str:
        if not PATRON_ID_REGISTRO.match(valor):
            raise ValueError(f"ID sin prefijo estable válido: {valor!r}")
        return valor


class Afirmacion(BaseModel):
    """Una afirmación atómica.

    hecho/declaración citan fuentes; inferencia/hipótesis citan las afirmaciones en que se basan.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="A1, A2, A3...")
    tipo: TipoAfirmacion
    texto: str = Field(min_length=1)
    citas: list[Cita] = Field(default_factory=list)
    base: list[str] = Field(default_factory=list, description="id de afirmaciones base")

    @model_validator(mode="after")
    def _reglas_por_tipo(self) -> Afirmacion:
        if self.tipo in ("hecho", "declaración") and not self.citas:
            raise ValueError(f"{self.id}: {self.tipo} requiere al menos una cita")
        if self.tipo in ("inferencia", "hipótesis") and not self.base:
            raise ValueError(f"{self.id}: {self.tipo} requiere afirmaciones base")
        return self


class AfirmacionesCitadas(BaseModel):
    """Salida del paso 1: lista de afirmaciones citadas (BORRADOR, E1-12 lo completa)."""

    model_config = ConfigDict(extra="forbid")

    afirmaciones: list[Afirmacion] = Field(min_length=1)


def esquema_json_afirmaciones() -> dict[str, Any]:
    """JSON Schema de ``AfirmacionesCitadas``, para el parámetro ``format`` de Ollama."""
    return AfirmacionesCitadas.model_json_schema()


class ParComparado(BaseModel):
    """Resultado de comparar dos titulares candidatos a contradicción (D-23).

    El LLM solo dice si el par es una **posible** contradicción y cita, literalmente, el fragmento de cada titular en que se
    nota. No hay texto libre: lo que se muestra al usuario es la etiqueta fija de ``config/prioridad.yaml``.
    """

    model_config = ConfigDict(extra="forbid")

    id_a: str = Field(min_length=1, description="ID de la noticia A, exacto")
    id_b: str = Field(min_length=1, description="ID de la noticia B, exacto")
    posible_contradiccion: bool
    fragmento_a: str = Field(default="", description="Fragmento literal del titular A; vacío si no hay posible contradicción")
    fragmento_b: str = Field(default="", description="Fragmento literal del titular B; vacío si no hay posible contradicción")

    @model_validator(mode="after")
    def _con_fragmentos(self) -> ParComparado:
        if self.posible_contradiccion and not (self.fragmento_a.strip() and self.fragmento_b.strip()):
            raise ValueError(f"{self.id_a}/{self.id_b}: una posible contradicción cita un fragmento literal de cada titular")
        return self


class ComparacionContradicciones(BaseModel):
    """Salida de la comparación de los pares candidatos de un grupo (uno por par, en cualquier orden)."""

    model_config = ConfigDict(extra="forbid")

    pares: list[ParComparado] = Field(min_length=1)


def esquema_json_comparacion() -> dict[str, Any]:
    """JSON Schema de ``ComparacionContradicciones``, para el parámetro ``format`` de Ollama."""
    return ComparacionContradicciones.model_json_schema()


# ======================================================================================================================
# E1-10b · Ficha de evidencia (etapa 5 del reto). Una sola ficha para ambas modalidades: DuckDB -> ``Ficha`` -> vista,
# Markdown y ``fichas.jsonl`` (``src/ficha.py``). Sin LLM (D-36). Las salidas de E1-12 (paquetes y boletín) van en otra sección.
# ======================================================================================================================

PREFIJOS_DE_HECHO = ("GRP-", "IND-", "SIS-", "SBP-")        # un hecho es un conteo o un dato oficial (CLAUDE.md)
PREFIJO_DE_DECLARACION = "NOT-"                            # un titular es lo que un medio reporta: declaración, nunca hecho
ETIQUETA_BORRADOR = "BORRADOR · requiere revisión"


class ModeloFicha(BaseModel):
    """Base de la ficha: sin campos de más."""

    model_config = ConfigDict(extra="forbid")


class VersionContradiccion(ModeloFicha):
    id: str = Field(min_length=1, description="NOT- del titular")
    medio: str
    titular: str
    fecha_publicacion: str | None = None


class ContradiccionFicha(ModeloFicha):
    """Un par con versiones distintas: siempre «posible contradicción, verificar» (D-23). La nota del LLM solo anota (X21)."""

    etiqueta: str = Field(min_length=1)
    version_a: VersionContradiccion
    version_b: VersionContradiccion
    detalle: str
    nota_llm: Literal["posible_contradiccion", "compatible", "pendiente"]
    fragmento_a: str | None = None
    fragmento_b: str | None = None


class TitularCentral(ModeloFicha):
    id_noticia: str = Field(min_length=1)
    titular: str = Field(min_length=1)
    medio: str
    url: str


class Cobertura(ModeloFicha):
    n_titulares: int = Field(ge=1)
    n_medios: int = Field(ge=1)
    fecha_inicio: str | None = None          # ISO 8601 UTC; la hora de Panamá solo se aplica al mostrar
    fecha_fin: str | None = None
    origen_fecha_inicio: str | None = None   # publicacion o deteccion: nunca se mezclan sin decirlo
    origen_fecha_fin: str | None = None


class QueSeReporta(ModeloFicha):
    tema: str | None = None
    subtema: str | None = None
    titular_central: TitularCentral
    cobertura: Cobertura
    contradicciones: list[ContradiccionFicha]
    advertencias: list[str]
    recirculada: bool


class TitularReportado(ModeloFicha):
    """Un titular y quién lo reporta. Solo agencia y tipo de firma: nunca el nombre de un autor (D-32)."""

    id_noticia: str = Field(min_length=1)
    titular: str
    medio: str
    dominio: str
    pais_medio: str | None = None
    agencia: str | None = None
    tipo_firma: str
    fecha_publicacion: str | None = None      # nula = desconocida; nunca se sustituye por la detección
    url: str
    idioma: str | None = None
    sospechoso_inyeccion: bool
    procedencia: int | None = None


class DetalleProcedencia(ModeloFicha):
    orden: int = Field(ge=1)
    etiqueta: str
    reglas: list[str]
    n_titulares: int = Field(ge=1)
    medios: list[str]
    ids_noticia: list[str]


class ProcedenciasFicha(ModeloFicha):
    n: int = Field(ge=0)
    estimado: bool
    explicacion: str
    detalle: list[DetalleProcedencia]


class MedioReferenciaFicha(ModeloFicha):
    """«¿El medio de referencia ya lo cubrió?» según los titulares del snapshot."""

    nombre: str
    dominio: str
    cubrio: bool
    n_titulares: int = Field(ge=0)
    ids_noticia: list[str]
    texto: str


class QuienLoReporta(ModeloFicha):
    titulares: list[TitularReportado] = Field(min_length=1)
    procedencias: ProcedenciasFicha
    medio_referencia: MedioReferenciaFicha | None = None


class LineaRespaldo(ModeloFicha):
    """Una línea de «qué está respaldado»: siempre con cita ``ID + campo``. Hecho = conteo o dato oficial; declaración = atribuida a un medio."""

    tipo: Literal["hecho", "declaración"]
    texto: str = Field(min_length=1)
    citas: list[Cita] = Field(min_length=1)
    limitacion: str | None = None
    atribucion: str | None = None
    fecha: str | None = None     # ISO 8601 UTC de un evento; la hora de Panamá solo se aplica al mostrar

    @model_validator(mode="after")
    def _reglas_por_tipo(self) -> LineaRespaldo:
        if self.tipo == "hecho" and not all(c.id.startswith(PREFIJOS_DE_HECHO) for c in self.citas):
            raise ValueError("un hecho solo cita conteos (GRP-) o datos oficiales (IND-, SIS-, SBP-)")
        if self.tipo == "declaración":
            if not self.atribucion:
                raise ValueError("una declaración se atribuye a un medio")
            if not all(c.id.startswith(PREFIJO_DE_DECLARACION) for c in self.citas):
                raise ValueError("una declaración cita el titular (NOT-)")
        return self


class Respaldado(ModeloFicha):
    reportes: list[LineaRespaldo] = Field(min_length=1)
    datos_oficiales: list[LineaRespaldo]
    eventos_oficiales: list[LineaRespaldo]
    declaraciones: list[LineaRespaldo]

    @model_validator(mode="after")
    def _cada_lista_con_lo_suyo(self) -> Respaldado:
        if any(x.tipo != "hecho" for x in (*self.reportes, *self.datos_oficiales, *self.eventos_oficiales)):
            raise ValueError("reportes y datos o eventos oficiales son hechos")
        if any(x.tipo != "declaración" for x in self.declaraciones):
            raise ValueError("lo que dicen los titulares son declaraciones")
        if any(not c.id.startswith("GRP-") for x in self.reportes for c in x.citas):
            raise ValueError("un conteo cita al grupo")
        if any(not c.id.startswith(("IND-", "SBP-")) for x in self.datos_oficiales for c in x.citas):
            raise ValueError("un dato oficial cita un indicador")
        if any(not c.id.startswith("SIS-") for x in self.eventos_oficiales for c in x.citas):
            raise ValueError("un evento oficial cita un sismo")
        return self


class VacioFicha(ModeloFicha):
    codigo: str = Field(min_length=1)
    texto: str = Field(min_length=1)
    verificacion: str = Field(min_length=1)


class FuenteSugerida(ModeloFicha):
    """Sugerencia para verificar (D-37): nunca evidencia ni con formato de cita."""

    nombre: str = Field(min_length=1)
    origen: Literal["subtema", "tema", "modalidad"]

    @field_validator("nombre")
    @classmethod
    def _sin_formato_de_cita(cls, v: str) -> str:
        if PATRON_ID_REGISTRO.match(v) or " · " in v:
            raise ValueError("una fuente sugerida no lleva formato de cita")
        return v


class FaltaComprobar(ModeloFicha):
    principales: list[VacioFicha]
    otros: list[VacioFicha]
    fuentes_sugeridas: list[FuenteSugerida]
    aviso_fuentes: str


class AccionRecomendada(ModeloFicha):
    """Celda (rango × estado de evidencia) de la tabla de la modalidad. Nunca habilita publicar ni una alerta definitiva."""

    accion: str = Field(min_length=1)
    motivo: str = Field(min_length=1)
    rango: Literal["bajo", "medio", "alto"]
    estado_evidencia: Literal["insuficiente", "parcial", "suficiente"]
    siguientes_pasos: list[str]
    habilita_publicar: Literal[False] = False

    @model_validator(mode="after")
    def _sin_publicar(self) -> AccionRecomendada:
        if FORMAS_DE_PUBLICAR.search(" ".join([self.accion, self.motivo, *self.siguientes_pasos])):
            raise ValueError("ninguna acción habilita publicar")
        return self


class ComponentePuntaje(ModeloFicha):
    valor: float = Field(ge=0, le=1)
    explicacion: dict[str, Any]


class PuntajeFicha(ModeloFicha):
    """P de E1-10, con su desglose. Ordena la atención: no es una probabilidad de verdad ni de pérdida."""

    puntaje: float = Field(ge=0, le=100)
    rango: Literal["bajo", "medio", "alto"]
    posicion: int = Field(ge=1)
    version_reglas: str
    fecha_referencia: str
    componentes: dict[str, ComponentePuntaje]
    habilita_publicacion: Literal[False] = False


class Ficha(ModeloFicha):
    """Ficha de evidencia de un grupo: las cinco partes de la etapa 5 del reto, todas obligatorias."""

    id_grupo: str = Field(min_length=1)
    modalidad: str = Field(min_length=1)
    borrador: Literal[True] = True
    marca_borrador: str
    alcance: str = Field(min_length=1, description="Leyenda de alcance (D-51)")
    puntaje: PuntajeFicha
    que_se_reporta: QueSeReporta
    quien_lo_reporta: QuienLoReporta
    respaldado: Respaldado
    falta_comprobar: FaltaComprobar
    accion_recomendada: AccionRecomendada
