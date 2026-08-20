from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import sqlite3

import pytest
from flask import Flask
from pypdf import PdfReader

from modules.expedicao import consolidado_estoque as consolidado
from modules.expedicao import routes
from modules.expedicao.relatorio_estoque import gerar_relatorio_estoque_pdf


@pytest.fixture()
def banco_consolidado(tmp_path, monkeypatch):
    caminho = tmp_path / "consolidado.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(consolidado, "conectar", conectar)
    monkeypatch.setattr(consolidado, "criar_tabelas_estoque_confiavel", lambda: None)
    monkeypatch.setattr(consolidado, "garantir_schema", lambda **_: None)

    conn = conectar()
    conn.executescript("""
        CREATE TABLE skus (
            id INTEGER PRIMARY KEY, codigo TEXT, nome TEXT,
            unidade_venda TEXT, ativo TEXT, excluido_em TEXT
        );
        INSERT INTO skus VALUES
            (1, 'LEG-1', 'Galinha Cortada', 'CAIXA', 'Sim', NULL),
            (2, 'LEG-2', 'Galinha Inteira', 'PACOTE', 'Sim', NULL);

        CREATE TABLE pa_caixas (
            id INTEGER PRIMARY KEY, codigo_caixa TEXT, sku TEXT,
            apresentacao TEXT, unidade_estoque TEXT, galinhas_por_pacote INTEGER,
            condicao TEXT, disponibilidade TEXT, status TEXT,
            estoque_operacional INTEGER, quantidade_bandejas INTEGER,
            peso_liquido REAL, quantidade_pacotes INTEGER,
            quantidade_galinhas INTEGER, quantidade_pacotes_reservados INTEGER
        );
        INSERT INTO pa_caixas VALUES
            (1, 'C-1', 'LEG-1', 'Congelada', 'CAIXA', NULL, 'CONFORME', 'DISPONIVEL', 'Em estoque', 1, 12, 10.111, 0, 0, 0),
            (2, 'C-2', 'Galinha Cortada', 'Congelada', 'CAIXA', NULL, 'CONFORME', 'RESERVADO', 'Em estoque', 1, 12, 5.555, 0, 0, 0),
            (3, 'C-3', 'LEG-1', 'Congelada', 'CAIXA', NULL, 'NAO_CONFORME', 'BLOQUEADO', 'Em estoque', 1, 12, 7.777, 0, 0, 0),
            (4, 'C-4', 'LEG-1', 'Congelada', 'CAIXA', NULL, 'NAO_CONFORME', 'REPROCESSAMENTO', 'Em estoque', 1, 12, 8.888, 0, 0, 0),
            (5, 'C-5', 'LEG-1', 'Congelada', 'CAIXA', NULL, 'CONFORME', 'AGUARDANDO_LIBERACAO', 'Em estoque', 1, 12, 9.999, 0, 0, 0),
            (6, 'C-X', 'LEG-1', 'Congelada', 'CAIXA', NULL, 'CONFORME', 'EXPEDIDO', 'Expedido', 1, 12, 99.999, 0, 0, 0),
            (7, 'GI-1', 'LEG-2', 'Pacote com 1 galinha inteira', 'PACOTE', 1, 'CONFORME', 'DISPONIVEL', 'Em estoque', 1, 100, NULL, 100, 100, 20),
            (8, 'GI-2', 'Galinha Inteira', 'Pacote com 2 galinhas inteiras', 'PACOTE', 2, 'CONFORME', 'RESERVADO', 'Em estoque', 1, 100, NULL, 50, 100, 10),
            (9, 'C-6', 'LEG-1', 'Congelada', 'CAIXA', NULL, 'NAO_CONFORME', 'BLOQUEADO', 'Em estoque', 1, 12, 4.444, 0, 0, 0),
            (10, 'C-7', 'Galinha Cortada', 'Congelada', 'CAIXA', NULL, 'CONFORME', 'DISPONIVEL', 'Em estoque', 1, 12, 10.222, 0, 0, 0),
            (11, 'C-C', 'LEG-1', 'Congelada', 'CAIXA', NULL, 'CONFORME', 'DISPONIVEL', 'CANCELADO', 1, 12, 90.000, 0, 0, 0),
            (12, 'C-Z', 'LEG-1', 'Congelada', 'CAIXA', NULL, 'CONFORME', 'DISPONIVEL', 'Em estoque', 1, 0, 0, 0, 0, 0);

        CREATE TABLE pa_nao_conformes (
            id INTEGER PRIMARY KEY, tipo_registro TEXT, caixa_id INTEGER, condicao_inicial TEXT,
            caixas_bloqueadas INTEGER, bandejas_bloqueadas INTEGER,
            saldo_bloqueado_g INTEGER, saldo_pendente_g INTEGER,
            saldo_operacional_g INTEGER, saldo_reservado_operacional_g INTEGER
        );
        INSERT INTO pa_nao_conformes VALUES
            (10, 'INVENTARIO_LEGADO_AGREGADO', NULL, 'NAO_CONFORME', 10, 120, 100000, 20000, 30000, 10000),
            (11, 'INVENTARIO_LEGADO_AGREGADO', NULL, 'CONFORME_AGUARDANDO_LIBERACAO', 3, 36, 30000, 0, 0, 0),
            (12, 'CAIXA_RASTREADA', 9, 'NAO_CONFORME', 0, 0, 0, 0, 0, 0);

        CREATE TABLE pa_nao_conforme_solicitacoes (
            id INTEGER PRIMARY KEY, pa_nao_conforme_id INTEGER,
            peso_g INTEGER, caixas INTEGER, bandejas INTEGER, status TEXT
        );
        INSERT INTO pa_nao_conforme_solicitacoes VALUES
            (1, 10, 20000, 2, 24, 'AGUARDANDO_VALIDACAO_GERENCIA'),
            (2, 10, 40000, 4, 48, 'APROVADA'),
            (3, 12, 4444, 1, 12, 'AGUARDANDO_VALIDACAO_GERENCIA');

        CREATE TABLE expedicoes (id INTEGER PRIMARY KEY, status TEXT);
        INSERT INTO expedicoes VALUES (1, 'Aberto'), (2, 'Concluído');
        CREATE TABLE expedicao_itens (
            id INTEGER PRIMARY KEY, expedicao_id INTEGER,
            pa_nao_conforme_id INTEGER, quantidade_caixas INTEGER,
            quantidade_bandejas INTEGER
        );
        INSERT INTO expedicao_itens VALUES
            (1, 1, 10, 1, 12),
            (2, 2, 10, 1, 12);

        CREATE TABLE estoque_eventos (id INTEGER PRIMARY KEY, acao TEXT);
        INSERT INTO estoque_eventos VALUES (1, 'BASELINE');
    """)
    conn.commit()
    conn.close()
    return conectar


def _por_chave(resultado):
    return {grupo["chave"]: grupo for grupo in resultado["grupos"]}


def _fotografia(conectar):
    conn = conectar()
    try:
        return {
            tabela: [tuple(linha) for linha in conn.execute(f"SELECT * FROM {tabela} ORDER BY id")]
            for tabela in (
                "pa_caixas", "pa_nao_conformes", "pa_nao_conforme_solicitacoes",
                "expedicoes", "expedicao_itens", "estoque_eventos",
            )
        }
    finally:
        conn.close()


def test_consolida_fontes_sem_dupla_contagem_e_preserva_precisao(banco_consolidado):
    antes = _fotografia(banco_consolidado)
    resultado = consolidado.consolidar_estoque_camara(incluir_nao_conforme=True)
    grupos = _por_chave(resultado)

    assert list(grupos)[:3] == [
        "galinha_cortada", "galinha_inteira_v1", "galinha_inteira_v2",
    ]
    cortada = grupos["galinha_cortada"]
    assert cortada["situacoes"]["disponivel"]["quantidades"] == {
        "caixas": 4, "bandejas": 48, "peso_kg": Decimal("50.333"),
    }
    assert cortada["situacoes"]["reservado"]["quantidades"] == {
        "caixas": 2, "bandejas": 24, "peso_kg": Decimal("15.555"),
    }
    assert cortada["situacoes"]["nao_conforme_bloqueado"]["quantidades"] == {
        "caixas": 9, "bandejas": 108, "peso_kg": Decimal("87.777"),
    }
    assert cortada["situacoes"]["reprocessamento"]["quantidades"]["peso_kg"] == Decimal("8.888")
    assert cortada["situacoes"]["aguardando_liberacao"]["quantidades"] == {
            "caixas": 7, "bandejas": 84, "peso_kg": Decimal("64.443"),
        }
    assert cortada["total_fisico"]["peso_kg"] == Decimal("226.996")

    v1 = grupos["galinha_inteira_v1"]
    assert v1["situacoes"]["disponivel"]["quantidades"] == {"galinhas": 80, "pacotes": 80}
    assert v1["situacoes"]["reservado"]["quantidades"] == {"galinhas": 20, "pacotes": 20}
    v2 = grupos["galinha_inteira_v2"]
    assert v2["situacoes"]["disponivel"]["quantidades"] == {"galinhas": 80, "pacotes": 40}
    assert v2["situacoes"]["reservado"]["quantidades"] == {"galinhas": 20, "pacotes": 10}
    assert _fotografia(banco_consolidado) == antes


def test_opcao_sem_nao_conforme_omite_saldos_bloqueados(banco_consolidado):
    resultado = consolidado.consolidar_estoque_camara(incluir_nao_conforme=False)
    for grupo in resultado["grupos"]:
        assert grupo["total_bloqueado"] == {
            unidade: Decimal("0") if unidade == "peso_kg" else 0
            for unidade in grupo["unidades"]
        }
        assert grupo["total_fisico"] == grupo["total_conforme"]


def test_pdf_usa_mesma_fotografia_e_separa_nao_conformes(banco_consolidado):
    antes = _fotografia(banco_consolidado)
    resultado = consolidado.consolidar_estoque_camara(incluir_nao_conforme=True)
    pdf = gerar_relatorio_estoque_pdf(resultado, usuario="Teste Qualidade", logo="")
    leitor = PdfReader(__import__("io").BytesIO(pdf))
    texto = "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)

    assert pdf.startswith(b"%PDF")
    assert "POSIÇÃO CONSOLIDADA DO ESTOQUE DA CÂMARA" in texto
    assert "Estoque não conforme e bloqueado" in texto
    assert "Galinha Cortada" in texto
    assert "Galinha Inteira" in texto
    assert "Teste Qualidade" in texto
    assert "50,333" in texto
    assert "15,555" in texto
    resultado_sem_nc = consolidado.consolidar_estoque_camara(incluir_nao_conforme=False)
    pdf_sem_nc = gerar_relatorio_estoque_pdf(resultado_sem_nc, usuario="Teste Qualidade", logo="")
    texto_sem_nc = "\n".join(
        pagina.extract_text() or "" for pagina in PdfReader(__import__("io").BytesIO(pdf_sem_nc)).pages
    )
    assert "Estoque não conforme e bloqueado" not in texto_sem_nc
    assert _fotografia(banco_consolidado) == antes


def test_tela_renderiza_grupos_e_modal_com_opcao_desmarcada(monkeypatch):
    app = Flask(__name__, template_folder="../templates")
    app.secret_key = "teste"
    app.jinja_env.filters["br_numero"] = lambda valor, casas=2: f"{float(valor):.{int(casas)}f}"
    app.url_build_error_handlers.append(lambda error, endpoint, values: "#")
    routes.register_expedicao_routes(app)

    fotografia = {
        "gerado_em_formatado": "20/08/2026 às 14:00",
        "fuso_horario": "America/Manaus",
        "grupos": [
            {
                "chave": chave, "produto": produto, "apresentacao": apresentacao,
                "sku_codigo": codigo, "classificado": True, "unidades": unidades,
                "situacoes": {
                    situacao: {"rotulo": rotulo, "quantidades": {u: 0 for u in unidades}}
                    for situacao, rotulo in (
                        ("disponivel", "Disponível para expedição"), ("reservado", "Reservado"),
                        ("nao_conforme_bloqueado", "Não conforme bloqueado"),
                        ("reprocessamento", "Em reprocessamento"),
                        ("aguardando_liberacao", "Aguardando liberação"),
                    )
                },
                "total_fisico": {u: 0 for u in unidades},
            }
            for chave, produto, apresentacao, codigo, unidades in (
                ("galinha_cortada", "Galinha Cortada", "Congelada", "LEG-1", ["caixas", "bandejas", "peso_kg"]),
                ("galinha_inteira_v1", "Galinha Inteira", "Pacote com 1 ave", "LEG-2", ["galinhas", "pacotes"]),
                ("galinha_inteira_v2", "Galinha Inteira", "Pacote com 2 aves", "LEG-2", ["galinhas", "pacotes"]),
            )
        ],
        "alertas_tecnicos": [],
    }
    monkeypatch.setattr(routes, "buscar_estoque_operacional", lambda: ([], {chave: 0 for chave in (
        "unidades_fisicas", "peso_fisico", "unidades_disponiveis", "peso_disponivel",
        "unidades_reservadas", "peso_reservado", "unidades_bloqueadas", "peso_bloqueado",
        "unidades_reprocessamento", "peso_reprocessamento", "unidades_outras_condicoes",
        "peso_outras_condicoes",
    )}))
    monkeypatch.setattr(routes, "saldos_legados_operacionais", lambda: [])
    monkeypatch.setattr(routes, "inventario_legado_fisico", lambda: [])
    monkeypatch.setattr(routes, "resumo_inventario_legado_fisico", lambda _: {"peso_fisico_g": 0, "bandejas_fisicas": 0})
    monkeypatch.setattr(routes, "integrar_resumo_inventario_legado", lambda resumo, _: {**resumo, "peso_legado_disponivel": 0, "bandejas_legado": 0})
    monkeypatch.setattr(routes, "obter_marco_zero", lambda: None)
    chamadas = []
    def fotografia_por_opcao(**opcoes):
        chamadas.append(opcoes["incluir_nao_conforme"])
        return fotografia
    monkeypatch.setattr(routes, "consolidar_estoque_camara", fotografia_por_opcao)
    monkeypatch.setattr(routes, "gerar_relatorio_estoque_pdf", lambda *_args, **_kwargs: b"%PDF-1.4\n%%EOF")

    with app.test_client() as cliente:
        with cliente.session_transaction() as sessao:
            sessao.update(usuario_id=1, perfil="qualidade", nome="Qualidade")
        resposta = cliente.get("/expedicao/estoque")
        pdf_padrao = cliente.get("/expedicao/estoque/relatorio-consolidado.pdf")
        pdf_com_nc = cliente.get("/expedicao/estoque/relatorio-consolidado.pdf?incluir_nao_conforme=1")
        with cliente.session_transaction() as sessao:
            sessao["perfil"] = "producao"
        pdf_sem_permissao = cliente.get("/expedicao/estoque/relatorio-consolidado.pdf")

    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert html.count('data-grupo-estoque="') == 3
    assert "Consolidado por Produto" in html
    assert 'name="incluir_nao_conforme" value="1"' in html
    assert 'name="incluir_nao_conforme" value="1" checked' not in html
    assert "Gerar relatório consolidado" in html
    assert "não aplicável" not in html.lower()
    assert pdf_padrao.status_code == pdf_com_nc.status_code == 200
    assert pdf_padrao.mimetype == pdf_com_nc.mimetype == "application/pdf"
    assert pdf_padrao.headers["Cache-Control"] == "no-store, private"
    assert pdf_sem_permissao.status_code == 302
    assert chamadas == [True, False, True]
