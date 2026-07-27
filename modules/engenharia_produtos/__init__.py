"""Engenharia de Produtos: catálogo, processos e estruturas de consumo."""

from .routes import register_engenharia_produtos_routes
from .services import criar_tabelas_engenharia_produtos

__all__ = ["register_engenharia_produtos_routes", "criar_tabelas_engenharia_produtos"]
