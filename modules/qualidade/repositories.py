"""Persistencia estruturada da Qualidade e da Central de Verificacoes SGI."""

from database import DATABASE_URL, conectar, q, transaction
from modules.cadastros import repositories as cadastros_repo


def criar_tabelas_sgi():
    cadastros_repo.criar_tabela_locais()
    conn = conectar()
    cursor = conn.cursor()
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp = "TIMESTAMP" if DATABASE_URL else "TEXT"
    tabelas = [
        f"""CREATE TABLE IF NOT EXISTS sgi_verificacoes (
            id {pk}, formulario_tipo TEXT NOT NULL, formulario_codigo TEXT NOT NULL,
            formulario_nome TEXT NOT NULL, data TEXT NOT NULL, setor TEXT NOT NULL,
            vinculo_tipo TEXT NOT NULL, local_id INTEGER, equipamento_id INTEGER,
            responsavel TEXT NOT NULL, status TEXT DEFAULT 'Pendente', observacoes TEXT,
            criado_por INTEGER NOT NULL, criado_por_nome TEXT NOT NULL,
            criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP,
            concluido_por INTEGER, concluido_por_nome TEXT, concluido_em {timestamp},
            atualizado_em {timestamp} DEFAULT CURRENT_TIMESTAMP,
            justificativa_alteracao TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS sgi_verificacao_itens (
            id {pk}, verificacao_id INTEGER NOT NULL, item_codigo TEXT NOT NULL,
            item_descricao TEXT NOT NULL, valor_texto TEXT, valor_numerico REAL,
            unidade TEXT, parametro_numerico REAL, resultado TEXT,
            observacoes TEXT, acao_adotada TEXT, reposicao_simples TEXT DEFAULT 'Nao',
            UNIQUE(verificacao_id, item_codigo)
        )""",
        f"""CREATE TABLE IF NOT EXISTS sgi_nao_conformidades (
            id {pk}, verificacao_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
            descricao TEXT NOT NULL, criticidade TEXT NOT NULL, situacao TEXT NOT NULL,
            tratamento TEXT, ordem_id INTEGER, criado_por INTEGER NOT NULL,
            criado_por_nome TEXT NOT NULL, criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP,
            gerencia_decisao TEXT, gerencia_justificativa TEXT, gerencia_usuario_id INTEGER,
            gerencia_usuario_nome TEXT, gerencia_em {timestamp}, eficacia_resultado TEXT,
            eficacia_observacao TEXT, eficacia_usuario_id INTEGER, eficacia_usuario_nome TEXT,
            eficacia_em {timestamp}, encerrado_por INTEGER, encerrado_por_nome TEXT,
            encerrado_em {timestamp}, atualizado_em {timestamp} DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS sgi_acoes_imediatas (
            id {pk}, nc_id INTEGER NOT NULL, item_ausente TEXT NOT NULL,
            pessoa_acionada TEXT NOT NULL, acionado_por INTEGER NOT NULL,
            acionado_por_nome TEXT NOT NULL, acionado_em {timestamp} DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'Aguardando reposicao', segunda_verificacao_resultado TEXT,
            segunda_verificacao_observacao TEXT, verificado_por INTEGER,
            verificado_por_nome TEXT, verificado_em {timestamp}
        )""",
        f"""CREATE TABLE IF NOT EXISTS sgi_eventos (
            id {pk}, entidade_tipo TEXT NOT NULL, entidade_id INTEGER NOT NULL,
            evento TEXT NOT NULL, descricao TEXT, justificativa TEXT,
            usuario_id INTEGER NOT NULL, usuario_nome TEXT NOT NULL,
            criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    for comando in tabelas:
        cursor.execute(q(comando))
    conn.commit()
    conn.close()


def listar_locais(tipo=None):
    return cadastros_repo.listar_locais(tipo)


def inserir_local(tipo, nome, setor, classificacao):
    return cadastros_repo.inserir_local(tipo, nome, setor, classificacao)


def buscar_local(local_id):
    return cadastros_repo.buscar_local(local_id)


def listar_equipamentos():
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("""SELECT * FROM manutencao_equipamentos
        WHERE COALESCE(status, '') <> 'Inativo' ORDER BY setor, nome"""))
    rows = cursor.fetchall(); conn.close(); return rows


def buscar_equipamento(equipamento_id):
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM manutencao_equipamentos WHERE id = ?"), (equipamento_id,))
    row = cursor.fetchone(); conn.close(); return row


def inserir_verificacao(cabecalho, itens, ncs, acoes, evento):
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("""INSERT INTO sgi_verificacoes (
            formulario_tipo, formulario_codigo, formulario_nome, data, setor,
            vinculo_tipo, local_id, equipamento_id, responsavel, status, observacoes,
            criado_por, criado_por_nome, concluido_por, concluido_por_nome, concluido_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)"""), cabecalho)
        cursor.execute("SELECT LASTVAL() AS id" if DATABASE_URL else "SELECT last_insert_rowid() AS id")
        verificacao_id = cursor.fetchone()["id"]
        item_ids = {}
        for item in itens:
            cursor.execute(q("""INSERT INTO sgi_verificacao_itens (
                verificacao_id, item_codigo, item_descricao, valor_texto, valor_numerico,
                unidade, parametro_numerico, resultado, observacoes, acao_adotada, reposicao_simples
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""), (verificacao_id, *item))
            cursor.execute("SELECT LASTVAL() AS id" if DATABASE_URL else "SELECT last_insert_rowid() AS id")
            item_ids[item[0]] = cursor.fetchone()["id"]
        for nc in ncs:
            item_codigo = nc.pop("item_codigo")
            cursor.execute(q("""INSERT INTO sgi_nao_conformidades (
                verificacao_id, item_id, descricao, criticidade, situacao, tratamento,
                criado_por, criado_por_nome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""), (
                verificacao_id, item_ids[item_codigo], nc["descricao"], nc["criticidade"],
                nc["situacao"], nc["tratamento"], evento[4], evento[5]))
            cursor.execute("SELECT LASTVAL() AS id" if DATABASE_URL else "SELECT last_insert_rowid() AS id")
            nc_id = cursor.fetchone()["id"]
            if item_codigo in acoes:
                acao = acoes[item_codigo]
                cursor.execute(q("""INSERT INTO sgi_acoes_imediatas (
                    nc_id, item_ausente, pessoa_acionada, acionado_por, acionado_por_nome
                ) VALUES (?, ?, ?, ?, ?)"""),
                    (nc_id, acao[0], acao[1], evento[4], evento[5]))
            cursor.execute(q("""INSERT INTO sgi_eventos
                (entidade_tipo, entidade_id, evento, descricao, usuario_id, usuario_nome)
                VALUES ('NC', ?, 'NC criada', ?, ?, ?)"""),
                (nc_id, nc["descricao"], evento[4], evento[5]))
        cursor.execute(q("""INSERT INTO sgi_eventos
            (entidade_tipo, entidade_id, evento, descricao, usuario_id, usuario_nome)
            VALUES (?, ?, ?, ?, ?, ?)"""), (evento[0], verificacao_id, *evento[2:]))
    return verificacao_id


def listar_verificacoes(filtros=None):
    filtros = filtros or {}
    condicoes, params = ["1=1"], []
    for campo in ("formulario_tipo", "setor", "status"):
        if filtros.get(campo) and filtros[campo] != "Todos":
            condicoes.append(f"v.{campo} = ?"); params.append(filtros[campo])
    if filtros.get("mes"):
        condicoes.append("SUBSTR(v.data, 1, 7) = ?"); params.append(filtros["mes"])
    if filtros.get("vinculo_tipo") and filtros["vinculo_tipo"] != "Todos":
        condicoes.append("v.vinculo_tipo = ?"); params.append(filtros["vinculo_tipo"])
    if filtros.get("local_id"):
        condicoes.append("v.local_id = ?"); params.append(int(filtros["local_id"]))
    if filtros.get("equipamento_id"):
        condicoes.append("v.equipamento_id = ?"); params.append(int(filtros["equipamento_id"]))
    if filtros.get("resultado") and filtros["resultado"] != "Todos":
        condicoes.append("EXISTS (SELECT 1 FROM sgi_verificacao_itens rf WHERE rf.verificacao_id=v.id AND rf.resultado=?)")
        params.append(filtros["resultado"])
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q(f"""SELECT v.*,
        COALESCE(l.nome, e.nome) AS vinculo_nome,
        (SELECT COUNT(*) FROM sgi_nao_conformidades nc WHERE nc.verificacao_id=v.id) AS total_ncs,
        (SELECT COUNT(*) FROM sgi_nao_conformidades nc WHERE nc.verificacao_id=v.id AND nc.situacao NOT IN ('Encerrada','NC corrigida imediatamente')) AS ncs_abertas,
        (SELECT COUNT(*) FROM sgi_nao_conformidades nc WHERE nc.verificacao_id=v.id AND nc.criticidade='CRITICA' AND nc.gerencia_decisao IS NULL) AS pendencias_gerencia
        FROM sgi_verificacoes v
        LEFT JOIN cadastros_locais l ON l.id=v.local_id
        LEFT JOIN manutencao_equipamentos e ON e.id=v.equipamento_id
        WHERE {' AND '.join(condicoes)} ORDER BY v.data DESC, v.id DESC"""), tuple(params))
    rows = cursor.fetchall(); conn.close(); return rows


def buscar_verificacao(verificacao_id):
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("""SELECT v.*, COALESCE(l.nome,e.nome) AS vinculo_nome,
        COALESCE(l.classificacao_iluminacao,'') AS classificacao_iluminacao
        FROM sgi_verificacoes v LEFT JOIN cadastros_locais l ON l.id=v.local_id
        LEFT JOIN manutencao_equipamentos e ON e.id=v.equipamento_id WHERE v.id=?"""), (verificacao_id,))
    v = cursor.fetchone()
    cursor.execute(q("SELECT * FROM sgi_verificacao_itens WHERE verificacao_id=? ORDER BY id"), (verificacao_id,)); itens=cursor.fetchall()
    cursor.execute(q("""SELECT nc.*, i.item_codigo, i.item_descricao, os.status AS ordem_status
        FROM sgi_nao_conformidades nc JOIN sgi_verificacao_itens i ON i.id=nc.item_id
        LEFT JOIN manutencao_ordens os ON os.id=nc.ordem_id
        WHERE nc.verificacao_id=? ORDER BY nc.id"""), (verificacao_id,)); ncs=cursor.fetchall()
    cursor.execute(q("""SELECT ai.* FROM sgi_acoes_imediatas ai JOIN sgi_nao_conformidades nc ON nc.id=ai.nc_id
        WHERE nc.verificacao_id=? ORDER BY ai.id"""), (verificacao_id,)); acoes=cursor.fetchall()
    cursor.execute(q("""SELECT * FROM sgi_eventos WHERE (entidade_tipo='Verificacao' AND entidade_id=?)
        OR (entidade_tipo='NC' AND entidade_id IN (SELECT id FROM sgi_nao_conformidades WHERE verificacao_id=?))
        ORDER BY criado_em,id"""), (verificacao_id,verificacao_id)); eventos=cursor.fetchall()
    conn.close(); return v, itens, ncs, acoes, eventos


def buscar_nc(nc_id):
    conn=conectar(); cursor=conn.cursor()
    cursor.execute(q("""SELECT nc.*, v.formulario_codigo,v.formulario_nome,v.setor,v.equipamento_id,
        COALESCE(l.nome,e.nome) AS ativo_nome,i.item_descricao
        FROM sgi_nao_conformidades nc JOIN sgi_verificacoes v ON v.id=nc.verificacao_id
        JOIN sgi_verificacao_itens i ON i.id=nc.item_id
        LEFT JOIN cadastros_locais l ON l.id=v.local_id LEFT JOIN manutencao_equipamentos e ON e.id=v.equipamento_id
        WHERE nc.id=?"""),(nc_id,)); row=cursor.fetchone(); conn.close(); return row


def registrar_evento(entidade, entidade_id, evento, descricao, usuario_id, usuario_nome, justificativa=None):
    with transaction() as conn:
        conn.cursor().execute(q("""INSERT INTO sgi_eventos
            (entidade_tipo,entidade_id,evento,descricao,justificativa,usuario_id,usuario_nome)
            VALUES (?,?,?,?,?,?,?)"""),(entidade,entidade_id,evento,descricao,justificativa,usuario_id,usuario_nome))


def confirmar_reposicao(acao_id, resultado, observacao, usuario_id, usuario_nome):
    with transaction() as conn:
        cursor=conn.cursor(); cursor.execute(q("SELECT * FROM sgi_acoes_imediatas WHERE id=?"),(acao_id,)); acao=cursor.fetchone()
        if not acao: raise ValueError("Acao imediata nao encontrada.")
        status="Confirmada" if resultado=="C" else "Aguardando reposicao"
        cursor.execute(q("""UPDATE sgi_acoes_imediatas SET status=?,segunda_verificacao_resultado=?,
            segunda_verificacao_observacao=?,verificado_por=?,verificado_por_nome=?,verificado_em=CURRENT_TIMESTAMP WHERE id=?"""),
            (status,resultado,observacao,usuario_id,usuario_nome,acao_id))
        situacao="NC corrigida imediatamente" if resultado=="C" else "Aguardando reposicao"
        cursor.execute(q("UPDATE sgi_nao_conformidades SET situacao=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"),(situacao,acao["nc_id"]))


def decidir_criticidade(nc_id, decisao, justificativa, usuario_id, usuario_nome):
    with transaction() as conn:
        conn.cursor().execute(q("""UPDATE sgi_nao_conformidades SET gerencia_decisao=?,gerencia_justificativa=?,
            gerencia_usuario_id=?,gerencia_usuario_nome=?,gerencia_em=CURRENT_TIMESTAMP,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"""),
            (decisao,justificativa,usuario_id,usuario_nome,nc_id))


def validar_eficacia(nc_id, resultado, observacao, usuario_id, usuario_nome):
    situacao="Eficaz - aguardando encerramento" if resultado=="Eficaz" else "Aberta - acao ineficaz"
    with transaction() as conn:
        conn.cursor().execute(q("""UPDATE sgi_nao_conformidades SET eficacia_resultado=?,eficacia_observacao=?,
            eficacia_usuario_id=?,eficacia_usuario_nome=?,eficacia_em=CURRENT_TIMESTAMP,situacao=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"""),
            (resultado,observacao,usuario_id,usuario_nome,situacao,nc_id))


def encerrar_nc(nc_id, usuario_id, usuario_nome):
    with transaction() as conn:
        conn.cursor().execute(q("""UPDATE sgi_nao_conformidades SET situacao='Encerrada',encerrado_por=?,
            encerrado_por_nome=?,encerrado_em=CURRENT_TIMESTAMP,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"""),
            (usuario_id,usuario_nome,nc_id))


def vincular_ordem(nc_id, ordem_id):
    with transaction() as conn:
        cursor=conn.cursor()
        cursor.execute(q("UPDATE sgi_nao_conformidades SET ordem_id=?,situacao='Em tratamento - OS aberta',atualizado_em=CURRENT_TIMESTAMP WHERE id=?"),(ordem_id,nc_id))
        cursor.execute(q("UPDATE manutencao_ordens SET sgi_nc_id=? WHERE id=?"),(nc_id,ordem_id))


def marcar_nc_aguardando_validacao(nc_id):
    with transaction() as conn:
        conn.cursor().execute(q("UPDATE sgi_nao_conformidades SET situacao='Aguardando validacao da Qualidade',atualizado_em=CURRENT_TIMESTAMP WHERE id=?"),(nc_id,))
