"""Punto de entrada ``python -m src.config --validar``; la lógica vive en ``src/configuracion.py``."""

from src.configuracion import principal

if __name__ == "__main__":
    raise SystemExit(principal())
