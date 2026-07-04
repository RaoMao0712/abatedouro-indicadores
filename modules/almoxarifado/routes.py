"""Rotas do modulo de Almoxarifado."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from modules.auth.decorators import perfil_permitido

from .services import (
    CATEGORIAS_ALMOXARIFADO,
    UNIDADES_ALMOXARIFADO,
    atualizar_insumo_almoxarifado,
    buscar_insumo_almoxarifado_por_id,
    buscar_insumos_almoxarifado,
    buscar_lotes_almoxarifado,
    buscar_lotes_almoxarifado_filtrado,
    buscar_movimentacoes_almoxarifado,
    buscar_movimentacoes_almoxarifado_filtrado,
    buscar_saldos_almoxarifado,
    buscar_saldos_almoxarifado_filtrado,
    calcular_resumo_almoxarifado,
    calcular_resumo_estoque_almoxarifado,
    calcular_resumo_rastreabilidade,
    salvar_entrada_estoque_almoxarifado,
    salvar_insumo_almoxarifado,
)


def register_almoxarifado_routes(app):

    @app.route("/almoxarifado", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def almoxarifado():
        categoria_filtro = request.args.get("categoria") or "Todas"
        status_filtro = request.args.get("status") or "Todos"
        termo = request.args.get("termo") or ""

        if request.method == "POST":
            try:
                salvar_insumo_almoxarifado(request.form)
                flash("Insumo cadastrado com sucesso.")
                return redirect(url_for("almoxarifado"))
            except Exception as erro:
                flash(f"Erro ao cadastrar insumo: {erro}")

        insumos = buscar_insumos_almoxarifado(categoria_filtro, status_filtro, termo)
        resumo = calcular_resumo_almoxarifado(insumos)

        return render_template(
            "almoxarifado.html",
            insumos=insumos,
            resumo=resumo,
            categorias=CATEGORIAS_ALMOXARIFADO,
            unidades=UNIDADES_ALMOXARIFADO,
            categoria_filtro=categoria_filtro,
            status_filtro=status_filtro,
            termo=termo
        )


    @app.route("/almoxarifado/editar/<int:insumo_id>", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def editar_insumo_almoxarifado(insumo_id):
        insumo = buscar_insumo_almoxarifado_por_id(insumo_id)

        if not insumo:
            flash("Insumo não encontrado.")
            return redirect(url_for("almoxarifado"))

        if request.method == "POST":
            try:
                atualizar_insumo_almoxarifado(insumo_id, request.form)
                flash("Insumo atualizado com sucesso.")
                return redirect(url_for("almoxarifado"))
            except Exception as erro:
                flash(f"Erro ao atualizar insumo: {erro}")

        return render_template(
            "almoxarifado_editar.html",
            insumo=insumo,
            categorias=CATEGORIAS_ALMOXARIFADO,
            unidades=UNIDADES_ALMOXARIFADO
        )


    @app.route("/almoxarifado/entrada", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def entrada_estoque_almoxarifado():
        if request.method == "POST":
            try:
                salvar_entrada_estoque_almoxarifado(request.form)
                flash("Entrada de estoque registrada com sucesso.")
                return redirect(url_for("entrada_estoque_almoxarifado"))
            except Exception as erro:
                flash(f"Erro ao registrar entrada de estoque: {erro}")

        hoje = datetime.now().strftime("%Y-%m-%d")
        insumos = buscar_insumos_almoxarifado("Todas", "Sim", "")
        saldos = buscar_saldos_almoxarifado()
        lotes = buscar_lotes_almoxarifado()
        movimentacoes = buscar_movimentacoes_almoxarifado()
        resumo = calcular_resumo_estoque_almoxarifado(saldos)

        return render_template(
            "almoxarifado_entrada.html",
            hoje=hoje,
            insumos=insumos,
            saldos=saldos,
            lotes=lotes,
            movimentacoes=movimentacoes,
            resumo=resumo
        )



    @app.route("/almoxarifado/saldo")
    @perfil_permitido("pcp")
    def saldo_almoxarifado():
        categoria_filtro = request.args.get("categoria") or "Todas"
        termo = request.args.get("termo") or ""

        saldos = buscar_saldos_almoxarifado_filtrado(categoria_filtro, termo)
        resumo = calcular_resumo_estoque_almoxarifado(saldos)

        return render_template(
            "almoxarifado_saldo.html",
            saldos=saldos,
            resumo=resumo,
            categorias=CATEGORIAS_ALMOXARIFADO,
            categoria_filtro=categoria_filtro,
            termo=termo
        )


    @app.route("/almoxarifado/movimentacoes")
    @perfil_permitido("pcp")
    def movimentacoes_almoxarifado():
        agora = datetime.now()
        hoje = agora.strftime("%Y-%m-%d")
        primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

        data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
        data_fim = request.args.get("data_fim") or hoje
        tipo_filtro = request.args.get("tipo") or "Todos"
        termo = request.args.get("termo") or ""

        movimentacoes = buscar_movimentacoes_almoxarifado_filtrado(
            data_inicio,
            data_fim,
            tipo_filtro,
            termo
        )

        entradas = sum(float(item["valor_total"] or 0) for item in movimentacoes if item["tipo"] == "ENTRADA")
        saidas = sum(float(item["valor_total"] or 0) for item in movimentacoes if item["tipo"] == "SAIDA")

        resumo = {
            "total_movimentacoes": len(movimentacoes),
            "valor_entradas": round(entradas, 2),
            "valor_saidas": round(saidas, 2),
            "saldo_valor": round(entradas - saidas, 2)
        }

        return render_template(
            "almoxarifado_movimentacoes.html",
            movimentacoes=movimentacoes,
            resumo=resumo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            tipo_filtro=tipo_filtro,
            termo=termo
        )


    @app.route("/almoxarifado/rastreabilidade")
    @perfil_permitido("pcp")
    def rastreabilidade_almoxarifado():
        insumo_id = request.args.get("insumo_id") or ""
        status_filtro = request.args.get("status") or "Todos"
        termo = request.args.get("termo") or ""

        insumos = buscar_insumos_almoxarifado("Todas", "Sim", "")
        lotes = buscar_lotes_almoxarifado_filtrado(insumo_id, status_filtro, termo)
        resumo = calcular_resumo_rastreabilidade(lotes)

        return render_template(
            "almoxarifado_rastreabilidade.html",
            insumos=insumos,
            lotes=lotes,
            resumo=resumo,
            insumo_id=insumo_id,
            status_filtro=status_filtro,
            termo=termo
        )



    # ============================================================
    # MÓDULO RECEITAS DOS SKUS
