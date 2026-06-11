from functools import wraps

from flask import flash, redirect, session, url_for


def login_obrigatorio(funcao):
    @wraps(funcao)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return funcao(*args, **kwargs)
    return wrapper


def destino_por_perfil(perfil):
    if perfil == "admin" or perfil == "pcp":
        return "dashboard"

    if perfil == "qualidade":
        return "apontamento_descartes"

    if perfil == "producao":
        return "apontamento_producao"

    return "login"


def perfil_permitido(*perfis_autorizados):
    def decorador(funcao):
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            if "usuario_id" not in session:
                return redirect(url_for("login"))

            perfil = session.get("perfil", "")

            if perfil == "admin" or perfil in perfis_autorizados:
                return funcao(*args, **kwargs)

            flash("Acesso não autorizado para este usuário.")
            return redirect(url_for(destino_por_perfil(perfil)))

        return wrapper

    return decorador
