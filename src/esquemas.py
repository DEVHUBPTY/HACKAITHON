"""Esquemas pydantic de las salidas del LLM y de los paquetes (editorial, investigación, boletín).

Por ahora solo existe el BORRADOR del paso 1 de la generación (afirmaciones citadas, E0-07).
Se completa en E1-12: citas por campo validadas contra la ficha, reglas por tipo (D-41) y los
límites de ``docs/salidas.md``.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TipoAfirmacion = Literal["hecho", "declaración", "inferencia", "hipótesis"]

# Prefijos de ID estables (CLAUDE.md, D-63). El patrón se valida en código y no en el JSON Schema
# que se pasa a Ollama, para no depender del soporte de ``pattern`` en su gramática.
PATRON_ID_REGISTRO = re.compile(r"^(NOT-[0-9a-f]{10}|IND-[A-Z]{3}-[^\s]+-\d{4}|SIS-\S+|SBP-\S+|GRP-\S+|CASO-\d+|SYN-\S+)$")


class Cita(BaseModel):
    """Cita válida = ID del registro + campo (ej. ``IND-PAN-FP.CPI.TOTL.ZG-2023`` · ``valor``)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="ID del registro de evidencia, exacto")
    campo: str = Field(min_length=1, description="Campo del registro, exacto")

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


# =====================================================================================================================
# E1-12 · SALIDAS DE LA GENERACIÓN (docs/salidas.md). Sección independiente para facilitar la integración con la Ficha (E1-10b).
# Campos exactos de cada paquete; el origen de cada uno (LLM · Ficha · Regla) está en el comentario de su campo.
# =====================================================================================================================

TipoParteGuion = Literal["entrada", "desarrollo", "cierre"]


class OracionLlm(BaseModel):
    """Lo que devuelve el LLM por oración: texto y los ``id`` de las afirmaciones validadas en que se apoya (D-22)."""

    model_config = ConfigDict(extra="forbid")

    texto: str = Field(min_length=1)
    afirmaciones: list[str] = Field(default_factory=list, description="id de afirmaciones validadas, p. ej. A1")


class OracionGuionLlm(OracionLlm):
    """Oración del guion: entrada, desarrollo o cierre."""

    parte: TipoParteGuion


class PreguntaLlm(BaseModel):
    """Pregunta de investigación y el vacío de la ficha que la origina (D-43)."""

    model_config = ConfigDict(extra="forbid")

    texto: str = Field(min_length=1)
    vacio: str = Field(min_length=1, description="id del vacío de la ficha, exacto")


class SalidaTitulos(BaseModel):
    """Grupo 1 (D-44): título + titulares + copy digital."""

    model_config = ConfigDict(extra="forbid")

    titulo: OracionLlm
    titulares: list[OracionLlm]
    copy_digital: list[OracionLlm]


class SalidaBrief(BaseModel):
    """Grupo 2 (D-44): brief + enfoque + preguntas."""

    model_config = ConfigDict(extra="forbid")

    brief: list[OracionLlm]
    enfoque: list[OracionLlm]
    preguntas: list[PreguntaLlm]


class SalidaGuion(BaseModel):
    """Grupo 3 (D-44): guion."""

    model_config = ConfigDict(extra="forbid")

    guion: list[OracionGuionLlm]


class SalidaResumen(BaseModel):
    """Grupo 4 (D-44): resumen web."""

    model_config = ConfigDict(extra="forbid")

    resumen_web: list[OracionLlm]


class SalidaInvestigacion(BaseModel):
    """Paquete de investigación (D-42): título de trabajo + enfoque + preguntas, en una sola llamada."""

    model_config = ConfigDict(extra="forbid")

    titulo_trabajo: OracionLlm
    enfoque: list[OracionLlm]
    preguntas: list[PreguntaLlm]


class Oracion(BaseModel):
    """Oración de un paquete, ya validada: cita al menos una afirmación (salvo un marcador ``[VISUAL: …]``)."""

    model_config = ConfigDict(extra="forbid")

    texto: str
    afirmaciones: list[str]
    parte: TipoParteGuion | None = None


class PreguntaInvestigacion(BaseModel):
    """Pregunta de investigación con el vacío de la ficha que la origina."""

    model_config = ConfigDict(extra="forbid")

    texto: str
    vacio: str


class CitaSalida(BaseModel):
    """Cita de una afirmación (ID + campo). ``traducido`` marca titulares que no están en el idioma base (D-45)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    campo: str
    traducido: bool = False


class AfirmacionSalida(BaseModel):
    """Afirmación validada que respalda las oraciones del paquete."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tipo: TipoAfirmacion
    texto: str
    citas: list[CitaSalida] = Field(default_factory=list)
    base: list[str] = Field(default_factory=list)


class Vacio(BaseModel):
    """Lo que falta: un vacío de la ficha (origen ``ficha``) o una sección que no se pudo redactar (origen ``seccion``)."""

    model_config = ConfigDict(extra="forbid")

    origen: Literal["ficha", "seccion"]
    referencia: str
    motivo: str


class PaqueteBase(BaseModel):
    """Campos comunes a toda salida (docs/salidas.md): marca de borrador, caso, versión y leyenda de alcance (D-51)."""

    model_config = ConfigDict(extra="forbid")

    marca: str  # Regla: ``marca_borrador`` de config/restricciones.yaml
    id_caso: str  # Ficha
    version: int  # Ficha
    leyenda_alcance: str  # Regla: ``leyendas_alcance`` de config/restricciones.yaml
    accion: str  # Ficha: la acción recomendada (D-42)
    forzado: bool = False  # Regla: la persona forzó el paquete completo (queda registrado)
    vacios: list[Vacio] = Field(default_factory=list)  # Regla
    afirmaciones: list[AfirmacionSalida] = Field(default_factory=list)  # Paso 1, validadas


class PaqueteEditorial(PaqueteBase):
    """Paquete editorial (TVN), docs/salidas.md §1."""

    titulo: Oracion | None = None  # LLM
    titulares: list[Oracion] = Field(default_factory=list)  # LLM
    enfoque: list[Oracion] = Field(default_factory=list)  # LLM
    brief: list[Oracion] = Field(default_factory=list)  # LLM
    preguntas: list[PreguntaInvestigacion] = Field(default_factory=list)  # LLM sobre vacíos
    fuentes_verificaciones: list[str] = Field(default_factory=list)  # Ficha, sin LLM (D-43)
    guion: list[Oracion] = Field(default_factory=list)  # LLM
    resumen_web: list[Oracion] = Field(default_factory=list)  # LLM
    copy_digital: list[Oracion] = Field(default_factory=list)  # LLM


class PaqueteInvestigacion(PaqueteBase):
    """Paquete de investigación (D-42): sin brief, guion, copy, titulares ni resumen web."""

    titulo_trabajo: Oracion | None = None  # LLM
    enfoque: list[Oracion] = Field(default_factory=list)  # LLM
    preguntas: list[PreguntaInvestigacion] = Field(default_factory=list)  # LLM sobre vacíos
    fuentes_verificaciones: list[str] = Field(default_factory=list)  # Ficha, sin LLM (D-43)


class SectorRelacionado(BaseModel):
    """Sector potencialmente relacionado y el motivo (mapeo tema → sector)."""

    model_config = ConfigDict(extra="forbid")

    sector: str
    motivo: str


class BoletinBanca(PaqueteBase):
    """Boletín de entorno (banca), docs/salidas.md §2. Solo el esquema: la generación es de E2-02."""

    observaciones: list[Oracion] = Field(default_factory=list)  # LLM: hecho o declaración
    hipotesis_impacto: list[Oracion] = Field(default_factory=list)  # LLM: inferencia o hipótesis
    sectores: list[SectorRelacionado] = Field(default_factory=list)  # Regla
    horizonte: Literal["inmediato", "corto plazo", "estructural"] | None = None  # Regla
    evidencia: list[str] = Field(default_factory=list)  # Ficha
    preguntas: list[PreguntaInvestigacion] = Field(default_factory=list)  # LLM sobre vacíos
    aviso: str = ""  # Regla: ``aviso_banca`` de config/restricciones.yaml
