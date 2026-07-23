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
    assert 'name="tipo_objeto"' in html
    assert "Manutencao Predial" in html
    assert 'name="categoria_predial"' in html
    assert 'name="veiculo_id"' in html

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
