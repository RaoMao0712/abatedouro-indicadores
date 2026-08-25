"""Governanca do Produto Acabado Nao Conforme ligado ao estoque fisico de PA."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import has_request_context, request, session

from database import DATABASE_URL, conectar, q, transaction


STATUS = {
    "BLOQUEADO", "EM_AVALIACAO", "LIBERADO", "RETRABALHO",
    "REPROCESSO", "REPROCESSADO", "DESCARTE", "DESCARTE_PARCIAL", "DESCARTADO",
    "MANTIDO_BLOQUEADO", "CANCELADO",
}
STATUS_LABELS = {
    "BLOQUEADO": "Bloqueado", "EM_AVALIACAO": "Em avaliação",
    "LIBERADO": "Liberado", "RETRABALHO": "Destinado a retrabalho",
    "REPROCESSO": "Destinado a reprocesso", "DESCARTE": "Destinado a descarte",
    "REPROCESSADO": "Reprocessado",
    "DESCARTE_PARCIAL": "Parcialmente descartado", "DESCARTADO": "Descartado",
    "MANTIDO_BLOQUEADO": "Mantido bloqueado", "CANCELADO": "Cancelado",
}
STATUS_TERMINAIS = {
    "LIBERADO", "RETRABALHO", "REPROCESSADO", "DESCARTADO", "CANCELADO",
    "CANCELADA", "ESTORNADO",
}
SITUACOES = {
    "ATIVOS": "Ativos", "FINALIZADOS": "Finalizados", "TODOS": "Todos",
    "BLOQUEADOS": "Bloqueados", "AGUARDANDO_AVALIACAO": "Aguardando avaliação",
    "REPROCESSAMENTO": "Reprocessamento", "DESTINADOS_DESCARTE": "Destinados a descarte",
    "DESCARTE_PARCIAL": "Descarte parcial",
    "DESCARTADOS": "Descartados", "LIBERADOS": "Liberados",
    "CANCELADOS": "Cancelados",
}
MOTIVOS = (
    "Carne Escura", "Carcaça Incompleta", "Aguardando Liberação",
    "Embalagem danificada", "Rotulagem incorreta", "Peso fora do padrão",
    "Temperatura fora do padrão", "Falha de selagem", "Contaminação visível",
    "Aspecto inadequado", "Produto fora da especificação",
    "Falha de identificação do lote", "Dano durante o processo",
    "Aguardando avaliação da Qualidade", "Outro",
)
PERFIS_DECISAO = {"qualidade", "gerencia", "admin"}
TIPO_LEGADO = "INVENTARIO_LEGADO_AGREGADO"
LOCAL_PADRAO = "Abatedouro — Área de Produto Não Conforme"


def _agora():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _identidade(usuario=None, perfil=None, origem=None):
    if has_request_context():
        usuario = usuario or session.get("nome") or "Usuário não identificado"
        perfil = perfil or session.get("perfil") or "não identificado"
        origem = origem or request.remote_addr or "web"
    return usuario or "Sistema", (perfil or "sistema").lower(), origem or "interno"


def _alterar_coluna(cursor, postgres_sql, sqlite_sql):
    try:
        cursor.execute(postgres_sql if DATABASE_URL else sqlite_sql)
    except Exception:
        if DATABASE_URL:
            raise


def criar_tabelas_pa_nao_conforme():
    """Migration de runtime idempotente, equivalente aos artefatos SQL versionados."""
    conn = conectar()
    cursor = conn.cursor()
    id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_type = "TIMESTAMP" if DATABASE_URL else "TEXT"
    try:
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS pa_nao_conformes (
            id {id_type}, numero TEXT UNIQUE NOT NULL, op_id INTEGER,
            caixa_id INTEGER UNIQUE, lote TEXT, produto TEXT NOT NULL,
            apresentacao TEXT NOT NULL, quantidade REAL NOT NULL, peso REAL,
            unidade TEXT NOT NULL, motivo TEXT NOT NULL, descricao TEXT,
            status TEXT NOT NULL DEFAULT 'BLOQUEADO', local_estoque_id INTEGER NOT NULL,
            registrado_por TEXT NOT NULL, perfil_registro TEXT NOT NULL,
            registrado_em {timestamp_type} NOT NULL, decisao TEXT,
            justificativa_destinacao TEXT, observacoes TEXT,
            decidido_por TEXT, perfil_decisao TEXT, decidido_em {timestamp_type},
            criado_em {timestamp_type} NOT NULL, atualizado_em {timestamp_type} NOT NULL,
            tipo_registro TEXT NOT NULL DEFAULT 'CAIXA_RASTREADA',
            idempotency_key TEXT UNIQUE, validade TEXT, origem_entrada TEXT,
            data_contagem TEXT, responsaveis_contagem TEXT, validacao_qualidade TEXT,
            validacao_gerencia TEXT, condicao_inicial TEXT,
            caixas_iniciais INTEGER NOT NULL DEFAULT 0,
            bandejas_iniciais INTEGER NOT NULL DEFAULT 0,
            caixas_bloqueadas INTEGER NOT NULL DEFAULT 0,
            bandejas_bloqueadas INTEGER NOT NULL DEFAULT 0,
            galinhas_bloqueadas INTEGER NOT NULL DEFAULT 0,
            pacotes_bloqueados INTEGER NOT NULL DEFAULT 0,
            saldo_inicial_g INTEGER NOT NULL DEFAULT 0,
            saldo_bloqueado_g INTEGER NOT NULL DEFAULT 0,
            saldo_pendente_g INTEGER NOT NULL DEFAULT 0,
            saldo_operacional_g INTEGER NOT NULL DEFAULT 0,
            saldo_reservado_operacional_g INTEGER NOT NULL DEFAULT 0,
            saldo_destinado_g INTEGER NOT NULL DEFAULT 0
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS pa_nao_conforme_eventos (
            id {id_type}, pa_nao_conforme_id INTEGER NOT NULL, acao TEXT NOT NULL,
            status_anterior TEXT, status_novo TEXT, usuario TEXT NOT NULL,
            perfil TEXT NOT NULL, justificativa TEXT, detalhes TEXT,
            origem TEXT NOT NULL, criado_em {timestamp_type} NOT NULL
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS pa_nao_conforme_solicitacoes (
            id {id_type}, pa_nao_conforme_id INTEGER NOT NULL,
            idempotency_key TEXT UNIQUE NOT NULL, peso_g INTEGER NOT NULL,
            caixas INTEGER NOT NULL DEFAULT 0, bandejas INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL, justificativa TEXT NOT NULL, observacoes TEXT,
            solicitado_por TEXT NOT NULL, solicitado_por_id INTEGER,
            perfil_solicitante TEXT NOT NULL,
            solicitado_em {timestamp_type} NOT NULL, decidido_por TEXT,
            decidido_por_id INTEGER, perfil_decisor TEXT, decidido_em {timestamp_type},
            justificativa_decisao TEXT, criado_em {timestamp_type} NOT NULL,
            atualizado_em {timestamp_type} NOT NULL
        )
        """)
        colunas = [
            "tipo_registro TEXT NOT NULL DEFAULT 'CAIXA_RASTREADA'", "idempotency_key TEXT",
            "validade TEXT", "origem_entrada TEXT", "data_contagem TEXT",
            "responsaveis_contagem TEXT", "validacao_qualidade TEXT", "validacao_gerencia TEXT",
            "condicao_inicial TEXT", "caixas_iniciais INTEGER NOT NULL DEFAULT 0",
            "bandejas_iniciais INTEGER NOT NULL DEFAULT 0", "caixas_bloqueadas INTEGER NOT NULL DEFAULT 0",
            "bandejas_bloqueadas INTEGER NOT NULL DEFAULT 0", "galinhas_bloqueadas INTEGER NOT NULL DEFAULT 0",
            "pacotes_bloqueados INTEGER NOT NULL DEFAULT 0", "saldo_inicial_g INTEGER NOT NULL DEFAULT 0",
            "saldo_bloqueado_g INTEGER NOT NULL DEFAULT 0", "saldo_pendente_g INTEGER NOT NULL DEFAULT 0",
            "saldo_operacional_g INTEGER NOT NULL DEFAULT 0", "saldo_reservado_operacional_g INTEGER NOT NULL DEFAULT 0",
            "saldo_destinado_g INTEGER NOT NULL DEFAULT 0",
        ]
        for coluna in colunas:
            _alterar_coluna(cursor, f"ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS {coluna}",
                           f"ALTER TABLE pa_nao_conformes ADD COLUMN {coluna}")
        for coluna in ("solicitado_por_id INTEGER", "decidido_por_id INTEGER"):
            _alterar_coluna(cursor,
                           f"ALTER TABLE pa_nao_conforme_solicitacoes ADD COLUMN IF NOT EXISTS {coluna}",
                           f"ALTER TABLE pa_nao_conforme_solicitacoes ADD COLUMN {coluna}")
        if DATABASE_URL:
            cursor.execute("ALTER TABLE pa_nao_conformes ALTER COLUMN op_id DROP NOT NULL")
            cursor.execute("ALTER TABLE pa_nao_conformes ALTER COLUMN caixa_id DROP NOT NULL")
            cursor.execute("ALTER TABLE pa_nao_conformes ALTER COLUMN lote DROP NOT NULL")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pa_nc_op ON pa_nao_conformes(op_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pa_nc_status ON pa_nao_conformes(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pa_nc_eventos ON pa_nao_conforme_eventos(pa_nao_conforme_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pa_nc_solicitacoes ON pa_nao_conforme_solicitacoes(pa_nao_conforme_id, status)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pa_nc_idempotency_key ON pa_nao_conformes(idempotency_key)")
        cursor.execute(q("""
            INSERT INTO locais_estoque (nome, tipo, ativo)
            SELECT ?, 'segregacao', 'Sim'
            WHERE NOT EXISTS (SELECT 1 FROM locais_estoque WHERE nome = ?)
        """), (LOCAL_PADRAO, LOCAL_PADRAO))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def listar_locais_segregacao():
    criar_tabelas_pa_nao_conforme()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome FROM locais_estoque WHERE ativo = 'Sim' ORDER BY nome")
        return cursor.fetchall()
    finally:
        conn.close()


def _evento(cursor, nc_id, acao, anterior, novo, usuario, perfil, origem,
            justificativa=None, detalhes=None):
    cursor.execute(q("""
        INSERT INTO pa_nao_conforme_eventos (
            pa_nao_conforme_id, acao, status_anterior, status_novo,
            usuario, perfil, justificativa, detalhes, origem, criado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (nc_id, acao, anterior, novo, usuario, perfil, justificativa,
           detalhes, origem, _agora()))


def _auditar_negacao(pa_nc_id, usuario, perfil, origem, justificativa, detalhes):
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT status FROM pa_nao_conformes WHERE id=?"), (pa_nc_id,))
        registro = cursor.fetchone()
        if registro:
            _evento(cursor, pa_nc_id, "TENTATIVA_NEGADA", registro["status"],
                    registro["status"], usuario, perfil, origem, justificativa, detalhes)


def impedir_fluxo_legado(caixa_ids, acao, *, somente_pendentes=False):
    """Bloqueia atalhos legados e audita a tentativa fora da transação recusada."""
    criar_tabelas_pa_nao_conforme()
    usuario, perfil, origem = _identidade()
    ids = [int(item) for item in caixa_ids]
    with transaction() as conn:
        cursor = conn.cursor()
        for caixa_id in ids:
            cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE caixa_id=?"), (caixa_id,))
            registro = cursor.fetchone()
            if not registro or (somente_pendentes and registro["status"] == "LIBERADO"):
                continue
            _evento(cursor, registro["id"], "TENTATIVA_NEGADA", registro["status"],
                    registro["status"], usuario, perfil, origem,
                    detalhes=f"Fluxo legado recusado: {acao}.")
            return registro
    return None


def _validar_item(cursor, op_id, item):
    try:
        caixa_id = int(item.get("caixa_id") or 0)
        quantidade = Decimal(str(item.get("quantidade") or "0").replace(",", "."))
        peso_raw = item.get("peso")
        peso = None if peso_raw in (None, "") else Decimal(str(peso_raw).replace(",", "."))
        local_id = int(item.get("local_estoque_id") or 0)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Quantidade, peso ou local inválido no Produto Não Conforme.")
    motivo = str(item.get("motivo") or "").strip()
    descricao = str(item.get("descricao") or "").strip()
    lote = str(item.get("lote") or "").strip()
    apresentacao = str(item.get("apresentacao") or "").strip()
    unidade = str(item.get("unidade") or "").strip()
    if quantidade <= 0 or (peso is not None and peso <= 0):
        raise ValueError("Quantidade e peso informado devem ser maiores que zero.")
    if not lote or not apresentacao or not unidade or not motivo or not local_id:
        raise ValueError("Preencha lote, apresentação, quantidade, unidade, motivo e local de segregação.")
    if motivo not in MOTIVOS:
        raise ValueError("Motivo de não conformidade inválido.")
    if motivo == "Outro" and not descricao:
        raise ValueError("Descreva a não conformidade quando o motivo for Outro.")
    cursor.execute(q("""
        SELECT cx.*, comp.op_id, le.id AS local_valido
        FROM pa_caixas cx
        JOIN pa_caixa_composicao comp ON comp.caixa_id = cx.id
        LEFT JOIN locais_estoque le ON le.id = ? AND le.ativo = 'Sim'
        WHERE cx.id = ? AND comp.op_id = ? AND COALESCE(cx.status, '') <> 'Cancelada'
    """), (local_id, caixa_id, op_id))
    caixa = cursor.fetchone()
    if not caixa:
        raise ValueError("A caixa informada não pertence à OP ou não está ativa.")
    if not caixa["local_valido"]:
        raise ValueError("Local de segregação inexistente ou inativo.")
    cursor.execute(q("SELECT id FROM pa_nao_conformes WHERE caixa_id = ?"), (caixa_id,))
    if cursor.fetchone():
        raise ValueError("A caixa já possui registro oficial de Produto Não Conforme.")
    unidade_fisica = "PACOTE" if caixa["unidade_estoque"] == "PACOTE" else "BANDEJA"
    quantidade_fisica = (
        Decimal(str(caixa["quantidade_pacotes"] or 0))
        if unidade_fisica == "PACOTE" else Decimal(str(caixa["quantidade_bandejas"] or 0))
    )
    peso_fisico = None if unidade_fisica == "PACOTE" else Decimal(str(caixa["peso_liquido"] or 0))
    if lote != caixa["codigo_caixa"]:
        raise ValueError("O lote informado não corresponde à caixa/posição da OP.")
    tolerancia = Decimal("0.0001")
    if unidade != unidade_fisica or abs(quantidade - quantidade_fisica) > tolerancia:
        raise ValueError("Quantidade ou unidade diverge do saldo físico da caixa/posição.")
    if (peso is None) != (peso_fisico is None) or (
        peso is not None and abs(peso - peso_fisico) > tolerancia
    ):
        raise ValueError("O peso informado diverge do peso físico da caixa.")
    apresentacao_fisica = str(caixa["apresentacao"] or apresentacao).strip()
    return {
        "caixa_id": caixa_id, "lote": caixa["codigo_caixa"], "produto": caixa["sku"],
        "apresentacao": apresentacao_fisica, "quantidade": quantidade_fisica, "peso": peso_fisico,
        "unidade": unidade_fisica, "motivo": motivo, "descricao": descricao,
        "local_estoque_id": local_id,
        "observacoes": str(item.get("observacoes") or "").strip(),
    }


def registrar_itens_encerramento(cursor, op_id, itens, *, usuario=None, perfil=None,
                                 origem=None, checkpoint=None):
    """Cria e bloqueia zero ou vários itens dentro da transação de encerramento."""
    usuario, perfil, origem = _identidade(usuario, perfil, origem)
    validados = [_validar_item(cursor, op_id, item) for item in (itens or [])]
    ids = []
    for indice, item in enumerate(validados, start=1):
        agora = _agora()
        numero = f"PNC-{int(op_id):06d}-{int(item['caixa_id']):06d}"
        parametros = (
            numero, op_id, item["caixa_id"], item["lote"], item["produto"],
            item["apresentacao"], str(item["quantidade"]),
            None if item["peso"] is None else str(item["peso"]), item["unidade"],
            item["motivo"], item["descricao"], item["local_estoque_id"], usuario,
            perfil, agora, item["observacoes"], agora, agora,
        )
        sql = """
            INSERT INTO pa_nao_conformes (
                numero, op_id, caixa_id, lote, produto, apresentacao, quantidade,
                peso, unidade, motivo, descricao, status, local_estoque_id,
                registrado_por, perfil_registro, registrado_em, observacoes,
                criado_em, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BLOQUEADO', ?, ?, ?, ?, ?, ?, ?)
        """
        if DATABASE_URL:
            cursor.execute(q(sql + " RETURNING id"), parametros)
            nc_id = cursor.fetchone()["id"]
        else:
            cursor.execute(q(sql), parametros)
            nc_id = cursor.lastrowid
        cursor.execute(q("""
            UPDATE pa_caixas SET condicao='NAO_CONFORME', disponibilidade='BLOQUEADO',
                zona_estoque='Produto Não Conforme', motivo_nao_conformidade=?,
                local_estoque_id=? WHERE id=?
        """), (item["motivo"], item["local_estoque_id"], item["caixa_id"]))
        _evento(cursor, nc_id, "CRIACAO_E_BLOQUEIO", None, "BLOQUEADO",
                usuario, perfil, origem, item["motivo"], item["descricao"])
        ids.append(nc_id)
        if checkpoint:
            checkpoint(f"pa_nc_{indice}")
    return ids


def decidir(pa_nc_id, destino, justificativa, observacoes="", *, usuario=None,
            perfil=None, origem=None):
    mapa = {
        "LIBERAR": ("LIBERADO", "CONFORME", "DISPONIVEL", "Conforme"),
        "RETRABALHO": ("RETRABALHO", "NAO_CONFORME", "BLOQUEADO", "Produto Não Conforme"),
        "REPROCESSO": ("REPROCESSO", "NAO_CONFORME", "REPROCESSAMENTO", "Produto Não Conforme"),
        "DESCARTE": ("DESCARTE", "NAO_CONFORME", "DESCARTADO", "Produto Não Conforme"),
        "MANTER_BLOQUEADO": ("MANTIDO_BLOQUEADO", "NAO_CONFORME", "BLOQUEADO", "Produto Não Conforme"),
    }
    usuario, perfil, origem = _identidade(usuario, perfil, origem)
    justificativa = str(justificativa or "").strip()
    criar_tabelas_pa_nao_conforme()
    if destino not in mapa:
        raise ValueError("Destinação inválida.")
    if destino == "LIBERAR":
        _auditar_negacao(pa_nc_id, usuario, perfil, origem, justificativa,
                         "Liberacao direta recusada; use solicitacao e validacao gerencial.")
        raise ValueError("A liberacao exige solicitacao da Qualidade e validacao da Gerencia.")
    if not justificativa:
        raise ValueError("A justificativa da destinação é obrigatória.")
    if perfil not in PERFIS_DECISAO:
        _auditar_negacao(pa_nc_id, usuario, perfil, origem, justificativa,
                         "Perfil sem permissão para decidir.")
        raise PermissionError("Perfil sem permissão para decidir Produto Não Conforme.")
    if destino == "REPROCESSO":
        from .reprocessamento import iniciar_reprocessamento
        return iniciar_reprocessamento(
            pa_nc_id, {"modalidade": "INTEGRAL", "justificativa": justificativa,
                       "observacoes": observacoes},
            usuario=usuario, perfil=perfil, origem=origem,
        )
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE id = ?"), (pa_nc_id,))
        registro = cursor.fetchone()
        if not registro:
            raise ValueError("Produto Não Conforme não encontrado.")
        if registro["status"] in {"LIBERADO", "RETRABALHO", "REPROCESSO", "DESCARTE"}:
            raise ValueError("A destinação final já foi registrada.")
        novo, condicao, disponibilidade, zona = mapa[destino]
        agora = _agora()
        cursor.execute(q("""
            UPDATE pa_nao_conformes SET status=?, decisao=?, justificativa_destinacao=?,
                observacoes=?, decidido_por=?, perfil_decisao=?, decidido_em=?, atualizado_em=?
            WHERE id=?
        """), (novo, destino, justificativa, str(observacoes or "").strip(),
               usuario, perfil, agora, agora, pa_nc_id))
        cursor.execute(q("""
            UPDATE pa_caixas SET condicao=?, disponibilidade=?, zona_estoque=?,
                motivo_nao_conformidade=CASE WHEN ?='CONFORME' THEN NULL ELSE motivo_nao_conformidade END
            WHERE id=?
        """), (condicao, disponibilidade, zona, condicao, registro["caixa_id"]))
        _evento(cursor, pa_nc_id, destino, registro["status"], novo, usuario,
                perfil, origem, justificativa, str(observacoes or "").strip())


def iniciar_avaliacao(pa_nc_id, *, usuario=None, perfil=None, origem=None):
    usuario, perfil, origem = _identidade(usuario, perfil, origem)
    criar_tabelas_pa_nao_conforme()
    if perfil not in PERFIS_DECISAO:
        _auditar_negacao(pa_nc_id, usuario, perfil, origem, None,
                         "Perfil sem permissão para avaliar.")
        raise PermissionError("Perfil sem permissão para avaliar Produto Não Conforme.")
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE id=?"), (pa_nc_id,))
        registro = cursor.fetchone()
        if not registro:
            raise ValueError("Produto Não Conforme não encontrado.")
        if registro["status"] not in {"BLOQUEADO", "MANTIDO_BLOQUEADO"}:
            raise ValueError("O registro não está disponível para iniciar avaliação.")
        cursor.execute(q("UPDATE pa_nao_conformes SET status='EM_AVALIACAO', atualizado_em=? WHERE id=?"),
                       (_agora(), pa_nc_id))
        _evento(cursor, pa_nc_id, "INICIO_AVALIACAO", registro["status"],
                "EM_AVALIACAO", usuario, perfil, origem)


def _inteiro_saldo(valor):
    try:
        return max(0, int(valor or 0))
    except (TypeError, ValueError):
        return 0


def _valor(registro, chave, padrao=None):
    try:
        valor = registro[chave]
    except (KeyError, IndexError, TypeError):
        return padrao
    return padrao if valor is None else valor


def _gramas_saldo(valor):
    try:
        decimal = Decimal(str(valor or 0))
        return max(0, int((decimal * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    except (InvalidOperation, TypeError, ValueError):
        return 0


def saldo_fisico_remanescente(registro):
    """Fonte unica de leitura do saldo atual, sem alterar estoque ou historico.

    O inventario agregado e as baixas parciais usam os campos consolidados que
    o fluxo de descarte mantem na mesma transacao dos movimentos. Para uma
    caixa rastreada ainda sem baixa, a posicao fisica corrente de ``pa_caixas``
    prevalece sobre o snapshot original do PNC.
    """
    tipo = str(_valor(registro, "tipo_registro", "") or "")
    status = str(_valor(registro, "status", "") or "").upper()
    consolidado = tipo == TIPO_LEGADO or status in {"DESCARTE_PARCIAL", "DESCARTADO"}
    if consolidado:
        saldo = {
            "peso_g": _inteiro_saldo(_valor(registro, "saldo_bloqueado_g")),
            "caixas": _inteiro_saldo(_valor(registro, "caixas_bloqueadas")),
            "bandejas": _inteiro_saldo(_valor(registro, "bandejas_bloqueadas")),
            "pacotes": _inteiro_saldo(_valor(registro, "pacotes_bloqueados")),
            "galinhas": _inteiro_saldo(_valor(registro, "galinhas_bloqueadas")),
        }
    elif _valor(registro, "caixa_id"):
        unidade = str(_valor(registro, "cx_unidade_estoque") or _valor(registro, "unidade") or "").upper()
        if unidade == "PACOTE":
            saldo = {
                "peso_g": 0, "caixas": 0, "bandejas": 0,
                "pacotes": _inteiro_saldo(_valor(
                    registro, "cx_quantidade_pacotes", _valor(registro, "quantidade")
                )),
                "galinhas": _inteiro_saldo(_valor(registro, "cx_quantidade_galinhas")),
            }
        else:
            peso_g = _gramas_saldo(_valor(registro, "cx_peso_liquido", _valor(registro, "peso")))
            bandejas = _inteiro_saldo(_valor(
                registro, "cx_quantidade_bandejas", _valor(registro, "quantidade")
            ))
            saldo = {
                "peso_g": peso_g,
                "caixas": 1 if peso_g > 0 or bandejas > 0 else 0,
                "bandejas": bandejas, "pacotes": 0, "galinhas": 0,
            }
    else:
        # Compatibilidade defensiva para registros historicos sem posicao.
        saldo = {
            "peso_g": _inteiro_saldo(_valor(registro, "saldo_bloqueado_g")),
            "caixas": _inteiro_saldo(_valor(registro, "caixas_bloqueadas")),
            "bandejas": _inteiro_saldo(_valor(registro, "bandejas_bloqueadas")),
            "pacotes": _inteiro_saldo(_valor(registro, "pacotes_bloqueados")),
            "galinhas": _inteiro_saldo(_valor(registro, "galinhas_bloqueadas")),
        }
    if status == "REPROCESSO":
        # Durante a execução, o material saiu do bloqueio, mas continua sendo
        # saldo físico do PNC até a conclusão documental do consumo.
        if tipo != TIPO_LEGADO:
            saldo = {"peso_g": 0, "caixas": 0, "bandejas": 0, "pacotes": 0, "galinhas": 0}
        for chave, coluna in (
            ("peso_g", "reprocessando_peso_g"), ("caixas", "reprocessando_caixas"),
            ("bandejas", "reprocessando_bandejas"), ("pacotes", "reprocessando_pacotes"),
            ("galinhas", "reprocessando_galinhas"),
        ):
            saldo[chave] += _inteiro_saldo(_valor(registro, coluna))
    if status in STATUS_TERMINAIS:
        # O saldo ainda pode existir na caixa ou no estoque operacional, mas já
        # não pertence ao bloqueio físico deste PNC.
        for chave in ("peso_g", "caixas", "bandejas", "pacotes", "galinhas"):
            saldo[chave] = 0
    saldo["tem_saldo"] = any(saldo[chave] > 0 for chave in (
        "peso_g", "caixas", "bandejas", "pacotes", "galinhas"
    ))
    saldo["ativo"] = saldo["tem_saldo"] and status not in STATUS_TERMINAIS
    return saldo


def _situacao_aceita(registro, situacao):
    situacao = str(situacao or "ATIVOS").upper()
    status = str(_valor(registro, "status", "") or "").upper()
    ativo = bool(registro["saldo_fisico"]["ativo"])
    if situacao == "TODOS":
        return True
    if situacao == "FINALIZADOS":
        return not ativo
    if situacao == "BLOQUEADOS":
        return ativo and status in {"BLOQUEADO", "MANTIDO_BLOQUEADO", "EM_AVALIACAO"}
    if situacao == "AGUARDANDO_AVALIACAO":
        return ativo and status == "BLOQUEADO"
    if situacao == "REPROCESSAMENTO":
        return ativo and status == "REPROCESSO"
    if situacao == "DESTINADOS_DESCARTE":
        return ativo and status == "DESCARTE"
    if situacao == "DESCARTE_PARCIAL":
        return ativo and status == "DESCARTE_PARCIAL"
    if situacao == "DESCARTADOS":
        return not ativo and status in {"DESCARTE", "DESCARTADO"}
    if situacao == "LIBERADOS":
        return not ativo and status == "LIBERADO"
    if situacao == "CANCELADOS":
        return not ativo and status in {"CANCELADO", "CANCELADA"}
    return ativo


def consultar(filtros=None, *, paginar=False):
    criar_tabelas_pa_nao_conforme()
    filtros = filtros or {}
    clausulas, params = ["1=1"], []
    mapa = {
        "op": "CAST(nc.op_id AS TEXT)", "lote": "nc.lote",
        "status": "nc.status", "responsavel": "nc.registrado_por",
        "destinacao": "nc.decisao",
    }
    for nome, coluna in mapa.items():
        valor = str(filtros.get(nome) or "").strip()
        if valor:
            clausulas.append(f"{coluna} = ?")
            params.append(valor)
    for nome, coluna in (("produto", "nc.produto"), ("motivo", "nc.motivo")):
        valor = str(filtros.get(nome) or "").strip()
        if valor:
            clausulas.append(f"LOWER({coluna}) LIKE LOWER(?)")
            params.append(f"%{valor}%")
    if filtros.get("local"):
        clausulas.append("nc.local_estoque_id = ?")
        params.append(int(filtros["local"]))
    if filtros.get("inicio"):
        clausulas.append("nc.registrado_em >= ?")
        params.append(filtros["inicio"] + " 00:00:00")
    if filtros.get("fim"):
        clausulas.append("nc.registrado_em <= ?")
        params.append(filtros["fim"] + " 23:59:59")
    conn = conectar()
    try:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("SELECT 1 FROM information_schema.tables WHERE table_name='pnc_movimentos_descarte'")
            colunas_caixa = {
                "unidade_estoque", "peso_liquido", "quantidade_bandejas",
                "quantidade_pacotes", "quantidade_galinhas",
            }
        else:
            cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pnc_movimentos_descarte'")
            cursor_colunas = conn.cursor()
            cursor_colunas.execute("PRAGMA table_info(pa_caixas)")
            colunas_caixa = {linha[1] for linha in cursor_colunas.fetchall()}
        possui_historico_descarte = cursor.fetchone() is not None
        if DATABASE_URL:
            cursor.execute("SELECT 1 FROM information_schema.tables WHERE table_name='pnc_reprocessamentos'")
        else:
            cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pnc_reprocessamentos'")
        possui_reprocessamento = cursor.fetchone() is not None
        def coluna_caixa(nome):
            return f"cx.{nome}" if nome in colunas_caixa else "NULL"
        if possui_historico_descarte:
            historico_sql = """
                   (SELECT COALESCE(SUM(CASE WHEN mov.tipo='SAIDA_DESCARTE_PNC' THEN mov.peso_g ELSE -mov.peso_g END),0)
                      FROM pnc_movimentos_descarte mov WHERE mov.pa_nao_conforme_id=nc.id) AS descartado_peso_g,
                   (SELECT COALESCE(SUM(CASE WHEN mov.tipo='SAIDA_DESCARTE_PNC' THEN mov.caixas ELSE -mov.caixas END),0)
                      FROM pnc_movimentos_descarte mov WHERE mov.pa_nao_conforme_id=nc.id) AS descartado_caixas,
                   (SELECT COALESCE(SUM(CASE WHEN mov.tipo='SAIDA_DESCARTE_PNC' THEN mov.bandejas ELSE -mov.bandejas END),0)
                      FROM pnc_movimentos_descarte mov WHERE mov.pa_nao_conforme_id=nc.id) AS descartado_bandejas,
                   (SELECT COALESCE(SUM(CASE WHEN mov.tipo='SAIDA_DESCARTE_PNC' THEN mov.pacotes ELSE -mov.pacotes END),0)
                      FROM pnc_movimentos_descarte mov WHERE mov.pa_nao_conforme_id=nc.id) AS descartado_pacotes,
                   (SELECT COALESCE(SUM(CASE WHEN mov.tipo='SAIDA_DESCARTE_PNC' THEN mov.galinhas ELSE -mov.galinhas END),0)
                      FROM pnc_movimentos_descarte mov WHERE mov.pa_nao_conforme_id=nc.id) AS descartado_galinhas,
                   (SELECT rom.id FROM pnc_romaneios_descarte rom
                      WHERE rom.pa_nao_conforme_id=nc.id AND rom.status='CONFIRMADO'
                      ORDER BY rom.saida_fisica_em DESC, rom.id DESC LIMIT 1) AS romaneio_descarte_id,
                   (SELECT rom.numero FROM pnc_romaneios_descarte rom
                      WHERE rom.pa_nao_conforme_id=nc.id AND rom.status='CONFIRMADO'
                      ORDER BY rom.saida_fisica_em DESC, rom.id DESC LIMIT 1) AS romaneio_descarte_numero,
                   (SELECT rom.saida_fisica_em FROM pnc_romaneios_descarte rom
                      WHERE rom.pa_nao_conforme_id=nc.id AND rom.status='CONFIRMADO'
                      ORDER BY rom.saida_fisica_em DESC, rom.id DESC LIMIT 1) AS descarte_finalizado_em,
                   (SELECT rom.usuario_emissor FROM pnc_romaneios_descarte rom
                      WHERE rom.pa_nao_conforme_id=nc.id AND rom.status='CONFIRMADO'
                      ORDER BY rom.saida_fisica_em DESC, rom.id DESC LIMIT 1) AS descarte_responsavel
            """
        else:
            historico_sql = """
                   0 AS descartado_peso_g, 0 AS descartado_caixas,
                   0 AS descartado_bandejas, 0 AS descartado_pacotes,
                   0 AS descartado_galinhas, NULL AS romaneio_descarte_id,
                   NULL AS romaneio_descarte_numero, NULL AS descarte_finalizado_em,
                   NULL AS descarte_responsavel
            """
        if possui_reprocessamento:
            reprocessamento_sql = """
                   (SELECT COALESCE(SUM(r.peso_g),0) FROM pnc_reprocessamentos r
                      WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_peso_g,
                   (SELECT COALESCE(SUM(r.caixas),0) FROM pnc_reprocessamentos r
                      WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_caixas,
                   (SELECT COALESCE(SUM(r.bandejas),0) FROM pnc_reprocessamentos r
                      WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_bandejas,
                   (SELECT COALESCE(SUM(r.pacotes),0) FROM pnc_reprocessamentos r
                      WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_pacotes,
                   (SELECT COALESCE(SUM(r.galinhas),0) FROM pnc_reprocessamentos r
                      WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_galinhas
            """
        else:
            reprocessamento_sql = """0 AS reprocessando_peso_g, 0 AS reprocessando_caixas,
                   0 AS reprocessando_bandejas, 0 AS reprocessando_pacotes,
                   0 AS reprocessando_galinhas"""
        cursor.execute(q(f"""
            SELECT nc.*, le.nome AS local_nome, cx.codigo_caixa,
                   cx.condicao, cx.disponibilidade,
                   {coluna_caixa('unidade_estoque')} AS cx_unidade_estoque,
                   {coluna_caixa('peso_liquido')} AS cx_peso_liquido,
                   {coluna_caixa('quantidade_bandejas')} AS cx_quantidade_bandejas,
                   {coluna_caixa('quantidade_pacotes')} AS cx_quantidade_pacotes,
                   {coluna_caixa('quantidade_galinhas')} AS cx_quantidade_galinhas,
                   {historico_sql},
                   {reprocessamento_sql}
            FROM pa_nao_conformes nc
            LEFT JOIN pa_caixas cx ON cx.id=nc.caixa_id
            JOIN locais_estoque le ON le.id=nc.local_estoque_id
            WHERE {' AND '.join(clausulas)}
            ORDER BY nc.registrado_em DESC, nc.id DESC
        """), tuple(params))
        registros = []
        for linha in cursor.fetchall():
            registro = dict(linha)
            registro["saldo_fisico"] = saldo_fisico_remanescente(registro)
            if _situacao_aceita(registro, filtros.get("situacao")):
                registros.append(registro)
        if not paginar:
            return registros
        try:
            pagina = max(1, int(filtros.get("pagina") or 1))
        except (TypeError, ValueError):
            pagina = 1
        try:
            por_pagina = min(100, max(1, int(filtros.get("por_pagina") or 25)))
        except (TypeError, ValueError):
            por_pagina = 25
        total = len(registros)
        paginas = max(1, (total + por_pagina - 1) // por_pagina)
        pagina = min(pagina, paginas)
        inicio = (pagina - 1) * por_pagina
        return registros[inicio:inicio + por_pagina], {
            "pagina": pagina, "por_pagina": por_pagina, "total": total,
            "paginas": paginas, "tem_anterior": pagina > 1, "tem_proxima": pagina < paginas,
        }
    finally:
        conn.close()


def obter_detalhe(pa_nc_id):
    criar_tabelas_pa_nao_conforme()
    from .reprocessamento import garantir_schema as garantir_schema_reprocessamento
    garantir_schema_reprocessamento()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""
            SELECT nc.*, le.nome AS local_nome, cx.codigo_caixa,
                   cx.condicao, cx.disponibilidade,
                   (SELECT COALESCE(SUM(r.peso_g),0) FROM pnc_reprocessamentos r
                     WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_peso_g,
                   (SELECT COALESCE(SUM(r.caixas),0) FROM pnc_reprocessamentos r
                     WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_caixas,
                   (SELECT COALESCE(SUM(r.bandejas),0) FROM pnc_reprocessamentos r
                     WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_bandejas,
                   (SELECT COALESCE(SUM(r.pacotes),0) FROM pnc_reprocessamentos r
                     WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_pacotes,
                   (SELECT COALESCE(SUM(r.galinhas),0) FROM pnc_reprocessamentos r
                     WHERE r.pa_nao_conforme_id=nc.id AND r.status='EM_ANDAMENTO') AS reprocessando_galinhas
            FROM pa_nao_conformes nc LEFT JOIN pa_caixas cx ON cx.id=nc.caixa_id
            JOIN locais_estoque le ON le.id=nc.local_estoque_id WHERE nc.id=?
        """), (pa_nc_id,))
        linha = cursor.fetchone()
        registro = dict(linha) if linha else None
        if registro:
            registro["saldo_fisico"] = saldo_fisico_remanescente(registro)
        cursor.execute(q("SELECT * FROM pa_nao_conforme_eventos WHERE pa_nao_conforme_id=? ORDER BY criado_em DESC, id DESC"), (pa_nc_id,))
        return registro, cursor.fetchall()
    finally:
        conn.close()


def indicadores(registros):
    ativos = [r for r in registros if saldo_fisico_remanescente(r)["ativo"]]
    bloqueados = [r for r in ativos if r["status"] in {
        "BLOQUEADO", "EM_AVALIACAO", "MANTIDO_BLOQUEADO", "DESCARTE", "DESCARTE_PARCIAL"
    }]
    tempos = []
    mil = Decimal(1000)
    zero = Decimal(0)
    for r in registros:
        if r["decidido_em"]:
            try:
                tempos.append((datetime.fromisoformat(str(r["decidido_em"])) - datetime.fromisoformat(str(r["registrado_em"]))).total_seconds() / 3600)
            except (TypeError, ValueError):
                pass
    return {
        "registros_bloqueados": len(bloqueados),
        "peso_bloqueado": sum((Decimal(saldo_fisico_remanescente(r)["peso_g"]) / mil for r in bloqueados), zero),
        "quantidade_bloqueada": sum(
            saldo_fisico_remanescente(r)["bandejas"] + saldo_fisico_remanescente(r)["pacotes"]
            for r in bloqueados
        ),
        "caixas_bloqueadas": sum(saldo_fisico_remanescente(r)["caixas"] for r in bloqueados),
        "bandejas_bloqueadas": sum(saldo_fisico_remanescente(r)["bandejas"] for r in bloqueados),
        "pacotes_bloqueados": sum(saldo_fisico_remanescente(r)["pacotes"] for r in bloqueados),
        "galinhas_bloqueadas": sum(saldo_fisico_remanescente(r)["galinhas"] for r in bloqueados),
        "aguardando_avaliacao": sum(r["status"] == "BLOQUEADO" for r in ativos),
        "liberados": sum(r["status"] == "LIBERADO" for r in registros),
        "retrabalho": sum(r["status"] == "RETRABALHO" for r in ativos),
        "reprocesso": sum(r["status"] == "REPROCESSO" for r in ativos),
        "descarte": sum(r["status"] in {"DESCARTE", "DESCARTE_PARCIAL"} for r in ativos),
        "tempo_medio_horas": sum(tempos) / len(tempos) if tempos else 0,
        "fisico_total_kg": round(sum((Decimal(saldo_fisico_remanescente(r)["peso_g"]) / mil for r in ativos), zero), 3),
        "caixas_informativas": sum(saldo_fisico_remanescente(r)["caixas"] for r in ativos),
        "nao_conforme_bloqueado_kg": round(sum((
            Decimal(saldo_fisico_remanescente(r)["peso_g"]) / mil for r in ativos
            if r["condicao_inicial"] == "NAO_CONFORME"
        ), zero), 3),
        "aguardando_liberacao_kg": round(sum((
            Decimal(saldo_fisico_remanescente(r)["peso_g"]) / mil for r in ativos
            if r["condicao_inicial"] == "CONFORME_AGUARDANDO_LIBERACAO"
        ), zero), 3),
        "pendente_gerencia_kg": round(sum((
            Decimal(min(int(r["saldo_pendente_g"] or 0), saldo_fisico_remanescente(r)["peso_g"])) / mil
            for r in ativos
        ), zero), 3),
        "disponivel_kg": round(sum((
            Decimal(min(int(r["saldo_operacional_g"] or 0), saldo_fisico_remanescente(r)["peso_g"])) / mil
            for r in ativos
        ), zero), 3),
    }
