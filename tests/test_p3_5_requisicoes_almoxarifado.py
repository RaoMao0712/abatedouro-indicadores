import sqlite3

import pytest
from flask import Flask

from modules.almoxarifado import requisicoes
from modules.almoxarifado import services as estoque
from modules.almoxarifado import routes
from modules.parceiros import services as parceiros


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "p35.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    for modulo in (requisicoes, estoque, parceiros):
        monkeypatch.setattr(modulo, "DATABASE_URL", None)
        monkeypatch.setattr(modulo, "conectar", conectar)
    estoque.criar_tabelas_estoque_almoxarifado()
    parceiros.criar_tabelas_parceiros()
    requisicoes.criar_tabelas_requisicoes_almoxarifado()
    conn = conectar()
    conn.execute("""INSERT INTO parceiros
        (uuid,tipo_pessoa,razao_social,status,criado_por,atualizado_por,criado_em,atualizado_em)
        VALUES ('p-1','PF','Ana Operadora','Ativo','teste','teste','2026-09-10','2026-09-10')""")
    conn.execute("""INSERT INTO parceiro_papeis
        (parceiro_id,papel,ativo,adicionado_por,adicionado_em)
        VALUES (1,'COLABORADOR_CLT',1,'teste','2026-09-10')""")
    conn.executemany("""INSERT INTO almoxarifado_insumos
        (descricao,categoria,unidade,ativo,origem_baixa) VALUES (?,?,?,'Sim',?)""", [
        ("Luva", "EPI", "Par", "REQUISICAO_ALMOXARIFADO"),
        ("Bandeja", "Embalagem", "Un", "ORDEM_PRODUCAO"),
    ])
    conn.executemany("""INSERT INTO almoxarifado_lotes
        (insumo_id,data_entrada,lote,quantidade_inicial,quantidade_atual,valor_unitario,valor_total,status,versao)
        VALUES (?,?,?,?,?,?,?,?,0)""", [
        (1, "2026-09-01", "L-ANTIGO", 6, 6, 2, 12, "Aberto"),
        (1, "2026-09-02", "L-NOVO", 10, 10, 3, 30, "Aberto"),
        (2, "2026-09-01", "B-1", 100, 100, .5, 50, "Aberto"),
    ])
    conn.commit()
    conn.close()
    return conectar


def _usuario(id=10, nome="PCP", perfil="pcp"):
    return {"id": id, "nome": nome, "perfil": perfil}


def _emitir(*, insumo=1, quantidade="10", chave="emissao-1", usuario=None, justificativa=""):
    return requisicoes.emitir_requisicao(
        {"parceiro_id": "1", "solicitante_papel": "COLABORADOR_CLT", "setor": "Produção",
         "finalidade": "Uso operacional", "justificativa": justificativa},
        [{"insumo_id": insumo, "quantidade": quantidade}],
        usuario=usuario or _usuario(), idempotency_key=chave,
    )


def test_migration_classifica_origem_e_e_idempotente(banco):
    conn = banco()
    conn.execute("UPDATE almoxarifado_insumos SET origem_baixa=NULL")
    conn.commit()
    conn.close()
    requisicoes.criar_tabelas_requisicoes_almoxarifado()
    requisicoes.criar_tabelas_requisicoes_almoxarifado()
    conn = banco()
    assert [r[0] for r in conn.execute("SELECT origem_baixa FROM almoxarifado_insumos ORDER BY id")] == [
        "REQUISICAO_ALMOXARIFADO", "ORDEM_PRODUCAO"]
    assert conn.execute("SELECT COUNT(*) FROM almoxarifado_requisicoes").fetchone()[0] == 0
    conn.close()


def test_emissao_reserva_sem_baixa_e_impede_sobrerreserva(banco):
    resultado = _emitir()
    repetida = _emitir()
    assert repetida["id"] == resultado["id"] and repetida["reaplicada"] is True
    conn = banco()
    assert conn.execute("SELECT SUM(quantidade_atual) FROM almoxarifado_lotes WHERE insumo_id=1").fetchone()[0] == 16
    assert conn.execute("SELECT quantidade_reservada FROM almoxarifado_requisicao_itens").fetchone()[0] == 10
    assert conn.execute("SELECT COUNT(*) FROM almoxarifado_movimentacoes").fetchone()[0] == 0
    conn.close()
    with pytest.raises(ValueError, match="Saldo disponível insuficiente"):
        _emitir(quantidade="7", chave="emissao-2")


def test_confirmacao_parcial_baixa_fifo_rastreia_saldos_e_libera_reserva(banco):
    req = _emitir(quantidade="10")
    detalhe = requisicoes.buscar_requisicao(req["id"])
    item_id = detalhe["itens"][0]["id"]
    atualizado = requisicoes.confirmar_requisicao(
        req["id"], [{"item_id": item_id, "quantidade": "8"}], documento_confirmado="sim",
        usuario=_usuario(), versao=0, idempotency_key="confirmacao-1")
    assert atualizado["status"] == "PARCIALMENTE_ATENDIDA"
    conn = banco()
    lotes = [tuple(r) for r in conn.execute("SELECT quantidade_atual,status FROM almoxarifado_lotes WHERE insumo_id=1 ORDER BY id")]
    assert lotes == [(0, "Fechado"), (8, "Aberto")]
    movs = list(conn.execute("SELECT quantidade,valor_total,origem,saldo_anterior,saldo_posterior FROM almoxarifado_movimentacoes ORDER BY id"))
    assert [r[0] for r in movs] == [6, 2]
    assert [r[1] for r in movs] == [12, 6]
    assert [r[2] for r in movs] == ["SAIDA_REQUISICAO_ALMOXARIFADO"] * 2
    assert [(r[3], r[4]) for r in movs] == [(16, 10), (10, 8)]
    item = conn.execute("SELECT * FROM almoxarifado_requisicao_itens").fetchone()
    assert (item["quantidade_reservada"], item["quantidade_entregue"], item["status"]) == (0, 8, "PARCIAL")
    conn.close()


def test_confirmacao_exige_documento_e_e_atomica(banco):
    req = _emitir()
    item_id = requisicoes.buscar_requisicao(req["id"])["itens"][0]["id"]
    with pytest.raises(ValueError, match="documento físico"):
        requisicoes.confirmar_requisicao(
            req["id"], [{"item_id": item_id, "quantidade": "10"}], documento_confirmado="",
            usuario=_usuario(), versao=0, idempotency_key="confirmar-sem-doc")
    conn = banco()
    assert conn.execute("SELECT SUM(quantidade_atual) FROM almoxarifado_lotes WHERE insumo_id=1").fetchone()[0] == 16
    assert conn.execute("SELECT status FROM almoxarifado_requisicoes").fetchone()[0] == "EMITIDA"
    conn.close()


def test_cancelamento_libera_reserva_sem_movimento(banco):
    req = _emitir()
    cancelada = requisicoes.cancelar_requisicao(
        req["id"], motivo="Solicitação indevida", usuario=_usuario(), versao=0,
        idempotency_key="cancelamento-1")
    assert cancelada["status"] == "CANCELADA"
    conn = banco()
    assert conn.execute("SELECT quantidade_reservada FROM almoxarifado_requisicao_itens").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM almoxarifado_movimentacoes").fetchone()[0] == 0
    conn.close()


def test_excecao_exige_admin_justificativa_e_aprovador_distinto(banco):
    with pytest.raises(PermissionError, match="Somente Administrador"):
        _emitir(insumo=2, quantidade="5", chave="ex-0")
    with pytest.raises(ValueError, match="justificativa"):
        _emitir(insumo=2, quantidade="5", chave="ex-1", usuario=_usuario(20, "Admin A", "admin"))
    req = _emitir(insumo=2, quantidade="5", chave="ex-2", justificativa="Uso emergencial",
                  usuario=_usuario(20, "Admin A", "admin"))
    assert req["status"] == "AGUARDANDO_APROVACAO"
    with pytest.raises(PermissionError, match="própria exceção"):
        requisicoes.decidir_excecao(req["id"], aprovar=True, motivo="", usuario=_usuario(20, "Admin A", "admin"),
                                    versao=0, idempotency_key="decisao-propria")
    aprovada = requisicoes.decidir_excecao(
        req["id"], aprovar=True, motivo="Conferido", usuario=_usuario(21, "Admin B", "admin"),
        versao=0, idempotency_key="decisao-2")
    assert aprovada["status"] == "EMITIDA"
    assert aprovada["aprovado_por_nome"] == "Admin B"


def test_estorno_compensa_movimentos_e_restaura_os_mesmos_lotes(banco):
    req = _emitir(quantidade="8")
    item_id = requisicoes.buscar_requisicao(req["id"])["itens"][0]["id"]
    baixada = requisicoes.confirmar_requisicao(
        req["id"], [{"item_id": item_id, "quantidade": "8"}], documento_confirmado=True,
        usuario=_usuario(), versao=0, idempotency_key="conf-estorno")
    estornada = requisicoes.estornar_requisicao(
        req["id"], motivo="Documento cancelado", usuario=_usuario(30, "Gerente", "gerencia"),
        versao=baixada["versao"], idempotency_key="estorno-1")
    assert estornada["status"] == "ESTORNADA"
    conn = banco()
    assert conn.execute("SELECT SUM(quantidade_atual) FROM almoxarifado_lotes WHERE insumo_id=1").fetchone()[0] == 16
    assert [r[0] for r in conn.execute("SELECT origem FROM almoxarifado_movimentacoes ORDER BY id")] == [
        "SAIDA_REQUISICAO_ALMOXARIFADO", "SAIDA_REQUISICAO_ALMOXARIFADO",
        "ESTORNO_SAIDA_REQUISICAO", "ESTORNO_SAIDA_REQUISICAO"]
    assert conn.execute("SELECT COUNT(*) FROM almoxarifado_movimentacoes WHERE movimento_estornado_id IS NOT NULL").fetchone()[0] == 2
    conn.close()


def test_pdf_e_indicador_nao_inventam_historico(banco):
    req = _emitir(quantidade="2")
    pdf = requisicoes.gerar_pdf_requisicao(req["id"])
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000
    indicador = requisicoes.indicadores_consumo_requisicao(1)
    assert indicador["status"] == "N/A — histórico insuficiente"
    assert indicador["cobertura_dias"] is None


def test_rotas_renderizam_emitem_e_exigem_autenticacao(banco):
    app = Flask(__name__, template_folder=str(routes.__file__).replace("modules\\almoxarifado\\routes.py", "templates"))
    app.secret_key = "teste"
    app.jinja_env.filters["br_data_hora"] = lambda valor: str(valor or "")

    @app.route("/inicio")
    def inicio():
        return "inicio"

    @app.route("/sair")
    def sair():
        return "sair"

    @app.route("/login")
    def login():
        return "login"

    routes.register_almoxarifado_routes(app)
    cliente = app.test_client()
    assert cliente.get("/almoxarifado/requisicoes").status_code == 302
    with cliente.session_transaction() as sessao:
        sessao.update({"usuario_id": 10, "nome": "PCP", "perfil": "pcp"})
    assert cliente.get("/almoxarifado/requisicoes").status_code == 200
    pagina = cliente.get("/almoxarifado/requisicoes/nova")
    assert pagina.status_code == 200 and "Emitir requisição" in pagina.get_data(as_text=True)
    resposta = cliente.post("/almoxarifado/requisicoes/nova", data={
        "idempotency_key": "rota-emissao", "parceiro_id": "1",
        "solicitante_papel": "COLABORADOR_CLT", "setor": "Produção",
        "finalidade": "Uso interno", "insumo_id": "1", "quantidade": "2",
    }, follow_redirects=True)
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200 and "REQ-" in html and "Itens e reservas" in html
