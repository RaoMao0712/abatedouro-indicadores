import sqlite3
from pathlib import Path

import pytest

from modules.producao import correcoes_administrativas as correcoes
from modules.producao.services import calcular_resumo_op


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "correcao-op.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(correcoes, "conectar", conectar)
    monkeypatch.setattr(correcoes, "DATABASE_URL", None)

    conn = conectar()
    conn.executescript("""
        CREATE TABLE ordens_producao (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            fornecedor TEXT NOT NULL,
            quantidade_aves INTEGER NOT NULL,
            mortes_antes_pendura INTEGER DEFAULT 0,
            peso_vivo REAL NOT NULL,
            peso_medio REAL NOT NULL,
            observacoes TEXT,
            status TEXT NOT NULL,
            sku TEXT
        );
        INSERT INTO ordens_producao VALUES
            (1, '2026-07-28', 'Fornecedor', 100, 0, 1000, 10, 'histórica', 'Encerrada', 'Galinha Cortada'),
            (2, '2026-07-28', 'Fornecedor', 100, 0, 900, 9, '', 'Encerrada', 'Galinha Inteira'),
            (3, '2026-07-28', 'Fornecedor', 100, 0, 800, 8, '', 'Aberta', 'Galinha Cortada'),
            (4, '2026-07-28', 'Fornecedor', 100, 0, 700, 7, '', 'Cancelada', 'Galinha Cortada');

        CREATE TABLE estoque_pi (id INTEGER PRIMARY KEY, op_id INTEGER, quantidade REAL);
        CREATE TABLE pa_caixas (id INTEGER PRIMARY KEY, op_id INTEGER, peso REAL);
        CREATE TABLE romaneios (id INTEGER PRIMARY KEY, total REAL);
        CREATE TABLE expedicoes (id INTEGER PRIMARY KEY, peso REAL);
        CREATE TABLE dre_resultados (id INTEGER PRIMARY KEY, valor REAL);
        CREATE TABLE cmv_resultados (id INTEGER PRIMARY KEY, valor REAL);
        CREATE TABLE movimentacoes_financeiras (id INTEGER PRIMARY KEY, valor REAL);
        CREATE TABLE estoque_almoxarifado (id INTEGER PRIMARY KEY, saldo REAL);

        INSERT INTO estoque_pi VALUES (1, 1, 77);
        INSERT INTO pa_caixas VALUES (1, 1, 88);
        INSERT INTO romaneios VALUES (1, 99);
        INSERT INTO expedicoes VALUES (1, 111);
        INSERT INTO dre_resultados VALUES (1, 222);
        INSERT INTO cmv_resultados VALUES (1, 333);
        INSERT INTO movimentacoes_financeiras VALUES (1, 444);
        INSERT INTO estoque_almoxarifado VALUES (1, 555);
    """)
    conn.commit()
    conn.close()

    correcoes.criar_tabelas_correcoes_administrativas_op()
    return conectar


def _usuario(nome="Gestora"):
    return {"id": 17, "nome": nome}


def _fotografia_operacional(conectar):
    conn = conectar()
    fotografia = {}
    for tabela in (
        "estoque_pi",
        "pa_caixas",
        "romaneios",
        "expedicoes",
        "dre_resultados",
        "cmv_resultados",
        "movimentacoes_financeiras",
        "estoque_almoxarifado",
    ):
        fotografia[tabela] = [tuple(linha) for linha in conn.execute(f"SELECT * FROM {tabela}")]
    conn.close()
    return fotografia


def test_gerencia_corrige_peso_recalcula_indicadores_sem_reabrir_ou_afetar_operacao(banco):
    antes = _fotografia_operacional(banco)

    resultado = correcoes.corrigir_peso_entrada_op(
        1,
        "800",
        "Correção da balança de recebimento",
        "Conferido no ticket físico",
        usuario=_usuario(),
        perfil="gerencia",
        origem="10.0.0.7",
    )

    conn = banco()
    op = conn.execute("SELECT * FROM ordens_producao WHERE id = 1").fetchone()
    auditoria = conn.execute("SELECT * FROM correcoes_administrativas_op WHERE op_id = 1").fetchone()
    conn.close()

    assert resultado == {"op_id": 1, "valor_anterior": 1000.0, "novo_valor": 800.0}
    assert op["peso_vivo"] == 800
    assert op["status"] == "Encerrada"
    assert op["peso_medio"] == 10
    assert op["quantidade_aves"] == 100
    assert op["sku"] == "Galinha Cortada"
    assert op["observacoes"] == "histórica"

    assert auditoria["numero_op"] == 1
    assert auditoria["usuario_nome"] == "Gestora"
    assert auditoria["perfil"] == "gerencia"
    assert auditoria["campo_alterado"] == "peso_vivo"
    assert auditoria["valor_anterior"] == 1000
    assert auditoria["novo_valor"] == 800
    assert auditoria["motivo"] == "Correção da balança de recebimento"
    assert auditoria["observacoes"] == "Conferido no ticket físico"
    assert auditoria["origem_sessao"] == "10.0.0.7"

    resumo = calcular_resumo_op(
        op,
        [{"quantidade": 400, "unidade": "kg"}],
        [{"quantidade": 40, "unidade": "kg", "motivo": "Perda"}],
    )
    assert resumo["rendimento"] == 50
    assert resumo["perdas_percentual"] == 5
    assert _fotografia_operacional(banco) == antes


def test_administrador_pode_corrigir_e_historico_preserva_multiplas_correcoes(banco):
    for valor, motivo in ((850, "Primeira conferência"), (825, "Conferência definitiva")):
        correcoes.corrigir_peso_entrada_op(
            2,
            valor,
            motivo,
            "",
            usuario=_usuario("Administrador"),
            perfil="admin",
            origem="127.0.0.1",
        )

    historico = correcoes.buscar_correcoes_op(2)
    assert len(historico) == 2
    assert [item["novo_valor"] for item in historico] == [825, 850]
    assert [item["valor_anterior"] for item in historico] == [850, 900]


@pytest.mark.parametrize("perfil", ["producao", "qualidade", "pcp"])
def test_perfis_operacionais_nao_podem_corrigir_e_tentativa_e_auditada(banco, perfil):
    with pytest.raises(ValueError, match="Perfil sem permissão"):
        correcoes.corrigir_peso_entrada_op(
            1,
            950,
            "Tentativa",
            "",
            usuario=_usuario(perfil),
            perfil=perfil,
            origem="10.0.0.8",
        )

    conn = banco()
    op = conn.execute("SELECT peso_vivo, status FROM ordens_producao WHERE id = 1").fetchone()
    tentativa = conn.execute(
        "SELECT * FROM tentativas_correcao_administrativa_op ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert tuple(op) == (1000, "Encerrada")
    assert tentativa["perfil"] == perfil
    assert "sem permissão" in tentativa["motivo_negacao"]


def test_motivo_e_obrigatorio_e_tentativa_fica_registrada(banco):
    with pytest.raises(ValueError, match="motivo da correção é obrigatório"):
        correcoes.corrigir_peso_entrada_op(
            1, 950, "   ", "", usuario=_usuario(), perfil="gerencia", origem="local"
        )

    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM correcoes_administrativas_op").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tentativas_correcao_administrativa_op").fetchone()[0] == 1
    assert conn.execute("SELECT peso_vivo FROM ordens_producao WHERE id = 1").fetchone()[0] == 1000
    conn.close()


@pytest.mark.parametrize(
    ("op_id", "mensagem"),
    [
        (3, "Somente OP encerrada"),
        (4, "OP cancelada"),
    ],
)
def test_estado_incompativel_bloqueia_correcao(banco, op_id, mensagem):
    with pytest.raises(ValueError, match=mensagem):
        correcoes.corrigir_peso_entrada_op(
            op_id, 650, "Ajuste", "", usuario=_usuario(), perfil="gerencia", origem="local"
        )


def test_bloqueio_administrativo_impede_correcao(banco):
    conn = banco()
    conn.execute("UPDATE ordens_producao SET bloqueada_administrativamente = 1 WHERE id = 1")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="bloqueada administrativamente"):
        correcoes.corrigir_peso_entrada_op(
            1, 950, "Ajuste", "", usuario=_usuario(), perfil="admin", origem="local"
        )


def test_tela_contem_acao_modal_alerta_e_historico():
    template = (
        Path(__file__).resolve().parents[1] / "templates" / "consultar_op.html"
    ).read_text(encoding="utf-8")

    assert "Corrigir OP" in template
    assert 'session.get("perfil") in ["admin", "gerencia"]' in template
    assert "Peso de Entrada Corrigido" in template
    assert "Motivo da Correção" in template
    assert "Todas as alterações" in template
    assert "Correções Administrativas" in template
    assert "correcoes_administrativas" in template
