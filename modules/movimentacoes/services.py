"""Servicos de Financeiro e Movimentacoes."""

import calendar
import hashlib
import re
import uuid
from datetime import datetime, date

from openpyxl import load_workbook
from openpyxl import Workbook
from openpyxl.utils.datetime import from_excel

from database import DATABASE_URL, conectar, q
from database.migrations import executar_alteracao_segura
from modules.financeiro.services import (
    categorias_entradas_financeiras,
    categorias_saidas_financeiras,
    listar_plano_contas,
)


def tentar_alter_table(cursor, conn, comando):
    executar_alteracao_segura(cursor, conn, comando)


CATEGORIAS_FINANCEIRAS_ENTRADA = categorias_entradas_financeiras()
CATEGORIAS_FINANCEIRAS_SAIDA = categorias_saidas_financeiras()
CATEGORIA_NAO_CLASSIFICADO = "Não Classificado"


FORMAS_PAGAMENTO_FINANCEIRO = [
    "Pix",
    "Dinheiro",
    "Boleto",
    "Cartão",
    "Transferência",
    "Cheque",
    "Outro"
]

# Status que o usuário escolhe no lançamento.
# "Em atraso" não deve ser escolhido manualmente; o sistema calcula pela data de vencimento.
STATUS_FINANCEIRO = [
    "Pendente",
    "Realizado",
    "Cancelado"
]

# Opções usadas nos filtros e na leitura gerencial da tela.
STATUS_FINANCEIRO_FILTRO = [
    "Todos",
    "A vencer",
    "Em atraso",
    "Realizado",
    "Cancelado"
]


def calcular_status_financeiro_visual(item, data_referencia=None):
    """
    Calcula o status visual/gerencial sem alterar o status gravado no banco.

    Regra:
    - Cancelado permanece Cancelado;
    - Realizado vira Liquidado;
    - Pendente com vencimento anterior à data de referência vira Em atraso;
    - Pendente com vencimento igual ou posterior vira A vencer.

    Observação de segurança:
    Se existir algum registro antigo com status "Atrasado", ele será exibido como "Em atraso"
    para manter compatibilidade com dados já lançados.
    """
    if data_referencia is None:
        data_referencia = datetime.now().date()

    status = (item.get("status") if hasattr(item, "get") else item["status"]) or "Pendente"
    data_vencimento = (item.get("data_vencimento") if hasattr(item, "get") else item["data_vencimento"]) or ""

    if status == "Cancelado":
        return "Cancelado"

    if status == "Realizado":
        return "Liquidado"

    if status == "Atrasado":
        return "Em atraso"

    try:
        vencimento = datetime.strptime(data_vencimento, "%Y-%m-%d").date()
    except Exception:
        return "A vencer"

    if vencimento < data_referencia:
        return "Em atraso"

    return "A vencer"


def preparar_movimentacoes_financeiras_para_tela(movimentacoes, status_filtro="Todos"):
    """
    Converte as linhas retornadas do banco em dicionários e adiciona campos calculados.
    Isso evita alterar a estrutura do banco e protege a lógica já existente.
    """
    hoje_data = datetime.now().date()
    resultado = []

    for item in movimentacoes:
        item_dict = dict(item)
        status_visual = calcular_status_financeiro_visual(item_dict, hoje_data)
        item_dict["status_original"] = item_dict.get("status", "Pendente")
        item_dict["status_visual"] = status_visual

        # Classe CSS simples para futura estilização do badge, sem obrigar mudança no template.
        item_dict["status_classe"] = (
            status_visual.lower()
            .replace(" ", "-")
            .replace("ç", "c")
            .replace("ã", "a")
        )

        if status_filtro == "Todos" or status_visual == status_filtro:
            resultado.append(item_dict)

    return resultado


def criar_tabela_movimentacoes_financeiras():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes_financeiras (
            id SERIAL PRIMARY KEY,
            data_vencimento TEXT NOT NULL,
            data_realizacao TEXT,
            tipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            forma_pagamento TEXT,
            status TEXT DEFAULT 'Pendente',
            parcelas INTEGER DEFAULT 1,
            parcela_atual INTEGER DEFAULT 1,
            intervalo_dias INTEGER DEFAULT 30,
            documento_id TEXT,
            data_documento TEXT,
            valor_documento REAL DEFAULT 0,
            prazo_medio_dias REAL DEFAULT 0,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes_financeiras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_vencimento TEXT NOT NULL,
            data_realizacao TEXT,
            tipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            forma_pagamento TEXT,
            status TEXT DEFAULT 'Pendente',
            parcelas INTEGER DEFAULT 1,
            parcela_atual INTEGER DEFAULT 1,
            intervalo_dias INTEGER DEFAULT 30,
            documento_id TEXT,
            data_documento TEXT,
            valor_documento REAL DEFAULT 0,
            prazo_medio_dias REAL DEFAULT 0,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN intervalo_dias INTEGER DEFAULT 30")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN documento_id TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN data_documento TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN valor_documento REAL DEFAULT 0")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN prazo_medio_dias REAL DEFAULT 0")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN import_key TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN cnpj_cpf TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN numero_documento TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN favorecido TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN parceiro TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN historico TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN valor_pago REAL DEFAULT 0")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN valor_liquido REAL DEFAULT 0")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN origem_importacao TEXT")

    conn.commit()
    conn.close()


def adicionar_meses(data_base, meses):
    ano = data_base.year
    mes = data_base.month + meses

    while mes > 12:
        mes -= 12
        ano += 1

    while mes < 1:
        mes += 12
        ano -= 1

    ultimo_dia = calendar.monthrange(ano, mes)[1]
    dia = min(data_base.day, ultimo_dia)

    return data_base.replace(year=ano, month=mes, day=dia)


def salvar_movimentacao_financeira(form):
    criar_tabela_movimentacoes_financeiras()

    tipo = form.get("tipo", "").strip()
    categoria = form.get("categoria", "").strip()
    descricao = form.get("descricao", "").strip()
    data_documento = form.get("data_documento") or datetime.now().strftime("%Y-%m-%d")
    data_realizacao = form.get("data_realizacao", "")
    forma_pagamento = form.get("forma_pagamento", "")
    status = form.get("status", "Pendente")
    observacoes = form.get("observacoes", "")
    valor_documento = float(form.get("valor") or 0)

    vencimentos = form.getlist("parcela_vencimento[]")
    valores = form.getlist("parcela_valor[]")

    if tipo not in ["Entrada", "Saída"]:
        raise ValueError("Tipo de movimentação inválido.")

    if not descricao:
        raise ValueError("Informe uma descrição para a movimentação.")

    if valor_documento <= 0:
        raise ValueError("O valor total do documento deve ser maior que zero.")

    parcelas_validas = []

    for vencimento, valor in zip(vencimentos, valores):
        vencimento = (vencimento or "").strip()
        valor = float(valor or 0)

        if vencimento and valor > 0:
            parcelas_validas.append({
                "vencimento": vencimento,
                "valor": round(valor, 2)
            })

    if not parcelas_validas:
        parcelas_validas.append({
            "vencimento": data_documento,
            "valor": round(valor_documento, 2)
        })

    soma_parcelas = round(sum(item["valor"] for item in parcelas_validas), 2)

    if abs(soma_parcelas - round(valor_documento, 2)) > 0.02:
        raise ValueError(
            f"A soma das parcelas (R$ {soma_parcelas:.2f}) precisa bater com o valor total do documento (R$ {valor_documento:.2f})."
        )

    data_base = datetime.strptime(data_documento, "%Y-%m-%d")
    prazo_ponderado = 0

    for item in parcelas_validas:
        data_vencimento = datetime.strptime(item["vencimento"], "%Y-%m-%d")
        dias = (data_vencimento - data_base).days
        prazo_ponderado += item["valor"] * dias

    prazo_medio_dias = prazo_ponderado / valor_documento if valor_documento > 0 else 0
    documento_id = uuid.uuid4().hex
    total_parcelas = len(parcelas_validas)

    conn = conectar()
    cursor = conn.cursor()

    for indice, parcela in enumerate(parcelas_validas, start=1):
        descricao_parcela = descricao

        if total_parcelas > 1:
            descricao_parcela = f"{descricao} ({indice}/{total_parcelas})"

        cursor.execute(q("""
        INSERT INTO movimentacoes_financeiras (
            data_vencimento,
            data_realizacao,
            tipo,
            categoria,
            descricao,
            valor,
            forma_pagamento,
            status,
            parcelas,
            parcela_atual,
            intervalo_dias,
            documento_id,
            data_documento,
            valor_documento,
            prazo_medio_dias,
            observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            parcela["vencimento"],
            data_realizacao if status == "Realizado" else "",
            tipo,
            categoria,
            descricao_parcela,
            parcela["valor"],
            forma_pagamento,
            status,
            total_parcelas,
            indice,
            0,
            documento_id,
            data_documento,
            valor_documento,
            round(prazo_medio_dias, 2),
            observacoes
        ))

    conn.commit()
    conn.close()


def buscar_movimentacao_financeira_por_id(movimentacao_id):
    criar_tabela_movimentacoes_financeiras()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE id = ?
    """), (movimentacao_id,))

    movimentacao = cursor.fetchone()
    conn.close()

    return movimentacao


def atualizar_movimentacao_financeira(movimentacao_id, form):
    criar_tabela_movimentacoes_financeiras()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    UPDATE movimentacoes_financeiras
    SET data_vencimento = ?,
        data_realizacao = ?,
        tipo = ?,
        categoria = ?,
        descricao = ?,
        valor = ?,
        forma_pagamento = ?,
        status = ?,
        intervalo_dias = ?,
        observacoes = ?
    WHERE id = ?
    """), (
        form.get("data_vencimento", ""),
        form.get("data_realizacao", ""),
        form.get("tipo", ""),
        form.get("categoria", ""),
        form.get("descricao", ""),
        float(form.get("valor") or 0),
        form.get("forma_pagamento", ""),
        form.get("status", ""),
        int(form.get("intervalo_dias") or 30),
        form.get("observacoes", ""),
        movimentacao_id
    ))

    conn.commit()
    conn.close()


def excluir_movimentacao_financeira(movimentacao_id):
    criar_tabela_movimentacoes_financeiras()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    DELETE FROM movimentacoes_financeiras
    WHERE id = ?
    """), (movimentacao_id,))

    conn.commit()
    conn.close()


def buscar_movimentacoes_financeiras(data_inicio, data_fim, tipo_filtro, status_filtro):
    criar_tabela_movimentacoes_financeiras()

    condicoes = ["data_vencimento BETWEEN ? AND ?"]
    parametros = [data_inicio, data_fim]

    if tipo_filtro in ["Entrada", "Saída"]:
        condicoes.append("tipo = ?")
        parametros.append(tipo_filtro)

    # O filtro por status visual é aplicado depois da consulta, porque "A vencer" e
    # "Em atraso" são calculados pela data de vencimento, não gravados no banco.
    if status_filtro == "Realizado":
        condicoes.append("status = ?")
        parametros.append("Realizado")
    elif status_filtro == "Cancelado":
        condicoes.append("status = ?")
        parametros.append("Cancelado")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE {where_sql}
    ORDER BY data_vencimento ASC, id ASC
    """), tuple(parametros))

    movimentacoes = cursor.fetchall()
    conn.close()

    return preparar_movimentacoes_financeiras_para_tela(movimentacoes, status_filtro)


def calcular_resumo_financeiro(movimentacoes):
    entradas_previstas = 0
    saidas_previstas = 0
    entradas_realizadas = 0
    saidas_realizadas = 0

    for item in movimentacoes:
        valor = float(item["valor"] or 0)
        tipo = item["tipo"]
        status = item.get("status_original", item.get("status", "Pendente")) if hasattr(item, "get") else item["status"]

        # Cancelados não entram no previsto nem no realizado.
        if status == "Cancelado":
            continue

        if tipo == "Entrada":
            entradas_previstas += valor

            if status == "Realizado":
                entradas_realizadas += valor

        elif tipo == "Saída":
            saidas_previstas += valor

            if status == "Realizado":
                saidas_realizadas += valor

    saldo_previsto = entradas_previstas - saidas_previstas
    saldo_realizado = entradas_realizadas - saidas_realizadas

    return {
        "entradas_previstas": round(entradas_previstas, 2),
        "saidas_previstas": round(saidas_previstas, 2),
        "saldo_previsto": round(saldo_previsto, 2),
        "entradas_realizadas": round(entradas_realizadas, 2),
        "saidas_realizadas": round(saidas_realizadas, 2),
        "saldo_realizado": round(saldo_realizado, 2)
    }


def agrupar_fluxo_por_dia(movimentacoes):
    fluxo = {}

    for item in movimentacoes:
        data = item["data_vencimento"]
        valor = float(item["valor"] or 0)

        if data not in fluxo:
            fluxo[data] = {
                "data": data,
                "entradas": 0,
                "saidas": 0,
                "saldo": 0
            }

        status = item.get("status_original", item.get("status", "Pendente")) if hasattr(item, "get") else item["status"]

        # Fluxo diário ignora documentos cancelados.
        if status == "Cancelado":
            continue

        if item["tipo"] == "Entrada":
            fluxo[data]["entradas"] += valor
        else:
            fluxo[data]["saidas"] += valor

        fluxo[data]["saldo"] = fluxo[data]["entradas"] - fluxo[data]["saidas"]

    return [
        {
            "data": item["data"],
            "entradas": round(item["entradas"], 2),
            "saidas": round(item["saidas"], 2),
            "saldo": round(item["saldo"], 2)
        }
        for item in fluxo.values()
    ]


def normalizar_cabecalho_importacao(valor):
    texto = str(valor or "").strip().lower()
    substituicoes = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for origem, destino in substituicoes.items():
        texto = texto.replace(origem, destino)
    return re.sub(r"[^a-z0-9]+", "", texto)


MAPEAMENTO_CABECALHOS_IMPORTACAO = {
    "categoria": ["categoria", "classificacao", "classificacaofinanceira"],
    "data_documento": ["datadocumento", "datadodocumento", "dataemissao", "emissao"],
    "cnpj_cpf": ["cnpjcpf", "cnpj", "cpf"],
    "valor_documento": ["valordocumento", "valordodocumento", "valor"],
    "numero_documento": ["numerodocumento", "numerododocumento", "documento", "numero", "nf", "notafiscal"],
    "data_vencimento": ["datavencimento", "datadevencimento", "vencimento"],
    "valor_pago": ["valorpago", "pago", "valorpagamento"],
    "data_pagamento": ["datapagamento", "datadepagamento", "pagamento", "datarealizacao"],
    "favorecido": ["favorecido", "fornecedor", "cliente"],
    "valor_liquido": ["valorliquido", "liquido", "valorliquidado"],
    "descricao": ["descricao", "descricaohistorico"],
    "parceiro": ["parceiro", "razaosocial", "nome"],
    "historico": ["historico", "histórico", "observacao", "observacoes"],
}


def mapear_cabecalhos_importacao(ws):
    cabecalhos = {}
    for indice, celula in enumerate(ws[1], start=1):
        chave = normalizar_cabecalho_importacao(celula.value)
        if chave:
            cabecalhos[chave] = indice

    colunas = {}
    for campo, aliases in MAPEAMENTO_CABECALHOS_IMPORTACAO.items():
        for alias in aliases:
            chave = normalizar_cabecalho_importacao(alias)
            if chave in cabecalhos:
                colunas[campo] = cabecalhos[chave]
                break

    obrigatorios = ["data_documento", "data_vencimento", "valor_documento"]
    ausentes = [campo for campo in obrigatorios if campo not in colunas]
    return colunas, ausentes


def texto_importacao(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def data_importacao(valor):
    if valor in [None, ""]:
        return ""
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, (int, float)) and valor > 20000:
        try:
            return from_excel(valor).date().isoformat()
        except Exception:
            return ""

    texto = str(valor).strip()
    for formato in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]:
        try:
            return datetime.strptime(texto[:10], formato).date().isoformat()
        except ValueError:
            pass
    return ""


def numero_importacao(valor):
    if valor in [None, ""]:
        return 0
    if isinstance(valor, (int, float)):
        return float(valor or 0)
    texto = str(valor).strip()
    if not texto:
        return 0
    texto = texto.replace("R$", "").replace(" ", "")
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0


def valor_celula(ws, linha, colunas, campo):
    coluna = colunas.get(campo)
    if not coluna:
        return None
    return ws.cell(linha, coluna).value


def natureza_por_categoria(categoria):
    if categoria in CATEGORIAS_FINANCEIRAS_ENTRADA:
        return "Entrada"
    if categoria in CATEGORIAS_FINANCEIRAS_SAIDA:
        return "Saída"
    return ""


def montar_import_key(dados):
    partes = [
        dados.get("numero_documento", ""),
        dados.get("data_documento", ""),
        dados.get("data_vencimento", ""),
        dados.get("favorecido", "") or dados.get("parceiro", ""),
        f"{float(dados.get('valor_documento') or 0):.2f}",
        dados.get("historico", "") or dados.get("descricao", ""),
    ]
    base = "|".join(str(parte).strip().lower() for parte in partes)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def linha_importacao_vazia(dados):
    return not any(str(valor or "").strip() for valor in dados.values())


def preparar_linha_importacao(ws, linha, colunas):
    valor_documento_original = numero_importacao(valor_celula(ws, linha, colunas, "valor_documento"))
    valor_liquido_original = numero_importacao(valor_celula(ws, linha, colunas, "valor_liquido"))
    valor_pago_original = numero_importacao(valor_celula(ws, linha, colunas, "valor_pago"))
    categoria = texto_importacao(valor_celula(ws, linha, colunas, "categoria")) or CATEGORIA_NAO_CLASSIFICADO
    descricao = texto_importacao(valor_celula(ws, linha, colunas, "descricao"))
    historico = texto_importacao(valor_celula(ws, linha, colunas, "historico"))
    favorecido = texto_importacao(valor_celula(ws, linha, colunas, "favorecido"))
    parceiro = texto_importacao(valor_celula(ws, linha, colunas, "parceiro"))

    valor_referencia = valor_liquido_original or valor_documento_original or valor_pago_original
    natureza_categoria = natureza_por_categoria(categoria)
    valores_com_sinal = [valor for valor in [valor_documento_original, valor_liquido_original] if valor]
    tipo_por_sinal = "Entrada"
    if any(valor < 0 for valor in valores_com_sinal):
        tipo_por_sinal = "Saída"
    elif any(valor > 0 for valor in valores_com_sinal):
        tipo_por_sinal = "Entrada"
    tipo = natureza_categoria or tipo_por_sinal

    valor_documento = abs(valor_documento_original or valor_referencia)
    valor_liquido = abs(valor_liquido_original)
    valor_pago = abs(valor_pago_original)

    data_documento = data_importacao(valor_celula(ws, linha, colunas, "data_documento"))
    data_vencimento = data_importacao(valor_celula(ws, linha, colunas, "data_vencimento")) or data_documento
    data_pagamento = data_importacao(valor_celula(ws, linha, colunas, "data_pagamento"))
    descricao_final = descricao or historico or favorecido or parceiro or "Movimentacao importada"
    status = "Realizado" if data_pagamento or valor_pago > 0 else "Pendente"

    dados = {
        "data_vencimento": data_vencimento,
        "data_realizacao": data_pagamento if status == "Realizado" else "",
        "tipo": tipo,
        "categoria": categoria,
        "descricao": descricao_final,
        "valor": abs(valor_referencia) if valor_referencia else valor_documento,
        "forma_pagamento": "",
        "status": status,
        "parcelas": 1,
        "parcela_atual": 1,
        "intervalo_dias": 0,
        "documento_id": texto_importacao(valor_celula(ws, linha, colunas, "numero_documento")),
        "data_documento": data_documento,
        "valor_documento": valor_documento,
        "prazo_medio_dias": 0,
        "observacoes": f"Importado do Excel. Historico: {historico}".strip(),
        "cnpj_cpf": texto_importacao(valor_celula(ws, linha, colunas, "cnpj_cpf")),
        "numero_documento": texto_importacao(valor_celula(ws, linha, colunas, "numero_documento")),
        "favorecido": favorecido,
        "parceiro": parceiro,
        "historico": historico,
        "valor_pago": valor_pago,
        "valor_liquido": valor_liquido,
        "origem_importacao": "excel_movimentacoes",
    }
    dados["import_key"] = montar_import_key(dados)
    return dados


def importar_movimentacoes_financeiras_excel(arquivo_excel):
    criar_tabela_movimentacoes_financeiras()

    wb = load_workbook(arquivo_excel, data_only=True)
    ws = wb.active
    colunas, ausentes = mapear_cabecalhos_importacao(ws)
    if ausentes:
        raise ValueError("Cabecalhos obrigatorios ausentes: " + ", ".join(ausentes))

    resultado = {
        "linhas_lidas": 0,
        "importadas": 0,
        "atualizadas": 0,
        "erros": 0,
        "classificadas": 0,
        "nao_classificadas": 0,
        "detalhes_erros": [],
    }

    conn = conectar()
    cursor = conn.cursor()

    for linha in range(2, ws.max_row + 1):
        resultado["linhas_lidas"] += 1
        try:
            dados = preparar_linha_importacao(ws, linha, colunas)
            if linha_importacao_vazia(dados):
                continue
            if not dados["data_documento"] and not dados["data_vencimento"]:
                raise ValueError("linha sem data do documento e sem vencimento")
            if float(dados["valor"] or 0) <= 0:
                raise ValueError("linha sem valor financeiro valido")

            if dados["categoria"] == CATEGORIA_NAO_CLASSIFICADO:
                resultado["nao_classificadas"] += 1
            else:
                resultado["classificadas"] += 1

            cursor.execute(q("""
            SELECT id
            FROM movimentacoes_financeiras
            WHERE import_key = ?
            """), (dados["import_key"],))
            existente = cursor.fetchone()

            if existente:
                cursor.execute(q("""
                UPDATE movimentacoes_financeiras
                SET data_vencimento = ?,
                    data_realizacao = ?,
                    tipo = ?,
                    categoria = ?,
                    descricao = ?,
                    valor = ?,
                    forma_pagamento = ?,
                    status = ?,
                    parcelas = ?,
                    parcela_atual = ?,
                    intervalo_dias = ?,
                    documento_id = ?,
                    data_documento = ?,
                    valor_documento = ?,
                    prazo_medio_dias = ?,
                    observacoes = ?,
                    cnpj_cpf = ?,
                    numero_documento = ?,
                    favorecido = ?,
                    parceiro = ?,
                    historico = ?,
                    valor_pago = ?,
                    valor_liquido = ?,
                    origem_importacao = ?
                WHERE id = ?
                """), (
                    dados["data_vencimento"], dados["data_realizacao"], dados["tipo"],
                    dados["categoria"], dados["descricao"], dados["valor"], dados["forma_pagamento"],
                    dados["status"], dados["parcelas"], dados["parcela_atual"], dados["intervalo_dias"],
                    dados["documento_id"], dados["data_documento"], dados["valor_documento"],
                    dados["prazo_medio_dias"], dados["observacoes"], dados["cnpj_cpf"],
                    dados["numero_documento"], dados["favorecido"], dados["parceiro"], dados["historico"],
                    dados["valor_pago"], dados["valor_liquido"], dados["origem_importacao"],
                    existente["id"],
                ))
                resultado["atualizadas"] += 1
            else:
                cursor.execute(q("""
                INSERT INTO movimentacoes_financeiras (
                    data_vencimento, data_realizacao, tipo, categoria, descricao, valor,
                    forma_pagamento, status, parcelas, parcela_atual, intervalo_dias,
                    documento_id, data_documento, valor_documento, prazo_medio_dias, observacoes,
                    import_key, cnpj_cpf, numero_documento, favorecido, parceiro, historico,
                    valor_pago, valor_liquido, origem_importacao
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (
                    dados["data_vencimento"], dados["data_realizacao"], dados["tipo"],
                    dados["categoria"], dados["descricao"], dados["valor"], dados["forma_pagamento"],
                    dados["status"], dados["parcelas"], dados["parcela_atual"], dados["intervalo_dias"],
                    dados["documento_id"], dados["data_documento"], dados["valor_documento"],
                    dados["prazo_medio_dias"], dados["observacoes"], dados["import_key"], dados["cnpj_cpf"],
                    dados["numero_documento"], dados["favorecido"], dados["parceiro"], dados["historico"],
                    dados["valor_pago"], dados["valor_liquido"], dados["origem_importacao"],
                ))
                resultado["importadas"] += 1
        except Exception as erro:
            resultado["erros"] += 1
            resultado["detalhes_erros"].append(f"Linha {linha}: {erro}")

    conn.commit()
    conn.close()
    return resultado


def buscar_pendencias_classificacao():
    criar_tabela_movimentacoes_financeiras()

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE categoria = ?
    ORDER BY data_documento ASC, data_vencimento ASC, id ASC
    """), (CATEGORIA_NAO_CLASSIFICADO,))
    pendencias = cursor.fetchall()
    conn.close()

    total = sum(float(item["valor"] or 0) for item in pendencias)
    return {
        "quantidade": len(pendencias),
        "valor_total": round(total, 2),
        "movimentacoes": pendencias,
    }


def categorias_reclassificacao_financeira():
    return [
        item["nome"]
        for item in listar_plano_contas()
    ]


def normalizar_filtros_auditoria(args):
    return {
        "data_inicio": args.get("data_inicio", "").strip(),
        "data_fim": args.get("data_fim", "").strip(),
        "categoria": args.get("categoria", "Todas").strip() or "Todas",
        "favorecido": args.get("favorecido", "").strip(),
        "descricao": args.get("descricao", "").strip(),
        "historico": args.get("historico", "").strip(),
        "mes": args.get("mes", "").strip(),
        "somente_nao_classificados": args.get("somente_nao_classificados") == "1",
    }


def buscar_movimentacoes_auditoria(filtros):
    criar_tabela_movimentacoes_financeiras()

    condicoes = ["(import_key IS NOT NULL OR origem_importacao = ?)"]
    parametros = ["excel_movimentacoes"]

    if filtros["data_inicio"]:
        condicoes.append("COALESCE(data_documento, data_vencimento) >= ?")
        parametros.append(filtros["data_inicio"])

    if filtros["data_fim"]:
        condicoes.append("COALESCE(data_documento, data_vencimento) <= ?")
        parametros.append(filtros["data_fim"])

    if filtros["categoria"] != "Todas":
        condicoes.append("categoria = ?")
        parametros.append(filtros["categoria"])

    if filtros["favorecido"]:
        condicoes.append("(COALESCE(favorecido, '') LIKE ? OR COALESCE(parceiro, '') LIKE ?)")
        termo = f"%{filtros['favorecido']}%"
        parametros.extend([termo, termo])

    if filtros["descricao"]:
        condicoes.append("COALESCE(descricao, '') LIKE ?")
        parametros.append(f"%{filtros['descricao']}%")

    if filtros["historico"]:
        condicoes.append("(COALESCE(historico, '') LIKE ? OR COALESCE(observacoes, '') LIKE ?)")
        termo = f"%{filtros['historico']}%"
        parametros.extend([termo, termo])

    if filtros["mes"]:
        condicoes.append("substr(COALESCE(data_documento, data_vencimento), 1, 7) = ?")
        parametros.append(filtros["mes"])

    if filtros["somente_nao_classificados"]:
        condicoes.append("categoria = ?")
        parametros.append(CATEGORIA_NAO_CLASSIFICADO)

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes)}
    ORDER BY COALESCE(data_documento, data_vencimento) ASC, id ASC
    """), tuple(parametros))
    movimentacoes = [dict(item) for item in cursor.fetchall()]
    conn.close()
    return movimentacoes


def _tipo_auditoria(item):
    return "Entrada" if item.get("tipo") == "Entrada" else "Saida"


def montar_indicadores_auditoria(movimentacoes):
    total_receitas = 0
    total_despesas = 0
    qtd_nao_classificado = 0
    valor_nao_classificado = 0

    for item in movimentacoes:
        valor = float(item.get("valor") or 0)
        if _tipo_auditoria(item) == "Entrada":
            total_receitas += valor
        else:
            total_despesas += valor

        if item.get("categoria") == CATEGORIA_NAO_CLASSIFICADO:
            qtd_nao_classificado += 1
            valor_nao_classificado += valor

    return {
        "total_movimentacoes": len(movimentacoes),
        "total_receitas": round(total_receitas, 2),
        "total_despesas": round(total_despesas, 2),
        "saldo_liquido": round(total_receitas - total_despesas, 2),
        "qtd_nao_classificado": qtd_nao_classificado,
        "valor_nao_classificado": round(valor_nao_classificado, 2),
    }


def montar_totais_categoria_auditoria(movimentacoes):
    total_geral = sum(float(item.get("valor") or 0) for item in movimentacoes)
    categorias = {}
    for item in movimentacoes:
        categoria = item.get("categoria") or CATEGORIA_NAO_CLASSIFICADO
        categorias.setdefault(categoria, {"categoria": categoria, "quantidade": 0, "valor_total": 0})
        categorias[categoria]["quantidade"] += 1
        categorias[categoria]["valor_total"] += float(item.get("valor") or 0)

    resultado = []
    for item in categorias.values():
        percentual = (item["valor_total"] / total_geral * 100) if total_geral else 0
        resultado.append({
            "categoria": item["categoria"],
            "quantidade": item["quantidade"],
            "valor_total": round(item["valor_total"], 2),
            "percentual": round(percentual, 2),
        })
    return sorted(resultado, key=lambda item: item["valor_total"], reverse=True)


def montar_totais_mes_auditoria(movimentacoes):
    meses = {}
    for item in movimentacoes:
        data_base = (item.get("data_documento") or item.get("data_vencimento") or "")[:7] or "Sem data"
        meses.setdefault(data_base, {
            "mes": data_base,
            "total_receitas": 0,
            "total_despesas": 0,
            "saldo": 0,
            "quantidade": 0,
        })
        valor = float(item.get("valor") or 0)
        if _tipo_auditoria(item) == "Entrada":
            meses[data_base]["total_receitas"] += valor
        else:
            meses[data_base]["total_despesas"] += valor
        meses[data_base]["quantidade"] += 1

    resultado = []
    for item in meses.values():
        item["saldo"] = item["total_receitas"] - item["total_despesas"]
        for chave in ["total_receitas", "total_despesas", "saldo"]:
            item[chave] = round(item[chave], 2)
        resultado.append(item)
    return sorted(resultado, key=lambda item: item["mes"])


def montar_contexto_auditoria_financeira(args):
    filtros = normalizar_filtros_auditoria(args)
    movimentacoes = buscar_movimentacoes_auditoria(filtros)
    pendencias = [
        item for item in movimentacoes
        if item.get("categoria") == CATEGORIA_NAO_CLASSIFICADO
    ]

    return {
        "filtros": filtros,
        "indicadores": montar_indicadores_auditoria(movimentacoes),
        "totais_categoria": montar_totais_categoria_auditoria(movimentacoes),
        "totais_mes": montar_totais_mes_auditoria(movimentacoes),
        "pendencias": pendencias,
        "categorias_reclassificacao": categorias_reclassificacao_financeira(),
        "categorias_filtro": [CATEGORIA_NAO_CLASSIFICADO] + categorias_reclassificacao_financeira(),
    }


def reclassificar_movimentacoes(ids, nova_categoria):
    criar_tabela_movimentacoes_financeiras()

    ids_validos = []
    for item in ids:
        try:
            ids_validos.append(int(item))
        except (TypeError, ValueError):
            pass

    if not ids_validos:
        raise ValueError("Selecione ao menos uma movimentacao.")

    if nova_categoria not in categorias_reclassificacao_financeira():
        raise ValueError("Categoria invalida para reclassificacao.")

    conn = conectar()
    cursor = conn.cursor()
    atualizadas = 0
    for movimentacao_id in ids_validos:
        cursor.execute(q("""
        UPDATE movimentacoes_financeiras
        SET categoria = ?
        WHERE id = ?
        """), (nova_categoria, movimentacao_id))
        atualizadas += cursor.rowcount
    conn.commit()
    conn.close()
    return atualizadas


def gerar_excel_auditoria_financeira(contexto):
    wb = Workbook()
    ws = wb.active
    ws.title = "Visao geral"
    indicadores = contexto["indicadores"]
    ws.append(["Indicador", "Valor"])
    ws.append(["Total de movimentacoes importadas", indicadores["total_movimentacoes"]])
    ws.append(["Total de receitas", indicadores["total_receitas"]])
    ws.append(["Total de despesas", indicadores["total_despesas"]])
    ws.append(["Saldo liquido", indicadores["saldo_liquido"]])
    ws.append(["Qtd. Nao Classificado", indicadores["qtd_nao_classificado"]])
    ws.append(["Valor Nao Classificado", indicadores["valor_nao_classificado"]])

    ws_cat = wb.create_sheet("Por categoria")
    ws_cat.append(["Categoria", "Quantidade", "Valor total", "Percentual"])
    for item in contexto["totais_categoria"]:
        ws_cat.append([item["categoria"], item["quantidade"], item["valor_total"], item["percentual"]])

    ws_mes = wb.create_sheet("Por mes")
    ws_mes.append(["Mes", "Receitas", "Despesas", "Saldo", "Quantidade"])
    for item in contexto["totais_mes"]:
        ws_mes.append([item["mes"], item["total_receitas"], item["total_despesas"], item["saldo"], item["quantidade"]])

    ws_pend = wb.create_sheet("Pendencias")
    ws_pend.append([
        "Data documento", "Data vencimento", "Favorecido", "Descricao", "Historico",
        "Numero documento", "Valor documento", "Valor pago", "Categoria atual"
    ])
    for item in contexto["pendencias"]:
        ws_pend.append([
            item.get("data_documento", ""),
            item.get("data_vencimento", ""),
            item.get("favorecido") or item.get("parceiro") or "",
            item.get("descricao", ""),
            item.get("historico", ""),
            item.get("numero_documento") or item.get("documento_id") or "",
            float(item.get("valor_documento") or item.get("valor") or 0),
            float(item.get("valor_pago") or 0),
            item.get("categoria", ""),
        ])

    from io import BytesIO
    arquivo = BytesIO()
    wb.save(arquivo)
    arquivo.seek(0)
    return arquivo
