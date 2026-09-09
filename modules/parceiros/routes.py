"""Rotas do Cadastro Mestre de Parceiros."""

from flask import flash, redirect, render_template, request, session, url_for

from modules.auth.decorators import perfil_permitido
from .services import (
    PAPEIS_VALIDOS, ROTULOS_PAPEIS, alterar_status, buscar_parceiro,
    historico_parceiro, listar_parceiros, salvar_parceiro,
)


def register_parceiros_routes(app):
    @app.get("/cadastros/parceiros")
    @perfil_permitido("gerencia", "pcp", "producao", "expedicao")
    def parceiros():
        filtros = {
            "busca": request.args.get("busca", ""),
            "status": request.args.get("status", "Todos"),
            "tipo_pessoa": request.args.get("tipo_pessoa", "Todos"),
            "papel": request.args.get("papel", "Todos"),
        }
        return render_template("parceiros.html", parceiros=listar_parceiros(**filtros),
                               rotulos_papeis=ROTULOS_PAPEIS, **filtros)

    @app.route("/cadastros/parceiros/novo", methods=["GET", "POST"])
    @perfil_permitido("gerencia", "pcp")
    def novo_parceiro():
        if request.method == "POST":
            try:
                parceiro_id = salvar_parceiro(request.form)
                flash("Parceiro cadastrado com auditoria.")
                return redirect(url_for("editar_parceiro", parceiro_id=parceiro_id))
            except (ValueError, PermissionError) as erro:
                flash(str(erro))
        return render_template("parceiro_form.html", parceiro=None, eventos=[],
                               papeis_validos=sorted(PAPEIS_VALIDOS), rotulos_papeis=ROTULOS_PAPEIS,
                               papeis_preselecionados={request.args.get("papel")} & PAPEIS_VALIDOS)

    @app.route("/cadastros/parceiros/<int:parceiro_id>", methods=["GET", "POST"])
    @perfil_permitido("gerencia", "pcp", "producao", "expedicao")
    def editar_parceiro(parceiro_id):
        parceiro = buscar_parceiro(parceiro_id)
        if not parceiro:
            flash("Parceiro não encontrado.")
            return redirect(url_for("parceiros"))
        somente_leitura = session.get("perfil") in {"producao", "expedicao"}
        if request.method == "POST" and not somente_leitura:
            try:
                salvar_parceiro(request.form, parceiro_id)
                flash("Parceiro atualizado com auditoria.")
                return redirect(url_for("editar_parceiro", parceiro_id=parceiro_id))
            except (ValueError, PermissionError) as erro:
                flash(str(erro))
            parceiro = buscar_parceiro(parceiro_id)
        return render_template("parceiro_form.html", parceiro=parceiro,
                               eventos=historico_parceiro(parceiro_id), somente_leitura=somente_leitura,
                               papeis_validos=sorted(PAPEIS_VALIDOS), rotulos_papeis=ROTULOS_PAPEIS)

    @app.post("/cadastros/parceiros/<int:parceiro_id>/status")
    @perfil_permitido("gerencia")
    def status_parceiro(parceiro_id):
        try:
            alterar_status(parceiro_id, request.form.get("status"))
            flash("Status do parceiro atualizado.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("parceiros"))
