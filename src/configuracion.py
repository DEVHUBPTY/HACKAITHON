"""Carga de configuración validada (D-79).

Todo YAML de ``config/`` se lee con ``yaml.safe_load`` y se valida con un modelo pydantic que
prohíbe claves desconocidas y coerciones de tipo. Así se detectan sangrías rotas, claves mal
escritas y trampas de YAML como ``no`` → ``False``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Literal, TypeVar, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from src import consultas_gdelt

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_CONFIG = RAIZ / "config"

T = TypeVar("T", bound=BaseModel)


class ErrorDeConfiguracion(ValueError):
    """El YAML no existe, no se puede leer o no cumple su modelo."""


class ModeloConfig(BaseModel):
    """Base de todos los modelos de configuración: sin claves extra y sin coerción de tipos."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def cargar_config(nombre: str, modelo: type[T], carpeta: Path | None = None) -> T:
    """Lee ``config/<nombre>.yaml`` con ``safe_load`` y lo valida con ``modelo``.

    Lanza ``ErrorDeConfiguracion`` nombrando el archivo y cada campo inválido.
    """
    ruta = (carpeta or CARPETA_CONFIG) / f"{nombre}.yaml"
    try:
        with ruta.open(encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except OSError as exc:
        raise ErrorDeConfiguracion(f"{ruta.name}: no se pudo leer ({exc})") from exc
    except yaml.YAMLError as exc:
        raise ErrorDeConfiguracion(f"{ruta.name}: YAML inválido ({exc})") from exc
    try:
        return modelo.model_validate(datos)
    except ValidationError as exc:
        detalle = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(raíz)'}: {e['msg']}" for e in exc.errors()
        )
        raise ErrorDeConfiguracion(f"{ruta.name}: {detalle}") from exc


def _compilar_todas(patrones: list[str], donde: str) -> None:
    """Falla con un mensaje claro si algún patrón no es una expresión regular válida."""
    for p in patrones:
        try:
            re.compile(p)
        except re.error as exc:
            raise ValueError(f"{donde}: patrón inválido {p!r} ({exc})") from exc


# ------------------------------------------------------------------ fuentes.yaml


class General(ModeloConfig):
    agente_http: str
    timeout_segundos: int
    reintentos: int
    espera_reintento_segundos: int
    alcance_texto: str
    idioma_por_defecto: str
    carpeta_registro: str


class VentanaNoticias(ModeloConfig):
    dias_base: int
    dias_maximo: int
    # Si es true y con dias_base no se alcanza el mínimo de noticias, la extracción amplía hasta
    # dias_maximo. Si es false, solo avisa y no amplía (docs/parametros.md).
    ampliar_si_no_alcanza_minimo: bool
    base_de_medicion: str
    intervalo_pdf_seccion_7_no_aplicado: list[str]


class VolumenNoticias(ModeloConfig):
    meta: int
    minimo: int
    minimo_tvn: int


class MedioConocido(ModeloConfig):
    nombre: str
    pais: str
    condiciones: str


class UrlCanonica(ModeloConfig):
    esquema: str
    quitar_prefijo_www: bool
    quitar_prefijo_movil: bool
    sufijos_ruta_amp: list[str]
    parametros_con_valor_a_quitar: dict[str, list[str]]
    parametros_a_quitar: list[str]


class RssTvn(ModeloConfig):
    url: str
    carpeta_cruda: str
    segmentos_minimos_para_seccion: int
    tema_sin_seccion: str


class PataConsulta(ModeloConfig):
    """Una llamada a GDELT por (tema, rango): filtros de operador + términos unidos con OR."""

    descripcion: str
    filtros: list[str]
    terminos: list[str]


class Gdelt(ModeloConfig):
    endpoint: str
    modo: str
    formato: str
    orden: str
    maxrecords: int
    pausa_segundos: int
    espera_429_segundos: int
    max_intentos: int
    rango_dias: int
    rango_minimo_horas: int
    carpeta_cruda: str
    idiomas: dict[str, str]
    # tema de origen (D-62) -> pata ('locales', 'internacional') -> definición; ver src/consultas_gdelt.py
    consultas: dict[str, dict[str, PataConsulta]]
    motivo_cambio_consultas: str
    # Consultas reemplazadas (tema -> consulta antigua): sus crudos siguen en raw/ pero no alimentan el snapshot (D-83).
    consultas_historicas: dict[str, str]
    largo_minimo_termino: int

    @model_validator(mode="after")
    def _consultas_validas(self) -> "Gdelt":
        for patas in self.consultas.values():
            for pata in patas.values():
                consultas_gdelt.construir_consulta(pata.model_dump(), self.largo_minimo_termino)  # ValueError si no sirve
        return self


class Indicador(ModeloConfig):
    nombre: str
    unidad: str


class BancoMundial(ModeloConfig):
    base_url: str
    paises: list[str]
    anio_inicio: int
    anio_fin: int
    per_page: int
    cuadricula_declarada_en_pdf: int
    licencia: str
    carpeta_cruda: str
    pausa_segundos: int
    indicadores: dict[str, Indicador]


class Usgs(ModeloConfig):
    endpoint: str
    formato: str
    starttime: str
    endtime: str
    minlatitude: int
    maxlatitude: int
    minlongitude: int
    maxlongitude: int
    minmagnitude: int
    orderby: str
    licencia: str
    carpeta_cruda: str


class ConfigFuentes(ModeloConfig):
    """Modelo de ``config/fuentes.yaml``."""

    general: General
    ventana_noticias: VentanaNoticias
    volumen_noticias: VolumenNoticias
    medios_conocidos: dict[str, MedioConocido]
    medio_tvn_dominio: str
    url_canonica: UrlCanonica
    rss_tvn: RssTvn
    gdelt: Gdelt
    banco_mundial: BancoMundial
    usgs: Usgs
    paises_es: dict[str, str]


def cargar_fuentes(carpeta: Path | None = None) -> ConfigFuentes:
    """Atajo para ``config/fuentes.yaml``."""
    return cargar_config("fuentes", ConfigFuentes, carpeta)



# ------------------------------------------------------------------ llm.yaml


class OllamaConfig(ModeloConfig):
    host_por_defecto: str
    timeout_segundos: int
    keep_alive_durante_prueba: str


class GeneracionConfig(ModeloConfig):
    temperatura: float
    semilla: int
    num_ctx: int
    num_predict: int
    pensar: bool


class MuestraConfig(ModeloConfig):
    medio: str
    idioma: str
    titulares_por_tema: dict[str, int]


class PruebaConfig(ModeloConfig):
    repeticiones: int
    calentamiento: int
    prompt: str
    confianza: float
    marcadores_atribucion: list[str]
    muestra: MuestraConfig


class CriterioD02(ModeloConfig):
    mediana_max_segundos: float
    invalidos_max_por_diez: int
    validador_rechazo_max: float


class EntornoConfig(ModeloConfig):
    longitud_minima_secreto: int


class ConfigLlm(ModeloConfig):
    """Modelo de ``config/llm.yaml``."""

    ollama: OllamaConfig
    generacion: GeneracionConfig
    prueba: PruebaConfig
    entorno: EntornoConfig
    criterio_d02: CriterioD02


def cargar_llm(carpeta: Path | None = None) -> ConfigLlm:
    """Atajo para ``config/llm.yaml``."""
    return cargar_config("llm", ConfigLlm, carpeta)


# ------------------------------------------------------------------ local.env


def leer_local_env(ruta: Path | None = None) -> dict[str, str]:
    """Lee ``local.env`` (``CLAVE=VALOR``, ``#`` comenta) sin tocar ``os.environ``.

    Los valores de claves sensibles (``*_KEY``, ``*_TOKEN``, ``*_SECRET``) se registran para
    que el logging los redacte (D-69) si miden al menos ``entorno.longitud_minima_secreto``.
    Un comentario en línea (`` # ...``) se descarta en valores sin comillas. Si el archivo no
    existe devuelve un dict vacío.
    """
    from src.registro import SUFIJOS_SENSIBLES, registrar_sensible

    minimo = cargar_llm().entorno.longitud_minima_secreto
    ruta = ruta or RAIZ / "local.env"
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    valores: dict[str, str] = {}
    for linea in lineas:
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        clave = clave.strip().removeprefix("export ").strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        else:
            valor = re.split(r"\s+#", valor, maxsplit=1)[0].strip()  # comentario en línea
        valores[clave] = valor
        if clave.upper().endswith(SUFIJOS_SENSIBLES) and len(valor) >= minimo:
            registrar_sensible(valor)
    return valores

# ------------------------------------------------------------------ carga.yaml (E1-02)


class ArchivosCarga(ModeloConfig):
    """Nombres de los cuatro archivos del snapshot que lee la carga."""

    noticias: str
    indicadores: str
    eventos: str
    fuentes: str


class SalidaCarga(ModeloConfig):
    """Salidas de la carga y parámetros del reporte."""

    errores: str
    reporte: str
    max_caracteres_valor_en_errores: int
    top_medios_concentracion: int
    z_intervalo_confianza: float
    carpeta_validos: str


class FechaIso(ModeloConfig):
    """Formato ISO 8601 UTC con ``Z``: patrón de sintaxis y formato de ``strptime`` (fecha real)."""

    patron: str
    formato: str


class FechasCarga(ModeloConfig):
    """Formatos de fecha que acepta la carga (solo el de ``data/processed/``)."""

    iso_utc: FechaIso


class NoticiasCarga(ModeloConfig):
    """Reglas de ``noticias.csv``: críticos, alternativas de fecha y columnas a validar."""

    patron_id: str
    criticos: list[str]
    fechas_alternativas: list[str]
    fecha_opcional: list[str]
    opcionales: list[str]
    columnas_fecha: list[str]
    columnas_url: list[str]


class IndicadoresCarga(ModeloConfig):
    """Reglas de ``indicadores.csv``: patrones, críticos, rango de año y clave única."""

    patron_id: str
    patron_pais: str
    patron_anio: str
    criticos: list[str]
    anio_minimo: int
    anio_maximo: int
    clave: list[str]


class EventosCarga(ModeloConfig):
    """Reglas de ``eventos.geojson``: patrón de id, críticos y límites de coordenadas."""

    patron_id: str
    criticos: list[str]
    latitud_maxima: int
    longitud_maxima: int


class FuentesCarga(ModeloConfig):
    """Reglas de ``fuentes.json``: campos críticos."""

    criticos: list[str]


class ConfigCarga(ModeloConfig):
    """Modelo de ``config/carga.yaml``."""

    archivos: ArchivosCarga
    salida: SalidaCarga
    fechas: FechasCarga
    patron_url: str
    noticias: NoticiasCarga
    indicadores: IndicadoresCarga
    eventos: EventosCarga
    fuentes: FuentesCarga


def cargar_carga(carpeta: Path | None = None) -> ConfigCarga:
    """Atajo para ``config/carga.yaml``."""
    return cargar_config("carga", ConfigCarga, carpeta)


# ------------------------------------------------------------------ contrato.yaml (única fuente de campos)


class ConfigContrato(ModeloConfig):
    """Modelo de ``config/contrato.yaml``: campos del contrato de datos, compartidos por todos."""

    noticias: list[str]
    indicadores: list[str]
    indicadores_extra: list[str]
    eventos: list[str]
    fuentes: list[str]


def cargar_contrato(carpeta: Path | None = None) -> ConfigContrato:
    """Atajo para ``config/contrato.yaml``."""
    return cargar_config("contrato", ConfigContrato, carpeta)
# ------------------------------------------------------------------ exploracion.yaml (E0-09)


class EstadisticaExploracion(ModeloConfig):
    z_95: float
    top_n: int
    nota: str


class RevisionManual(ModeloConfig):
    minimo_candidatos_por_tema: int
    temas_validos: list[str]
    archivo: str


class RssExploracion(ModeloConfig):
    carpeta_cruda: str
    carpeta_gdelt: str
    campos_firma: list[str]
    claves_excluidas: list[str]
    agencias: list[str]
    redaccion: list[str]


class PatronesExploracion(ModeloConfig):
    titulo_generico: list[str]
    sufijo_medio: str
    entidad_html: str
    espacio_antes_de_puntuacion: str
    separador_barra_tvn: str
    menciones_panama: list[str]
    falso_panama: list[str]
    deportes: list[str]
    farandula: list[str]
    autopromocion_tvn: list[str]


class DuplicadosExploracion(ModeloConfig):
    min_caracteres_contencion: int


class IndicadoresExploracion(ModeloConfig):
    anio_fin_esperado: int


class UsgsExploracion(ModeloConfig):
    bins_magnitud: list[float]
    panama_en_place: list[str]


class SalidaExploracion(ModeloConfig):
    informe: str
    carpeta_muestra: str
    ejemplos_excluidos: str


class ConfigExploracion(ModeloConfig):
    """Modelo de ``config/exploracion.yaml``."""

    version: int
    estadistica: EstadisticaExploracion
    revision_manual: RevisionManual
    rss: RssExploracion
    patrones: PatronesExploracion
    temas_palabras: dict[str, list[str]]
    duplicados: DuplicadosExploracion
    indicadores: IndicadoresExploracion
    usgs: UsgsExploracion
    salida: SalidaExploracion


def cargar_exploracion(carpeta: Path | None = None) -> ConfigExploracion:
    """Atajo para ``config/exploracion.yaml``."""
    return cargar_config("exploracion", ConfigExploracion, carpeta)


# ------------------------------------------------------------------ reglas_v1.3.yaml (E1-05)

Unidad = Field(ge=0, le=1)
TOLERANCIA = 1e-9  # épsilon numérico de la comparación de sumas en coma flotante; no es un parámetro del negocio


def _suma_es(valores: list[float], objetivo: float, que: str) -> None:
    if abs(sum(valores) - objetivo) > TOLERANCIA:
        raise ValueError(f"{que} deben sumar {objetivo}, suman {sum(valores)}")


class Pesos(ModeloConfig):
    R: float = Field(ge=0)
    I: float = Field(ge=0)
    U: float = Field(ge=0)
    N: float = Field(ge=0)
    E: float = Field(ge=0)

    @model_validator(mode="after")
    def _suman_cien(self) -> Pesos:
        _suma_es([self.R, self.I, self.U, self.N, self.E], 100, "los pesos")
        return self


class Tramo(ModeloConfig):
    desde: float
    hasta: float


class Rangos(ModeloConfig):
    bajo: Tramo
    medio: Tramo
    alto: Tramo

    @model_validator(mode="after")
    def _contiguos(self) -> Rangos:
        if not (self.bajo.desde < self.bajo.hasta == self.medio.desde < self.medio.hasta == self.alto.desde < self.alto.hasta):
            raise ValueError("los rangos deben ser contiguos y crecientes (bajo, medio, alto)")
        if self.bajo.desde != 0 or self.alto.hasta != 100:
            raise ValueError("los rangos deben cubrir de 0 a 100")
        return self


class Percentil(ModeloConfig):
    """Las similitudes se convierten a percentil dentro del snapshot antes de usarse (D-35)."""

    ambito: Literal["snapshot"]
    aplica_a: list[str]


class Relevancia(ModeloConfig):
    peso_foco: float = Unidad
    peso_tematica: float = Unidad
    foco_panama_sujeto: float = Unidad
    foco_otro_pais_afecta: float = Unidad

    @model_validator(mode="after")
    def _partes(self) -> Relevancia:
        _suma_es([self.peso_foco, self.peso_tematica], 1, "las partes de R")
        return self


class AlcanceGeografico(ModeloConfig):
    nacional: float = Unidad
    provincial: float = Unidad
    local: float = Unidad
    desconocido: float = Unidad


class Impacto(ModeloConfig):
    peso_subtema: float = Unidad
    peso_geografico: float = Unidad
    alcance_geografico: AlcanceGeografico
    alcance_subtema: dict[str, float]

    @model_validator(mode="after")
    def _partes(self) -> Impacto:
        _suma_es([self.peso_subtema, self.peso_geografico], 1, "las partes de I")
        malos = [k for k, v in self.alcance_subtema.items() if not 0 <= v <= 1]
        if malos:
            raise ValueError(f"alcance_subtema fuera de [0, 1]: {malos}")
        return self


class Urgencia(ModeloConfig):
    horas_pleno: float = Field(gt=0)
    dias_nulo: float = Field(gt=0)
    fecha_sin_publicacion: Literal["fecha_deteccion"]
    vacio_sin_publicacion: str

    @model_validator(mode="after")
    def _ventana(self) -> Urgencia:
        if self.horas_pleno >= self.dias_nulo * 24:
            raise ValueError("horas_pleno debe ser menor que dias_nulo")
        return self


class Novedad(ModeloConfig):
    sin_grupos_previos: float = Unidad


class EvidenciaReglas(ModeloConfig):
    peso_procedencias: float = Unidad
    peso_oficial: float = Unidad
    peso_identificables: float = Unidad
    tope_procedencias: int = Field(ge=1)

    @model_validator(mode="after")
    def _partes(self) -> EvidenciaReglas:
        _suma_es([self.peso_procedencias, self.peso_oficial, self.peso_identificables], 1, "las partes de E")
        return self


class EstadoEvidencia(ModeloConfig):
    procedencias_suficiente: int = Field(ge=1)
    procedencias_parcial_con_oficial: int = Field(ge=1)
    oficial_obligatorio_si_hay_cifras: bool
    sin_contradiccion_abierta_para_suficiente: Literal[True]  # diseño: suficiente exige no tener contradicción abierta


class Agrupacion(ModeloConfig):
    ventana_dias: int = Field(ge=1)
    umbral_similitud: float | None = Field(default=None, ge=0, le=1)  # None = por calibrar (E1-08)
    umbral_mismo_texto: float = Unidad


class Geografia(ModeloConfig):
    nacional_terminos: list[str]
    provincias: list[str]
    comarcas: list[str]
    distritos: list[str]


class ReglasV13(ModeloConfig):
    """Modelo de ``config/reglas_v1.3.yaml``."""

    version: str
    pesos: Pesos
    rangos: Rangos
    desempate: list[Literal["u_desc", "id_asc"]]
    percentil: Percentil
    relevancia: Relevancia
    impacto: Impacto
    urgencia: Urgencia
    novedad: Novedad
    evidencia: EvidenciaReglas
    estado_evidencia: EstadoEvidencia
    agrupacion: Agrupacion
    agencias: list[str]
    geografia: Geografia

    @field_validator("desempate")
    @classmethod
    def _desempate_valido(cls, v: list[str]) -> list[str]:
        if not v or len(set(v)) != len(v):
            raise ValueError("desempate: debe tener al menos un criterio y no repetirlos")
        return v


def cargar_reglas(carpeta: Path | None = None) -> ReglasV13:
    """Atajo para ``config/reglas_v1.3.yaml``."""
    return cargar_config("reglas_v1.3", ReglasV13, carpeta)


# ------------------------------------------------------------------ temas.yaml (E1-05)


class EjemploTema(ModeloConfig):
    titulo: str
    id_noticia: str | None = None
    real: bool

    @model_validator(mode="after")
    def _real_lleva_id(self) -> EjemploTema:
        if self.real != (self.id_noticia is not None):
            raise ValueError("un ejemplo real lleva id_noticia; uno ilustrativo no")
        return self


class Subtema(ModeloConfig):
    nombre: str
    prototipo: str


class Tema(ModeloConfig):
    nombre: str
    descripcion: str
    ejemplos: list[EjemploTema]
    subtemas: dict[str, Subtema]


class FueraDeTemas(ModeloConfig):
    no_es_panama: str
    fuera_de_temas: str


class ConfigTemas(ModeloConfig):
    """Modelo de ``config/temas.yaml``: exactamente los 6 temas del reto."""

    version: str
    cantidad_temas: int
    sectores_validos: list[str]  # D-11 (propuesta): sectores del boletín de banca
    temas: dict[str, Tema]
    fuera_de_temas: FueraDeTemas

    @model_validator(mode="after")
    def _cantidad_de_temas(self) -> ConfigTemas:
        if len(self.temas) != self.cantidad_temas:
            raise ValueError(f"cantidad_temas: son {self.cantidad_temas} y hay {len(self.temas)} temas")
        ids = [s for t in self.temas.values() for s in t.subtemas]
        if len(ids) != len(set(ids)):
            raise ValueError("un subtema se repite entre temas")
        return self


def cargar_temas(carpeta: Path | None = None) -> ConfigTemas:
    """Atajo para ``config/temas.yaml``."""
    return cargar_config("temas", ConfigTemas, carpeta)


# ------------------------------------------------------------------ vinculos.yaml (E1-05)


class Vinculo(ModeloConfig):
    fuente: Literal["indicador", "usgs"]
    id: str | None = None
    relacion: str
    limitacion: str

    @model_validator(mode="after")
    def _id_segun_fuente(self) -> Vinculo:
        if (self.fuente == "indicador") != (self.id is not None):
            raise ValueError("un vínculo a indicador lleva id; uno a usgs no")
        return self


class ConfigVinculos(ModeloConfig):
    """Modelo de ``config/vinculos.yaml``."""

    version: str
    tipos_relacion: dict[str, str]
    motivos_sin_vinculo: list[str]
    motivo_por_defecto: str
    ventana_coincidencia_dias: int = Field(ge=0)
    pais_por_defecto: str
    vinculos: dict[str, Vinculo]  # por subtema
    vinculos_por_tema: dict[str, Vinculo]  # cualquier subtema del tema

    @model_validator(mode="after")
    def _relaciones_declaradas(self) -> ConfigVinculos:
        if self.motivo_por_defecto not in self.motivos_sin_vinculo:
            raise ValueError("motivo_por_defecto debe estar en motivos_sin_vinculo")
        malas = {v.relacion for v in (*self.vinculos.values(), *self.vinculos_por_tema.values())} - set(self.tipos_relacion)
        if malas:
            raise ValueError(f"relaciones no declaradas en tipos_relacion: {sorted(malas)}")
        return self


def cargar_vinculos(carpeta: Path | None = None) -> ConfigVinculos:
    """Atajo para ``config/vinculos.yaml``."""
    return cargar_config("vinculos", ConfigVinculos, carpeta)


# ------------------------------------------------------------------ modalidad_*.yaml (E1-05)


RANGOS = ("bajo", "medio", "alto")
ESTADOS = ("insuficiente", "parcial", "suficiente")


class MedioReferencia(ModeloConfig):
    nombre: str
    dominio: str


# "publicar" y sus formas; no rechaza "público" ni "pública" (servicio público).
# Formas verbales de "publicar" (incluidas enclíticas y pretéritos); no "publicación" ni "público/a".
FORMAS_DE_PUBLICAR = re.compile(
    r"\b(publicar(lo|la|los|las|se)?|publicad[oa]s?|publicando|publiqu[eé](n|se|nse)?|publ[ií]quese|publicó|publicaron|publicará[n]?|publicaría[n]?)\b",
    re.IGNORECASE,
)


class Accion(ModeloConfig):
    accion: str
    motivo: str

    @model_validator(mode="after")
    def _sin_publicar(self) -> Accion:
        if FORMAS_DE_PUBLICAR.search(f"{self.accion} {self.motivo}"):
            raise ValueError("ninguna acción ni motivo puede hablar de publicar")
        return self


class FilaAcciones(ModeloConfig):
    insuficiente: Accion
    parcial: Accion
    suficiente: Accion


class TablaAcciones(ModeloConfig):
    bajo: FilaAcciones
    medio: FilaAcciones
    alto: FilaAcciones


class ConfigModalidad(ModeloConfig):
    """Modelo común de ``modalidad_editorial.yaml`` y ``modalidad_banca.yaml`` (D-01)."""

    version: str
    modalidad: Literal["editorial", "banca"]
    nombre: str
    usuario: str
    medio_referencia: MedioReferencia | None = None
    grupos_restricciones: list[str]  # grupos de restricciones.yaml que aplican a la modalidad
    tabla_acciones: TablaAcciones
    fuentes_sugeridas_extra: list[str]
    # Banca (D-11): tema -> sector; el alcance de I se mide por sector en lugar de subtema (diseño, reglas v1.3).
    sectores_por_tema: dict[str, str] = Field(default_factory=dict)
    alcance_por_sector: dict[str, float] = Field(default_factory=dict)


def cargar_modalidad(modalidad: str, carpeta: Path | None = None) -> ConfigModalidad:
    """Atajo para ``config/modalidad_<modalidad>.yaml``."""
    cfg = cargar_config(f"modalidad_{modalidad}", ConfigModalidad, carpeta)
    if cfg.modalidad != modalidad:
        raise ErrorDeConfiguracion(f"modalidad_{modalidad}.yaml: declara modalidad '{cfg.modalidad}'")
    _validar_sectores(cfg, carpeta)
    return cfg


def _validar_sectores(cfg: ConfigModalidad, carpeta: Path | None) -> None:
    """Los temas y sectores de la banca deben existir en temas.yaml (sectores de D-11)."""
    if not cfg.sectores_por_tema and not cfg.alcance_por_sector:
        return
    ruta = carpeta if carpeta is not None and (carpeta / "temas.yaml").exists() else CARPETA_CONFIG
    temas = cargar_temas(ruta)
    problemas = [f"tema desconocido en sectores_por_tema: {t}" for t in cfg.sectores_por_tema if t not in temas.temas]
    problemas += [f"sector fuera de D-11 en sectores_por_tema: {s}" for s in cfg.sectores_por_tema.values() if s not in temas.sectores_validos]
    problemas += [f"sector desconocido en alcance_por_sector: {s}" for s in cfg.alcance_por_sector if s not in temas.sectores_validos]
    problemas += [f"alcance_por_sector sin valor en [0, 1] para {s}" for s, v in cfg.alcance_por_sector.items() if not 0 <= v <= 1]
    problemas += [f"sector sin alcance_por_sector: {s}" for s in set(cfg.sectores_por_tema.values()) if s not in cfg.alcance_por_sector]
    if problemas:
        raise ErrorDeConfiguracion(f"modalidad_{cfg.modalidad}.yaml: " + "; ".join(problemas))


# ------------------------------------------------------------------ salidas.yaml y restricciones.yaml (E1-05)


class SalidasEditorial(ModeloConfig):
    titulo_max_palabras: int
    titulares_min: int
    titulares_max: int
    titular_max_palabras: int
    brief_max_palabras: int
    preguntas: int
    guion_segundos_min: int
    guion_segundos_max: int
    guion_palabras_min: int
    guion_palabras_max: int
    resumen_web_max_palabras: int
    copy_max_palabras: int
    copy_max_hashtags: int
    transiciones_sin_cita_max_por_seccion: int

    @model_validator(mode="after")
    def _rangos(self) -> SalidasEditorial:
        if self.guion_palabras_min > self.guion_palabras_max or self.titulares_min > self.titulares_max:
            raise ValueError("un mínimo supera a su máximo")
        return self


class SalidasBanca(ModeloConfig):
    resumen_max_palabras: int
    preguntas: int


class ConfigSalidas(ModeloConfig):
    """Modelo de ``config/salidas.yaml``."""

    version: str
    editorial: SalidasEditorial
    banca: SalidasBanca


def cargar_salidas(carpeta: Path | None = None) -> ConfigSalidas:
    """Atajo para ``config/salidas.yaml``."""
    return cargar_config("salidas", ConfigSalidas, carpeta)


class LeyendasAlcance(ModeloConfig):
    titular_metadatos: str
    con_descripcion: str


GRUPOS_RESTRICCIONES = ("comunes", "editorial", "banca")


class InyeccionRestricciones(ModeloConfig):
    """Patrones de instrucción en titulares y descripciones (D-69, E1-03b)."""

    patrones: list[str]

    @field_validator("patrones")
    @classmethod
    def _regex_validas(cls, v: list[str]) -> list[str]:
        _compilar_todas(v, "inyeccion.patrones")
        return v


class ConfigRestricciones(ModeloConfig):
    """Modelo de ``config/restricciones.yaml`` (D-25, D-51): listas agrupadas; cada modalidad declara las que aplican."""

    version: str
    marca_borrador: str
    marcador_visual: str
    aviso_banca: str
    leyendas_alcance: LeyendasAlcance
    grupos: dict[str, dict[str, list[str]]]
    inyeccion: InyeccionRestricciones

    @model_validator(mode="after")
    def _grupos_esperados(self) -> ConfigRestricciones:
        if set(self.grupos) != set(GRUPOS_RESTRICCIONES):
            raise ValueError(f"grupos debe tener exactamente {GRUPOS_RESTRICCIONES}")
        return self


def cargar_restricciones(carpeta: Path | None = None) -> ConfigRestricciones:
    """Atajo para ``config/restricciones.yaml``."""
    return cargar_config("restricciones", ConfigRestricciones, carpeta)


# ------------------------------------------------------------------ validación cruzada y CLI


def _ids_excluidos(ruta: Path) -> set[str]:
    ids: set[str] = set()
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip() and not linea.startswith("#"):
            ids.add(linea.split("\t", 1)[0].strip())
    return ids


def validar_coherencia(carpeta: Path | None = None) -> list[str]:
    """Cruza los YAML entre sí y devuelve los problemas encontrados (lista vacía = coherente)."""
    carpeta = carpeta or CARPETA_CONFIG
    problemas: list[str] = []
    reglas, temas, vinculos = cargar_reglas(carpeta), cargar_temas(carpeta), cargar_vinculos(carpeta)
    subtemas = {s for t in temas.temas.values() for s in t.subtemas}
    if set(reglas.impacto.alcance_subtema) != subtemas:
        dif = set(reglas.impacto.alcance_subtema) ^ subtemas
        problemas.append(f"alcance_subtema y subtemas de temas.yaml difieren: {sorted(dif)}")
    desconocidos = set(vinculos.vinculos) - subtemas
    if desconocidos:
        problemas.append(f"vinculos.yaml: subtemas inexistentes: {sorted(desconocidos)}")
    sin_tema = set(vinculos.vinculos_por_tema) - set(temas.temas)
    if sin_tema:
        problemas.append(f"vinculos.yaml: temas inexistentes en vinculos_por_tema: {sorted(sin_tema)}")
    indicadores = set(cargar_fuentes(carpeta).banco_mundial.indicadores)
    for sub, v in (*vinculos.vinculos.items(), *vinculos.vinculos_por_tema.items()):
        if v.fuente == "indicador" and v.id not in indicadores:
            problemas.append(f"vinculos.yaml: {sub} usa el indicador {v.id}, que no está en fuentes.yaml")
    reales = {e.id_noticia for t in temas.temas.values() for e in t.ejemplos if e.real}
    excluidos = _ids_excluidos(carpeta / "ejemplos_excluidos.txt")
    if reales != excluidos:
        problemas.append(f"ejemplos_excluidos.txt no coincide con los ejemplos reales de temas.yaml: {sorted(reales ^ excluidos)}")
    if (carpeta / "clasificacion.yaml").exists():  # su presencia la exige validar_todo; aquí solo se cruza si está
        claves = set(cargar_clasificacion(carpeta).baseline.palabras_clave)
        if claves != set(temas.temas):
            problemas.append(f"clasificacion.yaml: baseline.palabras_clave y temas de temas.yaml difieren: {sorted(claves ^ set(temas.temas))}")
    if (carpeta / "etiquetado.yaml").exists():
        motivos = set(cargar_etiquetado(carpeta).ruido.motivos)
        esperados = set(FueraDeTemas.model_fields) | MOTIVOS_RUIDO_HUMANO_EXTRA
        if motivos != esperados:
            problemas.append(f"etiquetado.yaml: ruido.motivos {sorted(motivos)} debe ser fuera_de_temas de temas.yaml más {sorted(MOTIVOS_RUIDO_HUMANO_EXTRA)}")
    if (carpeta / "consulta.yaml").exists():
        oficiales = cargar_consulta(carpeta).datos_oficiales
        if set(oficiales.indicadores) != indicadores:
            problemas.append(f"consulta.yaml: datos_oficiales.indicadores y fuentes.yaml difieren: {sorted(set(oficiales.indicadores) ^ indicadores)}")
        if set(oficiales.paises) != set(cargar_fuentes(carpeta).banco_mundial.paises):
            problemas.append("consulta.yaml: datos_oficiales.paises y banco_mundial.paises de fuentes.yaml difieren")
    grupos = set(cargar_restricciones(carpeta).grupos)
    for modalidad in MODALIDADES:
        if (carpeta / f"modalidad_{modalidad}.yaml").exists():
            faltan = set(cargar_modalidad(modalidad, carpeta).grupos_restricciones) - grupos
            if faltan:
                problemas.append(f"modalidad_{modalidad}.yaml: grupos_restricciones inexistentes: {sorted(faltan)}")
    return problemas


# ------------------------------------------------------------------ normalizacion.yaml (E1-03)


class EntradaNormalizacion(ModeloConfig):
    carpeta_validos: str


class SalidaNormalizacion(ModeloConfig):
    base_de_datos: str


class FechasNormalizacion(ModeloConfig):
    formato_salida: str


class NoticiasNormalizacion(ModeloConfig):
    prefijo_id: str
    largo_hash_id: int
    prefijos_sinteticos: list[str]
    separador_tema: str
    separador_origen: str
    orden_origen: list[str]
    dias_para_recirculada: int
    campos_firma: list[str]


class TiposFirma(ModeloConfig):
    agencia: str
    medio: str
    persona: str
    sin_firma: str


class FirmaNormalizacion(ModeloConfig):
    agencias: list[str]
    nombres_completos: dict[str, list[str]]
    agencias_genericas: list[str]
    redaccion: list[str]
    tipos: TiposFirma


class PrefijoId(ModeloConfig):
    prefijo_id: str


class ConfigNormalizacion(ModeloConfig):
    """Modelo de ``config/normalizacion.yaml``."""

    entrada: EntradaNormalizacion
    salida: SalidaNormalizacion
    fechas: FechasNormalizacion
    noticias: NoticiasNormalizacion
    firma: FirmaNormalizacion
    indicadores: PrefijoId
    sismos: PrefijoId


def cargar_normalizacion(carpeta: Path | None = None) -> ConfigNormalizacion:
    """Atajo para ``config/normalizacion.yaml``."""
    return cargar_config("normalizacion", ConfigNormalizacion, carpeta)




# ------------------------------------------------------------------ ruido.yaml (E1-03b)


class LimpiezaRuido(ModeloConfig):
    comillas: dict[str, str]
    separadores_sufijo: list[str]
    max_palabras_sufijo: int
    min_letras_medio: int
    medios_conocidos: list[str]
    reemplazos: list[list[str]]

    @field_validator("reemplazos")
    @classmethod
    def _regex_validas(cls, v: list[list[str]]) -> list[list[str]]:
        if any(len(par) != 2 for par in v):
            raise ValueError("limpieza.reemplazos: cada elemento es [patrón, reemplazo]")
        _compilar_todas([par[0] for par in v], "limpieza.reemplazos")
        return v


class NoNoticiaRuido(ModeloConfig):
    titulo_generico: list[str]
    titulo_promocional: list[str]
    titulo_igual_al_medio: bool
    patrones_url: list[str]
    categorias_rss: list[str]

    @model_validator(mode="after")
    def _regex_validas(self) -> NoNoticiaRuido:
        _compilar_todas([*self.titulo_generico, *self.titulo_promocional, *self.patrones_url], "no_noticia")
        return self


class PanamaRuido(ModeloConfig):
    falsos: list[str]
    menciones: list[str]
    origenes_sujetos: list[str]
    origenes_exentos: list[str]
    paises_medio_exentos: list[str]
    regionales: list[str]
    dominio_con_seccion: str
    secciones_dudosas: list[str]

    @model_validator(mode="after")
    def _regex_validas(self) -> PanamaRuido:
        _compilar_todas([*self.falsos, *self.menciones, *self.regionales], "panama")
        return self


class FueraDeTemasRuido(ModeloConfig):
    deportes: list[str]
    farandula: list[str]
    cultura: list[str]
    politica_partidista: list[str]
    autopromocion_tvn: list[str]

    @model_validator(mode="after")
    def _regex_validas(self) -> FueraDeTemasRuido:
        _compilar_todas(
            [*self.deportes, *self.farandula, *self.cultura, *self.politica_partidista, *self.autopromocion_tvn],
            "fuera_de_temas",
        )
        return self


class SimilitudPrototipo(ModeloConfig):
    """Filtro de ruido por similitud con prototipos de noticia sobre Panamá (D-84, implementado en E1-07).

    Se aplica con el modelo de ``clasificacion.yaml`` (``modelo_activo``). Una nota con similitud máxima menor que
    ``umbral`` se marca ``no_es_panama``, salvo que ya tenga ``alcance_regional`` (D-84).
    """

    activo: bool
    umbral: float
    prototipos: list[str]

    @model_validator(mode="after")
    def _valida(self) -> SimilitudPrototipo:
        if not self.prototipos or any(not p.strip() for p in self.prototipos):
            raise ValueError("similitud_prototipo.prototipos: debe haber al menos uno y ninguno vacío")
        if not 0.0 <= self.umbral <= 1.0:
            raise ValueError("similitud_prototipo.umbral: es una similitud coseno entre 0 y 1")
        return self


class ConfigRuido(ModeloConfig):
    """Modelo de ``config/ruido.yaml``."""

    version: int
    limpieza: LimpiezaRuido
    no_noticia: NoNoticiaRuido
    panama: PanamaRuido
    fuera_de_temas: FueraDeTemasRuido
    similitud_prototipo: SimilitudPrototipo


def cargar_ruido(carpeta: Path | None = None) -> ConfigRuido:
    """Atajo para ``config/ruido.yaml``."""
    return cargar_config("ruido", ConfigRuido, carpeta)


# ------------------------------------------------------------------ clasificacion.yaml (E1-07)

METODOS_CLASIFICACION = ("A", "B")


class UmbralesMetodo(ModeloConfig):
    """Umbrales de un método (A o B) para un modelo: la similitud coseno no tiene la misma escala en cada uno."""

    umbral_sin_tema: float
    margen_secundario: float

    @model_validator(mode="after")
    def _rangos(self) -> UmbralesMetodo:
        if not 0.0 <= self.umbral_sin_tema <= 1.0:
            raise ValueError("umbral_sin_tema: similitud coseno entre 0 y 1")
        if not 0.0 <= self.margen_secundario <= 1.0:
            raise ValueError("margen_secundario: entre 0 y 1")
        return self


class ModeloEmbeddings(ModeloConfig):
    """Un modelo local de sentence-transformers, fijado por nombre y revisión exactos (D-20, D-03)."""

    id: str
    revision: str
    prefijo_titular: str      # e5: ``query: `` (el titular es la consulta); MiniLM: sin prefijo
    prefijo_tema: str         # e5: ``passage: `` (descripciones, ejemplos y prototipos son los pasajes)
    umbrales: dict[str, UmbralesMetodo]

    @field_validator("revision")
    @classmethod
    def _revision_fija(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", v):
            raise ValueError("revision: debe ser el hash completo (40 hex) del commit del modelo en Hugging Face")
        return v

    @model_validator(mode="after")
    def _metodos(self) -> ModeloEmbeddings:
        if set(self.umbrales) != set(METODOS_CLASIFICACION):
            raise ValueError(f"umbrales: deben estar los métodos {list(METODOS_CLASIFICACION)}")
        return self


class CarpetasClasificacion(ModeloConfig):
    modelos: str       # caché de pesos de Hugging Face (ignorada por git)
    embeddings: str    # caché de embeddings de titulares (ignorada por git)


class CriterioAB(ModeloConfig):
    """Criterio fijado ANTES de medir (D-21, D-57): se usa B solo si el IC de la diferencia B − A excluye el cero
    y ningún tema empeora de forma significativa; si no, A."""

    remuestreos: int
    confianza: float
    semilla: int

    @model_validator(mode="after")
    def _rangos(self) -> CriterioAB:
        if self.remuestreos < 1 or not 0.0 < self.confianza < 1.0:
            raise ValueError("criterio_ab: remuestreos >= 1 y confianza entre 0 y 1")
        return self


class TerminosBaseline(ModeloConfig):
    """Términos de un tema: ``guia`` (literales de docs/guia_temas.md) y ``extension`` (vocabulario agregado)."""

    guia: list[str]
    extension: list[str]


class BaselineClasificacion(ModeloConfig):
    """Baseline por palabras clave (D-66): las mismas categorías; términos literales sin tildes y en minúsculas."""

    variante_activa: Literal["guia", "ampliado"]
    palabras_clave: dict[str, TerminosBaseline]

    @model_validator(mode="after")
    def _terminos_validos(self) -> BaselineClasificacion:
        for tema, grupos in self.palabras_clave.items():
            if not grupos.guia:
                raise ValueError(f"baseline.palabras_clave.{tema}: sin términos de la guía")
            if any(not t.strip() or t != t.lower() for t in [*grupos.guia, *grupos.extension]):
                raise ValueError(f"baseline.palabras_clave.{tema}: términos no vacíos y en minúsculas")
        return self


class FugaSemantica(ModeloConfig):
    """Detector de fuga por paráfrasis entre los casos difíciles y los ejemplos o prototipos de temas.yaml."""

    modelo: str
    umbral_coseno: float
    palabras_ignoradas: list[str]
    excepciones_aceptadas: list[str]   # "CD-02~eventos_naturales.ejemplo[0]": pares aceptados de forma explícita

    @model_validator(mode="after")
    def _rangos(self) -> FugaSemantica:
        if not 0.0 < self.umbral_coseno < 1.0:
            raise ValueError("fuga_semantica.umbral_coseno: entre 0 y 1")
        return self


class ConfigClasificacion(ModeloConfig):
    """Modelo de ``config/clasificacion.yaml``."""

    version: int
    semilla: int
    modelo_activo: str
    metodo_activo: str
    modelos: dict[str, ModeloEmbeddings]
    dispositivo: str
    lote: int
    usar_descripcion: bool          # texto interno para clasificar; nunca se muestra (D-31)
    carpetas: CarpetasClasificacion
    criterio_ab: CriterioAB
    fuga_semantica: FugaSemantica
    baseline: BaselineClasificacion

    @model_validator(mode="after")
    def _coherente(self) -> ConfigClasificacion:
        if self.modelo_activo not in self.modelos:
            raise ValueError(f"modelo_activo {self.modelo_activo!r} no está en modelos {sorted(self.modelos)}")
        if self.metodo_activo not in METODOS_CLASIFICACION:
            raise ValueError(f"metodo_activo: uno de {list(METODOS_CLASIFICACION)}")
        if self.fuga_semantica.modelo not in self.modelos:
            raise ValueError(f"fuga_semantica.modelo {self.fuga_semantica.modelo!r} no está en modelos")
        if self.lote < 1:
            raise ValueError("lote: al menos 1")
        return self


def cargar_clasificacion(carpeta: Path | None = None) -> ConfigClasificacion:
    """Atajo para ``config/clasificacion.yaml``."""
    return cargar_config("clasificacion", ConfigClasificacion, carpeta)
TipoConsulta = Literal[
    "respuesta_sustentada", "contradiccion_ambiguedad", "sin_respuesta", "adversarial"
]


class ConfigBenchmark(ModeloConfig):
    """``config/benchmark.yaml``: total y proporción de tipos del benchmark de desarrollo (E0-06)."""

    total: int = Field(gt=0)
    tipos: dict[TipoConsulta, int]

    @model_validator(mode="after")
    def _suma_coherente(self) -> "ConfigBenchmark":
        if set(self.tipos) != set(get_args(TipoConsulta)):
            raise ValueError("deben estar los cuatro tipos")
        if sum(self.tipos.values()) != self.total:
            raise ValueError("la suma de tipos no coincide con el total")
        return self


def cargar_benchmark(carpeta: Path | None = None) -> ConfigBenchmark:
    """Atajo para ``config/benchmark.yaml``."""
    return cargar_config("benchmark", ConfigBenchmark, carpeta)


# ------------------------------------------------------------------ etiquetado.yaml (E1-06)


class EstratoEtiquetado(ModeloConfig):
    cuota: int = Field(ge=0)
    dobles: int = Field(ge=0)


class EstratosEtiquetado(ModeloConfig):
    no_ruido: EstratoEtiquetado
    ruido: EstratoEtiquetado


class MuestraEtiquetado(ModeloConfig):
    semilla: int
    tamano: int = Field(ge=1)
    tamano_acuerdo: int = Field(ge=2)
    estratos: EstratosEtiquetado

    @model_validator(mode="after")
    def _acuerdo_cabe(self) -> MuestraEtiquetado:
        if self.tamano_acuerdo > self.tamano:
            raise ValueError("tamano_acuerdo no puede superar tamano")
        e = self.estratos
        if e.no_ruido.cuota + e.ruido.cuota != self.tamano:
            raise ValueError("las cuotas de los estratos deben sumar tamano")
        if e.no_ruido.dobles + e.ruido.dobles != self.tamano_acuerdo:
            raise ValueError("los dobles de los estratos deben sumar tamano_acuerdo")
        if e.no_ruido.dobles > e.no_ruido.cuota or e.ruido.dobles > e.ruido.cuota:
            raise ValueError("los dobles de un estrato no pueden superar su cuota")
        return self


class ArchivosEtiquetado(ModeloConfig):
    carpeta_personas: str
    consolidado: str
    ejemplos_excluidos: str


class RuidoEtiquetado(ModeloConfig):
    sin_ruido: str
    motivos: list[str]


class AcuerdoEtiquetado(ModeloConfig):
    kappa_minimo: float = Field(gt=0, le=1)


class NombresEtiquetado(ModeloConfig):
    longitud_minima: int = Field(ge=1)
    marcadores_ia: list[str]
    marcadores_ia_nombre_completo: list[str]


class InterfazEtiquetado(ModeloConfig):
    zona_horaria: str
    formato_fecha: str


class ConfigEtiquetado(ModeloConfig):
    """Modelo de ``config/etiquetado.yaml``."""

    version: int
    muestra: MuestraEtiquetado
    archivos: ArchivosEtiquetado
    ruido: RuidoEtiquetado
    acuerdo: AcuerdoEtiquetado
    nombres: NombresEtiquetado
    interfaz: InterfazEtiquetado


# Motivo que las personas etiquetan además de los de temas.yaml (decisión del equipo tras revisión, spec E1-06).
MOTIVOS_RUIDO_HUMANO_EXTRA = frozenset({"no_es_noticia"})


def cargar_etiquetado(carpeta: Path | None = None) -> ConfigEtiquetado:
    """Atajo para ``config/etiquetado.yaml``."""
    return cargar_config("etiquetado", ConfigEtiquetado, carpeta)


# ------------------------------------------------------------------ consulta.yaml (E1-11)


class Bm25Consulta(ModeloConfig):
    k1: float = Field(gt=0)
    b: float = Field(ge=0, le=1)
    largo_minimo_token: int = Field(ge=1)
    palabras_vacias: list[str]


class RecuperacionConsulta(ModeloConfig):
    top_k: int = Field(ge=1)
    bm25: Bm25Consulta


class AbstencionConsulta(ModeloConfig):
    umbral_similitud: dict[str, float]
    percentil_umbral: float = Field(gt=0, lt=100)

    @model_validator(mode="after")
    def _metodos(self) -> AbstencionConsulta:
        if set(self.umbral_similitud) != {"semantica", "bm25"}:
            raise ValueError("umbral_similitud: deben estar exactamente 'semantica' y 'bm25'")
        return self


class ReglaAbstencion(ModeloConfig):
    """Regla de abstención por patrón: coincide algún patrón y, si hay `ademas`, también alguno de ellos."""

    id: str
    motivo: str
    necesita: str
    patrones: list[str] = Field(min_length=1)
    ademas: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _regex(self) -> ReglaAbstencion:
        _compilar_todas([*self.patrones, *self.ademas], f"consulta.reglas.{self.id}")
        return self


class InyeccionConsulta(ModeloConfig):
    activa: bool
    motivo: str
    necesita: str


class Delimitador(ModeloConfig):
    abre: str = Field(min_length=1)
    cierra: str = Field(min_length=1)


class SismosConsulta(ModeloConfig):
    palabras: list[str] = Field(min_length=1)


class DatosOficialesConsulta(ModeloConfig):
    pais_por_defecto: str
    paises: dict[str, list[str]]
    nombres_pais: dict[str, str]
    indicadores: dict[str, list[str]]
    relacionados: dict[str, list[str]]
    calificadores: dict[str, list[str]]
    intencion_noticia: list[str]
    variacion: list[str]
    sismos: SismosConsulta

    @model_validator(mode="after")
    def _coherente(self) -> DatosOficialesConsulta:
        if self.pais_por_defecto not in self.paises:
            raise ValueError("pais_por_defecto: debe estar en paises")
        if set(self.nombres_pais) != set(self.paises):
            raise ValueError("nombres_pais: debe tener los mismos países que paises")
        if any(not v for v in [*self.paises.values(), *self.indicadores.values()]):
            raise ValueError("paises e indicadores: cada uno necesita al menos un término")
        if not set(self.relacionados) <= set(self.indicadores):
            raise ValueError("relacionados: cada clave debe ser un indicador de `indicadores`")
        if any(not t for t in self.calificadores.values()):
            raise ValueError("calificadores: cada grupo necesita al menos un término")
        _compilar_todas(self.intencion_noticia, "consulta.datos_oficiales.intencion_noticia")
        return self


class RespuestaConsultaConfig(ModeloConfig):
    decimales_valor: int = Field(ge=0)
    maximo_afirmaciones: int = Field(ge=1)
    advertencia_titular: str
    advertencia_anual: str


class EvaluacionConsulta(ModeloConfig):
    calibracion: Literal["pares", "impares"]
    tipos_con_respuesta: list[TipoConsulta]
    tipos_recuperacion: list[TipoConsulta]


class ConfigConsulta(ModeloConfig):
    """Modelo de ``config/consulta.yaml``."""

    version: int
    recuperacion: RecuperacionConsulta
    abstencion: AbstencionConsulta
    reglas: list[ReglaAbstencion]
    inyeccion: InyeccionConsulta
    delimitador_evidencia: Delimitador
    datos_oficiales: DatosOficialesConsulta
    respuesta: RespuestaConsultaConfig
    evaluacion: EvaluacionConsulta

    @model_validator(mode="after")
    def _coherente(self) -> ConfigConsulta:
        ids = [r.id for r in self.reglas]
        if len(ids) != len(set(ids)):
            raise ValueError("reglas: ids repetidos")
        if self.respuesta.maximo_afirmaciones > self.recuperacion.top_k:
            raise ValueError("respuesta.maximo_afirmaciones no puede superar recuperacion.top_k")
        return self


def cargar_consulta(carpeta: Path | None = None) -> ConfigConsulta:
    """Atajo para ``config/consulta.yaml``."""
    return cargar_config("consulta", ConfigConsulta, carpeta)


MODALIDADES = ("editorial", "banca")
OPCIONALES = {"modalidad_banca"}  # el esquema la admite aunque todavía no exista

# Un cargador por YAML de config/: `--validar` los recorre todos y falla ante uno sin modelo registrado.
CARGADORES = {
    "ruido": cargar_ruido,
    "benchmark": cargar_benchmark,
    "fuentes": cargar_fuentes,
    "exploracion": cargar_exploracion,
    "carga": cargar_carga,
    "contrato": cargar_contrato,
    "reglas_v1.3": cargar_reglas,
    "temas": cargar_temas,
    "vinculos": cargar_vinculos,
    "salidas": cargar_salidas,
    "restricciones": cargar_restricciones,
    "modalidad_editorial": lambda c=None: cargar_modalidad("editorial", c),
    "modalidad_banca": lambda c=None: cargar_modalidad("banca", c),
    "llm": cargar_llm,
    "normalizacion": cargar_normalizacion,
    "clasificacion": cargar_clasificacion,
    "etiquetado": cargar_etiquetado,
    "consulta": cargar_consulta,
}


def validar_todo(carpeta: Path | None = None) -> list[str]:
    """Carga cada YAML de la carpeta con su modelo estricto y valida la coherencia; lanza el primer error."""
    carpeta = carpeta or CARPETA_CONFIG
    presentes = sorted(p.stem for p in carpeta.glob("*.yaml"))
    sin_modelo = [n for n in presentes if n not in CARGADORES]
    if sin_modelo:
        raise ErrorDeConfiguracion(f"YAML sin modelo registrado en configuracion.CARGADORES: {sin_modelo}")
    faltan = sorted(set(CARGADORES) - set(presentes) - OPCIONALES)
    if faltan:
        raise ErrorDeConfiguracion(f"faltan YAML obligatorios en {carpeta}: {faltan}")
    for nombre in presentes:
        CARGADORES[nombre](carpeta)
    problemas = validar_coherencia(carpeta)
    if problemas:
        raise ErrorDeConfiguracion("; ".join(problemas))
    return presentes


def principal(argv: list[str] | None = None) -> int:
    """CLI: ``python -m src.config --validar``."""
    parser = argparse.ArgumentParser(description="Valida los YAML de config/")
    parser.add_argument("--validar", action="store_true", required=True)
    parser.add_argument("--config", type=Path, default=None, help="carpeta alternativa (por defecto config/)")
    args = parser.parse_args(argv)
    try:
        cargados = validar_todo(args.config)
    except ErrorDeConfiguracion as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {len(cargados)} archivos de configuración válidos ({', '.join(cargados)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
