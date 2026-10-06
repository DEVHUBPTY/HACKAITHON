"""Codificador de prueba para E1-07: bolsa de palabras con hash estable, sin red ni modelo.

Cada palabra (sin tildes y en minúsculas) suma 1 en una de ``DIMENSION`` posiciones elegida con ``zlib.crc32``
(estable entre procesos, a diferencia de ``hash``). Dos textos que comparten palabras tienen similitud coseno alta:
alcanza para verificar la lógica de clasificación sin descargar ningún modelo.
"""

from __future__ import annotations

import re
import zlib

import numpy as np

from src.configuracion import ConfigClasificacion, ConfigTemas, cargar_clasificacion
from src.limpieza import plano

DIMENSION = 256


class MotorFalso:
    """Cumple el protocolo ``src.embeddings.Motor``; registra cada texto que recibe."""

    def __init__(self) -> None:
        self.recibidos: list[str] = []

    def codificar(self, textos: list[str]) -> np.ndarray:
        self.recibidos.extend(textos)
        matriz = np.zeros((len(textos), DIMENSION), dtype=np.float32)
        for i, texto in enumerate(textos):
            for palabra in re.findall(r"\w+", plano(texto)):
                matriz[i, zlib.crc32(palabra.encode()) % DIMENSION] += 1.0
        return matriz


def config_de_prueba(**cambios: object) -> ConfigClasificacion:
    """La configuración real con umbrales neutros (sin_tema solo si no hay ninguna palabra en común)."""
    cfg = cargar_clasificacion()
    modelo = cfg.modelos[cfg.modelo_activo]
    umbrales = {m: u.model_copy(update={"umbral_sin_tema": 0.05, "margen_secundario": 0.05}) for m, u in modelo.umbrales.items()}
    modelos = {**cfg.modelos, cfg.modelo_activo: modelo.model_copy(update={"umbrales": umbrales})}
    return cfg.model_copy(update={"modelos": modelos, **cambios})


def temas_de_prueba() -> ConfigTemas:
    """Seis temas mínimos con vocabulario disjunto: cada uno se reconoce por sus palabras."""
    vocabulario = {
        "economia": ("inflacion precios canasta", ["inflacion sube precios", "deuda presupuesto fiscal"], {"precios": "precios canasta combustibles", "empleo": "desempleo empleo trabajo"}),
        "logistica": ("canal transitos buques", ["canal reduce transitos", "puerto contenedores carga"], {"canal": "canal transitos calado", "puertos": "puerto contenedores"}),
        "turismo": ("turistas hoteles cruceros", ["hoteles llenos turistas", "cruceros visitantes playa"], {"hoteles": "hoteles ocupacion", "cruceros": "cruceros colon"}),
        "servicios_publicos": ("agua luz hospital", ["sin agua barrios", "hospital medicamentos"], {"agua": "agua potable tuberia", "salud": "hospital pacientes"}),
        "eventos_naturales": ("sismo lluvias sequia", ["fuerte sismo temblor", "lluvias inundaciones"], {"sismos": "sismo temblor", "lluvias": "lluvias inundaciones"}),
        "regulacion": ("ley decreto resolucion", ["aprueban ley", "decreto regula sanciones"], {"leyes": "ley decreto", "sanciones": "sanciona multa"}),
    }
    temas = {
        id_tema: {
            "nombre": id_tema.title(),
            "descripcion": descripcion,
            "ejemplos": [{"titulo": t, "real": False} for t in ejemplos],
            "subtemas": {sub: {"nombre": sub, "prototipo": proto} for sub, proto in subtemas.items()},
        }
        for id_tema, (descripcion, ejemplos, subtemas) in vocabulario.items()
    }
    return ConfigTemas.model_validate(
        {
            "version": "t",
            "cantidad_temas": 6,
            "sectores_validos": ["economía"],
            "temas": temas,
            "fuera_de_temas": {"no_es_panama": "x", "fuera_de_temas": "y"},
        }
    )
