"""Carga de configuración validada (D-79).

Todo YAML de ``config/`` se lee con ``yaml.safe_load`` y se valida con un modelo pydantic que
prohíbe claves desconocidas y coerciones de tipo. Así se detectan sangrías rotas, claves mal
escritas y trampas de YAML como ``no`` → ``False``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

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
