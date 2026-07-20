"""Serviços de autenticação e perfis."""

from flask import session
from werkzeug.security import check_password_hash

from .repositories import buscar_usuario_por_email, inserir_usuario


def destino_por_perfil(perfil):
    if perfil == "admin" or perfil == "pcp":
        return "dashboard"

    if perfil == "gerencia":
        return "sgi_qualidade"

    if perfil == "qualidade":
        return "apontamento_descartes"

    if perfil == "producao":
        return "consultar_op"

    return "login"


def perfil_atual():
    return session.get("perfil", "")


def usuario_eh_admin():
    return perfil_atual() == "admin"


def nome_usuario_atual():
    return session.get("nome", "")


def autenticar_usuario(email, senha):
    usuario = buscar_usuario_por_email(email)

    if not usuario or not check_password_hash(usuario["senha_hash"], senha):
        return None

    return {
        "id": usuario["id"],
        "nome": usuario["nome"],
        "perfil": usuario["perfil"] or "admin",
    }


def cadastrar_novo_usuario(form):
    inserir_usuario(
        form["nome"],
        form["email"],
        form["senha"],
        form["perfil"],
    )
