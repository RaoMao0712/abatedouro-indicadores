"""GET /op/<id>/editar continua funcional após a Etapa B (SQLite).

Cobre a Etapa B do hotfix do 502/WORKER TIMEOUT em /op/<id>/editar (ver
output/hotfix-op97-502-auditoria-etapa-a.md e a nota de divergência no
relatório da Etapa B). A rota `editar_op` nunca chamou nenhuma das quatro
funções que emitem ALTER TABLE ordens_producao redundante; este teste
reconfirma isso na prática e garante que a tela de edição de OP (equivalente
à OP 97) segue funcional, sem workaround na rota.

Roda via SQLite, caminho já usado pelos demais testes locais (ver
tests/test_qual_sgi_01.py, tests/test_expedicao_marco_zero.py). Em SQLite:

  * criar_tabelas_estoque_confiavel, criar_tabelas_operacoes_op e
    criar_tabelas_correcoes_administrativas_op continuam rodando o
    ALTER TABLE ordens_producao normalmente, uma única vez por processo
    (guarda em memória) — comportamento inalterado, documentado nos módulos
    editados.
  * criar_tabelas_parceiros (módulo modules/parceiros/services.py) NÃO tem
    guarda de processo e é chamada a cada requisição por
    listar_parceiros_elegiveis()/obter_parceiro_por_papel(), usadas por
    editar_op. Isso significa que, em SQLite, um ALTER TABLE
    ordens_producao ADD COLUMN fornecedor_parceiro_id pode aparecer em TODA
    requisição a /op/<id>/editar — comportamento pré-existente e inalterado
    por esta Etapa B (só o ramo PostgreSQL dessa função foi tocado). Por
    isso este teste não afirma ausência de ALTER TABLE durante a
    requisição em SQLite; ele confirma apenas que a rota continua
    funcional. A ausência de DDL redundante contra PostgreSQL é provada em
    tests/test_hotfix_op502_ddl_bootstrap.py.
"""

from pathlib import Path
import os
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_DIR = tempfile.TemporaryDirectory()
DB_PATH = Path(TEMP_DIR.name) / "hotfix-op502.db"
os.environ["DB_NAME"] = str(DB_PATH)
os.environ.pop("DATABASE_URL", None)

from app import app  # noqa: E402
from database import conectar, q  # noqa: E402
from modules.parceiros.services import PAPEL_FORNECEDOR, salvar_parceiro  # noqa: E402


def _nome_unico(prefixo):
    return f"{prefixo} {uuid.uuid4().hex[:8]}"


def _semear_op_equivalente_op97(nome_fornecedor=None):
    nome_fornecedor = nome_fornecedor or _nome_unico("Fornecedor Teste OP97")
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(
        "INSERT INTO ordens_producao "
        "(data, fornecedor, gta, nota_fiscal, quantidade_aves, peso_vivo, peso_medio, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    ), ("2026-09-14", nome_fornecedor, "GTA-97", "NF-97", 1000, 2500.0, 2.5, "Aberta"))
    op_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return op_id


def test_boot_da_aplicacao_funciona_via_sqlite():
    assert app is not None
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ordens_producao'")
    assert cursor.fetchone() is not None
    conn.close()


def test_carregamento_de_parceiros_fornecedores_continua_funcionando():
    """Cadastro de Parceiros (fonte atual de fornecedores) segue funcional."""
    nome = _nome_unico("Fornecedor Disponibilidade Teste")
    salvar_parceiro(
        {"tipo_pessoa": "PJ", "razao_social": nome, "papeis": [PAPEL_FORNECEDOR]},
        usuario="Teste Etapa B", perfil="admin",
    )

    from modules.producao.services import buscar_fornecedores

    nomes = [linha["nome"] for linha in buscar_fornecedores()]
    assert nome in nomes


def test_rota_editar_op_funciona():
    """Cenário equivalente à OP 97: GET /op/<id>/editar funcional."""
    op_id = _semear_op_equivalente_op97()

    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao["usuario_id"] = 1
        sessao["nome"] = "Teste PCP"
        sessao["perfil"] = "pcp"

    resposta = cliente.get(f"/op/{op_id}/editar")
    assert resposta.status_code == 200


def test_rota_consulta_op_funciona():
    op_id = _semear_op_equivalente_op97()

    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao["usuario_id"] = 1
        sessao["nome"] = "Teste PCP"
        sessao["perfil"] = "pcp"

    resposta = cliente.get(f"/consultar-op?op_id={op_id}")
    assert resposta.status_code == 200
