"""T03 · Noticia antigua recirculada (E1-03): publicación y detección son distintas y se conservan."""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.t03

from src import db, limpieza, normalizacion, puntaje
from src.configuracion import cargar_fuentes, cargar_normalizacion, cargar_prioridad, cargar_reglas

FIXTURE = Path(__file__).parent / "fixtures" / "t03_recirculada.csv"
CONFIG = cargar_normalizacion()
FUENTES = cargar_fuentes()


def _normalizar(filas: list[dict]) -> list[dict]:
    return normalizacion.normalizar_noticias(filas, [], CONFIG, FUENTES, normalizacion.Registro())


def test_el_fixture_conserva_la_fecha_de_publicacion_original() -> None:
    (fila,) = _normalizar(normalizacion.leer_csv(FIXTURE))
    assert fila["fecha_publicacion"] == "2024-03-14T15:00:00Z"
    assert fila["fecha_deteccion"] == "2025-09-28T09:30:00Z"
    assert fila["fecha_publicacion"] != fila["fecha_deteccion"]
    assert fila["id_noticia"] == "SYN-T03-001"  # los sintéticos conservan su ID (D-63)


def test_la_noticia_antigua_no_se_trata_como_evento_nuevo() -> None:
    """Regla: detectada más de ``dias_para_recirculada`` días después de publicada = recirculada."""
    (fila,) = _normalizar(normalizacion.leer_csv(FIXTURE))
    assert fila["es_recirculada"] is True


def test_una_noticia_reciente_no_es_recirculada() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": "2025-09-28T08:00:00Z"}
    (resultado,) = _normalizar([fila])
    assert resultado["es_recirculada"] is False


def test_sin_publicacion_queda_nula_y_no_se_sustituye_por_la_deteccion() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": ""}
    (resultado,) = _normalizar([fila])
    assert resultado["fecha_publicacion"] is None
    assert resultado["fecha_deteccion"] == "2025-09-28T09:30:00Z"
    assert resultado["es_recirculada"] is None


def test_sin_deteccion_queda_nula_y_no_se_sustituye_por_la_publicacion() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_deteccion": ""}
    (resultado,) = _normalizar([fila])
    assert resultado["fecha_deteccion"] is None
    assert resultado["fecha_publicacion"] == "2024-03-14T15:00:00Z"


def test_una_fecha_con_zona_se_convierte_a_utc() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": "2024-03-14T10:00:00-05:00"}
    (resultado,) = _normalizar([fila])
    assert resultado["fecha_publicacion"] == "2024-03-14T15:00:00Z"


@pytest.mark.parametrize("texto", ["2024-03-14", "no es fecha", "2024-03-14T10:00:00"])
def test_una_fecha_ilegible_o_sin_zona_no_se_adivina_y_se_registra(texto: str) -> None:
    registro = normalizacion.Registro()
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": texto}
    (resultado,) = normalizacion.normalizar_noticias([fila], [], CONFIG, FUENTES, registro)
    assert resultado["fecha_publicacion"] is None
    assert [c["campo"] for c in registro.cambios] == ["fecha_publicacion"]


def test_las_dos_fechas_sobreviven_al_ida_y_vuelta_por_duckdb(tmp_path: Path) -> None:
    ruta = tmp_path / "t.duckdb"
    db.guardar_todo(ruta, {"noticias": _normalizar(normalizacion.leer_csv(FIXTURE))})
    con = db.conectar(ruta, solo_lectura=True)
    fila = db.leer_tabla(con, "noticias")[0]
    con.close()
    assert fila["fecha_publicacion"] == "2024-03-14T15:00:00Z"
    assert fila["fecha_deteccion"] == "2025-09-28T09:30:00Z"
    assert fila["es_recirculada"] is True


# ------------------------------------------------------------------ E1-10: la recirculada tiene U baja y no se marca como nueva

REGLAS = cargar_reglas()
PRIORIDAD = cargar_prioridad()
CORTE = datetime(2025, 9, 28, 12, 0, tzinfo=UTC)   # el snapshot del fixture se cortó el mismo día que se detectó


def _grupo_de(fila: dict) -> puntaje.EntradaGrupo:
    limpia = limpieza.limpiar_filas([fila], limpieza.Reglas.desde_config())[0] | {"tema_similitud": 0.8}
    return puntaje.EntradaGrupo("GRP-t03", (limpia,), np.array([[1.0, 0.0]], dtype=np.float32), "operacion_canal", 1, False)


def test_la_noticia_recirculada_tiene_urgencia_baja_y_no_se_marca_como_nueva() -> None:
    (fila,) = _normalizar(normalizacion.leer_csv(FIXTURE))
    (p,) = puntaje.calcular_puntajes([_grupo_de(fila)], REGLAS, PRIORIDAD, CORTE)
    u = p.componentes["U"]
    assert u.explicacion["fecha"] == "2024-03-14T15:00:00Z" and u.explicacion["fecha_origen"] == "publicacion"
    assert u.valor == 0.0                       # publicada hace casi 19 meses: más allá de los días nulos
    assert p.recirculada is True and p.es_nueva is False
    assert any(v.codigo == "noticia_recirculada" and "2024-03-14" in v.texto for v in p.vacios)


def test_la_misma_noticia_publicada_hoy_si_es_nueva_y_urgente() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": "2025-09-28T08:00:00Z"}
    (resultado,) = _normalizar([fila])
    (p,) = puntaje.calcular_puntajes([_grupo_de(resultado)], REGLAS, PRIORIDAD, CORTE)
    edad = (CORTE - datetime(2025, 9, 28, 8, 0, tzinfo=UTC)).total_seconds() / 3600   # publicada 4 h antes del corte
    # D-106: U es la fracción de la ventana que queda (sin meseta de 24 h)
    assert p.componentes["U"].valor == pytest.approx(1 - edad / (REGLAS.urgencia.dias_nulo * 24)) and p.recirculada is False and p.es_nueva is True


def test_la_deteccion_reciente_no_rescata_la_urgencia_de_una_recirculada() -> None:
    """La detección es de hoy (2025-09-28) pero la publicación es de 2024: U se mide sobre la publicación original."""
    (fila,) = _normalizar(normalizacion.leer_csv(FIXTURE))
    assert fila["fecha_deteccion"] == "2025-09-28T09:30:00Z"
    (p,) = puntaje.calcular_puntajes([_grupo_de(fila)], REGLAS, PRIORIDAD, CORTE)
    assert p.componentes["U"].explicacion["fecha_origen"] == "publicacion"
    assert not any(v.codigo == "urgencia_sin_publicacion" for v in p.vacios)


def test_t03_aceptacion_muestra_la_fecha_original_y_no_la_presenta_como_evento_nuevo() -> None:
    """PDF T03: mostrar fecha original; no presentarla como un evento nuevo."""
    (fila,) = _normalizar(normalizacion.leer_csv(FIXTURE))
    assert fila["fecha_publicacion"] == "2024-03-14T15:00:00Z" and fila["fecha_deteccion"] != fila["fecha_publicacion"]
    (p,) = puntaje.calcular_puntajes([_grupo_de(fila)], REGLAS, PRIORIDAD, CORTE)
    assert p.componentes["U"].explicacion["fecha"] == "2024-03-14T15:00:00Z"   # la fecha original es la que se muestra
    assert p.recirculada is True and p.es_nueva is False
