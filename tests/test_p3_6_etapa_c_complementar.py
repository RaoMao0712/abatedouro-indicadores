"""P3.6, Etapa C — cobertura complementar de itens do roteiro de regressão
não cobertos pela suíte da Etapa B: impacto em estoque do vínculo, fluxo
excepcional com OS vinculada, segurança do filtro de data (SQL não
dinâmico), múltiplos desdobramentos, estado ESTORNADA, filtros de data em
combinações adicionais, permissão de "Criar Requisição" reforçada no
backend, e origem NC real (não só degradação segura) através do fluxo
completo de Qualidade -> OS.

Arquivo independente (próprio DB_NAME), mesmo padrão dos demais.
"""

from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_DIR = tempfile.TemporaryDirectory()
DB_PATH = Path(TEMP_DIR.name) / "p3_6_etapa_c.db"
os.environ["DB_NAME"] = str(DB_PATH)
os.environ.pop("DATABASE_URL", None)

from app import app  # noqa: E402
from services import manutencao_service  # noqa: E402
from modules.almoxarifado import requisicoes  # noqa: E402
from modules.parceiros import services as parceiros_service  # noqa: E402
from modules.qualidade import repositories as qual_repo  # noqa: E402
from modules.qualidade import services as sgi  # noqa: E402
from modules.qualidade.plm_config import FORMULARIOS_PLM  # noqa: E402


def sessao(client, perfil, usuario_id=20):
    with client.session_transaction() as session:
        session["usuario_id"] = usuario_id
        session["nome"] = f"Usuario {perfil}"
        session["perfil"] = perfil


def criar_equipamento(codigo):
    manutencao_service.salvar_equipamento_manutencao({
        "codigo": codigo, "nome": f"Equipamento {codigo}", "setor": "Producao",
        "criticidade": "Alta", "status": "Operacional",
    })
    return manutencao_service.repo.buscar_equipamento_por_codigo(codigo)


def abrir_os(codigo, **extra):
    equipamento = criar_equipamento(codigo)
    dados = {
        "tipo": "Corretiva", "prioridade": "Media", "data_abertura": "2026-09-01",
        "descricao": "Solicitacao de manutencao", "tipo_objeto": "EQUIPAMENTO",
        "equipamento_id": str(equipamento["id"]),
    }
    dados.update(extra)
    return manutencao_service.salvar_ordem_manutencao(dados, 1, "Solicitante", "pcp"), equipamento


def criar_parceiro(razao="Solicitante Etapa C"):
    parceiros_service.criar_tabelas_parceiros()
    return parceiros_service.salvar_parceiro(
        {"tipo_pessoa": "PF", "razao_social": razao, "papeis": ["COLABORADOR_CLT"]},
        usuario="Teste", perfil="admin")


def criar_insumo(descricao, categoria="EPI", origem="REQUISICAO_ALMOXARIFADO", saldo=50):
    from modules.almoxarifado import services as almox_service
    almox_service.criar_tabelas_estoque_almoxarifado()
    conn = manutencao_service.repo.conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO almoxarifado_insumos (descricao, categoria, unidade, ativo, origem_baixa) "
        "VALUES (?, ?, 'Un', 'Sim', ?)", (descricao, categoria, origem))
    conn.commit()
    insumo_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO almoxarifado_lotes (insumo_id, data_entrada, lote, quantidade_inicial, "
        "quantidade_atual, valor_unitario, valor_total, status, versao) "
        "VALUES (?, '2026-09-01', 'L-EC', ?, ?, 1, ?, 'Aberto', 0)",
        (insumo_id, saldo, saldo, saldo))
    conn.commit()
    conn.close()
    return insumo_id


def emitir(parceiro_id, insumo_id, quantidade="1", *, ordem_servico_id=None, chave="chave", usuario=None):
    dados = {"parceiro_id": str(parceiro_id), "solicitante_papel": "COLABORADOR_CLT",
             "setor": "Producao", "finalidade": "Uso operacional"}
    if ordem_servico_id:
        dados["ordem_servico_id"] = str(ordem_servico_id)
    return requisicoes.emitir_requisicao(
        dados, [{"insumo_id": insumo_id, "quantidade": quantidade}],
        usuario=usuario or {"id": 1, "nome": "PCP", "perfil": "pcp"}, idempotency_key=chave)


# ---------------------------------------------------------------------------
# Item 20 — vinculo nao afeta estoque
# ---------------------------------------------------------------------------

def test_vinculo_nao_altera_estoque_reserva_nem_versao_alem_do_esperado():
    ordem_id, _e = abrir_os("EQ-EC-ESTOQUE")
    parceiro = criar_parceiro()
    insumo_id = criar_insumo("Insumo Estoque EC", saldo=20)

    resultado = emitir(parceiro, insumo_id, "5", chave="req-estoque")
    detalhe_antes = requisicoes.buscar_requisicao(resultado["id"])
    item_antes = detalhe_antes["itens"][0]

    conn = manutencao_service.repo.conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(quantidade_atual) AS s FROM almoxarifado_lotes WHERE insumo_id=?", (insumo_id,))
    saldo_fisico_antes = cursor.fetchone()["s"]
    cursor.execute("SELECT COUNT(*) AS c FROM almoxarifado_movimentacoes")
    movimentos_antes = cursor.fetchone()["c"]
    conn.close()

    requisicoes.vincular_a_ordem_servico(
        resultado["id"], ordem_id, usuario={"id": 2, "nome": "Gerencia", "perfil": "gerencia"},
        idempotency_key="vinculo-estoque")

    detalhe_depois = requisicoes.buscar_requisicao(resultado["id"])
    item_depois = detalhe_depois["itens"][0]

    conn = manutencao_service.repo.conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(quantidade_atual) AS s FROM almoxarifado_lotes WHERE insumo_id=?", (insumo_id,))
    saldo_fisico_depois = cursor.fetchone()["s"]
    cursor.execute("SELECT COUNT(*) AS c FROM almoxarifado_movimentacoes")
    movimentos_depois = cursor.fetchone()["c"]
    conn.close()

    assert saldo_fisico_depois == saldo_fisico_antes  # nenhum movimento fisico
    assert movimentos_depois == movimentos_antes  # nenhuma linha nova em movimentacoes
    assert item_depois["quantidade_reservada"] == item_antes["quantidade_reservada"]  # reserva intacta
    assert item_depois["quantidade_entregue"] == item_antes["quantidade_entregue"]
    assert detalhe_depois["versao"] == detalhe_antes["versao"] + 1  # so o vinculo incrementou a versao
    assert detalhe_depois["status"] == detalhe_antes["status"]  # status da requisicao nao muda


# ---------------------------------------------------------------------------
# Item 19 — fluxo excepcional (MP/Embalagem) com OS vinculada
# ---------------------------------------------------------------------------

def test_fluxo_excepcional_com_os_continua_exigindo_admin_justificativa_e_aprovador_distinto():
    ordem_id, _e = abrir_os("EQ-EC-EXCECAO")
    parceiro = criar_parceiro("Solicitante Excecao EC")
    insumo_excepcional = criar_insumo("Insumo Excecao EC", categoria="Embalagem", origem="ORDEM_PRODUCAO", saldo=100)

    # Perfil comum (pcp) tentando emitir item excepcional com OS vinculada: continua proibido.
    try:
        emitir(parceiro, insumo_excepcional, "5", ordem_servico_id=ordem_id, chave="exc-pcp-negado")
        assert False, "pcp nao pode emitir item excepcional, com ou sem OS"
    except PermissionError as erro:
        assert "Administrador" in str(erro)

    # Admin sem justificativa: continua proibido.
    try:
        emitir(parceiro, insumo_excepcional, "5", ordem_servico_id=ordem_id, chave="exc-sem-just",
               usuario={"id": 9, "nome": "Admin A", "perfil": "admin"})
        assert False, "admin sem justificativa deveria falhar"
    except ValueError as erro:
        assert "justificativa" in str(erro)

    # Admin com justificativa: emite, com OS vinculada, ainda AGUARDANDO_APROVACAO.
    dados = {"parceiro_id": str(parceiro), "solicitante_papel": "COLABORADOR_CLT",
             "setor": "Producao", "finalidade": "Uso operacional", "justificativa": "Uso emergencial",
             "ordem_servico_id": str(ordem_id)}
    resultado = requisicoes.emitir_requisicao(
        dados, [{"insumo_id": insumo_excepcional, "quantidade": "5"}],
        usuario={"id": 9, "nome": "Admin A", "perfil": "admin"}, idempotency_key="exc-ok")
    assert resultado["status"] == "AGUARDANDO_APROVACAO"
    assert requisicoes.buscar_requisicao(resultado["id"])["ordem_servico_id"] == ordem_id

    # O proprio emissor nao pode aprovar a propria excecao, mesmo com OS vinculada.
    try:
        requisicoes.decidir_excecao(
            resultado["id"], aprovar=True, motivo="", usuario={"id": 9, "nome": "Admin A", "perfil": "admin"},
            versao=0, idempotency_key="exc-autoaprovacao")
        assert False, "autoaprovacao deveria ser rejeitada"
    except PermissionError as erro:
        assert "própria exceção" in str(erro) or "propria excecao" in str(erro)

    # Aprovador distinto aprova normalmente; vinculo com OS continua intacto.
    aprovada = requisicoes.decidir_excecao(
        resultado["id"], aprovar=True, motivo="Conferido", usuario={"id": 10, "nome": "Admin B", "perfil": "admin"},
        versao=0, idempotency_key="exc-aprovada")
    assert aprovada["status"] == "EMITIDA"
    assert aprovada["ordem_servico_id"] == ordem_id


# ---------------------------------------------------------------------------
# Item 17 — Requisicao ESTORNADA nao pode ser vinculada
# ---------------------------------------------------------------------------

def test_requisicao_estornada_nao_pode_ser_vinculada():
    ordem_id, _e = abrir_os("EQ-EC-ESTORNO")
    parceiro = criar_parceiro("Solicitante Estorno EC")
    insumo_id = criar_insumo("Insumo Estorno EC", saldo=10)

    resultado = emitir(parceiro, insumo_id, "4", chave="req-estorno")
    item_id = requisicoes.buscar_requisicao(resultado["id"])["itens"][0]["id"]
    baixada = requisicoes.confirmar_requisicao(
        resultado["id"], [{"item_id": item_id, "quantidade": "4"}], documento_confirmado=True,
        usuario={"id": 1, "nome": "PCP", "perfil": "pcp"}, versao=0, idempotency_key="conf-estorno-ec")
    estornada = requisicoes.estornar_requisicao(
        resultado["id"], motivo="Documento cancelado", usuario={"id": 3, "nome": "Gerencia", "perfil": "gerencia"},
        versao=baixada["versao"], idempotency_key="estorno-ec")
    assert estornada["status"] == "ESTORNADA"

    try:
        requisicoes.vincular_a_ordem_servico(
            resultado["id"], ordem_id, usuario={"id": 4, "nome": "Gerencia", "perfil": "gerencia"},
            idempotency_key="vinculo-estornada")
        assert False, "requisicao estornada nao pode ser vinculada"
    except ValueError as erro:
        assert "estornada" in str(erro).lower() or "cancelada" in str(erro).lower()

    vinculaveis = {r["id"] for r in requisicoes.listar_requisicoes_vinculaveis()}
    assert resultado["id"] not in vinculaveis


# ---------------------------------------------------------------------------
# Item 27 — multiplos desdobramentos
# ---------------------------------------------------------------------------

def test_uma_os_pode_ter_dois_desdobramentos_sem_sobrescrever():
    ordem_id, _e = abrir_os("EQ-EC-MULTI")
    parceiro = criar_parceiro("Solicitante Multi EC")
    insumo_1 = criar_insumo("Insumo Multi 1 EC")
    insumo_2 = criar_insumo("Insumo Multi 2 EC")

    req_a = emitir(parceiro, insumo_1, "1", ordem_servico_id=ordem_id, chave="multi-a")
    req_b = emitir(parceiro, insumo_2, "1", chave="multi-b")
    requisicoes.vincular_a_ordem_servico(
        req_b["id"], ordem_id, usuario={"id": 5, "nome": "Gerencia", "perfil": "gerencia"},
        idempotency_key="multi-vinculo-b")

    desdobramentos = requisicoes.listar_requisicoes_por_ordem_servico(ordem_id)
    ids = {r["id"] for r in desdobramentos}
    assert ids == {req_a["id"], req_b["id"]}

    client = app.test_client()
    sessao(client, "pcp", 90)
    html = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
    assert req_a["numero"] in html
    assert req_b["numero"] in html


# ---------------------------------------------------------------------------
# Itens 31/30 — seguranca e robustez do filtro de data via rota
# ---------------------------------------------------------------------------

def test_tipo_data_arbitrario_via_querystring_nao_vira_sql_e_nao_quebra():
    abrir_os("EQ-EC-FILTRO-SEG")
    client = app.test_client()
    sessao(client, "pcp", 91)
    resposta = client.get(
        "/manutencao?aba=buscar&consultar=1"
        "&tipo_data=" + "coluna_inexistente_ou_malintencionada"
        "&data_inicio=2026-09-01&data_fim=2026-09-30")
    assert resposta.status_code == 200
    assert "invalido" in resposta.get_data(as_text=True).lower() or "inválido" in resposta.get_data(as_text=True)
    # A tabela continua intacta e consultavel (nenhum SQL destrutivo rodou).
    assert manutencao_service.repo.buscar_ordem_por_id(1) is not None


def test_intervalo_invalido_via_rota_nao_gera_500():
    abrir_os("EQ-EC-FILTRO-INV")
    client = app.test_client()
    sessao(client, "pcp", 92)
    resposta = client.get(
        "/manutencao?aba=buscar&consultar=1&data_inicio=2026-09-30&data_fim=2026-09-01")
    assert resposta.status_code == 200


# ---------------------------------------------------------------------------
# Itens 28/29 — combinacoes adicionais de filtro de periodo
# ---------------------------------------------------------------------------

def test_filtro_periodo_apenas_inicio_e_apenas_fim():
    ordem_meio, _e1 = abrir_os("EQ-EC-SOMENTE-1", data_abertura="2026-09-15")
    ordem_antes, _e2 = abrir_os("EQ-EC-SOMENTE-2", data_abertura="2026-09-01")

    so_inicio = manutencao_service.buscar_ordens_manutencao(data_inicio="2026-09-10", tipo_data="abertura")
    ids_so_inicio = {o["id"] for o in so_inicio}
    assert ordem_meio in ids_so_inicio
    assert ordem_antes not in ids_so_inicio

    so_fim = manutencao_service.buscar_ordens_manutencao(data_fim="2026-09-10", tipo_data="abertura")
    ids_so_fim = {o["id"] for o in so_fim}
    assert ordem_antes in ids_so_fim
    assert ordem_meio not in ids_so_fim


def test_filtro_periodo_intervalo_exato_de_um_dia_e_inclusivo():
    ordem_id, _e = abrir_os("EQ-EC-UMDIA", data_abertura="2026-09-20")
    dentro = manutencao_service.buscar_ordens_manutencao(
        data_inicio="2026-09-20", data_fim="2026-09-20", tipo_data="abertura")
    assert ordem_id in {o["id"] for o in dentro}


def test_filtro_conclusao_nao_mostra_os_sem_data_conclusao():
    ordem_aberta, _e = abrir_os("EQ-EC-SEM-CONCLUSAO")
    resultado = manutencao_service.buscar_ordens_manutencao(
        data_inicio="2026-01-01", data_fim="2026-12-31", tipo_data="conclusao")
    assert ordem_aberta not in {o["id"] for o in resultado}


# ---------------------------------------------------------------------------
# Item 36 — permissao de "Criar Requisicao" reforcada no backend
# ---------------------------------------------------------------------------

def test_criar_requisicao_a_partir_da_os_nega_perfil_sem_permissao_de_emissao():
    ordem_id, _e = abrir_os("EQ-EC-PERM-CRIAR")
    parceiro = criar_parceiro("Solicitante Permissao EC")
    insumo_id = criar_insumo("Insumo Permissao EC")

    client = app.test_client()
    sessao(client, "manutencao", 93)  # nao esta em PERFIS_EMISSAO (admin/pcp)
    resposta = client.post("/almoxarifado/requisicoes/nova", data={
        "idempotency_key": "perm-negada", "parceiro_id": str(parceiro),
        "solicitante_papel": "COLABORADOR_CLT", "setor": "Producao", "finalidade": "Uso",
        "insumo_id": str(insumo_id), "quantidade": "1", "ordem_servico_id": str(ordem_id),
    })
    assert resposta.status_code == 302  # bloqueado pelo perfil_permitido("pcp") da rota
    assert requisicoes.listar_requisicoes_por_ordem_servico(ordem_id) == []


# ---------------------------------------------------------------------------
# Item 22 — Origem NC real (nao so degradacao segura), fluxo completo Qualidade -> OS
# ---------------------------------------------------------------------------

def _preparar_cadastros_qualidade():
    try:
        qual_repo.inserir_setor("Producao")
    except Exception:
        pass
    setor = next(item for item in qual_repo.listar_setores() if item["nome"] == "Producao")
    if not qual_repo.listar_locais_por_setor(setor_id=setor["id"]):
        qual_repo.inserir_local("Ambiente", "Ambiente EC", "Producao", "Producao e recepcao", setor_id=setor["id"])
    if not qual_repo.listar_equipamentos():
        criar_equipamento("BAL-EC")
    return {
        "setor": setor,
        "ambientes": [item for item in qual_repo.listar_locais_por_setor(setor_id=setor["id"]) if item["tipo"] == "Ambiente"],
        "equipamento": qual_repo.listar_equipamentos()[0],
    }


def _form_nc(cadastros):
    ficha = FORMULARIOS_PLM["plm05_condensacao"]
    vinculo = ficha["vinculos"][0]
    dados = {"data": "2026-09-10", "setor_id": str(cadastros["setor"]["id"]), "responsavel": "Monitor",
             "vinculo_tipo": vinculo, "observacoes": "Rotina"}
    if vinculo == "Equipamento":
        dados["equipamento_id"] = str(cadastros["equipamento"]["id"])
    else:
        dados["local_id"] = str(cadastros["ambientes"][0]["id"])
    for codigo, _rotulo, campo in ficha["itens"]:
        if campo == "texto":
            dados[f"valor_{codigo}"] = "Verificado"
        elif campo == "lux":
            dados[f"valor_{codigo}"] = "100"  # fora do padrao -> gera NC
        else:
            dados[f"resultado_{codigo}"] = "NC"
    dados.update({"resultado_manutencao": "NC", "criticidade_manutencao": "ALTA",
                  "observacao_manutencao": "Manutencao pendente", "acao_manutencao": "Abrir OS"})
    return dados


def test_origem_nc_real_aparece_estruturada_e_navegacao_nc_para_os_continua():
    cadastros = _preparar_cadastros_qualidade()
    form = _form_nc(cadastros)
    vid = sgi.salvar_verificacao_sgi("plm05_condensacao", form, 2, "PCP")
    nc = qual_repo.buscar_verificacao(vid)[2][0]
    nc_detalhe = qual_repo.buscar_nc(nc["id"])

    ordem_id = manutencao_service.criar_ordem_por_nc(nc_detalhe, {
        "equipamento_id": str(cadastros["equipamento"]["id"]), "usuario_id": "2",
        "data_abertura": "2026-09-10", "descricao": "Calibrar balanca",
    }, "PCP")

    assert qual_repo.buscar_nc(nc["id"])["ordem_id"] == ordem_id
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["sgi_nc_id"] == nc["id"]

    with app.test_request_context():
        origens = manutencao_service.detalhes_origem_ordem(ordem)
    assert len(origens) == 1
    assert origens[0]["tipo"] == "Nao conformidade (SGI Qualidade)"
    assert origens[0]["numero"] == f"NC #{nc['id']}"
    assert origens[0]["situacao"] is not None  # situacao real da NC, nao degradacao
    assert origens[0]["link"] is not None

    # Navegacao NC -> OS (ja existente, preservada) continua funcionando.
    client = app.test_client()
    sessao(client, "qualidade", 3)
    html_verificacao = client.get(f"/sgi/qualidade/verificacoes/{vid}").get_data(as_text=True)
    assert f"OS #{ordem_id}" in html_verificacao or str(ordem_id) in html_verificacao

    # Detalhe da OS mostra a secao de Documentos Relacionados com a origem.
    sessao(client, "pcp", 94)
    html_os = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
    assert "Documentos Relacionados" in html_os
    assert f"NC #{nc['id']}" in html_os


# ---------------------------------------------------------------------------
# Itens 23/24/41 — Origem OP/Parada real (nao dict falso) + encerramento da parada
# ---------------------------------------------------------------------------

def test_origem_op_e_parada_reais_e_encerramento_da_parada_ao_concluir_os():
    equipamento = criar_equipamento("EQ-EC-PARADA")
    conn = manutencao_service.repo.conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO apontamentos_paradas (op_id, data, setor, motivo, hora_inicio, horas_paradas) "
        "VALUES (?, ?, ?, ?, ?, ?)", (321, "2026-09-10", "Producao", "Falha mecanica", "08:00", 0))
    conn.commit()
    parada_id = cursor.lastrowid
    conn.close()

    ordem_id = manutencao_service.criar_ordem_por_parada(
        parada_id, 321, equipamento["id"], "Producao", "Falha mecanica",
        "2026-09-10", "08:00", "Producao Usuario", "Parada nao planejada")

    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["op_id"] == 321
    assert ordem["parada_id"] == parada_id

    with app.test_request_context():
        origens = manutencao_service.detalhes_origem_ordem(ordem)
    tipos = {o["tipo"] for o in origens}
    assert tipos == {"Ordem de Producao", "Parada de producao"}
    origem_op = next(o for o in origens if o["tipo"] == "Ordem de Producao")
    assert origem_op["numero"] == "OP 321"
    assert origem_op["link"] is not None
    origem_parada = next(o for o in origens if o["tipo"] == "Parada de producao")
    assert origem_parada["numero"] == f"Parada #{parada_id}"

    # Concluir a OS deve encerrar a parada vinculada (callback preexistente, preservado).
    manutencao_service.atualizar_ordem_manutencao(ordem_id, {
        "status": "Concluida", "data_conclusao": "2026-09-11", "hora_conclusao": "09:00",
        "responsavel": "Tecnico", "diagnostico": "D", "solucao": "S",
    }, 1, "Manutencao", "manutencao")

    conn = manutencao_service.repo.conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT data_fim, encerrada_por_manutencao FROM apontamentos_paradas WHERE id=?", (parada_id,))
    parada = cursor.fetchone()
    conn.close()
    assert parada["data_fim"] == "2026-09-11"
    assert parada["encerrada_por_manutencao"] == "Sim"


def test_os_manual_sem_vinculo_estrutural_nao_mostra_link_inexistente():
    ordem_id, _e = abrir_os("EQ-EC-MANUAL")
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert not ordem["sgi_nc_id"] and not ordem["op_id"] and not ordem["parada_id"]

    with app.test_request_context():
        origens = manutencao_service.detalhes_origem_ordem(ordem)
    assert origens == []

    client = app.test_client()
    sessao(client, "pcp", 95)
    html = client.get(f"/manutencao/ordem/{ordem_id}").get_data(as_text=True)
    assert "Documentos Relacionados" in html
    assert "Manual" in html or "sem vínculo" in html.lower() or "sem vinculo" in html.lower()
