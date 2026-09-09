"""Redirecionamentos de compatibilidade do cadastro legado de clientes."""

from flask import flash, redirect, url_for

from modules.auth.decorators import perfil_permitido
from .services import buscar_cliente


def register_clientes_routes(app):
    @app.get("/cadastros/clientes")
    @perfil_permitido("gerencia", "pcp", "expedicao")
    def clientes():
        return redirect(url_for("parceiros", papel="CLIENTE"))

    @app.route("/cadastros/clientes/novo", methods=["GET", "POST"])
    @perfil_permitido("gerencia", "pcp")
    def novo_cliente():
        flash("Clientes agora são cadastrados como Parceiros.")
        return redirect(url_for("novo_parceiro", papel="CLIENTE"))

    @app.route("/cadastros/clientes/<int:cliente_id>", methods=["GET", "POST"])
    @perfil_permitido("gerencia", "pcp", "expedicao")
    def editar_cliente(cliente_id):
        cliente = buscar_cliente(cliente_id)
        if not cliente:
            flash("Cliente não encontrado.")
            return redirect(url_for("clientes"))
        if not cliente["parceiro_id"]:
            flash("Cliente legado ainda não possui vínculo com Parceiros.")
            return redirect(url_for("clientes"))
        return redirect(url_for("editar_parceiro", parceiro_id=cliente["parceiro_id"]))

    @app.post("/cadastros/clientes/<int:cliente_id>/status")
    @perfil_permitido("gerencia")
    def status_cliente(cliente_id):
        cliente = buscar_cliente(cliente_id)
        if cliente and cliente["parceiro_id"]:
            return redirect(url_for("editar_parceiro", parceiro_id=cliente["parceiro_id"]))
        return redirect(url_for("clientes"))
