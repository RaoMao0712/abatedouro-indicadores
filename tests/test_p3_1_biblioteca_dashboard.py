from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from modules.relatorios import gerencial
from modules.relatorios.services import (
    filtrar_relatorios_oficiais,
    listar_relatorios_oficiais,
    perfil_pode_acessar_relatorio,
)


def cliente(perfil="admin"):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(usuario_id=1, nome="P3.1", perfil=perfil)
    return client


def html_biblioteca(query="", perfil="admin"):
    return cliente(perfil).get(f"/relatorios{query}").get_data(as_text=True)


def contexto_dashboard_sem_banco(monkeypatch, args=None):
    monkeypatch.setattr(gerencial, "montar_comparativos_indicadores", lambda indicadores, filtros: [])
    monkeypatch.setattr(gerencial, "montar_tendencias_indicadores", lambda indicadores, filtros: [])
    monkeypatch.setattr(gerencial, "montar_posicao_atual_operacao", lambda: [])
    return gerencial.montar_contexto_dashboard_executivo(args or gerencial.ArgsDict())


def test_01_lista_por_modulo():
    contexto = filtrar_relatorios_oficiais({}, "admin")
    assert [grupo["modulo"] for grupo in contexto["grupos"]] == ["Financeiro", "Produção", "Estoque e Insumos", "Estoque e Expedição", "Gerencial"]


def test_02_busca_ignora_acentos():
    assert any(item["id"] == "producao-periodo" for item in filtrar_relatorios_oficiais({"q": "producao"}, "admin")["relatorios"])


def test_03_filtros_combinados():
    itens = filtrar_relatorios_oficiais({"modulo": "Produção", "tipo": "Movimentação", "nivel": "Operacional", "formato": "Excel"}, "admin")["relatorios"]
    assert itens and all(item["modulo"] == "Produção" and "Excel" in item["formatos"] for item in itens)


def test_04_permissao_por_modulo():
    assert perfil_pode_acessar_relatorio("qualidade", "Expedicao")
    assert not perfil_pode_acessar_relatorio("qualidade", "Financeiro")


def test_05_relatorio_oculto_sem_permissao():
    ids = {item["id"] for item in listar_relatorios_oficiais("qualidade")}
    assert "financeiro-dre-gerencial" not in ids and "expedicao-transferencias" in ids


def test_06_link_correto():
    assert '/relatorios/producao/rendimento' in html_biblioteca("?q=Rendimento")


def test_07_descricao_exibida():
    assert "Fonte única para localizar relatórios oficiais" in html_biblioteca()


def test_08_formato_disponivel():
    assert "Tela, Excel, Impressao" in html_biblioteca("?q=Rendimento")


def test_09_estado_vazio():
    assert "Nenhum relatório encontrado" in html_biblioteca("?q=termo-que-nao-existe")


def test_10_dashboard_producao():
    assert {"prod_peso", "prod_rendimento", "prod_perdas"}.issubset(gerencial.DASHBOARD_INICIAL_IDS)


def test_11_dashboard_estoque():
    assert "exp_caixas_camara" in gerencial.DASHBOARD_INICIAL_IDS


def test_12_dashboard_expedicao():
    assert gerencial.DASHBOARD_LINKS["exp_caixas_camara"][1]["slug"] == "estoque-camara-fria"


def test_13_dashboard_pnc():
    posicao = gerencial.montar_alertas_operacao([{"titulo": "PNC ativos", "valor": 2, "explicacao": "ativos", "endpoint": "produtos_nao_conformes", "args": {}}])
    assert posicao[0]["link_endpoint"] == "produtos_nao_conformes"


def test_14_dashboard_financeiro():
    assert {"fin_receita_liquida", "fin_resultado_operacional", "fin_saldo_caixa"}.issubset(gerencial.DASHBOARD_INICIAL_IDS)


def test_15_dashboard_na_expresso():
    assert "N/A" in (ROOT / "templates" / "dashboard_executivo.html").read_text(encoding="utf-8")


def test_16_alerta_objetivo_clicavel():
    alertas = gerencial.montar_alertas_operacao([{"titulo": "Pedidos pendentes", "valor": 1, "explicacao": "pendentes", "endpoint": "pedidos_venda", "args": {}}])
    assert alertas and alertas[0]["link_endpoint"] == "pedidos_venda"


def test_17_dashboard_permissao():
    assert cliente("qualidade").get("/relatorios/gerencial/dashboard-executivo").status_code == 302
    assert cliente("gerencia").get("/relatorios/gerencial/dashboard-executivo").status_code == 200


def test_18_dashboard_periodos(monkeypatch):
    contexto = contexto_dashboard_sem_banco(monkeypatch, gerencial.ArgsDict(periodo="mes_anterior"))
    assert contexto["filtros"]["periodo"] == "mes_anterior" and len(contexto["opcoes"]["periodos"]) == 4


def test_19_dashboard_posicao_atual_separada(monkeypatch):
    contexto = contexto_dashboard_sem_banco(monkeypatch)
    assert "itens_posicao" in contexto and "itens_periodo" in contexto and "posicao_operacao" in contexto


class CursorContado:
    def __init__(self): self.execucoes = 0
    def execute(self, sql): self.execucoes += 1
    def fetchone(self): return {"ops_ativas": 1, "pnc_ativos": 2, "pedidos_pendentes": 3}


class ConexaoContada:
    def __init__(self): self.cursor_obj = CursorContado()
    def cursor(self): return self.cursor_obj
    def close(self): pass


def test_20_sem_dupla_contagem(monkeypatch):
    conn = ConexaoContada(); monkeypatch.setattr(gerencial, "conectar", lambda: conn)
    valores = gerencial.montar_posicao_atual_operacao()
    assert [item["valor"] for item in valores] == [1, 2, 3]


def test_21_quantidade_de_queries_posicao(monkeypatch):
    conn = ConexaoContada(); monkeypatch.setattr(gerencial, "conectar", lambda: conn)
    gerencial.montar_posicao_atual_operacao()
    assert conn.cursor_obj.execucoes == 1


def test_22_carregamento_dashboard(monkeypatch):
    contexto_dashboard_sem_banco(monkeypatch)
    resposta = cliente("admin").get("/relatorios/gerencial/dashboard-executivo")
    assert resposta.status_code == 200


def test_23_biblioteca_com_catalogo_completo():
    assert len(listar_relatorios_oficiais("admin")) == 41


def test_24_biblioteca_sem_n_mais_um():
    contexto = filtrar_relatorios_oficiais({}, "admin")
    assert contexto["total_catalogo"] == 41 and contexto["total_filtrado"] == 41


def test_25_breadcrumb():
    assert "Navegação estrutural" in html_biblioteca()


def test_26_voltar():
    assert "Voltar à biblioteca" in (ROOT / "templates" / "dashboard_executivo.html").read_text(encoding="utf-8")


def test_27_link_profundo_preservado():
    resposta = cliente().get("/relatorios/producao/rendimento?data_inicio=2026-08-01&data_fim=2026-08-31")
    assert resposta.status_code == 200


def test_28_filtros_preservados():
    html = html_biblioteca("?modulo=Produ%C3%A7%C3%A3o&formato=Excel")
    assert 'value="Produção" selected' in html and 'value="Excel" selected' in html


def test_29_rota_antiga_preservada():
    resposta = cliente().get("/relatorio-rendimento?data_inicio=2026-08-01&data_fim=2026-08-31", follow_redirects=False)
    assert resposta.status_code == 302 and "/relatorios/producao/rendimento" in resposta.location
