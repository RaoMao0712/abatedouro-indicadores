"""Rotas de relatorios gerenciais."""

from datetime import datetime

from flask import abort, render_template, request, send_file, url_for

from modules.auth.decorators import perfil_permitido

from .services import buscar_dados_relatorio_custos, filtrar_relatorios_oficiais
from .financeiro import (
    RELATORIOS_FINANCEIROS,
    gerar_excel_relatorio_financeiro,
    montar_contexto_relatorio_financeiro,
)
from .producao import (
    RELATORIOS_PRODUCAO,
    gerar_excel_relatorio_producao,
    montar_contexto_relatorio_producao,
)
from .almoxarifado import (
    RELATORIOS_ALMOXARIFADO,
    gerar_excel_relatorio_almoxarifado,
    montar_contexto_relatorio_almoxarifado,
)
from .expedicao import (
    RELATORIOS_EXPEDICAO,
    gerar_excel_relatorio_expedicao,
    montar_contexto_relatorio_expedicao,
)
from .gerencial import (
    RELATORIOS_GERENCIAIS,
    gerar_excel_relatorio_gerencial,
    montar_contexto_relatorio_gerencial,
)


def register_relatorios_routes(app):

    @app.route("/relatorios")
    @perfil_permitido("pcp")
    def biblioteca_relatorios():
        contexto = filtrar_relatorios_oficiais(request.args)

        for relatorio in contexto["relatorios"]:
            endpoint = relatorio.get("endpoint")
            relatorio["url"] = url_for(endpoint, **relatorio.get("route_args", {})) if endpoint else None

        return render_template("biblioteca_relatorios.html", **contexto)

    @app.route("/relatorios/financeiro/<slug>")
    @perfil_permitido("pcp")
    def relatorio_financeiro_oficial(slug):
        if slug not in RELATORIOS_FINANCEIROS:
            abort(404)
        return render_template(
            "relatorio_financeiro_oficial.html",
            **montar_contexto_relatorio_financeiro(slug, request.args),
        )

    @app.route("/relatorios/financeiro/<slug>/exportar")
    @perfil_permitido("pcp")
    def relatorio_financeiro_oficial_exportar(slug):
        if slug not in RELATORIOS_FINANCEIROS:
            abort(404)
        contexto = montar_contexto_relatorio_financeiro(slug, request.args)
        arquivo = gerar_excel_relatorio_financeiro(contexto)
        nome = f"{slug}_{contexto['filtros']['data_inicio']}_{contexto['filtros']['data_fim']}.xlsx"
        return send_file(
            arquivo,
            as_attachment=True,
            download_name=nome,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/relatorios/producao/<slug>")
    @perfil_permitido("pcp")
    def relatorio_producao_oficial(slug):
        if slug not in RELATORIOS_PRODUCAO:
            abort(404)
        template = (
            "relatorio_eficiencia_producao.html"
            if RELATORIOS_PRODUCAO[slug].get("familia") == "eficiencia"
            else "relatorio_producao_oficial.html"
        )
        return render_template(
            template,
            **montar_contexto_relatorio_producao(slug, request.args),
        )

    @app.route("/relatorios/producao/<slug>/exportar")
    @perfil_permitido("pcp")
    def relatorio_producao_oficial_exportar(slug):
        if slug not in RELATORIOS_PRODUCAO:
            abort(404)
        contexto = montar_contexto_relatorio_producao(slug, request.args)
        arquivo = gerar_excel_relatorio_producao(contexto)
        nome = f"{slug}_{contexto['filtros']['data_inicio']}_{contexto['filtros']['data_fim']}.xlsx"
        return send_file(
            arquivo,
            as_attachment=True,
            download_name=nome,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/relatorios/almoxarifado/<slug>")
    @perfil_permitido("pcp")
    def relatorio_almoxarifado_oficial(slug):
        if slug not in RELATORIOS_ALMOXARIFADO:
            abort(404)
        return render_template(
            "relatorio_almoxarifado_oficial.html",
            **montar_contexto_relatorio_almoxarifado(slug, request.args),
        )

    @app.route("/relatorios/almoxarifado/<slug>/exportar")
    @perfil_permitido("pcp")
    def relatorio_almoxarifado_oficial_exportar(slug):
        if slug not in RELATORIOS_ALMOXARIFADO:
            abort(404)
        contexto = montar_contexto_relatorio_almoxarifado(slug, request.args)
        arquivo = gerar_excel_relatorio_almoxarifado(contexto)
        nome = f"{slug}_{contexto['filtros']['data_inicio']}_{contexto['filtros']['data_fim']}.xlsx"
        return send_file(
            arquivo,
            as_attachment=True,
            download_name=nome,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/relatorios/expedicao/<slug>")
    @perfil_permitido("pcp")
    def relatorio_expedicao_oficial(slug):
        if slug not in RELATORIOS_EXPEDICAO:
            abort(404)
        return render_template(
            "relatorio_expedicao_oficial.html",
            **montar_contexto_relatorio_expedicao(slug, request.args),
        )

    @app.route("/relatorios/expedicao/<slug>/exportar")
    @perfil_permitido("pcp")
    def relatorio_expedicao_oficial_exportar(slug):
        if slug not in RELATORIOS_EXPEDICAO or not RELATORIOS_EXPEDICAO[slug].get("excel"):
            abort(404)
        contexto = montar_contexto_relatorio_expedicao(slug, request.args)
        arquivo = gerar_excel_relatorio_expedicao(contexto)
        nome = f"{slug}_{contexto['filtros']['data_inicio']}_{contexto['filtros']['data_fim']}.xlsx"
        return send_file(
            arquivo,
            as_attachment=True,
            download_name=nome,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/relatorios/gerencial/<slug>")
    @perfil_permitido("pcp")
    def relatorio_gerencial_oficial(slug):
        if slug not in RELATORIOS_GERENCIAIS:
            abort(404)
        return render_template(
            "relatorio_gerencial_oficial.html",
            **montar_contexto_relatorio_gerencial(slug, request.args),
        )

    @app.route("/relatorios/gerencial/<slug>/exportar")
    @perfil_permitido("pcp")
    def relatorio_gerencial_oficial_exportar(slug):
        if slug not in RELATORIOS_GERENCIAIS:
            abort(404)
        args = request.args.copy()
        if slug == "comparativos" and (args.get("dominio") or "Todos") == "Todos":
            args = args.copy()
            args["carregar_todos"] = "1"
        contexto = montar_contexto_relatorio_gerencial(slug, args)
        arquivo = gerar_excel_relatorio_gerencial(contexto)
        nome = f"gerencial_{slug}_{contexto['filtros']['data_inicio']}_{contexto['filtros']['data_fim']}.xlsx"
        return send_file(
            arquivo,
            as_attachment=True,
            download_name=nome,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

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
