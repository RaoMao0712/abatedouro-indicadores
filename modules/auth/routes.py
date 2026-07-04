"""Rotas de autenticação registradas no app Flask principal."""

from flask import flash, redirect, render_template, request, session, url_for

from .services import autenticar_usuario, destino_por_perfil


def register_auth_routes(app, preparar_banco):
    @app.route("/", methods=["GET", "POST"])
    def login():
        preparar_banco()

        if request.method == "POST":
            usuario = autenticar_usuario(request.form["email"], request.form["senha"])

            if usuario:
                session["usuario_id"] = usuario["id"]
                session["nome"] = usuario["nome"]
                session["perfil"] = usuario["perfil"]

                return redirect(url_for(destino_por_perfil(session["perfil"])))

            flash("Usuário ou senha inválidos")

        return render_template("login.html")

    @app.route("/sair")
    def sair():
        session.clear()
        return redirect(url_for("login"))
