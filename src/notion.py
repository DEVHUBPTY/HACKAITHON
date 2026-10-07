"""Sincronización de una ficha exportada con la base *Casos y evidencias* de Notion (E3-03).

Toma lo que ya produce ``src.exportar`` (la fila de la base y el Markdown del caso, que salen de ``fichas_revisadas``) y lo envía con
la API de Notion. Es **idempotente por ``ID caso``**: busca la página por su título; si existe la actualiza (propiedades y cuerpo), si no
la crea; si hay más de una no adivina y se detiene. Todo sigue siendo BORRADOR: no escribe nada fuera de esa base ni en el registro de
revisiones. El token (``NOTION_TOKEN``) solo viaja en el encabezado ``Authorization`` y nunca se imprime ni aparece en un error (D-69).
El cliente HTTP se inyecta para las pruebas, que no usan la red.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from src.configuracion import ConfigNotion, cargar_notion
from src.registro import redactar

log = logging.getLogger(__name__)
HTTP_REINTENTABLES = frozenset({429, 500, 502, 503, 504})


class ErrorNotion(RuntimeError):
    """La API de Notion rechazó la operación (permiso, esquema, límite agotado): un error real, no una degradación."""


class SincronizacionIncompleta(ErrorNotion):
    """Se perdió la conexión (o venció el tiempo) DESPUÉS de haber enviado una escritura: la página pudo quedar a medias (X96)."""


class FalloAmbiguo(ErrorNotion):
    """Respuesta 5xx a una operación no idempotente: no se sabe si Notion la aplicó, por eso no se reintenta a ciegas (X97)."""


class SinConexion(ErrorNotion):
    """No hay red hacia la API: la exportación local se conserva y se informa que no se sincronizó."""


class SesionHttp(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class Sincronizacion:
    id_caso: str
    id_pagina: str
    url: str
    creada: bool
    bloques: int


def _texto(valor: str, maximo: int) -> list[dict[str, Any]]:
    """Texto enriquecido de Notion: trozos de a lo sumo ``maximo`` caracteres (literal, sin interpretar marcas)."""
    trozos = [valor[i : i + maximo] for i in range(0, len(valor), maximo)]
    return [{"type": "text", "text": {"content": t}} for t in trozos]


def propiedad(tipo: str, valor: str, maximo: int) -> dict[str, Any]:
    """Un valor de la fila (texto) como propiedad de Notion del ``tipo`` dado; vacío = sin valor (nunca cero, ni se inventa)."""
    v = valor.strip()
    if tipo == "titulo":
        return {"title": _texto(v, maximo)}
    if tipo == "texto":
        return {"rich_text": _texto(v, maximo)}
    if tipo == "seleccion":
        return {"select": {"name": v.replace(",", " ")} if v else None}   # Notion no admite comas en el nombre de una opción
    if tipo == "numero":
        try:
            return {"number": float(v) if v else None}
        except ValueError:
            raise ErrorNotion(f"valor no numérico para una propiedad numérica: {v[:40]!r}") from None
    if tipo == "fecha":
        return {"date": {"start": v} if v else None}
    raise ErrorNotion(f"tipo de propiedad desconocido: {tipo}")


def propiedades_de_fila(fila: dict[str, str], cfg: ConfigNotion) -> dict[str, Any]:
    """Todas las propiedades de la base a partir de la fila del CSV (``P`` y ``Rango`` son fórmulas y no se envían)."""
    faltan = sorted(set(cfg.propiedades) - set(fila))
    if faltan:
        raise ErrorNotion(f"la fila no trae las propiedades: {faltan}")
    return {n: propiedad(t, fila[n], cfg.cuerpo.max_caracteres_bloque) for n, t in cfg.propiedades.items()}


_ENCABEZADO = re.compile(r"^(#{1,3})\s+(.*)$")
_VINETA = re.compile(r"^(\s*)-\s+(.*)$")


def bloques_de_markdown(md: str, cfg: ConfigNotion) -> list[dict[str, Any]]:
    """El Markdown del caso como bloques de Notion: encabezados, viñetas y párrafos (las tablas quedan como líneas de texto).

    El texto va literal: ya viene escapado por ``escapar_markdown``, no se interpreta nada y nunca se crea un enlace ni HTML.
    """
    maximo = cfg.cuerpo.max_caracteres_bloque
    bloques: list[dict[str, Any]] = []
    for linea in md.splitlines():
        if not linea.strip() or set(linea.strip()) <= {"-", "|"}:
            continue
        if m := _ENCABEZADO.match(linea):
            tipo, contenido = f"heading_{len(m.group(1))}", m.group(2)
        elif m := _VINETA.match(linea):
            tipo, contenido = "bulleted_list_item", m.group(2)
        else:
            tipo, contenido = "paragraph", linea.strip()
        bloques.append({"object": "block", "type": tipo, tipo: {"rich_text": _texto(contenido, maximo)}})
    return bloques


class ClienteNotion:
    """Cliente mínimo de la API: buscar, crear y actualizar la página de un caso y reemplazar su cuerpo."""

    def __init__(self, token: str, cfg: ConfigNotion | None = None, sesion: SesionHttp | None = None, dormir: Any = time.sleep) -> None:
        self._token = token
        self.cfg = cfg or cargar_notion()
        self.sesion: SesionHttp = sesion or requests.Session()
        self._dormir = dormir
        self.escrituras = 0   # escrituras enviadas (aunque su respuesta se haya perdido): decide «sin conexión» vs «incompleta» (X96)

    def _llamar(
        self, metodo: str, ruta: str, cuerpo: dict[str, Any] | None = None, parametros: dict[str, Any] | None = None,
        *, lectura: bool = False, idempotente: bool = True,
    ) -> dict[str, Any]:
        """``lectura``: no escribe (la consulta de la base es un POST). ``idempotente``: repetirla es seguro; si no, un 5xx no se reintenta (solo el 429, que
        Notion no procesó)."""
        api = self.cfg.api
        escribe = metodo != "GET" and not lectura
        url = f"{api.base_url.rstrip('/')}/{ruta.lstrip('/')}"
        cabeceras = {"Authorization": f"Bearer {self._token}", "Notion-Version": api.version, "Content-Type": "application/json"}
        for intento in range(api.reintentos + 1):
            if escribe:
                self.escrituras += 1
            try:
                resp = self.sesion.request(metodo, url, json=cuerpo, params=parametros, headers=cabeceras, timeout=api.timeout_segundos)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if self.escrituras:
                    raise SincronizacionIncompleta(redactar(f"se perdió la conexión con Notion después de escribir ({type(exc).__name__})")) from None
                raise SinConexion(redactar(f"sin conexión con la API de Notion ({type(exc).__name__})")) from None
            except requests.RequestException as exc:
                raise ErrorNotion(redactar(f"fallo de red al llamar a Notion ({type(exc).__name__})")) from None
            if resp.status_code >= 500 and not idempotente:
                raise FalloAmbiguo(redactar(f"Notion respondió HTTP {resp.status_code} en {metodo} {ruta}: no se sabe si se aplicó"))
            if resp.status_code in HTTP_REINTENTABLES and intento < api.reintentos:
                espera = _espera(resp, intento, self.cfg)
                log.warning("Notion respondió HTTP %s; reintento %s/%s en %.1f s", resp.status_code, intento + 1, api.reintentos, espera)
                self._dormir(espera)
                continue
            if resp.status_code >= 400:
                raise ErrorNotion(redactar(f"Notion respondió HTTP {resp.status_code} en {metodo} {ruta}: {_mensaje(resp)}"))
            return resp.json()
        raise ErrorNotion("Notion: reintentos agotados")  # pragma: no cover - el bucle siempre retorna o lanza

    def buscar_paginas(self, id_caso: str) -> list[dict[str, Any]]:
        """Las páginas de la base cuyo título (``ID caso``) es exactamente ``id_caso`` (sin archivadas)."""
        filtro = {"filter": {"property": "ID caso", "title": {"equals": id_caso}}, "page_size": self.cfg.api.tamano_pagina_busqueda}
        r = self._llamar("POST", f"databases/{self.cfg.base_de_datos.id}/query", filtro, lectura=True)
        return [p for p in r.get("results", []) if not p.get("archived") and not p.get("in_trash")]

    def _hijos(self, id_pagina: str) -> list[str]:
        ids: list[str] = []
        cursor: str | None = None
        while True:
            r = self._llamar("GET", f"blocks/{id_pagina}/children", parametros={"page_size": self.cfg.api.tamano_pagina_hijos, **({"start_cursor": cursor} if cursor else {})})
            ids += [b["id"] for b in r.get("results", [])]
            if not r.get("has_more"):
                return ids
            cursor = r.get("next_cursor")

    def _reemplazar_cuerpo(self, id_pagina: str, bloques: list[dict[str, Any]]) -> None:
        """Primero agrega el cuerpo nuevo y recién después borra el viejo: si falla al agregar, la página conserva el cuerpo anterior (X95)."""
        viejos = self._hijos(id_pagina)
        n = self.cfg.cuerpo.max_bloques_por_llamada
        for i in range(0, len(bloques), n):
            self._llamar("PATCH", f"blocks/{id_pagina}/children", {"children": bloques[i : i + n]}, idempotente=False)
        for id_bloque in viejos:
            self._llamar("DELETE", f"blocks/{id_bloque}")

    def _crear(self, id_caso: str, props: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Crea la página; tras un fallo ambiguo (5xx o corte) vuelve a buscar por ``ID caso`` y, si ya existe, la usa en vez de crear otra (X97)."""
        api = self.cfg.api
        for intento in range(api.reintentos + 1):
            try:
                return self._llamar("POST", "pages", {"parent": {"database_id": self.cfg.base_de_datos.id}, "properties": props}, idempotente=False), True
            except (FalloAmbiguo, SincronizacionIncompleta) as exc:
                hallada = self.buscar_paginas(id_caso)
                if len(hallada) > 1:
                    raise ErrorNotion(f"{id_caso}: tras un fallo ambiguo hay {len(hallada)} páginas con ese ID caso; archive los duplicados en Notion.") from None
                if hallada:
                    return self._llamar("PATCH", f"pages/{hallada[0]['id']}", {"properties": props}), True
                if intento >= api.reintentos:
                    raise ErrorNotion(redactar(f"{id_caso}: no se pudo confirmar la creación ({exc})")) from None
                log.warning("Creación ambigua de %s; no existe aún, reintento %s/%s", id_caso, intento + 1, api.reintentos)
                self._dormir(_espera_base(intento, self.cfg))
        raise ErrorNotion("Notion: reintentos agotados")  # pragma: no cover

    def sincronizar(self, id_caso: str, fila: dict[str, str], markdown: str) -> Sincronizacion:
        """Crea o actualiza la página del caso (clave: ``ID caso``) con la fila y el Markdown ya exportados."""
        if fila.get("ID caso") != id_caso:
            raise ErrorNotion(f"la fila exportada no es la de {id_caso}")
        props = propiedades_de_fila(fila, self.cfg)
        bloques = bloques_de_markdown(markdown, self.cfg)
        existentes = self.buscar_paginas(id_caso)
        if len(existentes) > 1:
            raise ErrorNotion(
                f"{id_caso}: hay {len(existentes)} páginas con ese ID caso en «{self.cfg.base_de_datos.nombre}» (¿importaciones de CSV repetidas?). "
                "No se escribió nada: archive los duplicados en Notion y vuelva a intentar."
            )
        if existentes:
            pagina = self._llamar("PATCH", f"pages/{existentes[0]['id']}", {"properties": props})
            creada = False
        else:
            pagina, creada = self._crear(id_caso, props)
        self._reemplazar_cuerpo(pagina["id"], bloques)
        return Sincronizacion(id_caso, pagina["id"], pagina.get("url", ""), creada, len(bloques))


def _espera_base(intento: int, cfg: ConfigNotion) -> float:
    return min(cfg.api.espera_base_segundos * (2**intento), cfg.api.espera_maxima_segundos)


def _espera(resp: Any, intento: int, cfg: ConfigNotion) -> float:
    api = cfg.api
    try:
        indicada = float(resp.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        indicada = api.espera_base_segundos * (2**intento)
    return min(max(indicada, 0.0), api.espera_maxima_segundos)


def _mensaje(resp: Any) -> str:
    """El código y el mensaje de error de Notion (no contienen el token); acotado para no volcar la respuesta entera."""
    try:
        datos = resp.json()
        return f"{datos.get('code', '')}: {str(datos.get('message', ''))[:300]}"
    except ValueError:
        return "respuesta sin JSON"
