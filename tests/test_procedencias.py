"""E1-08: procedencias independientes (CU-03, D-32). Sin red: codificador de prueba o vectores a mano."""

import shutil
from pathlib import Path

import numpy as np
import pytest

from src import procedencias as pr
from src.configuracion import (
    CARPETA_CONFIG,
    ConfigProcedencias,
    ErrorDeConfiguracion,
    cargar_procedencias,
    cargar_reglas,
    validar_coherencia,
)

REGLAS = cargar_reglas()
CFG = cargar_procedencias()


@pytest.fixture
def copiar_config(tmp_path: Path) -> Path:
    """Una copia de ``config/`` que la prueba puede romper sin tocar la real."""
    destino = tmp_path / "config"
    shutil.copytree(CARPETA_CONFIG, destino)
    return destino


def _fila(id_, dominio, titulo="Titular distinto de cada medio " , agencia=None, medio=None):
    return {"id_noticia": id_, "dominio": dominio, "medio": medio or dominio, "titulo": f"{titulo}{id_}", "agencia": agencia}


def _vectores(n: int, parecidos: set[tuple[int, int]] = frozenset()) -> np.ndarray:
    """Vectores unitarios: ortogonales, salvo los pares de ``parecidos`` (dos filas con el mismo vector)."""
    v = np.eye(n, dtype=np.float32)
    for i, j in parecidos:
        v[j] = v[i]
    return v


def _etiquetas(procs) -> list[str]:
    return [p.etiqueta for p in procs]


# ------------------------------------------------------------------ CU-03: cinco medios que replican una agencia


def test_cinco_titulares_casi_identicos_en_cinco_medios_son_una_procedencia() -> None:
    filas = [_fila(f"NOT-{i}", f"medio{i}.example", titulo="El Canal reduce sus tránsitos por la sequía") for i in range(5)]
    vectores = np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (5, 1))     # mismo texto: coseno 1.0
    (unica,) = pr.estimar_procedencias(filas, vectores, CFG, REGLAS)
    assert len(unica.ids_noticia) == 5 and len(unica.medios) == 5
    assert unica.reglas == (pr.REGLA_TEXTO,)


def test_titulares_distintos_de_medios_distintos_son_procedencias_independientes() -> None:
    filas = [_fila(f"NOT-{i}", f"medio{i}.example") for i in range(4)]
    procs = pr.estimar_procedencias(filas, _vectores(4), CFG, REGLAS)
    assert len(procs) == 4 and all(p.reglas == () for p in procs)


def test_el_umbral_de_mismo_texto_sale_del_yaml_y_es_inclusivo() -> None:
    umbral = REGLAS.agrupacion.umbral_mismo_texto
    a, b = _fila("NOT-1", "a.example"), _fila("NOT-2", "b.example")
    justo = np.array([[1.0, 0.0], [umbral, np.sqrt(1 - umbral**2)]])
    debajo = np.array([[1.0, 0.0], [umbral - 0.02, np.sqrt(1 - (umbral - 0.02) ** 2)]])
    assert len(pr.estimar_procedencias([a, b], justo, CFG, REGLAS)) == 1
    assert len(pr.estimar_procedencias([a, b], debajo, CFG, REGLAS)) == 2


def test_sin_vectores_no_se_aplica_la_regla_de_texto() -> None:
    filas = [_fila("NOT-1", "a.example"), _fila("NOT-2", "b.example")]
    assert len(pr.estimar_procedencias(filas, None, CFG, REGLAS)) == 2


# ------------------------------------------------------------------ cada regla por separado


def test_el_mismo_medio_es_una_procedencia_aunque_el_texto_cambie() -> None:
    filas = [_fila("NOT-1", "www.prensa.example"), _fila("NOT-2", "prensa.example")]
    (unica,) = pr.estimar_procedencias(filas, _vectores(2), CFG, REGLAS)
    assert unica.reglas == (pr.REGLA_MISMO_MEDIO,)


def test_el_mismo_campo_agencia_une_medios_distintos() -> None:
    filas = [_fila("NOT-1", "a.example", agencia="EFE"), _fila("NOT-2", "b.example", agencia="EFE"), _fila("NOT-3", "c.example", agencia="AFP")]
    procs = pr.estimar_procedencias(filas, _vectores(3), CFG, REGLAS)
    assert sorted(_etiquetas(procs)) == ["AFP", "EFE"]
    assert next(p for p in procs if p.etiqueta == "EFE").reglas == (pr.REGLA_AGENCIA_CAMPO,)


def test_un_valor_de_agencia_fuera_de_la_lista_no_cuenta() -> None:
    filas = [_fila("NOT-1", "a.example", agencia="Agencia Inventada"), _fila("NOT-2", "b.example", agencia="Agencia Inventada")]
    assert len(pr.estimar_procedencias(filas, _vectores(2), CFG, REGLAS)) == 2


def test_la_agencia_nombrada_en_el_titular_une_a_sus_replicas() -> None:
    filas = [
        _fila("NOT-1", "a.example", titulo="Sube el petróleo - Reuters "),
        _fila("NOT-2", "b.example", titulo="Sube el petróleo, según Thomson Reuters "),
        _fila("NOT-3", "c.example", titulo="Sube el petróleo "),
    ]
    procs = pr.estimar_procedencias(filas, _vectores(3), CFG, REGLAS)
    assert sorted(len(p.ids_noticia) for p in procs) == [1, 2]
    unida = next(p for p in procs if len(p.ids_noticia) == 2)
    assert unida.etiqueta == "Reuters" and unida.reglas == (pr.REGLA_AGENCIA_MENCIONADA,)


def test_las_siglas_distinguen_mayusculas_y_los_nombres_no() -> None:
    assert pr._menciona("Reunión en el ap de la zona", "AP") is False       # "ap" no es la agencia AP
    assert pr._menciona("Informó AP este lunes", "AP") is True
    assert pr._menciona("informó la agencia xinhua", "Xinhua") is True
    assert pr._menciona("Xinhuanet publicó", "Xinhua") is False             # palabra completa


def test_un_dominio_de_agencia_se_une_con_quien_la_nombra() -> None:
    filas = [
        _fila("NOT-1", "english.news.cn", titulo="El Niño se intensifica "),
        _fila("NOT-2", "otro.example", titulo="El Niño se intensifica - Xinhua "),
    ]
    (unica,) = pr.estimar_procedencias(filas, _vectores(2), CFG, REGLAS)
    assert unica.etiqueta == "Xinhua"
    assert pr.REGLA_AGENCIA_DOMINIO in unica.reglas


def test_los_subdominios_de_una_red_o_agencia_cuentan() -> None:
    filas = [_fila("NOT-1", "english.news.cn"), _fila("NOT-2", "spanish.news.cn")]
    (unica,) = pr.estimar_procedencias(filas, _vectores(2), CFG, REGLAS)
    assert unica.etiqueta == "Xinhua"


def test_la_red_de_sindicacion_une_sus_sitios_espejo() -> None:
    dominios = CFG.redes_sindicacion["big_news_network"].dominios[:4]
    filas = [_fila(f"NOT-{i}", d) for i, d in enumerate(dominios)]
    (unica,) = pr.estimar_procedencias(filas, _vectores(4), CFG, REGLAS)
    assert unica.etiqueta == "Big News Network" and unica.reglas == (pr.REGLA_MISMA_RED,)


def test_la_relacion_es_transitiva_y_la_etiqueta_junta_agencia_y_red() -> None:
    """Xinhua (dominio) ~ copia sin firma (texto) ~ espejo de la red: una sola procedencia con las dos etiquetas."""
    red = CFG.redes_sindicacion["big_news_network"].dominios[0]
    filas = [_fila("NOT-1", "english.news.cn"), _fila("NOT-2", "copia.example"), _fila("NOT-3", red)]
    vectores = _vectores(3, {(0, 1), (1, 2)})
    (unica,) = pr.estimar_procedencias(filas, vectores, CFG, REGLAS)
    assert unica.etiqueta == f"Xinhua{CFG.separador_etiqueta}Big News Network"
    assert len(unica.ids_noticia) == 3


def test_cada_titular_cae_en_exactamente_una_procedencia() -> None:
    filas = [_fila(f"NOT-{i}", f"m{i % 3}.example") for i in range(9)]
    procs = pr.estimar_procedencias(filas, _vectores(9), CFG, REGLAS)
    todos = [i for p in procs for i in p.ids_noticia]
    assert sorted(todos) == sorted(f["id_noticia"] for f in filas)


def test_una_procedencia_sin_agencia_ni_red_se_llama_como_su_medio_mas_antiguo() -> None:
    filas = [_fila("NOT-1", "b.example", medio="Medio B"), _fila("NOT-2", "a.example", medio="Medio A")]
    (unica,) = pr.estimar_procedencias(filas, _vectores(2, {(0, 1)}), CFG, REGLAS, fechas=["2026-10-02T10:00:00Z", "2026-10-02T08:00:00Z"])
    assert unica.etiqueta == "Medio A"


def test_el_resultado_no_depende_del_orden_de_entrada() -> None:
    filas = [_fila(f"NOT-{i}", f"m{i}.example", agencia="EFE" if i % 2 else None) for i in range(6)]
    a = pr.estimar_procedencias(filas, _vectores(6), CFG, REGLAS)
    orden = [5, 3, 1, 0, 2, 4]
    b = pr.estimar_procedencias([filas[i] for i in orden], _vectores(6)[orden], CFG, REGLAS)
    assert {p.ids_noticia for p in a} == {p.ids_noticia for p in b}


def test_sin_miembros_no_hay_procedencias() -> None:
    assert pr.estimar_procedencias([], None, CFG, REGLAS) == []


# ------------------------------------------------------------------ privacidad (D-32) y puntaje


def test_nunca_se_guarda_ni_se_lee_el_nombre_de_un_autor() -> None:
    campos = set(pr.Procedencia.__dataclass_fields__) | set(pr.Senales.__dataclass_fields__)
    assert not {c for c in campos if "autor" in c or "firma" in c or "persona" in c}
    fila = _fila("NOT-1", "a.example") | {"autor": "Nombre Apellido", "firma": "Nombre Apellido"}
    assert "Nombre" not in str(pr.senales_de(fila, CFG, REGLAS))


def test_las_procedencias_aportan_a_e_con_tope_y_sin_contar_titulares() -> None:
    assert pr.fraccion_de_procedencias(1, REGLAS) == pytest.approx(1 / REGLAS.evidencia.tope_procedencias)
    assert pr.fraccion_de_procedencias(REGLAS.evidencia.tope_procedencias + 4, REGLAS) == 1.0
    assert pr.fraccion_de_procedencias(0, REGLAS) == 0.0


# ------------------------------------------------------------------ configuración


def test_la_configuracion_real_es_coherente() -> None:
    assert validar_coherencia() == []
    assert "Xinhua" in CFG.agencias_por_dominio and set(CFG.alias_agencias) <= set(REGLAS.agencias)


def test_un_dominio_en_dos_redes_se_rechaza() -> None:
    datos = CFG.model_dump()
    datos["agencias_por_dominio"]["EFE"] = [CFG.redes_sindicacion["big_news_network"].dominios[0]]
    with pytest.raises(ValueError, match="no puede estar en dos"):
        ConfigProcedencias.model_validate(datos)


def test_una_agencia_ajena_a_reglas_se_rechaza_en_la_coherencia(copiar_config) -> None:
    ruta = copiar_config / "procedencias.yaml"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("  Prensa Latina: [prensa-latina.cu]", "  Agencia Inventada: [inventada.example]"), encoding="utf-8")
    assert any("Agencia Inventada" in p for p in validar_coherencia(copiar_config))


def test_un_yaml_con_clave_desconocida_se_rechaza(copiar_config) -> None:
    ruta = copiar_config / "procedencias.yaml"
    ruta.write_text(ruta.read_text(encoding="utf-8") + "clave_con_errata: 1\n", encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match="clave_con_errata"):
        cargar_procedencias(copiar_config)
