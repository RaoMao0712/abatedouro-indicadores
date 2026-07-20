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
    if not repo.listar_locais():
        for indice, classificacao in enumerate((
            "Camara fria e estocagem", "Producao e recepcao",
            "Inspecao oficial e seguranca critica"), start=1):
            repo.inserir_local("Ambiente", f"Ambiente {indice}", "Producao", classificacao)
        repo.inserir_local("Estrutura", "Barreira Sanitaria", "Producao", None)
    if not repo.listar_equipamentos():
        manutencao_service.salvar_equipamento_manutencao({
            "codigo": "BAL-01", "nome": "Balanca de teste", "setor": "Recepcao",
            "criticidade": "Alta", "status": "Operacional",
        })
    locais = repo.listar_locais()
    return {
        "ambientes": [item for item in locais if item["tipo"] == "Ambiente"],
        "estrutura": [item for item in locais if item["tipo"] == "Estrutura"][0],
        "equipamento": repo.listar_equipamentos()[0],
    }


def form_conforme(tipo, cadastros, lux=600):
    ficha = FORMULARIOS_PLM[tipo]
    vinculo = ficha["vinculos"][0]
    dados = {"data": "2026-07-20", "setor": "Producao", "responsavel": "Monitor",
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
    ids = [sgi.salvar_verificacao_sgi(tipo, form_conforme(tipo, cadastros), 1, "Teste")
           for tipo in FORMULARIOS_PLM]
    assert len(ids) == 6 and len(set(ids)) == 6


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
    sessao(client, "qualidade")
    ok = client.post(f"/sgi/qualidade/reposicoes/{acoes[0]['id']}/confirmar",
        data={"resultado": "C", "observacao": "Reposto", "nc_id": ncs[0]["id"], "verificacao_id": vid})
    assert ok.status_code == 302
    assert repo.buscar_verificacao(vid)[2][0]["situacao"] == "NC corrigida imediatamente"


def test_os_bidirecional_conclusao_eficacia_e_encerramento():
    cadastros = preparar_cadastros()
    form = form_conforme("plm01_balancas", cadastros)
    form.update({"resultado_calibracao": "NC", "criticidade_calibracao": "ALTA",
                 "observacao_calibracao": "Calibracao vencida", "acao_calibracao": "Segregar"})
    vid = sgi.salvar_verificacao_sgi("plm01_balancas", form, 2, "PCP")
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


def test_schema_estruturado_e_sem_hard_delete_sgi():
    conn = sqlite3.connect(DB_PATH)
    tabelas = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sgi_verificacoes", "sgi_verificacao_itens", "sgi_nao_conformidades",
            "sgi_acoes_imediatas", "sgi_eventos", "cadastros_locais"} <= tabelas
    colunas = {row[1] for row in conn.execute("PRAGMA table_info(sgi_verificacao_itens)")}
    assert {"valor_texto", "valor_numerico", "parametro_numerico", "resultado"} <= colunas
    conn.close()
    fontes = (ROOT / "modules" / "qualidade").glob("*.py")
    texto = "\n".join(path.read_text(encoding="utf-8") for path in fontes)
    assert "DELETE FROM sgi_" not in texto
    migracao = (ROOT / "database" / "20260720_qual_sgi_01.sql").read_text(encoding="utf-8")
    assert "SERIAL PRIMARY KEY" in migracao and "ADD COLUMN IF NOT EXISTS" in migracao


if __name__ == "__main__":
    testes = [obj for nome, obj in sorted(globals().items()) if nome.startswith("test_")]
    try:
        for teste in testes:
            teste(); print("OK", teste.__name__)
    finally:
        TEMP_DIR.cleanup()
