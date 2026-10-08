"""D-130 · Carga en vivo de la etapa 1 y las etapas que la siguen, sobre una base propia de la corrida.

Lógica sin Streamlit (la pantalla «1 · Cargar» solo pinta). Una ``Corrida`` ejecuta paso a paso, con tiempos y cifras reales:

    fuentes → validación → normalización → almacenamiento → limpieza → clasificación → agrupación → contexto → puntaje

* **Solo lectura sobre lo vivo.** Lee ``data/raw/``, ``data/processed/`` y ``data/manifest.json``; todo lo que escribe (filas válidas,
  errores, reportes, ``senales.duckdb`` de la corrida) va a una carpeta propia bajo el directorio temporal del sistema
  (``config/corrida.yaml``). Nunca toca ``data/senales.duckdb``, ``data/revision.duckdb`` ni ``outputs/``.
* **Sin red y sin LLM.** Los embeddings son locales; el puntaje se calcula sin el modelo de lenguaje (``--sin-llm``).
* **Honesta.** ``comparar_con_base`` dice si la corrida reproduce la base de la app y, si no, lista cada diferencia.
* **T01 con un archivo propio.** ``validar_archivo_propio`` aplica solo la etapa 1 a un CSV subido y devuelve, fila por fila, si se aceptó
  o se rechazó y por qué. No alimenta ninguna base.

Los módulos de cada etapa se llaman por sus funciones públicas (``ejecutar``), no por subproceso.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.configuracion import RAIZ, ConfigCorrida, cargar_carga, cargar_contrato, cargar_corrida, cargar_normalizacion

logger = logging.getLogger(__name__)

ESTADO_OK = "ok"
ESTADO_AVISO = "aviso"
ESTADO_FALLA = "falla"
ESTADO_OMITIDO = "omitido"
MARCA_OK = "✓"
MARCA_MAL = "✗"
SIN_DATO = "—"
BLOQUE_DE_LECTURA = 1 << 20   # bytes por lectura al calcular un SHA-256 (no es un parámetro del pipeline)
LARGO_HASH_VISIBLE = 12       # caracteres de un SHA-256 que se muestran en pantalla (el completo está en el manifest)


class ErrorDeCorrida(RuntimeError):
    """Un paso necesita algo que todavía no se ejecutó, o el archivo subido no es utilizable."""


# ============================================================================================ resultados


@dataclass
class Paso:
    """Lo que se muestra de un paso: su explicación, sus cifras reales, sus tablas y el tiempo que tardó."""

    clave: str
    titulo: str
    explicacion: str
    estado: str = ESTADO_OK
    segundos: float = 0.0
    cifras: dict[str, Any] = field(default_factory=dict)
    tablas: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    mensajes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FilaComparacion:
    etiqueta: str
    corrida: Any
    viva: Any

    @property
    def igual(self) -> bool:
        return self.corrida == self.viva


@dataclass
class Comparacion:
    """Esta carga contra la base de la app: cuentas y huellas fila a fila."""

    filas: list[FilaComparacion]

    @property
    def iguales(self) -> bool:
        return all(f.igual for f in self.filas)

    @property
    def diferencias(self) -> list[FilaComparacion]:
        return [f for f in self.filas if not f.igual]


# ============================================================================================ utilidades


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while bloque := f.read(BLOQUE_DE_LECTURA):
            h.update(bloque)
    return h.hexdigest()


def huellas_de_arbol(carpeta: Path) -> dict[str, str]:
    """SHA-256 de cada archivo bajo ``carpeta`` (ruta relativa -> hash). Una carpeta ausente da ``{}``."""
    if not carpeta.is_dir():
        return {}
    return {p.relative_to(carpeta).as_posix(): sha256_archivo(p) for p in sorted(carpeta.rglob("*")) if p.is_file()}


def contar_registros(ruta: Path) -> int | None:
    """Registros de un archivo del snapshot: filas de un CSV, ``features`` de un GeoJSON o elementos de un JSON lista. ``None`` si no aplica."""
    if not ruta.is_file():
        return None
    if ruta.suffix == ".csv":
        with ruta.open(encoding="utf-8", newline="") as f:
            return max(sum(1 for _ in csv.reader(f)) - 1, 0)
    if ruta.suffix in {".geojson", ".json"}:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if isinstance(datos, list):
            return len(datos)
        if isinstance(datos, dict) and isinstance(datos.get("features"), list):
            return len(datos["features"])
    return None


def _corto(h: str | None) -> str:
    return SIN_DATO if not h else h[:LARGO_HASH_VISIBLE]


def raiz_de_corridas(cfg: ConfigCorrida) -> Path:
    return Path(tempfile.gettempdir()) / cfg.corridas.carpeta


def _es_carpeta_de_corrida(ruta: Path, formato: str) -> bool:
    """Una carpeta creada por ``crear_carpeta_de_corrida`` (su nombre es una hora UTC, con sufijo opcional): nunca se borra otra cosa."""
    if not ruta.is_dir():
        return False
    try:
        datetime.strptime(ruta.name.split("-")[0], formato)
    except ValueError:
        return False
    return True


def crear_carpeta_de_corrida(cfg: ConfigCorrida, ahora: datetime | None = None, subcarpeta: str | None = None) -> Path:
    """Crea ``<tmp>/<carpeta>[/<subcarpeta>]/<hora UTC>`` y borra las más viejas de esa misma carpeta (se conservan ``conservar_ultimas``)."""
    raiz = raiz_de_corridas(cfg) / (subcarpeta or "")
    raiz.mkdir(parents=True, exist_ok=True)
    sello = (ahora or datetime.now(timezone.utc)).strftime(cfg.corridas.formato_nombre)
    carpeta = raiz / sello
    sufijo = 1
    while carpeta.exists():   # dos corridas en el mismo segundo no se pisan
        sufijo += 1
        carpeta = raiz / f"{sello}-{sufijo}"
    carpeta.mkdir()
    previas = sorted((p for p in raiz.iterdir() if p != carpeta and _es_carpeta_de_corrida(p, cfg.corridas.formato_nombre)), key=lambda p: p.name)
    for vieja in previas[: max(len(previas) - (cfg.corridas.conservar_ultimas - 1), 0)]:
        shutil.rmtree(vieja, ignore_errors=True)
    return carpeta


def _filas_sql(con: Any, consulta: str) -> list[tuple[Any, ...]]:
    return con.execute(consulta).fetchall()


def _redondear(valor: Any, decimales: int) -> Any:
    if isinstance(valor, float):
        return round(valor, decimales) + 0.0
    return valor


# ============================================================================================ la corrida


class Corrida:
    """Una ejecución del paquete congelado. ``raiz`` es la raíz del repositorio (los datos vivos); ``carpeta`` es lo único donde se escribe."""

    def __init__(self, cfg: ConfigCorrida | None = None, raiz: Path = RAIZ, carpeta: Path | None = None) -> None:
        self.cfg = cfg or cargar_corrida()
        self.raiz = Path(raiz)
        self.carpeta = Path(carpeta) if carpeta else crear_carpeta_de_corrida(self.cfg)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.validos = self.carpeta / self.cfg.corridas.subcarpeta_validos
        self.salida = self.carpeta / self.cfg.corridas.subcarpeta_salida
        self.base = self.carpeta / cargar_normalizacion().salida.base_de_datos
        self.reporte_calidad = self.salida / cargar_carga().salida.reporte
        self.pasos: dict[str, Paso] = {}
        self._antes: dict[str, dict[str, str]] = {}
        self._tablas: dict[str, list[dict[str, Any]]] = {}
        self._manifest: dict[str, Any] = {}
        self._resultados: dict[str, Any] = {}
        self._reporte_carga: dict[str, Any] = {}
        self._metodos: dict[str, Callable[[], Paso]] = {
            "fuentes": self._fuentes, "validacion": self._validacion, "normalizacion": self._normalizacion, "almacenamiento": self._almacenamiento,
            "limpieza": self._limpieza, "clasificacion": self._clasificacion, "agrupacion": self._agrupacion, "contexto": self._contexto,
            "puntaje": self._puntaje,
        }

    # ---- rutas de los insumos (solo lectura)

    def _ruta(self, relativa: str) -> Path:
        return self.raiz / relativa

    @property
    def procesados(self) -> Path:
        return self._ruta(self.cfg.insumos.carpeta_procesados)

    @property
    def crudos(self) -> Path:
        return self._ruta(self.cfg.insumos.carpeta_crudos)

    # ---- orquestación

    def claves(self) -> list[str]:
        return [p.clave for p in self.cfg.pasos]

    def definicion(self, clave: str) -> Any:
        return next(p for p in self.cfg.pasos if p.clave == clave)

    def ejecutar_paso(self, clave: str) -> Paso:
        """Ejecuta un paso y lo mide. Una excepción no se propaga: queda como ``falla`` con su mensaje (los pasos siguientes se omiten)."""
        d = self.definicion(clave)
        previos_fallidos = [p for p in self.pasos.values() if p.estado == ESTADO_FALLA]
        if previos_fallidos:
            paso = Paso(clave, d.titulo, d.explicacion, ESTADO_OMITIDO, 0.0, mensajes=[f"Se omite: falló «{previos_fallidos[0].titulo}»."])
            self.pasos[clave] = paso
            return paso
        inicio = time.perf_counter()
        try:
            paso = self._metodos[clave]()
        except Exception as exc:  # noqa: BLE001 - un paso que falla se muestra, no rompe la pantalla
            logger.exception("Falló el paso %s", clave)
            paso = Paso(clave, d.titulo, d.explicacion, ESTADO_FALLA, mensajes=[f"{type(exc).__name__}: {exc}"])
        paso.segundos = time.perf_counter() - inicio
        paso.titulo, paso.explicacion = d.titulo, d.explicacion
        self.pasos[clave] = paso
        return paso

    def ejecutar_todo(self) -> list[Paso]:
        return [self.ejecutar_paso(c) for c in self.claves()]

    def _nuevo(self, clave: str) -> Paso:
        d = self.definicion(clave)
        return Paso(clave, d.titulo, d.explicacion)

    def _exigir(self, *claves: str) -> None:
        faltan = [c for c in claves if c not in self.pasos or self.pasos[c].estado not in {ESTADO_OK, ESTADO_AVISO}]
        if faltan:
            raise ErrorDeCorrida(f"antes hay que ejecutar: {', '.join(faltan)}")

    # ---- 1 · fuentes

    def _fuentes(self) -> Paso:
        from src import interfaz as ui   # import tardío: la interfaz importa medio pipeline

        paso = self._nuevo("fuentes")
        manifest_ruta = self._ruta(self.cfg.insumos.manifest)
        self._manifest = json.loads(manifest_ruta.read_text(encoding="utf-8"))
        m = self._manifest
        self._antes = {"crudos": huellas_de_arbol(self.crudos), "procesados": huellas_de_arbol(self.procesados)}
        registrados = m.get("sha256", {})
        cantidades = m.get("cantidad_por_archivo", {})
        archivos = []
        for clave, esperado in registrados.items():
            nombre = Path(clave).name
            ruta = self.raiz / self.cfg.insumos.carpeta_datos / clave
            actual = self._antes["procesados"].get(Path(clave).relative_to("processed").as_posix()) if ruta.is_file() else None
            leidos = contar_registros(ruta)
            en_manifest = cantidades.get(nombre)
            archivos.append({
                "Archivo": clave, "Registros leídos": SIN_DATO if leidos is None else leidos,
                "Registros en el manifest": SIN_DATO if en_manifest is None else en_manifest,
                "SHA-256 del manifest": _corto(esperado), "SHA-256 del archivo": _corto(actual),
                "Coincide": MARCA_OK if actual == esperado else MARCA_MAL,
                "_igual": actual == esperado and (leidos is None or en_manifest is None or leidos == en_manifest),
            })
        crudos_registrados = m.get("crudos", {})
        datos = self._ruta(self.cfg.insumos.carpeta_datos)
        por_carpeta: dict[str, Counter[str]] = {}
        for clave, v in crudos_registrados.items():
            carpeta = Path(clave).parent.name
            ruta = datos / clave
            estado = "ausente" if not ruta.is_file() else ("coincide" if self._antes["crudos"].get(Path(clave).relative_to("raw").as_posix()) == v.get("sha256") else "distinto")
            por_carpeta.setdefault(carpeta, Counter())[estado] += 1
        crudos = [
            {"Fuente cruda": c, "Archivos en el manifest": sum(n.values()), "Coinciden": n["coincide"], "Distintos": n["distinto"], "Ausentes": n["ausente"],
             "Coincide": MARCA_OK if not n["distinto"] and not n["ausente"] else MARCA_MAL}
            for c, n in sorted(por_carpeta.items())
        ]
        distintos = sum(n["distinto"] for n in por_carpeta.values())
        ausentes = sum(n["ausente"] for n in por_carpeta.values())
        malos = [a for a in archivos if not a["_igual"]]
        for a in archivos:
            a.pop("_igual")
        corte = m.get("fecha_corte_UTC")
        paso.cifras = {
            "Versión del snapshot": m.get("version", SIN_DATO),
            "Fecha de corte (UTC)": corte or SIN_DATO,
            "Fecha de corte (hora de Panamá)": ui.hora_panama(corte, ui.cargar_verificacion()) if corte else SIN_DATO,
            "Archivos procesados leídos": len(archivos),
            "Archivos con el hash del manifest": len(archivos) - len(malos),
            "Registros leídos (con conteo directo)": sum(a["Registros leídos"] for a in archivos if isinstance(a["Registros leídos"], int)),
            "Crudos en el manifest": sum(sum(n.values()) for n in por_carpeta.values()),
            "Crudos distintos del manifest": distintos,
            "Crudos ausentes en esta máquina": ausentes,
        }
        paso.tablas = {"Archivos del snapshot (data/processed)": archivos, "Crudos (data/raw)": crudos}
        if malos or distintos:
            paso.estado = ESTADO_AVISO
            paso.mensajes.append("Hay archivos cuyo hash no coincide con el manifest: el paquete no es exactamente el congelado.")
        if ausentes:
            paso.mensajes.append(
                f"{ausentes} crudos no están en esta máquina (el RSS, GDELT y la SBP no se versionan, D-72): no se pudieron verificar."
            )
        return paso

    # ---- 2 · validación

    def _reglas(self) -> list[dict[str, Any]]:
        c, contrato = cargar_carga(), cargar_contrato()
        n, i, e, f = c.noticias, c.indicadores, c.eventos, c.fuentes
        return [
            {"Archivo": c.archivos.noticias, "Regla": "Campos del contrato", "Detalle": ", ".join(contrato.noticias)},
            {"Archivo": c.archivos.noticias, "Regla": "ID (prefijo y forma)", "Detalle": n.patron_id},
            {"Archivo": c.archivos.noticias, "Regla": "Campos obligatorios", "Detalle": ", ".join(n.criticos)},
            {"Archivo": c.archivos.noticias, "Regla": "Fechas ISO 8601 UTC", "Detalle": f"{c.fechas.iso_utc.patron} · al menos una de {', '.join(n.fechas_alternativas)}"},
            {"Archivo": c.archivos.noticias, "Regla": "URL", "Detalle": c.patron_url},
            {"Archivo": c.archivos.noticias, "Regla": "ID único", "Detalle": "se conserva la primera aparición válida; las demás son id_duplicado"},
            {"Archivo": c.archivos.noticias, "Regla": "Campos opcionales vacíos", "Detalle": f"{', '.join(n.opcionales)}: quedan como nulos, no invalidan la fila"},
            {"Archivo": c.archivos.indicadores, "Regla": "Campos del contrato", "Detalle": ", ".join(contrato.indicadores)},
            {"Archivo": c.archivos.indicadores, "Regla": "ID, país y año", "Detalle": f"{i.patron_id} · país {i.patron_pais} · año {i.patron_anio} entre {i.anio_minimo} y {i.anio_maximo}"},
            {"Archivo": c.archivos.indicadores, "Regla": "Campos obligatorios", "Detalle": ", ".join(i.criticos)},
            {"Archivo": c.archivos.indicadores, "Regla": "Clave única", "Detalle": ", ".join(i.clave)},
            {"Archivo": c.archivos.indicadores, "Regla": "Valor nulo", "Detalle": "es válido: los nulos son nulos, nunca se rellenan con cero"},
            {"Archivo": c.archivos.eventos, "Regla": "ID y obligatorios", "Detalle": f"{e.patron_id} · {', '.join(e.criticos)} · |lat| ≤ {e.latitud_maxima}, |lon| ≤ {e.longitud_maxima}"},
            {"Archivo": c.archivos.fuentes, "Regla": "Obligatorios", "Detalle": ", ".join(f.criticos)},
        ]

    def _validacion(self) -> Paso:
        from src import carga   # import tardío: pandera pesa

        self._exigir("fuentes")
        paso = self._nuevo("validacion")
        config = cargar_carga()
        resultados = carga.cargar_todo(self.procesados, config)
        reporte = carga.construir_reporte(resultados, config)
        self.salida.mkdir(parents=True, exist_ok=True)
        escritos = carga.escribir_validos(resultados, self.validos, config)
        n_errores = carga.escribir_errores(resultados, self.salida / config.salida.errores)
        self.reporte_calidad.write_text(json.dumps(reporte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._resultados, self._reporte_carga = resultados, reporte
        t = reporte["totales"]
        paso.cifras = {
            "Registros leídos": t["leidas"], "Válidos": t["validas"], "Rechazados": t["rechazadas"],
            "Errores de archivo": t["errores_de_archivo"], "Líneas mal formadas": t["lineas_mal_formadas"],
            "Filas válidas escritas en": f"{self.validos.name}/ ({len(escritos)} archivos)",
        }
        vocabulario = [carga.OBLIGATORIO_VACIO, carga.FECHA_INVALIDA, carga.ID_DUPLICADO, carga.URL_MAL_FORMADA, carga.ID_FORMATO_INVALIDO,
                       carga.VALOR_INVALIDO, carga.COLUMNA_FALTANTE, carga.ESTRUCTURA_INVALIDA]
        por_tipo = t["errores_por_tipo"]
        paso.tablas["Reglas aplicadas (config/carga.yaml y config/contrato.yaml)"] = self._reglas()
        paso.tablas["Por archivo"] = [
            {"Archivo": a, "Leídas": v["leidas"], "Válidas": v["validas"], "Rechazadas": v["rechazadas"],
             "Errores": ", ".join(f"{k}: {n}" for k, n in v["errores_por_tipo"].items()) or "ninguno"}
            for a, v in reporte["archivos"].items()
        ]
        paso.tablas["Rechazos por tipo de error"] = [{"Tipo de error": k, "Filas con ese error": por_tipo.get(k, 0)} for k in vocabulario]
        nulos = [
            {"Archivo": a, "Campo": campo, "Nulos en las leídas": n, "Nulos en las válidas": v["nulos_por_campo"]["validas"].get(campo, 0)}
            for a, v in reporte["archivos"].items() for campo, n in v["nulos_por_campo"]["leidas"].items() if n
        ]
        if nulos:
            paso.tablas["Nulos conservados como nulos (nunca se rellenan con cero)"] = nulos
        if n_errores:
            paso.tablas["Rechazos (errores.csv)"] = _leer_csv_limitado(self.salida / config.salida.errores, self.cfg.archivo_propio.filas_visibles)
        if t["rechazadas"]:
            paso.estado = ESTADO_AVISO
            paso.mensajes.append(f"{t['rechazadas']} registros rechazados: quedan en errores.csv con su motivo; el resto sigue.")
        return paso

    # ---- 3 · normalización

    def _normalizacion(self) -> Paso:
        from src import normalizacion

        self._exigir("validacion")
        paso = self._nuevo("normalizacion")
        cfg_n = cargar_normalizacion()
        self._tablas = normalizacion.normalizar_carpeta(self.validos, cfg_n)
        noticias = self._tablas["noticias"]
        prefijo, sinteticos = cfg_n.noticias.prefijo_id, tuple(cfg_n.noticias.prefijos_sinteticos)
        con_id_url = sum(1 for r in noticias if str(r["id_noticia"]).startswith(prefijo))
        paso.cifras = {
            "Titulares normalizados": len(noticias),
            f"IDs {prefijo}<hash de la URL canónica>": con_id_url,
            "IDs sintéticos conservados": sum(1 for r in noticias if str(r["id_noticia"]).startswith(sinteticos)),
            "Duplicados eliminados (misma URL canónica)": len(self._tablas["duplicados_eliminados"]),
            "Titulares con fecha_publicacion nula": sum(1 for r in noticias if r.get("fecha_publicacion") is None),
            "Titulares con fecha_deteccion nula": sum(1 for r in noticias if r.get("fecha_deteccion") is None),
            "Titulares con descripción del RSS copiada": sum(1 for r in noticias if r.get("descripcion")),
            "Idiomas distintos (ISO 639-1)": len({r["idioma"] for r in noticias if r.get("idioma")}),
            "Cambios registrados (registro_normalizacion)": len(self._tablas["registro_normalizacion"]),
        }
        paso.tablas["Filas normalizadas por tabla"] = [{"Tabla": t, "Filas": len(f)} for t, f in self._tablas.items()]
        paso.tablas["Transformaciones declaradas (data/manifest.json)"] = [{"Transformación": t} for t in self._manifest.get("transformaciones", [])]
        paso.tablas["Parámetros de la normalización (config/normalizacion.yaml)"] = [
            {"Parámetro": "Formato de fecha de salida", "Valor": cfg_n.fechas.formato_salida},
            {"Parámetro": "Prefijo de ID de noticia", "Valor": prefijo},
            {"Parámetro": "Caracteres del SHA-1 de la URL canónica", "Valor": cfg_n.noticias.largo_hash_id},
            {"Parámetro": "Días para considerar una noticia recirculada", "Valor": cfg_n.noticias.dias_para_recirculada},
        ]
        cambios = Counter(str(r.get("motivo")) for r in self._tablas["registro_normalizacion"])
        if cambios:
            paso.tablas["Cambios por motivo"] = [{"Motivo": k, "Cambios": n} for k, n in cambios.most_common()]
        return paso

    # ---- 4 · almacenamiento

    def _almacenamiento(self) -> Paso:
        from src import db

        self._exigir("normalizacion")
        paso = self._nuevo("almacenamiento")
        conteos = db.guardar_todo(self.base, self._tablas)
        despues = {"crudos": huellas_de_arbol(self.crudos), "procesados": huellas_de_arbol(self.procesados)}
        intactos = despues == self._antes
        con = db.conectar(self.base, solo_lectura=True)
        try:
            tablas = []
            for tabla, n in conteos.items():
                columnas = [r[0] for r in _filas_sql(con, f"SELECT column_name FROM information_schema.columns WHERE table_name = '{tabla}' ORDER BY ordinal_position")]
                tablas.append({"Tabla": tabla, "Filas": n, "Columnas": f"{len(columnas)}: {', '.join(columnas)}"})
        finally:
            con.close()
        paso.cifras = {
            "Base de la corrida": f"{self.base.parent.name}/{self.base.name}",
            "Tablas creadas": len(conteos), "Filas en total": sum(conteos.values()),
            "Archivos de data/raw antes y después": f"{len(self._antes['crudos'])} · {'idénticos ' + MARCA_OK if self._antes['crudos'] == despues['crudos'] else 'DISTINTOS ' + MARCA_MAL}",
            "Archivos de data/processed antes y después": f"{len(self._antes['procesados'])} · {'idénticos ' + MARCA_OK if self._antes['procesados'] == despues['procesados'] else 'DISTINTOS ' + MARCA_MAL}",
        }
        paso.tablas["Tablas de la base de la corrida"] = tablas
        if not intactos:
            paso.estado = ESTADO_FALLA
            paso.mensajes.append("data/raw o data/processed cambiaron durante la corrida: esto no debería pasar.")
        return paso

    # ---- 5 a 9 · etapas siguientes sobre la base de la corrida

    def _sql(self, consulta: str) -> list[tuple[Any, ...]]:
        from src import db

        con = db.conectar(self.base, solo_lectura=True)
        try:
            return _filas_sql(con, consulta)
        finally:
            con.close()

    def _tabla_conteo(self, consulta: str, col_clave: str, col_n: str) -> list[dict[str, Any]]:
        return [{col_clave: "sin dato" if k is None else k, col_n: n} for k, n in self._sql(consulta)]

    def _limpieza(self) -> Paso:
        from src import limpieza

        self._exigir("almacenamiento")
        paso = self._nuevo("limpieza")
        limpieza.ejecutar(self.base, self.reporte_calidad)
        total, ruido = self._sql("SELECT count(*), count(*) FILTER (WHERE es_ruido) FROM noticias")[0]
        paso.cifras = {"Titulares": total, "Marcados como ruido": ruido, "Útiles (entran en la bandeja)": total - ruido}
        paso.tablas["Ruido por motivo"] = self._tabla_conteo("SELECT motivo_ruido, count(*) FROM noticias WHERE es_ruido GROUP BY 1 ORDER BY 2 DESC, 1", "Motivo", "Titulares")
        return paso

    def _clasificacion(self) -> Paso:
        from src import clasificacion

        self._exigir("limpieza")
        paso = self._nuevo("clasificacion")
        seccion = clasificacion.ejecutar(self.base, self.reporte_calidad)
        util = self._tabla_conteo("SELECT tema_clasificado, count(*) FROM noticias WHERE NOT es_ruido GROUP BY 1 ORDER BY 2 DESC, 1", "Tema", "Titulares")
        paso.cifras = {"Titulares clasificados": sum(r["Titulares"] for r in util if r["Tema"] != "sin dato")}
        emb = seccion.get("embeddings", {})
        if emb:
            paso.cifras["Titulares codificados con el modelo local"] = emb.get("codificados", SIN_DATO)
            paso.cifras["Aciertos de la caché de embeddings"] = emb.get("aciertos_cache", SIN_DATO)
        paso.tablas["Titulares por tema"] = util
        return paso

    def _agrupacion(self) -> Paso:
        from src import agrupacion

        self._exigir("clasificacion")
        paso = self._nuevo("agrupacion")
        agrupacion.ejecutar(self.base, self.reporte_calidad)
        grupos, titulares, mayor = self._sql("SELECT count(*), coalesce(sum(n_titulares), 0), coalesce(max(n_titulares), 0) FROM grupos")[0]
        procedencias = self._sql("SELECT count(*) FROM procedencias")[0][0]
        paso.cifras = {"Grupos": grupos, "Titulares agrupados": int(titulares), "Titulares del grupo más grande": mayor, "Procedencias independientes": procedencias}
        paso.tablas["Grupos por tema"] = self._tabla_conteo("SELECT tema_clasificado, count(*) FROM grupos GROUP BY 1 ORDER BY 2 DESC, 1", "Tema", "Grupos")
        return paso

    def _contexto(self) -> Paso:
        from src import contexto

        self._exigir("agrupacion")
        paso = self._nuevo("contexto")
        eventos = self.validos / cargar_carga().archivos.eventos
        reporte = contexto.ejecutar(self.base, self.salida / contexto.REPORTE, eventos if eventos.exists() else None, self._ruta(self.cfg.insumos.series_sbp))
        paso.cifras = {
            "Grupos en la base": reporte["grupos_en_base"], "Grupos con vínculo a un indicador del Banco Mundial": reporte["con_vinculo"]["n"],
            "Grupos sin vínculo (no se fuerza)": reporte["sin_vinculo"]["n"], "Filas en vínculos": self._sql("SELECT count(*) FROM vinculos")[0][0],
        }
        paso.tablas["Vínculos por fuente"] = self._tabla_conteo("SELECT coalesce(fuente, 'sin vínculo'), count(*) FROM vinculos GROUP BY 1 ORDER BY 2 DESC, 1", "Fuente", "Vínculos")
        paso.tablas["Grupos sin vínculo por motivo"] = [{"Motivo": k, "Grupos": n} for k, n in reporte.get("sin_vinculo_por_motivo", {}).items()]
        return paso

    def _puntaje(self) -> Paso:
        from src import prioridad

        self._exigir("contexto")
        paso = self._nuevo("puntaje")
        ahora = prioridad.fecha_de_corte(self._ruta(self.cfg.insumos.manifest))
        reporte = prioridad.ejecutar(self.base, self.salida / prioridad.REPORTE, ahora, None, self.cfg.insumos.modalidad)
        rangos = self._tabla_conteo("SELECT rango, count(*) FROM puntajes GROUP BY 1 ORDER BY 2 DESC, 1", "Rango", "Grupos")
        paso.cifras = {"Grupos puntuados": reporte["grupos"], "Reglas": reporte["version_reglas"], "Fecha de referencia (U)": reporte["fecha_referencia"],
                       "Modelo de lenguaje": "no se usó (--sin-llm)"}
        paso.tablas["Grupos por rango"] = rangos
        paso.tablas["Grupos por estado de evidencia"] = self._tabla_conteo("SELECT estado, count(*) FROM evidencia GROUP BY 1 ORDER BY 2 DESC, 1", "Estado", "Grupos")
        return paso

    # ---- comparación

    def comparar(self, base_viva: Path) -> Comparacion:
        return comparar_bases(self.base, base_viva, self.cfg)

    def resumen_de_tiempos(self) -> dict[str, float]:
        return {p.titulo: p.segundos for p in self.pasos.values()}


def _leer_csv_limitado(ruta: Path, limite: int) -> list[dict[str, Any]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return [fila for _, fila in zip(range(limite), csv.DictReader(f), strict=False)]


# ============================================================================================ comparación de bases


def _cuentas(con: Any, cfg: ConfigCorrida) -> dict[str, Any]:
    salida: dict[str, Any] = {}
    for c in cfg.comparacion.cuentas:
        try:
            filtro = f" WHERE {c.donde}" if c.donde else ""
            if c.agrupar_por:
                filas = _filas_sql(con, f'SELECT "{c.agrupar_por}", count(*) FROM "{c.tabla}"{filtro} GROUP BY 1')
                for k, n in filas:
                    salida[f"{c.etiqueta} · {k}"] = n
            else:
                salida[c.etiqueta] = _filas_sql(con, f'SELECT count(*) FROM "{c.tabla}"{filtro}')[0][0]
        except Exception as exc:  # noqa: BLE001 - tabla ausente en una de las dos bases
            salida[c.etiqueta] = f"no disponible ({type(exc).__name__})"
    return salida


def _huellas(con: Any, cfg: ConfigCorrida) -> dict[str, str]:
    salida: dict[str, str] = {}
    for h in cfg.comparacion.huellas:
        try:
            columnas = ", ".join(f'"{c}"' for c in h.columnas)
            filas = [[_redondear(v, cfg.comparacion.decimales_huella) for v in fila] for fila in _filas_sql(con, f'SELECT {columnas} FROM "{h.tabla}"')]
            filas.sort(key=lambda f: json.dumps(f, ensure_ascii=False, default=str))
            texto = json.dumps(filas, ensure_ascii=False, separators=(",", ":"), default=str)
            salida[h.etiqueta] = f"{len(filas)} filas · {hashlib.sha256(texto.encode('utf-8')).hexdigest()[:LARGO_HASH_VISIBLE]}"
        except Exception as exc:  # noqa: BLE001
            salida[h.etiqueta] = f"no disponible ({type(exc).__name__})"
    return salida


def comparar_bases(base_corrida: Path, base_viva: Path, cfg: ConfigCorrida | None = None) -> Comparacion:
    """Compara dos bases DuckDB (solo lectura): cuentas y huellas de filas. Una cuenta que falta en un lado cuenta 0 solo si la tabla existe."""
    from src import db

    cfg = cfg or cargar_corrida()
    resultados: list[dict[str, Any]] = []
    for ruta in (base_corrida, base_viva):
        con = db.conectar(ruta, solo_lectura=True)
        try:
            resultados.append({**_cuentas(con, cfg), **{f"huella::{k}": v for k, v in _huellas(con, cfg).items()}})
        finally:
            con.close()
    corrida, viva = resultados
    filas = []
    for etiqueta in dict.fromkeys([*corrida, *viva]):
        nombre = etiqueta.removeprefix("huella::")
        filas.append(FilaComparacion(nombre, corrida.get(etiqueta, 0), viva.get(etiqueta, 0)))
    return Comparacion(filas)


# ============================================================================================ D-132 · puntajes de otra modalidad


def modalidad_puntuada(base: Path) -> str | None:
    """Modalidad de los puntajes guardados en la base (``evidencia.modalidad``); ``None`` si no hay corrida de ``src.puntaje``."""
    from src import db

    con = db.conectar(base, solo_lectura=True)
    try:
        try:
            modalidades = sorted(r[0] for r in con.execute("SELECT DISTINCT modalidad FROM evidencia").fetchall() if r[0])
        except Exception:  # noqa: BLE001  tabla ausente: la base no se puntuó
            return None
    finally:
        con.close()
    return modalidades[0] if len(modalidades) == 1 else None


def base_de_modalidad(base: Path, modalidad: str, cfg: ConfigCorrida | None = None, raiz: Path = RAIZ) -> Path:
    """Base cuyos puntajes son de ``modalidad``: la misma ``base`` si ya lo son; si no, una copia de sesión re-puntuada (D-132).

    Una base guarda los puntajes de una sola modalidad a la vez (``src.puntaje``). Para ver la otra sin tocar el archivo vivo, se
    copia a ``<tmp>/<corridas>/<modalidades>/<modalidad>-<huella>/`` y en la copia se corre ``prioridad.ejecutar`` sin LLM (los pares
    candidatos a contradicción quedan sin nota, como en la carga en vivo). La carpeta depende de la modalidad y de la huella (tamaño y
    fecha de modificación) de ``base``: se reutiliza mientras la base no cambie y las anteriores de esa modalidad se borran.
    Nunca escribe en ``base``, en ``data/revision.duckdb`` ni en ``data/``.
    """
    from src import prioridad

    cfg = cfg or cargar_corrida()
    base = Path(base)
    if modalidad_puntuada(base) in (None, modalidad):
        return base
    estado = base.stat()
    destino = raiz_de_corridas(cfg) / cfg.corridas.subcarpeta_modalidades
    carpeta = destino / f"{modalidad}-{estado.st_size}-{estado.st_mtime_ns}"
    copia = carpeta / base.name
    if copia.exists() and modalidad_puntuada(copia) == modalidad:
        return copia
    for vieja in destino.glob(f"{modalidad}-*") if destino.exists() else ():
        shutil.rmtree(vieja, ignore_errors=True)
    carpeta.mkdir(parents=True, exist_ok=True)
    parcial = carpeta / f".{base.name}.parcial"
    shutil.copy2(base, parcial)
    ahora = prioridad.fecha_de_corte(Path(raiz) / cfg.insumos.manifest)
    prioridad.ejecutar(parcial, carpeta / prioridad.REPORTE, ahora, None, modalidad)
    parcial.replace(copia)   # solo una copia completa y puntuada tiene el nombre final
    return copia


# ============================================================================================ T01 · archivo propio


@dataclass
class FilaPropia:
    posicion: int
    id: str
    estado: str                 # «aceptada» | «rechazada»
    motivos: str
    tipos: str
    valor_rechazado: str
    campos: dict[str, Any]
    esperado: str | None = None
    coincide: bool | None = None


@dataclass
class ResultadoPropio:
    tipo: str                   # «noticias» | «indicadores»
    archivo: str
    leidas: int
    validas: int
    rechazadas: int
    errores_por_tipo: dict[str, int]
    errores_de_archivo: list[dict[str, str]]
    nulos_en_validas: dict[str, int]
    filas: list[FilaPropia]
    carpeta: Path
    columna_esperado: str | None = None

    @property
    def csv_de_filas(self) -> str:
        """Todas las filas con su veredicto, para descargar."""
        salida = io.StringIO()
        w = csv.writer(salida, lineterminator="\n")
        w.writerow(["posicion", "id", "estado", "tipos_de_error", "motivos", "valor_rechazado"] + (["esperado", "coincide"] if self.columna_esperado else []))
        for f in self.filas:
            w.writerow([f.posicion, f.id, f.estado, f.tipos, f.motivos, f.valor_rechazado] + ([f.esperado or "", "" if f.coincide is None else f.coincide] if self.columna_esperado else []))
        return salida.getvalue()

    @property
    def coinciden_con_lo_esperado(self) -> tuple[int, int] | None:
        """(filas que coinciden, filas con expectativa) si el archivo trae la columna ``error_esperado``."""
        if not self.columna_esperado:
            return None
        con = [f for f in self.filas if f.coincide is not None]
        return sum(1 for f in con if f.coincide), len(con)


def validar_archivo_propio(
    contenido: bytes, tipo: str, carpeta_corrida: Path, cfg: ConfigCorrida | None = None, config_carga: Any | None = None
) -> ResultadoPropio:
    """T01 con un archivo subido: aplica **solo la etapa 1** y devuelve el veredicto de cada fila.

    El archivo y sus resultados (válidos, ``errores.csv``, reporte) quedan en ``<carpeta_corrida>/<tipo>/``; no se escribe en ningún otro lado.
    """
    from src import carga

    cfg = cfg or cargar_corrida()
    config = config_carga or cargar_carga()
    if tipo not in {"noticias", "indicadores"}:
        raise ErrorDeCorrida(f"tipo de archivo no admitido: {tipo!r}")
    if len(contenido) > cfg.archivo_propio.maximo_bytes:
        raise ErrorDeCorrida(f"el archivo pesa {len(contenido):,} bytes y el tope es {cfg.archivo_propio.maximo_bytes:,}")
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ErrorDeCorrida("el archivo no está en UTF-8 (el contrato de datos exige UTF-8)") from exc
    nombre = config.archivos.noticias if tipo == "noticias" else config.archivos.indicadores
    cargador = carga.cargar_noticias if tipo == "noticias" else carga.cargar_indicadores
    carpeta = carpeta_corrida / tipo
    shutil.rmtree(carpeta, ignore_errors=True)
    (carpeta / "subido").mkdir(parents=True)
    ruta = carpeta / "subido" / nombre
    ruta.write_text(texto, encoding="utf-8", newline="")
    resultado = cargador(ruta, config)
    carga.escribir_validos({nombre: resultado}, carpeta / cfg.corridas.subcarpeta_validos, config)
    carga.escribir_errores({nombre: resultado}, carpeta / config.salida.errores)
    reporte = carga.construir_reporte({nombre: resultado}, config)
    (carpeta / config.salida.reporte).write_text(json.dumps(reporte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    filas = _veredicto_por_fila(texto, resultado, cfg.archivo_propio.columna_esperado)
    tiene_esperado = any(f.esperado is not None for f in filas)
    return ResultadoPropio(
        tipo, nombre, resultado.leidas, len(resultado.validas), resultado.rechazadas, resultado.errores_por_tipo(),
        [{"campo": e.campo, "tipo_error": e.tipo_error, "motivo": e.motivo} for e in resultado.errores_de_archivo],
        {k: v for k, v in resultado.nulos_validas.items() if v}, filas, carpeta, cfg.archivo_propio.columna_esperado if tiene_esperado else None,
    )


def _veredicto_por_fila(texto: str, resultado: Any, columna_esperado: str) -> list[FilaPropia]:
    """Une cada registro del CSV con sus errores por posición (1-based, igual que ``ErrorFila.fila``). Los nulos se muestran como nulos (``None``)."""
    filas_csv = list(csv.DictReader(io.StringIO(texto, newline="")))
    por_fila: dict[int, list[Any]] = {}
    for e in [*resultado.errores, *resultado.lineas_mal_formadas]:
        if e.fila is not None:
            por_fila.setdefault(e.fila, []).append(e)
    salida: list[FilaPropia] = []
    for i, fila in enumerate(filas_csv, start=1):
        errores = por_fila.get(i, [])
        campos = {k: (v if v not in (None, "") else None) for k, v in fila.items() if k is not None and k != columna_esperado}
        esperado = fila.get(columna_esperado) if columna_esperado in fila else None
        tipos = sorted({e.tipo_error for e in errores})
        id_fila = next((e.id for e in errores if e.id), "") or str(fila.get("id_noticia") or fila.get("indicador_id") or "")
        coincide = None
        if columna_esperado in fila:
            coincide = (esperado or "") in tipos if esperado else not errores
        salida.append(FilaPropia(
            i, id_fila, "rechazada" if errores else "aceptada", " · ".join(dict.fromkeys(e.motivo for e in errores)), ", ".join(tipos),
            " | ".join(dict.fromkeys(e.valor for e in errores if e.valor)), campos, (esperado or None) if columna_esperado in fila else None, coincide,
        ))
    return salida


def ejemplo_con_errores(tipo: str, cfg: ConfigCorrida | None = None, raiz: Path = RAIZ) -> bytes | None:
    """Los bytes del fixture T01 (con filas inválidas a propósito) para que el jurado lo descargue y lo suba. ``None`` si el fixture no está."""
    cfg = cfg or cargar_corrida()
    relativa = cfg.archivo_propio.ejemplo_noticias if tipo == "noticias" else cfg.archivo_propio.ejemplo_indicadores
    ruta = raiz / relativa
    return ruta.read_bytes() if ruta.is_file() else None


def pasos_por_clave(pasos: Sequence[Paso]) -> Mapping[str, Paso]:
    return {p.clave: p for p in pasos}
