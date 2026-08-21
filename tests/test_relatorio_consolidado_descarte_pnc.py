from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import sqlite3

import pytest
from flask import Flask
from pypdf import PdfReader

from modules.qualidade import descarte_pnc_relatorio as relatorio
from modules.qualidade.descarte_pnc_relatorio_pdf import gerar_relatorio_consolidado_descarte_pdf


def _snapshot(numero, produto, apresentacao, motivo, destino, motorista, placa, emissor,
              saida_fisica, lancamento, caixas=0, bandejas=0, galinhas=0, pacotes=0, peso_g=0):
    return {
        "numero": numero, "pnc_numero": f"PNC-{numero}", "produto": produto,
        "apresentacao": apresentacao, "motivo": motivo, "destino": destino,
        "motorista": motorista, "placa": placa, "usuario_emissor": emissor,
        "saida_fisica_em": saida_fisica, "lancado_em": lancamento,
        "saida": {"caixas": caixas, "bandejas": bandejas, "galinhas": galinhas,
                  "pacotes": pacotes, "peso_g": peso_g},
    }


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "relatorio-descarte.db"
    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(relatorio, "conectar", conectar)
    conn = conectar()
    conn.executescript("""
      CREATE TABLE pa_nao_conformes(id INTEGER PRIMARY KEY,numero TEXT,produto TEXT);
      CREATE TABLE pnc_romaneios_descarte(
        id INTEGER PRIMARY KEY,numero TEXT,status TEXT,pa_nao_conforme_id INTEGER,
        saida_fisica_em TEXT,lancado_em TEXT,criado_em TEXT,destino TEXT,motorista TEXT,
        placa TEXT,usuario_emissor TEXT,justificativa_estorno TEXT,snapshot_json TEXT);
      CREATE TABLE pnc_romaneio_descarte_itens(
        id INTEGER PRIMARY KEY,romaneio_id INTEGER,produto TEXT,apresentacao TEXT,motivo TEXT,
        caixas INTEGER,bandejas INTEGER,galinhas INTEGER,pacotes INTEGER,peso_g INTEGER,snapshot_json TEXT);
      CREATE TABLE pnc_movimentos_descarte(id INTEGER PRIMARY KEY,romaneio_id INTEGER,tipo TEXT);
      CREATE TABLE estoque_operacional_teste(id INTEGER PRIMARY KEY,peso_g INTEGER);
    """)
    documentos = [
      (1,"RDPNC-001","CONFIRMADO","2026-08-01 08:00:00","2026-08-02 09:00:00","2026-08-03 10:00:00",
       "Aterro Norte","Ana Silva","AAA1A11","PCP Um","Galinha Cortada","Congelada","Carne Escura",100,1200,0,0,1500250,None),
      (2,"RDPNC-002","CONFIRMADO","2026-08-04 08:00:00","2026-08-04 09:00:00","2026-08-05 10:00:00",
       "Aterro Sul","Bruno Lima","BBB2B22","Qualidade Dois","Galinha Cortada","Congelada","Carcaça Incompleta",45,540,0,0,710300,None),
      (3,"RDPNC-003","CONFIRMADO","2026-08-06 08:00:00","2026-08-06 09:00:00","2026-08-06 10:00:00",
       "Compostagem","Carlos Um","CCC3C33","Gerência","Galinha Inteira","Pacote c/1","Aspecto inadequado",0,0,80,80,0,None),
      (4,"RDPNC-004","CONFIRMADO","2026-08-07 08:00:00","2026-08-07 09:00:00","2026-08-07 10:00:00",
       "Compostagem","Carlos Dois","DDD4D44","Gerência","Galinha Inteira","Pacote c/2","Aspecto inadequado",0,0,120,60,0,None),
      (5,"RDPNC-005","ESTORNADO","2026-08-08 08:00:00","2026-08-08 09:00:00","2026-08-08 10:00:00",
       "Aterro Sul","Estornado","EEE5E55","Administrador","Galinha Cortada","Congelada","Carne Escura",10,120,0,0,100000,"Documento duplicado"),
      (6,"RDPNC-006","CANCELADO","2026-08-09 08:00:00","2026-08-09 09:00:00","2026-08-09 10:00:00",
       "Aterro Sul","Cancelado","FFF6F66","PCP Um","Galinha Cortada","Congelada","Carne Escura",20,240,0,0,200000,"Rascunho incorreto"),
      (7,"RDPNC-007","RASCUNHO","2026-08-10 08:00:00","2026-08-10 09:00:00","2026-08-10 10:00:00",
       "Aterro Norte","Rascunho","GGG7G77","PCP Um","Galinha Cortada","Resfriada","Carne Escura",5,60,0,0,50000,None),
    ]
    for item in documentos:
        (ident,numero,status,fisica,lancado,criado,destino,motorista,placa,emissor,produto,
         apresentacao,motivo,caixas,bandejas,galinhas,pacotes,peso,justificativa) = item
        snapshot = _snapshot(numero,produto,apresentacao,motivo,destino,motorista,placa,emissor,
                             fisica,lancado,caixas,bandejas,galinhas,pacotes,peso)
        conn.execute("INSERT INTO pa_nao_conformes VALUES(?,?,?)",(ident,f"PNC-{ident}","Cadastro atual alterável"))
        conn.execute("""INSERT INTO pnc_romaneios_descarte VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (ident,numero,status,ident,fisica,lancado,criado,destino,motorista,placa,emissor,
                      justificativa,json.dumps(snapshot,ensure_ascii=False)))
        conn.execute("""INSERT INTO pnc_romaneio_descarte_itens VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                     (ident,ident,produto,apresentacao,motivo,caixas,bandejas,galinhas,pacotes,peso,
                      json.dumps(snapshot,ensure_ascii=False)))
        conn.execute("INSERT INTO pnc_movimentos_descarte VALUES(?,?,?)",
                     (ident,ident,"SAIDA_DESCARTE_PNC"))
    conn.commit(); conn.close()
    return conectar


def _consultar(**filtros):
    base={"data_inicio":"2026-08-01","data_fim":"2026-08-31"}
    base.update(filtros)
    return relatorio.consultar_romaneios_descarte(base)


def test_periodo_padrao_e_tres_datas_sao_independentes(banco):
    padrao=relatorio.normalizar_filtros({},agora=datetime(2026,8,21,12,0))
    assert (padrao["data_inicio"],padrao["data_fim"],padrao["tipo_data"],padrao["status"]) == ("2026-08-01","2026-08-21","SAIDA_FISICA",["CONFIRMADO"])
    assert [x["numero"] for x in _consultar(data_inicio="2026-08-01",data_fim="2026-08-01")["registros"]] == ["RDPNC-001"]
    assert [x["numero"] for x in _consultar(tipo_data="LANCAMENTO",data_inicio="2026-08-02",data_fim="2026-08-02")["registros"]] == ["RDPNC-001"]
    assert [x["numero"] for x in _consultar(tipo_data="EMISSAO",data_inicio="2026-08-03",data_fim="2026-08-03")["registros"]] == ["RDPNC-001"]


@pytest.mark.parametrize("filtro,valor,esperado",[
    ("numero","002","RDPNC-002"),("produto",["Galinha Inteira"],"RDPNC-004"),
    ("apresentacao","Pacote c/1","RDPNC-003"),("motivo",["Carcaça Incompleta"],"RDPNC-002"),
    ("destino",["Aterro Norte"],"RDPNC-001"),("motorista","Bruno","RDPNC-002"),
    ("placa","CCC3","RDPNC-003"),("usuario_emissor","Qualidade","RDPNC-002"),
])
def test_filtros_de_documento_e_snapshot(banco,filtro,valor,esperado):
    resultado=_consultar(**{filtro:valor})
    numeros=[x["numero"] for x in resultado["registros"]]
    assert esperado in numeros
    if filtro not in {"produto","destino"}:
        assert len(numeros)==1


def test_status_padrao_e_excecoes_nao_entram_no_total_liquido(banco):
    padrao=_consultar()
    assert len(padrao["registros"]) == 4 and padrao["resumo"]["romaneios_confirmados"] == 4
    todos=_consultar(status=list(relatorio.STATUS_DOCUMENTO))
    assert len(todos["registros"]) == 7 and len(todos["excecoes"]) == 3
    assert todos["resumo"]["caixas"] == 145
    assert todos["resumo"]["bandejas"] == 1740
    assert todos["resumo"]["peso_g"] == 2210550
    assert todos["resumo"]["galinhas"] == 200 and todos["resumo"]["pacotes"] == 140
    assert {x["status"] for x in todos["excecoes"]} == {"RASCUNHO","CANCELADO","ESTORNADO"}


def test_consolidacao_separa_produto_apresentacao_e_caracteristica(banco):
    resultado=_consultar(modalidade="CARACTERISTICA")
    chaves={(g["produto"],g["apresentacao"],g["motivo"]):g for g in resultado["grupos"]}
    assert chaves[("Galinha Cortada","Congelada","Carne Escura")]["caixas"] == 100
    assert chaves[("Galinha Cortada","Congelada","Carcaça Incompleta")]["bandejas"] == 540
    assert chaves[("Galinha Inteira","Pacote c/1","Aspecto inadequado")]["pacotes"] == 80
    assert chaves[("Galinha Inteira","Pacote c/2","Aspecto inadequado")]["galinhas"] == 120
    assert len({(g["produto"],g["apresentacao"]) for g in resultado["grupos"]}) == 3


def test_snapshot_historico_independe_do_cadastro_atual_e_reimprime_igual(banco):
    conn=banco(); conn.execute("UPDATE pa_nao_conformes SET produto='Produto renomeado'"); conn.commit(); conn.close()
    resultado=_consultar(numero="RDPNC-001")
    assert resultado["registros"][0]["produto"] == "Galinha Cortada"
    emissao=datetime(2026,8,21,12,0,tzinfo=relatorio.FUSO_MANAUS)
    pdf1=gerar_relatorio_consolidado_descarte_pdf(resultado,usuario="Auditor",emissao=emissao,logo="")
    pdf2=gerar_relatorio_consolidado_descarte_pdf(resultado,usuario="Auditor",emissao=emissao,logo="")
    assert PdfReader(BytesIO(pdf1)).pages[0].extract_text() == PdfReader(BytesIO(pdf2)).pages[0].extract_text()
    assert "Galinha Cortada" in PdfReader(BytesIO(pdf1)).pages[0].extract_text()


def test_pdf_sintetico_consolidado_excecoes_filtros_e_metadados(banco):
    todos=_consultar(status=list(relatorio.STATUS_DOCUMENTO))
    emissao=datetime(2026,8,21,12,34,tzinfo=relatorio.FUSO_MANAUS)
    sintetico=gerar_relatorio_consolidado_descarte_pdf(todos,usuario="Usuário Teste",emissao=emissao,logo="")
    consolidado=gerar_relatorio_consolidado_descarte_pdf(
        {**todos,"filtros":{**todos["filtros"],"modalidade":"CARACTERISTICA"}},
        usuario="Usuário Teste",emissao=emissao,logo="")
    leitor_s=PdfReader(BytesIO(sintetico)); leitor_c=PdfReader(BytesIO(consolidado))
    texto_s="\n".join(p.extract_text() or "" for p in leitor_s.pages)
    texto_c="\n".join(p.extract_text() or "" for p in leitor_c.pages)
    assert float(leitor_s.pages[0].mediabox.width) > float(leitor_s.pages[0].mediabox.height)
    assert float(leitor_c.pages[0].mediabox.height) > float(leitor_c.pages[0].mediabox.width)
    for texto in (texto_s,texto_c):
        assert "RELATÓRIO CONSOLIDADO DE ROMANEIOS DE DESCARTE" in texto
        assert "America/Manaus" in texto and "Usuário Teste" in texto
        assert "Documento gerencial - não movimenta estoque" in texto
        assert "Documentos sem efeito no total físico" in texto
        assert "RDPNC-005" in texto and "Documento duplicado" in texto
        assert "01/08/2026 a 31/08/2026" in texto
    assert "2.210,550 kg" in texto_s
    assert "Pacote c/1" in texto_c and "Pacote c/2" in texto_c


def test_pdf_multipagina_repete_cabecalho_sem_corte_logico(banco):
    base=_consultar(numero="RDPNC-001")["registros"][0]
    registros=[]
    for indice in range(1,81):
        item={**base,"id":indice,"numero":f"RDPNC-LONGO-{indice:03d}","efetivo":True}
        registros.append(item)
    dados=relatorio.montar_relatorio(registros,{"data_inicio":"2026-08-01","data_fim":"2026-08-31","modalidade":"SINTETICO"})
    pdf=gerar_relatorio_consolidado_descarte_pdf(dados,usuario="Auditor",logo="")
    leitor=PdfReader(BytesIO(pdf))
    assert len(leitor.pages) > 2
    for numero,pagina in enumerate(leitor.pages,1):
        texto=pagina.extract_text() or ""
        assert "Número / data" in texto
        assert f"Página {numero}" in texto
        assert "Documento gerencial - não movimenta estoque" in texto


def test_consulta_pdf_e_opcoes_nao_alteram_banco(banco):
    conn=banco()
    antes={t:conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
           ("pnc_romaneios_descarte","pnc_movimentos_descarte","estoque_operacional_teste")}
    resultado=_consultar(status=list(relatorio.STATUS_DOCUMENTO))
    relatorio.opcoes_filtros_relatorio(conexao=conn)
    gerar_relatorio_consolidado_descarte_pdf(resultado,usuario="Leitura",logo="")
    depois={t:conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in antes}
    conn.close()
    assert antes == depois


def test_migracao_sqlite_cria_e_rollback_remove_indices(banco):
    conn=banco()
    raiz=Path(__file__).resolve().parents[1]/"database"
    upgrade=(raiz/"20260821_relatorio_consolidado_romaneios_descarte_sqlite.sql").read_text(encoding="utf-8")
    rollback=(raiz/"20260821_relatorio_consolidado_romaneios_descarte_sqlite_rollback.sql").read_text(encoding="utf-8")
    nomes={
        "idx_pnc_rom_descarte_status_saida",
        "idx_pnc_rom_descarte_lancamento_status",
        "idx_pnc_rom_descarte_emissao_status",
        "idx_pnc_rom_descarte_destino",
        "idx_pnc_rom_descarte_item_classificacao",
    }
    conn.executescript(upgrade)
    criados={linha[0] for linha in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_pnc_rom_descarte_%'"
    )}
    assert nomes <= criados
    conn.executescript(rollback)
    restantes={linha[0] for linha in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_pnc_rom_descarte_%'"
    )}
    conn.close()
    assert not (nomes & restantes)


def _app(monkeypatch):
    from modules.qualidade import routes
    raiz=__import__("pathlib").Path(__file__).resolve().parents[1]
    app=Flask(__name__,template_folder=str(raiz/"templates"),static_folder=str(raiz/"static")); app.secret_key="teste"
    app.config.update(TESTING=True,PNC_DISCARD_WAYBILL_ENABLED=True)
    app.jinja_env.filters["br_numero"] = lambda valor,casas=2:f"{float(valor or 0):.{casas}f}"
    for regra,nome in (("/login","login"),("/inicio","inicio"),("/","dashboard"),("/sair","sair")):
        app.add_url_rule(regra,nome,lambda:"ok")
    vazio=relatorio.montar_relatorio([],{"data_inicio":"2026-08-01","data_fim":"2026-08-31"})
    monkeypatch.setattr(routes,"consultar_romaneios_descarte",lambda _f:vazio)
    monkeypatch.setattr(routes,"opcoes_filtros_relatorio",lambda:{"produtos":[],"apresentacoes":[],"motivos":[],"destinos":[]})
    monkeypatch.setattr(routes,"gerar_relatorio_consolidado_descarte_pdf",lambda *_a,**_k:b"%PDF-1.4\n%%EOF")
    routes.register_qualidade_routes(app)
    return app


def _cliente(app,perfil):
    cliente=app.test_client()
    with cliente.session_transaction() as sess:
        sess.update({"usuario_id":1,"nome":"Usuário Rota","perfil":perfil})
    return cliente


@pytest.mark.parametrize("perfil",["admin","pcp","gerencia","qualidade"])
def test_backend_autoriza_perfis_de_consulta_e_get_nao_exige_csrf(monkeypatch,perfil):
    app=_app(monkeypatch); resposta=_cliente(app,perfil).get("/expedicao/romaneios/descarte/relatorio.pdf")
    assert resposta.status_code == 200 and resposta.mimetype == "application/pdf"
    assert _cliente(app,perfil).post("/expedicao/romaneios/descarte/relatorio.pdf").status_code == 405


def test_backend_bloqueia_perfil_sem_permissao(monkeypatch):
    app=_app(monkeypatch)
    resposta=_cliente(app,"producao").get("/expedicao/romaneios/descarte/relatorio.pdf")
    assert resposta.status_code == 302 and "/inicio" in resposta.headers["Location"]
