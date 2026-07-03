"""Inicialização única do schema da aplicação."""

from threading import RLock


_SCHEMA_INICIALIZADO = False
_SCHEMA_LOCK = RLock()


def inicializar_schema_uma_vez(rotinas):
    global _SCHEMA_INICIALIZADO

    with _SCHEMA_LOCK:
        if _SCHEMA_INICIALIZADO:
            return

        for rotina in rotinas:
            rotina()

        _SCHEMA_INICIALIZADO = True
