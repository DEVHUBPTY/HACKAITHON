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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    # Consultas reemplazadas (tema -> consulta antigua): sus crudos siguen en raw/ y SÍ alimentan el snapshot, declarados con su consulta (D-89, corrige D-83).
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


class Relevancia(ModeloConfig):
    """R = ``peso_foco`` × foco. D-103 quitó la parte temática (percentil de la similitud con el tema)."""

    peso_foco: float = Unidad
    foco_panama_sujeto: float = Unidad
    foco_otro_pais_afecta: float = Unidad

    @model_validator(mode="after")
    def _partes(self) -> Relevancia:
        _suma_es([self.peso_foco], 1, "las partes de R")
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
    horas_pleno: float = Field(ge=0)   # D-106: 0 = sin meseta, U decrece desde la publicación
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


class CalibracionAgrupacion(ModeloConfig):
    """Cómo se calibra ``umbral_similitud`` con ``eval/etiquetas.csv`` (``python -m eval.agrupacion``, D-16)."""

    barrido_desde: float = Unidad
    barrido_hasta: float = Unidad
    barrido_paso: float = Field(gt=0, le=1)
    pliegues: int = Field(ge=2)  # partición determinista por hash del id para medir con titulares no usados al calibrar

    @model_validator(mode="after")
    def _rango(self) -> CalibracionAgrupacion:
        if self.barrido_desde >= self.barrido_hasta:
            raise ValueError("barrido_desde debe ser menor que barrido_hasta")
        return self


class Agrupacion(ModeloConfig):
    ventana_dias: int = Field(ge=1)
    prefijo_id: str = Field(min_length=1)                             # prefijo del ID de grupo (D-63)
    largo_hash_id: int = Field(ge=1, le=40)                           # caracteres del SHA-1 de los NOT- ordenados (como en normalizacion.yaml)
    separador_ids: str = Field(min_length=1)                          # une los NOT- ordenados antes de aplicar el hash
    modelo: str                                                       # modelo de embeddings (clave de clasificacion.yaml) con el que se agrupa
    umbral_similitud: float | None = Field(default=None, ge=0, le=1)  # similitud coseno mínima promedio; None = sin calibrar
    umbral_mismo_texto: float = Unidad
    usar_descripcion: bool                                            # la descripción del RSS es de uso interno (D-31)
    campos_fecha: list[str] = Field(min_length=1)                     # prioridad al fechar un titular (publicación antes que detección)
    calibracion: CalibracionAgrupacion


class Geografia(ModeloConfig):
    nacional_terminos: list[str]
    nacional_implicito_terminos: list[str]   # E1-10c (X42): el país o una institución nacional; solo si no hay un lugar concreto
    provincias: list[str]
    comarcas: list[str]
    distritos: list[str]


class ReglasV13(ModeloConfig):
    """Modelo de ``config/reglas_v1.3.yaml``."""

    version: str
    pesos: Pesos
    rangos: Rangos
    desempate: list[Literal["u_desc", "id_asc"]]
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


class SubtemaVinculo(ModeloConfig):
    """D-92 y E1-10c (X41): el grupo toma el subtema más cercano solo si un criterio de ``criterios`` lo respalda.

    ``margen``: supera al segundo por ``margen_minimo``; ``lexico``: un titular nombra un término del subtema. En ambos
    casos, si un titular nombra un término de OTRO subtema del mismo tema, el subtema es ambiguo y no se afirma.
    """

    criterios: list[Literal["margen", "lexico"]] = Field(min_length=1)   # en este orden; E1-10c: solo ``lexico``
    margen_minimo: float = Field(ge=0)
    terminos_por_subtema: dict[str, list[str]]   # apoyo léxico: un término en el titular respalda el subtema


class SismosVinculo(ModeloConfig):
    """Presentación y textos fijos del vínculo con eventos de USGS (E1-09b)."""

    zona_horaria: str
    formato_hora: str
    formato_hora_utc: str
    decimales_horas: int = Field(ge=0)
    unidad_magnitud: str
    plantilla_regla: str
    nota_fecha_deteccion: str
    limitaciones: list[str] = Field(min_length=1)

    @field_validator("zona_horaria")
    @classmethod
    def _zona_existe(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"zona horaria desconocida: {v}") from exc
        return v


class NotasDato(ModeloConfig):
    """Plantillas de la nota de limitación que acompaña a cada dato anual (E1-09)."""

    ultimo_anio: str
    serie: str
    anios_sin_valor: str


class EtiquetasCifra(ModeloConfig):
    discrepancia: str
    periodo_distinto: str
    coincide: str


class CifraTitular(ModeloConfig):
    """Cómo se detecta la cifra propia de un titular (conservador, todo en configuración)."""

    patron_numero: str
    patron_anio: str
    ventana_caracteres: int = Field(ge=0)
    palabras_de_baja: list[str]  # verbos de baja inequívocos
    palabras_de_baja_ambiguas: list[str]  # «baja»: solo cuenta como cambio si le sigue una palabra de nivel
    palabras_de_alza: list[str]
    palabras_de_nivel: list[str]  # «a», «hasta»: tras un verbo de cambio, la cifra es el nivel alcanzado
    palabras_de_cota: list[str]  # «bajo», «menos de»…: la cifra es una cota o aproximación
    palabras_de_proyeccion: list[str]  # «podría», «prevé»…: proyección en cualquier parte del titular, no se compara
    patrones_de_verbo_no_listado: list[str]  # regex de palabras tipo verbo (futuro, infinitivo, «se …») fuera de las listas
    indicadores_de_variacion: list[str]  # indicadores oficiales que ya son una tasa de cambio
    palabras_clave: dict[str, list[str]]  # indicador -> palabras que ligan la cifra del titular a ese indicador
    etiquetas: EtiquetasCifra

    @field_validator("patron_numero", "patron_anio", "patrones_de_verbo_no_listado")
    @classmethod
    def _patron_valido(cls, v: str | list[str]) -> str | list[str]:
        try:
            for patron in [v] if isinstance(v, str) else v:
                re.compile(patron)
        except re.error as exc:
            raise ValueError(f"expresión regular inválida: {exc}") from exc
        return v

    @model_validator(mode="after")
    def _listas_coherentes(self) -> CifraTitular:
        for nombre in ("palabras_de_baja", "palabras_de_baja_ambiguas", "palabras_de_alza", "palabras_de_nivel", "palabras_de_cota", "palabras_de_proyeccion", "patrones_de_verbo_no_listado"):
            if any(not p.strip() for p in getattr(self, nombre)):
                raise ValueError(f"{nombre}: palabras no vacías")
        if "bajo" in self.palabras_de_baja:
            raise ValueError("«bajo» es una cota, no un verbo de baja")
        malos = set(self.indicadores_de_variacion) - set(self.palabras_clave)
        if malos:
            raise ValueError(f"indicadores_de_variacion sin palabras_clave: {sorted(malos)}")
        return self

    @field_validator("palabras_clave")
    @classmethod
    def _sin_palabras_vacias(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if any(not palabras or any(not p.strip() for p in palabras) for palabras in v.values()):
            raise ValueError("cada indicador necesita palabras clave no vacías")
        return v


class ConfigVinculos(ModeloConfig):
    """Modelo de ``config/vinculos.yaml``."""

    version: str
    tipos_relacion: dict[str, str]
    motivos_sin_vinculo: list[str]
    motivo_por_defecto: str
    ventana_coincidencia_dias: int = Field(ge=0)
    pais_por_defecto: str
    subtema: SubtemaVinculo
    sismos: SismosVinculo
    vinculos: dict[str, Vinculo]  # por subtema
    vinculos_por_tema: dict[str, Vinculo]  # cualquier subtema del tema
    tendencia_anios: int = Field(ge=1)
    indicadores_solo_contexto: list[str]
    palabras_prohibidas: list[str]
    notas: NotasDato
    cifra_titular: CifraTitular

    @model_validator(mode="after")
    def _relaciones_declaradas(self) -> ConfigVinculos:
        if self.motivo_por_defecto not in self.motivos_sin_vinculo:
            raise ValueError("motivo_por_defecto debe estar en motivos_sin_vinculo")
        malas = {v.relacion for v in (*self.vinculos.values(), *self.vinculos_por_tema.values())} - set(self.tipos_relacion)
        if malas:
            raise ValueError(f"relaciones no declaradas en tipos_relacion: {sorted(malas)}")
        return self

    @model_validator(mode="after")
    def _poblacion_no_va_sola(self) -> ConfigVinculos:
        todos = (*self.vinculos.values(), *self.vinculos_por_tema.values())
        solos = {v.id for v in todos} & set(self.indicadores_solo_contexto)
        if solos:
            raise ValueError(f"indicadores solo de contexto no pueden vincularse solos: {sorted(solos)}")
        return self

    @model_validator(mode="after")
    def _textos_sin_palabras_prohibidas(self) -> ConfigVinculos:
        textos = [v.limitacion for v in (*self.vinculos.values(), *self.vinculos_por_tema.values())]
        textos += [*self.notas.model_dump().values(), *self.cifra_titular.etiquetas.model_dump().values()]
        for palabra in self.palabras_prohibidas:
            patron = re.compile(rf"\b{re.escape(palabra)}\b", re.IGNORECASE)
            malos = [t for t in textos if patron.search(t)]
            if malos:
                raise ValueError(f"texto con la palabra prohibida {palabra!r}: {malos[0]!r}")
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


CODIGOS_DE_HORIZONTE = ("inmediato", "corto plazo", "estructural")   # el contrato con el boletín (E2-02); sus textos viven en el YAML


class HorizonteTemporal(ModeloConfig):
    """Escala de horizonte (D-11): *inmediato* hasta N días, *corto plazo* hasta M días y *estructural* más allá o sin fechas de noticia."""

    inmediato_hasta_dias: float = Field(gt=0)
    corto_plazo_hasta_dias: float = Field(gt=0)
    etiquetas: dict[str, str]  # código (inmediato, corto plazo, estructural) -> texto que ve la persona

    @model_validator(mode="after")
    def _crece(self) -> HorizonteTemporal:
        if self.inmediato_hasta_dias >= self.corto_plazo_hasta_dias:
            raise ValueError("horizonte: inmediato_hasta_dias debe ser menor que corto_plazo_hasta_dias")
        if set(self.etiquetas) != set(CODIGOS_DE_HORIZONTE):
            raise ValueError(f"horizonte: etiquetas debe tener exactamente {list(CODIGOS_DE_HORIZONTE)}; difieren {sorted(set(self.etiquetas) ^ set(CODIGOS_DE_HORIZONTE))}")
        return self


class BandejaPorSector(ModeloConfig):
    """Presentación de la bandeja agrupada por sector (E2-01)."""

    sin_sector: str  # etiqueta del bloque de los grupos cuyo tema no tiene sector
    etiquetas_sector: dict[str, str]  # sector -> título del bloque


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
    parcial: bool = False  # true: el archivo solo trae lo que necesita la ficha (D-90); la etapa que lo completa lo apaga
    # Banca (D-11): tema -> sector; el alcance de I se mide por sector en lugar de subtema (diseño, reglas v1.3).
    sectores_por_tema: dict[str, str] = Field(default_factory=dict)
    alcance_por_sector: dict[str, float] = Field(default_factory=dict)
    horizonte: HorizonteTemporal | None = None
    bandeja: BandejaPorSector | None = None


def cargar_modalidad(modalidad: str, carpeta: Path | None = None) -> ConfigModalidad:
    """Atajo para ``config/modalidad_<modalidad>.yaml``."""
    cfg = cargar_config(f"modalidad_{modalidad}", ConfigModalidad, carpeta)
    if cfg.modalidad != modalidad:
        raise ErrorDeConfiguracion(f"modalidad_{modalidad}.yaml: declara modalidad '{cfg.modalidad}'")
    _validar_sectores(cfg, carpeta)
    return cfg


def _validar_sectores(cfg: ConfigModalidad, carpeta: Path | None) -> None:
    """Los temas y sectores de la banca deben existir en temas.yaml (sectores de D-11)."""
    bloques = {
        "sectores_por_tema": bool(cfg.sectores_por_tema), "alcance_por_sector": bool(cfg.alcance_por_sector),
        "horizonte": cfg.horizonte is not None, "bandeja": cfg.bandeja is not None,
    }
    if not any(bloques.values()):
        return
    if not all(bloques.values()):
        faltan = sorted(b for b, hay in bloques.items() if not hay)
        raise ErrorDeConfiguracion(f"modalidad_{cfg.modalidad}.yaml: los bloques por sector van todos o ninguno; faltan {faltan}")
    ruta = carpeta if carpeta is not None and (carpeta / "temas.yaml").exists() else CARPETA_CONFIG
    temas = cargar_temas(ruta)
    problemas = [f"tema desconocido en sectores_por_tema: {t}" for t in cfg.sectores_por_tema if t not in temas.temas]
    problemas += [f"tema sin sector en sectores_por_tema: {t}" for t in temas.temas if t not in cfg.sectores_por_tema]
    problemas += [f"sector fuera de D-11 en sectores_por_tema: {s}" for s in cfg.sectores_por_tema.values() if s not in temas.sectores_validos]
    problemas += [f"sector desconocido en alcance_por_sector: {s}" for s in cfg.alcance_por_sector if s not in temas.sectores_validos]
    problemas += [f"alcance_por_sector sin valor en [0, 1] para {s}" for s, v in cfg.alcance_por_sector.items() if not 0 <= v <= 1]
    if cfg.bandeja is not None:
        problemas += [f"bandeja.etiquetas_sector sin el sector {s}" for s in temas.sectores_validos if s not in cfg.bandeja.etiquetas_sector]
        problemas += [f"bandeja.etiquetas_sector con un sector desconocido: {s}" for s in cfg.bandeja.etiquetas_sector if s not in temas.sectores_validos]
    problemas += [f"sector sin alcance_por_sector: {s}" for s in set(cfg.sectores_por_tema.values()) if s not in cfg.alcance_por_sector]
    if problemas:
        raise ErrorDeConfiguracion(f"modalidad_{cfg.modalidad}.yaml: " + "; ".join(problemas))


# ------------------------------------------------------------------ salidas.yaml y restricciones.yaml (E1-05)


class SalidasEditorial(ModeloConfig):
    titulo_max_palabras: int
    titulares_min: int
    titulares_max: int
    titular_max_palabras: int
    enfoque_oraciones_min: int
    enfoque_oraciones_max: int
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
        if (
            self.guion_palabras_min > self.guion_palabras_max
            or self.titulares_min > self.titulares_max
            or self.enfoque_oraciones_min > self.enfoque_oraciones_max
        ):
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
    if (carpeta / "prioridad.yaml").exists() and (carpeta / "interfaz.yaml").exists():
        mostrados = cargar_interfaz(carpeta).bandeja.decimales_puntaje
        comparados = cargar_prioridad(carpeta).comparacion.decimales_empate
        if comparados != mostrados:   # X60 (D-105): P se compara como se muestra
            problemas.append(f"prioridad.yaml: comparacion.decimales_empate ({comparados}) debe ser igual a interfaz.yaml: bandeja.decimales_puntaje ({mostrados})")
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
    if (carpeta / "procedencias.yaml").exists():
        proc = cargar_procedencias(carpeta)
        ajenas = (set(proc.agencias_por_dominio) | set(proc.alias_agencias)) - set(reglas.agencias)
        if ajenas:
            problemas.append(f"procedencias.yaml: agencias que no están en reglas_v1.3.yaml: {sorted(ajenas)}")
    if (carpeta / "clasificacion.yaml").exists() and reglas.agrupacion.modelo not in cargar_clasificacion(carpeta).modelos:
        problemas.append(f"reglas_v1.3.yaml: agrupacion.modelo {reglas.agrupacion.modelo!r} no está en clasificacion.yaml")
    if (carpeta / "consulta.yaml").exists():
        oficiales = cargar_consulta(carpeta).datos_oficiales
        if set(oficiales.indicadores) != indicadores:
            problemas.append(f"consulta.yaml: datos_oficiales.indicadores y fuentes.yaml difieren: {sorted(set(oficiales.indicadores) ^ indicadores)}")
        if set(oficiales.paises) != set(cargar_fuentes(carpeta).banco_mundial.paises):
            problemas.append("consulta.yaml: datos_oficiales.paises y banco_mundial.paises de fuentes.yaml difieren")
    if (carpeta / "verificacion.yaml").exists():
        ver = cargar_verificacion(carpeta)
        problemas += [f"verificacion.yaml: subtema inexistente en fuentes.por_subtema: {s}" for s in sorted(set(ver.fuentes.por_subtema) - subtemas)]
        problemas += [f"verificacion.yaml: tema inexistente en fuentes.por_tema: {t}" for t in sorted(set(ver.fuentes.por_tema) - set(temas.temas))]
        problemas += [f"verificacion.yaml: sin fuentes sugeridas para el tema {t}" for t in sorted(set(temas.temas) - set(ver.fuentes.por_tema))]
        problemas += [f"verificacion.yaml: sin fuentes sugeridas para el subtema {s}" for s in sorted(subtemas - set(ver.fuentes.por_subtema))]
        codigos = set(ver.vacios.catalogo)
        emitidos = (set(VaciosPrioridad.model_fields) - {"motivo_sin_dato_oficial_por_defecto", "motivos_sin_vinculo"}) | {CODIGO_URGENCIA_SIN_PUBLICACION}
        faltan = emitidos - codigos
        problemas += [f"verificacion.yaml: vacío de prioridad.yaml sin entrada en vacios.catalogo: {c}" for c in sorted(faltan)]
        motivos = set(cargar_prioridad(carpeta).vacios.motivos_sin_vinculo)
        if motivos != set(vinculos.motivos_sin_vinculo):
            problemas.append(f"prioridad.yaml: vacios.motivos_sin_vinculo y vinculos.yaml difieren: {sorted(motivos ^ set(vinculos.motivos_sin_vinculo))}")
    grupos = set(cargar_restricciones(carpeta).grupos)
    for modalidad in MODALIDADES:
        if (carpeta / f"modalidad_{modalidad}.yaml").exists():
            faltan = set(cargar_modalidad(modalidad, carpeta).grupos_restricciones) - grupos
            if faltan:
                problemas.append(f"modalidad_{modalidad}.yaml: grupos_restricciones inexistentes: {sorted(faltan)}")
    if (carpeta / "generacion.yaml").exists():  # E2-02: cada acción de la tabla de una modalidad con generación decide qué se genera
        gen = cargar_generacion(carpeta)
        conocidas = {x for lista in gen.acciones.model_dump().values() for x in lista}
        for modalidad in gen.modalidades:
            if (carpeta / f"modalidad_{modalidad}.yaml").exists():
                tabla = cargar_modalidad(modalidad, carpeta).tabla_acciones
                acciones = {getattr(getattr(tabla, r), e).accion for r in TablaAcciones.model_fields for e in FilaAcciones.model_fields}
                problemas += [f"generacion.yaml: la acción «{x}» de modalidad_{modalidad}.yaml no está en acciones" for x in sorted(acciones - conocidas)]
        for modalidad, paquete in gen.modalidades.items():
            if not getattr(gen.grupos, paquete):
                problemas.append(f"generacion.yaml: el paquete {paquete} de la modalidad {modalidad} no tiene grupos de redacción")
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


class ConfigSustento(ModeloConfig):
    """Muestra y veredictos de la revisión humana de la validez de sustento (E1-18)."""

    muestra: int = Field(gt=0)
    semilla: int
    meta_validez: float = Field(gt=0, le=1)
    veredictos: list[str] = Field(min_length=4, max_length=4)


class ConfigAnalisisUmbral(ModeloConfig):
    """Rejilla de la curva descriptiva de abstención por umbral (E1-18)."""

    desde: float = Field(gt=0)
    hasta: float = Field(gt=0)
    paso: float = Field(gt=0)

    @model_validator(mode="after")
    def _rango(self) -> "ConfigAnalisisUmbral":
        if self.hasta < self.desde:
            raise ValueError("analisis_umbral: hasta debe ser >= desde")
        return self


class ConfigLlmBenchmark(ModeloConfig):
    modalidad: Literal["editorial", "banca"]


class ConfigMetasBenchmark(ModeloConfig):
    """Metas de la sección 9.1 que el runner compara con lo medido (E1-18)."""

    abstencion_correcta: float = Field(gt=0, le=1)
    latencia_mediana_s: float = Field(gt=0)


class ConfigBenchmark(ModeloConfig):
    """``config/benchmark.yaml``: total y proporción de tipos del benchmark de desarrollo (E0-06) y parámetros de E1-18."""

    total: int = Field(gt=0)
    tipos: dict[TipoConsulta, int]
    intervalos: CriterioAB
    sustento: ConfigSustento
    analisis_umbral: ConfigAnalisisUmbral
    llm: ConfigLlmBenchmark
    metas: ConfigMetasBenchmark

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


# ------------------------------------------------------------------ procedencias.yaml (E1-08)


class RedSindicacion(ModeloConfig):
    nombre: str
    dominios: list[str] = Field(min_length=1)


class ConfigProcedencias(ModeloConfig):
    """Modelo de ``config/procedencias.yaml``: qué hace que dos titulares cuenten como UNA procedencia (CU-03, D-32).

    El RSS no trae firma, así que la independencia sale del dominio (red de sindicación o agencia dueña del dominio),
    de la agencia nombrada en el titular y del texto casi idéntico (``reglas_v1.3.yaml``: ``umbral_mismo_texto``).
    Las agencias son las de ``reglas_v1.3.yaml`` (``validar_coherencia`` lo cruza); nunca se guarda un nombre de autor.
    """

    version: int
    redes_sindicacion: dict[str, RedSindicacion]
    agencias_por_dominio: dict[str, list[str]]     # agencia -> dominios que son de ella
    alias_agencias: dict[str, list[str]]           # agencia -> otras formas de nombrarla en un titular
    separador_etiqueta: str                        # une los nombres cuando una procedencia reúne varias agencias o redes
    etiqueta_estimado: str                         # leyenda obligatoria: el conteo es una estimación

    @model_validator(mode="after")
    def _dominios_sin_repetir(self) -> ConfigProcedencias:
        todos = [d for r in self.redes_sindicacion.values() for d in r.dominios]
        todos += [d for ds in self.agencias_por_dominio.values() for d in ds]
        repetidos = sorted({d for d in todos if todos.count(d) > 1})
        if repetidos:
            raise ValueError(f"un dominio no puede estar en dos redes o agencias: {repetidos}")
        return self


def cargar_procedencias(carpeta: Path | None = None) -> ConfigProcedencias:
    """Atajo para ``config/procedencias.yaml``."""
    return cargar_config("procedencias", ConfigProcedencias, carpeta)
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


# ------------------------------------------------------------------ prioridad.yaml (E1-10)


class ComparacionPrioridad(ModeloConfig):
    decimales_p: int = Field(ge=0, le=15)
    decimales_empate: int = Field(ge=0, le=15)   # D-105: P se compara como se muestra (bandeja.decimales_puntaje)


class ImpactoPrioridad(ModeloConfig):
    alcance_subtema_desconocido: float = Unidad


class DatoOficialPrioridad(ModeloConfig):
    relaciones_aceptadas: list[str]
    estado_evento_automatico: str = Field(min_length=1)


class GeografiaPrioridad(ModeloConfig):
    prefijos_obligatorios: dict[str, list[str]]
    prefijos_excluidos: dict[str, list[str]]   # E1-10c (X42): el término implícito no cuenta precedido de estos
    sufijos_excluidos: dict[str, list[str]]    # X51: sin tilde, el término no cuenta seguido de estas palabras («pese a»)
    requieren_tilde: list[str]                 # X66: el término solo cuenta escrito con su tilde («Colón»; «colon» es el órgano)
    prefijos_excluidos_lugar: dict[str, list[str]]   # X66: el término de lugar no cuenta precedido de estos («Cristóbal Colón»)


class MediosPrioridad(ModeloConfig):
    desconocidos: list[str]


class CifrasPrioridad(ModeloConfig):
    patron: str
    patron_fecha: str
    anio_desde: int
    anio_hasta: int
    digitos_por_grupo_de_miles: int = Field(ge=1)
    palabras_previas_no_cifra: list[str]
    unidades_ignoradas: list[str]
    raiz_unidad_caracteres: int = Field(ge=1)

    @field_validator("patron")
    @classmethod
    def _patron_con_grupos(cls, v: str) -> str:
        grupos = re.compile(v).groupindex
        if "numero" not in grupos or "unidad" not in grupos:
            raise ValueError("el patrón de cifras necesita los grupos con nombre `numero` y `unidad`")
        return v

    @field_validator("patron_fecha")
    @classmethod
    def _fecha_valida(cls, v: str) -> str:
        _compilar_todas([v], "cifras.patron_fecha")
        return v

    @model_validator(mode="after")
    def _anios(self) -> CifrasPrioridad:
        if self.anio_desde >= self.anio_hasta:
            raise ValueError("anio_desde debe ser menor que anio_hasta")
        return self


class ParOpuesto(ModeloConfig):
    nombre: str
    a: list[str] = Field(min_length=1)
    b: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _lados_distintos(self) -> ParOpuesto:
        if set(self.a) & set(self.b):
            raise ValueError(f"{self.nombre}: una forma no puede estar en los dos lados")
        return self


class ContradiccionesPrioridad(ModeloConfig):
    etiqueta: str
    solo_entre_procedencias: bool
    maximo_candidatos_por_grupo: int = Field(ge=1)
    prompt: str
    pares_opuestos: list[ParOpuesto]


class VaciosPrioridad(ModeloConfig):
    procedencias_insuficientes: str
    cifras_sin_dato_oficial: str
    sin_dato_oficial: str
    solo_vinculo_indirecto: str
    cifra_discrepante: str
    cifra_periodo_distinto: str
    evento_sin_revisar: str
    contradiccion_abierta: str
    medios_o_fechas_desconocidos: str
    noticia_recirculada: str
    subtema_desconocido: str
    sector_desconocido: str
    motivo_sin_dato_oficial_por_defecto: str
    motivos_sin_vinculo: dict[str, str]


class SensibilidadPrioridad(ModeloConfig):
    variacion_peso: float = Field(gt=0)
    variacion_supuesto: float = Field(gt=0, lt=1)
    tamano_ranking: int = Field(ge=1)


class PuntajeEval(ModeloConfig):
    casi_constante_desviacion: float = Field(gt=0)
    top_en_reporte: int = Field(ge=1)


class ConfigPrioridad(ModeloConfig):
    """Modelo de ``config/prioridad.yaml``: geografía, cifras, contradicciones y vacíos de E1-10."""

    version: int
    comparacion: ComparacionPrioridad
    impacto: ImpactoPrioridad
    dato_oficial: DatoOficialPrioridad
    geografia: GeografiaPrioridad
    medios: MediosPrioridad
    cifras: CifrasPrioridad
    contradicciones: ContradiccionesPrioridad
    vacios: VaciosPrioridad
    sensibilidad: SensibilidadPrioridad
    puntaje_eval: PuntajeEval


def cargar_prioridad(carpeta: Path | None = None) -> ConfigPrioridad:
    """Atajo para ``config/prioridad.yaml``."""
    return cargar_config("prioridad", ConfigPrioridad, carpeta)


# ------------------------------------------------------------------ generacion.yaml (E1-12)


class PromptsGeneracion(ModeloConfig):
    afirmaciones: str
    redaccion: str
    paquetes: dict[str, str] = Field(default_factory=dict)  # E2-02: paquete -> prompt propio con los dos pasos (bloques ``## afirmaciones``…)


class AfirmacionesGeneracion(ModeloConfig):
    minimas_validas: int = Field(ge=1)
    maximas: int = Field(ge=1)
    exigir_inferencia: bool = False


class AccionesGeneracion(ModeloConfig):
    completo: list[str]
    completo_con_vacios: list[str]
    investigacion: list[str]
    nada: list[str]

    @model_validator(mode="after")
    def _sin_repetidas(self) -> AccionesGeneracion:
        todas = [*self.completo, *self.completo_con_vacios, *self.investigacion, *self.nada]
        if len(todas) != len(set(todas)):
            raise ValueError("una acción aparece en más de una lista")
        return self


class PrefijosGeneracion(ModeloConfig):
    hecho_oficial: list[str] = Field(min_length=1)
    hecho_conteo: list[str] = Field(min_length=1)
    reportes: list[str] = Field(min_length=1)


class AtribucionGeneracion(ModeloConfig):
    marcadores: list[str] = Field(min_length=1)


class TextoGeneracion(ModeloConfig):
    motivo_max_caracteres: int = Field(gt=0)
    vista_previa_caracteres: int = Field(gt=0)


class TraducidoGeneracion(ModeloConfig):
    idioma_base: str
    marca: str


class FugaPromptGeneracion(ModeloConfig):
    palabras_por_fragmento: int = Field(ge=2)


class GruposGeneracion(ModeloConfig):
    editorial: list[str]
    investigacion: list[str]
    boletin: list[str] = Field(default_factory=list)  # E2-02


PaqueteGeneracion = Literal["editorial", "boletin"]  # paquete completo de una modalidad (docs/salidas.md §1 y §2)


class MotivoSectorBoletin(ModeloConfig):
    principal: str
    secundario: str

    @model_validator(mode="after")
    def _con_marcadores(self) -> MotivoSectorBoletin:
        for texto in (self.principal, self.secundario):
            if "{tema}" not in texto or "{sector}" not in texto:
                raise ValueError("motivo_sector: cada texto lleva {tema} y {sector}")
        return self


class BoletinGeneracion(ModeloConfig):
    """Textos de los campos de origen «Regla» del boletín de entorno (E2-02, docs/salidas.md §2)."""

    motivo_sector: MotivoSectorBoletin
    sin_sector: str


class PreciosDeepSeek(ModeloConfig):
    entrada: float = Field(ge=0)
    salida: float = Field(ge=0)


class DeepSeekConfig(ModeloConfig):
    base_url: str
    modelo: str
    timeout_segundos: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    precio_usd_por_millon_tokens: PreciosDeepSeek


class TopeCostoConfig(ModeloConfig):
    tokens: int = Field(gt=0)
    usd: float = Field(gt=0)
    registro: str


class MedicionGeneracion(ModeloConfig):
    repeticiones: int = Field(ge=1)
    calentamiento: int = Field(ge=0)
    percentil: int = Field(ge=1, le=100)


class ConfigGeneracionBorrador(ModeloConfig):
    """Modelo de ``config/generacion.yaml``."""

    version: str
    prompts: PromptsGeneracion
    reintentos: int = Field(ge=0)
    afirmaciones: AfirmacionesGeneracion
    modalidades: dict[str, PaqueteGeneracion] = Field(min_length=1)  # modalidad -> su paquete completo (E2-02)
    acciones: AccionesGeneracion
    prefijos: PrefijosGeneracion
    campos_conteo: list[str] = Field(min_length=1)
    volatiles: list[str] = Field(min_length=1)
    patron_anio_en_id: str
    patron_valor_por_anio: str
    atribucion: AtribucionGeneracion
    traducido: TraducidoGeneracion
    texto: TextoGeneracion
    recortables: list[str]
    objetivo_fraccion_limite: float = Field(gt=0, le=1)
    fuga_prompt: FugaPromptGeneracion
    grupos: GruposGeneracion
    boletin: BoletinGeneracion
    deepseek: DeepSeekConfig
    tope_costo: TopeCostoConfig
    medicion: MedicionGeneracion

    @field_validator("patron_anio_en_id", "patron_valor_por_anio")
    @classmethod
    def _regex_valida(cls, v: str) -> str:
        _compilar_todas([v], "patron_anio_en_id")
        return v


def cargar_generacion(carpeta: Path | None = None) -> ConfigGeneracionBorrador:
    """Atajo para ``config/generacion.yaml``."""
    return cargar_config("generacion", ConfigGeneracionBorrador, carpeta)



# ------------------------------------------------------------------ validador.yaml (E1-13)


class NumerosValidador(ModeloConfig):
    tolerancia_absoluta: float = Field(ge=0)
    redondeo_permitido: bool
    decimales_minimos: int = Field(ge=0)
    tolerancia_relativa: float = Field(ge=0, lt=1)
    decimales_maximos: int = Field(ge=0)


class ListaValidador(ModeloConfig):
    """Cómo se aplica una lista de ``restricciones.yaml``: a qué tipos y si admite la excepción del titular literal."""

    excepcion_literal: bool
    tipos: list[str] = Field(default_factory=list)
    sin_excepcion_en: list[str] = Field(default_factory=list)
    excepcion_tipos: list[str] = Field(default_factory=list)  # E2-02: la excepción solo vale si todo lo citado es de estos tipos
    ventana_literal: int = Field(default=0, ge=0)  # X49: palabras a cada lado de la frase que también deben ser literales del titular (0 = solo la frase)
    rechaza_sector_financiero_ajeno: bool = False  # X57 (D-107): una oración que usa la excepción literal no puede traer un término de ``sector_financiero`` que el titular no tenga
    con_tildes: bool = False  # X50: se compara conservando las tildes («bajará», futuro, no es «bajara», subjuntivo)


class TransicionesValidador(ModeloConfig):
    max_palabras: int = Field(ge=1)
    secciones: list[str]
    inicio_no_entidad: list[str]


TIPOS_DE_AFIRMACION = ("hecho", "declaración", "inferencia", "hipótesis")  # D-41


class BloquesBoletinValidador(ModeloConfig):
    """Tipos de afirmación que puede citar cada bloque del resumen del boletín (E2-02, docs/salidas.md §2)."""

    observaciones: list[str] = Field(min_length=1)
    hipotesis_impacto: list[str] = Field(min_length=1)
    ventana_literal_condicional: int = Field(ge=0)  # X49: un marcador condicional en una observación solo vale dentro de un fragmento literal del titular

    @model_validator(mode="after")
    def _tipos_conocidos_y_separados(self) -> BloquesBoletinValidador:
        if not set(self.observaciones) | set(self.hipotesis_impacto) <= set(TIPOS_DE_AFIRMACION):
            raise ValueError(f"bloques_boletin: tipos fuera de {TIPOS_DE_AFIRMACION}")
        if set(self.observaciones) & set(self.hipotesis_impacto):
            raise ValueError("bloques_boletin: un tipo no puede estar en los dos bloques (observación e hipótesis no se mezclan)")
        return self


class ConfigValidador(ModeloConfig):
    """Modelo de ``config/validador.yaml`` (E1-13): listas y umbrales de las reglas del validador (D-79)."""

    version: str
    registro: str
    numeros: NumerosValidador
    condicionales: list[str] = Field(min_length=1)
    causales: list[str] = Field(min_length=1)
    acusaciones: list[str] = Field(min_length=1)
    detalle_sin_cita: list[str]
    listas: dict[str, ListaValidador]
    sector_financiero: list[str] = Field(min_length=1)  # X57 (D-107)
    transiciones: TransicionesValidador
    patrones: dict[str, list[str]]
    palabras_numero: dict[str, int]
    numerales_en_compuesto: dict[str, int]
    multiplicadores: dict[str, int]
    cantidades_vagas: list[str]
    juicios_transicion: list[str]
    equivalencias_traduccion: dict[str, list[str]]
    cognados_prefijo_min: int = Field(ge=2)
    fuentes_por_prefijo: dict[str, str]
    frases_sin_cifra: list[str]
    nombres_permitidos: list[str]
    meses: list[str] = Field(min_length=12, max_length=13)
    nombre_min_caracteres: int = Field(ge=1)
    campos_fecha: list[str] = Field(min_length=1)
    bloques_boletin: BloquesBoletinValidador  # E2-02

    @field_validator("patrones")
    @classmethod
    def _patrones_validos(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for lista in v.values():
            _compilar_todas(lista, "patrones")
        return v


def cargar_validador(carpeta: Path | None = None) -> ConfigValidador:
    """Atajo para ``config/validador.yaml``."""
    return cargar_config("validador", ConfigValidador, carpeta)


# ------------------------------------------------------------------ verificacion.yaml (E1-10b)


class VacioCatalogo(ModeloConfig):
    """Un tipo de vacío: qué hacer para cerrarlo. El texto del vacío lo calcula E1-10 (``prioridad.yaml``)."""

    verificacion: str = Field(min_length=1)


class VaciosVerificacion(ModeloConfig):
    principales: int = Field(ge=1)
    orden_importancia: list[str] = Field(min_length=1)
    verificacion_por_defecto: str = Field(min_length=1)
    catalogo: dict[str, VacioCatalogo]

    @model_validator(mode="after")
    def _orden_y_catalogo_coinciden(self) -> VaciosVerificacion:
        if len(set(self.orden_importancia)) != len(self.orden_importancia):
            raise ValueError("orden_importancia repite un código")
        if set(self.orden_importancia) != set(self.catalogo):
            raise ValueError(f"orden_importancia y catalogo difieren: {sorted(set(self.orden_importancia) ^ set(self.catalogo))}")
        return self


class FuentesVerificacion(ModeloConfig):
    subtema_desconocido: str
    nota: str
    por_subtema: dict[str, list[str]]
    por_tema: dict[str, list[str]]

    @field_validator("por_subtema", "por_tema")
    @classmethod
    def _fuentes_con_nombre(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if any(not fuentes or any(not f.strip() for f in fuentes) for fuentes in v.values()):
            raise ValueError("cada entrada necesita fuentes con nombre")
        return v


class TitularCentralVerificacion(ModeloConfig):
    candidatos: int = Field(ge=1)
    idioma_preferido: str
    pais_medio_preferido: str


class ProcedenciasVerificacion(ModeloConfig):
    explicacion: str
    reglas: dict[str, str]


class MedioReferenciaVerificacion(ModeloConfig):
    cubrio: str
    sin_titular: str


class PresentacionVerificacion(ModeloConfig):
    zona_horaria: str
    formato_fecha: str
    sufijo_zona: str
    fecha_desconocida: str
    decimales_valor: int = Field(ge=0)
    origen_fecha: dict[str, str]
    fuentes_oficiales: dict[str, str]
    roles: dict[str, str]
    advertencia_inyeccion: str
    advertencia_recirculada: str

    @field_validator("zona_horaria")
    @classmethod
    def _zona_existe(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"zona horaria desconocida: {v}") from exc
        return v


class SiguientesPasosVerificacion(ModeloConfig):
    maximo: int = Field(ge=1)


class ConfigVerificacion(ModeloConfig):
    """Modelo de ``config/verificacion.yaml``: vacíos, fuentes sugeridas y presentación de la ficha (común a las modalidades)."""

    version: str
    vacios: VaciosVerificacion
    fuentes: FuentesVerificacion
    titular_central: TitularCentralVerificacion
    procedencias: ProcedenciasVerificacion
    medio_referencia: MedioReferenciaVerificacion
    presentacion: PresentacionVerificacion
    siguientes_pasos: SiguientesPasosVerificacion

    @model_validator(mode="after")
    def _sin_publicar(self) -> ConfigVerificacion:
        textos = [self.vacios.verificacion_por_defecto, self.fuentes.nota]
        textos += [v.verificacion for v in self.vacios.catalogo.values()]
        if any(FORMAS_DE_PUBLICAR.search(t) for t in textos):
            raise ValueError("ningún texto de la ficha puede hablar de publicar")
        return self


def cargar_verificacion(carpeta: Path | None = None) -> ConfigVerificacion:
    """Atajo para ``config/verificacion.yaml``."""
    return cargar_config("verificacion", ConfigVerificacion, carpeta)


# ------------------------------------------------------------------ interfaz.yaml (E1-15)


class PantallaInterfaz(ModeloConfig):
    clave: Literal["calidad", "bandeja", "ficha", "consulta", "paquete", "revision"]
    titulo: str = Field(min_length=1)


class BandejaInterfaz(ModeloConfig):
    filas_iniciales: int = Field(ge=1)
    alto_filas_px: int = Field(ge=1)
    decimales_puntaje: int = Field(ge=0)
    largo_titular_selector: int = Field(ge=10)
    filas_iniciales_por_sector: int = Field(ge=1)
    ancho_titular_cli: int = Field(ge=10)


class CalidadInterfaz(ModeloConfig):
    top_medios: int = Field(ge=1)


class ConsultaInterfaz(ModeloConfig):
    metodo_inicial: Literal["semantica", "bm25"]
    largo_maximo_caracteres: int = Field(ge=1)
    ejemplos: list[str] = Field(min_length=1)


class FichaInterfaz(ModeloConfig):
    prefijo_desglose: str = Field(min_length=1)
    secciones_resumen: list[str] = Field(min_length=1)
    secciones_desplegables: list[str] = Field(min_length=1)
    citas_por_fila: int = Field(ge=1)
    campos_ocultos: list[str]


class DemoInterfaz(ModeloConfig):
    ruta_base: str = Field(min_length=1)
    parametro_caso: str = Field(min_length=1)
    guion: str = Field(min_length=1)


class CitasInterfaz(ModeloConfig):
    decimales_valor: int = Field(ge=0)
    aviso_anual: str = Field(min_length=1)


class GeneracionInterfaz(ModeloConfig):
    # Lista cerrada: el YAML nunca elige qué módulo se importa. Al integrar E1-12 se agrega aquí el nombre real de la función.
    modulo: Literal["src.generacion"]
    funcion: Literal["generar_paquete"]
    solo_cache: bool


class PaqueteInterfaz(ModeloConfig):
    """Etiquetas legibles de los campos del paquete en la pantalla Paquete; un campo sin etiqueta usa su nombre capitalizado."""

    etiquetas: dict[str, str]


class RevisionInterfaz(ModeloConfig):
    estados: list[str] = Field(min_length=1)
    estado_inicial: str


class TextosEmpate(ModeloConfig):
    """D-105: cómo se muestra el empate en P de un grupo (bandeja, ficha y CLI)."""

    uno: str = Field(min_length=1)
    varios: str = Field(min_length=1)

    @model_validator(mode="after")
    def _con_n(self) -> TextosEmpate:
        if "{n}" not in self.varios:
            raise ValueError("textos.empate.varios debe llevar {n}")
        return self


class TextosInterfaz(ModeloConfig):
    empate: TextosEmpate
    alerta: str
    sintetico: str
    sintetico_ayuda: str
    sin_base: str
    sin_demo: str
    banca_parcial: str
    sin_puntajes: str
    sin_borrador: str
    sin_borrador_ayuda: str
    borrador_no_listo: str
    sin_revision: str
    aprobar_aviso: str


class ConfigInterfaz(ModeloConfig):
    """Modelo de ``config/interfaz.yaml``: constantes de presentación de la app (E1-15). Sin reglas de negocio."""

    version: str
    titulo_app: str
    modalidad_inicial: Literal["editorial", "banca"]
    pantallas: list[PantallaInterfaz] = Field(min_length=6, max_length=6)
    pantalla_inicial: str
    bandeja: BandejaInterfaz
    calidad: CalidadInterfaz
    consulta: ConsultaInterfaz
    ficha: FichaInterfaz
    demo: DemoInterfaz
    citas: CitasInterfaz
    generacion: GeneracionInterfaz
    paquete: PaqueteInterfaz
    revision: RevisionInterfaz
    textos: TextosInterfaz

    @model_validator(mode="after")
    def _coherente(self) -> ConfigInterfaz:
        claves = [p.clave for p in self.pantallas]
        if len(set(claves)) != 6:
            raise ValueError("pantallas: las seis claves (calidad, bandeja, ficha, consulta, paquete, revision) deben aparecer una vez")
        if self.pantalla_inicial not in claves:
            raise ValueError("pantalla_inicial: debe ser una de las pantallas")
        if self.revision.estado_inicial not in self.revision.estados:
            raise ValueError("revision.estado_inicial: debe estar en revision.estados")
        propios = [t for v in self.textos.model_dump().values() for t in (v.values() if isinstance(v, dict) else [v])]
        textos = [self.titulo_app, *self.consulta.ejemplos, *self.revision.estados, *propios]
        if any(FORMAS_DE_PUBLICAR.search(t) for t in textos):
            raise ValueError("ningún texto de la interfaz puede hablar de publicar")
        return self


def cargar_interfaz(carpeta: Path | None = None) -> ConfigInterfaz:
    """Atajo para ``config/interfaz.yaml``."""
    return cargar_config("interfaz", ConfigInterfaz, carpeta)


# ------------------------------------------------------------------ cache.yaml (E1-14)


class SondeoRed(ModeloConfig):
    timeout_segundos: float = Field(gt=0)
    puerto: int = Field(gt=0, lt=65536)


class CalentamientoCache(ModeloConfig):
    top_bandeja: int = Field(ge=0)
    guion_demo: str = Field(min_length=1)
    patron_id_grupo: str = Field(min_length=1)

    @field_validator("patron_id_grupo")
    @classmethod
    def _patron_valido(cls, v: str) -> str:
        re.compile(v)
        return v


class ReglaEtiquetadoPrompt(ModeloConfig):
    """X64: cuándo una entrada de la caché sin ``prompt`` se reconoce como de este prompt (ver ``config/cache.yaml``)."""

    prompt: str = Field(min_length=1)
    version_prompt: str = Field(min_length=1)
    respuestas: list[list[str]] = Field(min_length=1)
    hasta_utc: str | None = None

    @field_validator("respuestas")
    @classmethod
    def _conjuntos_no_vacios(cls, v: list[list[str]]) -> list[list[str]]:
        if any(not claves for claves in v):
            raise ValueError("cada conjunto de claves de `respuestas` necesita al menos una clave")
        return v

    @field_validator("hasta_utc")
    @classmethod
    def _fecha_utc(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", v):
            raise ValueError("hasta_utc va como 2026-10-07T03:22:07Z (ISO 8601 UTC, igual que `creado_utc` de la caché)")
        return v


class TextosCache(ModeloConfig):
    sin_cache: str = Field(min_length=1)
    sin_cache_grupo: str = Field(min_length=1)
    borrador_invalido: str = Field(min_length=1)
    desajuste_proveedor: str = Field(min_length=1)
    sin_red: str = Field(min_length=1)


class ConfigCache(ModeloConfig):
    """Caché de respuestas del LLM (E1-14): dónde vive, qué la invalida y cómo se detecta que no hay red."""

    version: str
    version_cache: str = Field(min_length=1)
    proveedor_por_defecto: Literal["deepseek", "ollama"]
    ruta: str = Field(min_length=1)
    sondeo_red: SondeoRed
    variable_offline: str = Field(min_length=1)
    calentamiento: CalentamientoCache
    etiquetado_prompt: list[ReglaEtiquetadoPrompt]
    textos: TextosCache


def cargar_cache(carpeta: Path | None = None) -> ConfigCache:
    """Atajo para ``config/cache.yaml``."""
    return cargar_config("cache", ConfigCache, carpeta)


# ------------------------------------------------------------------ reproducibilidad.yaml (E1-20)


class PasoReproduccion(ModeloConfig):
    """Un paso del pipeline: un módulo que se ejecuta con ``python -m`` o un paso interno de ``scripts/reproducir.py``."""

    nombre: str = Field(min_length=1)
    tipo: Literal["modulo", "interno"]
    modulo: str | None = None
    argumentos: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _modulo_solo_si_corresponde(self) -> "PasoReproduccion":
        if (self.tipo == "modulo") != (self.modulo is not None):
            raise ValueError(f"paso {self.nombre!r}: «modulo» es obligatorio con tipo «modulo» y no se admite con tipo «interno»")
        return self


class MuestraSustentoReproduccion(ModeloConfig):
    archivo: str = Field(min_length=1)
    columnas_humanas: list[str] = Field(min_length=1)


class SalidasReproduccion(ModeloConfig):
    archivos: list[str] = Field(min_length=1)
    informes: dict[str, list[str]]
    tablas: list[str] = Field(min_length=1)
    fichas: str = Field(min_length=1)
    muestra_sustento: MuestraSustentoReproduccion
    metricas: str = Field(min_length=1)
    excluir_de_metricas: list[str]


class RegistroReproduccion(ModeloConfig):
    archivo_reglas: str = Field(min_length=1)
    carpeta_prompts: str = Field(min_length=1)


class ConfigReproducibilidad(ModeloConfig):
    """Pipeline de punta a punta y qué salidas se comparan (E1-20, D-65)."""

    version: str
    modalidad: Literal["editorial", "banca"]
    decimales: int = Field(ge=0, le=12)
    reiniciar_cache_embeddings: bool
    pasos: list[PasoReproduccion] = Field(min_length=1)
    salidas: SalidasReproduccion
    registro: RegistroReproduccion

    @model_validator(mode="after")
    def _pasos_sin_repetir(self) -> "ConfigReproducibilidad":
        nombres = [p.nombre for p in self.pasos]
        repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
        if repetidos:
            raise ValueError(f"pasos repetidos: {repetidos}")
        return self


def cargar_reproducibilidad(carpeta: Path | None = None) -> ConfigReproducibilidad:
    """Atajo para ``config/reproducibilidad.yaml``."""
    return cargar_config("reproducibilidad", ConfigReproducibilidad, carpeta)


# ------------------------------------------------------------------ revision.yaml (E1-16)


class AlmacenRevision(ModeloConfig):
    base: str = Field(min_length=1)
    base_demo: str = Field(min_length=1)


class CasosRevision(ModeloConfig):
    prefijo: str = Field(pattern=r"^[A-Z]+-$")
    ancho: int = Field(ge=1)


class AccionRevision(ModeloConfig):
    etiqueta: str = Field(min_length=1)
    desde: list[str] = Field(min_length=1)
    hacia: str
    motivo: Literal["ninguno", "lista", "texto"]
    nueva_version: bool


class RevisorConfig(ModeloConfig):
    nombre: str = Field(min_length=1)
    rol: str = Field(min_length=1)
    modalidad: Literal["editorial", "banca"]
    provisional: bool = False  # D-112: el asistente revisa de forma provisional; toda aprobación suya se rotula y una persona la rehace en C-09


class VinculoRechazadoRevision(ModeloConfig):
    codigo: str = Field(min_length=1)
    texto: str = Field(min_length=1)
    verificacion: str = Field(min_length=1)


class CorreccionRevision(ModeloConfig):
    prefijo_afirmaciones: str = Field(min_length=1)
    advertencia_vacio: str = Field(min_length=1)


class ExportacionRevision(ModeloConfig):
    carpeta: str = Field(min_length=1)
    csv: str = Field(min_length=1)
    fichas_jsonl: str = Field(min_length=1)
    carpeta_demo: str = Field(min_length=1)
    fichas_jsonl_demo: str = Field(min_length=1)
    max_caracteres_texto: int = Field(ge=100)
    marca_recorte: str
    columnas: list[str] = Field(min_length=1)
    modalidades: dict[str, str]
    sin_borrador: str = Field(min_length=1)


class TextosRevision(ModeloConfig):
    limitacion_historial: str
    sin_datos: str
    marca_provisional: str = Field(min_length=1)  # D-112: se agrega junto al revisor cuando su entrada es provisional


class ConfigRevision(ModeloConfig):
    """Modelo de ``config/revision.yaml``: estados, transiciones, motivos y revisores de la revisión humana (E1-16)."""

    version: str
    almacen: AlmacenRevision
    casos: CasosRevision
    estados: list[str] = Field(min_length=5, max_length=5)
    estado_inicial: str
    acciones: dict[str, AccionRevision]
    motivos_descarte: list[str] = Field(min_length=1)
    motivos_con_comentario: list[str]
    revisores: list[RevisorConfig] = Field(min_length=1)
    limitacion_revisor: str
    vinculo_rechazado: VinculoRechazadoRevision
    correccion: CorreccionRevision
    exportacion: ExportacionRevision
    textos: TextosRevision

    @model_validator(mode="after")
    def _coherente(self) -> ConfigRevision:
        if self.estado_inicial != self.estados[0]:
            raise ValueError("estado_inicial: debe ser el primero de estados")
        aprobado = "aprobado como borrador"
        if self.estados[3] != aprobado or self.estados[-1] == aprobado:
            raise ValueError("estados: los cinco del reto (sección 8); «aprobado como borrador» es el estado máximo y no es el último de la lista")
        obligatorias = {"abrir", "aceptar", "corregir", "pedir_evidencia", "descartar", "reabrir", "regenerar", "rechazar_vinculo", "restaurar_vinculo"}
        if set(self.acciones) != obligatorias:
            raise ValueError(f"acciones: deben ser exactamente {sorted(obligatorias)}")
        for nombre, a in self.acciones.items():
            if a.hacia not in self.estados or any(d not in self.estados for d in a.desde):
                raise ValueError(f"acciones.{nombre}: desde y hacia deben ser estados conocidos")
            if self.estado_inicial in a.desde and nombre != "abrir":
                raise ValueError("solo «abrir» parte del estado inicial")
            if a.hacia == self.estado_inicial:
                raise ValueError("ninguna acción vuelve al estado inicial")
        if self.acciones["aceptar"].etiqueta != "Aprobar como borrador" or self.acciones["aceptar"].hacia != aprobado:
            raise ValueError("aceptar: el botón dice «Aprobar como borrador» y llega a «aprobado como borrador»")
        if self.acciones["descartar"].motivo != "lista" or self.acciones["descartar"].hacia != "descartado":
            raise ValueError("descartar: lleva un motivo obligatorio de la lista y llega a «descartado»")
        if not set(self.motivos_con_comentario) <= set(self.motivos_descarte):
            raise ValueError("motivos_con_comentario: deben estar en motivos_descarte")
        if len(self.motivos_descarte) != len(set(self.motivos_descarte)):
            raise ValueError("motivos_descarte: sin repetidos")
        if {r.modalidad for r in self.revisores} != {"editorial", "banca"}:
            raise ValueError("revisores: debe haber al menos uno por modalidad")
        if len({(r.nombre, r.modalidad) for r in self.revisores}) != len(self.revisores):
            raise ValueError("revisores: una persona aparece una sola vez por modalidad")
        if any(r.provisional and r.modalidad == "editorial" for r in self.revisores) != any(r.provisional and r.modalidad == "banca" for r in self.revisores):
            raise ValueError("revisores: un revisor provisional se declara en las dos modalidades (D-112)")
        if all(r.provisional for r in self.revisores):
            raise ValueError("revisores: debe haber al menos una persona no provisional (D-112)")
        if self.exportacion.carpeta_demo == self.exportacion.carpeta or self.exportacion.fichas_jsonl_demo == self.exportacion.fichas_jsonl:
            raise ValueError("exportacion: la demo exporta a rutas distintas de las reales")
        if len(self.exportacion.columnas) != len(set(self.exportacion.columnas)) or "ID caso" not in self.exportacion.columnas:
            raise ValueError("exportacion.columnas: sin repetidos y con «ID caso»")
        textos = [
            *self.estados, *self.motivos_descarte, self.limitacion_revisor, *self.textos.model_dump().values(),
            *(a.etiqueta for a in self.acciones.values()), *self.exportacion.columnas, self.vinculo_rechazado.texto, self.vinculo_rechazado.verificacion,
        ]
        if any(FORMAS_DE_PUBLICAR.search(t) for t in textos):
            raise ValueError("ningún texto de la revisión puede hablar de publicar")
        return self

    def transiciones(self) -> dict[str, set[tuple[str, str]]]:
        """Acción -> pares ``(estado anterior, estado nuevo)`` permitidos. Es la única fuente de las transiciones."""
        return {n: {(d, a.hacia) for d in a.desde} for n, a in self.acciones.items()}


def cargar_revision(carpeta: Path | None = None) -> ConfigRevision:
    """Atajo para ``config/revision.yaml``."""
    return cargar_config("revision", ConfigRevision, carpeta)


# ------------------------------------------------------------------ precision.yaml (E1-19)


class HojaCiegaPrecision(ModeloConfig):
    semilla: str = Field(min_length=1)
    columnas: list[str] = Field(min_length=1)
    marca: str = Field(min_length=1)


class ArchivosPrecision(ModeloConfig):
    hoja: str = Field(min_length=1)
    seleccion: str = Field(min_length=1)
    salida: str = Field(min_length=1)


class TextosPrecision(ModeloConfig):
    pendiente: str = Field(min_length=1)
    exploratoria: str = Field(min_length=1)
    motivo_pocos_cortes: str = Field(min_length=1)
    motivo_sin_especialista: str = Field(min_length=1)
    sin_especialista: str = Field(min_length=1)
    criterio_de_empate: str = Field(min_length=1)   # D-105: cómo se resuelven y se informan los empates en el corte del top k


class ConfigPrecision(ModeloConfig):
    """Precision@5 contra la selección de un editor (E1-19): k, cortes mínimos y la hoja ciega (sin puntajes ni posiciones)."""

    version: int
    k: int = Field(ge=1)
    cortes_minimos: int = Field(ge=1)
    hoja_ciega: HojaCiegaPrecision
    archivos: ArchivosPrecision
    textos: TextosPrecision

    @model_validator(mode="after")
    def _hoja_sin_pistas(self) -> ConfigPrecision:
        prohibidas = {"puntaje", "posicion", "rango", "relevancia", "impacto", "urgencia", "novedad", "evidencia", "estado", "accion"}
        filtradas = prohibidas & set(self.hoja_ciega.columnas)
        if filtradas:
            raise ValueError(f"hoja_ciega.columnas: la hoja del editor no puede llevar {sorted(filtradas)} (revelan el ranking)")
        for obligatoria in ("id_grupo", "seleccion"):
            if obligatoria not in self.hoja_ciega.columnas:
                raise ValueError(f"hoja_ciega.columnas: falta {obligatoria!r}")
        return self


def cargar_precision(carpeta: Path | None = None) -> ConfigPrecision:
    """Atajo para ``config/precision.yaml``."""
    return cargar_config("precision", ConfigPrecision, carpeta)


# ------------------------------------------------------------------ origen_juicio.yaml (D-101)


class ConfigOrigenJuicio(ModeloConfig):
    """Procedencia de los juicios que alimentan una métrica (D-101): la columna, el origen humano y la etiqueta de cada origen."""

    version: int
    columna: str = Field(min_length=1)
    humano: str = Field(min_length=1)
    origenes: dict[str, str] = Field(min_length=2)
    aviso_provisional: str = Field(min_length=1)

    @model_validator(mode="after")
    def _humano_y_no_humano(self) -> ConfigOrigenJuicio:
        if self.humano not in self.origenes:
            raise ValueError(f"humano: {self.humano!r} no está en origenes {sorted(self.origenes)}")
        if any(k != k.strip().lower() or not v.strip() for k, v in self.origenes.items()):
            raise ValueError("origenes: cada clave va en minúsculas sin espacios y cada etiqueta no puede quedar vacía")
        return self


def cargar_origen_juicio(carpeta: Path | None = None) -> ConfigOrigenJuicio:
    """Atajo para ``config/origen_juicio.yaml``."""
    return cargar_config("origen_juicio", ConfigOrigenJuicio, carpeta)


# ------------------------------------------------------------------ pruebas.yaml (E1-17)

IDS_PRUEBAS_ACEPTACION = tuple(f"T{n:02d}" for n in range(1, 11))


class ConfigPruebas(ModeloConfig):
    """Modelo de ``config/pruebas.yaml``: por prueba T01–T10, la parte que el test no cubre y por qué sigue pendiente."""

    pendientes: dict[str, str]

    @field_validator("pendientes")
    @classmethod
    def _ids_y_causas(cls, v: dict[str, str]) -> dict[str, str]:
        ajenos = sorted(set(v) - set(IDS_PRUEBAS_ACEPTACION))
        if ajenos:
            raise ValueError(f"ids que no son T01–T10: {ajenos}")
        vacias = sorted(k for k, causa in v.items() if not causa.strip())
        if vacias:
            raise ValueError(f"causa vacía en {vacias}")
        return v


def cargar_pruebas(carpeta: Path | None = None) -> ConfigPruebas:
    """Atajo para ``config/pruebas.yaml``."""
    return cargar_config("pruebas", ConfigPruebas, carpeta)


CODIGO_URGENCIA_SIN_PUBLICACION ="urgencia_sin_publicacion"   # el único vacío de E1-10 cuyo texto vive en reglas_v1.3.yaml
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
    "procedencias": cargar_procedencias,
    "consulta": cargar_consulta,
    "prioridad": cargar_prioridad,
    "generacion": cargar_generacion,
    "validador": cargar_validador,
    "verificacion": cargar_verificacion,
    "interfaz": cargar_interfaz,
    "cache": cargar_cache,
    "revision": cargar_revision,
    "precision": cargar_precision,
    "origen_juicio": cargar_origen_juicio,
    "pruebas": cargar_pruebas,
    "reproducibilidad": cargar_reproducibilidad,
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
