import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, render_template_string, session

from modules.producao import correcoes_administrativas as correcoes
from modules.producao import routes as producao_routes
from modules.producao.services import calcular_resumo_op


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "correcao-op.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(correcoes, "conectar", conectar)
    monkeypatch.setattr(correcoes, "DATABASE_URL", None)

    conn = conectar()
    conn.executescript("""
        CREATE TABLE ordens_producao (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            fornecedor TEXT NOT NULL,
            quantidade_aves INTEGER NOT NULL,
            mortes_antes_pendura INTEGER DEFAULT 0,
            peso_vivo REAL NOT NULL,
            peso_medio REAL NOT NULL,
            observacoes TEXT,
            status TEXT NOT NULL,
            sku TEXT
        );
        INSERT INTO ordens_producao VALUES
            (1, '2026-07-28', 'Fornecedor', 100, 0, 1000, 10, 'histórica', 'Encerrada', 'Galinha Cortada'),
            (2, '2026-07-28', 'Fornecedor', 100, 0, 900, 9, '', 'Encerrada', 'Galinha Inteira'),
            (3, '2026-07-28', 'Fornecedor', 100, 0, 800, 8, '', 'Aberta', 'Galinha Cortada'),
            (4, '2026-07-28', 'Fornecedor', 100, 0, 700, 7, '', 'Cancelada', 'Galinha Cortada'),
            (5, '2026-07-28', 'Fornecedor', 100, 0, 912, 9.12, '', 'Encerrada', 'Galinha Cortada');

        CREATE TABLE estoque_pi (id INTEGER PRIMARY KEY, op_id INTEGER, quantidade REAL);
        CREATE TABLE pa_caixas (id INTEGER PRIMARY KEY, op_id INTEGER, peso REAL);
        CREATE TABLE romaneios (id INTEGER PRIMARY KEY, total REAL);
        CREATE TABLE expedicoes (id INTEGER PRIMARY KEY, peso REAL);
        CREATE TABLE dre_resultados (id INTEGER PRIMARY KEY, valor REAL);
        CREATE TABLE cmv_resultados (id INTEGER PRIMARY KEY, valor REAL);
        CREATE TABLE movimentacoes_financeiras (id INTEGER PRIMARY KEY, valor REAL);
        CREATE TABLE estoque_almoxarifado (id INTEGER PRIMARY KEY, saldo REAL);

        INSERT INTO estoque_pi VALUES (1, 1, 77);
        INSERT INTO pa_caixas VALUES (1, 1, 88);
        INSERT INTO pa_caixas VALUES (2, 5, 91.2);
        INSERT INTO romaneios VALUES (1, 99);
        INSERT INTO expedicoes VALUES (1, 111);
        INSERT INTO dre_resultados VALUES (1, 222);
        INSERT INTO cmv_resultados VALUES (1, 333);
        INSERT INTO movimentacoes_financeiras VALUES (1, 444);
        INSERT INTO estoque_almoxarifado VALUES (1, 555);
    """)
    conn.commit()
    conn.close()

    correcoes.criar_tabelas_correcoes_administrativas_op()
    return conectar


def _usuario(nome="Gestora"):
    return {"id": 17, "nome": nome}


def _fotografia_operacional(conectar):
    conn = conectar()
    fotografia = {}
    for tabela in (
        "estoque_pi",
        "pa_caixas",
        "romaneios",
        "expedicoes",
        "dre_resultados",
        "cmv_resultados",
        "movimentacoes_financeiras",
        "estoque_almoxarifado",
    ):
        fotografia[tabela] = [tuple(linha) for linha in conn.execute(f"SELECT * FROM {tabela}")]
    conn.close()
    return fotografia


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("900,75", 900.75), ("900.75", 900.75), ("1.234,56", 1234.56)],
)
def test_parser_aceita_decimal_pt_br_e_padrao_atual(entrada, esperado):
    assert correcoes._parse_peso_decimal(entrada) == esperado


def test_gerencia_corrige_peso_recalcula_indicadores_sem_reabrir_ou_afetar_operacao(banco):
    antes = _fotografia_operacional(banco)

    resultado = correcoes.corrigir_peso_entrada_op(
        1,
        "800",
        "Correção da balança de recebimento",
        "Conferido no ticket físico",
        usuario=_usuario(),
        perfil="gerencia",
        origem="10.0.0.7",
    )

    conn = banco()
    op = conn.execute("SELECT * FROM ordens_producao WHERE id = 1").fetchone()
    auditoria = conn.execute("SELECT * FROM correcoes_administrativas_op WHERE op_id = 1").fetchone()
    conn.close()

    assert resultado == {"op_id": 1, "valor_anterior": 1000.0, "novo_valor": 800.0}
    assert op["peso_vivo"] == 800
    assert op["status"] == "Encerrada"
    assert op["peso_medio"] == 10
    assert op["quantidade_aves"] == 100
    assert op["sku"] == "Galinha Cortada"
    assert op["observacoes"] == "histórica"

    assert auditoria["numero_op"] == 1
    assert auditoria["usuario_nome"] == "Gestora"
    assert auditoria["perfil"] == "gerencia"
    assert auditoria["campo_alterado"] == "peso_vivo"
    assert auditoria["valor_anterior"] == 1000
    assert auditoria["novo_valor"] == 800
    assert auditoria["motivo"] == "Correção da balança de recebimento"
    assert auditoria["observacoes"] == "Conferido no ticket físico"
    assert auditoria["origem_sessao"] == "10.0.0.7"

    resumo = calcular_resumo_op(
        op,
        [{"quantidade": 400, "unidade": "kg"}],
        [{"quantidade": 40, "unidade": "kg", "motivo": "Perda"}],
    )
    assert resumo["rendimento"] == 50
    assert resumo["perdas_percentual"] == 5
    assert _fotografia_operacional(banco) == antes


def test_administrador_pode_corrigir_e_historico_preserva_multiplas_correcoes(banco):
    for valor, motivo in ((850, "Primeira conferência"), (825, "Conferência definitiva")):
        correcoes.corrigir_peso_entrada_op(
            2,
            valor,
            motivo,
            "",
            usuario=_usuario("Administrador"),
            perfil="admin",
            origem="127.0.0.1",
        )

    historico = correcoes.buscar_correcoes_op(2)
    assert len(historico) == 2
    assert [item["novo_valor"] for item in historico] == [825, 850]
    assert [item["valor_anterior"] for item in historico] == [850, 900]


def test_op_de_912_com_caixa_pa_aceita_decimal_pt_br_sem_alterar_caixa(banco):
    antes = _fotografia_operacional(banco)

    correcoes.corrigir_peso_entrada_op(
        5,
        "900,75",
        "Conferência documental",
        "",
        usuario=_usuario(),
        perfil="gerencia",
        origem="local",
    )

    conn = banco()
    op = conn.execute("SELECT peso_vivo, status FROM ordens_producao WHERE id = 5").fetchone()
    auditoria = conn.execute(
        "SELECT valor_anterior, novo_valor FROM correcoes_administrativas_op WHERE op_id = 5"
    ).fetchone()
    conn.close()
    assert tuple(op) == (900.75, "Encerrada")
    assert tuple(auditoria) == (912, 900.75)
    assert _fotografia_operacional(banco) == antes


@pytest.mark.parametrize("perfil", ["producao", "qualidade", "pcp"])
def test_perfis_operacionais_nao_podem_corrigir_e_tentativa_e_auditada(banco, perfil):
    with pytest.raises(ValueError, match="Perfil sem permissão"):
        correcoes.corrigir_peso_entrada_op(
            1,
            950,
            "Tentativa",
            "",
            usuario=_usuario(perfil),
            perfil=perfil,
            origem="10.0.0.8",
        )

    conn = banco()
    op = conn.execute("SELECT peso_vivo, status FROM ordens_producao WHERE id = 1").fetchone()
    tentativa = conn.execute(
        "SELECT * FROM tentativas_correcao_administrativa_op ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert tuple(op) == (1000, "Encerrada")
    assert tentativa["perfil"] == perfil
    assert "sem permissão" in tentativa["motivo_negacao"]


def test_motivo_e_obrigatorio_e_tentativa_fica_registrada(banco):
    with pytest.raises(ValueError, match="motivo da correção é obrigatório"):
        correcoes.corrigir_peso_entrada_op(
            1, 950, "   ", "", usuario=_usuario(), perfil="gerencia", origem="local"
        )

    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM correcoes_administrativas_op").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tentativas_correcao_administrativa_op").fetchone()[0] == 1
    assert conn.execute("SELECT peso_vivo FROM ordens_producao WHERE id = 1").fetchone()[0] == 1000
    conn.close()


@pytest.mark.parametrize("valor", [None, "", "0", "-1", "texto", "NaN", "Infinity"])
def test_peso_vazio_zero_negativo_ou_invalido_e_rejeitado(banco, valor):
    with pytest.raises(ValueError, match="deve ser maior que zero"):
        correcoes.corrigir_peso_entrada_op(
            1, valor, "Ajuste", "", usuario=_usuario(), perfil="gerencia", origem="local"
        )

    conn = banco()
    assert conn.execute("SELECT peso_vivo FROM ordens_producao WHERE id = 1").fetchone()[0] == 1000
    assert conn.execute("SELECT COUNT(*) FROM correcoes_administrativas_op").fetchone()[0] == 0
    conn.close()


def test_peso_igual_ao_atual_e_rejeitado(banco):
    with pytest.raises(ValueError, match="deve ser diferente"):
        correcoes.corrigir_peso_entrada_op(
            5, "912,00", "Ajuste", "", usuario=_usuario(), perfil="admin", origem="local"
        )

    conn = banco()
    assert conn.execute("SELECT peso_vivo, status FROM ordens_producao WHERE id = 5").fetchone()[:] == (
        912,
        "Encerrada",
    )
    conn.close()


@pytest.mark.parametrize(
    ("op_id", "mensagem"),
    [
        (3, "Somente OP encerrada"),
        (4, "OP cancelada"),
    ],
)
def test_estado_incompativel_bloqueia_correcao(banco, op_id, mensagem):
    with pytest.raises(ValueError, match=mensagem):
        correcoes.corrigir_peso_entrada_op(
            op_id, 650, "Ajuste", "", usuario=_usuario(), perfil="gerencia", origem="local"
        )


def test_bloqueio_administrativo_impede_correcao(banco):
    conn = banco()
    conn.execute("UPDATE ordens_producao SET bloqueada_administrativamente = 1 WHERE id = 1")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="bloqueada administrativamente"):
        correcoes.corrigir_peso_entrada_op(
            1, 950, "Ajuste", "", usuario=_usuario(), perfil="admin", origem="local"
        )


class _ColetorInput(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = {}

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "input" and atributos.get("id"):
            self.inputs[atributos["id"]] = atributos


def _fragmento_modal():
    template = (
        Path(__file__).resolve().parents[1] / "templates" / "consultar_op.html"
    ).read_text(encoding="utf-8")
    inicio = template.index('{% if op.status == "Encerrada" and session.get("perfil")')
    fim = template.index("{% endif %}", inicio) + len("{% endif %}")
    return template, template[inicio:fim]


def test_campo_peso_corrigido_e_editavel_e_modal_mantem_ux_obrigatoria():
    template, _ = _fragmento_modal()
    coletor = _ColetorInput()
    coletor.feed(template)
    campo = coletor.inputs["peso-entrada-corrigido"]

    assert "disabled" not in campo
    assert "readonly" not in campo
    assert "aria-disabled" not in campo
    assert campo["type"] == "text"
    assert campo["inputmode"] == "decimal"
    assert "required" in campo
    assert campo["autocomplete"] == "off"
    assert 'value="' not in template[template.index('id="peso-entrada-corrigido"'):][:400]
    assert "Corrigir OP" in template
    assert "Peso de Entrada Corrigido" in template
    assert "Motivo da Correção" in template
    assert "Todas as alterações" in template
    assert "Correções Administrativas" in template
    assert 'class="campo-obrigatorio"' in template
    assert '<p class="alerta-correcao">' in template


@pytest.mark.parametrize("perfil", ["admin", "gerencia"])
def test_admin_e_gerencia_visualizam_campo_editavel(perfil):
    _, fragmento = _fragmento_modal()
    app = Flask(__name__)
    app.secret_key = "teste"

    @app.post("/op/<int:op_id>/corrigir-peso-entrada", endpoint="corrigir_peso_entrada")
    def rota_ficticia(op_id):
        return str(op_id)

    with app.test_request_context("/"):
        session["perfil"] = perfil
        html = render_template_string(
            fragmento,
            op=SimpleNamespace(
                id=5,
                status="Encerrada",
                sku="Galinha Cortada",
                data="2026-07-28",
                peso_vivo=912,
            ),
        )

    coletor = _ColetorInput()
    coletor.feed(html)
    assert "peso-entrada-corrigido" in coletor.inputs
    assert "disabled" not in coletor.inputs["peso-entrada-corrigido"]
    assert "readonly" not in coletor.inputs["peso-entrada-corrigido"]


def _app_rotas(monkeypatch, *, possui_caixa=True):
    app = Flask(__name__)
    app.secret_key = "teste"
    producao_routes.register_producao_routes(
        app,
        {
            "op_possui_caixa_pa": lambda op_id: possui_caixa,
            "remover_movimentacoes_estoque_pi_por_op": lambda op_id: None,
        },
    )
    return app


def test_rota_envia_novo_peso_ao_backend_mesmo_com_caixa_pa(monkeypatch):
    recebido = {}

    def corrigir(*args, **kwargs):
        recebido["args"] = args
        recebido["kwargs"] = kwargs

    monkeypatch.setattr(producao_routes, "corrigir_peso_entrada_op", corrigir)
    app = _app_rotas(monkeypatch, possui_caixa=True)
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(usuario_id=1, nome="Admin", perfil="admin")

    resposta = cliente.post(
        "/op/5/corrigir-peso-entrada",
        data={
            "peso_entrada_corrigido": "900,75",
            "motivo": "Conferência",
            "observacoes": "",
        },
    )

    assert resposta.status_code == 302
    assert recebido["args"][:4] == (5, "900,75", "Conferência", "")


def test_caixa_pa_continua_bloqueando_reabertura(monkeypatch):
    monkeypatch.setattr(
        producao_routes,
        "buscar_op_por_id",
        lambda op_id: {"id": op_id, "status": "Encerrada"},
    )
    app = _app_rotas(monkeypatch, possui_caixa=True)
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(usuario_id=1, nome="Admin", perfil="admin")

    resposta = cliente.post("/op/5/reabrir")
    with cliente.session_transaction() as sessao:
        mensagens = [mensagem for _, mensagem in sessao.get("_flashes", [])]

    assert resposta.status_code == 302
    assert any("Reabertura bloqueada" in mensagem for mensagem in mensagens)
