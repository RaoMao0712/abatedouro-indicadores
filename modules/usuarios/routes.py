"""Rotas administrativas de usuarios."""

from flask import flash, redirect, render_template, request, url_for

from modules.auth.decorators import perfil_permitido
from .services import cadastrar_usuario as cadastrar_usuario_service


def register_usuarios_routes(app, preparar_banco):

    @app.route("/cadastrar-usuario", methods=["GET", "POST"])
    @perfil_permitido("admin")
    def cadastrar_usuario():
        preparar_banco()

        if request.method == "POST":
            cadastrar_usuario_service(request.form)
            flash("Usuário cadastrado com sucesso.")

            return redirect(url_for("cadastrar_usuario"))

        return render_template("cadastrar_usuario.html")