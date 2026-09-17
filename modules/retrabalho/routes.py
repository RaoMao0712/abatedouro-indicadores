"""Rotas do módulo de Ordem de Retrabalho."""

from flask import flash, redirect, render_template, request, session, url_for

from modules.auth.decorators import perfil_permitido
from modules.engenharia_produtos.services import listar_catalogo
from modules.qualidade.produtos_nao_conformes import listar_locais_segregacao

from . import services as rt_service


def _usuario():
    return session.get("nome") or "Usuário não identificado"


def _perfil():
    return (session.get("perfil") or "").lower()


def _catalogo_pa():
    produtos, _resumo = listar_catalogo({"status": "Sim", "tipo": "PRODUTO_ACABADO"})
    return produtos


def register_retrabalho_routes(app):

    @app.get("/retrabalho")
    @perfil_permitido("admin", "pcp", "producao", "qualidade", "gerencia")
    def retrabalho_lista():
        filtros = {
            "numero": request.args.get("numero"),
            "status": request.args.get("status"),
            "sku_origem": request.args.get("sku_origem"),
            "sku_destino": request.args.get("sku_destino"),
            "inicio": request.args.get("inicio"),
            "fim": request.args.get("fim"),
        }
        registros = rt_service.listar_retrabalhos(filtros)
        return render_template(
            "retrabalho_lista.html", registros=registros, filtros=filtros,
            status_labels=rt_service.STATUS_LABELS, status_opcoes=rt_service.STATUS_LABELS,
        )

    @app.get("/retrabalho/novo")
    @perfil_permitido("admin", "pcp", "producao", "gerencia")
    def retrabalho_novo():
        return render_template(
            "retrabalho_novo.html", produtos=_catalogo_pa(), locais=listar_locais_segregacao(),
            familias=rt_service.FAMILIAS,
        )

    @app.get("/retrabalho/origens-elegiveis")
    @perfil_permitido("admin", "pcp", "producao", "gerencia")
    def retrabalho_origens_elegiveis():
        sku = request.args.get("sku", "")
        unidade_estoque = request.args.get("unidade_estoque", "")
        origens = rt_service.buscar_origens_elegiveis(sku, unidade_estoque)
        return {
            "origens": [
                {
                    "caixa_id": item["id"],
                    "codigo_caixa": item["codigo_caixa"],
                    "op_id": item["op_id"],
                    "galinhas_por_pacote": item["galinhas_por_pacote"],
                    "quantidade_pacotes": item["quantidade_pacotes"],
                    "quantidade_galinhas": item["quantidade_galinhas"],
                    "quantidade_pacotes_reservados": item["quantidade_pacotes_reservados"],
                    "peso_liquido": item["peso_liquido"],
                    "data_fabricacao": item["data_fabricacao"],
                    "data_validade": item["data_validade"],
                }
                for item in origens
            ]
        }

    @app.post("/retrabalho/novo")
    @perfil_permitido("admin", "pcp", "producao", "gerencia")
    def criar_retrabalho():
        form = request.form
        origens = []
        for caixa_id in form.getlist("origem_caixa_id"):
            quantidade = form.get(f"origem_quantidade_{caixa_id}")
            if quantidade:
                origens.append({"caixa_id": caixa_id, "quantidade": quantidade})
        try:
            rt = rt_service.abrir_retrabalho(
                form.to_dict(), origens, usuario=_usuario(), perfil=_perfil(),
                idempotency_key=form.get("idempotency_key"),
            )
            flash(f"Ordem de Retrabalho {rt['numero']} aberta; saldo de origem reservado.")
            return redirect(url_for("retrabalho_detalhe", rt_id=rt["id"]))
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
            return redirect(url_for("retrabalho_novo"))

    @app.get("/retrabalho/<int:rt_id>")
    @perfil_permitido("admin", "pcp", "producao", "qualidade", "gerencia")
    def retrabalho_detalhe(rt_id):
        rt = rt_service.obter_detalhe_retrabalho(rt_id)
        if not rt:
            flash("Ordem de Retrabalho não encontrada.")
            return redirect(url_for("retrabalho_lista"))
        return render_template(
            "retrabalho_detalhe.html", rt=rt, status_labels=rt_service.STATUS_LABELS,
            locais=listar_locais_segregacao(),
        )

    @app.post("/retrabalho/<int:rt_id>/encerrar")
    @perfil_permitido("admin", "pcp", "producao", "gerencia")
    def encerrar_retrabalho_view(rt_id):
        try:
            rt_service.encerrar_retrabalho(
                rt_id, request.form.to_dict(), usuario=_usuario(), perfil=_perfil(),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Ordem de Retrabalho encerrada; produto formado aguardando liberação da Qualidade.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("retrabalho_detalhe", rt_id=rt_id))

    @app.post("/retrabalho/<int:rt_id>/liberar")
    @perfil_permitido("admin", "qualidade", "gerencia")
    def liberar_retrabalho_view(rt_id):
        try:
            rt_service.liberar_retrabalho(
                rt_id, usuario=_usuario(), perfil=_perfil(),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Produto do retrabalho liberado para expedição.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("retrabalho_detalhe", rt_id=rt_id))

    @app.post("/retrabalho/<int:rt_id>/cancelar")
    @perfil_permitido("admin", "pcp", "producao", "gerencia")
    def cancelar_retrabalho_view(rt_id):
        try:
            rt_service.cancelar_retrabalho(
                rt_id, request.form.get("justificativa"), usuario=_usuario(), perfil=_perfil(),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Ordem de Retrabalho cancelada; reservas liberadas.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("retrabalho_detalhe", rt_id=rt_id))

    @app.post("/retrabalho/<int:rt_id>/estornar")
    @perfil_permitido("admin", "gerencia")
    def estornar_retrabalho_view(rt_id):
        try:
            rt_service.estornar_retrabalho(
                rt_id, request.form.get("justificativa"), usuario=_usuario(), perfil=_perfil(),
                idempotency_key=request.form.get("idempotency_key"),
            )
            flash("Ordem de Retrabalho estornada; origens restauradas.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("retrabalho_detalhe", rt_id=rt_id))
