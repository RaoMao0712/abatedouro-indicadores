from pathlib import Path
import os
import sys
import tempfile
from werkzeug.datastructures import MultiDict


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_DIR = tempfile.TemporaryDirectory()
DB_PATH = Path(TEMP_DIR.name) / "manutencao.db"
os.environ["DB_NAME"] = str(DB_PATH)

from app import app
from services import manutencao_service
from modules.auth.repositories import inserir_usuario


def sessao(client, perfil, usuario_id=20):
    with client.session_transaction() as session:
        session["usuario_id"] = usuario_id
        session["nome"] = f"Usuario {perfil}"
        session["perfil"] = perfil


def criar_equipamento(codigo="EQ-01", status="Operacional"):
    manutencao_service.salvar_equipamento_manutencao({
        "codigo": codigo,
        "nome": f"Equipamento {codigo}",
        "setor": "Producao",
        "criticidade": "Alta",
        "status": status,
    })
    return manutencao_service.repo.buscar_equipamento_por_codigo(codigo)


def criar_veiculo(codigo="VEI-01", status="Ativo"):
    manutencao_service.salvar_veiculo_manutencao({
        "codigo": codigo,
        "identificacao": f"Veiculo {codigo}",
        "placa": f"ABC{codigo[-2:]}23",
        "tipo": "Veiculo utilitario",
        "marca": "Marca",
        "modelo": "Modelo",
        "ano": "2024",
        "finalidade": "Apoio",
        "setor_responsavel": "Expedicao",
        "status": status,
    })
    return manutencao_service.repo.buscar_veiculo_por_codigo(codigo)


def criar_usuario_solicitante(nome_base="Solicitante Edicao", perfil="pcp"):
    sufixo = len(manutencao_service.repo.listar_usuarios_solicitantes()) + 1
    nome = f"{nome_base} {sufixo}"
    inserir_usuario(nome, f"solicitante{sufixo}@teste.local", "123", perfil)
    return next(usuario for usuario in manutencao_service.repo.listar_usuarios_solicitantes() if usuario["nome"] == nome)


def form_base():
    return {
        "tipo": "Corretiva",
        "prioridade": "Media",
        "data_abertura": "2026-07-23",
        "descricao": "Solicitacao de manutencao",
    }


def abrir_os(codigo="EQ-OS"):
    equipamento = criar_equipamento(codigo)
    dados = form_base()
    dados.update({"tipo_objeto": "EQUIPAMENTO", "equipamento_id": str(equipamento["id"])})
    return manutencao_service.salvar_ordem_manutencao(dados, 1, "Solicitante", "pcp"), equipamento


def form_material(descricao="Rolamento", quantidade="2", status="Necessario"):
    return {
        "recurso_id[]": [""],
        "remover[]": ["Nao"],
        "recurso_tipo[]": ["Material"],
        "recurso_descricao[]": [descricao],
        "recurso_insumo_id[]": [""],
        "recurso_descricao_complementar[]": ["Aplicacao na linha"],
        "recurso_quantidade[]": [quantidade],
        "recurso_unidade[]": ["Un"],
        "recurso_fornecedor[]": [""],
        "recurso_valor_estimado[]": ["0"],
        "recurso_status[]": [status],
        "recurso_observacoes[]": ["Necessidade preliminar"],
    }


def form_materiais_variados(equipamento_id):
    dados = form_base()
    dados.update({
        "tipo_objeto": "EQUIPAMENTO",
        "equipamento_id": str(equipamento_id),
        "responsavel": "Manutencao",
        "recurso_id[]": ["", "", ""],
        "remover[]": ["Nao", "Nao", "Nao"],
        "recurso_tipo[]": ["Material", "Servico", "Outra aquisicao"],
        "recurso_descricao[]": ["Rolamento", "Servico eletrico", "Compra emergencial"],
        "recurso_insumo_id[]": ["", "", ""],
        "recurso_descricao_complementar[]": ["", "", ""],
        "recurso_quantidade[]": ["2", "1", "3"],
        "recurso_unidade[]": ["Un", "h", "Un"],
        "recurso_fornecedor[]": ["", "", ""],
        "recurso_valor_estimado[]": ["100.50", "250", "30"],
        "recurso_status[]": ["Necessario", "Necessario", "Necessario"],
        "recurso_observacoes[]": ["", "", ""],
    })
    return MultiDict(dados)


def form_ficha_dados_gerais(**extras):
    dados = {
        "tipo_objeto": "EQUIPAMENTO",
        "equipamento_id": "",
        "veiculo_id": "",
        "categoria_predial": "CIVIL",
        "local_predial": "Area Externa",
        "tipo": "Preventiva",
        "prioridade": "Alta",
        "status": "Em andamento",
        "data_abertura": "2026-07-24",
        "data_prevista": "2026-08-02",
        "solicitante_id": "",
        "origem": "Qualidade",
        "responsavel": "Responsavel Geral",
        "descricao": "Descricao editada",
        "custo_estimado": "0",
        "recurso_id[]": [""],
        "remover[]": ["Nao"],
        "recurso_tipo[]": ["Material"],
        "recurso_descricao[]": ["Filtro"],
        "recurso_insumo_id[]": [""],
        "recurso_descricao_complementar[]": [""],
        "recurso_quantidade[]": ["2"],
        "recurso_unidade[]": ["Un"],
        "recurso_fornecedor[]": [""],
        "recurso_valor_estimado[]": ["45"],
        "recurso_status[]": ["Necessario"],
        "recurso_observacoes[]": ["Observacao material"],
    }
    dados.update(extras)
    return MultiDict(dados)


def test_abertura_por_equipamento_preserva_fluxo_antigo():
    equipamento = criar_equipamento("EQ-A")
    dados = form_base()
    dados["equipamento_id"] = str(equipamento["id"])

    ordem_id = manutencao_service.salvar_ordem_manutencao(dados, 1, "Solicitante", "pcp")
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)

    assert ordem["tipo_objeto"] == "EQUIPAMENTO"
    assert ordem["equipamento_id"] == equipamento["id"]
    assert not ordem["veiculo_id"]
    assert ordem["solicitante"] == "Solicitante"
    assert ordem["solicitante_perfil"] == "pcp"


def test_abertura_com_materiais_servico_aquisicao_e_custo_transacional():
    equipamento = criar_equipamento("EQ-GRID")
    ordem_id = manutencao_service.salvar_ordem_manutencao(
        form_materiais_variados(equipamento["id"]), 10, "Solicitante", "pcp")

    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    recursos = manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]

    assert len(recursos) == 3
    assert {recurso["tipo"] for recurso in recursos} == {"Material", "Servico", "Outra aquisicao"}
    assert round(float(ordem["custo_estimado"] or 0), 2) == 380.50

    dados_invalidos = form_materiais_variados(equipamento["id"])
    dados_invalidos.setlist("recurso_descricao[]", ["Linha invalida"])
    dados_invalidos.setlist("recurso_quantidade[]", ["0"])
    total_antes = len(manutencao_service.buscar_ordens_manutencao())
    try:
        manutencao_service.salvar_ordem_manutencao(dados_invalidos, 11, "Solicitante", "pcp")
        assert False, "linha com quantidade zerada deveria falhar"
    except ValueError:
        pass
    assert len(manutencao_service.buscar_ordens_manutencao()) == total_antes


def test_equipamento_inexistente_ou_inativo_e_rejeitado():
    inativo = criar_equipamento("EQ-I", "Inativo")
    dados = form_base()
    dados.update({"tipo_objeto": "EQUIPAMENTO", "equipamento_id": str(inativo["id"])})

    try:
        manutencao_service.salvar_ordem_manutencao(dados)
        assert False, "equipamento inativo deveria ser rejeitado"
    except ValueError as erro:
        assert "inativo" in str(erro)

    dados["equipamento_id"] = "9999"
    try:
        manutencao_service.salvar_ordem_manutencao(dados)
        assert False, "equipamento inexistente deveria ser rejeitado"
    except ValueError as erro:
        assert "inexistente" in str(erro)


def test_abertura_predial_por_categorias_e_local_outros():
    for categoria in ("ELETRICA", "CIVIL", "HIDRAULICA"):
        dados = form_base()
        dados.update({
            "tipo_objeto": "PREDIAL",
            "categoria_predial": categoria,
            "local_predial": "Barreira Sanitaria",
            "equipamento_id": "999",
            "veiculo_id": "999",
        })
        ordem_id = manutencao_service.salvar_ordem_manutencao(dados)
        ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
        assert ordem["tipo_objeto"] == "PREDIAL"
        assert ordem["equipamento_id"] == 0
        assert not ordem["veiculo_id"]

    dados = form_base()
    dados.update({
        "tipo_objeto": "PREDIAL",
        "categoria_predial": "OUTRAS",
        "local_predial": "Outros",
    })
    try:
        manutencao_service.salvar_ordem_manutencao(dados)
        assert False, "local Outros sem descricao deveria falhar"
    except ValueError as erro:
        assert "Informe o local" in str(erro)

    dados["local_predial_descricao"] = "Casa de bombas"
    ordem_id = manutencao_service.salvar_ordem_manutencao(dados)
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["categoria_predial"] == "OUTRAS"
    assert ordem["local_predial_descricao"] == "Casa de bombas"


def test_abertura_por_veiculo_e_inativacao_preserva_historico():
    veiculo = criar_veiculo("VEI-A")
    dados = form_base()
    dados.update({"tipo_objeto": "VEICULO", "veiculo_id": str(veiculo["id"]), "equipamento_id": "999"})

    ordem_id = manutencao_service.salvar_ordem_manutencao(dados)
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["tipo_objeto"] == "VEICULO"
    assert ordem["veiculo_id"] == veiculo["id"]
    assert ordem["equipamento_id"] == 0

    manutencao_service.inativar_veiculo_manutencao(veiculo["id"])
    assert all(item["id"] != veiculo["id"] for item in manutencao_service.buscar_veiculos_ativos_manutencao())
    assert manutencao_service.repo.buscar_ordem_por_id(ordem_id)["veiculo_id"] == veiculo["id"]

    criar_veiculo("VEI-B")
    try:
        manutencao_service.salvar_ordem_manutencao(dados)
        assert False, "veiculo inativo deveria ser rejeitado"
    except ValueError as erro:
        assert "inativo" in str(erro)


def test_permissoes_abertura_e_bloqueio_tecnico_por_rota():
    equipamento = criar_equipamento("EQ-P")
    for indice, perfil in enumerate(("qualidade", "producao", "pcp", "manutencao", "gerencia", "admin"), start=1):
        client = app.test_client()
        sessao(client, perfil, indice)
        resposta = client.post("/manutencao", data={
            "tipo_objeto": "EQUIPAMENTO",
            "equipamento_id": str(equipamento["id"]),
            "tipo": "Corretiva",
            "prioridade": "Media",
            "data_abertura": "2026-07-23",
            "descricao": f"OS perfil {perfil}",
        })
        assert resposta.status_code == 302

    ordens = manutencao_service.buscar_ordens_manutencao()
    ordem_id = ordens[0]["id"]

    for perfil in ("qualidade", "producao", "pcp"):
        client = app.test_client()
        sessao(client, perfil)
        resposta = client.post(f"/manutencao/ordem/{ordem_id}/atualizar", data={
            "status": "Concluida",
            "horas_paradas": "10",
            "custo_real": "500",
        })
        assert resposta.status_code == 302
        assert manutencao_service.repo.buscar_ordem_por_id(ordem_id)["status"] != "Concluida"


def test_rotas_renderizam_campos_oficiais():
    equipamento_rota = criar_equipamento("EQ-R")
    criar_veiculo("VEI-R")
    dados_os_rota = form_base()
    dados_os_rota.update({"tipo_objeto": "EQUIPAMENTO", "equipamento_id": str(equipamento_rota["id"])})
    manutencao_service.salvar_ordem_manutencao(dados_os_rota, 1, "Solicitante", "pcp")
    client = app.test_client()
    sessao(client, "pcp")

    manutencao = client.get("/manutencao")
    html = manutencao.get_data(as_text=True)
    assert manutencao.status_code == 200
    assert "hero-dashboard" not in html
    assert "Visao Geral" in html and "Abrir OS" in html and "Buscar OS" in html and "Materiais" in html
    assert "Situacao das OS" in html

    abrir = client.get("/manutencao?aba=abrir")
    html_abrir = abrir.get_data(as_text=True)
    assert abrir.status_code == 200
    assert 'name="tipo_objeto"' in html_abrir
    assert "Manutencao Predial" in html_abrir
    assert 'name="categoria_predial"' in html_abrir
    assert 'name="veiculo_id"' in html_abrir
    assert "Materiais e aquisicoes necessarias" in html_abrir
    assert 'name="recurso_valor_estimado[]"' in html_abrir
    assert "Abrir ordem" in html_abrir
    assert "Salvar materiais" not in html_abrir

    buscar = client.get("/manutencao?aba=buscar")
    html_buscar = buscar.get_data(as_text=True)
    assert buscar.status_code == 200
    assert "Utilize os filtros para consultar as Ordens de Servico." in html_buscar
    assert 'class="botao-tabela-almoxarifado manutencao-btn-tabela">Detalhes</a>' not in html_buscar

    total_ordens = len(manutencao_service.buscar_ordens_manutencao())
    buscar_todos = client.get("/manutencao?aba=buscar&consultar=1&status=Todos&tipo_objeto=Todos&prioridade=Todos")
    html_todos = buscar_todos.get_data(as_text=True)
    assert buscar_todos.status_code == 200
    assert html_todos.count('class="botao-tabela-almoxarifado manutencao-btn-tabela">Detalhes</a>') == total_ordens
    assert 'name="consultar" value="1"' in html_todos
    assert '<option value="Todos" selected>Todos</option>' in html_todos
    assert '<option value="Todos" selected>Todas</option>' in html_todos

    buscar_filtrado = client.get("/manutencao?aba=buscar&consultar=1&status=Aberta")
    html_filtrado = buscar_filtrado.get_data(as_text=True)
    assert buscar_filtrado.status_code == 200
    assert 'class="botao-tabela-almoxarifado manutencao-btn-tabela">Detalhes</a>' in html_filtrado
    assert "Atualizar</summary>" not in html_filtrado

    buscar_combinado = client.get("/manutencao?aba=buscar&consultar=1&status=Aberta&prioridade=Media")
    html_combinado = buscar_combinado.get_data(as_text=True)
    assert buscar_combinado.status_code == 200
    assert "Media" in html_combinado

    buscar_objeto_pesquisa = client.get("/manutencao?aba=buscar&consultar=1&tipo_objeto=EQUIPAMENTO&pesquisa=EQ-R")
    html_objeto_pesquisa = buscar_objeto_pesquisa.get_data(as_text=True)
    assert buscar_objeto_pesquisa.status_code == 200
    assert "EQ-R" in html_objeto_pesquisa

    buscar_vazio = client.get("/manutencao?aba=buscar&consultar=1&pesquisa=SEM-RESULTADO-OS")
    html_vazio = buscar_vazio.get_data(as_text=True)
    assert buscar_vazio.status_code == 200
    assert "Nenhuma ordem encontrada para os filtros aplicados." in html_vazio

    materiais = client.get("/manutencao?aba=materiais&consultar=1&status=Aberta")
    assert materiais.status_code == 200
    assert "Materiais necessarios por OS" in materiais.get_data(as_text=True)

    ordem_id = manutencao_service.buscar_ordens_manutencao("Aberta")[0]["id"]
    detalhe = client.get(f"/manutencao/ordem/{ordem_id}")
    html_detalhe = detalhe.get_data(as_text=True)
    assert detalhe.status_code == 200
    assert "Dados da OS" in html_detalhe
    assert "Materiais e Aquisicoes Necessarias" in html_detalhe
    assert "Execucao" in html_detalhe
    assert "Salvar materiais" not in html_detalhe
    assert "Salvar alteracoes" in html_detalhe
    assert "Historico" in html_detalhe

    veiculos = client.get("/cadastros/veiculos")
    html_veiculos = veiculos.get_data(as_text=True)
    assert veiculos.status_code == 200
    assert "Cadastro de Veiculos" in html_veiculos
    assert 'name="codigo"' in html_veiculos
    assert 'name="identificacao"' in html_veiculos


def test_impressao_relatorio_os_e_ordem_individual():
    equipamento_base = criar_equipamento("EQ-PRINT")
    veiculo = criar_veiculo("VEI-PRINT")
    os_aberta = manutencao_service.salvar_ordem_manutencao({
        "tipo_objeto": "EQUIPAMENTO",
        "equipamento_id": str(equipamento_base["id"]),
        "tipo": "Corretiva",
        "prioridade": "Alta",
        "data_abertura": "2026-07-20",
        "data_prevista": "2026-07-30",
        "descricao": "Texto longo da ocorrencia para impressao " * 5,
    }, 1, "Solicitante Print", "pcp")
    os_veiculo = manutencao_service.salvar_ordem_manutencao({
        "tipo_objeto": "VEICULO",
        "veiculo_id": str(veiculo["id"]),
        "tipo": "Preventiva",
        "prioridade": "Media",
        "data_abertura": "2026-07-21",
        "descricao": "OS veiculo para pesquisa textual",
    }, 2, "Solicitante Veiculo", "qualidade")
    os_cancelada, _ = abrir_os("EQ-PRINT-CAN")
    manutencao_service.cancelar_ordem_manutencao(
        os_cancelada, "Cancelamento para impressao", 3, "Gerente", "gerencia")
    os_concluida, _ = abrir_os("EQ-PRINT-CON")
    manutencao_service.atualizar_ordem_manutencao(os_concluida, {
        "status": "Concluida",
        "data_conclusao": "2026-07-24",
        "hora_conclusao": "11:20",
        "responsavel": "Tecnico Print",
        "diagnostico": "Diagnostico impresso",
        "solucao": "Solucao impressa",
        "pecas_utilizadas": "Peca impressa",
        "observacoes_finais": "Observacao final impressa",
        "horas_paradas": "2.5",
        "custo_real": "150",
    }, 4, "Manutencao", "manutencao")
    for indice in range(25):
        equipamento = criar_equipamento(f"EQ-PRINT-{indice:02d}")
        manutencao_service.salvar_ordem_manutencao({
            "tipo_objeto": "EQUIPAMENTO",
            "equipamento_id": str(equipamento["id"]),
            "tipo": "Corretiva",
            "prioridade": "Baixa" if indice % 2 else "Media",
            "data_abertura": "2026-07-22",
            "descricao": f"OS impressao pagina {indice}",
        }, 5, "Solicitante Lote", "pcp")

    manutencao_service.salvar_recursos_ordem_manutencao(
        os_aberta,
        MultiDict({
            "recurso_id[]": ["", "", ""],
            "remover[]": ["Nao", "Nao", "Nao"],
            "recurso_tipo[]": ["Material", "Servico", "Outra aquisicao"],
            "recurso_descricao[]": ["Material print", "Servico print", "Compra print"],
            "recurso_insumo_id[]": ["", "", ""],
            "recurso_descricao_complementar[]": ["", "Complemento servico", ""],
            "recurso_quantidade[]": ["2", "1.5", "1"],
            "recurso_unidade[]": ["Un", "h", "Un"],
            "recurso_fornecedor[]": ["", "", ""],
            "recurso_valor_estimado[]": ["20", "100", "300"],
            "recurso_status[]": ["Necessario", "Disponivel", "Aguardando aquisicao"],
            "recurso_observacoes[]": ["Obs material", "Obs servico", "Obs compra"],
        }),
        "pcp", 5, "Usuario pcp")

    client = app.test_client()
    sessao(client, "gerencia", 120)

    inicial = client.get("/manutencao?aba=buscar")
    assert "IMPRIMIR RELATORIO" not in inicial.get_data(as_text=True)

    busca_todos = client.get("/manutencao?aba=buscar&consultar=1&status=Todos&tipo_objeto=Todos&prioridade=Todos")
    html_busca_todos = busca_todos.get_data(as_text=True)
    assert busca_todos.status_code == 200
    assert "IMPRIMIR RELATORIO" in html_busca_todos

    relatorio_todos = client.get("/manutencao/ordens/imprimir?status=Todos&tipo_objeto=Todos&prioridade=Todos")
    html_relatorio_todos = relatorio_todos.get_data(as_text=True)
    assert relatorio_todos.status_code == 200
    assert "Relatorio de Ordens de Servico" in html_relatorio_todos
    assert html_relatorio_todos.count("<tr>") >= 30
    assert "Solicitante Print" in html_relatorio_todos
    assert "window.print()" in html_relatorio_todos
    assert "sidebar-menu" not in html_relatorio_todos

    relatorio_status = client.get("/manutencao/ordens/imprimir?status=Cancelada")
    html_status = relatorio_status.get_data(as_text=True)
    assert "Cancelada" in html_status
    assert "Cancelamento" not in html_status

    relatorio_prioridade = client.get("/manutencao/ordens/imprimir?prioridade=Alta")
    assert "Alta" in relatorio_prioridade.get_data(as_text=True)

    relatorio_objeto = client.get("/manutencao/ordens/imprimir?tipo_objeto=VEICULO&pesquisa=veiculo")
    html_objeto = relatorio_objeto.get_data(as_text=True)
    assert "Veiculo" in html_objeto and "Veiculo VEI-PRINT" in html_objeto

    relatorio_vazio = client.get("/manutencao/ordens/imprimir?pesquisa=SEM-OS-PRINT")
    assert "Nenhuma ordem encontrada para os filtros aplicados." in relatorio_vazio.get_data(as_text=True)

    detalhe = client.get(f"/manutencao/ordem/{os_aberta}")
    assert "IMPRIMIR OS" in detalhe.get_data(as_text=True)

    impressao_aberta = client.get(f"/manutencao/ordem/{os_aberta}/imprimir")
    html_aberta = impressao_aberta.get_data(as_text=True)
    assert impressao_aberta.status_code == 200
    assert "Ordem de Servico" in html_aberta
    assert "Texto longo da ocorrencia" in html_aberta
    assert "Material print" in html_aberta and "Servico print" in html_aberta and "Compra print" in html_aberta
    assert "Linhas: 3" in html_aberta
    assert "R$ 420,00" in html_aberta
    assert "sidebar-menu" not in html_aberta

    impressao_sem_material = client.get(f"/manutencao/ordem/{os_veiculo}/imprimir")
    assert "Nenhum material ou aquisicao informado." in impressao_sem_material.get_data(as_text=True)

    impressao_concluida = client.get(f"/manutencao/ordem/{os_concluida}/imprimir")
    html_concluida = impressao_concluida.get_data(as_text=True)
    assert "Diagnostico impresso" in html_concluida
    assert "Solucao impressa" in html_concluida
    assert "Peca impressa" in html_concluida

    impressao_cancelada = client.get(f"/manutencao/ordem/{os_cancelada}/imprimir")
    html_cancelada = impressao_cancelada.get_data(as_text=True)
    assert "Situacao: Cancelada" in html_cancelada
    assert "Cancelamento para impressao" in html_cancelada

    inexistente = client.get("/manutencao/ordem/999999/imprimir")
    assert inexistente.status_code == 404


def test_lista_materiais_permissoes_auditoria_e_validacao():
    ordem_id, _equipamento = abrir_os("EQ-MAT")

    for indice, perfil in enumerate(("qualidade", "pcp", "manutencao", "gerencia", "admin"), start=30):
        client = app.test_client()
        sessao(client, perfil, indice)
        resposta = client.post(f"/manutencao/ordem/{ordem_id}/recursos", data=form_material(f"Item {perfil}", "1"))
        assert resposta.status_code == 302

    recursos = manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]
    assert len(recursos) == 5
    assert {item["usuario_nome"] for item in recursos} >= {
        "Usuario qualidade", "Usuario pcp", "Usuario manutencao", "Usuario gerencia", "Usuario admin"}

    eventos = manutencao_service.repo.listar_eventos_ordem(ordem_id)
    assert len([evento for evento in eventos if evento["evento"] == "Material incluido"]) == 5

    client = app.test_client()
    sessao(client, "producao", 50)
    resposta = client.post(f"/manutencao/ordem/{ordem_id}/recursos", data=form_material("Nao permitido", "1"))
    assert resposta.status_code == 302
    assert len(manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]) == 5

    try:
        manutencao_service.salvar_recursos_ordem_manutencao(
            ordem_id, MultiDict(form_material("Quantidade invalida", "-1")),
            "pcp", 99, "Teste")
        assert False, "quantidade negativa deveria falhar"
    except ValueError as erro:
        assert "Quantidade" in str(erro)


def test_ficha_unica_edita_material_e_execucao_com_bloqueios():
    ordem_id, equipamento = abrir_os("EQ-FICHA")
    client = app.test_client()
    sessao(client, "pcp", 81)
    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data=form_ficha_dados_gerais(
        equipamento_id=str(equipamento["id"]),
        descricao="Solicitacao de manutencao",
    ))
    assert resposta.status_code == 302
    recursos = manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]
    assert len(recursos) == 1
    assert recursos[0]["descricao"] == "Filtro"

    client_prod = app.test_client()
    sessao(client_prod, "producao", 82)
    bloqueio = client_prod.post(f"/manutencao/ordem/{ordem_id}/salvar", data=form_material("Nao pode", "1"))
    assert bloqueio.status_code in (302, 403)
    assert len(manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]) == 1

    client_manut = app.test_client()
    sessao(client_manut, "manutencao", 83)
    resposta = client_manut.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
        "status": "Concluida",
        "data_conclusao": "2026-07-24",
        "hora_conclusao": "10:30",
        "responsavel": "Tecnico",
        "horas_paradas": "1.5",
        "custo_real": "120",
        "diagnostico": "Falha identificada",
        "solucao": "Ajuste aplicado",
        "pecas_utilizadas": "Filtro",
        "observacoes_finais": "Concluido",
        "recurso_id[]": [str(recursos[0]["id"])],
        "remover[]": ["Nao"],
        "recurso_tipo[]": ["Material"],
        "recurso_descricao[]": ["Filtro atualizado"],
        "recurso_insumo_id[]": [""],
        "recurso_descricao_complementar[]": [""],
        "recurso_quantidade[]": ["3"],
        "recurso_unidade[]": ["Un"],
        "recurso_fornecedor[]": [""],
        "recurso_valor_estimado[]": ["45"],
        "recurso_status[]": ["Necessario"],
        "recurso_observacoes[]": ["Atualizado na ficha"],
    })
    assert resposta.status_code == 302
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    recursos = manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]
    assert ordem["status"] == "Concluida"
    assert recursos[0]["descricao"] == "Filtro atualizado"
    assert recursos[0]["quantidade"] == 3

    resposta = client_manut.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
        "status": "Aberta",
        "responsavel": "Tecnico",
        "horas_paradas": "0",
        "custo_real": "0",
        "diagnostico": "Tentativa de reabertura",
        "solucao": "",
        "pecas_utilizadas": "",
        "observacoes_finais": "",
    })
    assert resposta.status_code == 302
    assert manutencao_service.repo.buscar_ordem_por_id(ordem_id)["status"] == "Concluida"


def test_ficha_gerencia_edita_dados_gerais_descricao_e_registra_historico():
    ordem_id, _equipamento = abrir_os("EQ-GERAL")
    equipamento_novo = criar_equipamento("EQ-GERAL-2")
    veiculo = criar_veiculo("VEI-GERAL")
    solicitante = criar_usuario_solicitante()

    client = app.test_client()
    sessao(client, "gerencia", 90)
    detalhe = client.get(f"/manutencao/ordem/{ordem_id}")
    html = detalhe.get_data(as_text=True)
    assert 'name="descricao"' in html
    assert 'name="descricao_visual"' not in html
    assert 'name="tipo_objeto"' in html
    assert 'name="equipamento_id"' in html
    assert 'name="veiculo_id"' in html
    assert 'name="categoria_predial"' in html
    assert 'name="status"' in html
    assert 'name="solicitante_id"' in html
    assert 'name="origem"' in html
    assert 'name="prioridade"' in html
    assert 'name="data_prevista"' in html

    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
        "tipo_objeto": "EQUIPAMENTO",
        "equipamento_id": str(equipamento_novo["id"]),
        "tipo": "Preventiva",
        "prioridade": "Alta",
        "data_abertura": "2026-07-24",
        "data_prevista": "2026-08-02",
        "solicitante_id": str(solicitante["id"]),
        "origem": "Qualidade",
        "responsavel": "Responsavel Geral",
        "descricao": "Descricao editada pela gerencia",
        "custo_estimado": "0",
        "status": "Em andamento",
        "data_conclusao": "",
        "hora_conclusao": "",
        "horas_paradas": "2.25",
        "custo_real": "321.50",
        "diagnostico": "Diagnostico editado",
        "solucao": "Solucao editada",
        "pecas_utilizadas": "Peca X",
        "observacoes_finais": "Observacao editada",
    })
    assert resposta.status_code == 302

    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["tipo_objeto"] == "EQUIPAMENTO"
    assert ordem["equipamento_id"] == equipamento_novo["id"]
    assert not ordem["veiculo_id"]
    assert ordem["categoria_predial"] is None
    assert ordem["tipo"] == "Preventiva"
    assert ordem["prioridade"] == "Alta"
    assert ordem["data_abertura"] == "2026-07-24"
    assert ordem["data_prevista"] == "2026-08-02"
    assert ordem["solicitante_id"] == solicitante["id"]
    assert ordem["solicitante"] == solicitante["nome"]
    assert ordem["origem"] == "Qualidade"
    assert ordem["responsavel"] == "Responsavel Geral"
    assert ordem["descricao"] == "Descricao editada pela gerencia"
    assert ordem["status"] == "Em andamento"
    assert float(ordem["horas_paradas"]) == 2.25
    assert float(ordem["custo_real"]) == 321.50
    assert ordem["diagnostico"] == "Diagnostico editado"
    assert ordem["solucao"] == "Solucao editada"
    assert ordem["pecas_utilizadas"] == "Peca X"
    assert ordem["observacoes_finais"] == "Observacao editada"

    html_recarregado = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
    assert "Descricao editada pela gerencia" in html_recarregado
    assert equipamento_novo["nome"] in html_recarregado
    assert "Em andamento | Alta | Responsavel: Responsavel Geral | Prazo: 2026-08-02" in html_recarregado
    eventos = manutencao_service.repo.listar_eventos_ordem(ordem_id)
    assert any(evento["evento"] == "OS atualizada" and "descricao" in (evento["valor_novo"] or "") for evento in eventos)
    assert any("equipamento_id" in (evento["valor_novo"] or "") and "origem" in (evento["valor_novo"] or "") for evento in eventos)

    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
        "tipo_objeto": "VEICULO",
        "veiculo_id": str(veiculo["id"]),
        "tipo": "Melhoria",
        "prioridade": "Critica",
        "data_abertura": "2026-07-25",
        "data_prevista": "2026-08-03",
        "solicitante_id": str(solicitante["id"]),
        "origem": "PCP",
        "responsavel": "Responsavel Veiculo",
        "descricao": "Descricao veiculo",
        "status": "Aguardando material",
        "data_conclusao": "",
        "hora_conclusao": "",
        "horas_paradas": "0",
        "custo_real": "0",
        "diagnostico": "",
        "solucao": "",
        "pecas_utilizadas": "",
        "observacoes_finais": "",
    })
    assert resposta.status_code == 302
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["tipo_objeto"] == "VEICULO"
    assert ordem["equipamento_id"] == 0
    assert ordem["veiculo_id"] == veiculo["id"]
    assert ordem["categoria_predial"] is None
    assert ordem["objeto_nome"].startswith(veiculo["identificacao"])

    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
        "tipo_objeto": "PREDIAL",
        "categoria_predial": "CIVIL",
        "local_predial": "Area Externa",
        "tipo": "Corretiva",
        "prioridade": "Media",
        "data_abertura": "2026-07-26",
        "data_prevista": "2026-08-04",
        "solicitante_id": str(solicitante["id"]),
        "origem": "Auditoria",
        "responsavel": "Responsavel Predial",
        "descricao": "Descricao predial",
        "status": "Em andamento",
        "data_conclusao": "",
        "hora_conclusao": "",
        "horas_paradas": "0",
        "custo_real": "0",
        "diagnostico": "",
        "solucao": "",
        "pecas_utilizadas": "",
        "observacoes_finais": "",
    })
    assert resposta.status_code == 302
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["tipo_objeto"] == "PREDIAL"
    assert ordem["equipamento_id"] == 0
    assert not ordem["veiculo_id"]
    assert ordem["categoria_predial"] == "CIVIL"
    assert ordem["local_predial"] == "Area Externa"

    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
        "tipo_objeto": "PREDIAL",
        "categoria_predial": "CIVIL",
        "local_predial": "Area Externa",
        "tipo": "Corretiva",
        "prioridade": "Media",
        "data_abertura": "2026-07-26",
        "data_prevista": "2026-08-04",
        "solicitante_id": str(solicitante["id"]),
        "origem": "Auditoria",
        "responsavel": "Responsavel Predial",
        "descricao": "Descricao predial",
        "status": "Cancelada",
        "data_conclusao": "",
        "hora_conclusao": "",
        "horas_paradas": "0",
        "custo_real": "0",
        "diagnostico": "",
        "solucao": "",
        "pecas_utilizadas": "",
        "observacoes_finais": "",
    })
    assert resposta.status_code == 302
    assert manutencao_service.repo.buscar_ordem_por_id(ordem_id)["status"] == "Em andamento"


def test_qualidade_e_pcp_editam_dados_ocorrencia_materiais_sem_execucao_tecnica():
    cenarios = (
        ("qualidade", "VEICULO", "Qualidade"),
        ("pcp", "PREDIAL", "PCP"),
    )
    for indice, (perfil, tipo_objeto, origem) in enumerate(cenarios, start=101):
        ordem_id, _equipamento = abrir_os(f"EQ-{perfil.upper()}")
        veiculo = criar_veiculo(f"VEI-{perfil.upper()}")
        solicitante = criar_usuario_solicitante(f"Solicitante {perfil}", perfil)
        manutencao_service.repo.atualizar_ordem(ordem_id, (
            "Aberta", "", "Tecnico original", "Diagnostico preservado",
            "Solucao preservada", 3.5, 222.75, "", "Peca preservada",
            "Observacao tecnica preservada",
        ))

        client = app.test_client()
        sessao(client, perfil, indice)
        html = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
        assert 'name="tipo_objeto"' in html
        assert 'name="descricao"' in html
        assert 'name="recurso_descricao[]"' in html
        assert 'name="diagnostico"' not in html
        assert 'name="solucao"' not in html
        assert 'name="horas_paradas"' not in html
        assert 'value="Concluida"' not in html

        if tipo_objeto == "VEICULO":
            payload = form_ficha_dados_gerais(
                tipo_objeto="VEICULO",
                veiculo_id=str(veiculo["id"]),
                tipo="Melhoria",
                prioridade="Critica",
                origem=origem,
                solicitante_id=str(solicitante["id"]),
                responsavel=f"Responsavel {perfil}",
                descricao=f"Ocorrencia editada {perfil}",
            )
        else:
            payload = form_ficha_dados_gerais(
                tipo_objeto="PREDIAL",
                categoria_predial="HIDRAULICA",
                local_predial="Barreira Sanitaria",
                tipo="Preventiva",
                prioridade="Alta",
                origem=origem,
                solicitante_id=str(solicitante["id"]),
                responsavel=f"Responsavel {perfil}",
                descricao=f"Ocorrencia editada {perfil}",
            )

        resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data=payload)
        assert resposta.status_code == 302
        ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
        assert ordem["tipo_objeto"] == tipo_objeto
        assert ordem["tipo"] == payload["tipo"]
        assert ordem["prioridade"] == payload["prioridade"]
        assert ordem["status"] == "Em andamento"
        assert ordem["data_abertura"] == "2026-07-24"
        assert ordem["data_prevista"] == "2026-08-02"
        assert ordem["solicitante"] == solicitante["nome"]
        assert ordem["responsavel"] == f"Responsavel {perfil}"
        assert ordem["origem"] == origem
        assert ordem["descricao"] == f"Ocorrencia editada {perfil}"
        assert ordem["diagnostico"] == "Diagnostico preservado"
        assert ordem["solucao"] == "Solucao preservada"
        assert float(ordem["horas_paradas"]) == 3.5
        assert float(ordem["custo_real"]) == 222.75
        if tipo_objeto == "VEICULO":
            assert ordem["equipamento_id"] == 0
            assert ordem["veiculo_id"] == veiculo["id"]
        else:
            assert ordem["equipamento_id"] == 0
            assert not ordem["veiculo_id"]
            assert ordem["categoria_predial"] == "HIDRAULICA"

        recursos = manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]
        assert len(recursos) == 1
        recurso_id = recursos[0]["id"]
        assert recursos[0]["descricao"] == "Filtro"
        assert recursos[0]["quantidade"] == 2

        payload.setlist("recurso_id[]", [str(recurso_id), ""])
        payload.setlist("remover[]", ["Nao", "Nao"])
        payload.setlist("recurso_tipo[]", ["Servico", "Outra aquisicao"])
        payload.setlist("recurso_descricao[]", ["Servico atualizado", "Compra adicional"])
        payload.setlist("recurso_insumo_id[]", ["", ""])
        payload.setlist("recurso_descricao_complementar[]", ["", ""])
        payload.setlist("recurso_quantidade[]", ["4", "1"])
        payload.setlist("recurso_unidade[]", ["h", "Un"])
        payload.setlist("recurso_fornecedor[]", ["", ""])
        payload.setlist("recurso_valor_estimado[]", ["100", "250"])
        payload.setlist("recurso_status[]", ["Disponivel", "Aguardando aquisicao"])
        payload.setlist("recurso_observacoes[]", ["Alterado", "Novo"])
        assert client.post(f"/manutencao/ordem/{ordem_id}/salvar", data=payload).status_code == 302
        recursos = manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]
        assert {item["descricao"] for item in recursos} >= {"Servico atualizado", "Compra adicional"}

        payload.setlist("recurso_id[]", [str(recurso_id)])
        payload.setlist("remover[]", ["Sim"])
        payload.setlist("recurso_tipo[]", ["Servico"])
        payload.setlist("recurso_descricao[]", ["Servico atualizado"])
        payload.setlist("recurso_insumo_id[]", [""])
        payload.setlist("recurso_descricao_complementar[]", [""])
        payload.setlist("recurso_quantidade[]", ["4"])
        payload.setlist("recurso_unidade[]", ["h"])
        payload.setlist("recurso_fornecedor[]", [""])
        payload.setlist("recurso_valor_estimado[]", ["100"])
        payload.setlist("recurso_status[]", ["Disponivel"])
        payload.setlist("recurso_observacoes[]", ["Alterado"])
        assert client.post(f"/manutencao/ordem/{ordem_id}/salvar", data=payload).status_code == 302
        recursos = manutencao_service.repo.listar_recursos_por_ordens([ordem_id])[str(ordem_id)]
        assert any(item["id"] == recurso_id and item["status"] == "Cancelado" for item in recursos)

        payload["status"] = "Concluida"
        assert client.post(f"/manutencao/ordem/{ordem_id}/salvar", data=payload).status_code == 302
        assert manutencao_service.repo.buscar_ordem_por_id(ordem_id)["status"] == "Em andamento"

        html_recarregado = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
        assert f"Ocorrencia editada {perfil}" in html_recarregado
        eventos = manutencao_service.repo.listar_eventos_ordem(ordem_id)
        assert any(evento["evento"] == "OS atualizada" and f"perfil: {perfil}" in (evento["descricao"] or "") for evento in eventos)
        assert any(evento["evento"] == "Material alterado" and evento["usuario_nome"] == f"Usuario {perfil}" for evento in eventos)
        assert any(evento["evento"] == "Material cancelado" and evento["usuario_nome"] == f"Usuario {perfil}" for evento in eventos)


def test_manutencao_nao_altera_descricao_ou_dados_gerais():
    ordem_id, _equipamento = abrir_os("EQ-BLOQ-GERAL")
    client = app.test_client()
    sessao(client, "manutencao", 91)

    html = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
    assert 'name="descricao"' not in html
    assert 'name="prioridade"' not in html
    assert 'name="tipo_objeto"' not in html
    assert 'name="solicitante_id"' not in html
    assert 'name="origem"' not in html

    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
        "tipo_objeto": "PREDIAL",
        "categoria_predial": "CIVIL",
        "local_predial": "Area Externa",
        "tipo": "Preventiva",
        "prioridade": "Critica",
        "data_abertura": "2026-08-01",
        "data_prevista": "2026-08-09",
        "descricao": "Descricao indevida",
        "status": "Em andamento",
        "responsavel": "Tecnico permitido",
        "horas_paradas": "0",
        "custo_real": "0",
        "diagnostico": "Diagnostico permitido",
        "solucao": "",
        "pecas_utilizadas": "",
        "observacoes_finais": "",
    })
    assert resposta.status_code == 302

    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["tipo_objeto"] == "EQUIPAMENTO"
    assert ordem["tipo"] == "Corretiva"
    assert ordem["prioridade"] == "Media"
    assert ordem["descricao"] == "Solicitacao de manutencao"
    assert ordem["data_abertura"] == "2026-07-23"
    assert ordem["data_prevista"] in ("", None)
    assert ordem["responsavel"] == "Tecnico permitido"
    assert ordem["diagnostico"] == "Diagnostico permitido"


def test_cancelamento_os_controlado_e_indicadores():
    ordem_id, equipamento = abrir_os("EQ-CAN")

    client = app.test_client()
    sessao(client, "gerencia", 60)
    resposta = client.post(f"/manutencao/ordem/{ordem_id}/cancelar", data={"motivo_cancelamento": "Aberta em duplicidade"})
    assert resposta.status_code == 302
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["status"] == "Cancelada"
    assert ordem["cancelamento_motivo"] == "Aberta em duplicidade"
    assert manutencao_service.repo.buscar_equipamento_por_id(equipamento["id"])["status"] == "Operacional"
    assert manutencao_service.repo.listar_eventos_ordem(ordem_id)[-1]["evento"] == "OS cancelada"

    resumo = manutencao_service.calcular_resumo_manutencao(
        manutencao_service.buscar_equipamentos_ativos_manutencao(),
        [ordem],
        manutencao_service.buscar_veiculos_ativos_manutencao())
    assert resumo["abertas"] == 0
    assert resumo["horas_paradas"] == 0
    assert resumo["custo_real"] == 0


def test_cancelamento_bloqueios_por_perfil_status_motivo_e_execucao():
    ordem_id, _equipamento = abrir_os("EQ-BLOQ")

    for perfil in ("qualidade", "pcp", "producao"):
        client = app.test_client()
        sessao(client, perfil, 70)
        resposta = client.post(f"/manutencao/ordem/{ordem_id}/cancelar", data={"motivo_cancelamento": "Teste"})
        assert resposta.status_code == 302
        assert manutencao_service.repo.buscar_ordem_por_id(ordem_id)["status"] == "Aberta"

    try:
        manutencao_service.cancelar_ordem_manutencao(ordem_id, "", 1, "Gerente", "gerencia")
        assert False, "motivo obrigatorio deveria falhar"
    except ValueError as erro:
        assert "motivo" in str(erro)

    manutencao_service.atualizar_ordem_manutencao(ordem_id, {
        "status": "Em andamento",
        "horas_paradas": "0",
        "custo_real": "0",
    }, 1, "Manutencao", "manutencao")
    try:
        manutencao_service.cancelar_ordem_manutencao(ordem_id, "Nao pode", 1, "Gerente", "gerencia")
        assert False, "OS em andamento deveria bloquear cancelamento"
    except ValueError as erro:
        assert "preservacao" in str(erro)

    ordem_custo_id, _ = abrir_os("EQ-CUSTO")
    manutencao_service.repo.atualizar_ordem(ordem_custo_id, (
        "Aberta", "", "", "", "", 0, 10, "", "", "",
    ))
    try:
        manutencao_service.cancelar_ordem_manutencao(ordem_custo_id, "Nao pode", 1, "Gerente", "gerencia")
        assert False, "OS com custo deveria bloquear cancelamento"
    except ValueError:
        pass


if __name__ == "__main__":
    testes = [obj for nome, obj in sorted(globals().items()) if nome.startswith("test_")]
    try:
        for teste in testes:
            teste()
            print("OK", teste.__name__)
    finally:
        TEMP_DIR.cleanup()
