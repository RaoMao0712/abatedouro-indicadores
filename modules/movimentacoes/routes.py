"""Rotas de Movimentacoes com compatibilidade para URLs antigas do Financeiro."""

import json
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, send_file, url_for

from database import conectar
from modules.auth.decorators import perfil_permitido

from .services import (
    CATEGORIAS_FINANCEIRAS_ENTRADA,
    CATEGORIAS_FINANCEIRAS_SAIDA,
    CATEGORIA_RECEITA_BRUTA,
    FORMAS_PAGAMENTO_FINANCEIRO,
    ORIGEM_IMPORTACAO_VENDAS,
    STATUS_FINANCEIRO,
    STATUS_FINANCEIRO_FILTRO,
    agrupar_fluxo_por_dia,
    atualizar_movimentacao_financeira,
    auditar_reset_financeiro,
    buscar_movimentacao_financeira_por_id,
    buscar_movimentacoes_financeiras,
    buscar_pendencias_classificacao,
    calcular_resumo_financeiro,
    executar_reset_financeiro_controlado,
    excluir_movimentacao_financeira,
    gerar_excel_auditoria_financeira,
    gerar_planilha_modelo_importacao_financeira,
    importar_movimentacoes_financeiras_excel,
    montar_contexto_auditoria_financeira,
    reclassificar_movimentacoes,
    salvar_movimentacao_financeira,
)


def register_movimentacoes_routes(app):

    def contar_tabelas_reset(tabelas):
        conn = conectar()
        cursor = conn.cursor()
        try:
            contagens = {}
            for tabela in tabelas:
                try:
                    cursor.execute(f"SELECT COUNT(*) as total FROM {tabela}")
                    contagens[tabela] = int(cursor.fetchone()["total"] or 0)
                except Exception:
                    contagens[tabela] = None
            return contagens
        finally:
            conn.close()


    def destino_movimentacao_por_tipo(tipo):
        if tipo == "Saída":
            return "movimentacoes_despesas"
        return "movimentacoes_entradas"


    def contexto_movimentacoes(visao, tipo_movimentacao=None):
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
                    resultado = importar_movimentacoes_financeiras_excel(arquivo, natureza_padrao="DESPESA")
                    flash("Importacao de movimentacoes concluida.")
                except Exception as erro:
                    flash(f"Erro ao importar movimentacoes: {erro}")

        return render_template(
            "movimentacoes_importar.html",
            resultado=resultado,
            titulo_importacao="Importar movimentacoes financeiras",
            subtitulo_importacao="Importacao inicial via Excel com deduplicacao por documento, datas, favorecido, valor e historico.",
            botao_importacao="Importar movimentacoes",
        )


    @app.route("/movimentacoes/modelo-importacao-oficial")
    @perfil_permitido("pcp")
    def modelo_importacao_financeira_oficial():
        arquivo = gerar_planilha_modelo_importacao_financeira()
        return send_file(
            arquivo,
            as_attachment=True,
            download_name="Modelo_Importacao_Financeira_Oficial.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


    @app.route("/movimentacoes/reset-financeiro-controlado-executar", methods=["POST"])
    @perfil_permitido("admin")
    def reset_financeiro_controlado_executar():
        if request.form.get("confirmacao") != "RESET_FINANCEIRO_PRODUCAO_AUTORIZADO":
            abort(400)

        auditoria_antes = auditar_reset_financeiro()
        tabelas_preservadas = auditoria_antes["tabelas_preservadas"]
        preservadas_antes = contar_tabelas_reset(tabelas_preservadas)

        reset = executar_reset_financeiro_controlado(confirmar=True)

        auditoria_depois = auditar_reset_financeiro()
        preservadas_depois = contar_tabelas_reset(tabelas_preservadas)
        tabelas_depois = {
            item["tabela"]: item["registros"]
            for item in auditoria_depois["tabelas_limpeza"]
        }
        exportadas = {
            item["tabela"]: item["registros"]
            for item in reset["backup"]["manifest"]["tabelas"]
        }

        relatorio = {
            "backup_render": reset["backup"]["pasta"],
            "tabelas_exportadas": exportadas,
            "tabelas_apagadas": exportadas,
            "tabelas_financeiras_apos_reset": tabelas_depois,
            "tabelas_preservadas_antes": preservadas_antes,
            "tabelas_preservadas_depois": preservadas_depois,
            "tabelas_limpas": reset["tabelas_limpas"],
        }

        pasta_backup = Path(reset["backup"]["pasta"])
        (pasta_backup / "reset_resultado.json").write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        arquivo_zip = BytesIO()
        with zipfile.ZipFile(arquivo_zip, "w", zipfile.ZIP_DEFLATED) as pacote:
            for caminho in pasta_backup.glob("*"):
                pacote.write(caminho, caminho.name)
        arquivo_zip.seek(0)

        return send_file(
            arquivo_zip,
            as_attachment=True,
            download_name=f"{pasta_backup.name}_reset_financeiro.zip",
            mimetype="application/zip",
        )


    @app.route("/movimentacoes/importar-vendas", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def importar_vendas_financeiras():
        resultado = None

        if request.method == "POST":
            arquivo = request.files.get("arquivo")

            if not arquivo or not arquivo.filename:
                flash("Selecione uma planilha de vendas para importar.")
            else:
                try:
                    resultado = importar_movimentacoes_financeiras_excel(
                        arquivo,
                        natureza_padrao="RECEITA",
                        categoria_padrao=CATEGORIA_RECEITA_BRUTA,
                        origem_importacao=ORIGEM_IMPORTACAO_VENDAS,
                        incluir_origem_import_key=True,
                    )
                    flash("Importacao de vendas concluida.")
                except Exception as erro:
                    flash(f"Erro ao importar vendas: {erro}")

        return render_template(
            "movimentacoes_importar.html",
            resultado=resultado,
            titulo_importacao="Importar vendas",
            subtitulo_importacao="Importacao de receitas operacionais para a Central de Movimentacoes.",
            botao_importacao="Importar vendas",
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
                    request.form.get("plano_conta_id", "")
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
        contexto = montar_contexto_auditoria_financeira(request.args, exportar=True)
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
