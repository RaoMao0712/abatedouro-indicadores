import sqlite3
from io import BytesIO

import pytest
from pypdf import PdfReader
from werkzeug.datastructures import MultiDict

import database.connection as db
import modules.clientes.services as clientes
import modules.expedicao.services as expedicao
import modules.expedicao.estoque_service as estoque
import modules.pedidos_venda.services as pedidos
from modules.pedidos_venda.pdf import gerar_pdf_pedido


@pytest.fixture()
def base(tmp_path, monkeypatch):
    caminho = str(tmp_path / "pedidos.db")
    monkeypatch.setattr(db, "DB_NAME", caminho)
    monkeypatch.setattr(db, "DATABASE_URL", None)
    pedidos._SCHEMA_INICIALIZADO = False
    expedicao._SCHEMA_EXPEDICAO_INICIALIZADO = False
    expedicao._SCHEMA_ESTOQUE_PI_PA_INICIALIZADO = False
    estoque._SCHEMA_ESTOQUE_CONFIAVEL_INICIALIZADO = False
    conn = sqlite3.connect(caminho)
    conn.executescript("""
    CREATE TABLE expedicoes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, numero_romaneio TEXT UNIQUE NOT NULL,
      data TEXT NOT NULL, tipo_movimentacao TEXT NOT NULL, origem TEXT, destino TEXT NOT NULL,
      responsavel TEXT, observacoes TEXT, status TEXT NOT NULL DEFAULT 'Aberto', criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
      criado_por TEXT, perfil_criacao TEXT, atualizado_em TEXT, tipo_saida TEXT, cliente_id INTEGER,
      cliente_snapshot TEXT, veiculo TEXT, motorista TEXT
    );
    CREATE TABLE expedicao_itens (
      id INTEGER PRIMARY KEY AUTOINCREMENT, expedicao_id INTEGER NOT NULL, caixa_id INTEGER,
      op_id INTEGER, sku TEXT NOT NULL, quantidade_unidades REAL DEFAULT 0, quantidade_kg REAL,
      quantidade_pacotes INTEGER, quantidade_galinhas INTEGER, unidade_estoque TEXT, criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE skus (
      id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT, nome TEXT NOT NULL, unidade_venda TEXT NOT NULL,
      ativo TEXT DEFAULT 'Sim', excluido_em TEXT
    );
    CREATE TABLE ordens_producao (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT DEFAULT 'Encerrada');
    INSERT INTO skus(codigo,nome,unidade_venda) VALUES ('GI-PCT','Galinha Inteira','Pct');
    INSERT INTO skus(codigo,nome,unidade_venda) VALUES ('GC-KG','Galinha Cortada','Kg');
    """)
    conn.close()
    clientes.criar_tabelas_clientes()
    agora = "2026-08-10 08:00:00"
    conn = sqlite3.connect(caminho)
    conn.execute("""INSERT INTO clientes(razao_social,nome_fantasia,tipo_pessoa,status,criado_por,
        atualizado_por,criado_em,atualizado_em) VALUES (?,?,?,?,?,?,?,?)""",
        ("Cliente Homologação", "Cliente", "PJ", "Ativo", "Teste", "Teste", agora, agora))
    conn.commit(); conn.close()
    pedidos.criar_tabelas_pedidos_venda()
    yield caminho
    pedidos._SCHEMA_INICIALIZADO = False
    expedicao._SCHEMA_EXPEDICAO_INICIALIZADO = False
    expedicao._SCHEMA_ESTOQUE_PI_PA_INICIALIZADO = False
    estoque._SCHEMA_ESTOQUE_CONFIAVEL_INICIALIZADO = False


def formulario(condicao="A_VISTA", **extras):
    dados = [
        ("cliente_id", "1"), ("destino", "Rua de entrega"), ("data_pedido", "2026-08-10"),
        ("previsao_entrega", "2026-08-12"), ("responsavel", "Vendedor"),
        ("forma_pagamento", "PIX"), ("condicao_pagamento", condicao),
        ("produto_id", "1"), ("sku", "GI-PCT"), ("apresentacao", "V1"),
        ("quantidade", "10.000"), ("unidade", "PACOTE"), ("preco_unitario", "12.35"),
        ("desconto_item", "1.00"), ("observacao_item", "Primeiro item"),
        ("produto_id", "2"), ("sku", "GC-KG"), ("apresentacao", "Resfriada"),
        ("quantidade", "2.500"), ("unidade", "KG"), ("preco_unitario", "20.10"),
        ("desconto_item", "0"), ("observacao_item", "Segundo item"),
        ("desconto_geral", "2.00"),
    ]
    for chave, valor in extras.items():
        dados.append((chave, str(valor)))
    return MultiDict(dados)


def criar_confirmado():
    pedido_id, numero = pedidos.salvar_pedido(formulario(), usuario="Comercial", perfil="pcp")
    pedidos.confirmar_pedido(pedido_id, usuario="Comercial", perfil="pcp")
    return pedido_id, numero


def test_rascunho_multiplos_itens_e_calculo_exato(base):
    pedido_id, numero = pedidos.salvar_pedido(formulario(), usuario="Comercial", perfil="pcp")
    pedido = pedidos.buscar_pedido(pedido_id)
    assert numero == "PV-20260810-001"
    assert pedido["status"] == "RASCUNHO"
    assert len(pedido["itens"]) == 2
    # 10 * 12,35 - 1,00 + 2,5 * 20,10 - 2,00 = 170,75
    assert pedido["valor_total_centavos"] == 17075
    assert [e["acao"] for e in pedido["eventos"]] == ["PEDIDO_CRIADO"]


@pytest.mark.parametrize("alteracao,mensagem", [
    ({"cliente_id": ""}, "cliente"), ({"quantidade": "0"}, "maior que zero"),
    ({"preco_unitario": "0"}, "maior que zero"), ({"desconto_item": "999"}, "supera"),
])
def test_validacoes_comerciais_backend(base, alteracao, mensagem):
    form = formulario()
    for chave, valor in alteracao.items():
        form.setlist(chave, [valor] + form.getlist(chave)[1:])
    with pytest.raises(ValueError, match=mensagem):
        pedidos.salvar_pedido(form, usuario="Comercial", perfil="pcp")


@pytest.mark.parametrize("condicao,campos", [
    ("A_VISTA", {}), ("PRAZO_UNICO", {"prazo_dias": 15}),
    ("PARCELADO", {"numero_parcelas": 3, "vencimento_inicial": "2026-08-20", "intervalo_dias": 30}),
    ("ENTRADA_MAIS_SALDO", {"entrada_percentual": 20, "condicao_saldo": "30 dias"}),
    ("OUTRO", {"descricao_condicao": "Conforme contrato"}),
])
def test_condicoes_pagamento_validas(base, condicao, campos):
    pedido_id, _ = pedidos.salvar_pedido(formulario(condicao, **campos), usuario="Comercial", perfil="pcp")
    assert pedidos.buscar_pedido(pedido_id)["condicao_pagamento"] == condicao


def test_campos_condicionais_pagamento_obrigatorios(base):
    for condicao in ("PRAZO_UNICO", "PARCELADO", "ENTRADA_MAIS_SALDO", "OUTRO"):
        with pytest.raises(ValueError):
            pedidos.salvar_pedido(formulario(condicao), usuario="Comercial", perfil="pcp")


def test_confirmacao_protege_edicao_e_nao_movimenta_estoque(base):
    pedido_id, _ = criar_confirmado()
    conn = sqlite3.connect(base)
    antes = conn.execute("SELECT COUNT(*) FROM expedicoes").fetchone()[0]
    conn.close()
    assert pedidos.buscar_pedido(pedido_id)["status"] == "CONFIRMADO"
    with pytest.raises(ValueError, match="rascunho"):
        pedidos.salvar_pedido(formulario(), pedido_id, usuario="Comercial", perfil="pcp")
    conn = sqlite3.connect(base)
    assert conn.execute("SELECT COUNT(*) FROM expedicoes").fetchone()[0] == antes
    conn.close()


def _registrar_entrega(base, expedicao_id, pedido_item_id, pacotes):
    conn = db.get_connection(); cursor = conn.cursor()
    cursor.execute("""INSERT INTO expedicao_itens(expedicao_id,sku,quantidade_unidades,
        quantidade_pacotes,quantidade_galinhas,unidade_estoque,pedido_item_id)
        VALUES (?,?,?,?,?,?,?)""", (expedicao_id, "GI-PCT", pacotes, pacotes, pacotes, "PACOTE", pedido_item_id))
    pedidos.validar_e_registrar_atendimento_cursor(cursor, expedicao_id)
    cursor.execute("UPDATE expedicoes SET status='Concluído' WHERE id=?", (expedicao_id,))
    conn.commit(); conn.close()


def test_entrega_parcial_multiplos_romaneios_e_estorno(base):
    pedido_id, _ = criar_confirmado(); pedido = pedidos.buscar_pedido(pedido_id); item = pedido["itens"][0]
    exp1, _ = pedidos.gerar_romaneio_pedido(pedido_id, {item["id"]: "4"}, usuario="Expedição", perfil="pcp")
    _registrar_entrega(base, exp1, item["id"], 4)
    assert pedidos.buscar_pedido(pedido_id)["status"] == "PARCIALMENTE_ATENDIDO"
    exp2, _ = pedidos.gerar_romaneio_pedido(pedido_id, {item["id"]: "6"}, usuario="Expedição", perfil="pcp")
    _registrar_entrega(base, exp2, item["id"], 6)
    # O segundo item de 2,5 kg ainda está pendente; logo não há conclusão geral prematura.
    assert pedidos.buscar_pedido(pedido_id)["status"] == "PARCIALMENTE_ATENDIDO"
    conn = db.get_connection(); cursor = conn.cursor()
    pedidos.estornar_atendimento_cursor(cursor, exp2, "Homologação controlada")
    conn.commit(); conn.close()
    pedido = pedidos.buscar_pedido(pedido_id)
    assert pedido["status"] == "PARCIALMENTE_ATENDIDO"
    assert pedido["itens"][0]["quantidade_entregue_mil"] == 4000


def test_saldo_e_item_do_pedido_sao_protegidos(base):
    pedido_id, _ = criar_confirmado(); item = pedidos.buscar_pedido(pedido_id)["itens"][0]
    with pytest.raises(ValueError, match="supera"):
        pedidos.gerar_romaneio_pedido(pedido_id, {item["id"]: "11"}, usuario="Expedição", perfil="pcp")
    with pytest.raises(ValueError, match="ao menos"):
        pedidos.gerar_romaneio_pedido(pedido_id, {999: "1"}, usuario="Expedição", perfil="pcp")


def test_duplo_clique_na_geracao_e_rejeitado_por_versao(base):
    pedido_id, _ = criar_confirmado(); pedido = pedidos.buscar_pedido(pedido_id); item = pedido["itens"][0]
    pedidos.gerar_romaneio_pedido(pedido_id, {item["id"]: "2"}, versao_esperada=pedido["versao"],
                                  usuario="Expedição", perfil="pcp")
    with pytest.raises(ValueError, match="já processada"):
        pedidos.gerar_romaneio_pedido(pedido_id, {item["id"]: "2"}, versao_esperada=pedido["versao"],
                                      usuario="Expedição", perfil="pcp")
    conn = sqlite3.connect(base)
    assert conn.execute("SELECT COUNT(*) FROM expedicoes WHERE pedido_venda_id=?", (pedido_id,)).fetchone()[0] == 1
    conn.close()


def test_reserva_oficial_do_romaneio_cria_vinculo_por_item(base):
    pedido_id, _ = criar_confirmado(); item = pedidos.buscar_pedido(pedido_id)["itens"][0]
    expedicao.criar_tabelas_estoque_pi_pa(); estoque.criar_tabelas_estoque_confiavel()
    conn = db.get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO ordens_producao(status,estoque_classificacao) VALUES ('Encerrada','POS_MARCO')")
    op_id = cursor.lastrowid
    cursor.execute("SELECT id FROM locais_estoque WHERE nome='Abatedouro'"); local_id = cursor.fetchone()["id"]
    cursor.execute("""INSERT INTO pa_caixas(codigo_caixa,sku,status,local_estoque_id,estoque_operacional,
        unidade_estoque,apresentacao,galinhas_por_pacote,quantidade_pacotes,quantidade_galinhas,
        quantidade_pacotes_reservados,condicao,disponibilidade)
        VALUES (?,?,?,?,1,'PACOTE','V1',1,10,10,0,'CONFORME','DISPONIVEL')""",
        ("LOTE-PEDIDO-1", "Galinha Inteira", "Em estoque", local_id))
    caixa_id = cursor.lastrowid
    cursor.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES (?,?,0)",
                   (caixa_id, op_id))
    conn.commit(); conn.close()
    expedicao_id, _ = pedidos.gerar_romaneio_pedido(pedido_id, {item["id"]: "4"},
                                                    usuario="Expedição", perfil="pcp")
    estoque.reservar_itens(expedicao_id, [caixa_id], {str(caixa_id): "4"})
    conn = db.get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT pedido_item_id,quantidade_pacotes FROM expedicao_itens WHERE expedicao_id=?",
                   (expedicao_id,)); vinculo = cursor.fetchone()
    cursor.execute("SELECT disponibilidade,quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (caixa_id,))
    posicao = cursor.fetchone(); conn.close()
    assert vinculo["pedido_item_id"] == item["id"] and vinculo["quantidade_pacotes"] == 4
    assert posicao["quantidade_pacotes_reservados"] == 4
    # Reserva parcial mantém a posição disponível para outro saldo, sem baixa física.
    assert posicao["disponibilidade"] == "DISPONIVEL"


def test_cancelamento_exige_gestao_motivo_e_audita_negativa(base):
    pedido_id, _ = criar_confirmado()
    with pytest.raises(PermissionError):
        pedidos.cancelar_pedido(pedido_id, "Sem estoque", usuario="PCP", perfil="pcp")
    with pytest.raises(ValueError, match="motivo"):
        pedidos.cancelar_pedido(pedido_id, "", usuario="Gerente", perfil="gerencia")
    pedidos.cancelar_pedido(pedido_id, "Cliente desistiu", usuario="Gerente", perfil="gerencia")
    pedido = pedidos.buscar_pedido(pedido_id)
    assert pedido["status"] == "CANCELADO"
    assert {e["acao"] for e in pedido["eventos"]} >= {"TENTATIVA_NEGADA", "PEDIDO_CANCELADO"}


def test_pdf_a4_horizontal_identidade_e_acentos(base):
    pedido_id, _ = criar_confirmado(); pdf = gerar_pdf_pedido(pedidos.buscar_pedido(pedido_id))
    leitor = PdfReader(BytesIO(pdf)); pagina = leitor.pages[0]
    assert float(pagina.mediabox.width) > float(pagina.mediabox.height)
    texto = "\n".join(p.extract_text() or "" for p in leitor.pages)
    assert "ABATEDOURO DE AVES SÃO PEDRO" in texto
    assert "LF Boratto Abatedouro de Aves Ltda." in texto
    assert "Documento gerado pelo FrigoDatta" in texto
    assert "Cliente Homologação" in texto


def test_catalogo_comercial_reutiliza_apresentacoes_e_prioriza_sku(base):
    conn = sqlite3.connect(base)
    conn.execute("""CREATE TABLE pa_caixas (
        id INTEGER PRIMARY KEY, sku TEXT, apresentacao TEXT,
        unidade_estoque TEXT, galinhas_por_pacote INTEGER
    )""")
    conn.executemany("""INSERT INTO pa_caixas
        (sku,apresentacao,unidade_estoque,galinhas_por_pacote) VALUES (?,?,?,?)""", [
        ("Galinha Inteira", "Pacote com 1 galinha inteira", "PACOTE", 1),
        ("Galinha Inteira", "Pacote com 2 galinhas inteiras", "PACOTE", 2),
    ])
    conn.commit(); conn.close()
    catalogo = pedidos.catalogo_produtos_venda([
        {"id": 10, "codigo": "LEG-2", "nome": "Galinha Inteira", "unidade_venda": "Pct"}
    ])
    assert len(catalogo) == 1
    opcoes = catalogo[0]["apresentacoes"]
    assert [opcao["fator_aves"] for opcao in opcoes] == [2, 1]
    assert opcoes[0]["rotulo"] == "Pacote com 2 aves"
    assert {opcao["unidade_rotulo"] for opcao in opcoes} == {"Ave"}
    assert 500 * opcoes[1]["fator_aves"] == 500
    assert 1864 * opcoes[0]["fator_aves"] == 3728
    outro = pedidos.catalogo_produtos_venda([
        {"id": 12, "codigo": "OUTRO", "nome": "Galinha Inteira", "unidade_venda": "Pct"}
    ])[0]["apresentacoes"]
    assert {opcao["unidade_rotulo"] for opcao in outro} == {"Pacote"}
    automatico = pedidos.catalogo_produtos_venda([
        {"id": 11, "codigo": "GC-KG", "nome": "Galinha Cortada", "unidade_venda": "Kg"}
    ])[0]["apresentacoes"]
    assert automatico == [{"valor": "Quilograma", "rotulo": "Quilograma", "unidade": "KG",
                           "unidade_rotulo": "Quilograma", "fator_aves": None,
                           "base_preco": "KG"}]


def test_backend_aceita_unidade_da_apresentacao_fisica_cadastrada(base):
    conn = sqlite3.connect(base)
    conn.execute("UPDATE skus SET codigo='LEG-2',nome='Galinha Inteira',unidade_venda='Un' WHERE id=2")
    conn.execute("""CREATE TABLE pa_caixas (
        id INTEGER PRIMARY KEY, sku TEXT, apresentacao TEXT,
        unidade_estoque TEXT, galinhas_por_pacote INTEGER
    )""")
    conn.execute("""INSERT INTO pa_caixas
        (sku,apresentacao,unidade_estoque,galinhas_por_pacote) VALUES (?,?,?,?)""",
        ("Galinha Inteira", "Pacote com 2 galinhas inteiras", "PACOTE", 2))
    conn.commit(); conn.close()
    form = formulario()
    valores = {
        "produto_id": ["2"], "sku": ["LEG-2"],
        "apresentacao": ["Pacote com 2 galinhas inteiras"], "quantidade": ["150"],
        "unidade": ["PACOTE"], "preco_unitario": ["12,50"],
        "desconto_item": ["0"], "observacao_item": [""], "desconto_geral": ["0"],
    }
    for chave, lista in valores.items():
        form.setlist(chave, lista)
    pedido_id, _ = pedidos.salvar_pedido(form, usuario="Comercial", perfil="pcp")
    item = pedidos.buscar_pedido(pedido_id)["itens"][0]
    assert item["unidade_comercial"] == "AVE"
    assert item["unidade_operacional"] == "PACOTE"
    assert item["unidade_exibicao"] == "Ave"
    assert item["quantidade_negociada_mil"] == 150000
    assert item["quantidade_operacional_mil"] == 150000
    assert item["aves_por_unidade_operacional"] == 2
    assert item["quantidade_comercial_mil"] == 300000
    assert item["base_preco"] == "AVE"
    assert item["valor_liquido_centavos"] == 375000
    texto_pdf = "\n".join(
        pagina.extract_text() or "" for pagina in PdfReader(BytesIO(gerar_pdf_pedido(pedidos.buscar_pedido(pedido_id)))).pages
    )
    assert "Ave" in texto_pdf and "PACOTE" not in texto_pdf
    pedidos.confirmar_pedido(pedido_id, usuario="Comercial", perfil="pcp")
    item = pedidos.buscar_pedido(pedido_id)["itens"][0]
    expedicao_id, _ = pedidos.gerar_romaneio_pedido(
        pedido_id, {item["id"]: "150"}, usuario="Expedição", perfil="pcp"
    )
    plano = pedidos.plano_romaneio(expedicao_id)[0]
    assert plano["unidade"] == "PACOTE"
    assert plano["unidade_exibicao"] == "PACOTE"
    assert plano["quantidade_comercial_planejada_mil"] == 300000


@pytest.mark.parametrize("apresentacao,pacotes,fator,total_aves,total_centavos", [
    ("Pacote com 1 galinha inteira", "500", 1, 500000, 325000),
    ("Pacote com 2 galinhas inteiras", "1864", 2, 3728000, 2423200),
])
def test_leg2_preco_e_total_sao_sempre_por_ave(base, apresentacao, pacotes, fator,
                                                total_aves, total_centavos):
    conn = sqlite3.connect(base)
    conn.execute("UPDATE skus SET codigo='LEG-2',nome='Galinha Inteira',unidade_venda='Pct' WHERE id=1")
    conn.execute("""CREATE TABLE pa_caixas (
        id INTEGER PRIMARY KEY, sku TEXT, apresentacao TEXT,
        unidade_estoque TEXT, galinhas_por_pacote INTEGER
    )""")
    conn.executemany("""INSERT INTO pa_caixas
        (sku,apresentacao,unidade_estoque,galinhas_por_pacote) VALUES (?,?,?,?)""", [
        ("Galinha Inteira", "Pacote com 1 galinha inteira", "PACOTE", 1),
        ("Galinha Inteira", "Pacote com 2 galinhas inteiras", "PACOTE", 2),
    ])
    conn.commit(); conn.close()
    form = formulario()
    for chave, lista in {
        "produto_id": ["1"], "sku": ["LEG-2"], "apresentacao": [apresentacao],
        "quantidade": [pacotes], "unidade": ["PACOTE"], "preco_unitario": ["6.50"],
        "desconto_item": ["0"], "observacao_item": [""], "desconto_geral": ["0"],
        "valor_total": [f"{total_centavos / 100:.2f}"],
    }.items():
        form.setlist(chave, lista)
    pedido_id, _ = pedidos.salvar_pedido(form, usuario="Comercial", perfil="pcp")
    pedido = pedidos.buscar_pedido(pedido_id)
    item = pedido["itens"][0]
    assert item["quantidade_operacional_mil"] == int(pacotes) * 1000
    assert item["unidade_operacional"] == "PACOTE"
    assert item["aves_por_unidade_operacional"] == fator
    assert item["quantidade_comercial_mil"] == total_aves
    assert item["unidade_comercial"] == "AVE"
    assert item["preco_unitario_centavos"] == 650
    assert item["valor_bruto_centavos"] == total_centavos
    assert item["valor_liquido_centavos"] == total_centavos
    assert pedido["subtotal_centavos"] == pedido["valor_total_centavos"] == total_centavos


def test_leg2_rejeita_total_adulterado_e_apresentacao_ambigua(base):
    conn = sqlite3.connect(base)
    conn.execute("UPDATE skus SET codigo='LEG-2',nome='Galinha Inteira',unidade_venda='Pct' WHERE id=1")
    conn.execute("""CREATE TABLE pa_caixas (
        id INTEGER PRIMARY KEY, sku TEXT, apresentacao TEXT,
        unidade_estoque TEXT, galinhas_por_pacote INTEGER
    )""")
    conn.execute("""INSERT INTO pa_caixas
        (sku,apresentacao,unidade_estoque,galinhas_por_pacote) VALUES (?,?,?,?)""",
        ("Galinha Inteira", "Pacote com 2 galinhas inteiras", "PACOTE", 2))
    conn.commit(); conn.close()
    form = formulario(valor_total="120.00")
    form.setlist("produto_id", ["1"]); form.setlist("sku", ["LEG-2"])
    form.setlist("apresentacao", ["Pacote com 2 galinhas inteiras"])
    form.setlist("quantidade", ["10"]); form.setlist("unidade", ["PACOTE"])
    form.setlist("preco_unitario", ["6.50"]); form.setlist("desconto_item", ["0"])
    form.setlist("observacao_item", [""]); form.setlist("desconto_geral", ["0"])
    with pytest.raises(ValueError, match="divergente"):
        pedidos.salvar_pedido(form, usuario="Comercial", perfil="pcp")
    form.setlist("apresentacao", ["Pacote especial"])
    with pytest.raises(ValueError, match="conversão segura"):
        pedidos.salvar_pedido(form, usuario="Comercial", perfil="pcp")


def test_contrato_ux_do_formulario_preserva_backend_e_acessibilidade():
    from pathlib import Path
    template = (Path(__file__).parents[1] / "templates" / "pedido_venda_form.html").read_text(encoding="utf-8")
    assert "2. Itens do pedido" in template
    assert "+ Adicionar item" in template
    assert "Quantidade de ${unidadesPlural[unidade]" in template
    assert "Preço unitário (R$)" in template
    assert "Preço por Ave (R$)" in template
    assert "quantidadePrecificada = row.dataset.basePreco === 'AVE' ? quantidade * fator : quantidade" in template
    assert "Desconto do item (R$)" in template
    assert "Total do item" in template and "Total do pedido" in template
    assert "window.confirm('Remover este item preenchido do pedido?')" in template
    assert "data-show=\"PRAZO_UNICO PARCELADO ENTRADA_MAIS_SALDO\"" in template
    assert "@media(max-width:700px)" in template
    assert 'type="hidden" name="sku"' in template
    assert 'placeholder="SKU"' not in template
    assert "form.checkValidity()" in template


def test_acao_principal_salva_e_confirma_sem_movimentar_estoque(monkeypatch):
    from flask import Flask
    import modules.pedidos_venda.routes as rotas

    aplicacao = Flask(__name__)
    aplicacao.secret_key = "teste-ux"
    chamadas = []
    monkeypatch.setattr(rotas, "salvar_pedido", lambda form: (77, "PV-20260810-077"))
    monkeypatch.setattr(rotas, "confirmar_pedido", lambda pedido_id: chamadas.append(pedido_id))
    rotas.register_pedidos_venda_routes(aplicacao)
    cliente = aplicacao.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update({"usuario_id": 1, "nome": "Administrador", "perfil": "admin"})
    resposta = cliente.post("/pedidos-venda/novo", data={"acao": "confirmar"})
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/pedidos-venda/77")
    assert chamadas == [77]
