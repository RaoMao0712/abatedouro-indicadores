"""RC: totais estimados, aprovação com ajuste de quantidade, auditoria, PDF e histórico."""
import sqlite3
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import pytest
from test_requisicoes_compra import banco, u, item, criar, contagens  # noqa: F401
from modules.requisicoes_compra import services as svc
from modules.requisicoes_compra.pdf import gerar_pdf

ROOT = Path(__file__).resolve().parents[1]

def _it(mid,q,custo=""): return {**item(mid,q),"custo_item":custo}

def _aberta(itens,chave="ab"):
    rc=criar("ADMINISTRATIVO",None,itens=itens,ator=u(1,"admin"),chave=chave)
    return svc.enviar(rc["id"],ator=u(1,"admin"),versao=0,idempotency_key=chave+"-env")

def _aprovar(rc,ajustes=None,just=None,ator=None,chave="apr"):
    return svc.aprovar(rc["id"],ator=ator or u(2,"gerencia"),versao=rc["versao"],idempotency_key=chave,ajustes=ajustes,justificativa_ajuste=just)

def test_totais_item_e_rc_no_backend_com_arredondamento_em_centavos(banco):
    rc=criar("ADMINISTRATIVO",None,itens=[_it(1,"3","1,005"),_it(2,"2","2,50"),item(3,"4")],chave="tot")
    a,b,c=rc["itens"]
    assert a["total_estimado_solicitado"]==Decimal("3.02") and b["total_estimado_solicitado"]==Decimal("5.00")
    assert c["total_estimado_solicitado"] is None and rc["itens_sem_custo"]==1
    assert rc["total_estimado_solicitado"]==Decimal("8.02") and rc["total_estimado_aprovado"]==Decimal("8.02")
    assert rc["tem_ajuste"] is False and rc["ajuste_financeiro"] is False

def test_aprovacao_sem_ajuste_mantem_aprovada_e_quantidade_igual_a_solicitada(banco):
    rc=_aprovar(_aberta([_it(1,"5","2"),_it(2,"3","1")]))
    assert rc["status"]=="APROVADA" and rc["tem_ajuste"] is False
    assert [i["quantidade_aprovada"] for i in rc["itens"]]==[5.0,3.0]
    assert not [e for e in rc["eventos"] if e["evento"]=="AJUSTE_QUANTIDADE_APROVADA"]

@pytest.mark.parametrize("novas,esperado",[(("3","3"),"reducao"),(("3","1"),"reducao-multipla")])
def test_aprovacao_com_reducao_preserva_solicitada_e_audita(banco,novas,esperado):
    rc=_aberta([_it(1,"5","2"),_it(2,"3","1")],chave="aj-"+esperado); i1,i2=[i["id"] for i in rc["itens"]]
    rc=_aprovar(rc,{i1:novas[0],i2:novas[1]},"Ajuste conforme orçamento",chave="apr-"+esperado)
    assert rc["status"]=="APROVADA_COM_AJUSTES" and rc["tem_ajuste"] is True
    it1,it2=rc["itens"]
    assert it1["quantidade_solicitada"]==5.0 and it1["quantidade_aprovada"]==float(novas[0]) and it1["quantidade_efetiva"]==float(novas[0])
    assert it2["quantidade_aprovada"]==float(novas[1]) and it2["tem_ajuste"] is (novas[1]!="3")
    ev=[e for e in rc["eventos"] if e["evento"]=="AJUSTE_QUANTIDADE_APROVADA"]
    assert len(ev)==(1 if novas[1]=="3" else 2) and ev[0]["item_id"]==i1 and ev[0]["justificativa"]=="Ajuste conforme orçamento"
    assert ev[0]["usuario_id"]==2 and ev[0]["usuario_nome"] and ev[0]["criado_em"]
    assert '"5.0"' in ev[0]["dados_anteriores"] and f'"{Decimal(novas[0])}"' in ev[0]["dados_novos"]
    assert rc["total_estimado_solicitado"]==Decimal("13.00")
    assert rc["total_estimado_aprovado"]==Decimal(int(novas[0])*2+int(novas[1])).quantize(Decimal("0.01"))
    assert rc["ajuste_financeiro"] is True

def test_justificativa_obrigatoria_e_nada_e_gravado_sem_ela(banco):
    rc=_aberta([_it(1,"5","2")],chave="sj"); iid=rc["itens"][0]["id"]
    with pytest.raises(ValueError,match="justificativa do ajuste"): _aprovar(rc,{iid:"4"},"  ",chave="sj-apr")
    atual=svc.buscar_rc(rc["id"])
    assert atual["status"]=="ABERTA" and atual["itens"][0]["quantidade_aprovada"] is None

@pytest.mark.parametrize("valor",["0","-1","abc","1e999","nan"])
def test_quantidade_aprovada_invalida_ou_zero_e_rejeitada(banco,valor):
    rc=_aberta([_it(1,"5")],chave="inv"+valor); iid=rc["itens"][0]["id"]
    with pytest.raises(ValueError): _aprovar(rc,{iid:valor},"x",chave="inv-apr"+valor)
    assert svc.buscar_rc(rc["id"])["status"]=="ABERTA"

def test_item_de_outra_rc_nao_pode_ser_ajustado(banco):
    rc=_aberta([_it(1,"5")],chave="a1"); outra=_aberta([_it(2,"5")],chave="a2")
    with pytest.raises(ValueError,match="pertencer à RC"): _aprovar(rc,{outra["itens"][0]["id"]:"1"},"x",chave="ap-x")

def test_permissoes_e_autoaprovacao_continuam_valendo_com_ajustes(banco):
    rc=_aberta([_it(1,"5")],chave="perm"); iid=rc["itens"][0]["id"]
    with pytest.raises(PermissionError): _aprovar(rc,{iid:"1"},"x",ator=u(3,"pcp"),chave="p1")
    with pytest.raises(PermissionError): _aprovar(rc,{iid:"1"},"x",ator=u(1,"admin"),chave="p2")
    atual=svc.buscar_rc(rc["id"]); assert atual["status"]=="ABERTA" and atual["itens"][0]["quantidade_aprovada"] is None

def test_repeticao_idempotente_nao_duplica_auditoria(banco):
    rc=_aberta([_it(1,"5")],chave="idem"); iid=rc["itens"][0]["id"]
    r1=_aprovar(rc,{iid:"2"},"corte",chave="idem-apr"); r2=_aprovar(rc,{iid:"2"},"corte",chave="idem-apr")
    assert r1["versao"]==r2["versao"] and len([e for e in r2["eventos"] if e["evento"]=="AJUSTE_QUANTIDADE_APROVADA"])==1

def test_bloqueio_pos_aprovacao_edicao_nu_e_cancelamento(banco):
    rc=_aberta([_it(1,"5","2")],chave="blq"); iid=rc["itens"][0]["id"]
    rc=_aprovar(rc,{iid:"2"},"corte",chave="blq-apr")
    with pytest.raises(ValueError,match="Somente rascunho"):
        svc.editar_rascunho(rc["id"],{"prioridade":"NORMAL"},[_it(1,"9")],ator=u(1,"admin"),versao=rc["versao"],idempotency_key="blq-ed")
    rc=svc.aplicar_nu(rc["id"],[iid],"123",ator=u(4,"pcp"),versao=rc["versao"],idempotency_key="blq-nu")
    assert rc["itens"][0]["nu"]=="123" and rc["itens"][0]["quantidade_efetiva"]==2.0 and rc["status"]=="APROVADA_COM_AJUSTES"
    rc=svc.cancelar(rc["id"],ator=u(2,"gerencia"),versao=rc["versao"],idempotency_key="blq-can",motivo="teste")
    assert rc["status"]=="CANCELADA"

def test_rejeicao_existente_nao_registra_quantidade_aprovada(banco):
    rc=_aberta([_it(1,"5")],chave="rej")
    rc=svc.rejeitar(rc["id"],ator=u(2,"gerencia"),versao=rc["versao"],idempotency_key="rej-r",motivo="sem verba")
    assert rc["status"]=="REJEITADA" and rc["itens"][0]["quantidade_aprovada"] is None

def test_rc_historica_sem_quantidade_aprovada_usa_solicitada(banco):
    rc=_aberta([_it(1,"7","3")],chave="hist")
    assert rc["itens"][0]["quantidade_aprovada"] is None and rc["itens"][0]["quantidade_efetiva"]==7.0
    assert rc["total_estimado_aprovado"]==rc["total_estimado_solicitado"]==Decimal("21.00")

def test_ajuste_nao_movimenta_estoque_nem_financeiro(banco):
    antes=contagens(banco); rc=_aberta([_it(1,"5")],chave="mov"); _aprovar(rc,{rc["itens"][0]["id"]:"1"},"corte",chave="mov-apr")
    assert contagens(banco)==antes

def test_migration_sqlite_backfill_preserva_dados_e_so_preenche_rcs_aprovadas():
    c=sqlite3.connect(":memory:")
    c.executescript("""CREATE TABLE requisicoes_compra(id INTEGER PRIMARY KEY,aprovado_em TEXT);
    CREATE TABLE requisicao_compra_itens(id INTEGER PRIMARY KEY,requisicao_compra_id INTEGER,quantidade_solicitada REAL);
    INSERT INTO requisicoes_compra VALUES(1,'2026-09-01 10:00:00'),(2,NULL);
    INSERT INTO requisicao_compra_itens VALUES(1,1,5),(2,2,9);""")
    c.executescript((ROOT/"database"/"20260925_rc_quantidade_aprovada_sqlite.sql").read_text(encoding="utf-8"))
    assert c.execute("SELECT id,quantidade_solicitada,quantidade_aprovada FROM requisicao_compra_itens ORDER BY id").fetchall()==[(1,5.0,5.0),(2,9.0,None)]
    c.executescript((ROOT/"database"/"20260925_rc_quantidade_aprovada_sqlite_rollback.sql").read_text(encoding="utf-8"))
    assert c.execute("SELECT id,quantidade_solicitada FROM requisicao_compra_itens ORDER BY id").fetchall()==[(1,5.0),(2,9.0)]

def test_migration_postgresql_e_idempotente_e_sem_perda_de_dados():
    sql=(ROOT/"database"/"20260925_rc_quantidade_aprovada.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS quantidade_aprovada" in sql and "aprovado_em IS NOT NULL" in sql and "quantidade_aprovada IS NULL" in sql and "DELETE" not in sql.upper()
    assert "DROP COLUMN IF EXISTS quantidade_aprovada" in (ROOT/"database"/"20260925_rc_quantidade_aprovada_rollback.sql").read_text(encoding="utf-8")

def _texto_pdf(rc):
    from pypdf import PdfReader
    return " ".join(p.extract_text() for p in PdfReader(BytesIO(gerar_pdf(rc))).pages)

def test_pdf_sem_ajuste_mostra_totais_e_aviso_sem_coluna_aprovada(banco):
    rc=svc.buscar_rc(_aberta([_it(1,"5","2,50")],chave="pdf1")["id"]); t=_texto_pdf(rc)
    assert "Custo unit. estimado" in t and "Total estimado" in t and "R$ 12,50" in t and "Total geral estimado" in t
    assert "Qtd. aprovada" not in t and "não movimenta estoque nem gera lançamento financeiro" in t

def test_pdf_com_ajuste_mostra_solicitada_aprovada_e_valores(banco):
    rc=_aberta([_it(1,"10","2,50")],chave="pdf2"); rc=_aprovar(rc,{rc["itens"][0]["id"]:"4"},"corte",chave="pdf2-apr"); t=_texto_pdf(svc.buscar_rc(rc["id"]))
    assert "Qtd. solicitada" in t and "Qtd. aprovada" in t and "R$ 25,00" in t and "R$ 10,00" in t and "Total geral aprovado" in t
    assert "não movimenta estoque nem gera lançamento financeiro" in t

def test_templates_rotulos_e_totais_na_interface():
    base=ROOT/"templates"
    for arq in ("requisicao_compra_nova.html","requisicao_compra_editar.html","requisicao_compra_detalhe.html"):
        t=(base/arq).read_text(encoding="utf-8"); assert "Custo unit. estimado" in t and "Custo estimado" not in t and "Custo unitário estimado" not in t
    for arq in ("requisicao_compra_nova.html","requisicao_compra_editar.html"):
        assert "rc-total-geral" in (base/arq).read_text(encoding="utf-8")
    d=(base/"requisicao_compra_detalhe.html").read_text(encoding="utf-8")
    assert "Valor estimado solicitado" in d and "Valor estimado aprovado" in d and "justificativa_ajuste" in d and "qtd_aprovada_" in d


@pytest.mark.parametrize("valores",[("6","3"),("5.01","3"),("5","4"),("100","3")])
def test_aumento_acima_do_solicitado_e_rejeitado_atomicamente(banco,valores):
    rc=_aberta([_it(1,"5","2"),_it(2,"3","1")],chave="up"+valores[0]+valores[1]); i1,i2=[i["id"] for i in rc["itens"]]
    eventos_antes=len(rc["eventos"])
    with pytest.raises(ValueError,match="superior à quantidade solicitada"):
        _aprovar(rc,{i1:valores[0],i2:valores[1]},"Justificativa presente",chave="up-apr"+valores[0]+valores[1])
    atual=svc.buscar_rc(rc["id"])
    assert atual["status"]=="ABERTA" and atual["versao"]==rc["versao"] and atual["aprovado_em"] is None and atual["aprovado_por"] is None
    assert [i["quantidade_aprovada"] for i in atual["itens"]]==[None,None] and len(atual["eventos"])==eventos_antes
    assert not [e for e in atual["eventos"] if e["evento"] in {"APROVACAO","AJUSTE_QUANTIDADE_APROVADA"}]

def test_aprovada_igual_a_solicitada_e_reducao_parcial_no_mesmo_pedido(banco):
    rc=_aberta([_it(1,"5","2"),_it(2,"3","1")],chave="mix"); i1,i2=[i["id"] for i in rc["itens"]]
    rc=_aprovar(rc,{i1:"5",i2:"1.5"},"Corte parcial",chave="mix-apr")
    assert rc["status"]=="APROVADA_COM_AJUSTES" and [i["quantidade_aprovada"] for i in rc["itens"]]==[5.0,1.5]
    ev=[e for e in rc["eventos"] if e["evento"]=="AJUSTE_QUANTIDADE_APROVADA"]
    assert [e["item_id"] for e in ev]==[i2] and ev[0]["perfil"]=="gerencia"

def test_historico_permite_reconstruir_solicitacao_e_decisao(banco):
    rc=_aberta([_it(1,"5","2")],chave="rec"); iid=rc["itens"][0]["id"]
    rc=_aprovar(rc,{iid:"2"},"Verba limitada",chave="rec-apr")
    nomes=[e["evento"] for e in rc["eventos"]]
    assert nomes[:2]==["CRIACAO_RASCUNHO","ENVIO"] and "APROVACAO" in nomes and "AJUSTE_QUANTIDADE_APROVADA" in nomes
    aj=[e for e in rc["eventos"] if e["evento"]=="AJUSTE_QUANTIDADE_APROVADA"][0]
    assert (aj["status_anterior"],aj["status_novo"])==("ABERTA","APROVADA_COM_AJUSTES") and aj["usuario_nome"] and aj["criado_em"]
    assert rc["solicitante_nome_snapshot"] and rc["aprovado_por"]==2 and rc["itens"][0]["quantidade_solicitada"]==5.0

def test_quantidade_efetiva_solicitada_ate_aprovar_e_aprovada_depois(banco):
    rc=_aberta([_it(1,"5")],chave="ef"); assert rc["itens"][0]["quantidade_efetiva"]==5.0
    rc=_aprovar(rc,{rc["itens"][0]["id"]:"2"},"corte",chave="ef-apr"); assert rc["itens"][0]["quantidade_efetiva"]==2.0
    from modules.requisicoes_compra.services import quantidade_efetiva
    assert quantidade_efetiva({"quantidade_solicitada":9.0,"quantidade_aprovada":None})==9.0

def test_total_estimado_parcial_quando_ha_item_sem_custo_e_completo_quando_todos_tem(banco):
    parcial=criar("ADMINISTRATIVO",None,itens=[_it(1,"2","5"),item(2,"3")],chave="par")
    assert parcial["total_parcial"] is True and parcial["itens_sem_custo"]==1 and parcial["total_estimado_solicitado"]==Decimal("10.00")
    assert parcial["itens"][1]["total_estimado_solicitado"] is None
    completo=criar("ADMINISTRATIVO",None,itens=[_it(1,"2","5"),_it(2,"3","1")],chave="comp")
    assert completo["total_parcial"] is False and completo["itens_sem_custo"]==0

def test_pdf_total_parcial_informa_itens_sem_custo(banco):
    rc=svc.buscar_rc(criar("ADMINISTRATIVO",None,itens=[_it(1,"2","5"),item(2,"3")],chave="pdfp")["id"]); t=_texto_pdf(rc)
    assert "Total geral estimado parcial" in t and "1 de 2 item(ns) sem custo estimado" in t and "R$ 10,00" in t

def test_templates_total_parcial_e_sem_custo_nao_vira_zero():
    base=ROOT/"templates"
    for arq in ("requisicao_compra_nova.html","requisicao_compra_editar.html"):
        t=(base/arq).read_text(encoding="utf-8"); assert "Total estimado parcial" in t and "sem custo estimado" in t and "if(c===null)" in t
    d=(base/"requisicao_compra_detalhe.html").read_text(encoding="utf-8")
    assert "Total estimado parcial" in d and "não são tratados como custo zero" in d


@pytest.mark.parametrize("valor,esperado,input_",[(1.0,"R$ 1,00","1,00"),(1.2,"R$ 1,20","1,20"),(1.005,"R$ 1,005","1,005"),(11.32,"R$ 11,32","11,32"),(1234.5,"R$ 1.234,50","1234,50"),(None,None,None)])
def test_formatacao_do_custo_unitario_ate_3_casas_quando_significativo(valor,esperado,input_):
    from modules.requisicoes_compra.services import formatar_custo_unitario
    assert formatar_custo_unitario(valor)==esperado and formatar_custo_unitario(valor,moeda=False)==input_

def test_custo_com_3_casas_visivel_no_backend_no_pdf_e_totais_com_2_casas(banco):
    rc=svc.buscar_rc(criar("ADMINISTRATIVO",None,itens=[_it(1,"3","1,005"),_it(2,"2","11,32")],chave="c3")["id"])
    assert [i["custo_unitario_formatado"] for i in rc["itens"]]==["R$ 1,005","R$ 11,32"]
    assert [i["custo_unitario_input"] for i in rc["itens"]]==["1,005","11,32"]
    assert rc["itens"][0]["total_estimado_solicitado"]==Decimal("3.02") and rc["total_estimado_solicitado"]==Decimal("25.66")
    t=_texto_pdf(rc); assert "R$ 1,005" in t and "R$ 11,32" in t and "R$ 3,02" in t and "R$ 25,66" in t

def test_templates_usam_custo_formatado_em_detalhe_e_edicao():
    base=ROOT/"templates"
    assert "i.custo_unitario_formatado" in (base/"requisicao_compra_detalhe.html").read_text(encoding="utf-8")
    assert "i.custo_unitario_input" in (base/"requisicao_compra_editar.html").read_text(encoding="utf-8")

