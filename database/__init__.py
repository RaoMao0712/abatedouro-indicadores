"""Camada central de banco de dados do FrigoDatta."""

from .connection import DATABASE_URL, DB_NAME, conectar, get_connection, q, transaction
from .migrations import executar_alteracao_segura
from .schema import inicializar_schema_uma_vez
