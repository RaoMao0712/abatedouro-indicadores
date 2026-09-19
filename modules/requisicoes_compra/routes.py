from io import BytesIO
from uuid import uuid4
from flask import abort, flash, redirect, render_template, request, send_file, session, url_for
from modules.auth.decorators import perfil_permitido
from modules.almoxarifado.services import buscar_insumos_almoxarifado
from .origens import TIPOS
from .services import PRIORIDADES, STATUS, UNIDADES, ConflitoRC, alertas_duplicidade, aprovar, buscar_rc, cancelar, criar_rascunho, editar_rascunho, enviar, listar, normalizar_itens, rejeitar, vincular_material

ACESSO=("pcp","producao","qualidade","manutencao","gerencia")
def _u(): return {"id":session.get("usuario_id"),"nome":session.get("nome","Sistema"),"perfil":session.get("perfil","")}

def register_requisicoes_compra_routes(app):
    @app.route("/compras/requisicoes")
    @perfil_permitido(*ACESSO)
    def requisicoes_compra():
        filtros={k:request.args.get(k,"") for k in ("status","tipo_origem","setor","prioridade","data_inicio","data_fim","termo")}
        return render_template("requisicoes_compra.html",requisicoes=listar(filtros),filtros=filtros,status_opcoes=STATUS,tipos_origem=TIPOS,prioridades=PRIORIDADES)

    @app.route("/compras/requisicoes/nova",methods=["GET","POST"])
    @perfil_permitido(*ACESSO)
    def nova_requisicao_compra():
        if request.method=="POST":
            try:
                materiais=[int(x) for x in request.form.getlist("material_id") if str(x).strip()]
                for aviso in alertas_duplicidade(request.form.get("tipo_origem"),request.form.get("origem_id"),materiais): flash(aviso)
                rc=criar_rascunho(request.form,normalizar_itens(request.form),ator=_u(),idempotency_key=request.form.get("idempotency_key")); flash("Rascunho da RC criado sem movimentar estoque ou Financeiro."); return redirect(url_for("detalhe_requisicao_compra",rc_id=rc["id"]))
            except Exception as e: flash(str(e))
        return render_template("requisicao_compra_nova.html",tipos_origem=TIPOS,prioridades=PRIORIDADES,unidades=UNIDADES,insumos=buscar_insumos_almoxarifado("Todas","Sim",""),idempotency_key=str(uuid4()),pre_tipo=request.values.get("tipo_origem",""),pre_id=request.values.get("origem_id",""),pre_setor=request.values.get("setor",""),pre_descricao=request.values.get("origem_descricao",""),pre_numero=request.values.get("origem_numero",""))

    @app.route("/compras/requisicoes/<int:rc_id>/editar",methods=["GET","POST"])
    @perfil_permitido(*ACESSO)
    def editar_requisicao_compra(rc_id):
        rc=buscar_rc(rc_id)
        if not rc: abort(404)
        if request.method=="POST":
            try: editar_rascunho(rc_id,request.form,normalizar_itens(request.form),ator=_u(),versao=request.form.get("versao"),idempotency_key=request.form.get("idempotency_key")); flash("Rascunho atualizado."); return redirect(url_for("detalhe_requisicao_compra",rc_id=rc_id))
            except Exception as e: flash(str(e))
        return render_template("requisicao_compra_editar.html",rc=rc,prioridades=PRIORIDADES,unidades=UNIDADES,insumos=buscar_insumos_almoxarifado("Todas","Sim",""),idempotency_key=str(uuid4()))

    @app.route("/compras/requisicoes/<int:rc_id>")
    @perfil_permitido(*ACESSO)
    def detalhe_requisicao_compra(rc_id):
        rc=buscar_rc(rc_id)
        if not rc: abort(404)
        return render_template("requisicao_compra_detalhe.html",rc=rc,insumos=buscar_insumos_almoxarifado("Todas","Sim",""),chave=str(uuid4()))

    @app.route("/compras/requisicoes/<int:rc_id>/<acao>",methods=["POST"])
    @perfil_permitido(*ACESSO)
    def acao_requisicao_compra(rc_id,acao):
        try:
            kw={"ator":_u(),"versao":request.form.get("versao"),"idempotency_key":request.form.get("idempotency_key"),"motivo":request.form.get("motivo")}
            if acao=="enviar": kw.pop("motivo"); enviar(rc_id,**kw)
            elif acao=="aprovar": kw.pop("motivo"); aprovar(rc_id,**kw)
            elif acao=="rejeitar": rejeitar(rc_id,**kw)
            elif acao=="cancelar": cancelar(rc_id,**kw)
            else: abort(404)
            flash("Ação registrada com sucesso.")
        except (ValueError,PermissionError,ConflitoRC) as e: flash(str(e))
        return redirect(url_for("detalhe_requisicao_compra",rc_id=rc_id))

    @app.route("/compras/requisicoes/<int:rc_id>/itens/<int:item_id>/vincular",methods=["POST"])
    @perfil_permitido("pcp")
    def vincular_material_requisicao_compra(rc_id,item_id):
        try: vincular_material(rc_id,item_id,int(request.form.get("material_id") or 0),ator=_u(),idempotency_key=request.form.get("idempotency_key")); flash("Material vinculado; snapshot original preservado.")
        except Exception as e: flash(str(e))
        return redirect(url_for("detalhe_requisicao_compra",rc_id=rc_id))

    @app.route("/compras/requisicoes/<int:rc_id>/pdf")
    @perfil_permitido(*ACESSO)
    def imprimir_requisicao_compra(rc_id):
        from .pdf import gerar_pdf
        rc=buscar_rc(rc_id)
        if not rc: abort(404)
        return send_file(BytesIO(gerar_pdf(rc)),mimetype="application/pdf",download_name=f"{rc['numero']}.pdf",as_attachment=False)
