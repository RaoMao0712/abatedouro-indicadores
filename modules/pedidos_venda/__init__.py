"""Pedidos comerciais de venda direta vinculados à expedição."""

from .routes import register_pedidos_venda_routes
from .services import criar_tabelas_pedidos_venda

__all__ = ["criar_tabelas_pedidos_venda", "register_pedidos_venda_routes"]
