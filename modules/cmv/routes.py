"""Consultas gerenciais, sem mutacao, para CMV e estoque valorizado."""

from datetime import date

from flask import render_template, request, send_file

from modules.auth.decorators import perfil_permitido

from .services import detalhamento_periodo, estoque_valorizado, gerar_excel, gerar_pdf, resumo_periodo


def _periodo():
    hoje = date.today()
    inicio = request.args.get("data_inicio") or hoje.replace(day=1).isoformat()
    fim = request.args.get("data_fim") or hoje.isoformat()
    return inicio, fim


def register_cmv_routes(app):
    @app.route("/cmv")
    @perfil_permitido("pcp", "gerencia", "financeiro")
    def cmv_gerencial():
        inicio, fim = _periodo()
        return render_template("cmv_gerencial.html", data_inicio=inicio, data_fim=fim,
                               resumo=resumo_periodo(inicio, fim),
                               detalhes=detalhamento_periodo(inicio, fim),
                               estoque=estoque_valorizado())

    @app.route("/cmv/exportar-excel")
    @perfil_permitido("pcp", "gerencia", "financeiro")
    def cmv_exportar_excel():
        inicio, fim = _periodo()
        return send_file(gerar_excel(inicio, fim), as_attachment=True,
                         download_name=f"CMV_FIFO_{inicio}_{fim}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.route("/cmv/exportar-pdf")
    @perfil_permitido("pcp", "gerencia", "financeiro")
    def cmv_exportar_pdf():
        inicio, fim = _periodo()
        return send_file(gerar_pdf(inicio, fim), as_attachment=True,
                         download_name=f"CMV_FIFO_{inicio}_{fim}.pdf", mimetype="application/pdf")
