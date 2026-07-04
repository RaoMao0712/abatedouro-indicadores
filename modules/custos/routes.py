"""Rotas do modulo de Custos."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from modules.auth.decorators import perfil_permitido

from .services import (
    CATEGORIAS_CUSTOS,
    buscar_custo_mensal_por_id,
    buscar_custos_mensais,
    buscar_parametros_custos,
    salvar_custo_mensal,
    salvar_custos_mensais_lote,
    salvar_parametros_custos,
    atualizar_custo_mensal as atualizar_custo_mensal_service,
    excluir_custo_mensal as excluir_custo_mensal_service,
)


def register_custos_routes(app):

    @app.route("/custos", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def custos():
        if request.method == "POST":
            acao = request.form.get("acao")

            try:
                if acao == "salvar_parametros":
                    salvar_parametros_custos(request.form)
                    flash("Parâmetros de CMV atualizados com sucesso.")

                elif acao == "salvar_custo_mensal":
                    salvar_custo_mensal(request.form)
                    flash("Custo mensal cadastrado com sucesso.")

                elif acao == "salvar_custos_lote":
                    total_linhas = salvar_custos_mensais_lote(request.form)
                    flash(f"{total_linhas} custos mensais cadastrados com sucesso.")

            except ValueError as erro:
                flash(str(erro) or "Verifique os valores informados. Use apenas números nos campos de custo.")

            return redirect(url_for("custos"))

        categorias_custos = CATEGORIAS_CUSTOS

        competencia_atual = datetime.now().strftime("%Y-%m")
        competencia_inicio = request.args.get("competencia_inicio") or competencia_atual
        competencia_fim = request.args.get("competencia_fim") or competencia_atual
        categoria_filtro = request.args.get("categoria") or "Todas"
        custos_filtrados = buscar_custos_mensais(
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            categoria=categoria_filtro
        )
        total_custos_filtrados = sum(float(item["valor"] or 0) for item in custos_filtrados)

        return render_template(
            "custos.html",
            parametros=buscar_parametros_custos(),
            custos_mensais=custos_filtrados,
            categorias_custos=categorias_custos,
            competencia_atual=competencia_atual,
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            categoria_filtro=categoria_filtro,
            total_custos_filtrados=total_custos_filtrados
        )

    @app.route("/custos/mensal/<int:custo_id>/editar", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def editar_custo_mensal(custo_id):
        custo = buscar_custo_mensal_por_id(custo_id)

        if not custo:
            flash("Custo mensal não encontrado.")
            return redirect(url_for("custos"))

        categorias_custos = CATEGORIAS_CUSTOS

        if request.method == "POST":
            try:
                atualizar_custo_mensal_service(custo_id, request.form)
                flash("Custo mensal atualizado com sucesso.")
                return redirect(url_for("custos"))
            except ValueError:
                flash("Verifique o valor informado. Use apenas números no campo de valor.")

        return render_template(
            "editar_custo_mensal.html",
            custo=custo,
            categorias_custos=categorias_custos
        )


    @app.route("/custos/mensal/<int:custo_id>/excluir", methods=["POST"])
    @perfil_permitido("pcp")
    def excluir_custo_mensal(custo_id):
        if not buscar_custo_mensal_por_id(custo_id):
            flash("Custo mensal não encontrado.")
            return redirect(url_for("custos"))

        excluir_custo_mensal_service(custo_id)

        flash("Custo mensal excluído com sucesso.")
        return redirect(url_for("custos"))
