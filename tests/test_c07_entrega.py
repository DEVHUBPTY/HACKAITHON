"""C-07: el paquete de datos no lleva material prohibido y la auditoría final da el estado correcto a cada ítem."""

from __future__ import annotations

import csv
import json
import shutil
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
    prohibidos = {c.lower() for c in CFG.paquete.prohibido.campos}
    for f in carpeta.rglob("*"):
        if f.suffix in CFG.paquete.prohibido.extensiones_estructuradas:
            assert not (emp.campos_de(f) & prohibidos), f
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
