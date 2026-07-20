"""Rotas do modulo de Manutencao."""

from flask import flash, redirect, render_template, request, session, url_for

from modules.auth.decorators import perfil_permitido
from . import services as manutencao_service
from . import repositories as manutencao_repo


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
            manutencao_service.atualizar_ordem_manutencao(
                ordem_id, request.form, session.get("usuario_id", 0), session.get("nome", "Sistema"))
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

    @app.route("/manutencao/ordem/sgi/<int:nc_id>", methods=["GET", "POST"])
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def abrir_ordem_manutencao_sgi(nc_id):
        from modules.qualidade import repositories as qualidade_repo
        nc = qualidade_repo.buscar_nc(nc_id)
        if not nc:
            flash("Nao conformidade nao encontrada.")
            return redirect(url_for("sgi_qualidade"))
        if nc["ordem_id"]:
            flash("Esta NC ja possui ordem de manutencao vinculada.")
            return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=nc["verificacao_id"]))
        if request.method == "POST":
            try:
                ordem_id = manutencao_service.criar_ordem_por_nc(
                    nc, request.form, session.get("nome", "Usuario"))
                flash(f"Ordem de manutencao #{ordem_id} aberta e vinculada a NC.")
                return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=nc["verificacao_id"]))
            except Exception as erro:
                flash(str(erro))
        return render_template(
            "manutencao_ordem_sgi.html", nc=nc,
            equipamentos=manutencao_service.buscar_equipamentos_manutencao(),
            tipos=manutencao_service.TIPOS_MANUTENCAO,
            hoje=__import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        )

    @app.route("/manutencao/ordem/<int:ordem_id>")
    @perfil_permitido("qualidade", "pcp", "producao", "gerencia")
    def visualizar_ordem_manutencao(ordem_id):
        ordem = manutencao_repo.buscar_ordem_por_id(ordem_id)
        if not ordem:
            flash("Ordem de manutencao nao encontrada.")
            return redirect(url_for("sgi_qualidade"))
        equipamento = manutencao_service.buscar_equipamento_manutencao_por_id(ordem["equipamento_id"])
        verificacao_id = None
        if ordem["sgi_nc_id"]:
            from modules.qualidade import repositories as qualidade_repo
            nc = qualidade_repo.buscar_nc(ordem["sgi_nc_id"])
            verificacao_id = nc["verificacao_id"] if nc else None
        return render_template("manutencao_ordem_detalhe.html", ordem=ordem,
                               equipamento=equipamento, verificacao_id=verificacao_id)
