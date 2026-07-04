"""Rotas do modulo de Manutencao."""

from flask import flash, redirect, render_template, request, url_for

from modules.auth.decorators import perfil_permitido
from . import services as manutencao_service


def register_manutencao_routes(app):

    @app.route("/cadastros/equipamentos", methods=["GET", "POST"])
    @perfil_permitido("pcp", "producao")
    def cadastro_equipamentos_manutencao():
        if request.method == "POST":
            try:
                manutencao_service.salvar_equipamento_manutencao(request.form)
                flash("Equipamento cadastrado com sucesso.")
            except Exception as erro:
                flash(str(erro))

            return redirect(url_for("cadastro_equipamentos_manutencao"))

        return render_template(
            "cadastro_equipamentos.html",
            **manutencao_service.preparar_contexto_cadastro_equipamentos(request.args)
        )

    @app.route("/cadastros/equipamentos/<int:equipamento_id>/editar", methods=["POST"])
    @perfil_permitido("pcp", "producao")
    def editar_equipamento_manutencao(equipamento_id):
        try:
            manutencao_service.atualizar_equipamento_manutencao(equipamento_id, request.form)
            flash("Equipamento atualizado com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("cadastro_equipamentos_manutencao", busca=request.form.get("busca", "")))

    @app.route("/cadastros/equipamentos/<int:equipamento_id>/excluir", methods=["POST"])
    @perfil_permitido("pcp", "producao")
    def excluir_equipamento_manutencao(equipamento_id):
        try:
            manutencao_service.excluir_equipamento_manutencao(equipamento_id)
            flash("Equipamento removido com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("cadastro_equipamentos_manutencao", busca=request.form.get("busca", "")))

    @app.route("/manutencao", methods=["GET", "POST"])
    @perfil_permitido("pcp", "producao")
    def manutencao():
        if request.method == "POST":
            try:
                manutencao_service.salvar_ordem_manutencao(request.form)
                flash("Ordem de manutencao aberta com sucesso.")
            except Exception as erro:
                flash(str(erro))

            return redirect(url_for("manutencao"))

        return render_template(
            "manutencao.html",
            **manutencao_service.preparar_contexto_manutencao(request.args)
        )

    @app.route("/manutencao/ordem/<int:ordem_id>/atualizar", methods=["POST"])
    @perfil_permitido("pcp", "producao")
    def atualizar_ordem_manutencao_rota(ordem_id):
        try:
            manutencao_service.atualizar_ordem_manutencao(ordem_id, request.form)
            flash("Ordem de manutencao atualizada com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("manutencao"))

    @app.route("/manutencao/ordem/<int:ordem_id>/recursos", methods=["POST"])
    @perfil_permitido("pcp", "producao")
    def salvar_recursos_ordem_manutencao_rota(ordem_id):
        try:
            manutencao_service.salvar_recursos_ordem_manutencao(ordem_id, request.form)
            flash("Lista de materiais e terceiros atualizada com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for(
            "manutencao",
            status=request.form.get("status_filtro", "Todos"),
            equipamento_id=request.form.get("equipamento_filtro", ""),
        ))