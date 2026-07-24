from functools import wraps
import os
import threading

import database
from database import DATABASE_URL, conectar, q


ROTINAS_ESTRUTURAIS_EXECUTADAS = set()
ROTINAS_ESTRUTURAIS_LOCK = threading.RLock()


def executar_rotina_estrutural_uma_vez(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        destino_banco = database.DATABASE_URL or os.path.abspath(database.DB_NAME)
        chave = (func.__name__, destino_banco)

        with ROTINAS_ESTRUTURAIS_LOCK:
            if chave in ROTINAS_ESTRUTURAIS_EXECUTADAS:
                return None

            resultado = func(*args, **kwargs)
            ROTINAS_ESTRUTURAIS_EXECUTADAS.add(chave)
            return resultado

    return wrapper


TIPOS_MANUTENCAO = [
    "Corretiva",
    "Preventiva",
    "Preditiva",
    "Melhoria",
]

PRIORIDADES_MANUTENCAO = [
    "Baixa",
    "Media",
    "Alta",
    "Critica",
]

STATUS_MANUTENCAO = [
    "Aberta",
    "Em andamento",
    "Aguardando peca",
    "Aguardando material",
    "Concluida",
    "Cancelada",
]

TIPOS_OBJETO_MANUTENCAO = [
    "EQUIPAMENTO",
    "PREDIAL",
    "VEICULO",
]

CATEGORIAS_PREDIAIS = [
    ("ELETRICA", "Eletrica"),
    ("CIVIL", "Civil"),
    ("HIDRAULICA", "Hidraulica"),
    ("OUTRAS", "Outras"),
]

LOCAIS_PREDIAIS = [
    "Producao",
    "Recepcao",
    "Camara Fria",
    "Area de Embalagem",
    "Expedicao",
    "Vestiario Masculino",
    "Vestiario Feminino",
    "Banheiros",
    "Barreira Sanitaria",
    "Almoxarifado",
    "Escritorio",
    "Area Externa",
    "Outros",
]

TIPOS_VEICULO = [
    "Caminhao de transporte de aves",
    "Caminhao frigorifico",
    "Caminhao de expedicao",
    "Veiculo utilitario",
    "Automovel",
    "Empilhadeira",
    "Outro",
]

STATUS_RECURSO_ORDEM = [
    "Necessario",
    "Disponivel",
    "Indisponivel",
    "Aguardando aquisicao",
    "Atendido",
    "Cancelado",
]


def _executar_alteracao(cursor, conn, comando):
    try:
        cursor.execute(q(comando))
        conn.commit()
    except Exception:
        conn.rollback()


@executar_rotina_estrutural_uma_vez
def criar_tabelas_manutencao():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_equipamentos (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            setor TEXT NOT NULL,
            fabricante TEXT,
            modelo TEXT,
            numero_serie TEXT,
            criticidade TEXT DEFAULT 'Media',
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordens (
            id SERIAL PRIMARY KEY,
            equipamento_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            prioridade TEXT NOT NULL,
            status TEXT DEFAULT 'Aberta',
            data_abertura TEXT NOT NULL,
            data_prevista TEXT,
            data_conclusao TEXT,
            solicitante TEXT,
            responsavel TEXT,
            descricao TEXT NOT NULL,
            diagnostico TEXT,
            solucao TEXT,
            horas_paradas REAL DEFAULT 0,
            custo_estimado REAL DEFAULT 0,
            custo_real REAL DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordem_recursos (
            id SERIAL PRIMARY KEY,
            ordem_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            quantidade REAL DEFAULT 0,
            unidade TEXT,
            fornecedor TEXT,
            valor_estimado REAL DEFAULT 0,
            status TEXT DEFAULT 'Pendente',
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_veiculos (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE NOT NULL,
            identificacao TEXT NOT NULL,
            placa TEXT UNIQUE,
            tipo TEXT,
            tipo_outro TEXT,
            marca TEXT,
            modelo TEXT,
            ano INTEGER,
            finalidade TEXT,
            setor_responsavel TEXT,
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordem_eventos (
            id SERIAL PRIMARY KEY,
            ordem_id INTEGER NOT NULL,
            recurso_id INTEGER,
            evento TEXT NOT NULL,
            descricao TEXT,
            valor_anterior TEXT,
            valor_novo TEXT,
            usuario_id INTEGER,
            usuario_nome TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_equipamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            setor TEXT NOT NULL,
            fabricante TEXT,
            modelo TEXT,
            numero_serie TEXT,
            criticidade TEXT DEFAULT 'Media',
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipamento_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            prioridade TEXT NOT NULL,
            status TEXT DEFAULT 'Aberta',
            data_abertura TEXT NOT NULL,
            data_prevista TEXT,
            data_conclusao TEXT,
            solicitante TEXT,
            responsavel TEXT,
            descricao TEXT NOT NULL,
            diagnostico TEXT,
            solucao TEXT,
            horas_paradas REAL DEFAULT 0,
            custo_estimado REAL DEFAULT 0,
            custo_real REAL DEFAULT 0,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordem_recursos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ordem_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            quantidade REAL DEFAULT 0,
            unidade TEXT,
            fornecedor TEXT,
            valor_estimado REAL DEFAULT 0,
            status TEXT DEFAULT 'Pendente',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            identificacao TEXT NOT NULL,
            placa TEXT UNIQUE,
            tipo TEXT,
            tipo_outro TEXT,
            marca TEXT,
            modelo TEXT,
            ano INTEGER,
            finalidade TEXT,
            setor_responsavel TEXT,
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordem_eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ordem_id INTEGER NOT NULL,
            recurso_id INTEGER,
            evento TEXT NOT NULL,
            descricao TEXT,
            valor_anterior TEXT,
            valor_novo TEXT,
            usuario_id INTEGER,
            usuario_nome TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()

    alteracoes = [
        "ALTER TABLE manutencao_ordens ADD COLUMN op_id INTEGER",
        "ALTER TABLE manutencao_ordens ADD COLUMN parada_id INTEGER",
        "ALTER TABLE manutencao_ordens ADD COLUMN motivo_parada TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN hora_abertura TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN hora_conclusao TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN pecas_utilizadas TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN observacoes_finais TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN sgi_nc_id INTEGER",
        "ALTER TABLE manutencao_ordens ADD COLUMN tipo_objeto TEXT DEFAULT 'EQUIPAMENTO'",
        "ALTER TABLE manutencao_ordens ADD COLUMN veiculo_id INTEGER",
        "ALTER TABLE manutencao_ordens ADD COLUMN categoria_predial TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN local_predial TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN local_predial_descricao TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN solicitante_id INTEGER",
        "ALTER TABLE manutencao_ordens ADD COLUMN solicitante_perfil TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN cancelamento_motivo TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN cancelado_por_id INTEGER",
        "ALTER TABLE manutencao_ordens ADD COLUMN cancelado_por_nome TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN cancelado_em TEXT",
        "ALTER TABLE manutencao_ordem_recursos ADD COLUMN insumo_id INTEGER",
        "ALTER TABLE manutencao_ordem_recursos ADD COLUMN descricao_complementar TEXT",
        "ALTER TABLE manutencao_ordem_recursos ADD COLUMN usuario_id INTEGER",
        "ALTER TABLE manutencao_ordem_recursos ADD COLUMN usuario_nome TEXT",
        "ALTER TABLE manutencao_ordem_recursos ADD COLUMN atualizado_em TEXT",
    ]

    for comando in alteracoes:
        _executar_alteracao(cursor, conn, comando)

    try:
        cursor.execute(q("""
        UPDATE manutencao_equipamentos
        SET status = ?
        WHERE COALESCE(status, '') = ?
        """), ("Operacional", "Ativo"))
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        cursor.execute(q("""
        UPDATE manutencao_ordens
        SET tipo_objeto = ?
        WHERE tipo_objeto IS NULL OR tipo_objeto = ?
        """), ("EQUIPAMENTO", ""))
        conn.commit()
    except Exception:
        conn.rollback()

    conn.close()


def inserir_equipamento(dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    INSERT INTO manutencao_equipamentos (
        codigo,
        nome,
        setor,
        fabricante,
        modelo,
        numero_serie,
        criticidade,
        status,
        observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), dados)
    conn.commit()
    conn.close()


def atualizar_equipamento(equipamento_id, dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE manutencao_equipamentos
    SET
        codigo = ?,
        nome = ?,
        setor = ?,
        fabricante = ?,
        modelo = ?,
        numero_serie = ?,
        criticidade = ?,
        status = ?,
        observacoes = ?
    WHERE id = ?
    """), (*dados, equipamento_id))
    conn.commit()
    conn.close()


def equipamento_existe(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT id FROM manutencao_equipamentos WHERE id = ?"), (equipamento_id,))
    equipamento = cursor.fetchone()
    conn.close()
    return equipamento


def equipamento_ativo(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_equipamentos
    WHERE id = ? AND COALESCE(status, '') <> ?
    """), (equipamento_id, "Inativo"))
    equipamento = cursor.fetchone()
    conn.close()
    return equipamento


def buscar_equipamento_por_codigo(codigo):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_equipamentos
    WHERE codigo = ?
    """), (codigo,))
    equipamento = cursor.fetchone()
    conn.close()
    return equipamento


def inserir_ordem(dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    ordem_id = _inserir_ordem_cursor(cursor, dados)
    conn.commit()
    conn.close()
    return ordem_id


def inserir_ordem_com_recursos(dados, recursos=None, usuario_id=0, usuario_nome="Sistema"):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    try:
        ordem_id = _inserir_ordem_cursor(cursor, dados)
        _salvar_recursos_ordem_cursor(cursor, ordem_id, recursos or [], usuario_id, usuario_nome)
        conn.commit()
        return ordem_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _inserir_ordem_cursor(cursor, dados):
    cursor.execute(q("""
    INSERT INTO manutencao_ordens (
        tipo_objeto,
        equipamento_id,
        veiculo_id,
        categoria_predial,
        local_predial,
        local_predial_descricao,
        op_id,
        parada_id,
        tipo,
        prioridade,
        status,
        data_abertura,
        hora_abertura,
        data_prevista,
        solicitante,
        solicitante_id,
        solicitante_perfil,
        responsavel,
        descricao,
        motivo_parada,
        custo_estimado
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), dados)
    if dados[0] == "EQUIPAMENTO" and dados[1]:
        cursor.execute(q("""
        UPDATE manutencao_equipamentos
        SET status = ?
        WHERE id = ?
        """), ("Em Manutencao", dados[1]))
    cursor.execute("SELECT LASTVAL() as id" if DATABASE_URL else "SELECT last_insert_rowid() as id")
    ordem = cursor.fetchone()
    return ordem["id"]


def atualizar_ordem(ordem_id, dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    _atualizar_ordem_cursor(cursor, ordem_id, dados)
    conn.commit()
    conn.close()


def atualizar_ordem_com_recursos(ordem_id, dados, recursos=None, usuario_id=0, usuario_nome="Sistema", evento=None):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    try:
        _atualizar_ordem_cursor(cursor, ordem_id, dados)
        _salvar_recursos_ordem_cursor(cursor, ordem_id, recursos or [], usuario_id, usuario_nome)
        if evento:
            _registrar_evento_cursor(
                cursor, ordem_id, None, evento["evento"], evento["descricao"],
                evento.get("anterior", ""), evento.get("novo", ""), usuario_id, usuario_nome)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def atualizar_ficha_ordem_com_recursos(ordem_id, dados, recursos=None, usuario_id=0, usuario_nome="Sistema", evento=None):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    try:
        _atualizar_ficha_ordem_cursor(cursor, ordem_id, dados)
        _salvar_recursos_ordem_cursor(cursor, ordem_id, recursos or [], usuario_id, usuario_nome)
        if evento:
            _registrar_evento_cursor(
                cursor, ordem_id, None, evento["evento"], evento["descricao"],
                evento.get("anterior", ""), evento.get("novo", ""), usuario_id, usuario_nome)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _atualizar_ordem_cursor(cursor, ordem_id, dados):
    cursor.execute(q("""
    UPDATE manutencao_ordens
    SET
        status = ?,
        data_conclusao = ?,
        responsavel = ?,
        diagnostico = ?,
        solucao = ?,
        horas_paradas = ?,
        custo_real = ?,
        hora_conclusao = ?,
        pecas_utilizadas = ?,
        observacoes_finais = ?
    WHERE id = ?
    """), (*dados, ordem_id))


def _atualizar_ficha_ordem_cursor(cursor, ordem_id, dados):
    cursor.execute(q("""
    UPDATE manutencao_ordens
    SET
        tipo = ?,
        prioridade = ?,
        data_abertura = ?,
        data_prevista = ?,
        responsavel = ?,
        descricao = ?,
        custo_estimado = ?,
        status = ?,
        data_conclusao = ?,
        diagnostico = ?,
        solucao = ?,
        horas_paradas = ?,
        custo_real = ?,
        hora_conclusao = ?,
        pecas_utilizadas = ?,
        observacoes_finais = ?
    WHERE id = ?
    """), (*dados, ordem_id))


def buscar_ordem_por_id(ordem_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT
        o.*,
        COALESCE(o.tipo_objeto, 'EQUIPAMENTO') AS tipo_objeto,
        e.codigo AS equipamento_codigo,
        e.nome AS equipamento_nome,
        e.setor AS equipamento_setor,
        v.codigo AS veiculo_codigo,
        v.identificacao AS veiculo_identificacao,
        v.placa AS veiculo_placa,
        v.status AS veiculo_status,
        CASE
            WHEN COALESCE(o.tipo_objeto, 'EQUIPAMENTO') = 'VEICULO' THEN
                COALESCE(v.identificacao, 'Veiculo nao encontrado') ||
                CASE WHEN COALESCE(v.placa, '') <> '' THEN ' | ' || v.placa ELSE '' END
            WHEN COALESCE(o.tipo_objeto, 'EQUIPAMENTO') = 'PREDIAL' THEN
                COALESCE(o.categoria_predial, 'Predial') || ' | ' ||
                COALESCE(o.local_predial, '')
            ELSE
                COALESCE(e.nome, 'Equipamento nao encontrado')
        END AS objeto_nome
    FROM manutencao_ordens o
    LEFT JOIN manutencao_equipamentos e ON e.id = o.equipamento_id
    LEFT JOIN manutencao_veiculos v ON v.id = o.veiculo_id
    WHERE o.id = ?
    """), (ordem_id,))
    ordem = cursor.fetchone()
    conn.close()
    return ordem


def atualizar_status_equipamento(equipamento_id, status):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE manutencao_equipamentos
    SET status = ?
    WHERE id = ?
    """), (status, equipamento_id))
    conn.commit()
    conn.close()


def buscar_equipamento_por_id(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_equipamentos
    WHERE id = ?
    """), (equipamento_id,))
    equipamento = cursor.fetchone()
    conn.close()
    return equipamento


def vincular_ordem_a_parada(parada_id, ordem_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE apontamentos_paradas
    SET manutencao_ordem_id = ?,
        manutencao_aberta = ?
    WHERE id = ?
    """), (ordem_id, "Sim", parada_id))
    conn.commit()
    conn.close()


def encerrar_parada_por_ordem(parada_id, data_fim, hora_fim, horas_paradas):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE apontamentos_paradas
    SET data_fim = ?,
        hora_fim = ?,
        horas_paradas = ?,
        encerrada_por_manutencao = ?
    WHERE id = ?
    """), (data_fim, hora_fim, horas_paradas, "Sim", parada_id))
    conn.commit()
    conn.close()


def listar_equipamentos():
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_equipamentos
    ORDER BY setor ASC, nome ASC
    """))
    equipamentos = cursor.fetchall()
    conn.close()
    return equipamentos


def listar_equipamentos_ativos():
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_equipamentos
    WHERE COALESCE(status, '') <> ?
    ORDER BY setor ASC, nome ASC
    """), ("Inativo",))
    equipamentos = cursor.fetchall()
    conn.close()
    return equipamentos


def cancelar_ordem(ordem_id, motivo, usuario_id, usuario_nome):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE manutencao_ordens
    SET status = ?,
        cancelamento_motivo = ?,
        cancelado_por_id = ?,
        cancelado_por_nome = ?,
        cancelado_em = CURRENT_TIMESTAMP
    WHERE id = ?
    """), ("Cancelada", motivo, usuario_id, usuario_nome, ordem_id))
    cursor.execute(q("""
    UPDATE manutencao_ordem_recursos
    SET status = ?,
        atualizado_em = CURRENT_TIMESTAMP
    WHERE ordem_id = ? AND COALESCE(status, '') <> ?
    """), ("Cancelado", ordem_id, "Cancelado"))
    cursor.execute(q("""
    INSERT INTO manutencao_ordem_eventos (
        ordem_id, evento, descricao, valor_anterior, valor_novo, usuario_id, usuario_nome
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        ordem_id, "OS cancelada", "Cancelamento logico da ordem de servico",
        "Aberta", f"Cancelada: {motivo}", usuario_id, usuario_nome
    ))
    conn.commit()
    conn.close()


def listar_equipamentos_filtrados(busca=""):
    criar_tabelas_manutencao()
    termo = (busca or "").strip()
    parametros = []
    where = ""

    if termo:
        where = """
        WHERE LOWER(codigo) LIKE ?
           OR LOWER(nome) LIKE ?
           OR LOWER(setor) LIKE ?
           OR LOWER(fabricante) LIKE ?
           OR LOWER(modelo) LIKE ?
           OR LOWER(status) LIKE ?
        """
        like = f"%{termo.lower()}%"
        parametros = [like, like, like, like, like, like]

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT *
    FROM manutencao_equipamentos
    {where}
    ORDER BY setor ASC, nome ASC
    """), tuple(parametros))
    equipamentos = cursor.fetchall()
    conn.close()
    return equipamentos


def contar_ordens_por_equipamento(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT COUNT(*) as total
    FROM manutencao_ordens
    WHERE equipamento_id = ? AND COALESCE(tipo_objeto, 'EQUIPAMENTO') = ?
    """), (equipamento_id, "EQUIPAMENTO"))
    total = cursor.fetchone()["total"]
    conn.close()
    return int(total or 0)


def excluir_equipamento(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    DELETE FROM manutencao_equipamentos
    WHERE id = ?
    """), (equipamento_id,))
    conn.commit()
    conn.close()


def inserir_veiculo(dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    INSERT INTO manutencao_veiculos (
        codigo, identificacao, placa, tipo, tipo_outro, marca, modelo, ano,
        finalidade, setor_responsavel, status, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), dados)
    conn.commit()
    conn.close()


def atualizar_veiculo(veiculo_id, dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE manutencao_veiculos
    SET codigo = ?, identificacao = ?, placa = ?, tipo = ?, tipo_outro = ?,
        marca = ?, modelo = ?, ano = ?, finalidade = ?, setor_responsavel = ?,
        status = ?, observacoes = ?
    WHERE id = ?
    """), (*dados, veiculo_id))
    conn.commit()
    conn.close()


def buscar_veiculo_por_id(veiculo_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM manutencao_veiculos WHERE id = ?"), (veiculo_id,))
    veiculo = cursor.fetchone()
    conn.close()
    return veiculo


def buscar_veiculo_por_codigo(codigo):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM manutencao_veiculos WHERE codigo = ?"), (codigo,))
    veiculo = cursor.fetchone()
    conn.close()
    return veiculo


def buscar_veiculo_por_placa(placa):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM manutencao_veiculos WHERE placa = ?"), (placa,))
    veiculo = cursor.fetchone()
    conn.close()
    return veiculo


def veiculo_ativo(veiculo_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_veiculos
    WHERE id = ? AND COALESCE(status, '') = ?
    """), (veiculo_id, "Ativo"))
    veiculo = cursor.fetchone()
    conn.close()
    return veiculo


def listar_veiculos(busca=""):
    criar_tabelas_manutencao()
    termo = (busca or "").strip()
    parametros = []
    where = ""

    if termo:
        where = """
        WHERE LOWER(codigo) LIKE ?
           OR LOWER(identificacao) LIKE ?
           OR LOWER(COALESCE(placa, '')) LIKE ?
           OR LOWER(COALESCE(tipo, '')) LIKE ?
           OR LOWER(COALESCE(status, '')) LIKE ?
        """
        like = f"%{termo.lower()}%"
        parametros = [like, like, like, like, like]

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT *
    FROM manutencao_veiculos
    {where}
    ORDER BY status ASC, identificacao ASC
    """), tuple(parametros))
    veiculos = cursor.fetchall()
    conn.close()
    return veiculos


def listar_veiculos_ativos():
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_veiculos
    WHERE COALESCE(status, '') = ?
    ORDER BY identificacao ASC
    """), ("Ativo",))
    veiculos = cursor.fetchall()
    conn.close()
    return veiculos


def contar_ordens_por_veiculo(veiculo_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT COUNT(*) as total
    FROM manutencao_ordens
    WHERE veiculo_id = ? AND COALESCE(tipo_objeto, '') = ?
    """), (veiculo_id, "VEICULO"))
    total = cursor.fetchone()["total"]
    conn.close()
    return int(total or 0)


def inativar_veiculo(veiculo_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE manutencao_veiculos
    SET status = ?
    WHERE id = ?
    """), ("Inativo", veiculo_id))
    conn.commit()
    conn.close()


def listar_ordens(
    status_filtro="Todos",
    equipamento_id="",
    tipo_objeto="Todos",
    veiculo_id="",
    setor="",
    responsavel="",
    prioridade="Todos",
    pesquisa="",
):
    criar_tabelas_manutencao()
    filtros = []
    parametros = []

    if status_filtro and status_filtro != "Todos":
        filtros.append("o.status = ?")
        parametros.append(status_filtro)

    if equipamento_id:
        filtros.append("COALESCE(o.tipo_objeto, 'EQUIPAMENTO') = ? AND o.equipamento_id = ?")
        parametros.append("EQUIPAMENTO")
        parametros.append(int(equipamento_id))

    if tipo_objeto and tipo_objeto != "Todos":
        filtros.append("COALESCE(o.tipo_objeto, 'EQUIPAMENTO') = ?")
        parametros.append(tipo_objeto)

    if veiculo_id:
        filtros.append("COALESCE(o.tipo_objeto, 'EQUIPAMENTO') = ? AND o.veiculo_id = ?")
        parametros.append("VEICULO")
        parametros.append(int(veiculo_id))

    if setor:
        filtros.append("(LOWER(COALESCE(e.setor, '')) LIKE ? OR LOWER(COALESCE(o.local_predial, '')) LIKE ?)")
        like = f"%{setor.lower()}%"
        parametros.extend([like, like])

    if responsavel:
        filtros.append("LOWER(COALESCE(o.responsavel, '')) LIKE ?")
        parametros.append(f"%{responsavel.lower()}%")

    if prioridade and prioridade != "Todos":
        filtros.append("o.prioridade = ?")
        parametros.append(prioridade)

    if pesquisa:
        like = f"%{pesquisa.lower()}%"
        filtros.append("""(
            LOWER(COALESCE(o.descricao, '')) LIKE ?
            OR LOWER(COALESCE(o.solicitante, '')) LIKE ?
            OR LOWER(COALESCE(o.responsavel, '')) LIKE ?
            OR LOWER(COALESCE(e.codigo, '')) LIKE ?
            OR LOWER(COALESCE(e.nome, '')) LIKE ?
            OR LOWER(COALESCE(v.codigo, '')) LIKE ?
            OR LOWER(COALESCE(v.identificacao, '')) LIKE ?
            OR LOWER(COALESCE(v.placa, '')) LIKE ?
        )""")
        parametros.extend([like] * 8)

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT
        o.*,
        COALESCE(o.tipo_objeto, 'EQUIPAMENTO') AS tipo_objeto,
        e.codigo AS equipamento_codigo,
        e.nome AS equipamento_nome,
        e.setor AS equipamento_setor,
        e.criticidade AS equipamento_criticidade,
        v.codigo AS veiculo_codigo,
        v.identificacao AS veiculo_identificacao,
        v.placa AS veiculo_placa,
        CASE
            WHEN COALESCE(o.tipo_objeto, 'EQUIPAMENTO') = 'VEICULO' THEN
                COALESCE(v.identificacao, 'Veiculo nao encontrado') ||
                CASE WHEN COALESCE(v.placa, '') <> '' THEN ' | ' || v.placa ELSE '' END
            WHEN COALESCE(o.tipo_objeto, 'EQUIPAMENTO') = 'PREDIAL' THEN
                COALESCE(o.categoria_predial, 'Predial') || ' | ' ||
                COALESCE(o.local_predial, '')
            ELSE
                COALESCE(e.nome, 'Equipamento nao encontrado')
        END AS objeto_nome,
        o.op_id,
        o.parada_id,
        o.motivo_parada,
        o.hora_abertura,
        o.hora_conclusao,
        o.pecas_utilizadas,
        o.observacoes_finais,
        o.sgi_nc_id,
        (
            SELECT COUNT(*)
            FROM manutencao_ordem_recursos r
            WHERE r.ordem_id = o.id AND COALESCE(r.status, '') <> 'Cancelado'
        ) AS total_materiais
    FROM manutencao_ordens o
    LEFT JOIN manutencao_equipamentos e ON e.id = o.equipamento_id
    LEFT JOIN manutencao_veiculos v ON v.id = o.veiculo_id
    {where}
    ORDER BY
        CASE o.status
            WHEN 'Aberta' THEN 1
            WHEN 'Em andamento' THEN 2
            WHEN 'Aguardando peca' THEN 3
            WHEN 'Concluida' THEN 4
            ELSE 5
        END,
        o.data_abertura DESC,
        o.id DESC
    """), tuple(parametros))
    ordens = cursor.fetchall()
    conn.close()
    return ordens


def listar_recursos_por_ordens(ordem_ids):
    criar_tabelas_manutencao()
    if not ordem_ids:
        return {}

    placeholders = ", ".join(["?"] * len(ordem_ids))
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT
        r.*,
        i.descricao AS insumo_nome,
        i.unidade AS insumo_unidade
    FROM manutencao_ordem_recursos r
    LEFT JOIN almoxarifado_insumos i ON i.id = r.insumo_id
    WHERE r.ordem_id IN ({placeholders})
    ORDER BY r.id ASC
    """), tuple(ordem_ids))
    recursos = cursor.fetchall()
    conn.close()

    recursos_por_ordem = {}
    for recurso in recursos:
        chave = str(recurso["ordem_id"])
        recursos_por_ordem.setdefault(chave, []).append(recurso)
    return recursos_por_ordem


def listar_eventos_ordem(ordem_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_ordem_eventos
    WHERE ordem_id = ?
    ORDER BY id ASC
    """), (ordem_id,))
    eventos = cursor.fetchall()
    conn.close()
    return eventos


def _buscar_recurso_cursor(cursor, recurso_id, ordem_id):
    cursor.execute(q("""
    SELECT *
    FROM manutencao_ordem_recursos
    WHERE id = ? AND ordem_id = ?
    """), (recurso_id, ordem_id))
    return cursor.fetchone()


def _registrar_evento_cursor(cursor, ordem_id, recurso_id, evento, descricao, anterior, novo, usuario_id, usuario_nome):
    cursor.execute(q("""
    INSERT INTO manutencao_ordem_eventos (
        ordem_id, recurso_id, evento, descricao, valor_anterior, valor_novo, usuario_id, usuario_nome
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), (ordem_id, recurso_id, evento, descricao, anterior, novo, usuario_id, usuario_nome))


def salvar_recursos_ordem(ordem_id, linhas, usuario_id=0, usuario_nome="Sistema"):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    try:
        _salvar_recursos_ordem_cursor(cursor, ordem_id, linhas, usuario_id, usuario_nome)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _salvar_recursos_ordem_cursor(cursor, ordem_id, linhas, usuario_id=0, usuario_nome="Sistema"):
    for linha in linhas:
        recurso_id = int(linha.get("id") or 0)

        if linha.get("remover") == "Sim":
            if recurso_id:
                anterior = _buscar_recurso_cursor(cursor, recurso_id, ordem_id)
                cursor.execute(q("""
                UPDATE manutencao_ordem_recursos
                SET status = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND ordem_id = ?
                """), ("Cancelado", recurso_id, ordem_id))
                if anterior:
                    _registrar_evento_cursor(
                        cursor, ordem_id, recurso_id, "Material cancelado",
                        "Item removido/cancelado da lista de materiais",
                        str(dict(anterior)), "status=Cancelado", usuario_id, usuario_nome)
            continue

        descricao = (linha.get("descricao") or "").strip()
        if not descricao:
            continue

        dados = (
            ordem_id,
            linha.get("tipo") or "Material",
            descricao,
            int(linha.get("insumo_id") or 0) or None,
            (linha.get("descricao_complementar") or "").strip(),
            float(linha.get("quantidade") or 0),
            (linha.get("unidade") or "").strip(),
            (linha.get("fornecedor") or "").strip(),
            float(linha.get("valor_estimado") or 0),
            linha.get("status") or "Necessario",
            (linha.get("observacoes") or "").strip(),
            usuario_id,
            usuario_nome,
        )

        if recurso_id:
            anterior = _buscar_recurso_cursor(cursor, recurso_id, ordem_id)
            cursor.execute(q("""
            UPDATE manutencao_ordem_recursos
            SET
                tipo = ?,
                descricao = ?,
                insumo_id = ?,
                descricao_complementar = ?,
                quantidade = ?,
                unidade = ?,
                fornecedor = ?,
                valor_estimado = ?,
                status = ?,
                observacoes = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND ordem_id = ?
            """), (*dados[1:11], recurso_id, ordem_id))
            if anterior:
                _registrar_evento_cursor(
                    cursor, ordem_id, recurso_id, "Material alterado",
                    "Item da lista de materiais atualizado",
                    str(dict(anterior)), str(dados[1:10]), usuario_id, usuario_nome)
        else:
            cursor.execute(q("""
            INSERT INTO manutencao_ordem_recursos (
                ordem_id,
                tipo,
                descricao,
                insumo_id,
                descricao_complementar,
                quantidade,
                unidade,
                fornecedor,
                valor_estimado,
                status,
                observacoes,
                usuario_id,
                usuario_nome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """), dados)
            cursor.execute("SELECT LASTVAL() as id" if DATABASE_URL else "SELECT last_insert_rowid() as id")
            novo = cursor.fetchone()
            _registrar_evento_cursor(
                cursor, ordem_id, novo["id"], "Material incluido",
                "Item incluido na lista de materiais", "", str(dados[1:10]),
                usuario_id, usuario_nome)
