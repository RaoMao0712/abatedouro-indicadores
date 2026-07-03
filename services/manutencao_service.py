from datetime import datetime

from repositories import manutencao_repository as repo


TIPOS_MANUTENCAO = repo.TIPOS_MANUTENCAO
PRIORIDADES_MANUTENCAO = repo.PRIORIDADES_MANUTENCAO
STATUS_MANUTENCAO = repo.STATUS_MANUTENCAO
MOTIVOS_MANUTENCAO = ["Mecanica", "Eletrica", "Pneumatica", "Hidraulica", "Instrumentacao"]
MOTIVOS_OPERACIONAIS = ["Falta de materia-prima", "Falta de embalagem", "Setup", "Limpeza", "Espera", "Outros"]
TIPOS_RECURSO_ORDEM = ["Material", "Mao de obra externa"]
STATUS_RECURSO_ORDEM = ["Pendente", "Solicitado", "Comprado/Contratado", "Recebido", "Cancelado"]


def criar_tabelas_manutencao():
    return repo.criar_tabelas_manutencao()


def salvar_equipamento_manutencao(form):
    repo.inserir_equipamento(_dados_equipamento(form))


def atualizar_equipamento_manutencao(equipamento_id, form):
    equipamento_id = int(equipamento_id or 0)
    if not equipamento_id or not repo.buscar_equipamento_por_id(equipamento_id):
        raise ValueError("Equipamento nao encontrado.")

    dados = _dados_equipamento(form)
    equipamento_codigo = repo.buscar_equipamento_por_codigo(dados[0])
    if equipamento_codigo and int(equipamento_codigo["id"]) != equipamento_id:
        raise ValueError("Ja existe outro equipamento com este codigo.")

    repo.atualizar_equipamento(equipamento_id, dados)


def excluir_equipamento_manutencao(equipamento_id):
    equipamento_id = int(equipamento_id or 0)
    if not equipamento_id or not repo.buscar_equipamento_por_id(equipamento_id):
        raise ValueError("Equipamento nao encontrado.")

    if repo.contar_ordens_por_equipamento(equipamento_id) > 0:
        raise ValueError("Este equipamento possui ordens vinculadas. Altere o status para Inativo para preservar o historico.")

    repo.excluir_equipamento(equipamento_id)


def _dados_equipamento(form):
    codigo = (form.get("codigo") or "").strip()
    nome = (form.get("nome") or "").strip()
    setor = (form.get("setor") or "").strip()

    if not codigo or not nome or not setor:
        raise ValueError("Informe codigo, nome e setor do equipamento.")

    return (
        codigo,
        nome,
        setor,
        (form.get("fabricante") or "").strip(),
        (form.get("modelo") or "").strip(),
        (form.get("numero_serie") or "").strip(),
        form.get("criticidade") or "Media",
        form.get("status") or "Operacional",
        (form.get("observacoes") or "").strip(),
    )


def salvar_ordem_manutencao(form):
    equipamento_id = int(form.get("equipamento_id") or 0)
    descricao = (form.get("descricao") or "").strip()

    if not equipamento_id:
        raise ValueError("Selecione um equipamento.")

    if not descricao:
        raise ValueError("Descreva a ocorrencia ou servico solicitado.")

    if not repo.equipamento_existe(equipamento_id):
        raise ValueError("Equipamento nao encontrado.")

    return repo.inserir_ordem((
        equipamento_id,
        int(form.get("op_id") or 0) or None,
        int(form.get("parada_id") or 0) or None,
        form.get("tipo") or "Corretiva",
        form.get("prioridade") or "Media",
        "Aberta",
        form.get("data_abertura") or datetime.now().strftime("%Y-%m-%d"),
        form.get("hora_abertura") or datetime.now().strftime("%H:%M"),
        form.get("data_prevista") or "",
        (form.get("solicitante") or "").strip(),
        (form.get("responsavel") or "").strip(),
        descricao,
        (form.get("motivo_parada") or "").strip(),
        float(form.get("custo_estimado") or 0),
    ))


def atualizar_ordem_manutencao(ordem_id, form):
    ordem_atual = repo.buscar_ordem_por_id(ordem_id)
    status = form.get("status") or "Aberta"
    if status not in STATUS_MANUTENCAO:
        raise ValueError("Status de manutencao invalido.")

    data_conclusao = form.get("data_conclusao") or ""
    if status == "Concluida" and not data_conclusao:
        data_conclusao = datetime.now().strftime("%Y-%m-%d")

    hora_conclusao = form.get("hora_conclusao") or ""
    if status == "Concluida" and not hora_conclusao:
        hora_conclusao = datetime.now().strftime("%H:%M")

    horas_paradas = float(form.get("horas_paradas") or 0)
    if status == "Concluida" and ordem_atual and ordem_atual["parada_id"]:
        horas_calculadas = calcular_horas_indisponibilidade_ordem(ordem_atual, data_conclusao, hora_conclusao)
        if horas_calculadas > 0:
            horas_paradas = horas_calculadas

    repo.atualizar_ordem(ordem_id, (
        status,
        data_conclusao,
        (form.get("responsavel") or "").strip(),
        (form.get("diagnostico") or "").strip(),
        (form.get("solucao") or "").strip(),
        horas_paradas,
        float(form.get("custo_real") or 0),
        hora_conclusao,
        (form.get("pecas_utilizadas") or "").strip(),
        (form.get("observacoes_finais") or "").strip(),
    ))

    if status == "Concluida" and ordem_atual:
        repo.atualizar_status_equipamento(ordem_atual["equipamento_id"], "Operacional")
        if ordem_atual["parada_id"]:
            repo.encerrar_parada_por_ordem(ordem_atual["parada_id"], data_conclusao, hora_conclusao, horas_paradas)


def buscar_equipamentos_manutencao(busca=""):
    if busca:
        return repo.listar_equipamentos_filtrados(busca)
    return repo.listar_equipamentos()


def buscar_equipamento_manutencao_por_id(equipamento_id):
    return repo.buscar_equipamento_por_id(equipamento_id)


def buscar_ordens_manutencao(status_filtro="Todos", equipamento_id=""):
    return repo.listar_ordens(status_filtro, equipamento_id)


def salvar_recursos_ordem_manutencao(ordem_id, form):
    ordem_id = int(ordem_id or 0)
    if not ordem_id or not repo.buscar_ordem_por_id(ordem_id):
        raise ValueError("Ordem de manutencao nao encontrada.")

    recurso_ids = form.getlist("recurso_id[]")
    remover = form.getlist("remover[]")
    tipos = form.getlist("recurso_tipo[]")
    descricoes = form.getlist("recurso_descricao[]")
    quantidades = form.getlist("recurso_quantidade[]")
    unidades = form.getlist("recurso_unidade[]")
    fornecedores = form.getlist("recurso_fornecedor[]")
    valores = form.getlist("recurso_valor_estimado[]")
    status = form.getlist("recurso_status[]")
    observacoes = form.getlist("recurso_observacoes[]")

    total_linhas = max(
        len(recurso_ids),
        len(remover),
        len(tipos),
        len(descricoes),
        len(quantidades),
        len(unidades),
        len(fornecedores),
        len(valores),
        len(status),
        len(observacoes),
    )

    linhas = []
    for indice in range(total_linhas):
        tipo = _item_lista(tipos, indice) or "Material"
        if tipo not in TIPOS_RECURSO_ORDEM:
            raise ValueError("Tipo de recurso invalido.")

        status_linha = _item_lista(status, indice) or "Pendente"
        if status_linha not in STATUS_RECURSO_ORDEM:
            raise ValueError("Status de recurso invalido.")

        linhas.append({
            "id": _item_lista(recurso_ids, indice),
            "remover": _item_lista(remover, indice) or "Nao",
            "tipo": tipo,
            "descricao": _item_lista(descricoes, indice),
            "quantidade": _item_lista(quantidades, indice),
            "unidade": _item_lista(unidades, indice),
            "fornecedor": _item_lista(fornecedores, indice),
            "valor_estimado": _item_lista(valores, indice),
            "status": status_linha,
            "observacoes": _item_lista(observacoes, indice),
        })

    repo.salvar_recursos_ordem(ordem_id, linhas)


def _item_lista(lista, indice):
    if indice < len(lista):
        return lista[indice]
    return ""


def calcular_resumo_manutencao(equipamentos, ordens):
    abertas = sum(1 for item in ordens if item["status"] == "Aberta")
    andamento = sum(1 for item in ordens if item["status"] == "Em andamento")
    aguardando = sum(1 for item in ordens if item["status"] == "Aguardando peca")
    concluidas = sum(1 for item in ordens if item["status"] == "Concluida")
    criticas = sum(1 for item in ordens if item["prioridade"] == "Critica" and item["status"] not in ["Concluida", "Cancelada"])
    horas_paradas = sum(float(item["horas_paradas"] or 0) for item in ordens)
    custo_real = sum(float(item["custo_real"] or 0) for item in ordens)

    return {
        "equipamentos": len(equipamentos),
        "abertas": abertas,
        "andamento": andamento,
        "aguardando": aguardando,
        "concluidas": concluidas,
        "criticas": criticas,
        "horas_paradas": round(horas_paradas, 2),
        "custo_real": round(custo_real, 2),
    }


def preparar_contexto_cadastro_equipamentos(args=None):
    args = args or {}
    busca = (args.get("busca") or "").strip()
    return {
        "equipamentos": buscar_equipamentos_manutencao(busca),
        "prioridades": PRIORIDADES_MANUTENCAO,
        "busca": busca,
    }


def preparar_contexto_manutencao(args):
    status_filtro = args.get("status") or "Todos"
    equipamento_filtro = args.get("equipamento_id") or ""
    equipamentos = buscar_equipamentos_manutencao()
    ordens = buscar_ordens_manutencao(status_filtro, equipamento_filtro)
    recursos_por_ordem = repo.listar_recursos_por_ordens([item["id"] for item in ordens])
    return {
        "equipamentos": equipamentos,
        "ordens": ordens,
        "recursos_por_ordem": recursos_por_ordem,
        "resumo": calcular_resumo_manutencao(equipamentos, ordens),
        "tipos": TIPOS_MANUTENCAO,
        "prioridades": PRIORIDADES_MANUTENCAO,
        "status_opcoes": STATUS_MANUTENCAO,
        "tipos_recurso": TIPOS_RECURSO_ORDEM,
        "status_recurso": STATUS_RECURSO_ORDEM,
        "status_filtro": status_filtro,
        "equipamento_filtro": equipamento_filtro,
        "hoje": datetime.now().strftime("%Y-%m-%d"),
    }


def calcular_horas_indisponibilidade(data_inicio, hora_inicio, data_fim, hora_fim):
    if not data_inicio or not hora_inicio or not data_fim or not hora_fim:
        return 0
    try:
        inicio = datetime.strptime(f"{data_inicio} {hora_inicio}", "%Y-%m-%d %H:%M")
        fim = datetime.strptime(f"{data_fim} {hora_fim}", "%Y-%m-%d %H:%M")
    except ValueError:
        return 0
    if fim <= inicio:
        return 0
    return round((fim - inicio).total_seconds() / 3600, 2)


def calcular_horas_indisponibilidade_ordem(ordem, data_fim, hora_fim):
    return calcular_horas_indisponibilidade(
        ordem["data_abertura"],
        ordem["hora_abertura"],
        data_fim,
        hora_fim,
    )


def criar_ordem_por_parada(parada_id, op_id, equipamento_id, setor, motivo, data, hora_inicio, usuario, observacoes):
    equipamento = buscar_equipamento_manutencao_por_id(equipamento_id)
    if not equipamento:
        raise ValueError("Equipamento nao encontrado.")

    form = {
        "equipamento_id": str(equipamento_id),
        "op_id": str(op_id),
        "parada_id": str(parada_id),
        "tipo": "Corretiva",
        "prioridade": "Alta",
        "data_abertura": data,
        "hora_abertura": hora_inicio,
        "solicitante": usuario or "",
        "responsavel": "",
        "descricao": f"Parada de producao - {motivo}. Setor: {setor}. {observacoes or ''}".strip(),
        "motivo_parada": motivo,
        "custo_estimado": "0",
    }
    ordem_id = salvar_ordem_manutencao(form)
    repo.vincular_ordem_a_parada(parada_id, ordem_id)
    return ordem_id
