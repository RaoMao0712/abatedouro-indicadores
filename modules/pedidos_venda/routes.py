"""Rotas do fluxo comercial de venda direta."""

from datetime import datetime
from io import BytesIO
import secrets

from flask import flash, redirect, render_template, request, send_file, session, url_for

from modules.auth.decorators import perfil_permitido
from modules.clientes.services import listar_clientes
from modules.engenharia_produtos.services import listar_catalogo
from .pdf import gerar_pdf_pedido
from .services import (CONDICOES_PAGAMENTO, FORMAS_PAGAMENTO, STATUS, UNIDADES,
    buscar_pedido, cancelar_pedido, catalogo_produtos_venda, confirmar_pedido, decimal_centavos, decimal_milesimos,
    gerar_romaneio_pedido, listar_pedidos, listar_romaneios_elegiveis, resumo_pedidos, salvar_pedido,
    vincular_romaneios_existentes)


def _dados_formulario(pedido=None):
    clientes = [dict(cliente) for cliente in listar_clientes(somente_ativos=True)]
    destinos = {}
    for cliente in clientes:
        partes = [cliente.get("endereco"), cliente.get("complemento"), cliente.get("bairro")]
        cidade_uf = " / ".join(x for x in (cliente.get("cidade"), cliente.get("uf")) if x)
        partes.extend((cidade_uf, cliente.get("cep")))
        destinos[str(cliente["id"])] = ", ".join(str(x).strip() for x in partes if x and str(x).strip())
    produtos, _ = listar_catalogo({"status": "Sim"})
    return {
        "pedido": pedido, "clientes": clientes, "destinos_clientes": destinos,
        "produtos": catalogo_produtos_venda(produtos), "unidades": UNIDADES,
        "formas": FORMAS_PAGAMENTO, "condicoes": CONDICOES_PAGAMENTO,
        "hoje": datetime.now().strftime("%Y-%m-%d"),
    }


def register_pedidos_venda_routes(app):
    app.jinja_env.globals["pedido_centavos"] = decimal_centavos
    app.jinja_env.globals["pedido_milesimos"] = decimal_milesimos

    @app.route("/pedidos-venda")
    @perfil_permitido("pcp", "expedicao", "gerencia")
    def pedidos_venda():
        filtros={k:request.args.get(k) or "" for k in ("numero","data_inicio","data_fim","cliente_id","destino","produto","status","responsavel","forma_pagamento","condicao_pagamento")}
        pedidos=listar_pedidos(filtros)
        return render_template("pedidos_venda.html",pedidos=pedidos,resumo=resumo_pedidos(pedidos),filtros=filtros,
            clientes=listar_clientes(somente_ativos=False),status_opcoes=STATUS,formas=FORMAS_PAGAMENTO,condicoes=CONDICOES_PAGAMENTO)

    @app.route("/pedidos-venda/novo",methods=["GET","POST"])
    @perfil_permitido("pcp", "expedicao", "gerencia")
    def novo_pedido_venda():
        if request.method=="POST":
            try:
                pedido_id,numero=salvar_pedido(request.form)
                if request.form.get("acao") == "confirmar":
                    confirmar_pedido(pedido_id)
                    flash(f"Pedido {numero} salvo e confirmado sem movimentar estoque.")
                else:
                    flash(f"Pedido {numero} salvo como rascunho.")
                return redirect(url_for("detalhe_pedido_venda",pedido_id=pedido_id))
            except (ValueError,PermissionError) as erro: flash(str(erro))
        return render_template("pedido_venda_form.html", **_dados_formulario())

    @app.route("/pedidos-venda/<int:pedido_id>/editar",methods=["GET","POST"])
    @perfil_permitido("pcp", "expedicao", "gerencia")
    def editar_pedido_venda(pedido_id):
        pedido=buscar_pedido(pedido_id)
        if not pedido: flash("Pedido não encontrado."); return redirect(url_for("pedidos_venda"))
        if pedido["status"]!="RASCUNHO": flash("Somente rascunhos podem ser editados."); return redirect(url_for("detalhe_pedido_venda",pedido_id=pedido_id))
        if request.method=="POST":
            try:
                salvar_pedido(request.form,pedido_id)
                if request.form.get("acao") == "confirmar":
                    confirmar_pedido(pedido_id)
                    flash("Pedido atualizado e confirmado sem movimentar estoque.")
                else:
                    flash("Pedido atualizado.")
                return redirect(url_for("detalhe_pedido_venda",pedido_id=pedido_id))
            except (ValueError,PermissionError) as erro: flash(str(erro))
        return render_template("pedido_venda_form.html", **_dados_formulario(pedido))

    @app.route("/pedidos-venda/<int:pedido_id>",methods=["GET","POST"])
    @perfil_permitido("pcp", "expedicao", "gerencia")
    def detalhe_pedido_venda(pedido_id):
        if request.method=="POST":
            try:
                acao=request.form.get("acao")
                if acao=="confirmar": confirmar_pedido(pedido_id); flash("Pedido confirmado sem movimentar estoque.")
                elif acao=="cancelar": cancelar_pedido(pedido_id,request.form.get("motivo")); flash("Saldo pendente do pedido cancelado.")
                elif acao=="gerar_romaneio":
                    quantidades={chave.split("_",1)[1]:valor for chave,valor in request.form.items() if chave.startswith("q_")}
                    expedicao_id,numero=gerar_romaneio_pedido(pedido_id,quantidades,data=request.form.get("data_romaneio"),responsavel=request.form.get("responsavel"),versao_esperada=request.form.get("versao"))
                    flash(f"Romaneio {numero} criado. Reserve os itens físicos para concluir.")
                    return redirect(url_for("detalhe_romaneio_expedicao",expedicao_id=expedicao_id))
                elif acao=="vincular_romaneio_existente":
                    romaneio_ids = request.form.getlist("romaneio_ids[]")
                    vincular_romaneios_existentes(
                        pedido_id, romaneio_ids,
                        request.form.get("idempotency_key"),
                        confirmar_destino=request.form.get("confirmar_destino") == "1")
                    quantidade = len(romaneio_ids)
                    flash(f"{quantidade} romaneio(s) vinculado(s) sem nova movimentação de estoque.")
                else: raise ValueError("Ação inválida.")
            except (ValueError,PermissionError) as erro: flash(str(erro))
            return redirect(url_for("detalhe_pedido_venda",pedido_id=pedido_id))
        pedido=buscar_pedido(pedido_id)
        if not pedido: flash("Pedido não encontrado."); return redirect(url_for("pedidos_venda"))
        saldos_selecao = {}
        for item in pedido["itens"]:
            unidade = "AVE" if item.get("aves_por_unidade_operacional") else item["unidade_comercial"]
            saldos_selecao[unidade] = saldos_selecao.get(unidade, 0) + int(item["saldo_pendente_exibicao_mil"])
        return render_template("pedido_venda_detalhe.html",pedido=pedido,status_descricoes=STATUS,
            hoje=datetime.now().strftime("%Y-%m-%d"),pode_cancelar=session.get("perfil") in {"admin","gerencia"},
            romaneios_elegiveis=listar_romaneios_elegiveis(pedido_id),
            saldos_selecao=saldos_selecao,
            vinculo_idempotency_key=secrets.token_urlsafe(24))

    @app.route("/pedidos-venda/<int:pedido_id>/imprimir")
    @perfil_permitido("pcp", "expedicao", "gerencia")
    def imprimir_pedido_venda(pedido_id):
        pedido=buscar_pedido(pedido_id)
        if not pedido: flash("Pedido não encontrado."); return redirect(url_for("pedidos_venda"))
        return send_file(BytesIO(gerar_pdf_pedido(pedido)),mimetype="application/pdf",as_attachment=False,
                         download_name=f"{pedido['numero']}.pdf")
