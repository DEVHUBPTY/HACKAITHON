"""C-01 · Cinco fichas trazables: selección determinista por regla y comprobación de la trazabilidad contra los datos.

Sobre la base sintética de E1-10b (sin red ni LLM real). Cada comprobación tiene su caso en que falla: una comprobación que nunca falla no prueba nada.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import fichas_trazables as cli
from src import db, embeddings, exportar
from src.configuracion import RAIZ, ErrorDeConfiguracion, cargar_config, cargar_fichas_trazables, cargar_revision, validar_todo, ConfigFichasTrazables
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


def _modificada(**cambios):
    """Una copia validada de la configuración con ``seleccion`` cambiada (para probar lo que rechaza el modelo)."""
    datos = CFG.model_dump()
    datos["seleccion"].update(cambios)
    return ConfigFichasTrazables.model_validate(datos)


def test_la_configuracion_valida_y_exige_al_menos_una_ficha_insuficiente() -> None:
    assert "fichas_trazables" in validar_todo()
    with pytest.raises(ValueError, match="insuficiente"):
        _modificada(minimo_insuficiente=0)


def test_la_configuracion_tiene_un_caso_de_uso_por_ficha_y_cu05_es_un_grupo_fijo_de_banca() -> None:
    cus = {cu.id: cu for cu in CFG.seleccion.casos_de_uso}
    assert list(cus) == ["CU-01", "CU-02", "CU-03", "CU-04", "CU-05"] and CFG.seleccion.minimo_total == 5
    assert cus["CU-05"].grupo == "GRP-da35c3dead" and cus["CU-05"].modalidad == "banca" and not cus["CU-05"].criterios


def test_la_configuracion_rechaza_ids_repetidos_menos_casos_que_el_minimo_y_un_caso_de_uso_ambiguo() -> None:
    cus = CFG.model_dump()["seleccion"]["casos_de_uso"]
    with pytest.raises(ValueError, match="repetido"):
        _modificada(casos_de_uso=[*cus, cus[0]])
    with pytest.raises(ValueError, match="menos casos de uso"):
        _modificada(casos_de_uso=cus[:4])
    with pytest.raises(ValueError, match="grupo fijo"):
        _modificada(casos_de_uso=[*cus[:4], {**cus[4], "criterios": [{}]}])
    with pytest.raises(ValueError, match="criterios"):
        _modificada(casos_de_uso=[*cus[:4], {"id": "CU-05", "pregunta": "x", "criterios": []}])


def test_la_garantia_exige_criterios_de_evidencia_insuficiente_y_un_caso_de_uso_con_criterios() -> None:
    with pytest.raises(ValueError, match="insuficiente"):
        _modificada(garantia_insuficiente={"caso_de_uso": "CU-04", "criterios": [{"estado": "parcial"}]})
    with pytest.raises(ValueError, match="criterios"):
        _modificada(garantia_insuficiente={"caso_de_uso": "CU-05", "criterios": [{"estado": "insuficiente"}]})


def test_el_motivo_de_reemplazo_debe_estar_en_los_motivos_de_descarte(tmp_path) -> None:
    carpeta = tmp_path / "config"
    shutil.copytree(RAIZ / "config", carpeta)
    ruta = carpeta / "fichas_trazables.yaml"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace(CFG.reemplazo.motivo, "un motivo que no existe", 1), encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match="motivos_descarte"):
        validar_todo(carpeta)


def test_la_configuracion_rechaza_un_registro_sin_url_ni_id() -> None:
    datos = CFG.model_dump()
    datos["registros"][0]["columna_url"] = None
    with pytest.raises(ValueError, match="columna_url"):
        ConfigFichasTrazables.model_validate(datos)


def _c(i: int, estado: str = "insuficiente", tema: str = "servicios_publicos", nt: int = 1, npr: int = 1, oficial: bool = False, contra: int = 0, vacios: tuple[str, ...] = (), ruido: bool = False) -> Candidato:
    return Candidato(f"GRP-{i:02d}", i, 100 - i, estado, tema, nt, npr, oficial, contra, vacios, ruido)


def _ranking() -> list[Candidato]:
    """Un ranking donde cada caso de uso tiene un candidato anterior que NO cumple y uno posterior que sí (el criterio, no la posición, decide)."""
    return [
        _c(1),                                                                           # CU-01
        _c(2, tema="economia"),                                                          # economía sin dato oficial: no es CU-02
        _c(3, "parcial", "economia", oficial=True),                                      # CU-02
        _c(4, nt=2, npr=1),                                                              # un par del mismo medio: solo respaldo de CU-03 (pide >= 3 titulares)
        _c(5, "suficiente", nt=4, npr=2),                                                # CU-03
        _c(6, vacios=("sin_dato_oficial",)),                                             # insuficiente sin cifras: no es CU-04
        _c(7, vacios=("procedencias_insuficientes", "cifras_sin_dato_oficial")),         # CU-04 por respaldo (no hay contradicción)
        _c(8, "parcial", vacios=("cifras_sin_dato_oficial",)),
    ]


def _por_cu(elegidas) -> dict[str, object]:
    return {e.caso_de_uso: e for e in elegidas}


def test_la_seleccion_elige_una_ficha_por_caso_de_uso_con_su_regla() -> None:
    e = _por_cu(seleccionar(_ranking(), CFG))
    assert {cu: x.id_grupo for cu, x in e.items()} == {"CU-01": "GRP-01", "CU-02": "GRP-03", "CU-03": "GRP-05", "CU-04": "GRP-07", "CU-05": "GRP-da35c3dead"}
    assert e["CU-01"].criterio == 0 and e["CU-02"].criterio == 0 and e["CU-03"].criterio == 0 and not e["CU-03"].es_respaldo
    assert e["CU-04"].criterio == 1 and e["CU-04"].es_respaldo                       # sin contradicción abierta: el respaldo declarado
    assert e["CU-05"].candidato is None and e["CU-05"].modalidad == "banca"          # el grupo fijo no sale del ranking de esta base


def test_cu01_es_siempre_el_primero_del_ranking() -> None:
    r = _ranking()
    assert seleccionar(r, CFG)[0].id_grupo == min(r, key=lambda c: c.posicion).id_grupo


def test_cu02_pide_tema_economico_y_dato_oficial_a_la_vez() -> None:
    r = [_c(1), _c(2, tema="economia"), _c(3, tema="turismo", oficial=True), _c(4, tema="economia", oficial=True), _c(5, tema="economia", oficial=True), _c(6, "suficiente", nt=4, npr=2), _c(7, vacios=("cifras_sin_dato_oficial",))]
    assert _por_cu(seleccionar(r, CFG))["CU-02"].id_grupo == "GRP-04"


def test_cu03_es_la_replicacion_de_una_agencia_con_varios_titulares_y_declara_el_respaldo_si_solo_hay_un_par() -> None:
    solo_par = [_c(1), _c(2, tema="economia", oficial=True), _c(3, nt=2, npr=1), _c(4, vacios=("cifras_sin_dato_oficial",))]
    par = _por_cu(seleccionar(solo_par, CFG))["CU-03"]
    assert par.id_grupo == "GRP-03" and par.criterio == 1 and par.es_respaldo
    replica = _por_cu(seleccionar([*solo_par, _c(9, nt=20, npr=1)], CFG))["CU-03"]
    assert replica.id_grupo == "GRP-09" and replica.criterio == 0 and not replica.es_respaldo     # 20 titulares, 1 procedencia: no hace falta corroboración (PDF sección 4)
    uno_por_procedencia = _por_cu(seleccionar([*solo_par, _c(9, "suficiente", nt=3, npr=3)], CFG))["CU-03"]
    assert uno_por_procedencia.id_grupo == "GRP-03"                                                 # un titular por procedencia no es repetición


def test_cu03_exige_un_tema_del_reto_y_sin_ruido_aunque_el_grupo_calce_en_lo_demas() -> None:
    base = [_c(1), _c(2, tema="economia", oficial=True), _c(4, vacios=("cifras_sin_dato_oficial",))]
    sin_tema = _c(3, "suficiente", tema="sin_tema", nt=12, npr=3)
    ruidoso = _c(5, tema="turismo", nt=9, npr=1, ruido=True)
    valido = _c(8, tema="eventos_naturales", nt=20, npr=1)
    e = _por_cu(seleccionar([*base, sin_tema, ruidoso, valido], CFG))["CU-03"]
    assert e.id_grupo == "GRP-08" and e.criterio == 0
    with pytest.raises(ErrorDeTrazabilidad, match="CU-03"):
        seleccionar([*base, sin_tema, ruidoso], CFG)


def test_cu04_prefiere_la_contradiccion_abierta_sobre_la_cifra_sin_dato_oficial() -> None:
    r = [*_ranking(), _c(9, "parcial", contra=1)]
    e = _por_cu(seleccionar(r, CFG))["CU-04"]
    assert e.id_grupo == "GRP-09" and e.criterio == 0 and not e.es_respaldo


def test_un_grupo_que_calza_en_dos_casos_de_uso_va_al_primero_y_el_siguiente_ocupa_el_otro() -> None:
    r = [_c(1), _c(2, "parcial", "economia", nt=3, npr=2, oficial=True), _c(3, "suficiente", nt=4, npr=2), _c(4, vacios=("cifras_sin_dato_oficial",))]
    e = _por_cu(seleccionar(r, CFG))
    assert e["CU-02"].id_grupo == "GRP-02" and e["CU-03"].id_grupo == "GRP-03"      # GRP-02 también calzaba en CU-03; CU-02 va antes
    grupos = [x.id_grupo for x in e.values()]
    assert len(set(grupos)) == len(grupos) == 5


def test_el_grupo_fijo_de_cu05_se_reserva_y_no_lo_toma_otro_caso_de_uso() -> None:
    fijo = next(cu.grupo for cu in CFG.seleccion.casos_de_uso if cu.grupo)
    r = [Candidato(fijo, 1, 99, "suficiente", "economia", 3, 2, True), *[Candidato(x.id_grupo, x.posicion + 1, x.puntaje, x.estado, x.tema, x.n_titulares, x.n_procedencias, x.con_dato_oficial, x.contradicciones_abiertas, x.vacios) for x in _ranking()]]
    e = seleccionar(r, CFG)
    assert [x.id_grupo for x in e].count(fijo) == 1 and _por_cu(e)["CU-01"].id_grupo != fijo


def test_la_seleccion_es_determinista_e_independiente_del_orden_de_entrada() -> None:
    ranking = _ranking()
    esperado = seleccionar(ranking, CFG)
    for semilla in range(5):
        barajado = random.Random(semilla).sample(ranking, len(ranking))
        assert seleccionar(barajado, CFG) == esperado
    assert seleccionar(ranking, CFG) == esperado


def test_un_caso_de_uso_sin_ningun_grupo_falla_con_su_nombre_y_no_inventa_uno() -> None:
    sin_economia = [c for c in _ranking() if c.tema != "economia"]
    with pytest.raises(ErrorDeTrazabilidad, match="CU-02.*no se inventa"):
        seleccionar(sin_economia, CFG)


def test_si_ninguna_ficha_es_insuficiente_la_garantia_vuelve_a_elegir_cu04_con_una_insuficiente() -> None:
    r = [_c(1, "parcial"), _c(2, "parcial", "economia", oficial=True), _c(3, "suficiente", nt=4, npr=2), _c(4, "parcial", contra=1), _c(5, vacios=("cifras_sin_dato_oficial",))]
    e = _por_cu(seleccionar(r, CFG))
    assert e["CU-04"].id_grupo == "GRP-05" and e["CU-04"].garantia and e["CU-04"].es_respaldo     # la contradicción era parcial: se cambia por la insuficiente
    assert sum(x.candidato is not None and x.candidato.estado == "insuficiente" for x in e.values()) >= CFG.seleccion.minimo_insuficiente


def test_sin_ninguna_ficha_insuficiente_en_el_ranking_la_seleccion_falla_con_un_mensaje() -> None:
    ranking = [_c(1, "parcial"), _c(2, "parcial", "economia", oficial=True), _c(3, "suficiente", nt=4, npr=2), _c(4, "parcial", contra=1)]
    with pytest.raises(ErrorDeTrazabilidad, match="insuficiente"):
        seleccionar(ranking, CFG)


def test_los_candidatos_salen_del_ranking_oficial_y_exigen_la_modalidad(base) -> None:
    con = db.conectar(base, solo_lectura=True)
    try:
        c = candidatos(con, "editorial")
        assert [x.posicion for x in c] == sorted(x.posicion for x in c) and {x.estado for x in c} <= {"suficiente", "parcial", "insuficiente"}
        completo = next(x for x in c if x.id_grupo == h.G_COMPLETO)
        assert completo.tema == "economia" and completo.n_titulares == 3 and completo.n_procedencias == 3 and completo.con_dato_oficial
        assert all(x.contradicciones_abiertas >= 0 for x in c) and any(x.vacios for x in c)
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


def test_una_cifra_oficial_de_un_indicador_que_difiere_del_dato_falla_y_la_que_coincide_al_redondeo_pasa(base) -> None:
    ok = _ejecutar(base, h.G_COMPLETO)
    assert ok.conteo("cifra_oficial_coincide")[1] >= 2 and not _falla(ok, "cifra_oficial_coincide")        # 0.69322 se muestra como 0.69
    r = _ejecutar(base, h.G_COMPLETO, "UPDATE indicadores SET valor = 5.0 WHERE id_indicador = 'IND-PAN-FP.CPI.TOTL.ZG-2024'")
    assert _falla(r, "cifra_oficial_coincide") and "IND-PAN-FP.CPI.TOTL.ZG-2024" in next(u.detalle for u in r.fallos() if u.regla == "cifra_oficial_coincide")
    cerca = _ejecutar(base, h.G_COMPLETO, "UPDATE indicadores SET valor = 0.6949 WHERE id_indicador = 'IND-PAN-FP.CPI.TOTL.ZG-2024'")
    assert not _falla(cerca, "cifra_oficial_coincide")                                                      # 0.6949 y 0.69322 se muestran igual (2 decimales)
    lejos = _ejecutar(base, h.G_COMPLETO, "UPDATE indicadores SET valor = 0.70 WHERE id_indicador = 'IND-PAN-FP.CPI.TOTL.ZG-2024'")
    assert _falla(lejos, "cifra_oficial_coincide")                                                          # otro valor al redondeo mostrado


def test_la_magnitud_de_un_sismo_que_difiere_del_dato_falla(base) -> None:
    assert _ejecutar(base, h.G_SISMO).conteo("cifra_oficial_coincide")[1] == 1
    r = _ejecutar(base, h.G_SISMO, "UPDATE sismos SET magnitude = 7.9")
    assert _falla(r, "cifra_oficial_coincide")


def test_una_cifra_de_la_sbp_se_compara_con_sus_decimales_propios() -> None:
    from src.configuracion import cargar_verificacion
    from src.trazabilidad import Registro, _cifra_oficial
    regla = next(r for r in CFG.registros if r.prefijo == "SBP-")
    reg = Registro("SBP-MOROSIDAD-SISTEMA-2024-01", {"periodo": "2024-01", "valor": "0.01741113516302623"}, "https://x.example")
    pres = cargar_verificacion().presentacion

    def comprobar(texto: str, valor: str = "0.01741113516302623"):
        return _cifra_oficial(reg.id, valor, texto, reg, regla.cifra, CFG, pres)

    assert comprobar("SBP · Saldo moroso, período 2024-01: 0.0174 proporción; informe «x»; página: 1").ok
    assert not comprobar("SBP · Saldo moroso, período 2024-01: 0.0199 proporción; informe «x»; página: 1").ok
    assert not comprobar("SBP · Saldo moroso, período 2024-01: 0.0174 proporción", valor="0.5").ok           # el dato cambió
    assert not comprobar("SBP · Saldo moroso, período 2024-02: 0.0174 proporción").ok                         # la ficha no muestra la cifra de ESTE período


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


# ------------------------------------------------------------------ reemplazo de casos de corridas anteriores (D-118)


def _abrir_como_c01(rev: Revisiones, base: Path, grupo: str, estado: str, tmp_path: Path) -> str:
    return _revisar(rev, base, grupo, estado, tmp_path)[0]


def test_los_casos_que_c01_abrio_y_ya_no_elige_se_reabren_y_se_descartan_con_el_motivo_y_se_conservan(rev, base, tmp_path) -> None:
    aprobado = _abrir_como_c01(rev, base, h.G_COMPLETO, "suficiente", tmp_path)
    pide = _abrir_como_c01(rev, base, h.G_CIFRAS, "insuficiente", tmp_path)
    sigue = _abrir_como_c01(rev, base, h.G_SOLO, "parcial", tmp_path)
    retirados = cli.retirar_reemplazadas(rev, {(h.G_SOLO, "editorial")}, CFG)
    assert sorted(retirados) == sorted([aprobado, pide])
    for id_caso in retirados:
        assert rev.estado(id_caso) == "descartado" and rev.vigente_provisional(id_caso)
        ultima = rev.historial(id_caso)[-1]
        assert ultima.accion == "descartar" and ultima.motivo == CFG.reemplazo.motivo and ultima.comentario == CFG.reemplazo.comentario
    assert [f.accion for f in rev.historial(aprobado)] == ["abrir", "aceptar", "reabrir", "descartar"]    # el aprobado se reabre antes; nada se borra
    assert [f.accion for f in rev.historial(pide)] == ["abrir", "pedir_evidencia", "descartar"]
    assert rev.estado(sigue) == "aprobado como borrador" and len(rev.casos()) == 3                          # el que sigue elegido no se toca
    assert cli.retirar_reemplazadas(rev, {(h.G_SOLO, "editorial")}, CFG) == []                              # idempotente


def test_un_caso_con_una_fila_de_una_persona_o_que_no_abrio_c01_no_se_descarta(rev, base, tmp_path) -> None:
    de_persona = _abrir_como_c01(rev, base, h.G_COMPLETO, "suficiente", tmp_path)
    rev.reabrir(de_persona, "David Fen", "una persona lo retoma")
    rev.aceptar(de_persona, "David Fen")                       # ya no es la fila provisional la vigente
    ajeno = rev.abrir(h.G_CIFRAS, "editorial", "David Fen").id_caso     # lo abrió una persona, no esta tarea
    assert cli.retirar_reemplazadas(rev, set(), CFG) == []
    assert rev.estado(de_persona) == "aprobado como borrador" and rev.estado(ajeno) == "en revisión"


def test_un_grupo_descartado_por_reemplazo_que_vuelve_a_ser_elegido_se_reabre(rev, base, tmp_path) -> None:
    id_caso = _abrir_como_c01(rev, base, h.G_CIFRAS, "insuficiente", tmp_path)
    cli.retirar_reemplazadas(rev, set(), CFG)
    assert rev.estado(id_caso) == "descartado"
    volver, _, _ = _revisar(rev, base, h.G_CIFRAS, "insuficiente", tmp_path)
    assert volver == id_caso and rev.estado(id_caso) == "requiere evidencia"       # el mismo CASO-, no uno nuevo (D-63)


# ------------------------------------------------------------------ el comando de punta a punta (base sintética)


def _cfg_de_prueba() -> ConfigFichasTrazables:
    """Cinco casos de uso sobre la base sintética: sus criterios calzan con lo que tiene (CU-05 es el grupo completo, reutilizado de banca)."""
    datos = CFG.model_dump()
    datos["seleccion"]["casos_de_uso"] = [
        {"id": "CU-01", "pregunta": "q1", "criterios": [{}]},
        {"id": "CU-02", "pregunta": "q2", "criterios": [{"tema": "economia", "con_dato_oficial": True}]},
        {"id": "CU-03", "pregunta": "q3", "criterios": [{"estado": "suficiente", "tema": "eventos_naturales"}]},
        {"id": "CU-04", "pregunta": "q4", "criterios": [{"contradiccion_abierta": True}]},
        {"id": "CU-05", "pregunta": "q5", "grupo": h.G_COMPLETO, "modalidad": "banca"},
    ]
    return ConfigFichasTrazables.model_validate(datos)


@pytest.fixture
def corrida(base, tmp_path, emb, monkeypatch):
    """La base editorial, un registro de revisión con el caso bancario ya revisado (E2-03) y las exportaciones redirigidas a tmp_path."""
    ruta = tmp_path / "revision.duckdb"
    banca = Revisiones(ruta, h.construir(tmp_path / "banca.duckdb", emb, modalidad="banca"), huellas=[tmp_path / "notion", tmp_path / "fichas.jsonl"])
    caso = banca.abrir(h.G_COMPLETO, "banca", CFG.revision.revisor)
    banca.aceptar(caso.id_caso, CFG.revision.revisor)
    monkeypatch.setattr(cli, "cargar_fichas_trazables", _cfg_de_prueba)
    monkeypatch.setattr(cli, "huellas_de_exportacion", lambda *a, **k: [tmp_path / "notion", tmp_path / "fichas.jsonl"])
    monkeypatch.setattr(cli, "exportar_caso", lambda rev, id_caso: exportar.exportar_caso(rev, id_caso, tmp_path / "notion", tmp_path / "fichas.jsonl"))
    return {"ruta": ruta, "caso_banca": caso.id_caso, "base": base, "salida": tmp_path / "fichas_trazables"}


def _lanzar(c, *extra: str) -> int:
    return cli.principal(["--base", str(c["base"]), "--revision", str(c["ruta"]), "--salida", str(c["salida"]), *extra])


def test_el_comando_sin_casos_escribe_el_informe_rotula_cada_ficha_y_no_abre_casos(corrida) -> None:
    code = _lanzar(corrida)
    salida = corrida["salida"]
    inf = json.loads((salida / "trazabilidad.json").read_text())
    assert code == (0 if inf["todo_ok"] else 1) and inf["todo_ok"] and inf["n_fichas"] == 5 and inf["con_casos"] is False and inf["juicio_humano"] is False and inf["borrador"] is True
    elegidas = {e["caso_de_uso"]: e for e in inf["seleccion"]["elegidas"]}
    assert list(elegidas) == ["CU-01", "CU-02", "CU-03", "CU-04", "CU-05"] and len({e["id_grupo"] for e in elegidas.values()}) == 5
    assert elegidas["CU-05"]["reutilizado"] and elegidas["CU-05"]["id_caso"] == corrida["caso_banca"] and elegidas["CU-05"]["modalidad"] == "banca"
    assert len(Revisiones(corrida["ruta"]).casos()) == 1                              # el modo sin --casos no abre ninguno
    archivos = sorted(salida.glob("GRP-*.md"))
    assert len(archivos) == 5 and all(a.read_text().startswith("> **Caso de uso CU-0") for a in archivos)
    assert "REVISIÓN PROVISIONAL" in (salida / "indice.md").read_text() and "CU-05" in (salida / "indice.md").read_text()


def test_la_garantia_de_evidencia_insuficiente_se_aplica_y_el_informe_la_declara(corrida) -> None:
    assert _lanzar(corrida) == 0
    inf = json.loads((corrida["salida"] / "trazabilidad.json").read_text())
    elegidas = {e["caso_de_uso"]: e for e in inf["seleccion"]["elegidas"]}
    assert any(e["estado"] == "insuficiente" for e in elegidas.values())
    assert elegidas["CU-04"]["garantia"] and elegidas["CU-04"]["respaldo"] and "CU-04" in inf["seleccion"]["respaldos_usados"]    # el contradictorio era «parcial»


def test_con_casos_abre_uno_por_ficha_reutiliza_el_de_banca_rellena_el_caso_de_uso_y_es_idempotente(corrida, tmp_path) -> None:
    antes = Revisiones(corrida["ruta"])
    historial_banca = len(antes.historial(corrida["caso_banca"]))
    assert _lanzar(corrida, "--casos") == 0
    rev = Revisiones(corrida["ruta"])
    inf = json.loads((corrida["salida"] / "trazabilidad.json").read_text())
    por_cu = {e["caso_de_uso"]: e for e in inf["seleccion"]["elegidas"]}
    assert inf["con_casos"] is True and por_cu["CU-05"]["id_caso"] == corrida["caso_banca"]
    assert len(rev.casos()) == 5 and len(rev.historial(corrida["caso_banca"])) == historial_banca       # CU-05 reutiliza su CASO-: ni se renumera ni se reabre
    assert sorted(c.id_caso for c in rev.casos()) == [f"CASO-{i:03d}" for i in range(1, 6)]
    with (corrida["salida"] / "casos_y_evidencias.csv").open(encoding="utf-8") as f:
        filas = {r["ID caso"]: r["Caso de uso"] for r in csv.DictReader(f)}
    assert filas == {e["id_caso"]: cu for cu, e in por_cu.items()}                                        # la columna sale de la selección
    with (tmp_path / "notion" / cargar_revision().exportacion.csv).open(encoding="utf-8") as f:
        assert {r["Caso de uso"] for r in csv.DictReader(f)} == set(por_cu)
    n = {c.id_caso: len(rev.historial(c.id_caso)) for c in rev.casos()}
    assert _lanzar(corrida, "--casos") == 0
    again = Revisiones(corrida["ruta"])
    assert {c.id_caso: len(again.historial(c.id_caso)) for c in again.casos()} == n                       # idempotente: ni casos ni filas nuevas


def test_con_casos_descarta_los_de_una_corrida_anterior_que_ya_no_son_la_ficha_de_un_caso_de_uso(corrida, base, tmp_path) -> None:
    previo = Revisiones(corrida["ruta"], base, huellas=[tmp_path / "notion", tmp_path / "fichas.jsonl"])
    viejo = _abrir_como_c01(previo, base, h.G_SOLO, "parcial", tmp_path)          # GRP-solo no es de ningún caso de uso
    assert _lanzar(corrida, "--casos") == 0
    rev = Revisiones(corrida["ruta"])
    inf = json.loads((corrida["salida"] / "trazabilidad.json").read_text())
    assert inf["reemplazados"] == [viejo] and rev.estado(viejo) == "descartado" and rev.historial(viejo)[-1].motivo == CFG.reemplazo.motivo
    assert viejo not in {e["id_caso"] for e in inf["seleccion"]["elegidas"]} and "reemplazados" in (corrida["salida"] / "indice.md").read_text()


def test_con_casos_y_notion_el_caso_reemplazado_se_sincroniza_con_caso_de_uso_vacio_explicito(corrida, base, tmp_path, monkeypatch) -> None:
    """X108: un caso que C-01 ya había subido con «CU-03» y la selección reemplaza queda con su estado nuevo y SIN «Caso de uso» en Notion."""
    from tests.test_e3_03_notion import CFG as CFG_NOTION, TOKEN, NotionFalso
    from src.notion import ClienteNotion
    previo = Revisiones(corrida["ruta"], base, huellas=[tmp_path / "notion", tmp_path / "fichas.jsonl"])
    viejo = _abrir_como_c01(previo, base, h.G_SOLO, "parcial", tmp_path)
    falso = NotionFalso([{"id": "pagina-vieja", "titulo": viejo, "props": {"Caso de uso": {"select": {"name": "CU-03"}}, "Estado de revisión": {"select": {"name": "En revisión"}}}}])
    cliente = ClienteNotion(TOKEN, CFG_NOTION, falso, dormir=lambda x: None)
    llamadas: list[tuple[str, bool]] = []

    def enviar(e, limpiar_vacias=False):
        llamadas.append((e.id_caso, limpiar_vacias))
        return exportar.sincronizar_con_notion(e, cliente=cliente, limpiar_vacias=limpiar_vacias)

    monkeypatch.setattr(cli, "sincronizar_con_notion", enviar)
    assert _lanzar(corrida, "--casos", "--notion") == 0
    assert Revisiones(corrida["ruta"]).estado(viejo) == "descartado"
    assert (viejo, True) in llamadas and all(not limpiar for id_caso, limpiar in llamadas if id_caso != viejo)   # solo el reemplazado limpia
    props = falso.paginas["pagina-vieja"]["props"]
    assert props["Caso de uso"] == {"select": None} and props["Estado de revisión"] != {"select": {"name": "En revisión"}}


def test_si_el_caso_bancario_de_cu05_no_existe_el_comando_falla_con_un_mensaje(corrida, tmp_path, capsys) -> None:
    corrida["ruta"].unlink()
    corrida["ruta"].with_suffix(".casos.csv").unlink(missing_ok=True)
    assert _lanzar(corrida) == 1
    assert "CU-05" in capsys.readouterr().err


def test_x107_sin_casos_y_sin_salida_escribe_en_la_vista_previa_y_no_toca_lo_versionado(corrida, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RAIZ", tmp_path / "repo")
    oficial = tmp_path / "repo" / CFG.archivos.carpeta
    oficial.mkdir(parents=True)
    versionados = {oficial / "CASO-001.md": "caso", oficial / cargar_revision().exportacion.csv: "csv", oficial / "trazabilidad.json": "{}", oficial / "indice.md": "indice"}
    for ruta, texto in versionados.items():
        ruta.write_text(texto, encoding="utf-8")
    assert cli.principal(["--base", str(corrida["base"]), "--revision", str(corrida["ruta"])]) == 0
    assert {r: r.read_text(encoding="utf-8") for r in versionados} == versionados                  # nada borrado ni pisado
    previa = tmp_path / "repo" / CFG.archivos.vista_previa
    assert (previa / "trazabilidad.json").exists() and (previa / "indice.md").exists() and len(list(previa.glob("GRP-*.md"))) == 5
    assert json.loads((previa / "trazabilidad.json").read_text())["con_casos"] is False


def test_x107_sin_ninguna_descripcion_la_comprobacion_no_aplica_y_no_se_informa_100_por_ciento(base) -> None:
    r = _ejecutar(base, h.G_COMPLETO)
    assert r.conteo("sin_descripcion_rss") == (0, 0)                      # los datos de prueba no traen descripciones: no hay nada que comparar
    inf = informe([r], CFG)["por_regla"]["sin_descripcion_rss"]
    assert inf["n"] == 0 and inf["proporcion"] is None and inf["nota"] == "no aplica (0 descripciones en los datos)"


def test_x107_con_una_descripcion_evaluable_la_comprobacion_si_se_cuenta(base) -> None:
    descripcion = "Texto interno del RSS que nunca debe republicarse en una ficha"
    r = _ejecutar(base, h.G_COMPLETO, f"UPDATE noticias SET descripcion = '{descripcion}' WHERE id_noticia = 'NOT-c000000001'")
    assert r.conteo("sin_descripcion_rss") == (1, 1)
