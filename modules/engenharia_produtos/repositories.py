"""Persistência retrocompatível da Engenharia de Produtos."""

import json

from database import DATABASE_URL, conectar, q
from database.migrations import executar_alteracao_segura
from modules.almoxarifado.services import criar_tabelas_estoque_almoxarifado


def _pk():
    return "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _timestamp():
    return "TIMESTAMP" if DATABASE_URL else "TEXT"


def _alterar(cursor, conn, postgres, sqlite=None):
    executar_alteracao_segura(cursor, conn, postgres if DATABASE_URL else (sqlite or postgres))


def criar_estrutura():
    """Evolui as tabelas legadas sem apagar ou renomear contratos existentes."""
    criar_tabelas_estoque_almoxarifado()
    conn = conectar()
    cursor = conn.cursor()
    pk = _pk()
    timestamp = _timestamp()

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS skus (
            id {pk},
            nome TEXT NOT NULL UNIQUE,
            unidade_venda TEXT NOT NULL DEFAULT 'Kg',
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT,
            criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS receitas_sku (
            id {pk},
            sku_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            quantidade_por_unidade REAL NOT NULL,
            tipo_consumo TEXT DEFAULT '',
            observacoes TEXT,
            criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    for coluna, tipo in (
        ("codigo", "TEXT"),
        ("tipo_produto", "TEXT DEFAULT 'PRODUTO_ACABADO'"),
        ("atualizado_em", f"{timestamp}"),
        ("excluido_em", f"{timestamp}"),
    ):
        _alterar(
            cursor,
            conn,
            f"ALTER TABLE skus ADD COLUMN IF NOT EXISTS {coluna} {tipo}",
            f"ALTER TABLE skus ADD COLUMN {coluna} {tipo}",
        )

    for coluna, tipo in (
        ("unidade", "TEXT"),
        ("fator_proporcao", "REAL"),
        ("percentual_perda", "REAL"),
        ("status", "TEXT DEFAULT 'Ativo'"),
        ("data_vigencia", "TEXT"),
        ("usuario_responsavel", "TEXT"),
        ("atualizado_em", f"{timestamp}"),
        ("removido_em", f"{timestamp}"),
    ):
        _alterar(
            cursor,
            conn,
            f"ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS {coluna} {tipo}",
            f"ALTER TABLE receitas_sku ADD COLUMN {coluna} {tipo}",
        )

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS processos_produtivos (
            id {pk},
            codigo TEXT NOT NULL UNIQUE,
            nome TEXT NOT NULL,
            descricao TEXT,
            setor TEXT,
            status TEXT NOT NULL DEFAULT 'Ativo',
            observacoes TEXT,
            criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP,
            atualizado_em {timestamp} DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS engenharia_produtos_historico (
            id {pk},
            entidade TEXT NOT NULL,
            entidade_id INTEGER NOT NULL,
            acao TEXT NOT NULL,
            usuario_id INTEGER,
            usuario_nome TEXT,
            valores_anteriores TEXT,
            valores_novos TEXT,
            criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # Todo SKU legado permanece sendo produto. Como não havia discriminador confiável,
    # não se convertem nomes em processos por heurística.
    cursor.execute("""
        UPDATE skus
        SET codigo = 'LEG-' || id
        WHERE codigo IS NULL OR TRIM(codigo) = ''
    """)
    cursor.execute("""
        UPDATE skus
        SET tipo_produto = 'PRODUTO_ACABADO'
        WHERE tipo_produto IS NULL OR TRIM(tipo_produto) = ''
    """)
    cursor.execute("""
        UPDATE skus
        SET atualizado_em = COALESCE(atualizado_em, criado_em, CURRENT_TIMESTAMP)
    """)
    cursor.execute("""
        UPDATE receitas_sku
        SET tipo_consumo = CASE
            WHEN tipo_consumo IN ('FIXO_UNIDADE','POR_KG','POR_CAIXA','PROPORCIONAL',
                                  'PERCENTUAL','PERDA_ESPERADA','OPCIONAL') THEN tipo_consumo
            WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%proporcional%' THEN 'PROPORCIONAL'
            WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%perda%' THEN 'PERDA_ESPERADA'
            WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%outro%' THEN 'OPCIONAL'
            ELSE 'FIXO_UNIDADE'
        END,
        unidade = COALESCE(
            NULLIF(unidade, ''),
            (SELECT unidade FROM almoxarifado_insumos i WHERE i.id = receitas_sku.insumo_id),
            'Un'
        ),
        status = COALESCE(NULLIF(status, ''), 'Ativo'),
        data_vigencia = COALESCE(NULLIF(data_vigencia, ''), SUBSTR(CAST(criado_em AS TEXT), 1, 10)),
        atualizado_em = COALESCE(atualizado_em, criado_em, CURRENT_TIMESTAMP)
    """)
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_skus_codigo_ci ON skus (LOWER(codigo))")
    except Exception:
        conn.rollback()
    conn.commit()
    conn.close()


def _linha_dict(linha):
    return dict(linha) if linha else None


def listar_produtos(filtros=None):
    filtros = filtros or {}
    condicoes = ["s.excluido_em IS NULL"]
    parametros = []
    if filtros.get("status") in {"Sim", "Não"}:
        condicoes.append("s.ativo = ?")
        parametros.append(filtros["status"])
    if filtros.get("tipo"):
        condicoes.append("s.tipo_produto = ?")
        parametros.append(filtros["tipo"])
    if filtros.get("unidade"):
        condicoes.append("s.unidade_venda = ?")
        parametros.append(filtros["unidade"])
    if filtros.get("estrutura") == "com":
        condicoes.append("EXISTS (SELECT 1 FROM receitas_sku r WHERE r.sku_id=s.id AND r.status='Ativo' AND r.removido_em IS NULL)")
    elif filtros.get("estrutura") == "sem":
        condicoes.append("NOT EXISTS (SELECT 1 FROM receitas_sku r WHERE r.sku_id=s.id AND r.status='Ativo' AND r.removido_em IS NULL)")
    if filtros.get("pesquisa"):
        condicoes.append("(LOWER(s.nome) LIKE ? OR LOWER(s.codigo) LIKE ?)")
        termo = f"%{filtros['pesquisa'].lower()}%"
        parametros.extend([termo, termo])

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
        SELECT s.*,
               COUNT(CASE WHEN r.status='Ativo' AND r.removido_em IS NULL THEN 1 END) AS total_itens_ativos
        FROM skus s
        LEFT JOIN receitas_sku r ON r.sku_id = s.id
        WHERE {' AND '.join(condicoes)}
        GROUP BY s.id
        ORDER BY CASE WHEN s.ativo='Sim' THEN 0 ELSE 1 END, s.nome
    """), tuple(parametros))
    linhas = cursor.fetchall()
    conn.close()
    return linhas


def buscar_produto(produto_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM skus WHERE id=? AND excluido_em IS NULL"), (produto_id,))
    linha = cursor.fetchone()
    conn.close()
    return linha


def buscar_produto_por_codigo(codigo, ignorar_id=None):
    conn = conectar()
    cursor = conn.cursor()
    sql = "SELECT * FROM skus WHERE LOWER(codigo)=LOWER(?) AND excluido_em IS NULL"
    parametros = [codigo]
    if ignorar_id:
        sql += " AND id<>?"
        parametros.append(ignorar_id)
    cursor.execute(q(sql), tuple(parametros))
    linha = cursor.fetchone()
    conn.close()
    return linha


def inserir_produto(dados):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        INSERT INTO skus (codigo, nome, tipo_produto, unidade_venda, ativo, observacoes, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """), dados)
    produto_id = cursor.lastrowid
    if DATABASE_URL:
        cursor.execute("SELECT LASTVAL() AS id")
        produto_id = cursor.fetchone()["id"]
    conn.commit()
    conn.close()
    return produto_id


def atualizar_produto(produto_id, dados):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        UPDATE skus SET codigo=?, nome=?, tipo_produto=?, unidade_venda=?,
                        ativo=?, observacoes=?, atualizado_em=CURRENT_TIMESTAMP
        WHERE id=? AND excluido_em IS NULL
    """), (*dados, produto_id))
    conn.commit()
    conn.close()


def alterar_status_produto(produto_id, ativo):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        UPDATE skus SET ativo=?, atualizado_em=CURRENT_TIMESTAMP
        WHERE id=? AND excluido_em IS NULL
    """), (ativo, produto_id))
    conn.commit()
    conn.close()


def listar_itens(produto_id, incluir_inativos=True):
    conn = conectar()
    cursor = conn.cursor()
    filtro = "" if incluir_inativos else " AND r.status='Ativo'"
    cursor.execute(q(f"""
        SELECT r.*, i.descricao AS insumo_nome, i.categoria AS insumo_categoria,
               i.unidade AS insumo_unidade, i.ativo AS insumo_ativo
        FROM receitas_sku r
        JOIN almoxarifado_insumos i ON i.id=r.insumo_id
        WHERE r.sku_id=? AND r.removido_em IS NULL {filtro}
        ORDER BY CASE WHEN r.status='Ativo' THEN 0 ELSE 1 END, i.descricao, r.id
    """), (produto_id,))
    linhas = cursor.fetchall()
    conn.close()
    return linhas


def buscar_item(item_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        SELECT r.*, i.descricao AS insumo_nome, i.ativo AS insumo_ativo
        FROM receitas_sku r
        JOIN almoxarifado_insumos i ON i.id=r.insumo_id
        WHERE r.id=? AND r.removido_em IS NULL
    """), (item_id,))
    linha = cursor.fetchone()
    conn.close()
    return linha


def buscar_insumo(insumo_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM almoxarifado_insumos WHERE id=?"), (insumo_id,))
    linha = cursor.fetchone()
    conn.close()
    return linha


def buscar_item_duplicado(produto_id, insumo_id, tipo_consumo, ignorar_id=None):
    conn = conectar()
    cursor = conn.cursor()
    sql = """SELECT * FROM receitas_sku
             WHERE sku_id=? AND insumo_id=? AND tipo_consumo=?
               AND status='Ativo' AND removido_em IS NULL"""
    parametros = [produto_id, insumo_id, tipo_consumo]
    if ignorar_id:
        sql += " AND id<>?"
        parametros.append(ignorar_id)
    cursor.execute(q(sql), tuple(parametros))
    linha = cursor.fetchone()
    conn.close()
    return linha


def inserir_item(dados):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        INSERT INTO receitas_sku (
            sku_id, insumo_id, quantidade_por_unidade, unidade, tipo_consumo,
            fator_proporcao, percentual_perda, observacoes, status,
            data_vigencia, usuario_responsavel, atualizado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """), dados)
    item_id = cursor.lastrowid
    if DATABASE_URL:
        cursor.execute("SELECT LASTVAL() AS id")
        item_id = cursor.fetchone()["id"]
    conn.commit()
    conn.close()
    return item_id


def atualizar_item(item_id, dados):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        UPDATE receitas_sku SET
            insumo_id=?, quantidade_por_unidade=?, unidade=?, tipo_consumo=?,
            fator_proporcao=?, percentual_perda=?, observacoes=?, status=?,
            data_vigencia=?, usuario_responsavel=?, atualizado_em=CURRENT_TIMESTAMP
        WHERE id=? AND removido_em IS NULL
    """), (*dados, item_id))
    conn.commit()
    conn.close()


def alterar_status_item(item_id, status, usuario):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        UPDATE receitas_sku SET status=?, usuario_responsavel=?, atualizado_em=CURRENT_TIMESTAMP
        WHERE id=? AND removido_em IS NULL
    """), (status, usuario, item_id))
    conn.commit()
    conn.close()


def listar_processos():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM processos_produtivos ORDER BY CASE WHEN status='Ativo' THEN 0 ELSE 1 END, nome")
    linhas = cursor.fetchall()
    conn.close()
    return linhas


def buscar_processo_por_codigo(codigo):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM processos_produtivos WHERE LOWER(codigo)=LOWER(?)"), (codigo,))
    linha = cursor.fetchone()
    conn.close()
    return linha


def inserir_processo(dados):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        INSERT INTO processos_produtivos
            (codigo, nome, descricao, setor, status, observacoes, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """), dados)
    processo_id = cursor.lastrowid
    if DATABASE_URL:
        cursor.execute("SELECT LASTVAL() AS id")
        processo_id = cursor.fetchone()["id"]
    conn.commit()
    conn.close()
    return processo_id


def registrar_historico(entidade, entidade_id, acao, usuario_id, usuario_nome, anterior, novo):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        INSERT INTO engenharia_produtos_historico (
            entidade, entidade_id, acao, usuario_id, usuario_nome,
            valores_anteriores, valores_novos
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        entidade,
        entidade_id,
        acao,
        usuario_id,
        usuario_nome,
        json.dumps(_linha_dict(anterior), ensure_ascii=False, default=str) if anterior else None,
        json.dumps(novo, ensure_ascii=False, default=str) if novo else None,
    ))
    conn.commit()
    conn.close()


def listar_historico_produto(produto_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        SELECT * FROM engenharia_produtos_historico
        WHERE (entidade='produto' AND entidade_id=?)
           OR (entidade='item_estrutura' AND entidade_id IN (
                SELECT id FROM receitas_sku WHERE sku_id=?
           ))
        ORDER BY criado_em DESC, id DESC
    """), (produto_id, produto_id))
    linhas = cursor.fetchall()
    conn.close()
    return linhas


def resumo_catalogo():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            SUM(CASE WHEN ativo='Sim' AND excluido_em IS NULL THEN 1 ELSE 0 END) AS produtos_ativos,
            SUM(CASE WHEN ativo='Não' AND excluido_em IS NULL THEN 1 ELSE 0 END) AS produtos_inativos,
            SUM(CASE WHEN ativo='Sim' AND excluido_em IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM receitas_sku r
                    WHERE r.sku_id=skus.id AND r.status='Ativo' AND r.removido_em IS NULL
                ) THEN 1 ELSE 0 END) AS produtos_sem_estrutura
        FROM skus
    """)
    resumo = dict(cursor.fetchone())
    cursor.execute("""
        SELECT COUNT(DISTINCT sku_id) AS estruturas_ativas
        FROM receitas_sku WHERE status='Ativo' AND removido_em IS NULL
    """)
    resumo["estruturas_ativas"] = cursor.fetchone()["estruturas_ativas"]
    conn.close()
    return resumo
