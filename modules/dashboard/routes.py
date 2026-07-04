"""Rotas do Dashboard."""

from flask import render_template, request

from modules.auth.decorators import perfil_permitido

from .services import montar_contexto_dashboard


def register_dashboard_routes(app):
    @app.route("/dashboard")
    @perfil_permitido("pcp", "producao", "qualidade")
    def dashboard():
        return render_template(
            "dashboard.html",
            **montar_contexto_dashboard(request.args),
        )
