"""Rotas do modulo de Almoxarifado."""

from datetime import datetime
from uuid import uuid4

from flask import flash, redirect, render_template, request, send_file, session, url_for

from modules.auth.decorators import perfil_permitido
from modules.parceiros.services import listar_parceiros_elegiveis

from .requisicoes import (
    ConflitoRequisicao,
    buscar_requisicao,
    cancelar_requisicao,
    confirmar_requisicao,
    decidir_excecao,
    emitir_requisicao,
    estornar_requisicao,
    gerar_pdf_requisicao,
    listar_insumos_requisicao,
    listar_requisicoes,
    normalizar_itens_form,
)

from .services import (
    CATEGORIAS_ALMOXARIFADO,
    ConflitoCorrecaoEntrada,
    UNIDADES_ALMOXARIFADO,
    atualizar_insumo_almoxarifado,
    buscar_insumo_almoxarifado_por_id,
    buscar_insumos_almoxarifado,
    buscar_entrada_estoque_almoxarifado,
    buscar_historico_correcoes_entrada,
    buscar_lotes_almoxarifado,
    buscar_lotes_almoxarifado_filtrado,
    buscar_movimentacoes_almoxarifado,
    buscar_movimentacoes_almoxarifado_filtrado,
    buscar_saldos_almoxarifado,
    buscar_saldos_almoxarifado_filtrado,
    calcular_resumo_almoxarifado,
    calcular_resumo_estoque_almoxarifado,
    calcular_resumo_rastreabilidade,
    corrigir_entrada_estoque_almoxarifado,
    perfil_pode_corrigir_entrada,
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
                salvar_entrada_estoque_almoxarifado(request.form, usuario=session.get("nome"))
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


    @app.route("/almoxarifado/entradas/<int:entrada_id>")
    @perfil_permitido("pcp", "gerencia")
    def detalhe_entrada_estoque_almoxarifado(entrada_id):
        entrada = buscar_entrada_estoque_almoxarifado(entrada_id)
        if not entrada:
            flash("Entrada de estoque não encontrada.")
            return redirect(url_for("rastreabilidade_almoxarifado"))
        return render_template(
            "almoxarifado_entrada_detalhe.html",
            entrada=entrada,
            historico=buscar_historico_correcoes_entrada(entrada_id),
            pode_corrigir=perfil_pode_corrigir_entrada(session.get("perfil")),
        )


    @app.route("/almoxarifado/entradas/<int:entrada_id>/corrigir", methods=["GET", "POST"])
    @perfil_permitido("gerencia")
    def corrigir_entrada_estoque(entrada_id):
        entrada = buscar_entrada_estoque_almoxarifado(entrada_id)
        if not entrada:
            flash("Entrada de estoque não encontrada.")
            return redirect(url_for("rastreabilidade_almoxarifado"))

        if request.method == "POST":
            try:
                corrigir_entrada_estoque_almoxarifado(
                    entrada_id,
                    request.form,
                    usuario=session.get("nome") or "Sistema",
                    usuario_id=session.get("usuario_id"),
                    perfil=session.get("perfil"),
                    idempotency_key=request.form.get("idempotency_key"),
                )
                flash("Entrada corrigida e estoque recalculado com sucesso.")
                return redirect(url_for("detalhe_entrada_estoque_almoxarifado", entrada_id=entrada_id))
            except (ValueError, PermissionError, ConflitoCorrecaoEntrada) as erro:
                flash(str(erro))
            except Exception:
                app.logger.exception("Falha transacional ao corrigir entrada %s", entrada_id)
                flash("Não foi possível corrigir a entrada. Nenhuma alteração foi gravada.")

        return render_template(
            "almoxarifado_entrada_corrigir.html",
            entrada=buscar_entrada_estoque_almoxarifado(entrada_id),
            idempotency_key=str(uuid4()),
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
    @perfil_permitido("pcp", "gerencia")
    def rastreabilidade_almoxarifado():
        insumo_id = request.args.get("insumo_id") or ""
        status_filtro = request.args.get("status") or "Todos"
        termo = request.args.get("termo") or ""
        data_entrada = request.args.get("data_entrada") or ""
        fornecedor = request.args.get("fornecedor") or ""
        numero_nf = request.args.get("numero_nf") or ""
        entrada_id = request.args.get("entrada_id") or ""

        insumos = buscar_insumos_almoxarifado("Todas", "Sim", "")
        lotes = buscar_lotes_almoxarifado_filtrado(
            insumo_id, status_filtro, termo, data_entrada, fornecedor, numero_nf, entrada_id
        )
        resumo = calcular_resumo_rastreabilidade(lotes)

        return render_template(
            "almoxarifado_rastreabilidade.html",
            insumos=insumos,
            lotes=lotes,
            resumo=resumo,
            insumo_id=insumo_id,
            status_filtro=status_filtro,
            termo=termo,
            data_entrada=data_entrada,
            fornecedor=fornecedor,
            numero_nf=numero_nf,
            entrada_id=entrada_id,
        )


    def _usuario_sessao():
        return {
            "id": session.get("usuario_id"),
            "nome": session.get("nome") or "Sistema",
            "perfil": session.get("perfil") or "",
        }


    @app.route("/almoxarifado/requisicoes")
    @perfil_permitido("pcp", "gerencia")
    def requisicoes_almoxarifado():
        filtros = {
            "status": request.args.get("status") or "Todos",
            "tipo": request.args.get("tipo") or "Todos",
            "parceiro_id": request.args.get("parceiro_id") or "",
            "data_inicio": request.args.get("data_inicio") or "",
            "data_fim": request.args.get("data_fim") or "",
            "termo": request.args.get("termo") or "",
        }
        return render_template(
            "almoxarifado_requisicoes.html",
            requisicoes=listar_requisicoes(filtros),
            parceiros=listar_parceiros_elegiveis(),
            filtros=filtros,
            pode_emitir=session.get("perfil") in {"admin", "pcp"},
        )


    @app.route("/almoxarifado/requisicoes/nova", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def nova_requisicao_almoxarifado():
        if request.method == "POST":
            try:
                resultado = emitir_requisicao(
                    request.form,
                    normalizar_itens_form(request.form),
                    usuario=_usuario_sessao(),
                    idempotency_key=request.form.get("idempotency_key"),
                )
                if resultado.get("reaplicada"):
                    flash("Requisição já havia sido emitida; nenhum lançamento foi duplicado.")
                elif resultado["status"] == "AGUARDANDO_APROVACAO":
                    flash("Requisição excepcional emitida e enviada para aprovação distinta.")
                else:
                    flash("Requisição emitida e estoque reservado sem baixa física.")
                return redirect(url_for("detalhe_requisicao_almoxarifado", requisicao_id=resultado["id"]))
            except (ValueError, PermissionError, ConflitoRequisicao) as erro:
                flash(str(erro))
            except Exception:
                app.logger.exception("Falha ao emitir requisição de almoxarifado")
                flash("Não foi possível emitir a requisição. Nenhuma alteração foi gravada.")
        return render_template(
            "almoxarifado_requisicao_nova.html",
            parceiros=listar_parceiros_elegiveis(),
            insumos=listar_insumos_requisicao(),
            idempotency_key=str(uuid4()),
        )


    @app.route("/almoxarifado/requisicoes/<int:requisicao_id>")
    @perfil_permitido("pcp", "gerencia")
    def detalhe_requisicao_almoxarifado(requisicao_id):
        requisicao = buscar_requisicao(requisicao_id)
        if not requisicao:
            flash("Requisição não encontrada.")
            return redirect(url_for("requisicoes_almoxarifado"))
        return render_template(
            "almoxarifado_requisicao_detalhe.html",
            requisicao=requisicao,
            perfil=session.get("perfil"),
            usuario_id=session.get("usuario_id"),
            chave_acao=str(uuid4()),
        )


    @app.route("/almoxarifado/requisicoes/<int:requisicao_id>/decidir", methods=["POST"])
    @perfil_permitido("gerencia")
    def decidir_requisicao_almoxarifado(requisicao_id):
        try:
            aprovar = request.form.get("decisao") == "aprovar"
            decidir_excecao(
                requisicao_id,
                aprovar=aprovar,
                motivo=request.form.get("motivo"),
                usuario=_usuario_sessao(),
                versao=request.form.get("versao"),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Exceção aprovada e liberada para entrega." if aprovar else "Exceção rejeitada e reserva liberada.")
        except (ValueError, PermissionError, ConflitoRequisicao) as erro:
            flash(str(erro))
        except Exception:
            app.logger.exception("Falha ao decidir requisição %s", requisicao_id)
            flash("Não foi possível registrar a decisão. Nenhuma alteração foi gravada.")
        return redirect(url_for("detalhe_requisicao_almoxarifado", requisicao_id=requisicao_id))


    @app.route("/almoxarifado/requisicoes/<int:requisicao_id>/confirmar", methods=["POST"])
    @perfil_permitido("pcp")
    def confirmar_requisicao_almoxarifado(requisicao_id):
        entregas = [
            {"item_id": item_id, "quantidade": request.form.get(f"quantidade_{item_id}", "0")}
            for item_id in request.form.getlist("item_id")
        ]
        try:
            confirmar_requisicao(
                requisicao_id,
                entregas,
                documento_confirmado=request.form.get("documento_confirmado"),
                usuario=_usuario_sessao(),
                versao=request.form.get("versao"),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Entrega confirmada, baixa FIFO registrada e reserva remanescente liberada.")
        except (ValueError, PermissionError, ConflitoRequisicao) as erro:
            flash(str(erro))
        except Exception:
            app.logger.exception("Falha ao confirmar requisição %s", requisicao_id)
            flash("Não foi possível confirmar a entrega. Nenhuma alteração foi gravada.")
        return redirect(url_for("detalhe_requisicao_almoxarifado", requisicao_id=requisicao_id))


    @app.route("/almoxarifado/requisicoes/<int:requisicao_id>/cancelar", methods=["POST"])
    @perfil_permitido("pcp")
    def cancelar_requisicao_almoxarifado(requisicao_id):
        try:
            cancelar_requisicao(
                requisicao_id,
                motivo=request.form.get("motivo"),
                usuario=_usuario_sessao(),
                versao=request.form.get("versao"),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Requisição cancelada e reserva liberada sem baixa física.")
        except (ValueError, PermissionError, ConflitoRequisicao) as erro:
            flash(str(erro))
        except Exception:
            app.logger.exception("Falha ao cancelar requisição %s", requisicao_id)
            flash("Não foi possível cancelar a requisição. Nenhuma alteração foi gravada.")
        return redirect(url_for("detalhe_requisicao_almoxarifado", requisicao_id=requisicao_id))


    @app.route("/almoxarifado/requisicoes/<int:requisicao_id>/estornar", methods=["POST"])
    @perfil_permitido("gerencia")
    def estornar_requisicao_almoxarifado(requisicao_id):
        try:
            estornar_requisicao(
                requisicao_id,
                motivo=request.form.get("motivo"),
                usuario=_usuario_sessao(),
                versao=request.form.get("versao"),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Baixa estornada por movimentos compensatórios; histórico preservado.")
        except (ValueError, PermissionError, ConflitoRequisicao) as erro:
            flash(str(erro))
        except Exception:
            app.logger.exception("Falha ao estornar requisição %s", requisicao_id)
            flash("Não foi possível estornar a requisição. Nenhuma alteração foi gravada.")
        return redirect(url_for("detalhe_requisicao_almoxarifado", requisicao_id=requisicao_id))


    @app.route("/almoxarifado/requisicoes/<int:requisicao_id>/pdf")
    @perfil_permitido("pcp", "gerencia")
    def imprimir_requisicao_almoxarifado(requisicao_id):
        requisicao = buscar_requisicao(requisicao_id)
        if not requisicao:
            flash("Requisição não encontrada.")
            return redirect(url_for("requisicoes_almoxarifado"))
        return send_file(
            __import__("io").BytesIO(gerar_pdf_requisicao(requisicao_id)),
            mimetype="application/pdf",
            as_attachment=False,
            download_name=f"{requisicao['numero']}.pdf",
        )



    # ============================================================
    # MÓDULO RECEITAS DOS SKUS
