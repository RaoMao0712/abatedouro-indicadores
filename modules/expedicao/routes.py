"""Rotas de Expedicao, Embalagem e estoques PI/PA."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from database import conectar, q
from modules.auth.decorators import perfil_permitido
from modules.producao.services import buscar_op_por_id

from .services import (
    BANDEJAS_POR_CAIXA,
    buscar_apontamento_embalagem_primaria_por_op,
    buscar_apontamentos_embalagem_primaria,
    buscar_caixas_pa,
    buscar_caixas_disponiveis_transferencia,
    buscar_expedicao_por_id,
    buscar_expedicoes,
    buscar_itens_expedicao,
    buscar_movimentacoes_pa,
    buscar_movimentacoes_estoque_pi,
    buscar_ops_com_saldo_pi,
    buscar_ops_para_embalagem_primaria,
    buscar_saldo_pa_por_local,
    buscar_saldos_estoque_pi,
    calcular_fechamento_industrial_op,
    calcular_resumo_expedicao,
    calcular_resumo_estoques_pi_pa,
    calcular_resumo_itens_expedicao,
    confirmar_transferencia_romaneio,
    configurar_integracoes,
    finalizar_embalagem_secundaria_op,
    registrar_apontamento_embalagem_primaria,
    registrar_caixa_pa_manual,
    registrar_caixas_pa_lote,
    resetar_processamento_op,
    salvar_romaneio_expedicao,
)


def register_expedicao_routes(app, integracoes=None):
    integracoes = integracoes or {}
    configurar_integracoes(criar_banco=integracoes.get("criar_banco"))

    @app.route("/embalagem-primaria", methods=["GET", "POST"])
    @perfil_permitido("pcp", "producao")
    def embalagem_primaria():
        if request.method == "POST":
            try:
                op_id = int(request.form.get("op_id") or 0)
                op = buscar_op_por_id(op_id)
                resultado = registrar_apontamento_embalagem_primaria(
                    op=op,
                    quantidade_bandejas=request.form.get("quantidade_bandejas"),
                    observacoes=request.form.get("observacoes") or "",
                    kg_produzidos=request.form.get("kg_produzidos"),
                    pacotes_1_ave=request.form.get("pacotes_1_ave"),
                    pacotes_2_aves=request.form.get("pacotes_2_aves")
                )
                if resultado.get("tipo") == "encerramento_primaria":
                    flash(
                        "Galinha Inteira encerrada na Embalagem Primaria. "
                        f"Lote PA: {resultado['codigo_lote']} | "
                        f"Unidades vendaveis: {resultado['unidades_vendaveis']:.0f} | "
                        f"Peso produzido: {resultado['kg_produzidos']:.3f} kg."
                    )
                else:
                    flash("Embalagem Primária apontada com sucesso. O Estoque PI foi atualizado e a OP permanece pendente para Embalagem Secundária.")
            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("embalagem_primaria", op_id=request.form.get("op_id") or ""))

        op_id_selecionada = request.args.get("op_id", "")
        modo_edicao = request.args.get("editar") == "1"
        apontamento_edicao = None

        if modo_edicao and op_id_selecionada:
            try:
                apontamento_edicao = buscar_apontamento_embalagem_primaria_por_op(int(op_id_selecionada))
            except (TypeError, ValueError):
                apontamento_edicao = None

        ops = buscar_ops_para_embalagem_primaria()
        apontamentos = buscar_apontamentos_embalagem_primaria()
        saldos_pi = buscar_saldos_estoque_pi()
        caixas_pa = buscar_caixas_pa()
        resumo = calcular_resumo_estoques_pi_pa(saldos_pi, caixas_pa)

        return render_template(
            "embalagem_primaria.html",
            ops=ops,
            apontamentos=apontamentos,
            saldos_pi=saldos_pi,
            resumo=resumo,
            op_id_selecionada=str(op_id_selecionada),
            apontamento_edicao=apontamento_edicao,
            modo_edicao=modo_edicao
        )


    @app.route("/estoque-produtos")
    @perfil_permitido("pcp")
    def estoque_produtos():
        saldos_pi = buscar_saldos_estoque_pi()
        movimentacoes_pi = buscar_movimentacoes_estoque_pi()
        movimentacoes_pa = buscar_movimentacoes_pa()
        caixas_pa = buscar_caixas_pa()
        saldo_pa_por_local = buscar_saldo_pa_por_local()
        resumo = calcular_resumo_estoques_pi_pa(saldos_pi, caixas_pa)

        return render_template(
            "estoque_produtos.html",
            saldos_pi=saldos_pi,
            movimentacoes_pi=movimentacoes_pi,
            movimentacoes_pa=movimentacoes_pa,
            caixas_pa=caixas_pa,
            saldo_pa_por_local=saldo_pa_por_local,
            resumo=resumo
        )


    @app.route("/embalagem-secundaria/<int:op_id>/finalizar", methods=["POST"])
    @perfil_permitido("pcp")
    def finalizar_embalagem_secundaria(op_id):
        try:
            fechamento = finalizar_embalagem_secundaria_op(op_id)
            flash(
                "OP encerrada com sucesso. "
                f"Peso oficial: {fechamento['peso_liquido_total']:.3f} kg | "
                f"Caixas: {fechamento['caixas']} | "
                f"Bandejas: {fechamento['bandejas_consumidas']:.0f}."
            )
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("embalagem_secundaria", op_id=op_id))


    @app.route("/embalagem-secundaria/<int:op_id>/resetar", methods=["POST"])
    @perfil_permitido("pcp")
    def resetar_embalagem_secundaria_op(op_id):
        try:
            resultado = resetar_processamento_op(op_id, request.form.get("confirmacao_reset"))
            flash(
                "OP resetada com sucesso. "
                f"Caixas removidas: {resultado['caixas_removidas']}. "
                "A OP voltou para Aberta e pode ser reapontada desde a Embalagem Primária."
            )
            return redirect(url_for("embalagem_primaria", op_id=op_id))
        except ValueError as erro:
            flash(str(erro))
            return redirect(url_for("embalagem_secundaria", op_id=op_id))


    @app.route("/embalagem-secundaria", methods=["GET", "POST"])

    @perfil_permitido("pcp")
    def embalagem_secundaria():
        if request.method == "POST":
            try:
                if request.form.get("modo_lancamento") == "lote":
                    codigos = registrar_caixas_pa_lote(request.form)
                    flash(f"{len(codigos)} caixas registradas no Estoque PA com sucesso.")
                else:
                    codigo_caixa = registrar_caixa_pa_manual(request.form)
                    flash(f"Caixa {codigo_caixa} registrada no Estoque PA com sucesso.")
            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("embalagem_secundaria", op_id=request.form.get("op_principal") or ""))

        saldos_pi = buscar_ops_com_saldo_pi()
        caixas_pa = buscar_caixas_pa()
        resumo = calcular_resumo_estoques_pi_pa(saldos_pi, caixas_pa)
        op_id_selecionada = request.args.get("op_id", "")
        op_selecionada = None
        caixas_op = []
        fechamento_op = None

        if op_id_selecionada:
            try:
                op_id_int = int(op_id_selecionada)
            except Exception:
                op_id_int = None

            if op_id_int:
                # A OP deve abrir para lançamento contínuo sempre que houver PI disponível.
                # O painel de fechamento é complementar e não pode impedir a abertura da tela de caixas.
                op_selecionada = next((item for item in saldos_pi if int(item["op_id"]) == op_id_int), None)

                try:
                    fechamento_op = calcular_fechamento_industrial_op(op_id_int)
                except Exception:
                    fechamento_op = None

                # Quando o saldo PI chega a zero, a OP deixa de aparecer em saldos_pi.
                # Ainda assim ela precisa permanecer carregada para conferência e encerramento.
                if op_selecionada is None and fechamento_op:
                    op_base = fechamento_op["op"]
                    op_selecionada = {
                        "op_id": op_id_int,
                        "data_op": op_base["data"],
                        "sku": op_base["sku"] or "Galinha Cortada",
                        "saldo_bandejas": fechamento_op["saldo_pi"],
                    }

                try:
                    conn = conectar()
                    cursor = conn.cursor()
                    cursor.execute(q("""
                    SELECT cx.*
                    FROM pa_caixas cx
                    INNER JOIN pa_caixa_composicao comp ON comp.caixa_id = cx.id
                    WHERE comp.op_id = ?
                    ORDER BY cx.id DESC
                    LIMIT 80
                    """), (op_id_int,))
                    caixas_op = cursor.fetchall()
                    conn.close()
                except Exception:
                    caixas_op = []

        return render_template(
            "embalagem_secundaria.html",
            saldos_pi=saldos_pi,
            caixas_pa=caixas_pa,
            resumo=resumo,
            hoje=datetime.now().strftime("%Y-%m-%d"),
            bandejas_por_caixa=BANDEJAS_POR_CAIXA,
            op_id_selecionada=str(op_id_selecionada),
            op_selecionada=op_selecionada,
            caixas_op=caixas_op,
            fechamento_op=fechamento_op
        )

    @app.route("/expedicao")
    @perfil_permitido("pcp")
    def expedicao():
        hoje = datetime.now()
        primeiro_dia_mes = hoje.replace(day=1).strftime("%Y-%m-%d")
        data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
        data_fim = request.args.get("data_fim") or hoje.strftime("%Y-%m-%d")
        status = request.args.get("status") or "Todos"

        expedicoes = buscar_expedicoes(data_inicio, data_fim, status)
        resumo = calcular_resumo_expedicao(expedicoes)

        return render_template(
            "expedicao.html",
            expedicoes=expedicoes,
            resumo=resumo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            status=status,
            status_opcoes=["Todos", "Aberto", "Concluído", "Cancelado"]
        )

    @app.route("/expedicao/novo", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def novo_romaneio_expedicao():
        hoje = datetime.now().strftime("%Y-%m-%d")

        if request.method == "POST":
            try:
                numero_romaneio = salvar_romaneio_expedicao(request.form)
                flash(f"Romaneio {numero_romaneio} criado com sucesso.")
                return redirect(url_for("expedicao"))
            except Exception as erro:
                flash(f"Erro ao criar romaneio: {erro}")

        return render_template(
            "novo_romaneio.html",
            hoje=hoje
        )

    @app.route("/expedicao/<int:expedicao_id>", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def detalhe_romaneio_expedicao(expedicao_id):
        expedicao = buscar_expedicao_por_id(expedicao_id)

        if not expedicao:
            flash("Romaneio não encontrado.")
            return redirect(url_for("expedicao"))

        if request.method == "POST":
            try:
                resultado = confirmar_transferencia_romaneio(
                    expedicao_id,
                    request.form.getlist("caixa_ids")
                )
                flash(
                    "Romaneio de transferencia concluido. "
                    f"Caixas: {resultado['caixas']} | "
                    f"Peso liquido: {resultado['peso_liquido']:.3f} kg."
                )
                return redirect(url_for("detalhe_romaneio_expedicao", expedicao_id=expedicao_id))
            except Exception as erro:
                flash(f"Erro ao confirmar transferencia: {erro}")

        itens = buscar_itens_expedicao(expedicao_id)
        resumo_itens = calcular_resumo_itens_expedicao(itens)
        caixas_disponiveis = []
        if expedicao["status"] == "Aberto":
            caixas_disponiveis = buscar_caixas_disponiveis_transferencia()

        return render_template(
            "romaneio_detalhe.html",
            expedicao=expedicao,
            itens=itens,
            resumo_itens=resumo_itens,
            caixas_disponiveis=caixas_disponiveis,
            skus=["Galinha Cortada", "Galinha Inteira"]
        )
