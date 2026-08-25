from decimal import Decimal
from io import BytesIO
from pathlib import Path
import sqlite3

from openpyxl import load_workbook

from modules.relatorios import expedicao as relatorio_expedicao
from modules.relatorios.expedicao import (
    agrupar_estoque_oficial,
    gerar_excel_relatorio_expedicao,
    linhas_estoque_oficial,
    reconciliar_estoque_oficial,
    resumo_estoque_oficial,
)
from modules.relatorios.producao import cte_ops_agregadas, normalizar_filtros


def _situacao(rotulo, **quantidades):
    return {"rotulo": rotulo, "quantidades": quantidades, "origens": ["Pós-marco-zero"]}


def _fotografia():
    return {"grupos": [
        {
            "chave": "galinha_cortada", "sku_codigo": "LEG-1", "produto": "Galinha Cortada",
            "apresentacao": "Congelada", "classificado": True,
            "unidades": ["caixas", "bandejas", "peso_kg"],
            "situacoes": {
                "disponivel": _situacao("Disponível para expedição", caixas=2, bandejas=18, peso_kg=Decimal("41.460")),
                "reservado": _situacao("Reservado", caixas=1, bandejas=4, peso_kg=Decimal("8.250")),
                "nao_conforme_bloqueado": _situacao("Não conforme bloqueado", caixas=1, bandejas=2, peso_kg=Decimal("4.125")),
            },
        },
        {
            "chave": "galinha_inteira_v2", "sku_codigo": "LEG-2", "produto": "Galinha Inteira",
            "apresentacao": "Pacote com 2 aves", "classificado": True,
            "unidades": ["galinhas", "pacotes"],
            "situacoes": {
                "disponivel": _situacao("Disponível para expedição", galinhas=3972, pacotes=1986),
                "reservado": _situacao("Reservado", galinhas=20, pacotes=10),
                "nao_conforme_bloqueado": _situacao("Não conforme bloqueado", galinhas=0, pacotes=0),
            },
        },
    ]}


def _filtros(**valores):
    base = {"sku": "Todos", "apresentacao": "", "status": "Todos", "origem": "Todos"}
    base.update(valores)
    return base


def test_tela_cards_e_servico_compartilham_decimal_e_conjunto_completo():
    fotografia = _fotografia()
    linhas = linhas_estoque_oficial(fotografia, _filtros())
    resumo = {item["rotulo"]: item["valor"] for item in resumo_estoque_oficial(linhas)}
    assert resumo == {
        "Caixas": 4, "Bandejas": 24, "Peso físico": Decimal("53.835"),
        "Galinhas": 3992, "Pacotes": 1996,
    }
    assert reconciliar_estoque_oficial(fotografia, linhas, _filtros())["ok"] is True
    alteradas = [dict(item) for item in linhas]
    alteradas[0]["peso_kg"] += Decimal("0.001")
    assert reconciliar_estoque_oficial(fotografia, alteradas, _filtros())["ok"] is False


def test_filtros_status_produto_apresentacao_e_origem_afetam_cards_e_linhas_igualmente():
    filtros = _filtros(sku="LEG-2", apresentacao="2 aves", status="reservado", origem="Pós-marco-zero")
    linhas = linhas_estoque_oficial(_fotografia(), filtros)
    assert len(linhas) == 1
    assert linhas[0]["pacotes"] == 10 and linhas[0]["galinhas"] == 20
    assert resumo_estoque_oficial(linhas)[4]["valor"] == 10
    assert agrupar_estoque_oficial(linhas)[0]["pacotes"] == 10


def test_contexto_estoque_nao_depende_da_consulta_legada_e_repassa_filtros(monkeypatch):
    monkeypatch.setattr(relatorio_expedicao, "consolidar_estoque_camara", lambda **_opcoes: _fotografia())
    monkeypatch.setattr(
        relatorio_expedicao, "buscar_opcoes_filtro",
        lambda: (_ for _ in ()).throw(AssertionError("consulta paralela não deve ser usada")),
    )
    contexto = relatorio_expedicao.montar_contexto_relatorio_expedicao(
        "estoque-camara-fria", {"sku": "LEG-2", "status": "reservado"})
    assert contexto["reconciliacao"]["ok"] is True
    assert len(contexto["detalhes"]) == 1 and contexto["detalhes"][0]["pacotes"] == 10
    assert "por_pagina" not in contexto["query_string"]
    gerencial = relatorio_expedicao.montar_resumo_gerencial_expedicao(
        "estoque-camara-fria", {"sku": "LEG-2", "status": "reservado"})
    assert gerencial["reconciliacao"]["ok"] is True
    assert gerencial["resumo"][4]["valor"] == 10


def test_excel_exporta_exatamente_as_linhas_filtradas_com_numeros_reais():
    filtros = _filtros(sku="LEG-1", status="disponivel")
    linhas = linhas_estoque_oficial(_fotografia(), filtros)
    contexto = {
        "slug": "estoque-camara-fria",
        "config": {"titulo": "Estoque Câmara Fria", "objetivo": "Posição atual"},
        "filtros": filtros,
        "resumo": resumo_estoque_oficial(linhas),
        "agrupamentos": agrupar_estoque_oficial(linhas),
        "detalhes": linhas,
    }
    arquivo = gerar_excel_relatorio_expedicao(contexto)
    ws = load_workbook(BytesIO(arquivo.getvalue()), data_only=True).active
    valores = list(ws.values)
    cabecalho = valores.index(("sku", "produto", "apresentacao", "situacao_rotulo", "origens",
                               "caixas", "bandejas", "peso_kg", "galinhas", "pacotes"))
    detalhe = valores[cabecalho + 1]
    assert detalhe[:5] == ("LEG-1", "Galinha Cortada", "Congelada", "Disponível para expedição", "Pós-marco-zero")
    assert detalhe[5:10] == (2, 18, 41.46, 0, 0)


def test_relatorio_producao_exclui_op_estornada_do_volume_operacional():
    filtros = normalizar_filtros({
        "data_inicio": "2026-08-01", "data_fim": "2026-08-31", "sku": "Todos",
        "op_id": "", "fornecedor": "Todos", "status": "Todos", "causa": "Todos", "setor": "Todos",
    })
    sql, parametros = cte_ops_agregadas(filtros)
    assert "NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')" in sql
    assert parametros == ["2026-08-01", "2026-08-31"]


def test_migration_snapshot_sqlite_e_aditiva_reversivel(tmp_path):
    conn = sqlite3.connect(tmp_path / "p1-3.db")
    conn.execute("CREATE TABLE embalagem_secundaria_conferencias(id INTEGER PRIMARY KEY, hash_conferencia TEXT)")
    raiz = Path(__file__).resolve().parents[1] / "database"
    conn.executescript((raiz / "20260825_p1_3_snapshot_conferencia_embalagem_sqlite.sql").read_text(encoding="utf-8"))
    assert "snapshot_json" in {item[1] for item in conn.execute("PRAGMA table_info(embalagem_secundaria_conferencias)")}
    conn.executescript((raiz / "20260825_p1_3_snapshot_conferencia_embalagem_sqlite_rollback.sql").read_text(encoding="utf-8"))
    assert "snapshot_json" not in {item[1] for item in conn.execute("PRAGMA table_info(embalagem_secundaria_conferencias)")}
    conn.close()
