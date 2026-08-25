"""Rotas operacionais do m?dulo de Produ??o."""

from datetime import datetime
import uuid

from flask import flash, redirect, render_template, request, session, url_for

from database import DATABASE_URL, conectar, q
from modules.auth.decorators import login_obrigatorio, perfil_permitido
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
    registrar_peso_caixa_op,
    salvar_apontamento_mao_obra,
    salvar_apontamento_parada,
    salvar_tempos_setor,
    setores_por_sku,
)
from .correcoes_administrativas import (
    buscar_correcoes_op,
    corrigir_peso_entrada_op,
)
from .disponibilidade import (
    CATEGORIAS_PAUSA,
    calcular_disponibilidade,
    consultar_historico_paradas,
    corrigir_medicao,
    obter_programacao,
    pausas_do_form,
    reclassificar_parada,
    registrar_fim_linha,
    registrar_inicio_linha,
    salvar_programacao,
)
from .performance import (
    calcular_performance,
    confirmar_contagem,
    corrigir_snapshot,
    decidir_velocidade,
    historico_performance,
    listar_skus_operacionais,
    listar_velocidades,
    preparar_snapshot_inicio,
    propor_velocidade,
    registrar_reprocesso,
    sugerir_contagem,
)
from .operacoes_op import (
    estornar_op_integral,
    historico_operacoes_op,
    preflight_operacao_op,
    reabrir_op as reabrir_op_operacional,
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
            sql_op = """
            INSERT INTO ordens_producao (
                data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
                mortes_antes_pendura, peso_vivo, peso_medio, observacoes, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            parametros_op = (
                data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
                mortes_antes_pendura, peso_vivo, peso_medio, observacoes, "Aberta"
            )
            try:
                if DATABASE_URL:
                    cursor.execute(q(sql_op + " RETURNING id"), parametros_op)
                    op_id = cursor.fetchone()["id"]
                else:
                    cursor.execute(sql_op, parametros_op)
                    op_id = cursor.lastrowid
                inicio_programado = request.form.get("inicio_programado")
                fim_programado = request.form.get("fim_programado")
                if inicio_programado or fim_programado:
                    salvar_programacao(
                        op_id,
                        f"{data}T{inicio_programado}" if inicio_programado else "",
                        f"{data}T{fim_programado}" if fim_programado else "",
                        pausas_do_form(request.form),
                        usuario=session.get("nome") or "Usuario",
                        usuario_id=session.get("usuario_id"),
                        perfil=session.get("perfil"),
                        conn=conn,
                    )
                conn.commit()
            except (ValueError, PermissionError) as erro:
                conn.rollback()
                conn.close()
                flash(str(erro))
                return render_template(
                    "ordem_producao.html", hoje=data, ordens=buscar_ordens()[:10],
                    fornecedores=buscar_fornecedores(), categorias_pausa=sorted(CATEGORIAS_PAUSA),
                )
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
            fornecedores=fornecedores,
            categorias_pausa=sorted(CATEGORIAS_PAUSA),
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
                if not request.form.get("afeta_linha_abate"):
                    raise ValueError("Informe se a parada afetou a Linha de Abate.")
                salvar_apontamento_parada(request.form)
                flash("Apontamento de horas paradas salvo.")
            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("apontamento_paradas"))

        filtros = {nome: request.args.get(nome, "") for nome in (
            "inicio", "fim", "op", "status", "setor", "equipamento",
            "motivo", "situacao", "afeta",
        )}
        contexto = contexto_apontamento()
        contexto.update({
            "filtros": filtros,
            "historico_paradas": consultar_historico_paradas(filtros),
        })
        return render_template("apontamento_paradas.html", **contexto)


    @app.post("/op/<int:op_id>/linha/iniciar")
    @perfil_permitido("producao")
    def iniciar_linha_abate(op_id):
        try:
            preparar_snapshot_inicio(
                op_id, usuario=session.get("nome") or "Usuario",
                usuario_id=session.get("usuario_id"), perfil=session.get("perfil"),
            )
            registrar_inicio_linha(
                op_id, usuario=session.get("nome") or "Usuario",
                usuario_id=session.get("usuario_id"), perfil=session.get("perfil"),
            )
            flash("Inicio real da Linha de Abate registrado.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.route("/linha-abate/velocidades")
    @perfil_permitido("pcp", "gerencia", "producao", "qualidade")
    def velocidades_ideais_linha():
        filtros = {campo: request.args.get(campo, "") for campo in ("status", "configuracao", "sku")}
        return render_template(
            "velocidades_ideais_linha.html",
            velocidades=listar_velocidades(filtros), filtros=filtros,
            skus=listar_skus_operacionais(),
        )


    @app.post("/linha-abate/velocidades/propor")
    @perfil_permitido("pcp", "gerencia")
    def propor_velocidade_linha():
        try:
            propor_velocidade(
                request.form.get("configuracao"), request.form.get("sku"),
                request.form.get("velocidade_aves_hora"), request.form.get("vigencia_inicio"),
                request.form.get("justificativa_tecnica"),
                usuario=session.get("nome") or "Usuario", usuario_id=session.get("usuario_id"),
                perfil=session.get("perfil"),
            )
            flash("Velocidade ideal proposta e enviada para aprovacao.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("velocidades_ideais_linha"))


    @app.post("/linha-abate/velocidades/<int:velocidade_id>/decidir")
    @perfil_permitido("admin")
    def decidir_velocidade_linha(velocidade_id):
        try:
            decidir_velocidade(
                velocidade_id, request.form.get("acao"), request.form.get("justificativa"),
                vigencia_fim=request.form.get("vigencia_fim"),
                usuario=session.get("nome") or "Usuario", usuario_id=session.get("usuario_id"),
                perfil=session.get("perfil"),
            )
            flash("Decisao da velocidade registrada com auditoria.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("velocidades_ideais_linha"))


    @app.post("/op/<int:op_id>/performance/confirmar-contagem")
    @perfil_permitido("producao")
    def confirmar_contagem_performance(op_id):
        try:
            confirmar_contagem(
                op_id, request.form.get("aves_recebidas"),
                request.form.get("mortes_antes_pendura"), request.form.get("aves_processadas"),
                observacao=request.form.get("observacao"),
                justificativa=request.form.get("justificativa"),
                usuario=session.get("nome") or "Usuario", usuario_id=session.get("usuario_id"),
                perfil=session.get("perfil"),
            )
            flash("Contagem oficial da Linha de Abate confirmada com auditoria.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.post("/op/<int:op_id>/performance/corrigir-snapshot")
    @perfil_permitido("admin")
    def corrigir_snapshot_performance(op_id):
        try:
            corrigir_snapshot(
                op_id, int(request.form.get("velocidade_id") or 0),
                request.form.get("justificativa"), usuario=session.get("nome") or "Usuario",
                usuario_id=session.get("usuario_id"), perfil=session.get("perfil"),
            )
            flash("Snapshot de velocidade corrigido com auditoria.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.post("/op/<int:op_id>/performance/reprocesso")
    @perfil_permitido("producao")
    def registrar_reprocesso_performance(op_id):
        try:
            registrar_reprocesso(
                op_id, request.form.get("quantidade_aves"),
                request.form.get("atravessou_linha"), request.form.get("data_hora"),
                request.form.get("motivo"), request.form.get("execucao_original"),
                request.form.get("chave_idempotencia"),
                usuario=session.get("nome") or "Usuario", usuario_id=session.get("usuario_id"),
                perfil=session.get("perfil"),
            )
            flash("Evento de reprocesso registrado com auditoria.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.post("/op/<int:op_id>/linha/encerrar")
    @perfil_permitido("producao")
    def encerrar_linha_abate(op_id):
        try:
            registrar_fim_linha(
                op_id, usuario=session.get("nome") or "Usuario",
                usuario_id=session.get("usuario_id"), perfil=session.get("perfil"),
            )
            flash("Termino real da Linha de Abate registrado sem encerrar a OP.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.post("/op/<int:op_id>/linha/corrigir")
    @perfil_permitido("admin")
    def corrigir_medicao_linha_abate(op_id):
        try:
            corrigir_medicao(
                op_id, request.form.get("inicio_real"), request.form.get("fim_real"),
                request.form.get("justificativa"), usuario=session.get("nome") or "Usuario",
                usuario_id=session.get("usuario_id"), perfil=session.get("perfil"),
            )
            flash("Medicao da Linha corrigida com auditoria.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.post("/parada/<int:parada_id>/classificar-linha")
    @perfil_permitido("admin")
    def classificar_parada_linha(parada_id):
        op_id = request.form.get("op_id")
        try:
            reclassificar_parada(
                parada_id, request.form.get("afeta_linha_abate"),
                request.form.get("justificativa"), usuario=session.get("nome") or "Usuario",
                usuario_id=session.get("usuario_id"), perfil=session.get("perfil"),
            )
            flash("Classificacao da parada atualizada com auditoria.")
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("consultar_op", op_id=op_id) if op_id else url_for("apontamento_paradas"))




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

            sucesso = False
            try:
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
                inicio_programado = request.form.get("inicio_programado")
                fim_programado = request.form.get("fim_programado")
                if inicio_programado or fim_programado:
                    salvar_programacao(
                        op_id,
                        f"{data}T{inicio_programado}" if inicio_programado else "",
                        f"{data}T{fim_programado}" if fim_programado else "",
                        pausas_do_form(request.form),
                        usuario=session.get("nome") or "Usuario",
                        usuario_id=session.get("usuario_id"),
                        perfil=session.get("perfil"),
                        justificativa=request.form.get("justificativa_programacao"),
                        conn=conn,
                    )
                conn.commit()
                sucesso = True
            except (ValueError, PermissionError) as erro:
                conn.rollback()
                flash(str(erro))
            finally:
                conn.close()

            if sucesso:
                flash("OP atualizada com sucesso.")
            return redirect(url_for("editar_op", op_id=op_id))

        fornecedores = buscar_fornecedores()
        programacao_linha, pausas_planejadas = obter_programacao(op_id)

        conn.close()
        return render_template(
            "editar_op.html",
            op=op,
            fornecedores=fornecedores,
            programacao_linha=programacao_linha,
            pausas_planejadas=pausas_planejadas,
            categorias_pausa=sorted(CATEGORIAS_PAUSA),
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

            if "corretiva" in str(apontamento["motivo"] or "").lower() and "preventiva" in motivo.lower():
                conn.close()
                flash("Manutencao corretiva nao pode ser reclassificada como preventiva.")
                return redirect(url_for("editar_parada", parada_id=parada_id))

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

            if any(
                "corretiva" in str(item["motivo"] or "").lower()
                for item in registros
            ) and "preventiva" in motivo.lower():
                flash("Manutencao corretiva nao pode ser reclassificada como preventiva.")
                return redirect(url_for("editar_paradas_lote", ids=ids))

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

        if (op["sku"] or "Galinha Cortada") == "Galinha Inteira":
            flash("Galinha Inteira deve ser encerrada pela Embalagem Primária, com pacotes V1 e V2.")
            return redirect(url_for("embalagem_primaria", op_id=op_id))

        flash("Galinha Cortada deve ser encerrada pela validação final da Embalagem Secundária.")
        return redirect(url_for("embalagem_secundaria", op_id=op_id))


    @app.route("/op/<int:op_id>/reabrir", methods=["POST"])
    @perfil_permitido("admin", "pcp", "gerencia")
    def reabrir_op(op_id):
        try:
            resultado = reabrir_op_operacional(
                op_id, usuario=session.get("nome") or session.get("usuario_nome") or "Usuário",
                perfil=session.get("perfil"), motivo=request.form.get("motivo"),
                etapa_destino=request.form.get("etapa_destino"),
                idempotency_key=request.form.get("idempotency_key"),
                ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
                confirmacao=request.form.get("confirmacao") == "REABRIR",
            )
            flash(f"OP reaberta para {resultado['etapa_destino']}. PI, PA, caixas e apontamentos foram preservados.")
            return redirect(url_for(
                "embalagem_secundaria", op_id=op_id,
                conferencia="1" if resultado["etapa_destino"] == "CONFERENCIA_FINAL" else None,
            ))
        except (ValueError, PermissionError) as erro:
            flash(str(erro))
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.route("/op/<int:op_id>/estornar-integral", methods=["POST"])
    @perfil_permitido("admin", "pcp", "gerencia")
    def estornar_op_integral_route(op_id):
        try:
            resultado = estornar_op_integral(
                op_id, usuario=session.get("nome") or session.get("usuario_nome") or "Usuário",
                perfil=session.get("perfil"), motivo=request.form.get("motivo"),
                idempotency_key=request.form.get("idempotency_key"),
                ip_origem=request.access_route[0] if request.access_route else request.remote_addr,
                confirmacao=request.form.get("confirmacao") == "ESTORNAR_INTEGRAL",
            )
            flash(f"OP estornada integralmente. {resultado['efeitos']['caixas_estornadas']} caixa(s) revertida(s), sem exclusão física.")
        except (ValueError, PermissionError) as erro:
            status = 403 if isinstance(erro, PermissionError) else 409
            return render_template(
                "erro_operacional.html", titulo="Estorno integral não executado",
                mensagem=str(erro), retorno=url_for("consultar_op", op_id=op_id),
            ), status
        return redirect(url_for("consultar_op", op_id=op_id))


    @app.route("/consultar-op")
    @perfil_permitido("pcp", "qualidade", "producao", "gerencia", "manutencao")
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
        correcoes_administrativas = []
        disponibilidade_linha = None
        performance_linha = None
        sugestao_contagem_performance = None
        historico_performance_linha = []
        preflight_reabertura = None
        preflight_estorno = None
        historico_operacional_op = []
        chaves_operacao = {}

        if op_id:
            conn = conectar()
            cursor = conn.cursor()

            cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
            op = cursor.fetchone()

            cursor.execute(q("SELECT * FROM apontamentos_producao WHERE op_id = ? AND COALESCE(vigente,1)=1 ORDER BY id ASC"), (op_id,))
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
                correcoes_administrativas = buscar_correcoes_op(op_id)
                disponibilidade_linha = calcular_disponibilidade(op_id, conn=conn)
                performance_linha = calcular_performance(
                    op_id, conn=conn, disponibilidade=disponibilidade_linha,
                )
                sugestao_contagem_performance = sugerir_contagem(op_id, conn=conn)
                cursor.execute("SELECT * FROM linha_abate_velocidades_ideais WHERE status='ATIVA' AND ativo_logico=1 ORDER BY configuracao,sku,id DESC")
                velocidades_ativas_performance = cursor.fetchall()
                cursor.execute(q("SELECT * FROM linha_performance_auditoria WHERE op_id=? ORDER BY criado_em DESC,id DESC"), (op_id,))
                historico_performance_linha = cursor.fetchall()
                preflight_reabertura = preflight_operacao_op(op_id, "REABERTURA")
                preflight_estorno = preflight_operacao_op(op_id, "ESTORNO_INTEGRAL")
                historico_operacional_op = historico_operacoes_op(op_id)
                chaves_operacao = {
                    "reabertura": f"REABRIR-OP-{op_id}-{uuid.uuid4()}",
                    "estorno": f"ESTORNAR-OP-{op_id}-{uuid.uuid4()}",
                }
            else:
                velocidades_ativas_performance = []

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
            resumo=resumo,
            correcoes_administrativas=correcoes_administrativas,
            disponibilidade_linha=disponibilidade_linha,
            performance_linha=performance_linha,
            sugestao_contagem_performance=sugestao_contagem_performance,
            velocidades_ativas_performance=velocidades_ativas_performance if op else [],
            historico_performance_linha=historico_performance_linha,
            preflight_reabertura=preflight_reabertura,
            preflight_estorno=preflight_estorno,
            historico_operacional_op=historico_operacional_op,
            chaves_operacao=chaves_operacao,
        )

    @app.route("/op/<int:op_id>/corrigir-peso-entrada", methods=["POST"])
    @login_obrigatorio
    def corrigir_peso_entrada(op_id):
        usuario = {
            "id": session.get("usuario_id"),
            "nome": session.get("nome") or session.get("usuario_nome"),
        }
        try:
            corrigir_peso_entrada_op(
                op_id,
                request.form.get("peso_entrada_corrigido"),
                request.form.get("motivo"),
                request.form.get("observacoes"),
                usuario=usuario,
                perfil=session.get("perfil"),
                origem=request.access_route[0] if request.access_route else request.remote_addr,
            )
            flash("Peso de Entrada corrigido. A OP permaneceu encerrada e a auditoria foi registrada.")
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("consultar_op", op_id=op_id))


    @app.route("/op/<int:op_id>/imprimir")
    @perfil_permitido("pcp", "qualidade", "producao")
    def imprimir_op(op_id):
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
        op = cursor.fetchone()

        cursor.execute(q("SELECT * FROM apontamentos_producao WHERE op_id = ? AND COALESCE(vigente,1)=1 ORDER BY id ASC"), (op_id,))
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
