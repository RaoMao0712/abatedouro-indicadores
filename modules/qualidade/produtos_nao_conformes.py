"""Governanca do Produto Acabado Nao Conforme ligado ao estoque fisico de PA."""

from datetime import datetime

from flask import has_request_context, request, session

from database import DATABASE_URL, conectar, q, transaction


STATUS = {
    "BLOQUEADO", "EM_AVALIACAO", "LIBERADO", "RETRABALHO",
    "REPROCESSO", "DESCARTE", "MANTIDO_BLOQUEADO",
}
STATUS_LABELS = {
    "BLOQUEADO": "Bloqueado", "EM_AVALIACAO": "Em avaliação",
    "LIBERADO": "Liberado", "RETRABALHO": "Destinado a retrabalho",
    "REPROCESSO": "Destinado a reprocesso", "DESCARTE": "Destinado a descarte",
    "MANTIDO_BLOQUEADO": "Mantido bloqueado",
}
MOTIVOS = (
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
            solicitado_por TEXT NOT NULL, perfil_solicitante TEXT NOT NULL,
            solicitado_em {timestamp_type} NOT NULL, decidido_por TEXT,
            perfil_decisor TEXT, decidido_em {timestamp_type},
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
            "bandejas_bloqueadas INTEGER NOT NULL DEFAULT 0", "saldo_inicial_g INTEGER NOT NULL DEFAULT 0",
            "saldo_bloqueado_g INTEGER NOT NULL DEFAULT 0", "saldo_pendente_g INTEGER NOT NULL DEFAULT 0",
            "saldo_operacional_g INTEGER NOT NULL DEFAULT 0", "saldo_reservado_operacional_g INTEGER NOT NULL DEFAULT 0",
            "saldo_destinado_g INTEGER NOT NULL DEFAULT 0",
        ]
        for coluna in colunas:
            _alterar_coluna(cursor, f"ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS {coluna}",
                           f"ALTER TABLE pa_nao_conformes ADD COLUMN {coluna}")
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
        quantidade = float(str(item.get("quantidade") or "0").replace(",", "."))
        peso_raw = item.get("peso")
        peso = None if peso_raw in (None, "") else float(str(peso_raw).replace(",", "."))
        local_id = int(item.get("local_estoque_id") or 0)
    except (TypeError, ValueError):
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
        float(caixa["quantidade_pacotes"] or 0)
        if unidade_fisica == "PACOTE" else float(caixa["quantidade_bandejas"] or 0)
    )
    peso_fisico = None if unidade_fisica == "PACOTE" else float(caixa["peso_liquido"] or 0)
    if lote != caixa["codigo_caixa"]:
        raise ValueError("O lote informado não corresponde à caixa/posição da OP.")
    if unidade != unidade_fisica or abs(quantidade - quantidade_fisica) > 0.0001:
        raise ValueError("Quantidade ou unidade diverge do saldo físico da caixa/posição.")
    if (peso is None) != (peso_fisico is None) or (
        peso is not None and abs(peso - peso_fisico) > 0.0001
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
            item["apresentacao"], item["quantidade"], item["peso"], item["unidade"],
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


def consultar(filtros=None):
    criar_tabelas_pa_nao_conforme()
    filtros = filtros or {}
    clausulas, params = ["1=1"], []
    mapa = {
        "op": "CAST(nc.op_id AS TEXT)", "lote": "nc.lote", "produto": "nc.produto",
        "motivo": "nc.motivo", "status": "nc.status", "responsavel": "nc.registrado_por",
        "destinacao": "nc.decisao",
    }
    for nome, coluna in mapa.items():
        valor = str(filtros.get(nome) or "").strip()
        if valor:
            clausulas.append(f"{coluna} = ?")
            params.append(valor)
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
        cursor.execute(q(f"""
            SELECT nc.*, le.nome AS local_nome, cx.codigo_caixa,
                   cx.condicao, cx.disponibilidade
            FROM pa_nao_conformes nc
            LEFT JOIN pa_caixas cx ON cx.id=nc.caixa_id
            JOIN locais_estoque le ON le.id=nc.local_estoque_id
            WHERE {' AND '.join(clausulas)}
            ORDER BY nc.registrado_em DESC, nc.id DESC
        """), tuple(params))
        return cursor.fetchall()
    finally:
        conn.close()


def obter_detalhe(pa_nc_id):
    criar_tabelas_pa_nao_conforme()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""
            SELECT nc.*, le.nome AS local_nome, cx.codigo_caixa,
                   cx.condicao, cx.disponibilidade
            FROM pa_nao_conformes nc LEFT JOIN pa_caixas cx ON cx.id=nc.caixa_id
            JOIN locais_estoque le ON le.id=nc.local_estoque_id WHERE nc.id=?
        """), (pa_nc_id,))
        registro = cursor.fetchone()
        cursor.execute(q("SELECT * FROM pa_nao_conforme_eventos WHERE pa_nao_conforme_id=? ORDER BY criado_em DESC, id DESC"), (pa_nc_id,))
        return registro, cursor.fetchall()
    finally:
        conn.close()


def indicadores(registros):
    bloqueados = [r for r in registros if r["status"] in {"BLOQUEADO", "EM_AVALIACAO", "MANTIDO_BLOQUEADO"}]
    tempos = []
    for r in registros:
        if r["decidido_em"]:
            try:
                tempos.append((datetime.fromisoformat(str(r["decidido_em"])) - datetime.fromisoformat(str(r["registrado_em"]))).total_seconds() / 3600)
            except (TypeError, ValueError):
                pass
    return {
        "registros_bloqueados": len(bloqueados),
        "peso_bloqueado": sum(
            int(r["saldo_bloqueado_g"] or 0) / 1000
            if r["tipo_registro"] == TIPO_LEGADO else float(r["peso"] or 0)
            for r in bloqueados
        ),
        "quantidade_bloqueada": sum(float(r["quantidade"] or 0) for r in bloqueados),
        "aguardando_avaliacao": sum(r["status"] == "BLOQUEADO" for r in registros),
        "liberados": sum(r["status"] == "LIBERADO" for r in registros),
        "retrabalho": sum(r["status"] == "RETRABALHO" for r in registros),
        "reprocesso": sum(r["status"] == "REPROCESSO" for r in registros),
        "descarte": sum(r["status"] == "DESCARTE" for r in registros),
        "tempo_medio_horas": sum(tempos) / len(tempos) if tempos else 0,
        "fisico_total_kg": round(sum(
            int(r["saldo_inicial_g"] or 0) / 1000
            if r["tipo_registro"] == TIPO_LEGADO else float(r["peso"] or 0)
            for r in registros
        ), 3),
        "caixas_informativas": sum(int(r["caixas_iniciais"] or 0) for r in registros if r["tipo_registro"] == TIPO_LEGADO),
        "nao_conforme_bloqueado_kg": round(sum(int(r["saldo_bloqueado_g"] or 0) / 1000 for r in registros if r["tipo_registro"] == TIPO_LEGADO and r["condicao_inicial"] == "NAO_CONFORME"), 3),
        "aguardando_liberacao_kg": round(sum(int(r["saldo_bloqueado_g"] or 0) / 1000 for r in registros if r["tipo_registro"] == TIPO_LEGADO and r["condicao_inicial"] == "CONFORME_AGUARDANDO_LIBERACAO"), 3),
        "pendente_gerencia_kg": round(sum(int(r["saldo_pendente_g"] or 0) / 1000 for r in registros), 3),
        "disponivel_kg": round(sum(int(r["saldo_operacional_g"] or 0) / 1000 for r in registros), 3),
    }
