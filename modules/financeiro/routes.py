"""Rotas do nucleo financeiro."""

from flask import render_template

from modules.auth.decorators import perfil_permitido

from .services import agrupar_plano_contas, diagnostico_categorias_legadas


def register_financeiro_routes(app):
    @app.route("/plano-contas-gerencial")
    @perfil_permitido("pcp")
    def plano_contas_gerencial():
        return render_template(
            "plano_contas_gerencial.html",
            grupos_plano=agrupar_plano_contas(),
            diagnostico=diagnostico_categorias_legadas(),
        )
