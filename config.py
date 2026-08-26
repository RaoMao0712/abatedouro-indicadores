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
    PNC_DISCARD_WAYBILL_ENABLED = os.getenv(
        "PNC_DISCARD_WAYBILL_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes", "on", "sim"}
    LABEL_PRINTING_ENABLED = os.getenv("LABEL_PRINTING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on", "sim"}
    BOX_LABEL_AUTO_PRINT_ENABLED = os.getenv("BOX_LABEL_AUTO_PRINT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on", "sim"}
    LOCAL_PRINT_AGENT_ENABLED = os.getenv("LOCAL_PRINT_AGENT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on", "sim"}
