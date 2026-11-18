"""Interface da BOM no módulo Engenharia de Produtos."""

from flask import abort, flash, redirect, render_template, request, session, url_for

from modules.auth.decorators import perfil_permitido
from . import bom


def registrar_bom(app, leitura, escrita, pode_editar):
    base = "/engenharia-produtos/boms"

    def consultar(bom_id):
        try:
            return bom.detalhar(bom_id)
        except LookupError:
            abort(404)

    def tela(modo, **dados):
        return render_template(
            "engenharia_produtos/bom.html", modo=modo, pode_editar=pode_editar(), **dados
        )

    @app.get(base)
    @perfil_permitido(*leitura)
    def bom_lista():
        return tela("lista", versoes=bom.listar())

    @app.post(base + "/aquisicao")
    @perfil_permitido(*escrita)
    def bom_aquisicao():
        try:
            bom.definir_aquisicao(
                request.form.get("produto_id", type=int),
                "fabricavel" in request.form, "compravel" in request.form,
            )
            flash("Forma de aquisição atualizada.")
        except ValueError as erro:
            flash(str(erro))
        return redirect(url_for("bom_nova"))

    @app.route(base + "/nova", methods=["GET", "POST"])
    @app.route(base + "/<int:origem_id>/nova-versao", methods=["GET", "POST"])
    @perfil_permitido(*escrita)
    def bom_nova(origem_id=None):
        origem = consultar(origem_id) if origem_id else None
        dados = dict(origem or {})
        if origem:
            dados["data_inicio_vigencia"] = ""
            dados["data_fim_vigencia"] = ""
        if request.method == "POST":
            dados = request.form
            produto_id = origem["produto_id"] if origem else dados.get("produto_id", type=int)
            try:
                bom_id = bom.criar_versao(
                    produto_id, dados, session.get("usuario_id"), origem_id,
                    clonar=dados.get("modelo") == "clonar",
                )
                return redirect(url_for("bom_editor", bom_id=bom_id))
            except ValueError as erro:
                flash(str(erro))
        return tela("nova", origem=origem, dados=dados, opcoes=bom.opcoes())

    @app.route(base + "/<int:bom_id>", methods=["GET", "POST"])
    @perfil_permitido(*leitura)
    def bom_detalhe(bom_id):
        versao = consultar(bom_id)
        calculo = None
        if request.method == "POST":
            try:
                calculo = bom.calcular_necessidades(
                    versao["produto_id"], versao, request.form.get("quantidade_planejada")
                )
            except ValueError as erro:
                flash(str(erro))
        return tela("detalhe", versao=versao, calculo=calculo)

    @app.route(base + "/<int:bom_id>/editar", methods=["GET", "POST"])
    @perfil_permitido(*escrita)
    def bom_editor(bom_id):
        versao = consultar(bom_id)
        if versao["status"] != "RASCUNHO":
            abort(409)
        item_id = request.args.get("item", type=int)
        item = next((linha for linha in versao["itens"] if linha["id"] == item_id), None)
        if item_id and item is None:
            abort(404)
        cabecalho = versao
        item_form = dict(item or {})
        if item:
            if item["componente_produto_id"]:
                item_form["componente"] = f"produto:{item['componente_produto_id']}"
            else:
                item_form["componente"] = f"insumo:{item['componente_insumo_id']}"
        if request.method == "POST":
            dados = request.form
            acao = dados.get("acao")
            usuario = session.get("usuario_id")
            try:
                if acao == "cabecalho":
                    cabecalho = dados
                    bom.atualizar_cabecalho(bom_id, dados, usuario)
                elif acao == "item":
                    item_form = dados
                    bom.salvar_item(bom_id, dados, usuario, item_id)
                elif acao == "remover":
                    bom.remover_item(bom_id, dados.get("item_id", type=int), usuario)
                else:
                    abort(400)
                return redirect(url_for("bom_editor", bom_id=bom_id))
            except ValueError as erro:
                flash(str(erro))
            except LookupError:
                abort(404)
        return tela("editor", versao=versao, dados=cabecalho, item=item_form,
                    item_id=item_id, opcoes=bom.opcoes())

    @app.post(base + "/<int:bom_id>/status")
    @perfil_permitido(*escrita)
    def bom_status(bom_id):
        try:
            if request.form.get("acao") == "publicar":
                bom.publicar(bom_id, session.get("usuario_id"))
            elif request.form.get("acao") == "inativar":
                bom.inativar(bom_id, request.form.get("ultimo_dia"), session.get("usuario_id"))
            else:
                abort(400)
        except ValueError as erro:
            flash(str(erro))
        except LookupError:
            abort(404)
        return redirect(url_for("bom_detalhe", bom_id=bom_id))
