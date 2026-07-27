"""Rotas da Engenharia de Produtos com leitura e escrita separadas por perfil."""

from flask import flash, redirect, render_template, request, session, url_for

from modules.auth.decorators import perfil_permitido

from . import services


PERFIS_LEITURA = ("pcp", "gerencia", "producao", "qualidade")
PERFIS_ESCRITA = ("pcp", "gerencia")


def _usuario():
    return {
        "id": session.get("usuario_id"),
        "nome": session.get("nome") or session.get("perfil") or "Usuário",
    }


def _pode_editar():
    return session.get("perfil") in {"admin", "pcp", "gerencia"}


def register_engenharia_produtos_routes(app):
    @app.route("/receitas-sku", methods=["GET"], endpoint="receitas_sku")
    @app.route("/engenharia-produtos", methods=["GET"], endpoint="engenharia_produtos")
    @perfil_permitido(*PERFIS_LEITURA)
    def catalogo():
        filtros = {
            "status": request.args.get("status", ""),
            "tipo": request.args.get("tipo", ""),
            "unidade": request.args.get("unidade", ""),
            "estrutura": request.args.get("estrutura", ""),
            "pesquisa": (request.args.get("pesquisa") or "").strip(),
        }
        produtos, resumo = services.listar_catalogo(filtros)
        return render_template(
            "engenharia_produtos/catalogo.html",
            produtos=produtos,
            resumo=resumo,
            filtros=filtros,
            tipos_produto=services.TIPOS_PRODUTO,
            unidades=services.UNIDADES,
            pode_editar=_pode_editar(),
        )

    @app.route("/engenharia-produtos/novo", methods=["GET", "POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def novo_produto():
        if request.method == "POST":
            try:
                produto_id = services.salvar_produto(request.form, _usuario())
                flash("Produto cadastrado com sucesso.")
                return redirect(url_for("detalhe_produto", produto_id=produto_id))
            except (ValueError, TypeError) as erro:
                flash(str(erro))
        return render_template(
            "engenharia_produtos/produto_form.html",
            produto=None,
            tipos_produto=services.TIPOS_PRODUTO,
            unidades=services.UNIDADES,
        )

    @app.route("/engenharia-produtos/<int:produto_id>")
    @perfil_permitido(*PERFIS_LEITURA)
    def detalhe_produto(produto_id):
        try:
            dados = services.dados_detalhe(produto_id)
        except ValueError as erro:
            flash(str(erro))
            return redirect(url_for("engenharia_produtos"))
        return render_template(
            "engenharia_produtos/detalhe.html",
            **dados,
            tipos_produto=services.TIPOS_PRODUTO,
            tipos_consumo=services.TIPOS_CONSUMO,
            pode_editar=_pode_editar(),
        )

    @app.route("/engenharia-produtos/<int:produto_id>/editar", methods=["GET", "POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def editar_produto(produto_id):
        try:
            produto = services.obter_produto(produto_id)
            if request.method == "POST":
                services.salvar_produto(request.form, _usuario(), produto_id)
                flash("Produto atualizado com sucesso.")
                return redirect(url_for("detalhe_produto", produto_id=produto_id))
        except (ValueError, TypeError) as erro:
            flash(str(erro))
            return redirect(url_for("engenharia_produtos"))
        return render_template(
            "engenharia_produtos/produto_form.html",
            produto=produto,
            tipos_produto=services.TIPOS_PRODUTO,
            unidades=services.UNIDADES,
        )

    @app.route("/engenharia-produtos/<int:produto_id>/status", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def status_produto(produto_id):
        try:
            status = services.alternar_status_produto(produto_id, _usuario())
            flash(f"Produto {'ativado' if status == 'Sim' else 'inativado'} com sucesso.")
        except ValueError as erro:
            flash(str(erro))
        return redirect(url_for("detalhe_produto", produto_id=produto_id))

    @app.route("/engenharia-produtos/processos", methods=["GET", "POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def processos_produtivos():
        if request.method == "POST":
            try:
                services.salvar_processo(request.form, _usuario())
                flash("Processo cadastrado com sucesso.")
                return redirect(url_for("processos_produtivos"))
            except (ValueError, TypeError) as erro:
                flash(str(erro))
        return render_template(
            "engenharia_produtos/processos.html",
            processos=services.listar_processos(),
        )

    @app.route("/engenharia-produtos/<int:produto_id>/estrutura/novo", methods=["GET", "POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def novo_item_estrutura(produto_id):
        try:
            produto = services.obter_produto(produto_id)
            if request.method == "POST":
                services.salvar_item_estrutura(request.form, _usuario(), produto_id)
                flash("Item adicionado à estrutura com sucesso.")
                return redirect(url_for("detalhe_produto", produto_id=produto_id))
        except (ValueError, TypeError) as erro:
            flash(str(erro))
            if request.method == "POST":
                produto = services.obter_produto(produto_id)
            else:
                return redirect(url_for("engenharia_produtos"))
        return render_template(
            "engenharia_produtos/item_form.html",
            produto=produto,
            item=None,
            insumos=services.insumos_ativos(),
            tipos_consumo=services.TIPOS_CONSUMO,
            unidades=services.UNIDADES,
        )

    @app.route("/engenharia-produtos/<int:produto_id>/estrutura/<int:item_id>/editar", methods=["GET", "POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def editar_item_estrutura(produto_id, item_id):
        try:
            produto = services.obter_produto(produto_id)
            item = services.repo.buscar_item(item_id)
            if not item or item["sku_id"] != produto_id:
                raise ValueError("Item da estrutura não encontrado.")
            if request.method == "POST":
                services.salvar_item_estrutura(request.form, _usuario(), produto_id, item_id)
                flash("Item da estrutura atualizado com sucesso.")
                return redirect(url_for("detalhe_produto", produto_id=produto_id))
        except (ValueError, TypeError) as erro:
            flash(str(erro))
            return redirect(url_for("detalhe_produto", produto_id=produto_id))
        return render_template(
            "engenharia_produtos/item_form.html",
            produto=produto,
            item=item,
            insumos=services.insumos_ativos(),
            tipos_consumo=services.TIPOS_CONSUMO,
            unidades=services.UNIDADES,
        )

    @app.route("/engenharia-produtos/<int:produto_id>/estrutura/<int:item_id>/status", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def status_item_estrutura(produto_id, item_id):
        try:
            status = services.alternar_status_item(produto_id, item_id, _usuario())
            flash(f"Item {'ativado' if status == 'Ativo' else 'inativado'} com sucesso.")
        except ValueError as erro:
            flash(str(erro))
        return redirect(url_for("detalhe_produto", produto_id=produto_id))
