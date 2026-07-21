"""Servicos do modulo de Qualidade."""

from datetime import datetime

from database import conectar, q
from modules.producao.services import validar_op_aberta
from . import repositories as repo
from .plm_config import CRITICIDADES, FORMULARIOS_PLM, LIMITES_LUX


def salvar_apontamento_descarte(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_descartes (
        op_id, data, setor, categoria, motivo, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        op_id,
        form["data"],
        form["setor"],
        form["categoria"],
        form["motivo"],
        float(form["quantidade"]),
        form["unidade"],
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()


def salvar_apontamentos_descartes_lote(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    data = form["data"]
    observacoes = form.get("observacoes", "")
    quantidades = form.getlist("quantidade[]")
    motivos = form.getlist("motivo[]")
    setores = form.getlist("setor[]")

    if not quantidades:
        raise ValueError("Adicione pelo menos uma linha de descarte antes de confirmar.")

    if not (len(quantidades) == len(motivos) == len(setores)):
        raise ValueError("As linhas de descarte estao incompletas. Revise quantidades, motivos e setores.")

    linhas = []
    for indice, quantidade_raw in enumerate(quantidades, start=1):
        try:
            quantidade = float(quantidade_raw)
        except (TypeError, ValueError):
            raise ValueError(f"Informe uma quantidade valida na linha {indice}.")

        if quantidade <= 0:
            raise ValueError(f"A quantidade da linha {indice} precisa ser maior que zero.")

        motivo = motivos[indice - 1]
        setor = setores[indice - 1]

        if not motivo or not setor:
            raise ValueError(f"Selecione motivo e setor na linha {indice}.")

        linhas.append((op_id, data, setor, "Descarte", motivo, quantidade, "aves", observacoes))

    conn = conectar()
    cursor = conn.cursor()

    cursor.executemany(q("""
    INSERT INTO apontamentos_descartes (
        op_id, data, setor, categoria, motivo, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), linhas)

    conn.commit()
    conn.close()

    return len(linhas)


def criar_tabelas_sgi():
    repo.criar_tabelas_sgi()


def cadastrar_setor_sgi(form):
    nome = (form.get("nome") or "").strip()
    repo.inserir_setor(nome)


def cadastrar_local_sgi(form):
    tipo = (form.get("tipo") or "").strip()
    nome = (form.get("nome") or "").strip()
    setor_id = int(form.get("setor_id") or 0) or None
    setor = repo.buscar_setor(setor_id) if setor_id else None
    classificacao = (form.get("classificacao_iluminacao") or "").strip()
    descricao = (form.get("descricao") or "").strip()
    ambiente_id = int(form.get("ambiente_id") or 0) or None
    if tipo not in ("Ambiente", "Estrutura"):
        raise ValueError("Tipo de cadastro invalido.")
    if not nome or not setor:
        raise ValueError("Informe nome e setor do local.")
    if tipo == "Ambiente" and classificacao not in LIMITES_LUX:
        raise ValueError("Classifique a iluminacao do ambiente.")
    if tipo == "Estrutura" and ambiente_id:
        ambiente = repo.buscar_local(ambiente_id)
        if not ambiente or ambiente["tipo"] != "Ambiente":
            raise ValueError("Ambiente relacionado invalido.")
        if ambiente["setor_id"] and int(ambiente["setor_id"]) != int(setor_id):
            raise ValueError("Ambiente relacionado pertence a outro setor.")
    repo.inserir_local(tipo, nome, setor["nome"], classificacao, descricao, setor_id, ambiente_id)


def contexto_central_sgi(args=None):
    args = args or {}
    filtros = {
        "mes": args.get("mes") or datetime.now().strftime("%Y-%m"),
        "formulario_tipo": args.get("formulario_tipo") or "Todos",
        "setor_id": args.get("setor_id") or "Todos",
        "setor": "Todos",
        "status": args.get("status") or "Todos",
    }
    verificacoes = repo.listar_verificacoes(filtros)
    return {
        "formularios": FORMULARIOS_PLM,
        "verificacoes": verificacoes,
        "filtros": filtros,
        "setores": repo.listar_setores(),
        "ambientes": repo.listar_locais("Ambiente"),
        "estruturas": repo.listar_locais("Estrutura"),
        "total_concluidas": sum(1 for item in verificacoes if item["status"] == "Concluida"),
        "total_pendencias": sum(int(item["ncs_abertas"] or 0) for item in verificacoes),
        "total_ncs": sum(int(item["total_ncs"] or 0) for item in verificacoes),
        "pendencias_gerencia": sum(int(item["pendencias_gerencia"] or 0) for item in verificacoes),
    }


def contexto_nova_verificacao(tipo):
    formulario = FORMULARIOS_PLM.get(tipo)
    if not formulario:
        raise ValueError("Formulario PLM invalido.")
    return {
        "tipo": tipo,
        "formulario": formulario,
        "formularios": FORMULARIOS_PLM,
        "setores": repo.listar_setores(),
        "locais": repo.listar_locais(),
        "ambientes": repo.listar_locais("Ambiente"),
        "estruturas": repo.listar_locais("Estrutura"),
        "equipamentos": repo.listar_equipamentos(),
        "limites_lux": LIMITES_LUX,
    }


def _valor(form, nome):
    return (form.get(nome) or "").strip()


def salvar_verificacao_sgi(tipo, form, usuario_id, usuario_nome):
    formulario = FORMULARIOS_PLM.get(tipo)
    if not formulario:
        raise ValueError("Formulario PLM invalido.")
    data = _valor(form, "data")
    setor_id = int(form.get("setor_id") or 0) or None
    setor_cadastro = repo.buscar_setor(setor_id) if setor_id else None
    setor = setor_cadastro["nome"] if setor_cadastro else _valor(form, "setor")
    responsavel = _valor(form, "responsavel")
    vinculo_tipo = _valor(form, "vinculo_tipo")
    if not data or not responsavel:
        raise ValueError("Informe data e responsavel/monitor.")
    if not setor_cadastro:
        raise ValueError("Selecione um setor cadastrado ativo.")
    if vinculo_tipo not in formulario["vinculos"]:
        raise ValueError("Vinculo incompativel com este formulario.")

    local_id = int(form.get("local_id") or 0) or None
    equipamento_id = int(form.get("equipamento_id") or 0) or None
    local = None
    if vinculo_tipo == "Equipamento":
        if not equipamento_id or not repo.buscar_equipamento(equipamento_id):
            raise ValueError("Vincule um equipamento cadastrado para concluir.")
        equipamento = repo.buscar_equipamento(equipamento_id)
        if equipamento["setor"] and equipamento["setor"] != setor:
            raise ValueError("Equipamento nao pertence ao setor selecionado.")
    else:
        local = repo.buscar_local(local_id) if local_id else None
        if not local or local["tipo"] != vinculo_tipo:
            raise ValueError("Vincule um ambiente ou estrutura cadastrado para concluir.")
        if local["setor_id"] and int(local["setor_id"]) != int(setor_id):
            raise ValueError("Item vinculado nao pertence ao setor selecionado.")
        if not local["setor_id"] and local["setor"] != setor:
            raise ValueError("Item vinculado nao pertence ao setor selecionado.")

    itens, ncs, acoes = [], [], {}
    for codigo, descricao, tipo_campo in formulario["itens"]:
        valor_texto = _valor(form, f"valor_{codigo}")
        valor_numerico = None
        unidade = None
        parametro = None
        resultado = _valor(form, f"resultado_{codigo}") or None
        if tipo_campo == "lux":
            try:
                valor_numerico = float(form.get(f"valor_{codigo}") or "")
            except ValueError:
                raise ValueError("Informe o valor medido em lux.")
            classificacao = local["classificacao_iluminacao"] if local else ""
            parametro = LIMITES_LUX.get(classificacao)
            if not parametro:
                raise ValueError("O ambiente nao possui classificacao de iluminacao valida.")
            unidade = "lux"
            resultado = "C" if valor_numerico >= parametro else "NC"
            valor_texto = None
        elif tipo_campo.startswith("resultado"):
            permitidos = ("C", "NC", "NA") if "na" in tipo_campo else ("C", "NC")
            if resultado not in permitidos:
                raise ValueError(f"Informe o resultado de: {descricao}.")
            valor_texto = None
        elif tipo_campo == "texto" and not valor_texto:
            valor_texto = ""

        observacao = _valor(form, f"observacao_{codigo}")
        acao = _valor(form, f"acao_{codigo}")
        reposicao = "Sim" if form.get(f"reposicao_{codigo}") == "Sim" else "Nao"
        itens.append((codigo, descricao, valor_texto, valor_numerico, unidade, parametro,
                      resultado, observacao, acao, reposicao))
        if resultado == "NC":
            criticidade = _valor(form, f"criticidade_{codigo}") or "NORMAL"
            if criticidade not in CRITICIDADES:
                raise ValueError("Criticidade invalida.")
            descricao_nc = observacao or f"Nao conformidade em {descricao}."
            situacao = "Aguardando reposicao" if reposicao == "Sim" else "Aberta"
            ncs.append({
                "item_codigo": codigo, "descricao": descricao_nc,
                "criticidade": criticidade, "situacao": situacao,
                "tratamento": acao,
            })
            if reposicao == "Sim":
                if tipo != "plm02_sanitarios":
                    raise ValueError("Reposicao simples e exclusiva do PLM 02.")
                pessoa = _valor(form, f"pessoa_acionada_{codigo}")
                if not pessoa:
                    raise ValueError(f"Informe a pessoa acionada para repor: {descricao}.")
                acoes[codigo] = (descricao, pessoa)

    cabecalho = (
        tipo, formulario["codigo"], formulario["nome"], data, setor, setor_id, vinculo_tipo,
        local_id, equipamento_id, responsavel, "Concluida", _valor(form, "observacoes"),
        usuario_id, usuario_nome, usuario_id, usuario_nome,
    )
    evento = ("Verificacao", None, "Verificacao concluida",
              f"{formulario['codigo']} - {formulario['nome']}", usuario_id, usuario_nome)
    return repo.inserir_verificacao(cabecalho, itens, ncs, acoes, evento)


def contexto_verificacao(verificacao_id):
    verificacao, itens, ncs, acoes, eventos = repo.buscar_verificacao(verificacao_id)
    if not verificacao:
        raise ValueError("Verificacao nao encontrada.")
    return {"verificacao": verificacao, "itens": itens, "ncs": ncs,
            "acoes_imediatas": acoes, "eventos": eventos}


def confirmar_reposicao_sgi(acao_id, form, usuario_id, usuario_nome):
    resultado = _valor(form, "resultado")
    if resultado not in ("C", "NC"):
        raise ValueError("Informe o resultado da segunda verificacao.")
    repo.confirmar_reposicao(acao_id, resultado, _valor(form, "observacao"), usuario_id, usuario_nome)
    repo.registrar_evento("NC", int(form["nc_id"]), "Segunda verificacao de reposicao",
                          resultado, usuario_id, usuario_nome)


def decidir_nc_critica(nc_id, form, usuario_id, usuario_nome):
    nc = repo.buscar_nc(nc_id)
    if not nc or nc["criticidade"] != "CRITICA":
        raise ValueError("NC critica nao encontrada.")
    decisao = _valor(form, "decisao")
    justificativa = _valor(form, "justificativa")
    if decisao not in ("Autorizar interrupcao", "Recusar interrupcao") or not justificativa:
        raise ValueError("Informe a decisao da Gerencia e a justificativa.")
    repo.decidir_criticidade(nc_id, decisao, justificativa, usuario_id, usuario_nome)
    repo.registrar_evento("NC", nc_id, "Decisao da Gerencia", decisao,
                          usuario_id, usuario_nome, justificativa)


def validar_eficacia_sgi(nc_id, form, usuario_id, usuario_nome):
    resultado = _valor(form, "resultado")
    observacao = _valor(form, "observacao")
    if resultado not in ("Eficaz", "Ineficaz") or not observacao:
        raise ValueError("Informe o resultado e a observacao da eficacia.")
    repo.validar_eficacia(nc_id, resultado, observacao, usuario_id, usuario_nome)
    repo.registrar_evento("NC", nc_id, "Eficacia validada", resultado,
                          usuario_id, usuario_nome, observacao)


def encerrar_nc_sgi(nc_id, usuario_id, usuario_nome):
    nc = repo.buscar_nc(nc_id)
    if not nc or nc["eficacia_resultado"] != "Eficaz":
        raise ValueError("A NC somente pode ser encerrada apos eficacia validada.")
    repo.encerrar_nc(nc_id, usuario_id, usuario_nome)
    repo.registrar_evento("NC", nc_id, "NC encerrada", "Encerramento definitivo",
                          usuario_id, usuario_nome)


def contexto_consolidado(args):
    filtros = {
        "mes": args.get("mes") or datetime.now().strftime("%Y-%m"),
        "formulario_tipo": args.get("formulario_tipo") or "Todos",
        "setor_id": args.get("setor_id") or "Todos",
        "setor": "Todos",
        "status": "Todos",
        "vinculo_tipo": args.get("vinculo_tipo") or "Todos",
        "local_id": args.get("ambiente_id") or args.get("estrutura_id") or "",
        "ambiente_id": args.get("ambiente_id") or "",
        "estrutura_id": args.get("estrutura_id") or "",
        "equipamento_id": args.get("equipamento_id") or "",
        "resultado": args.get("resultado") or "Todos",
    }
    verificacoes = []
    for resumo in repo.listar_verificacoes(filtros):
        verificacao, itens, ncs, _, _ = repo.buscar_verificacao(resumo["id"])
        verificacoes.append({"cabecalho": verificacao, "itens": itens, "ncs": ncs})
    return {"formularios": FORMULARIOS_PLM, "filtros": filtros, "verificacoes": verificacoes,
            "setores": repo.listar_setores(),
            "ambientes": repo.listar_locais("Ambiente"), "estruturas": repo.listar_locais("Estrutura"),
            "equipamentos": repo.listar_equipamentos()}
