import sqlite3

import pytest
from flask import Flask
from werkzeug.datastructures import MultiDict

import database.connection as db_connection
from modules.parceiros import services as parceiros
from modules.parceiros.routes import register_parceiros_routes
from modules.producao import services as producao


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "p3-3.sqlite"
    monkeypatch.setattr(db_connection, "DB_NAME", str(caminho))
    monkeypatch.setattr(db_connection, "DATABASE_URL", None)
    monkeypatch.setattr(parceiros, "DATABASE_URL", None)
    monkeypatch.setattr(producao, "DATABASE_URL", None)
    conn = sqlite3.connect(caminho)
    conn.executescript("""
        CREATE TABLE ordens_producao (
            id INTEGER PRIMARY KEY, status TEXT NOT NULL, data TEXT,
            fornecedor TEXT, quantidade_aves INTEGER DEFAULT 0,
            peso_vivo REAL DEFAULT 0, mortes_antes_pendura INTEGER DEFAULT 0
        );
        CREATE TABLE apontamentos_mao_obra (
            id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER NOT NULL,
            data TEXT NOT NULL, colaborador TEXT NOT NULL, funcao TEXT NOT NULL,
            setor TEXT NOT NULL, turno TEXT, observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO ordens_producao(id,status,data,fornecedor) VALUES(100,'Aberta','2026-09-09','Teste');
    """)
    conn.close()
    parceiros.criar_tabelas_parceiros()
    return caminho


def form(nome="João Teste", tipo="PF", documento="529.982.247-25", papeis=()):
    return MultiDict([
        ("tipo_pessoa", tipo), ("razao_social", nome),
        ("nome_fantasia", ""), ("documento", documento),
        ("telefone", "92999990000"), ("email", "TESTE@EXEMPLO.COM"),
        ("endereco", "Rua A"), ("cidade", "Manaus"), ("uf", "am"),
        *(("papeis", papel) for papel in papeis),
    ])


def mao_obra(parceiro_id, natureza=""):
    return MultiDict({
        "op_id": "100", "data": "2026-09-09", "parceiro_id": str(parceiro_id),
        "natureza_vinculo": natureza, "funcao": "Corte", "setor": "Corte",
        "turno": "A", "observacoes": "Teste controlado",
    })


def consultar(caminho, sql, parametros=()):
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


@pytest.mark.parametrize("tipo,documento", [
    ("PF", "529.982.247-25"),
    ("PJ", "11.222.333/0001-81"),
])
def test_01_a_04_cria_pf_pj_e_valida_documento(banco, tipo, documento):
    parceiro_id = parceiros.salvar_parceiro(
        form("Pessoa válida", tipo, documento), usuario="Admin", perfil="admin"
    )
    registro = parceiros.buscar_parceiro(parceiro_id)
    assert registro["tipo_pessoa"] == tipo
    assert registro["documento"] == parceiros.normalizar_documento(documento)
    assert registro["email"] == "teste@exemplo.com"


@pytest.mark.parametrize("tipo,documento", [
    ("PF", "52998224725"), ("PJ", "11222333000181"),
])
def test_05_e_06_impede_documento_duplicado_com_ou_sem_mascara(banco, tipo, documento):
    mascarado = "529.982.247-25" if tipo == "PF" else "11.222.333/0001-81"
    parceiros.salvar_parceiro(form("Primeiro", tipo, mascarado), usuario="Admin", perfil="admin")
    with pytest.raises(ValueError, match="já cadastrado"):
        parceiros.salvar_parceiro(form("Duplicado", tipo, documento), usuario="Admin", perfil="admin")


@pytest.mark.parametrize("tipo,documento", [("PF", "111.111.111-11"), ("PJ", "11.111.111/1111-11")])
def test_documento_invalido_e_rejeitado_no_backend(banco, tipo, documento):
    with pytest.raises(ValueError, match="inválido"):
        parceiros.salvar_parceiro(form("Inválido", tipo, documento), usuario="Admin", perfil="admin")


def test_07_a_10_documento_ausente_edicao_inativacao_e_reativacao(banco):
    parceiro_id = parceiros.salvar_parceiro(form(documento=""), usuario="Admin", perfil="admin")
    atualizado = form("João Atualizado", documento="", papeis=(parceiros.PAPEL_CLIENTE,))
    parceiros.salvar_parceiro(atualizado, parceiro_id, usuario="PCP", perfil="pcp")
    assert parceiros.buscar_parceiro(parceiro_id)["razao_social"] == "João Atualizado"
    parceiros.alterar_status(parceiro_id, "Inativo", usuario="Gerente", perfil="gerencia")
    assert parceiros.buscar_parceiro(parceiro_id)["status"] == "Inativo"
    parceiros.alterar_status(parceiro_id, "Ativo", usuario="Gerente", perfil="gerencia")
    assert parceiros.buscar_parceiro(parceiro_id)["status"] == "Ativo"


@pytest.mark.parametrize("papel", sorted(parceiros.PAPEIS_VALIDOS))
def test_11_a_14_aceita_cada_papel(banco, papel):
    parceiro_id = parceiros.salvar_parceiro(form(documento="", papeis=(papel,)), usuario="Admin", perfil="admin")
    assert parceiros.buscar_parceiro(parceiro_id)["papeis"] == [papel]


def test_15_a_18_multiplos_papeis_adicao_remocao_e_historico(banco):
    parceiro_id = parceiros.salvar_parceiro(
        form(documento="", papeis=(parceiros.PAPEL_CLIENTE, parceiros.PAPEL_FORNECEDOR)),
        usuario="Admin", perfil="admin",
    )
    parceiros.salvar_parceiro(
        form(documento="", papeis=(parceiros.PAPEL_FORNECEDOR, parceiros.PAPEL_PRESTADOR)),
        parceiro_id, usuario="PCP", perfil="pcp",
    )
    assert set(parceiros.buscar_parceiro(parceiro_id)["papeis"]) == {parceiros.PAPEL_FORNECEDOR, parceiros.PAPEL_PRESTADOR}
    eventos = parceiros.historico_parceiro(parceiro_id)
    assert any(e["acao"] == "PAPEL_ADICIONADO" and e["papel"] == parceiros.PAPEL_PRESTADOR for e in eventos)
    assert any(e["acao"] == "PAPEL_REMOVIDO" and e["papel"] == parceiros.PAPEL_CLIENTE for e in eventos)


def test_parceiro_sem_papel_e_permitido(banco):
    parceiro_id = parceiros.salvar_parceiro(form(documento="", papeis=()), usuario="Admin", perfil="admin")
    assert parceiros.buscar_parceiro(parceiro_id)["papeis"] == []


def test_19_a_24_elegibilidade_ativa_e_sem_duplicar_clt_prestador(banco):
    clt = parceiros.salvar_parceiro(form("CLT", documento="", papeis=(parceiros.PAPEL_CLT,)), usuario="Admin", perfil="admin")
    prestador = parceiros.salvar_parceiro(form("Prestador", documento="", papeis=(parceiros.PAPEL_PRESTADOR,)), usuario="Admin", perfil="admin")
    parceiros.salvar_parceiro(form("Cliente", documento="", papeis=(parceiros.PAPEL_CLIENTE,)), usuario="Admin", perfil="admin")
    parceiros.salvar_parceiro(form("Fornecedor", documento="", papeis=(parceiros.PAPEL_FORNECEDOR,)), usuario="Admin", perfil="admin")
    duplo = parceiros.salvar_parceiro(form("Duplo", documento="", papeis=(parceiros.PAPEL_CLT, parceiros.PAPEL_PRESTADOR)), usuario="Admin", perfil="admin")
    inativo = parceiros.salvar_parceiro(form("Inativo", documento="", papeis=(parceiros.PAPEL_CLT,)), usuario="Admin", perfil="admin")
    parceiros.alterar_status(inativo, "Inativo", usuario="Admin", perfil="admin")
    ids = [item["id"] for item in parceiros.listar_parceiros_elegiveis()]
    assert clt in ids and prestador in ids and duplo in ids
    assert ids.count(duplo) == 1
    assert inativo not in ids and len(ids) == 3


def test_25_a_28_apontamento_snapshot_papel_e_inativacao_preservam_historico(banco):
    joao = parceiros.salvar_parceiro(form(documento="", papeis=(parceiros.PAPEL_CLT,)), usuario="Admin", perfil="admin")
    producao.salvar_apontamento_mao_obra(mao_obra(joao))
    parceiros.salvar_parceiro(form(documento="", papeis=(parceiros.PAPEL_PRESTADOR,)), joao, usuario="Admin", perfil="admin")
    producao.salvar_apontamento_mao_obra(mao_obra(joao, parceiros.PAPEL_PRESTADOR))
    parceiros.alterar_status(joao, "Inativo", usuario="Admin", perfil="admin")
    registros = consultar(banco, "SELECT * FROM apontamentos_mao_obra ORDER BY id")
    assert [r["natureza_vinculo"] for r in registros] == [parceiros.PAPEL_CLT, parceiros.PAPEL_PRESTADOR]
    assert all(r["parceiro_id"] == joao and r["parceiro_nome_snapshot"] == "João Teste" for r in registros)
    assert joao not in [item["id"] for item in parceiros.listar_parceiros_elegiveis()]
    assert len(consultar(banco, "SELECT * FROM apontamentos_mao_obra WHERE parceiro_id=?", (joao,))) == 2


def test_cenario_b_empresa_so_aparece_apos_papel_prestador(banco):
    empresa = parceiros.salvar_parceiro(form("Empresa XPTO", "PJ", "", (parceiros.PAPEL_CLIENTE, parceiros.PAPEL_FORNECEDOR)), usuario="Admin", perfil="admin")
    assert empresa not in [p["id"] for p in parceiros.listar_parceiros_elegiveis()]
    parceiros.salvar_parceiro(form("Empresa XPTO", "PJ", "", (parceiros.PAPEL_CLIENTE, parceiros.PAPEL_FORNECEDOR, parceiros.PAPEL_PRESTADOR)), empresa, usuario="Admin", perfil="admin")
    assert empresa in [p["id"] for p in parceiros.listar_parceiros_elegiveis()]


def test_cenario_d_exige_natureza_quando_parceiro_tem_dois_vinculos(banco):
    duplo = parceiros.salvar_parceiro(form(documento="", papeis=(parceiros.PAPEL_CLT, parceiros.PAPEL_PRESTADOR)), usuario="Admin", perfil="admin")
    with pytest.raises(ValueError, match="natureza"):
        producao.salvar_apontamento_mao_obra(mao_obra(duplo))
    producao.salvar_apontamento_mao_obra(mao_obra(duplo, parceiros.PAPEL_CLT))
    assert consultar(banco, "SELECT natureza_vinculo FROM apontamentos_mao_obra")[0][0] == parceiros.PAPEL_CLT


def test_cliente_ou_fornecedor_nao_pode_ser_apontado(banco):
    cliente = parceiros.salvar_parceiro(form(documento="", papeis=(parceiros.PAPEL_CLIENTE,)), usuario="Admin", perfil="admin")
    with pytest.raises(ValueError, match="não possui papel"):
        producao.salvar_apontamento_mao_obra(mao_obra(cliente, parceiros.PAPEL_CLT))


def test_permissoes_criticas_protegidas_no_backend(banco):
    with pytest.raises(PermissionError):
        parceiros.salvar_parceiro(form(documento=""), usuario="Produção", perfil="producao")
    parceiro_id = parceiros.salvar_parceiro(form(documento=""), usuario="PCP", perfil="pcp")
    with pytest.raises(PermissionError):
        parceiros.alterar_status(parceiro_id, "Inativo", usuario="PCP", perfil="pcp")


def test_rotas_listagem_filtros_e_permissoes_renderizam_sem_duplicidade(banco):
    parceiros.salvar_parceiro(form("Duplo", documento="", papeis=(parceiros.PAPEL_CLT, parceiros.PAPEL_PRESTADOR)), usuario="Admin", perfil="admin")
    app = Flask(__name__, template_folder=str(__import__("pathlib").Path(__file__).parents[1] / "templates"))
    app.secret_key = "teste"
    app.add_url_rule("/inicio", "inicio", lambda: "inicio")
    app.add_url_rule("/sair", "sair", lambda: "sair")
    register_parceiros_routes(app)
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(usuario_id=1, nome="Produção", perfil="producao")
    resposta = cliente.get("/cadastros/parceiros?status=Ativo&tipo_pessoa=PF&papel=COLABORADOR_CLT")
    assert resposta.status_code == 200
    assert resposta.get_data(as_text=True).count("<strong>Duplo</strong>") == 1
    assert cliente.get("/cadastros/parceiros/novo").status_code == 302


def test_busca_por_nome_fantasia_documento_telefone_e_email(banco):
    dados = form("Razão Encontrável", documento="52998224725")
    dados.setlist("nome_fantasia", ["Fantasia Única"])
    parceiro_id = parceiros.salvar_parceiro(dados, usuario="Admin", perfil="admin")
    for termo in ("encontrável", "Fantasia Única", "52998224725", "92999990000", "teste@exemplo.com"):
        assert [p["id"] for p in parceiros.listar_parceiros(busca=termo)] == [parceiro_id]


def test_migration_sqlite_upgrade_e_rollback_preservam_linha_legada(tmp_path):
    caminho = tmp_path / "migration.sqlite"
    conn = sqlite3.connect(caminho)
    conn.executescript("""CREATE TABLE apontamentos_mao_obra(id INTEGER PRIMARY KEY,op_id INTEGER,colaborador TEXT);
        INSERT INTO apontamentos_mao_obra VALUES(1,100,'Legado');""")
    raiz = __import__("pathlib").Path(__file__).parents[1]
    conn.executescript((raiz / "database/20260909_p3_3_cadastro_parceiros_sqlite.sql").read_text(encoding="utf-8"))
    linha = conn.execute("SELECT colaborador,parceiro_id,natureza_vinculo FROM apontamentos_mao_obra").fetchone()
    assert linha == ("Legado", None, None)
    conn.executescript((raiz / "database/20260909_p3_3_cadastro_parceiros_sqlite_rollback.sql").read_text(encoding="utf-8"))
    assert conn.execute("SELECT colaborador FROM apontamentos_mao_obra").fetchone()[0] == "Legado"
    conn.close()
