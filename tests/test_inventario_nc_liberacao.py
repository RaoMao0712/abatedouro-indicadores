from contextlib import contextmanager
import sqlite3

import pytest

from modules.qualidade import liberacoes
from modules.qualidade import produtos_nao_conformes as nc


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "inventario-nc.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transacao():
        conn = conectar()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(nc, "conectar", conectar)
    monkeypatch.setattr(nc, "transaction", transacao)
    monkeypatch.setattr(nc, "DATABASE_URL", None)
    monkeypatch.setattr(liberacoes, "conectar", conectar)
    monkeypatch.setattr(liberacoes, "transaction", transacao)
    monkeypatch.setattr(liberacoes, "DATABASE_URL", None)

    conn = conectar()
    conn.executescript("""
        CREATE TABLE locais_estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL,
            tipo TEXT NOT NULL, ativo TEXT NOT NULL
        );
        CREATE TABLE skus (
            id INTEGER PRIMARY KEY, codigo TEXT, nome TEXT, ativo TEXT,
            excluido_em TEXT
        );
        CREATE TABLE pa_caixas (
            id INTEGER PRIMARY KEY, codigo_caixa TEXT UNIQUE, sku TEXT,
            peso_liquido REAL, quantidade_bandejas REAL, status TEXT,
            condicao TEXT, disponibilidade TEXT, zona_estoque TEXT,
            motivo_nao_conformidade TEXT, local_estoque_id INTEGER,
            estoque_operacional INTEGER, unidade_estoque TEXT,
            apresentacao TEXT, quantidade_pacotes INTEGER,
            quantidade_pacotes_reservados INTEGER DEFAULT 0
        );
        CREATE TABLE pa_caixa_composicao (
            id INTEGER PRIMARY KEY AUTOINCREMENT, caixa_id INTEGER, op_id INTEGER,
            quantidade_bandejas REAL
        );
        CREATE TABLE expedicoes (
            id INTEGER PRIMARY KEY, status TEXT, tipo_movimentacao TEXT
        );
        CREATE TABLE expedicao_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT, expedicao_id INTEGER NOT NULL,
            caixa_id INTEGER, op_id INTEGER, sku TEXT NOT NULL,
            quantidade_unidades REAL DEFAULT 0, quantidade_kg REAL DEFAULT 0,
            situacao_anterior TEXT, condicao_anterior TEXT, unidade_estoque TEXT,
            apresentacao TEXT, lote TEXT, pa_nao_conforme_id INTEGER,
            quantidade_caixas INTEGER DEFAULT 0, quantidade_bandejas INTEGER DEFAULT 0,
            origem_tipo TEXT
        );
        INSERT INTO expedicoes VALUES (1, 'Aberto', 'TRANSFERENCIA');
        INSERT INTO skus VALUES (1, 'LEG-1', 'Galinha Cortada', 'Sim', NULL);
        INSERT INTO locais_estoque(id,nome,tipo,ativo) VALUES
            (4, 'Câmara de Estocagem - Estoque Não Conforme', 'segregacao', 'Sim');
    """)
    conn.commit()
    conn.close()
    nc.criar_tabelas_pa_nao_conforme()
    return conectar, transacao


def _carga(banco):
    return liberacoes.carregar_inventario(confirmar=True, usuario="Admin", perfil="admin", origem="teste")


def _registro(banco, chave="INVENTARIO_NC_2026_07_30_AGUARDANDO_LIBERACAO"):
    conn = banco[0]()
    item = conn.execute("SELECT * FROM pa_nao_conformes WHERE idempotency_key=?", (chave,)).fetchone()
    conn.close()
    return item


def test_simulacao_e_carga_idempotente_reconciliam_totais_oficiais(banco):
    assert liberacoes.simular_carga() == {
        "registros": 3, "caixas": 867, "bandejas": 10398, "peso_g": 10472060,
    }
    primeira = _carga(banco)
    segunda = _carga(banco)
    assert (primeira["inseridos"], primeira["existentes"]) == (3, 0)
    assert (segunda["inseridos"], segunda["existentes"]) == (0, 3)
    assert primeira["ids"] == segunda["ids"]
    conn = banco[0]()
    resumo = conn.execute("""SELECT COUNT(*),SUM(saldo_inicial_g),SUM(saldo_bloqueado_g),
        SUM(saldo_operacional_g),SUM(caixas_iniciais),SUM(bandejas_iniciais)
        FROM pa_nao_conformes""").fetchone()
    eventos = conn.execute("SELECT COUNT(*) FROM pa_nao_conforme_eventos WHERE acao='CARGA_INICIAL'").fetchone()[0]
    conn.close()
    assert resumo[:] == (3, 10472060, 10472060, 0, 867, 10398)
    assert eventos == 3
    conn = banco[0]()
    registros = conn.execute("""SELECT produto,apresentacao,observacoes
        FROM pa_nao_conformes ORDER BY id""").fetchall()
    detalhes = conn.execute("""SELECT detalhes FROM pa_nao_conforme_eventos
        WHERE acao='CARGA_INICIAL' ORDER BY id""").fetchall()
    conn.close()
    assert all(item["produto"] == "Galinha Cortada" for item in registros)
    assert all(item["apresentacao"] == "Congelada" for item in registros)
    assert all("LEG-1 (ID 1)" in item["observacoes"] for item in registros)
    assert all('"sku_id": 1' in item["detalhes"] for item in detalhes)
    indicadores = nc.indicadores(nc.consultar())
    assert indicadores["fisico_total_kg"] == 10472.060
    assert indicadores["nao_conforme_bloqueado_kg"] == 9876.560
    assert indicadores["aguardando_liberacao_kg"] == 595.500
    assert indicadores["disponivel_kg"] == 0


@pytest.mark.parametrize("perfil", ["pcp", "producao", "gerencia"])
def test_apenas_qualidade_solicita(perfil, banco):
    _carga(banco)
    registro = _registro(banco)
    with pytest.raises(PermissionError):
        liberacoes.solicitar(registro["id"], "100", 8, 96, "Amostra conforme",
                             usuario=perfil, perfil=perfil, origem="teste")


def test_solicitacao_reserva_peso_e_impede_dupla_solicitacao(banco):
    _carga(banco)
    registro = _registro(banco)
    solicitacao = liberacoes.solicitar(registro["id"], "500,000", 40, 480,
        "Produto conforme", usuario="Qualidade", perfil="qualidade", origem="teste",
        idempotency_key="SOL-1")
    repetida = liberacoes.solicitar(registro["id"], "500,000", 40, 480,
        "Produto conforme", usuario="Qualidade", perfil="qualidade", origem="teste",
        idempotency_key="SOL-1")
    assert repetida == solicitacao
    with pytest.raises(ValueError, match="excede"):
        liberacoes.solicitar(registro["id"], "100,000", 8, 96, "Excesso",
            usuario="Qualidade", perfil="qualidade", origem="teste", idempotency_key="SOL-2")
    atualizado = _registro(banco)
    assert atualizado["saldo_pendente_g"] == 500000
    assert atualizado["saldo_bloqueado_g"] == 595500


def test_rejeicao_devolve_reserva_sem_alterar_fisico(banco):
    _carga(banco)
    registro = _registro(banco)
    solicitacao = liberacoes.solicitar(registro["id"], "100", 8, 96, "Avaliar",
        usuario="Qualidade", perfil="qualidade", origem="teste")
    liberacoes.validar(solicitacao, "REJEITAR", "Laudo insuficiente",
                       usuario="Gerente", perfil="gerencia", origem="teste")
    atualizado = _registro(banco)
    assert (atualizado["saldo_bloqueado_g"], atualizado["saldo_pendente_g"],
            atualizado["saldo_operacional_g"]) == (595500, 0, 0)


def test_aprovacao_parcial_e_total_movem_exatamente_o_mesmo_peso(banco):
    _carga(banco)
    registro = _registro(banco)
    parcial = liberacoes.solicitar(registro["id"], "100,250", 8, 96, "Parcial",
        usuario="Qualidade", perfil="qualidade", origem="teste")
    with pytest.raises(PermissionError):
        liberacoes.validar(parcial, "APROVAR", "Autorizo", usuario="Qualidade",
                           perfil="qualidade", origem="teste")
    liberacoes.validar(parcial, "APROVAR", "Autorizo", usuario="Gerente",
                       perfil="gerencia", origem="teste")
    meio = _registro(banco)
    assert (meio["saldo_bloqueado_g"], meio["saldo_operacional_g"]) == (495250, 100250)
    restante = liberacoes.solicitar(registro["id"], "495,250", 40, 474, "Total",
        usuario="Qualidade", perfil="qualidade", origem="teste")
    liberacoes.validar(restante, "APROVAR", "Autorizo", usuario="Admin",
                       perfil="admin", origem="teste")
    final = _registro(banco)
    assert (final["saldo_bloqueado_g"], final["saldo_pendente_g"],
            final["saldo_operacional_g"]) == (0, 0, 595500)
    with pytest.raises(ValueError, match="ja foi validada"):
        liberacoes.validar(restante, "APROVAR", "Repetir", usuario="Admin",
                           perfil="admin", origem="teste")


def test_caixa_futura_nao_fraciona_e_so_gerencia_libera(banco):
    conn = banco[0]()
    conn.execute("INSERT INTO locais_estoque(nome,tipo,ativo) VALUES ('Bloqueado','segregacao','Sim')")
    conn.execute("""INSERT INTO pa_caixas VALUES
        (10,'CX-10','Galinha Cortada',10.5,12,'Em estoque','NAO_CONFORME','BLOQUEADO',
         'Produto Nao Conforme','Falha',1,1,'CAIXA','Caixa',NULL,0)""")
    conn.execute("""INSERT INTO pa_nao_conformes (
        numero,op_id,caixa_id,lote,produto,apresentacao,quantidade,peso,unidade,motivo,status,
        local_estoque_id,registrado_por,perfil_registro,registrado_em,criado_em,atualizado_em
        ) VALUES ('PNC-CX10',7,10,'CX-10','Galinha Cortada','Caixa',12,10.5,'BANDEJA','Falha',
        'BLOQUEADO',1,'Producao','producao','2026-08-01','2026-08-01','2026-08-01')""")
    registro_id = conn.execute("SELECT id FROM pa_nao_conformes WHERE caixa_id=10").fetchone()[0]
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="nao pode ser fracionada"):
        liberacoes.solicitar(registro_id, "5", 1, 6, "Parcial", usuario="Q",
                             perfil="qualidade", origem="teste")
    solicitacao = liberacoes.solicitar(registro_id, "10,500", 1, 12, "Integral",
                                       usuario="Q", perfil="qualidade", origem="teste")
    liberacoes.validar(solicitacao, "APROVAR", "Conforme", usuario="G",
                       perfil="gerencia", origem="teste")
    conn = banco[0]()
    caixa = conn.execute("SELECT condicao,disponibilidade FROM pa_caixas WHERE id=10").fetchone()
    conn.close()
    assert caixa[:] == ("CONFORME", "DISPONIVEL")


def test_romaneio_consume_saldo_legado_por_kg_com_auxiliares(banco):
    _carga(banco)
    registro = _registro(banco)
    solicitacao = liberacoes.solicitar(registro["id"], "200", 16, 192, "Liberar",
        usuario="Q", perfil="qualidade", origem="teste")
    liberacoes.validar(solicitacao, "APROVAR", "Aprovado", usuario="G",
                       perfil="gerencia", origem="teste")
    item_id = liberacoes.reservar_operacional(1, registro["id"], "50", 4, 48,
                                               usuario="PCP", perfil="pcp", origem="teste")
    reservado = _registro(banco)
    assert (reservado["saldo_operacional_g"], reservado["saldo_reservado_operacional_g"]) == (150000, 50000)
    liberacoes.remover_reserva_operacional(1, item_id, usuario="PCP", perfil="pcp", origem="teste")
    restaurado = _registro(banco)
    assert (restaurado["saldo_operacional_g"], restaurado["saldo_reservado_operacional_g"]) == (200000, 0)
    liberacoes.reservar_operacional(1, registro["id"], "50", 4, 48,
                                    usuario="PCP", perfil="pcp", origem="teste")
    with banco[1]() as conn:
        liberacoes.concluir_reservas_cursor(conn.cursor(), 1, "PCP", "pcp", "teste")
    concluido = _registro(banco)
    assert (concluido["saldo_operacional_g"], concluido["saldo_reservado_operacional_g"],
            concluido["saldo_destinado_g"]) == (150000, 0, 50000)
    with banco[1]() as conn:
        liberacoes.estornar_baixas_cursor(conn.cursor(), 1, "Correcao", "PCP", "pcp", "teste")
    estornado = _registro(banco)
    assert (estornado["saldo_operacional_g"], estornado["saldo_destinado_g"]) == (200000, 0)
