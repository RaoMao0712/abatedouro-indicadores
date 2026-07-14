"""Plano de Contas Mestre do FrigoDatta."""

import re
import unicodedata
from datetime import datetime

from database import DATABASE_URL, conectar, q
from database.migrations import executar_alteracao_segura


LINHA_RECEITA_BRUTA = "Receita Bruta"
LINHA_DEDUCOES_RECEITA = "Deducoes da Receita"
LINHA_CMV = "CMV"
LINHA_DESPESAS_OPERACIONAIS = "Despesas Operacionais"
LINHA_RESULTADO_NAO_OPERACIONAL = "Resultado Nao Operacional"
LINHA_NEUTRA = "Neutro"


def _normalizar(texto):
    texto = str(texto or "").strip().lower()
    substituicoes = {
        "Ã£": "a", "Ã¡": "a", "Ã ": "a", "Ã¢": "a",
        "Ã©": "e", "Ãª": "e", "Ã­": "i",
        "Ã³": "o", "Ã´": "o", "Ãµ": "o", "Ãº": "u",
        "Ã§": "c", "ç": "c",
    }
    for origem, destino in substituicoes.items():
        texto = texto.replace(origem, destino)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _tipo_sem_acento(tipo):
    return "Saida" if _normalizar(tipo) == "saida" else (tipo or "")


def conta_mestre(
    id,
    grupo_gerencial,
    categoria,
    subcategoria="",
    centro_analise_opcional="",
    linha_dre=LINHA_NEUTRA,
    tipo_conta="Neutro",
    aceita_subcategoria=False,
    aceita_centro_analise=False,
    ativo=True,
    ordem_exibicao=0,
    aliases=None,
    formacao_estoque=False,
    cmv=False,
    imobilizado=False,
    financeiro=False,
    transferencia_neutro=False,
    impacta_fluxo_caixa=True,
):
    nome = categoria if not subcategoria else f"{categoria} - {subcategoria}"
    impacta_dre = linha_dre not in ("", LINHA_NEUTRA)
    impacta_resultado_operacional = linha_dre == LINHA_DESPESAS_OPERACIONAIS
    tipo_normalizado = _tipo_sem_acento(tipo_conta)
    return {
        "id": id,
        "grupo_gerencial": grupo_gerencial,
        "categoria": categoria,
        "subcategoria": subcategoria,
        "centro_analise_opcional": centro_analise_opcional,
        "linha_dre": linha_dre,
        "tipo_conta": tipo_normalizado,
        "aceita_subcategoria": bool(aceita_subcategoria),
        "aceita_centro_analise": bool(aceita_centro_analise),
        "ativo": bool(ativo),
        "ordem_exibicao": ordem_exibicao,
        "aliases": aliases or [],
        "nome": nome,
        "grupo": grupo_gerencial,
        "natureza": tipo_normalizado,
        "impacta_dre": impacta_dre,
        "impacta_resultado_operacional": impacta_resultado_operacional,
        "impacta_fluxo_caixa": bool(impacta_fluxo_caixa),
        "formacao_estoque": bool(formacao_estoque),
        "cmv": bool(cmv),
        "imobilizado": bool(imobilizado),
        "financeiro": bool(financeiro),
        "transferencia_neutro": bool(transferencia_neutro),
    }


PLANO_CONTAS_MESTRE = [
    conta_mestre(1001, "Receita Operacional", "Venda de Producao Propria", linha_dre=LINHA_RECEITA_BRUTA, tipo_conta="Entrada", ordem_exibicao=10, aliases=["Receita Bruta", "Venda de Produtos", "Recebimento de cliente"]),
    conta_mestre(1002, "Receita Operacional", "Venda de Mercadorias", linha_dre=LINHA_RECEITA_BRUTA, tipo_conta="Entrada", ordem_exibicao=20),

    conta_mestre(2001, "Deducoes da Receita", "Devolucoes", linha_dre=LINHA_DEDUCOES_RECEITA, tipo_conta="Saida", ordem_exibicao=30),
    conta_mestre(2002, "Deducoes da Receita", "Bonificacoes", linha_dre=LINHA_DEDUCOES_RECEITA, tipo_conta="Saida", ordem_exibicao=40),
    conta_mestre(2003, "Deducoes da Receita", "Descontos", linha_dre=LINHA_DEDUCOES_RECEITA, tipo_conta="Saida", ordem_exibicao=50),
    conta_mestre(2004, "Deducoes da Receita", "Tributos sobre Vendas", linha_dre=LINHA_DEDUCOES_RECEITA, tipo_conta="Saida", ordem_exibicao=60, aliases=["Impostos sobre Vendas"]),

    conta_mestre(3001, "CMV", "Materia Prima", linha_dre=LINHA_CMV, tipo_conta="Saida", ordem_exibicao=70, aliases=["Galinha Viva", "Insumos para Producao"], formacao_estoque=True, cmv=True),
    conta_mestre(3002, "CMV", "Embalagens", linha_dre=LINHA_CMV, tipo_conta="Saida", ordem_exibicao=80, formacao_estoque=True, cmv=True),

    conta_mestre(4001, "Despesas Operacionais", "Energia", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=100),
    conta_mestre(4002, "Despesas Operacionais", "Agua", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=110),
    conta_mestre(4003, "Despesas Operacionais", "Combustivel", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=120),
    conta_mestre(4004, "Despesas Operacionais", "Lenha", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=130),
    conta_mestre(4005, "Despesas Operacionais", "Manutencao Predial", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=140, aliases=["Manutencao Predial", "Manutenção Predial"]),
    conta_mestre(4006, "Despesas Operacionais", "Manutencao de Equipamentos", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=150, aliases=["Manutencao", "Manutencao Equipamentos", "Manutenção de Equipamentos"]),
    conta_mestre(4007, "Despesas Operacionais", "Manutencao de Veiculos", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=160),
    conta_mestre(4101, "Despesas Operacionais", "Mao de Obra", "CLT", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=170, aliases=["Mao de Obra", "Salarios CLT", "Salários CLT", "Folha de Pagamento"]),
    conta_mestre(4102, "Despesas Operacionais", "Mao de Obra", "Encargos", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=180, aliases=["FGTS", "INSS", "IRRF", "Darf Previdenciario", "DARF Previdenciário", "Encargos Trabalhistas"]),
    conta_mestre(4103, "Despesas Operacionais", "Mao de Obra", "13o Salario", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=190),
    conta_mestre(4104, "Despesas Operacionais", "Mao de Obra", "Ferias", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=200, aliases=["Férias", "Ferias + 1/3"]),
    conta_mestre(4105, "Despesas Operacionais", "Mao de Obra", "Rescisoes", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=210, aliases=["Rescisao", "Rescisão", "Rescisorio", "Rescisório", "Termo de Rescisao", "Termo de Rescisão", "Acordo Trabalhista", "Acordo Judicial"]),
    conta_mestre(4106, "Despesas Operacionais", "Mao de Obra", "Terceiros", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=220, aliases=["Terceirizados", "Servicos Terceiros", "Serviços Terceiros"]),
    conta_mestre(4201, "Despesas Operacionais", "Servicos", "Transporte", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=230, aliases=["Servicos", "Fornecedor"]),
    conta_mestre(4202, "Despesas Operacionais", "Servicos", "Alimentacao", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=240),
    conta_mestre(4203, "Despesas Operacionais", "Servicos", "Analises Laboratoriais", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=250),
    conta_mestre(4204, "Despesas Operacionais", "Servicos", "CSC", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=260),
    conta_mestre(4205, "Despesas Operacionais", "Servicos", "Coleta de Residuos", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=270),
    conta_mestre(4206, "Despesas Operacionais", "Servicos", "Outros", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", aceita_subcategoria=True, ordem_exibicao=280),
    conta_mestre(4301, "Despesas Operacionais", "Produtos Quimicos", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=290),
    conta_mestre(4302, "Despesas Operacionais", "Limpeza", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=300, aliases=["Material de Limpeza", "Produtos de Limpeza"]),
    conta_mestre(4303, "Despesas Operacionais", "EPIs", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=310, aliases=["EPI", "Equipamentos de Protecao Individual", "Equipamentos de Proteção Individual"]),
    conta_mestre(4304, "Despesas Operacionais", "Uniformes", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=320, aliases=["Uniforme"]),
    conta_mestre(4305, "Despesas Operacionais", "Qualidade", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=330),
    conta_mestre(4306, "Despesas Operacionais", "Seguranca", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=340, aliases=["Seguranca do Trabalho", "Licencas Operacionais"]),
    conta_mestre(4307, "Despesas Operacionais", "Escritorio", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=350, aliases=["Material de Escritorio"]),
    conta_mestre(4308, "Despesas Operacionais", "Telefonia", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=360),
    conta_mestre(4309, "Despesas Operacionais", "Internet", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=370),
    conta_mestre(4310, "Despesas Operacionais", "Sistemas", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=380),
    conta_mestre(4311, "Despesas Operacionais", "Viagens", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=390, aliases=["Despesas com Viagens"]),
    conta_mestre(4312, "Despesas Operacionais", "Outras Despesas Operacionais", linha_dre=LINHA_DESPESAS_OPERACIONAIS, tipo_conta="Saida", ordem_exibicao=400, aliases=["Outras saidas", "Cursos e Treinamentos", "Consultoria", "Responsabilidade Tecnica", "Responsabilidade Técnica", "Consultoria e Responsabilidade Tecnica", "Contratos com Clientes", "Uso e Consumo"]),

    conta_mestre(5001, "Resultado Nao Operacional", "Receitas Financeiras", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Entrada", ordem_exibicao=500, financeiro=True),
    conta_mestre(5002, "Resultado Nao Operacional", "Despesas Financeiras", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Saida", ordem_exibicao=510, aliases=["Juros", "Tarifas Bancarias", "IOF"], financeiro=True),
    conta_mestre(5003, "Resultado Nao Operacional", "Aportes", linha_dre=LINHA_NEUTRA, tipo_conta="Entrada", ordem_exibicao=520, aliases=["Aporte"], transferencia_neutro=True),
    conta_mestre(5004, "Resultado Nao Operacional", "Transferencias", linha_dre=LINHA_NEUTRA, tipo_conta="Neutro", ordem_exibicao=530, aliases=["Mutuos", "Transferencias entre contas", "Transferencia entre contas da empresa"], transferencia_neutro=True, impacta_fluxo_caixa=False),
    conta_mestre(5005, "Resultado Nao Operacional", "Investimentos", linha_dre=LINHA_NEUTRA, tipo_conta="Saida", ordem_exibicao=540, imobilizado=True),
    conta_mestre(5006, "Resultado Nao Operacional", "Equipamentos", linha_dre=LINHA_NEUTRA, tipo_conta="Saida", ordem_exibicao=550, aliases=["Aquisicao de Equipamentos", "Aquisição de Equipamentos"], imobilizado=True),
    conta_mestre(5007, "Resultado Nao Operacional", "Veiculos", linha_dre=LINHA_NEUTRA, tipo_conta="Saida", ordem_exibicao=560, imobilizado=True),
    conta_mestre(5008, "Resultado Nao Operacional", "Obras e Benfeitorias", linha_dre=LINHA_NEUTRA, tipo_conta="Saida", ordem_exibicao=570, aliases=["Obras", "Reformas", "Maquinas", "Benfeitorias"], imobilizado=True),
    conta_mestre(5009, "Resultado Nao Operacional", "Ganhos Extraordinarios", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Entrada", ordem_exibicao=580),
    conta_mestre(5010, "Resultado Nao Operacional", "Perdas Extraordinarias", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Saida", ordem_exibicao=590),
    conta_mestre(5011, "Resultado Nao Operacional", "Marketing", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Saida", ordem_exibicao=600, aliases=["Comercial Marketing"]),
    conta_mestre(5012, "Resultado Nao Operacional", "Despesas Comerciais", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Saida", ordem_exibicao=610),
    conta_mestre(5013, "Resultado Nao Operacional", "Comissoes", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Saida", ordem_exibicao=620),
    conta_mestre(5014, "Resultado Nao Operacional", "Multas", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Saida", ordem_exibicao=630),
    conta_mestre(5015, "Resultado Nao Operacional", "Impostos", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Saida", ordem_exibicao=640, aliases=["Impostos e Taxas", "Encargos Tributarios", "Encargos Tributários"]),
    conta_mestre(5016, "Resultado Nao Operacional", "Taxas", linha_dre=LINHA_RESULTADO_NAO_OPERACIONAL, tipo_conta="Saida", ordem_exibicao=650),

    conta_mestre(9001, "Transferencias", "Retiradas", linha_dre=LINHA_NEUTRA, tipo_conta="Saida", ordem_exibicao=900, transferencia_neutro=True),
    conta_mestre(9002, "Transferencias", "Adiantamentos", linha_dre=LINHA_NEUTRA, tipo_conta="Saida", ordem_exibicao=910, transferencia_neutro=True),
    conta_mestre(9003, "Financeiro", "Emprestimos", linha_dre=LINHA_NEUTRA, tipo_conta="Saida", ordem_exibicao=920, aliases=["Emprestimos e financiamentos", "Financiamentos", "Emprestimo recebido", "Emprestimos Recebidos", "Amortizacao de Emprestimos"], financeiro=True),
]


INDICE_PLANO_CONTAS_ID = {item["id"]: item for item in PLANO_CONTAS_MESTRE}
INDICE_PLANO_CONTAS = {}
for item in PLANO_CONTAS_MESTRE:
    chaves = [item["nome"], item["categoria"], f"{item['grupo_gerencial']} {item['categoria']} {item['subcategoria']}"]
    chaves.extend(item.get("aliases", []))
    for chave in chaves:
        INDICE_PLANO_CONTAS.setdefault(_normalizar(chave), item)


def listar_plano_contas():
    return sorted(PLANO_CONTAS_MESTRE, key=lambda item: (item["ordem_exibicao"], item["id"]))


def buscar_conta_gerencial(nome):
    return INDICE_PLANO_CONTAS.get(_normalizar(nome))


def buscar_conta_mestre_por_id(plano_conta_id):
    try:
        return INDICE_PLANO_CONTAS_ID.get(int(plano_conta_id))
    except (TypeError, ValueError):
        return None


def resolver_conta_plano(categoria=None, plano_conta_id=None):
    return buscar_conta_mestre_por_id(plano_conta_id) or buscar_conta_gerencial(categoria)


def campos_derivados_conta(conta):
    if not conta:
        return {
            "plano_conta_id": None,
            "grupo_gerencial": "",
            "categoria_plano": "",
            "subcategoria": "",
            "centro_analise": "",
            "linha_dre": "",
            "tipo_conta": "",
            "impacta_fluxo_caixa": True,
            "categoria_movimentacao": "",
        }
    return {
        "plano_conta_id": conta["id"],
        "grupo_gerencial": conta["grupo_gerencial"],
        "categoria_plano": conta["categoria"],
        "subcategoria": conta["subcategoria"],
        "centro_analise": conta["centro_analise_opcional"],
        "linha_dre": conta["linha_dre"],
        "tipo_conta": conta["tipo_conta"],
        "impacta_fluxo_caixa": conta["impacta_fluxo_caixa"],
        "categoria_movimentacao": conta["nome"],
    }


def categoria_impacta_resultado_operacional(nome):
    conta_gerencial = buscar_conta_gerencial(nome)
    return bool(conta_gerencial and conta_gerencial["impacta_resultado_operacional"])


def categorias_por_natureza(natureza):
    natureza_normalizada = _normalizar(natureza)
    return [
        item["nome"]
        for item in listar_plano_contas()
        if _normalizar(item["natureza"]) == natureza_normalizada
    ]


def categorias_entradas_financeiras():
    return categorias_por_natureza("Entrada")


def categorias_saidas_financeiras():
    return categorias_por_natureza("Saida")


def categorias_custos_operacionais():
    return [
        item["nome"]
        for item in listar_plano_contas()
        if item["linha_dre"] == LINHA_DESPESAS_OPERACIONAIS
    ]


def opcoes_reclassificacao_plano():
    return [
        {
            "id": item["id"],
            "label": " / ".join(
                parte
                for parte in [item["grupo_gerencial"], item["categoria"], item["subcategoria"]]
                if parte
            ),
            **item,
        }
        for item in listar_plano_contas()
        if item["ativo"]
    ]


def agrupar_plano_contas():
    grupos = {}
    for item in listar_plano_contas():
        grupos.setdefault(item["grupo_gerencial"], []).append(item)
    return grupos


def criar_tabela_plano_contas_mestre():
    conn = conectar()
    cursor = conn.cursor()
    timestamp_col = "TIMESTAMP" if DATABASE_URL else "TEXT"
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS plano_contas_mestre (
        id INTEGER PRIMARY KEY,
        grupo_gerencial TEXT NOT NULL,
        categoria TEXT NOT NULL,
        subcategoria TEXT,
        centro_analise_opcional TEXT,
        linha_dre TEXT NOT NULL,
        tipo_conta TEXT NOT NULL,
        impacta_dre INTEGER DEFAULT 1,
        impacta_fluxo_caixa INTEGER DEFAULT 1,
        aceita_subcategoria INTEGER DEFAULT 0,
        aceita_centro_analise INTEGER DEFAULT 0,
        ativo INTEGER DEFAULT 1,
        ordem_exibicao INTEGER DEFAULT 0,
        criado_em {timestamp_col} DEFAULT CURRENT_TIMESTAMP,
        atualizado_em {timestamp_col} DEFAULT CURRENT_TIMESTAMP
    )
    """)
    executar_alteracao_segura(cursor, conn, "CREATE INDEX IF NOT EXISTS idx_plano_contas_mestre_linha_dre ON plano_contas_mestre (linha_dre)")
    executar_alteracao_segura(cursor, conn, "CREATE INDEX IF NOT EXISTS idx_plano_contas_mestre_categoria ON plano_contas_mestre (categoria, subcategoria)")
    executar_alteracao_segura(cursor, conn, "ALTER TABLE plano_contas_mestre ADD COLUMN impacta_dre INTEGER DEFAULT 1")
    executar_alteracao_segura(cursor, conn, "ALTER TABLE plano_contas_mestre ADD COLUMN impacta_fluxo_caixa INTEGER DEFAULT 1")

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    valores = [
        (
            item["id"], item["grupo_gerencial"], item["categoria"], item["subcategoria"],
            item["centro_analise_opcional"], item["linha_dre"], item["tipo_conta"],
            int(item["impacta_dre"]), int(item["impacta_fluxo_caixa"]),
            int(item["aceita_subcategoria"]), int(item["aceita_centro_analise"]),
            int(item["ativo"]), item["ordem_exibicao"], agora, agora,
        )
        for item in listar_plano_contas()
    ]

    if DATABASE_URL:
        cursor.executemany(q("""
        INSERT INTO plano_contas_mestre (
            id, grupo_gerencial, categoria, subcategoria, centro_analise_opcional,
            linha_dre, tipo_conta, impacta_dre, impacta_fluxo_caixa,
            aceita_subcategoria, aceita_centro_analise,
            ativo, ordem_exibicao, criado_em, atualizado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            grupo_gerencial = EXCLUDED.grupo_gerencial,
            categoria = EXCLUDED.categoria,
            subcategoria = EXCLUDED.subcategoria,
            centro_analise_opcional = EXCLUDED.centro_analise_opcional,
            linha_dre = EXCLUDED.linha_dre,
            tipo_conta = EXCLUDED.tipo_conta,
            impacta_dre = EXCLUDED.impacta_dre,
            impacta_fluxo_caixa = EXCLUDED.impacta_fluxo_caixa,
            aceita_subcategoria = EXCLUDED.aceita_subcategoria,
            aceita_centro_analise = EXCLUDED.aceita_centro_analise,
            ativo = EXCLUDED.ativo,
            ordem_exibicao = EXCLUDED.ordem_exibicao,
            atualizado_em = EXCLUDED.atualizado_em
        """), valores)
    else:
        cursor.executemany(q("""
        INSERT INTO plano_contas_mestre (
            id, grupo_gerencial, categoria, subcategoria, centro_analise_opcional,
            linha_dre, tipo_conta, impacta_dre, impacta_fluxo_caixa,
            aceita_subcategoria, aceita_centro_analise,
            ativo, ordem_exibicao, criado_em, atualizado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            grupo_gerencial = excluded.grupo_gerencial,
            categoria = excluded.categoria,
            subcategoria = excluded.subcategoria,
            centro_analise_opcional = excluded.centro_analise_opcional,
            linha_dre = excluded.linha_dre,
            tipo_conta = excluded.tipo_conta,
            impacta_dre = excluded.impacta_dre,
            impacta_fluxo_caixa = excluded.impacta_fluxo_caixa,
            aceita_subcategoria = excluded.aceita_subcategoria,
            aceita_centro_analise = excluded.aceita_centro_analise,
            ativo = excluded.ativo,
            ordem_exibicao = excluded.ordem_exibicao,
            atualizado_em = excluded.atualizado_em
        """), valores)
    conn.commit()
    conn.close()


def diagnostico_categorias_legadas():
    return {
        "duplicadas": [
            "Manutencao consolidada em Manutencao de Equipamentos/Predial/Veiculos",
            "Viagens e Despesas com Viagens consolidadas em Viagens",
            "Obras, Reformas, Maquinas e Benfeitorias consolidadas em Obras e Benfeitorias",
        ],
        "ambiguas": [
            "Fornecedor direcionado para Servicos - Transporte quando nao houver detalhe",
            "Outras saidas direcionado para Outras Despesas Operacionais",
            "Mao de Obra sem detalhe direcionado para Mao de Obra - CLT",
        ],
        "tratamento_incorreto_corrigido": [
            "Receita Bruta passa a ser linha_dre do Plano de Contas, nao origem_importacao",
            "Aportes e Transferencias ficam fora da Receita Bruta operacional",
            "Marketing, impostos, taxas e investimentos ficam fora do Resultado Operacional",
            "CMV permanece como linha estrutural com calculo congelado pela regra atual",
        ],
    }
