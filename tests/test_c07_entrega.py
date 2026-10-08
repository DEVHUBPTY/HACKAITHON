"""C-07: el paquete de datos no lleva material prohibido y la auditoría final da el estado correcto a cada ítem."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import auditoria_final as aud
from scripts import empaquetar_datos as emp
from src.configuracion import CARPETA_CONFIG, RAIZ, ErrorDeConfiguracion, cargar_config, cargar_entrega, ConfigEntrega, validar_todo

CFG = cargar_entrega()


def _por_id(items: list[aud.Item], id_: str) -> aud.Item:
    return next(i for i in items if i.id == id_)


# ---------------------------------------------------------------------------------------------- configuración


def test_la_configuracion_se_valida_con_el_resto() -> None:
    assert "entrega" in validar_todo()


def test_la_configuracion_prohibe_claves_extra(tmp_path: Path) -> None:
    datos = yaml.safe_load((CARPETA_CONFIG / "entrega.yaml").read_text(encoding="utf-8"))
    datos["paquete"]["extra"] = 1
    (tmp_path / "entrega.yaml").write_text(yaml.safe_dump(datos), encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion):
        cargar_config("entrega", ConfigEntrega, tmp_path)


def test_la_configuracion_rechaza_una_ruta_restringida_en_la_lista(tmp_path: Path) -> None:
    datos = yaml.safe_load((CARPETA_CONFIG / "entrega.yaml").read_text(encoding="utf-8"))
    datos["paquete"]["archivos"]["snapshot/rss.xml"] = "data/raw/rss_tvn/rss_tvn_20261006T155952Z.xml"
    (tmp_path / "entrega.yaml").write_text(yaml.safe_dump(datos), encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match="ruta prohibida"):
        cargar_config("entrega", ConfigEntrega, tmp_path)


# ---------------------------------------------------------------------------------------------- paquete


def test_el_paquete_real_no_tiene_descripciones_socialimage_ni_extractos(tmp_path: Path) -> None:
    indice = emp.construir(CFG, RAIZ, tmp_path / "datos")
    carpeta = tmp_path / "datos"
    assert indice["n_archivos"] > 20
    assert emp.revisar_carpeta(carpeta, CFG) == []
    for f in carpeta.rglob("*"):
        if f.suffix in CFG.paquete.prohibido.extensiones_estructuradas:
            assert not emp.campos_restringidos_de(f, CFG), f
    nombres = {f.name for f in carpeta.rglob("*") if f.is_file()}
    assert not {"local.env", ".env"} & nombres
    assert not [n for n in nombres if n.endswith((".duckdb", ".xlsx", ".xml"))]
    assert not [f for f in carpeta.rglob("*") if "reservado" in f.name.lower()]
    assert (carpeta / CFG.paquete.sbp.nota_destino).is_file()           # D-116: la SBP va con su nota de riesgo
    assert (carpeta / CFG.paquete.sbp.destino).is_file()
    assert emp.verificar(CFG, RAIZ, carpeta) == []


def test_sin_sbp_el_csv_y_su_nota_no_entran(tmp_path: Path) -> None:
    cfg = CFG.model_copy(update={"paquete": CFG.paquete.model_copy(update={"sbp": CFG.paquete.sbp.model_copy(update={"incluir": False})})})
    emp.construir(cfg, RAIZ, tmp_path / "datos")
    assert not (tmp_path / "datos" / CFG.paquete.sbp.destino).exists()
    assert not (tmp_path / "datos" / CFG.paquete.sbp.nota_destino).exists()


def test_revisar_carpeta_detecta_cada_tipo_de_material_prohibido(tmp_path: Path) -> None:
    (tmp_path / "local.env").write_text("X=1\n", encoding="utf-8")
    (tmp_path / "base.duckdb").write_bytes(b"x")
    (tmp_path / "noticias.csv").write_text("id,titulo,descripcion\n1,a,b\n", encoding="utf-8")
    (tmp_path / "gdelt.json").write_text(json.dumps({"articles": [{"url": "u", "socialimage": "i"}]}), encoding="utf-8")
    (tmp_path / "notas.md").write_text("DEEPSEEK_API_KEY=abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    (tmp_path / "data" / "raw" / "rss_tvn").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "rss_tvn" / "x.txt").write_text("rss", encoding="utf-8")
    reglas = {h.regla for h in emp.revisar_carpeta(tmp_path, CFG)}
    assert {"nombre_prohibido", "campo_restringido", "secreto", "ruta_prohibida"} <= reglas


def test_construir_descarta_el_paquete_si_una_fuente_trae_un_campo_restringido(tmp_path: Path) -> None:
    raiz = tmp_path / "repo"
    for origen in emp._plan(CFG, RAIZ).values():
        destino = raiz / origen.relative_to(RAIZ)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(origen, destino)
    (raiz / "data").mkdir(exist_ok=True)
    noticias = raiz / "data" / "processed" / "noticias.csv"
    filas = list(csv.reader(noticias.open(encoding="utf-8", newline="")))
    filas[0].append("descripcion")
    for f in filas[1:]:
        f.append("texto protegido")
    with noticias.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(filas)
    with pytest.raises(emp.ErrorPaquete, match="campo_restringido"):
        emp.construir(CFG, raiz, raiz / "entrega" / "datos")
    assert not (raiz / "entrega" / "datos").exists()


def test_verificar_detecta_un_checksum_alterado_y_un_paquete_ausente(tmp_path: Path) -> None:
    assert emp.verificar(CFG, RAIZ, tmp_path / "no_existe")[0].regla == "paquete_ausente"
    emp.construir(CFG, RAIZ, tmp_path / "datos")
    objetivo = tmp_path / "datos" / "snapshot" / "indicadores.csv"
    objetivo.write_text(objetivo.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert {h.regla for h in emp.verificar(CFG, RAIZ, tmp_path / "datos")} == {"checksum"}


# ---------------------------------------------------------------------------------------------- auditoría


def _contexto(tmp_path: Path) -> aud.Contexto:
    return aud.Contexto(CFG, tmp_path)


def _pruebas(tmp_path: Path, estados: dict[str, str]) -> None:
    ruta = tmp_path / CFG.auditoria.pruebas
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ID", "Estado"])
        w.writeheader()
        w.writerows({"ID": k, "Estado": v} for k, v in estados.items())


def test_la_matriz_de_pruebas_exige_las_diez_en_pasa(tmp_path: Path) -> None:
    todos = {f"T{i:02d}": "Pasa" for i in range(1, 11)}
    _pruebas(tmp_path, todos)
    c = _contexto(tmp_path)
    aud.pruebas(c)
    assert c.items[0].estado == aud.PASS
    _pruebas(tmp_path, {**todos, "T09": "Pendiente"})
    c = _contexto(tmp_path)
    aud.pruebas(c)
    assert c.items[0].estado == aud.FALTA and "T09" in c.items[0].evidencia
    _pruebas(tmp_path, {k: v for k, v in todos.items() if k != "T10"})
    c = _contexto(tmp_path)
    aud.pruebas(c)
    assert c.items[0].estado == aud.FALTA


def _trazabilidad(tmp_path: Path, n: int, estados: list[str], todo_ok: bool = True) -> None:
    ruta = tmp_path / CFG.auditoria.trazabilidad
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"n_fichas": n, "todo_ok": todo_ok, "juicio_humano": False,
                                "seleccion": {"elegidas": [{"id_caso": f"CASO-{i}", "estado": e} for i, e in enumerate(estados)]}}), encoding="utf-8")


def test_las_fichas_trazables_exigen_cinco_y_una_insuficiente(tmp_path: Path) -> None:
    for n, estados, ok, esperado in [(5, ["suficiente"] * 4 + ["insuficiente"], True, aud.PASS), (5, ["suficiente"] * 5, True, aud.FALTA),
                                     (4, ["suficiente"] * 3 + ["insuficiente"], True, aud.FALTA), (5, ["suficiente"] * 4 + ["insuficiente"], False, aud.FALTA)]:
        _trazabilidad(tmp_path, n, estados, ok)
        c = _contexto(tmp_path)
        aud.fichas(c)
        assert c.items[0].estado == esperado, (n, estados, ok)


def test_secretos_sin_resultado_de_c11_queda_en_falta_pendiente(tmp_path: Path) -> None:
    c = _contexto(tmp_path)
    aud.secretos(c)
    assert c.items[0].estado == aud.FALTA and "Pendiente C-11" in c.items[0].evidencia
    ruta = tmp_path / CFG.auditoria.resultado_secretos
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"limpio": True}), encoding="utf-8")
    c = _contexto(tmp_path)
    aud.secretos(c)
    assert c.items[0].estado == aud.PASS


def test_secretos_en_un_archivo_son_falta_aunque_exista_resultado(tmp_path: Path) -> None:
    (tmp_path / "config.txt").write_text("API_KEY=abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    ruta = tmp_path / CFG.auditoria.resultado_secretos
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"limpio": True}), encoding="utf-8")
    c = _contexto(tmp_path)
    aud.secretos(c)
    assert c.items[0].estado == aud.FALTA and "config.txt" in c.items[0].evidencia
    assert "abcdefghijklmnopqrstuvwxyz123456" not in c.items[0].evidencia      # nunca se imprime el valor


def test_publicar_se_detecta_en_estados_y_botones(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / CFG.auditoria.revision_config).write_text(yaml.safe_dump({"estados": ["nuevo", "aprobado como borrador"], "acciones": {"a": {"etiqueta": "Aprobar como borrador"}}}), encoding="utf-8")
    (tmp_path / CFG.auditoria.app).write_text('st.button("Aprobar")\n', encoding="utf-8")
    c = _contexto(tmp_path)
    aud.sin_publicar(c)
    assert c.items[0].estado == aud.PASS
    (tmp_path / CFG.auditoria.app).write_text('st.button("Publicar nota")\n', encoding="utf-8")
    c = _contexto(tmp_path)
    aud.sin_publicar(c)
    assert c.items[0].estado == aud.FALTA


def test_la_pagina_de_metricas_provisional_es_falta(tmp_path: Path) -> None:
    ruta = tmp_path / CFG.auditoria.pagina_metricas
    ruta.parent.mkdir(parents=True)
    ruta.write_text("# Métricas\n> BORRADOR — métricas provisionales\nGenerada desde el commit `abcdef0` con x\n| PROVISIONAL |\n", encoding="utf-8")
    c = _contexto(tmp_path)
    aud.metricas(c)
    assert c.items[0].estado == aud.FALTA and "BORRADOR" in c.items[0].evidencia and "PROVISIONAL" in c.items[0].evidencia


def test_lo_que_depende_de_notion_nunca_se_marca_pass() -> None:
    items = aud.auditar(CFG, RAIZ)
    for id_ in ("S5-01", "S5-02", "S5-03", "S5-08", "S10-06", "S10-07", "S10-08", "S10-09", "S10-11"):
        it = _por_id(items, id_)
        assert it.estado == aud.NO_VERIFICABLE and it.como_verificar, id_
    assert {i.estado for i in items} <= {aud.PASS, aud.FALTA, aud.NO_VERIFICABLE}
    assert len({i.id for i in items}) == len(items)
    assert all(i.evidencia for i in items)


def test_el_markdown_y_el_resumen_cuentan_todos_los_items() -> None:
    items = aud.auditar(CFG, RAIZ)
    r = aud.resumen(items)
    assert sum(r.values()) == len(items)
    md = aud.a_markdown(items, "abc1234", "2026-10-07T00:00:00Z")
    assert all(f"### {i.id} · {i.estado}" in md for i in items)


def test_salir_con_1_si_hay_falta_y_con_estricto_si_hay_no_verificable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item = lambda e: aud.Item("X", "g", "r", e, "ev")   # noqa: E731
    cfg = CFG.model_copy(update={"auditoria": CFG.auditoria.model_copy(update={"salida_md": str(tmp_path / "a.md"), "salida_json": str(tmp_path / "a.json")})})
    monkeypatch.setattr(aud, "cargar_entrega", lambda: cfg)
    for items, args, esperado in [([item(aud.PASS)], [], 0), ([item(aud.FALTA)], [], 1), ([item(aud.NO_VERIFICABLE)], [], 0), ([item(aud.NO_VERIFICABLE)], ["--estricto"], 1)]:
        monkeypatch.setattr(aud, "auditar", lambda *a, _i=items, **k: _i)
        assert aud.principal(args) == esperado


# ---------------------------------------------------------------------------------------------- X112: campos restringidos por nombre normalizado y por valor


@pytest.mark.parametrize("nombre", ["descripcion_rss", "Descripción", "rss_description", "socialimage_url", "extracto_corto", "excerpt", "cuerpo_nota", "autor_firma", "author_name"])
def test_x112_una_columna_csv_con_prefijo_o_sufijo_restringido_se_detecta(tmp_path: Path, nombre: str) -> None:
    (tmp_path / "t.csv").write_text(f"id,{nombre}\n1,x\n", encoding="utf-8")
    assert {h.regla for h in emp.revisar_carpeta(tmp_path, CFG)} == {"campo_restringido"}


@pytest.mark.parametrize("clave", ["descripcion_rss", "Socialimage_url", "autor_nota"])
def test_x112_una_clave_json_anidada_con_prefijo_restringido_se_detecta(tmp_path: Path, clave: str) -> None:
    (tmp_path / "n.json").write_text(json.dumps({"lista": [{"x": {"y": [{clave: "texto"}]}}]}), encoding="utf-8")
    hallazgos = emp.revisar_carpeta(tmp_path, CFG)
    assert [h.regla for h in hallazgos] == ["campo_restringido"]


def test_x112_las_banderas_booleanas_permitidas_no_son_hallazgo(tmp_path: Path) -> None:
    (tmp_path / "f.json").write_text(json.dumps({"sin_descripcion_rss": True, "sin_nombres_de_autor": True}), encoding="utf-8")
    assert emp.revisar_carpeta(tmp_path, CFG) == []


def test_x112_los_valores_crudos_del_rss_y_de_socialimage_se_buscan_en_texto_libre(tmp_path: Path) -> None:
    raiz = tmp_path / "repo"
    (raiz / "data" / "raw" / "rss_tvn").mkdir(parents=True)
    (raiz / "data" / "raw" / "gdelt").mkdir(parents=True)
    descripcion = "La sesión estuvo marcada por tensión e intercambios de palabras entre los diputados."
    (raiz / "data" / "raw" / "rss_tvn" / "r.xml").write_text(
        f"<rss><channel><description>Portada</description><item><description><![CDATA[{descripcion}]]></description></item></channel></rss>", encoding="utf-8")
    imagen = "https://cdn.ejemplo.com/imagenes/social/0123456789abcdef.jpg"
    (raiz / "data" / "raw" / "gdelt" / "g.json").write_text(json.dumps({"articles": [{"socialimage": imagen}]}), encoding="utf-8")
    valores = emp.valores_restringidos(CFG, raiz)
    assert len(valores) == 2                                           # «Portada» es más corta que el mínimo y no se busca
    paquete = tmp_path / "paquete"
    paquete.mkdir()
    (paquete / "nota.md").write_text(f"Resumen:\n{descripcion.upper()}\n", encoding="utf-8")   # distinta capitalización y renglón
    (paquete / "ok.md").write_text("nada que ver\n", encoding="utf-8")
    (paquete / "img.txt").write_text(f"ver {imagen}\n", encoding="utf-8")
    hallazgos = emp.revisar_carpeta(paquete, CFG, restringidos=valores)
    assert {(h.regla, h.archivo) for h in hallazgos} == {("valor_restringido", "nota.md"), ("valor_restringido", "img.txt")}
    assert descripcion not in " ".join(str(h) for h in hallazgos)      # el hallazgo nombra el archivo, nunca el valor


def test_x112_sin_crudos_locales_el_control_de_valores_se_omite(tmp_path: Path) -> None:
    assert emp.valores_restringidos(CFG, tmp_path) == set()


def test_x112_verificar_falla_con_un_archivo_que_no_esta_en_los_checksums(tmp_path: Path) -> None:
    emp.construir(CFG, RAIZ, tmp_path / "datos")
    assert emp.verificar(CFG, RAIZ, tmp_path / "datos") == []
    (tmp_path / "datos" / "snapshot" / "extra.txt").write_text("agregado después\n", encoding="utf-8")
    hallazgos = emp.verificar(CFG, RAIZ, tmp_path / "datos")
    assert [(h.regla, h.archivo) for h in hallazgos] == [("archivo_no_listado", "snapshot/extra.txt")]


def test_x112_la_vista_previa_no_entra_al_paquete_y_viene_de_la_configuracion(tmp_path: Path) -> None:
    assert CFG.paquete.carpetas_excluidas == ["vista_previa"]
    raiz = tmp_path / "repo"
    for origen in emp._plan(CFG, RAIZ).values():
        destino = raiz / origen.relative_to(RAIZ)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(origen, destino)
    previa = raiz / "outputs" / "fichas_trazables" / "vista_previa"
    previa.mkdir(parents=True)
    (previa / "GRP-x.md").write_text("vista previa\n", encoding="utf-8")
    assert not [d for d in emp._plan(CFG, raiz) if "vista_previa" in d]


# ---------------------------------------------------------------------------------------------- X110: P-02 re-verifica todas las fichas que se entregan


def _ficha_jsonl(tmp_path: Path, registros: list[tuple[str, str, str]]) -> None:
    ruta = tmp_path / CFG.auditoria.fichas_jsonl
    ruta.parent.mkdir(parents=True, exist_ok=True)
    base = {k: None for k in CFG.auditoria.campos_fichas_jsonl}
    ruta.write_text("".join(json.dumps({**base, "id_caso": c, "id_grupo": g, "estado_revision": e, "ficha": {}}) + "\n" for c, g, e in registros), encoding="utf-8")


def _traza(tmp_path: Path, casos: dict[str, str], todo_ok: bool = True, citas: list[dict] | None = None) -> None:
    ruta = tmp_path / CFG.auditoria.trazabilidad
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"todo_ok": todo_ok, "juicio_humano": True, "n_fichas": len(casos), "fichas": [
        {"id_caso": c, "id_grupo": g, "fallos": [], "citas": citas if citas is not None else [{"id": "NOT-1", "campo": "titulo", "existe_en_datos": True}]} for c, g in casos.items()]}), encoding="utf-8")


def _vivo(registros_ids: list[str], *, fallos: dict[str, list[str]] | None = None, citas: list[tuple] | None = None, omitir: tuple[str, ...] = ()):
    def falso(c, registros, exportados):  # noqa: ANN001, ANN202
        return {i: {"fallos": (fallos or {}).get(i, []), "citas": citas if citas is not None else [("NOT-1", "titulo", True)]} for i in registros_ids if i not in omitir}
    return falso


FICHAS = [("CASO-001", "GRP-a", "aprobado como borrador"), ("CASO-002", "GRP-b", "requiere evidencia"), ("CASO-004", "GRP-d", "descartado")]


def _p02(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vivo, *, fichas=FICHAS, traza=None) -> aud.Item:
    _ficha_jsonl(tmp_path, fichas)
    _traza(tmp_path, traza if traza is not None else {"CASO-001": "GRP-a", "CASO-002": "GRP-b"})
    monkeypatch.setattr(aud, "reverificar_fichas", vivo)
    c = _contexto(tmp_path)
    aud.validador(c)
    return c.items[0]


def test_x110_p02_pasa_solo_si_cada_ficha_de_fichas_jsonl_se_re_verifico(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _p02(tmp_path, monkeypatch, _vivo(["CASO-001", "CASO-002", "CASO-004"]))
    assert it.estado == aud.PASS and "3 de 3" in it.evidencia


def test_x110_una_ficha_de_fichas_jsonl_sin_verificar_es_falta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _p02(tmp_path, monkeypatch, _vivo(["CASO-001", "CASO-002", "CASO-004"], omitir=("CASO-004",)))
    assert it.estado == aud.FALTA and "CASO-004" in it.evidencia


def test_x110_una_ficha_vigente_que_trazabilidad_no_cubre_es_falta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _p02(tmp_path, monkeypatch, _vivo(["CASO-001", "CASO-002", "CASO-004"]), traza={"CASO-001": "GRP-a"})
    assert it.estado == aud.FALTA and "desactualizado" in it.evidencia


def test_x110_un_fallo_del_validador_en_una_ficha_descartada_tambien_es_falta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _p02(tmp_path, monkeypatch, _vivo(["CASO-001", "CASO-002", "CASO-004"], fallos={"CASO-004": ["cita_con_id_en_datos: NOT-9"]}))
    assert it.estado == aud.FALTA and "CASO-004" in it.evidencia


def test_x110_trazabilidad_con_citas_que_ya_no_coinciden_con_los_datos_es_falta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _p02(tmp_path, monkeypatch, _vivo(["CASO-001", "CASO-002", "CASO-004"], citas=[("NOT-1", "titulo", True), ("NOT-2", "titulo", True)]))
    assert it.estado == aud.FALTA and "ya no coinciden" in it.evidencia


def test_x110_trazabilidad_de_otro_grupo_es_falta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _p02(tmp_path, monkeypatch, _vivo(["CASO-001", "CASO-002", "CASO-004"]), traza={"CASO-001": "GRP-OTRO", "CASO-002": "GRP-b"})
    assert it.estado == aud.FALTA and "otro grupo" in it.evidencia


def test_x110_sin_base_de_senales_lo_no_cubierto_no_es_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _p02(tmp_path, monkeypatch, lambda *a, **k: None)
    assert it.estado == aud.NO_VERIFICABLE and "CASO-004" in it.evidencia


def test_x110_una_exportacion_de_un_caso_ajeno_a_fichas_jsonl_es_falta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    carpeta = tmp_path / "outputs" / "fichas_trazables"
    carpeta.mkdir(parents=True)
    (carpeta / "CASO-099.md").write_text("# otro caso\n", encoding="utf-8")
    it = _p02(tmp_path, monkeypatch, _vivo(["CASO-001", "CASO-002", "CASO-004"]))
    assert it.estado == aud.FALTA and "CASO-099" in it.evidencia


def test_x110_el_validador_real_se_corre_sobre_cada_ficha_de_fichas_jsonl() -> None:
    if not (RAIZ / CFG.auditoria.base_senales).is_file():
        pytest.skip("sin data/senales.duckdb en esta máquina")
    c = aud.Contexto(CFG, RAIZ)
    registros, problemas = aud._registros_fichas(c)
    assert registros and problemas == []
    exportados, _ = aud._textos_exportados(c)
    vivo = aud.reverificar_fichas(c, registros, exportados)
    assert set(vivo) == {r["id_caso"] for r in registros}
    estados = {r["id_caso"]: r.get("estado_revision") for r in registros}
    vigentes = {i: v for i, v in vivo.items() if estados[i] not in CFG.auditoria.estados_sin_trazabilidad}
    assert all(not v["fallos"] and v["citas"] for v in vigentes.values())          # lo que se entrega nunca cita algo que no existe
    for i, v in vivo.items():
        assert v["citas"], i
        if v["fallos"]:      # un caso descartado puede citar un grupo que una nueva agrupación ya no tiene: la auditoría lo declara, no lo esconde
            assert estados[i] in CFG.auditoria.estados_sin_trazabilidad, i
    item = aud.Contexto(CFG, RAIZ)
    aud.validador(item)
    p02 = next(i for i in item.items if i.id == "P-02")
    fallan = [i for i, v in vivo.items() if v["fallos"]]
    assert (p02.estado == aud.FALTA) == bool(fallan) and all(i in p02.evidencia for i in fallan)      # la auditoría los declara
    if not fallan:
        assert p02.estado == aud.PASS


def test_x110_el_validador_real_rechaza_una_ficha_alterada() -> None:
    if not (RAIZ / CFG.auditoria.base_senales).is_file():
        pytest.skip("sin data/senales.duckdb en esta máquina")
    c = aud.Contexto(CFG, RAIZ)
    registros, _ = aud._registros_fichas(c)
    alterado = json.loads(json.dumps(registros[0]))
    citado = alterado["ficha"]["respaldado"]
    afirmacion = next(x for k in ("reportes", "datos_oficiales", "contexto_oficial", "declaraciones", "eventos_oficiales") for x in citado.get(k, []) if x.get("citas"))
    afirmacion["citas"][0]["id"] = "NOT-0000000000"
    vivo = aud.reverificar_fichas(c, [alterado], {})
    assert vivo[alterado["id_caso"]]["fallos"]


# ---------------------------------------------------------------------------------------------- X111: .env.example


def _env(tmp_path: Path, texto: str) -> aud.Item:
    (tmp_path / CFG.auditoria.env_ejemplo).write_text(texto, encoding="utf-8")
    c = _contexto(tmp_path)
    aud.entregables(c)
    return next(i for i in c.items if i.id == "S10-03")


def test_x111_env_example_con_nombres_y_valores_vacios_pasa(tmp_path: Path) -> None:
    it = _env(tmp_path, "# comentario\nLLM_PROVIDER=\nDEEPSEEK_API_KEY=\nNOTION_TOKEN=\n")
    assert it.estado == aud.PASS and "3 variables" in it.evidencia


def test_x111_env_example_sin_variables_o_ausente_no_pasa(tmp_path: Path) -> None:
    assert _env(tmp_path, "# solo comentarios\n").estado == aud.FALTA
    (tmp_path / CFG.auditoria.env_ejemplo).unlink()
    c = _contexto(tmp_path)
    aud.entregables(c)
    assert next(i for i in c.items if i.id == "S10-03").estado == aud.FALTA


def test_x111_una_clave_con_formato_real_en_env_example_es_falta_y_no_se_imprime(tmp_path: Path) -> None:
    clave = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
    it = _env(tmp_path, f"LLM_PROVIDER=\nDEEPSEEK_API_KEY={clave}\n")
    assert it.estado == aud.FALTA and "DEEPSEEK_API_KEY" in it.evidencia and clave not in it.evidencia and clave not in aud.a_markdown([it], "x", "y")


def test_x111_cualquier_valor_en_una_variable_secreta_es_falta_aunque_no_parezca_clave(tmp_path: Path) -> None:
    assert _env(tmp_path, "NOTION_TOKEN=corto\n").estado == aud.FALTA
    assert _env(tmp_path, "OLLAMA_MODEL=qwen3.5:9b\nNOTION_TOKEN=\n").estado == aud.PASS      # una variable que no es secreta puede traer un valor por defecto


def test_x111_el_escaneo_de_secretos_ya_no_omite_env_example(tmp_path: Path) -> None:
    clave = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
    (tmp_path / CFG.auditoria.env_ejemplo).write_text(f"DEEPSEEK_API_KEY={clave}\n", encoding="utf-8")
    c = _contexto(tmp_path)
    aud.secretos(c)
    assert c.items[0].estado == aud.FALTA and CFG.auditoria.env_ejemplo in c.items[0].evidencia and clave not in c.items[0].evidencia


# ---------------------------------------------------------------------------------------------- X112: P-04, S5-04, S10-01, S10-10, P-05, S5-07


def _repo_git(ruta: Path) -> None:
    ruta.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=ruta, check=True)                                                    # noqa: S603, S607


def _commit(ruta: Path, mensaje: str) -> str:
    env = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "add", "-A"], cwd=ruta, check=True)                                                     # noqa: S603, S607
    subprocess.run(["git", *env, "commit", "-q", "-m", mensaje], cwd=ruta, check=True)                             # noqa: S603, S607
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ruta, check=True, capture_output=True, text=True).stdout.strip()   # noqa: S603, S607


def test_x112_p04_comprueba_git_ls_files_de_demo_duckdb(tmp_path: Path) -> None:
    _repo_git(tmp_path)
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    _commit(tmp_path, "base")
    c = _contexto(tmp_path)
    aud.restringido(c)
    assert c.items[0].estado == aud.PASS and "git ls-files" in c.items[0].evidencia
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "demo.duckdb").write_bytes(b"x")
    _commit(tmp_path, "versiona la demo")
    c = _contexto(tmp_path)
    aud.restringido(c)
    assert c.items[0].estado == aud.FALTA and "data/demo.duckdb" in c.items[0].evidencia


def test_x112_p04_detecta_rutas_restringidas_y_el_conjunto_oculto_versionados(tmp_path: Path) -> None:
    _repo_git(tmp_path)
    for rel in ("data/raw/rss_tvn/a.xml", "eval/benchmark_" + "reserv" + "ado.jsonl"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n", encoding="utf-8")
    _commit(tmp_path, "mal")
    c = _contexto(tmp_path)
    aud.restringido(c)
    assert c.items[0].estado == aud.FALTA and "rss_tvn" in c.items[0].evidencia and "reservado" in c.items[0].evidencia


def _catalogo(tmp_path: Path, fuentes: list[str], manifest: list[str], licencia: str = "CC") -> None:
    ruta = tmp_path / CFG.auditoria.catalogo
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[CFG.auditoria.columna_fuente_catalogo, "Licencia / condiciones"])
        w.writeheader()
        w.writerows({CFG.auditoria.columna_fuente_catalogo: n, "Licencia / condiciones": licencia} for n in fuentes)
    (tmp_path / CFG.auditoria.manifest).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / CFG.auditoria.manifest).write_text(json.dumps({"licencias": {k: {} for k in manifest}}), encoding="utf-8")


def _s504(tmp_path: Path) -> aud.Item:
    c = _contexto(tmp_path)
    aud.catalogo(c)
    return c.items[0]


def test_x112_s504_las_fuentes_salen_del_manifest(tmp_path: Path) -> None:
    claves = list(CFG.auditoria.nombres_fuentes_catalogo)
    nombres = list(CFG.auditoria.nombres_fuentes_catalogo.values())
    _catalogo(tmp_path, nombres, claves)
    assert _s504(tmp_path).estado == aud.PASS
    _catalogo(tmp_path, nombres, [*claves, "fuente_nueva"])                       # una fuente nueva en el manifest sin nombre en la configuración
    it = _s504(tmp_path)
    assert it.estado == aud.FALTA and "fuente_nueva" in it.evidencia
    _catalogo(tmp_path, nombres[:-1], claves)                                      # una fuente del manifest que el catálogo no lista
    assert _s504(tmp_path).estado == aud.FALTA
    _catalogo(tmp_path, nombres, claves, licencia="")                              # sin licencia
    assert _s504(tmp_path).estado == aud.FALTA
    _catalogo(tmp_path, nombres, [])                                               # un manifest sin fuentes no es un catálogo completo
    assert _s504(tmp_path).estado == aud.FALTA


def test_x112_s1001_exige_demo_verificacion_offline_y_guion(tmp_path: Path) -> None:
    d = CFG.auditoria.demo
    c = _contexto(tmp_path)
    aud.entregables(c)
    assert _por_id(c.items, "S10-01").estado == aud.FALTA
    for rel in (d.base, d.verificar_offline, d.guion):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    c = _contexto(tmp_path)
    aud.entregables(c)
    assert _por_id(c.items, "S10-01").estado == aud.PASS
    (tmp_path / d.guion).unlink()
    c = _contexto(tmp_path)
    aud.entregables(c)
    assert _por_id(c.items, "S10-01").estado == aud.FALTA


def test_x112_s1010_revisa_el_paquete_construido(tmp_path: Path) -> None:
    c = _contexto(tmp_path)
    aud.paquete_datos(c)
    assert _por_id(c.items, "S10-10").estado == aud.FALTA                          # sin paquete
    emp.construir(CFG, RAIZ, tmp_path / CFG.paquete.carpeta)
    c = _contexto(tmp_path)
    aud.paquete_datos(c)
    assert _por_id(c.items, "S10-10").estado == aud.PASS
    (tmp_path / CFG.paquete.carpeta / "snapshot" / "extra.txt").write_text("x\n", encoding="utf-8")
    c = _contexto(tmp_path)
    aud.paquete_datos(c)
    assert _por_id(c.items, "S10-10").estado == aud.FALTA


def test_x112_p05_los_juicios_provisionales_son_falta(tmp_path: Path) -> None:
    for juicio_humano, pagina, esperado in [(True, None, aud.PASS), (False, None, aud.FALTA), (True, f"# Métricas\n{CFG.auditoria.marca_provisional_metricas}\n", aud.FALTA)]:
        _traza(tmp_path, {"CASO-001": "GRP-a"})
        t = json.loads((tmp_path / CFG.auditoria.trazabilidad).read_text(encoding="utf-8"))
        t["juicio_humano"] = juicio_humano
        (tmp_path / CFG.auditoria.trazabilidad).write_text(json.dumps(t), encoding="utf-8")
        ruta = tmp_path / CFG.auditoria.pagina_metricas
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.unlink(missing_ok=True)
        if pagina:
            ruta.write_text(pagina, encoding="utf-8")
        c = _contexto(tmp_path)
        aud.provisionales(c)
        assert c.items[0].estado == esperado, (juicio_humano, pagina)


def test_x112_s507_una_pagina_de_metricas_de_un_commit_viejo_es_falta(tmp_path: Path) -> None:
    _repo_git(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "modulo.py").write_text("X = 1\n", encoding="utf-8")
    commit = _commit(tmp_path, "base")
    pagina = tmp_path / CFG.auditoria.pagina_metricas
    pagina.parent.mkdir(parents=True, exist_ok=True)
    pagina.write_text(f"# Métricas\nGenerada desde el commit `{commit}` con x\n", encoding="utf-8")
    c = _contexto(tmp_path)
    aud.metricas(c)
    assert c.items[0].estado == aud.PASS
    (tmp_path / "src" / "modulo.py").write_text("X = 2\n", encoding="utf-8")
    _commit(tmp_path, "cambia el código")
    c = _contexto(tmp_path)
    aud.metricas(c)
    assert c.items[0].estado == aud.FALTA and "cambiaron" in c.items[0].evidencia
    (tmp_path / CFG.auditoria.pagina_metricas).write_text("# Métricas\nGenerada desde el commit `0000000` con x\n", encoding="utf-8")
    c = _contexto(tmp_path)
    aud.metricas(c)
    assert c.items[0].estado == aud.FALTA and "no existe" in c.items[0].evidencia
