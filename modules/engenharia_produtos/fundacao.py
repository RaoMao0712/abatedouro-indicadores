"""Fundação aditiva e isolada para versionamento futuro de SKU e roteiro."""
import json
from pathlib import Path
from database import DATABASE_URL, conectar, q, transaction

UNIDADES = {"Kg","Un","Cx","L","Ml","G","Pct","AVE","BANDEJA","CAIXA","PACOTE"}
STATUS_SKU = {"RASCUNHO","ATIVA","INATIVA"}
STATUS_ROTEIRO = {"RASCUNHO","ATIVO","INATIVO"}
TIPOS_CALCULO = {"FIXO","POR_UNIDADE_ENTRADA","POR_UNIDADE_SAIDA","PERCENTUAL","PROPORCIONAL"}
ORIGENS_BAIXA = {"MANUAL","REQUISICAO","FUTURA_SAIDA_OP"}


def criar_estrutura():
    nome = "20260922_fase1_fundacao_sku_roteiro.sql" if DATABASE_URL else "20260922_fase1_fundacao_sku_roteiro_sqlite.sql"
    sql = (Path(__file__).resolve().parents[2] / "database" / nome).read_text(encoding="utf-8")
    conn=conectar(); cur=conn.cursor()
    try:
        for comando in [x.strip() for x in sql.replace("BEGIN;","").replace("COMMIT;","").split(";") if x.strip()]:
            cur.execute(comando)
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()


def _json(valor):
    if valor in (None, ""): return "{}"
    if isinstance(valor, str):
        json.loads(valor); return valor
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)


def _id_insert(cur, sql, args):
    if DATABASE_URL:
        cur.execute(q(sql + " RETURNING id"), args); return cur.fetchone()["id"]
    cur.execute(q(sql), args); return cur.lastrowid


def criar_sku_versao(sku_id, dados, usuario):
    criar_estrutura(); status=dados.get("status","RASCUNHO"); unidade=dados["unidade_apresentacao"]
    if status not in STATUS_SKU: raise ValueError("Status de versão de SKU inválido.")
    if unidade not in UNIDADES: raise ValueError("Unidade/apresentação inválida.")
    with transaction() as conn:
        cur=conn.cursor(); cur.execute(q("SELECT 1 FROM skus WHERE id=?"),(sku_id,))
        if not cur.fetchone(): raise ValueError("SKU não encontrado.")
        if status=="ATIVA":
            cur.execute(q("SELECT 1 FROM sku_versoes WHERE sku_id=? AND status='ATIVA'"),(sku_id,))
            if cur.fetchone(): raise ValueError("Já existe uma versão ativa para o SKU.")
        return _id_insert(cur,"""INSERT INTO sku_versoes(sku_id,versao,nome,unidade_apresentacao,categoria_tipo,status,
          vigencia_inicio,vigencia_fim,usuario_id,usuario_nome) VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (sku_id,int(dados["versao"]),dados["nome"].strip(),unidade,dados["categoria_tipo"],status,
           dados["vigencia_inicio"],dados.get("vigencia_fim"),usuario.get("id"),usuario["nome"]))


def criar_etapa_catalogo(dados, usuario):
    criar_estrutura()
    with transaction() as conn:
        return _id_insert(conn.cursor(),"""INSERT INTO etapas_catalogo(codigo,nome,natureza,ativo,parametros_json,usuario_nome)
          VALUES(?,?,?,?,?,?)""",(dados["codigo"].strip().upper(),dados["nome"].strip(),dados["natureza"],
          int(dados.get("ativo",1)),_json(dados.get("parametros_json")),usuario["nome"]))


def criar_roteiro_versao(sku_versao_id,dados,usuario):
    criar_estrutura(); status=dados.get("status","RASCUNHO")
    if status not in STATUS_ROTEIRO: raise ValueError("Status de roteiro inválido.")
    with transaction() as conn:
        cur=conn.cursor(); cur.execute(q("SELECT 1 FROM sku_versoes WHERE id=?"),(sku_versao_id,))
        if not cur.fetchone(): raise ValueError("Versão de SKU não encontrada.")
        if status=="ATIVO":
            cur.execute(q("SELECT 1 FROM roteiro_versoes WHERE sku_versao_id=? AND status='ATIVO'"),(sku_versao_id,))
            if cur.fetchone(): raise ValueError("Já existe um roteiro ativo para esta versão de SKU.")
        return _id_insert(cur,"""INSERT INTO roteiro_versoes(sku_versao_id,versao,status,vigencia_inicio,vigencia_fim,
          aprovado_por,aprovado_em,observacoes,parametros_json,usuario_nome) VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (sku_versao_id,int(dados["versao"]),status,dados["vigencia_inicio"],dados.get("vigencia_fim"),
           dados.get("aprovado_por"),dados.get("aprovado_em"),dados.get("observacoes"),
           _json(dados.get("parametros_json")),usuario["nome"]))


def _roteiro_editavel(cur, roteiro_id):
    cur.execute(q("""SELECT rv.status, EXISTS(SELECT 1 FROM op_config_snapshots s WHERE s.roteiro_versao_id=rv.id) usado
      FROM roteiro_versoes rv WHERE rv.id=?"""),(roteiro_id,)); row=cur.fetchone()
    if not row: raise ValueError("Roteiro não encontrado.")
    if row["status"] != "RASCUNHO" or row["usado"]: raise ValueError("Versão imutável; crie uma nova versão.")


def adicionar_etapa(roteiro_id,dados):
    criar_estrutura(); ue=dados.get("unidade_entrada"); us=dados.get("unidade_saida")
    if ue and ue not in UNIDADES or us and us not in UNIDADES: raise ValueError("Unidade inválida.")
    with transaction() as conn:
        cur=conn.cursor(); _roteiro_editavel(cur,roteiro_id)
        catalogo=dados.get("etapa_catalogo_id") or None
        if catalogo:
            cur.execute(q("SELECT 1 FROM etapas_catalogo WHERE id=? AND ativo=1"),(catalogo,))
            if not cur.fetchone(): raise ValueError("Etapa de catálogo inválida.")
        return _id_insert(cur,"""INSERT INTO roteiro_etapas(roteiro_versao_id,etapa_catalogo_id,ordem,nome,obrigatoria,
          unidade_entrada,unidade_saida,gera_intermediario,controla_qualidade,parametros_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (roteiro_id,catalogo,int(dados["ordem"]),dados["nome"].strip(),int(dados.get("obrigatoria",1)),ue,us,
           int(dados.get("gera_intermediario",0)),int(dados.get("controla_qualidade",0)),_json(dados.get("parametros_json"))))


def adicionar_insumo(etapa_id,dados):
    criar_estrutura(); tipo=dados["tipo_calculo"]; origem=dados.get("origem_baixa","MANUAL"); unidade=dados["unidade"]
    if tipo not in TIPOS_CALCULO or origem not in ORIGENS_BAIXA or unidade not in UNIDADES: raise ValueError("Configuração de insumo inválida.")
    with transaction() as conn:
        cur=conn.cursor(); cur.execute(q("SELECT roteiro_versao_id FROM roteiro_etapas WHERE id=?"),(etapa_id,)); etapa=cur.fetchone()
        if not etapa: raise ValueError("Etapa não encontrada.")
        _roteiro_editavel(cur,etapa["roteiro_versao_id"])
        cur.execute(q("SELECT 1 FROM almoxarifado_insumos WHERE id=?"),(dados["insumo_id"],))
        if not cur.fetchone(): raise ValueError("Insumo não encontrado.")
        return _id_insert(cur,"""INSERT INTO roteiro_etapa_insumos(roteiro_etapa_id,insumo_id,unidade,quantidade_fator,
          tipo_calculo,tolerancia_perda,obrigatorio,origem_baixa,parametros_json) VALUES(?,?,?,?,?,?,?,?,?)""",
          (etapa_id,int(dados["insumo_id"]),unidade,float(dados["quantidade_fator"]),tipo,
           dados.get("tolerancia_perda"),int(dados.get("obrigatorio",1)),origem,_json(dados.get("parametros_json"))))


def listar_fundacao(sku_id=None):
    criar_estrutura(); conn=conectar(); cur=conn.cursor()
    try:
        where=" WHERE sv.sku_id=?" if sku_id else ""; args=(sku_id,) if sku_id else ()
        cur.execute(q("SELECT sv.* FROM sku_versoes sv"+where+" ORDER BY sv.sku_id,sv.versao"),args); versoes=[dict(x) for x in cur.fetchall()]
        cur.execute("SELECT * FROM etapas_catalogo ORDER BY nome"); catalogo=[dict(x) for x in cur.fetchall()]
        return {"sku_versoes":versoes,"etapas_catalogo":catalogo}
    finally: conn.close()


def atualizar_etapa_catalogo(etapa_id,dados,usuario):
    criar_estrutura()
    with transaction() as conn:
        cur=conn.cursor(); cur.execute(q("UPDATE etapas_catalogo SET nome=?,natureza=?,ativo=?,parametros_json=?,usuario_nome=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"),
          (dados["nome"].strip(),dados["natureza"],int(dados.get("ativo",1)),_json(dados.get("parametros_json")),usuario["nome"],etapa_id))
        if cur.rowcount != 1: raise ValueError("Etapa de catálogo não encontrada.")


def atualizar_sku_versao(versao_id,dados,usuario):
    criar_estrutura()
    with transaction() as conn:
        cur=conn.cursor(); cur.execute(q("""SELECT sv.*, EXISTS(SELECT 1 FROM roteiro_versoes r WHERE r.sku_versao_id=sv.id) usada,
          EXISTS(SELECT 1 FROM op_config_snapshots s WHERE s.sku_versao_id=sv.id) snapshot FROM sku_versoes sv WHERE sv.id=?"""),(versao_id,)); row=cur.fetchone()
        if not row: raise ValueError("Versão de SKU não encontrada.")
        if row["status"] != "RASCUNHO" or row["usada"] or row["snapshot"]: raise ValueError("Versão imutável; crie uma nova versão.")
        unidade=dados["unidade_apresentacao"]
        if unidade not in UNIDADES: raise ValueError("Unidade/apresentação inválida.")
        cur.execute(q("""UPDATE sku_versoes SET nome=?,unidade_apresentacao=?,categoria_tipo=?,vigencia_inicio=?,vigencia_fim=?,
          usuario_id=?,usuario_nome=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"""),(dados["nome"].strip(),unidade,dados["categoria_tipo"],
          dados["vigencia_inicio"],dados.get("vigencia_fim"),usuario.get("id"),usuario["nome"],versao_id))


def atualizar_roteiro(roteiro_id,dados,usuario):
    criar_estrutura()
    with transaction() as conn:
        cur=conn.cursor(); _roteiro_editavel(cur,roteiro_id)
        cur.execute(q("""UPDATE roteiro_versoes SET vigencia_inicio=?,vigencia_fim=?,observacoes=?,parametros_json=?,
          usuario_nome=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"""),(dados["vigencia_inicio"],dados.get("vigencia_fim"),
          dados.get("observacoes"),_json(dados.get("parametros_json")),usuario["nome"],roteiro_id))


def excluir_etapa(roteiro_id,etapa_id):
    criar_estrutura()
    with transaction() as conn:
        cur=conn.cursor(); _roteiro_editavel(cur,roteiro_id)
        cur.execute(q("DELETE FROM roteiro_etapas WHERE id=? AND roteiro_versao_id=?"),(etapa_id,roteiro_id))
        if cur.rowcount != 1: raise ValueError("Etapa não encontrada.")


def ativar_sku_versao(versao_id,usuario):
    criar_estrutura()
    with transaction() as conn:
        cur=conn.cursor(); cur.execute(q("SELECT sku_id,status FROM sku_versoes WHERE id=?"),(versao_id,)); row=cur.fetchone()
        if not row: raise ValueError("Versão de SKU não encontrada.")
        cur.execute(q("SELECT 1 FROM sku_versoes WHERE sku_id=? AND status='ATIVA' AND id<>?"),(row["sku_id"],versao_id))
        if cur.fetchone(): raise ValueError("Já existe uma versão ativa para o SKU.")
        cur.execute(q("UPDATE sku_versoes SET status='ATIVA',usuario_id=?,usuario_nome=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"),(usuario.get("id"),usuario["nome"],versao_id))


def ativar_roteiro(roteiro_id,usuario):
    criar_estrutura()
    with transaction() as conn:
        cur=conn.cursor(); _roteiro_editavel(cur,roteiro_id)
        cur.execute(q("SELECT sku_versao_id FROM roteiro_versoes WHERE id=?"),(roteiro_id,)); sku_versao_id=cur.fetchone()["sku_versao_id"]
        cur.execute(q("SELECT 1 FROM roteiro_versoes WHERE sku_versao_id=? AND status='ATIVO' AND id<>?"),(sku_versao_id,roteiro_id))
        if cur.fetchone(): raise ValueError("Já existe um roteiro ativo para esta versão de SKU.")
        cur.execute(q("""UPDATE roteiro_versoes SET status='ATIVO',aprovado_por=?,aprovado_em=CURRENT_TIMESTAMP,
          usuario_nome=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?"""),(usuario["nome"],usuario["nome"],roteiro_id))
