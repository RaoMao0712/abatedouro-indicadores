import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from modules.producao import disponibilidade as disp


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "disponibilidade.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(disp, "conectar", conectar)
    conn = conectar()
    conn.executescript("""
    CREATE TABLE ordens_producao (
        id INTEGER PRIMARY KEY, data TEXT NOT NULL, status TEXT DEFAULT 'Aberta'
    );
    CREATE TABLE apontamentos_paradas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, evento_id TEXT, op_id INTEGER,
        data TEXT NOT NULL, data_fim TEXT, setor TEXT NOT NULL, motivo TEXT NOT NULL,
        equipamento TEXT, equipamento_id INTEGER, hora_inicio TEXT, hora_fim TEXT,
        horas_paradas REAL NOT NULL DEFAULT 0, observacoes TEXT,
        manutencao_aberta TEXT, criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO ordens_producao(id,data,status) VALUES (1,'2026-08-10','Aberta');
    """)
    conn.commit()
    conn.close()
    disp.criar_tabelas_disponibilidade()
    return conectar


def programar(pausas=None, inicio="2026-08-10T08:00", fim="2026-08-10T16:00"):
    return disp.salvar_programacao(
        1, inicio, fim, pausas or [], usuario="PCP", usuario_id=10, perfil="pcp"
    )


def medir(conectar, inicio="2026-08-10T08:00", fim="2026-08-10T16:00"):
    conn = conectar()
    conn.execute(
        "UPDATE linha_abate_programacoes SET inicio_real=?,fim_real=? WHERE op_id=1",
        (inicio + "-04:00", fim + "-04:00"),
    )
    conn.commit()
    conn.close()


def parada(conectar, inicio, fim, *, data="2026-08-10", data_fim=None, op_id=1,
           afeta=1, setor="Corte", natureza="NAO_PLANEJADA"):
    conn = conectar()
    conn.execute("""INSERT INTO apontamentos_paradas
        (op_id,data,data_fim,setor,motivo,hora_inicio,hora_fim,horas_paradas,
         afeta_linha_abate,natureza_disponibilidade)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (op_id, data, data_fim, setor, "Falha", inicio, fim, 1, afeta, natureza))
    conn.commit()
    conn.close()


def resultado():
    return disp.calcular_disponibilidade(1)


def test_op_programada_sem_perda_tem_cem_por_cento(banco):
    programar(); medir(banco)
    assert resultado()["disponibilidade"] == Decimal("100")


def test_almoco_e_limpeza_saem_do_denominador(banco):
    programar([
        {"categoria": "ALMOCO", "inicio_previsto": "12:00", "fim_previsto": "13:00"},
        {"categoria": "LIMPEZA_PROGRAMADA", "inicio_previsto": "15:30", "fim_previsto": "15:45"},
    ])
    medir(banco)
    r = resultado()
    assert r["paradas_planejadas_minutos"] == Decimal("75")
    assert r["tempo_planejado_liquido_minutos"] == Decimal("405")
    assert r["disponibilidade"] == Decimal("100")


def test_parada_nao_planejada_reduz_disponibilidade(banco):
    programar(); medir(banco); parada(banco, "10:00", "11:00")
    assert resultado()["disponibilidade"] == Decimal("87.500")


def test_inicio_atrasado_reduz_disponibilidade(banco):
    programar(); medir(banco, "2026-08-10T09:00")
    r = resultado()
    assert r["atraso_inicio_minutos"] == Decimal("60")
    assert r["disponibilidade"] == Decimal("87.500")


def test_encerramento_antecipado_reduz_disponibilidade(banco):
    programar(); medir(banco, fim="2026-08-10T15:00")
    r = resultado()
    assert r["encerramento_antecipado_minutos"] == Decimal("60")
    assert r["disponibilidade"] == Decimal("87.500")


def test_inicio_antecipado_nao_supera_cem(banco):
    programar(); medir(banco, inicio="2026-08-10T07:00")
    assert resultado()["disponibilidade"] == Decimal("100")


def test_termino_posterior_nao_supera_cem(banco):
    programar(); medir(banco, fim="2026-08-10T17:00")
    assert resultado()["disponibilidade"] == Decimal("100")


def test_paradas_sobrepostas_contam_minuto_uma_vez(banco):
    programar(); medir(banco)
    parada(banco, "10:00", "11:00"); parada(banco, "10:30", "11:30", setor="Embalagem")
    r = resultado()
    assert r["paradas_nao_planejadas_minutos"] == Decimal("90.0")
    assert r["disponibilidade"] == Decimal("81.2500")


def test_sobreposicao_com_pausa_planejada_nao_reduz_duas_vezes(banco):
    programar([{"categoria": "ALMOCO", "inicio_previsto": "12:00", "fim_previsto": "13:00"}])
    medir(banco); parada(banco, "11:30", "12:30")
    r = resultado()
    assert r["paradas_nao_planejadas_minutos"] == Decimal("30.0")
    assert r["tempo_planejado_liquido_minutos"] == Decimal("420")


def test_excesso_de_pausa_e_perda_nao_planejada(banco):
    programar([{"categoria": "ALMOCO", "inicio_previsto": "12:00", "fim_previsto": "13:00"}])
    medir(banco); parada(banco, "12:00", "13:30")
    assert resultado()["paradas_nao_planejadas_minutos"] == Decimal("30.0")


def test_op_que_atravessa_meia_noite(banco):
    programar(inicio="2026-08-10T22:00", fim="2026-08-10T06:00")
    medir(banco, "2026-08-10T22:00", "2026-08-11T06:00")
    assert resultado()["duracao_bruta_minutos"] == Decimal("480")
    assert resultado()["disponibilidade"] == Decimal("100")


def test_programacao_sobreposta_e_rejeitada(banco):
    with pytest.raises(ValueError, match="sobrepor"):
        programar([
            {"categoria": "ALMOCO", "inicio_previsto": "12:00", "fim_previsto": "13:00"},
            {"categoria": "INTERVALO_CURTO", "inicio_previsto": "12:30", "fim_previsto": "12:45"},
        ])


def test_op_historica_sem_programacao_nao_e_zero(banco):
    r = resultado()
    assert r["situacao"] == "NAO_CALCULAVEL"
    assert r["disponibilidade"] is None


def test_inicio_e_fim_sao_idempotentes(banco):
    programar()
    inicio = datetime.fromisoformat("2026-08-10T08:00:00-04:00")
    fim = datetime.fromisoformat("2026-08-10T16:00:00-04:00")
    assert disp.registrar_inicio_linha(1, usuario="Prod", perfil="producao", agora=inicio) == disp.registrar_inicio_linha(1, usuario="Prod", perfil="producao", agora=inicio)
    assert disp.registrar_fim_linha(1, usuario="Prod", perfil="producao", agora=fim) == disp.registrar_fim_linha(1, usuario="Prod", perfil="producao", agora=fim)
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM linha_abate_auditoria WHERE acao IN ('INICIO_LINHA','FIM_LINHA')").fetchone()[0] == 2
    conn.close()


def test_perfil_sem_permissao_e_bloqueado_no_servico(banco):
    with pytest.raises(PermissionError):
        disp.salvar_programacao(1, "2026-08-10T08:00", "2026-08-10T16:00", [], perfil="qualidade")
    programar()
    with pytest.raises(PermissionError):
        disp.registrar_inicio_linha(1, perfil="pcp")


def test_alteracao_pos_inicio_exige_admin_e_justificativa(banco):
    programar()
    disp.registrar_inicio_linha(1, usuario="Prod", perfil="producao", agora=datetime.fromisoformat("2026-08-10T08:00-04:00"))
    with pytest.raises(PermissionError):
        disp.salvar_programacao(1, "2026-08-10T08:30", "2026-08-10T16:00", [], perfil="pcp")
    with pytest.raises(ValueError, match="justificativa"):
        disp.salvar_programacao(1, "2026-08-10T08:30", "2026-08-10T16:00", [], perfil="admin")


def test_alteracao_auditada_preserva_antes_depois_usuario_e_motivo(banco):
    programar()
    disp.registrar_inicio_linha(1, usuario="Prod", perfil="producao", agora=datetime.fromisoformat("2026-08-10T08:00-04:00"))
    disp.salvar_programacao(1, "2026-08-10T08:30", "2026-08-10T16:00", [],
                           perfil="admin", usuario="Admin", justificativa="Mudanca aprovada")
    conn = banco(); evento = conn.execute("SELECT * FROM linha_abate_auditoria WHERE acao='ALTERACAO_PROGRAMACAO'").fetchone(); conn.close()
    assert evento["valor_anterior"] and evento["valor_novo"]
    assert evento["usuario"] == "Admin"
    assert evento["justificativa"] == "Mudanca aprovada"


def test_parada_orfa_e_identificada_sem_quebrar_consulta(banco):
    parada(banco, "10:00", "10:30", op_id=999)
    itens = disp.consultar_historico_paradas({"status": "ORFA"})
    assert len(itens) == 1
    assert itens[0]["registro_orfao"] == 1


def test_reclassificacao_exige_valor_explicito(banco):
    parada(banco, "10:00", "10:30")
    with pytest.raises(ValueError, match="afetou ou nao"):
        disp.reclassificar_parada(
            1, "", "Revisao administrativa", perfil="admin", usuario="Admin"
        )


def test_corretiva_nao_pode_virar_preventiva_programada(banco):
    programar()
    disp.registrar_inicio_linha(
        1, usuario="Prod", perfil="producao",
        agora=datetime.fromisoformat("2026-08-10T08:00-04:00"),
    )
    conn = banco()
    conn.execute("""INSERT INTO apontamentos_paradas
        (op_id,data,setor,motivo,hora_inicio,hora_fim,horas_paradas,
         manutencao_aberta,afeta_linha_abate,natureza_disponibilidade)
        VALUES (1,'2026-08-10','Corte','Falha mecanica','10:00','11:00',1,
                'Sim',1,'NAO_PLANEJADA')""")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="corretiva"):
        disp.salvar_programacao(
            1, "2026-08-10T08:00", "2026-08-10T16:00",
            [{
                "categoria": "MANUTENCAO_PREVENTIVA_PROGRAMADA",
                "inicio_previsto": "10:00",
                "fim_previsto": "11:00",
            }],
            perfil="admin", usuario="Admin", justificativa="Revisao posterior",
        )


def test_parada_fechada_sem_classificacao_torna_resultado_inconsistente(banco):
    programar(); medir(banco); parada(banco, "10:00", "11:00", afeta=None)
    r = resultado()
    assert r["situacao"] == "INCONSISTENTE"
    assert r["disponibilidade"] is None
    assert r["tempo_operacional_minutos"] is None
    assert r["inconsistencias"] == [{
        "codigo": "PARADA_SEM_CLASSIFICACAO_IMPACTO", "parada_id": 1,
    }]
    assert "reclassificacao administrativa" in r["alertas"][0]


def test_parada_aberta_sem_classificacao_torna_resultado_inconsistente(banco):
    programar(); medir(banco); parada(banco, "10:00", "", afeta=None)
    r = resultado()
    assert r["situacao"] == "INCONSISTENTE"
    assert r["disponibilidade"] is None


def test_parada_com_impacto_e_natureza_ausente_e_inconsistente(banco):
    programar(); medir(banco); parada(banco, "10:00", "11:00", natureza=None)
    r = resultado()
    assert r["situacao"] == "INCONSISTENTE"
    assert r["disponibilidade"] is None
    assert r["inconsistencias"][0]["codigo"] == "PARADA_COM_NATUREZA_INVALIDA"


def test_parada_explicitamente_sem_impacto_nao_bloqueia_calculo(banco):
    programar(); medir(banco)
    parada(banco, "10:00", "11:00", afeta=0, natureza=None)
    r = resultado()
    assert r["situacao"] == "CALCULAVEL"
    assert r["disponibilidade"] == Decimal("100")
    assert r["paradas_nao_planejadas_minutos"] == Decimal("0")


def test_parada_sem_classificacao_totalmente_fora_da_janela_nao_bloqueia(banco):
    programar(); medir(banco); parada(banco, "17:00", "18:00", afeta=None)
    r = resultado()
    assert r["situacao"] == "CALCULAVEL"
    assert r["disponibilidade"] == Decimal("100")


def test_parada_sem_classificacao_parcialmente_sobreposta_bloqueia(banco):
    programar(); medir(banco); parada(banco, "07:30", "08:30", afeta=None)
    r = resultado()
    assert r["situacao"] == "INCONSISTENTE"
    assert r["disponibilidade"] is None


def test_uma_parada_sem_classificacao_bloqueia_entre_multiplas(banco):
    programar(); medir(banco)
    parada(banco, "10:00", "11:00")
    parada(banco, "13:00", "13:30", afeta=None, setor="Embalagem")
    r = resultado()
    assert r["situacao"] == "INCONSISTENTE"
    assert r["disponibilidade"] is None
    assert r["paradas_nao_planejadas_minutos"] == Decimal("60.0")


def test_multiplas_inconsistencias_sao_acumuladas_sem_inspecao_de_texto(banco):
    programar(); medir(banco)
    parada(banco, "10:00", "", afeta=1, natureza=None)
    r = resultado()
    assert [item["codigo"] for item in r["inconsistencias"]] == [
        "PARADA_COM_NATUREZA_INVALIDA",
        "PARADA_ABERTA_OU_INTERVALO_INVALIDO",
    ]
    assert len(r["alertas"]) == 2
    assert r["disponibilidade"] is None


def test_calculo_nao_faz_backfill_em_registro_historico(banco):
    programar(); medir(banco); parada(banco, "10:00", "11:00", afeta=None, natureza=None)
    resultado()
    conn = banco()
    registro = conn.execute(
        "SELECT afeta_linha_abate,natureza_disponibilidade FROM apontamentos_paradas WHERE id=1"
    ).fetchone()
    auditorias = conn.execute(
        "SELECT COUNT(*) FROM linha_abate_auditoria WHERE entidade='PARADA'"
    ).fetchone()[0]
    conn.close()
    assert registro["afeta_linha_abate"] is None
    assert registro["natureza_disponibilidade"] is None
    assert auditorias == 0


def test_parada_nao_classificada_permanece_visivel_no_historico(banco):
    parada(banco, "10:00", "11:00", afeta=None, natureza=None)
    itens = disp.consultar_historico_paradas({"afeta": "NAO_CLASSIFICADA"})
    assert len(itens) == 1
    assert itens[0]["id"] == 1
    assert itens[0]["afeta_linha_abate"] is None


def test_reclassificacao_administrativa_regulariza_e_retorna_calculavel(banco):
    programar(); medir(banco); parada(banco, "10:00", "11:00", afeta=None, natureza=None)
    assert resultado()["situacao"] == "INCONSISTENTE"
    disp.reclassificar_parada(
        1, "sim", "Impacto confirmado", perfil="admin", usuario="Admin", usuario_id=9,
    )
    r = resultado()
    assert r["situacao"] == "CALCULAVEL"
    assert r["disponibilidade"] == Decimal("87.500")
    conn = banco()
    auditoria = conn.execute(
        "SELECT * FROM linha_abate_auditoria WHERE acao='RECLASSIFICACAO_PARADA'"
    ).fetchone()
    conn.close()
    assert auditoria["justificativa"] == "Impacto confirmado"
    assert auditoria["usuario"] == "Admin"


def test_estados_principais_permanecem_compativeis(banco):
    assert resultado()["situacao"] == "NAO_CALCULAVEL"
    programar()
    disp.registrar_inicio_linha(
        1, perfil="producao", agora=datetime.fromisoformat("2026-08-10T08:00-04:00")
    )
    assert resultado()["situacao"] == "EM_ANDAMENTO"
    disp.registrar_fim_linha(
        1, perfil="producao", agora=datetime.fromisoformat("2026-08-10T16:00-04:00")
    )
    assert resultado()["situacao"] == "CALCULAVEL"


def test_template_nao_exibe_percentual_oficial_com_resultado_inconsistente():
    conteudo = (Path(__file__).parents[1] / "templates" / "consultar_op.html").read_text(
        encoding="utf-8"
    )
    assert "situacao-{{ disponibilidade_linha.situacao|lower }}" in conteudo
    assert "disponibilidade_linha.disponibilidade is not none" in conteudo
    assert "Percentual oficial indispon&iacute;vel" in conteudo
