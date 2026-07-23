from pathlib import Path
import os
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_DIR = tempfile.TemporaryDirectory()
DB_PATH = Path(TEMP_DIR.name) / "sgi.db"
os.environ["DB_NAME"] = str(DB_PATH)

from app import app
from database import conectar
from modules.qualidade import repositories as repo
from modules.qualidade import services as sgi
from modules.qualidade.plm_config import FORMULARIOS_PLM
from services import manutencao_service


def sessao(client, perfil, usuario_id=10):
    with client.session_transaction() as session:
        session["usuario_id"] = usuario_id
        session["nome"] = f"Teste {perfil}"
        session["perfil"] = perfil


def preparar_cadastros():
    try:
        repo.inserir_setor("Producao")
    except Exception:
        pass
    setor = next(item for item in repo.listar_setores() if item["nome"] == "Producao")
    if not repo.listar_locais_por_setor(setor_id=setor["id"]):
        for indice, classificacao in enumerate((
            "Camara fria e estocagem", "Producao e recepcao",
            "Inspecao oficial e seguranca critica"), start=1):
            repo.inserir_local("Ambiente", f"Ambiente {indice}", "Producao", classificacao, setor_id=setor["id"])
        repo.inserir_local("Estrutura", "Barreira Sanitaria", "Producao", None, setor_id=setor["id"])
    if not repo.listar_equipamentos():
        manutencao_service.salvar_equipamento_manutencao({
            "codigo": "BAL-01", "nome": "Balanca de teste", "setor": "Producao",
            "criticidade": "Alta", "status": "Operacional",
        })
    locais = repo.listar_locais_por_setor(setor_id=setor["id"])
    return {
        "ambientes": [item for item in locais if item["tipo"] == "Ambiente"],
        "estrutura": [item for item in locais if item["tipo"] == "Estrutura"][0],
        "equipamento": repo.listar_equipamentos()[0],
        "setor": setor,
    }


def form_conforme(tipo, cadastros, lux=600):
    ficha = FORMULARIOS_PLM[tipo]
    vinculo = ficha["vinculos"][0]
    dados = {"data": "2026-07-20", "setor_id": str(cadastros["setor"]["id"]), "responsavel": "Monitor",
             "vinculo_tipo": vinculo, "observacoes": "Rotina diaria"}
    if vinculo == "Equipamento":
        dados["equipamento_id"] = str(cadastros["equipamento"]["id"])
    elif vinculo == "Estrutura":
        dados["local_id"] = str(cadastros["estrutura"]["id"])
    else:
        dados["local_id"] = str(cadastros["ambientes"][0]["id"])
    for codigo, _, campo in ficha["itens"]:
        if campo == "texto": dados[f"valor_{codigo}"] = "Verificado"
        elif campo == "lux": dados[f"valor_{codigo}"] = str(lux)
        else: dados[f"resultado_{codigo}"] = "C"
    return dados


def form_plm01(competencia, linhas):
    dados = {
        "competencia": competencia,
        "linha_id[]": [],
        "ordem[]": [],
        "data_linha[]": [],
        "setor_id[]": [],
        "tipo_item[]": [],
        "descricao_atividade[]": [],
        "higienizacao_apos_reparo[]": [],
        "condicao_final[]": [],
    }
    for indice, linha in enumerate(linhas, start=1):
        dados["linha_id[]"].append(str(linha.get("id", "")))
        dados["ordem[]"].append(str(linha.get("ordem", indice)))
        dados["data_linha[]"].append(linha.get("data", ""))
        dados["setor_id[]"].append(str(linha.get("setor_id", "")))
        dados["tipo_item[]"].append(linha.get("tipo_item", ""))
        dados["descricao_atividade[]"].append(linha.get("descricao_atividade", ""))
        dados["higienizacao_apos_reparo[]"].append(linha.get("higienizacao_apos_reparo", ""))
        dados["condicao_final[]"].append(linha.get("condicao_final", ""))
    return dados


def test_permissoes_central():
    for perfil in ("qualidade", "pcp", "gerencia"):
        client = app.test_client(); sessao(client, perfil)
        assert client.get("/sgi/qualidade").status_code == 200
    for perfil in ("producao", "desconhecido"):
        client = app.test_client(); sessao(client, perfil)
        resposta = client.get("/sgi/qualidade")
        assert resposta.status_code == 302


def test_vinculo_obrigatorio_e_seis_controles():
    cadastros = preparar_cadastros()
    invalido = form_conforme("plm03_iluminacao", cadastros)
    invalido.pop("local_id")
    try:
        sgi.salvar_verificacao_sgi("plm03_iluminacao", invalido, 1, "Teste")
        assert False, "deveria bloquear verificacao sem vinculo"
    except ValueError as erro:
        assert "Vincule" in str(erro)
    tipos_legados = [tipo for tipo in FORMULARIOS_PLM if not tipo.startswith("plm01")]
    ids = [sgi.salvar_verificacao_sgi(tipo, form_conforme(tipo, cadastros), 1, "Teste")
           for tipo in tipos_legados]
    assert len(ids) == 4 and len(set(ids)) == 4


def test_limites_lux_110_220_540():
    cadastros = preparar_cadastros()
    esperados = [110, 220, 540]
    for ambiente, limite in zip(cadastros["ambientes"], esperados):
        form = form_conforme("plm03_iluminacao", cadastros, lux=limite - 1)
        form["local_id"] = str(ambiente["id"])
        form["criticidade_iluminancia"] = "ALTA"
        verificacao_id = sgi.salvar_verificacao_sgi("plm03_iluminacao", form, 1, "Teste")
        _, itens, ncs, _, _ = repo.buscar_verificacao(verificacao_id)
        assert itens[0]["parametro_numerico"] == limite
        assert itens[0]["resultado"] == "NC" and len(ncs) == 1


def test_na_ventilacao_e_acao_imediata_plm02():
    cadastros = preparar_cadastros()
    ventilacao = form_conforme("plm04_ventilacao", cadastros)
    ventilacao["resultado_exaustor"] = "NA"
    vid = sgi.salvar_verificacao_sgi("plm04_ventilacao", ventilacao, 1, "Teste")
    assert any(item["resultado"] == "NA" for item in repo.buscar_verificacao(vid)[1])

    plm02 = form_conforme("plm02_sanitarios", cadastros)
    plm02.update({"resultado_sabao": "NC", "reposicao_sabao": "Sim",
                  "pessoa_acionada_sabao": "Almoxarife", "observacao_sabao": "Sem sabao"})
    vid = sgi.salvar_verificacao_sgi("plm02_sanitarios", plm02, 1, "Teste")
    _, _, ncs, acoes, _ = repo.buscar_verificacao(vid)
    assert ncs[0]["criado_por"] == 1 and ncs[0]["criado_por_nome"] == "Teste"
    assert ncs[0]["situacao"] == "Aguardando reposicao"
    assert acoes[0]["pessoa_acionada"] == "Almoxarife"

    client = app.test_client(); sessao(client, "pcp")
    bloqueado = client.post(f"/sgi/qualidade/reposicoes/{acoes[0]['id']}/confirmar",
        data={"resultado": "C", "nc_id": ncs[0]["id"], "verificacao_id": vid})
    assert bloqueado.status_code == 302
    assert repo.buscar_verificacao(vid)[3][0]["status"] == "Aguardando reposicao"
    sessao(client, "admin")
    client.post(f"/sgi/qualidade/reposicoes/{acoes[0]['id']}/confirmar",
        data={"resultado": "C", "nc_id": ncs[0]["id"], "verificacao_id": vid})
    assert repo.buscar_verificacao(vid)[3][0]["status"] == "Aguardando reposicao"
    sessao(client, "qualidade")
    ok = client.post(f"/sgi/qualidade/reposicoes/{acoes[0]['id']}/confirmar",
        data={"resultado": "C", "observacao": "Reposto", "nc_id": ncs[0]["id"], "verificacao_id": vid})
    assert ok.status_code == 302
    assert repo.buscar_verificacao(vid)[2][0]["situacao"] == "NC corrigida imediatamente"


def test_os_bidirecional_conclusao_eficacia_e_encerramento():
    cadastros = preparar_cadastros()
    form = form_conforme("plm05_condensacao", cadastros)
    form.update({"resultado_manutencao": "NC", "criticidade_manutencao": "ALTA",
                 "observacao_manutencao": "Manutencao pendente", "acao_manutencao": "Abrir OS"})
    vid = sgi.salvar_verificacao_sgi("plm05_condensacao", form, 2, "PCP")
    nc = repo.buscar_verificacao(vid)[2][0]
    nc_detalhe = repo.buscar_nc(nc["id"])
    ordem_id = manutencao_service.criar_ordem_por_nc(nc_detalhe, {
        "equipamento_id": str(cadastros["equipamento"]["id"]), "usuario_id": "2",
        "data_abertura": "2026-07-20", "descricao": "Calibrar balanca",
    }, "PCP")
    assert repo.buscar_nc(nc["id"])["ordem_id"] == ordem_id
    ordem = manutencao_service.repo.buscar_ordem_por_id(ordem_id)
    assert ordem["sgi_nc_id"] == nc["id"]
    manutencao_service.atualizar_ordem_manutencao(ordem_id, {
        "status": "Concluida", "data_conclusao": "2026-07-21", "hora_conclusao": "10:00"
    })
    assert repo.buscar_nc(nc["id"])["situacao"] == "Aguardando validacao da Qualidade"
    try:
        sgi.encerrar_nc_sgi(nc["id"], 3, "Qualidade")
        assert False, "nao pode encerrar antes da eficacia"
    except ValueError:
        pass
    client = app.test_client(); sessao(client, "pcp", 2)
    client.post(f"/sgi/qualidade/ncs/{nc['id']}/eficacia", data={
        "verificacao_id": vid, "resultado": "Eficaz", "observacao": "Tentativa PCP"})
    assert repo.buscar_nc(nc["id"])["eficacia_resultado"] is None
    sessao(client, "qualidade", 3)
    client.post(f"/sgi/qualidade/ncs/{nc['id']}/eficacia", data={
        "verificacao_id": vid, "resultado": "Eficaz", "observacao": "Calibracao conferida"})
    sessao(client, "pcp", 2)
    client.post(f"/sgi/qualidade/ncs/{nc['id']}/encerrar", data={"verificacao_id": vid})
    assert repo.buscar_nc(nc["id"])["situacao"] != "Encerrada"
    sessao(client, "qualidade", 3)
    client.post(f"/sgi/qualidade/ncs/{nc['id']}/encerrar", data={"verificacao_id": vid})
    assert repo.buscar_nc(nc["id"])["situacao"] == "Encerrada"


def test_criticidade_gerencia_historico_e_consolidado():
    cadastros = preparar_cadastros()
    form = form_conforme("plm05_condensacao", cadastros)
    form.update({"resultado_condensacao": "NC", "criticidade_condensacao": "CRITICA",
                 "observacao_condensacao": "Gotejamento sobre area de produto"})
    vid = sgi.salvar_verificacao_sgi("plm05_condensacao", form, 4, "Gerencia")
    nc = repo.buscar_verificacao(vid)[2][0]
    client = app.test_client(); sessao(client, "pcp")
    client.post(f"/sgi/qualidade/ncs/{nc['id']}/decisao-gerencia",
                data={"verificacao_id": vid, "decisao": "Autorizar interrupcao", "justificativa": "Risco"})
    assert repo.buscar_nc(nc["id"])["gerencia_decisao"] is None
    sessao(client, "gerencia")
    resposta = client.post(f"/sgi/qualidade/ncs/{nc['id']}/decisao-gerencia",
                data={"verificacao_id": vid, "decisao": "Autorizar interrupcao", "justificativa": "Risco de contaminacao"})
    assert resposta.status_code == 302
    assert repo.buscar_nc(nc["id"])["gerencia_decisao"] == "Autorizar interrupcao"
    eventos = repo.buscar_verificacao(vid)[4]
    assert any(evento["evento"] == "Decisao da Gerencia" for evento in eventos)
    assert client.get("/sgi/qualidade/consolidado?mes=2026-07").status_code == 200


def test_plm01_manual_competencia_linhas_pesquisa_e_impressao():
    try:
        repo.inserir_setor("Teste SGI")
    except Exception:
        pass
    setor = next(item for item in repo.listar_setores() if item["nome"] == "Teste SGI")
    contexto_vazio = sgi.contexto_plm01_mensal({"competencia": "2026-06"})
    assert len(contexto_vazio["linhas"]) == 18
    assert not any(linha["id"] for linha in contexto_vazio["linhas"])

    form = form_plm01("2026-06", [
        {
            "ordem": 1,
            "data": "2026-06-02",
            "setor_id": setor["id"],
            "tipo_item": "Instalacoes",
            "descricao_atividade": "Reparo em porta da camara",
            "higienizacao_apos_reparo": "Sim",
            "condicao_final": "C",
        },
        {
            "ordem": 2,
            "data": "2026-06-03",
            "setor_id": setor["id"],
            "tipo_item": "Equipamentos",
            "descricao_atividade": "Afericao de termometro",
            "higienizacao_apos_reparo": "Nao",
            "condicao_final": "NC",
        },
        {"ordem": 3},
    ])
    ficha_id = sgi.salvar_plm01_mensal(form, 11, "Qualidade")
    ficha = repo.buscar_plm01_ficha("2026-06")
    assert ficha["id"] == ficha_id
    linhas = repo.listar_plm01_linhas(ficha_id)
    assert len(linhas) == 2
    assert [linha["ordem"] for linha in linhas] == [1, 2]

    contexto_junho = sgi.contexto_plm01_mensal({"competencia": "2026-06"})
    assert len([linha for linha in contexto_junho["linhas"] if linha["id"]]) == 2
    contexto_julho = sgi.contexto_plm01_mensal({"competencia": "2026-07"})
    assert len(contexto_julho["linhas"]) == 18
    assert not any(linha["id"] for linha in contexto_julho["linhas"])
    assert len([linha for linha in sgi.contexto_plm01_mensal({"competencia": "2026-06"})["linhas"] if linha["id"]]) == 2

    terceira = {
        "ordem": 19,
        "data": "2026-06-19",
        "setor_id": setor["id"],
        "tipo_item": "Equipamentos",
        "descricao_atividade": "Calibracao de balanca",
        "higienizacao_apos_reparo": "Sim",
        "condicao_final": "C",
    }
    linhas_form = [dict(row) for row in linhas] + [terceira]
    form_19 = form_plm01("2026-06", linhas_form)
    sgi.salvar_plm01_mensal(form_19, 11, "Qualidade")
    assert len(repo.listar_plm01_linhas(ficha_id)) == 3

    central = sgi.contexto_central_sgi({
        "mes": "2026-06",
        "setor_id": str(setor["id"]),
        "tipo_item": "Equipamentos",
        "condicao_final": "NC",
    })
    assert any(item["id"] == ficha_id for item in central["plm01_fichas"])

    client = app.test_client(); sessao(client, "qualidade")
    assert client.get("/sgi/qualidade/plm01/imprimir?competencia=2026-06").status_code == 200


def test_plm01_rejeita_linha_parcial_data_fora_e_edita_com_historico_automatico():
    cadastros = preparar_cadastros()
    setor = cadastros["setor"]
    parcial = form_plm01("2026-06", [{"ordem": 1, "data": "2026-06-02", "setor_id": setor["id"]}])
    try:
        sgi.salvar_plm01_mensal(parcial, 1, "Teste")
        assert False, "deveria rejeitar linha parcial"
    except ValueError as erro:
        assert "Linha 1" in str(erro)

    fora = form_plm01("2026-06", [{
        "ordem": 1, "data": "2026-07-02", "setor_id": setor["id"],
        "tipo_item": "Instalacoes", "descricao_atividade": "Reparo",
        "higienizacao_apos_reparo": "Sim", "condicao_final": "C",
    }])
    try:
        sgi.salvar_plm01_mensal(fora, 1, "Teste")
        assert False, "deveria rejeitar data fora da competencia"
    except ValueError as erro:
        assert "competencia selecionada" in str(erro)

    ok = form_plm01("2026-08", [{
        "ordem": 1, "data": "2026-08-02", "setor_id": setor["id"],
        "tipo_item": "Instalacoes", "descricao_atividade": "Reparo",
        "higienizacao_apos_reparo": "Sim", "condicao_final": "C",
    }])
    ficha_id = sgi.salvar_plm01_mensal(ok, 1, "Teste")
    linha = repo.listar_plm01_linhas(ficha_id)[0]
    alterado = form_plm01("2026-08", [{
        "id": linha["id"], "ordem": 1, "data": "2026-08-02", "setor_id": setor["id"],
        "tipo_item": "Instalacoes", "descricao_atividade": "Reparo corrigido",
        "higienizacao_apos_reparo": "Sim", "condicao_final": "C",
    }])
    try:
        sgi.salvar_plm01_mensal(alterado, 1, "Teste")
    except ValueError as erro:
        assert False, f"nao deveria exigir justificativa manual: {erro}"
    historico = repo.listar_plm01_historico(ficha_id)
    assert historico and historico[0]["usuario_nome"] == "Teste"


def test_rejeita_setor_e_vinculo_manipulados():
    cadastros = preparar_cadastros()
    form = form_conforme("plm03_iluminacao", cadastros)
    form["setor_id"] = "999999"
    try:
        sgi.salvar_verificacao_sgi("plm03_iluminacao", form, 1, "Teste")
        assert False, "deveria rejeitar setor manipulado"
    except ValueError as erro:
        assert "setor cadastrado" in str(erro)

    try:
        repo.inserir_setor("Outro SGI")
    except Exception:
        pass
    outro = next(item for item in repo.listar_setores() if item["nome"] == "Outro SGI")
    form = form_conforme("plm03_iluminacao", cadastros)
    form["setor_id"] = str(outro["id"])
    try:
        sgi.salvar_verificacao_sgi("plm03_iluminacao", form, 1, "Teste")
        assert False, "deveria rejeitar local de outro setor"
    except ValueError as erro:
        assert "nao pertence ao setor" in str(erro)


def test_plm01_antigo_redireciona_para_ficha_manual_e_plm02_05_sem_regressao():
    cadastros = preparar_cadastros()
    client = app.test_client(); sessao(client, "qualidade")
    resposta = client.get("/sgi/qualidade/verificacoes/nova/plm01_instalacoes?competencia=2026-06")
    assert resposta.status_code == 302 and "/sgi/qualidade/plm01" in resposta.location
    for tipo in ("plm02_sanitarios", "plm03_iluminacao", "plm04_ventilacao", "plm05_condensacao"):
        vid = sgi.salvar_verificacao_sgi(tipo, form_conforme(tipo, cadastros), 1, "Teste")
        assert repo.buscar_verificacao(vid)[0]["formulario_tipo"] == tipo


def test_rotas_renderizam_selects_oficiais_e_preservam_mes():
    cadastros = preparar_cadastros()
    client = app.test_client(); sessao(client, "qualidade")
    central = client.get(f"/sgi/qualidade?mes=2026-06&setor_id={cadastros['setor']['id']}")
    html = central.get_data(as_text=True)
    assert central.status_code == 200
    assert 'type="month" name="mes" value="2026-06"' in html
    assert 'name="setor_id"' in html

    form = client.get("/sgi/qualidade/verificacoes/nova/plm01_instalacoes")
    assert form.status_code == 302
    form = client.get("/sgi/qualidade/plm01?competencia=2026-06")
    html_form = form.get_data(as_text=True)
    assert form.status_code == 200
    assert 'name="setor_id[]"' in html_form
    assert 'name="setor" required' not in html_form
    assert 'Adicionar linha' in html_form and 'Salvar PLM 01' in html_form
    assert 'Justificativa de alteracao' not in html_form
    assert 'name="justificativa[]"' not in html_form


def test_schema_estruturado_e_sem_hard_delete_sgi():
    conn = sqlite3.connect(DB_PATH)
    tabelas = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sgi_verificacoes", "sgi_verificacao_itens", "sgi_nao_conformidades",
            "sgi_acoes_imediatas", "sgi_eventos", "cadastros_locais",
            "sgi_plm01_fichas", "sgi_plm01_linhas", "sgi_plm01_linha_historico"} <= tabelas
    colunas = {row[1] for row in conn.execute("PRAGMA table_info(sgi_verificacao_itens)")}
    assert {"valor_texto", "valor_numerico", "parametro_numerico", "resultado"} <= colunas
    conn.close()
    fontes = (ROOT / "modules" / "qualidade").glob("*.py")
    texto = "\n".join(path.read_text(encoding="utf-8") for path in fontes)
    assert "DELETE FROM sgi_" not in texto
    migracao = (ROOT / "database" / "20260720_qual_sgi_01.sql").read_text(encoding="utf-8")
    assert "SERIAL PRIMARY KEY" in migracao and "ADD COLUMN IF NOT EXISTS" in migracao
    assert "cadastros_setores" in migracao and "setor_id" in migracao
    assert "sgi_plm01_fichas" in migracao and "sgi_plm01_linhas" in migracao


if __name__ == "__main__":
    testes = [obj for nome, obj in sorted(globals().items()) if nome.startswith("test_")]
    try:
        for teste in testes:
            teste(); print("OK", teste.__name__)
    finally:
        TEMP_DIR.cleanup()
