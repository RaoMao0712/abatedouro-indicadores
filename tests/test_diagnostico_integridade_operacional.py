import hashlib
import sqlite3
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from modules.relatorios import integridade

SCHEMA = """
CREATE TABLE pa_caixas(id INTEGER PRIMARY KEY,codigo_caixa TEXT,unidade_estoque TEXT,quantidade_pacotes INTEGER,
  quantidade_galinhas INTEGER,galinhas_por_pacote INTEGER,quantidade_pacotes_reservados INTEGER,
  quantidade_bandejas REAL,peso_liquido REAL,disponibilidade TEXT,reservado_expedicao_id INTEGER);
CREATE TABLE pa_nao_conformes(id INTEGER PRIMARY KEY,numero TEXT,saldo_bloqueado_g INTEGER,saldo_pendente_g INTEGER,
  saldo_operacional_g INTEGER,saldo_reservado_operacional_g INTEGER,saldo_destinado_g INTEGER);
CREATE TABLE expedicoes(id INTEGER PRIMARY KEY,numero_romaneio TEXT,data TEXT,tipo_movimentacao TEXT,status TEXT,cliente_id INTEGER);
CREATE TABLE expedicao_itens(id INTEGER PRIMARY KEY,expedicao_id INTEGER,caixa_id INTEGER,unidade_estoque TEXT,ativo INTEGER DEFAULT 1);
CREATE TABLE cmv_camadas(id INTEGER PRIMARY KEY,produto TEXT,documento TEXT,quantidade_disponivel REAL);
CREATE TABLE cmv_eventos(id INTEGER PRIMARY KEY,tipo TEXT,data_evento TEXT,documento TEXT,produto TEXT,quantidade REAL,
  quantidade_com_custo REAL,quantidade_sem_custo REAL,evento_original_id INTEGER,origem_tipo TEXT,origem_id TEXT);
CREATE TABLE cmv_consumos(id INTEGER PRIMARY KEY,evento_id INTEGER,quantidade REAL);
CREATE TABLE pnc_romaneios_descarte(id INTEGER PRIMARY KEY,numero TEXT,status TEXT);
CREATE TABLE pnc_romaneio_descarte_itens(id INTEGER PRIMARY KEY,romaneio_id INTEGER,caixas INTEGER,bandejas INTEGER,galinhas INTEGER,pacotes INTEGER,peso_g INTEGER);
CREATE TABLE pnc_movimentos_descarte(id INTEGER PRIMARY KEY,romaneio_id INTEGER,tipo TEXT,caixas INTEGER,bandejas INTEGER,galinhas INTEGER,pacotes INTEGER,peso_g INTEGER);
"""

CONSISTENTE = """
INSERT INTO pa_caixas VALUES(1,'CX-1','CAIXA',NULL,NULL,NULL,0,12,25.5,'DISPONIVEL',NULL);
INSERT INTO pa_caixas VALUES(2,'PC-2','PACOTE',10,20,2,4,0,0,'DISPONIVEL',NULL);
INSERT INTO pa_nao_conformes VALUES(1,'PNC-1',100,0,0,0,0);
INSERT INTO expedicoes VALUES(1,'RM-1','2026-10-01','VENDA_DIRETA','Concluído',1);
INSERT INTO expedicao_itens VALUES(1,1,1,'CAIXA',1);
INSERT INTO cmv_camadas VALUES(1,'LEG-1','OP-1',50);
INSERT INTO cmv_eventos VALUES(1,'VENDA','2026-10-01','RM-1','LEG-1',5,5,0,NULL,'ROMANEIO','1');
INSERT INTO cmv_consumos VALUES(1,1,5);
INSERT INTO pnc_romaneios_descarte VALUES(1,'RD-1','CONFIRMADO');
INSERT INTO pnc_romaneio_descarte_itens VALUES(1,1,1,2,0,0,1000);
INSERT INTO pnc_movimentos_descarte VALUES(1,1,'SAIDA_DESCARTE_PNC',1,2,0,0,1000);
"""

INCONSISTENTE = CONSISTENTE + """
INSERT INTO pa_caixas VALUES(3,'CX-NEG','CAIXA',NULL,NULL,NULL,0,-3,10,'DISPONIVEL',NULL);
INSERT INTO pa_caixas VALUES(4,'PC-DIV','PACOTE',5,11,2,9,0,0,'DISPONIVEL',NULL);
INSERT INTO pa_caixas VALUES(5,'CX-RES','CAIXA',NULL,NULL,NULL,0,1,5,'RESERVADO',NULL);
INSERT INTO pa_nao_conformes VALUES(2,'PNC-NEG',-5,0,0,0,0);
INSERT INTO cmv_camadas VALUES(2,'LEG-2','OP-2',-1);
INSERT INTO expedicoes VALUES(2,'RM-2','2026-10-02','VENDA_DIRETA','Concluído',1);
INSERT INTO expedicoes VALUES(3,'RM-3','2026-10-03','VENDA_DIRETA','Aberto',1);
INSERT INTO expedicao_itens VALUES(2,2,1,'CAIXA',1);
INSERT INTO expedicao_itens VALUES(3,3,1,'CAIXA',1);
INSERT INTO cmv_eventos VALUES(2,'VENDA','2026-10-01','X','LEG-1',4,1,1,NULL,'ROMANEIO','9');
INSERT INTO cmv_eventos VALUES(3,'VENDA','2026-10-01','Y','LEG-1',4,4,0,NULL,'ROMANEIO','9');
INSERT INTO cmv_consumos VALUES(2,2,4);
INSERT INTO cmv_consumos VALUES(3,3,4);
INSERT INTO pnc_romaneios_descarte VALUES(2,'RD-2','CONFIRMADO');
INSERT INTO pnc_romaneio_descarte_itens VALUES(2,2,1,2,0,0,1000);
INSERT INTO pnc_movimentos_descarte VALUES(2,2,'SAIDA_DESCARTE_PNC',1,2,0,0,900);
"""


def _montar(tmp_path, monkeypatch, dados, schema=SCHEMA):
    caminho = tmp_path / "integridade.db"
    conn = sqlite3.connect(caminho)
    conn.executescript(schema + dados)
    conn.commit()
    conn.close()

    def conectar():
        c = sqlite3.connect(caminho)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(integridade, "conectar", conectar)
    monkeypatch.setattr(integridade, "DATABASE_URL", None)
    return caminho


def _hash(caminho):
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def _regras(ctx):
    return {(a["categoria"], a["origem"], a["registro_id"], a["regra"]) for a in ctx["achados"]}


def test_cenario_consistente_nao_gera_achados(tmp_path, monkeypatch):
    _montar(tmp_path, monkeypatch, CONSISTENTE)
    ctx = integridade.montar_diagnostico_integridade()
    assert ctx["achados"] == []
    assert ctx["consistente"] is True
    assert all(item["total"] == 0 for item in ctx["resumo"])
    assert ctx["nao_avaliadas"] == []


def test_cenario_inconsistente_identifica_cada_divergencia(tmp_path, monkeypatch):
    _montar(tmp_path, monkeypatch, INCONSISTENTE)
    ctx = integridade.montar_diagnostico_integridade()
    regras = _regras(ctx)
    assert ("saldo_negativo", "pa_caixas", 3, "pa_caixas.quantidade_bandejas < 0") in regras
    assert ("saldo_negativo", "pa_nao_conformes", 2, "pa_nao_conformes.saldo_bloqueado_g < 0") in regras
    assert ("saldo_negativo", "cmv_camadas", 2, "cmv_camadas.quantidade_disponivel < 0") in regras
    assert ("expedicao_duplicada", "expedicao_itens", 1, "caixa inteira em mais de um item ativo de romaneio") in regras
    assert ("expedicao_duplicada", "cmv_eventos", 2, "mais de um evento CMV ativo para a mesma origem") in regras
    assert ("divergencia_quantidade", "pa_caixas", 4, "pacotes reservados > pacotes em estoque") in regras
    assert ("divergencia_quantidade", "pa_caixas", 4, "quantidade_galinhas <> pacotes x galinhas_por_pacote") in regras
    assert ("divergencia_quantidade", "pa_caixas", 5, "caixa RESERVADO sem romaneio de reserva") in regras
    assert ("divergencia_quantidade", "pnc_romaneios_descarte", 2, "descarte: item.peso_g <> movimento.peso_g") in regras
    assert ("divergencia_quantidade", "cmv_eventos", 2, "evento CMV: com_custo + sem_custo <> quantidade") in regras
    assert ("venda_sem_cmv", "expedicoes", 2,
            "romaneio de Venda Direta concluido sem evento CMV de VENDA vinculado") in regras
    # Romaneio com CMV vinculado e romaneio ainda Aberto nao sao vendas sem CMV.
    vendas = {a["registro_id"] for a in ctx["achados"] if a["categoria"] == "venda_sem_cmv"}
    assert vendas == {2}
    for achado in ctx["achados"]:
        assert achado["origem"] and achado["registro_id"] is not None
        assert achado["comparados"] and achado["descricao"]
    item = next(a for a in ctx["achados"] if a["regra"].startswith("descarte: item.peso_g"))
    assert dict(item["comparados"]) == {
        "pnc_romaneio_descarte_itens.peso_g": 1000, "pnc_movimentos_descarte.peso_g": 900,
    }


def test_filtro_por_categoria(tmp_path, monkeypatch):
    _montar(tmp_path, monkeypatch, INCONSISTENTE)
    ctx = integridade.montar_diagnostico_integridade({"categoria": "venda_sem_cmv"})
    assert {a["categoria"] for a in ctx["achados"]} == {"venda_sem_cmv"}
    assert ctx["total_achados"] > len(ctx["achados"])


def test_execucao_nao_altera_banco(tmp_path, monkeypatch):
    caminho = _montar(tmp_path, monkeypatch, INCONSISTENTE)
    antes = _hash(caminho)
    integridade.montar_diagnostico_integridade()
    integridade.montar_diagnostico_integridade({"categoria": "saldo_negativo"})
    assert _hash(caminho) == antes


def test_conexao_somente_leitura_bloqueia_escrita(tmp_path, monkeypatch):
    caminho = _montar(tmp_path, monkeypatch, CONSISTENTE)
    antes = _hash(caminho)
    conn, cursor = integridade._abrir_somente_leitura()
    try:
        with pytest.raises(sqlite3.OperationalError):
            cursor.execute("UPDATE pa_caixas SET quantidade_bandejas = 0")
    finally:
        conn.close()
    assert _hash(caminho) == antes


def test_tabelas_ausentes_sao_informadas_sem_falhar(tmp_path, monkeypatch):
    _montar(tmp_path, monkeypatch, "", schema="CREATE TABLE pa_caixas(id INTEGER PRIMARY KEY);")
    ctx = integridade.montar_diagnostico_integridade()
    assert ctx["achados"] == []
    assert any("cmv_eventos" in item for item in ctx["nao_avaliadas"])


def test_rota_renderiza_relatorio(tmp_path, monkeypatch):
    from app import app

    _montar(tmp_path, monkeypatch, INCONSISTENTE)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = 1
        sess["nome"] = "Teste"
        sess["perfil"] = "admin"
    resposta = client.get("/relatorios/diagnostico/integridade-operacional")
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert "Integridade Operacional" in html
    assert "CX-NEG" in html and "RM-2" in html
    assert "pnc_movimentos_descarte.peso_g" in html
    filtrada = client.get("/relatorios/diagnostico/integridade-operacional?categoria=saldo_negativo")
    assert "RM-2" not in filtrada.get_data(as_text=True).split("Detalhamento")[1]


class _CursorPostgresFalso:
    """Registra o SQL emitido em modo PostgreSQL; sem servidor, valida somente dialeto."""

    def __init__(self, sqls):
        self.sqls = sqls
        self._linhas = []

    def execute(self, sql, parametros=()):
        self.sqls.append(sql)
        self._linhas = [{"column_name": "id"}] if "information_schema.columns" in sql else []
        if "information_schema.tables" in sql:
            self._linhas = [(1,)]

    def fetchone(self):
        return self._linhas[0] if self._linhas else None

    def fetchall(self):
        return list(self._linhas)


class _ConexaoPostgresFalsa:
    def __init__(self, sqls):
        self.cursor_ = _CursorPostgresFalso(sqls)

    def cursor(self):
        return self.cursor_

    def rollback(self):
        self.cursor_.sqls.append("ROLLBACK")

    def close(self):
        pass


def test_dialeto_postgresql_somente_leitura_e_sem_construcoes_sqlite(monkeypatch):
    sqls = []
    monkeypatch.setattr(integridade, "DATABASE_URL", "postgresql://teste")
    monkeypatch.setattr(integridade, "conectar", lambda: _ConexaoPostgresFalsa(sqls))
    monkeypatch.setattr(integridade, "q", lambda sql: sql.replace("?", "%s"))
    integridade.montar_diagnostico_integridade()
    assert sqls[0] == "SET TRANSACTION READ ONLY"
    assert sqls[-1] == "ROLLBACK"
    for sql in sqls[1:-1]:
        topo = sql.lstrip().upper()
        assert topo.startswith(("SELECT", "WITH")), sql
        assert "PRAGMA" not in topo and "SQLITE_MASTER" not in topo
        assert "?" not in sql  # placeholders convertidos para %s
        assert "%" not in sql.replace("%s", "")


SEM_VINCULO = """
INSERT INTO expedicoes VALUES(1,'RM-1','2026-09-01','VENDA_DIRETA','Concluído',1);
INSERT INTO expedicoes VALUES(2,'RM-2','2026-09-02','VENDA_DIRETA','Concluído',1);
INSERT INTO cmv_eventos VALUES(1,'VENDA','2026-09-05','RM-X','LEG-1',1,1,0,NULL,'RETRABALHO','7');
INSERT INTO cmv_consumos VALUES(1,1,1);
"""


def test_venda_sem_vinculo_rastreavel_e_nao_avaliavel_nao_achado(tmp_path, monkeypatch):
    caminho = _montar(tmp_path, monkeypatch, SEM_VINCULO)
    antes = _hash(caminho)
    ctx = integridade.montar_diagnostico_integridade()
    assert [a for a in ctx["achados"] if a["categoria"] == "venda_sem_cmv"] == []
    assert ctx["total_achados"] == 0 and ctx["consistente"] is True
    assert ctx["total_nao_avaliaveis"] == 2
    assert {n["registro_id"] for n in ctx["nao_avaliaveis"]} == {1, 2}
    assert all("vinculo" in n["justificativa"] for n in ctx["nao_avaliaveis"])
    assert _hash(caminho) == antes


def test_venda_anterior_ao_primeiro_vinculo_explicito_e_nao_avaliavel(tmp_path, monkeypatch):
    dados = """
    INSERT INTO expedicoes VALUES(1,'RM-1','2026-09-01','VENDA_DIRETA','Concluído',1);
    INSERT INTO expedicoes VALUES(2,'RM-2','2026-10-05','VENDA_DIRETA','Concluído',1);
    INSERT INTO expedicoes VALUES(3,'RM-3','2026-10-06','VENDA_DIRETA','Concluído',1);
    INSERT INTO cmv_eventos VALUES(1,'VENDA','2026-10-01','RM-3','LEG-1',1,1,0,NULL,'ROMANEIO','3');
    INSERT INTO cmv_consumos VALUES(1,1,1);
    """
    _montar(tmp_path, monkeypatch, dados)
    ctx = integridade.montar_diagnostico_integridade()
    assert {a["registro_id"] for a in ctx["achados"] if a["categoria"] == "venda_sem_cmv"} == {2}
    assert {n["registro_id"] for n in ctx["nao_avaliaveis"]} == {1}
    assert ctx["total_nao_avaliaveis"] == 1


def test_rota_exibe_nao_avaliaveis_separados(tmp_path, monkeypatch):
    from app import app

    _montar(tmp_path, monkeypatch, SEM_VINCULO)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = 1
        sess["nome"] = "Teste"
        sess["perfil"] = "gerencia"
    html = client.get("/relatorios/diagnostico/integridade-operacional").get_data(as_text=True)
    assert "Nao avaliaveis (2)" in html
    assert "Nenhuma inconsistencia encontrada" in html


def test_biblioteca_lista_diagnostico_e_perfis(tmp_path, monkeypatch):
    from app import app

    _montar(tmp_path, monkeypatch, CONSISTENTE)
    for perfil, esperado in (("pcp", 200), ("gerencia", 200), ("producao", 403)):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["usuario_id"] = 1
            sess["nome"] = "Teste"
            sess["perfil"] = perfil
        resposta = client.get("/relatorios/diagnostico/integridade-operacional")
        assert (resposta.status_code == 200) == (esperado == 200)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = 1
        sess["nome"] = "Teste"
        sess["perfil"] = "gerencia"
    assert "/relatorios/diagnostico/integridade-operacional" in client.get("/relatorios").get_data(as_text=True)
