"""Rotas de Expedicao, Embalagem e estoques PI/PA."""

from datetime import datetime
from decimal import Decimal
import secrets
import uuid

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for
from io import BytesIO

from config import EMPRESA_EMITENTE, ESTABELECIMENTO_DOCUMENTO, IDENTIFICACAO_TECNOLOGIA
from database import conectar, q
from modules.auth.decorators import perfil_permitido
from modules.producao.services import buscar_op_por_id
from modules.producao.operacoes_op import (
    estornar_op_integral,
    preflight_operacao_op,
    preflight_retomada_embalagem_secundaria,
    retomar_embalagem_secundaria,
)

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
    calcular_resumo_expedicao,
    calcular_resumo_estoques_pi_pa,
    calcular_resumo_itens_expedicao,
    calcular_resumo_mz,
    confirmar_transferencia_romaneio,
    configurar_integracoes,
    finalizar_embalagem_secundaria_op,
    montar_contexto_estoque_produtos,
    paginar_expedicoes,
    registrar_apontamento_embalagem_primaria,
    registrar_caixa_pa_manual,
    registrar_caixas_pa_lote,
    salvar_romaneio_expedicao,
)
from .estornos_embalagem import (
    estornar_caixa_embalagem_secundaria,
    estornar_caixas_embalagem_secundaria_em_lote,
    funcionalidade_estorno_habilitada,
)
from .conferencia_embalagem import confirmar_conferencia_op, obter_conferencia_op
from .encerramento_op import preflight_encerramento_op
from .relatorio_conferencia_embalagem import gerar_relatorio_conferencia_embalagem_pdf
from .estoque_service import (
    DESTINOS_CONTROLADOS,
    TIPOS_ROMANEIO,
    TIPOS_SAIDA,
    bloquear_produto,
    buscar_caixas_elegiveis_op,
    buscar_caixas_por_op_e_peso,
    buscar_estoque_operacional,
    buscar_historico_estoque,
    buscar_op_para_romaneio,
    cancelar_romaneio,
    concluir_romaneio,
    destinar_produto,
    editar_romaneio_aberto,
    estornar_romaneio,
    formatar_data_hora_emissao_manaus,
    formatar_data_brasileira,
    formatar_documento_brasileiro,
    obter_marco_zero,
    registrar_emissao_romaneio,
    registrar_itens_historicos,
    remover_item_reservado,
    remover_itens_reservados_op,
    reservar_itens,
)
from modules.qualidade.produtos_nao_conformes import listar_locais_segregacao, MOTIVOS
from modules.qualidade.liberacoes import (
    inventario_legado_fisico,
    remover_reserva_operacional, reservar_operacional,
    saldos_legados_operacionais,
)
from modules.label_printing.services import listar_jobs_caixas, solicitar_reimpressao
from modules.clientes.services import listar_clientes
from .relatorio_entregas import gerar_relatorio_entregas_pdf


def _csrf_estorno_valido():
    informado = str(request.form.get("csrf_token") or "")
    esperado = str(session.get("estorno_embalagem_csrf") or "")
    return bool(informado and esperado and secrets.compare_digest(informado, esperado))


from .consolidado_estoque import ROTULOS_SITUACOES, consolidar_estoque_camara
from .relatorio_estoque import gerar_relatorio_estoque_pdf
from .relatorio_nc_pdf import gerar_relatorio_nc_pdf
from .relatorio_nc_service import (
    consolidar_selecao, emitir_relatorio_nc, listar_relatorios_nc,
    listar_saldos_nc, obter_relatorio_nc,
)
from modules.pedidos_venda.services import plano_romaneio


def _itens_nc_caixas(form):
    itens = []
    for caixa_id in form.getlist("nc_caixa_id"):
        prefixo = f"nc_{caixa_id}_"
        itens.append({
            "caixa_id": caixa_id,
            "lote": form.get(prefixo + "lote"),
            "apresentacao": form.get(prefixo + "apresentacao"),
            "quantidade": form.get(prefixo + "quantidade"),
            "peso": form.get(prefixo + "peso"),
            "unidade": form.get(prefixo + "unidade"),
            "motivo": form.get(prefixo + "motivo"),
            "descricao": form.get(prefixo + "descricao"),
            "local_estoque_id": form.get(prefixo + "local"),
            "observacoes": form.get(prefixo + "observacoes"),
        })
    return itens


def _itens_nc_galinha_inteira(form):
    itens = []
    for apresentacao in ("V1", "V2"):
        if form.get(f"nc_{apresentacao}_ativo"):
            prefixo = f"nc_{apresentacao}_"
            itens.append({
                "apresentacao": apresentacao,
                "motivo": form.get(prefixo + "motivo"),
                "descricao": form.get(prefixo + "descricao"),
                "local_estoque_id": form.get(prefixo + "local"),
                "observacoes": form.get(prefixo + "observacoes"),
            })
    return itens


def alinhar_resumo_ao_consolidado(resumo, consolidado, saldos_legados):
    """Faz os cards consumirem a mesma fotografia física do consolidado por produto."""
    resumo = dict(resumo)
    campos = {
        "unidades_fisicas": ("total_fisico", None),
        "unidades_disponiveis": ("disponivel", None),
        "unidades_reservadas": ("reservado", None),
        "unidades_bloqueadas": ("nao_conforme_bloqueado", None),
        "unidades_reprocessamento": ("reprocessamento", None),
        "unidades_outras_condicoes": ("aguardando_liberacao", None),
        "peso_fisico": ("total_fisico", "peso_kg"),
        "peso_disponivel": ("disponivel", "peso_kg"),
        "peso_reservado": ("reservado", "peso_kg"),
        "peso_bloqueado": ("nao_conforme_bloqueado", "peso_kg"),
        "peso_reprocessamento": ("reprocessamento", "peso_kg"),
        "peso_outras_condicoes": ("aguardando_liberacao", "peso_kg"),
    }
    for campo, (situacao, unidade_fixa) in campos.items():
        total = Decimal("0")
        for grupo in consolidado.get("grupos", []):
            quantidades = (
                grupo.get("total_fisico", {}) if situacao == "total_fisico"
                else grupo.get("situacoes", {}).get(situacao, {}).get("quantidades", {})
            )
            unidade = unidade_fixa
            if unidade is None:
                unidade = "caixas" if "caixas" in quantidades else "pacotes"
            total += Decimal(str(quantidades.get(unidade, 0) or 0))
        resumo[campo] = float(total)
    situacoes_cards = {
        "quantidades_fisicas": "total_fisico",
        "quantidades_disponiveis": "disponivel",
        "quantidades_reservadas": "reservado",
        "quantidades_bloqueadas": "nao_conforme_bloqueado",
        "quantidades_reprocessamento": "reprocessamento",
        "quantidades_outras_condicoes": "aguardando_liberacao",
    }
    for campo, situacao in situacoes_cards.items():
        totais = {unidade: Decimal("0") for unidade in (
            "caixas", "bandejas", "pacotes", "galinhas", "peso_kg",
        )}
        for grupo in consolidado.get("grupos", []):
            quantidades = (
                grupo.get("total_fisico", {}) if situacao == "total_fisico"
                else grupo.get("situacoes", {}).get(situacao, {}).get("quantidades", {})
            )
            for unidade in totais:
                totais[unidade] += Decimal(str(quantidades.get(unidade, 0) or 0))
        resumo[campo] = {unidade: float(valor) for unidade, valor in totais.items()}
    resumo["bandejas_legado"] = float(sum(
        Decimal(str(grupo.get("total_fisico", {}).get("bandejas", 0) or 0))
        for grupo in consolidado.get("grupos", [])
    ))
    resumo["peso_legado_disponivel"] = float(sum(
        Decimal(int(item["saldo_operacional_g"] or 0)) / Decimal(1000)
        for item in saldos_legados
    ))
    return resumo


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
                    pacotes_2_aves=request.form.get("pacotes_2_aves"),
                    nao_conformes=_itens_nc_galinha_inteira(request.form),
                    usuario=session.get("nome") or "Usuário",
                    perfil=session.get("perfil") or "",
                    idempotency_key=request.form.get("idempotency_key") or str(uuid.uuid4()),
                    versao_esperada=request.form.get("versao_operacional"),
                    ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
                    request_id=request.headers.get("X-Request-ID"),
                )
                if resultado.get("tipo") == "encerramento_primaria":
                    flash(
                        "Galinha Inteira encerrada na Embalagem Primaria. "
                        f"Posicoes: {', '.join(resultado['codigos_lote'])} | "
                        f"Pacotes: {resultado['unidades_vendaveis']:.0f} | "
                        f"Galinhas: {resultado['aves_embaladas']:.0f}."
                    )
                else:
                    flash("Embalagem Primária apontada com sucesso. O Estoque PI foi atualizado e a OP permanece pendente para Embalagem Secundária.")
            except (ValueError, PermissionError, RuntimeError) as erro:
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
            modo_edicao=modo_edicao,
            locais_segregacao=listar_locais_segregacao(),
            motivos_nc=MOTIVOS,
        )


    @app.route("/estoque-produtos")
    @perfil_permitido("pcp", "qualidade")
    def estoque_produtos():
        contexto = montar_contexto_estoque_produtos()

        return render_template(
            "estoque_produtos.html",
            **contexto
        )


    @app.route("/embalagem-secundaria/<int:op_id>/finalizar", methods=["POST"])
    @perfil_permitido("pcp", "producao")
    def finalizar_embalagem_secundaria(op_id):
        try:
            fechamento = finalizar_embalagem_secundaria_op(
                op_id, nao_conformes=_itens_nc_caixas(request.form),
                conferencia_hash=request.form.get("conferencia_hash"),
                exigir_conferencia=True,
                usuario=session.get("nome") or "Usuário",
                perfil=session.get("perfil") or "",
                idempotency_key=request.form.get("idempotency_key"),
                versao_esperada=request.form.get("versao_operacional"),
                ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
                request_id=request.headers.get("X-Request-ID"),
            )
            flash(
                ("A OP já estava encerrada; nenhum movimento foi duplicado. "
                 if fechamento.get("ja_encerrada") else "OP encerrada com sucesso. ")
                + f"PA operacional liberado: {fechamento['caixas_liberadas']} caixa(s) | "
                f"Peso líquido: {fechamento['peso_liquido_total']:.3f} kg | "
                f"Bandejas: {fechamento['bandejas_consumidas']:.0f}."
            )
        except (ValueError, PermissionError) as erro:
            return render_template(
                "erro_operacional.html", titulo=f"OP #{op_id} não encerrada",
                mensagem=str(erro), retorno=url_for("embalagem_secundaria", op_id=op_id),
            ), 409
        except Exception as erro:
            app.logger.exception("Falha transacional ao encerrar a OP #%s", op_id)
            mensagem_publica = str(erro) if "Identificador:" in str(erro) else (
                "O encerramento falhou e foi revertido integralmente. "
                "Nenhum PI ou PA foi duplicado. Consulte o suporte com o número da OP."
            )
            return render_template(
                "erro_operacional.html", titulo=f"OP #{op_id} não encerrada",
                mensagem=mensagem_publica,
                retorno=url_for("embalagem_secundaria", op_id=op_id),
            ), 500

        return redirect(url_for("embalagem_secundaria", op_id=op_id))


    @app.route("/embalagem-secundaria/<int:op_id>/estornar", methods=["POST"])
    @perfil_permitido("pcp", "gerencia")
    def estornar_embalagem_secundaria_op(op_id):
        try:
            if not _csrf_estorno_valido():
                raise PermissionError("Sessão de confirmação expirada. Atualize a página e tente novamente.")
            resultado = estornar_op_integral(
                op_id,
                usuario=session.get("nome") or "Usuário",
                perfil=session.get("perfil"),
                motivo=request.form.get("justificativa"),
                idempotency_key=request.form.get("idempotency_key"),
                ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
                confirmacao=request.form.get("confirmacao") == "ESTORNAR_INTEGRAL",
            )
            flash(
                "OP estornada com sucesso, sem exclusão de histórico. "
                f"Caixas estornadas: {resultado['caixas_estornadas']}."
            )
        except (ValueError, PermissionError) as erro:
            status = 403 if isinstance(erro, PermissionError) else 409
            return render_template(
                "erro_operacional.html", titulo="Estorno integral não executado",
                mensagem=str(erro), retorno=url_for("embalagem_secundaria", op_id=op_id),
            ), status
        return redirect(url_for("embalagem_secundaria", op_id=op_id))


    @app.route("/embalagem-secundaria/<int:op_id>/estorno/preflight")
    @perfil_permitido("pcp", "gerencia")
    def preflight_estorno_embalagem_secundaria_op(op_id):
        try:
            return jsonify(preflight_operacao_op(op_id, "ESTORNO_INTEGRAL"))
        except ValueError as erro:
            return jsonify({"permitido": False, "erro": str(erro), "op_id": op_id}), 404


    @app.route("/embalagem-secundaria/<int:op_id>/retomar", methods=["POST"])
    @perfil_permitido("pcp", "gerencia")
    def retomar_embalagem_secundaria_op(op_id):
        try:
            if not _csrf_estorno_valido():
                raise PermissionError("Sessão de confirmação expirada. Atualize a página e tente novamente.")
            resultado = retomar_embalagem_secundaria(
                op_id, usuario=session.get("nome") or "Usuário",
                perfil=session.get("perfil"),
                idempotency_key=request.form.get("idempotency_key"),
                ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
                confirmacao=request.form.get("confirmacao") == "RETOMAR",
            )
            flash(
                "Embalagem Secundária retomada. Caixas válidas, estornos, PI e PA foram preservados; "
                "uma nova conferência será exigida antes do encerramento."
            )
            return redirect(url_for("embalagem_secundaria", op_id=op_id, retomada="1"))
        except (ValueError, PermissionError) as erro:
            status = 403 if isinstance(erro, PermissionError) else 409
            return render_template(
                "erro_operacional.html", titulo="Retomada não executada",
                mensagem=str(erro), retorno=url_for("embalagem_secundaria", op_id=op_id),
            ), status


    @app.route("/embalagem-secundaria/<int:op_id>/conferencia/confirmar", methods=["POST"])
    @perfil_permitido("pcp", "producao", "gerencia")
    def confirmar_conferencia_embalagem_secundaria(op_id):
        try:
            if not _csrf_estorno_valido():
                raise PermissionError("Sessão de confirmação expirada. Atualize a página e tente novamente.")
            if request.form.get("confirmacao") != "1":
                raise ValueError("Confirme que conferiu os lançamentos da Embalagem Secundária.")
            conferencia = confirmar_conferencia_op(
                op_id, usuario=session.get("nome") or "Usuário",
                perfil=session.get("perfil") or "", hash_informado=request.form.get("conferencia_hash"),
            )
            resultado = finalizar_embalagem_secundaria_op(
                op_id, conferencia_hash=conferencia["hash"], exigir_conferencia=True,
                usuario=session.get("nome") or "Usuário", perfil=session.get("perfil") or "",
                idempotency_key=request.form.get("idempotency_key"),
                versao_esperada=request.form.get("versao_operacional"),
                ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
                request_id=request.headers.get("X-Request-ID"),
            )
            flash(
                f"Conferência concluída e OP encerrada. PA operacional liberado: "
                f"{resultado['caixas_liberadas']} caixa(s) | "
                f"Peso líquido: {resultado['peso_liquido_total']:.3f} kg."
            )
        except (ValueError, PermissionError) as erro:
            return render_template(
                "erro_operacional.html", titulo=f"OP #{op_id} não encerrada",
                mensagem=str(erro), retorno=url_for("embalagem_secundaria", op_id=op_id),
            ), 409
        except Exception as erro:
            app.logger.exception("Falha após conferência da OP #%s", op_id)
            mensagem_publica = str(erro) if "Identificador:" in str(erro) else (
                "A conferência foi preservada, mas o encerramento falhou e "
                "a transação operacional foi revertida integralmente."
            )
            return render_template(
                "erro_operacional.html", titulo=f"OP #{op_id} não encerrada",
                mensagem=mensagem_publica,
                retorno=url_for("embalagem_secundaria", op_id=op_id),
            ), 500
        return redirect(url_for("embalagem_secundaria", op_id=op_id, conferencia="1"))


    @app.route("/embalagem-secundaria/<int:op_id>/conferencia/relatorio.pdf")
    @perfil_permitido("pcp", "producao", "gerencia")
    def pdf_conferencia_embalagem_secundaria(op_id):
        op = buscar_op_por_id(op_id)
        if not op:
            flash("OP não encontrada.")
            return redirect(url_for("embalagem_secundaria"))
        conferencia = obter_conferencia_op(op_id, {"situacao": "todas", "ordem": "asc"})
        conferencia_pdf = conferencia.get("snapshot_documental") or conferencia
        pdf = gerar_relatorio_conferencia_embalagem_pdf(
            dict(op), conferencia_pdf, session.get("nome") or "Usuário não identificado",
        )
        resposta = send_file(
            BytesIO(pdf), mimetype="application/pdf", as_attachment=False,
            download_name=f"conferencia-embalagem-secundaria-op-{op_id}.pdf",
        )
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta


    @app.route("/embalagem-secundaria/<int:op_id>/caixas/<int:caixa_id>/estornar", methods=["POST"])
    @perfil_permitido("pcp", "gerencia")
    def estornar_caixa_embalagem_secundaria_rota(op_id, caixa_id):
        try:
            if not _csrf_estorno_valido():
                raise PermissionError("Sessão de confirmação expirada. Atualize a página e tente novamente.")
            motivo = str(request.form.get("motivo") or "").strip()
            detalhes = str(request.form.get("detalhes") or "").strip()
            if not motivo:
                raise ValueError("Selecione o motivo do estorno.")
            if motivo == "Outro" and not detalhes:
                raise ValueError("Descreva o motivo quando selecionar Outro.")
            justificativa = motivo if not detalhes else f"{motivo}: {detalhes}"
            resultado = estornar_caixa_embalagem_secundaria(
                op_id, caixa_id,
                usuario=session.get("nome") or "Usuário",
                perfil=session.get("perfil"),
                justificativa=justificativa,
                idempotency_key=request.form.get("idempotency_key"),
                ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
            )
            flash(
                f"Caixa {resultado['codigo_caixa']} estornada. "
                "As demais caixas foram preservadas e as bandejas retornaram ao saldo da OP."
            )
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("embalagem_secundaria", op_id=op_id))


    @app.route("/embalagem-secundaria/<int:op_id>/caixas/estornar-lote", methods=["POST"])
    @perfil_permitido("pcp", "gerencia")
    def estornar_caixas_embalagem_secundaria_lote_rota(op_id):
        try:
            if not _csrf_estorno_valido():
                raise PermissionError("Sessão de confirmação expirada. Atualize a página e tente novamente.")
            motivo = str(request.form.get("motivo") or "").strip()
            detalhes = str(request.form.get("detalhes") or "").strip()
            if not motivo:
                raise ValueError("Selecione o motivo do estorno.")
            if motivo == "Outro" and not detalhes:
                raise ValueError("Descreva o motivo quando selecionar Outro.")
            justificativa = motivo if not detalhes else f"{motivo}: {detalhes}"
            resultado = estornar_caixas_embalagem_secundaria_em_lote(
                op_id, request.form.getlist("caixa_ids[]"),
                usuario=session.get("nome") or "Usuário", perfil=session.get("perfil"),
                justificativa=justificativa, idempotency_key=request.form.get("idempotency_key"),
                ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
            )
            impacto = resultado["impacto"]
            flash(
                f"{resultado['caixas_estornadas']} caixas estornadas com sucesso. "
                f"{impacto['bandejas']} bandejas, {impacto['peso_bruto']} kg brutos e "
                f"{impacto['peso_liquido']} kg líquidos foram revertidos."
            )
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("embalagem_secundaria", op_id=op_id, conferencia="1"))

    @app.post("/embalagem-secundaria/<int:op_id>/caixas/<int:caixa_id>/etiqueta/reimprimir")
    @perfil_permitido("pcp", "gerencia")
    def reimprimir_etiqueta_caixa(op_id, caixa_id):
        try:
            if not _csrf_estorno_valido():
                raise PermissionError("Sessão de confirmação expirada. Atualize a página e tente novamente.")
            job_uuid = solicitar_reimpressao(caixa_id, usuario=session.get("nome") or "Usuário",
                                              justificativa=request.form.get("justificativa"))
            flash(f"Reimpressão solicitada e registrada na fila ({job_uuid[:8]}).")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("embalagem_secundaria", op_id=op_id, conferencia="1"))


    @app.route("/embalagem-secundaria", methods=["GET", "POST"])

    @perfil_permitido("pcp", "producao", "gerencia")
    def embalagem_secundaria():
        if request.method == "POST":
            inclusao_erro = False
            try:
                if request.form.get("modo_lancamento") == "lote":
                    codigos = registrar_caixas_pa_lote(request.form, usuario=session.get("nome"))
                    flash(f"{len(codigos)} caixas registradas no Estoque PA com sucesso.")
                else:
                    codigo_caixa = registrar_caixa_pa_manual(request.form, usuario=session.get("nome"))
                    flash(f"Caixa {codigo_caixa} registrada no Estoque PA com sucesso.")
            except ValueError as erro:
                flash(str(erro))
                inclusao_erro = True

            return redirect(url_for(
                "embalagem_secundaria", op_id=request.form.get("op_principal") or "",
                inclusao_erro="1" if inclusao_erro else None,
            ))

        saldos_pi = buscar_ops_com_saldo_pi()
        caixas_pa = buscar_caixas_pa()
        resumo = calcular_resumo_estoques_pi_pa(saldos_pi, caixas_pa)
        op_id_selecionada = request.args.get("op_id", "")
        op_selecionada = None
        caixas_op = []
        fechamento_op = None
        conferencia_op = None
        retomada_op = None

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
                    fechamento_op = preflight_encerramento_op(op_id_int)
                except Exception as erro:
                    app.logger.exception("Falha ao validar encerramento da OP #%s", op_id_int)
                    op_base = buscar_op_por_id(op_id_int)
                    fechamento_op = ({
                        "op": op_base, "status": op_base["status"],
                        "versao_operacional": int(op_base["versao_operacional"] or 0),
                        "pronta_para_encerramento": False, "pode_encerrar": False,
                        "bloqueios": [f"Não foi possível validar o encerramento: {erro}"],
                        "pendencias": [f"Não foi possível validar o encerramento: {erro}"],
                        "pi": {"saldo": 0}, "saldo_pi": 0, "caixas": 0,
                        "aves_vivas": 0, "mortes_antes_pendura": 0,
                        "bandejas_primaria": 0, "bandejas_consumidas": 0,
                        "descartes": 0, "condenacoes": 0,
                        "peso_liquido_total": 0,
                    } if op_base else None)

                # Quando o saldo PI chega a zero, a OP deixa de aparecer em saldos_pi.
                # Ainda assim ela precisa permanecer carregada para conferência e encerramento.
                if (op_selecionada is None and fechamento_op
                        and str(fechamento_op["op"]["status"] or "").upper()
                        not in {"ESTORNADA", "ESTORNADO", "CANCELADA", "CANCELADO"}):
                    op_base = fechamento_op["op"]
                    op_selecionada = {
                        "op_id": op_id_int,
                        "data_op": op_base["data"],
                        "sku": op_base["sku"] or "Galinha Cortada",
                        "saldo_bandejas": fechamento_op["pi"]["saldo"],
                    }

                try:
                    conferencia_op = obter_conferencia_op(op_id_int, request.args)
                    caixas_op = conferencia_op["caixas_exibidas"]
                except Exception:
                    caixas_op = []

                try:
                    retomada_op = preflight_retomada_embalagem_secundaria(op_id_int)
                except ValueError as erro:
                    retomada_op = {"permitido": False, "bloqueios": [str(erro)]}

        estorno_habilitado = funcionalidade_estorno_habilitada()
        csrf_estorno = session.get("estorno_embalagem_csrf") or secrets.token_urlsafe(32)
        session["estorno_embalagem_csrf"] = csrf_estorno
        chaves_estorno = {int(caixa["id"]): str(uuid.uuid4()) for caixa in caixas_op}
        jobs_etiqueta = listar_jobs_caixas([caixa["id"] for caixa in caixas_op])

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
            caixas_fechamento=conferencia_op["caixas"] if conferencia_op else [],
            fechamento_op=fechamento_op,
            locais_segregacao=listar_locais_segregacao(),
            motivos_nc=MOTIVOS,
            estorno_habilitado=estorno_habilitado,
            pode_estornar_caixa=session.get("perfil") in {"admin", "pcp", "gerencia"},
            csrf_estorno=csrf_estorno,
            chaves_estorno=chaves_estorno,
            chave_estorno_op=str(uuid.uuid4()),
            chave_estorno_lote=str(uuid.uuid4()),
            chave_inclusao_individual=str(uuid.uuid4()),
            chave_inclusao_lote=str(uuid.uuid4()),
            chave_retomada=str(uuid.uuid4()),
            chave_encerramento=str(uuid.uuid4()),
            conferencia_op=conferencia_op,
            retomada_op=retomada_op,
            jobs_etiqueta=jobs_etiqueta,
            label_printing_enabled=bool(app.config.get("LABEL_PRINTING_ENABLED", False)),
            data_fabricacao_padrao=(op_selecionada["data_op"] if op_selecionada else datetime.now().strftime("%Y-%m-%d")),
        )

    @app.route("/expedicao")
    @perfil_permitido("pcp", "qualidade", "gerencia", "expedicao")
    def expedicao():
        hoje = datetime.now()
        primeiro_dia_mes = hoje.replace(day=1).strftime("%Y-%m-%d")
        data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
        data_fim = request.args.get("data_fim") or hoje.strftime("%Y-%m-%d")
        status = request.args.get("status") or "Todos"
        tipo_movimentacao = request.args.get("tipo") or "Todos"
        cliente_id = request.args.get("cliente_id") or None
        numero = request.args.get("numero") or ""
        produto = request.args.get("produto") or ""
        destino = request.args.get("destino") or ""
        pedido_numero = request.args.get("pedido_numero") or ""
        agrupamento_relatorio = request.args.get("agrupamento") or "ROMANEIO"

        expedicoes = buscar_expedicoes(data_inicio, data_fim, status, tipo_movimentacao,
                                       numero, cliente_id, produto, destino, pedido_numero)
        resumo = calcular_resumo_expedicao(expedicoes)
        expedicoes, paginacao = paginar_expedicoes(
            expedicoes, request.args.get("pagina"), request.args.get("por_pagina")
        )
        args_paginacao = request.args.to_dict()
        args_paginacao["por_pagina"] = paginacao["por_pagina"]
        url_anterior = url_proxima = None
        if paginacao["tem_anterior"]:
            url_anterior = url_for("expedicao", **{
                **args_paginacao, "pagina": paginacao["pagina"] - 1,
            })
        if paginacao["tem_proxima"]:
            url_proxima = url_for("expedicao", **{
                **args_paginacao, "pagina": paginacao["pagina"] + 1,
            })

        return render_template(
            "expedicao.html",
            expedicoes=expedicoes,
            resumo=resumo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            status=status,
            tipo_movimentacao=tipo_movimentacao,
            marco=obter_marco_zero(),
            tipos_romaneio=TIPOS_ROMANEIO,
            tipos_saida=TIPOS_SAIDA,
            clientes=listar_clientes(somente_ativos=True), cliente_id=cliente_id,
            numero=numero, produto=produto, destino=destino,
            pedido_numero=pedido_numero,
            agrupamento_relatorio=agrupamento_relatorio,
            paginacao=paginacao, url_anterior=url_anterior, url_proxima=url_proxima,
            status_opcoes=["Todos", "Aberto", "Concluído", "Cancelado", "Estornado"]
        )

    @app.route("/expedicao/novo", methods=["GET", "POST"])
    @perfil_permitido("pcp", "qualidade", "gerencia", "expedicao")
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
            hoje=hoje,
            tipos_romaneio=TIPOS_ROMANEIO,
            tipos_saida=TIPOS_SAIDA,
            destinos_controlados=DESTINOS_CONTROLADOS,
            clientes=listar_clientes(somente_ativos=True),
        )

    @app.route("/expedicao/<int:expedicao_id>", methods=["GET", "POST"])
    @perfil_permitido("pcp", "qualidade", "gerencia", "expedicao")
    def detalhe_romaneio_expedicao(expedicao_id):
        expedicao = buscar_expedicao_por_id(expedicao_id)

        if not expedicao:
            flash("Romaneio não encontrado.")
            return redirect(url_for("expedicao"))

        if request.method == "POST":
            try:
                acao = request.form.get("acao") or "reservar"
                if acao == "reservar":
                    if request.form.get("pa_nao_conforme_id"):
                        reservar_operacional(
                            expedicao_id, int(request.form.get("pa_nao_conforme_id")),
                            request.form.get("peso_kg"), request.form.get("quantidade_caixas"),
                            request.form.get("quantidade_bandejas"),
                        )
                    else:
                        caixa_ids = request.form.getlist("caixa_ids")
                        reservar_itens(
                            expedicao_id,
                            caixa_ids,
                            {
                                caixa_id: request.form.get(f"quantidade_pacotes_{caixa_id}")
                                for caixa_id in caixa_ids
                            },
                        )
                    flash("Itens reservados com sucesso.")
                elif acao == "remover":
                    if request.form.get("item_id"):
                        remover_reserva_operacional(expedicao_id, int(request.form.get("item_id")))
                    else:
                        remover_item_reservado(expedicao_id, int(request.form.get("caixa_id") or 0))
                    flash("Item removido e situação anterior restaurada.")
                elif acao == "concluir":
                    if request.form.get("confirmacao_conclusao") != "confirmado":
                        raise ValueError("Confirme conscientemente a conferência antes de concluir.")
                    concluir_romaneio(expedicao_id)
                    if expedicao["tipo_movimentacao"] == "HISTORICO_MARCO_ZERO":
                        flash("Romaneio histórico concluído. O estoque operacional não foi movimentado.")
                    else:
                        flash("Romaneio concluído e estoque baixado com sucesso.")
                elif acao == "cancelar":
                    if request.form.get("confirmacao_cancelamento") != "confirmado":
                        raise ValueError("Confirme o cancelamento antes de continuar.")
                    cancelar_romaneio(expedicao_id, request.form.get("justificativa"))
                    flash("Romaneio cancelado; reservas restauradas.")
                elif acao == "estornar":
                    estornar_romaneio(expedicao_id, request.form.get("justificativa"))
                    flash("Romaneio estornado; situações anteriores restauradas.")
                elif acao == "editar_cabecalho":
                    editar_romaneio_aberto(expedicao_id, request.form)
                    flash("Cabeçalho do romaneio atualizado.")
                elif acao == "salvar_historico":
                    registrar_itens_historicos(expedicao_id, [
                        {
                            "sku": "Galinha Inteira",
                            "quantidade_pacotes": request.form.get("inteira_pacotes_v1"),
                            "galinhas_por_pacote": 1,
                        },
                        {
                            "sku": "Galinha Inteira",
                            "quantidade_pacotes": request.form.get("inteira_pacotes_v2"),
                            "galinhas_por_pacote": 2,
                        },
                        {
                            "sku": "Galinha Cortada",
                            "quantidade": request.form.get("cortada_quantidade"),
                            "peso": request.form.get("cortada_peso"),
                        },
                    ])
                    flash("Totais históricos registrados.")
                else:
                    raise ValueError("Ação inválida.")
                return redirect(url_for("detalhe_romaneio_expedicao", expedicao_id=expedicao_id))
            except Exception as erro:
                flash(str(erro))

        expedicao = buscar_expedicao_por_id(expedicao_id)
        itens = buscar_itens_expedicao(expedicao_id)
        ops_selecionadas = {}
        caixas_selecionadas_ids = []
        for item in itens:
            if item["caixa_id"]:
                caixas_selecionadas_ids.append(int(item["caixa_id"]))
                if item["op_id"]:
                    chave_op = int(item["op_id"])
                    ops_selecionadas[chave_op] = ops_selecionadas.get(chave_op, 0) + 1
        resumo_itens = calcular_resumo_itens_expedicao(itens)
        resumo_mz = calcular_resumo_mz(itens)
        caixas_disponiveis = []
        if (expedicao["status"] == "Aberto"
                and expedicao["tipo_movimentacao"] in {
                    "DESCARTE", "DEVOLUCAO", "TRANSFERENCIA_AUTORIZADA"
                }):
            estoque, _ = buscar_estoque_operacional()
            caixas_disponiveis = [
                item for item in estoque
                if item["condicao"] == "NAO_CONFORME" and item["disponibilidade"] == "BLOQUEADO"
            ]

        return render_template(
            "romaneio_detalhe.html",
            expedicao=expedicao,
            itens=itens,
            resumo_itens=resumo_itens,
            resumo_mz=resumo_mz,
            caixas_disponiveis=caixas_disponiveis,
            ops_selecionadas=ops_selecionadas,
            caixas_selecionadas_ids=caixas_selecionadas_ids,
            plano_pedido=plano_romaneio(expedicao_id),
            saldos_legados=saldos_legados_operacionais() if expedicao["tipo_movimentacao"] in {"TRANSFERENCIA", "VENDA_DIRETA"} else [],
            tipo_descricao=TIPOS_SAIDA.get(expedicao["tipo_saida"], TIPOS_ROMANEIO.get(
                expedicao["tipo_movimentacao"], expedicao["tipo_movimentacao"])),
            skus=["Galinha Cortada", "Galinha Inteira"]
        )

    @app.get("/expedicao/<int:expedicao_id>/selecao-ops/<int:op_id>")
    @perfil_permitido("pcp", "qualidade", "gerencia", "expedicao")
    def carregar_op_romaneio(expedicao_id, op_id):
        try:
            op = buscar_op_para_romaneio(expedicao_id, op_id)
            caixas = buscar_caixas_elegiveis_op(
                expedicao_id, op_id, op_validada=op
            )
            return jsonify({"ok": True, "op": op, "caixas": caixas})
        except ValueError as erro:
            return jsonify({"ok": False, "mensagem": str(erro)}), 400

    @app.get("/expedicao/<int:expedicao_id>/selecao-ops/<int:op_id>/caixas")
    @perfil_permitido("pcp", "qualidade", "gerencia", "expedicao")
    def pesquisar_caixas_op_romaneio(expedicao_id, op_id):
        try:
            caixas = buscar_caixas_por_op_e_peso(expedicao_id, op_id, request.args.get("peso"))
            peso_informado = bool(str(request.args.get("peso") or "").strip())
            mensagem = (
                "Nenhuma caixa desta OP corresponde ao peso informado."
                if peso_informado and not caixas else None
            )
            return jsonify({"ok": True, "caixas": caixas, "mensagem": mensagem})
        except ValueError as erro:
            return jsonify({"ok": False, "mensagem": str(erro)}), 400

    @app.post("/expedicao/<int:expedicao_id>/selecao-ops/<int:op_id>/reservar")
    @perfil_permitido("pcp", "qualidade", "gerencia", "expedicao")
    def reservar_caixas_op_romaneio(expedicao_id, op_id):
        dados = request.get_json(silent=True) or {}
        caixa_ids = dados.get("caixa_ids") or []
        try:
            reservar_itens(expedicao_id, caixa_ids, op_id_esperada=op_id)
            return jsonify({
                "ok": True,
                "mensagem": "Caixas selecionadas e acumuladas no romaneio.",
                "op": buscar_op_para_romaneio(expedicao_id, op_id),
            })
        except (TypeError, ValueError) as erro:
            return jsonify({"ok": False, "mensagem": str(erro)}), 400

    @app.delete("/expedicao/<int:expedicao_id>/selecao-ops/<int:op_id>")
    @perfil_permitido("pcp", "qualidade", "gerencia", "expedicao")
    def remover_op_romaneio(expedicao_id, op_id):
        try:
            op = buscar_op_para_romaneio(expedicao_id, op_id)
            dados = request.get_json(silent=True) or {}
            if op["selecionadas"] and dados.get("confirmar_remocao_caixas") is not True:
                raise ValueError("Confirme a remoção das caixas selecionadas desta OP.")
            removidas = remover_itens_reservados_op(expedicao_id, op_id)
            return jsonify({
                "ok": True,
                "caixas_removidas": len(removidas),
                "caixa_ids": removidas,
            })
        except ValueError as erro:
            return jsonify({"ok": False, "mensagem": str(erro)}), 400

    @app.route("/expedicao/estoque")
    @perfil_permitido("pcp", "qualidade")
    def estoque_camara_expedicao():
        itens, resumo = buscar_estoque_operacional()
        saldos_legados = saldos_legados_operacionais()
        inventario_fisico = inventario_legado_fisico()
        consolidado = consolidar_estoque_camara(incluir_nao_conforme=True)
        resumo = alinhar_resumo_ao_consolidado(resumo, consolidado, saldos_legados)
        return render_template(
            "expedicao_estoque.html",
            itens=itens,
            resumo=resumo,
            consolidado=consolidado,
            saldos_legados=saldos_legados,
            inventario_fisico=inventario_fisico,
            marco=obter_marco_zero(),
        )

    @app.route("/expedicao/estoque/relatorio-consolidado.pdf")
    @perfil_permitido("pcp", "qualidade")
    def imprimir_consolidado_estoque_expedicao():
        incluir_parametro = request.args.get("incluir_nao_conforme", "0")
        if incluir_parametro not in {"0", "1"}:
            flash("A opção de estoque não conforme é inválida.")
            return redirect(url_for("estoque_camara_expedicao"))
        consolidado = consolidar_estoque_camara(
            incluir_nao_conforme=incluir_parametro == "1")
        pdf = gerar_relatorio_estoque_pdf(
            consolidado,
            usuario=session.get("nome") or "Usuário não identificado",
        )
        resposta = send_file(
            BytesIO(pdf), mimetype="application/pdf", as_attachment=False,
            download_name="posicao-consolidada-estoque-camara.pdf",
        )
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta

    @app.route("/expedicao/nao-conformes")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def nao_conformes_expedicao():
        filtros = {nome: request.args.get(nome, "") for nome in (
            "produto", "apresentacao", "caracteristica", "situacao", "busca",
        )}
        saldos, opcoes, filtros = listar_saldos_nc(filtros)
        itens, _ = buscar_estoque_operacional()
        return render_template(
            "expedicao_nao_conformes.html",
            saldos=saldos, opcoes=opcoes, filtros=filtros,
            rotulos_situacoes=ROTULOS_SITUACOES,
            relatorios=listar_relatorios_nc(),
            itens=[item for item in itens if item["condicao"] == "NAO_CONFORME"],
        )

    @app.post("/expedicao/nao-conformes/relatorio/previa")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def previa_verificacao_nc_expedicao():
        try:
            previa = consolidar_selecao(request.form.getlist("saldo_id"))
            return jsonify({
                "token": previa["token"],
                "quantidade_registros": previa["quantidade_registros"],
                "secoes": [{
                    "produto": secao["produto"], "apresentacao": secao["apresentacao"],
                    "unidades": secao["unidades"],
                    "totais": {k: str(v) for k, v in secao["totais"].items()},
                } for secao in previa["secoes"]],
            })
        except ValueError as erro:
            return jsonify({"erro": str(erro)}), 409

    @app.post("/expedicao/nao-conformes/relatorio/gerar")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def gerar_verificacao_nc_expedicao():
        filtros = {nome: request.form.get(nome, "") for nome in (
            "produto", "apresentacao", "caracteristica", "situacao", "busca",
        )}
        try:
            relatorio = emitir_relatorio_nc(
                request.form.getlist("saldo_id"), request.form.get("snapshot_token"), filtros,
                usuario=session.get("nome") or "Usuário não identificado",
                perfil=session.get("perfil") or "não identificado",
            )
        except ValueError as erro:
            flash(str(erro))
            return redirect(url_for("nao_conformes_expedicao", **filtros))
        resposta = send_file(
            BytesIO(gerar_relatorio_nc_pdf(relatorio)), mimetype="application/pdf",
            as_attachment=False, download_name=f"{relatorio['numero']}.pdf",
        )
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta

    @app.get("/expedicao/nao-conformes/relatorio/<int:relatorio_id>.pdf")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def reimprimir_verificacao_nc_expedicao(relatorio_id):
        try:
            relatorio = obter_relatorio_nc(relatorio_id)
        except ValueError as erro:
            flash(str(erro))
            return redirect(url_for("nao_conformes_expedicao"))
        if not relatorio:
            flash("Relatório de verificação não encontrado.")
            return redirect(url_for("nao_conformes_expedicao"))
        resposta = send_file(
            BytesIO(gerar_relatorio_nc_pdf(relatorio)), mimetype="application/pdf",
            as_attachment=False, download_name=f"{relatorio['numero']}.pdf",
        )
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta

    @app.route("/expedicao/estoque/<int:caixa_id>/bloquear", methods=["POST"])
    @perfil_permitido("pcp", "qualidade")
    def bloquear_estoque_expedicao(caixa_id):
        try:
            bloquear_produto(
                caixa_id,
                request.form.get("motivo"),
                request.form.get("observacao"),
            )
            flash("Produto bloqueado e segregado como não conforme.")
        except ValueError as erro:
            flash(str(erro))
        return redirect(request.referrer or url_for("estoque_camara_expedicao"))

    @app.route("/expedicao/estoque/<int:caixa_id>/destinar", methods=["POST"])
    @perfil_permitido("pcp", "qualidade")
    def destinar_estoque_expedicao(caixa_id):
        try:
            destinar_produto(
                caixa_id,
                request.form.get("destino"),
                request.form.get("justificativa"),
            )
            flash("Destinação registrada com histórico preservado.")
        except ValueError as erro:
            flash(str(erro))
        return redirect(url_for("nao_conformes_expedicao"))

    @app.route("/expedicao/historico")
    @perfil_permitido("pcp", "qualidade")
    def historico_estoque_expedicao():
        return render_template(
            "expedicao_historico.html",
            eventos=buscar_historico_estoque(),
        )

    @app.route("/expedicao/<int:expedicao_id>/imprimir")
    @perfil_permitido("pcp", "qualidade", "gerencia", "expedicao")
    def imprimir_romaneio_expedicao(expedicao_id):
        expedicao = buscar_expedicao_por_id(expedicao_id)
        if not expedicao:
            flash("Romaneio não encontrado.")
            return redirect(url_for("expedicao"))
        registrar_emissao_romaneio(expedicao_id)
        expedicao = buscar_expedicao_por_id(expedicao_id)
        itens = buscar_itens_expedicao(expedicao_id)
        return render_template(
            "romaneio_impressao.html",
            expedicao=expedicao,
            itens=itens,
            empresa_emitente=EMPRESA_EMITENTE,
            estabelecimento_documento=ESTABELECIMENTO_DOCUMENTO,
            identificacao_tecnologia=IDENTIFICACAO_TECNOLOGIA,
            resumo=calcular_resumo_itens_expedicao(itens),
            tipo_descricao=TIPOS_SAIDA.get(expedicao["tipo_saida"], TIPOS_ROMANEIO.get(
                expedicao["tipo_movimentacao"], expedicao["tipo_movimentacao"])),
            emissao_formatada=formatar_data_hora_emissao_manaus(
                expedicao["emitido_em"]
            ),
            conclusao_formatada=formatar_data_hora_emissao_manaus(
                expedicao["concluido_em"]
            ),
            data_romaneio_formatada=formatar_data_brasileira(expedicao["data"]),
            documento_cliente_formatado=formatar_documento_brasileiro(
                expedicao["cliente_documento"]
            ),
        )

    @app.route("/expedicao/relatorio-entregas.pdf")
    @perfil_permitido("pcp", "qualidade", "gerencia")
    def relatorio_entregas_expedicao():
        filtros = {
            "numero": request.args.get("numero") or "",
            "data_inicio": request.args.get("data_inicio") or "",
            "data_fim": request.args.get("data_fim") or "",
            "status": request.args.get("status") or "Todos",
            "tipo": request.args.get("tipo") or "Todos",
            "cliente_id": request.args.get("cliente_id") or None,
            "produto": request.args.get("produto") or "",
            "destino": request.args.get("destino") or "",
            "agrupamento": request.args.get("agrupamento") or "ROMANEIO",
            "pedido_numero": request.args.get("pedido_numero") or "",
        }
        argumentos = [
            filtros["data_inicio"], filtros["data_fim"], filtros["status"], filtros["tipo"],
            filtros["numero"], filtros["cliente_id"], filtros["produto"], filtros["destino"],
        ]
        if filtros["pedido_numero"]:
            argumentos.append(filtros["pedido_numero"])
        expedicoes = buscar_expedicoes(*argumentos)
        cliente_selecionado = None
        if filtros["cliente_id"]:
            cliente_selecionado = next(
                (item["razao_social"] for item in listar_clientes(somente_ativos=False)
                 if str(item["id"]) == str(filtros["cliente_id"])),
                None,
            )
        pdf = gerar_relatorio_entregas_pdf(
            expedicoes, filtros, cliente_selecionado=cliente_selecionado,
            usuario=session.get("nome") or "Usuário não identificado",
            agrupamento=filtros["agrupamento"],
        )
        nome_arquivo = "relatorio-entregas-por-op.pdf" if filtros["agrupamento"].upper() == "OP" else "relatorio-entregas-por-romaneio.pdf"
        return send_file(
            BytesIO(pdf), mimetype="application/pdf", as_attachment=False,
            download_name=nome_arquivo,
        )
