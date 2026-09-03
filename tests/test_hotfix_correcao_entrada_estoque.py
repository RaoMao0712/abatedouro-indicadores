import sqlite3

import pytest

from modules.almoxarifado import services as estoque
from modules.relatorios import almoxarifado as relatorio_almoxarifado


@pytest.fixture()
def banco_sintetico(tmp_path, monkeypatch):
    caminho = tmp_path / "estoque_hotfix.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(estoque, "DATABASE_URL", None)
    monkeypatch.setattr(estoque, "conectar", conectar)
    monkeypatch.setattr(relatorio_almoxarifado, "conectar", conectar)
    estoque.criar_tabelas_estoque_almoxarifado()
    conn = conectar()
    conn.executemany(
        "INSERT INTO almoxarifado_insumos(descricao,categoria,unidade,ativo) VALUES(?,?,?,'Sim')",
        [("Bandeja", "Embalagem", "Un"), ("Caixa", "Embalagem", "Un")],
    )
    conn.commit()
    conn.close()
    return conectar


def _entrada(banco, *, insumo=1, quantidade="1000", valor="15", nf="NF-1"):
    estoque.salvar_entrada_estoque_almoxarifado({
        "insumo_id": str(insumo), "data_entrada": "2026-09-03", "quantidade": quantidade,
        "valor_unitario": valor, "fornecedor": "Fornecedor A", "numero_nf": nf,
        "lote": "L-1", "validade": "2027-09-03", "observacoes": "Conferida",
    }, usuario="Operadora PCP")
    conn = banco()
    entrada_id = conn.execute("SELECT MAX(id) FROM almoxarifado_lotes").fetchone()[0]
    conn.close()
    return entrada_id


def _form(*, quantidade="1000", valor="0,15", versao="0", chave="REQ-1", motivo="Valor digitado incorretamente"):
    return {
        "quantidade": quantidade, "valor_unitario": valor, "fornecedor": "Fornecedor corrigido",
        "numero_nf": "NF-2", "lote": "L-2", "validade": "2027-10-01",
        "observacoes": "Revisada", "motivo_correcao": motivo, "confirmacao": "sim",
        "idempotency_key": chave, "versao": versao, "insumo_id": "1", "valor_total": "999999",
    }


def _corrigir(entrada_id, form):
    return estoque.corrigir_entrada_estoque_almoxarifado(
        entrada_id, form, usuario="Gerente", usuario_id=7, perfil="gerencia",
        idempotency_key=form.get("idempotency_key"),
    )


def test_preco_corrigido_preserva_fisico_recalcula_total_valor_estoque_e_audita(banco_sintetico):
    principal = _entrada(banco_sintetico)
    outra_mesmo_material = _entrada(banco_sintetico, quantidade="5", valor="2", nf="NF-OUTRA")
    outro_material = _entrada(banco_sintetico, insumo=2, quantidade="8", valor="3", nf="NF-CAIXA")

    resultado = _corrigir(principal, _form())
    assert resultado["reaplicada"] is True
    conn = banco_sintetico()
    lote = conn.execute("SELECT * FROM almoxarifado_lotes WHERE id=?", (principal,)).fetchone()
    movimento = conn.execute("SELECT * FROM almoxarifado_movimentacoes WHERE lote_id=?", (principal,)).fetchone()
    auditoria = conn.execute("SELECT * FROM almoxarifado_correcoes_entrada WHERE entrada_id=?", (principal,)).fetchone()
    assert lote["quantidade_inicial"] == lote["quantidade_atual"] == 1000
    assert lote["valor_unitario"] == pytest.approx(.15)
    assert lote["valor_total"] == pytest.approx(150)
    assert movimento["valor_total"] == pytest.approx(150)
    assert conn.execute("SELECT quantidade_inicial FROM almoxarifado_lotes WHERE id=?", (outra_mesmo_material,)).fetchone()[0] == 5
    assert conn.execute("SELECT quantidade_inicial FROM almoxarifado_lotes WHERE id=?", (outro_material,)).fetchone()[0] == 8
    saldo = next(item for item in estoque.buscar_saldos_almoxarifado() if item["id"] == 1)
    assert saldo["saldo_atual"] == pytest.approx(1005)
    assert saldo["valor_estoque"] == pytest.approx(160)
    filtros = {"categoria": "Todas", "insumo": "Bandeja", "fornecedor": "", "numero_nf": "",
               "lote": "", "status_lote": "Todos", "somente_com_saldo": "Nao", "por_pagina": 100}
    linha_relatorio = relatorio_almoxarifado.buscar_saldos(filtros)[0]
    assert linha_relatorio["saldo_atual"] == pytest.approx(1005)
    assert linha_relatorio["valor_estoque"] == pytest.approx(160)
    esperado = {"usuario": "Gerente", "usuario_id": 7, "quantidade_anterior": "1000.0000",
                "quantidade_nova": "1000.0000", "valor_unitario_anterior": "15.0000",
                "valor_unitario_novo": "0.1500", "total_anterior": "15000.0000",
                "total_novo": "150.0000", "impacto_financeiro": "-14850.0000",
                "metodo": "correção direta"}
    assert {chave: auditoria[chave] for chave in esperado} == esperado
    conn.close()


def test_aceita_virgula_e_ponto_sem_float_no_calculo(banco_sintetico):
    primeiro = _entrada(banco_sintetico, valor="15,00")
    _corrigir(primeiro, _form(valor="0,15"))
    segundo = _entrada(banco_sintetico, nf="NF-PONTO")
    formulario = _form(valor="0.15", chave="REQ-2")
    _corrigir(segundo, formulario)
    conn = banco_sintetico()
    assert [r[0] for r in conn.execute("SELECT valor_total FROM almoxarifado_lotes WHERE id IN (?,?) ORDER BY id", (primeiro, segundo))] == [150, 150]
    conn.close()


@pytest.mark.parametrize("valor", ["-0,01", "abc", "NaN", "Infinity", "1.23456"])
def test_rejeita_valor_monetario_negativo_invalido_nao_finito_ou_fora_da_escala(banco_sintetico, valor):
    entrada = _entrada(banco_sintetico)
    with pytest.raises(ValueError):
        _corrigir(entrada, _form(valor=valor))


@pytest.mark.parametrize("quantidade", ["0", "-1", "abc", "NaN", "1.23456"])
def test_rejeita_quantidade_zero_negativa_invalida_nao_finita_ou_incompativel(banco_sintetico, quantidade):
    entrada = _entrada(banco_sintetico)
    with pytest.raises(ValueError):
        _corrigir(entrada, _form(quantidade=quantidade))


def test_corrige_quantidade_intacta_e_nao_permite_trocar_material(banco_sintetico):
    entrada = _entrada(banco_sintetico, quantidade="10", valor="2")
    _corrigir(entrada, _form(quantidade="12,5", valor="2", chave="REQ-QTD"))
    conn = banco_sintetico()
    lote = conn.execute("SELECT * FROM almoxarifado_lotes WHERE id=?", (entrada,)).fetchone()
    assert lote["quantidade_inicial"] == lote["quantidade_atual"] == 12.5
    assert lote["valor_total"] == 25
    conn.close()
    invalido = _form(quantidade="12,5", valor="2", chave="REQ-MAT", versao="1")
    invalido["insumo_id"] = "2"
    with pytest.raises(ValueError, match="material"):
        _corrigir(entrada, invalido)


def test_localiza_entrada_por_material_data_fornecedor_documento_e_id(banco_sintetico):
    entrada = _entrada(banco_sintetico)
    encontrados = estoque.buscar_lotes_almoxarifado_filtrado(
        "1", "Todos", "bandeja", "2026-09-03", "fornecedor a", "nf-1", str(entrada)
    )
    assert [item["id"] for item in encontrados] == [entrada]
    assert estoque.buscar_lotes_almoxarifado_filtrado(entrada_id="invalido") == []


def test_movimento_posterior_bloqueia_sem_apagar_historico(banco_sintetico):
    entrada = _entrada(banco_sintetico, quantidade="10000", valor="1")
    conn = banco_sintetico()
    conn.execute("UPDATE almoxarifado_lotes SET quantidade_atual=8800 WHERE id=?", (entrada,))
    conn.execute("INSERT INTO almoxarifado_movimentacoes(data_movimentacao,tipo,insumo_id,lote_id,quantidade,valor_unitario,valor_total) VALUES('2026-09-04','SAIDA_OP',1,?,1200,1,1200)", (entrada,))
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="inferior à quantidade já movimentada"):
        _corrigir(entrada, _form(quantidade="1000", valor="1", chave="REQ-CONS"))
    with pytest.raises(ValueError, match="movimentações posteriores"):
        _corrigir(entrada, _form(quantidade="10000", valor="0,5", chave="REQ-BLOQ"))
    conn = banco_sintetico()
    assert conn.execute("SELECT COUNT(*) FROM almoxarifado_movimentacoes WHERE lote_id=?", (entrada,)).fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM almoxarifado_correcoes_entrada WHERE entrada_id=?", (entrada,)).fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize("alteracao,erro", [
    ({"motivo_correcao": "   "}, "motivo"),
    ({"confirmacao": ""}, "Confirme"),
])
def test_motivo_e_confirmacao_sao_obrigatorios(banco_sintetico, alteracao, erro):
    entrada = _entrada(banco_sintetico)
    formulario = _form() | alteracao
    with pytest.raises(ValueError, match=erro):
        _corrigir(entrada, formulario)


def test_permissao_especifica_impede_operador_pcp(banco_sintetico):
    entrada = _entrada(banco_sintetico)
    with pytest.raises(PermissionError):
        estoque.corrigir_entrada_estoque_almoxarifado(
            entrada, _form(), usuario="Operadora", perfil="pcp", idempotency_key="NEGADA"
        )
    assert estoque.perfil_pode_corrigir_entrada("admin")
    assert estoque.perfil_pode_corrigir_entrada("gerencia")
    assert not estoque.perfil_pode_corrigir_entrada("pcp")


def test_conflito_e_retry_idempotente_nao_aplicam_duas_vezes(banco_sintetico):
    entrada = _entrada(banco_sintetico)
    formulario = _form(chave="REQ-IDEM")
    primeiro = _corrigir(entrada, formulario)
    segundo = _corrigir(entrada, formulario)
    assert primeiro["correcao_id"] == segundo["correcao_id"]
    assert segundo["reaplicada"] is False
    conn = banco_sintetico()
    assert conn.execute("SELECT COUNT(*) FROM almoxarifado_correcoes_entrada").fetchone()[0] == 1
    conn.close()
    with pytest.raises(estoque.ConflitoCorrecaoEntrada):
        _corrigir(entrada, _form(chave="REQ-CONFLITO", versao="0"))


def test_falha_na_auditoria_provoca_rollback_integral(banco_sintetico):
    entrada = _entrada(banco_sintetico)
    conn = banco_sintetico()
    conn.execute("CREATE TRIGGER falhar_auditoria BEFORE INSERT ON almoxarifado_correcoes_entrada BEGIN SELECT RAISE(ABORT, 'falha auditada'); END")
    conn.commit(); conn.close()
    with pytest.raises(sqlite3.IntegrityError):
        _corrigir(entrada, _form(chave="REQ-ROLLBACK"))
    conn = banco_sintetico()
    lote = conn.execute("SELECT quantidade_inicial,valor_unitario,valor_total,versao FROM almoxarifado_lotes WHERE id=?", (entrada,)).fetchone()
    movimento = conn.execute("SELECT valor_unitario,valor_total FROM almoxarifado_movimentacoes WHERE lote_id=?", (entrada,)).fetchone()
    assert tuple(lote) == (1000, 15, 15000, 0)
    assert tuple(movimento) == (15, 15000)
    conn.close()
