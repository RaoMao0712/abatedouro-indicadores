"""Requisicoes formais, reservas e baixas rastreaveis do Almoxarifado."""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from database import DATABASE_URL, conectar, q
from modules.parceiros.services import obter_parceiro_elegivel


ORIGEM_REQUISICAO = "REQUISICAO_ALMOXARIFADO"
ORIGEM_ORDEM_PRODUCAO = "ORDEM_PRODUCAO"
ORIGENS_BAIXA = (ORIGEM_REQUISICAO, ORIGEM_ORDEM_PRODUCAO)
STATUS_RESERVA_ATIVA = ("AGUARDANDO_APROVACAO", "EMITIDA")
PERFIS_EMISSAO = frozenset({"admin", "pcp"})
PERFIS_APROVACAO = frozenset({"admin", "gerencia"})
ESCALA = Decimal("0.0001")


class ConflitoRequisicao(RuntimeError):
    """A requisicao mudou desde que a tela foi aberta."""


def _agora():
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _decimal(valor, campo, *, permite_zero=False):
    texto = str(valor if valor is not None else "").strip()
    if not texto:
        raise ValueError(f"Informe {campo.lower()}.")
    if "," in texto and "." in texto:
        raise ValueError(f"{campo} inválida.")
    try:
        numero = Decimal(texto.replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{campo} inválida.") from None
    if not numero.is_finite() or numero < 0 or (numero == 0 and not permite_zero):
        regra = "maior ou igual a zero" if permite_zero else "maior que zero"
        raise ValueError(f"{campo} precisa ser {regra}.")
    if numero.as_tuple().exponent < -4:
        raise ValueError(f"{campo} aceita no máximo 4 casas decimais.")
    return numero.quantize(ESCALA, rounding=ROUND_HALF_UP)


def _alterar_coluna(cursor, conn, tabela, coluna, tipo):
    try:
        if DATABASE_URL:
            cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {coluna} {tipo}")
        else:
            cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
        conn.commit()
    except Exception:
        conn.rollback()


def _id_inserido(cursor):
    if DATABASE_URL:
        cursor.execute("SELECT LASTVAL() AS id")
        return int(cursor.fetchone()["id"])
    return int(cursor.lastrowid)


def criar_tabelas_requisicoes_almoxarifado():
    """Migration aditiva e idempotente da P3.5."""
    from .services import criar_tabelas_estoque_almoxarifado

    criar_tabelas_estoque_almoxarifado()
    conn = conectar()
    cursor = conn.cursor()

    _alterar_coluna(cursor, conn, "almoxarifado_insumos", "origem_baixa", "TEXT")
    for coluna, tipo in (
        ("requisicao_id", "INTEGER"),
        ("requisicao_item_id", "INTEGER"),
        ("parceiro_id", "INTEGER"),
        ("saldo_anterior", "REAL"),
        ("saldo_posterior", "REAL"),
        ("movimento_estornado_id", "INTEGER"),
        ("idempotency_key", "TEXT"),
    ):
        _alterar_coluna(cursor, conn, "almoxarifado_movimentacoes", coluna, tipo)

    id_sql = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_sql = "TIMESTAMP" if DATABASE_URL else "TEXT"
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS almoxarifado_requisicoes (
        id {id_sql},
        numero TEXT NOT NULL UNIQUE,
        parceiro_id INTEGER NOT NULL,
        solicitante_nome TEXT NOT NULL,
        solicitante_papel TEXT NOT NULL,
        setor TEXT NOT NULL,
        finalidade TEXT NOT NULL,
        justificativa TEXT,
        excepcional INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        versao INTEGER NOT NULL DEFAULT 0,
        chave_emissao TEXT NOT NULL UNIQUE,
        emitido_por_id INTEGER,
        emitido_por_nome TEXT NOT NULL,
        emitido_em {timestamp_sql} NOT NULL,
        aprovado_por_id INTEGER,
        aprovado_por_nome TEXT,
        aprovado_em {timestamp_sql},
        rejeitado_por_id INTEGER,
        rejeitado_por_nome TEXT,
        rejeitado_em {timestamp_sql},
        motivo_rejeicao TEXT,
        confirmado_por_id INTEGER,
        confirmado_por_nome TEXT,
        confirmado_em {timestamp_sql},
        documento_fisico_confirmado INTEGER NOT NULL DEFAULT 0,
        cancelado_por_id INTEGER,
        cancelado_por_nome TEXT,
        cancelado_em {timestamp_sql},
        motivo_cancelamento TEXT,
        estornado_por_id INTEGER,
        estornado_por_nome TEXT,
        estornado_em {timestamp_sql},
        motivo_estorno TEXT,
        atualizado_em {timestamp_sql} NOT NULL
    )
    """)
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS almoxarifado_requisicao_itens (
        id {id_sql},
        requisicao_id INTEGER NOT NULL,
        insumo_id INTEGER NOT NULL,
        insumo_descricao TEXT NOT NULL,
        categoria TEXT NOT NULL,
        unidade TEXT NOT NULL,
        origem_baixa TEXT NOT NULL,
        quantidade_solicitada REAL NOT NULL,
        quantidade_reservada REAL NOT NULL,
        quantidade_entregue REAL NOT NULL DEFAULT 0,
        quantidade_baixada REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'RESERVADO',
        criado_em {timestamp_sql} NOT NULL,
        UNIQUE (requisicao_id, insumo_id)
    )
    """)
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS almoxarifado_requisicao_alocacoes (
        id {id_sql},
        requisicao_id INTEGER NOT NULL,
        requisicao_item_id INTEGER NOT NULL,
        lote_id INTEGER NOT NULL,
        movimento_saida_id INTEGER NOT NULL UNIQUE,
        quantidade REAL NOT NULL,
        valor_unitario REAL NOT NULL,
        valor_total REAL NOT NULL,
        movimento_estorno_id INTEGER UNIQUE,
        criado_em {timestamp_sql} NOT NULL,
        estornado_em {timestamp_sql}
    )
    """)
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS almoxarifado_requisicao_eventos (
        id {id_sql},
        requisicao_id INTEGER NOT NULL,
        evento TEXT NOT NULL,
        status_anterior TEXT,
        status_novo TEXT NOT NULL,
        detalhes TEXT,
        usuario_id INTEGER,
        usuario_nome TEXT NOT NULL,
        perfil TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        criado_em {timestamp_sql} NOT NULL
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_almox_req_status ON almoxarifado_requisicoes(status, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_almox_req_parceiro ON almoxarifado_requisicoes(parceiro_id, emitido_em)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_almox_req_item_insumo ON almoxarifado_requisicao_itens(insumo_id, requisicao_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_almox_mov_req ON almoxarifado_movimentacoes(requisicao_id, requisicao_item_id)")
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_almox_mov_idempotencia ON almoxarifado_movimentacoes(idempotency_key) WHERE idempotency_key IS NOT NULL")
    except Exception:
        conn.rollback()

    cursor.execute(q("""
    UPDATE almoxarifado_insumos
       SET origem_baixa = CASE
           WHEN categoria IN (?, ?) THEN ? ELSE ? END
     WHERE origem_baixa IS NULL OR origem_baixa NOT IN (?, ?)
    """), ("Embalagem", "Matéria-prima", ORIGEM_ORDEM_PRODUCAO,
           ORIGEM_REQUISICAO, ORIGEM_REQUISICAO, ORIGEM_ORDEM_PRODUCAO))
    conn.commit()
    conn.close()


def origem_baixa_padrao(categoria):
    return ORIGEM_ORDEM_PRODUCAO if categoria in {"Embalagem", "Matéria-prima"} else ORIGEM_REQUISICAO


def normalizar_itens_form(form):
    ids = form.getlist("insumo_id") if hasattr(form, "getlist") else form.get("insumo_id", [])
    quantidades = form.getlist("quantidade") if hasattr(form, "getlist") else form.get("quantidade", [])
    if not isinstance(ids, (list, tuple)):
        ids = [ids]
    if not isinstance(quantidades, (list, tuple)):
        quantidades = [quantidades]
    return [{"insumo_id": insumo_id, "quantidade": quantidades[indice] if indice < len(quantidades) else ""}
            for indice, insumo_id in enumerate(ids) if str(insumo_id or "").strip()]


def _usuario(usuario):
    return {
        "id": usuario.get("id") or usuario.get("usuario_id"),
        "nome": str(usuario.get("nome") or "Sistema"),
        "perfil": str(usuario.get("perfil") or "").lower(),
    }


def _saldo_fisico(cursor, insumo_id):
    cursor.execute(q("SELECT COALESCE(SUM(quantidade_atual),0) AS saldo FROM almoxarifado_lotes WHERE insumo_id=?"), (insumo_id,))
    return Decimal(str(cursor.fetchone()["saldo"] or 0))


def _reservado(cursor, insumo_id, excluir_requisicao_id=None):
    condicao = " AND r.id<>?" if excluir_requisicao_id else ""
    parametros = [insumo_id, *STATUS_RESERVA_ATIVA]
    if excluir_requisicao_id:
        parametros.append(excluir_requisicao_id)
    cursor.execute(q(f"""
    SELECT COALESCE(SUM(i.quantidade_reservada),0) AS reservado
      FROM almoxarifado_requisicao_itens i
      JOIN almoxarifado_requisicoes r ON r.id=i.requisicao_id
     WHERE i.insumo_id=? AND r.status IN (?,?){condicao}
    """), tuple(parametros))
    return Decimal(str(cursor.fetchone()["reservado"] or 0))


def _evento(cursor, requisicao_id, evento, anterior, novo, detalhes, usuario, chave):
    cursor.execute(q("""
    INSERT INTO almoxarifado_requisicao_eventos
      (requisicao_id,evento,status_anterior,status_novo,detalhes,usuario_id,
       usuario_nome,perfil,idempotency_key,criado_em)
    VALUES (?,?,?,?,?,?,?,?,?,?)
    """), (requisicao_id, evento, anterior, novo, detalhes or None, usuario["id"],
           usuario["nome"], usuario["perfil"], chave, _agora()))


def _iniciar_transacao(conn):
    if not DATABASE_URL:
        conn.execute("BEGIN IMMEDIATE")


def emitir_requisicao(dados, itens, *, usuario, idempotency_key):
    criar_tabelas_requisicoes_almoxarifado()
    usuario = _usuario(usuario)
    if usuario["perfil"] not in PERFIS_EMISSAO:
        raise PermissionError("Usuário sem permissão para emitir requisição.")
    chave = str(idempotency_key or "").strip()
    if not chave:
        raise ValueError("Requisição inválida. Recarregue a página.")
    setor = str(dados.get("setor") or "").strip()
    finalidade = str(dados.get("finalidade") or "").strip()
    justificativa = str(dados.get("justificativa") or "").strip()
    natureza = str(dados.get("solicitante_papel") or "").strip()
    if not setor or not finalidade:
        raise ValueError("Informe setor e finalidade.")
    parceiro, natureza = obter_parceiro_elegivel(dados.get("parceiro_id"), natureza)
    itens = list(itens or [])
    if not itens:
        raise ValueError("Inclua ao menos um item na requisição.")

    conn = conectar()
    try:
        _iniciar_transacao(conn)
        cursor = conn.cursor()
        cursor.execute(q("""SELECT p.id FROM parceiros p JOIN parceiro_papeis pp ON pp.parceiro_id=p.id
            WHERE p.id=? AND p.status='Ativo' AND pp.papel=? AND pp.ativo=1"""),
            (parceiro["id"], natureza))
        if not cursor.fetchone():
            raise ValueError("O solicitante deixou de ser um parceiro ativo elegível. Recarregue a página.")
        cursor.execute(q("SELECT id,numero FROM almoxarifado_requisicoes WHERE chave_emissao=?"), (chave,))
        repetida = cursor.fetchone()
        if repetida:
            conn.rollback()
            return {"id": repetida["id"], "numero": repetida["numero"], "reaplicada": True}

        preparados = []
        vistos = set()
        excepcional = False
        sufixo = " FOR UPDATE" if DATABASE_URL else ""
        for item in itens:
            try:
                insumo_id = int(item.get("insumo_id") or 0)
            except (TypeError, ValueError):
                raise ValueError("Selecione um insumo válido.") from None
            if insumo_id in vistos:
                raise ValueError("Não repita o mesmo insumo na requisição.")
            vistos.add(insumo_id)
            quantidade = _decimal(item.get("quantidade"), "Quantidade")
            cursor.execute(q(f"SELECT * FROM almoxarifado_insumos WHERE id=?{sufixo}"), (insumo_id,))
            insumo = cursor.fetchone()
            if not insumo or insumo["ativo"] != "Sim":
                raise ValueError("A requisição contém insumo inexistente ou inativo.")
            origem = insumo["origem_baixa"] or origem_baixa_padrao(insumo["categoria"])
            if origem == ORIGEM_ORDEM_PRODUCAO:
                excepcional = True
            disponivel = _saldo_fisico(cursor, insumo_id) - _reservado(cursor, insumo_id)
            if quantidade > disponivel:
                raise ValueError(
                    f"Saldo disponível insuficiente para {insumo['descricao']}. "
                    f"Disponível: {disponivel.quantize(ESCALA)} {insumo['unidade']}.")
            preparados.append((dict(insumo), origem, quantidade))

        if excepcional:
            if usuario["perfil"] != "admin":
                raise PermissionError("Somente Administrador pode solicitar exceção para item de consumo por OP.")
            if not justificativa:
                raise ValueError("Informe a justificativa da exceção para item de consumo por OP.")
        status = "AGUARDANDO_APROVACAO" if excepcional else "EMITIDA"
        agora = _agora()
        numero_temporario = f"TEMP-{chave}"
        cursor.execute(q("""
        INSERT INTO almoxarifado_requisicoes
          (numero,parceiro_id,solicitante_nome,solicitante_papel,setor,finalidade,
           justificativa,excepcional,status,chave_emissao,emitido_por_id,
           emitido_por_nome,emitido_em,atualizado_em)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """), (numero_temporario, parceiro["id"], parceiro["razao_social"], natureza,
               setor, finalidade, justificativa or None, int(excepcional), status, chave,
               usuario["id"], usuario["nome"], agora, agora))
        requisicao_id = _id_inserido(cursor)
        numero = f"REQ-{datetime.now():%Y}-{requisicao_id:06d}"
        cursor.execute(q("UPDATE almoxarifado_requisicoes SET numero=? WHERE id=?"), (numero, requisicao_id))
        for insumo, origem, quantidade in preparados:
            cursor.execute(q("""
            INSERT INTO almoxarifado_requisicao_itens
              (requisicao_id,insumo_id,insumo_descricao,categoria,unidade,origem_baixa,
               quantidade_solicitada,quantidade_reservada,criado_em)
            VALUES (?,?,?,?,?,?,?,?,?)
            """), (requisicao_id, insumo["id"], insumo["descricao"], insumo["categoria"],
                   insumo["unidade"], origem, str(quantidade), str(quantidade), agora))
        _evento(cursor, requisicao_id, "EMISSAO", None, status,
                "Reserva criada sem baixa física.", usuario, f"{chave}:emissao")
        conn.commit()
        return {"id": requisicao_id, "numero": numero, "status": status, "reaplicada": False}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _carregar_requisicao_bloqueada(cursor, requisicao_id):
    sufixo = " FOR UPDATE" if DATABASE_URL else ""
    cursor.execute(q(f"SELECT * FROM almoxarifado_requisicoes WHERE id=?{sufixo}"), (requisicao_id,))
    item = cursor.fetchone()
    return dict(item) if item else None


def _validar_versao(requisicao, versao):
    try:
        esperada = int(versao)
    except (TypeError, ValueError):
        raise ConflitoRequisicao("Versão inválida. Recarregue a página.") from None
    if esperada != int(requisicao["versao"] or 0):
        raise ConflitoRequisicao("A requisição foi alterada por outro usuário. Recarregue a página.")


def _evento_repetido(cursor, chave):
    cursor.execute(q("SELECT requisicao_id FROM almoxarifado_requisicao_eventos WHERE idempotency_key=?"), (chave,))
    return cursor.fetchone()


def decidir_excecao(requisicao_id, *, aprovar, motivo, usuario, versao, idempotency_key):
    criar_tabelas_requisicoes_almoxarifado()
    usuario = _usuario(usuario)
    if usuario["perfil"] not in PERFIS_APROVACAO:
        raise PermissionError("Usuário sem permissão para decidir exceções.")
    motivo = str(motivo or "").strip()
    if not aprovar and not motivo:
        raise ValueError("Informe o motivo da rejeição.")
    chave = str(idempotency_key or "").strip()
    if not chave:
        raise ValueError("Decisão inválida. Recarregue a página.")
    conn = conectar()
    try:
        _iniciar_transacao(conn)
        cursor = conn.cursor()
        if _evento_repetido(cursor, chave):
            conn.rollback()
            return buscar_requisicao(requisicao_id)
        req = _carregar_requisicao_bloqueada(cursor, requisicao_id)
        if not req or req["status"] != "AGUARDANDO_APROVACAO":
            raise ValueError("A requisição não está aguardando aprovação.")
        _validar_versao(req, versao)
        mesma_identidade = (
            usuario["id"] is not None and str(usuario["id"]) == str(req["emitido_por_id"])
        ) or (
            usuario["id"] is None and req["emitido_por_id"] is None
            and usuario["nome"].strip().casefold() == str(req["emitido_por_nome"] or "").strip().casefold()
        )
        if mesma_identidade:
            raise PermissionError("O emissor não pode aprovar ou rejeitar a própria exceção.")
        agora = _agora()
        novo = "EMITIDA" if aprovar else "REJEITADA"
        campos = ("aprovado_por_id=?, aprovado_por_nome=?, aprovado_em=?" if aprovar else
                  "rejeitado_por_id=?, rejeitado_por_nome=?, rejeitado_em=?, motivo_rejeicao=?")
        valores = ([usuario["id"], usuario["nome"], agora] if aprovar else
                   [usuario["id"], usuario["nome"], agora, motivo])
        if not aprovar:
            cursor.execute(q("UPDATE almoxarifado_requisicao_itens SET quantidade_reservada=0,status='REJEITADO' WHERE requisicao_id=?"), (requisicao_id,))
        cursor.execute(q(f"UPDATE almoxarifado_requisicoes SET status=?,versao=versao+1,{campos},atualizado_em=? WHERE id=?"),
                       tuple([novo, *valores, agora, requisicao_id]))
        _evento(cursor, requisicao_id, "APROVACAO" if aprovar else "REJEICAO",
                req["status"], novo, motivo, usuario, chave)
        conn.commit()
        return buscar_requisicao(requisicao_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancelar_requisicao(requisicao_id, *, motivo, usuario, versao, idempotency_key):
    criar_tabelas_requisicoes_almoxarifado()
    usuario = _usuario(usuario)
    if usuario["perfil"] not in PERFIS_EMISSAO:
        raise PermissionError("Usuário sem permissão para cancelar requisição.")
    motivo = str(motivo or "").strip()
    if not motivo:
        raise ValueError("Informe o motivo do cancelamento.")
    chave = str(idempotency_key or "").strip()
    if not chave:
        raise ValueError("Cancelamento inválido. Recarregue a página.")
    conn = conectar()
    try:
        _iniciar_transacao(conn)
        cursor = conn.cursor()
        if _evento_repetido(cursor, chave):
            conn.rollback()
            return buscar_requisicao(requisicao_id)
        req = _carregar_requisicao_bloqueada(cursor, requisicao_id)
        if not req or req["status"] not in STATUS_RESERVA_ATIVA:
            raise ValueError("Somente requisição reservada pode ser cancelada.")
        _validar_versao(req, versao)
        agora = _agora()
        cursor.execute(q("UPDATE almoxarifado_requisicao_itens SET quantidade_reservada=0,status='CANCELADO' WHERE requisicao_id=?"), (requisicao_id,))
        cursor.execute(q("""UPDATE almoxarifado_requisicoes SET status='CANCELADA',versao=versao+1,
            cancelado_por_id=?,cancelado_por_nome=?,cancelado_em=?,motivo_cancelamento=?,atualizado_em=? WHERE id=?"""),
            (usuario["id"], usuario["nome"], agora, motivo, agora, requisicao_id))
        _evento(cursor, requisicao_id, "CANCELAMENTO", req["status"], "CANCELADA", motivo, usuario, chave)
        conn.commit()
        return buscar_requisicao(requisicao_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def confirmar_requisicao(requisicao_id, entregas, *, documento_confirmado, usuario, versao, idempotency_key):
    criar_tabelas_requisicoes_almoxarifado()
    usuario = _usuario(usuario)
    if usuario["perfil"] not in PERFIS_EMISSAO:
        raise PermissionError("Usuário sem permissão para confirmar entrega.")
    if str(documento_confirmado).lower() not in {"1", "sim", "on", "true"}:
        raise ValueError("Confirme o recebimento do documento físico assinado.")
    chave = str(idempotency_key or "").strip()
    if not chave:
        raise ValueError("Confirmação inválida. Recarregue a página.")
    conn = conectar()
    try:
        _iniciar_transacao(conn)
        cursor = conn.cursor()
        if _evento_repetido(cursor, chave):
            conn.rollback()
            return buscar_requisicao(requisicao_id)
        req = _carregar_requisicao_bloqueada(cursor, requisicao_id)
        if not req or req["status"] != "EMITIDA":
            raise ValueError("Somente requisição emitida pode ter entrega confirmada.")
        _validar_versao(req, versao)
        cursor.execute(q("SELECT * FROM almoxarifado_requisicao_itens WHERE requisicao_id=? ORDER BY id"), (requisicao_id,))
        itens = [dict(item) for item in cursor.fetchall()]
        por_id = {int(item.get("item_id")): item.get("quantidade") for item in entregas}
        preparados = []
        for item in itens:
            entregue = _decimal(por_id.get(int(item["id"]), 0), "Quantidade entregue", permite_zero=True)
            reservado = Decimal(str(item["quantidade_reservada"] or 0))
            if entregue > reservado:
                raise ValueError(f"Entrega superior à reserva de {item['insumo_descricao']}.")
            preparados.append((item, entregue))
        if not any(quantidade > 0 for _, quantidade in preparados):
            raise ValueError("Informe ao menos uma quantidade entregue maior que zero.")

        agora = _agora()
        data_movimento = date.today().isoformat()
        parcial = False
        for item, entregue in preparados:
            solicitado = Decimal(str(item["quantidade_solicitada"]))
            parcial = parcial or entregue < solicitado
            saldo_anterior = _saldo_fisico(cursor, item["insumo_id"])
            restante = entregue
            sufixo = " FOR UPDATE" if DATABASE_URL else ""
            cursor.execute(q(f"""SELECT * FROM almoxarifado_lotes
                WHERE insumo_id=? AND quantidade_atual>0 AND status='Aberto'
                ORDER BY data_entrada,id{sufixo}"""), (item["insumo_id"],))
            lotes = [dict(lote) for lote in cursor.fetchall()]
            if sum(Decimal(str(lote["quantidade_atual"])) for lote in lotes) < entregue:
                raise ConflitoRequisicao(f"Saldo físico mudou para {item['insumo_descricao']}. Recarregue a página.")
            saldo_corrente = saldo_anterior
            for lote in lotes:
                if restante <= 0:
                    break
                atual = Decimal(str(lote["quantidade_atual"]))
                baixa = min(atual, restante)
                novo_lote = atual - baixa
                valor_unitario = Decimal(str(lote["valor_unitario"] or 0))
                valor_total = (baixa * valor_unitario).quantize(ESCALA, rounding=ROUND_HALF_UP)
                saldo_posterior = saldo_corrente - baixa
                cursor.execute(q("""UPDATE almoxarifado_lotes SET quantidade_atual=?,
                    status=?,versao=COALESCE(versao,0)+1,atualizado_em=? WHERE id=?"""),
                    (str(novo_lote), "Fechado" if novo_lote == 0 else "Aberto", agora, lote["id"]))
                mov_chave = f"{chave}:saida:{item['id']}:{lote['id']}"
                cursor.execute(q("""
                INSERT INTO almoxarifado_movimentacoes
                  (data_movimentacao,tipo,insumo_id,lote_id,quantidade,valor_unitario,
                   valor_total,lote,origem,observacoes,criado_por,requisicao_id,
                   requisicao_item_id,parceiro_id,saldo_anterior,saldo_posterior,idempotency_key)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """), (data_movimento, "SAIDA", item["insumo_id"], lote["id"], str(baixa),
                       str(valor_unitario), str(valor_total), lote["lote"],
                       "SAIDA_REQUISICAO_ALMOXARIFADO", f"Baixa da {req['numero']}", usuario["nome"],
                       requisicao_id, item["id"], req["parceiro_id"], str(saldo_corrente),
                       str(saldo_posterior), mov_chave))
                movimento_id = _id_inserido(cursor)
                cursor.execute(q("""INSERT INTO almoxarifado_requisicao_alocacoes
                    (requisicao_id,requisicao_item_id,lote_id,movimento_saida_id,quantidade,
                     valor_unitario,valor_total,criado_em) VALUES (?,?,?,?,?,?,?,?)"""),
                    (requisicao_id, item["id"], lote["id"], movimento_id, str(baixa),
                     str(valor_unitario), str(valor_total), agora))
                restante -= baixa
                saldo_corrente = saldo_posterior
            status_item = "ATENDIDO" if entregue == solicitado else ("PARCIAL" if entregue > 0 else "NAO_ATENDIDO")
            cursor.execute(q("""UPDATE almoxarifado_requisicao_itens SET quantidade_entregue=?,
                quantidade_baixada=?,quantidade_reservada=0,status=? WHERE id=?"""),
                (str(entregue), str(entregue), status_item, item["id"]))

        novo = "PARCIALMENTE_ATENDIDA" if parcial else "BAIXADA"
        cursor.execute(q("""UPDATE almoxarifado_requisicoes SET status=?,versao=versao+1,
            confirmado_por_id=?,confirmado_por_nome=?,confirmado_em=?,documento_fisico_confirmado=1,
            atualizado_em=? WHERE id=?"""),
            (novo, usuario["id"], usuario["nome"], agora, agora, requisicao_id))
        _evento(cursor, requisicao_id, "CONFIRMACAO_ENTREGA", req["status"], novo,
                "Documento físico assinado confirmado; reserva remanescente liberada.", usuario, chave)
        conn.commit()
        return buscar_requisicao(requisicao_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def estornar_requisicao(requisicao_id, *, motivo, usuario, versao, idempotency_key):
    criar_tabelas_requisicoes_almoxarifado()
    usuario = _usuario(usuario)
    if usuario["perfil"] not in PERFIS_APROVACAO:
        raise PermissionError("Usuário sem permissão para estornar requisição.")
    motivo = str(motivo or "").strip()
    if not motivo:
        raise ValueError("Informe o motivo do estorno.")
    chave = str(idempotency_key or "").strip()
    if not chave:
        raise ValueError("Estorno inválido. Recarregue a página.")
    conn = conectar()
    try:
        _iniciar_transacao(conn)
        cursor = conn.cursor()
        if _evento_repetido(cursor, chave):
            conn.rollback()
            return buscar_requisicao(requisicao_id)
        req = _carregar_requisicao_bloqueada(cursor, requisicao_id)
        if not req or req["status"] not in {"BAIXADA", "PARCIALMENTE_ATENDIDA"}:
            raise ValueError("Somente requisição baixada pode ser estornada.")
        _validar_versao(req, versao)
        cursor.execute(q("""SELECT a.*,i.insumo_id FROM almoxarifado_requisicao_alocacoes a
            JOIN almoxarifado_requisicao_itens i ON i.id=a.requisicao_item_id
            WHERE a.requisicao_id=? AND a.movimento_estorno_id IS NULL ORDER BY a.id"""), (requisicao_id,))
        alocacoes = [dict(item) for item in cursor.fetchall()]
        agora = _agora()
        for alocacao in alocacoes:
            quantidade = Decimal(str(alocacao["quantidade"]))
            saldo_anterior = _saldo_fisico(cursor, alocacao["insumo_id"])
            saldo_posterior = saldo_anterior + quantidade
            cursor.execute(q("""UPDATE almoxarifado_lotes SET quantidade_atual=quantidade_atual+?,
                status='Aberto',versao=COALESCE(versao,0)+1,atualizado_em=? WHERE id=?"""),
                (str(quantidade), agora, alocacao["lote_id"]))
            mov_chave = f"{chave}:estorno:{alocacao['id']}"
            cursor.execute(q("""INSERT INTO almoxarifado_movimentacoes
              (data_movimentacao,tipo,insumo_id,lote_id,quantidade,valor_unitario,valor_total,
               origem,observacoes,criado_por,requisicao_id,requisicao_item_id,parceiro_id,
               saldo_anterior,saldo_posterior,movimento_estornado_id,idempotency_key)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
              (date.today().isoformat(), "ENTRADA", alocacao["insumo_id"], alocacao["lote_id"],
               str(quantidade), alocacao["valor_unitario"], alocacao["valor_total"],
               "ESTORNO_SAIDA_REQUISICAO", motivo, usuario["nome"], requisicao_id,
               alocacao["requisicao_item_id"], req["parceiro_id"], str(saldo_anterior),
               str(saldo_posterior), alocacao["movimento_saida_id"], mov_chave))
            movimento_id = _id_inserido(cursor)
            cursor.execute(q("UPDATE almoxarifado_requisicao_alocacoes SET movimento_estorno_id=?,estornado_em=? WHERE id=?"),
                           (movimento_id, agora, alocacao["id"]))
        cursor.execute(q("""UPDATE almoxarifado_requisicoes SET status='ESTORNADA',versao=versao+1,
            estornado_por_id=?,estornado_por_nome=?,estornado_em=?,motivo_estorno=?,atualizado_em=? WHERE id=?"""),
            (usuario["id"], usuario["nome"], agora, motivo, agora, requisicao_id))
        _evento(cursor, requisicao_id, "ESTORNO", req["status"], "ESTORNADA", motivo, usuario, chave)
        conn.commit()
        return buscar_requisicao(requisicao_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def listar_insumos_requisicao():
    criar_tabelas_requisicoes_almoxarifado()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT i.*,COALESCE(SUM(l.quantidade_atual),0) AS saldo_fisico
            FROM almoxarifado_insumos i LEFT JOIN almoxarifado_lotes l ON l.insumo_id=i.id
            WHERE i.ativo='Sim' GROUP BY i.id ORDER BY i.descricao"""))
        resultado = []
        for row in cursor.fetchall():
            item = dict(row)
            item["reservado"] = float(_reservado(cursor, item["id"]))
            item["disponivel"] = float(Decimal(str(item["saldo_fisico"] or 0)) - Decimal(str(item["reservado"])))
            indicador = _indicadores_cursor(cursor, item["id"], dias=30, hoje=date.today(),
                                             disponivel=Decimal(str(item["disponivel"])))
            item["cobertura_status"] = indicador["status"]
            item["cobertura_dias"] = indicador["cobertura_dias"]
            resultado.append(item)
        return resultado
    finally:
        conn.close()


def listar_requisicoes(filtros=None, limite=300):
    criar_tabelas_requisicoes_almoxarifado()
    filtros = filtros or {}
    condicoes = ["1=1"]
    parametros = []
    for campo, coluna in (("status", "r.status"), ("parceiro_id", "r.parceiro_id")):
        valor = str(filtros.get(campo) or "").strip()
        if valor and valor != "Todos":
            condicoes.append(f"{coluna}=?")
            parametros.append(valor)
    tipo = str(filtros.get("tipo") or "Todos")
    if tipo == "COMUM":
        condicoes.append("r.excepcional=0")
    elif tipo == "EXCECAO":
        condicoes.append("r.excepcional=1")
    if filtros.get("data_inicio"):
        condicoes.append("r.emitido_em>=?")
        parametros.append(filtros["data_inicio"])
    if filtros.get("data_fim"):
        condicoes.append("r.emitido_em<?")
        parametros.append((date.fromisoformat(filtros["data_fim"]) + timedelta(days=1)).isoformat())
    termo = str(filtros.get("termo") or "").strip().lower()
    if termo:
        condicoes.append("(LOWER(r.numero) LIKE ? OR LOWER(r.solicitante_nome) LIKE ? OR EXISTS (SELECT 1 FROM almoxarifado_requisicao_itens i WHERE i.requisicao_id=r.id AND LOWER(i.insumo_descricao) LIKE ?))")
        parametros.extend([f"%{termo}%"] * 3)
    conn = conectar()
    try:
        cursor = conn.cursor()
        parametros.append(int(limite))
        cursor.execute(q(f"""SELECT r.*,
            (SELECT COUNT(*) FROM almoxarifado_requisicao_itens i WHERE i.requisicao_id=r.id) AS total_itens,
            (SELECT COALESCE(SUM(i.quantidade_reservada),0) FROM almoxarifado_requisicao_itens i WHERE i.requisicao_id=r.id) AS total_reservado
            FROM almoxarifado_requisicoes r WHERE {' AND '.join(condicoes)}
            ORDER BY r.id DESC LIMIT ?"""), tuple(parametros))
        return cursor.fetchall()
    finally:
        conn.close()


def buscar_requisicao(requisicao_id):
    criar_tabelas_requisicoes_almoxarifado()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM almoxarifado_requisicoes WHERE id=?"), (requisicao_id,))
        row = cursor.fetchone()
        if not row:
            return None
        req = dict(row)
        cursor.execute(q("SELECT * FROM almoxarifado_requisicao_itens WHERE requisicao_id=? ORDER BY id"), (requisicao_id,))
        req["itens"] = [dict(item) for item in cursor.fetchall()]
        cursor.execute(q("SELECT * FROM almoxarifado_requisicao_eventos WHERE requisicao_id=? ORDER BY id"), (requisicao_id,))
        req["eventos"] = [dict(item) for item in cursor.fetchall()]
        cursor.execute(q("""SELECT m.*,i.insumo_descricao,i.unidade FROM almoxarifado_movimentacoes m
            JOIN almoxarifado_requisicao_itens i ON i.id=m.requisicao_item_id
            WHERE m.requisicao_id=? ORDER BY m.id"""), (requisicao_id,))
        req["movimentacoes"] = [dict(item) for item in cursor.fetchall()]
        return req
    finally:
        conn.close()


def _indicadores_cursor(cursor, insumo_id, *, dias, hoje, disponivel):
    inicio = hoje - timedelta(days=dias - 1)
    cursor.execute(q("""SELECT MIN(data_movimentacao) AS primeira,
        COUNT(DISTINCT data_movimentacao) AS dias_consumo_total
        FROM almoxarifado_movimentacoes
        WHERE insumo_id=? AND tipo='SAIDA' AND origem='SAIDA_REQUISICAO_ALMOXARIFADO'"""),
        (insumo_id,))
    primeira_row = cursor.fetchone()
    primeira = date.fromisoformat(primeira_row["primeira"]) if primeira_row["primeira"] else None
    cursor.execute(q("""SELECT COALESCE(SUM(quantidade),0) AS consumo
            FROM almoxarifado_movimentacoes
            WHERE insumo_id=? AND tipo='SAIDA' AND origem='SAIDA_REQUISICAO_ALMOXARIFADO'
              AND data_movimentacao BETWEEN ? AND ?"""), (insumo_id, inicio.isoformat(), hoje.isoformat()))
    row = cursor.fetchone()
    dias_historico = (hoje - primeira).days + 1 if primeira else 0
    if not primeira or dias_historico < 7 or int(primeira_row["dias_consumo_total"] or 0) < 2:
        return {"status": "N/A — histórico insuficiente", "cobertura_dias": None,
                "consumo": float(row["consumo"] or 0), "disponivel": float(disponivel)}
    consumo = Decimal(str(row["consumo"] or 0))
    if consumo == 0:
        return {"status": "N/A — sem consumo no período", "cobertura_dias": None,
                "consumo": 0, "disponivel": float(disponivel)}
    media = consumo / Decimal(dias)
    cobertura = max(Decimal("0"), disponivel) / media
    return {"status": "Disponível", "cobertura_dias": float(cobertura.quantize(Decimal("0.1"))),
            "consumo": float(consumo), "disponivel": float(disponivel)}


def indicadores_consumo_requisicao(insumo_id, *, dias=30, hoje=None):
    """Cobertura sem fabricar histórico anterior à primeira baixa confirmada."""
    criar_tabelas_requisicoes_almoxarifado()
    hoje = hoje or date.today()
    conn = conectar()
    try:
        cursor = conn.cursor()
        saldo = _saldo_fisico(cursor, insumo_id)
        disponivel = saldo - _reservado(cursor, insumo_id)
        return _indicadores_cursor(cursor, insumo_id, dias=dias, hoje=hoje, disponivel=disponivel)
    finally:
        conn.close()


def gerar_pdf_requisicao(requisicao_id):
    req = buscar_requisicao(requisicao_id)
    if not req:
        raise ValueError("Requisição não encontrada.")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Requisição {req['numero']}")
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("fd", parent=estilos["Title"], alignment=TA_CENTER,
                            textColor=colors.HexColor("#173B2A"), fontSize=18)
    historia = [Paragraph("FRIGODATTA", titulo),
                Paragraph("REQUISIÇÃO DE ALMOXARIFADO", ParagraphStyle("sub", parent=estilos["Heading2"], alignment=TA_CENTER)),
                Spacer(1, 5 * mm)]
    if req["excepcional"]:
        historia.append(Paragraph("EXCEÇÃO CONTROLADA — ITEM DE CONSUMO OFICIAL POR ORDEM DE PRODUÇÃO",
                                  ParagraphStyle("alerta", parent=estilos["Heading3"], alignment=TA_CENTER,
                                                 textColor=colors.HexColor("#A13A20"))))
    metadados = [
        ["Número", req["numero"], "Estado", req["status"].replace("_", " ")],
        ["Emissão", str(req["emitido_em"]), "Emitido por", req["emitido_por_nome"]],
        ["Solicitante", req["solicitante_nome"], "Papel", req["solicitante_papel"].replace("_", " ")],
        ["Setor", req["setor"], "Finalidade", req["finalidade"]],
    ]
    if req.get("justificativa"):
        metadados.append(["Justificativa", req["justificativa"], "", ""])
    tabela_meta = Table(metadados, colWidths=[25 * mm, 58 * mm, 25 * mm, 62 * mm])
    tabela_meta.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.grey),
                                     ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8F0EB")),
                                     ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#E8F0EB")),
                                     ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    historia.extend([tabela_meta, Spacer(1, 5 * mm)])
    dados_itens = [["Item", "Categoria", "Origem oficial", "Solicitado", "Entregue", "Un."]]
    for item in req["itens"]:
        dados_itens.append([item["insumo_descricao"], item["categoria"], item["origem_baixa"].replace("_", " "),
                            str(item["quantidade_solicitada"]), str(item["quantidade_entregue"]), item["unidade"]])
    tabela = Table(dados_itens, repeatRows=1, colWidths=[48 * mm, 30 * mm, 38 * mm, 22 * mm, 22 * mm, 14 * mm])
    tabela.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173B2A")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    historia.extend([tabela, Spacer(1, 14 * mm),
                     Paragraph("__________________________________ &nbsp;&nbsp;&nbsp;&nbsp; __________________________________", estilos["Normal"]),
                     Paragraph("Responsável pela entrega &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; Solicitante / recebedor", estilos["Normal"]),
                     Spacer(1, 8 * mm),
                     Paragraph("O saldo físico somente é baixado após a confirmação deste documento assinado no sistema.", estilos["Italic"])])
    doc.build(historia)
    return buffer.getvalue()
