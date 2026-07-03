"""Configurações futuras da aplicação Flask.

Mantido sem integração com o app principal nesta sprint.
"""

import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "segredo")
    DATABASE_URL = os.getenv("DATABASE_URL")
    DB_NAME = os.getenv("DB_NAME", "abatedouro.db")
