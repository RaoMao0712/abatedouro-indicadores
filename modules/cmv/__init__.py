"""Razao auditavel de custo das mercadorias vendidas."""

from .routes import register_cmv_routes
from .services import criar_tabelas_cmv

__all__ = ["criar_tabelas_cmv", "register_cmv_routes"]
