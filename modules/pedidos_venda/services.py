"""Domínio transacional dos Pedidos de Venda Direta.

Valores financeiros são persistidos em centavos e quantidades em milésimos.
Assim, SQLite e PostgreSQL compartilham a mesma semântica exata.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re

from flask import has_request_context, session

from database import DATABASE_URL, conectar, q, transaction
from modules.clientes.services import snapshot_cliente


STATUS = {
    "RASCUNHO": "Rascunho",
    "CONFIRMADO": "Confirmado",
    "PARCIALMENTE_ATENDIDO": "Parcialmente atendido",
    "ATENDIDO": "Atendido",
    "CANCELADO": "Cancelado",
}
FORMAS_PAGAMENTO = ("PIX", "DINHEIRO", "TRANSFERENCIA_BANCARIA", "BOLETO", "CARTAO", "OUTRO")
CONDICOES_PAGAMENTO = ("A_VISTA", "PRAZO_UNICO", "PARCELADO", "ENTRADA_MAIS_SALDO", "OUTRO")
UNIDADES = ("KG", "CAIXA", "BANDEJA", "PACOTE", "UNIDADE", "GALINHA")
PERFIS_OPERACAO = {"admin", "gerencia", "pcp", "expedicao"}
PERFIS_GESTAO = {"admin", "gerencia"}
_SCHEMA_INICIALIZADO = False


def rotulo_unidade_comercial(sku, apresentacao, unidade):
    if str(sku or "").strip().upper() != "LEG-2" or str(unidade or "").strip().upper() != "PACOTE":
        return None
    apresentacao_normalizada = str(apresentacao or "").strip().casefold()
    if apresentacao_normalizada in {
        "pacote com 1 ave", "pacote com 2 aves",
        "pacote com 1 galinha inteira", "pacote com 2 galinhas inteiras",
    }:
        return "Ave"
    return None


def _opcao_comercial_ave(sku, apresentacao, unidade, opcoes):
    """Resolve no cadastro, nunca no formulário, a conversão comercial da LEG-2."""
    if str(sku or "").strip().upper() != "LEG-2" or str(unidade or "").strip().upper() != "PACOTE":
        return None
    apresentacao_normalizada = str(apresentacao or "").strip().casefold()
    opcao = next((item for item in opcoes
                  if str(item.get("valor") or "").strip().casefold() == apresentacao_normalizada
                  and item.get("unidade") == "PACOTE"), None)
    if not opcao or opcao.get("fator_aves") not in {1, 2}:
        raise ValueError("Apresentação da LEG-2 não possui conversão segura para aves.")
    return opcao


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _identidade(usuario=None, perfil=None):
    if has_request_context():
        usuario = usuario or session.get("nome")
        perfil = perfil or session.get("perfil")
    return usuario or "Sistema", (perfil or "sistema").lower()


def _alterar(cursor, postgres, sqlite):
    try:
        cursor.execute(postgres if DATABASE_URL else sqlite)
    except Exception:
        if DATABASE_URL:
            raise


def _decimal(valor, campo, *, positivo=False):
    texto = str(valor if valor is not None else "").strip()
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError) as erro:
        raise ValueError(f"{campo} inválido.") from erro
    if not numero.is_finite() or numero < 0 or (positivo and numero <= 0):
        regra = "maior que zero" if positivo else "não negativo"
        raise ValueError(f"{campo} deve ser {regra}.")
    return numero


def _centavos(valor, campo, *, positivo=False):
    numero = _decimal(valor, campo, positivo=positivo).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(numero * 100)


def _milesimos(valor, campo, *, positivo=False):
    numero = _decimal(valor, campo, positivo=positivo).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return int(numero * 1000)


def decimal_centavos(valor):
    return (Decimal(int(valor or 0)) / Decimal(100)).quantize(Decimal("0.01"))


def decimal_milesimos(valor):
    return (Decimal(int(valor or 0)) / Decimal(1000)).quantize(Decimal("0.001"))


def catalogo_produtos_venda(produtos):
    """Monta opções de venda usando cadastro e apresentações já vistas no estoque.

    Não cria um segundo cadastro comercial. Quando não há apresentação física
    conhecida, a unidade de venda do SKU fornece uma opção segura de fallback.
    """
    produtos = [dict(produto) for produto in produtos]
    apresentacoes_estoque = []
    conn = conectar()
    try:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("SELECT to_regclass('public.pa_caixas') AS tabela")
            existe = bool(cursor.fetchone()["tabela"])
        else:
            cursor.execute("SELECT name AS tabela FROM sqlite_master WHERE type='table' AND name='pa_caixas'")
            existe = bool(cursor.fetchone())
        if existe:
            cursor.execute("""SELECT DISTINCT sku,apresentacao,unidade_estoque,galinhas_por_pacote
                FROM pa_caixas WHERE apresentacao IS NOT NULL AND TRIM(apresentacao)<>''
                ORDER BY apresentacao""")
            apresentacoes_estoque = [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()

    mapa_unidades = {
        "KG": ("KG", "Quilograma"), "UN": ("UNIDADE", "Unidade"),
        "CX": ("CAIXA", "Caixa"), "PCT": ("PACOTE", "Pacote"),
    }
    catalogo = []
    for produto in produtos:
        unidade_cadastro = str(produto.get("unidade_venda") or "").upper()
        unidade_padrao = mapa_unidades.get(unidade_cadastro)
        if not unidade_padrao:
            continue
        codigo = str(produto.get("codigo") or "").strip()
        nome = str(produto.get("nome") or "").strip()
        chaves = {codigo.casefold(), nome.casefold()}
        opcoes = []
        for estoque in apresentacoes_estoque:
            if str(estoque.get("sku") or "").strip().casefold() not in chaves:
                continue
            unidade = str(estoque.get("unidade_estoque") or unidade_padrao[0]).upper()
            if unidade not in UNIDADES:
                unidade = unidade_padrao[0]
            fator = int(estoque.get("galinhas_por_pacote") or 0) or None
            valor = str(estoque["apresentacao"]).strip()
            rotulo = valor
            if unidade == "PACOTE" and fator:
                rotulo = f"Pacote com {fator} {'ave' if fator == 1 else 'aves'}"
            unidade_rotulo = rotulo_unidade_comercial(codigo, valor, unidade) or \
                mapa_unidades.get(unidade, (unidade, unidade.title()))[1]
            base_preco = "AVE" if rotulo_unidade_comercial(codigo, valor, unidade) else unidade
            opcoes.append({"valor": valor, "rotulo": rotulo, "unidade": unidade,
                           "unidade_rotulo": unidade_rotulo,
                           "fator_aves": fator, "base_preco": base_preco})
        if not opcoes:
            fator = None
            valor = unidade_padrao[1]
            rotulo = unidade_padrao[1]
            if unidade_padrao[0] == "PACOTE" and "galinha inteira" in nome.casefold():
                sufixo = re.search(r"(?:^|[-_ V])([12])$", codigo, re.IGNORECASE)
                fator = int(sufixo.group(1)) if sufixo else None
                if fator:
                    valor = f"Pacote com {fator} {'galinha inteira' if fator == 1 else 'galinhas inteiras'}"
                    rotulo = f"Pacote com {fator} {'ave' if fator == 1 else 'aves'}"
            unidade_rotulo = rotulo_unidade_comercial(codigo, valor, unidade_padrao[0]) or unidade_padrao[1]
            base_preco = "AVE" if rotulo_unidade_comercial(codigo, valor, unidade_padrao[0]) else unidade_padrao[0]
            opcoes.append({"valor": valor, "rotulo": rotulo, "unidade": unidade_padrao[0],
                           "unidade_rotulo": unidade_rotulo, "fator_aves": fator,
                           "base_preco": base_preco})
        unicas = []
        vistos = set()
        for opcao in opcoes:
            chave = (opcao["valor"].casefold(), opcao["unidade"])
            if chave not in vistos:
                vistos.add(chave)
                unicas.append(opcao)
        preferido = re.search(r"(?:^|[-_ V])([12])$", codigo, re.IGNORECASE)
        if preferido:
            fator_preferido = int(preferido.group(1))
            unicas.sort(key=lambda item: item.get("fator_aves") != fator_preferido)
        catalogo.append({"id": produto["id"], "codigo": codigo, "nome": nome,
                         "apresentacoes": unicas})
    return catalogo


def criar_tabelas_pedidos_venda():
    global _SCHEMA_INICIALIZADO
    if _SCHEMA_INICIALIZADO:
        return
    conn = conectar()
    cursor = conn.cursor()
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if DATABASE_URL else "TEXT"
    try:
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS pedidos_venda (
            id {pk}, numero TEXT UNIQUE NOT NULL, cliente_id INTEGER NOT NULL,
            cliente_snapshot TEXT NOT NULL, destino TEXT NOT NULL, data_pedido TEXT NOT NULL,
            previsao_entrega TEXT, responsavel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'RASCUNHO',
            subtotal_centavos BIGINT NOT NULL DEFAULT 0, desconto_centavos BIGINT NOT NULL DEFAULT 0,
            valor_total_centavos BIGINT NOT NULL DEFAULT 0, forma_pagamento TEXT NOT NULL,
            condicao_pagamento TEXT NOT NULL, vencimento_inicial TEXT, prazo_dias INTEGER,
            numero_parcelas INTEGER, intervalo_dias INTEGER, entrada_centavos BIGINT,
            entrada_percentual_milesimos INTEGER, condicao_saldo TEXT, descricao_condicao TEXT,
            observacoes TEXT, motivo_cancelamento TEXT, criado_por TEXT NOT NULL,
            atualizado_por TEXT NOT NULL, criado_em {ts} NOT NULL, atualizado_em {ts} NOT NULL,
            confirmado_em {ts}, cancelado_em {ts}, versao INTEGER NOT NULL DEFAULT 1
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS pedido_venda_itens (
            id {pk}, pedido_id INTEGER NOT NULL, produto_id INTEGER, sku TEXT NOT NULL,
            produto_snapshot TEXT NOT NULL, apresentacao_snapshot TEXT,
            quantidade_negociada_mil BIGINT NOT NULL, unidade_comercial TEXT NOT NULL,
            preco_unitario_centavos BIGINT NOT NULL, desconto_centavos BIGINT NOT NULL DEFAULT 0,
            valor_bruto_centavos BIGINT NOT NULL, valor_liquido_centavos BIGINT NOT NULL,
            quantidade_operacional_mil BIGINT, unidade_operacional TEXT,
            aves_por_unidade_operacional INTEGER, quantidade_comercial_mil BIGINT,
            base_preco TEXT, observacoes TEXT, criado_em {ts} NOT NULL
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS pedido_venda_romaneio_itens (
            id {pk}, pedido_id INTEGER NOT NULL, pedido_item_id INTEGER NOT NULL,
            expedicao_id INTEGER NOT NULL, quantidade_planejada_mil BIGINT NOT NULL,
            unidade TEXT NOT NULL, criado_por TEXT NOT NULL, criado_em {ts} NOT NULL,
            UNIQUE(pedido_item_id, expedicao_id)
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS pedido_venda_atendimentos (
            id {pk}, pedido_id INTEGER NOT NULL, pedido_item_id INTEGER NOT NULL,
            expedicao_id INTEGER NOT NULL, expedicao_item_id INTEGER NOT NULL UNIQUE,
            quantidade_atendida_mil BIGINT NOT NULL, unidade TEXT NOT NULL,
            peso_atendido_mil_kg BIGINT, status TEXT NOT NULL DEFAULT 'ENTREGUE',
            criado_por TEXT NOT NULL, criado_em {ts} NOT NULL, atualizado_em {ts} NOT NULL
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS pedido_venda_eventos (
            id {pk}, pedido_id INTEGER, acao TEXT NOT NULL, estado_anterior TEXT,
            estado_novo TEXT, dados_anteriores TEXT, dados_novos TEXT,
            usuario TEXT NOT NULL, perfil TEXT NOT NULL, justificativa TEXT,
            origem TEXT NOT NULL, criado_em {ts} NOT NULL, idempotency_key TEXT UNIQUE
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS pedido_venda_sequencias (
            data_documento TEXT PRIMARY KEY, ultimo INTEGER NOT NULL
        )""")
        _alterar(cursor, "ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS pedido_venda_id INTEGER",
                 "ALTER TABLE expedicoes ADD COLUMN pedido_venda_id INTEGER")
        _alterar(cursor, "ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS pedido_destino_entrega TEXT",
                 "ALTER TABLE expedicoes ADD COLUMN pedido_destino_entrega TEXT")
        _alterar(cursor, "ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS pedido_item_id INTEGER",
                 "ALTER TABLE expedicao_itens ADD COLUMN pedido_item_id INTEGER")
        for coluna, tipo in (
            ("quantidade_operacional_mil", "BIGINT"), ("unidade_operacional", "TEXT"),
            ("aves_por_unidade_operacional", "INTEGER"), ("quantidade_comercial_mil", "BIGINT"),
            ("base_preco", "TEXT"),
        ):
            _alterar(cursor, f"ALTER TABLE pedido_venda_itens ADD COLUMN IF NOT EXISTS {coluna} {tipo}",
                     f"ALTER TABLE pedido_venda_itens ADD COLUMN {coluna} {tipo}")
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_pedidos_venda_filtros ON pedidos_venda(status,data_pedido,cliente_id)",
            "CREATE INDEX IF NOT EXISTS idx_pedido_itens_pedido ON pedido_venda_itens(pedido_id)",
            "CREATE INDEX IF NOT EXISTS idx_pedido_planos_expedicao ON pedido_venda_romaneio_itens(expedicao_id)",
            "CREATE INDEX IF NOT EXISTS idx_pedido_atendimentos_item ON pedido_venda_atendimentos(pedido_item_id,status)",
            "CREATE INDEX IF NOT EXISTS idx_pedido_eventos_pedido ON pedido_venda_eventos(pedido_id,criado_em)",
            "CREATE INDEX IF NOT EXISTS idx_expedicoes_pedido ON expedicoes(pedido_venda_id,status)",
            "CREATE INDEX IF NOT EXISTS idx_expedicao_itens_pedido_item ON expedicao_itens(pedido_item_id)",
        ):
            cursor.execute(sql)
        conn.commit()
        _SCHEMA_INICIALIZADO = True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str) if valor is not None else None


def _evento(cursor, pedido_id, acao, antes=None, depois=None, *, justificativa=None,
            origem="pedidos_venda", idempotency_key=None, usuario=None, perfil=None):
    usuario, perfil = _identidade(usuario, perfil)
    params = (pedido_id, acao, antes.get("status") if antes else None,
              depois.get("status") if depois else None, _json(antes), _json(depois),
              usuario, perfil, justificativa, origem, _agora(), idempotency_key)
    if DATABASE_URL:
        cursor.execute(q("""INSERT INTO pedido_venda_eventos
            (pedido_id,acao,estado_anterior,estado_novo,dados_anteriores,dados_novos,
             usuario,perfil,justificativa,origem,criado_em,idempotency_key)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO NOTHING"""), params)
    else:
        cursor.execute(q("""INSERT OR IGNORE INTO pedido_venda_eventos
            (pedido_id,acao,estado_anterior,estado_novo,dados_anteriores,dados_novos,
             usuario,perfil,justificativa,origem,criado_em,idempotency_key)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""), params)


def _autorizar(cursor, pedido_id, perfis, acao, usuario, perfil):
    if perfil == "admin" or perfil in perfis:
        return
    _evento(cursor, pedido_id, "TENTATIVA_NEGADA", depois={"acao": acao}, usuario=usuario, perfil=perfil)
    # A tentativa negada é um evento autônomo: deve sobreviver ao rollback da
    # operação recusada. Este helper é sempre chamado antes de qualquer mutação.
    cursor.connection.commit()
    raise PermissionError("Perfil sem permissão para esta ação comercial.")


def _proximo_numero(cursor, data_pedido):
    if DATABASE_URL:
        cursor.execute(q("""INSERT INTO pedido_venda_sequencias(data_documento,ultimo) VALUES (?,1)
            ON CONFLICT(data_documento) DO UPDATE SET ultimo=pedido_venda_sequencias.ultimo+1
            RETURNING ultimo"""), (data_pedido,))
        sequencial = cursor.fetchone()["ultimo"]
    else:
        cursor.execute(q("SELECT ultimo FROM pedido_venda_sequencias WHERE data_documento=?"), (data_pedido,))
        linha = cursor.fetchone()
        sequencial = int(linha["ultimo"] or 0) + 1 if linha else 1
        if linha:
            cursor.execute(q("UPDATE pedido_venda_sequencias SET ultimo=? WHERE data_documento=?"),
                           (sequencial, data_pedido))
        else:
            cursor.execute(q("INSERT INTO pedido_venda_sequencias(data_documento,ultimo) VALUES (?,?)"),
                           (data_pedido, sequencial))
    return f"PV-{data_pedido.replace('-', '')}-{sequencial:03d}"


def _lista(form, chave):
    if hasattr(form, "getlist"):
        return form.getlist(chave)
    valor = form.get(chave, [])
    return valor if isinstance(valor, (list, tuple)) else [valor]


def _validar_data(valor, campo, obrigatoria=False):
    valor = str(valor or "").strip()
    if not valor and not obrigatoria:
        return None
    try:
        datetime.strptime(valor, "%Y-%m-%d")
    except ValueError as erro:
        raise ValueError(f"{campo} inválida.") from erro
    return valor


def _validar_pagamento(dados):
    if dados["forma_pagamento"] not in FORMAS_PAGAMENTO:
        raise ValueError("Forma de pagamento inválida ou ausente.")
    condicao = dados["condicao_pagamento"]
    if condicao not in CONDICOES_PAGAMENTO:
        raise ValueError("Condição de pagamento inválida ou ausente.")
    if condicao == "PRAZO_UNICO" and not (dados["vencimento_inicial"] or dados["prazo_dias"]):
        raise ValueError("Prazo único exige vencimento ou prazo em dias.")
    if condicao == "PARCELADO":
        if not dados["numero_parcelas"] or dados["numero_parcelas"] < 2:
            raise ValueError("Pagamento parcelado exige ao menos duas parcelas.")
        if not dados["vencimento_inicial"] or not dados["intervalo_dias"]:
            raise ValueError("Pagamento parcelado exige vencimento inicial e intervalo.")
    if condicao == "ENTRADA_MAIS_SALDO":
        if not (dados["entrada_centavos"] or dados["entrada_percentual_milesimos"]):
            raise ValueError("Entrada mais saldo exige valor ou percentual de entrada.")
        if not dados["condicao_saldo"]:
            raise ValueError("Informe a condição do saldo.")
        if (dados["entrada_percentual_milesimos"] or 0) > 100000:
            raise ValueError("Percentual de entrada não pode superar 100%.")
    if condicao == "OUTRO" and not dados["descricao_condicao"]:
        raise ValueError("Descreva a condição de pagamento.")


def _dados_form(form):
    from modules.clientes.services import buscar_cliente
    try:
        cliente_id = int(form.get("cliente_id") or 0)
    except (TypeError, ValueError):
        cliente_id = 0
    cliente = buscar_cliente(cliente_id) if cliente_id else None
    if not cliente or cliente["status"] != "Ativo":
        raise ValueError("Selecione um cliente ativo.")
    destino = str(form.get("destino") or "").strip()
    responsavel = str(form.get("responsavel") or "").strip()
    if not destino or not responsavel:
        raise ValueError("Destino e responsável são obrigatórios.")
    data_pedido = _validar_data(form.get("data_pedido"), "Data do pedido", True)
    cliente_snapshot = snapshot_cliente(cliente)
    if isinstance(cliente_snapshot, str):
        cliente_snapshot = json.loads(cliente_snapshot)
    dados = {
        "cliente_id": cliente_id, "cliente_snapshot": cliente_snapshot,
        "destino": destino, "data_pedido": data_pedido,
        "previsao_entrega": _validar_data(form.get("previsao_entrega"), "Previsão de entrega"),
        "responsavel": responsavel,
        "forma_pagamento": str(form.get("forma_pagamento") or "").upper(),
        "condicao_pagamento": str(form.get("condicao_pagamento") or "").upper(),
        "vencimento_inicial": _validar_data(form.get("vencimento_inicial"), "Vencimento inicial"),
        "prazo_dias": int(form.get("prazo_dias") or 0) or None,
        "numero_parcelas": int(form.get("numero_parcelas") or 0) or None,
        "intervalo_dias": int(form.get("intervalo_dias") or 0) or None,
        "entrada_centavos": _centavos(form.get("entrada_valor") or 0, "Valor de entrada") or None,
        "entrada_percentual_milesimos": _milesimos(form.get("entrada_percentual") or 0, "Percentual de entrada") or None,
        "condicao_saldo": str(form.get("condicao_saldo") or "").strip() or None,
        "descricao_condicao": str(form.get("descricao_condicao") or "").strip() or None,
        "observacoes": str(form.get("observacoes") or "").strip() or None,
    }
    for campo, rotulo in (("prazo_dias", "Prazo"), ("numero_parcelas", "Número de parcelas"),
                          ("intervalo_dias", "Intervalo entre parcelas")):
        if dados[campo] is not None and dados[campo] <= 0:
            raise ValueError(f"{rotulo} deve ser maior que zero.")
    _validar_pagamento(dados)
    produto_ids = _lista(form, "produto_id")
    skus = _lista(form, "sku")
    apresentacoes = _lista(form, "apresentacao")
    quantidades = _lista(form, "quantidade")
    unidades = _lista(form, "unidade")
    precos = _lista(form, "preco_unitario")
    descontos = _lista(form, "desconto_item")
    observacoes = _lista(form, "observacao_item")
    itens = []
    chaves_itens = set()
    total_linhas = max(len(skus), len(produto_ids), len(quantidades))
    if not total_linhas:
        raise ValueError("Inclua ao menos um item.")
    conn = conectar()
    try:
        cursor = conn.cursor()
        for indice in range(total_linhas):
            produto_id = int(produto_ids[indice] or 0) if indice < len(produto_ids) else 0
            sku = str(skus[indice] if indice < len(skus) else "").strip()
            produto = None
            if produto_id:
                cursor.execute(q("SELECT * FROM skus WHERE id=? AND ativo='Sim' AND excluido_em IS NULL"), (produto_id,))
                produto = cursor.fetchone()
                if not produto:
                    raise ValueError("Produto ativo não encontrado.")
                sku = produto["codigo"]
            if not sku:
                raise ValueError("Produto/SKU é obrigatório.")
            unidade = str(unidades[indice] if indice < len(unidades) else "").upper().strip()
            if unidade not in UNIDADES:
                raise ValueError(f"Unidade comercial inválida para {sku}.")
            apresentacao = str(apresentacoes[indice] if indice < len(apresentacoes) else "").strip() or None
            if produto:
                mapa = {"KG": "KG", "UN": "UNIDADE", "CX": "CAIXA", "PCT": "PACOTE"}
                unidade_catalogo = mapa.get(str(produto["unidade_venda"] or "").upper())
                catalogo_apresentacao = catalogo_produtos_venda([produto])
                opcoes_apresentacao = catalogo_apresentacao[0]["apresentacoes"] if catalogo_apresentacao else []
                unidade_da_apresentacao = any(
                    opcao["valor"].casefold() == (apresentacao or "").casefold()
                    and opcao["unidade"] == unidade
                    for opcao in opcoes_apresentacao
                )
                if unidade_catalogo and unidade != unidade_catalogo and not unidade_da_apresentacao:
                    raise ValueError(f"Unidade incompatível com o cadastro do produto {sku}.")
            else:
                opcoes_apresentacao = []
            chave_item = (sku.casefold(), (apresentacao or "").casefold(), unidade)
            if chave_item in chaves_itens:
                raise ValueError("Itens com mesmo SKU, apresentação e unidade devem ser consolidados.")
            chaves_itens.add(chave_item)
            qtd_mil = _milesimos(quantidades[indice] if indice < len(quantidades) else 0,
                                  f"Quantidade de {sku}", positivo=True)
            preco_cent = _centavos(precos[indice] if indice < len(precos) else 0,
                                    f"Preço de {sku}", positivo=True)
            desconto_cent = _centavos(descontos[indice] if indice < len(descontos) else 0,
                                       f"Desconto de {sku}")
            opcao_ave = _opcao_comercial_ave(sku, apresentacao, unidade, opcoes_apresentacao)
            fator_aves = int(opcao_ave["fator_aves"]) if opcao_ave else None
            quantidade_comercial_mil = qtd_mil * fator_aves if fator_aves else qtd_mil
            unidade_comercial = "AVE" if fator_aves else unidade
            base_preco = "AVE" if fator_aves else unidade_comercial
            bruto = int((Decimal(quantidade_comercial_mil) * Decimal(preco_cent) / Decimal(1000))
                        .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if desconto_cent > bruto:
                raise ValueError(f"Desconto de {sku} supera o valor bruto.")
            produto_snapshot = {"codigo": sku, "nome": produto["nome"] if produto else sku,
                                "unidade_venda": produto["unidade_venda"] if produto else unidade,
                                "unidade_operacional": unidade,
                                "quantidade_operacional_mil": qtd_mil,
                                "unidade_comercial": unidade_comercial,
                                "quantidade_comercial_mil": quantidade_comercial_mil,
                                "base_preco": base_preco}
            if fator_aves:
                produto_snapshot["aves_por_unidade_operacional"] = fator_aves
            unidade_rotulo = rotulo_unidade_comercial(sku, apresentacao, unidade)
            if unidade_rotulo:
                produto_snapshot["unidade_comercial_rotulo"] = unidade_rotulo
            itens.append({
                "produto_id": produto_id or None, "sku": sku,
                "produto_snapshot": produto_snapshot,
                "apresentacao_snapshot": apresentacao,
                # O campo legado permanece com a quantidade operacional para não alterar
                # saldos/romaneios históricos. Os novos campos tornam as duas dimensões explícitas.
                "quantidade_negociada_mil": qtd_mil, "unidade_comercial": unidade_comercial,
                "quantidade_operacional_mil": qtd_mil, "unidade_operacional": unidade,
                "aves_por_unidade_operacional": fator_aves,
                "quantidade_comercial_mil": quantidade_comercial_mil, "base_preco": base_preco,
                "preco_unitario_centavos": preco_cent, "desconto_centavos": desconto_cent,
                "valor_bruto_centavos": bruto, "valor_liquido_centavos": bruto - desconto_cent,
                "observacoes": str(observacoes[indice] if indice < len(observacoes) else "").strip() or None,
            })
    finally:
        conn.close()
    dados["itens"] = itens
    dados["subtotal_centavos"] = sum(i["valor_liquido_centavos"] for i in itens)
    dados["desconto_centavos"] = _centavos(form.get("desconto_geral") or 0, "Desconto geral")
    if dados["desconto_centavos"] > dados["subtotal_centavos"]:
        raise ValueError("Desconto geral supera o subtotal.")
    dados["valor_total_centavos"] = dados["subtotal_centavos"] - dados["desconto_centavos"]
    if (dados["entrada_centavos"] or 0) > dados["valor_total_centavos"]:
        raise ValueError("Valor de entrada supera o total do pedido.")
    total_navegador = form.get("valor_total")
    if total_navegador not in (None, "") and _centavos(total_navegador, "Valor total") != dados["valor_total_centavos"]:
        raise ValueError("Valor total divergente do cálculo do servidor.")
    return dados


def salvar_pedido(form, pedido_id=None, *, usuario=None, perfil=None):
    criar_tabelas_pedidos_venda()
    usuario, perfil = _identidade(usuario, perfil)
    dados = _dados_form(form)
    agora = _agora()
    with transaction() as conn:
        cursor = conn.cursor()
        _autorizar(cursor, pedido_id, PERFIS_OPERACAO, "SALVAR", usuario, perfil)
        antes = None
        if pedido_id:
            cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"), (pedido_id,))
            registro = cursor.fetchone()
            if not registro:
                raise ValueError("Pedido não encontrado.")
            antes = dict(registro)
            if registro["status"] != "RASCUNHO":
                _evento(cursor, pedido_id, "TENTATIVA_EDICAO_NEGADA", antes, usuario=usuario, perfil=perfil)
                cursor.connection.commit()
                raise ValueError("Somente pedidos em rascunho podem ser editados.")
            numero = registro["numero"]
            cursor.execute(q("DELETE FROM pedido_venda_itens WHERE pedido_id=?"), (pedido_id,))
            cursor.execute(q("""UPDATE pedidos_venda SET cliente_id=?,cliente_snapshot=?,destino=?,data_pedido=?,
                previsao_entrega=?,responsavel=?,subtotal_centavos=?,desconto_centavos=?,valor_total_centavos=?,
                forma_pagamento=?,condicao_pagamento=?,vencimento_inicial=?,prazo_dias=?,numero_parcelas=?,
                intervalo_dias=?,entrada_centavos=?,entrada_percentual_milesimos=?,condicao_saldo=?,
                descricao_condicao=?,observacoes=?,atualizado_por=?,atualizado_em=?,versao=versao+1 WHERE id=?"""),
                (dados["cliente_id"], _json(dados["cliente_snapshot"]), dados["destino"], dados["data_pedido"],
                 dados["previsao_entrega"], dados["responsavel"], dados["subtotal_centavos"],
                 dados["desconto_centavos"], dados["valor_total_centavos"], dados["forma_pagamento"],
                 dados["condicao_pagamento"], dados["vencimento_inicial"], dados["prazo_dias"],
                 dados["numero_parcelas"], dados["intervalo_dias"], dados["entrada_centavos"],
                 dados["entrada_percentual_milesimos"], dados["condicao_saldo"], dados["descricao_condicao"],
                 dados["observacoes"], usuario, agora, pedido_id))
        else:
            numero = _proximo_numero(cursor, dados["data_pedido"])
            campos = (numero, dados["cliente_id"], _json(dados["cliente_snapshot"]), dados["destino"],
                      dados["data_pedido"], dados["previsao_entrega"], dados["responsavel"], "RASCUNHO",
                      dados["subtotal_centavos"], dados["desconto_centavos"], dados["valor_total_centavos"],
                      dados["forma_pagamento"], dados["condicao_pagamento"], dados["vencimento_inicial"],
                      dados["prazo_dias"], dados["numero_parcelas"], dados["intervalo_dias"],
                      dados["entrada_centavos"], dados["entrada_percentual_milesimos"], dados["condicao_saldo"],
                      dados["descricao_condicao"], dados["observacoes"], usuario, usuario, agora, agora)
            sql = """INSERT INTO pedidos_venda(numero,cliente_id,cliente_snapshot,destino,data_pedido,
                previsao_entrega,responsavel,status,subtotal_centavos,desconto_centavos,valor_total_centavos,
                forma_pagamento,condicao_pagamento,vencimento_inicial,prazo_dias,numero_parcelas,intervalo_dias,
                entrada_centavos,entrada_percentual_milesimos,condicao_saldo,descricao_condicao,observacoes,
                criado_por,atualizado_por,criado_em,atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
            if DATABASE_URL:
                cursor.execute(q(sql + " RETURNING id"), campos)
                pedido_id = cursor.fetchone()["id"]
            else:
                cursor.execute(q(sql), campos)
                pedido_id = cursor.lastrowid
        for item in dados["itens"]:
            cursor.execute(q("""INSERT INTO pedido_venda_itens(pedido_id,produto_id,sku,produto_snapshot,
                apresentacao_snapshot,quantidade_negociada_mil,unidade_comercial,preco_unitario_centavos,
                desconto_centavos,valor_bruto_centavos,valor_liquido_centavos,quantidade_operacional_mil,
                unidade_operacional,aves_por_unidade_operacional,quantidade_comercial_mil,base_preco,
                observacoes,criado_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
                (pedido_id, item["produto_id"], item["sku"], _json(item["produto_snapshot"]),
                 item["apresentacao_snapshot"], item["quantidade_negociada_mil"], item["unidade_comercial"],
                 item["preco_unitario_centavos"], item["desconto_centavos"], item["valor_bruto_centavos"],
                 item["valor_liquido_centavos"], item["quantidade_operacional_mil"], item["unidade_operacional"],
                 item["aves_por_unidade_operacional"], item["quantidade_comercial_mil"], item["base_preco"],
                 item["observacoes"], agora))
        cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"), (pedido_id,))
        depois = dict(cursor.fetchone())
        _evento(cursor, pedido_id, "PEDIDO_EDITADO" if antes else "PEDIDO_CRIADO", antes, depois,
                usuario=usuario, perfil=perfil)
    return pedido_id, numero


def confirmar_pedido(pedido_id, *, usuario=None, perfil=None):
    criar_tabelas_pedidos_venda()
    usuario, perfil = _identidade(usuario, perfil)
    with transaction() as conn:
        cursor = conn.cursor()
        _autorizar(cursor, pedido_id, PERFIS_OPERACAO, "CONFIRMAR", usuario, perfil)
        cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"), (pedido_id,))
        row = cursor.fetchone()
        if not row or row["status"] != "RASCUNHO":
            raise ValueError("Somente pedido em rascunho pode ser confirmado.")
        antes = dict(row)
        agora = _agora()
        cursor.execute(q("""UPDATE pedidos_venda SET status='CONFIRMADO',confirmado_em=?,
            atualizado_em=?,atualizado_por=?,versao=versao+1 WHERE id=? AND status='RASCUNHO'"""),
                       (agora, agora, usuario, pedido_id))
        if cursor.rowcount != 1:
            raise ValueError("Pedido já foi processado por outro usuário.")
        cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"), (pedido_id,))
        _evento(cursor, pedido_id, "PEDIDO_CONFIRMADO", antes, dict(cursor.fetchone()),
                idempotency_key=f"CONFIRMACAO-PEDIDO-{pedido_id}", usuario=usuario, perfil=perfil)


def cancelar_pedido(pedido_id, motivo, *, usuario=None, perfil=None):
    criar_tabelas_pedidos_venda()
    usuario, perfil = _identidade(usuario, perfil)
    motivo = str(motivo or "").strip()
    if not motivo:
        raise ValueError("Informe o motivo do cancelamento.")
    with transaction() as conn:
        cursor = conn.cursor()
        _autorizar(cursor, pedido_id, PERFIS_GESTAO, "CANCELAR", usuario, perfil)
        cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"), (pedido_id,))
        row = cursor.fetchone()
        if not row or row["status"] not in {"RASCUNHO", "CONFIRMADO", "PARCIALMENTE_ATENDIDO"}:
            raise ValueError("Pedido não possui saldo cancelável.")
        cursor.execute(q("SELECT COUNT(*) total FROM expedicoes WHERE pedido_venda_id=? AND status='Aberto'"),
                       (pedido_id,))
        if int(cursor.fetchone()["total"] or 0):
            raise ValueError("Cancele primeiro os romaneios abertos vinculados ao pedido.")
        antes = dict(row); agora = _agora()
        cursor.execute(q("""UPDATE pedidos_venda SET status='CANCELADO',motivo_cancelamento=?,
            cancelado_em=?,atualizado_em=?,atualizado_por=?,versao=versao+1 WHERE id=?"""),
                       (motivo, agora, agora, usuario, pedido_id))
        cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"), (pedido_id,))
        _evento(cursor, pedido_id, "PEDIDO_CANCELADO", antes, dict(cursor.fetchone()),
                justificativa=motivo, idempotency_key=f"CANCELAMENTO-PEDIDO-{pedido_id}",
                usuario=usuario, perfil=perfil)


def _quantidade_entregue_expr():
    return """COALESCE((SELECT SUM(a.quantidade_atendida_mil) FROM pedido_venda_atendimentos a
        WHERE a.pedido_item_id=i.id AND a.status='ENTREGUE'),0)"""


def buscar_pedido(pedido_id):
    criar_tabelas_pedidos_venda()
    conn = conectar(); cursor = conn.cursor()
    try:
        cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"), (pedido_id,))
        pedido = cursor.fetchone()
        if not pedido:
            return None
        pedido = dict(pedido); pedido["cliente_snapshot"] = json.loads(pedido["cliente_snapshot"])
        expr = _quantidade_entregue_expr()
        cursor.execute(q(f"""SELECT i.*, {expr} AS quantidade_entregue_mil,
            COALESCE(i.quantidade_operacional_mil,i.quantidade_negociada_mil)-{expr} AS saldo_pendente_mil
            FROM pedido_venda_itens i WHERE i.pedido_id=? ORDER BY i.id"""), (pedido_id,))
        pedido["itens"] = []
        for linha in cursor.fetchall():
            item = dict(linha)
            snapshot = json.loads(item.get("produto_snapshot") or "{}")
            fator = int(item.get("aves_por_unidade_operacional") or 1)
            quantidade_operacional = int(item.get("quantidade_operacional_mil") or item["quantidade_negociada_mil"])
            entregue_operacional = int(item.get("quantidade_entregue_mil") or 0)
            item["quantidade_operacional_mil"] = quantidade_operacional
            item["unidade_operacional"] = item.get("unidade_operacional") or snapshot.get("unidade_operacional") or item["unidade_comercial"]
            item["quantidade_exibicao_mil"] = int(item.get("quantidade_comercial_mil") or quantidade_operacional * fator)
            item["quantidade_entregue_exibicao_mil"] = entregue_operacional * fator
            item["saldo_pendente_exibicao_mil"] = int(item["saldo_pendente_mil"]) * fator
            item["unidade_exibicao"] = snapshot.get("unidade_comercial_rotulo") or item["unidade_comercial"]
            pedido["itens"].append(item)
        cursor.execute(q("""SELECT e.id,e.numero_romaneio,e.data,e.status
            FROM expedicoes e WHERE e.pedido_venda_id=? ORDER BY e.data,e.id"""), (pedido_id,))
        pedido["romaneios"] = [dict(x) for x in cursor.fetchall()]
        cursor.execute(q("SELECT * FROM pedido_venda_eventos WHERE pedido_id=? ORDER BY criado_em,id"), (pedido_id,))
        pedido["eventos"] = [dict(x) for x in cursor.fetchall()]
        return pedido
    finally:
        conn.close()


def listar_pedidos(filtros=None):
    criar_tabelas_pedidos_venda(); filtros = filtros or {}
    clausulas, params = [], []
    mapa = {"numero": "p.numero LIKE ?", "destino": "p.destino LIKE ?", "responsavel": "p.responsavel LIKE ?"}
    for campo, sql in mapa.items():
        if filtros.get(campo): clausulas.append(sql); params.append(f"%{filtros[campo].strip()}%")
    for campo, coluna in (("data_inicio", "p.data_pedido >= ?"), ("data_fim", "p.data_pedido <= ?"),
                          ("cliente_id", "p.cliente_id = ?"), ("status", "p.status = ?"),
                          ("forma_pagamento", "p.forma_pagamento = ?"),
                          ("condicao_pagamento", "p.condicao_pagamento = ?")):
        if filtros.get(campo) and filtros[campo] != "Todos": clausulas.append(coluna); params.append(filtros[campo])
    if filtros.get("produto"):
        clausulas.append("EXISTS(SELECT 1 FROM pedido_venda_itens i WHERE i.pedido_id=p.id AND i.sku LIKE ?)")
        params.append(f"%{filtros['produto'].strip()}%")
    where = " WHERE " + " AND ".join(clausulas) if clausulas else ""
    conn = conectar(); cursor = conn.cursor()
    try:
        cursor.execute(q(f"""SELECT p.*, COALESCE((SELECT SUM(a.quantidade_atendida_mil)
            FROM pedido_venda_atendimentos a WHERE a.pedido_id=p.id AND a.status='ENTREGUE'),0) AS entregue_mil,
            COALESCE((SELECT SUM(i.quantidade_negociada_mil) FROM pedido_venda_itens i WHERE i.pedido_id=p.id),0) AS negociado_mil
            FROM pedidos_venda p{where} ORDER BY p.data_pedido DESC,p.id DESC"""), tuple(params))
        resultado=[]
        for row in cursor.fetchall():
            item=dict(row); item["cliente_snapshot"]=json.loads(item["cliente_snapshot"])
            item["quantidades_resumo"] = _resumo_quantidades_cursor(cursor, item["id"])
            cursor.execute(q("""SELECT i.quantidade_negociada_mil,i.valor_liquido_centavos,
                COALESCE(SUM(CASE WHEN a.status='ENTREGUE' THEN a.quantidade_atendida_mil ELSE 0 END),0) entregue
                FROM pedido_venda_itens i LEFT JOIN pedido_venda_atendimentos a ON a.pedido_item_id=i.id
                WHERE i.pedido_id=? GROUP BY i.id,i.quantidade_negociada_mil,i.valor_liquido_centavos"""), (item["id"],))
            valor_itens = Decimal(0)
            for linha in cursor.fetchall():
                proporcao = min(Decimal(int(linha["entregue"] or 0)) / Decimal(int(linha["quantidade_negociada_mil"])), Decimal(1))
                valor_itens += Decimal(int(linha["valor_liquido_centavos"])) * proporcao
            subtotal = Decimal(int(item["subtotal_centavos"] or 0))
            fator_desconto = (Decimal(int(item["valor_total_centavos"] or 0)) / subtotal) if subtotal else Decimal(0)
            item["valor_entregue_centavos"] = int((valor_itens * fator_desconto).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            resultado.append(item)
        return resultado
    finally: conn.close()


def resumo_pedidos(pedidos):
    resumo={"total":len(pedidos), **{s.lower():0 for s in STATUS}, "valor_total_centavos":0,
            "valor_entregue_centavos":0, "saldo_centavos":0}
    for p in pedidos:
        resumo[p["status"].lower()] += 1
        if p["status"] != "CANCELADO": resumo["valor_total_centavos"] += int(p["valor_total_centavos"] or 0)
        resumo["valor_entregue_centavos"] += int(p.get("valor_entregue_centavos") or 0)
    resumo["saldo_centavos"] = resumo["valor_total_centavos"]-resumo["valor_entregue_centavos"]
    return resumo


def gerar_romaneio_pedido(pedido_id, quantidades, *, data=None, responsavel=None,
                          versao_esperada=None, usuario=None, perfil=None):
    """Cria somente o cabeçalho e o plano comercial; não toca no estoque."""
    criar_tabelas_pedidos_venda(); usuario, perfil = _identidade(usuario, perfil)
    data = data or datetime.now().strftime("%Y-%m-%d")
    with transaction() as conn:
        cursor=conn.cursor(); _autorizar(cursor,pedido_id,PERFIS_OPERACAO,"GERAR_ROMANEIO",usuario,perfil)
        if DATABASE_URL:
            cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=? FOR UPDATE"),(pedido_id,))
        else: cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"),(pedido_id,))
        pedido=cursor.fetchone()
        if not pedido or pedido["status"] not in {"CONFIRMADO","PARCIALMENTE_ATENDIDO"}:
            raise ValueError("Pedido não está disponível para gerar romaneio.")
        if versao_esperada is not None and int(versao_esperada) != int(pedido["versao"]):
            raise ValueError("Solicitação já processada ou pedido atualizado; recarregue a página.")
        cursor.execute(q("SELECT * FROM pedido_venda_itens WHERE pedido_id=? ORDER BY id"),(pedido_id,))
        itens=cursor.fetchall(); planos=[]
        for item in itens:
            bruto=quantidades.get(str(item["id"]),quantidades.get(item["id"],""))
            if bruto in (None,""): continue
            qtd=_milesimos(bruto,f"Quantidade de {item['sku']}",positivo=True)
            cursor.execute(q("""SELECT COALESCE(SUM(quantidade_atendida_mil),0) total FROM pedido_venda_atendimentos
                WHERE pedido_item_id=? AND status='ENTREGUE'"""),(item["id"],))
            entregue=int(cursor.fetchone()["total"] or 0)
            cursor.execute(q("""SELECT COALESCE(SUM(pr.quantidade_planejada_mil),0) total
                FROM pedido_venda_romaneio_itens pr JOIN expedicoes e ON e.id=pr.expedicao_id
                WHERE pr.pedido_item_id=? AND e.status='Aberto'"""),(item["id"],))
            aberto=int(cursor.fetchone()["total"] or 0)
            quantidade_operacional = int(item["quantidade_operacional_mil"] or item["quantidade_negociada_mil"])
            if qtd > quantidade_operacional-entregue-aberto:
                raise ValueError(f"Quantidade de {item['sku']} supera o saldo disponível.")
            planos.append((item,qtd))
        if not planos: raise ValueError("Selecione ao menos uma quantidade para entrega.")
        if DATABASE_URL:
            cursor.execute("LOCK TABLE expedicoes IN SHARE ROW EXCLUSIVE MODE")
        prefixo = "ROM-" + data.replace("-", "")
        cursor.execute(q("SELECT numero_romaneio FROM expedicoes WHERE numero_romaneio LIKE ?"),
                       (prefixo + "-%",))
        sequenciais = []
        for linha in cursor.fetchall():
            try: sequenciais.append(int(str(linha["numero_romaneio"]).rsplit("-", 1)[1]))
            except (ValueError, IndexError): pass
        numero=f"{prefixo}-{max(sequenciais, default=0)+1:03d}"
        snap=json.loads(pedido["cliente_snapshot"])
        sql="""INSERT INTO expedicoes(numero_romaneio,data,tipo_movimentacao,origem,destino,responsavel,
            observacoes,status,criado_por,perfil_criacao,atualizado_em,tipo_saida,cliente_id,cliente_snapshot,
            pedido_venda_id,pedido_destino_entrega) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        valores=(numero,data,"VENDA_DIRETA","Abatedouro","Venda direta",responsavel or usuario,
                 f"Gerado a partir do pedido {pedido['numero']}","Aberto",usuario,perfil,_agora(),"VENDA_DIRETA",
                 pedido["cliente_id"],_json(snap),pedido_id,pedido["destino"])
        if DATABASE_URL:
            cursor.execute(q(sql+" RETURNING id"),valores); expedicao_id=cursor.fetchone()["id"]
        else: cursor.execute(q(sql),valores); expedicao_id=cursor.lastrowid
        for item,qtd in planos:
            cursor.execute(q("""INSERT INTO pedido_venda_romaneio_itens(pedido_id,pedido_item_id,expedicao_id,
                quantidade_planejada_mil,unidade,criado_por,criado_em) VALUES (?,?,?,?,?,?,?)"""),
                (pedido_id,item["id"],expedicao_id,qtd,item["unidade_operacional"] or item["unidade_comercial"],usuario,_agora()))
        cursor.execute(q("UPDATE pedidos_venda SET versao=versao+1,atualizado_em=?,atualizado_por=? WHERE id=?"),
                       (_agora(), usuario, pedido_id))
        _evento(cursor,pedido_id,"ROMANEIO_GERADO",dict(pedido),{"status":pedido["status"],"romaneio":numero},
                origem="expedicao",idempotency_key=f"PEDIDO-ROMANEIO-{expedicao_id}",usuario=usuario,perfil=perfil)
        return expedicao_id,numero


def _qtd_item_romaneio_mil(item, unidade):
    if unidade == "PACOTE": return int(Decimal(str(item["quantidade_pacotes"] or 0))*1000)
    if unidade == "CAIXA": return 1000
    if unidade == "BANDEJA": return int(Decimal(str(item["quantidade_unidades"] or 0))*1000)
    if unidade == "KG": return int(Decimal(str(item["quantidade_kg"] or 0))*1000)
    if unidade in {"UNIDADE","GALINHA"}:
        valor=item["quantidade_galinhas"] if unidade=="GALINHA" else item["quantidade_unidades"]
        return int(Decimal(str(valor or 0))*1000)
    raise ValueError("Unidade comercial sem conversão operacional.")


def vincular_item_reservado_cursor(cursor, expedicao_id, expedicao_item_id):
    try:
        cursor.execute(q("SELECT pedido_venda_id FROM expedicoes WHERE id=?"),(expedicao_id,))
    except Exception:
        return  # banco legado ainda sem a migration; fluxo histórico permanece íntegro
    rom=cursor.fetchone()
    if not rom or not rom["pedido_venda_id"]: return
    cursor.execute(q("SELECT * FROM expedicao_itens WHERE id=?"),(expedicao_item_id,)); item=cursor.fetchone()
    cursor.execute(q("""SELECT pr.*,pi.sku,pi.produto_snapshot,pi.apresentacao_snapshot FROM pedido_venda_romaneio_itens pr
        JOIN pedido_venda_itens pi ON pi.id=pr.pedido_item_id WHERE pr.expedicao_id=? ORDER BY pr.id"""),(expedicao_id,))
    candidatos=[]
    for plano in cursor.fetchall():
        snapshot = json.loads(plano["produto_snapshot"] or "{}")
        codigos = {str(plano["sku"] or "").strip().casefold(), str(snapshot.get("nome") or "").strip().casefold()}
        if str(item["sku"] or "").strip().casefold() not in codigos: continue
        if plano["apresentacao_snapshot"] and item["apresentacao"] and str(plano["apresentacao_snapshot"]).strip().casefold() != str(item["apresentacao"]).strip().casefold():
            continue
        qtd=_qtd_item_romaneio_mil(item,plano["unidade"])
        cursor.execute(q("""SELECT COALESCE(SUM(CASE WHEN ei.id=? THEN 0 ELSE
            CASE pr2.unidade WHEN 'PACOTE' THEN COALESCE(ei.quantidade_pacotes,0)*1000
            WHEN 'CAIXA' THEN 1000 WHEN 'BANDEJA' THEN COALESCE(ei.quantidade_unidades,0)*1000
            WHEN 'KG' THEN COALESCE(ei.quantidade_kg,0)*1000 WHEN 'GALINHA' THEN COALESCE(ei.quantidade_galinhas,0)*1000
            ELSE COALESCE(ei.quantidade_unidades,0)*1000 END END),0) total
            FROM expedicao_itens ei JOIN pedido_venda_romaneio_itens pr2
              ON pr2.expedicao_id=ei.expedicao_id AND pr2.pedido_item_id=ei.pedido_item_id
            WHERE ei.expedicao_id=? AND ei.pedido_item_id=?"""),(expedicao_item_id,expedicao_id,plano["pedido_item_id"]))
        usado=int(cursor.fetchone()["total"] or 0)
        if usado+qtd <= int(plano["quantidade_planejada_mil"]): candidatos.append((plano,qtd))
    if len(candidatos)!=1:
        raise ValueError("Item de estoque não corresponde unicamente ao saldo planejado do pedido.")
    plano,_=candidatos[0]
    cursor.execute(q("UPDATE expedicao_itens SET pedido_item_id=? WHERE id=?"),(plano["pedido_item_id"],expedicao_item_id))


def validar_e_registrar_atendimento_cursor(cursor, expedicao_id):
    cursor.execute(q("SELECT * FROM expedicoes WHERE id=?"),(expedicao_id,)); rom=cursor.fetchone()
    pedido_id = dict(rom).get("pedido_venda_id") if rom else None
    if not pedido_id: return
    if DATABASE_URL: cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=? FOR UPDATE"),(pedido_id,))
    else: cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"),(pedido_id,))
    pedido=cursor.fetchone()
    if not pedido or pedido["status"] not in {"CONFIRMADO","PARCIALMENTE_ATENDIDO"}:
        raise ValueError("Pedido vinculado não está disponível para atendimento.")
    cursor.execute(q("SELECT * FROM expedicao_itens WHERE expedicao_id=? ORDER BY id"),(expedicao_id,))
    itens=cursor.fetchall()
    if any(not i["pedido_item_id"] for i in itens): raise ValueError("Todo item do romaneio deve estar vinculado a um item do pedido.")
    for item in itens:
        cursor.execute(q("SELECT * FROM pedido_venda_itens WHERE id=? AND pedido_id=?"),(item["pedido_item_id"],pedido_id))
        pi=cursor.fetchone()
        if not pi: raise ValueError("Item não pertence ao pedido vinculado.")
        unidade_operacional = pi["unidade_operacional"] or pi["unidade_comercial"]
        qtd=_qtd_item_romaneio_mil(item,unidade_operacional)
        cursor.execute(q("SELECT COALESCE(SUM(quantidade_atendida_mil),0) total FROM pedido_venda_atendimentos WHERE pedido_item_id=? AND status='ENTREGUE'"),(pi["id"],))
        entregue=int(cursor.fetchone()["total"] or 0)
        quantidade_operacional = int(pi["quantidade_operacional_mil"] or pi["quantidade_negociada_mil"])
        if entregue+qtd>quantidade_operacional: raise ValueError(f"Entrega de {pi['sku']} supera o saldo do pedido.")
        peso=int(Decimal(str(item["quantidade_kg"] or 0))*1000) if item["quantidade_kg"] is not None else None
        params=(pedido_id,pi["id"],expedicao_id,item["id"],qtd,unidade_operacional,peso,"ENTREGUE",_identidade()[0],_agora(),_agora())
        if DATABASE_URL:
            cursor.execute(q("""INSERT INTO pedido_venda_atendimentos(pedido_id,pedido_item_id,expedicao_id,
                expedicao_item_id,quantidade_atendida_mil,unidade,peso_atendido_mil_kg,status,criado_por,criado_em,atualizado_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(expedicao_item_id) DO NOTHING"""),params)
        else:
            cursor.execute(q("""INSERT OR IGNORE INTO pedido_venda_atendimentos(pedido_id,pedido_item_id,expedicao_id,
                expedicao_item_id,quantidade_atendida_mil,unidade,peso_atendido_mil_kg,status,criado_por,criado_em,atualizado_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)"""),params)
    _recalcular_status_cursor(cursor,pedido_id,"ATENDIMENTO_ROMANEIO",expedicao_id)


def estornar_atendimento_cursor(cursor, expedicao_id, justificativa):
    try:
        cursor.execute(q("SELECT pedido_venda_id FROM expedicoes WHERE id=?"),(expedicao_id,))
    except Exception:
        return
    rom=cursor.fetchone()
    if not rom or not rom["pedido_venda_id"]: return
    cursor.execute(q("""UPDATE pedido_venda_atendimentos SET status='ESTORNADO',atualizado_em=?
        WHERE expedicao_id=? AND status='ENTREGUE'"""),(_agora(),expedicao_id))
    _recalcular_status_cursor(cursor,rom["pedido_venda_id"],"ESTORNO_ATENDIMENTO",expedicao_id,justificativa)


def _recalcular_status_cursor(cursor,pedido_id,acao,expedicao_id,justificativa=None):
    cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"),(pedido_id,)); pedido=cursor.fetchone()
    if not pedido or pedido["status"]=="CANCELADO": return
    cursor.execute(q("""SELECT COUNT(*) total,
        SUM(CASE WHEN entregue>0 THEN 1 ELSE 0 END) com_entrega,
        SUM(CASE WHEN entregue>=quantidade_operacional_mil THEN 1 ELSE 0 END) completos FROM (
          SELECT COALESCE(i.quantidade_operacional_mil,i.quantidade_negociada_mil) quantidade_operacional_mil,
            COALESCE(SUM(CASE WHEN a.status='ENTREGUE' THEN a.quantidade_atendida_mil ELSE 0 END),0) entregue
          FROM pedido_venda_itens i LEFT JOIN pedido_venda_atendimentos a ON a.pedido_item_id=i.id
          WHERE i.pedido_id=? GROUP BY i.id,i.quantidade_operacional_mil,i.quantidade_negociada_mil) x"""),(pedido_id,))
    r=cursor.fetchone(); novo="ATENDIDO" if int(r["completos"] or 0)==int(r["total"] or 0) else ("PARCIALMENTE_ATENDIDO" if int(r["com_entrega"] or 0)>0 else "CONFIRMADO")
    antes=dict(pedido); cursor.execute(q("UPDATE pedidos_venda SET status=?,atualizado_em=?,versao=versao+1 WHERE id=?"),(novo,_agora(),pedido_id))
    cursor.execute(q("SELECT * FROM pedidos_venda WHERE id=?"),(pedido_id,)); depois=dict(cursor.fetchone())
    _evento(cursor,pedido_id,acao,antes,depois,justificativa=justificativa,origem="expedicao",
            idempotency_key=f"{acao}-{expedicao_id}-{novo}")


def plano_romaneio(expedicao_id):
    criar_tabelas_pedidos_venda(); conn=conectar(); cursor=conn.cursor()
    try:
        cursor.execute(q("""SELECT pr.*,pi.sku,pi.apresentacao_snapshot,pi.produto_snapshot,
            pi.unidade_comercial,pi.aves_por_unidade_operacional,p.numero FROM pedido_venda_romaneio_itens pr
            JOIN pedido_venda_itens pi ON pi.id=pr.pedido_item_id JOIN pedidos_venda p ON p.id=pr.pedido_id
            WHERE pr.expedicao_id=? ORDER BY pr.id"""),(expedicao_id,))
        planos = []
        for linha in cursor.fetchall():
            plano = dict(linha)
            fator = int(plano.get("aves_por_unidade_operacional") or 1)
            plano["unidade_exibicao"] = plano["unidade"]
            plano["quantidade_comercial_planejada_mil"] = int(plano["quantidade_planejada_mil"]) * fator
            planos.append(plano)
        return planos
    finally: conn.close()


def _resumo_quantidades_cursor(cursor, pedido_id):
    cursor.execute(q("""SELECT i.unidade_comercial,i.produto_snapshot,i.quantidade_negociada_mil,
        i.quantidade_operacional_mil,i.quantidade_comercial_mil,i.aves_por_unidade_operacional,
        COALESCE(SUM(CASE WHEN a.status='ENTREGUE' THEN a.quantidade_atendida_mil ELSE 0 END),0) entregue
        FROM pedido_venda_itens i LEFT JOIN pedido_venda_atendimentos a ON a.pedido_item_id=i.id
        WHERE i.pedido_id=? GROUP BY i.id,i.unidade_comercial,i.produto_snapshot,i.quantidade_negociada_mil,
          i.quantidade_operacional_mil,i.quantidade_comercial_mil,i.aves_por_unidade_operacional"""), (pedido_id,))
    totais = {}
    for linha in cursor.fetchall():
        snapshot = json.loads(linha["produto_snapshot"] or "{}")
        unidade = snapshot.get("unidade_comercial_rotulo") or linha["unidade_comercial"]
        fator = int(linha["aves_por_unidade_operacional"] or 1)
        quantidade_comercial = int(linha["quantidade_comercial_mil"] or linha["quantidade_negociada_mil"])
        entregue_comercial = int(linha["entregue"] or 0) * fator
        atual = totais.setdefault(unidade, [0, 0])
        atual[0] += entregue_comercial
        atual[1] += quantidade_comercial - entregue_comercial
    partes = []
    for unidade, (entregue, saldo) in sorted(totais.items()):
        partes.append(f"{decimal_milesimos(entregue)} {unidade} entregue; {decimal_milesimos(saldo)} {unidade} saldo")
    return " | ".join(partes) or "Sem quantidades"


def resumo_quantidades_pedido(pedido_id):
    criar_tabelas_pedidos_venda()
    conn = conectar()
    try:
        return _resumo_quantidades_cursor(conn.cursor(), pedido_id)
    finally:
        conn.close()
