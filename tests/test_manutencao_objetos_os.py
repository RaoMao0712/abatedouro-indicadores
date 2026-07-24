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
    criar_equipamento("EQ-R")
    criar_veiculo("VEI-R")
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

    buscar_filtrado = client.get("/manutencao?aba=buscar&status=Aberta")
    html_filtrado = buscar_filtrado.get_data(as_text=True)
    assert buscar_filtrado.status_code == 200
    assert 'class="botao-tabela-almoxarifado manutencao-btn-tabela">Detalhes</a>' in html_filtrado
    assert "Atualizar</summary>" not in html_filtrado

    materiais = client.get("/manutencao?aba=materiais&status=Aberta")
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
    ordem_id, _equipamento = abrir_os("EQ-FICHA")
    client = app.test_client()
    sessao(client, "pcp", 81)
    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data=form_material("Filtro", "2"))
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


def test_ficha_gerencia_edita_dados_gerais_descricao_e_registra_historico():
    ordem_id, _equipamento = abrir_os("EQ-GERAL")

    client = app.test_client()
    sessao(client, "gerencia", 90)
    detalhe = client.get(f"/manutencao/ordem/{ordem_id}")
    html = detalhe.get_data(as_text=True)
    assert 'name="descricao"' in html
    assert 'name="descricao_visual"' not in html
    assert 'name="prioridade"' in html
    assert 'name="data_prevista"' in html

    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
        "tipo": "Preventiva",
        "prioridade": "Alta",
        "data_abertura": "2026-07-24",
        "data_prevista": "2026-08-02",
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
    assert ordem["tipo"] == "Preventiva"
    assert ordem["prioridade"] == "Alta"
    assert ordem["data_abertura"] == "2026-07-24"
    assert ordem["data_prevista"] == "2026-08-02"
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
    eventos = manutencao_service.repo.listar_eventos_ordem(ordem_id)
    assert any(evento["evento"] == "OS atualizada" and "descricao" in (evento["valor_novo"] or "") for evento in eventos)


def test_manutencao_nao_altera_descricao_ou_dados_gerais():
    ordem_id, _equipamento = abrir_os("EQ-BLOQ-GERAL")
    client = app.test_client()
    sessao(client, "manutencao", 91)

    html = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
    assert 'name="descricao"' not in html
    assert 'name="prioridade"' not in html

    resposta = client.post(f"/manutencao/ordem/{ordem_id}/salvar", data={
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
