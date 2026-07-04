"""Servicos administrativos de usuarios."""

from modules.auth.services import cadastrar_novo_usuario


def cadastrar_usuario(form):
    return cadastrar_novo_usuario(form)