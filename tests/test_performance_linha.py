import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from modules.producao import disponibilidade as disp
from modules.producao import performance as perf


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "performance.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(perf, "conectar", conectar)
    monkeypatch.setattr(disp, "conectar", conectar)
    conn = conectar()
    conn.executescript("""
    CREATE TABLE ordens_producao (
      id INTEGER PRIMARY KEY, data TEXT NOT NULL, quantidade_aves INTEGER,
      mortes_antes_pendura INTEGER, status TEXT, sku TEXT,
      fornecedor TEXT DEFAULT 'Fornecedor', peso_vivo REAL DEFAULT 0,
      peso_medio REAL DEFAULT 0, gta TEXT, nota_fiscal TEXT, observacoes TEXT
    );
    CREATE TABLE apontamentos_descartes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER, data TEXT,
      setor TEXT, categoria TEXT, motivo TEXT, quantidade REAL, unidade TEXT,
      observacoes TEXT
    );
    CREATE TABLE apontamentos_paradas (
      id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER, data TEXT,
      data_fim TEXT, setor TEXT, motivo TEXT, hora_inicio TEXT, hora_fim TEXT,
      horas_paradas REAL DEFAULT 0, manutencao_aberta TEXT,
      afeta_linha_abate INTEGER, natureza_disponibilidade TEXT
    );
    CREATE TABLE apontamentos_producao (
      id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER, setor TEXT,
      quantidade REAL, unidade TEXT
    );
    CREATE TABLE produtos_nao_conformes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER, quantidade REAL
    );
    INSERT INTO ordens_producao
      (id,data,quantidade_aves,mortes_antes_pendura,status,sku)
      VALUES (1,'2026-08-10',1000,0,'Encerrada','Galinha Cortada');
    """)
    conn.commit()
    conn.close()
    disp.criar_tabelas_disponibilidade()
    perf.criar_tabelas_performance()
    return conectar


def disponibilidade(status="CALCULAVEL", tempo=60):
    return {"situacao": status, "tempo_operacional_minutos": tempo}


def inserir_snapshot(banco, velocidade="1000", configuracao="PADRAO", atual=1, versao=1):
    conn = banco()
    conn.execute("""INSERT INTO linha_performance_snapshots_op
      (op_id,velocidade_id,linha,configuracao,sku,velocidade_aves_hora,
       vigencia_inicio,resolvido_em,resolvido_por,versao,atual)
      VALUES (1,1,'LINHA_ABATE',?,'Galinha Cortada',?,'2026-08-01',
              '2026-08-10T07:00:00-04:00','Prod',?,?)""",
      (configuracao, velocidade, versao, atual))
    conn.commit(); conn.close()


def inserir_contagem(banco, recebidas="1000", mortes="0", processadas="1000", atual=1):
    conn = banco()
    conn.execute("""INSERT INTO linha_performance_contagens
      (op_id,aves_recebidas,mortes_antes_pendura,aves_processadas,origem_calculo,
       confirmado_por,confirmado_em,versao,atual)
      VALUES (1,?,?,?,'OP_QUANTIDADE_AVES + MORTE_NA_GAIOLA','Prod',
              '2026-08-10T16:00:00-04:00',1,?)""", (recebidas, mortes, processadas, atual))
    conn.commit(); conn.close()


def resultado(banco, *, status="CALCULAVEL", tempo=60):
    conn = banco()
    try:
        return perf.calcular_performance(1, conn=conn, disponibilidade=disponibilidade(status, tempo))
    finally:
        conn.close()


def preparar_calculo(banco, *, velocidade="1000", recebidas="1000", mortes="0", processadas="1000"):
    inserir_snapshot(banco, velocidade)
    inserir_contagem(banco, recebidas, mortes, processadas)


def propor_aprovar_ativar(*, configuracao="PADRAO", sku="Galinha Cortada", velocidade="1000", inicio="2026-08-01"):
    velocidade_id = perf.propor_velocidade(
        configuracao, sku, velocidade, inicio, "Estudo tecnico aprovado",
        usuario="PCP", usuario_id=2, perfil="pcp",
    )
    perf.decidir_velocidade(velocidade_id, "APROVAR", "Validacao administrativa",
                            usuario="Admin", usuario_id=1, perfil="admin")
    perf.decidir_velocidade(velocidade_id, "ATIVAR", "Liberacao operacional",
                            usuario="Admin", usuario_id=1, perfil="admin")
    return velocidade_id


def programar():
    disp.salvar_programacao(
        1, "2026-08-10T08:00-04:00", "2026-08-10T16:00-04:00", [],
        usuario="PCP", usuario_id=2, perfil="pcp",
    )


def test_01_performance_exatamente_cem(banco):
    preparar_calculo(banco)
    assert resultado(banco)["performance"] == Decimal("100")


def test_02_performance_abaixo_de_cem(banco):
    preparar_calculo(banco, recebidas="800", processadas="800")
    assert resultado(banco)["performance"] == Decimal("80.0")


def test_03_performance_acima_de_cem_preservada_com_alerta(banco):
    preparar_calculo(banco, recebidas="1200", processadas="1200")
    r = resultado(banco)
    assert r["performance"] == Decimal("120.0")
    assert "acima de 100%" in r["alertas"][0]


def test_04_velocidade_ausente(banco):
    inserir_contagem(banco)
    r = resultado(banco)
    assert r["situacao"] == "NAO_CALCULAVEL" and r["performance"] is None


def test_05_velocidade_zero_no_snapshot_e_inconsistente(banco):
    inserir_snapshot(banco, "0"); inserir_contagem(banco)
    r = resultado(banco)
    assert r["situacao"] == "INCONSISTENTE"
    assert r["inconsistencias"][0]["codigo"] == "VELOCIDADE_NAO_POSITIVA"


def test_06_quantidade_ausente(banco):
    inserir_snapshot(banco)
    assert resultado(banco)["situacao"] == "NAO_CALCULAVEL"


def test_07_quantidade_zero_explicitamente_confirmada(banco):
    preparar_calculo(banco, recebidas="0", processadas="0")
    r = resultado(banco)
    assert r["performance"] == Decimal("0")
    assert "zero" in r["alertas"][0].lower()


def test_08_disponibilidade_calculavel_fornece_tempo(banco):
    preparar_calculo(banco)
    assert resultado(banco, tempo=90)["tempo_operacional_minutos"] == Decimal("90")


def test_09_disponibilidade_em_andamento_nao_exibe_percentual(banco):
    preparar_calculo(banco)
    r = resultado(banco, status="EM_ANDAMENTO", tempo=None)
    assert r["situacao"] == "EM_ANDAMENTO" and r["performance"] is None


def test_10_disponibilidade_nao_calculavel(banco):
    preparar_calculo(banco)
    assert resultado(banco, status="NAO_CALCULAVEL", tempo=None)["situacao"] == "NAO_CALCULAVEL"


def test_11_disponibilidade_inconsistente(banco):
    preparar_calculo(banco)
    r = resultado(banco, status="INCONSISTENTE", tempo=None)
    assert r["situacao"] == "INCONSISTENTE"


@pytest.mark.parametrize("tempo,codigo", [(None, "TEMPO_OPERACIONAL_AUSENTE"), (0, "TEMPO_OPERACIONAL_NAO_POSITIVO")])
def test_12_tempo_operacional_ausente_ou_zero(banco, tempo, codigo):
    preparar_calculo(banco)
    r = resultado(banco, tempo=tempo)
    assert r["situacao"] == "INCONSISTENTE"
    assert r["inconsistencias"][0]["codigo"] == codigo


def test_13_snapshot_preservado_apos_nova_vigencia(banco):
    programar(); primeira = propor_aprovar_ativar()
    snapshot = perf.preparar_snapshot_inicio(1, usuario="Prod", perfil="producao")
    perf.decidir_velocidade(primeira, "ENCERRAR", "Nova referencia", vigencia_fim=date.today().isoformat(), usuario="Admin", perfil="admin")
    conn = banco(); valor = conn.execute("SELECT velocidade_id,velocidade_aves_hora FROM linha_performance_snapshots_op WHERE id=?", (snapshot,)).fetchone(); conn.close()
    assert valor["velocidade_id"] == primeira and valor["velocidade_aves_hora"] == "1000"


def test_14_tentativa_alterar_vigencia_passada(banco):
    velocidade_id = propor_aprovar_ativar(inicio="2026-01-01")
    with pytest.raises(ValueError, match="retroativamente"):
        perf.decidir_velocidade(velocidade_id, "ENCERRAR", "Retroagir", vigencia_fim="2026-01-31", usuario="Admin", perfil="admin")


def test_15_vigencias_ativas_sobrepostas(banco):
    propor_aprovar_ativar()
    segunda = perf.propor_velocidade("PADRAO", "Galinha Cortada", "1100", "2026-08-05", "Novo estudo", usuario="Gerente", perfil="gerencia")
    perf.decidir_velocidade(segunda, "APROVAR", "Aprovada", usuario="Admin", perfil="admin")
    with pytest.raises(ValueError, match="sobreposta"):
        perf.decidir_velocidade(segunda, "ATIVAR", "Ativar", usuario="Admin", perfil="admin")


def test_16_velocidade_negativa_ou_zero_rejeitada(banco):
    for valor in ("0", "-1"):
        with pytest.raises(ValueError, match="maior que zero"):
            perf.propor_velocidade("PADRAO", None, valor, "2026-08-01", "Teste", usuario="PCP", perfil="pcp")


def test_17_proposta_aprovacao_rejeicao_ativacao_e_encerramento(banco):
    rejeitada = perf.propor_velocidade("A", None, "1000", "2026-08-01", "Teste", usuario="PCP", perfil="pcp")
    assert perf.decidir_velocidade(rejeitada, "REJEITAR", "Nao aprovada", usuario="Admin", perfil="admin") == "REJEITADA"
    ativa = propor_aprovar_ativar(configuracao="B", sku=None)
    assert perf.decidir_velocidade(ativa, "ENCERRAR", "Fim", vigencia_fim=date.today().isoformat(), usuario="Admin", perfil="admin") == "ENCERRADA"


def test_18_tentativa_sem_permissao(banco):
    with pytest.raises(PermissionError):
        perf.propor_velocidade("A", None, "1000", "2026-08-01", "Teste", usuario="Qual", perfil="qualidade")
    with pytest.raises(PermissionError):
        perf.confirmar_contagem(1, 1000, 0, 1000, usuario="PCP", perfil="pcp")


def test_19_correcao_posterior_sem_justificativa(banco):
    perf.confirmar_contagem(1, 1000, 0, 1000, usuario="Prod", perfil="producao")
    conn=banco(); conn.execute("UPDATE ordens_producao SET mortes_antes_pendura=10 WHERE id=1"); conn.commit(); conn.close()
    with pytest.raises(ValueError, match="justificativa"):
        perf.confirmar_contagem(1, 1000, 10, 990, usuario="Admin", perfil="admin")


def test_20_correcao_posterior_com_auditoria(banco):
    perf.confirmar_contagem(1, 1000, 0, 1000, usuario="Prod", perfil="producao")
    conn=banco(); conn.execute("UPDATE ordens_producao SET mortes_antes_pendura=10 WHERE id=1"); conn.commit(); conn.close()
    perf.confirmar_contagem(1, 1000, 10, 990, justificativa="Conferencia documental", usuario="Admin", usuario_id=1, perfil="admin")
    conn=banco(); evento=conn.execute("SELECT * FROM linha_performance_auditoria WHERE acao='CORRECAO_CONTAGEM'").fetchone(); conn.close()
    assert evento["justificativa"] == "Conferencia documental" and evento["usuario"] == "Admin"


def test_21_aves_recebidas_menos_mortes_antes_pendura(banco):
    conn=banco(); conn.execute("UPDATE ordens_producao SET mortes_antes_pendura=5 WHERE id=1"); conn.execute("INSERT INTO apontamentos_descartes(op_id,motivo,quantidade,unidade) VALUES (1,'Morte na gaiola',10,'aves')"); conn.commit(); conn.close()
    sugestao = perf.sugerir_contagem(1)
    assert sugestao["aves_processadas"] == Decimal("985")


@pytest.mark.parametrize("motivo", ["Condenacao sanitaria", "Descarte pos pendura"])
def test_22_23_perdas_posteriores_nao_reduzem_performance(banco, motivo):
    conn=banco(); conn.execute("INSERT INTO apontamentos_descartes(op_id,motivo,quantidade,unidade) VALUES (1,?,100,'aves')", (motivo,)); conn.commit(); conn.close()
    assert perf.sugerir_contagem(1)["aves_processadas"] == Decimal("1000")


def test_24_produto_nao_conforme_nao_reduz_performance(banco):
    conn=banco(); conn.execute("INSERT INTO produtos_nao_conformes(op_id,quantidade) VALUES (1,500)"); conn.commit(); conn.close()
    assert perf.sugerir_contagem(1)["aves_processadas"] == Decimal("1000")


def test_25_reprocesso_que_atravessa_linha(banco):
    preparar_calculo(banco)
    perf.registrar_reprocesso(1, 100, "Sim", "2026-08-10T15:00", "Retorno real", "exec-1", usuario="Prod", perfil="producao")
    assert resultado(banco)["quantidade_total_considerada"] == Decimal("1100")


def test_26_reembalagem_nao_atravessa_linha(banco):
    preparar_calculo(banco)
    perf.registrar_reprocesso(1, 100, "Nao", "2026-08-10T15:00", "Reembalagem", "exec-1", usuario="Prod", perfil="producao")
    assert resultado(banco)["quantidade_total_considerada"] == Decimal("1000")


def test_27_multiplas_apresentacoes_nao_duplicam_aves(banco):
    preparar_calculo(banco)
    conn=banco(); conn.executemany("INSERT INTO apontamentos_producao(op_id,setor,quantidade,unidade) VALUES (1,'Expedicao',?,?)", [(50,"pacotes V1"),(80,"pacotes V2"),(500,"kg")]); conn.commit(); conn.close()
    assert resultado(banco)["quantidade_total_considerada"] == Decimal("1000")


def test_28_configuracao_unica_calculavel(banco):
    preparar_calculo(banco)
    assert resultado(banco)["configuracao"] == "PADRAO"


def test_29_multiplas_configuracoes_sem_segmentacao_nao_calculavel(banco):
    inserir_snapshot(banco, configuracao="A"); inserir_snapshot(banco, configuracao="B"); inserir_contagem(banco)
    r=resultado(banco)
    assert r["situacao"] == "NAO_CALCULAVEL" and "Multiplas" in r["motivos"][0]


def test_30_op_historica_sem_snapshot_nao_recebe_backfill(banco):
    programar(); conn=banco(); conn.execute("UPDATE linha_abate_programacoes SET inicio_real='2026-08-10T08:00:00-04:00' WHERE op_id=1"); conn.commit(); conn.close()
    with pytest.raises(ValueError, match="retroativo"):
        perf.preparar_snapshot_inicio(1, usuario="Prod", perfil="producao")


def test_31_op_em_andamento_sem_percentual(banco):
    inserir_snapshot(banco)
    r=resultado(banco,status="EM_ANDAMENTO",tempo=None)
    assert r["performance"] is None


def test_32_op_reaberta_invalida_snapshot_e_contagem(banco):
    preparar_calculo(banco)
    conn=banco(); cursor=conn.cursor(); perf.invalidar_por_reabertura(1,cursor=cursor,usuario="Admin",perfil="admin"); conn.execute("UPDATE ordens_producao SET status='Aberta' WHERE id=1"); conn.commit(); conn.close()
    r=resultado(banco)
    assert r["situacao"] == "EM_ANDAMENTO"


def test_33_op_cancelada(banco):
    preparar_calculo(banco); conn=banco(); conn.execute("UPDATE ordens_producao SET status='Cancelada' WHERE id=1"); conn.commit(); conn.close()
    assert resultado(banco)["situacao"] == "NAO_CALCULAVEL"


def test_34_idempotencia_dupla_submissao(banco):
    primeiro=perf.confirmar_contagem(1,1000,0,1000,usuario="Prod",perfil="producao")
    segundo=perf.confirmar_contagem(1,1000,0,1000,usuario="Prod",perfil="producao")
    r1=perf.registrar_reprocesso(1,10,"Sim","2026-08-10T15:00","Teste","exec","chave-1",usuario="Prod",perfil="producao")
    r2=perf.registrar_reprocesso(1,10,"Sim","2026-08-10T15:00","Teste","exec","chave-1",usuario="Prod",perfil="producao")
    assert primeiro==segundo and r1==r2


def test_35_fuso_manaus_na_auditoria(banco):
    perf.confirmar_contagem(1,1000,0,1000,usuario="Prod",perfil="producao")
    conn=banco(); quando=conn.execute("SELECT criado_em FROM linha_performance_auditoria").fetchone()[0]; conn.close()
    assert datetime.fromisoformat(quando).utcoffset().total_seconds() == -4*3600


def test_36_regressao_disponibilidade(banco):
    programar(); conn=banco(); conn.execute("UPDATE linha_abate_programacoes SET inicio_real='2026-08-10T08:00:00-04:00',fim_real='2026-08-10T16:00:00-04:00' WHERE op_id=1"); conn.commit(); conn.close()
    r=disp.calcular_disponibilidade(1)
    assert r["situacao"]=="CALCULAVEL" and r["disponibilidade"]==Decimal("100")


def _codigo_performance():
    return (Path(__file__).parents[1]/"modules/producao/performance.py").read_text(encoding="utf-8").lower()


def test_37_regressao_fechamento_da_op_sem_dependencia(banco):
    assert "finalizar_embalagem" not in _codigo_performance()


def test_38_regressao_estoque_pi_pa_sem_dependencia(banco):
    assert "ativar_estoque" not in _codigo_performance()


def test_39_regressao_caixas_sem_dependencia(banco):
    assert "pa_caixas" not in _codigo_performance()


def test_40_regressao_romaneios_e_expedicao_sem_dependencia(banco):
    codigo = _codigo_performance()
    assert "romaneio" not in codigo and "expedicao" not in codigo


def test_41_regressao_rendimento_e_viabilidade_inalterados():
    conteudo=(Path(__file__).parents[1]/"modules/producao/services.py").read_text(encoding="utf-8")
    assert "viabilidade_percentual = (viabilidade / op[\"quantidade_aves\"]) * 100" in conteudo
    assert "rendimento = (kg_produzidos / op[\"peso_vivo\"]) * 100" in conteudo


def test_42_regressao_relatorio_eficiencia_sem_performance_oee():
    raiz=Path(__file__).parents[1]
    arquivos=list((raiz/"modules/relatorios").glob("*.py"))
    assert all("calcular_performance" not in item.read_text(encoding="utf-8") for item in arquivos)


def test_interface_exibe_oee_sem_calculo_parcial_e_formula_fica_no_servico():
    raiz=Path(__file__).parents[1]
    consulta=(raiz/"templates/_performance_linha.html").read_text(encoding="utf-8")
    assert "OEE" in consulta
    assert "OEE parcial" in consulta
    assert "Performance da Linha" in consulta
    assert "performance_linha.performance" in consulta


def test_contagem_persistida_invalida_nao_gera_percentual(banco):
    inserir_snapshot(banco)
    inserir_contagem(banco, recebidas="1000", mortes="10", processadas="1000")
    r = resultado(banco)
    assert r["situacao"] == "INCONSISTENTE"
    assert r["performance"] is None
    assert r["inconsistencias"][0]["codigo"] == "CONTAGEM_OFICIAL_INVALIDA"


def test_correcao_snapshot_rejeita_velocidade_de_outro_sku(banco):
    programar()
    velocidade_id = propor_aprovar_ativar(sku="Galinha Inteira")
    with pytest.raises(ValueError, match="nao corresponde"):
        perf.corrigir_snapshot(
            1, velocidade_id, "Correcao controlada", usuario="Admin", perfil="admin"
        )
