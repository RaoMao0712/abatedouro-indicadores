"""Cadastro mestre de parceiros e integração cadastral."""

from .routes import register_parceiros_routes
from .services import criar_tabelas_parceiros

__all__ = ["criar_tabelas_parceiros", "register_parceiros_routes"]
