"""Rotas operacionais do m?dulo de Produ??o."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from database import conectar, q
from modules.auth.decorators import perfil_permitido
from modules.auth.services import usuario_eh_admin
from modules.qualidade import services as qualidade_service
from utils import normalizar_chave_setor, setores_padrao

from .services import (
    buscar_fornecedores,
    buscar_op_por_id,
    buscar_ordens,
    buscar_ordens_abertas,
    buscar_tempos_setor_por_op,
    buscar_contexto_pesagem_op,
    calcular_resumo_op,
    cancelar_ultima_caixa_pesagem_op,
    contexto_apontamento,
    copiar_mao_obra_de_op,
    gerar_producao_automatica_setores,
    registrar_peso_caixa_op,
    salvar_apontamento_mao_obra,
    salvar_apontamento_parada,
    salvar_tempos_setor,
    setores_por_sku,
)

_INTEGRACOES = {}


def _integracao(nome):
    try:
        return _INTEGRACOES[nome]
    except KeyError as exc:
        raise RuntimeError(f"Integra??o de produ??o n?o configurada: {nome}") from exc


def register_producao_routes(app, integracoes=None):
    global _INTEGRACOES
    _INTEGRACOES = integracoes or {}

    @app.route("/ordem-producao", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def ordem_producao():
        if request.method == "POST":
            data = request.form["data"]
            sku = request.form.get("sku", "Galinha Cortada")
            fornecedor = request.form["fornecedor"]
            gta = request.form["gta"]
            nota_fiscal = request.form["nota_fiscal"]
            quantidade_aves = int(request.form["quantidade_aves"])
            mortes_antes_pendura = 0
            peso_vivo = float(request.form["peso_vivo"])
            observacoes = request.form["observacoes"]

            peso_medio = peso_vivo / quantidade_aves if quantidade_aves else 0

            conn = conectar()
            cursor = conn.cursor()

            cursor.execute(q("""
            INSERT INTO ordens_producao (
                data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
                mortes_antes_pendura, peso_vivo, peso_medio, observacoes, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """), (
                data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
                mortes_antes_pendura, peso_vivo, peso_medio, observacoes, "Aberta"
            ))

            conn.commit()
            conn.close()

            flash("OP cadastrada com sucesso")
            return redirect(url_for("ordem_producao"))

        hoje = datetime.now().strftime("%Y-%m-%d")
        ordens = buscar_ordens()[:10]
        fornecedores = buscar_fornecedores()

        return render_template(
            "ordem_producao.html",
            hoje=hoje,
            ordens=ordens,
            fornecedores=fornecedores
        )


    @app.route("/apontamento-setor", methods=["GET", "POST"])
    @perfil_permitido("admin")
    def apontamento_setor():
        if request.method == "POST":
            tipo = request.form.get("tipo_apontamento")

            if tipo == "mao_obra":
                salvar_apontamento_mao_obra(request.form)
                flash("Apontamento de mão de obra salvo.")

            elif tipo == "parada":
                salvar_apontamento_parada(request.form)
                flash("Apontamento de parada salvo.")

            elif tipo == "descarte":
                if request.form.get("tipo_apontamento") == "descarte_lote":
                    qualidade_service.salvar_apontamentos_descartes_lote(request.form)
                else:
                    qualidade_service.salvar_apontamento_descarte(request.form)
                flash("Apontamento de descarte/condenação salvo.")

            return redirect(url_for("apontamento_setor"))

        return render_template("apontamento_setor.html", **contexto_apontamento())



    @app.route("/apontamento-mao-obra", methods=["GET", "POST"])
    @perfil_permitido("producao")
    def apontamento_mao_obra():
        if request.method == "POST":
            tipo = request.form.get("tipo_apontamento")

            try:
                if tipo == "copiar_mao_obra":
                    origem_op_id = request.form["origem_op_id"]
                    destino_op_id = request.form["destino_op_id"]
                    data_destino = request.form["data_destino"]

                    total = copiar_mao_obra_de_op(
                        origem_op_id,
                        destino_op_id,
                        data_destino
                    )

                    flash(f"Equipe copiada com sucesso. {total} colaboradores foram lançados na OP destino.")

                else:
                    salvar_apontamento_mao_obra(request.form)
                    flash("Apontamento de mão de obra salvo.")

            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("apontamento_mao_obra"))

        contexto = contexto_apontamento()
        contexto["ordens_origem"] = buscar_ordens()

        return render_template(
            "apontamento_mao_obra.html",
            **contexto
        )


    @app.route("/apontamento-paradas", methods=["GET", "POST"])
    @perfil_permitido("producao")
    def apontamento_paradas():
        if request.method == "POST":
            try:
                salvar_apontamento_parada(request.form)
                flash("Apontamento de horas paradas salvo.")
            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("apontamento_paradas"))

        return render_template("apontamento_paradas.html", **contexto_apontamento())




    @app.route("/tempos-setor", methods=["GET", "POST"])
    @perfil_permitido("producao")
    def tempos_setor():
        if request.method == "POST":
            try:
                salvar_tempos_setor(request.form)
                flash("Tempos dos setores salvos com sucesso.")
            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("tempos_setor", op_id=request.form.get("op_id")))

        op_id = request.args.get("op_id")
        op = None
        tempos_salvos = []
        setores_op = []

        if op_id:
            op = buscar_op_por_id(op_id)

            if op:
                setores_op = setores_por_sku(op["sku"] or "Galinha Cortada")
                tempos_salvos = buscar_tempos_setor_por_op(op_id)

        tempos_por_setor = {
            item["setor"]: item
            for item in tempos_salvos
        }

        return render_template(
            "tempos_setor.html",
            hoje=datetime.now().strftime("%Y-%m-%d"),
            ordens=buscar_ordens_abertas(),
            op=op,
            setores_op=setores_op,
            tempos_por_setor=tempos_por_setor,
            normalizar_chave_setor=normalizar_chave_setor
        )


    @app.route("/ordem-producao/<int:op_id>/pesagem", methods=["GET", "POST"])
    @perfil_permitido("pcp", "producao")
    def pesagem_op(op_id):
        if request.method == "POST":
            try:
                contexto = registrar_peso_caixa_op(op_id, request.form.get("peso_caixa"))
                caixa = contexto["ultima_caixa"]
                flash(f"Caixa {caixa['op_numero_caixa']} registrada com {caixa['peso_liquido']:.3f} kg.")
            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("pesagem_op", op_id=op_id))

        try:
            contexto = buscar_contexto_pesagem_op(op_id)
        except ValueError as erro:
            flash(str(erro))
            return redirect(url_for("consultar_op"))

        return render_template("pesagem_op.html", **contexto)


    @app.route("/ordem-producao/<int:op_id>/pesagem/etiqueta/<int:caixa_id>")
    @perfil_permitido("pcp", "producao")
    def etiqueta_pesagem_op(op_id, caixa_id):
        try:
            contexto = buscar_contexto_pesagem_op(op_id, caixa_id)
        except ValueError as erro:
            flash(str(erro))
            return redirect(url_for("consultar_op"))

        if not contexto.get("caixa_etiqueta"):
            flash("Caixa nao encontrada para esta OP.")
            return redirect(url_for("pesagem_op", op_id=op_id))

        return render_template("pesagem_op.html", **contexto)


    @app.route("/ordem-producao/<int:op_id>/pesagem/cancelar-ultima", methods=["POST"])
    @perfil_permitido("pcp", "producao")
    def cancelar_ultima_pesagem_op(op_id):
        try:
            contexto = cancelar_ultima_caixa_pesagem_op(op_id)
            flash("Ultima caixa cancelada com seguranca.")
            caixa = contexto.get("caixa_etiqueta")
            if caixa:
                return redirect(url_for("etiqueta_pesagem_op", op_id=op_id, caixa_id=caixa["id"]))
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("pesagem_op", op_id=op_id))


    @app.route("/op/<int:op_id>/editar", methods=["GET", "POST"])
    @perfil_permitido("pcp")
    def editar_op(op_id):
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
        op = cursor.fetchone()

        if not op:
            conn.close()
            flash("OP não encontrada.")
            return redirect(url_for("consultar_op"))

        if op["status"] == "Encerrada" and not usuario_eh_admin():
            conn.close()
            flash("Esta OP está encerrada. Edição bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        if request.method == "POST":
            data = request.form["data"]
            sku = request.form.get("sku", "Galinha Cortada")
            fornecedor = request.form["fornecedor"]
            gta = request.form["gta"]
            nota_fiscal = request.form["nota_fiscal"]
            quantidade_aves = int(request.form["quantidade_aves"])
            mortes_antes_pendura = 0
            peso_vivo = float(request.form["peso_vivo"])
            observacoes = request.form["observacoes"]
            peso_medio = peso_vivo / quantidade_aves if quantidade_aves else 0

            cursor.execute(q("""
            UPDATE ordens_producao
            SET data = ?, sku = ?, fornecedor = ?, gta = ?, nota_fiscal = ?,
                quantidade_aves = ?, mortes_antes_pendura = ?, peso_vivo = ?,
                peso_medio = ?, observacoes = ?
            WHERE id = ?
            """), (
                data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
                mortes_antes_pendura, peso_vivo, peso_medio, observacoes, op_id
            ))

            conn.commit()
            conn.close()

            flash("OP atualizada com sucesso.")
            return redirect(url_for("consultar_op", op_id=op_id))

        fornecedores = buscar_fornecedores()

        conn.close()
        return render_template(
            "editar_op.html",
            op=op,
            fornecedores=fornecedores
        )


    @app.route("/mao-obra/<int:mao_obra_id>/editar", methods=["GET", "POST"])
    @perfil_permitido("producao")
    def editar_mao_obra(mao_obra_id):
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        SELECT
            m.*,
            o.status as op_status
        FROM apontamentos_mao_obra m
        JOIN ordens_producao o ON o.id = m.op_id
        WHERE m.id = ?
        """), (mao_obra_id,))

        apontamento = cursor.fetchone()

        if not apontamento:
            conn.close()
            flash("Apontamento de mão de obra não encontrado.")
            return redirect(url_for("consultar_op"))

        if apontamento["op_status"] == "Encerrada" and not usuario_eh_admin():
            op_id = apontamento["op_id"]
            conn.close()
            flash("Esta OP está encerrada. Edição de mão de obra bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        if request.method == "POST":
            colaborador = request.form["colaborador"]
            funcao = request.form["funcao"]
            setor = request.form["setor"]
            turno = request.form.get("turno", "")
            observacoes = request.form.get("observacoes", "")

            cursor.execute(q("""
            UPDATE apontamentos_mao_obra
            SET colaborador = ?,
                funcao = ?,
                setor = ?,
                turno = ?,
                observacoes = ?
            WHERE id = ?
            """), (
                colaborador,
                funcao,
                setor,
                turno,
                observacoes,
                mao_obra_id
            ))

            conn.commit()
            op_id = apontamento["op_id"]
            conn.close()

            flash("Apontamento de mão de obra atualizado com sucesso.")
            return redirect(url_for("consultar_op", op_id=op_id))

        conn.close()

        lista_funcoes = [
            "Lavar gaiolas",
            "Pendura",
            "Sangria",
            "Depenadeira",
            "Transpasse",
            "Retirada do papo",
            "Retirada da cloaca",
            "Corte abdominal",
            "Eventração",
            "Retirada da moela",
            "Abertura da moela",
            "Retirada do coração",
            "Retirada do pulmão",
            "Retirada da cabeça/Revisão final",
            "Limpeza de miudos",
            "Corte",
            "Organização da bandeja",
            "Ensaque da bandeja",
            "Selagem",
            "Pesagem",
            "Embalagem secundária",
            "Rotulagem",
            "Outra"
        ]

        return render_template(
            "editar_mao_obra.html",
            apontamento=apontamento,
            setores=setores_padrao(),
            lista_funcoes=lista_funcoes
        )


    @app.route("/parada/<int:parada_id>/editar", methods=["GET", "POST"])
    @perfil_permitido("producao")
    def editar_parada(parada_id):
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        SELECT
            p.*,
            o.status as op_status
        FROM apontamentos_paradas p
        JOIN ordens_producao o ON o.id = p.op_id
        WHERE p.id = ?
        """), (parada_id,))

        apontamento = cursor.fetchone()

        if not apontamento:
            conn.close()
            flash("Apontamento de parada não encontrado.")
            return redirect(url_for("consultar_op"))

        if apontamento["op_status"] == "Encerrada" and not usuario_eh_admin():
            op_id = apontamento["op_id"]
            conn.close()
            flash("Esta OP está encerrada. Edição de parada bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        if request.method == "POST":
            data = request.form["data"]
            setor = request.form["setor"]
            motivo = request.form["motivo"]
            horas_paradas = float(request.form.get("horas_paradas") or 0)
            observacoes = request.form.get("observacoes", "")

            cursor.execute(q("""
            UPDATE apontamentos_paradas
            SET data = ?,
                setor = ?,
                motivo = ?,
                horas_paradas = ?,
                observacoes = ?
            WHERE id = ?
            """), (
                data,
                setor,
                motivo,
                horas_paradas,
                observacoes,
                parada_id
            ))

            conn.commit()
            op_id = apontamento["op_id"]
            conn.close()

            flash("Apontamento de parada atualizado com sucesso.")
            return redirect(url_for("consultar_op", op_id=op_id))

        conn.close()

        lista_motivos_parada = [
            "Falta de matéria prima",
            "Falta de insumos",
            "Falta de mão de obra",
            "Quebra de equipamento",
            "Manutenção corretiva",
            "Manutenção preventiva",
            "Setup / Troca de Produto",
            "Falta de energia",
            "Ajuste operacional",
            "Limpeza / higienização",
            "Outro"
        ]

        return render_template(
            "editar_parada.html",
            apontamento=apontamento,
            setores=setores_padrao(),
            lista_motivos_parada=lista_motivos_parada
        )


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


    @app.route("/mao-obra/lote/editar", methods=["GET", "POST"])
    @perfil_permitido("producao")
    def editar_mao_obra_lote():
        ids = ids_do_request("ids")

        if not ids:
            flash("Selecione pelo menos um lançamento de mão de obra.")
            return redirect(url_for("consultar_op"))

        registros = obter_registros_por_ids("apontamentos_mao_obra", ids)

        if not registros:
            flash("Nenhum lançamento de mão de obra encontrado.")
            return redirect(url_for("consultar_op"))

        op_id = primeiro_op_id(registros)

        if edicao_bloqueada_por_status(registros):
            flash("Esta OP está encerrada. Edição de mão de obra bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        if request.method == "POST" and request.form.get("acao") == "salvar":
            funcao = request.form["funcao"]
            setor = request.form["setor"]
            turno = request.form.get("turno", "")
            observacoes = request.form.get("observacoes", "")

            placeholders = ",".join(["?"] * len(ids))

            conn = conectar()
            cursor = conn.cursor()

            cursor.execute(q(f"""
            UPDATE apontamentos_mao_obra
            SET funcao = ?,
                setor = ?,
                turno = ?,
                observacoes = ?
            WHERE id IN ({placeholders})
            """), (funcao, setor, turno, observacoes, *ids))

            conn.commit()
            conn.close()

            flash("Lançamentos de mão de obra atualizados com sucesso.")
            return redirect(url_for("consultar_op", op_id=op_id))

        lista_funcoes = [
            "Lavar gaiolas",
            "Pendura",
            "Sangria",
            "Depenadeira",
            "Transpasse",
            "Retirada do papo",
            "Retirada da cloaca",
            "Corte abdominal",
            "Eventração",
            "Retirada da moela",
            "Abertura da moela",
            "Retirada do coração",
            "Retirada do pulmão",
            "Retirada da cabeça/Revisão final",
            "Limpeza de miudos",
            "Corte",
            "Organização da bandeja",
            "Ensaque da bandeja",
            "Selagem",
            "Pesagem",
            "Embalagem secundária",
            "Rotulagem",
            "Outra"
        ]

        return render_template(
            "editar_mao_obra_lote.html",
            registros=registros,
            ids=ids,
            setores=setores_padrao(),
            lista_funcoes=lista_funcoes
        )


    @app.route("/mao-obra/lote/excluir", methods=["POST"])
    @perfil_permitido("producao")
    def excluir_mao_obra_lote():
        ids = ids_do_request("ids")

        if not ids:
            flash("Selecione pelo menos um lançamento de mão de obra para excluir.")
            return redirect(url_for("consultar_op"))

        registros = obter_registros_por_ids("apontamentos_mao_obra", ids)
        op_id = primeiro_op_id(registros)

        if not registros:
            flash("Nenhum lançamento de mão de obra encontrado.")
            return redirect(url_for("consultar_op"))

        if edicao_bloqueada_por_status(registros):
            flash("Esta OP está encerrada. Exclusão de mão de obra bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        DELETE FROM apontamentos_mao_obra
        WHERE id IN ({placeholders})
        """), tuple(ids))

        conn.commit()
        conn.close()

        flash("Lançamentos de mão de obra excluídos com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.route("/paradas/lote/editar", methods=["GET", "POST"])
    @perfil_permitido("producao")
    def editar_paradas_lote():
        ids = ids_do_request("ids")

        if not ids:
            flash("Selecione pelo menos um lançamento de parada.")
            return redirect(url_for("consultar_op"))

        registros = obter_registros_por_ids("apontamentos_paradas", ids)

        if not registros:
            flash("Nenhum lançamento de parada encontrado.")
            return redirect(url_for("consultar_op"))

        op_id = primeiro_op_id(registros)

        if edicao_bloqueada_por_status(registros):
            flash("Esta OP está encerrada. Edição de parada bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        if request.method == "POST" and request.form.get("acao") == "salvar":
            data = request.form["data"]
            setor = request.form["setor"]
            motivo = request.form["motivo"]
            horas_paradas = float(request.form.get("horas_paradas") or 0)
            observacoes = request.form.get("observacoes", "")

            placeholders = ",".join(["?"] * len(ids))

            conn = conectar()
            cursor = conn.cursor()

            cursor.execute(q(f"""
            UPDATE apontamentos_paradas
            SET data = ?,
                setor = ?,
                motivo = ?,
                horas_paradas = ?,
                observacoes = ?
            WHERE id IN ({placeholders})
            """), (data, setor, motivo, horas_paradas, observacoes, *ids))

            conn.commit()
            conn.close()

            flash("Lançamentos de parada atualizados com sucesso.")
            return redirect(url_for("consultar_op", op_id=op_id))

        lista_motivos_parada = [
            "Falta de matéria prima",
            "Falta de insumos",
            "Falta de mão de obra",
            "Quebra de equipamento",
            "Manutenção corretiva",
            "Manutenção preventiva",
            "Setup / Troca de Produto",
            "Falta de energia",
            "Ajuste operacional",
            "Limpeza / higienização",
            "Outro"
        ]

        return render_template(
            "editar_paradas_lote.html",
            registros=registros,
            ids=ids,
            setores=setores_padrao(),
            lista_motivos_parada=lista_motivos_parada
        )


    @app.route("/paradas/lote/excluir", methods=["POST"])
    @perfil_permitido("producao")
    def excluir_paradas_lote():
        ids = ids_do_request("ids")

        if not ids:
            flash("Selecione pelo menos um lançamento de parada para excluir.")
            return redirect(url_for("consultar_op"))

        registros = obter_registros_por_ids("apontamentos_paradas", ids)
        op_id = primeiro_op_id(registros)

        if not registros:
            flash("Nenhum lançamento de parada encontrado.")
            return redirect(url_for("consultar_op"))

        if edicao_bloqueada_por_status(registros):
            flash("Esta OP está encerrada. Exclusão de parada bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        DELETE FROM apontamentos_paradas
        WHERE id IN ({placeholders})
        """), tuple(ids))

        conn.commit()
        conn.close()

        flash("Lançamentos de parada excluídos com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))




    @app.route("/op/<int:op_id>/excluir", methods=["POST"])
    @perfil_permitido("admin")
    def excluir_op(op_id):
        conn = conectar()
        cursor = conn.cursor()

        for tabela in [
            "apontamentos_setor",
            "apontamentos_producao",
            "apontamentos_mao_obra",
            "apontamentos_paradas",
            "apontamentos_descartes",
            "apontamentos_tempos_setor"
        ]:
            cursor.execute(q(f"DELETE FROM {tabela} WHERE op_id = ?"), (op_id,))

        cursor.execute(q("DELETE FROM ordens_producao WHERE id = ?"), (op_id,))

        conn.commit()
        conn.close()

        flash("OP excluída com sucesso.")
        return redirect(url_for("consultar_op"))


    @app.route("/op/<int:op_id>/encerrar", methods=["POST"])
    @perfil_permitido("pcp")
    def encerrar_op(op_id):
        op = buscar_op_por_id(op_id)

        if not op:
            flash("OP não encontrada.")
            return redirect(url_for("consultar_op"))

        if op["status"] == "Encerrada":
            flash("Esta OP já está encerrada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        try:
            hora_inicio = request.form["hora_inicio"]
            hora_fim = request.form["hora_fim"]
            unidades_produzidas = float(request.form["unidades_produzidas"])
            kg_produzidos_raw = request.form.get("kg_produzidos", "")
            descontar_almoco = request.form.get("descontar_almoco") == "sim"

            kg_produzidos = None
            if (op["sku"] or "Galinha Cortada") == "Galinha Cortada":
                if not kg_produzidos_raw:
                    raise ValueError("Informe o kg produzido para Galinha Cortada.")
                kg_produzidos = float(kg_produzidos_raw)

            gerar_producao_automatica_setores(
                op=op,
                data_lancamento=op["data"],
                hora_inicio=hora_inicio,
                hora_fim=hora_fim,
                unidades_produzidas=unidades_produzidas,
                kg_produzidos=kg_produzidos,
                descontar_almoco=descontar_almoco
            )

            conn = conectar()
            cursor = conn.cursor()

            cursor.execute(q("""
            UPDATE ordens_producao
            SET status = ?
            WHERE id = ?
            """), ("Encerrada", op_id))

            conn.commit()
            conn.close()

            flash("OP encerrada com sucesso. A produção final foi gerada automaticamente.")

        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("consultar_op", op_id=op_id))


    @app.route("/op/<int:op_id>/reabrir", methods=["POST"])
    @perfil_permitido("admin")
    def reabrir_op(op_id):
        op = buscar_op_por_id(op_id)

        if not op:
            flash("OP não encontrada.")
            return redirect(url_for("consultar_op"))

        if _integracao("op_possui_caixa_pa")(op_id):
            flash("Esta OP já possui bandejas vinculadas a caixas de PA. Reabertura bloqueada para preservar a rastreabilidade.")
            return redirect(url_for("consultar_op", op_id=op_id))

        _integracao("remover_movimentacoes_estoque_pi_por_op")(op_id)

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        UPDATE ordens_producao
        SET status = ?
        WHERE id = ?
        """), ("Aberta", op_id))

        conn.commit()
        conn.close()

        flash("OP reaberta com sucesso. A entrada automática no Estoque PI foi estornada.")
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.route("/consultar-op")
    @perfil_permitido("pcp", "qualidade", "producao")
    def consultar_op():
        op_id = request.args.get("op_id")
        ordens = buscar_ordens()

        op = None
        producoes = []
        mao_obra = []
        paradas = []
        descartes = []
        tempos_setor = []
        resumo = None

        if op_id:
            conn = conectar()
            cursor = conn.cursor()

            cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
            op = cursor.fetchone()

            cursor.execute(q("SELECT * FROM apontamentos_producao WHERE op_id = ? ORDER BY id ASC"), (op_id,))
            producoes = cursor.fetchall()

            cursor.execute(q("SELECT * FROM apontamentos_mao_obra WHERE op_id = ? ORDER BY id ASC"), (op_id,))
            mao_obra = cursor.fetchall()

            cursor.execute(q("SELECT * FROM apontamentos_paradas WHERE op_id = ? ORDER BY id ASC"), (op_id,))
            paradas = cursor.fetchall()

            cursor.execute(q("SELECT * FROM apontamentos_descartes WHERE op_id = ? ORDER BY id ASC"), (op_id,))
            descartes = cursor.fetchall()

            cursor.execute(q("SELECT * FROM apontamentos_tempos_setor WHERE op_id = ? ORDER BY id ASC"), (op_id,))
            tempos_setor = cursor.fetchall()

            if op:
                resumo = calcular_resumo_op(op, producoes, descartes)

            conn.close()

        return render_template(
            "consultar_op.html",
            ordens=ordens,
            op=op,
            producoes=producoes,
            mao_obra=mao_obra,
            paradas=paradas,
            descartes=descartes,
            tempos_setor=tempos_setor,
            resumo=resumo
        )


    @app.route("/op/<int:op_id>/imprimir")
    @perfil_permitido("pcp", "qualidade", "producao")
    def imprimir_op(op_id):
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
        op = cursor.fetchone()

        cursor.execute(q("SELECT * FROM apontamentos_producao WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        producoes = cursor.fetchall()

        cursor.execute(q("SELECT * FROM apontamentos_mao_obra WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        mao_obra = cursor.fetchall()

        cursor.execute(q("SELECT * FROM apontamentos_paradas WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        paradas = cursor.fetchall()

        cursor.execute(q("SELECT * FROM apontamentos_descartes WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        descartes = cursor.fetchall()

        resumo = calcular_resumo_op(op, producoes, descartes) if op else None

        conn.close()

        return render_template(
            "op_impressao.html",
            op=op,
            producoes=producoes,
            mao_obra=mao_obra,
            paradas=paradas,
            descartes=descartes,
            resumo=resumo
        )
