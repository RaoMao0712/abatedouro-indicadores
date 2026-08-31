from contextlib import contextmanager
import sqlite3

import pytest

from modules.qualidade import produtos_nao_conformes as nc
from modules.expedicao import estoque_service as estoque
from modules.expedicao import services as expedicao_services
from modules.expedicao import encerramento_op as encerramento
from modules.producao import operacoes_op


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "pa-nc.db"

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

    monkeypatch.setattr(nc, "conectar", conectar)
    monkeypatch.setattr(nc, "transaction", transacao)
    monkeypatch.setattr(nc, "DATABASE_URL", None)
    monkeypatch.setattr(estoque, "transaction", transacao)
    monkeypatch.setattr(estoque, "criar_tabelas_estoque_confiavel", lambda: None)
    conn = conectar()
    conn.executescript("""
        CREATE TABLE locais_estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL,
            tipo TEXT NOT NULL, ativo TEXT NOT NULL
        );
        CREATE TABLE ordens_producao (id INTEGER PRIMARY KEY, status TEXT, sku TEXT, data TEXT);
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
        CREATE TABLE expedicoes (id INTEGER PRIMARY KEY, status TEXT, tipo_movimentacao TEXT);
        CREATE TABLE expedicao_itens (id INTEGER PRIMARY KEY, expedicao_id INTEGER, caixa_id INTEGER);
        INSERT INTO expedicoes VALUES (1, 'Aberto', 'TRANSFERENCIA');
        INSERT INTO ordens_producao VALUES (7, 'Aberta', 'Galinha Cortada', '2026-07-31');
        INSERT INTO locais_estoque(nome,tipo,ativo) VALUES ('Câmara Fria — Área Bloqueada','segregacao','Sim');
        INSERT INTO pa_caixas VALUES
            (1,'OP00007-CX001','Galinha Cortada',10.5,12,'Em estoque','CONFORME','PENDENTE_OP','Conforme',NULL,1,0,'CAIXA',NULL,NULL,0),
            (2,'OP00007-CX002','Galinha Cortada',9.5,10,'Em estoque','CONFORME','PENDENTE_OP','Conforme',NULL,1,0,'CAIXA',NULL,NULL,0);
        INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES (1,7,12),(2,7,10);
    """)
    conn.commit()
    conn.close()
    nc.criar_tabelas_pa_nao_conforme()
    return conectar, transacao


def _item(caixa_id=1, **alteracoes):
    base = {
        "caixa_id": caixa_id,
        "lote": f"OP00007-CX00{caixa_id}",
        "apresentacao": "Caixa de Galinha Cortada",
        "quantidade": 12 if caixa_id == 1 else 10,
        "peso": 10.5 if caixa_id == 1 else 9.5,
        "unidade": "BANDEJA",
        "motivo": "Falha de selagem",
        "descricao": "Selagem lateral incompleta",
        "local_estoque_id": 1,
        "observacoes": "Segregado fisicamente",
    }
    base.update(alteracoes)
    return base


def _registrar(banco, itens):
    _, transacao = banco
    with transacao() as conn:
        return nc.registrar_itens_encerramento(
            conn.cursor(), 7, itens, usuario="Operadora", perfil="producao", origem="teste"
        )


def _preparar_finalizador(monkeypatch, banco):
    conectar, transacao = banco
    monkeypatch.setattr(expedicao_services, "transaction", transacao)
    monkeypatch.setattr(encerramento, "transaction", transacao)
    monkeypatch.setattr(expedicao_services, "garantir_schema_producao", lambda: None)
    monkeypatch.setattr(expedicao_services, "criar_tabelas_estoque_pi_pa", lambda: None)
    monkeypatch.setattr(expedicao_services, "gerar_producao_automatica_setores", lambda **kwargs: None)
    monkeypatch.setattr(encerramento, "gerar_producao_automatica_setores", lambda **kwargs: None)
    # O teste isola o encerramento; a migration de reabertura P0.2 possui sua
    # própria suíte e depende de tabelas que não fazem parte deste fixture.
    monkeypatch.setattr(operacoes_op, "criar_tabelas_operacoes_op", lambda: None)

    def fechamento(op_id, conn=None):
        op = conn.execute("SELECT * FROM ordens_producao WHERE id=?", (op_id,)).fetchone()
        return {"pode_encerrar": True, "pendencias": [], "op": op,
                "bandejas_consumidas": 22, "peso_liquido_total": 20,
                "peso_bruto_total": 20, "aves_vivas": 22,
                "mortes_antes_pendura": 0, "bandejas_primaria": 22,
                "descartes": 0, "condenacoes": 0}

    def ativar(cursor, op_id):
        cursor.execute("""
            UPDATE pa_caixas SET estoque_operacional=1,
                disponibilidade=CASE WHEN condicao='NAO_CONFORME' THEN 'BLOQUEADO' ELSE 'DISPONIVEL' END
            WHERE id IN (SELECT caixa_id FROM pa_caixa_composicao WHERE op_id=?)
        """, (op_id,))

    monkeypatch.setattr(expedicao_services, "calcular_fechamento_industrial_op", fechamento)
    monkeypatch.setattr(
        encerramento, "_calcular_fechamento_cursor",
        lambda cursor, op: fechamento(op["id"], conn=cursor.connection),
    )
    monkeypatch.setattr(estoque, "ativar_estoque_op_encerrada", ativar)
    return conectar


def test_encerramento_sem_nao_conforme_nao_cria_registro(banco):
    assert _registrar(banco, []) == []
    conn = banco[0]()
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conformes").fetchone()[0] == 0
    conn.close()


def test_um_item_nasce_bloqueado_rastreavel_e_sem_duplicar_peso(banco):
    conn = banco[0]()
    peso_antes = conn.execute("SELECT SUM(peso_liquido) FROM pa_caixas").fetchone()[0]
    conn.close()
    ids = _registrar(banco, [_item()])
    conn = banco[0]()
    registro = conn.execute("SELECT * FROM pa_nao_conformes WHERE id=?", ids).fetchone()
    caixa = conn.execute("SELECT * FROM pa_caixas WHERE id=1").fetchone()
    peso_depois = conn.execute("SELECT SUM(peso_liquido) FROM pa_caixas").fetchone()[0]
    evento = conn.execute("SELECT * FROM pa_nao_conforme_eventos WHERE pa_nao_conforme_id=?", ids).fetchone()
    conn.close()
    assert registro["status"] == "BLOQUEADO"
    assert (registro["op_id"], registro["lote"], registro["caixa_id"]) == (7, "OP00007-CX001", 1)
    assert (caixa["condicao"], caixa["disponibilidade"]) == ("NAO_CONFORME", "BLOQUEADO")
    assert peso_depois == peso_antes == 20
    assert evento["acao"] == "CRIACAO_E_BLOQUEIO"


def test_varios_itens_sao_segregados_na_mesma_transacao(banco):
    ids = _registrar(banco, [_item(1), _item(2, quantidade=10, peso=9.5)])
    conn = banco[0]()
    assert len(ids) == 2
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conformes WHERE status='BLOQUEADO'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE condicao='NAO_CONFORME' AND disponibilidade='BLOQUEADO'").fetchone()[0] == 2
    conn.close()


@pytest.mark.parametrize("campo,valor,mensagem", [
    ("motivo", "", "motivo"), ("quantidade", 0, "Quantidade"),
    ("peso", -1, "Quantidade"), ("lote", "", "lote"),
    ("local_estoque_id", "", "local"),
])
def test_campos_obrigatorios_e_valores_invalidos_impedem_registro(banco, campo, valor, mensagem):
    with pytest.raises(ValueError, match=mensagem):
        _registrar(banco, [_item(**{campo: valor})])
    conn = banco[0]()
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conformes").fetchone()[0] == 0
    assert conn.execute("SELECT condicao FROM pa_caixas WHERE id=1").fetchone()[0] == "CONFORME"
    conn.close()


def test_outro_exige_descricao_e_lote_local_devem_existir(banco):
    with pytest.raises(ValueError, match="Descreva"):
        _registrar(banco, [_item(motivo="Outro", descricao="")])
    with pytest.raises(ValueError, match="inexistente"):
        _registrar(banco, [_item(local_estoque_id=999)])


@pytest.mark.parametrize("alteracao,mensagem", [
    ({"lote": "LOTE-FALSO"}, "lote informado"),
    ({"quantidade": 99}, "Quantidade ou unidade"),
    ({"peso": 99}, "peso informado"),
    ({"unidade": "KG"}, "Quantidade ou unidade"),
])
def test_backend_rejeita_adulteracao_dos_dados_fisicos(alteracao, mensagem, banco):
    with pytest.raises(ValueError, match=mensagem):
        _registrar(banco, [_item(**alteracao)])


def test_falha_no_segundo_item_faz_rollback_integral(banco):
    _, transacao = banco
    with pytest.raises(ValueError):
        with transacao() as conn:
            nc.registrar_itens_encerramento(
                conn.cursor(), 7, [_item(1), _item(2, motivo="")],
                usuario="Operadora", perfil="producao", origem="teste",
            )
    conn = banco[0]()
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conformes").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE condicao='NAO_CONFORME'").fetchone()[0] == 0
    conn.close()


def test_encerramento_op_registro_e_bloqueio_ocorrem_na_mesma_transacao(monkeypatch, banco):
    conectar = _preparar_finalizador(monkeypatch, banco)
    expedicao_services.finalizar_embalagem_secundaria_op(7, nao_conformes=[_item()])
    conn = conectar()
    assert conn.execute("SELECT status FROM ordens_producao WHERE id=7").fetchone()[0] == "Encerrada"
    assert conn.execute("SELECT status FROM pa_nao_conformes WHERE caixa_id=1").fetchone()[0] == "BLOQUEADO"
    assert conn.execute("SELECT condicao,disponibilidade,estoque_operacional FROM pa_caixas WHERE id=1").fetchone()[:] == ("NAO_CONFORME", "BLOQUEADO", 1)
    conn.close()


def test_falha_durante_pa_nc_desfaz_tambem_o_encerramento_da_op(monkeypatch, banco):
    conectar = _preparar_finalizador(monkeypatch, banco)

    def falhar(etapa):
        if etapa == "pa_nc_1":
            raise RuntimeError("falha simulada")

    with pytest.raises(RuntimeError, match="falha simulada"):
        expedicao_services.finalizar_embalagem_secundaria_op(
            7, checkpoint=falhar, nao_conformes=[_item()]
        )
    conn = conectar()
    assert conn.execute("SELECT status FROM ordens_producao WHERE id=7").fetchone()[0] == "Aberta"
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conformes").fetchone()[0] == 0
    assert conn.execute("SELECT condicao,disponibilidade,estoque_operacional FROM pa_caixas WHERE id=1").fetchone()[:] == ("CONFORME", "PENDENTE_OP", 0)
    conn.close()


def test_bloqueado_fica_fora_dos_seletores_de_transferencia_venda_e_expedicao(banco):
    _registrar(banco, [_item()])
    conn = banco[0]()
    elegiveis = conn.execute("""
        SELECT id FROM pa_caixas
        WHERE estoque_operacional=1 AND condicao='CONFORME' AND disponibilidade='DISPONIVEL'
    """).fetchall()
    fisico = conn.execute("SELECT id FROM pa_caixas WHERE id=1").fetchone()
    conn.close()
    assert elegiveis == []
    assert fisico[0] == 1


def test_tentativa_direta_pelos_fluxos_legados_tambem_e_rejeitada(banco):
    _registrar(banco, [_item()])
    conn = banco[0]()
    conn.execute("UPDATE pa_caixas SET estoque_operacional=1 WHERE id=1")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="fluxo oficial"):
        estoque.destinar_produto(1, "LIBERAR", "Tentativa paralela")
    with pytest.raises(ValueError, match="fluxo oficial"):
        estoque.bloquear_produto(1, "Troca silenciosa")
    with pytest.raises(ValueError, match="aguarda destinação"):
        estoque.reservar_itens(1, [1])


@pytest.mark.parametrize("destino,status,disponibilidade", [
    ("RETRABALHO", "RETRABALHO", "BLOQUEADO"),
    ("REPROCESSO", "REPROCESSO", "REPROCESSAMENTO"),
    ("DESCARTE", "DESCARTE", "DESCARTADO"),
    ("MANTER_BLOQUEADO", "MANTIDO_BLOQUEADO", "BLOQUEADO"),
])
def test_qualidade_destina_sem_apagar_ou_duplicar_estoque(banco, destino, status, disponibilidade):
    registro_id = _registrar(banco, [_item()])[0]
    nc.decidir(registro_id, destino, "Decisão técnica documentada", usuario="Analista",
               perfil="qualidade", origem="teste")
    conn = banco[0]()
    registro = conn.execute("SELECT * FROM pa_nao_conformes WHERE id=?", (registro_id,)).fetchone()
    caixa = conn.execute("SELECT * FROM pa_caixas WHERE id=1").fetchone()
    eventos = conn.execute("SELECT COUNT(*) FROM pa_nao_conforme_eventos WHERE pa_nao_conforme_id=?", (registro_id,)).fetchone()[0]
    total_caixas = conn.execute("SELECT COUNT(*) FROM pa_caixas").fetchone()[0]
    conn.close()
    assert (registro["status"], caixa["disponibilidade"]) == (status, disponibilidade)
    assert (registro["op_id"], registro["lote"], registro["caixa_id"]) == (7, "OP00007-CX001", 1)
    assert eventos == 2 and total_caixas == 2


def test_justificativa_obrigatoria_e_producao_pcp_nao_decidem_com_tentativa_auditada(banco):
    registro_id = _registrar(banco, [_item()])[0]
    with pytest.raises(ValueError, match="obrigatória"):
        nc.decidir(registro_id, "RETRABALHO", "", usuario="Analista", perfil="qualidade", origem="teste")
    for perfil in ("producao", "pcp"):
        with pytest.raises(PermissionError):
            nc.decidir(registro_id, "RETRABALHO", "Tentativa", usuario=perfil, perfil=perfil, origem="teste")
    conn = banco[0]()
    assert conn.execute("SELECT status FROM pa_nao_conformes WHERE id=?", (registro_id,)).fetchone()[0] == "BLOQUEADO"
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conforme_eventos WHERE acao='TENTATIVA_NEGADA'").fetchone()[0] == 2
    conn.close()


@pytest.mark.parametrize("perfil", ["qualidade", "gerencia", "admin"])
def test_perfis_autorizados_iniciam_avaliacao(perfil, banco):
    registro_id = _registrar(banco, [_item()])[0]
    nc.iniciar_avaliacao(registro_id, usuario=perfil, perfil=perfil, origem="teste")
    conn = banco[0]()
    assert conn.execute("SELECT status FROM pa_nao_conformes WHERE id=?", (registro_id,)).fetchone()[0] == "EM_AVALIACAO"
    conn.close()


def test_liberacao_direta_e_rejeitada_e_preserva_bloqueio(banco):
    registro_id = _registrar(banco, [_item()])[0]
    with pytest.raises(ValueError, match="solicitacao"):
        nc.decidir(registro_id, "LIBERAR", "Conforme", usuario="Gerente",
                   perfil="gerencia", origem="teste")
    conn = banco[0]()
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE id=1 AND condicao='NAO_CONFORME' AND disponibilidade='BLOQUEADO'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM pa_nao_conformes WHERE caixa_id=1").fetchone()[0] == 1
    conn.close()
