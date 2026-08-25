from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from modules.qualidade import produtos_nao_conformes as nc
from modules.qualidade import reprocessamento as reprocesso
from modules.qualidade import liberacoes


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "reprocessamento.db"

    def conectar():
        conn = sqlite3.connect(caminho, timeout=10)
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

    monkeypatch.setattr(nc, "conectar", conectar)
    monkeypatch.setattr(nc, "transaction", transacao)
    monkeypatch.setattr(nc, "DATABASE_URL", None)
    monkeypatch.setattr(liberacoes, "conectar", conectar)
    monkeypatch.setattr(liberacoes, "transaction", transacao)
    monkeypatch.setattr(liberacoes, "DATABASE_URL", None)
    conn = conectar()
    conn.executescript("""
        CREATE TABLE locais_estoque(id INTEGER PRIMARY KEY,nome TEXT,tipo TEXT,ativo TEXT);
        INSERT INTO locais_estoque VALUES(4,'Câmara NC','segregacao','Sim');
        CREATE TABLE pa_caixas(id INTEGER PRIMARY KEY,codigo_caixa TEXT,condicao TEXT,
            disponibilidade TEXT,zona_estoque TEXT,motivo_nao_conformidade TEXT,
            local_estoque_id INTEGER,quantidade_pacotes INTEGER,quantidade_galinhas INTEGER);
    """)
    conn.commit()
    conn.close()
    nc.criar_tabelas_pa_nao_conforme()
    reprocesso.garantir_schema()
    return conectar


def criar_legado(banco, *, numero="PNC-REPROC-1", peso=1250000, caixas=100, bandejas=1200):
    agora = "2026-08-25 08:00:00"
    conn = banco()
    cursor = conn.execute("""INSERT INTO pa_nao_conformes(numero,produto,apresentacao,quantidade,peso,
        unidade,motivo,status,local_estoque_id,registrado_por,perfil_registro,registrado_em,
        criado_em,atualizado_em,tipo_registro,condicao_inicial,caixas_iniciais,bandejas_iniciais,
        caixas_bloqueadas,bandejas_bloqueadas,saldo_inicial_g,saldo_bloqueado_g)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero, "Galinha Cortada", "Congelada", bandejas, peso / 1000, "BANDEJA",
         "Carne Escura", "BLOQUEADO", 4, "Inventário", "admin", agora, agora, agora,
         nc.TIPO_LEGADO, "NAO_CONFORME", caixas, bandejas, caixas, bandejas, peso, peso))
    conn.commit()
    registro_id = cursor.lastrowid
    conn.close()
    return registro_id


def linha(banco, sql, params=()):
    conn = banco()
    resultado = conn.execute(sql, params).fetchone()
    conn.close()
    return resultado


def test_reprocessamento_integral_idempotente_e_finaliza_sem_saldo(banco):
    registro_id = criar_legado(banco)
    dados = {"modalidade": "INTEGRAL", "justificativa": "Tratamento térmico controlado",
             "idempotency_key": "REPROC-INTEGRAL-1"}
    primeiro = reprocesso.iniciar_reprocessamento(
        registro_id, dados, usuario="Qualidade", perfil="qualidade", origem="teste"
    )
    repetido = reprocesso.iniciar_reprocessamento(
        registro_id, dados, usuario="Qualidade", perfil="qualidade", origem="teste"
    )
    assert repetido["id"] == primeiro["id"]
    em_processo = nc.consultar({"situacao": "REPROCESSAMENTO"})
    assert len(em_processo) == 1
    assert em_processo[0]["saldo_fisico"]["peso_g"] == 1250000
    assert nc.indicadores(em_processo)["peso_bloqueado"] == 0
    resultado = reprocesso.concluir_reprocessamento(
        primeiro["id"], "Reprocesso consumido e concluído",
        usuario="Gerente", perfil="gerencia", origem="teste"
    )
    assert resultado["pnc_status"] == "REPROCESSADO"
    registro = linha(banco, "SELECT * FROM pa_nao_conformes WHERE id=?", (registro_id,))
    assert registro["status"] == "REPROCESSADO" and registro["saldo_bloqueado_g"] == 0
    assert nc.consultar({"situacao": "ATIVOS"}) == []
    assert nc.consultar({"situacao": "FINALIZADOS"})[0]["saldo_fisico"]["peso_g"] == 0


def test_caixa_rastreada_entra_uma_vez_no_saldo_em_processo_e_finaliza(banco):
    conn = banco()
    conn.execute("""INSERT INTO pa_caixas(id,codigo_caixa,condicao,disponibilidade,zona_estoque,
        motivo_nao_conformidade,local_estoque_id) VALUES(1,'CX-REPROC-1','NAO_CONFORME',
        'BLOQUEADO','Produto Não Conforme','Falha de selagem',4)""")
    agora = "2026-08-25 09:00:00"
    cursor = conn.execute("""INSERT INTO pa_nao_conformes(numero,caixa_id,produto,apresentacao,
        quantidade,peso,unidade,motivo,status,local_estoque_id,registrado_por,perfil_registro,
        registrado_em,criado_em,atualizado_em,tipo_registro)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("PNC-CX-REPROC-1", 1, "Galinha Cortada", "Congelada", 12, 10.5, "BANDEJA",
         "Falha de selagem", "BLOQUEADO", 4, "Produção", "producao", agora, agora, agora,
         "CAIXA_RASTREADA"))
    conn.commit()
    registro_id = cursor.lastrowid
    conn.close()
    processo = reprocesso.iniciar_reprocessamento(registro_id, {
        "modalidade": "INTEGRAL", "justificativa": "Reprocesso integral da caixa",
    }, usuario="Qualidade", perfil="qualidade", origem="teste")
    ativo = nc.consultar({"situacao": "REPROCESSAMENTO"})[0]
    assert (ativo["saldo_fisico"]["peso_g"], ativo["saldo_fisico"]["caixas"],
            ativo["saldo_fisico"]["bandejas"]) == (10500, 1, 12)
    reprocesso.concluir_reprocessamento(
        processo["id"], "Caixa consumida no reprocesso",
        usuario="Gerente", perfil="gerencia", origem="teste"
    )
    assert linha(banco, "SELECT status FROM pa_nao_conformes WHERE id=?", (registro_id,))["status"] == "REPROCESSADO"
    assert linha(banco, "SELECT disponibilidade FROM pa_caixas WHERE id=1")["disponibilidade"] == "REPROCESSADO"


def test_galinha_inteira_preserva_pacotes_e_galinhas_sem_inventar_peso(banco):
    conn = banco()
    conn.execute("""INSERT INTO pa_caixas(id,codigo_caixa,condicao,disponibilidade,zona_estoque,
        motivo_nao_conformidade,local_estoque_id,quantidade_pacotes,quantidade_galinhas)
        VALUES(2,'CX-GI-REPROC','NAO_CONFORME','BLOQUEADO','Produto Não Conforme',
        'Carcaça Incompleta',4,5,10)""")
    agora = "2026-08-25 09:30:00"
    cursor = conn.execute("""INSERT INTO pa_nao_conformes(numero,caixa_id,produto,apresentacao,
        quantidade,peso,unidade,motivo,status,local_estoque_id,registrado_por,perfil_registro,
        registrado_em,criado_em,atualizado_em,tipo_registro)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("PNC-GI-REPROC", 2, "Galinha Inteira", "Pacote com 2 aves", 5, None, "PACOTE",
         "Carcaça Incompleta", "BLOQUEADO", 4, "Produção", "producao", agora, agora, agora,
         "CAIXA_RASTREADA"))
    conn.commit()
    registro_id = cursor.lastrowid
    conn.close()
    reprocesso.iniciar_reprocessamento(registro_id, {
        "modalidade": "INTEGRAL", "justificativa": "Reprocesso integral de aves",
    }, usuario="Qualidade", perfil="qualidade", origem="teste")
    saldo = nc.consultar({"situacao": "REPROCESSAMENTO"})[0]["saldo_fisico"]
    assert (saldo["peso_g"], saldo["pacotes"], saldo["galinhas"]) == (0, 5, 10)


def test_reprocessamento_parcial_conclui_e_mantem_somente_remanescente_ativo(banco):
    registro_id = criar_legado(banco)
    processo = reprocesso.iniciar_reprocessamento(registro_id, {
        "modalidade": "PARCIAL", "peso": "500,000", "caixas": "40", "bandejas": "480",
        "justificativa": "Parcela segregada para reprocesso", "idempotency_key": "REPROC-PARCIAL-1",
    }, usuario="Qualidade", perfil="qualidade", origem="teste")
    reprocesso.concluir_reprocessamento(
        processo["id"], "Parcela consumida no reprocesso",
        usuario="Gerente", perfil="gerencia", origem="teste"
    )
    registro = linha(banco, "SELECT * FROM pa_nao_conformes WHERE id=?", (registro_id,))
    assert (registro["status"], registro["saldo_bloqueado_g"], registro["caixas_bloqueadas"],
            registro["bandejas_bloqueadas"]) == ("BLOQUEADO", 750000, 60, 720)
    ativo = nc.consultar({"situacao": "ATIVOS"})[0]
    assert ativo["saldo_fisico"]["peso_g"] == 750000


def test_cancelamento_restaura_exatamente_o_bloqueio_e_preserva_historico(banco):
    registro_id = criar_legado(banco)
    processo = reprocesso.iniciar_reprocessamento(registro_id, {
        "modalidade": "PARCIAL", "peso": "500", "caixas": 40, "bandejas": 480,
        "justificativa": "Teste de processo", "idempotency_key": "REPROC-CANCELA-1",
    }, usuario="Qualidade", perfil="qualidade", origem="teste")
    resultado = reprocesso.cancelar_reprocessamento(
        processo["id"], "Equipamento indisponível", usuario="Gerente", perfil="gerencia", origem="teste"
    )
    assert resultado["pnc_status"] == "BLOQUEADO"
    registro = linha(banco, "SELECT * FROM pa_nao_conformes WHERE id=?", (registro_id,))
    assert (registro["saldo_bloqueado_g"], registro["caixas_bloqueadas"],
            registro["bandejas_bloqueadas"]) == (1250000, 100, 1200)
    assert linha(banco, "SELECT status FROM pnc_reprocessamentos WHERE id=?", (processo["id"],))["status"] == "CANCELADO"
    assert linha(banco, "SELECT COUNT(*) total FROM pa_nao_conforme_eventos WHERE pa_nao_conforme_id=?",
                 (registro_id,))["total"] == 2


def test_falha_intermediaria_desfaz_inicio_por_inteiro(banco):
    registro_id = criar_legado(banco)

    def falhar(etapa):
        assert etapa == "reprocessamento_iniciado"
        raise RuntimeError("falha simulada")

    with pytest.raises(RuntimeError, match="falha simulada"):
        reprocesso.iniciar_reprocessamento(registro_id, {
            "modalidade": "INTEGRAL", "justificativa": "Teste de rollback",
        }, usuario="Qualidade", perfil="qualidade", origem="teste", checkpoint=falhar)
    registro = linha(banco, "SELECT * FROM pa_nao_conformes WHERE id=?", (registro_id,))
    assert registro["status"] == "BLOQUEADO" and registro["saldo_bloqueado_g"] == 1250000
    assert linha(banco, "SELECT COUNT(*) total FROM pnc_reprocessamentos")["total"] == 0


def test_reprocessamento_recusa_saldo_excedente_e_segunda_destinacao(banco):
    registro_id = criar_legado(banco)
    with pytest.raises(ValueError, match="excede"):
        reprocesso.iniciar_reprocessamento(registro_id, {
            "modalidade": "PARCIAL", "peso": "1300", "caixas": 1, "bandejas": 1,
            "justificativa": "Inválido",
        }, usuario="Qualidade", perfil="qualidade", origem="teste")
    reprocesso.iniciar_reprocessamento(registro_id, {
        "modalidade": "INTEGRAL", "justificativa": "Válido", "idempotency_key": "REPROC-VALIDO",
    }, usuario="Qualidade", perfil="qualidade", origem="teste")
    with pytest.raises(ValueError, match="não está disponível|em andamento"):
        reprocesso.iniciar_reprocessamento(registro_id, {
            "modalidade": "INTEGRAL", "justificativa": "Concorrente", "idempotency_key": "REPROC-OUTRO",
        }, usuario="Qualidade", perfil="qualidade", origem="teste")


def test_inicio_cancela_liberacao_pendente_sem_criar_estoque_operacional(banco):
    registro_id = criar_legado(banco)
    solicitacao_id = liberacoes.solicitar(
        registro_id, "100", 8, 96, "Avaliação comercial",
        usuario="Qualidade A", perfil="qualidade", origem="teste",
    )
    processo = reprocesso.iniciar_reprocessamento(registro_id, {
        "modalidade": "INTEGRAL", "justificativa": "Prioridade técnica de reprocesso",
    }, usuario="Qualidade B", perfil="qualidade", origem="teste")
    solicitacao = linha(banco, "SELECT * FROM pa_nao_conforme_solicitacoes WHERE id=?", (solicitacao_id,))
    registro = linha(banco, "SELECT * FROM pa_nao_conformes WHERE id=?", (registro_id,))
    assert solicitacao["status"] == reprocesso.CANCELADA_LIBERACAO
    assert registro["saldo_pendente_g"] == 0 and registro["saldo_operacional_g"] == 0
    assert processo["status"] == reprocesso.EM_ANDAMENTO


def test_dois_inicios_concorrentes_consumem_o_saldo_uma_unica_vez(banco):
    registro_id = criar_legado(banco)

    def iniciar(indice):
        try:
            return reprocesso.iniciar_reprocessamento(registro_id, {
                "modalidade": "INTEGRAL", "justificativa": "Corrida controlada",
                "idempotency_key": f"REPROC-CORRIDA-{indice}",
            }, usuario=f"Qualidade {indice}", perfil="qualidade", origem="teste")
        except ValueError as erro:
            return str(erro)

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(iniciar, (1, 2)))
    assert sum(isinstance(item, dict) for item in resultados) == 1
    assert linha(banco, "SELECT COUNT(*) total FROM pnc_reprocessamentos")["total"] == 1
    assert linha(banco, "SELECT saldo_bloqueado_g FROM pa_nao_conformes WHERE id=?", (registro_id,))["saldo_bloqueado_g"] == 0


def test_migration_sqlite_upgrade_downgrade_upgrade(tmp_path):
    raiz = __import__("pathlib").Path(__file__).resolve().parents[1]
    upgrade = (raiz / "database" / "20260825_p1_1_reprocessamento_pnc_sqlite.sql").read_text(encoding="utf-8")
    downgrade = (raiz / "database" / "20260825_p1_1_reprocessamento_pnc_sqlite_rollback.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(tmp_path / "migration-reprocesso.db")
    conn.executescript(upgrade)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='pnc_reprocessamentos'").fetchone()
    conn.executescript(downgrade)
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name='pnc_reprocessamentos'").fetchone()
    conn.executescript(upgrade)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='pnc_reprocessamentos'").fetchone()
    conn.close()
