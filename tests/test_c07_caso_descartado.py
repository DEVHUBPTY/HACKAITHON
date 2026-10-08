"""C-07: un caso descartado cuyo grupo ya no está en el snapshot se rotula en fichas.jsonl y la auditoría lo informa (no es FALTA)."""
from __future__ import annotations

import json

from src import exportar
from src.configuracion import cargar_revision


def test_la_nota_sale_de_la_configuracion() -> None:
    assert "ya no está en el snapshot actual" in cargar_revision().exportacion.nota_grupo_ausente


def test_grupo_ausente_en_el_snapshot_se_detecta(tmp_path) -> None:
    from types import SimpleNamespace

    from src import db

    base = tmp_path / "s.duckdb"
    con = db.conectar(base)
    con.execute("CREATE TABLE grupos (id_grupo VARCHAR)")
    con.execute("INSERT INTO grupos VALUES ('GRP-presente')")
    con.close()
    rev = SimpleNamespace(base_fichas=base)
    assert exportar.grupo_en_snapshot(rev, "GRP-presente")
    assert not exportar.grupo_en_snapshot(rev, "GRP-ausente")
    assert exportar.grupo_en_snapshot(SimpleNamespace(base_fichas=tmp_path / "no_existe.duckdb"), "GRP-x")   # sin base no se rotula


def test_la_auditoria_trata_un_descartado_sin_grupo_como_informativo() -> None:
    from scripts import auditoria_final

    fuente = open(auditoria_final.__file__, encoding="utf-8").read()
    assert "informativo:" in fuente and 'r.get("nota_estado")' in fuente
