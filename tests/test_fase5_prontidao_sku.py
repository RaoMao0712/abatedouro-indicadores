import json
import sqlite3
from pathlib import Path

import pytest
from flask import Flask, session

from modules.engenharia_produtos import prontidao
from modules.engenharia_produtos import routes as engenharia_routes


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "fase5.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(prontidao, "conectar", conectar)
    monkeypatch.setattr(prontidao, "DATABASE_URL", None)
    prontidao.criar_estrutura()
    conn = conectar()
    conn.executescript("""
        CREATE TABLE op_config_reconciliacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER NOT NULL,
            snapshot_id INTEGER NOT NULL, sku TEXT NOT NULL,
            executado_em TEXT NOT NULL, resultado_geral TEXT NOT NULL,
            dimensoes_json TEXT NOT NULL, divergencias_json TEXT NOT NULL,
            versao_comparacao INTEGER NOT NULL, revisao INTEGER NOT NULL,
            hash_comparacao TEXT NOT NULL
        );
        CREATE TABLE op_config_reconciliacao_execucoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER NOT NULL,
            snapshot_id INTEGER NOT NULL, versao_comparacao INTEGER NOT NULL,
            gatilho TEXT NOT NULL, tentativa INTEGER NOT NULL, status TEXT NOT NULL,
            reconciliacao_id INTEGER, erro_tipo TEXT, erro_mensagem TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP, iniciado_em TEXT,
            concluido_em TEXT, atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY, sku TEXT, status TEXT);
        CREATE TABLE op_config_snapshots(id INTEGER PRIMARY KEY, op_id INTEGER UNIQUE, snapshot_json TEXT);
        CREATE TABLE estoque_eventos(id INTEGER PRIMARY KEY, op_id INTEGER);
        CREATE TABLE pa_nao_conformes(id INTEGER PRIMARY KEY, op_id INTEGER);
        CREATE TABLE expedicoes(id INTEGER PRIMARY KEY);
        CREATE TABLE cmv_eventos(id INTEGER PRIMARY KEY, op_id INTEGER);
        CREATE TABLE linha_oee(id INTEGER PRIMARY KEY);
        CREATE TABLE movimentacoes_financeiras(id INTEGER PRIMARY KEY);
        INSERT INTO ordens_producao VALUES(900,'Galinha Cortada','Aberta');
        INSERT INTO op_config_snapshots VALUES(900,900,'{"imutavel":true}');
        INSERT INTO estoque_eventos VALUES(1,900);
        INSERT INTO pa_nao_conformes VALUES(1,900);
        INSERT INTO expedicoes VALUES(1);
        INSERT INTO cmv_eventos VALUES(1,900);
        INSERT INTO linha_oee VALUES(1);
        INSERT INTO movimentacoes_financeiras VALUES(1);
    """)
    conn.commit(); conn.close()
    return conectar


def _dimensoes(sku="Galinha Cortada", resultado="PARIDADE", severidade="CRITICA", somente=None):
    nomes = somente or prontidao.DIMENSOES_CRITICAS_SKU[sku]
    return [{
        "dimensao": nome, "resultado": resultado, "severidade": severidade,
        "valor_legado": 1, "valor_sombra": 1 if resultado == "PARIDADE" else 2,
    } for nome in nomes]


def _evidencia(banco, op_id, resultado="PARIDADE", data="2026-09-01 10:00:00",
                sku="Galinha Cortada", revisao=1, dimensoes=None):
    dimensoes = dimensoes if dimensoes is not None else _dimensoes(sku, resultado)
    divergencias = [item for item in dimensoes if item["resultado"] != "PARIDADE"]
    conn = banco()
    conn.execute("""INSERT INTO op_config_reconciliacoes(
        op_id,snapshot_id,sku,executado_em,resultado_geral,dimensoes_json,
        divergencias_json,versao_comparacao,revisao,hash_comparacao
    ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
        op_id, op_id, sku, data, resultado, json.dumps(dimensoes),
        json.dumps(divergencias), 1, revisao, f"{op_id}-{revisao}-{resultado}",
    ))
    conn.execute("""INSERT INTO op_config_reconciliacao_execucoes(
        op_id,snapshot_id,versao_comparacao,gatilho,tentativa,status
    ) VALUES(?,?,1,'TESTE',1,'SUCESSO')""", (op_id, op_id))
    conn.commit(); conn.close()


def _parametros(banco, sku="Galinha Cortada", **mudancas):
    dados = {
        "minimo_ops_reconciliadas": 1, "janela_minima_dias": 0,
        "sequencia_minima_paridade": 1, "max_divergencias_media": 0,
        "max_divergencias_baixa": 0, "cobertura_critica_minima": 100,
        "dimensoes_criticas": prontidao.DIMENSOES_CRITICAS_SKU[sku],
    }
    dados.update(mudancas)
    return prontidao.salvar_parametros(sku, dados, {"id": 1, "nome": "Teste"})


def _fotografia(banco):
    conn = banco(); resultado = {}
    for tabela in ("ordens_producao", "op_config_snapshots", "op_config_reconciliacoes",
                   "estoque_eventos", "pa_nao_conformes", "expedicoes", "cmv_eventos",
                   "linha_oee", "movimentacoes_financeiras"):
        resultado[tabela] = [tuple(item) for item in conn.execute(f"SELECT * FROM {tabela}")]
    conn.close(); return resultado


def test_ausencia_de_dados_e_nao_avaliavel(banco):
    _parametros(banco)
    avaliacao = prontidao.recalcular("Galinha Cortada")
    assert avaliacao["estado"] == "NAO_AVALIAVEL"
    assert avaliacao["autoridade_operacional"] == "LEGADO"


def test_poucas_ops_paridade_insuficiente_e_em_observacao(banco):
    _parametros(banco, minimo_ops_reconciliadas=3, sequencia_minima_paridade=2)
    _evidencia(banco, 1)
    avaliacao = prontidao.recalcular("Galinha Cortada")
    assert avaliacao["estado"] == "EM_OBSERVACAO"
    assert any("Quantidade mínima" in motivo for motivo in avaliacao["motivos"])
    assert any("Sequência contínua" in motivo for motivo in avaliacao["motivos"])


def test_sequencia_e_cobertura_suficientes_chegam_a_apto(banco):
    _parametros(banco, minimo_ops_reconciliadas=3, sequencia_minima_paridade=3, janela_minima_dias=2)
    for op_id, dia in ((1, 1), (2, 2), (3, 3)):
        _evidencia(banco, op_id, data=f"2026-09-{dia:02d} 10:00:00")
    avaliacao = prontidao.recalcular("Galinha Cortada")
    assert avaliacao["estado"] == "APTO_PARA_AVALIACAO"
    assert avaliacao["metricas"]["sequencia_atual_paridade"] == 3
    assert avaliacao["metricas"]["maior_sequencia_paridade"] == 3
    assert avaliacao["metricas"]["cobertura_critica_percentual"] == 100
    assert avaliacao["autoridade_operacional"] == "LEGADO"


@pytest.mark.parametrize("severidade", ["CRITICA", "ALTA"])
def test_divergencia_critica_ou_alta_aberta_bloqueia(banco, severidade):
    _parametros(banco)
    _evidencia(banco, 1, resultado="DIVERGENCIA",
               dimensoes=_dimensoes(resultado="DIVERGENCIA", severidade=severidade,
                                    somente=["identidade_sku"]))
    avaliacao = prontidao.recalcular("Galinha Cortada")
    assert avaliacao["estado"] == "BLOQUEADO_POR_DIVERGENCIA"
    assert avaliacao["metricas"]["divergencias_abertas"][severidade] == 1


def test_divergencia_historica_superada_nao_fica_aberta(banco):
    _parametros(banco)
    _evidencia(banco, 1, resultado="DIVERGENCIA", revisao=1,
               dimensoes=_dimensoes(resultado="DIVERGENCIA", somente=["identidade_sku"]))
    _evidencia(banco, 1, resultado="PARIDADE", revisao=2,
               data="2026-09-02 10:00:00")
    avaliacao = prontidao.recalcular("Galinha Cortada")
    assert avaliacao["estado"] == "APTO_PARA_AVALIACAO"
    assert avaliacao["metricas"]["divergencias_abertas"]["CRITICA"] == 0
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM op_config_reconciliacoes WHERE op_id=1").fetchone()[0] == 2
    conn.close()


def test_cobertura_critica_incompleta_em_observacao(banco):
    _parametros(banco)
    _evidencia(banco, 1, dimensoes=_dimensoes(somente=["identidade_sku"]))
    avaliacao = prontidao.recalcular("Galinha Cortada")
    assert avaliacao["estado"] == "EM_OBSERVACAO"
    assert avaliacao["metricas"]["dimensoes_criticas_pendentes"]


def test_parametro_mudado_gera_nova_avaliacao_e_idempotencia(banco):
    _parametros(banco)
    _evidencia(banco, 1)
    primeira = prontidao.recalcular("Galinha Cortada")
    repetida = prontidao.recalcular("Galinha Cortada")
    assert repetida["id"] == primeira["id"]
    _parametros(banco, minimo_ops_reconciliadas=2)
    segunda = prontidao.recalcular("Galinha Cortada")
    assert segunda["id"] != primeira["id"]
    assert segunda["estado"] == "EM_OBSERVACAO"
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM sku_prontidao_avaliacoes").fetchone()[0] == 2
    conn.close()


def test_erro_no_calculo_nao_altera_modulos_operacionais(banco, monkeypatch):
    _parametros(banco)
    _evidencia(banco, 1)
    antes = _fotografia(banco)
    monkeypatch.setattr(prontidao, "calcular_metricas", lambda *_args: (_ for _ in ()).throw(RuntimeError("falha")))
    with pytest.raises(RuntimeError, match="falha"):
        prontidao.recalcular("Galinha Cortada")
    assert _fotografia(banco) == antes


def test_defaults_sao_conservadores_configuraveis_e_sku_invalido_rejeitado(banco):
    params = prontidao.obter_parametros("Galinha Inteira")
    assert params["minimo_ops_reconciliadas"] == 10
    assert params["janela_minima_dias"] == 30
    assert params["cobertura_critica_minima"] == 100
    with pytest.raises(ValueError, match="sem representação"):
        prontidao.recalcular("SKU Novo")


def test_visao_get_nao_recalcula_e_filtros_sao_exibidos(monkeypatch):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "teste"
    chamados = []
    monkeypatch.setattr(prontidao, "listar_avaliacoes", lambda filtros: ([], []))
    monkeypatch.setattr(prontidao, "recalcular", lambda *args: chamados.append(args))
    monkeypatch.setattr(
        engenharia_routes, "render_template",
        lambda _template, **contexto: "|".join(contexto["estados"]),
    )
    engenharia_routes.register_engenharia_produtos_routes(app)
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update({"usuario_id": 1, "nome": "Admin", "perfil": "admin"})
    resposta = cliente.get("/engenharia-produtos/prontidao?sku=Galinha+Cortada&estado=EM_OBSERVACAO")
    assert resposta.status_code == 200
    assert b"APTO_PARA_AVALIACAO" in resposta.data
    assert chamados == []


def test_acao_explicita_recalcula_sem_propagar_erro(monkeypatch):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "teste"
    monkeypatch.setattr(prontidao, "recalcular", lambda *_args: (_ for _ in ()).throw(RuntimeError("controlado")))
    engenharia_routes.register_engenharia_produtos_routes(app)
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update({"usuario_id": 1, "nome": "Admin", "perfil": "admin"})
    resposta = cliente.post(
        "/engenharia-produtos/prontidao/Galinha%20Cortada/recalcular",
        follow_redirects=False,
    )
    assert resposta.status_code == 302
    with cliente.session_transaction() as sessao:
        assert "Falha no cálculo" in sessao["_flashes"][0][1]
