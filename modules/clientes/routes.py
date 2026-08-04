"""Rotas do cadastro operacional de clientes."""

from flask import flash, redirect, render_template, request, session, url_for

from modules.auth.decorators import perfil_permitido
from .services import alterar_status, buscar_cliente, historico_cliente, listar_clientes, salvar_cliente


def register_clientes_routes(app):
    @app.get("/cadastros/clientes")
    @perfil_permitido("gerencia", "pcp", "expedicao")
    def clientes():
        return render_template("clientes.html", clientes=listar_clientes(
            request.args.get("busca", ""), request.args.get("status", "Todos")
        ), busca=request.args.get("busca", ""), status=request.args.get("status", "Todos"))

    @app.route("/cadastros/clientes/novo", methods=["GET", "POST"])
    @perfil_permitido("gerencia", "pcp")
    def novo_cliente():
        if request.method == "POST":
            try:
                cliente_id = salvar_cliente(request.form)
                flash("Cliente cadastrado com auditoria.")
                return redirect(url_for("editar_cliente", cliente_id=cliente_id))
            except (ValueError, PermissionError) as erro:
                flash(str(erro))
        return render_template("cliente_form.html", cliente=None, eventos=[])

    @app.route("/cadastros/clientes/<int:cliente_id>", methods=["GET", "POST"])
    @perfil_permitido("gerencia", "pcp", "expedicao")
    def editar_cliente(cliente_id):
        cliente = buscar_cliente(cliente_id)
        if not cliente:
            flash("Cliente não encontrado.")
            return redirect(url_for("clientes"))
        if request.method == "POST":
            try:
                salvar_cliente(request.form, cliente_id)
                flash("Cliente atualizado com auditoria.")
                return redirect(url_for("editar_cliente", cliente_id=cliente_id))
            except (ValueError, PermissionError) as erro:
                flash(str(erro))
        return render_template("cliente_form.html", cliente=cliente,
                               eventos=historico_cliente(cliente_id),
                               somente_leitura=session.get("perfil") == "expedicao")

    @app.post("/cadastros/clientes/<int:cliente_id>/status")
    @perfil_permitido("gerencia")
    def status_cliente(cliente_id):
        try:
            alterar_status(cliente_id, request.form.get("status"))
            flash("Status do cliente atualizado.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("clientes"))
