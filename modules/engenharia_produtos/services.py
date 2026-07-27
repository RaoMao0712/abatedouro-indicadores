"""Regras de negócio da Engenharia de Produtos."""

from datetime import date

from modules.almoxarifado.services import buscar_insumos_almoxarifado

from . import repositories as repo


TIPOS_PRODUTO = {
    "PRODUTO_ACABADO": "Produto acabado",
    "PRODUTO_INTERMEDIARIO": "Produto intermediário",
    "MATERIA_PRIMA": "Matéria-prima",
    "SUBPRODUTO": "Subproduto",
    "OUTRO": "Outro",
}
TIPOS_CONSUMO = {
    "FIXO_UNIDADE": "Fixo por unidade produzida",
    "POR_KG": "Por quilograma produzido",
    "POR_CAIXA": "Por caixa produzida",
    "PROPORCIONAL": "Proporcional",
    "PERCENTUAL": "Percentual",
    "PERDA_ESPERADA": "Perda esperada",
    "OPCIONAL": "Opcional",
}
UNIDADES = ("Kg", "Un", "Cx", "L", "Ml", "G", "Pct")
STATUS_PRODUTO = {"Sim": "Ativo", "Não": "Inativo"}


def criar_tabelas_engenharia_produtos():
    repo.criar_estrutura()


def _texto(form, campo, obrigatorio=False):
    valor = (form.get(campo) or "").strip()
    if obrigatorio and not valor:
        raise ValueError(f"Informe {campo.replace('_', ' ')}.")
    return valor


def _numero(form, campo, obrigatorio=False, minimo=None, maximo=None):
    bruto = (form.get(campo) or "").strip().replace(",", ".")
    if not bruto:
        if obrigatorio:
            raise ValueError(f"Informe {campo.replace('_', ' ')}.")
        return None
    try:
        valor = float(bruto)
    except ValueError as exc:
        raise ValueError(f"{campo.replace('_', ' ').capitalize()} inválido.") from exc
    if minimo is not None and valor < minimo:
        raise ValueError(f"{campo.replace('_', ' ').capitalize()} deve ser no mínimo {minimo}.")
    if maximo is not None and valor > maximo:
        raise ValueError(f"{campo.replace('_', ' ').capitalize()} deve ser no máximo {maximo}.")
    return valor


def listar_catalogo(filtros=None):
    criar_tabelas_engenharia_produtos()
    return repo.listar_produtos(filtros), repo.resumo_catalogo()


def obter_produto(produto_id):
    criar_tabelas_engenharia_produtos()
    produto = repo.buscar_produto(produto_id)
    if not produto:
        raise ValueError("Produto não encontrado.")
    return produto


def salvar_produto(form, usuario, produto_id=None):
    criar_tabelas_engenharia_produtos()
    codigo = _texto(form, "codigo", True).upper()
    nome = _texto(form, "nome", True)
    tipo = _texto(form, "tipo_produto", True)
    unidade = _texto(form, "unidade_venda", True)
    ativo = _texto(form, "ativo") or "Sim"
    observacoes = _texto(form, "observacoes")
    if tipo not in TIPOS_PRODUTO:
        raise ValueError("Tipo de produto inválido.")
    if unidade not in UNIDADES:
        raise ValueError("Unidade de venda inválida.")
    if ativo not in STATUS_PRODUTO:
        raise ValueError("Status inválido.")
    if repo.buscar_produto_por_codigo(codigo, produto_id):
        raise ValueError("Já existe um produto com este código.")
    dados = (codigo, nome, tipo, unidade, ativo, observacoes)
    anterior = repo.buscar_produto(produto_id) if produto_id else None
    if produto_id:
        if not anterior:
            raise ValueError("Produto não encontrado.")
        repo.atualizar_produto(produto_id, dados)
        acao = "edicao"
    else:
        produto_id = repo.inserir_produto(dados)
        acao = "inclusao"
    novo = repo.buscar_produto(produto_id)
    repo.registrar_historico("produto", produto_id, acao, usuario["id"], usuario["nome"], anterior, novo)
    return produto_id


def alternar_status_produto(produto_id, usuario):
    produto = obter_produto(produto_id)
    novo_status = "Não" if produto["ativo"] == "Sim" else "Sim"
    repo.alterar_status_produto(produto_id, novo_status)
    novo = repo.buscar_produto(produto_id)
    repo.registrar_historico(
        "produto", produto_id, "inativacao" if novo_status == "Não" else "reativacao",
        usuario["id"], usuario["nome"], produto, novo,
    )
    return novo_status


def dados_detalhe(produto_id):
    produto = obter_produto(produto_id)
    return {
        "produto": produto,
        "itens": repo.listar_itens(produto_id),
        "historico": repo.listar_historico_produto(produto_id),
    }


def salvar_item_estrutura(form, usuario, produto_id, item_id=None):
    produto = obter_produto(produto_id)
    if produto["ativo"] != "Sim":
        raise ValueError("Reative o produto antes de alterar sua estrutura.")
    try:
        insumo_id = int(form.get("insumo_id") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Selecione um insumo válido.") from exc
    insumo = repo.buscar_insumo(insumo_id)
    if not insumo:
        raise ValueError("Insumo não encontrado.")
    if insumo["ativo"] != "Sim":
        raise ValueError("O insumo selecionado está inativo.")
    quantidade = _numero(form, "quantidade", True, minimo=0.000001)
    unidade = _texto(form, "unidade", True)
    tipo = _texto(form, "tipo_consumo", True)
    fator = _numero(form, "fator_proporcao", minimo=0)
    perda = _numero(form, "percentual_perda", minimo=0, maximo=100)
    observacoes = _texto(form, "observacoes")
    status = _texto(form, "status") or "Ativo"
    vigencia = _texto(form, "data_vigencia") or date.today().isoformat()
    if unidade not in UNIDADES:
        raise ValueError("Unidade inválida.")
    if tipo not in TIPOS_CONSUMO:
        raise ValueError("Tipo de consumo inválido.")
    if status not in {"Ativo", "Inativo"}:
        raise ValueError("Status inválido.")
    if tipo not in {"PROPORCIONAL", "PERCENTUAL"}:
        fator = None
    if tipo != "PERDA_ESPERADA":
        perda = None
    if repo.buscar_item_duplicado(produto_id, insumo_id, tipo, item_id):
        raise ValueError("Já existe um item ativo com este insumo e tipo de consumo.")

    responsavel = usuario["nome"]
    anterior = repo.buscar_item(item_id) if item_id else None
    if item_id:
        if not anterior or anterior["sku_id"] != produto_id:
            raise ValueError("Item da estrutura não encontrado.")
        repo.atualizar_item(
            item_id,
            (insumo_id, quantidade, unidade, tipo, fator, perda, observacoes, status, vigencia, responsavel),
        )
        acao = "edicao"
    else:
        item_id = repo.inserir_item(
            (produto_id, insumo_id, quantidade, unidade, tipo, fator, perda,
             observacoes, status, vigencia, responsavel),
        )
        acao = "inclusao"
    novo = repo.buscar_item(item_id)
    repo.registrar_historico("item_estrutura", item_id, acao, usuario["id"], usuario["nome"], anterior, novo)
    return item_id


def alternar_status_item(produto_id, item_id, usuario):
    obter_produto(produto_id)
    item = repo.buscar_item(item_id)
    if not item or item["sku_id"] != produto_id:
        raise ValueError("Item da estrutura não encontrado.")
    status = "Inativo" if item["status"] == "Ativo" else "Ativo"
    repo.alterar_status_item(item_id, status, usuario["nome"])
    novo = repo.buscar_item(item_id)
    repo.registrar_historico(
        "item_estrutura", item_id, "inativacao" if status == "Inativo" else "reativacao",
        usuario["id"], usuario["nome"], item, novo,
    )
    return status


def salvar_processo(form, usuario):
    criar_tabelas_engenharia_produtos()
    codigo = _texto(form, "codigo", True).upper()
    nome = _texto(form, "nome", True)
    descricao = _texto(form, "descricao")
    setor = _texto(form, "setor")
    status = _texto(form, "status") or "Ativo"
    observacoes = _texto(form, "observacoes")
    if status not in {"Ativo", "Inativo"}:
        raise ValueError("Status inválido.")
    if repo.buscar_processo_por_codigo(codigo):
        raise ValueError("Já existe um processo com este código.")
    processo_id = repo.inserir_processo((codigo, nome, descricao, setor, status, observacoes))
    repo.registrar_historico(
        "processo", processo_id, "inclusao", usuario["id"], usuario["nome"], None,
        {"codigo": codigo, "nome": nome, "descricao": descricao, "setor": setor,
         "status": status, "observacoes": observacoes},
    )
    return processo_id


def listar_processos():
    criar_tabelas_engenharia_produtos()
    return repo.listar_processos()


def insumos_ativos():
    criar_tabelas_engenharia_produtos()
    return buscar_insumos_almoxarifado("Todas", "Sim", "")
