"""Token protegido pelo DPAPI do usuário atual; nunca persiste texto puro."""

import ctypes
from ctypes import wintypes
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(dados: bytes):
    buffer = ctypes.create_string_buffer(dados)
    return DATA_BLOB(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect(token: str, destino: Path):
    entrada, manter = _blob(token.encode("utf-8")); saida = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), "FrigoDatta Print Agent", None, None, None, 0, ctypes.byref(saida)):
        raise ctypes.WinError()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(ctypes.string_at(saida.pbData, saida.cbData))
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def unprotect(origem: Path) -> str:
    entrada, manter = _blob(origem.read_bytes()); saida = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(saida.pbData, saida.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)
