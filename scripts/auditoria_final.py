"""C-07 · Auditoría final de las condiciones previas (PDF secciones 5 y 10, D-72).

    poetry run python -m scripts.auditoria_final                 # escribe outputs/auditoria_final.md y .json
    poetry run python -m scripts.auditoria_final --reproducir    # además corre scripts.reproducir --verificar (≈ 1 min)
    poetry run python -m scripts.auditoria_final --estricto       # sale con 1 también si algo es NO VERIFICABLE AUTOMÁTICAMENTE

Cada ítem termina en uno de tres estados, siempre con la evidencia (ruta o comando) que lo respalda:

* **PASS**: el script lo comprobó contra archivos reales.
* **FALTA**: lo comprobó y no se cumple (o falta la evidencia que lo demuestra). Hay que corregirlo; la falla se registra en Notion **antes** de corregir.
* **NO VERIFICABLE AUTOMÁTICAMENTE**: depende de Notion, del acceso del jurado o de otra máquina; el ítem dice cómo verificarlo a mano.

Sale con 1 si hay algún FALTA. Nunca marca PASS lo que no pudo comprobar. No lee el benchmark reservado ni el contenido de ``local.env``.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts import empaquetar_datos as paquete
from src.configuracion import RAIZ, ConfigEntrega, cargar_entrega, cargar_fuentes

PASS = "PASS"
FALTA = "FALTA"
NO_VERIFICABLE = "NO VERIFICABLE AUTOMÁTICAMENTE"


@dataclass
class Item:
    id: str
    grupo: str
    requisito: str
    estado: str
    evidencia: str
    como_verificar: str = ""
    depende_de: str = ""


@dataclass
class Contexto:
    cfg: ConfigEntrega
    raiz: Path
    reproducir: bool = False
    items: list[Item] = field(default_factory=list)

    @property
    def a(self):  # noqa: ANN201
        return self.cfg.auditoria

    def agregar(self, *args: str, **kw: str) -> None:
        self.items.append(Item(*args, **kw))

    def ruta(self, rel: str) -> Path:
        return self.raiz / rel

    def json(self, rel: str) -> dict | None:
        try:
            return json.loads(self.ruta(rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def git(self, *args: str) -> str | None:
        r = subprocess.run(["git", *args], cwd=self.raiz, capture_output=True, text=True, check=False)  # noqa: S603, S607
        return r.stdout if r.returncode == 0 else None


def _archivos_versionados(c: Contexto) -> list[str]:
    salida = c.git("ls-files")
    if salida is not None:
        return [r for r in salida.splitlines() if r]
    return [str(p.relative_to(c.raiz)) for p in c.raiz.rglob("*") if p.is_file() and ".git" not in p.parts]


# ------------------------------------------------------------------------------------------------ admisión (sección 5)


def notion(c: Contexto) -> None:
    a = c.a
    c.agregar("S5-01", "Admisión (sec. 5)", "URL de Notion accesible al jurado al cierre", NO_VERIFICABLE,
              "Depende del acceso de la cuenta del jurado; no hay URL ni token de Notion en el repo.",
              "Abrir la URL del espacio en una ventana privada y con la cuenta del jurado.", "C-05")
    c.agregar("S5-02", "Admisión (sec. 5)", f"Plan con al menos {a.minimo_tareas_notion} tareas y {a.minimo_decisiones_notion} decisiones justificadas",
              NO_VERIFICABLE, f"Local: {len(list(c.ruta('specs').glob('*.md')))} specs en specs/ (una por tarea). El conteo real vive en las bases Backlog y Decisiones de Notion.",
              f"En Notion: Backlog ≥ {a.minimo_tareas_notion} filas y Decisiones ≥ {a.minimo_decisiones_notion} con contexto, opciones y justificación.", "C-05")
    c.agregar("S5-03", "Admisión (sec. 5)", "Registro durante la ejecución, no solo un resumen final", NO_VERIFICABLE,
              "Las bases Bitácora y Decisiones con Fase = Evento.", "En Notion: filtrar Bitácora y Decisiones por Fase = Evento y comprobar fechas repartidas durante el evento.", "C-05")


def catalogo(c: Contexto) -> None:
    a = c.a
    ruta = c.ruta(a.catalogo)
    if not ruta.is_file():
        c.agregar("S5-04", "Admisión (sec. 5)", "Catálogo completo de las fuentes utilizadas", FALTA, f"No existe {a.catalogo}.", "poetry run python -m scripts.catalogo")
        return
    with ruta.open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    nombres = " | ".join(r.get(a.columna_fuente_catalogo, "") for r in filas).lower()
    manifest = c.json(a.manifest) or {}
    claves = sorted(manifest.get("licencias", {}))           # las fuentes que el manifest declara: una nueva no puede pasar sin catalogar
    sin_nombre = [k for k in claves if k not in a.nombres_fuentes_catalogo]
    faltan = [a.nombres_fuentes_catalogo[k] for k in claves if k in a.nombres_fuentes_catalogo and a.nombres_fuentes_catalogo[k].lower() not in nombres]
    sin_licencia = [r.get(a.columna_fuente_catalogo, "?") for r in filas if not (r.get("Licencia / condiciones") or "").strip()]
    estado = PASS if claves and not sin_nombre and not faltan and not sin_licencia and filas else FALTA
    c.agregar("S5-04", "Admisión (sec. 5)", "Catálogo completo de las fuentes utilizadas (cada fuente del manifest, con licencia/condiciones)", estado,
              f"{a.catalogo}: {len(filas)} fuentes; fuentes del manifest ({a.manifest}): {claves or 'ninguna'}; sin nombre de catálogo en la configuración: {sin_nombre or 'ninguna'}; "
              f"sin catalogar: {faltan or 'ninguna'}; sin licencia: {sin_licencia or 'ninguna'}.", "poetry run python -m scripts.catalogo")


def fichas(c: Contexto) -> None:
    a = c.a
    t = c.json(a.trazabilidad)
    if t is None:
        c.agregar("S5-05", "Admisión (sec. 5)", f"Al menos {a.minimo_fichas_trazables} fichas trazables, una sin evidencia suficiente", FALTA,
                  f"No existe o no se puede leer {a.trazabilidad}.", "poetry run python -m scripts.fichas_trazables", "C-01")
        return
    elegidas = (t.get("seleccion") or {}).get("elegidas", [])
    insuficientes = [e["id_caso"] for e in elegidas if e.get("estado") == "insuficiente"]
    n = int(t.get("n_fichas", 0))
    ok = n >= a.minimo_fichas_trazables and bool(insuficientes) and bool(t.get("todo_ok"))
    c.agregar("S5-05", "Admisión (sec. 5)", f"Al menos {a.minimo_fichas_trazables} fichas trazables, incluyendo un caso sin evidencia suficiente",
              PASS if ok else FALTA,
              f"{a.trazabilidad}: {n} fichas, todo_ok={t.get('todo_ok')}, insuficientes={insuficientes}. "
              f"Aviso: juicio_humano={t.get('juicio_humano')} (revisión provisional hasta C-09).", "poetry run python -m scripts.fichas_trazables", "C-01")


def pruebas(c: Contexto) -> None:
    a = c.a
    ruta = c.ruta(a.pruebas)
    if not ruta.is_file():
        c.agregar("S5-06", "Admisión (sec. 5)", f"Matriz de los {a.minimo_casos_prueba} casos de prueba (T01–T10)", FALTA, f"No existe {a.pruebas}.", "poetry run python -m eval.reporte_pruebas")
        return
    with ruta.open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    ids = {r["ID"] for r in filas}
    esperados = {f"T{i:02d}" for i in range(1, a.minimo_casos_prueba + 1)}
    no_ok = {r["ID"]: r["Estado"] for r in filas if r["Estado"] != a.estado_prueba_ok}
    estado = PASS if ids >= esperados and not no_ok else FALTA
    c.agregar("S5-06", "Admisión (sec. 5)", f"Matriz de los {a.minimo_casos_prueba} casos de prueba, todos en «{a.estado_prueba_ok}»", estado,
              f"{a.pruebas}: {len(filas)} filas; faltan {sorted(esperados - ids) or 'ninguna'}; no pasan: {no_ok or 'ninguna'}.",
              "poetry run python -m eval.reporte_pruebas (tras terminar E2-02/C-04 para T09 y T10)", "C-04, E2-02")


def metricas(c: Contexto) -> None:
    a = c.a
    ruta = c.ruta(a.pagina_metricas)
    if not ruta.is_file():
        c.agregar("S5-07", "Admisión (sec. 5)", "Métricas de la ejecución final", FALTA, f"No existe {a.pagina_metricas}.", "poetry run python -m scripts.pagina_metricas", "C-02, C-10")
        return
    texto = ruta.read_text(encoding="utf-8")
    m = re.search(r"desde el commit `([0-9a-f]{7,40})`", texto)
    commit = m.group(1) if m else ""
    problemas: list[str] = []
    if not commit:
        problemas.append("la página no declara su commit")
    else:
        cambios = c.git("diff", "--name-only", commit, "HEAD", "--", *a.carpetas_codigo_metricas, *(f":(exclude){x}" for x in a.sin_efecto_en_metricas))
        if cambios is None:
            problemas.append(f"el commit {commit} de la página no existe en este repo")
        elif cambios.strip():
            lista = cambios.split()
            problemas.append(f"{len(lista)} archivos de {a.carpetas_codigo_metricas} cambiaron desde el commit {commit} (p. ej. {lista[:3]}): regenerar las métricas")
    if a.marca_borrador_metricas in texto:
        problemas.append(f"la página sigue marcada «{a.marca_borrador_metricas}»")
    if a.marca_provisional_metricas in texto:
        problemas.append(f"hay métricas con juicio {a.marca_provisional_metricas} (D-101)")
    c.agregar("S5-07", "Admisión (sec. 5)", "Métricas de la ejecución final: página generada del commit vigente, sin borrador ni juicios provisionales",
              FALTA if problemas else PASS, f"{a.pagina_metricas} (commit {commit or '?'}): " + ("; ".join(problemas) if problemas else "vigente y definitiva."),
              "Tras C-09 y C-10: correr los eval/ y `poetry run python -m scripts.pagina_metricas`.", "C-09, C-10")


def pitch(c: Contexto) -> None:
    c.agregar("S5-08", "Admisión (sec. 5)", "Pitch de 10 minutos presentado desde Notion", NO_VERIFICABLE, "No hay artefacto local que lo demuestre; se presenta en vivo desde Notion.",
              "Ensayo cronometrado desde la página de Notion (sin PDF ni PowerPoint) con enlaces al prototipo y a GitHub.", "C-03, C-04")


# ------------------------------------------------------------------------------------------------ entregables (sección 10)


def _revisar_env_ejemplo(c: Contexto, env: Path) -> tuple[list[str], list[str], list[str]]:
    """(nombres de variables, variables secretas con valor, patrones de secreto que coinciden). Nunca devuelve un valor."""
    if not env.is_file():
        return [], [], []
    texto = env.read_text(encoding="utf-8")
    secretas = [re.compile(x) for x in c.a.nombres_secretos_env]
    nombres: list[str] = []
    con_valor: list[str] = []
    for linea in texto.splitlines():
        if "=" not in linea or linea.lstrip().startswith("#"):
            continue
        nombre, _, valor = linea.partition("=")
        nombre, valor = nombre.strip().removeprefix("export ").strip(), valor.strip().strip("'\"")
        nombres.append(nombre)
        if any(rx.search(nombre) for rx in secretas) and valor and valor not in c.a.placeholders_env:
            con_valor.append(nombre)
    patrones = [re.compile(x) for x in c.cfg.paquete.prohibido.patrones_secretos]
    return nombres, con_valor, [p.pattern[:30] for p in patrones if p.search(texto)]


def entregables(c: Contexto) -> None:
    a = c.a
    d = a.demo
    faltan = [r for r in (d.base, d.verificar_offline, d.guion) if not c.ruta(r).exists()]
    c.agregar("S10-01", "Entregables (sec. 10)", "Prototipo ejecutable y demo reproducible sin fuente en vivo", FALTA if faltan else PASS,
              f"Faltan: {faltan}" if faltan else "Base de demo, guion y verificación offline presentes.", "poetry run python -m scripts.verificar_offline", "C-06, C-04")
    readme = c.ruta(a.readme)
    titulos = re.findall(r"(?m)^#{1,3}\s+(.+)$", readme.read_text(encoding="utf-8")) if readme.is_file() else []
    sin = [k for k, rx in a.secciones_readme.items() if not any(re.search(rx, t, re.I) for t in titulos)]
    c.agregar("S10-02", "Entregables (sec. 10)", "README con instalación, comando de ejecución, pruebas y evaluación reservada", FALTA if sin or not titulos else PASS,
              f"{a.readme}: encabezados {len(titulos)}; secciones que faltan: {sin or 'ninguna'}.", "Editar README.md")
    env = c.ruta(a.env_ejemplo)
    nombres_env, con_valor, sospechosas = _revisar_env_ejemplo(c, env)
    ok_env = env.is_file() and bool(nombres_env) and not con_valor and not sospechosas
    c.agregar("S10-03", "Entregables (sec. 10)", ".env.example solo con nombres de variables, sin valores en las claves y sin nada que parezca un secreto", PASS if ok_env else FALTA,
              (f"{a.env_ejemplo}: {len(nombres_env)} variables; claves con valor: {con_valor or 'ninguna'}; coincidencias con patrones de secreto: {sospechosas or 'ninguna'}." if env.is_file()
               else f"No existe {a.env_ejemplo}."),
              "Dejar vacíos los valores de *_KEY, *_TOKEN, *_SECRET y *_PASSWORD; el valor real va en local.env.")
    c.agregar("S10-04", "Entregables (sec. 10)", "Dependencias fijadas", PASS if c.ruta(a.lock).is_file() else FALTA, f"{a.lock} {'presente' if c.ruta(a.lock).is_file() else 'ausente'}.",
              "poetry lock")
    lic = [n for n in a.licencia_codigo if c.ruta(n).is_file()]
    c.agregar("S10-05", "Entregables (sec. 10)", "Archivo LICENSE para el código (spec C-07)", PASS if lic else FALTA,
              f"Encontrado: {lic}" if lic else f"No existe ninguno de {a.licencia_codigo}; el README dice «licencia pendiente de decisión del equipo».", "El equipo elige la licencia y agrega LICENSE.", "decisión del equipo")
    c.agregar("S10-06", "Entregables (sec. 10)", "Repositorio con acceso del jurado (privado con colaboradores, o público)", NO_VERIFICABLE,
              "La visibilidad y los colaboradores viven en GitHub.", "`gh repo view DEVHUBPTY/HackAIthon --json visibility` y comprobar que el jurado figura como colaborador.", "C-05")
    c.agregar("S10-07", "Entregables (sec. 10)", "Espacio Notion con los artefactos de la sección 5 y la presentación final (PDF de respaldo opcional)", NO_VERIFICABLE,
              "Solo se ve en Notion.", "Recorrer el índice del espacio con la lista de la sección 5.", "C-03, C-05, C-08")
    c.agregar("S10-08", "Entregables (sec. 10)", "Instalación limpia en otra máquina: git clone, poetry install, comando de ejecución y pytest", NO_VERIFICABLE,
              "Requiere otra máquina.", "En una máquina sin el repo: seguir README.md y correr `poetry run pytest -v`.", "C-04")
    c.agregar("S10-09", "Entregables (sec. 10)", "Checklist de admisión y autoevaluación con la rúbrica completos", NO_VERIFICABLE, "Viven en Notion.",
              "Revisar la página de autoevaluación contra la rúbrica de 100 puntos.", "C-08")


def paquete_datos(c: Contexto) -> None:
    hallazgos = paquete.verificar(c.cfg, c.raiz)
    estado = PASS if not hallazgos else FALTA
    carpeta = c.cfg.paquete.carpeta
    c.agregar("S10-10", "Entregables (sec. 10)", "Paquete de datos redistribuible: snapshot, diccionario, manifest, licencias, benchmark dev, sin campos restringidos", estado,
              f"{carpeta}: " + ("checksums correctos y sin material prohibido." if not hallazgos else "; ".join(str(h) for h in hallazgos[:5])),
              "poetry run python -m scripts.empaquetar_datos")
    sbp = c.cfg.paquete.sbp
    c.agregar("S10-11", "Entregables (sec. 10)", "SBP (D-116): autorización escrita o CSV retirado si la entrega es pública", NO_VERIFICABLE,
              f"El CSV {'se incluye' if sbp.incluir else 'está retirado'} en el paquete; autorización escrita de la SBP: pendiente de pedir (docs/fuentes.md). Decisión del dueño según la visibilidad.",
              "Si el repo o el paquete son públicos: pedir la autorización o poner paquete.sbp.incluir: false y retirar data/processed/sbp_series.csv.", "decisión del dueño")


# ------------------------------------------------------------------------------------------------ condiciones previas


def secretos(c: Contexto) -> None:
    a, p = c.a, c.cfg.paquete.prohibido
    patrones = [re.compile(x) for x in p.patrones_secretos]
    omitidas = set(a.escaneo_secretos_extensiones_omitidas)
    hallazgos: list[str] = []
    for rel in _archivos_versionados(c):
        ruta = c.ruta(rel)
        if rel in a.archivos_sin_escanear or ruta.suffix in omitidas or not ruta.is_file():
            continue
        for patron in paquete.buscar_secretos(ruta, patrones):
            hallazgos.append(f"{rel} ({patron[:30]})")
    versionados_env = [r for r in _archivos_versionados(c) if Path(r).name in ("local.env", ".env")]
    res = c.json(a.resultado_secretos)
    arbol = f"escaneo rápido de {len(_archivos_versionados(c))} archivos versionados: " + (f"{len(hallazgos)} coincidencias {hallazgos[:5]}" if hallazgos else "sin coincidencias") + \
        f"; local.env/.env versionados: {versionados_env or 'no'}."
    if hallazgos or versionados_env:
        c.agregar("P-01", "Condiciones previas", "Sin secretos en historial, archivos, capturas ni exportaciones", FALTA, arbol, "Retirar y rotar la credencial; limpiar historial", "C-11")
    elif res is None:
        c.agregar("P-01", "Condiciones previas", "Sin secretos en historial, archivos, capturas ni exportaciones", FALTA,
                  f"Pendiente C-11: no existe {a.resultado_secretos} (escaneo del historial de git, capturas y exportaciones). {arbol}", "Correr el escaneo de C-11 y guardar su resultado.", "C-11")
    else:
        limpio = res.get("limpio") is True
        c.agregar("P-01", "Condiciones previas", "Sin secretos en historial, archivos, capturas ni exportaciones", PASS if limpio else FALTA,
                  f"{a.resultado_secretos}: limpio={res.get('limpio')}. {arbol}", "Resultado de C-11.", "C-11")


def _registros_fichas(c: Contexto) -> tuple[list[dict], list[str]]:
    """Las líneas de fichas.jsonl como registros, y los problemas de lectura o de contrato (campos que faltan)."""
    ruta = c.ruta(c.a.fichas_jsonl)
    if not ruta.is_file():
        return [], [f"no existe {c.a.fichas_jsonl}"]
    registros: list[dict] = []
    problemas: list[str] = []
    for i, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if not linea.strip():
            continue
        try:
            r = json.loads(linea)
        except ValueError:
            problemas.append(f"línea {i} no es JSON")
            continue
        faltan = [k for k in c.a.campos_fichas_jsonl if k not in r]
        if faltan:
            problemas.append(f"{r.get('id_caso')}: sin campos del contrato {faltan}")
        registros.append(r)
    return registros, problemas


def _textos_exportados(c: Contexto) -> tuple[dict[str, list[str]], list[str]]:
    """Lo que se entrega de cada caso: sus CASO-*.md y las filas de los CSV de las carpetas de exportación. (id_caso -> textos, rutas leídas)."""
    por_caso: dict[str, list[str]] = {}
    leidas: list[str] = []
    for carpeta in c.a.exportaciones:
        base = c.ruta(carpeta)
        for f in sorted(base.glob("CASO-*.md")) if base.is_dir() else []:
            por_caso.setdefault(f.stem, []).append(f.read_text(encoding="utf-8"))
            leidas.append(f"{carpeta}/{f.name}")
        for f in sorted(base.glob("*.csv")) if base.is_dir() else []:
            with f.open(encoding="utf-8", newline="") as fh:
                for fila in csv.DictReader(fh):
                    id_caso = fila.get("ID caso") or fila.get("id_caso") or ""
                    por_caso.setdefault(id_caso, []).append(" ".join(str(v) for v in fila.values()))
            leidas.append(f"{carpeta}/{f.name}")
    return por_caso, leidas


def reverificar_fichas(c: Contexto, registros: list[dict], exportados: dict[str, list[str]]) -> dict[str, dict] | None:
    """Corre de nuevo la comprobación de trazabilidad de ``src/trazabilidad.py`` (el validador de citas, cifras, D-31 y D-32) sobre CADA registro de
    fichas.jsonl contra los datos de esta máquina, con los textos exportados del caso como salidas extra. ``None`` si no hay base de señales.
    Devuelve id_caso -> {"fallos": [...], "citas": [(id, campo, existe)]}."""
    base = c.ruta(c.a.base_senales)
    if not base.is_file():
        return None
    from src import db
    from src.configuracion import cargar_fichas_trazables
    from src.esquemas import Ficha
    from src.trazabilidad import Resolutor, verificar_ficha

    cfg_t = cargar_fichas_trazables()
    con = db.conectar(base, solo_lectura=True)
    try:
        resolutor = Resolutor(con, cfg_t, c.raiz)
        salida: dict[str, dict] = {}
        for r in registros:
            id_caso = str(r.get("id_caso"))
            try:
                res = verificar_ficha(Ficha.model_validate(r["ficha"]), resolutor, cfg_t, id_caso=id_caso, estado_revision=r.get("estado_revision"),
                                      textos_extra=exportados.get(id_caso, ()))
            except ValueError as exc:                        # la ficha ya no cumple su propio esquema: es un fallo, no una caída de la auditoría
                salida[id_caso] = {"fallos": [f"esquema_de_ficha: {str(exc).splitlines()[0][:120]}"], "citas": []}
                continue
            salida[id_caso] = {"fallos": [f"{u.regla}: {u.detalle}" for u in res.fallos()], "citas": sorted((t.id, t.campo, bool(t.existe)) for t in res.trazas)}
        return salida
    finally:
        con.close()


def validador(c: Contexto) -> None:
    a = c.a
    titulo = "Toda afirmación de fichas.jsonl y de las exportaciones pasa el validador; ninguna cita falsa"
    comando = "poetry run python -m scripts.fichas_trazables --casos; poetry run python -m src.ficha --formato jsonl"
    t = c.json(a.trazabilidad)
    registros, problemas = _registros_fichas(c)
    if t is None:
        problemas.append(f"no existe o no se puede leer {a.trazabilidad}")
        t = {}
    por_caso = {f.get("id_caso"): f for f in t.get("fichas", [])}
    ids = [str(r.get("id_caso")) for r in registros]
    if not registros:
        problemas.append("fichas.jsonl no tiene fichas")
    # trazabilidad.json vs fichas.jsonl: lo que el informe cubre es exactamente lo que fichas.jsonl dice que sigue vigente
    vigentes = {str(r.get("id_caso")): r.get("id_grupo") for r in registros if r.get("estado_revision") not in a.estados_sin_trazabilidad}
    if set(vigentes) != set(por_caso):
        problemas.append(f"trazabilidad.json desactualizado: cubre {sorted(por_caso)} y fichas.jsonl pide {sorted(vigentes)}")
    else:
        distintos = sorted(k for k, g in vigentes.items() if por_caso[k].get("id_grupo") != g)
        if distintos:
            problemas.append(f"trazabilidad.json desactualizado: otro grupo en {distintos}")
    falsas = [(ci.get("id"), ci.get("campo")) for f in por_caso.values() for ci in f.get("citas", []) if not ci.get("existe_en_datos")]
    if falsas:
        problemas.append(f"citas no resueltas en trazabilidad.json: {falsas}")
    if not t.get("todo_ok"):
        problemas.append("trazabilidad.json: todo_ok no es verdadero")
    exportados, leidas = _textos_exportados(c)
    huerfanos = sorted(k for k in exportados if k not in ids)
    if huerfanos:
        problemas.append(f"exportaciones de casos que no están en fichas.jsonl: {huerfanos}")
    vivo = reverificar_fichas(c, registros, exportados) if registros else None
    sin_verificar: list[str] = []
    informativos: list[str] = []
    if vivo is not None:
        for r in registros:
            id_caso = str(r.get("id_caso"))
            v = vivo.get(id_caso)
            if v is None:
                sin_verificar.append(id_caso)
                continue
            if v["fallos"] and r.get("nota_estado") and all(f.startswith(("cita_con_id_en_datos", "cita_con_campo_y_valor")) and str(r.get("id_grupo")) in f for f in v["fallos"]):
                informativos.append(f"{id_caso}: {r['nota_estado']} (se conserva en el historial; sus {len(v['fallos'])} citas ya no se pueden resolver)")
            elif v["fallos"]:
                problemas.append(f"{id_caso}: {len(v['fallos'])} fallos del validador ({v['fallos'][0][:80]})")
            guardadas = sorted((ci.get("id"), ci.get("campo"), bool(ci.get("existe_en_datos"))) for ci in por_caso.get(id_caso, {}).get("citas", []))
            if id_caso in por_caso and guardadas != [tuple(x) for x in v["citas"]]:
                problemas.append(f"trazabilidad.json desactualizado: las citas de {id_caso} ya no coinciden con los datos actuales")
        if sin_verificar:
            problemas.append(f"fichas sin verificar: {sin_verificar}")
    sin_cubrir = [i for i in ids if i not in por_caso] if vivo is None else []
    cobertura = (f"re-verificadas con el validador contra {a.base_senales}: {len(vivo)} de {len(registros)}" if vivo is not None
                 else f"sin {a.base_senales} en esta máquina: solo cubiertas por trazabilidad.json {len(registros) - len(sin_cubrir)} de {len(registros)}")
    detalle = (f"{a.fichas_jsonl}: {len(registros)} fichas ({', '.join(ids)}); {cobertura}; exportaciones revisadas: {len(leidas)} archivos; "
               f"problemas: {problemas or 'ninguno'}; informativo: {informativos or 'ninguno'}.")
    if problemas:
        estado = FALTA
    elif vivo is None:
        estado = NO_VERIFICABLE
        detalle += f" No se pudo correr el validador sobre {sin_cubrir or 'las fichas'}."
    else:
        estado = PASS
    c.agregar("P-02", "Condiciones previas", titulo, estado, detalle, comando, "C-01")


def sin_publicar(c: Contexto) -> None:
    a = c.a
    patron = re.compile(a.patron_publicar)
    cfg_rev = yaml.safe_load(c.ruta(a.revision_config).read_text(encoding="utf-8")) if c.ruta(a.revision_config).is_file() else {}
    estados = [e for e in cfg_rev.get("estados", []) if patron.search(e)]
    etiquetas = [x.get("etiqueta", "") for x in cfg_rev.get("acciones", {}).values() if patron.search(x.get("etiqueta", ""))]
    app = c.ruta(a.app)
    botones = [l.strip()[:80] for l in app.read_text(encoding="utf-8").splitlines() if "button" in l and patron.search(l)] if app.is_file() else []
    ok = bool(cfg_rev) and app.is_file() and not (estados or etiquetas or botones)
    c.agregar("P-03", "Condiciones previas", "Ninguna acción, botón o estado «publicar»", PASS if ok else FALTA,
              f"{a.revision_config}: estados {cfg_rev.get('estados')}; con «publicar»: {estados or 'ninguno'}; etiquetas: {etiquetas or 'ninguna'}; botones en {a.app}: {botones or 'ninguno'}.",
              "Revisar a mano la app antes de cerrar.")


def restringido(c: Contexto) -> None:
    a = c.a
    versionados = _archivos_versionados(c)
    rutas = [r for lst in cargar_fuentes().redistribucion_restringida.values() for r in lst]
    metidos = sorted(f for f in versionados for r in rutas if f.startswith(r))
    reservado = sorted(f for f in versionados if re.search(a.patron_reservado, f))
    bases = sorted(f for f in versionados if any(fnmatch.fnmatch(f, pat) or fnmatch.fnmatch(Path(f).name, pat) for pat in a.nunca_versionados))
    c.agregar("P-04", "Condiciones previas", "Nada con redistribución restringida, ni bases de datos de la sesión, ni el benchmark reservado en el repositorio (D-72)",
              PASS if not (metidos or reservado or bases) else FALTA,
              f"`git ls-files` ({len(versionados)} archivos): rutas restringidas ({rutas}) versionadas: {metidos[:5] or 'ninguna'}; "
              f"bases {a.nunca_versionados} versionadas: {bases[:5] or 'ninguna'}; benchmark reservado versionado: {reservado or 'ninguno'}.", "git rm --cached <ruta>")


def provisionales(c: Contexto) -> None:
    t = c.json(c.a.trazabilidad) or {}
    pend = []
    if t.get("juicio_humano") is False:
        pend.append("fichas trazables: revisión provisional del asistente")
    texto = c.ruta(c.a.pagina_metricas).read_text(encoding="utf-8") if c.ruta(c.a.pagina_metricas).is_file() else ""
    if c.a.marca_provisional_metricas in texto:
        pend.append("página de métricas: sustento y Precision@5 PROVISIONAL")
    c.agregar("P-05", "Condiciones previas", "Los juicios que exige una persona (sustento, Precision@5, revisión editorial) los hizo una persona (D-85, D-101)", FALTA if pend else PASS,
              "; ".join(pend) if pend else "Sin juicios provisionales.", "Una persona rehace el juicio y se regenera (C-09).", "C-09")


def reproducibilidad(c: Contexto) -> None:
    a = c.a
    m = c.json("data/manifest.json") or {}
    if not c.reproducir:
        registrado = bool(m.get("reproducibilidad"))
        c.agregar("P-06", "Condiciones previas", "Reproducibilidad de punta a punta (hashes del manifest)", NO_VERIFICABLE,
                  f"Hashes registrados en el manifest: {'sí' if registrado else 'no'}. No se corrió aquí (≈ 1 min).",
                  "poetry run python -m scripts.reproducir --verificar, o esta auditoría con --reproducir (restaurar outputs/metricas.json si solo cambió el tiempo).")
        return
    r = subprocess.run([sys.executable, *a.comando_reproducir], cwd=c.raiz, capture_output=True, text=True, timeout=a.espera_reproducir_segundos, check=False)  # noqa: S603
    cola = (r.stdout + r.stderr).strip().splitlines()[-3:]
    c.agregar("P-06", "Condiciones previas", "Reproducibilidad de punta a punta (hashes del manifest)", PASS if r.returncode == 0 else FALTA,
              f"{' '.join(['python', *a.comando_reproducir])} → código {r.returncode}: {' | '.join(cola)}", "poetry run python -m scripts.reproducir --verificar")


VERIFICACIONES = (notion, catalogo, fichas, pruebas, metricas, pitch, entregables, paquete_datos, secretos, validador, sin_publicar, restringido, provisionales, reproducibilidad)


def auditar(cfg: ConfigEntrega | None = None, raiz: Path = RAIZ, *, reproducir: bool = False) -> list[Item]:
    c = Contexto(cfg or cargar_entrega(), raiz, reproducir)
    for v in VERIFICACIONES:
        v(c)
    return c.items


def resumen(items: list[Item]) -> dict[str, int]:
    return {e: sum(1 for i in items if i.estado == e) for e in (PASS, FALTA, NO_VERIFICABLE)}


def a_markdown(items: list[Item], commit: str, fecha: str) -> str:
    r = resumen(items)
    L = ["# Auditoría final · condiciones previas (C-07)", "",
         f"Generada el {fecha} desde el commit `{commit}` con `poetry run python -m scripts.auditoria_final`. PASS: {r[PASS]} · FALTA: {r[FALTA]} · NO VERIFICABLE AUTOMÁTICAMENTE: {r[NO_VERIFICABLE]}.", "",
         "| ID | Requisito | Estado | Depende de |", "|---|---|---|---|"]
    L += [f"| {i.id} | {i.requisito} | **{i.estado}** | {i.depende_de or '—'} |" for i in items]
    L += ["", "## Evidencia y cómo verificar", ""]
    for i in items:
        L += [f"### {i.id} · {i.estado}", "", f"- **Requisito:** {i.requisito}", f"- **Evidencia:** {i.evidencia}"]
        if i.como_verificar:
            L.append(f"- **Cómo verificar o corregir:** {i.como_verificar}")
        L.append("")
    return "\n".join(L)


def principal(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C-07: auditoría final de las condiciones previas")
    parser.add_argument("--reproducir", action="store_true", help="corre también scripts.reproducir --verificar")
    parser.add_argument("--estricto", action="store_true", help="también falla si algo es NO VERIFICABLE AUTOMÁTICAMENTE")
    args = parser.parse_args(argv)
    cfg = cargar_entrega()
    items = auditar(cfg, reproducir=args.reproducir)
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, capture_output=True, text=True, check=False)  # noqa: S603, S607
    commit, fecha = r.stdout.strip() or "sin git", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md, js = RAIZ / cfg.auditoria.salida_md, RAIZ / cfg.auditoria.salida_json
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(a_markdown(items, commit, fecha), encoding="utf-8")
    js.write_text(json.dumps({"commit": commit, "generado_utc": fecha, "resumen": resumen(items), "items": [asdict(i) for i in items]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for i in items:
        print(f"{i.estado:34s} {i.id:7s} {i.requisito}")
    print(f"\n{resumen(items)} → {md}")
    r_ = resumen(items)
    return 1 if r_[FALTA] or (args.estricto and r_[NO_VERIFICABLE]) else 0


if __name__ == "__main__":
    raise SystemExit(principal())
