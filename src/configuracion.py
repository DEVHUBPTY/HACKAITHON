"""Carga de configuración validada (D-79).

Todo YAML de ``config/`` se lee con ``yaml.safe_load`` y se valida con un modelo pydantic que
prohíbe claves desconocidas y coerciones de tipo. Así se detectan sangrías rotas, claves mal
escritas y trampas de YAML como ``no`` → ``False``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    consultas: dict[str, str]


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
TOLERANCIA = 1e-9


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
        return self


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
    relevancia: Relevancia
    impacto: Impacto
    urgencia: Urgencia
    novedad: Novedad
    evidencia: EvidenciaReglas
    estado_evidencia: EstadoEvidencia
    agrupacion: Agrupacion
    agencias: list[str]
    geografia: Geografia


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
    temas: dict[str, Tema]
    fuera_de_temas: FueraDeTemas

    @model_validator(mode="after")
    def _seis_temas(self) -> ConfigTemas:
        if len(self.temas) != 6:
            raise ValueError(f"deben ser 6 temas, hay {len(self.temas)}")
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
    ventana_coincidencia_dias: int = Field(ge=0)
    pais_por_defecto: str
    vinculos: dict[str, Vinculo]

    @model_validator(mode="after")
    def _relaciones_declaradas(self) -> ConfigVinculos:
        malas = {v.relacion for v in self.vinculos.values()} - set(self.tipos_relacion)
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


class Accion(ModeloConfig):
    accion: str
    motivo: str

    @model_validator(mode="after")
    def _sin_publicar(self) -> Accion:
        if "public" in f"{self.accion} {self.motivo}".lower():
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
    tabla_acciones: TablaAcciones
    fuentes_sugeridas_extra: list[str]
    sectores_por_tema: dict[str, str] = Field(default_factory=dict)  # banca: tema -> sector


def cargar_modalidad(modalidad: str, carpeta: Path | None = None) -> ConfigModalidad:
    """Atajo para ``config/modalidad_<modalidad>.yaml``."""
    cfg = cargar_config(f"modalidad_{modalidad}", ConfigModalidad, carpeta)
    if cfg.modalidad != modalidad:
        raise ErrorDeConfiguracion(f"modalidad_{modalidad}.yaml: declara modalidad '{cfg.modalidad}'")
    return cfg


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


class FrasesProhibidas(ModeloConfig):
    lectura_simulada: list[str]
    entrevistas: list[str]
    imagenes: list[str]
    recomendacion: list[str]
    certeza: list[str]


class ConfigRestricciones(ModeloConfig):
    """Modelo de ``config/restricciones.yaml`` (D-25, D-51)."""

    version: str
    marca_borrador: str
    marcador_visual: str
    aviso_banca: str
    leyendas_alcance: LeyendasAlcance
    frases_prohibidas: FrasesProhibidas
    frases_prohibidas_en_inferencias: list[str]
    palabras_sensacionalistas: list[str]


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
    indicadores = set(cargar_fuentes(carpeta).banco_mundial.indicadores)
    for sub, v in vinculos.vinculos.items():
        if v.fuente == "indicador" and v.id not in indicadores:
            problemas.append(f"vinculos.yaml: {sub} usa el indicador {v.id}, que no está en fuentes.yaml")
    reales = {e.id_noticia for t in temas.temas.values() for e in t.ejemplos if e.real}
    excluidos = _ids_excluidos(carpeta / "ejemplos_excluidos.txt")
    if reales != excluidos:
        problemas.append(f"ejemplos_excluidos.txt no coincide con los ejemplos reales de temas.yaml: {sorted(reales ^ excluidos)}")
    for modalidad in ("editorial", "banca"):
        if (carpeta / f"modalidad_{modalidad}.yaml").exists():
            cargar_modalidad(modalidad, carpeta)
    return problemas


ARCHIVOS_VALIDADOS = ["fuentes", "exploracion", "reglas_v1.3", "temas", "vinculos", "modalidad_editorial", "salidas", "restricciones"]


def validar_todo(carpeta: Path | None = None) -> list[str]:
    """Carga cada YAML con su modelo estricto y valida la coherencia; lanza el primer error."""
    cargar_fuentes(carpeta)
    cargar_exploracion(carpeta)
    cargar_salidas(carpeta)
    cargar_restricciones(carpeta)
    problemas = validar_coherencia(carpeta)
    if problemas:
        raise ErrorDeConfiguracion("; ".join(problemas))
    return ARCHIVOS_VALIDADOS


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
