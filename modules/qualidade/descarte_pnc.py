"""Romaneio e baixa auditada de Produto Acabado Nao Conforme para descarte."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re

from flask import has_request_context, request, session

from database import DATABASE_URL, conectar, q, transaction


PERFIS_GERAR = {"admin", "pcp", "gerencia", "qualidade"}
PERFIS_ESTORNAR = {"admin", "gerencia"}
STATUS_DESTINADOS = {"DESCARTE", "DESCARTE_PARCIAL"}
PENDENTE_LIBERACAO = "AGUARDANDO_VALIDACAO_GERENCIA"
CANCELADA_LIBERACAO = "CANCELADA_POR_DESTINACAO_DESCARTE"


def _agora():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _identidade(usuario=None, perfil=None, origem=None):
    if has_request_context():
        usuario = usuario or session.get("nome") or "Usuário não identificado"
        perfil = perfil or session.get("perfil") or "não identificado"
        origem = origem or request.remote_addr or "web"
    return usuario or "Sistema", str(perfil or "sistema").lower(), origem or "interno"


def _inteiro(valor, campo):
    if valor in (None, ""):
        return 0
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError) as erro:
        raise ValueError(f"{campo} deve ser um número inteiro.") from erro
    if numero < 0:
        raise ValueError(f"{campo} não pode ser negativo.")
    return numero


def _gramas(valor, campo="Peso"):
    if valor in (None, ""):
        return 0
    texto = str(valor).strip().replace(".", "").replace(",", ".") if "," in str(valor) else str(valor).strip()
    try:
        numero = Decimal(texto)
    except InvalidOperation as erro:
        raise ValueError(f"{campo} inválido.") from erro
    if numero < 0:
        raise ValueError(f"{campo} não pode ser negativo.")
    return int((numero * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dict(linha):
    return dict(linha) if linha is not None else None


def criar_tabelas_descarte_pnc():
    """Schema runtime idempotente; os SQLs versionados são a fonte para o deploy."""
    conn = conectar()
    cursor = conn.cursor()
    ident = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if DATABASE_URL else "TEXT"
    try:
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS pnc_romaneios_descarte (
            id {ident}, numero TEXT NOT NULL UNIQUE, pa_nao_conforme_id INTEGER NOT NULL,
            status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
            saida_fisica_em {ts} NOT NULL, lancado_em {ts} NOT NULL,
            saida_ja_realizada INTEGER NOT NULL DEFAULT 0,
            destino TEXT NOT NULL, motorista TEXT NOT NULL, motorista_cpf TEXT,
            placa TEXT NOT NULL, responsavel_entrega TEXT NOT NULL,
            responsavel_recebimento TEXT, observacoes TEXT, referencia_manual TEXT,
            usuario_emissor TEXT NOT NULL, perfil_emissor TEXT NOT NULL,
            snapshot_json TEXT NOT NULL, justificativa_estorno TEXT,
            estornado_por TEXT, estornado_em {ts}, criado_em {ts} NOT NULL
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS pnc_romaneio_descarte_itens (
            id {ident}, romaneio_id INTEGER NOT NULL UNIQUE, pa_nao_conforme_id INTEGER NOT NULL,
            produto TEXT NOT NULL, apresentacao TEXT, motivo TEXT,
            caixas INTEGER NOT NULL DEFAULT 0, bandejas INTEGER NOT NULL DEFAULT 0,
            galinhas INTEGER NOT NULL DEFAULT 0, pacotes INTEGER NOT NULL DEFAULT 0,
            peso_g INTEGER NOT NULL DEFAULT 0, snapshot_json TEXT NOT NULL
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS pnc_movimentos_descarte (
            id {ident}, pa_nao_conforme_id INTEGER NOT NULL, romaneio_id INTEGER NOT NULL,
            movimento_origem_id INTEGER, tipo TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
            produto TEXT NOT NULL, caixas INTEGER NOT NULL DEFAULT 0,
            bandejas INTEGER NOT NULL DEFAULT 0, galinhas INTEGER NOT NULL DEFAULT 0,
            pacotes INTEGER NOT NULL DEFAULT 0, peso_g INTEGER NOT NULL DEFAULT 0,
            usuario TEXT NOT NULL, perfil TEXT NOT NULL, saida_fisica_em {ts} NOT NULL,
            lancado_em {ts} NOT NULL, destino TEXT NOT NULL, justificativa TEXT NOT NULL,
            criado_em {ts} NOT NULL
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS pnc_romaneio_numeracoes (
            data_chave TEXT PRIMARY KEY, ultimo_numero INTEGER NOT NULL
        )""")
        for comando in (
            "CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_pnc ON pnc_romaneios_descarte(pa_nao_conforme_id, criado_em)",
            "CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_saida ON pnc_romaneios_descarte(saida_fisica_em, status)",
            "CREATE INDEX IF NOT EXISTS idx_pnc_mov_descarte_pnc ON pnc_movimentos_descarte(pa_nao_conforme_id, criado_em)",
            "CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_status_saida ON pnc_romaneios_descarte(status, saida_fisica_em)",
            "CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_lancamento_status ON pnc_romaneios_descarte(status, lancado_em)",
            "CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_emissao_status ON pnc_romaneios_descarte(status, criado_em)",
            "CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_destino ON pnc_romaneios_descarte(destino)",
            "CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_item_classificacao ON pnc_romaneio_descarte_itens(produto, apresentacao, motivo)",
        ):
            cursor.execute(comando)
        colunas = ("galinhas_bloqueadas INTEGER NOT NULL DEFAULT 0", "pacotes_bloqueados INTEGER NOT NULL DEFAULT 0")
        for coluna in colunas:
            try:
                cursor.execute((f"ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS {coluna}"
                                if DATABASE_URL else f"ALTER TABLE pa_nao_conformes ADD COLUMN {coluna}"))
            except Exception:
                if DATABASE_URL:
                    raise
        try:
            cursor.execute(("ALTER TABLE pa_nao_conforme_solicitacoes ADD COLUMN IF NOT EXISTS romaneio_descarte_id INTEGER"
                            if DATABASE_URL else "ALTER TABLE pa_nao_conforme_solicitacoes ADD COLUMN romaneio_descarte_id INTEGER"))
        except Exception:
            if DATABASE_URL:
                raise
        if DATABASE_URL:
            cursor.execute("""CREATE OR REPLACE FUNCTION impedir_mutacao_pnc_descarte() RETURNS trigger AS $$
                BEGIN RAISE EXCEPTION 'Movimento/snapshot de descarte é imutável'; END; $$ LANGUAGE plpgsql""")
            for tabela in ("pnc_movimentos_descarte", "pnc_romaneio_descarte_itens"):
                cursor.execute(f"DROP TRIGGER IF EXISTS trg_{tabela}_imutavel ON {tabela}")
                cursor.execute(f"CREATE TRIGGER trg_{tabela}_imutavel BEFORE UPDATE OR DELETE ON {tabela} FOR EACH ROW EXECUTE FUNCTION impedir_mutacao_pnc_descarte()")
        else:
            for tabela in ("pnc_movimentos_descarte", "pnc_romaneio_descarte_itens"):
                for acao in ("UPDATE", "DELETE"):
                    nome = f"trg_{tabela}_{acao.lower()}_imutavel"
                    cursor.execute(f"CREATE TRIGGER IF NOT EXISTS {nome} BEFORE {acao} ON {tabela} BEGIN SELECT RAISE(ABORT, 'Movimento/snapshot de descarte e imutavel'); END")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _bloqueio():
    return " FOR UPDATE" if DATABASE_URL else ""


def _proximo_numero(cursor, agora):
    chave = agora[:10].replace("-", "")
    cursor.execute(q("INSERT INTO pnc_romaneio_numeracoes(data_chave, ultimo_numero) VALUES (?, 0) ON CONFLICT(data_chave) DO NOTHING"), (chave,))
    cursor.execute(q("SELECT ultimo_numero FROM pnc_romaneio_numeracoes WHERE data_chave=?" + _bloqueio()), (chave,))
    sequencia = int(cursor.fetchone()["ultimo_numero"]) + 1
    cursor.execute(q("UPDATE pnc_romaneio_numeracoes SET ultimo_numero=? WHERE data_chave=?"), (sequencia, chave))
    return f"RDPNC-{chave}-{sequencia:06d}"


def _disponiveis(registro, pendentes=None):
    legado = registro["tipo_registro"] == "INVENTARIO_LEGADO_AGREGADO"
    saldo_parcial = registro["status"] == "DESCARTE_PARCIAL"
    peso = int(registro["saldo_bloqueado_g"] or 0) if legado or saldo_parcial else _gramas(registro["peso"] or 0)
    caixas = int(registro["caixas_bloqueadas"] or 0) if legado or saldo_parcial else 1
    bandejas = int(registro["bandejas_bloqueadas"] or 0) if legado or saldo_parcial else (int(registro["quantidade"] or 0) if str(registro["unidade"]).upper() == "BANDEJA" else 0)
    pacotes = int(registro["pacotes_bloqueados"] or 0) if "pacotes_bloqueados" in registro.keys() else 0
    galinhas = int(registro["galinhas_bloqueadas"] or 0) if "galinhas_bloqueadas" in registro.keys() else 0
    if not legado and str(registro["unidade"]).upper() == "PACOTE":
        pacotes = int(registro["quantidade"] or 0)
        fator = 2 if re.search(r"2\s*aves?", str(registro["apresentacao"] or ""), re.I) else 1
        galinhas = pacotes * fator
    return {"peso_g": peso, "caixas": caixas, "bandejas": bandejas, "pacotes": pacotes, "galinhas": galinhas}


def previa_saida_descarte_pnc(registro, dados):
    """Valida e monta uma prévia sem gravar ou reservar saldo."""
    registro = _dict(registro)
    if not registro or registro["status"] not in STATUS_DESTINADOS:
        raise ValueError("O Produto Não Conforme não está destinado a descarte.")
    disponivel = _disponiveis(registro)
    integral = str(dados.get("modalidade") or "INTEGRAL").upper() == "INTEGRAL"
    saida = dict(disponivel) if integral else {
        "caixas": _inteiro(dados.get("caixas"), "Caixas"),
        "bandejas": _inteiro(dados.get("bandejas"), "Bandejas"),
        "galinhas": _inteiro(dados.get("galinhas"), "Galinhas"),
        "pacotes": _inteiro(dados.get("pacotes"), "Pacotes"),
        "peso_g": _gramas(dados.get("peso")),
    }
    _validar_unidades_produto(registro, saida, integral)
    _validar_quantidades(saida, disponivel)
    return {"disponivel": disponivel, "saida": saida,
            "remanescente": {k: disponivel[k] - saida[k] for k in disponivel},
            "numero_provisorio": f"PRÉVIA-RDPNC-{datetime.now():%Y%m%d}-{registro['id']:06d}"}


def _validar_quantidades(saida, disponivel):
    if not any(int(v or 0) > 0 for v in saida.values()):
        raise ValueError("Informe ao menos uma quantidade para descarte.")
    for chave, rotulo in (("peso_g", "peso"), ("caixas", "caixas"), ("bandejas", "bandejas"), ("galinhas", "galinhas"), ("pacotes", "pacotes")):
        if int(saida[chave] or 0) > int(disponivel[chave] or 0):
            raise ValueError(f"A saída de {rotulo} excede o saldo disponível.")


def _validar_unidades_produto(registro, saida, integral):
    if integral:
        return
    inteira = "galinha inteira" in f"{registro['produto']} {registro['apresentacao']}".casefold()
    if inteira and any(saida[k] for k in ("caixas", "bandejas", "peso_g")):
        raise ValueError("Galinha Inteira deve ser informada somente em galinhas e pacotes.")
    if not inteira and any(saida[k] for k in ("galinhas", "pacotes")):
        raise ValueError("Galinha Cortada deve ser informada somente em caixas, bandejas e peso.")


def _validar_campos(dados):
    obrigatorios = (("destino", "Destino"), ("motorista", "Motorista"), ("placa", "Placa"),
                    ("responsavel_entrega", "Responsável pela entrega"), ("data_saida", "Data da saída"),
                    ("hora_saida", "Hora da saída"))
    limpos = {k: str(v or "").strip() for k, v in dados.items()}
    for chave, rotulo in obrigatorios:
        if not limpos.get(chave):
            raise ValueError(f"{rotulo} é obrigatório.")
    try:
        fisica = datetime.fromisoformat(f"{limpos['data_saida']}T{limpos['hora_saida']}")
    except ValueError as erro:
        raise ValueError("Data ou hora da saída inválida.") from erro
    if fisica > datetime.now():
        raise ValueError("A data/hora física da saída não pode estar no futuro.")
    posterior = limpos.get("saida_ja_realizada") in {"1", "on", "true", "True"}
    if fisica.date() < datetime.now().date() and not posterior:
        raise ValueError("Marque 'Saída já realizada' para informar uma data física anterior.")
    return limpos, fisica.isoformat(sep=" ", timespec="seconds")


def registrar_saida_descarte_pnc(registro_id, dados, *, usuario=None, perfil=None, origem=None, checkpoint=None):
    """Confirma documento, movimento e saldos em uma única transação."""
    criar_tabelas_descarte_pnc()
    usuario, perfil, origem = _identidade(usuario, perfil, origem)
    if perfil not in PERFIS_GERAR:
        raise PermissionError("Perfil sem permissão para registrar saída de descarte.")
    dados, saida_fisica_em = _validar_campos(dados)
    chave = dados.get("idempotency_key")
    if not chave or len(chave) > 160:
        raise ValueError("Chave de idempotência inválida.")
    lancado_em = _agora()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM pnc_romaneios_descarte WHERE idempotency_key=?" + _bloqueio()), (chave,))
        existente = cursor.fetchone()
        if existente:
            return _dict(existente)
        cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE id=?" + _bloqueio()), (registro_id,))
        registro = cursor.fetchone()
        if not registro:
            raise ValueError("Produto Não Conforme não encontrado.")
        if registro["status"] not in STATUS_DESTINADOS:
            raise ValueError("O Produto Não Conforme não está disponível para descarte.")
        if int(registro["saldo_operacional_g"] or 0) != 0:
            raise ValueError("Inconsistência impeditiva: o PNC destinado a descarte possui saldo operacional.")
        cursor.execute(q("SELECT id FROM pa_nao_conforme_solicitacoes WHERE pa_nao_conforme_id=? AND status=?" + _bloqueio()),
                       (registro_id, PENDENTE_LIBERACAO))
        cursor.fetchall()  # bloqueia as solicitações; o saldo bloqueado já inclui o peso reservado.
        disponivel = _disponiveis(registro)
        integral = dados.get("modalidade", "INTEGRAL").upper() == "INTEGRAL"
        saida = dict(disponivel) if integral else {
            "caixas": _inteiro(dados.get("caixas"), "Caixas"), "bandejas": _inteiro(dados.get("bandejas"), "Bandejas"),
            "galinhas": _inteiro(dados.get("galinhas"), "Galinhas"), "pacotes": _inteiro(dados.get("pacotes"), "Pacotes"),
            "peso_g": _gramas(dados.get("peso")),
        }
        _validar_unidades_produto(registro, saida, integral)
        _validar_quantidades(saida, disponivel)
        if checkpoint: checkpoint("revalidado")
        numero = _proximo_numero(cursor, lancado_em)
        remanescente = {k: disponivel[k] - saida[k] for k in disponivel}
        snapshot = {
            "numero": numero, "pnc_id": registro_id, "pnc_numero": registro["numero"],
            "produto": registro["produto"], "apresentacao": registro["apresentacao"],
            "motivo": registro["motivo"], "origem": registro["origem_entrada"],
            "saida_fisica_em": saida_fisica_em, "lancado_em": lancado_em,
            "saida_ja_realizada": dados.get("saida_ja_realizada") in {"1", "on", "true", "True"},
            "destino": dados["destino"], "motorista": dados["motorista"], "motorista_cpf": dados.get("motorista_cpf"),
            "placa": dados["placa"].upper(), "responsavel_entrega": dados["responsavel_entrega"],
            "responsavel_recebimento": dados.get("responsavel_recebimento"), "observacoes": dados.get("observacoes"),
            "referencia_manual": dados.get("referencia_manual"), "usuario_emissor": usuario,
            "saldo_anterior": disponivel, "saida": saida, "saldo_remanescente": remanescente,
        }
        snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        parametros = (numero, registro_id, "CONFIRMADO", chave, saida_fisica_em, lancado_em,
            1 if snapshot["saida_ja_realizada"] else 0, dados["destino"], dados["motorista"], dados.get("motorista_cpf"),
            dados["placa"].upper(), dados["responsavel_entrega"], dados.get("responsavel_recebimento"), dados.get("observacoes"),
            dados.get("referencia_manual"), usuario, perfil, snapshot_json, lancado_em)
        sql = """INSERT INTO pnc_romaneios_descarte(numero,pa_nao_conforme_id,status,idempotency_key,
            saida_fisica_em,lancado_em,saida_ja_realizada,destino,motorista,motorista_cpf,placa,
            responsavel_entrega,responsavel_recebimento,observacoes,referencia_manual,usuario_emissor,
            perfil_emissor,snapshot_json,criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        if DATABASE_URL:
            cursor.execute(q(sql + " RETURNING id"), parametros); romaneio_id = cursor.fetchone()["id"]
        else:
            cursor.execute(q(sql), parametros); romaneio_id = cursor.lastrowid
        cursor.execute(q("""INSERT INTO pnc_romaneio_descarte_itens(romaneio_id,pa_nao_conforme_id,produto,
            apresentacao,motivo,caixas,bandejas,galinhas,pacotes,peso_g,snapshot_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)"""), (romaneio_id,registro_id,registro["produto"],registro["apresentacao"],
            registro["motivo"],saida["caixas"],saida["bandejas"],saida["galinhas"],saida["pacotes"],saida["peso_g"],snapshot_json))
        cursor.execute(q("""INSERT INTO pnc_movimentos_descarte(pa_nao_conforme_id,romaneio_id,tipo,
            idempotency_key,produto,caixas,bandejas,galinhas,pacotes,peso_g,usuario,perfil,saida_fisica_em,
            lancado_em,destino,justificativa,criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
            (registro_id,romaneio_id,"SAIDA_DESCARTE_PNC",f"{chave}:MOV",registro["produto"],saida["caixas"],saida["bandejas"],
             saida["galinhas"],saida["pacotes"],saida["peso_g"],usuario,perfil,saida_fisica_em,lancado_em,dados["destino"],
             registro["justificativa_destinacao"] or "Destinação para descarte",lancado_em))
        cursor.execute(q("""UPDATE pa_nao_conforme_solicitacoes SET status=?, decidido_por=?, perfil_decisor=?,
            decidido_em=?, justificativa_decisao=?, atualizado_em=?, romaneio_descarte_id=?
            WHERE pa_nao_conforme_id=? AND status=?"""), (CANCELADA_LIBERACAO,usuario,perfil,lancado_em,
            f"Superada pelo romaneio de descarte {numero}",lancado_em,romaneio_id,registro_id,PENDENTE_LIBERACAO))
        novo_status = "DESCARTADO" if not any(remanescente.values()) else "DESCARTE_PARCIAL"
        cursor.execute(q("""UPDATE pa_nao_conformes SET saldo_bloqueado_g=?, saldo_pendente_g=0,
            caixas_bloqueadas=?, bandejas_bloqueadas=?, galinhas_bloqueadas=?, pacotes_bloqueados=?,
            status=?, atualizado_em=? WHERE id=?"""), (remanescente["peso_g"],remanescente["caixas"],
            remanescente["bandejas"],remanescente["galinhas"],remanescente["pacotes"],novo_status,lancado_em,registro_id))
        detalhes = json.dumps({"romaneio_id":romaneio_id,"numero":numero,"movimento":"SAIDA_DESCARTE_PNC",
            "saida":saida,"saldo_anterior":disponivel,"saldo_remanescente":remanescente,
            "lancamento_posterior":snapshot["saida_ja_realizada"]}, ensure_ascii=False, sort_keys=True)
        cursor.execute(q("""INSERT INTO pa_nao_conforme_eventos(pa_nao_conforme_id,acao,status_anterior,status_novo,
            usuario,perfil,justificativa,detalhes,origem,criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)"""),
            (registro_id,"SAIDA_DESCARTE_REGISTRADA_POSTERIORMENTE" if snapshot["saida_ja_realizada"] else "SAIDA_DESCARTE_PNC",
             registro["status"],novo_status,usuario,perfil,registro["justificativa_destinacao"],detalhes,origem,lancado_em))
        if checkpoint: checkpoint("antes_commit")
        cursor.execute(q("SELECT * FROM pnc_romaneios_descarte WHERE id=?"), (romaneio_id,))
        return _dict(cursor.fetchone())


def listar_romaneios_descarte():
    criar_tabelas_descarte_pnc()
    conn = conectar()
    try:
        cur = conn.cursor(); cur.execute("""SELECT r.*,i.produto,i.motivo,i.caixas,i.bandejas,i.galinhas,i.pacotes,i.peso_g,
            nc.numero AS pnc_numero FROM pnc_romaneios_descarte r JOIN pnc_romaneio_descarte_itens i ON i.romaneio_id=r.id
            JOIN pa_nao_conformes nc ON nc.id=r.pa_nao_conforme_id ORDER BY r.saida_fisica_em DESC,r.id DESC""")
        return cur.fetchall()
    finally: conn.close()


def obter_romaneio_descarte(romaneio_id):
    criar_tabelas_descarte_pnc(); conn = conectar()
    try:
        cur=conn.cursor(); cur.execute(q("SELECT * FROM pnc_romaneios_descarte WHERE id=?"),(romaneio_id,)); linha=cur.fetchone()
        if not linha: return None
        resultado=_dict(linha); resultado["snapshot"]=json.loads(resultado["snapshot_json"]); return resultado
    finally: conn.close()


def cancelar_romaneio_descarte(romaneio_id, justificativa, *, usuario=None, perfil=None):
    """Cancela somente eventual rascunho, sem apagar documento ou movimentar saldo."""
    criar_tabelas_descarte_pnc(); usuario,perfil,_=_identidade(usuario,perfil)
    if perfil not in PERFIS_GERAR: raise PermissionError("Perfil sem permissão para cancelar romaneio de descarte.")
    justificativa=str(justificativa or "").strip()
    if not justificativa: raise ValueError("A justificativa do cancelamento é obrigatória.")
    with transaction() as conn:
        cur=conn.cursor(); cur.execute(q("SELECT status FROM pnc_romaneios_descarte WHERE id=?"+_bloqueio()),(romaneio_id,)); rom=cur.fetchone()
        if not rom: raise ValueError("Romaneio de descarte não encontrado.")
        if rom["status"] != "RASCUNHO":
            raise ValueError("Saída confirmada não pode ser cancelada; utilize estorno autorizado.")
        cur.execute(q("UPDATE pnc_romaneios_descarte SET status='CANCELADO',justificativa_estorno=?,estornado_por=?,estornado_em=? WHERE id=? AND status='RASCUNHO'"),
                    (justificativa,usuario,_agora(),romaneio_id))
        return {"romaneio_id":romaneio_id,"status":"CANCELADO"}


def estornar_romaneio_descarte(romaneio_id, justificativa, *, usuario=None, perfil=None, origem=None):
    criar_tabelas_descarte_pnc(); usuario,perfil,origem=_identidade(usuario,perfil,origem)
    if perfil not in PERFIS_ESTORNAR: raise PermissionError("Perfil sem permissão para estornar romaneio de descarte.")
    justificativa=str(justificativa or "").strip()
    if not justificativa: raise ValueError("A justificativa do estorno é obrigatória.")
    agora=_agora()
    with transaction() as conn:
        cur=conn.cursor(); cur.execute(q("SELECT * FROM pnc_romaneios_descarte WHERE id=?"+_bloqueio()),(romaneio_id,)); rom=cur.fetchone()
        if not rom: raise ValueError("Romaneio de descarte não encontrado.")
        if rom["status"]=="ESTORNADO": raise ValueError("Este romaneio já foi estornado.")
        if rom["status"]!="CONFIRMADO": raise ValueError("Somente saída confirmada pode ser estornada por este fluxo.")
        cur.execute(q("SELECT * FROM pa_nao_conformes WHERE id=?"+_bloqueio()),(rom["pa_nao_conforme_id"],)); nc=cur.fetchone()
        cur.execute(q("SELECT * FROM pnc_romaneio_descarte_itens WHERE romaneio_id=?"),(romaneio_id,)); item=cur.fetchone()
        novos={"peso_g":int(nc["saldo_bloqueado_g"] or 0)+int(item["peso_g"]),"caixas":int(nc["caixas_bloqueadas"] or 0)+int(item["caixas"]),
            "bandejas":int(nc["bandejas_bloqueadas"] or 0)+int(item["bandejas"]),"galinhas":int(nc["galinhas_bloqueadas"] or 0)+int(item["galinhas"]),
            "pacotes":int(nc["pacotes_bloqueados"] or 0)+int(item["pacotes"])}
        cur.execute(q("SELECT id FROM pnc_movimentos_descarte WHERE romaneio_id=? AND tipo='SAIDA_DESCARTE_PNC'"),(romaneio_id,)); origem_mov=cur.fetchone()["id"]
        cur.execute(q("""INSERT INTO pnc_movimentos_descarte(pa_nao_conforme_id,romaneio_id,movimento_origem_id,tipo,idempotency_key,
            produto,caixas,bandejas,galinhas,pacotes,peso_g,usuario,perfil,saida_fisica_em,lancado_em,destino,justificativa,criado_em)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),(nc["id"],romaneio_id,origem_mov,"ESTORNO_SAIDA_DESCARTE_PNC",f"ESTORNO:{romaneio_id}",item["produto"],
            item["caixas"],item["bandejas"],item["galinhas"],item["pacotes"],item["peso_g"],usuario,perfil,rom["saida_fisica_em"],agora,rom["destino"],justificativa,agora))
        cur.execute(q("UPDATE pnc_romaneios_descarte SET status='ESTORNADO',justificativa_estorno=?,estornado_por=?,estornado_em=? WHERE id=? AND status='CONFIRMADO'"),(justificativa,usuario,agora,romaneio_id))
        cur.execute(q("SELECT COUNT(*) total FROM pnc_romaneios_descarte WHERE pa_nao_conforme_id=? AND status='CONFIRMADO'"),(nc["id"],)); ativos=int(cur.fetchone()["total"])
        novo="DESCARTE" if ativos==0 else "DESCARTE_PARCIAL"
        cur.execute(q("""UPDATE pa_nao_conformes SET saldo_bloqueado_g=?,caixas_bloqueadas=?,bandejas_bloqueadas=?,galinhas_bloqueadas=?,pacotes_bloqueados=?,status=?,atualizado_em=? WHERE id=?"""),
            (novos["peso_g"],novos["caixas"],novos["bandejas"],novos["galinhas"],novos["pacotes"],novo,agora,nc["id"]))
        cur.execute(q("""INSERT INTO pa_nao_conforme_eventos(pa_nao_conforme_id,acao,status_anterior,status_novo,usuario,perfil,justificativa,detalhes,origem,criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)"""),
            (nc["id"],"ESTORNO_SAIDA_DESCARTE_PNC",nc["status"],novo,usuario,perfil,justificativa,json.dumps({"romaneio_id":romaneio_id,"saldo_restaurado":novos},ensure_ascii=False),origem,agora))
        return {"romaneio_id":romaneio_id,"status":"ESTORNADO","pnc_status":novo}
