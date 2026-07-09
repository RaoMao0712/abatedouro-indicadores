"""Rotas da DRE Gerencial."""

from datetime import datetime

from flask import render_template, request, send_file

from modules.auth.decorators import perfil_permitido

from .services import buscar_dados_dre_gerencial, gerar_excel_dre_gerencial


def register_dre_routes(app, integracoes=None):
    @app.route("/dre-gerencial/exportar-excel")
    @perfil_permitido("pcp")
    def exportar_dre_gerencial_excel():
        competencia = request.args.get("competencia") or datetime.now().strftime("%Y-%m")
        dados = buscar_dados_dre_gerencial(competencia)
        arquivo = gerar_excel_dre_gerencial(competencia, dados)

        nome_arquivo = f"DRE_Gerencial_{competencia}.xlsx"

        return send_file(
            arquivo,
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    @app.route("/dre-gerencial")
    @perfil_permitido("pcp")
    def dre_gerencial():
        competencia = request.args.get("competencia") or datetime.now().strftime("%Y-%m")
        dados = buscar_dados_dre_gerencial(competencia)

        return render_template(
            "dre_gerencial.html",
            competencia=competencia,
            receita_bruta=dados["receita_bruta"],
            deducoes_receita=dados["deducoes_receita"],
            receita_operacional_liquida=dados["receita_operacional_liquida"],
            vendas_por_sku=dados["vendas_por_sku"],
            cmv_total=dados["cmv_total"],
            cmv_percentual=dados["cmv_percentual"],
            cmv_por_sku=dados["cmv_por_sku"],
            margem_bruta=dados["margem_bruta"],
            margem_bruta_percentual=dados["margem_bruta_percentual"],
            custos_operacionais_total=dados["custos_operacionais_total"],
            custos_operacionais_percentual=dados["custos_operacionais_percentual"],
            linhas_custos=dados["linhas_custos"],
            linhas_custos_executivas=dados.get("linhas_custos_executivas", dados["linhas_custos"]),
            despesas_grafico=dados.get("despesas_grafico", {}),
            resultado_operacional=dados["resultado_operacional"],
            resultado_nao_operacional=dados["resultado_nao_operacional"],
            resultado_gerencial_periodo=dados["resultado_gerencial_periodo"],
            margem_operacional_percentual=dados["margem_operacional_percentual"]
        )
