import sqlite3
from contextlib import closing

from modules.producao.planejamento_reversao_op import _planejar


def test_plano_preserva_historico_e_identifica_romaneio_de_varias_ops():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE ordens_producao (id INTEGER, status TEXT, versao_operacional INTEGER);
            CREATE TABLE pa_caixas (id INTEGER, codigo_caixa TEXT, status TEXT, peso_liquido REAL, estoque_operacional INTEGER);
            CREATE TABLE pa_caixa_composicao (caixa_id INTEGER, op_id INTEGER, quantidade_bandejas INTEGER);
            CREATE TABLE estoque_eventos (id INTEGER, caixa_id INTEGER, acao TEXT, evento_origem_id INTEGER);
            CREATE TABLE expedicoes (id INTEGER, numero_romaneio TEXT, status TEXT, tipo_movimentacao TEXT);
            CREATE TABLE expedicao_itens (
                id INTEGER, expedicao_id INTEGER, caixa_id INTEGER, ativo INTEGER,
                quantidade_pacotes INTEGER, quantidade_kg REAL
            );
            CREATE TABLE estoque_produto_intermediario (op_id INTEGER, tipo TEXT, quantidade_bandejas INTEGER);
            INSERT INTO ordens_producao VALUES (1, 'Aberta', 4), (2, 'Encerrada', 1);
            INSERT INTO pa_caixas VALUES
             (10, 'PENDENTE', 'Em estoque', 12, 0),
             (11, 'FORMADA', 'Expedido', 14, 1),
             (12, 'OUTRA-OP', 'Expedido', 8, 1),
             (13, 'HISTORICA', 'Estornada', 9, 0);
            INSERT INTO pa_caixa_composicao VALUES (10, 1, 12), (11, 1, 12), (12, 2, 12), (13, 1, 12);
            INSERT INTO estoque_eventos VALUES (1, 11, 'FORMACAO_ESTOQUE', NULL);
            INSERT INTO expedicoes VALUES (8, '8', 'Concluído', 'VENDA_DIRETA');
            INSERT INTO expedicao_itens VALUES (101, 8, 11, 1, 12, NULL), (102, 8, 12, 1, 7, NULL);
            INSERT INTO estoque_produto_intermediario VALUES (1, 'ENTRADA_EMBALAGEM_PRIMARIA', 20);
        """)
        alteracoes = conn.total_changes
        plano = _planejar(conn.cursor(), 1)
        assert conn.total_changes == alteracoes
        assert plano["op"]["versao_operacional"] == 4
        assert [caixa["consequencia"] for caixa in plano["caixas"]] == [
            "INVALIDAR_CAIXA_SEM_COMPENSAR_PA", "COMPENSAR_FORMACAO", "PRESERVAR_HISTORICO",
        ]
        [doc] = plano["documentos"]
        assert doc["consequencia"] == "REVERTER_SOMENTE_ITENS_DA_OP"
        assert (doc["itens_ativos_op"], doc["itens_ativos_fora_op"]) == (1, 1)
        assert [(item["id"], item["pertence_op"]) for item in plano["itens_documentos"]] == [
            (101, 1), (102, 0),
        ]
        assert plano["executavel"] is False
