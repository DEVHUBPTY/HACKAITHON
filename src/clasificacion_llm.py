"""C-10c: clasificar el tema de un titular con un LLM (medición única; NO está conectado a la canalización).

El clasificador de producción sigue siendo e5 · método A (``src/clasificacion.py``). Este módulo solo se usa desde
``eval/clasificacion_llm.py`` para medir si un LLM que lee la guía de temas acierta más.

* **Qué sale hacia el proveedor:** únicamente el texto del titular, dentro de ``<titular>…</titular>`` en el mensaje de usuario (dato,
  nunca instrucción). Las reglas van en el system prompt (``prompts/clasificar_tema.txt``, versionado y congelado por versión y huella
  en ``config/clasificacion_llm.yaml``). Ningún id, URL, etiqueta, medio ni descripción del RSS (D-31).
* **Salida:** JSON validado con pydantic (``RespuestaTema``): ``tema`` (uno de los 6 de ``temas.yaml`` o ``sin_tema``), ``confianza``
  (alta, media o baja) y ``motivo``. Temperatura 0. Una respuesta mal formada es ``sin_tema`` con ``malformada = True``; no se reintenta.
  Un error del proveedor (red, autenticación, tope de costo) **detiene** la corrida: nunca se convierte en una predicción.
* **Caché:** una respuesta por archivo en ``data/cache_clasificacion_llm/`` (``src/cache.py``), con la clave modelo + versión y huella del
  prompt + temperatura + titular. Guarda la respuesta, el modelo y las cifras de uso; nunca el prompt, el titular ni claves. Con
  ``proveedor = None`` se reproduce solo desde la caché, sin red.
* **Costo:** el proveedor se envuelve en el ``ProveedorConTope`` existente (D-67, D-98).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, ValidationError

from src.baseline import SIN_TEMA
from src.cache import CacheLlm, SinCache
from src.configuracion import (
    RAIZ,
    ConfigClasificacionLlm,
    ConfigTemas,
    cargar_generacion,
    cargar_llm,
    leer_local_env,
)
from src.generacion import cargar_prompt
from src.limpieza import plano
from src.llm.costo import ProveedorConTope, RegistroCosto
from src.llm.deepseek import ProveedorDeepSeek
from src.llm.ollama import SesionHttp
from src.llm.proveedor import ErrorProveedor, Proveedor

log = logging.getLogger(__name__)

ETIQUETA_ABRE = "<titular>"
ETIQUETA_CIERRA = "</titular>"
MARCADOR_ESQUEMA = "{esquema}"
Confianza = Literal["alta", "media", "baja"]


# ============================================================================================ salida del LLM


class RespuestaTema(BaseModel):
    """La respuesta del LLM: sin claves de más y sin coerción de tipos. Que ``tema`` sea uno de los temas lo comprueba ``interpretar``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tema: str
    confianza: Confianza
    motivo: str


def temas_validos(temas: ConfigTemas) -> list[str]:
    """Los identificadores que el LLM puede devolver: los 6 temas de ``temas.yaml`` y ``sin_tema``."""
    return [*temas.temas, SIN_TEMA]


def esquema_salida(temas: ConfigTemas) -> dict[str, Any]:
    """JSON Schema de ``RespuestaTema`` con la lista cerrada de temas; es lo que va en el system prompt."""
    esquema = RespuestaTema.model_json_schema()
    esquema["properties"]["tema"] = {"type": "string", "enum": temas_validos(temas)}
    esquema["properties"]["confianza"] = {"type": "string", "enum": list(get_args(Confianza))}
    return esquema


def interpretar_respuesta(texto: str, validos: Sequence[str]) -> RespuestaTema | None:
    """La respuesta validada, o ``None`` si no es un objeto JSON de la forma pedida o si el tema no es uno de ``validos``."""
    try:
        datos = json.loads(texto)
        respuesta = RespuestaTema.model_validate(datos)
    except (ValueError, ValidationError):
        return None
    return respuesta if respuesta.tema in validos else None


# ============================================================================================ prompt versionado y congelado


@dataclass(frozen=True)
class PromptClasificacion:
    """El system prompt ya armado (con el esquema), su versión y la huella SHA-256 del cuerpo congelado."""

    version: str
    texto: str
    huella: str


def huella_de(cuerpo: str) -> str:
    return hashlib.sha256(cuerpo.encode("utf-8")).hexdigest()


def cargar_prompt_clasificacion(cfg: ConfigClasificacionLlm, temas: ConfigTemas) -> PromptClasificacion:
    """Lee ``prompts/<cfg.prompt>.txt`` y comprueba que sea el prompt congelado: misma versión y misma huella que la configuración.

    Si el texto cambió sin subir la versión y la huella, falla: una medición con otro prompt no es la medición única de C-10c.
    """
    version, cuerpo = cargar_prompt(cfg.prompt)
    if version != cfg.version_prompt:
        raise ValueError(f"prompts/{cfg.prompt}.txt declara la versión {version!r}, pero la configuración congela {cfg.version_prompt!r}")
    huella = huella_de(cuerpo)
    if huella != cfg.huella_prompt:
        raise ValueError(
            f"la huella del prompt {cfg.prompt!r} ({huella[:12]}…) no es la congelada en config/clasificacion_llm.yaml ({cfg.huella_prompt[:12]}…): "
            "el texto cambió; no se puede presentar como la misma medición"
        )
    if MARCADOR_ESQUEMA not in cuerpo:
        raise ValueError(f"prompts/{cfg.prompt}.txt no trae el marcador {MARCADOR_ESQUEMA}")
    texto = cuerpo.replace(MARCADOR_ESQUEMA, json.dumps(esquema_salida(temas), ensure_ascii=False, indent=2))
    return PromptClasificacion(version, texto, huella)


def _normalizado(texto: str) -> str:
    return " ".join(plano(texto).split())


def titulares_en_prompt(texto_prompt: str, titulares: Sequence[str]) -> list[int]:
    """Posiciones de los ``titulares`` que aparecen dentro del prompt (sin distinguir mayúsculas, tildes ni espacios): una fuga de evaluación."""
    prompt = _normalizado(texto_prompt)
    return [k for k, t in enumerate(titulares) if (n := _normalizado(t)) and n in prompt]


def mensaje_usuario(titular: str) -> str:
    """El único dato que recibe el LLM: el titular dentro de ``<titular>…</titular>``.

    Los ``<`` y ``>`` del titular se escapan: un titular no puede cerrar la etiqueta ni abrir otra, así que sigue siendo dato.
    """
    seguro = titular.replace("<", "&lt;").replace(">", "&gt;")
    return f"{ETIQUETA_ABRE}{seguro}{ETIQUETA_CIERRA}"


# ============================================================================================ caché


def clave_cache(cfg: ConfigClasificacionLlm, prompt: PromptClasificacion, titular: str) -> str:
    """SHA-256 de modelo + versión y huella del prompt + prompt armado + temperatura + titular + versión de la caché (y el proveedor)."""
    carga = {
        "version_cache": cfg.cache.version_cache,
        "proveedor": cfg.proveedor,
        "modelo": cfg.modelo,
        "version_prompt": cfg.version_prompt,
        "huella_prompt": prompt.huella,
        "sistema": hashlib.sha256(prompt.texto.encode("utf-8")).hexdigest(),
        "temperatura": cfg.temperatura,
        "titular": titular,
    }
    return hashlib.sha256(json.dumps(carga, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _leer_entrada(cache: CacheLlm, clave: str) -> dict[str, Any] | None:
    """La entrada guardada (con sus cifras de uso) o ``None`` si falta, es ilegible o no corresponde a su clave."""
    try:
        datos = json.loads((cache.carpeta / f"{clave}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        log.warning("entrada de caché ilegible %s…: se ignora", clave[:12])
        return None
    respuesta = datos.get("respuesta") if isinstance(datos, dict) else None
    if not isinstance(datos, dict) or datos.get("clave") != clave or not isinstance(respuesta, str) or not respuesta.strip():
        log.warning("entrada de caché inválida %s…: se ignora", clave[:12])
        return None
    return datos


# ============================================================================================ clasificador


@dataclass(frozen=True)
class Clasificacion:
    """Lo que se decidió de un titular. ``malformada``: la respuesta no cumplió el esquema (``tema = sin_tema``, sin confianza ni motivo)."""

    tema: str
    confianza: str | None
    motivo: str | None
    malformada: bool
    desde_cache: bool
    tokens_entrada: int
    tokens_salida: int


class ClasificadorLlm:
    """Clasifica titulares con un ``Proveedor`` (o solo desde la caché si ``proveedor`` es ``None``)."""

    def __init__(
        self,
        cfg: ConfigClasificacionLlm,
        temas: ConfigTemas,
        proveedor: Proveedor | None,
        cache: CacheLlm,
        prompt: PromptClasificacion | None = None,
    ) -> None:
        self.cfg, self.proveedor, self.cache = cfg, proveedor, cache
        self.prompt = prompt or cargar_prompt_clasificacion(cfg, temas)
        self._validos = temas_validos(temas)
        self._esquema = esquema_salida(temas)

    def clasificar(self, titular: str) -> Clasificacion:
        """Tema del titular. Solo el texto del titular sale hacia el proveedor; un error del proveedor sube sin guardar nada."""
        clave = clave_cache(self.cfg, self.prompt, titular)
        entrada = _leer_entrada(self.cache, clave)
        if entrada is not None:
            texto, desde_cache = entrada["respuesta"], True
            entrada_tokens, salida_tokens = int(entrada.get("tokens_entrada") or 0), int(entrada.get("tokens_salida") or 0)
        else:
            if self.proveedor is None:
                raise SinCache("no hay respuesta guardada para este titular en la caché de C-10c y no se puede llamar al proveedor (modo sin red)")
            texto = self.proveedor.generar_json(self.prompt.texto, mensaje_usuario(titular), self._esquema)
            uso = getattr(self.proveedor, "ultimo_uso", None)
            entrada_tokens, salida_tokens = (uso.tokens_entrada, uso.tokens_salida) if uso else (0, 0)
            desde_cache = False
            self.cache.guardar(
                clave,
                texto,
                {
                    "proveedor": self.proveedor.nombre,
                    "modelo": self.proveedor.modelo,
                    "version_prompt": self.cfg.version_prompt,
                    "prompt": self.cfg.prompt,
                    "version_cache": self.cfg.cache.version_cache,
                    "tokens_entrada": entrada_tokens,
                    "tokens_salida": salida_tokens,
                },
            )
        respuesta = interpretar_respuesta(texto, self._validos)
        if respuesta is None:
            return Clasificacion(SIN_TEMA, None, None, True, desde_cache, entrada_tokens, salida_tokens)
        return Clasificacion(respuesta.tema, respuesta.confianza, respuesta.motivo, False, desde_cache, entrada_tokens, salida_tokens)

    def clasificar_todos(self, titulares: Sequence[str]) -> list[Clasificacion]:
        """Clasifica en orden; si el proveedor falla o se alcanza el tope de costo, la corrida se detiene (lo ya hecho queda en la caché)."""
        resultados = []
        for k, titular in enumerate(titulares, start=1):
            resultados.append(self.clasificar(titular))
            log.info("clasificado %d de %d (desde_cache=%s)", k, len(titulares), resultados[-1].desde_cache)
        return resultados


# ============================================================================================ proveedor (el existente, con tope de costo)


def crear_proveedor_clasificacion(
    cfg: ConfigClasificacionLlm,
    env: Mapping[str, str] | None = None,
    sesion: SesionHttp | None = None,
    registro: RegistroCosto | None = None,
) -> Proveedor:
    """DeepSeek detrás del tope de costo (D-67, D-98), con el modelo, la temperatura y ``max_tokens`` de ``config/clasificacion_llm.yaml``.

    La clave sale de ``local.env`` (``leer_local_env``) y nunca se imprime. ``DEEPSEEK_MODEL`` no se usa: el modelo de la medición está
    fijado en la configuración. ``sesion`` y ``registro`` se inyectan en las pruebas (sin red y sin tocar ``outputs/costo_llm.json``).
    """
    env = leer_local_env() if env is None else env
    nombre = (env.get("LLM_PROVIDER") or "").strip().lower()
    if nombre != cfg.proveedor:
        raise ErrorProveedor(f"C-10c se mide con el proveedor {cfg.proveedor!r}: LLM_PROVIDER en local.env debe valer {cfg.proveedor!r}")
    clave = (env.get("DEEPSEEK_API_KEY") or "").strip()
    if not clave:
        raise ErrorProveedor("DEEPSEEK_API_KEY no está definido en local.env")
    gen = cargar_generacion()
    gen = gen.model_copy(update={"deepseek": gen.deepseek.model_copy(update={"modelo": cfg.modelo, "max_tokens": cfg.max_tokens})})
    llm = cargar_llm()
    llm = llm.model_copy(update={"generacion": llm.generacion.model_copy(update={"temperatura": cfg.temperatura})})
    registro = registro or RegistroCosto(RAIZ / gen.tope_costo.registro)
    return ProveedorConTope(ProveedorDeepSeek(clave, gen, llm, sesion), registro, gen.tope_costo, gen.deepseek.precio_usd_por_millon_tokens)
