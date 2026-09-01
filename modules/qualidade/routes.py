"""Rotas do modulo de Qualidade."""

from datetime import datetime
from decimal import Decimal
import csv
import io
import json
import click
import secrets

from flask import Response, abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from io import BytesIO

from database import conectar, q
from modules.auth.decorators import perfil_permitido
from modules.auth.services import usuario_eh_admin
from modules.producao.services import buscar_fornecedores, contexto_apontamento
from .services import salvar_apontamento_descarte, salvar_apontamentos_descartes_lote
from . import services as qualidade_service
from .produtos_nao_conformes import (
    MOTIVOS, SITUACOES, STATUS, STATUS_LABELS, consultar as consultar_pa_nc, decidir as decidir_pa_nc,
    indicadores as indicadores_pa_nc, iniciar_avaliacao, listar_locais_segregacao,
    obter_detalhe as obter_detalhe_pa_nc,
)
from .liberacoes import (
    carregar_inventario, pendentes as liberacoes_pendentes,
    solicitar as solicitar_liberacao, solicitacoes_do_registro,
    validar as validar_liberacao,
)
from .descarte_pnc import (
    cancelar_romaneio_descarte, estornar_romaneio_descarte, obter_romaneio_descarte,
    previa_saida_descarte_pnc, registrar_saida_descarte_pnc,
)
from .descarte_pnc_pdf import gerar_romaneio_descarte_pdf
from .reprocessamento import (
    cancelar_reprocessamento, concluir_reprocessamento, iniciar_reprocessamento,
    listar_reprocessamentos,
)
from .reconciliacao_p1_1_1 import (
    diagnosticar as diagnosticar_reconciliacao_p1_1_1,
    reconciliar as reconciliar_p1_1_1,
    reverter as reverter_reconciliacao_p1_1_1,
)
from .descarte_pnc_relatorio import (
    MODALIDADES, STATUS_DOCUMENTO, TIPOS_DATA, consultar_romaneios_descarte,
    normalizar_filtros, opcoes_filtros_relatorio,
)
from .descarte_pnc_relatorio_pdf import gerar_relatorio_consolidado_descarte_pdf
from modules.expedicao.estoque_service import formatar_data_brasileira, formatar_data_hora_brasileira

_CRIAR_BANCO = None


def _normalizar_situacao_pnc(valor):
    situacao = str(valor or "ATIVOS").strip().upper()
    return situacao if situacao in SITUACOES else "ATIVOS"


def register_qualidade_routes(app, integracoes=None):
    global _CRIAR_BANCO
    integracoes = integracoes or {}
    _CRIAR_BANCO = integracoes.get("criar_banco")
    app.jinja_env.filters.setdefault("br_data", formatar_data_brasileira)
    app.jinja_env.filters.setdefault("br_data_hora", formatar_data_hora_brasileira)

    def descarte_habilitado():
        return bool(current_app.config.get("PNC_DISCARD_WAYBILL_ENABLED", False))

    def token_descarte():
        return session.setdefault("csrf_descarte_pnc", secrets.token_urlsafe(32))

    def validar_csrf_descarte():
        recebido = request.form.get("csrf_token", "")
        if not recebido or not secrets.compare_digest(recebido, session.get("csrf_descarte_pnc", "")):
            abort(400, description="Token CSRF inválido.")

    def filtros_relatorio_descarte():
        return normalizar_filtros({
            "data_inicio": request.args.get("data_inicio"),
            "data_fim": request.args.get("data_fim"),
            "tipo_data": request.args.get("tipo_data"),
            "numero": request.args.get("numero"),
            "status": request.args.getlist("status"),
            "produto": request.args.getlist("produto"),
            "apresentacao": request.args.get("apresentacao"),
            "motivo": request.args.getlist("motivo"),
            "destino": request.args.getlist("destino"),
            "motorista": request.args.get("motorista"),
            "placa": request.args.get("placa"),
            "usuario_emissor": request.args.get("usuario_emissor"),
            "modalidade": request.args.get("modalidade"),
        })

    @app.cli.command("carga-inventario-nc-20260730")
    @click.option("--confirmar", is_flag=True, help="Persiste a carga; sem a flag apenas simula.")
    def carga_inventario_nc_20260730(confirmar):
        resultado = carregar_inventario(confirmar=confirmar, usuario="CLI administrativo",
                                        perfil="admin", origem="flask-cli")
        click.echo(json.dumps(resultado, ensure_ascii=False, sort_keys=True))

    @app.cli.command("diagnosticar-pnc-p1-1-1")
    def diagnosticar_pnc_p1_1_1():
        """Fotografia somente leitura das pré-condições da reconciliação P1.1.1."""
        click.echo(json.dumps(diagnosticar_reconciliacao_p1_1_1(), ensure_ascii=False,
                              sort_keys=True, default=str))

    @app.cli.command("reconciliar-pnc-p1-1-1")
    @click.option("--confirmar", is_flag=True, help="Aplica a reconciliação documental estrita.")
    def reconciliar_pnc_legado_p1_1_1(confirmar):
        resultado = reconciliar_p1_1_1(confirmar=confirmar)
        click.echo(json.dumps(resultado, ensure_ascii=False, sort_keys=True, default=str))

    @app.cli.command("reverter-reconciliacao-pnc-p1-1-1")
    @click.option("--confirmar", is_flag=True, help="Reverte somente a reconciliação documental.")
    def reverter_pnc_legado_p1_1_1(confirmar):
        resultado = reverter_reconciliacao_p1_1_1(confirmar=confirmar)
        click.echo(json.dumps(resultado, ensure_ascii=False, sort_keys=True, default=str))

    @app.get("/qualidade/produtos-nao-conformes")
    @perfil_permitido("pcp", "producao", "qualidade", "gerencia")
    def produtos_nao_conformes():
        filtros = {nome: request.args.get(nome, "") for nome in (
            "inicio", "fim", "op", "lote", "produto", "motivo", "status",
            "local", "responsavel", "destinacao", "situacao", "pagina", "por_pagina",
        )}
        filtros["situacao"] = _normalizar_situacao_pnc(filtros["situacao"])
        registros, paginacao = consultar_pa_nc(
            filtros, paginar=True, garantir_schema=False,
        )
        registros_indicadores = consultar_pa_nc(
            {**filtros, "pagina": ""}, garantir_schema=False,
        )
        args_paginacao = request.args.to_dict()
        args_paginacao["situacao"] = filtros["situacao"]
        url_anterior = url_proxima = None
        if paginacao["tem_anterior"]:
            url_anterior = url_for("produtos_nao_conformes", **{
                **args_paginacao, "pagina": paginacao["pagina"] - 1,
            })
        if paginacao["tem_proxima"]:
            url_proxima = url_for("produtos_nao_conformes", **{
                **args_paginacao, "pagina": paginacao["pagina"] + 1,
            })
        return render_template(
            "produtos_nao_conformes.html", registros=registros,
            indicadores=indicadores_pa_nc(registros_indicadores), filtros=filtros,
            paginacao=paginacao, situacoes=SITUACOES,
            url_anterior=url_anterior, url_proxima=url_proxima,
            motivos=MOTIVOS, status_opcoes=sorted(STATUS),
            status_labels=STATUS_LABELS,
            locais=listar_locais_segregacao(garantir_schema=False),
        )

    @app.get("/qualidade/produtos-nao-conformes/exportar.csv")
    @perfil_permitido("pcp", "producao", "qualidade", "gerencia")
    def exportar_produtos_nao_conformes():
        filtros = {nome: request.args.get(nome, "") for nome in (
            "inicio", "fim", "op", "lote", "produto", "motivo", "status",
            "local", "responsavel", "destinacao", "situacao",
        )}
        filtros["situacao"] = _normalizar_situacao_pnc(filtros["situacao"])
        saida = io.StringIO()
        escritor = csv.writer(saida, delimiter=";")
        escritor.writerow(("Número", "Data", "OP", "Lote", "Produto", "Apresentação",
                           "Saldo remanescente", "Peso remanescente", "Unidade", "Motivo",
                           "Status", "Local", "Responsável", "Destinação", "Data da decisão",
                           "Romaneio de descarte", "Data da finalização"))
        for item in consultar_pa_nc(filtros):
            saldo = item["saldo_fisico"]
            quantidade = saldo["pacotes"] if str(item["unidade"]).upper() == "PACOTE" else saldo["bandejas"]
            escritor.writerow((item["numero"], formatar_data_hora_brasileira(item["registrado_em"]),
                               item["op_id"] if item["op_id"] else "Não identificada",
                               item["lote"] or "Não identificado",
                               item["produto"], item["apresentacao"], quantidade,
                               Decimal(saldo["peso_g"]) / Decimal(1000),
                               item["unidade"], item["motivo"], item["status"], item["local_nome"],
                               item["registrado_por"], item["decisao"],
                               formatar_data_hora_brasileira(item["decidido_em"]),
                               item["romaneio_descarte_numero"],
                               formatar_data_hora_brasileira(item["descarte_finalizado_em"] or item["decidido_em"])))
        return Response("\ufeff" + saida.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=produtos-nao-conformes.csv"})

    @app.get("/qualidade/produtos-nao-conformes/<int:pa_nc_id>")
    @perfil_permitido("pcp", "producao", "qualidade", "gerencia")
    def detalhe_produto_nao_conforme(pa_nc_id):
        registro, eventos = obter_detalhe_pa_nc(pa_nc_id)
        if not registro:
            flash("Produto Não Conforme não encontrado.")
            return redirect(url_for("produtos_nao_conformes"))
        return render_template("produto_nao_conforme_detalhe.html", registro=registro,
                               eventos=eventos, solicitacoes=solicitacoes_do_registro(pa_nc_id),
                               reprocessamentos=listar_reprocessamentos(pa_nc_id),
                               status_labels=STATUS_LABELS, descarte_pnc_habilitado=descarte_habilitado())

    @app.post("/qualidade/produtos-nao-conformes/<int:pa_nc_id>/reprocessar")
    @perfil_permitido("qualidade", "gerencia")
    def iniciar_reprocessamento_produto(pa_nc_id):
        try:
            iniciar_reprocessamento(pa_nc_id, request.form.to_dict())
            flash("Reprocessamento iniciado; a quantidade informada saiu do saldo bloqueado.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("detalhe_produto_nao_conforme", pa_nc_id=pa_nc_id))

    @app.post("/qualidade/reprocessamentos/<int:reprocessamento_id>/concluir")
    @perfil_permitido("qualidade", "gerencia")
    def concluir_reprocessamento_produto(reprocessamento_id):
        try:
            resultado = concluir_reprocessamento(
                reprocessamento_id, request.form.get("justificativa"),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Reprocessamento concluído; o remanescente voltou ao bloqueio." if resultado["pnc_status"] == "BLOQUEADO"
                  else "Reprocessamento integral concluído e PNC finalizado.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(request.referrer or url_for("produtos_nao_conformes"))

    @app.post("/qualidade/reprocessamentos/<int:reprocessamento_id>/cancelar")
    @perfil_permitido("qualidade", "gerencia")
    def cancelar_reprocessamento_produto(reprocessamento_id):
        try:
            cancelar_reprocessamento(reprocessamento_id, request.form.get("justificativa"))
            flash("Reprocessamento cancelado; o saldo foi restaurado somente ao bloqueio.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(request.referrer or url_for("produtos_nao_conformes"))

    @app.get("/qualidade/produtos-nao-conformes/<int:pa_nc_id>/romaneio-descarte")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def novo_romaneio_descarte_pnc(pa_nc_id):
        if not descarte_habilitado():
            abort(404)
        registro, _ = obter_detalhe_pa_nc(pa_nc_id)
        if not registro:
            abort(404)
        try:
            previa = previa_saida_descarte_pnc(registro, {"modalidade": "INTEGRAL"})
        except ValueError as erro:
            flash(str(erro)); return redirect(url_for("detalhe_produto_nao_conforme", pa_nc_id=pa_nc_id))
        return render_template("romaneio_descarte_pnc_form.html", registro=registro, previa=previa,
                               dados={}, csrf_token=token_descarte(), confirmar=False)

    @app.post("/qualidade/produtos-nao-conformes/<int:pa_nc_id>/romaneio-descarte/previa")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def prever_romaneio_descarte_pnc(pa_nc_id):
        if not descarte_habilitado(): abort(404)
        validar_csrf_descarte()
        registro, _ = obter_detalhe_pa_nc(pa_nc_id)
        if not registro: abort(404)
        dados = request.form.to_dict()
        try:
            previa = previa_saida_descarte_pnc(registro, dados)
        except ValueError as erro:
            flash(str(erro)); previa = previa_saida_descarte_pnc(registro, {"modalidade":"INTEGRAL"})
            return render_template("romaneio_descarte_pnc_form.html", registro=registro, previa=previa,
                                   dados=dados, csrf_token=token_descarte(), confirmar=False), 400
        from .descarte_pnc import _validar_campos
        try:
            _validar_campos(dados)
            pronto_confirmar, pendencia = True, None
        except ValueError as erro:
            # A prévia quantitativa é somente leitura e pode ser auditada antes
            # do preenchimento dos dados operacionais. A confirmação continua
            # bloqueada até que todos os campos obrigatórios sejam válidos.
            pronto_confirmar, pendencia = False, str(erro)
        dados["idempotency_key"] = dados.get("idempotency_key") or f"WEB-DESC-{pa_nc_id}-{secrets.token_hex(16)}"
        return render_template("romaneio_descarte_pnc_form.html", registro=registro, previa=previa,
                               dados=dados, csrf_token=token_descarte(), confirmar=True,
                               pronto_confirmar=pronto_confirmar, pendencia=pendencia)

    @app.post("/qualidade/produtos-nao-conformes/<int:pa_nc_id>/romaneio-descarte/confirmar")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def confirmar_romaneio_descarte_pnc(pa_nc_id):
        if not descarte_habilitado(): abort(404)
        validar_csrf_descarte()
        try:
            romaneio = registrar_saida_descarte_pnc(pa_nc_id, request.form.to_dict())
            flash("Saída para descarte confirmada; somente o saldo bloqueado foi baixado.")
            return redirect(url_for("visualizar_romaneio_descarte_pnc", romaneio_id=romaneio["id"]))
        except (ValueError, PermissionError) as erro:
            flash(str(erro)); return redirect(url_for("novo_romaneio_descarte_pnc", pa_nc_id=pa_nc_id))

    @app.get("/expedicao/romaneios/descarte")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def romaneios_descarte_pnc():
        if not descarte_habilitado(): abort(404)
        filtros = filtros_relatorio_descarte()
        relatorio = consultar_romaneios_descarte(filtros)
        return render_template("romaneios_descarte_pnc.html", romaneios=relatorio["registros"],
                               relatorio=relatorio, filtros=filtros,
                               opcoes=opcoes_filtros_relatorio(), status_opcoes=STATUS_DOCUMENTO,
                               tipos_data=TIPOS_DATA, modalidades=MODALIDADES)

    @app.get("/expedicao/romaneios/descarte/relatorio.pdf")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def relatorio_romaneios_descarte_pnc():
        if not descarte_habilitado(): abort(404)
        filtros = filtros_relatorio_descarte()
        relatorio = consultar_romaneios_descarte(filtros)
        pdf = gerar_relatorio_consolidado_descarte_pdf(
            relatorio, usuario=session.get("nome") or "Usuário não identificado")
        nome = ("relatorio-romaneios-descarte-sintetico.pdf" if filtros["modalidade"] == "SINTETICO"
                else "relatorio-romaneios-descarte-por-caracteristica.pdf")
        resposta = send_file(BytesIO(pdf), mimetype="application/pdf", as_attachment=False,
                             download_name=nome)
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta

    @app.get("/expedicao/romaneios/descarte/<int:romaneio_id>")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def visualizar_romaneio_descarte_pnc(romaneio_id):
        if not descarte_habilitado(): abort(404)
        romaneio = obter_romaneio_descarte(romaneio_id)
        if not romaneio: abort(404)
        return render_template("romaneio_descarte_pnc_detalhe.html", romaneio=romaneio,
                               csrf_token=token_descarte())

    @app.get("/expedicao/romaneios/descarte/<int:romaneio_id>.pdf")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def imprimir_romaneio_descarte_pnc(romaneio_id):
        if not descarte_habilitado(): abort(404)
        romaneio = obter_romaneio_descarte(romaneio_id)
        if not romaneio: abort(404)
        resposta = send_file(BytesIO(gerar_romaneio_descarte_pdf(romaneio["snapshot"])),
            mimetype="application/pdf", as_attachment=False, download_name=f"{romaneio['numero']}.pdf")
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta

    @app.post("/expedicao/romaneios/descarte/<int:romaneio_id>/estornar")
    @perfil_permitido("gerencia")
    def estornar_saida_romaneio_descarte_pnc(romaneio_id):
        if not descarte_habilitado(): abort(404)
        validar_csrf_descarte()
        try:
            estornar_romaneio_descarte(romaneio_id, request.form.get("justificativa"))
            flash("Romaneio estornado por movimento inverso; o saldo voltou somente ao estoque bloqueado.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("visualizar_romaneio_descarte_pnc", romaneio_id=romaneio_id))

    @app.post("/expedicao/romaneios/descarte/<int:romaneio_id>/cancelar")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def cancelar_saida_romaneio_descarte_pnc(romaneio_id):
        if not descarte_habilitado(): abort(404)
        validar_csrf_descarte()
        try:
            cancelar_romaneio_descarte(romaneio_id, request.form.get("justificativa"))
            flash("Rascunho cancelado sem movimentação de estoque.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("visualizar_romaneio_descarte_pnc", romaneio_id=romaneio_id))

    @app.post("/qualidade/produtos-nao-conformes/<int:pa_nc_id>/solicitar-liberacao")
    @perfil_permitido("qualidade")
    def solicitar_liberacao_produto(pa_nc_id):
        try:
            solicitar_liberacao(pa_nc_id, request.form.get("peso"), request.form.get("caixas"),
                                request.form.get("bandejas"), request.form.get("justificativa"),
                                request.form.get("observacoes"),
                                idempotency_key=request.form.get("idempotency_key"))
            flash("Solicitacao registrada e reservada para validacao da Gerencia.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("detalhe_produto_nao_conforme", pa_nc_id=pa_nc_id))

    @app.get("/qualidade/liberacoes-pendentes")
    @perfil_permitido("gerencia")
    def validar_liberacoes_pendentes():
        return render_template(
            "liberacoes_pendentes.html",
            solicitacoes=liberacoes_pendentes(
                usuario_id=session.get("usuario_id"), usuario=session.get("nome")
            ),
        )

    @app.post("/qualidade/liberacoes/<int:solicitacao_id>/validar")
    @perfil_permitido("gerencia")
    def validar_liberacao_produto(solicitacao_id):
        try:
            validar_liberacao(solicitacao_id, request.form.get("decisao"),
                              request.form.get("justificativa"))
            flash("Validacao gerencial registrada sem duplicidade.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("validar_liberacoes_pendentes"))

    @app.post("/qualidade/produtos-nao-conformes/<int:pa_nc_id>/avaliar")
    @perfil_permitido("pcp", "producao", "qualidade", "gerencia")
    def avaliar_produto_nao_conforme(pa_nc_id):
        try:
            iniciar_avaliacao(pa_nc_id)
            flash("Avaliação iniciada; o produto permanece bloqueado.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("detalhe_produto_nao_conforme", pa_nc_id=pa_nc_id))

    @app.post("/qualidade/produtos-nao-conformes/<int:pa_nc_id>/decidir")
    @perfil_permitido("pcp", "producao", "qualidade", "gerencia")
    def decidir_produto_nao_conforme(pa_nc_id):
        try:
            decidir_pa_nc(pa_nc_id, request.form.get("destino"),
                          request.form.get("justificativa"), request.form.get("observacoes"))
            flash("Destinação registrada com rastreabilidade preservada.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("detalhe_produto_nao_conforme", pa_nc_id=pa_nc_id))


    def garantir_schema_producao():
        if _CRIAR_BANCO:
            _CRIAR_BANCO()


    def formatar_numero_br(valor, casas=2):
        try:
            numero = float(valor or 0)
        except Exception:
            numero = 0
        texto = f"{numero:,.{casas}f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")


    def formatar_percentual_br(valor):
        return f"{formatar_numero_br(valor, 2)}%"


    def obter_registros_por_ids(tabela, ids):
        if not ids:
            return []

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        SELECT
            r.*,
            o.status as op_status
        FROM {tabela} r
        JOIN ordens_producao o ON o.id = r.op_id
        WHERE r.id IN ({placeholders})
        ORDER BY r.id ASC
        """), tuple(ids))

        registros = cursor.fetchall()
        conn.close()
        return registros


    def ids_do_request(nome="ids"):
        valores = request.values.getlist(nome)

        if not valores:
            valores = request.form.getlist(nome)

        ids = []

        for valor in valores:
            try:
                ids.append(int(valor))
            except (TypeError, ValueError):
                pass

        return ids


    def primeiro_op_id(registros):
        if not registros:
            return None
        return registros[0]["op_id"]


    def edicao_bloqueada_por_status(registros):
        if usuario_eh_admin():
            return False

        for registro in registros:
            if registro["op_status"] == "Encerrada":
                return True

        return False


    # ============================================================
    # RELATÓRIO DE RENDIMENTO
    # ============================================================

    @app.route("/relatorio-rendimento")
    @perfil_permitido("pcp")
    def relatorio_rendimento():
        return redirect(url_for("relatorio_producao_oficial", slug="rendimento", **request.args))


    def relatorio_rendimento_legado_descontinuado():
        agora = datetime.now()
        hoje = agora.strftime("%Y-%m-%d")
        primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

        data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
        data_fim = request.args.get("data_fim") or hoje
        sku_filtro = request.args.get("sku") or "Todos"
        fornecedor_filtro = request.args.get("fornecedor") or "Todos"

        meta_rendimento = 63.0

        condicoes = [
            "o.data BETWEEN ? AND ?",
            "COALESCE(o.status, 'Aberta') = 'Encerrada'"
        ]
        parametros = [data_inicio, data_fim]

        if sku_filtro != "Todos":
            condicoes.append("COALESCE(o.sku, 'Galinha Cortada') = ?")
            parametros.append(sku_filtro)

        if fornecedor_filtro != "Todos":
            condicoes.append("o.fornecedor = ?")
            parametros.append(fornecedor_filtro)

        where_sql = " AND ".join(condicoes)

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        SELECT
            o.data,
            o.fornecedor,
            COALESCE(SUM(o.peso_vivo), 0) as peso_vivo,
            COALESCE(SUM(prod.kg_produzidos), 0) as kg_produzidos
        FROM ordens_producao o
        LEFT JOIN (
            SELECT
                op_id,
                COALESCE(SUM(quantidade), 0) as kg_produzidos
            FROM apontamentos_producao
            WHERE LOWER(unidade) = 'kg' AND COALESCE(vigente,1)=1
            GROUP BY op_id
        ) prod ON prod.op_id = o.id
        WHERE {where_sql}
        GROUP BY o.data, o.fornecedor
        ORDER BY o.data ASC, o.fornecedor ASC
        """), tuple(parametros))

        registros = cursor.fetchall()
        conn.close()

        datas = sorted({item["data"] for item in registros})
        fornecedores_grafico = sorted({item["fornecedor"] for item in registros})

        dados_por_chave = {}

        total_kg_produzidos = 0
        total_peso_vivo = 0
        tabela_linhas = []

        for item in registros:
            data = item["data"]
            fornecedor = item["fornecedor"]
            kg_produzidos = float(item["kg_produzidos"] or 0)
            peso_vivo = float(item["peso_vivo"] or 0)
            rendimento = (kg_produzidos / peso_vivo * 100) if peso_vivo > 0 else 0
            desvio_meta = rendimento - meta_rendimento

            total_kg_produzidos += kg_produzidos
            total_peso_vivo += peso_vivo

            linha = {
                "data": data,
                "fornecedor": fornecedor,
                "kg_produzidos": round(kg_produzidos, 2),
                "peso_vivo": round(peso_vivo, 2),
                "rendimento": round(rendimento, 2),
                "desvio_meta": round(desvio_meta, 2)
            }

            dados_por_chave[(data, fornecedor)] = linha
            tabela_linhas.append(linha)

        rendimento_medio = (
            total_kg_produzidos / total_peso_vivo * 100
            if total_peso_vivo > 0
            else 0
        )

        cores = [
            "#2563eb",
            "#16a34a",
            "#f97316",
            "#8b5cf6",
            "#0891b2",
            "#dc2626",
            "#64748b"
        ]

        datasets = []

        for indice, fornecedor in enumerate(fornecedores_grafico):
            dados_linha = []
            detalhes_linha = []

            for data in datas:
                linha = dados_por_chave.get((data, fornecedor))

                if linha:
                    dados_linha.append(linha["rendimento"])
                    detalhes_linha.append({
                        "kg_produzidos": linha["kg_produzidos"],
                        "peso_vivo": linha["peso_vivo"]
                    })
                else:
                    dados_linha.append(None)
                    detalhes_linha.append(None)

            cor = cores[indice % len(cores)]

            datasets.append({
                "label": fornecedor,
                "data": dados_linha,
                "detalhes": detalhes_linha,
                "borderColor": cor,
                "backgroundColor": cor,
                "tension": 0.25,
                "pointRadius": 4,
                "pointHoverRadius": 6,
                "spanGaps": False
            })

        if datas:
            datasets.append({
                "label": f"Meta {formatar_percentual_br(meta_rendimento)}",
                "data": [meta_rendimento for _ in datas],
                "borderColor": "#111827",
                "backgroundColor": "#111827",
                "borderDash": [8, 6],
                "pointRadius": 0,
                "pointHoverRadius": 0,
                "tension": 0,
                "ehMeta": True
            })

        return render_template(
            "relatorio_rendimento.html",
            data_inicio=data_inicio,
            data_fim=data_fim,
            sku_filtro=sku_filtro,
            fornecedor_filtro=fornecedor_filtro,
            fornecedores=buscar_fornecedores(),
            skus=["Galinha Inteira", "Galinha Cortada"],
            datas=datas,
            datasets=datasets,
            tabela_linhas=tabela_linhas,
            rendimento_medio=round(rendimento_medio, 2),
            meta_rendimento=meta_rendimento,
            total_kg_produzidos=round(total_kg_produzidos, 2),
            total_peso_vivo=round(total_peso_vivo, 2)
        )


    # ============================================================
    # RELATÓRIO DE VIABILIDADE
    # Relatório executivo de viabilidade das aves.
    # Escopo: perdas operacionais por período, fornecedor, motivo e setor.
    # ============================================================


    def normalizar_data_relatorio_viabilidade(valor, padrao):
        if not valor:
            return padrao

        try:
            datetime.strptime(valor, "%Y-%m-%d")
            return valor
        except Exception:
            return padrao


    def buscar_opcoes_relatorio_viabilidade(data_inicio, data_fim, fornecedor_filtro="Todos"):
        garantir_schema_producao()

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        SELECT DISTINCT fornecedor
        FROM ordens_producao
        WHERE data BETWEEN ? AND ?
          AND fornecedor IS NOT NULL
          AND fornecedor <> ''
        ORDER BY fornecedor
        """), (data_inicio, data_fim))
        fornecedores_periodo = [item["fornecedor"] for item in cursor.fetchall()]

        cursor.execute(q("""
        SELECT DISTINCT d.setor
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE o.data BETWEEN ? AND ?
          AND d.setor IS NOT NULL
          AND d.setor <> ''
        ORDER BY d.setor
        """), (data_inicio, data_fim))
        setores = [item["setor"] for item in cursor.fetchall()]

        filtros_motivos = ["o.data BETWEEN ? AND ?"]
        parametros_motivos = [data_inicio, data_fim]

        if fornecedor_filtro and fornecedor_filtro != "Todos":
            filtros_motivos.append("o.fornecedor = ?")
            parametros_motivos.append(fornecedor_filtro)

        where_motivos = " AND ".join(filtros_motivos)

        cursor.execute(q(f"""
        SELECT DISTINCT d.motivo
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_motivos}
          AND d.motivo IS NOT NULL
          AND d.motivo <> ''
        ORDER BY d.motivo
        """), tuple(parametros_motivos))
        motivos = [item["motivo"] for item in cursor.fetchall()]

        conn.close()

        return {
            "fornecedores": fornecedores_periodo,
            "setores": setores,
            "motivos": motivos
        }


    def buscar_dados_relatorio_viabilidade(data_inicio, data_fim, fornecedor_filtro="Todos", motivo_filtro="Todos", setor_filtro="Todos"):
        garantir_schema_producao()

        filtros_op = ["o.data BETWEEN ? AND ?"]
        parametros_op = [data_inicio, data_fim]

        if fornecedor_filtro and fornecedor_filtro != "Todos":
            filtros_op.append("o.fornecedor = ?")
            parametros_op.append(fornecedor_filtro)

        where_op = " AND ".join(filtros_op)

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        SELECT
            COALESCE(SUM(o.quantidade_aves), 0) AS aves_recebidas,
            COALESCE(SUM(o.mortes_antes_pendura), 0) AS mortes_antes_pendura,
            COUNT(o.id) AS total_ops
        FROM ordens_producao o
        WHERE {where_op}
        """), tuple(parametros_op))
        resumo_op = cursor.fetchone()

        aves_recebidas = float(resumo_op["aves_recebidas"] or 0)
        mortes_legado_base = float(resumo_op["mortes_antes_pendura"] or 0)
        motivo_normalizado = str(motivo_filtro or "").strip().lower()
        mortes_legado_aplicavel = motivo_normalizado in ["", "todos", "morte na gaiola"]
        mortes_antes_pendura = mortes_legado_base if mortes_legado_aplicavel else 0
        total_ops = int(resumo_op["total_ops"] or 0)

        filtros_perdas = list(filtros_op)
        parametros_perdas = list(parametros_op)

        if motivo_filtro and motivo_filtro != "Todos":
            filtros_perdas.append("d.motivo = ?")
            parametros_perdas.append(motivo_filtro)

        if setor_filtro and setor_filtro != "Todos":
            filtros_perdas.append("d.setor = ?")
            parametros_perdas.append(setor_filtro)

        filtros_perdas.append("LOWER(COALESCE(d.unidade, '')) IN ('aves', 'ave', 'unidade', 'unidades')")
        where_perdas = " AND ".join(filtros_perdas)

        cursor.execute(q(f"""
        SELECT
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                THEN d.quantidade ELSE 0 END), 0) AS condenacoes,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                  OR LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN 0 ELSE d.quantidade END), 0) AS descartes
            ,
            COALESCE(SUM(CASE
                WHEN LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN d.quantidade ELSE 0 END), 0) AS mortes_na_gaiola
            ,
            COALESCE(SUM(CASE
                WHEN LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN d.quantidade ELSE 0 END), 0) AS mortes_na_gaiola
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_perdas}
        """), tuple(parametros_perdas))
        perdas = cursor.fetchone()

        condenacoes = float(perdas["condenacoes"] or 0)
        descartes = float(perdas["descartes"] or 0)
        mortes_antes_pendura += float(perdas["mortes_na_gaiola"] or 0)
        total_perdas = mortes_antes_pendura + condenacoes + descartes
        aves_viaveis = max(0, aves_recebidas - total_perdas)
        viabilidade_percentual = (aves_viaveis / aves_recebidas * 100) if aves_recebidas > 0 else 0

        cursor.execute(q(f"""
        SELECT
            o.data,
            COALESCE(SUM(o.quantidade_aves), 0) AS aves_recebidas,
            COALESCE(SUM(o.mortes_antes_pendura), 0) AS mortes_antes_pendura
        FROM ordens_producao o
        WHERE {where_op}
        GROUP BY o.data
        ORDER BY o.data
        """), tuple(parametros_op))
        ops_por_data = {
            item["data"]: {
                "aves_recebidas": float(item["aves_recebidas"] or 0),
                "mortes_antes_pendura": float(item["mortes_antes_pendura"] or 0)
            }
            for item in cursor.fetchall()
        }

        cursor.execute(q(f"""
        SELECT
            o.data,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                THEN d.quantidade ELSE 0 END), 0) AS condenacoes,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                  OR LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN 0 ELSE d.quantidade END), 0) AS descartes
            ,
            COALESCE(SUM(CASE
                WHEN LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN d.quantidade ELSE 0 END), 0) AS mortes_na_gaiola
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_perdas}
        GROUP BY o.data
        ORDER BY o.data
        """), tuple(parametros_perdas))
        perdas_por_data = {
            item["data"]: {
                "condenacoes": float(item["condenacoes"] or 0),
                "descartes": float(item["descartes"] or 0),
                "mortes_na_gaiola": float(item["mortes_na_gaiola"] or 0)
            }
            for item in cursor.fetchall()
        }

        evolucao_diaria = []
        for data in sorted(ops_por_data.keys()):
            base = ops_por_data.get(data, {})
            perda = perdas_por_data.get(data, {})
            aves_dia = float(base.get("aves_recebidas", 0) or 0)
            mortes_dia = float(base.get("mortes_antes_pendura", 0) or 0) if mortes_legado_aplicavel else 0
            mortes_dia += float(perda.get("mortes_na_gaiola", 0) or 0)
            condenacoes_dia = float(perda.get("condenacoes", 0) or 0)
            descartes_dia = float(perda.get("descartes", 0) or 0)
            total_perdas_dia = mortes_dia + condenacoes_dia + descartes_dia
            aves_viaveis_dia = max(0, aves_dia - total_perdas_dia)
            viabilidade_dia = (aves_viaveis_dia / aves_dia * 100) if aves_dia > 0 else 0

            try:
                data_formatada = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m")
            except Exception:
                data_formatada = data

            evolucao_diaria.append({
                "data": data,
                "data_formatada": data_formatada,
                "aves_recebidas": round(aves_dia, 2),
                "mortes_antes_pendura": round(mortes_dia, 2),
                "condenacoes": round(condenacoes_dia, 2),
                "descartes": round(descartes_dia, 2),
                "total_perdas": round(total_perdas_dia, 2),
                "viabilidade_percentual": round(viabilidade_dia, 2)
            })

        filtros_perdas_sem_setor = list(filtros_op)
        parametros_perdas_sem_setor = list(parametros_op)

        if motivo_filtro and motivo_filtro != "Todos":
            filtros_perdas_sem_setor.append("d.motivo = ?")
            parametros_perdas_sem_setor.append(motivo_filtro)

        if setor_filtro and setor_filtro != "Todos":
            filtros_perdas_sem_setor.append("d.setor = ?")
            parametros_perdas_sem_setor.append(setor_filtro)

        filtros_perdas_sem_setor.append("LOWER(COALESCE(d.unidade, '')) IN ('aves', 'ave', 'unidade', 'unidades')")
        where_setor = " AND ".join(filtros_perdas_sem_setor)

        cursor.execute(q(f"""
        SELECT
            COALESCE(NULLIF(d.setor, ''), 'Sem setor') AS setor,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                THEN d.quantidade ELSE 0 END), 0) AS condenacoes,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                  OR LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN 0 ELSE d.quantidade END), 0) AS descartes,
            COALESCE(SUM(d.quantidade), 0) AS total
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_setor}
        GROUP BY COALESCE(NULLIF(d.setor, ''), 'Sem setor')
        ORDER BY total DESC
        """), tuple(parametros_perdas_sem_setor))

        perdas_por_setor = []
        for item in cursor.fetchall():
            total = float(item["total"] or 0)
            percentual = (total / total_perdas * 100) if total_perdas > 0 else 0
            perdas_por_setor.append({
                "setor": item["setor"],
                "condenacoes": round(float(item["condenacoes"] or 0), 2),
                "descartes": round(float(item["descartes"] or 0), 2),
                "total": round(total, 2),
                "percentual": round(percentual, 2)
            })

        cursor.execute(q(f"""
        SELECT
            COALESCE(NULLIF(d.motivo, ''), 'Sem motivo') AS motivo,
            COALESCE(NULLIF(d.setor, ''), 'Sem setor') AS setor,
            COALESCE(SUM(d.quantidade), 0) AS total
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_perdas}
        GROUP BY COALESCE(NULLIF(d.motivo, ''), 'Sem motivo'), COALESCE(NULLIF(d.setor, ''), 'Sem setor')
        ORDER BY total DESC
        LIMIT 20
        """), tuple(parametros_perdas))

        ranking_motivos = []
        for item in cursor.fetchall():
            total = float(item["total"] or 0)
            percentual = (total / total_perdas * 100) if total_perdas > 0 else 0
            ranking_motivos.append({
                "motivo": item["motivo"],
                "setor": item["setor"],
                "total": round(total, 2),
                "percentual": round(percentual, 2)
            })

        cursor.execute(q(f"""
        SELECT
            o.fornecedor,
            COALESCE(SUM(o.quantidade_aves), 0) AS aves_recebidas,
            COALESCE(SUM(o.mortes_antes_pendura), 0) AS mortes_antes_pendura
        FROM ordens_producao o
        WHERE {where_op}
        GROUP BY o.fornecedor
        ORDER BY o.fornecedor
        """), tuple(parametros_op))
        fornecedores_base = {
            item["fornecedor"]: {
                "aves_recebidas": float(item["aves_recebidas"] or 0),
                "mortes_antes_pendura": float(item["mortes_antes_pendura"] or 0)
            }
            for item in cursor.fetchall()
        }

        cursor.execute(q(f"""
        SELECT
            o.fornecedor,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                THEN d.quantidade ELSE 0 END), 0) AS condenacoes,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                  OR LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN 0 ELSE d.quantidade END), 0) AS descartes,
            COALESCE(SUM(CASE
                WHEN LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN d.quantidade ELSE 0 END), 0) AS mortes_na_gaiola
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_perdas}
        GROUP BY o.fornecedor
        ORDER BY o.fornecedor
        """), tuple(parametros_perdas))
        fornecedores_perdas = {
            item["fornecedor"]: {
                "condenacoes": float(item["condenacoes"] or 0),
                "descartes": float(item["descartes"] or 0),
                "mortes_na_gaiola": float(item["mortes_na_gaiola"] or 0)
            }
            for item in cursor.fetchall()
        }

        comparativo_fornecedores = []
        for fornecedor, base in fornecedores_base.items():
            perdas_fornecedor = fornecedores_perdas.get(fornecedor, {})
            aves_fornecedor = float(base.get("aves_recebidas", 0) or 0)
            mortes_fornecedor = float(base.get("mortes_antes_pendura", 0) or 0) if mortes_legado_aplicavel else 0
            mortes_fornecedor += float(perdas_fornecedor.get("mortes_na_gaiola", 0) or 0)
            condenacoes_fornecedor = float(perdas_fornecedor.get("condenacoes", 0) or 0)
            descartes_fornecedor = float(perdas_fornecedor.get("descartes", 0) or 0)
            total_perdas_fornecedor = mortes_fornecedor + condenacoes_fornecedor + descartes_fornecedor
            viabilidade_fornecedor = ((aves_fornecedor - total_perdas_fornecedor) / aves_fornecedor * 100) if aves_fornecedor > 0 else 0

            comparativo_fornecedores.append({
                "fornecedor": fornecedor,
                "aves_recebidas": round(aves_fornecedor, 2),
                "mortes_antes_pendura": round(mortes_fornecedor, 2),
                "condenacoes": round(condenacoes_fornecedor, 2),
                "descartes": round(descartes_fornecedor, 2),
                "total_perdas": round(total_perdas_fornecedor, 2),
                "viabilidade_percentual": round(viabilidade_fornecedor, 2)
            })

        comparativo_fornecedores = sorted(
            comparativo_fornecedores,
            key=lambda item: item["viabilidade_percentual"],
            reverse=True
        )

        conn.close()

        return {
            "resumo": {
                "aves_recebidas": round(aves_recebidas, 2),
                "mortes_antes_pendura": round(mortes_antes_pendura, 2),
                "condenacoes": round(condenacoes, 2),
                "descartes": round(descartes, 2),
                "total_perdas": round(total_perdas, 2),
                "aves_viaveis": round(aves_viaveis, 2),
                "viabilidade_percentual": round(viabilidade_percentual, 2),
                "total_ops": total_ops
            },
            "evolucao_diaria": evolucao_diaria,
            "perdas_por_setor": perdas_por_setor,
            "ranking_motivos": ranking_motivos,
            "comparativo_fornecedores": comparativo_fornecedores
        }


    @app.route("/relatorio-viabilidade")
    @perfil_permitido("pcp")
    def relatorio_viabilidade():
        hoje = datetime.now().strftime("%Y-%m-%d")
        primeiro_dia_mes = datetime.now().replace(day=1).strftime("%Y-%m-%d")

        data_inicio = normalizar_data_relatorio_viabilidade(
            request.args.get("data_inicio"),
            primeiro_dia_mes
        )
        data_fim = normalizar_data_relatorio_viabilidade(
            request.args.get("data_fim"),
            hoje
        )

        fornecedor_filtro = request.args.get("fornecedor", "Todos") or "Todos"
        motivo_filtro = request.args.get("motivo", "Todos") or "Todos"
        setor_filtro = request.args.get("setor", "Todos") or "Todos"

        opcoes = buscar_opcoes_relatorio_viabilidade(
            data_inicio,
            data_fim,
            fornecedor_filtro
        )

        dados = buscar_dados_relatorio_viabilidade(
            data_inicio,
            data_fim,
            fornecedor_filtro,
            motivo_filtro,
            setor_filtro
        )

        return render_template(
            "relatorio_viabilidade.html",
            data_inicio=data_inicio,
            data_fim=data_fim,
            fornecedor_filtro=fornecedor_filtro,
            motivo_filtro=motivo_filtro,
            setor_filtro=setor_filtro,
            fornecedores=opcoes["fornecedores"],
            motivos=opcoes["motivos"],
            setores=opcoes["setores"],
            resumo=dados["resumo"],
            evolucao_diaria=dados["evolucao_diaria"],
            perdas_por_setor=dados["perdas_por_setor"],
            ranking_motivos=dados["ranking_motivos"],
            comparativo_fornecedores=dados["comparativo_fornecedores"]
        )


    @app.route("/apontamento-descartes", methods=["GET", "POST"])
    @perfil_permitido("qualidade")
    def apontamento_descartes():
        if request.method == "POST":
            try:
                if request.form.get("tipo_apontamento") == "descarte_lote":
                    salvar_apontamentos_descartes_lote(request.form)
                else:
                    salvar_apontamento_descarte(request.form)
                flash("Apontamento de descarte/condenação salvo.")
            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("apontamento_descartes"))

        return render_template("apontamento_descartes.html", **contexto_apontamento())


    @app.route("/descartes/lote/editar", methods=["GET", "POST"])
    @perfil_permitido("qualidade")
    def editar_descartes_lote():
        ids = ids_do_request("ids")

        if not ids:
            flash("Selecione pelo menos um descarte.")
            return redirect(url_for("consultar_op"))

        registros = obter_registros_por_ids("apontamentos_descartes", ids)

        if not registros:
            flash("Nenhum descarte encontrado.")
            return redirect(url_for("consultar_op"))

        op_id = primeiro_op_id(registros)

        if edicao_bloqueada_por_status(registros):
            flash("Esta OP está encerrada. Edição de descartes bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        if request.method == "POST" and request.form.get("acao") == "salvar":
            categoria = request.form["categoria"]
            motivo = request.form["motivo"]
            unidade = request.form["unidade"]
            observacoes = request.form.get("observacoes", "")

            placeholders = ",".join(["?"] * len(ids))

            conn = conectar()
            cursor = conn.cursor()

            cursor.execute(q(f"""
            UPDATE apontamentos_descartes
            SET categoria = ?,
                motivo = ?,
                unidade = ?,
                observacoes = ?
            WHERE id IN ({placeholders})
            """), (categoria, motivo, unidade, observacoes, *ids))

            conn.commit()
            conn.close()

            flash("Descartes atualizados com sucesso.")
            return redirect(url_for("consultar_op", op_id=op_id))

        return render_template(
            "editar_descartes_lote.html",
            registros=registros,
            ids=ids
        )


    @app.route("/descartes/lote/excluir", methods=["POST"])
    @perfil_permitido("qualidade")
    def excluir_descartes_lote():
        ids = ids_do_request("ids")

        if not ids:
            flash("Selecione pelo menos um descarte.")
            return redirect(url_for("consultar_op"))

        registros = obter_registros_por_ids("apontamentos_descartes", ids)

        if not registros:
            flash("Nenhum descarte encontrado.")
            return redirect(url_for("consultar_op"))

        op_id = primeiro_op_id(registros)

        if edicao_bloqueada_por_status(registros):
            flash("Esta OP está encerrada. Exclusão de descartes bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        DELETE FROM apontamentos_descartes
        WHERE id IN ({placeholders})
        """), tuple(ids))

        conn.commit()
        conn.close()

        flash("Descartes excluídos com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    @app.route("/sgi/qualidade")
    @app.route("/sgi/qualidade/verificacoes")
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_qualidade():
        return render_template("sgi_qualidade.html", **qualidade_service.contexto_central_sgi(request.args))

    @app.route("/sgi/qualidade/cadastros/locais", methods=["POST"])
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_cadastrar_local():
        try:
            qualidade_service.cadastrar_local_sgi(request.form)
            flash("Local incluido na Central de Configuracao.")
        except Exception as erro:
            flash(str(erro))
        retorno_tipo = request.form.get("retorno_tipo")
        if retorno_tipo:
            return redirect(url_for("sgi_nova_verificacao", tipo=retorno_tipo))
        return redirect(url_for("sgi_qualidade"))

    @app.route("/sgi/qualidade/cadastros/setores", methods=["POST"])
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_cadastrar_setor():
        try:
            qualidade_service.cadastrar_setor_sgi(request.form)
            flash("Setor incluido na Central de Configuracao.")
        except Exception as erro:
            flash(str(erro))
        retorno_tipo = request.form.get("retorno_tipo")
        if retorno_tipo:
            return redirect(url_for("sgi_nova_verificacao", tipo=retorno_tipo))
        return redirect(url_for("sgi_qualidade"))

    @app.route("/sgi/qualidade/verificacoes/nova/<tipo>", methods=["GET", "POST"])
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_nova_verificacao(tipo):
        if tipo in ("plm01_instalacoes", "plm01_balancas", "plm01"):
            return redirect(url_for("sgi_plm01_mensal", competencia=request.args.get("competencia") or request.args.get("mes") or ""))
        try:
            contexto = qualidade_service.contexto_nova_verificacao(tipo)
            if request.method == "POST":
                verificacao_id = qualidade_service.salvar_verificacao_sgi(
                    tipo, request.form, session["usuario_id"], session.get("nome", "Usuario"))
                flash(f"Verificacao #{verificacao_id} concluida e registrada no historico.")
                return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=verificacao_id))
            return render_template("sgi_verificacao_form.html", **contexto)
        except Exception as erro:
            flash(str(erro))
            return redirect(url_for("sgi_qualidade"))

    @app.route("/sgi/qualidade/plm01", methods=["GET", "POST"])
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_plm01_mensal():
        competencia = request.values.get("competencia") or request.values.get("mes") or ""
        if request.method == "POST":
            try:
                ficha_id = qualidade_service.salvar_plm01_mensal(
                    request.form, session["usuario_id"], session.get("nome", "Usuario"))
                competencia = request.form.get("competencia") or competencia
                flash(f"PLM 01 mensal #{ficha_id} salva com sucesso.")
                return redirect(url_for("sgi_plm01_mensal", competencia=competencia))
            except Exception as erro:
                flash(str(erro))
                contexto = qualidade_service.contexto_plm01_mensal({"competencia": competencia})
                return render_template("sgi_plm01_form.html", **contexto)
        return render_template("sgi_plm01_form.html", **qualidade_service.contexto_plm01_mensal({"competencia": competencia}))

    @app.route("/sgi/qualidade/plm01/imprimir")
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_plm01_imprimir():
        return render_template("sgi_plm01_print.html", **qualidade_service.contexto_plm01_mensal(request.args))

    @app.route("/sgi/qualidade/verificacoes/<int:verificacao_id>")
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_verificacao_detalhe(verificacao_id):
        try:
            return render_template("sgi_verificacao_detalhe.html", **qualidade_service.contexto_verificacao(verificacao_id))
        except ValueError as erro:
            flash(str(erro))
            return redirect(url_for("sgi_qualidade"))

    @app.route("/sgi/qualidade/reposicoes/<int:acao_id>/confirmar", methods=["POST"])
    @perfil_permitido("qualidade")
    def sgi_confirmar_reposicao(acao_id):
        if session.get("perfil") != "qualidade":
            flash("Operacao exclusiva do perfil Qualidade.")
            return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))
        qualidade_service.confirmar_reposicao_sgi(
            acao_id, request.form, session["usuario_id"], session.get("nome", "Usuario"))
        flash("Segunda verificacao registrada.")
        return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))

    @app.route("/sgi/qualidade/ncs/<int:nc_id>/decisao-gerencia", methods=["POST"])
    @perfil_permitido("gerencia")
    def sgi_decisao_gerencia(nc_id):
        qualidade_service.decidir_nc_critica(
            nc_id, request.form, session["usuario_id"], session.get("nome", "Usuario"))
        flash("Decisao da Gerencia registrada.")
        return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))

    @app.route("/sgi/qualidade/ncs/<int:nc_id>/eficacia", methods=["POST"])
    @perfil_permitido("qualidade")
    def sgi_validar_eficacia(nc_id):
        if session.get("perfil") != "qualidade":
            flash("Operacao exclusiva do perfil Qualidade.")
            return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))
        qualidade_service.validar_eficacia_sgi(
            nc_id, request.form, session["usuario_id"], session.get("nome", "Usuario"))
        flash("Eficacia registrada. Confira o resultado antes do encerramento.")
        return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))

    @app.route("/sgi/qualidade/ncs/<int:nc_id>/encerrar", methods=["POST"])
    @perfil_permitido("qualidade")
    def sgi_encerrar_nc(nc_id):
        if session.get("perfil") != "qualidade":
            flash("Operacao exclusiva do perfil Qualidade.")
            return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))
        qualidade_service.encerrar_nc_sgi(
            nc_id, session["usuario_id"], session.get("nome", "Usuario"))
        flash("Nao conformidade encerrada definitivamente.")
        return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))

    @app.route("/sgi/qualidade/consolidado")
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_consolidado_mensal():
        return render_template("sgi_consolidado.html", **qualidade_service.contexto_consolidado(request.args))
