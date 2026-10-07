"""C-01 · Cinco fichas trazables: selección determinista por regla y comprobación de la trazabilidad contra los datos.

Sobre la base sintética de E1-10b (sin red ni LLM real). Cada comprobación tiene su caso en que falla: una comprobación que nunca falla no prueba nada.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import fichas_trazables as cli
from src import db, embeddings, exportar
from src.configuracion import ErrorDeConfiguracion, cargar_config, cargar_fichas_trazables, cargar_revision, validar_todo, ConfigFichasTrazables
from src.esquemas import RegistroFichasJsonl
from src.ficha import construir_ficha
from src.revision import Revisiones
from src.trazabilidad import REGLAS, Candidato, ErrorDeTrazabilidad, Resolutor, candidatos, informe, seleccionar, verificar_ficha
from tests import ficha_ayuda as h
from tests.motor_falso import MotorFalso, config_de_prueba

CFG = cargar_fichas_trazables()
MARCA = cargar_revision().textos.marca_provisional


@pytest.fixture(scope="module")
def emb(tmp_path_factory):
    return embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path_factory.mktemp("emb"))


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch, emb):
    monkeypatch.setattr("src.ficha._embeddings", lambda: emb)


def _indicadores(grupo_anios: list[int]) -> list[dict]:
    """Las filas de ``indicadores`` que citan los vínculos de G_COMPLETO (PAN y COL 2024, y la tendencia)."""
    filas = [("PAN", 2024, 0.69322), ("COL", 2024, 6.6), *(("PAN", a, a / 1000) for a in grupo_anios if a != 2024)]
    return [{"id_indicador": f"IND-{p}-FP.CPI.TOTL.ZG-{a}", "pais_iso3": p, "indicador_id": "FP.CPI.TOTL.ZG", "anio": a, "valor": v, "unidad": "% anual",
             "fuente_url": "https://api.worldbank.org/v2/country/x/indicator/FP.CPI.TOTL.ZG", "fecha_extraccion": "2026-10-06T00:00:00Z", "licencia": "CC BY 4.0"} for p, a, v in filas]


@pytest.fixture
def base(tmp_path, emb) -> Path:
    ruta = h.construir(tmp_path / "senales.duckdb", emb)
    con = db.conectar(ruta)
    db.insertar(con, "indicadores", _indicadores([2022, 2023, 2024]))
    db.insertar(con, "sismos", [{"id": "SIS-us7000test", "magnitude": 5.1, "time": "2026-10-06T07:30:00Z", "updated": "2026-10-06T08:00:00Z", "longitude": -82.9, "latitude": 8.2,
                                 "depth": 10.0, "place": "12 km S of Puerto Armuelles, Panama", "status": "automatic", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test"}])
    con.close()
    return ruta


def _ejecutar(base: Path, grupo: str, cambios: str | None = None, cfg: ConfigFichasTrazables = CFG, **k):
    """Arma la ficha del grupo, aplica ``cambios`` (SQL) a los datos DESPUÉS de armarla y la comprueba contra lo que quedó."""
    con = db.conectar(base)
    try:
        ficha = construir_ficha(grupo, "editorial", con)
        if cambios:
            con.execute(cambios)
        return verificar_ficha(ficha, Resolutor(con, cfg), cfg, **k)
    finally:
        con.close()


def _falla(r, regla: str) -> bool:
    return any(u.regla == regla and not u.ok for u in r.unidades)


# ------------------------------------------------------------------ configuración y selección


def test_la_configuracion_valida_y_exige_al_menos_una_ficha_insuficiente() -> None:
    assert "fichas_trazables" in validar_todo()
    datos = CFG.model_dump()
    datos["seleccion"]["cupos"].update(suficiente=3, parcial=2, insuficiente=0)
    with pytest.raises(ValueError, match="insuficiente"):
        ConfigFichasTrazables.model_validate(datos)


def test_la_configuracion_rechaza_un_registro_sin_url_ni_id() -> None:
    datos = CFG.model_dump()
    datos["registros"][0]["columna_url"] = None
    with pytest.raises(ValueError, match="columna_url"):
        ConfigFichasTrazables.model_validate(datos)


def _ranking() -> list[Candidato]:
    estados = ["insuficiente"] * 4 + ["parcial", "suficiente", "insuficiente", "parcial", "parcial", "suficiente", "suficiente"]
    return [Candidato(f"GRP-{i:02d}", i, 100 - i, e) for i, e in enumerate(estados, start=1)]


def test_la_seleccion_toma_los_cupos_por_estado_en_orden_de_ranking() -> None:
    elegidos = seleccionar(_ranking(), CFG)
    assert [(c.posicion, c.estado) for c in elegidos] == [(1, "insuficiente"), (5, "parcial"), (6, "suficiente"), (8, "parcial"), (10, "suficiente")]


def test_la_seleccion_es_determinista_e_independiente_del_orden_de_entrada() -> None:
    ranking = _ranking()
    esperado = seleccionar(ranking, CFG)
    for semilla in range(5):
        barajado = random.Random(semilla).sample(ranking, len(ranking))
        assert seleccionar(barajado, CFG) == esperado
    assert seleccionar(ranking, CFG) == esperado


def test_si_un_estado_no_alcanza_su_cupo_se_completa_con_el_ranking() -> None:
    solo_insuficientes = [Candidato(f"GRP-{i}", i, 90 - i, "insuficiente") for i in range(1, 9)]
    elegidos = seleccionar(solo_insuficientes, CFG)
    assert [c.posicion for c in elegidos] == [1, 2, 3, 4, 5] and len(elegidos) == CFG.seleccion.minimo_total


def test_sin_ninguna_ficha_insuficiente_la_seleccion_falla_con_un_mensaje() -> None:
    ranking = [Candidato(f"GRP-{i}", i, 90 - i, "parcial") for i in range(1, 9)]
    with pytest.raises(ErrorDeTrazabilidad, match="insuficiente"):
        seleccionar(ranking, CFG)


def test_con_menos_fichas_que_el_minimo_falla() -> None:
    with pytest.raises(ErrorDeTrazabilidad, match="solo hay"):
        seleccionar(_ranking()[:3], CFG)


def test_los_candidatos_salen_del_ranking_oficial_y_exigen_la_modalidad(base) -> None:
    con = db.conectar(base, solo_lectura=True)
    try:
        c = candidatos(con, "editorial")
        assert [x.posicion for x in c] == sorted(x.posicion for x in c) and {x.estado for x in c} <= {"suficiente", "parcial", "insuficiente"}
        with pytest.raises(db.ModalidadDistinta):
            candidatos(con, "banca")
    finally:
        con.close()


# ------------------------------------------------------------------ una ficha buena pasa todo


@pytest.mark.parametrize("grupo", [h.G_COMPLETO, h.G_SISMO, h.G_SOLO, h.G_CIFRAS, h.G_INYECCION])
def test_una_ficha_real_pasa_todas_las_comprobaciones_y_cita_id_y_campo(base, grupo) -> None:
    r = _ejecutar(base, grupo)
    assert r.fallos() == []
    assert r.trazas and all(t.existe and t.campo and t.valor for t in r.trazas)
    assert r.conteo("cinco_partes") == (1, 1) and r.conteo("leyenda_de_alcance") == (1, 1) and r.conteo("marca_borrador") == (1, 1)


def test_las_citas_oficiales_traen_su_url_y_las_de_titular_su_declaracion_literal(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO)
    oficiales = [t for t in r.trazas if t.id.startswith("IND-")]
    assert oficiales and all(t.url and t.url.startswith("https://") for t in oficiales)
    assert r.conteo("declaracion_literal")[1] == 3 and r.conteo("url_presente")[1] >= len(oficiales) + 3


# ------------------------------------------------------------------ cada comprobación falla cuando debe


def test_una_cita_a_un_id_que_no_esta_en_los_datos_falla(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO, "DELETE FROM indicadores WHERE id_indicador = 'IND-COL-FP.CPI.TOTL.ZG-2024'")
    assert _falla(r, "cita_con_id_en_datos") and _falla(r, "cita_con_campo_y_valor")


def test_un_valor_nulo_en_los_datos_no_respalda_la_cita(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO, "UPDATE indicadores SET valor = NULL WHERE id_indicador = 'IND-PAN-FP.CPI.TOTL.ZG-2024'")
    assert _falla(r, "cita_con_campo_y_valor") and not _falla(r, "cita_con_id_en_datos")


def test_un_dato_oficial_sin_url_falla(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO, "UPDATE indicadores SET fuente_url = '' WHERE id_indicador = 'IND-PAN-FP.CPI.TOTL.ZG-2024'")
    assert _falla(r, "url_presente")


def test_un_evento_oficial_sin_url_falla(base) -> None:
    r = _ejecutar(base, h.G_SISMO, "UPDATE sismos SET url = NULL")
    assert _falla(r, "url_presente")


def test_la_url_del_titular_debe_ser_la_de_los_datos(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO, "UPDATE noticias SET url = 'https://otra.example/x' WHERE id_noticia = 'NOT-c000000001'")
    assert _falla(r, "url_presente")


def test_una_declaracion_que_ya_no_es_literal_del_campo_citado_falla(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO, "UPDATE noticias SET titulo_limpio = 'Otro titular distinto' WHERE id_noticia = 'NOT-c000000001'")
    assert _falla(r, "declaracion_literal")


def test_una_cifra_de_conteo_que_difiere_de_los_datos_falla(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO, "UPDATE grupos SET n_titulares = 7 WHERE id_grupo = 'GRP-completo'")
    assert _falla(r, "cifra_de_conteo_coincide")


def test_la_descripcion_del_rss_en_una_salida_falla_y_en_ninguna_pasa(base) -> None:
    descripcion = "Texto interno del RSS que nunca debe republicarse en una ficha"
    actualizar = f"UPDATE noticias SET descripcion = '{descripcion}' WHERE id_noticia = 'NOT-c000000001'"
    assert not _falla(_ejecutar(base, h.G_COMPLETO, actualizar), "sin_descripcion_rss")
    fuga = _ejecutar(base, h.G_COMPLETO, actualizar, textos_extra=[f"Resumen: {descripcion}"])
    assert _falla(fuga, "sin_descripcion_rss")


def test_una_descripcion_corta_no_se_busca(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO, "UPDATE noticias SET descripcion = 'Panamá' WHERE id_noticia = 'NOT-c000000001'", textos_extra=["Panamá"])
    assert not _falla(r, "sin_descripcion_rss")


def test_un_nombre_de_autor_como_agencia_falla(base) -> None:
    con = db.conectar(base)
    con.execute("UPDATE noticias SET agencia = 'Juan Pérez' WHERE id_noticia = 'NOT-c000000001'")
    con.close()
    assert _falla(_ejecutar(base, h.G_COMPLETO), "sin_nombres_de_autor")


def test_una_clave_de_autor_en_la_ficha_falla(base) -> None:
    cfg = CFG.model_copy(update={"claves_de_autor": ["agencia"]})        # «agencia» sí es una clave de la ficha: la comprobación la detecta
    assert _falla(_ejecutar(base, h.G_COMPLETO, cfg=cfg), "sin_nombres_de_autor")


def test_una_leyenda_de_alcance_inventada_falla(base) -> None:
    con = db.conectar(base)
    try:
        ficha = construir_ficha(h.G_COMPLETO, "editorial", con)
        mala = ficha.model_copy(update={"alcance": "basado en la lectura del artículo completo"})
        r = verificar_ficha(mala, Resolutor(con, CFG), CFG)
    finally:
        con.close()
    assert _falla(r, "leyenda_de_alcance")


def test_un_texto_sin_la_marca_de_borrador_falla(base) -> None:
    con = db.conectar(base)
    try:
        ficha = construir_ficha(h.G_COMPLETO, "editorial", con)
        r = verificar_ficha(ficha.model_copy(update={"marca_borrador": "APROBADO"}), Resolutor(con, CFG), CFG)
    finally:
        con.close()
    assert _falla(r, "marca_borrador")


# ------------------------------------------------------------------ informe: n e IC 95 %


def test_el_informe_cuenta_n_y_pone_ic_de_wilson_a_cada_proporcion(base) -> None:
    ok = _ejecutar(base, h.G_COMPLETO)
    mal = _ejecutar(base, h.G_SISMO, "UPDATE sismos SET url = NULL")
    inf = informe([ok, mal], CFG)
    assert inf["n_fichas"] == 2 and inf["todo_ok"] is False
    url = inf["por_regla"]["url_presente"]
    assert url["n"] == ok.conteo("url_presente")[1] + mal.conteo("url_presente")[1] and url["ok"] == url["n"] - 1
    lo, hi = url["ic95"]
    assert 0 < lo < url["proporcion"] < hi <= 1 and "Wilson" in url["metodo_ic"]
    assert set(inf["por_regla"]) == set(REGLAS) and inf["por_regla"]["contrato_fichas_jsonl"]["n"] == 0     # sin CASO- no aplica
    assert any(f["fallos"] for f in inf["fichas"]) and inf["fichas"][0]["citas"]


def test_un_informe_sin_fallos_es_todo_ok(base) -> None:
    assert informe([_ejecutar(base, h.G_COMPLETO)], CFG)["todo_ok"] is True


# ------------------------------------------------------------------ con CASO-: revisión provisional visible y contrato


@pytest.fixture
def rev(base, tmp_path) -> Revisiones:
    t = {"n": 0}

    def ahora() -> datetime:
        t["n"] += 1
        return datetime(2026, 10, 7, 14, 0, tzinfo=UTC) + timedelta(minutes=t["n"])

    return Revisiones(tmp_path / "revision.duckdb", base, ahora=ahora, huellas=[tmp_path / "notion", tmp_path / "fichas.jsonl"])


def _revisar(rev: Revisiones, base: Path, grupo: str, estado: str, tmp_path: Path):
    c = Candidato(grupo, 1, 80.0, estado)
    con = db.conectar(base, solo_lectura=True)
    try:
        ficha = construir_ficha(grupo, "editorial", con)
    finally:
        con.close()
    id_caso = cli.revisar_provisionalmente(rev, c, ficha, CFG, base)
    e = exportar.exportar_caso(rev, id_caso, tmp_path / "notion", tmp_path / "fichas.jsonl")
    return id_caso, e, ficha


def test_la_revision_provisional_aprueba_o_pide_evidencia_segun_el_estado_y_se_ve_rotulada(rev, base, tmp_path) -> None:
    id_a, e, ficha = _revisar(rev, base, h.G_COMPLETO, "suficiente", tmp_path)
    assert rev.estado(id_a) == "aprobado como borrador" and rev.vigente_provisional(id_a)
    id_b, _, _ = _revisar(rev, base, h.G_CIFRAS, "insuficiente", tmp_path)
    assert rev.estado(id_b) == "requiere evidencia" and rev.vigente_provisional(id_b)
    con = db.conectar(base, solo_lectura=True)
    try:
        r = verificar_ficha(rev.ficha_revisada(id_a), Resolutor(con, CFG), CFG, id_caso=id_a, estado_revision=rev.estado(id_a), textos_extra=[e.markdown, *e.fila.values()],
                            fila_notion=e.fila, revision_provisional=True, marca_provisional=MARCA)
    finally:
        con.close()
    assert r.fallos() == [] and r.conteo("contrato_fichas_jsonl") == (1, 1) and r.conteo("revision_provisional_visible") == (1, 1)
    linea = json.loads((tmp_path / "fichas.jsonl").read_text().splitlines()[0])
    RegistroFichasJsonl.model_validate(linea)
    assert linea["revision_provisional"] is True and linea["borrador"] is True


def test_la_revision_provisional_es_idempotente_y_no_toca_un_caso_que_ya_avanzo(rev, base, tmp_path) -> None:
    id_1, _, _ = _revisar(rev, base, h.G_COMPLETO, "suficiente", tmp_path)
    n = len(rev.historial(id_1))
    id_2, _, _ = _revisar(rev, base, h.G_COMPLETO, "suficiente", tmp_path)
    assert id_1 == id_2 and len(rev.historial(id_1)) == n        # no agrega filas ni abre otro caso


def test_si_la_marca_provisional_no_esta_en_la_exportacion_la_comprobacion_falla(rev, base, tmp_path) -> None:
    id_a, e, _ = _revisar(rev, base, h.G_COMPLETO, "suficiente", tmp_path)
    con = db.conectar(base, solo_lectura=True)
    try:
        r = verificar_ficha(rev.ficha_revisada(id_a), Resolutor(con, CFG), CFG, id_caso=id_a, estado_revision=rev.estado(id_a), textos_extra=["sin marca"],
                            fila_notion={"Revisor": "Asistente"}, revision_provisional=True, marca_provisional=MARCA)
    finally:
        con.close()
    assert _falla(r, "revision_provisional_visible")


def test_el_comando_sin_casos_escribe_el_informe_y_no_abre_casos(base, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "cargar_fichas_trazables", lambda: CFG.model_copy(update={"seleccion": CFG.seleccion.model_copy(update={"cupos": {"suficiente": 1, "parcial": 1, "insuficiente": 3}, "minimo_total": 5})}))
    salida = tmp_path / "fichas_trazables"
    code = cli.principal(["--base", str(base), "--salida", str(salida)])
    inf = json.loads((salida / "trazabilidad.json").read_text())
    assert code == (0 if inf["todo_ok"] else 1) and inf["n_fichas"] == 5 and inf["con_casos"] is False and inf["juicio_humano"] is False and inf["borrador"] is True
    assert (salida / "indice.md").exists() and len(list(salida.glob("GRP-*.md"))) == 5
    assert "REVISIÓN PROVISIONAL" in (salida / "indice.md").read_text()
