"""Prueba de humo: el paquete src y todos sus módulos se importan."""

import importlib
import pkgutil

import src


def test_importa_todos_los_modulos() -> None:
    nombres = [
        m.name for m in pkgutil.walk_packages(src.__path__, prefix="src.")
    ]
    assert "src.registro" in nombres
    assert "src.llm.deepseek" in nombres
    assert len(nombres) >= 25
    for nombre in nombres:
        importlib.import_module(nombre)
