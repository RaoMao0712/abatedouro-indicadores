from contextlib import contextmanager
from pathlib import Path
import sqlite3

import pytest
from jinja2 import Environment, select_autoescape

from modules.qualidade import liberacoes
from modules.qualidade import produtos_nao_conformes as nc
from modules.qualidade import reconciliacao_p1_1_1 as reconciliacao


ALVO = "INVENTARIO_NC_2026_07_30_AGUARDANDO_LIBERACAO"


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "p1-1-1.db"

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

    for modulo in (nc, liberacoes, reconciliacao):
        monkeypatch.setattr(modulo, "conectar", conectar)
        monkeypatch.setattr(modulo, "transaction", transacao)
        monkeypatch.setattr(modulo, "DATABASE_URL", None)
    conn = conectar()
    conn.executescript("""
        CREATE TABLE locais_estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL,
            tipo TEXT NOT NULL, ativo TEXT NOT NULL
        );
        CREATE TABLE skus (
            id INTEGER PRIMARY KEY, codigo TEXT, nome TEXT, ativo TEXT, excluido_em TEXT
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


def _preparar_inconsistencia_legada(banco):
    liberacoes.carregar_inventario(confirmar=True, usuario="Carga", perfil="admin", origem="teste")
    conn = banco[0]()
    registro = conn.execute("SELECT * FROM pa_nao_conformes WHERE idempotency_key=?", (ALVO,)).fetchone()
    conn.close()
    solicitacao = liberacoes.solicitar(
        registro["id"], "595,500", 48, 570, "Liberação integral",
        usuario="Qualidade", usuario_id=10, perfil="qualidade", origem="teste",
        idempotency_key="P111-SOLICITACAO-APROVADA",
    )
    liberacoes.validar(
        solicitacao, "APROVAR", "Produto conforme",
        usuario="Gerência", usuario_id=20, perfil="gerencia", origem="teste",
    )
    conn = banco[0]()
    conn.execute("""UPDATE pa_nao_conformes SET status='BLOQUEADO',decisao=NULL,
        decidido_por=NULL,perfil_decisao=NULL,decidido_em=NULL,
        justificativa_destinacao=NULL WHERE id=?""", (registro["id"],))
    conn.execute("""UPDATE pa_nao_conforme_eventos SET status_novo='BLOQUEADO'
        WHERE pa_nao_conforme_id=? AND acao='APROVACAO_LIBERACAO'""", (registro["id"],))
    conn.commit()
    conn.close()
    return registro["id"], solicitacao


def _estoque(banco, registro_id):
    conn = banco[0]()
    linha = conn.execute("""SELECT saldo_inicial_g,saldo_bloqueado_g,saldo_pendente_g,
        saldo_operacional_g,saldo_reservado_operacional_g,saldo_destinado_g,
        caixas_iniciais,bandejas_iniciais,caixas_bloqueadas,bandejas_bloqueadas
        FROM pa_nao_conformes WHERE id=?""", (registro_id,)).fetchone()
    conn.close()
    return tuple(linha)


def test_reconciliacao_aplica_somente_estado_e_evento_uma_vez(banco):
    registro_id, solicitacao_id = _preparar_inconsistencia_legada(banco)
    estoque_antes = _estoque(banco, registro_id)
    diagnostico = reconciliacao.diagnosticar()
    assert diagnostico["apto"] is True
    assert diagnostico["solicitacao_aprovada_id"] == solicitacao_id
    assert diagnostico["evento_aprovacao_id"] is not None

    primeira = reconciliacao.reconciliar(confirmar=True)
    segunda = reconciliacao.reconciliar(confirmar=True)
    assert primeira["alterado"] is True
    assert segunda["alterado"] is False
    assert segunda["ja_aplicada"] is True
    assert _estoque(banco, registro_id) == estoque_antes

    conn = banco[0]()
    registro = conn.execute("SELECT status,decisao FROM pa_nao_conformes WHERE id=?",
                            (registro_id,)).fetchone()
    eventos = conn.execute("""SELECT status_anterior,status_novo,detalhes
        FROM pa_nao_conforme_eventos WHERE pa_nao_conforme_id=? AND acao=?""",
        (registro_id, reconciliacao.ACAO_RECONCILIACAO)).fetchall()
    outros = conn.execute("SELECT status FROM pa_nao_conformes WHERE id<>? ORDER BY id",
                          (registro_id,)).fetchall()
    conn.close()
    assert tuple(registro) == ("LIBERADO", "LIBERAR")
    assert len(eventos) == 1
    assert tuple(eventos[0])[:2] == ("BLOQUEADO", "LIBERADO")
    assert '"estoque_movimentado_novamente": false' in eventos[0]["detalhes"]
    assert [item["status"] for item in outros] == ["BLOQUEADO", "BLOQUEADO"]
    assert registro_id in {item["id"] for item in nc.consultar({"situacao": "LIBERADOS"})}
    assert registro_id not in {item["id"] for item in nc.consultar({"situacao": "BLOQUEADOS"})}
    assert registro_id in {item["id"] for item in nc.consultar({"situacao": "FINALIZADOS"})}


@pytest.mark.parametrize("divergencia", [
    "saldo_bloqueado", "solicitacao_nao_integral", "destinacao_incompativel",
])
def test_reconciliacao_aborta_quando_precondicao_diverge(banco, divergencia):
    registro_id, solicitacao_id = _preparar_inconsistencia_legada(banco)
    conn = banco[0]()
    if divergencia == "saldo_bloqueado":
        conn.execute("UPDATE pa_nao_conformes SET saldo_bloqueado_g=1 WHERE id=?", (registro_id,))
    elif divergencia == "solicitacao_nao_integral":
        conn.execute("UPDATE pa_nao_conforme_solicitacoes SET peso_g=595499 WHERE id=?",
                     (solicitacao_id,))
    else:
        conn.execute("UPDATE pa_nao_conformes SET decisao='DESCARTE' WHERE id=?", (registro_id,))
    conn.commit()
    conn.close()
    estoque_antes = _estoque(banco, registro_id)
    with pytest.raises(RuntimeError, match="Reconciliação abortada"):
        reconciliacao.reconciliar(confirmar=True)
    assert _estoque(banco, registro_id) == estoque_antes
    conn = banco[0]()
    assert conn.execute("SELECT status FROM pa_nao_conformes WHERE id=?", (registro_id,)).fetchone()[0] == "BLOQUEADO"
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conforme_eventos WHERE acao=?",
                        (reconciliacao.ACAO_RECONCILIACAO,)).fetchone()[0] == 0
    conn.close()


def test_rollback_reverte_somente_documento_e_e_idempotente(banco):
    registro_id, _ = _preparar_inconsistencia_legada(banco)
    estoque_antes = _estoque(banco, registro_id)
    reconciliacao.reconciliar(confirmar=True)
    primeira = reconciliacao.reverter(confirmar=True)
    segunda = reconciliacao.reverter(confirmar=True)
    assert primeira["alterado"] is True
    assert segunda["alterado"] is False and segunda["ja_revertida"] is True
    assert _estoque(banco, registro_id) == estoque_antes
    conn = banco[0]()
    assert conn.execute("SELECT status FROM pa_nao_conformes WHERE id=?", (registro_id,)).fetchone()[0] == "BLOQUEADO"
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conforme_eventos WHERE acao=?",
                        (reconciliacao.ACAO_ROLLBACK,)).fetchone()[0] == 1
    conn.close()


def test_textos_pnc_usam_unicode_normal_sem_safe_ou_dupla_decodificacao():
    raiz = Path(__file__).resolve().parents[1]
    lista = (raiz / "templates" / "produtos_nao_conformes.html").read_text(encoding="utf-8")
    detalhe = (raiz / "templates" / "produto_nao_conforme_detalhe.html").read_text(encoding="utf-8")
    rotas = (raiz / "modules" / "qualidade" / "routes.py").read_text(encoding="utf-8")
    assert "'Não identificada'" in lista and "'Não identificado'" in lista
    assert "'Inventário legado agregado'" in detalhe
    assert "'Produção rastreada'" in detalhe
    assert "N&atilde;o identificada" not in lista + detalhe
    assert "Invent&aacute;rio legado agregado" not in detalhe
    assert "|safe" not in lista + detalhe
    assert "html.unescape" not in lista + detalhe + rotas
    assert '"Não identificada"' in rotas and '"Não identificado"' in rotas

    ambiente = Environment(autoescape=select_autoescape(default=True))
    template = ambiente.from_string("{{ valor }}")
    assert template.render(valor="Não identificada") == "Não identificada"
    assert template.render(valor="A & B") == "A &amp; B"
    assert "<script>" not in template.render(valor="<script>alert(1)</script>")
