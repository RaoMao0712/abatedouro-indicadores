"""Configurações centrais da aplicação Flask e dos documentos oficiais."""

import os


MARCA_SISTEMA = "FrigoDatta"
EMPRESA_EMITENTE = "LF Boratto Abatedouro de Aves Ltda."


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "segredo")
    DATABASE_URL = os.getenv("DATABASE_URL")
    DB_NAME = os.getenv("DB_NAME", "abatedouro.db")
    MARCA_SISTEMA = MARCA_SISTEMA
    EMPRESA_EMITENTE = EMPRESA_EMITENTE
