"""Integração da criação de OP com o snapshot na mesma transação SQLite."""

import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DB_NAME"] = str(Path(TEMP_DIR.name) / "fase3-rota.db")
os.environ.pop("DATABASE_URL", None)

from app import app  # noqa: E402
from database import conectar  # noqa: E402
from modules.engenharia_produtos import representacao_legada  # noqa: E402
from modules.parceiros.services import PAPEL_FORNECEDOR, salvar_parceiro  # noqa: E402
import modules.producao.routes as producao_routes  # noqa: E402


def _preparar():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM op_config_snapshots")
    cursor.execute("DELETE FROM roteiro_etapa_insumos")
    cursor.execute("DELETE FROM roteiro_etapas")
    cursor.execute("DELETE FROM roteiro_versoes")
    cursor.execute("DELETE FROM sku_versoes")
    cursor.execute("DELETE FROM etapas_catalogo")
    cursor.execute("DELETE FROM receitas_sku")
    cursor.execute("DELETE FROM skus")
    cursor.execute("DELETE FROM ordens_producao")
    cursor.execute("""INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo)
        VALUES('LEG-1','Galinha Cortada','PRODUTO_ACABADO','Kg','Sim')""")
    cursor.execute("""INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo)
        VALUES('LEG-2','Galinha Inteira','PRODUTO_ACABADO','Un','Sim')""")
    conn.commit()
    conn.close()
    representacao_legada.aplicar("Teste de rota Fase 3")
    fornecedor = salvar_parceiro({
        "tipo_pessoa": "PJ", "razao_social": "Fornecedor Fase 3",
        "papeis": [PAPEL_FORNECEDOR],
    }, usuario="Teste", perfil="admin")
    return fornecedor


def _cliente():
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao["usuario_id"] = 1
        sessao["nome"] = "Teste PCP"
        sessao["perfil"] = "pcp"
    return cliente


def _form(fornecedor, sku="Galinha Cortada", gta="F3-001"):
    return {
        "data": "2026-09-24", "sku": sku, "fornecedor": str(fornecedor),
        "gta": gta, "nota_fiscal": "NF-F3", "quantidade_aves": "100",
        "peso_vivo": "200", "observacoes": "Teste Fase 3",
        "inicio_programado": "", "fim_programado": "",
    }


def test_rota_cria_op_e_snapshot_na_mesma_transacao():
    fornecedor = _preparar()
    resposta = _cliente().post("/ordem-producao", data=_form(fornecedor))
    assert resposta.status_code == 302
    conn = conectar()
    cursor = conn.cursor()
    op = cursor.execute("SELECT id,sku FROM ordens_producao WHERE gta='F3-001'").fetchone()
    snapshot = cursor.execute("SELECT snapshot_json FROM op_config_snapshots WHERE op_id=?", (op["id"],)).fetchone()
    assert op["sku"] == "Galinha Cortada"
    assert json.loads(snapshot["snapshot_json"])["sku"]["codigo"] == "LEG-1"
    conn.close()


def test_rota_reverte_op_se_snapshot_falhar(monkeypatch):
    fornecedor = _preparar()

    def falhar(*_args, **_kwargs):
        raise ValueError("snapshot sombra indisponível")

    monkeypatch.setattr(producao_routes, "gravar_snapshot", falhar)
    resposta = _cliente().post(
        "/ordem-producao", data=_form(fornecedor, "Galinha Inteira", "F3-ROLLBACK")
    )
    assert resposta.status_code == 200
    conn = conectar()
    cursor = conn.cursor()
    assert cursor.execute("SELECT COUNT(*) n FROM ordens_producao WHERE gta='F3-ROLLBACK'").fetchone()["n"] == 0
    assert cursor.execute("SELECT COUNT(*) n FROM op_config_snapshots").fetchone()["n"] == 0
    conn.close()
