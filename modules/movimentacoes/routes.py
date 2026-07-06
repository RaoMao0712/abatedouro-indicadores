"""Rotas de Movimentacoes com compatibilidade para URLs antigas do Financeiro."""

from datetime import datetime

from flask import flash, redirect, render_template, request, send_file, url_for

from modules.auth.decorators import perfil_permitido

from .services import (
    CATEGORIAS_FINANCEIRAS_ENTRADA,
    CATEGORIAS_FINANCEIRAS_SAIDA,
    FORMAS_PAGAMENTO_FINANCEIRO,
    STATUS_FINANCEIRO,
    STATUS_FINANCEIRO_FILTRO,
    agrupar_fluxo_por_dia,
    atualizar_movimentacao_financeira,
    buscar_movimentacao_financeira_por_id,
    buscar_movimentacoes_financeiras,
    buscar_pendencias_classificacao,
    calcular_resumo_financeiro,
    criar_tabela_movimentacoes_financeiras,
    excluir_movimentacao_financeira,
    gerar_excel_auditoria_financeira,
    importar_movimentacoes_financeiras_excel,
    montar_contexto_auditoria_financeira,
    reclassificar_movimentacoes,
    salvar_movimentacao_financeira,
)


def register_movimentacoes_routes(app):

    def destino_movimentacao_por_tipo(tipo):
        if tipo == "Saída":
            return "movimentacoes_despesas"
        return "movimentacoes_entradas"


    def contexto_movimentacoes(visao, tipo_movimentacao=None):
        criar_tabela_movimentacoes_financeiras()

        agora = datetime.now()
        hoje = agora.strftime("%Y-%m-%d")
        primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

        data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
        data_fim = request.args.get("data_fim") or hoje
        status_filtro = request.args.get("status") or "Todos"
        tipo_filtro = tipo_movimentacao or request.args.get("tipo") or "Todos"

        movimentacoes = buscar_movimentacoes_financeiras(
            data_inicio,
            data_fim,
            tipo_filtro,
            status_filtro
        )

        return {
            "visao": visao,
            "hoje": hoje,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "tipo_filtro": tipo_filtro,
            "tipo_padrao": tipo_movimentacao or "Entrada",
            "status_filtro": status_filtro,
            "movimentacoes": movimentacoes,
            "resumo": calcular_resumo_financeiro(movimentacoes),
            "fluxo_diario": agrupar_fluxo_por_dia(movimentacoes),
            "categorias_entrada": CATEGORIAS_FINANCEIRAS_ENTRADA,
            "categorias_saida": CATEGORIAS_FINANCEIRAS_SAIDA,
            "categorias_lancamento": CATEGORIAS_FINANCEIRAS_ENTRADA if tipo_movimentacao == "Entrada" else CATEGORIAS_FINANCEIRAS_SAIDA,
            "formas_pagamento": FORMAS_PAGAMENTO_FINANCEIRO,
            "status_opcoes": STATUS_FINANCEIRO_FILTRO
        }


    def salvar_movimentacao_por_visao(tipo_movimentacao, endpoint):
        form = request.form.copy()
        form["tipo"] = tipo_movimentacao

        try:
            salvar_movimentacao_financeira(form)
            flash("Movimentacao lancada com sucesso.")
        except Exception as erro:
            flash(f"Erro ao salvar movimentacao: {erro}")

        return redirect(url_for(endpoint))


    @app.route("/financeiro")
    @perfil_permitido("pcp")
    def financeiro():
        return redirect(url_for("movimentacoes_entradas"))


    @app.route("/movimentacoes")
    @perfil_permitido("pcp")
    def movimentacoes():
        return redirect(url_for("movimentacoes_entradas"))


    @app.route("/movimentacoes/entradas", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def movimentacoes_entradas():
        if request.method == "POST":
            return salvar_movimentacao_por_visao("Entrada", "movimentacoes_entradas")

        return render_template(
            "financeiro.html",
            **contexto_movimentacoes("entradas", "Entrada")
        )


    @app.route("/movimentacoes/despesas", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def movimentacoes_despesas():
        if request.method == "POST":
            return salvar_movimentacao_por_visao("Saída", "movimentacoes_despesas")

        return render_template(
            "financeiro.html",
            **contexto_movimentacoes("despesas", "Saída")
        )


    @app.route("/movimentacoes/estoque")
    @perfil_permitido("pcp")
    def movimentacoes_estoque():
        return render_template(
            "financeiro.html",
            **contexto_movimentacoes("estoque")
        )


    @app.route("/movimentacoes/importar", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def importar_movimentacoes_financeiras():
        resultado = None

        if request.method == "POST":
            arquivo = request.files.get("arquivo")

            if not arquivo or not arquivo.filename:
                flash("Selecione uma planilha para importar.")
            else:
                try:
                    resultado = importar_movimentacoes_financeiras_excel(arquivo)
                    flash("Importacao de movimentacoes concluida.")
                except Exception as erro:
                    flash(f"Erro ao importar movimentacoes: {erro}")

        return render_template(
            "movimentacoes_importar.html",
            resultado=resultado,
        )


    @app.route("/movimentacoes/pendencias")
    @perfil_permitido("pcp")
    def movimentacoes_pendencias():
        return render_template(
            "movimentacoes_pendencias.html",
            pendencias=buscar_pendencias_classificacao(),
        )


    @app.route("/movimentacoes/auditoria", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def movimentacoes_auditoria():
        if request.method == "POST":
            try:
                atualizadas = reclassificar_movimentacoes(
                    request.form.getlist("movimentacao_id"),
                    request.form.get("nova_categoria", "")
                )
                flash(f"{atualizadas} movimentacao(oes) reclassificada(s) com sucesso.")
            except Exception as erro:
                flash(f"Erro ao reclassificar movimentacoes: {erro}")
            return redirect(url_for("movimentacoes_auditoria", **request.args))

        return render_template(
            "movimentacoes_auditoria.html",
            **montar_contexto_auditoria_financeira(request.args),
            query_string=request.query_string.decode("utf-8"),
        )


    @app.route("/movimentacoes/auditoria/exportar")
    @perfil_permitido("pcp")
    def movimentacoes_auditoria_exportar():
        contexto = montar_contexto_auditoria_financeira(request.args)
        arquivo = gerar_excel_auditoria_financeira(contexto)
        return send_file(
            arquivo,
            as_attachment=True,
            download_name="auditoria_financeira.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


    @app.route("/financeiro/editar/<int:movimentacao_id>", methods=["GET", "POST"])
    @app.route("/movimentacoes/editar/<int:movimentacao_id>", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def editar_movimentacao_financeira(movimentacao_id):
        movimentacao = buscar_movimentacao_financeira_por_id(movimentacao_id)

        if not movimentacao:
            flash("Movimentacao nao encontrada.")
            return redirect(url_for("financeiro"))

        if request.method == "POST":
            try:
                atualizar_movimentacao_financeira(movimentacao_id, request.form)
                flash("Movimentacao atualizada com sucesso.")
                return redirect(url_for(destino_movimentacao_por_tipo(request.form.get("tipo", movimentacao["tipo"]))))
            except Exception as erro:
                flash(f"Erro ao atualizar movimentacao: {erro}")

        return render_template(
            "financeiro_editar.html",
            movimentacao=movimentacao,
            categorias_entrada=CATEGORIAS_FINANCEIRAS_ENTRADA,
            categorias_saida=CATEGORIAS_FINANCEIRAS_SAIDA,
            formas_pagamento=FORMAS_PAGAMENTO_FINANCEIRO,
            status_opcoes=STATUS_FINANCEIRO,
            voltar_endpoint=destino_movimentacao_por_tipo(movimentacao["tipo"])
        )


    @app.route("/financeiro/excluir/<int:movimentacao_id>", methods=["POST"])
    @app.route("/movimentacoes/excluir/<int:movimentacao_id>", methods=["POST"])
    @perfil_permitido("pcp")
    def excluir_movimentacao_financeira_rota(movimentacao_id):
        movimentacao = buscar_movimentacao_financeira_por_id(movimentacao_id)
        excluir_movimentacao_financeira(movimentacao_id)
        flash("Movimentacao excluida com sucesso.")
        return redirect(url_for(destino_movimentacao_por_tipo(movimentacao["tipo"] if movimentacao else "Entrada")))
