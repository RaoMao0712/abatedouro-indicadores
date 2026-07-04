"""Rotas de relatorios gerenciais."""

from datetime import datetime

from flask import render_template, request

from modules.auth.decorators import perfil_permitido

from .services import buscar_dados_relatorio_custos


def register_relatorios_routes(app):

    @app.route("/relatorio-custos")
    @perfil_permitido("pcp")
    def relatorio_custos():
        agora = datetime.now()
        competencia_fim = request.args.get("competencia_fim") or agora.strftime("%Y-%m")

        seis_meses_atras = agora

        for _ in range(5):
            if seis_meses_atras.month == 1:
                seis_meses_atras = seis_meses_atras.replace(
                    year=seis_meses_atras.year - 1,
                    month=12
                )
            else:
                seis_meses_atras = seis_meses_atras.replace(
                    month=seis_meses_atras.month - 1
                )

        competencia_inicio = (
            request.args.get("competencia_inicio")
            or seis_meses_atras.strftime("%Y-%m")
        )

        if competencia_inicio > competencia_fim:
            competencia_inicio, competencia_fim = competencia_fim, competencia_inicio

        categoria_filtro = request.args.get("categoria") or "Todas"

        dados = buscar_dados_relatorio_custos(
            competencia_inicio,
            competencia_fim,
            categoria_filtro
        )

        return render_template(
            "relatorio_custos.html",
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            categoria_filtro=categoria_filtro,
            categorias_custos=dados["categorias_disponiveis"],
            competencias=dados["competencias"],
            datasets=dados["datasets"],
            custo_total=dados["custo_total"],
            media_mensal=dados["media_mensal"],
            maior_categoria=dados["maior_categoria"],
            valor_maior_categoria=dados["valor_maior_categoria"],
            maior_crescimento_categoria=dados["maior_crescimento_categoria"],
            maior_crescimento_valor=dados["maior_crescimento_valor"],
            resumo_categorias=dados["resumo_categorias"]
        )
