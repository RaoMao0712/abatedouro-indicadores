"""Rotas do Fluxo de Caixa."""

from flask import render_template, request

from modules.auth.decorators import perfil_permitido

from .services import montar_contexto_fluxo_caixa


def register_fluxo_caixa_routes(app):
    @app.route("/fluxo-caixa")
    @perfil_permitido("pcp")
    def fluxo_caixa():
        return render_template(
            "fluxo_caixa.html",
            **montar_contexto_fluxo_caixa(request.args),
        )

