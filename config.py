"""Configurações centrais da aplicação Flask e dos documentos oficiais."""

import os


MARCA_SISTEMA = "FrigoDatta"
EMPRESA_EMITENTE = "LF Boratto Abatedouro de Aves Ltda."
ESTABELECIMENTO_DOCUMENTO = "ABATEDOURO DE AVES SÃO PEDRO"
IDENTIFICACAO_TECNOLOGIA = "Documento gerado pelo FrigoDatta"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "segredo")
    DATABASE_URL = os.getenv("DATABASE_URL")
    DB_NAME = os.getenv("DB_NAME", "abatedouro.db")
    MARCA_SISTEMA = MARCA_SISTEMA
    EMPRESA_EMITENTE = EMPRESA_EMITENTE
    ESTABELECIMENTO_DOCUMENTO = ESTABELECIMENTO_DOCUMENTO
    IDENTIFICACAO_TECNOLOGIA = IDENTIFICACAO_TECNOLOGIA
    SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED = os.getenv(
        "SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes", "on", "sim"}
