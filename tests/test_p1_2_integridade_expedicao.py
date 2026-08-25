"""Contratos transversais da estabilização P1.2 da Expedição."""

import inspect
from pathlib import Path
import sqlite3

from modules.expedicao import estoque_service
from modules.qualidade import liberacoes


ROOT = Path(__file__).resolve().parents[1]


def test_migration_sqlite_upgrade_downgrade_upgrade(tmp_path):
    banco = tmp_path / "p1-2.db"
    upgrade = (ROOT / "database" / "20260825_p1_2_integridade_expedicao_sqlite.sql").read_text(
        encoding="utf-8")
    rollback = (ROOT / "database" / "20260825_p1_2_integridade_expedicao_sqlite_rollback.sql").read_text(
        encoding="utf-8")
    conn = sqlite3.connect(banco)
    conn.execute("CREATE TABLE expedicao_itens (id INTEGER PRIMARY KEY, expedicao_id INTEGER)")
    conn.executescript(upgrade)
    assert {linha[1] for linha in conn.execute("PRAGMA table_info(expedicao_itens)")} >= {
        "ativo", "removido_em", "removido_por", "motivo_remocao"}
    conn.executescript(rollback)
    assert "ativo" not in {linha[1] for linha in conn.execute("PRAGMA table_info(expedicao_itens)")}
    conn.executescript(upgrade)
    assert conn.execute("SELECT ativo FROM expedicao_itens").fetchall() == []
    conn.close()


def test_remocoes_operacionais_nao_usam_hard_delete():
    fontes = "\n".join((
        inspect.getsource(estoque_service.remover_item_reservado),
        inspect.getsource(estoque_service.registrar_itens_historicos),
        inspect.getsource(liberacoes.remover_reserva_operacional),
    ))
    assert "DELETE FROM expedicao_itens" not in fontes
    assert "ativo=0" in fontes
    assert "removido_em" in fontes


def test_operacoes_criticas_declaram_bloqueio_de_linha_postgresql():
    for funcao in (
        estoque_service.reservar_itens,
        estoque_service.remover_item_reservado,
        estoque_service.concluir_romaneio,
        estoque_service.cancelar_romaneio,
        estoque_service.estornar_romaneio,
    ):
        assert "FOR UPDATE" in inspect.getsource(funcao)


def test_migration_postgresql_e_aditiva_e_reversivel():
    upgrade = (ROOT / "database" / "20260825_p1_2_integridade_expedicao.sql").read_text(
        encoding="utf-8")
    rollback = (ROOT / "database" / "20260825_p1_2_integridade_expedicao_rollback.sql").read_text(
        encoding="utf-8")
    assert upgrade.count("ADD COLUMN IF NOT EXISTS") == 4
    assert "DELETE " not in upgrade.upper()
    assert rollback.count("DROP COLUMN IF EXISTS") == 4


def test_telas_exibem_estado_de_reserva_e_unicode_normal():
    pedido = (ROOT / "templates" / "pedido_venda_detalhe.html").read_text(encoding="utf-8")
    romaneio = (ROOT / "templates" / "romaneio_detalhe.html").read_text(encoding="utf-8")
    assert "status_reserva_descricao" in pedido
    assert "quantidade_reservada_exibicao_mil" in pedido
    assert '"Inventário legado"' in romaneio
    assert '"Não identificada"' in romaneio
    assert '"Invent&aacute;rio legado"' not in romaneio
    assert '"N&atilde;o identificada"' not in romaneio
