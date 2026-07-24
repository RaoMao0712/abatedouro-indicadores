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

    @app.route("/cadastros/veiculos", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def cadastro_veiculos_manutencao():
        if request.method == "POST":
            try:
                manutencao_service.salvar_veiculo_manutencao(request.form)
                flash("Veiculo cadastrado com sucesso.")
            except Exception as erro:
                flash(str(erro))

            return redirect(url_for("cadastro_veiculos_manutencao"))

        return render_template(
            "cadastro_veiculos.html",
            **manutencao_service.preparar_contexto_cadastro_veiculos(request.args)
        )

    @app.route("/cadastros/veiculos/<int:veiculo_id>/editar", methods=["POST"])
    @perfil_permitido("pcp")
    def editar_veiculo_manutencao(veiculo_id):
        try:
            manutencao_service.atualizar_veiculo_manutencao(veiculo_id, request.form)
            flash("Veiculo atualizado com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("cadastro_veiculos_manutencao", busca=request.form.get("busca", "")))

    @app.route("/cadastros/veiculos/<int:veiculo_id>/inativar", methods=["POST"])
    @perfil_permitido("pcp")
    def inativar_veiculo_manutencao(veiculo_id):
        try:
            manutencao_service.inativar_veiculo_manutencao(veiculo_id)
            flash("Veiculo inativado com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("cadastro_veiculos_manutencao", busca=request.form.get("busca", "")))

    @app.route("/manutencao", methods=["GET", "POST"])
    @perfil_permitido("qualidade", "producao", "pcp", "manutencao", "gerencia")
    def manutencao():
        if request.method == "POST":
            try:
                manutencao_service.salvar_ordem_manutencao(
                    request.form,
                    session.get("usuario_id", 0),
                    session.get("nome", "Usuario"),
                    session.get("perfil", ""),
                )
                flash("Ordem de manutencao aberta com sucesso.")
            except Exception as erro:
                flash(str(erro))

            return redirect(url_for("manutencao", aba="abrir"))

        return render_template(
            "manutencao.html",
            **manutencao_service.preparar_contexto_manutencao(request.args)
        )

    @app.route("/manutencao/ordem/<int:ordem_id>/atualizar", methods=["POST"])
    @perfil_permitido("manutencao", "gerencia")
    def atualizar_ordem_manutencao_rota(ordem_id):
        try:
            manutencao_service.atualizar_ordem_manutencao(
                ordem_id,
                request.form,
                session.get("usuario_id", 0),
                session.get("nome", "Sistema"),
                session.get("perfil", ""),
            )
            flash("Ordem de manutencao atualizada com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("visualizar_ordem_manutencao", ordem_id=ordem_id))

    @app.route("/manutencao/ordem/<int:ordem_id>/recursos", methods=["POST"])
    @perfil_permitido("qualidade", "pcp", "manutencao", "gerencia")
    def salvar_recursos_ordem_manutencao_rota(ordem_id):
        try:
            manutencao_service.salvar_recursos_ordem_manutencao(
                ordem_id,
                request.form,
                session.get("perfil", ""),
                session.get("usuario_id", 0),
                session.get("nome", "Sistema"),
            )
            flash("Lista de materiais e terceiros atualizada com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("visualizar_ordem_manutencao", ordem_id=ordem_id))

    @app.route("/manutencao/ordem/<int:ordem_id>/cancelar", methods=["POST"])
    @perfil_permitido("manutencao", "gerencia")
    def cancelar_ordem_manutencao_rota(ordem_id):
        try:
            manutencao_service.cancelar_ordem_manutencao(
                ordem_id,
                request.form.get("motivo_cancelamento", ""),
                session.get("usuario_id", 0),
                session.get("nome", "Sistema"),
                session.get("perfil", ""),
            )
            flash("Ordem de servico cancelada com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("visualizar_ordem_manutencao", ordem_id=ordem_id))

    @app.route("/manutencao/ordem/<int:ordem_id>/salvar", methods=["POST"])
    @perfil_permitido("qualidade", "pcp", "manutencao", "gerencia")
    def salvar_ficha_ordem_manutencao_rota(ordem_id):
        try:
            manutencao_service.salvar_ficha_ordem_manutencao(
                ordem_id,
                request.form,
                session.get("usuario_id", 0),
                session.get("nome", "Sistema"),
                session.get("perfil", ""),
            )
            flash("Ordem de servico atualizada com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("visualizar_ordem_manutencao", ordem_id=ordem_id))

    @app.route("/manutencao/ordem/<int:ordem_id>/recursos/painel", methods=["POST"])
    @perfil_permitido("qualidade", "pcp", "manutencao", "gerencia")
    def salvar_recursos_ordem_manutencao_painel(ordem_id):
        try:
            manutencao_service.salvar_recursos_ordem_manutencao(
                ordem_id,
                request.form,
                session.get("perfil", ""),
                session.get("usuario_id", 0),
                session.get("nome", "Sistema"),
            )
            flash("Lista de materiais e terceiros atualizada com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for(
            "manutencao",
            aba="materiais",
            status=request.form.get("status_filtro", "Todos"),
            equipamento_id=request.form.get("equipamento_filtro", ""),
            tipo_objeto=request.form.get("tipo_objeto_filtro", "Todos"),
            veiculo_id=request.form.get("veiculo_filtro", ""),
            setor=request.form.get("setor_filtro", ""),
            responsavel=request.form.get("responsavel_filtro", ""),
            prioridade=request.form.get("prioridade_filtro", "Todos"),
            pesquisa=request.form.get("pesquisa_filtro", ""),
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
            equipamentos=manutencao_service.buscar_equipamentos_ativos_manutencao(),
            tipos=manutencao_service.TIPOS_MANUTENCAO,
            hoje=__import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        )

    @app.route("/manutencao/ordem/<int:ordem_id>")
    @perfil_permitido("qualidade", "pcp", "producao", "manutencao", "gerencia")
    def visualizar_ordem_manutencao(ordem_id):
        ordem = manutencao_repo.buscar_ordem_por_id(ordem_id)
        if not ordem:
            flash("Ordem de manutencao nao encontrada.")
            return redirect(url_for("sgi_qualidade"))
        verificacao_id = None
        if ordem["sgi_nc_id"]:
            from modules.qualidade import repositories as qualidade_repo
            nc = qualidade_repo.buscar_nc(ordem["sgi_nc_id"])
            verificacao_id = nc["verificacao_id"] if nc else None
        recursos_por_ordem = manutencao_repo.listar_recursos_por_ordens([ordem_id])
        try:
            from modules.almoxarifado.services import buscar_insumos_almoxarifado
            insumos_manutencao = buscar_insumos_almoxarifado("Todas", "Sim", "")
        except Exception:
            insumos_manutencao = []
        return render_template(
            "manutencao_ordem_detalhe.html",
            ordem=ordem,
            recursos=recursos_por_ordem.get(str(ordem_id), []),
            eventos=manutencao_repo.listar_eventos_ordem(ordem_id),
            verificacao_id=verificacao_id,
            tipos_recurso=manutencao_service.TIPOS_RECURSO_ORDEM,
            status_recurso=manutencao_service.STATUS_RECURSO_ORDEM,
            status_opcoes=manutencao_service.STATUS_MANUTENCAO,
            tipos=manutencao_service.TIPOS_MANUTENCAO,
            prioridades=manutencao_service.PRIORIDADES_MANUTENCAO,
            insumos_manutencao=insumos_manutencao,
            perfis_materiais=manutencao_service.PERFIS_MATERIAIS_OS,
            perfis_cancelamento=manutencao_service.PERFIS_CANCELAMENTO_OS,
            perfis_dados_gerais=manutencao_service.PERFIS_DADOS_GERAIS_OS,
        )
