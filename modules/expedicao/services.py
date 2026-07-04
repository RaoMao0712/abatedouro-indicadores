"""Servicos de Expedicao, Embalagem e estoques PI/PA."""

from datetime import datetime, timedelta

from database import DATABASE_URL, conectar, q
from modules.producao.services import buscar_op_por_id, gerar_producao_automatica_setores

_CRIAR_BANCO = None


def configurar_integracoes(criar_banco=None):
    global _CRIAR_BANCO
    _CRIAR_BANCO = criar_banco


def garantir_schema_producao():
    if _CRIAR_BANCO:
        _CRIAR_BANCO()


def criar_tabelas_expedicao():
    """
    Cria a fundação do módulo de Expedição.

    Sprint 1.0:
    - Apenas estrutura, listagem e ponto de entrada no menu.
    - Não baixa estoque.
    - Não gera venda.
    - Não interfere na DRE nem no Financeiro.
    """
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedicoes (
            id SERIAL PRIMARY KEY,
            numero_romaneio TEXT UNIQUE NOT NULL,
            data TEXT NOT NULL,
            tipo_movimentacao TEXT NOT NULL DEFAULT 'TRANSFERENCIA',
            destino TEXT NOT NULL,
            responsavel TEXT,
            observacoes TEXT,
            status TEXT NOT NULL DEFAULT 'Aberto',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedicao_itens (
            id SERIAL PRIMARY KEY,
            expedicao_id INTEGER NOT NULL,
            op_id INTEGER,
            sku TEXT NOT NULL,
            quantidade_unidades REAL DEFAULT 0,
            quantidade_kg REAL DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_romaneio TEXT UNIQUE NOT NULL,
            data TEXT NOT NULL,
            tipo_movimentacao TEXT NOT NULL DEFAULT 'TRANSFERENCIA',
            destino TEXT NOT NULL,
            responsavel TEXT,
            observacoes TEXT,
            status TEXT NOT NULL DEFAULT 'Aberto',
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedicao_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expedicao_id INTEGER NOT NULL,
            op_id INTEGER,
            sku TEXT NOT NULL,
            quantidade_unidades REAL DEFAULT 0,
            quantidade_kg REAL DEFAULT 0,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()



# ============================================================
# ESTOQUE PI / PA - ARQUITETURA RASTREÁVEL
# ============================================================

BANDEJAS_POR_CAIXA = 12


def sku_sem_embalagem_secundaria(sku):
    return (sku or "").strip().lower() == "galinha inteira"


def criar_tabelas_estoque_pi_pa():
    """
    Cria a estrutura de estoque em duas etapas:

    1) Produto Intermediário (PI)
       - nasce no encerramento da OP;
       - controla bandejas por OP/lote;
       - nenhuma bandeja fica sem vínculo com OP.

    2) Produto Acabado (PA)
       - nasce na Embalagem Secundária;
       - controla caixas físicas;
       - permite composição da caixa por uma ou mais OPs;
       - preparado para integração futura com balança, Zebra e leitor.
    """
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS estoque_produto_intermediario (
            id SERIAL PRIMARY KEY,
            data_movimentacao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            op_id INTEGER,
            sku TEXT NOT NULL,
            quantidade_bandejas REAL DEFAULT 0,
            origem TEXT,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS embalagem_primaria_apontamentos (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            data_apontamento TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantidade_bandejas REAL DEFAULT 0,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pa_caixas (
            id SERIAL PRIMARY KEY,
            codigo_caixa TEXT UNIQUE NOT NULL,
            sku TEXT NOT NULL,
            data_fabricacao TEXT,
            data_validade TEXT,
            peso_bruto REAL DEFAULT 0,
            peso_liquido REAL DEFAULT 0,
            quantidade_bandejas REAL DEFAULT 0,
            status TEXT DEFAULT 'Em estoque',
            origem TEXT,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pa_caixa_composicao (
            id SERIAL PRIMARY KEY,
            caixa_id INTEGER NOT NULL,
            op_id INTEGER NOT NULL,
            quantidade_bandejas REAL DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS estoque_produto_intermediario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_movimentacao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            op_id INTEGER,
            sku TEXT NOT NULL,
            quantidade_bandejas REAL DEFAULT 0,
            origem TEXT,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS embalagem_primaria_apontamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            data_apontamento TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantidade_bandejas REAL DEFAULT 0,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pa_caixas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_caixa TEXT UNIQUE NOT NULL,
            sku TEXT NOT NULL,
            data_fabricacao TEXT,
            data_validade TEXT,
            peso_bruto REAL DEFAULT 0,
            peso_liquido REAL DEFAULT 0,
            quantidade_bandejas REAL DEFAULT 0,
            status TEXT DEFAULT 'Em estoque',
            origem TEXT,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pa_caixa_composicao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caixa_id INTEGER NOT NULL,
            op_id INTEGER NOT NULL,
            quantidade_bandejas REAL DEFAULT 0,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()


def remover_movimentacoes_estoque_pi_por_op(op_id):
    criar_tabelas_estoque_pi_pa()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    DELETE FROM estoque_produto_intermediario
    WHERE op_id = ?
      AND tipo IN (?, ?)
    """), (op_id, "ENTRADA_OP", "ENTRADA_EMBALAGEM_PRIMARIA"))

    cursor.execute(q("""
    DELETE FROM embalagem_primaria_apontamentos
    WHERE op_id = ?
    """), (op_id,))

    conn.commit()
    conn.close()


def op_possui_caixa_pa(op_id):
    criar_tabelas_estoque_pi_pa()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT COUNT(*) AS total
    FROM pa_caixa_composicao
    WHERE op_id = ?
    """), (op_id,))

    linha = cursor.fetchone()
    conn.close()

    return float(linha["total"] or 0) > 0


def registrar_entrada_estoque_pi_op(op, unidades_produzidas, origem="Embalagem Primária", observacoes=None):
    criar_tabelas_estoque_pi_pa()

    op_id = op["id"]
    sku = op["sku"] or "Galinha Cortada"
    bandejas = float(unidades_produzidas or 0)

    # Segurança contra duplicidade: se a OP for reapontada, a entrada anterior é substituída.
    remover_movimentacoes_estoque_pi_por_op(op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO estoque_produto_intermediario (
        data_movimentacao,
        tipo,
        op_id,
        sku,
        quantidade_bandejas,
        origem,
        observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        op["data"],
        "ENTRADA_EMBALAGEM_PRIMARIA",
        op_id,
        sku,
        bandejas,
        origem,
        observacoes or "Entrada automática de PI gerada no apontamento da Embalagem Primária."
    ))

    conn.commit()
    conn.close()


def calcular_perdas_aves_op(cursor, op_id):
    cursor.execute(q("""
    SELECT
        COALESCE(SUM(CASE
            WHEN LOWER(COALESCE(categoria, '')) LIKE '%%conden%%' THEN quantidade
            ELSE 0
        END), 0) AS condenacoes,
        COALESCE(SUM(CASE
            WHEN LOWER(COALESCE(categoria, '')) NOT LIKE '%%conden%%'
             AND LOWER(TRIM(COALESCE(motivo, ''))) <> 'morte na gaiola' THEN quantidade
            ELSE 0
        END), 0) AS descartes,
        COALESCE(SUM(CASE
            WHEN LOWER(TRIM(COALESCE(motivo, ''))) = 'morte na gaiola' THEN quantidade
            ELSE 0
        END), 0) AS mortes_na_gaiola
    FROM apontamentos_descartes
    WHERE op_id = ?
      AND LOWER(unidade) IN ('aves', 'ave', 'unidade', 'unidades')
    """), (op_id,))

    perdas = cursor.fetchone()
    return {
        "condenacoes": float(perdas["condenacoes"] or 0),
        "descartes": float(perdas["descartes"] or 0),
        "mortes_na_gaiola": float(perdas["mortes_na_gaiola"] or 0),
    }


def validar_balanco_aves_op(op, aves_produzidas, perdas):
    aves_vivas = float(op["quantidade_aves"] or 0)
    mortes_na_gaiola = float(op["mortes_antes_pendura"] or 0) + float(perdas["mortes_na_gaiola"] or 0)
    total_fechamento = float(aves_produzidas or 0) + float(perdas["descartes"] or 0) + float(perdas["condenacoes"] or 0) + mortes_na_gaiola
    saldo_aves = aves_vivas - total_fechamento

    if abs(saldo_aves) > 0.0001:
        raise ValueError(
            f"Balanco de aves divergente em {saldo_aves:g} aves. "
            "Revise Embalagem Primaria, descartes, condenacoes ou mortes na gaiola."
        )

    return saldo_aves


def registrar_lote_pa_galinha_inteira(cursor, op, unidades_vendaveis, aves_embaladas, kg_produzidos, observacoes):
    codigo_lote = f"GI-OP-{int(op['id']):05d}"
    data_fabricacao = op["data"] or datetime.now().strftime("%Y-%m-%d")
    data_validade = calcular_validade_padrao(data_fabricacao)
    observacao_lote = observacoes or f"Lote Galinha Inteira. Aves embaladas: {aves_embaladas:g}."

    if DATABASE_URL:
        cursor.execute(q("""
        INSERT INTO pa_caixas (
            codigo_caixa,
            sku,
            data_fabricacao,
            data_validade,
            peso_bruto,
            peso_liquido,
            quantidade_bandejas,
            status,
            origem,
            observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """), (
            codigo_lote,
            op["sku"] or "Galinha Inteira",
            data_fabricacao,
            data_validade,
            kg_produzidos,
            kg_produzidos,
            unidades_vendaveis,
            "Em estoque",
            "Embalagem Primaria",
            observacao_lote
        ))
        caixa_id = cursor.fetchone()["id"]
    else:
        cursor.execute(q("""
        INSERT INTO pa_caixas (
            codigo_caixa,
            sku,
            data_fabricacao,
            data_validade,
            peso_bruto,
            peso_liquido,
            quantidade_bandejas,
            status,
            origem,
            observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            codigo_lote,
            op["sku"] or "Galinha Inteira",
            data_fabricacao,
            data_validade,
            kg_produzidos,
            kg_produzidos,
            unidades_vendaveis,
            "Em estoque",
            "Embalagem Primaria",
            observacao_lote
        ))
        caixa_id = cursor.lastrowid

    cursor.execute(q("""
    INSERT INTO pa_caixa_composicao (
        caixa_id,
        op_id,
        quantidade_bandejas
    ) VALUES (?, ?, ?)
    """), (caixa_id, op["id"], unidades_vendaveis))

    return codigo_lote


def registrar_apontamento_embalagem_primaria(op, quantidade_bandejas, observacoes="", kg_produzidos=None, pacotes_1_ave=0, pacotes_2_aves=0):
    criar_tabelas_estoque_pi_pa()

    if not op:
        raise ValueError("OP não encontrada.")

    if op["status"] == "Encerrada":
        raise ValueError("Esta OP já está encerrada.")

    if op_possui_caixa_pa(op["id"]):
        raise ValueError("Esta OP já possui caixas PA vinculadas. Não é possível reapontar a Embalagem Primária.")

    sku = op["sku"] or "Galinha Cortada"
    bandejas = float(quantidade_bandejas or 0)
    if bandejas <= 0 and not sku_sem_embalagem_secundaria(sku):
        raise ValueError("Informe uma quantidade válida de bandejas produzidas.")

    if sku_sem_embalagem_secundaria(sku):
        pacotes_1 = parse_numero_form(pacotes_1_ave or 0)
        pacotes_2 = parse_numero_form(pacotes_2_aves or 0)
        aves_embaladas = pacotes_1 + (pacotes_2 * 2)
        unidades_vendaveis = pacotes_1 + pacotes_2
        kg_final = parse_numero_form(kg_produzidos or 0)

        if aves_embaladas <= 0:
            aves_embaladas = bandejas
            unidades_vendaveis = bandejas

        if aves_embaladas <= 0:
            raise ValueError("Informe as aves embaladas ou os pacotes de Galinha Inteira.")

        if unidades_vendaveis <= 0:
            raise ValueError("Informe uma quantidade valida de unidades vendaveis.")

        if kg_final <= 0:
            raise ValueError("Informe o peso liquido produzido em kg para calcular o rendimento da OP.")

        conn = conectar()
        cursor = conn.cursor()
        perdas = calcular_perdas_aves_op(cursor, op["id"])
        conn.close()

        validar_balanco_aves_op(op, aves_embaladas, perdas)
        remover_movimentacoes_estoque_pi_por_op(op["id"])

        observacao_final = observacoes or f"Pacotes 1 ave: {pacotes_1:g} | Pacotes 2 aves: {pacotes_2:g}"

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        INSERT INTO embalagem_primaria_apontamentos (
            op_id,
            data_apontamento,
            sku,
            quantidade_bandejas,
            observacoes
        ) VALUES (?, ?, ?, ?, ?)
        """), (
            op["id"],
            op["data"],
            sku,
            aves_embaladas,
            observacao_final
        ))

        codigo_lote = registrar_lote_pa_galinha_inteira(
            cursor,
            op,
            unidades_vendaveis,
            aves_embaladas,
            kg_final,
            observacao_final
        )

        cursor.execute(q("""
        UPDATE ordens_producao
        SET status = ?
        WHERE id = ?
        """), ("Encerrada", op["id"]))

        conn.commit()
        conn.close()

        gerar_producao_automatica_setores(
            op=op,
            data_lancamento=op["data"],
            hora_inicio="N/A",
            hora_fim="N/A",
            unidades_produzidas=unidades_vendaveis,
            kg_produzidos=kg_final,
            descontar_almoco=False
        )

        return {
            "tipo": "encerramento_primaria",
            "codigo_lote": codigo_lote,
            "aves_embaladas": aves_embaladas,
            "unidades_vendaveis": unidades_vendaveis,
            "kg_produzidos": kg_final,
        }

    # Substitui o apontamento anterior da mesma OP, se existir.
    remover_movimentacoes_estoque_pi_por_op(op["id"])

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO embalagem_primaria_apontamentos (
        op_id,
        data_apontamento,
        sku,
        quantidade_bandejas,
        observacoes
    ) VALUES (?, ?, ?, ?, ?)
    """), (
        op["id"],
        op["data"],
        sku,
        bandejas,
        observacoes or ""
    ))

    cursor.execute(q("""
    INSERT INTO estoque_produto_intermediario (
        data_movimentacao,
        tipo,
        op_id,
        sku,
        quantidade_bandejas,
        origem,
        observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        op["data"],
        "ENTRADA_EMBALAGEM_PRIMARIA",
        op["id"],
        sku,
        bandejas,
        "Embalagem Primária",
        "PI gerado pelo apontamento da Embalagem Primária. A OP permanece aberta até a validação da Embalagem Secundária."
    ))

    # A OP ainda não está encerrada. O status apenas sinaliza que há PI aguardando embalagem secundária.
    cursor.execute(q("""
    UPDATE ordens_producao
    SET status = ?
    WHERE id = ?
    """), ("Aguardando Embalagem Secundária", op["id"]))

    conn.commit()
    conn.close()

    return {
        "tipo": "pi",
        "bandejas": bandejas,
    }


def buscar_apontamentos_embalagem_primaria(limite=50):
    criar_tabelas_estoque_pi_pa()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT ep.*, op.data AS data_op, op.fornecedor, op.quantidade_aves
    FROM embalagem_primaria_apontamentos ep
    LEFT JOIN ordens_producao op ON op.id = ep.op_id
    ORDER BY ep.id DESC
    LIMIT ?
    """), (limite,))

    linhas = cursor.fetchall()
    conn.close()
    return linhas


def buscar_apontamento_embalagem_primaria_por_op(op_id):
    criar_tabelas_estoque_pi_pa()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT ep.*, op.data AS data_op, op.fornecedor, op.quantidade_aves
    FROM embalagem_primaria_apontamentos ep
    LEFT JOIN ordens_producao op ON op.id = ep.op_id
    WHERE ep.op_id = ?
    ORDER BY ep.id DESC
    LIMIT 1
    """), (op_id,))

    linha = cursor.fetchone()
    conn.close()
    return linha


def buscar_ops_para_embalagem_primaria():
    garantir_schema_producao()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM ordens_producao
    WHERE status <> ?
    ORDER BY data DESC, id DESC
    """), ("Encerrada",))

    ops = cursor.fetchall()
    conn.close()
    return ops


def buscar_saldos_estoque_pi():
    criar_tabelas_estoque_pi_pa()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        pi.op_id,
        op.data AS data_op,
        pi.sku,
        COALESCE(SUM(
            CASE
                WHEN pi.tipo LIKE 'ENTRADA%' THEN pi.quantidade_bandejas
                WHEN pi.tipo LIKE 'SAIDA%' THEN -pi.quantidade_bandejas
                ELSE pi.quantidade_bandejas
            END
        ), 0) AS saldo_bandejas
    FROM estoque_produto_intermediario pi
    LEFT JOIN ordens_producao op ON op.id = pi.op_id
    GROUP BY pi.op_id, op.data, pi.sku
    HAVING COALESCE(SUM(
            CASE
                WHEN pi.tipo LIKE 'ENTRADA%' THEN pi.quantidade_bandejas
                WHEN pi.tipo LIKE 'SAIDA%' THEN -pi.quantidade_bandejas
                ELSE pi.quantidade_bandejas
            END
        ), 0) <> 0
    ORDER BY op.data ASC, pi.op_id ASC
    """))

    saldos = cursor.fetchall()
    conn.close()
    return saldos


def buscar_movimentacoes_estoque_pi(limite=50):
    criar_tabelas_estoque_pi_pa()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM estoque_produto_intermediario
    ORDER BY data_movimentacao DESC, id DESC
    LIMIT ?
    """), (limite,))

    movimentacoes = cursor.fetchall()
    conn.close()
    return movimentacoes


def buscar_caixas_pa(limite=80):
    criar_tabelas_estoque_pi_pa()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM pa_caixas
    ORDER BY id DESC
    LIMIT ?
    """), (limite,))

    caixas = cursor.fetchall()
    conn.close()
    return caixas


def buscar_ops_com_saldo_pi():
    return buscar_saldos_estoque_pi()


def gerar_codigo_caixa():
    criar_tabelas_estoque_pi_pa()

    hoje = datetime.now().strftime("%Y%m%d")
    prefixo = f"CX-{hoje}-"

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT codigo_caixa
    FROM pa_caixas
    WHERE codigo_caixa LIKE ?
    ORDER BY codigo_caixa DESC
    LIMIT 1
    """), (f"{prefixo}%",))

    ultima = cursor.fetchone()
    conn.close()

    if not ultima:
        return f"{prefixo}001"

    try:
        sequencia = int(str(ultima["codigo_caixa"]).split("-")[-1]) + 1
    except Exception:
        sequencia = 1

    return f"{prefixo}{sequencia:03d}"


def obter_sku_op(op_id):
    op = buscar_op_por_id(op_id)
    if not op:
        return None
    return op["sku"] or "Galinha Cortada"


def registrar_saida_pi_por_caixa(cursor, op_id, sku, bandejas, caixa_id):
    cursor.execute(q("""
    INSERT INTO estoque_produto_intermediario (
        data_movimentacao,
        tipo,
        op_id,
        sku,
        quantidade_bandejas,
        origem,
        observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        datetime.now().strftime("%Y-%m-%d"),
        "SAIDA_EMBALAGEM_SECUNDARIA",
        op_id,
        sku,
        float(bandejas or 0),
        "Embalagem Secundária",
        f"Bandejas consumidas na formação da caixa PA #{caixa_id}."
    ))


def parse_numero_form(valor):
    if valor is None:
        return 0.0

    texto = str(valor).strip()
    if not texto:
        return 0.0

    texto = texto.replace(" ", "")
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")

    try:
        return float(texto)
    except ValueError:
        raise ValueError(f"Valor numérico inválido: {valor}")


def calcular_validade_padrao(data_fabricacao):
    if not data_fabricacao:
        return ""

    try:
        data_base = datetime.strptime(data_fabricacao, "%Y-%m-%d")
        try:
            validade = data_base.replace(year=data_base.year + 1)
        except ValueError:
            validade = data_base + timedelta(days=365)
        return validade.strftime("%Y-%m-%d")
    except Exception:
        return ""


def preparar_composicao_caixa(form):
    op_principal = int(form.get("op_principal") or 0)
    bandejas_principal = parse_numero_form(form.get("bandejas_principal") or 0)
    op_complementar_raw = form.get("op_complementar") or ""
    bandejas_complementar = parse_numero_form(form.get("bandejas_complementar") or 0)

    composicao = []

    if op_principal and bandejas_principal > 0:
        composicao.append((op_principal, bandejas_principal))

    if op_complementar_raw and bandejas_complementar > 0:
        op_complementar = int(op_complementar_raw)
        if op_complementar == op_principal:
            raise ValueError("A OP complementar deve ser diferente da OP principal.")
        composicao.append((op_complementar, bandejas_complementar))

    if not composicao:
        raise ValueError("Informe ao menos uma OP e a quantidade de bandejas utilizadas.")

    total_bandejas = sum(qtd for _, qtd in composicao)

    if total_bandejas <= 0 or total_bandejas > BANDEJAS_POR_CAIXA:
        raise ValueError(f"A caixa deve conter entre 1 e {BANDEJAS_POR_CAIXA} bandejas.")

    skus = {obter_sku_op(op_id) for op_id, _ in composicao}
    skus.discard(None)

    if not skus:
        raise ValueError("Não foi possível identificar o SKU das OPs informadas.")

    if len(skus) > 1:
        raise ValueError("Não é permitido formar uma caixa com SKUs diferentes.")

    return composicao, total_bandejas, list(skus)[0]


def validar_saldo_pi_para_composicoes(composicoes):
    consumo_por_op = {}
    for composicao in composicoes:
        for op_id, qtd in composicao:
            consumo_por_op[op_id] = consumo_por_op.get(op_id, 0) + float(qtd or 0)

    saldos = {int(item["op_id"]): float(item["saldo_bandejas"] or 0) for item in buscar_saldos_estoque_pi()}
    for op_id, qtd_total in consumo_por_op.items():
        saldo_disponivel = saldos.get(op_id, 0)
        if qtd_total > saldo_disponivel:
            raise ValueError(
                f"A OP #{op_id} possui apenas {saldo_disponivel:g} bandejas disponíveis em PI. "
                f"O lançamento tentaria consumir {qtd_total:g}."
            )


def inserir_caixa_pa(cursor, codigo_caixa, sku, data_fabricacao, data_validade, peso_bruto, peso_liquido, total_bandejas, observacoes, composicao):
    if DATABASE_URL:
        cursor.execute(q("""
        INSERT INTO pa_caixas (
            codigo_caixa,
            sku,
            data_fabricacao,
            data_validade,
            peso_bruto,
            peso_liquido,
            quantidade_bandejas,
            status,
            origem,
            observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """), (
            codigo_caixa,
            sku,
            data_fabricacao or "",
            data_validade or "",
            peso_bruto,
            peso_liquido,
            total_bandejas,
            "Em estoque",
            "Embalagem Secundária",
            observacoes or ""
        ))
        caixa_id = cursor.fetchone()["id"]
    else:
        cursor.execute(q("""
        INSERT INTO pa_caixas (
            codigo_caixa,
            sku,
            data_fabricacao,
            data_validade,
            peso_bruto,
            peso_liquido,
            quantidade_bandejas,
            status,
            origem,
            observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            codigo_caixa,
            sku,
            data_fabricacao or "",
            data_validade or "",
            peso_bruto,
            peso_liquido,
            total_bandejas,
            "Em estoque",
            "Embalagem Secundária",
            observacoes or ""
        ))
        caixa_id = cursor.lastrowid

    for op_id, qtd in composicao:
        cursor.execute(q("""
        INSERT INTO pa_caixa_composicao (
            caixa_id,
            op_id,
            quantidade_bandejas
        ) VALUES (?, ?, ?)
        """), (caixa_id, op_id, qtd))

        registrar_saida_pi_por_caixa(cursor, op_id, sku, qtd, caixa_id)

    return caixa_id


def registrar_caixa_pa_manual(form):
    criar_tabelas_estoque_pi_pa()

    composicao, total_bandejas, sku = preparar_composicao_caixa(form)
    validar_saldo_pi_para_composicoes([composicao])

    peso_bruto = parse_numero_form(form.get("peso_bruto") or 0)
    peso_liquido = parse_numero_form(form.get("peso_liquido") or 0)

    if peso_bruto <= 0:
        raise ValueError("Informe o peso bruto da caixa.")

    if peso_liquido <= 0:
        peso_liquido = peso_bruto - 0.5

    if peso_liquido <= 0:
        raise ValueError("O peso líquido calculado precisa ser maior que zero.")

    data_fabricacao = form.get("data_fabricacao") or datetime.now().strftime("%Y-%m-%d")
    data_validade = form.get("data_validade") or calcular_validade_padrao(data_fabricacao)
    codigo_caixa = form.get("codigo_caixa") or gerar_codigo_caixa()

    conn = conectar()
    cursor = conn.cursor()

    inserir_caixa_pa(
        cursor,
        codigo_caixa,
        sku,
        data_fabricacao,
        data_validade,
        peso_bruto,
        peso_liquido,
        total_bandejas,
        form.get("observacoes") or "",
        composicao
    )

    conn.commit()
    conn.close()

    return codigo_caixa


def registrar_caixas_pa_lote(form):
    criar_tabelas_estoque_pi_pa()

    composicao, total_bandejas, sku = preparar_composicao_caixa(form)
    linhas = [linha.strip() for linha in (form.get("pesos_brutos_lote") or "").splitlines() if linha.strip()]

    if not linhas:
        raise ValueError("Informe ao menos um peso bruto no lançamento em lote.")

    pesos_brutos = [parse_numero_form(linha) for linha in linhas]
    pesos_liquidos_raw = [linha.strip() for linha in (form.get("pesos_liquidos_lote") or "").splitlines() if linha.strip()]

    if pesos_liquidos_raw and len(pesos_liquidos_raw) != len(pesos_brutos):
        raise ValueError("A lista de pesos líquidos editados deve ter a mesma quantidade de linhas da lista de pesos brutos.")

    pesos_liquidos = []
    for indice, peso_bruto in enumerate(pesos_brutos):
        if peso_bruto <= 0:
            raise ValueError("Todos os pesos brutos do lote precisam ser maiores que zero.")

        if pesos_liquidos_raw:
            peso_liquido = parse_numero_form(pesos_liquidos_raw[indice])
        else:
            peso_liquido = peso_bruto - 0.5

        if peso_liquido <= 0:
            raise ValueError("Todos os pesos líquidos do lote precisam ser maiores que zero.")
        pesos_liquidos.append(peso_liquido)

    validar_saldo_pi_para_composicoes([composicao for _ in pesos_brutos])

    data_fabricacao = form.get("data_fabricacao") or datetime.now().strftime("%Y-%m-%d")
    data_validade = form.get("data_validade") or calcular_validade_padrao(data_fabricacao)
    observacoes = form.get("observacoes") or "Lançamento em lote na Embalagem Secundária"

    codigos = []
    primeiro_codigo = gerar_codigo_caixa()
    try:
        prefixo_codigo = "-".join(primeiro_codigo.split("-")[:-1])
        sequencia_codigo = int(primeiro_codigo.split("-")[-1])
    except Exception:
        prefixo_codigo = f"CX-{datetime.now().strftime('%Y%m%d')}"
        sequencia_codigo = 1

    conn = conectar()
    cursor = conn.cursor()

    for peso_bruto, peso_liquido in zip(pesos_brutos, pesos_liquidos):
        codigo_caixa = f"{prefixo_codigo}-{sequencia_codigo:03d}"
        sequencia_codigo += 1
        inserir_caixa_pa(
            cursor,
            codigo_caixa,
            sku,
            data_fabricacao,
            data_validade,
            peso_bruto,
            peso_liquido,
            total_bandejas,
            observacoes,
            composicao
        )
        codigos.append(codigo_caixa)

    conn.commit()
    conn.close()

    return codigos


def calcular_fechamento_industrial_op(op_id):
    """
    Consolida as validações necessárias para finalizar a Embalagem Secundária
    e encerrar oficialmente a OP.

    Regras:
    1) Aves vivas = bandejas apontadas na Embalagem Primária + descartes/condenações + mortes na gaiola.
    2) Todas as bandejas apontadas na Embalagem Primária precisam ter sido pesadas na Embalagem Secundária.
    3) O peso oficial da OP nasce da soma dos pesos líquidos das caixas PA vinculadas à OP.
    """
    garantir_schema_producao()
    criar_tabelas_estoque_pi_pa()

    op = buscar_op_por_id(op_id)
    if not op:
        raise ValueError("OP não encontrada.")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT COALESCE(SUM(quantidade_bandejas), 0) AS total
    FROM embalagem_primaria_apontamentos
    WHERE op_id = ?
    """), (op_id,))
    bandejas_primaria = float(cursor.fetchone()["total"] or 0)

    cursor.execute(q("""
    SELECT
        COALESCE(SUM(CASE
            WHEN LOWER(COALESCE(categoria, '')) LIKE '%%conden%%' THEN quantidade
            ELSE 0
        END), 0) AS condenacoes,
        COALESCE(SUM(CASE
            WHEN LOWER(COALESCE(categoria, '')) NOT LIKE '%%conden%%'
             AND LOWER(TRIM(COALESCE(motivo, ''))) <> 'morte na gaiola' THEN quantidade
            ELSE 0
        END), 0) AS descartes,
        COALESCE(SUM(CASE
            WHEN LOWER(TRIM(COALESCE(motivo, ''))) = 'morte na gaiola' THEN quantidade
            ELSE 0
        END), 0) AS mortes_na_gaiola
    FROM apontamentos_descartes
    WHERE op_id = ?
      AND LOWER(unidade) IN ('aves', 'ave', 'unidade', 'unidades')
    """), (op_id,))
    perdas = cursor.fetchone()
    condenacoes = float(perdas["condenacoes"] or 0)
    descartes = float(perdas["descartes"] or 0)
    mortes_na_gaiola_descartes = float(perdas["mortes_na_gaiola"] or 0)

    cursor.execute(q("""
    SELECT
        COUNT(DISTINCT cx.id) AS caixas,
        COALESCE(SUM(comp.quantidade_bandejas), 0) AS bandejas_consumidas,
        COALESCE(SUM(cx.peso_liquido), 0) AS peso_liquido_total,
        COALESCE(SUM(cx.peso_bruto), 0) AS peso_bruto_total
    FROM pa_caixa_composicao comp
    INNER JOIN pa_caixas cx ON cx.id = comp.caixa_id
    WHERE comp.op_id = ?
    """), (op_id,))
    caixas = cursor.fetchone()

    conn.close()

    aves_vivas = float(op["quantidade_aves"] or 0)
    mortes_antes_pendura = float(op["mortes_antes_pendura"] or 0) + mortes_na_gaiola_descartes
    caixas_qtd = int(caixas["caixas"] or 0)
    bandejas_consumidas = float(caixas["bandejas_consumidas"] or 0)
    peso_liquido_total = float(caixas["peso_liquido_total"] or 0)
    peso_bruto_total = float(caixas["peso_bruto_total"] or 0)

    total_fechamento_aves = bandejas_primaria + descartes + condenacoes + mortes_antes_pendura
    saldo_aves = aves_vivas - total_fechamento_aves
    saldo_pi = bandejas_primaria - bandejas_consumidas

    tolerancia = 0.0001
    aves_ok = abs(saldo_aves) <= tolerancia
    pi_ok = abs(saldo_pi) <= tolerancia
    possui_peso = peso_liquido_total > 0 and caixas_qtd > 0
    pode_encerrar = aves_ok and pi_ok and possui_peso and op["status"] != "Encerrada"

    pendencias = []
    if not aves_ok:
        pendencias.append(
            f"Balanço de aves divergente em {saldo_aves:g} aves. Revise Embalagem Primária, descartes, condenações ou mortes na gaiola."
        )
    if not pi_ok:
        if saldo_pi > 0:
            pendencias.append(
                f"Existem {saldo_pi:g} bandejas sem pesagem. Lance uma caixa parcial antes de encerrar."
            )
        else:
            pendencias.append(
                f"A Embalagem Secundária consumiu {-saldo_pi:g} bandejas a mais que o PI produzido. Revise as caixas lançadas."
            )
    if not possui_peso:
        pendencias.append("Nenhuma caixa com peso líquido foi registrada para esta OP.")
    if op["status"] == "Encerrada":
        pendencias.append("Esta OP já está encerrada.")

    return {
        "op": op,
        "aves_vivas": aves_vivas,
        "mortes_antes_pendura": mortes_antes_pendura,
        "bandejas_primaria": bandejas_primaria,
        "descartes": descartes,
        "condenacoes": condenacoes,
        "total_fechamento_aves": total_fechamento_aves,
        "saldo_aves": saldo_aves,
        "aves_ok": aves_ok,
        "caixas": caixas_qtd,
        "bandejas_consumidas": bandejas_consumidas,
        "saldo_pi": saldo_pi,
        "pi_ok": pi_ok,
        "peso_liquido_total": peso_liquido_total,
        "peso_bruto_total": peso_bruto_total,
        "possui_peso": possui_peso,
        "pode_encerrar": pode_encerrar,
        "pendencias": pendencias,
    }


def finalizar_embalagem_secundaria_op(op_id):
    fechamento = calcular_fechamento_industrial_op(op_id)

    if not fechamento["pode_encerrar"]:
        raise ValueError("Não foi possível encerrar a OP: " + " ".join(fechamento["pendencias"]))

    op = fechamento["op"]
    unidades_produzidas = fechamento["bandejas_consumidas"]
    kg_produzidos = fechamento["peso_liquido_total"]

    gerar_producao_automatica_setores(
        op=op,
        data_lancamento=op["data"],
        hora_inicio="N/A",
        hora_fim="N/A",
        unidades_produzidas=unidades_produzidas,
        kg_produzidos=kg_produzidos,
        descontar_almoco=False
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

    return fechamento


def validar_reset_processamento_op(op_id):
    """
    Valida se a OP pode voltar ao estado anterior à Embalagem Primária.

    Esta rotina não é uma reabertura de OP encerrada. Ela serve para desfazer
    processamento operacional parcial: Embalagem Primária, PI, Embalagem
    Secundária e caixas PA ainda não expedidas.
    """
    garantir_schema_producao()
    criar_tabelas_estoque_pi_pa()

    op = buscar_op_por_id(op_id)
    if not op:
        raise ValueError("OP não encontrada.")

    if (op["status"] or "") == "Encerrada":
        raise ValueError("Esta OP já está encerrada. O reset operacional só é permitido antes do encerramento.")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT DISTINCT caixa_id
    FROM pa_caixa_composicao
    WHERE op_id = ?
    """), (op_id,))
    caixas_ids = [linha["caixa_id"] for linha in cursor.fetchall()]

    if caixas_ids:
        placeholders = ",".join(["?"] * len(caixas_ids))

        cursor.execute(q(f"""
        SELECT caixa_id, COUNT(DISTINCT op_id) AS total_ops
        FROM pa_caixa_composicao
        WHERE caixa_id IN ({placeholders})
        GROUP BY caixa_id
        HAVING COUNT(DISTINCT op_id) > 1
        """), tuple(caixas_ids))
        caixas_mistas = cursor.fetchall()
        if caixas_mistas:
            conn.close()
            raise ValueError("Não é possível resetar esta OP porque existem caixas mistas vinculadas a outras OPs.")

        cursor.execute(q(f"""
        SELECT codigo_caixa, status
        FROM pa_caixas
        WHERE id IN ({placeholders})
          AND COALESCE(status, '') <> ?
        """), tuple(caixas_ids) + ("Em estoque",))
        caixas_indisponiveis = cursor.fetchall()
        if caixas_indisponiveis:
            conn.close()
            raise ValueError("Não é possível resetar esta OP porque existem caixas que não estão mais em estoque.")

    conn.close()
    return op, caixas_ids


def resetar_processamento_op(op_id, confirmacao):
    if str(confirmacao or "").strip().upper() != "RESETAR":
        raise ValueError("Digite RESETAR para confirmar o reset da OP.")

    op, caixas_ids = validar_reset_processamento_op(op_id)

    conn = conectar()
    cursor = conn.cursor()

    try:
        if caixas_ids:
            placeholders = ",".join(["?"] * len(caixas_ids))

            cursor.execute(q(f"""
            DELETE FROM pa_caixa_composicao
            WHERE caixa_id IN ({placeholders})
            """), tuple(caixas_ids))

            cursor.execute(q(f"""
            DELETE FROM pa_caixas
            WHERE id IN ({placeholders})
            """), tuple(caixas_ids))

        cursor.execute(q("""
        DELETE FROM estoque_produto_intermediario
        WHERE op_id = ?
        """), (op_id,))

        cursor.execute(q("""
        DELETE FROM embalagem_primaria_apontamentos
        WHERE op_id = ?
        """), (op_id,))

        cursor.execute(q("""
        UPDATE ordens_producao
        SET status = ?
        WHERE id = ?
        """), ("Aberta", op_id))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "op": op,
        "caixas_removidas": len(caixas_ids),
    }


def buscar_resumo_pa_completo():
    """
    Calcula o resumo de Produto Acabado usando a base completa de caixas.

    Importante: a listagem visual de caixas pode continuar limitada, mas os
    cards de saldo não podem depender da lista exibida na tela. Por isso o
    resumo é apurado diretamente em pa_caixas, sem LIMIT.
    """
    criar_tabelas_estoque_pi_pa()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        COALESCE(COUNT(CASE WHEN status = ? THEN 1 END), 0) AS saldo_pa_caixas,
        COALESCE(SUM(CASE WHEN status = ? THEN quantidade_bandejas ELSE 0 END), 0) AS saldo_pa_bandejas,
        COALESCE(SUM(CASE WHEN status = ? THEN peso_liquido ELSE 0 END), 0) AS saldo_pa_kg
    FROM pa_caixas
    """), ("Em estoque", "Em estoque", "Em estoque"))

    resumo = cursor.fetchone()
    conn.close()

    return {
        "saldo_pa_caixas": int(resumo["saldo_pa_caixas"] or 0),
        "saldo_pa_bandejas": float(resumo["saldo_pa_bandejas"] or 0),
        "saldo_pa_kg": float(resumo["saldo_pa_kg"] or 0),
    }


def calcular_resumo_estoques_pi_pa(saldos_pi, caixas_pa=None):
    saldo_pi_bandejas = sum(float(item["saldo_bandejas"] or 0) for item in saldos_pi)
    resumo_pa = buscar_resumo_pa_completo()

    return {
        "saldo_pi_bandejas": saldo_pi_bandejas,
        "ops_com_pi": len({item["op_id"] for item in saldos_pi}),
        "saldo_pa_caixas": resumo_pa["saldo_pa_caixas"],
        "saldo_pa_bandejas": resumo_pa["saldo_pa_bandejas"],
        "saldo_pa_kg": resumo_pa["saldo_pa_kg"],
    }


# Compatibilidade temporária com chamadas antigas do Sprint PA-1.
def criar_tabela_estoque_produto_acabado():
    criar_tabelas_estoque_pi_pa()


def remover_movimentacoes_estoque_pa_por_op(op_id):
    remover_movimentacoes_estoque_pi_por_op(op_id)


def registrar_entrada_estoque_pa_op(op, unidades_produzidas, kg_produzidos=None):
    registrar_entrada_estoque_pi_op(op, unidades_produzidas)


def buscar_saldos_estoque_pa():
    return buscar_saldos_estoque_pi()


def buscar_movimentacoes_estoque_pa(limite=50):
    return buscar_movimentacoes_estoque_pi(limite)


def calcular_resumo_estoque_pa(saldos):
    caixas = buscar_caixas_pa()
    return calcular_resumo_estoques_pi_pa(saldos, caixas)


def buscar_expedicoes(data_inicio=None, data_fim=None, status=None):
    criar_tabelas_expedicao()

    filtros = []
    parametros = []

    if data_inicio:
        filtros.append("data >= ?")
        parametros.append(data_inicio)

    if data_fim:
        filtros.append("data <= ?")
        parametros.append(data_fim)

    if status and status != "Todos":
        filtros.append("status = ?")
        parametros.append(status)

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT
        e.*,
        COALESCE(COUNT(i.id), 0) as total_itens,
        COALESCE(SUM(i.quantidade_unidades), 0) as total_unidades,
        COALESCE(SUM(i.quantidade_kg), 0) as total_kg
    FROM expedicoes e
    LEFT JOIN expedicao_itens i ON i.expedicao_id = e.id
    {where}
    GROUP BY e.id, e.numero_romaneio, e.data, e.tipo_movimentacao, e.destino, e.responsavel, e.observacoes, e.status, e.criado_em
    ORDER BY e.data DESC, e.id DESC
    """), tuple(parametros))

    expedicoes = cursor.fetchall()
    conn.close()
    return expedicoes


def calcular_resumo_expedicao(expedicoes):
    total_romaneios = len(expedicoes)
    abertos = sum(1 for item in expedicoes if item["status"] == "Aberto")
    concluidos = sum(1 for item in expedicoes if item["status"] == "Concluído")
    cancelados = sum(1 for item in expedicoes if item["status"] == "Cancelado")

    total_unidades = sum(float(item["total_unidades"] or 0) for item in expedicoes)
    total_kg = sum(float(item["total_kg"] or 0) for item in expedicoes)

    return {
        "total_romaneios": total_romaneios,
        "abertos": abertos,
        "concluidos": concluidos,
        "cancelados": cancelados,
        "total_unidades": round(total_unidades, 2),
        "total_kg": round(total_kg, 2)
    }

def gerar_numero_romaneio(data_romaneio):
    """
    Gera número sequencial diário do romaneio.
    Formato: ROM-AAAAMMDD-001

    Sprint 1.1:
    - Numeração simples e isolada.
    - Não baixa estoque.
    - Não gera venda.
    - Não interfere em DRE, Financeiro ou Almoxarifado.
    """
    criar_tabelas_expedicao()

    data_base = (data_romaneio or datetime.now().strftime("%Y-%m-%d")).strip()
    prefixo = "ROM-" + data_base.replace("-", "")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT COUNT(*) as total
    FROM expedicoes
    WHERE numero_romaneio LIKE ?
    """), (f"{prefixo}-%",))

    resultado = cursor.fetchone()
    conn.close()

    total = int(resultado["total"] or 0)
    sequencial = total + 1

    return f"{prefixo}-{sequencial:03d}"


def salvar_romaneio_expedicao(form):
    """
    Salva apenas o cabeçalho do romaneio.

    Sprint 1.1:
    - Cria o romaneio em aberto.
    - Tipo fixo: TRANSFERENCIA.
    - Sem itens.
    - Sem baixa de estoque.
    """
    criar_tabelas_expedicao()

    data_romaneio = (form.get("data") or "").strip()
    destino = (form.get("destino") or "").strip()
    responsavel = (form.get("responsavel") or "").strip()
    observacoes = (form.get("observacoes") or "").strip()

    if not data_romaneio:
        raise ValueError("Informe a data do romaneio.")

    if not destino:
        raise ValueError("Informe o destino do romaneio.")

    numero_romaneio = gerar_numero_romaneio(data_romaneio)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO expedicoes (
        numero_romaneio,
        data,
        tipo_movimentacao,
        destino,
        responsavel,
        observacoes,
        status
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        numero_romaneio,
        data_romaneio,
        "TRANSFERENCIA",
        destino,
        responsavel,
        observacoes,
        "Aberto"
    ))

    conn.commit()
    conn.close()

    return numero_romaneio

def buscar_expedicao_por_id(expedicao_id):
    criar_tabelas_expedicao()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM expedicoes
    WHERE id = ?
    """), (expedicao_id,))

    expedicao = cursor.fetchone()
    conn.close()

    return expedicao


def buscar_itens_expedicao(expedicao_id):
    criar_tabelas_expedicao()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM expedicao_itens
    WHERE expedicao_id = ?
    ORDER BY id ASC
    """), (expedicao_id,))

    itens = cursor.fetchall()
    conn.close()

    return itens


def calcular_resumo_itens_expedicao(itens):
    total_itens = len(itens)
    total_unidades = sum(float(item["quantidade_unidades"] or 0) for item in itens)
    total_kg = sum(float(item["quantidade_kg"] or 0) for item in itens)

    return {
        "total_itens": total_itens,
        "total_unidades": round(total_unidades, 2),
        "total_kg": round(total_kg, 2)
    }


def salvar_item_expedicao(expedicao_id, form):
    """
    Salva item manual do romaneio.

    Sprint 1.2:
    - Itens manuais.
    - Sem baixa de estoque.
    - Sem vínculo obrigatório com OP.
    - Sem impacto na DRE, Financeiro ou Almoxarifado.
    """
    criar_tabelas_expedicao()

    expedicao = buscar_expedicao_por_id(expedicao_id)

    if not expedicao:
        raise ValueError("Romaneio não encontrado.")

    if expedicao["status"] != "Aberto":
        raise ValueError("Só é possível adicionar itens em romaneios abertos.")

    sku = (form.get("sku") or "").strip()
    quantidade_unidades = float(form.get("quantidade_unidades") or 0)
    quantidade_kg = float(form.get("quantidade_kg") or 0)

    if sku not in ["Galinha Cortada", "Galinha Inteira"]:
        raise ValueError("Selecione um SKU válido.")

    if quantidade_unidades < 0 or quantidade_kg < 0:
        raise ValueError("As quantidades não podem ser negativas.")

    if quantidade_unidades <= 0 and quantidade_kg <= 0:
        raise ValueError("Informe pelo menos uma quantidade para o item.")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO expedicao_itens (
        expedicao_id,
        op_id,
        sku,
        quantidade_unidades,
        quantidade_kg
    ) VALUES (?, ?, ?, ?, ?)
    """), (
        expedicao_id,
        None,
        sku,
        quantidade_unidades,
        quantidade_kg
    ))

    conn.commit()
    conn.close()
