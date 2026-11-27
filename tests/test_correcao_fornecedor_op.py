from contextlib import contextmanager
import json
import sqlite3

from flask import Flask
import pytest

from modules.parceiros import services as parceiros
from modules.producao import operacoes_op, routes


@pytest.fixture
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "fornecedor.db"

    @contextmanager
    def transacao():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with transacao() as conn:
        conn.executescript("""
            CREATE TABLE ordens_producao (
                id INTEGER PRIMARY KEY, fornecedor TEXT, fornecedor_parceiro_id INTEGER,
                status TEXT, versao_operacional INTEGER, quantidade_aves INTEGER,
                mortes_antes_pendura INTEGER, sku TEXT
            );
            INSERT INTO ordens_producao VALUES (1, 'Fornecedor A', 10, 'Encerrada', 4, 1250, 3, 'Galinha Inteira');
            CREATE TABLE op_operacoes_auditoria (
                op_id INTEGER, tipo TEXT, idempotency_key TEXT UNIQUE, usuario TEXT, perfil TEXT,
                motivo TEXT, etapa_destino TEXT, status_anterior TEXT, status_posterior TEXT,
                preflight_json TEXT, efeitos_json TEXT, resultado_json TEXT, ip_origem TEXT, criado_em TEXT
            );
        """)

    monkeypatch.setattr(operacoes_op, "transaction", transacao)
    monkeypatch.setattr(operacoes_op, "DATABASE_URL", None)
    monkeypatch.setattr(operacoes_op, "q", lambda sql: sql)
    monkeypatch.setattr(operacoes_op, "_bloqueio_sql", lambda: "")
    monkeypatch.setattr(parceiros, "obter_parceiro_por_papel",
                        lambda parceiro_id, papel: {"id": 20, "razao_social": "Fornecedor B"})
    return transacao


def corrigir(perfil="admin", motivo="Fornecedor original incorreto"):
    return operacoes_op.corrigir_fornecedor_op(
        1, 20, usuario="Admin", perfil=perfil, motivo=motivo,
    )


def test_corrigir_apenas_fornecedor_preserva_op_encerrada_e_audita(banco):
    assert corrigir() is True
    assert corrigir() is False
    with banco() as conn:
        assert tuple(conn.execute("SELECT * FROM ordens_producao").fetchone()) == (
            1, "Fornecedor B", 20, "Encerrada", 4, 1250, 3, "Galinha Inteira",
        )
        [evento] = conn.execute("SELECT * FROM op_operacoes_auditoria").fetchall()
        assert evento["tipo"] == "CORRECAO_CADASTRAL_FORNECEDOR"
        assert evento["status_anterior"] == evento["status_posterior"] == "Encerrada"
        assert json.loads(evento["resultado_json"])["fornecedor_anterior"]["id"] == 10


def test_auditoria_invalida_reverte_correcao(banco, monkeypatch):
    with pytest.raises(PermissionError):
        corrigir(perfil="pcp")
    with pytest.raises(ValueError):
        corrigir(motivo="   ")

    def falhar(*args, **kwargs):
        raise RuntimeError("Auditoria indisponível")

    monkeypatch.setattr(operacoes_op, "_auditar", falhar)
    with pytest.raises(RuntimeError, match="Auditoria indisponível"):
        corrigir()
    with banco() as conn:
        assert conn.execute("SELECT fornecedor_parceiro_id FROM ordens_producao").fetchone()[0] == 10


def test_rota_exige_administrador_e_csrf(banco, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "teste"
    app.add_url_rule("/login", "login", lambda: "")
    routes.register_producao_routes(app)
    monkeypatch.setattr(routes, "buscar_op_por_id", lambda op_id: {"id": op_id})
    cliente = app.test_client()
    url = "/op/1/corrigir-fornecedor"
    dados = {"fornecedor": "20", "motivo": "Motivo cadastral", "csrf_token": "teste"}
    assert cliente.post(url, data=dados).location == "/login"
    with cliente.session_transaction() as sessao:
        sessao.update(usuario_id=1, perfil="pcp", nome="PCP")
    assert cliente.post(url, data=dados).status_code == 403
    with cliente.session_transaction() as sessao:
        sessao.update(perfil="admin", nome="Admin", csrf_correcao_fornecedor_op="teste")
    assert cliente.post(url, data={**dados, "csrf_token": ""}).status_code == 403
    assert cliente.post(url, data=dados).location == "/consultar-op?op_id=1"
