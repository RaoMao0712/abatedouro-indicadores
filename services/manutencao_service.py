from datetime import datetime, timedelta

from repositories import manutencao_repository as repo


TIPOS_MANUTENCAO = repo.TIPOS_MANUTENCAO
PRIORIDADES_MANUTENCAO = repo.PRIORIDADES_MANUTENCAO
STATUS_MANUTENCAO = repo.STATUS_MANUTENCAO
TIPOS_OBJETO_MANUTENCAO = repo.TIPOS_OBJETO_MANUTENCAO
CATEGORIAS_PREDIAIS = repo.CATEGORIAS_PREDIAIS
LOCAIS_PREDIAIS = repo.LOCAIS_PREDIAIS
TIPOS_VEICULO = repo.TIPOS_VEICULO
MOTIVOS_MANUTENCAO = ["Mecanica", "Eletrica", "Pneumatica", "Hidraulica", "Instrumentacao"]
MOTIVOS_OPERACIONAIS = ["Falta de materia-prima", "Falta de embalagem", "Setup", "Limpeza", "Espera", "Outros"]
TIPOS_RECURSO_ORDEM = ["Material", "Servico", "Outra aquisicao", "Mao de obra externa"]
STATUS_RECURSO_ORDEM = repo.STATUS_RECURSO_ORDEM
PERFIS_ABERTURA_OS = ("qualidade", "producao", "pcp", "manutencao", "gerencia")
PERFIS_TECNICOS_OS = ("manutencao", "gerencia", "admin")
PERFIS_MATERIAIS_OS = ("qualidade", "pcp", "manutencao", "gerencia", "admin")
PERFIS_CANCELAMENTO_OS = ("manutencao", "gerencia", "admin")


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


def salvar_veiculo_manutencao(form):
    dados = _dados_veiculo(form)
    _validar_codigo_placa_veiculo(dados[0], dados[2])
    repo.inserir_veiculo(dados)


def atualizar_veiculo_manutencao(veiculo_id, form):
    veiculo_id = int(veiculo_id or 0)
    if not veiculo_id or not repo.buscar_veiculo_por_id(veiculo_id):
        raise ValueError("Veiculo nao encontrado.")

    dados = _dados_veiculo(form)
    _validar_codigo_placa_veiculo(dados[0], dados[2], veiculo_id)
    repo.atualizar_veiculo(veiculo_id, dados)


def inativar_veiculo_manutencao(veiculo_id):
    veiculo_id = int(veiculo_id or 0)
    if not veiculo_id or not repo.buscar_veiculo_por_id(veiculo_id):
        raise ValueError("Veiculo nao encontrado.")
    repo.inativar_veiculo(veiculo_id)


def _validar_codigo_placa_veiculo(codigo, placa, veiculo_id=None):
    veiculo_codigo = repo.buscar_veiculo_por_codigo(codigo)
    if veiculo_codigo and int(veiculo_codigo["id"]) != int(veiculo_id or 0):
        raise ValueError("Ja existe outro veiculo com este codigo interno.")

    if placa:
        veiculo_placa = repo.buscar_veiculo_por_placa(placa)
        if veiculo_placa and int(veiculo_placa["id"]) != int(veiculo_id or 0):
            raise ValueError("Ja existe outro veiculo com esta placa.")


def _dados_veiculo(form):
    codigo = (form.get("codigo") or "").strip()
    identificacao = (form.get("identificacao") or "").strip()
    placa = (form.get("placa") or "").strip().upper()
    tipo = form.get("tipo") or ""
    tipo_outro = (form.get("tipo_outro") or "").strip()

    if not codigo or not identificacao:
        raise ValueError("Informe codigo interno e identificacao do veiculo.")

    if tipo and tipo not in TIPOS_VEICULO:
        raise ValueError("Tipo de veiculo invalido.")

    if tipo == "Outro" and not tipo_outro:
        raise ValueError("Informe a descricao complementar quando o tipo for Outro.")

    ano = int(form.get("ano") or 0) or None
    status = form.get("status") or "Ativo"
    if status not in ("Ativo", "Inativo"):
        raise ValueError("Status de veiculo invalido.")

    return (
        codigo,
        identificacao,
        placa or None,
        tipo,
        tipo_outro,
        (form.get("marca") or "").strip(),
        (form.get("modelo") or "").strip(),
        ano,
        (form.get("finalidade") or "").strip(),
        (form.get("setor_responsavel") or "").strip(),
        status,
        (form.get("observacoes") or "").strip(),
    )


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


def salvar_ordem_manutencao(form, usuario_id=0, usuario_nome="", usuario_perfil=""):
    tipo_objeto = form.get("tipo_objeto") or "EQUIPAMENTO"
    descricao = (form.get("descricao") or "").strip()

    if tipo_objeto not in TIPOS_OBJETO_MANUTENCAO:
        raise ValueError("Selecione o tipo de manutencao.")

    if not descricao:
        raise ValueError("Descreva a ocorrencia ou servico solicitado.")

    equipamento_id = 0
    veiculo_id = None
    categoria_predial = None
    local_predial = None
    local_predial_descricao = None

    if tipo_objeto == "EQUIPAMENTO":
        equipamento_id = int(form.get("equipamento_id") or 0)
        if not equipamento_id:
            raise ValueError("Selecione o equipamento.")
        if not repo.equipamento_ativo(equipamento_id):
            raise ValueError("Equipamento inexistente ou inativo.")

    if tipo_objeto == "VEICULO":
        veiculo_id = int(form.get("veiculo_id") or 0)
        if not repo.listar_veiculos_ativos():
            raise ValueError("Nenhum veiculo ativo cadastrado.")
        if not veiculo_id:
            raise ValueError("Selecione o veiculo.")
        if not repo.veiculo_ativo(veiculo_id):
            raise ValueError("Veiculo inexistente ou inativo.")

    if tipo_objeto == "PREDIAL":
        categoria_predial = form.get("categoria_predial") or ""
        local_predial = form.get("local_predial") or ""
        categorias_validas = {codigo for codigo, _rotulo in CATEGORIAS_PREDIAIS}
        if categoria_predial not in categorias_validas:
            raise ValueError("Selecione a categoria da manutencao predial.")
        if local_predial not in LOCAIS_PREDIAIS:
            raise ValueError("Selecione o local da manutencao.")
        if local_predial == "Outros":
            local_predial_descricao = (form.get("local_predial_descricao") or "").strip()
            if not local_predial_descricao:
                raise ValueError("Informe o local quando a opcao 'Outros' for selecionada.")

    solicitante = (usuario_nome or form.get("solicitante") or "").strip()

    linhas_recursos = coletar_linhas_recursos_ordem(form)
    custo_estimado_form = float(form.get("custo_estimado") or 0)
    custo_estimado_recursos = somar_valor_estimado_recursos(linhas_recursos)
    custo_estimado = custo_estimado_recursos if custo_estimado_recursos > 0 else custo_estimado_form

    return repo.inserir_ordem_com_recursos((
        tipo_objeto,
        equipamento_id,
        veiculo_id,
        categoria_predial,
        local_predial,
        local_predial_descricao,
        int(form.get("op_id") or 0) or None,
        int(form.get("parada_id") or 0) or None,
        form.get("tipo") or "Corretiva",
        form.get("prioridade") or "Media",
        "Aberta",
        form.get("data_abertura") or datetime.now().strftime("%Y-%m-%d"),
        form.get("hora_abertura") or datetime.now().strftime("%H:%M"),
        form.get("data_prevista") or "",
        solicitante,
        int(usuario_id or form.get("usuario_id") or 0) or None,
        usuario_perfil or form.get("solicitante_perfil") or "",
        (form.get("responsavel") or "").strip(),
        descricao,
        (form.get("motivo_parada") or "").strip(),
        custo_estimado,
    ), linhas_recursos, usuario_id, usuario_nome)


def atualizar_ordem_manutencao(ordem_id, form, usuario_id=0, usuario_nome="Sistema", usuario_perfil=""):
    if usuario_perfil and usuario_perfil not in PERFIS_TECNICOS_OS:
        raise PermissionError("Perfil sem permissao para encerramento tecnico da OS.")

    dados, ordem_atual, status, data_conclusao, hora_conclusao, horas_paradas = preparar_atualizacao_ordem_manutencao(
        ordem_id, form)
    repo.atualizar_ordem(ordem_id, dados)
    aplicar_pos_atualizacao_ordem(ordem_id, ordem_atual, status, data_conclusao, hora_conclusao, horas_paradas, usuario_id, usuario_nome)


def preparar_atualizacao_ordem_manutencao(ordem_id, form):
    ordem_atual = repo.buscar_ordem_por_id(ordem_id)
    if ordem_atual and ordem_atual["status"] == "Cancelada":
        raise ValueError("OS cancelada nao pode ser executada ou editada operacionalmente.")

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

    dados = (
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
    )
    return dados, ordem_atual, status, data_conclusao, hora_conclusao, horas_paradas


def aplicar_pos_atualizacao_ordem(ordem_id, ordem_atual, status, data_conclusao, hora_conclusao, horas_paradas, usuario_id, usuario_nome):
    if status == "Concluida" and ordem_atual:
        if ordem_atual["tipo_objeto"] == "EQUIPAMENTO" and ordem_atual["equipamento_id"]:
            repo.atualizar_status_equipamento(ordem_atual["equipamento_id"], "Operacional")
        if ordem_atual["parada_id"]:
            repo.encerrar_parada_por_ordem(ordem_atual["parada_id"], data_conclusao, hora_conclusao, horas_paradas)
        if ordem_atual["sgi_nc_id"]:
            from modules.qualidade import repositories as qualidade_repo
            qualidade_repo.marcar_nc_aguardando_validacao(ordem_atual["sgi_nc_id"])
            qualidade_repo.registrar_evento(
                "NC", ordem_atual["sgi_nc_id"], "OS concluida",
                f"OS #{ordem_id} concluida; aguardando validacao da Qualidade.",
                usuario_id, usuario_nome)


def salvar_ficha_ordem_manutencao(ordem_id, form, usuario_id=0, usuario_nome="Sistema", usuario_perfil=""):
    ordem = repo.buscar_ordem_por_id(ordem_id)
    if not ordem:
        raise ValueError("Ordem de manutencao nao encontrada.")
    if ordem["status"] == "Cancelada":
        raise ValueError("OS cancelada nao pode ser editada.")

    perfil = usuario_perfil or ""
    if perfil in PERFIS_TECNICOS_OS:
        dados, ordem_atual, status, data_conclusao, hora_conclusao, horas_paradas = preparar_atualizacao_ordem_manutencao(
            ordem_id, form)
        linhas = coletar_linhas_recursos_ordem(form) if perfil in PERFIS_MATERIAIS_OS else []
        repo.atualizar_ordem_com_recursos(ordem_id, dados, linhas, usuario_id, usuario_nome)
        aplicar_pos_atualizacao_ordem(
            ordem_id, ordem_atual, status, data_conclusao, hora_conclusao, horas_paradas, usuario_id, usuario_nome)
    elif perfil not in PERFIS_MATERIAIS_OS:
        raise PermissionError("Perfil sem permissao para editar a OS.")
    else:
        salvar_recursos_ordem_manutencao(ordem_id, form, perfil, usuario_id, usuario_nome)


def usuario_pode_editar_materiais(perfil):
    return perfil in PERFIS_MATERIAIS_OS


def usuario_pode_cancelar_os(perfil):
    return perfil in PERFIS_CANCELAMENTO_OS


def buscar_equipamentos_manutencao(busca=""):
    if busca:
        return repo.listar_equipamentos_filtrados(busca)
    return repo.listar_equipamentos()


def buscar_equipamentos_ativos_manutencao():
    return repo.listar_equipamentos_ativos()


def buscar_equipamento_manutencao_por_id(equipamento_id):
    return repo.buscar_equipamento_por_id(equipamento_id)


def buscar_veiculos_manutencao(busca=""):
    return repo.listar_veiculos(busca)


def buscar_veiculos_ativos_manutencao():
    return repo.listar_veiculos_ativos()


def buscar_ordens_manutencao(
    status_filtro="Todos",
    equipamento_id="",
    tipo_objeto="Todos",
    veiculo_id="",
    setor="",
    responsavel="",
    prioridade="Todos",
    pesquisa="",
):
    return repo.listar_ordens(
        status_filtro, equipamento_id, tipo_objeto, veiculo_id,
        setor, responsavel, prioridade, pesquisa)


def salvar_recursos_ordem_manutencao(ordem_id, form, usuario_perfil="", usuario_id=0, usuario_nome="Sistema"):
    if usuario_perfil and usuario_perfil not in PERFIS_MATERIAIS_OS:
        raise PermissionError("Perfil sem permissao para lancar recursos da OS.")
    ordem_id = int(ordem_id or 0)
    ordem = repo.buscar_ordem_por_id(ordem_id)
    if not ordem_id or not ordem:
        raise ValueError("Ordem de manutencao nao encontrada.")
    if ordem["status"] == "Cancelada":
        raise ValueError("OS cancelada nao pode receber alteracao de materiais.")

    linhas = coletar_linhas_recursos_ordem(form)
    repo.salvar_recursos_ordem(ordem_id, linhas, usuario_id, usuario_nome)


def coletar_linhas_recursos_ordem(form):
    recurso_ids = _getlist_form(form, "recurso_id[]")
    remover = _getlist_form(form, "remover[]")
    tipos = _getlist_form(form, "recurso_tipo[]")
    descricoes = _getlist_form(form, "recurso_descricao[]")
    insumos = _getlist_form(form, "recurso_insumo_id[]")
    complementos = _getlist_form(form, "recurso_descricao_complementar[]")
    quantidades = _getlist_form(form, "recurso_quantidade[]")
    unidades = _getlist_form(form, "recurso_unidade[]")
    fornecedores = _getlist_form(form, "recurso_fornecedor[]")
    valores = _getlist_form(form, "recurso_valor_estimado[]")
    status = _getlist_form(form, "recurso_status[]")
    observacoes = _getlist_form(form, "recurso_observacoes[]")

    total_linhas = max(
        len(recurso_ids),
        len(remover),
        len(tipos),
        len(descricoes),
        len(insumos),
        len(complementos),
        len(quantidades),
        len(unidades),
        len(fornecedores),
        len(valores),
        len(status),
        len(observacoes),
    )

    linhas = []
    for indice in range(total_linhas):
        removida = _item_lista(remover, indice) == "Sim"
        tipo = _item_lista(tipos, indice) or "Material"
        if tipo not in TIPOS_RECURSO_ORDEM:
            raise ValueError("Tipo de recurso invalido.")

        status_linha = _item_lista(status, indice) or "Necessario"
        if status_linha not in STATUS_RECURSO_ORDEM:
            raise ValueError("Status de recurso invalido.")

        descricao = _item_lista(descricoes, indice)
        quantidade = float(_item_lista(quantidades, indice) or 0)
        valor_estimado = float(_item_lista(valores, indice) or 0)
        if quantidade < 0:
            raise ValueError("Quantidade do material nao pode ser negativa.")
        if valor_estimado < 0:
            raise ValueError("Valor estimado do material nao pode ser negativo.")

        tem_conteudo = any([
            descricao,
            _item_lista(insumos, indice),
            _item_lista(complementos, indice),
            quantidade,
            _item_lista(unidades, indice),
            _item_lista(fornecedores, indice),
            valor_estimado,
            _item_lista(observacoes, indice),
        ])
        if not tem_conteudo and not _item_lista(recurso_ids, indice):
            continue
        if not removida and not descricao:
            raise ValueError("Informe a descricao do material, servico ou aquisicao.")
        if not removida and quantidade <= 0:
            raise ValueError("Informe a quantidade do material ou servico.")

        linhas.append({
            "id": _item_lista(recurso_ids, indice),
            "remover": "Sim" if removida else "Nao",
            "tipo": tipo,
            "descricao": descricao,
            "insumo_id": _item_lista(insumos, indice),
            "descricao_complementar": _item_lista(complementos, indice),
            "quantidade": quantidade,
            "unidade": _item_lista(unidades, indice),
            "fornecedor": _item_lista(fornecedores, indice),
            "valor_estimado": valor_estimado,
            "status": status_linha,
            "observacoes": _item_lista(observacoes, indice),
        })

    return linhas


def somar_valor_estimado_recursos(linhas):
    return sum(float(linha.get("valor_estimado") or 0) for linha in linhas if linha.get("remover") != "Sim")


def _getlist_form(form, chave):
    if hasattr(form, "getlist"):
        return form.getlist(chave)
    valor = form.get(chave, []) if hasattr(form, "get") else []
    if isinstance(valor, (list, tuple)):
        return list(valor)
    if valor in (None, ""):
        return []
    return [valor]


def cancelar_ordem_manutencao(ordem_id, motivo, usuario_id=0, usuario_nome="Sistema", usuario_perfil=""):
    if usuario_perfil and usuario_perfil not in PERFIS_CANCELAMENTO_OS:
        raise PermissionError("Perfil sem permissao para cancelar OS.")

    ordem_id = int(ordem_id or 0)
    ordem = repo.buscar_ordem_por_id(ordem_id)
    if not ordem:
        raise ValueError("Ordem de manutencao nao encontrada.")

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Informe o motivo da exclusao/cancelamento.")

    if not ordem_elegivel_cancelamento(ordem):
        raise ValueError("Esta OS possui execucao, apontamento ou vinculo que exige preservacao operacional.")

    repo.cancelar_ordem(ordem_id, motivo, int(usuario_id or 0), usuario_nome or "Sistema")
    if ordem["tipo_objeto"] == "EQUIPAMENTO" and ordem["equipamento_id"]:
        repo.atualizar_status_equipamento(ordem["equipamento_id"], "Operacional")


def ordem_elegivel_cancelamento(ordem):
    if ordem["status"] != "Aberta":
        return False
    if float(ordem["horas_paradas"] or 0) > 0 or float(ordem["custo_real"] or 0) > 0:
        return False
    campos_tecnicos = [
        "diagnostico", "solucao", "hora_conclusao", "pecas_utilizadas",
        "observacoes_finais", "data_conclusao", "parada_id", "sgi_nc_id",
    ]
    return not any(ordem[campo] for campo in campos_tecnicos if campo in ordem.keys())


def _item_lista(lista, indice):
    if indice < len(lista):
        return lista[indice]
    return ""


def calcular_resumo_manutencao(equipamentos, ordens, veiculos=None):
    abertas = sum(1 for item in ordens if item["status"] == "Aberta")
    andamento = sum(1 for item in ordens if item["status"] == "Em andamento")
    aguardando = sum(1 for item in ordens if item["status"] == "Aguardando peca")
    concluidas = sum(1 for item in ordens if item["status"] == "Concluida")
    criticas = sum(1 for item in ordens if item["prioridade"] == "Critica" and item["status"] not in ["Concluida", "Cancelada"])
    operacionais = [item for item in ordens if item["status"] != "Cancelada"]
    horas_paradas = sum(float(item["horas_paradas"] or 0) for item in operacionais)
    custo_real = sum(float(item["custo_real"] or 0) for item in operacionais)

    return {
        "equipamentos": len(equipamentos),
        "veiculos": len(veiculos or []),
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


def filtros_busca_aplicados(args):
    campos = ["status", "equipamento_id", "tipo_objeto", "veiculo_id", "setor", "responsavel", "prioridade", "pesquisa"]
    for campo in campos:
        valor = (args.get(campo) or "").strip()
        if valor and valor != "Todos":
            return True
    return False


def _data(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def calcular_graficos_manutencao(ordens):
    hoje = datetime.now().date()
    limite_proximo = hoje + timedelta(days=3)

    situacao = {
        "Aberta": 0,
        "Em andamento": 0,
        "Aguardando material": 0,
        "Concluida": 0,
    }
    prioridade = {"Baixa": 0, "Media": 0, "Alta": 0, "Critica": 0}
    prazo = {"No prazo": 0, "Proximas do vencimento": 0, "Atrasadas": 0}

    for ordem in ordens:
        status = ordem["status"]
        if status in situacao:
            situacao[status] += 1

        if status not in ("Concluida", "Cancelada"):
            prio = ordem["prioridade"] or "Media"
            if prio in prioridade:
                prioridade[prio] += 1

            data_prevista = _data(ordem["data_prevista"])
            if data_prevista:
                if data_prevista < hoje:
                    prazo["Atrasadas"] += 1
                elif data_prevista <= limite_proximo:
                    prazo["Proximas do vencimento"] += 1
                else:
                    prazo["No prazo"] += 1

    return {
        "situacao": situacao,
        "prioridade": prioridade,
        "prazo": prazo,
    }


def preparar_contexto_cadastro_veiculos(args=None):
    args = args or {}
    busca = (args.get("busca") or "").strip()
    return {
        "veiculos": buscar_veiculos_manutencao(busca),
        "tipos_veiculo": TIPOS_VEICULO,
        "busca": busca,
    }


def preparar_contexto_manutencao(args):
    aba = args.get("aba") or "visao"
    abas_validas = {"visao", "abrir", "buscar", "materiais"}
    if aba not in abas_validas:
        aba = "visao"

    status_filtro = args.get("status") or "Todos"
    equipamento_filtro = args.get("equipamento_id") or ""
    tipo_objeto_filtro = args.get("tipo_objeto") or "Todos"
    veiculo_filtro = args.get("veiculo_id") or ""
    setor_filtro = (args.get("setor") or "").strip()
    responsavel_filtro = (args.get("responsavel") or "").strip()
    prioridade_filtro = args.get("prioridade") or "Todos"
    pesquisa_filtro = (args.get("pesquisa") or "").strip()
    equipamentos = buscar_equipamentos_manutencao()
    equipamentos_ativos = buscar_equipamentos_ativos_manutencao()
    veiculos = buscar_veiculos_manutencao()
    veiculos_ativos = buscar_veiculos_ativos_manutencao()
    ordens_painel = buscar_ordens_manutencao()
    tem_busca = filtros_busca_aplicados(args)
    ordens = []
    if aba in ("buscar", "materiais") and tem_busca:
        ordens = buscar_ordens_manutencao(
            status_filtro, equipamento_filtro, tipo_objeto_filtro, veiculo_filtro,
            setor_filtro, responsavel_filtro, prioridade_filtro, pesquisa_filtro)
    recursos_por_ordem = repo.listar_recursos_por_ordens([item["id"] for item in ordens])
    try:
        from modules.almoxarifado.services import buscar_insumos_almoxarifado
        insumos_manutencao = buscar_insumos_almoxarifado("Todas", "Sim", "")
    except Exception:
        insumos_manutencao = []
    return {
        "aba": aba,
        "equipamentos": equipamentos,
        "equipamentos_ativos": equipamentos_ativos,
        "veiculos": veiculos,
        "veiculos_ativos": veiculos_ativos,
        "ordens": ordens,
        "ordens_painel": ordens_painel,
        "recursos_por_ordem": recursos_por_ordem,
        "resumo": calcular_resumo_manutencao(equipamentos_ativos, ordens_painel, veiculos_ativos),
        "graficos": calcular_graficos_manutencao(ordens_painel),
        "tem_busca": tem_busca,
        "tipos": TIPOS_MANUTENCAO,
        "tipos_objeto": TIPOS_OBJETO_MANUTENCAO,
        "categorias_prediais": CATEGORIAS_PREDIAIS,
        "locais_prediais": LOCAIS_PREDIAIS,
        "prioridades": PRIORIDADES_MANUTENCAO,
        "status_opcoes": STATUS_MANUTENCAO,
        "tipos_recurso": TIPOS_RECURSO_ORDEM,
        "status_recurso": STATUS_RECURSO_ORDEM,
        "insumos_manutencao": insumos_manutencao,
        "perfis_materiais": PERFIS_MATERIAIS_OS,
        "perfis_cancelamento": PERFIS_CANCELAMENTO_OS,
        "status_filtro": status_filtro,
        "equipamento_filtro": equipamento_filtro,
        "tipo_objeto_filtro": tipo_objeto_filtro,
        "veiculo_filtro": veiculo_filtro,
        "setor_filtro": setor_filtro,
        "responsavel_filtro": responsavel_filtro,
        "prioridade_filtro": prioridade_filtro,
        "pesquisa_filtro": pesquisa_filtro,
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
        "tipo_objeto": "EQUIPAMENTO",
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


def criar_ordem_por_nc(nc, form, usuario):
    equipamento_id = int(form.get("equipamento_id") or nc["equipamento_id"] or 0)
    if not equipamento_id:
        raise ValueError("Selecione o equipamento aplicavel antes de abrir a OS.")
    dados = dict(form)
    dados.update({
        "equipamento_id": str(equipamento_id),
        "tipo_objeto": "EQUIPAMENTO",
        "tipo": form.get("tipo") or "Corretiva",
        "prioridade": {"NORMAL": "Media", "ALTA": "Alta", "CRITICA": "Critica"}.get(nc["criticidade"], "Media"),
        "solicitante": usuario,
        "descricao": form.get("descricao") or (
            f"Origem SGI - {nc['formulario_codigo']} {nc['formulario_nome']}. "
            f"Item: {nc['item_descricao']}. Setor: {nc['setor']}. "
            f"Ativo/local: {nc['ativo_nome']}. NC: {nc['descricao']}"
        ),
    })
    ordem_id = salvar_ordem_manutencao(dados, int(form.get("usuario_id") or 0), usuario, form.get("solicitante_perfil") or "")
    from modules.qualidade import repositories as qualidade_repo
    qualidade_repo.vincular_ordem(nc["id"], ordem_id)
    qualidade_repo.registrar_evento(
        "NC", nc["id"], "OS vinculada", f"Ordem de manutencao #{ordem_id} aberta.",
        int(form.get("usuario_id") or 0), usuario)
    return ordem_id
