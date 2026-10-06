"""Corpus sintético mínimo y consultor de prueba para E1-11: sin red ni modelo (codificador de bolsa de palabras)."""

from __future__ import annotations

from pathlib import Path

from src import db, embeddings
from src.configuracion import ConfigConsulta, cargar_consulta
from src.consulta import Consultor, Indice, cargar_corpus, validar_citas
from tests.motor_falso import MotorFalso, config_de_prueba

UMBRAL_SEMANTICA = 0.2   # con la bolsa de palabras, dos textos sin palabras en común dan 0
UMBRAL_BM25 = 0.5


def _noticia(id_: str, titulo: str, medio: str = "Medio Uno", es_ruido: bool = False) -> dict:
    return {
        "id_noticia": id_, "titulo": titulo, "url": f"https://x.test/{id_}", "url_canonica": f"https://x.test/{id_}",
        "medio": medio, "tipo_firma": "sin firma", "fecha_publicacion": "2026-10-01T10:00:00Z",
        "titulo_limpio": titulo, "es_ruido": es_ruido, "sospechoso_inyeccion": False,
    }


def _indicador(pais: str, ind: str, anio: int, valor: float | None, unidad: str = "%") -> dict:
    return {"id_indicador": f"IND-{pais}-{ind}-{anio}", "pais_iso3": pais, "indicador_id": ind, "anio": anio,
            "valor": valor, "unidad": unidad}


def _sismo(id_: str, mag: float, tiempo: str, lugar: str) -> dict:
    return {"id": id_, "magnitude": mag, "time": tiempo, "place": lugar}


NOTICIAS = [
    _noticia("NOT-0000000001", "Canal de Panamá aprueba presupuesto para 2027", "Panamá América"),
    _noticia("NOT-0000000002", "Ministerio de Salud anuncia vacunación contra el virus respiratorio en embarazadas"),
    _noticia("NOT-0000000003", "Concierto de música tropical llena la plaza", es_ruido=True),
]
INDICADORES = [
    _indicador("PAN", "SL.UEM.TOTL.ZS", 2022, None),                  # nulo explícito: no se rellena con cero
    _indicador("PAN", "SL.UEM.TOTL.ZS", 2023, 6.5),
    _indicador("PAN", "SL.UEM.TOTL.ZS", 2024, 8.4),
    _indicador("PAN", "FP.CPI.TOTL.ZG", 2024, 0.7),
    _indicador("CRI", "SL.UEM.TOTL.ZS", 2024, 7.1),
]
SISMOS = [
    _sismo("SIS-us0001", 5.4, "2024-03-10T08:00:00Z", "10 km al sur de Puerto Armuelles, Panama"),
    _sismo("SIS-us0002", 4.1, "2024-12-29T23:00:00Z", "35 km de Sardinal, Costa Rica"),
]


def crear_base(ruta: Path) -> Path:
    db.guardar_todo(ruta, {"noticias": NOTICIAS, "indicadores": INDICADORES, "sismos": SISMOS})
    return ruta


def config_consulta(**umbrales: float) -> ConfigConsulta:
    cfg = cargar_consulta()
    u = {"semantica": UMBRAL_SEMANTICA, "bm25": UMBRAL_BM25, **umbrales}
    return cfg.model_copy(update={"abstencion": cfg.abstencion.model_copy(update={"umbral_similitud": u})})


def crear_consultor(tmp_path: Path, validador=validar_citas, **umbrales: float) -> tuple[Consultor, MotorFalso]:
    motor = MotorFalso()
    emb = embeddings.crear(config_de_prueba(), motor=motor, raiz=tmp_path)
    cfg = config_consulta(**umbrales)
    corpus = cargar_corpus(crear_base(tmp_path / "senales.duckdb"))
    return Consultor(Indice(corpus, emb, cfg), cfg, validador=validador), motor
