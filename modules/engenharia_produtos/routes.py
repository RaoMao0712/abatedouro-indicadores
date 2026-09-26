"""Rotas da Engenharia de Produtos com leitura e escrita separadas por perfil."""

import json

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from modules.auth.decorators import perfil_permitido

from . import services
from . import fundacao
from . import representacao_legada
from . import reconciliacao
from . import prontidao


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
    @app.get("/engenharia-produtos/prontidao")
    @perfil_permitido(*PERFIS_LEITURA)
    def prontidao_skus():
        filtros = {
            "sku": (request.args.get("sku") or "").strip(),
            "estado": (request.args.get("estado") or "").strip(),
        }
        avaliacoes, historico = prontidao.listar_avaliacoes(filtros)
        return render_template(
            "engenharia_produtos/prontidao.html", avaliacoes=avaliacoes,
            historico=historico, filtros=filtros,
            estados=sorted(prontidao.ESTADOS),
            skus=sorted(prontidao.SKUS_OPERACIONAIS_LEGADOS),
            pode_editar=_pode_editar(),
        )

    @app.post("/engenharia-produtos/prontidao/<path:sku>/recalcular")
    @perfil_permitido(*PERFIS_ESCRITA)
    def prontidao_sku_recalcular(sku):
        try:
            prontidao.recalcular(sku, _usuario())
            flash("Avaliação de prontidão recalculada; a autoridade permanece LEGADO.")
        except Exception as erro:
            flash(f"Falha no cálculo de prontidão: {erro}")
        return redirect(url_for("prontidao_skus", sku=sku))

    @app.route("/engenharia-produtos/reconciliacoes", methods=["GET"])
    @perfil_permitido(*PERFIS_LEITURA)
    def reconciliacoes_sombra():
        filtros = {
            "op_id": request.args.get("op_id", type=int),
            "sku": (request.args.get("sku") or "").strip(),
            "resultado": (request.args.get("resultado") or "").strip(),
            "inicio": (request.args.get("inicio") or "").strip(),
            "fim": (request.args.get("fim") or "").strip(),
            "estado_tecnico": (request.args.get("estado_tecnico") or "").strip(),
        }
        registros, resumo = reconciliacao.listar_reconciliacoes(filtros)
        execucoes, resumo_tecnico = reconciliacao.listar_execucoes_tecnicas(filtros)
        resumo.update({
            "pendentes_tecnicos": resumo_tecnico["pendentes"],
            "erros_tecnicos": resumo_tecnico["erros"],
        })
        for registro in registros:
            registro["dimensoes"] = json.loads(registro["dimensoes_json"])
            registro["divergencias"] = json.loads(registro["divergencias_json"])
        return render_template(
            "engenharia_produtos/reconciliacoes.html", registros=registros,
            resumo=resumo, filtros=filtros, resultados=sorted(reconciliacao.RESULTADOS),
            execucoes=execucoes, estados_tecnicos=["PENDENTE", "PROCESSANDO", "SUCESSO", "ERRO"],
        )

    @app.post("/engenharia-produtos/reconciliacoes/<int:op_id>/reexecutar")
    @perfil_permitido(*PERFIS_ESCRITA)
    def reconciliacao_sombra_reexecutar(op_id):
        resultado = reconciliacao.executar_reconciliacao_segura(op_id, "MANUAL")
        if resultado["status"] == "SUCESSO":
            flash("Reconciliação reexecutada com sucesso.")
        else:
            flash("Reconciliação registrada como erro técnico; a OP não foi alterada.")
        return redirect(url_for("reconciliacoes_sombra", op_id=op_id))

    @app.post("/engenharia-produtos/reconciliacoes/reprocessar-pendentes")
    @perfil_permitido(*PERFIS_ESCRITA)
    def reconciliacao_sombra_reprocessar_pendentes():
        resultados = reconciliacao.reprocessar_pendentes(50)
        flash(f"{len(resultados)} reconciliação(ões) pendente(s) processada(s).")
        return redirect(url_for("reconciliacoes_sombra"))

    @app.route("/cadastros/fundacao-sku", methods=["GET"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_sku_listar():
        sku_id = request.args.get("sku_id", type=int)
        return jsonify(fundacao.listar_fundacao(sku_id))

    @app.route("/cadastros/fundacao-sku/representacao-legada", methods=["GET"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_sku_comparar_legados():
        return jsonify(representacao_legada.comparar_todos())

    @app.route("/cadastros/fundacao-sku/representacao-legada", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_sku_representar_legados():
        try:
            return jsonify(representacao_legada.aplicar(_usuario()["nome"])), 201
        except ValueError as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/skus/<int:sku_id>/versoes", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_sku_versao_criar(sku_id):
        try:
            return jsonify({"id": fundacao.criar_sku_versao(sku_id, request.get_json(silent=True) or request.form, _usuario())}), 201
        except (ValueError, KeyError) as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/etapas-catalogo", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_etapa_catalogo_criar():
        try:
            return jsonify({"id": fundacao.criar_etapa_catalogo(request.get_json(silent=True) or request.form, _usuario())}), 201
        except (ValueError, KeyError) as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/sku-versoes/<int:versao_id>/roteiros", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_roteiro_criar(versao_id):
        try:
            return jsonify({"id": fundacao.criar_roteiro_versao(versao_id, request.get_json(silent=True) or request.form, _usuario())}), 201
        except (ValueError, KeyError) as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/roteiros/<int:roteiro_id>/etapas", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_roteiro_etapa_criar(roteiro_id):
        try:
            return jsonify({"id": fundacao.adicionar_etapa(roteiro_id, request.get_json(silent=True) or request.form)}), 201
        except (ValueError, KeyError) as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/roteiro-etapas/<int:etapa_id>/insumos", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_roteiro_insumo_criar(etapa_id):
        try:
            return jsonify({"id": fundacao.adicionar_insumo(etapa_id, request.get_json(silent=True) or request.form)}), 201
        except (ValueError, KeyError) as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/sku-versoes/<int:versao_id>", methods=["PUT"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_sku_versao_editar(versao_id):
        try:
            fundacao.atualizar_sku_versao(versao_id, request.get_json() or {}, _usuario())
            return jsonify({"ok": True})
        except (ValueError, KeyError) as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/sku-versoes/<int:versao_id>/ativar", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_sku_versao_ativar(versao_id):
        try:
            fundacao.ativar_sku_versao(versao_id, _usuario())
            return jsonify({"ok": True})
        except ValueError as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/etapas-catalogo/<int:etapa_id>", methods=["PUT"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_etapa_catalogo_editar(etapa_id):
        try:
            fundacao.atualizar_etapa_catalogo(etapa_id, request.get_json() or {}, _usuario())
            return jsonify({"ok": True})
        except (ValueError, KeyError) as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/roteiros/<int:roteiro_id>", methods=["PUT"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_roteiro_editar(roteiro_id):
        try:
            fundacao.atualizar_roteiro(roteiro_id, request.get_json() or {}, _usuario())
            return jsonify({"ok": True})
        except (ValueError, KeyError) as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/roteiros/<int:roteiro_id>/ativar", methods=["POST"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_roteiro_ativar(roteiro_id):
        try:
            fundacao.ativar_roteiro(roteiro_id, _usuario())
            return jsonify({"ok": True})
        except ValueError as erro:
            return jsonify({"erro": str(erro)}), 400

    @app.route("/cadastros/roteiros/<int:roteiro_id>/etapas/<int:etapa_id>", methods=["DELETE"])
    @perfil_permitido(*PERFIS_ESCRITA)
    def fundacao_roteiro_etapa_excluir(roteiro_id, etapa_id):
        try:
            fundacao.excluir_etapa(roteiro_id, etapa_id)
            return jsonify({"ok": True})
        except ValueError as erro:
            return jsonify({"erro": str(erro)}), 400

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
