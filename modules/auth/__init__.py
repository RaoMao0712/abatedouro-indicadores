"""Autenticação e controle de acesso do FrigoDatta."""

from .decorators import login_obrigatorio, perfil_permitido
from .routes import register_auth_routes
from .services import destino_por_perfil
