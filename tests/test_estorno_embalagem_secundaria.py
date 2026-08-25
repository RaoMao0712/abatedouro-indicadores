from contextlib import contextmanager
from io import BytesIO
import inspect
import json
import sqlite3

import pytest
from pypdf import PdfReader

from modules.expedicao import estornos_embalagem as estornos
from modules.expedicao import services as expedicao_services
from modules.expedicao import conferencia_embalagem as conferencia
from modules.expedicao.relatorio_conferencia_embalagem import gerar_relatorio_conferencia_embalagem_pdf


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "estorno-embalagem.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transacao():
        conn = conectar()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(estornos, "conectar", conectar)
    monkeypatch.setattr(estornos, "transaction", transacao)
    monkeypatch.setattr(estornos, "DATABASE_URL", None)
    monkeypatch.setattr(estornos, "_SCHEMA_ESTORNOS_INICIALIZADO", False)
    monkeypatch.setenv("SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED", "true")
    conn = conectar()
    conn.executescript("""
        CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,status TEXT,sku TEXT,data TEXT);
        CREATE TABLE pa_caixas(
            id INTEGER PRIMARY KEY,codigo_caixa TEXT UNIQUE,sku TEXT,data_fabricacao TEXT,
            data_validade TEXT,peso_bruto REAL,peso_tara REAL,peso_liquido REAL,
            quantidade_bandejas REAL,status TEXT,origem TEXT,observacoes TEXT,
            local_estoque_id INTEGER,criado_em TEXT,estoque_operacional INTEGER,
            condicao TEXT,disponibilidade TEXT,reservado_expedicao_id INTEGER,
            quantidade_pacotes_reservados INTEGER DEFAULT 0
        );
        CREATE TABLE pa_caixa_composicao(
            id INTEGER PRIMARY KEY AUTOINCREMENT,caixa_id INTEGER,op_id INTEGER,
            quantidade_bandejas REAL,criado_em TEXT
        );
        CREATE TABLE estoque_produto_intermediario(
            id INTEGER PRIMARY KEY AUTOINCREMENT,data_movimentacao TEXT,tipo TEXT,op_id INTEGER,
            sku TEXT,quantidade_bandejas REAL,origem TEXT,observacoes TEXT,criado_em TEXT,
            caixa_id INTEGER,movimento_origem_id INTEGER,idempotency_key TEXT
        );
        CREATE TABLE estoque_eventos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,caixa_id INTEGER,expedicao_id INTEGER,
            acao TEXT,situacao_anterior TEXT,situacao_nova TEXT,condicao_anterior TEXT,
            condicao_nova TEXT,quantidade REAL,peso REAL,justificativa TEXT,observacao TEXT,
            usuario TEXT,perfil TEXT,criado_em TEXT,idempotency_key TEXT UNIQUE
        );
        CREATE TABLE expedicoes(id INTEGER PRIMARY KEY,numero_romaneio TEXT,status TEXT);
        CREATE TABLE expedicao_itens(id INTEGER PRIMARY KEY,expedicao_id INTEGER,caixa_id INTEGER);
        CREATE TABLE pa_movimentacoes(id INTEGER PRIMARY KEY,caixa_id INTEGER,tipo TEXT);
        CREATE TABLE pa_nao_conformes(id INTEGER PRIMARY KEY,caixa_id INTEGER,status TEXT);
        CREATE TABLE apontamentos_producao(
            id INTEGER PRIMARY KEY AUTOINCREMENT,op_id INTEGER,observacoes TEXT
        );
        INSERT INTO ordens_producao VALUES(7,'Aberta','Galinha Cortada','2026-08-21');
        INSERT INTO ordens_producao VALUES(8,'Aberta','Galinha Cortada','2026-08-21');
        INSERT INTO pa_caixas VALUES
          (1,'CX-001','Galinha Cortada','2026-08-21','2027-08-21',12.760,.5,12.260,12,'Em estoque','Embalagem Secundária','',1,'2026-08-21 08:00:00',0,'CONFORME','PENDENTE_OP',NULL,0),
          (2,'CX-002','Galinha Cortada','2026-08-21','2027-08-21',10.500,.5,10.000,10,'Em estoque','Embalagem Secundária','',1,'2026-08-21 08:01:00',0,'CONFORME','PENDENTE_OP',NULL,0),
          (3,'CX-003','Galinha Cortada','2026-08-21','2027-08-21',13.000,.5,12.500,12,'Em estoque','Embalagem Secundária','',1,'2026-08-21 08:02:00',0,'CONFORME','PENDENTE_OP',NULL,0);
        INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(1,7,12),(2,7,10),(3,7,12);
        INSERT INTO estoque_produto_intermediario(
          data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,caixa_id,idempotency_key)
        VALUES
          ('2026-08-21','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',12,'Embalagem Secundária','Bandejas consumidas na formação da caixa PA #1.',1,'SAIDA-1'),
          ('2026-08-21','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',10,'Embalagem Secundária','Bandejas consumidas na formação da caixa PA #2.',2,'SAIDA-2'),
          ('2026-08-21','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',12,'Embalagem Secundária','Bandejas consumidas na formação da caixa PA #3.',3,'SAIDA-3');
    """)
    conn.commit()
    conn.close()
    estornos.criar_tabelas_estornos_embalagem()
    return conectar


def _estornar(caixa_id, chave, **kwargs):
    dados = dict(usuario="Supervisora", perfil="pcp", justificativa="Peso informado incorretamente",
                 idempotency_key=chave, ip_origem="127.0.0.1")
    dados.update(kwargs)
    return estornos.estornar_caixa_embalagem_secundaria(7, caixa_id, **dados)


def test_diagnostico_reset_legado_apagava_historico_e_validava_fora_da_transacao():
    fonte = inspect.getsource(expedicao_services.resetar_processamento_op)
    validacao = inspect.getsource(expedicao_services.validar_reset_processamento_op)
    assert "reset destrutivo foi desativado" in fonte
    assert "apagava fisicamente" in fonte
    assert "conn = conectar()" in validacao and "conn.close()" in validacao


def test_estorno_individual_parcial_preserva_demais_caixas_e_reverte_pi_pa(banco):
    resultado = _estornar(2, "EST-IND-1")
    conn = banco()
    caixas = conn.execute("SELECT id,status,estoque_operacional FROM pa_caixas ORDER BY id").fetchall()
    reversao = conn.execute("SELECT * FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()
    auditoria = conn.execute("SELECT * FROM embalagem_secundaria_estornos WHERE tipo='CAIXA'").fetchone()
    assert [(c["id"], c["status"]) for c in caixas] == [(1, "Em estoque"), (2, "Estornada"), (3, "Em estoque")]
    assert caixas[1]["estoque_operacional"] == 0
    assert (reversao["caixa_id"], reversao["movimento_origem_id"], reversao["quantidade_bandejas"]) == (2, 2, 10)
    assert resultado["totais_antes"] == {"caixas": 3, "bandejas": "34.0", "peso_bruto": "36.26", "peso_liquido": "34.76"}
    assert resultado["totais_depois"] == {"caixas": 2, "bandejas": "24.0", "peso_bruto": "25.76", "peso_liquido": "24.76"}
    snapshot = json.loads(auditoria["snapshot_json"])
    assert snapshot["peso_bruto"] == "10.5" and snapshot["quantidade_bandejas"] == "10.0"
    conn.close()


def test_caixa_padrao_devolve_exatamente_doze_bandejas(banco):
    _estornar(1, "EST-PADRAO")
    conn = banco()
    linha = conn.execute("SELECT quantidade_bandejas FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()
    assert linha[0] == 12
    conn.close()


@pytest.mark.parametrize("quantidade", [1, 6, 11, 12])
def test_retorno_pi_exato_recompoe_saldo_anterior_ao_lancamento(banco, quantidade):
    conn = banco()
    conn.execute("DELETE FROM estoque_produto_intermediario")
    conn.execute("UPDATE pa_caixa_composicao SET quantidade_bandejas=? WHERE caixa_id=2", (quantidade,))
    conn.execute("UPDATE pa_caixas SET quantidade_bandejas=? WHERE id=2", (quantidade,))
    conn.execute("""INSERT INTO estoque_produto_intermediario(
        data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,idempotency_key)
        VALUES('2026-08-21','ENTRADA_EMBALAGEM_PRIMARIA',7,'Galinha Cortada',50,
        'Embalagem Primária','Saldo inicial controlado','PI-INICIAL')""")
    conn.execute("""INSERT INTO estoque_produto_intermediario(
        data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,caixa_id,idempotency_key)
        VALUES('2026-08-21','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',?,
        'Embalagem Secundária','Bandejas consumidas na formação da caixa PA #2.',2,'SAIDA-CONTROLADA')""", (quantidade,))
    saldo_apos_lancamento = conn.execute("""SELECT SUM(CASE WHEN tipo LIKE 'ENTRADA%' THEN quantidade_bandejas ELSE -quantidade_bandejas END)
        FROM estoque_produto_intermediario WHERE op_id=7""").fetchone()[0]
    conn.commit(); conn.close()

    _estornar(2, f"PI-EXATO-{quantidade}")
    conn = banco()
    saldo_final = conn.execute("""SELECT SUM(CASE WHEN tipo LIKE 'ENTRADA%' THEN quantidade_bandejas ELSE -quantidade_bandejas END)
        FROM estoque_produto_intermediario WHERE op_id=7""").fetchone()[0]
    devolvido = conn.execute("SELECT quantidade_bandejas FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()[0]
    assert saldo_apos_lancamento == 50 - quantidade
    assert saldo_final == 50
    assert devolvido == quantidade
    conn.close()


def test_pa_estornado_fica_fora_de_reserva_romaneio_e_estoque_ativo(banco):
    _estornar(2, "PA-INATIVO")
    conn = banco()
    caixa = conn.execute("SELECT * FROM pa_caixas WHERE id=2").fetchone()
    elegiveis = conn.execute("""SELECT id FROM pa_caixas WHERE status='Em estoque'
        AND estoque_operacional=1 AND disponibilidade='DISPONIVEL'
        AND reservado_expedicao_id IS NULL AND quantidade_pacotes_reservados=0""").fetchall()
    assert caixa["status"] == "Estornada"
    assert caixa["estoque_operacional"] == 0
    assert caixa["disponibilidade"] == "ESTORNADO"
    assert 2 not in {item["id"] for item in elegiveis}
    conn.close()


def test_op_encerrada_reabre_e_invalida_totais_automaticos_sem_apagar(banco):
    conn = banco()
    conn.execute("UPDATE ordens_producao SET status='Encerrada' WHERE id=7")
    conn.execute("INSERT INTO apontamentos_producao(op_id,observacoes) VALUES(7,'Produção final informada no encerramento da OP | teste')")
    conn.commit(); conn.close()
    resultado = _estornar(2, "EST-REABRE")
    conn = banco()
    assert resultado["status_op_posterior"] == "Aberta"
    assert conn.execute("SELECT status FROM ordens_producao WHERE id=7").fetchone()[0] == "Aberta"
    assert conn.execute("SELECT COUNT(*) FROM apontamentos_producao WHERE op_id=7").fetchone()[0] == 1
    assert conn.execute("SELECT vigente FROM apontamentos_producao WHERE op_id=7").fetchone()[0] == 0
    conn.close()


def test_idempotencia_mesma_chave_nao_duplica_reversao(banco):
    primeiro = _estornar(2, "EST-IDEM")
    segundo = _estornar(2, "EST-IDEM")
    assert segundo == primeiro
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM embalagem_secundaria_estornos WHERE idempotency_key='EST-IDEM'").fetchone()[0] == 1
    conn.close()


def test_nova_chave_nao_estorna_caixa_duas_vezes(banco):
    _estornar(2, "EST-UMA")
    with pytest.raises(ValueError, match="já foi estornada"):
        _estornar(2, "EST-DUAS")


@pytest.mark.parametrize("preparar,mensagem", [
    (lambda c: c.executescript("INSERT INTO expedicoes VALUES(1,'ROM-154','Aberto'); INSERT INTO expedicao_itens VALUES(1,1,2);"), "Romaneio nº ROM-154"),
    (lambda c: c.execute("INSERT INTO pa_movimentacoes VALUES(1,2,'TRANSFERENCIA')"), "movimentação posterior"),
    (lambda c: c.execute("INSERT INTO pa_nao_conformes VALUES(1,2,'BLOQUEADO')"), "Produto Não Conforme"),
    (lambda c: c.execute("INSERT INTO estoque_eventos(caixa_id,acao,idempotency_key) VALUES(2,'AJUSTE','AJ-1')"), "evento sucessor"),
])
def test_vinculos_posteriores_bloqueiam_sem_alterar_dados(banco, preparar, mensagem):
    conn = banco(); preparar(conn); conn.commit(); conn.close()
    with pytest.raises(ValueError, match=mensagem):
        _estornar(2, "EST-BLOQ")
    conn = banco()
    assert conn.execute("SELECT status FROM pa_caixas WHERE id=2").fetchone()[0] == "Em estoque"
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()[0] == 0
    conn.close()


def test_caixa_de_outra_op_e_caixa_inexistente_sao_rejeitadas(banco):
    with pytest.raises(ValueError, match="não pertence"):
        estornos.estornar_caixa_embalagem_secundaria(
            8, 2, usuario="Supervisora", perfil="pcp", justificativa="Correção necessária",
            idempotency_key="ERR-OP")
    with pytest.raises(ValueError, match="Caixa não encontrada"):
        _estornar(999, "ERR-CX")


@pytest.mark.parametrize("alteracao,erro", [
    ({"perfil": "producao"}, PermissionError),
    ({"justificativa": "   "}, ValueError),
])
def test_permissao_e_justificativa_sao_validadas_no_dominio(banco, alteracao, erro):
    with pytest.raises(erro):
        _estornar(2, "EST-NEGADO", **alteracao)


def test_feature_flag_desativada_bloqueia_backend(banco, monkeypatch):
    monkeypatch.setenv("SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED", "false")
    with pytest.raises(PermissionError, match="desativado"):
        _estornar(2, "EST-FLAG")


def test_falha_na_auditoria_de_estoque_causa_rollback_integral(banco, monkeypatch):
    def falhar(*args, **kwargs):
        raise RuntimeError("falha simulada de auditoria")
    monkeypatch.setattr(estornos, "_inserir_evento_estoque", falhar)
    with pytest.raises(RuntimeError, match="falha simulada"):
        _estornar(2, "EST-ROLLBACK")
    conn = banco()
    assert conn.execute("SELECT status FROM pa_caixas WHERE id=2").fetchone()[0] == "Em estoque"
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM embalagem_secundaria_estornos").fetchone()[0] == 0
    conn.close()


def test_estorno_integral_reutiliza_nucleo_e_preserva_historico(banco):
    resultado = estornos.estornar_op_embalagem_secundaria(
        7, usuario="Gerente", perfil="admin", justificativa="Lançamento integral inválido",
        idempotency_key="EST-OP-1")
    conn = banco()
    assert resultado["caixas_estornadas"] == 3
    assert conn.execute("SELECT status FROM ordens_producao WHERE id=7").fetchone()[0] == "Estornada"
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE status='Estornada'").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM embalagem_secundaria_estornos WHERE tipo='OP'").fetchone()[0] == 1
    conn.close()


def test_estorno_integral_com_uma_caixa_bloqueada_nao_deixa_efeito_parcial(banco):
    conn = banco()
    conn.executescript("INSERT INTO expedicoes VALUES(1,'ROM-999','Aberto'); INSERT INTO expedicao_itens VALUES(1,1,3);")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="CX-003"):
        estornos.estornar_op_embalagem_secundaria(
            7, usuario="Gerente", perfil="admin", justificativa="Tentativa integral controlada",
            idempotency_key="EST-OP-BLOQ")
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE status='Estornada'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()[0] == 0
    assert conn.execute("SELECT status FROM ordens_producao WHERE id=7").fetchone()[0] == "Aberta"
    conn.close()


def test_rotas_exigem_csrf_e_template_respeita_feature_flag():
    rotas = open("modules/expedicao/routes.py", encoding="utf-8").read()
    template = open("templates/embalagem_secundaria.html", encoding="utf-8").read()
    assert "secrets.compare_digest" in rotas
    assert "funcionalidade_estorno_habilitada" in rotas
    assert "estorno_habilitado and pode_estornar_caixa" in template
    assert "Confirmar estorno desta caixa" in template


def test_migration_sqlite_upgrade_e_downgrade_sao_reversiveis(tmp_path):
    conn = sqlite3.connect(tmp_path / "migration.db")
    conn.executescript("""
        CREATE TABLE pa_caixas(id INTEGER PRIMARY KEY);
        CREATE TABLE estoque_produto_intermediario(id INTEGER PRIMARY KEY,tipo TEXT);
        CREATE TABLE estoque_eventos(id INTEGER PRIMARY KEY);
    """)
    upgrade = open("database/20260821_estorno_caixa_embalagem_secundaria_sqlite.sql", encoding="utf-8").read()
    downgrade = open("database/20260821_estorno_caixa_embalagem_secundaria_sqlite_rollback.sql", encoding="utf-8").read()
    conn.executescript(upgrade)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='embalagem_secundaria_estornos'").fetchone()
    assert "estornada_em" in {item[1] for item in conn.execute("PRAGMA table_info(pa_caixas)")}
    conn.executescript(downgrade)
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name='embalagem_secundaria_estornos'").fetchone()
    assert "estornada_em" not in {item[1] for item in conn.execute("PRAGMA table_info(pa_caixas)")}
    conn.close()


def test_estorno_lote_atomico_preserva_caixas_nao_selecionadas(banco):
    resultado = estornos.estornar_caixas_embalagem_secundaria_em_lote(
        7, [1, 2], usuario="Supervisora", perfil="pcp",
        justificativa="Lançamentos em duplicidade", idempotency_key="LOTE-1")
    conn = banco()
    assert resultado["caixas_estornadas"] == 2
    assert resultado["impacto"] == {"bandejas": "22.0", "peso_bruto": "23.26", "peso_liquido": "22.26"}
    assert [(r["id"], r["status"]) for r in conn.execute("SELECT id,status FROM pa_caixas ORDER BY id")] == [
        (1, "Estornada"), (2, "Estornada"), (3, "Em estoque")]
    assert conn.execute("SELECT COUNT(*) FROM embalagem_secundaria_estornos WHERE tipo='LOTE'").fetchone()[0] == 1
    conn.close()


def test_estorno_lote_idempotente_nao_repete_movimentos(banco):
    argumentos = dict(usuario="Supervisora", perfil="pcp", justificativa="Duplicidade confirmada", idempotency_key="LOTE-IDEM")
    primeiro = estornos.estornar_caixas_embalagem_secundaria_em_lote(7, [1, 2], **argumentos)
    segundo = estornos.estornar_caixas_embalagem_secundaria_em_lote(7, [2, 1], **argumentos)
    assert segundo == primeiro
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()[0] == 2
    conn.close()


@pytest.mark.parametrize("ids,mensagem", [([], "ao menos uma"), ([1, 1], "mais de uma vez"), ([1, 999], "Caixa não encontrada")])
def test_estorno_lote_rejeita_payload_invalido_sem_efeito(banco, ids, mensagem):
    with pytest.raises(ValueError, match=mensagem):
        estornos.estornar_caixas_embalagem_secundaria_em_lote(
            7, ids, usuario="Supervisora", perfil="pcp", justificativa="Correção operacional",
            idempotency_key="LOTE-INVALIDO")
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE status='Estornada'").fetchone()[0] == 0
    conn.close()


def test_estorno_lote_faz_rollback_quando_uma_caixa_esta_bloqueada(banco):
    conn = banco()
    conn.executescript("INSERT INTO expedicoes VALUES(1,'ROM-X','Aberto'); INSERT INTO expedicao_itens VALUES(1,1,2);")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="CX-002"):
        estornos.estornar_caixas_embalagem_secundaria_em_lote(
            7, [1, 2], usuario="Supervisora", perfil="pcp", justificativa="Correção operacional",
            idempotency_key="LOTE-BLOQ")
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE status='Estornada'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_ESTORNO_CAIXA'").fetchone()[0] == 0
    conn.close()


@pytest.fixture()
def conferencia_banco(banco, monkeypatch):
    monkeypatch.setattr(conferencia, "conectar", banco)
    monkeypatch.setattr(conferencia, "transaction", estornos.transaction)
    monkeypatch.setattr(conferencia, "DATABASE_URL", None)
    conferencia.criar_tabelas_conferencia_embalagem()
    return banco


def test_conferencia_lista_estornadas_fora_dos_totais_e_filtra(conferencia_banco):
    conn = conferencia_banco()
    conn.execute("UPDATE pa_caixas SET status='Estornada' WHERE id=3")
    conn.commit(); conn.close()
    painel = conferencia.obter_conferencia_op(7, {"situacao": "ativas", "busca": "CX-002"})
    assert painel["totais"]["caixas_ativas"] == 2
    assert painel["totais"]["caixas_estornadas"] == 1
    assert [c["codigo_caixa"] for c in painel["caixas_exibidas"]] == ["CX-002"]
    assert [c["codigo_caixa"] for c in painel["caixas"]] == ["CX-003", "CX-002", "CX-001"]


def test_conferencia_filtra_campos_operacionais_ordena_e_totaliza_tara(conferencia_banco):
    conn = conferencia_banco()
    conn.execute("UPDATE pa_caixas SET usuario_pesagem='Maria' WHERE id=2")
    conn.commit(); conn.close()
    painel = conferencia.obter_conferencia_op(7, {
        "situacao": "todas", "usuario": "mari", "peso_bruto": "10,500",
        "bandejas": "10", "horario_inicial": "08:00", "horario_final": "08:01",
        "ordem": "asc",
    })
    assert [c["codigo_caixa"] for c in painel["caixas_exibidas"]] == ["CX-002"]
    assert painel["totais"]["peso_tara"] == pytest.approx(1.5)
    assert painel["ordem"] == "asc"


def test_alerta_duplicidade_nao_estorna_nem_seleciona(conferencia_banco):
    conn = conferencia_banco()
    conn.execute("""UPDATE pa_caixas SET peso_bruto=12.760,peso_liquido=12.260,
        quantidade_bandejas=12,data_fabricacao='2026-08-21',data_validade='2027-08-21',
        criado_em='2026-08-21 08:01:00' WHERE id=2""")
    conn.commit(); conn.close()
    painel = conferencia.obter_conferencia_op(7, {"situacao": "todas", "duplicadas": "1"})
    assert painel["duplicidades"] == [1, 2]
    assert all(c["status"] == "Em estoque" for c in painel["caixas"])
    assert all(c["selecionavel"] for c in painel["caixas_exibidas"])


def test_conferencia_persistida_e_invalidada_por_alteracao(conferencia_banco):
    painel = conferencia.obter_conferencia_op(7)
    registro = conferencia.confirmar_conferencia_op(
        7, usuario="Operadora", perfil="producao", hash_informado=painel["hash"])
    assert registro["caixas_ativas"] == 3
    assert conferencia.obter_conferencia_op(7)["confirmacao_valida"] is True
    conn = conferencia_banco()
    conn.execute("UPDATE pa_caixas SET peso_bruto=peso_bruto+0.001 WHERE id=1")
    conn.commit(); conn.close()
    assert conferencia.obter_conferencia_op(7)["confirmacao_valida"] is False


def test_snapshot_persiste_tara_saldo_e_pdf_analitico_multipagina(conferencia_banco):
    painel = conferencia.obter_conferencia_op(7, {"situacao": "todas"})
    conferencia.confirmar_conferencia_op(
        7, usuario="Operadora", perfil="producao", hash_informado=painel["hash"])
    confirmado = conferencia.obter_conferencia_op(7, {"situacao": "todas"})
    conn = conferencia_banco()
    snapshot = conn.execute("SELECT * FROM embalagem_secundaria_conferencias ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert float(snapshot["peso_tara"]) == pytest.approx(1.5)
    assert "saldo_pendente" in snapshot.keys()

    caixas_base = confirmado["caixas"]
    confirmado["caixas"] = []
    for indice in range(90):
        item = dict(caixas_base[indice % len(caixas_base)])
        item["id"] = 1000 + indice
        item["codigo_caixa"] = f"CX-PDF-{indice:03d}"
        confirmado["caixas"].append(item)
    pdf = gerar_relatorio_conferencia_embalagem_pdf(
        {"id": 7, "data": "2026-08-21", "sku": "Galinha Cortada", "lote": "L-7"},
        confirmado, "Operadora",
    )
    leitor = PdfReader(BytesIO(pdf))
    texto = "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)
    assert len(leitor.pages) >= 2
    assert float(leitor.pages[0].mediabox.width) > float(leitor.pages[0].mediabox.height)
    assert "Resumo para fechamento da OP" in texto
    assert "CX-PDF-089" in texto


def test_template_expoe_selecao_resumo_filtros_e_portao_de_encerramento():
    template = open("templates/embalagem_secundaria.html", encoding="utf-8").read()
    rotas = open("modules/expedicao/routes.py", encoding="utf-8").read()
    assert "Conferência de Caixas da OP" in template
    assert 'name="caixa_ids[]"' in template and "data-resumo-selecao" in template
    assert "Somente possíveis duplicidades" in template and "Conferi os lançamentos" in template
    assert "caixas/estornar-lote" in rotas and "exigir_conferencia=True" in rotas
    assert 'name="confirmacao" value="1" required' in template
    assert 'request.form.get("confirmacao") != "1"' in rotas
    assert 'type="button" class="botao-principal" data-confirmar-caixa' in template
    assert 'evento.key !== "Enter"' in template and "evento.preventDefault()" in template
    assert "Peso bruto exato" in template and "Horário inicial" in template and "Gerar relatório" in template


def test_migration_p0_snapshot_sqlite_e_reversivel(tmp_path):
    conn = sqlite3.connect(tmp_path / "p0-snapshot.db")
    conn.execute("CREATE TABLE embalagem_secundaria_conferencias(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE embalagem_secundaria_requisicoes(id INTEGER PRIMARY KEY)")
    raiz = "database/20260825_p0_conferencia_embalagem_secundaria"
    conn.executescript(open(raiz + "_sqlite.sql", encoding="utf-8").read())
    colunas = {item[1] for item in conn.execute("PRAGMA table_info(embalagem_secundaria_conferencias)")}
    assert {"peso_tara", "saldo_pendente"} <= colunas
    colunas_req = {item[1] for item in conn.execute("PRAGMA table_info(embalagem_secundaria_requisicoes)")}
    assert {"repeticoes", "ultimo_reenvio_em"} <= colunas_req
    conn.executescript(open(raiz + "_sqlite_rollback.sql", encoding="utf-8").read())
    colunas = {item[1] for item in conn.execute("PRAGMA table_info(embalagem_secundaria_conferencias)")}
    assert "peso_tara" not in colunas and "saldo_pendente" not in colunas
    colunas_req = {item[1] for item in conn.execute("PRAGMA table_info(embalagem_secundaria_requisicoes)")}
    assert "repeticoes" not in colunas_req and "ultimo_reenvio_em" not in colunas_req
    conn.close()


def test_homologacao_cinco_caixas_estorna_duas_preserva_tres_e_invalida_ao_continuar(conferencia_banco):
    conn = conferencia_banco()
    conn.executescript("""
        INSERT INTO pa_caixas VALUES
          (4,'CX-DUP-1','Galinha Cortada','2026-08-21','2027-08-21',12.760,.5,12.260,12,'Em estoque','Embalagem Secundária','',1,'2026-08-21 08:10:00',0,'CONFORME','PENDENTE_OP',NULL,0,NULL,NULL,NULL,NULL,0,NULL),
          (5,'CX-DUP-2','Galinha Cortada','2026-08-21','2027-08-21',12.760,.5,12.260,12,'Em estoque','Embalagem Secundária','',1,'2026-08-21 08:11:00',0,'CONFORME','PENDENTE_OP',NULL,0,NULL,NULL,NULL,NULL,0,NULL);
        INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(4,7,12),(5,7,12);
        INSERT INTO estoque_produto_intermediario(data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,caixa_id,idempotency_key)
        VALUES('2026-08-21','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',12,'Embalagem Secundária','Bandejas consumidas na formação da caixa PA #4.',4,'SAIDA-4'),
              ('2026-08-21','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',12,'Embalagem Secundária','Bandejas consumidas na formação da caixa PA #5.',5,'SAIDA-5');
    """)
    conn.commit(); conn.close()
    resultado = estornos.estornar_caixas_embalagem_secundaria_em_lote(
        7, [4, 5], usuario="Supervisora", perfil="pcp",
        justificativa="Lançamentos em duplicidade", idempotency_key="HOMOLOG-5-2")
    assert resultado["totais_antes"] == {"caixas": 5, "bandejas": "58.0", "peso_bruto": "61.78", "peso_liquido": "59.28"}
    assert resultado["totais_depois"] == {"caixas": 3, "bandejas": "34.0", "peso_bruto": "36.26", "peso_liquido": "34.76"}
    painel = conferencia.obter_conferencia_op(7)
    conferencia.confirmar_conferencia_op(7, usuario="Supervisora", perfil="pcp", hash_informado=painel["hash"])
    assert conferencia.obter_conferencia_op(7)["confirmacao_valida"] is True
    conn = conferencia_banco()
    conn.execute("""INSERT INTO pa_caixas(
        id,codigo_caixa,sku,data_fabricacao,data_validade,peso_bruto,peso_tara,peso_liquido,
        quantidade_bandejas,status,origem,criado_em,estoque_operacional,condicao,disponibilidade)
        VALUES(6,'CX-NOVA','Galinha Cortada','2026-08-21','2027-08-21',11.5,.5,11,12,
        'Em estoque','Embalagem Secundária','2026-08-21 08:20:00',0,'CONFORME','PENDENTE_OP')""")
    conn.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(6,7,12)")
    conn.commit(); conn.close()
    painel_final = conferencia.obter_conferencia_op(7)
    assert painel_final["totais"]["caixas_ativas"] == 4
    assert painel_final["confirmacao_valida"] is False
