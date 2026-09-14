"""P3.6 — rastreabilidade documental da OS: vinculo OS<->Requisicao de
Almoxarifado, origem estruturada e filtro de periodo na listagem.

Roda via SQLite, aplicacao real, seguindo o mesmo padrao de
tests/test_manutencao_objetos_os.py (arquivo independente, nao importa
helpers de outros arquivos de teste, para nao depender da ordem de coleta
do pytest — ver licao registrada no hotfix do 502 sobre DATABASE_URL/DB_NAME
serem lidos uma unica vez por processo).
"""

from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_DIR = tempfile.TemporaryDirectory()
DB_PATH = Path(TEMP_DIR.name) / "p3_6.db"
os.environ["DB_NAME"] = str(DB_PATH)
os.environ.pop("DATABASE_URL", None)

from app import app  # noqa: E402
from services import manutencao_service  # noqa: E402
from modules.almoxarifado import requisicoes  # noqa: E402
from modules.parceiros import services as parceiros_service  # noqa: E402


def sessao(client, perfil, usuario_id=20):
    with client.session_transaction() as session:
        session["usuario_id"] = usuario_id
        session["nome"] = f"Usuario {perfil}"
        session["perfil"] = perfil


def criar_equipamento(codigo="EQ-P36"):
    manutencao_service.salvar_equipamento_manutencao({
        "codigo": codigo, "nome": f"Equipamento {codigo}", "setor": "Producao",
        "criticidade": "Alta", "status": "Operacional",
    })
    return manutencao_service.repo.buscar_equipamento_por_codigo(codigo)


def abrir_os(codigo="EQ-P36", **extra_dados):
    equipamento = criar_equipamento(codigo)
    dados = {
        "tipo": "Corretiva", "prioridade": "Media", "data_abertura": "2026-09-01",
        "descricao": "Solicitacao de manutencao", "tipo_objeto": "EQUIPAMENTO",
        "equipamento_id": str(equipamento["id"]),
    }
    dados.update(extra_dados)
    return manutencao_service.salvar_ordem_manutencao(dados, 1, "Solicitante", "pcp"), equipamento


def criar_parceiro_fornecedor_solicitante():
    """Parceiro com o papel exigido para emitir requisicao (COLABORADOR_CLT,
    mesma exigencia da P3.5). Retorna o id do parceiro (salvar_parceiro
    retorna so o id, nao um dict)."""
    parceiros_service.criar_tabelas_parceiros()
    return parceiros_service.salvar_parceiro(
        {"tipo_pessoa": "PF", "razao_social": "Solicitante P3.6", "papeis": ["COLABORADOR_CLT"]},
        usuario="Teste", perfil="admin")


def criar_insumo(descricao="Insumo P3.6"):
    from modules.almoxarifado import services as almox_service
    almox_service.criar_tabelas_estoque_almoxarifado()
    conn = manutencao_service.repo.conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO almoxarifado_insumos (descricao, categoria, unidade, ativo, origem_baixa) "
        "VALUES (?, ?, ?, 'Sim', 'REQUISICAO_ALMOXARIFADO')",
        (descricao, "EPI", "Un"))
    conn.commit()
    insumo_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO almoxarifado_lotes (insumo_id, data_entrada, lote, quantidade_inicial, "
        "quantidade_atual, valor_unitario, valor_total, status, versao) "
        "VALUES (?, '2026-09-01', 'L-P36', 50, 50, 1, 50, 'Aberto', 0)",
        (insumo_id,))
    conn.commit()
    conn.close()
    return insumo_id


def emitir_requisicao_teste(parceiro_id, insumo_id, *, ordem_servico_id=None, chave="chave-p36", usuario=None):
    dados = {"parceiro_id": str(parceiro_id), "solicitante_papel": "COLABORADOR_CLT",
              "setor": "Producao", "finalidade": "Uso operacional"}
    if ordem_servico_id:
        dados["ordem_servico_id"] = str(ordem_servico_id)
    return requisicoes.emitir_requisicao(
        dados, [{"insumo_id": insumo_id, "quantidade": "1"}],
        usuario=usuario or {"id": 1, "nome": "PCP", "perfil": "pcp"}, idempotency_key=chave)


# ---------------------------------------------------------------------------
# Vinculo OS <-> Requisicao de Almoxarifado (itens 38 do escopo da Etapa B)
# ---------------------------------------------------------------------------

def test_criar_requisicao_a_partir_da_os_grava_vinculo():
    ordem_id, _equipamento = abrir_os("EQ-VINC-1")
    parceiro = criar_parceiro_fornecedor_solicitante()
    insumo_id = criar_insumo("Insumo Vinculo 1")

    resultado = emitir_requisicao_teste(parceiro, insumo_id, ordem_servico_id=ordem_id, chave="req-criada-os")

    requisicao = requisicoes.buscar_requisicao(resultado["id"])
    assert requisicao["ordem_servico_id"] == ordem_id

    desdobramentos = requisicoes.listar_requisicoes_por_ordem_servico(ordem_id)
    assert len(desdobramentos) == 1
    assert desdobramentos[0]["id"] == resultado["id"]

    # Evento de vinculo registrado junto da emissao (item 19 do escopo).
    eventos = [evento["evento"] for evento in requisicao["eventos"]]
    assert "VINCULO_ORDEM_SERVICO" in eventos


def test_criar_requisicao_com_os_inexistente_falha_sem_gravar():
    parceiro = criar_parceiro_fornecedor_solicitante()
    insumo_id = criar_insumo("Insumo OS Inexistente")
    try:
        emitir_requisicao_teste(parceiro, insumo_id, ordem_servico_id=999999, chave="req-os-invalida")
        assert False, "OS inexistente deveria ser rejeitada"
    except ValueError as erro:
        assert "não foi encontrada" in str(erro) or "nao foi encontrada" in str(erro)
    # Nada foi gravado sob esta chave de idempotencia especifica (nao inspeciona
    # a tabela inteira: outros testes deste arquivo compartilham o mesmo banco).
    assert not [r for r in requisicoes.listar_requisicoes({}) if r["chave_emissao"] == "req-os-invalida"]


def test_vincular_requisicao_existente_e_idempotente():
    ordem_id, _equipamento = abrir_os("EQ-VINC-2")
    parceiro = criar_parceiro_fornecedor_solicitante()
    insumo_id = criar_insumo("Insumo Vinculo 2")

    # Requisicao emitida sem vinculo, depois vinculada a OS ja existente.
    resultado = emitir_requisicao_teste(parceiro, insumo_id, chave="req-avulsa")
    usuario = {"id": 2, "nome": "Gerencia", "perfil": "gerencia"}

    vinculada = requisicoes.vincular_a_ordem_servico(
        resultado["id"], ordem_id, usuario=usuario, idempotency_key="vinculo-1")
    assert vinculada["ordem_servico_id"] == ordem_id

    # Reenviar o mesmo vinculo (mesma requisicao, mesma OS) e idempotente.
    repetido = requisicoes.vincular_a_ordem_servico(
        resultado["id"], ordem_id, usuario=usuario, idempotency_key="vinculo-2")
    assert repetido["ordem_servico_id"] == ordem_id

    eventos_vinculo = [e for e in requisicoes.buscar_requisicao(resultado["id"])["eventos"]
                        if e["evento"] == "VINCULO_ORDEM_SERVICO"]
    assert len(eventos_vinculo) == 1  # nao duplicou


def test_vincular_requisicao_ja_vinculada_a_outra_os_e_rejeitado():
    ordem_a, _equipamento_a = abrir_os("EQ-VINC-3A")
    ordem_b, _equipamento_b = abrir_os("EQ-VINC-3B")
    parceiro = criar_parceiro_fornecedor_solicitante()
    insumo_id = criar_insumo("Insumo Vinculo 3")

    resultado = emitir_requisicao_teste(parceiro, insumo_id, ordem_servico_id=ordem_a, chave="req-a")
    usuario = {"id": 3, "nome": "Gerencia", "perfil": "gerencia"}

    try:
        requisicoes.vincular_a_ordem_servico(resultado["id"], ordem_b, usuario=usuario, idempotency_key="vinculo-cruzado")
        assert False, "requisicao ja vinculada a outra OS nao pode ser transferida"
    except ValueError as erro:
        assert "já está vinculada" in str(erro) or "ja esta vinculada" in str(erro)

    assert requisicoes.buscar_requisicao(resultado["id"])["ordem_servico_id"] == ordem_a


def test_vincular_requisicao_cancelada_e_rejeitado():
    ordem_id, _equipamento = abrir_os("EQ-VINC-4")
    parceiro = criar_parceiro_fornecedor_solicitante()
    insumo_id = criar_insumo("Insumo Vinculo 4")

    resultado = emitir_requisicao_teste(parceiro, insumo_id, chave="req-cancelar")
    requisicoes.cancelar_requisicao(
        resultado["id"], motivo="Nao sera mais necessaria",
        usuario={"id": 4, "nome": "PCP", "perfil": "pcp"}, versao=0, idempotency_key="cancel-1")

    try:
        requisicoes.vincular_a_ordem_servico(
            resultado["id"], ordem_id, usuario={"id": 5, "nome": "Gerencia", "perfil": "gerencia"},
            idempotency_key="vinculo-cancelada")
        assert False, "requisicao cancelada nao pode ser vinculada"
    except ValueError as erro:
        assert "cancelada" in str(erro).lower()


def test_listar_requisicoes_vinculaveis_exclui_vinculadas_e_canceladas():
    ordem_id, _equipamento = abrir_os("EQ-VINC-5")
    parceiro = criar_parceiro_fornecedor_solicitante()
    insumo_id = criar_insumo("Insumo Vinculo 5")

    elegivel = emitir_requisicao_teste(parceiro, insumo_id, chave="req-elegivel")
    ja_vinculada = emitir_requisicao_teste(parceiro, insumo_id, ordem_servico_id=ordem_id, chave="req-ja-vinculada")
    cancelada = emitir_requisicao_teste(parceiro, insumo_id, chave="req-cancelada-elegibilidade")
    requisicoes.cancelar_requisicao(
        cancelada["id"], motivo="Cancelada para teste de elegibilidade",
        usuario={"id": 6, "nome": "PCP", "perfil": "pcp"}, versao=0, idempotency_key="cancel-elegibilidade")

    vinculaveis = {req["id"] for req in requisicoes.listar_requisicoes_vinculaveis()}
    assert elegivel["id"] in vinculaveis
    assert ja_vinculada["id"] not in vinculaveis
    assert cancelada["id"] not in vinculaveis


def test_rota_vincular_requisicao_respeita_permissoes():
    ordem_id, _equipamento = abrir_os("EQ-VINC-ROTA")
    parceiro = criar_parceiro_fornecedor_solicitante()
    insumo_id = criar_insumo("Insumo Vinculo Rota")
    resultado = emitir_requisicao_teste(parceiro, insumo_id, chave="req-rota")

    client_prod = app.test_client()
    sessao(client_prod, "producao", 60)
    bloqueio = client_prod.post(
        f"/manutencao/ordem/{ordem_id}/requisicao/vincular",
        data={"requisicao_id": str(resultado["id"]), "idempotency_key": "vinculo-rota-negado"})
    assert bloqueio.status_code == 302
    assert requisicoes.buscar_requisicao(resultado["id"])["ordem_servico_id"] is None

    client_pcp = app.test_client()
    sessao(client_pcp, "pcp", 61)
    ok = client_pcp.post(
        f"/manutencao/ordem/{ordem_id}/requisicao/vincular",
        data={"requisicao_id": str(resultado["id"]), "idempotency_key": "vinculo-rota-ok"},
        follow_redirects=True)
    assert ok.status_code == 200
    assert requisicoes.buscar_requisicao(resultado["id"])["ordem_servico_id"] == ordem_id
    assert "vinculada" in ok.get_data(as_text=True).lower()


def test_detalhe_os_mostra_documentos_relacionados():
    ordem_id, _equipamento = abrir_os("EQ-DOC-REL")
    parceiro = criar_parceiro_fornecedor_solicitante()
    insumo_id = criar_insumo("Insumo Doc Relacionado")
    emitir_requisicao_teste(parceiro, insumo_id, ordem_servico_id=ordem_id, chave="req-doc-rel")

    client = app.test_client()
    sessao(client, "pcp", 62)
    html = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
    assert "Documentos Relacionados" in html
    assert "Desdobramentos" in html
    assert "REQ-" in html  # numero da requisicao vinculada aparece na lista


# ---------------------------------------------------------------------------
# Origem estruturada (itens 39 do escopo da Etapa B)
# ---------------------------------------------------------------------------

def test_origem_estruturada_op_e_parada_sem_qualidade():
    with app.test_request_context():
        ordem_op = {"sgi_nc_id": None, "op_id": 42, "parada_id": None}
        origens = manutencao_service.detalhes_origem_ordem(ordem_op)
        assert len(origens) == 1
        assert origens[0]["tipo"] == "Ordem de Producao"
        assert origens[0]["numero"] == "OP 42"
        assert origens[0]["link"] is not None

        ordem_parada = {"sgi_nc_id": None, "op_id": None, "parada_id": 7}
        origens_parada = manutencao_service.detalhes_origem_ordem(ordem_parada)
        assert len(origens_parada) == 1
        assert origens_parada[0]["tipo"] == "Parada de producao"
        assert origens_parada[0]["numero"] == "Parada #7"


def test_origem_estruturada_vazia_quando_manual():
    with app.test_request_context():
        ordem_manual = {"sgi_nc_id": None, "op_id": None, "parada_id": None}
        assert manutencao_service.detalhes_origem_ordem(ordem_manual) == []


def test_origem_estruturada_nc_degrada_com_seguranca_se_nc_nao_existir():
    """sgi_nc_id preenchido mas NC ja nao existe mais: a funcao nao deve
    lançar excecao, so degradar para situacao/link ausentes (item 24:
    complementar sem quebrar comportamento legado)."""
    with app.test_request_context():
        ordem = {"sgi_nc_id": 999999, "op_id": None, "parada_id": None}
        origens = manutencao_service.detalhes_origem_ordem(ordem)
        assert len(origens) == 1
        assert origens[0]["tipo"] == "Nao conformidade (SGI Qualidade)"
        assert origens[0]["numero"] == "NC #999999"
        assert origens[0]["situacao"] is None
        assert origens[0]["link"] is None


# ---------------------------------------------------------------------------
# Filtro de periodo na listagem de OS (itens 40 do escopo da Etapa B)
# ---------------------------------------------------------------------------

def test_filtro_periodo_por_abertura():
    ordem_antiga, _e1 = abrir_os("EQ-PERIODO-1", data_abertura="2026-08-01")
    ordem_recente, _e2 = abrir_os("EQ-PERIODO-2", data_abertura="2026-09-10")

    dentro = manutencao_service.buscar_ordens_manutencao(
        data_inicio="2026-09-01", data_fim="2026-09-30", tipo_data="abertura")
    ids_dentro = {o["id"] for o in dentro}
    assert ordem_recente in ids_dentro
    assert ordem_antiga not in ids_dentro


def test_filtro_periodo_por_conclusao():
    ordem_id, _equipamento = abrir_os("EQ-PERIODO-CONCL")
    manutencao_service.atualizar_ordem_manutencao(ordem_id, {
        "status": "Concluida", "data_conclusao": "2026-09-15", "hora_conclusao": "10:00",
        "responsavel": "Tecnico", "diagnostico": "D", "solucao": "S",
    }, 1, "Manutencao", "manutencao")

    dentro = manutencao_service.buscar_ordens_manutencao(
        data_inicio="2026-09-15", data_fim="2026-09-15", tipo_data="conclusao")
    fora = manutencao_service.buscar_ordens_manutencao(
        data_inicio="2026-09-16", data_fim="2026-09-20", tipo_data="conclusao")
    assert ordem_id in {o["id"] for o in dentro}
    assert ordem_id not in {o["id"] for o in fora}


def test_validar_filtro_periodo_datas_invalidas_sao_ignoradas():
    _inicio, _fim, tipo, erro = manutencao_service.validar_filtro_periodo(
        {"tipo_data": "abertura", "data_inicio": "2026-09-30", "data_fim": "2026-09-01"})
    assert _inicio == "" and _fim == ""
    assert erro is not None

    _inicio2, _fim2, tipo2, erro2 = manutencao_service.validar_filtro_periodo(
        {"tipo_data": "abertura", "data_inicio": "data-invalida"})
    assert _inicio2 == ""
    assert erro2 is not None

    _inicio3, _fim3, tipo3, erro3 = manutencao_service.validar_filtro_periodo(
        {"tipo_data": "coluna_arbitraria_via_querystring"})
    assert tipo3 == "abertura"  # nunca aceita um tipo fora do dicionario fixo
    assert erro3 is not None


def test_filtro_periodo_combina_com_status_e_e_herdado_pela_impressao():
    ordem_aberta, _e1 = abrir_os("EQ-PERIODO-COMBO-1", data_abertura="2026-09-05")
    ordem_id2, _e2 = abrir_os("EQ-PERIODO-COMBO-2", data_abertura="2026-09-05")
    manutencao_service.cancelar_ordem_manutencao(
        ordem_id2, "Cancelada para teste de combinacao", 1, "Gerente", "gerencia")

    client = app.test_client()
    sessao(client, "pcp", 70)
    resposta = client.get(
        "/manutencao?aba=buscar&consultar=1&status=Aberta"
        "&data_inicio=2026-09-01&data_fim=2026-09-30&tipo_data=abertura")
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert "EQ-PERIODO-COMBO-1" in html
    assert "EQ-PERIODO-COMBO-2" not in html  # cancelada nao aparece com status=Aberta

    impressao = client.get(
        "/manutencao/ordens/imprimir?status=Aberta"
        "&data_inicio=2026-09-01&data_fim=2026-09-30&tipo_data=abertura")
    html_impressao = impressao.get_data(as_text=True)
    assert impressao.status_code == 200
    assert "EQ-PERIODO-COMBO-1" in html_impressao
    assert "Data de abertura" in html_impressao
