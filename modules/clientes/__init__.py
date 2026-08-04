"""Cadastro operacional de clientes para a Expedição."""

from .routes import register_clientes_routes
from .services import criar_tabelas_clientes

__all__ = ["criar_tabelas_clientes", "register_clientes_routes"]
