"""Ordem de Retrabalho: transforma Produto Acabado existente em outro Produto Acabado.

Entidade própria, separada de `ordens_producao` (ver desenho em
output/ordem-retrabalho-etapa-a-auditoria-desenho.md). A saída da RT nunca
recebe linha em `pa_caixa_composicao` — a rastreabilidade de origem vive em
`retrabalho_origens`/`retrabalho_saidas`, e a origem sistêmica do PA formado é
a própria RT, nunca uma OP fictícia.

Reaproveita, sem duplicar, os mecanismos já existentes de:
- estoque (mesmo padrão `SELECT...FOR UPDATE` + guarda de saldo no `WHERE` do
  `UPDATE`, já usado em `modules.expedicao.estoque_service`);
- custo (`modules.cmv.services`, que já é genérico por `origem_tipo`/`origem_id`);
- etiquetas (`modules.label_printing.services`, que opera por `caixa_id`).
"""

from decimal import Decimal, InvalidOperation
import json
from uuid import uuid4

from database import DATABASE_URL, conectar, q, transaction
from modules.cmv.services import (
    estornar_saida as cmv_estornar_saida,
    registrar_camada as cmv_registrar_camada,
    registrar_saida as cmv_registrar_saida,
)
from modules.label_printing.services import criar_job_caixa_cursor, invalidar_jobs_caixa_cursor


PERFIS_ABRIR = {"admin", "gerencia", "pcp", "producao"}
PERFIS_ENCERRAR = PERFIS_ABRIR
PERFIS_CANCELAR = PERFIS_ABRIR
PERFIS_LIBERAR = {"admin", "gerencia", "qualidade"}
PERFIS_ESTORNAR = {"admin", "gerencia"}

STATUS_ABERTA = "ABERTA"
STATUS_EM_EXECUCAO = "EM_EXECUCAO"
STATUS_ENCERRADA = "ENCERRADA"
STATUS_CANCELADA = "CANCELADA"
STATUS_ESTORNADA = "ESTORNADA"
STATUS_LABELS = {
    STATUS_ABERTA: "Aberta (saldo reservado)",
    STATUS_EM_EXECUCAO: "Em execução",
    STATUS_ENCERRADA: "Encerrada",
    STATUS_CANCELADA: "Cancelada",
    STATUS_ESTORNADA: "Estornada",
}

FAMILIA_PACOTE = "PACOTE"
FAMILIA_PESO = "CAIXA"
FAMILIAS = (FAMILIA_PACOTE, FAMILIA_PESO)

_SCHEMA_RETRABALHO_INICIALIZADO = False


def _agora():
    from datetime import datetime
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _decimal(valor, campo, *, permite_ausente=False):
    if valor in (None, ""):
        if permite_ausente:
            return Decimal("0")
        raise ValueError(f"{campo} é obrigatória.")
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{campo} inválida.")


def criar_tabelas_retrabalho():
    """Migration de runtime idempotente (mesmo padrão de `criar_tabelas_estoque_confiavel`)."""
    global _SCHEMA_RETRABALHO_INICIALIZADO
    if _SCHEMA_RETRABALHO_INICIALIZADO:
        return
    conn = conectar()
    cursor = conn.cursor()
    id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_type = "TIMESTAMP" if DATABASE_URL else "TEXT"
    try:
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS retrabalhos (
            id {id_type},
            numero TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'ABERTA',
            motivo TEXT NOT NULL,
            sku_origem TEXT NOT NULL,
            apresentacao_origem TEXT,
            unidade_estoque_origem TEXT NOT NULL,
            sku_destino TEXT NOT NULL,
            apresentacao_destino TEXT,
            unidade_estoque_destino TEXT NOT NULL,
            galinhas_por_pacote_destino INTEGER,
            unidade_origem TEXT NOT NULL,
            unidade_destino TEXT NOT NULL,
            quantidade_planejada_origem REAL NOT NULL DEFAULT 0,
            quantidade_apontada_destino REAL,
            quantidade_perda REAL NOT NULL DEFAULT 0,
            unidade_perda TEXT,
            justificativa_perda TEXT,
            data_retrabalho TEXT NOT NULL,
            data_fabricacao_destino TEXT,
            data_validade_destino TEXT,
            local_estoque_id_destino INTEGER,
            observacoes TEXT,
            criado_por TEXT NOT NULL,
            perfil_criacao TEXT NOT NULL,
            criado_em {timestamp_type} NOT NULL,
            encerrado_por TEXT,
            encerrado_em {timestamp_type},
            liberado_por TEXT,
            liberado_em {timestamp_type},
            cancelado_por TEXT,
            cancelado_em {timestamp_type},
            motivo_cancelamento TEXT,
            estornado_por TEXT,
            estornado_em {timestamp_type},
            motivo_estorno TEXT,
            idempotency_key TEXT UNIQUE NOT NULL,
            versao INTEGER NOT NULL DEFAULT 0
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS retrabalho_origens (
            id {id_type},
            retrabalho_id INTEGER NOT NULL,
            caixa_id_origem INTEGER NOT NULL,
            op_id_origem INTEGER,
            quantidade_reservada REAL NOT NULL,
            quantidade_consumida REAL NOT NULL DEFAULT 0,
            unidade TEXT NOT NULL,
            galinhas_por_pacote_origem INTEGER,
            condicao_no_momento TEXT,
            disponibilidade_no_momento TEXT,
            data_fabricacao_origem TEXT,
            data_validade_origem TEXT,
            snapshot_json TEXT,
            criado_em {timestamp_type} NOT NULL
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS retrabalho_saidas (
            id {id_type},
            retrabalho_id INTEGER NOT NULL,
            caixa_id_destino INTEGER NOT NULL,
            quantidade REAL NOT NULL,
            unidade TEXT NOT NULL,
            criado_em {timestamp_type} NOT NULL
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS retrabalho_eventos (
            id {id_type},
            retrabalho_id INTEGER NOT NULL,
            acao TEXT NOT NULL,
            estado_anterior TEXT,
            estado_novo TEXT,
            usuario TEXT NOT NULL,
            perfil TEXT NOT NULL,
            justificativa TEXT,
            dados_json TEXT,
            criado_em {timestamp_type} NOT NULL,
            idempotency_key TEXT
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_retrabalho_origens_rt ON retrabalho_origens(retrabalho_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_retrabalho_saidas_rt ON retrabalho_saidas(retrabalho_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_retrabalho_eventos_rt ON retrabalho_eventos(retrabalho_id)")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_retrabalho_eventos_idem ON retrabalho_eventos(idempotency_key)"
        )
        conn.commit()
        _SCHEMA_RETRABALHO_INICIALIZADO = True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _evento_estoque(cursor, *, caixa_id, acao, situacao_anterior=None, situacao_nova=None,
                    condicao_anterior=None, condicao_nova=None, quantidade=0, justificativa=None,
                    observacao=None, usuario, perfil, idempotency_key=None):
    agora = _agora()
    parametros = (
        caixa_id, None, acao, situacao_anterior, situacao_nova, condicao_anterior, condicao_nova,
        float(quantidade or 0), None, justificativa, observacao, usuario, perfil, agora, idempotency_key,
    )
    if DATABASE_URL:
        cursor.execute(q("""
        INSERT INTO estoque_eventos (
            caixa_id, expedicao_id, acao, situacao_anterior, situacao_nova, condicao_anterior,
            condicao_nova, quantidade, peso, justificativa, observacao, usuario, perfil, criado_em,
            idempotency_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (idempotency_key) DO NOTHING
        """), parametros)
    else:
        cursor.execute(q("""
        INSERT OR IGNORE INTO estoque_eventos (
            caixa_id, expedicao_id, acao, situacao_anterior, situacao_nova, condicao_anterior,
            condicao_nova, quantidade, peso, justificativa, observacao, usuario, perfil, criado_em,
            idempotency_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """), parametros)


def _ja_processado(cursor, idempotency_key):
    if not idempotency_key:
        return None
    cursor.execute(q("SELECT * FROM retrabalho_eventos WHERE idempotency_key=?"), (idempotency_key,))
    linha = cursor.fetchone()
    return dict(linha) if linha else None


def _evento_rt(cursor, retrabalho_id, acao, estado_anterior, estado_novo, *, usuario, perfil,
              justificativa=None, dados=None, idempotency_key=None):
    cursor.execute(q("""
        INSERT INTO retrabalho_eventos (
            retrabalho_id, acao, estado_anterior, estado_novo, usuario, perfil, justificativa,
            dados_json, criado_em, idempotency_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
    """), (
        retrabalho_id, acao, estado_anterior, estado_novo, usuario, perfil, justificativa,
        json.dumps(dados or {}, ensure_ascii=False, sort_keys=True, default=str), _agora(), idempotency_key,
    ))


def _unidade_padrao(unidade_estoque, papel):
    if unidade_estoque == FAMILIA_PACOTE:
        return "AVE" if papel == "origem" else "PACOTE"
    return "KG"


def abrir_retrabalho(dados, origens, *, usuario, perfil, idempotency_key=None, checkpoint=None):
    """Cria a RT (numero RT-000001) e reserva imediatamente o saldo das origens.

    `origens` é uma lista de {"caixa_id": int, "quantidade": ...}. A quantidade é
    expressa na unidade nativa da posição de origem: aves, quando
    `unidade_estoque_origem == 'PACOTE'` (galinha inteira), ou quilogramas
    quando for da família caixa/bandeja/peso.
    """
    perfil = (perfil or "").strip().lower()
    if perfil not in PERFIS_ABRIR:
        raise PermissionError("Perfil sem permissão para abrir Ordem de Retrabalho.")
    motivo = str(dados.get("motivo") or "").strip()
    sku_origem = str(dados.get("sku_origem") or "").strip()
    unidade_estoque_origem = str(dados.get("unidade_estoque_origem") or "").strip().upper()
    sku_destino = str(dados.get("sku_destino") or "").strip()
    unidade_estoque_destino = str(dados.get("unidade_estoque_destino") or "").strip().upper()
    data_retrabalho = str(dados.get("data_retrabalho") or "").strip()
    if not motivo or not sku_origem or not sku_destino or not data_retrabalho:
        raise ValueError("Motivo, produto de origem, produto de destino e data são obrigatórios.")
    if unidade_estoque_origem not in FAMILIAS:
        raise ValueError("Unidade de estoque de origem inválida.")
    if unidade_estoque_destino not in FAMILIAS:
        raise ValueError("Unidade de estoque de destino inválida.")
    galinhas_por_pacote_destino = None
    if unidade_estoque_destino == FAMILIA_PACOTE:
        galinhas_por_pacote_destino = int(dados.get("galinhas_por_pacote_destino") or 0)
        if galinhas_por_pacote_destino <= 0:
            raise ValueError("Informe quantas aves compõem cada pacote do produto de destino.")
    if not origens:
        raise ValueError("Selecione ao menos uma posição de origem.")

    criar_tabelas_retrabalho()
    idempotency_key = idempotency_key or f"RT-ABERTURA-{uuid4().hex}"
    unidade_origem = str(dados.get("unidade_origem") or "").strip().upper() or _unidade_padrao(unidade_estoque_origem, "origem")
    unidade_destino = str(dados.get("unidade_destino") or "").strip().upper() or _unidade_padrao(unidade_estoque_destino, "destino")

    with transaction() as conn:
        cursor = conn.cursor()
        existente = _ja_processado(cursor, idempotency_key)
        if existente and existente["acao"] == "ABERTURA":
            cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (existente["retrabalho_id"],))
            return dict(cursor.fetchone())

        agora = _agora()
        parametros = (
            STATUS_ABERTA, motivo, sku_origem, str(dados.get("apresentacao_origem") or "").strip() or None,
            unidade_estoque_origem, sku_destino, str(dados.get("apresentacao_destino") or "").strip() or None,
            unidade_estoque_destino, galinhas_por_pacote_destino, unidade_origem, unidade_destino,
            data_retrabalho, str(dados.get("observacoes") or "").strip() or None,
            usuario, perfil, agora, idempotency_key,
        )
        sql = """INSERT INTO retrabalhos (
            status, motivo, sku_origem, apresentacao_origem, unidade_estoque_origem,
            sku_destino, apresentacao_destino, unidade_estoque_destino, galinhas_por_pacote_destino,
            unidade_origem, unidade_destino, data_retrabalho, observacoes,
            criado_por, perfil_criacao, criado_em, idempotency_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        if DATABASE_URL:
            cursor.execute(q(sql + " RETURNING id"), parametros)
            rt_id = cursor.fetchone()["id"]
        else:
            cursor.execute(q(sql), parametros)
            rt_id = cursor.lastrowid
        numero = f"RT-{rt_id:06d}"
        cursor.execute(q("UPDATE retrabalhos SET numero=? WHERE id=?"), (numero, rt_id))

        bloqueio = " FOR UPDATE" if DATABASE_URL else ""
        total_origem = Decimal("0")
        for item in origens:
            caixa_id = int(item.get("caixa_id"))
            quantidade = _decimal(item.get("quantidade"), "Quantidade de origem")
            if quantidade <= 0:
                raise ValueError("A quantidade de cada origem deve ser maior que zero.")
            cursor.execute(q(f"SELECT * FROM pa_caixas WHERE id=?{bloqueio}"), (caixa_id,))
            caixa = cursor.fetchone()
            if not caixa:
                raise ValueError(f"Posição de origem {caixa_id} não encontrada.")
            codigo = caixa["codigo_caixa"]
            if (caixa["sku"] or "").strip() != sku_origem:
                raise ValueError(f"A posição {codigo} não é do produto de origem informado.")
            if (caixa["unidade_estoque"] or "").upper() != unidade_estoque_origem:
                raise ValueError(f"A posição {codigo} não usa a unidade de estoque informada.")
            if caixa["condicao"] != "CONFORME" or caixa["disponibilidade"] != "DISPONIVEL" \
                    or int(caixa["estoque_operacional"] or 0) != 1:
                raise ValueError(f"A posição {codigo} não está disponível para retrabalho.")

            situacao_nova_evento = "DISPONIVEL"
            if unidade_estoque_origem == FAMILIA_PACOTE:
                fator = int(caixa["galinhas_por_pacote"] or 0)
                if fator <= 0:
                    raise ValueError(f"A posição {codigo} não tem quantidade de aves por pacote configurada.")
                if quantidade % fator != 0:
                    raise ValueError(f"A posição {codigo} exige múltiplos de {fator} aves por pacote.")
                pacotes_necessarios = int(quantidade // fator)
                cursor.execute(q("""
                    UPDATE pa_caixas SET quantidade_pacotes_reservados = COALESCE(quantidade_pacotes_reservados,0) + ?
                    WHERE id=? AND quantidade_pacotes - COALESCE(quantidade_pacotes_reservados,0) >= ?
                """), (pacotes_necessarios, caixa_id, pacotes_necessarios))
                if cursor.rowcount != 1:
                    raise ValueError(f"Saldo insuficiente na posição {codigo} (reservado por outra operação).")
            else:
                peso_disponivel = Decimal(str(caixa["peso_liquido"] or 0))
                if quantidade > peso_disponivel:
                    raise ValueError(f"Saldo insuficiente na posição {codigo}.")
                cursor.execute(q("""
                    UPDATE pa_caixas SET disponibilidade='RESERVADO'
                    WHERE id=? AND disponibilidade='DISPONIVEL'
                """), (caixa_id,))
                if cursor.rowcount != 1:
                    raise ValueError(f"A posição {codigo} foi reservada por outra operação.")
                situacao_nova_evento = "RESERVADO"

            cursor.execute(q("SELECT MIN(op_id) AS op_id FROM pa_caixa_composicao WHERE caixa_id=?"), (caixa_id,))
            linha_op = cursor.fetchone()
            op_id_origem = int(linha_op["op_id"]) if linha_op and linha_op["op_id"] is not None else None

            cursor.execute(q("""
                INSERT INTO retrabalho_origens (
                    retrabalho_id, caixa_id_origem, op_id_origem, quantidade_reservada, unidade,
                    galinhas_por_pacote_origem, condicao_no_momento, disponibilidade_no_momento,
                    data_fabricacao_origem, data_validade_origem, snapshot_json, criado_em
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """), (
                rt_id, caixa_id, op_id_origem, float(quantidade), unidade_origem,
                caixa["galinhas_por_pacote"], caixa["condicao"], caixa["disponibilidade"],
                caixa["data_fabricacao"], caixa["data_validade"],
                json.dumps({"codigo_caixa": codigo}, ensure_ascii=False), agora,
            ))
            _evento_estoque(
                cursor, caixa_id=caixa_id, acao="RETRABALHO_RESERVA", situacao_anterior="DISPONIVEL",
                situacao_nova=situacao_nova_evento, quantidade=quantidade, justificativa=motivo,
                observacao=f"Reservado para {numero}.", usuario=usuario, perfil=perfil,
            )
            total_origem += quantidade

        cursor.execute(q("UPDATE retrabalhos SET quantidade_planejada_origem=? WHERE id=?"),
                       (float(total_origem), rt_id))
        _evento_rt(
            cursor, rt_id, "ABERTURA", None, STATUS_ABERTA, usuario=usuario, perfil=perfil,
            justificativa=motivo, dados={"total_origem": str(total_origem), "origens": len(origens)},
            idempotency_key=idempotency_key,
        )
        if checkpoint:
            checkpoint("retrabalho_aberto")
        cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
        return dict(cursor.fetchone())


def encerrar_retrabalho(rt_id, saida, *, usuario, perfil, idempotency_key=None, checkpoint=None):
    """Consome as origens reservadas e forma o PA de destino, tudo em uma única transação.

    O produto formado nasce com `condicao='CONFORME'` e `disponibilidade='PENDENTE_OP'`
    (o mesmo estado já usado hoje para "formado, mas ainda não liberado para
    expedição" — ver seção 3.3/17 do desenho aprovado). Não fica disponível para
    romaneio até `liberar_retrabalho` ser chamado pela Qualidade.
    """
    perfil = (perfil or "").strip().lower()
    if perfil not in PERFIS_ENCERRAR:
        raise PermissionError("Perfil sem permissão para encerrar Ordem de Retrabalho.")
    quantidade_apontada = _decimal(saida.get("quantidade_apontada_destino"), "Quantidade apontada de saída")
    if quantidade_apontada <= 0:
        raise ValueError("Informe a quantidade real produzida.")
    data_fabricacao_destino = str(saida.get("data_fabricacao_destino") or "").strip()
    data_validade_destino = str(saida.get("data_validade_destino") or "").strip()
    if not data_fabricacao_destino or not data_validade_destino:
        raise ValueError("Informe a data de fabricação e a validade do produto resultante.")
    try:
        local_estoque_id_destino = int(saida.get("local_estoque_id_destino") or 0)
    except (TypeError, ValueError):
        local_estoque_id_destino = 0
    if not local_estoque_id_destino:
        raise ValueError("Informe o local de estoque do produto resultante.")
    quantidade_perda = _decimal(saida.get("quantidade_perda"), "Perda", permite_ausente=True)

    criar_tabelas_retrabalho()
    idempotency_key = idempotency_key or f"RT-ENCERRAR-{rt_id}-{uuid4().hex}"

    with transaction() as conn:
        cursor = conn.cursor()
        existente = _ja_processado(cursor, idempotency_key)
        if existente and existente["acao"] == "ENCERRAMENTO":
            cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
            resultado = dict(cursor.fetchone())
            cursor.execute(q("SELECT * FROM retrabalho_saidas WHERE retrabalho_id=?"), (rt_id,))
            saidas_existentes = [dict(r) for r in cursor.fetchall()]
            resultado["caixa_destino_id"] = saidas_existentes[0]["caixa_id_destino"] if saidas_existentes else None
            return resultado

        bloqueio = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q(f"SELECT * FROM retrabalhos WHERE id=?{bloqueio}"), (rt_id,))
        rt = cursor.fetchone()
        if not rt:
            raise ValueError("Ordem de Retrabalho não encontrada.")
        if rt["status"] not in (STATUS_ABERTA, STATUS_EM_EXECUCAO):
            raise ValueError("A Ordem de Retrabalho não está aberta para encerramento.")

        cursor.execute(q("SELECT * FROM retrabalho_origens WHERE retrabalho_id=?"), (rt_id,))
        origens = cursor.fetchall()
        if not origens:
            raise ValueError("A Ordem de Retrabalho não possui origens reservadas.")

        total_aves_consumidas = Decimal("0")
        total_peso_consumido = Decimal("0")
        for origem in origens:
            caixa_id = origem["caixa_id_origem"]
            quantidade = Decimal(str(origem["quantidade_reservada"]))
            cursor.execute(q(f"SELECT * FROM pa_caixas WHERE id=?{bloqueio}"), (caixa_id,))
            caixa = cursor.fetchone()
            if not caixa:
                raise ValueError(f"Posição de origem {caixa_id} não encontrada para consumo.")
            codigo = caixa["codigo_caixa"]
            situacao_anterior = caixa["disponibilidade"]

            if rt["unidade_estoque_origem"] == FAMILIA_PACOTE:
                fator = int(caixa["galinhas_por_pacote"] or origem["galinhas_por_pacote_origem"] or 0)
                if fator <= 0:
                    raise ValueError(f"A posição {codigo} perdeu a configuração de aves por pacote.")
                pacotes = int(quantidade // fator)
                cursor.execute(q("""
                    UPDATE pa_caixas SET
                        quantidade_pacotes = quantidade_pacotes - ?,
                        quantidade_galinhas = quantidade_galinhas - ?,
                        quantidade_pacotes_reservados = quantidade_pacotes_reservados - ?
                    WHERE id=? AND quantidade_pacotes >= ? AND quantidade_pacotes_reservados >= ?
                """), (pacotes, int(quantidade), pacotes, caixa_id, pacotes, pacotes))
                if cursor.rowcount != 1:
                    raise ValueError(f"A reserva da posição {codigo} não está mais íntegra.")
                cursor.execute(q("SELECT quantidade_pacotes FROM pa_caixas WHERE id=?"), (caixa_id,))
                restante = int(cursor.fetchone()["quantidade_pacotes"] or 0)
                if restante == 0:
                    cursor.execute(q("""
                        UPDATE pa_caixas SET disponibilidade='RETRABALHADO', status='Retrabalhada' WHERE id=?
                    """), (caixa_id,))
                    invalidar_jobs_caixa_cursor(cursor, caixa_id, motivo="RETRABALHO_CONSUMO_TOTAL")
                total_aves_consumidas += quantidade
            else:
                cursor.execute(q("""
                    UPDATE pa_caixas SET peso_liquido = peso_liquido - ?
                    WHERE id=? AND peso_liquido >= ? AND disponibilidade='RESERVADO'
                """), (float(quantidade), caixa_id, float(quantidade)))
                if cursor.rowcount != 1:
                    raise ValueError(f"A reserva da posição {codigo} não está mais íntegra.")
                cursor.execute(q("SELECT peso_liquido FROM pa_caixas WHERE id=?"), (caixa_id,))
                restante_peso = Decimal(str(cursor.fetchone()["peso_liquido"] or 0))
                if restante_peso <= 0:
                    cursor.execute(q("""
                        UPDATE pa_caixas SET disponibilidade='RETRABALHADO', status='Retrabalhada' WHERE id=?
                    """), (caixa_id,))
                    invalidar_jobs_caixa_cursor(cursor, caixa_id, motivo="RETRABALHO_CONSUMO_TOTAL")
                else:
                    cursor.execute(q("UPDATE pa_caixas SET disponibilidade='DISPONIVEL' WHERE id=?"), (caixa_id,))
                total_peso_consumido += quantidade

            cursor.execute(q("UPDATE retrabalho_origens SET quantidade_consumida=? WHERE id=?"),
                           (float(quantidade), origem["id"]))
            _evento_estoque(
                cursor, caixa_id=caixa_id, acao="RETRABALHO_CONSUMO", situacao_anterior=situacao_anterior,
                situacao_nova="RETRABALHADO", quantidade=quantidade, justificativa=rt["motivo"],
                observacao=f"Consumido por {rt['numero']}.", usuario=usuario, perfil=perfil,
            )

        unidade_cmv_origem = "UN" if rt["unidade_estoque_origem"] == FAMILIA_PACOTE else "KG"
        quantidade_cmv_origem = total_aves_consumidas if rt["unidade_estoque_origem"] == FAMILIA_PACOTE else total_peso_consumido
        evento_cmv_saida = None
        if quantidade_cmv_origem > 0:
            evento_cmv_saida, _ = cmv_registrar_saida(
                data_evento=rt["data_retrabalho"], documento=rt["numero"], produto=rt["sku_origem"],
                unidade=unidade_cmv_origem, quantidade=quantidade_cmv_origem, origem_tipo="RETRABALHO",
                origem_id=str(rt_id), idempotency_key=f"CMV:RT:{rt_id}:SAIDA", usuario=usuario,
                tipo_evento="RETRABALHO", cursor=cursor,
            )

        familia_destino = rt["unidade_estoque_destino"]
        codigo_caixa_destino = f"RT-PA-{rt_id:06d}-01"
        if familia_destino == FAMILIA_PACOTE:
            galinhas_por_pacote = int(rt["galinhas_por_pacote_destino"] or 0)
            quantidade_pacotes_destino = int(quantidade_apontada)
            quantidade_galinhas_destino = quantidade_pacotes_destino * galinhas_por_pacote
            sql_destino = """
            INSERT INTO pa_caixas (
                codigo_caixa, sku, data_fabricacao, data_validade, status, origem, observacoes,
                local_estoque_id, estoque_operacional, unidade_estoque, apresentacao,
                galinhas_por_pacote, quantidade_pacotes, quantidade_galinhas,
                quantidade_pacotes_reservados, condicao, disponibilidade, zona_estoque
            ) VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?,0,?,?,?)
            """
            parametros_destino = (
                codigo_caixa_destino, rt["sku_destino"], data_fabricacao_destino, data_validade_destino,
                "Em estoque", "Retrabalho", f"Formado pela Ordem de Retrabalho {rt['numero']}.",
                local_estoque_id_destino, FAMILIA_PACOTE, rt["apresentacao_destino"],
                galinhas_por_pacote, quantidade_pacotes_destino, quantidade_galinhas_destino,
                "CONFORME", "PENDENTE_OP", "Conforme",
            )
            quantidade_cmv_destino = Decimal(quantidade_galinhas_destino)
            unidade_cmv_destino = "UN"
        else:
            sql_destino = """
            INSERT INTO pa_caixas (
                codigo_caixa, sku, data_fabricacao, data_validade, status, origem, observacoes,
                local_estoque_id, estoque_operacional, unidade_estoque, apresentacao,
                peso_bruto, peso_liquido, peso_tara, quantidade_bandejas,
                condicao, disponibilidade, zona_estoque
            ) VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)
            """
            parametros_destino = (
                codigo_caixa_destino, rt["sku_destino"], data_fabricacao_destino, data_validade_destino,
                "Em estoque", "Retrabalho", f"Formado pela Ordem de Retrabalho {rt['numero']}.",
                local_estoque_id_destino, FAMILIA_PESO, rt["apresentacao_destino"],
                float(quantidade_apontada), float(quantidade_apontada), 0.0,
                int(saida.get("quantidade_bandejas_destino") or 0),
                "CONFORME", "PENDENTE_OP", "Conforme",
            )
            quantidade_cmv_destino = quantidade_apontada
            unidade_cmv_destino = "KG"

        if DATABASE_URL:
            cursor.execute(q(sql_destino + " RETURNING id"), parametros_destino)
            caixa_destino_id = cursor.fetchone()["id"]
        else:
            cursor.execute(q(sql_destino), parametros_destino)
            caixa_destino_id = cursor.lastrowid

        cursor.execute(q("""
            INSERT INTO retrabalho_saidas (retrabalho_id, caixa_id_destino, quantidade, unidade, criado_em)
            VALUES (?,?,?,?,?)
        """), (rt_id, caixa_destino_id, float(quantidade_apontada), rt["unidade_destino"], _agora()))

        if familia_destino == FAMILIA_PESO:
            # Galinha Inteira (PACOTE) nunca teve automação de etiqueta por posição
            # (ver seção 15-A do desenho); só a família caixa/bandeja participa.
            criar_job_caixa_cursor(cursor, caixa_destino_id, solicitado_por=usuario)

        if evento_cmv_saida is not None and quantidade_cmv_destino and quantidade_cmv_destino > 0:
            custo_total_origem = evento_cmv_saida.get("custo_total")
            custo_unitario_destino = None
            custo_conhecido = False
            if custo_total_origem is not None:
                custo_unitario_destino = Decimal(str(custo_total_origem)) / quantidade_cmv_destino
                custo_conhecido = True
            cmv_registrar_camada(
                produto=rt["sku_destino"], unidade=unidade_cmv_destino, data_entrada=rt["data_retrabalho"],
                quantidade=quantidade_cmv_destino, custo_unitario=custo_unitario_destino,
                custo_conhecido=custo_conhecido, origem_tipo="RETRABALHO", origem_id=str(rt_id),
                documento=rt["numero"], idempotency_key=f"CMV:RT:{rt_id}:CAMADA", usuario=usuario,
                cursor=cursor,
            )

        _evento_estoque(
            cursor, caixa_id=caixa_destino_id, acao="RETRABALHO_FORMACAO", situacao_nova="PENDENTE_OP",
            condicao_nova="CONFORME", quantidade=quantidade_apontada, justificativa=rt["motivo"],
            observacao=f"Formado por {rt['numero']}; aguardando liberação da Qualidade.",
            usuario=usuario, perfil=perfil,
        )

        cursor.execute(q("""
            UPDATE retrabalhos SET status=?, quantidade_apontada_destino=?, quantidade_perda=?,
                unidade_perda=?, justificativa_perda=?, data_fabricacao_destino=?, data_validade_destino=?,
                local_estoque_id_destino=?, encerrado_por=?, encerrado_em=?, versao=versao+1
            WHERE id=?
        """), (
            STATUS_ENCERRADA, float(quantidade_apontada), float(quantidade_perda),
            str(saida.get("unidade_perda") or "").strip() or None,
            str(saida.get("justificativa_perda") or "").strip() or None,
            data_fabricacao_destino, data_validade_destino, local_estoque_id_destino,
            usuario, _agora(), rt_id,
        ))
        _evento_rt(
            cursor, rt_id, "ENCERRAMENTO", rt["status"], STATUS_ENCERRADA, usuario=usuario, perfil=perfil,
            justificativa=rt["motivo"],
            dados={"quantidade_apontada_destino": str(quantidade_apontada), "caixa_destino_id": caixa_destino_id},
            idempotency_key=idempotency_key,
        )
        if checkpoint:
            checkpoint("retrabalho_encerrado")
        cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
        resultado = dict(cursor.fetchone())
        resultado["caixa_destino_id"] = caixa_destino_id
        return resultado


def liberar_retrabalho(rt_id, *, usuario, perfil, idempotency_key=None):
    """Ação da Qualidade: libera o(s) PA formado(s) para expedição (PENDENTE_OP -> DISPONIVEL)."""
    perfil = (perfil or "").strip().lower()
    if perfil not in PERFIS_LIBERAR:
        raise PermissionError("Perfil sem permissão para liberar o produto do retrabalho.")
    criar_tabelas_retrabalho()
    idempotency_key = idempotency_key or f"RT-LIBERAR-{rt_id}-{uuid4().hex}"
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _ja_processado(cursor, idempotency_key)
        if existente and existente["acao"] == "LIBERACAO":
            cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
            return dict(cursor.fetchone())

        bloqueio = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q(f"SELECT * FROM retrabalhos WHERE id=?{bloqueio}"), (rt_id,))
        rt = cursor.fetchone()
        if not rt:
            raise ValueError("Ordem de Retrabalho não encontrada.")
        if rt["status"] != STATUS_ENCERRADA:
            raise ValueError("Somente uma Ordem de Retrabalho encerrada pode ser liberada.")
        if rt["liberado_em"]:
            raise ValueError("O produto desta Ordem de Retrabalho já foi liberado.")

        cursor.execute(q("SELECT * FROM retrabalho_saidas WHERE retrabalho_id=?"), (rt_id,))
        saidas = cursor.fetchall()
        if not saidas:
            raise ValueError("A Ordem de Retrabalho não possui produto formado para liberar.")
        for saida in saidas:
            caixa_id = saida["caixa_id_destino"]
            cursor.execute(q(f"SELECT disponibilidade FROM pa_caixas WHERE id=?{bloqueio}"), (caixa_id,))
            caixa = cursor.fetchone()
            if not caixa or caixa["disponibilidade"] != "PENDENTE_OP":
                raise ValueError("O produto formado não está mais aguardando liberação.")
            cursor.execute(q("""
                UPDATE pa_caixas SET disponibilidade='DISPONIVEL' WHERE id=? AND disponibilidade='PENDENTE_OP'
            """), (caixa_id,))
            if cursor.rowcount != 1:
                raise ValueError("O produto formado foi alterado simultaneamente.")
            _evento_estoque(
                cursor, caixa_id=caixa_id, acao="RETRABALHO_LIBERACAO", situacao_anterior="PENDENTE_OP",
                situacao_nova="DISPONIVEL", justificativa="Liberação da Qualidade.",
                usuario=usuario, perfil=perfil,
            )

        cursor.execute(q("UPDATE retrabalhos SET liberado_por=?, liberado_em=?, versao=versao+1 WHERE id=?"),
                       (usuario, _agora(), rt_id))
        _evento_rt(cursor, rt_id, "LIBERACAO", STATUS_ENCERRADA, STATUS_ENCERRADA, usuario=usuario,
                  perfil=perfil, idempotency_key=idempotency_key)
        cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
        return dict(cursor.fetchone())


def cancelar_retrabalho(rt_id, justificativa, *, usuario, perfil, idempotency_key=None):
    """Cancela uma RT ainda não encerrada e libera as reservas feitas na abertura."""
    perfil = (perfil or "").strip().lower()
    if perfil not in PERFIS_CANCELAR:
        raise PermissionError("Perfil sem permissão para cancelar Ordem de Retrabalho.")
    justificativa = str(justificativa or "").strip()
    if not justificativa:
        raise ValueError("A justificativa do cancelamento é obrigatória.")
    criar_tabelas_retrabalho()
    idempotency_key = idempotency_key or f"RT-CANCELAR-{rt_id}-{uuid4().hex}"
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _ja_processado(cursor, idempotency_key)
        if existente and existente["acao"] == "CANCELAMENTO":
            cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
            return dict(cursor.fetchone())

        bloqueio = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q(f"SELECT * FROM retrabalhos WHERE id=?{bloqueio}"), (rt_id,))
        rt = cursor.fetchone()
        if not rt:
            raise ValueError("Ordem de Retrabalho não encontrada.")
        if rt["status"] not in (STATUS_ABERTA, STATUS_EM_EXECUCAO):
            raise ValueError("Somente uma Ordem de Retrabalho aberta pode ser cancelada.")

        cursor.execute(q("SELECT * FROM retrabalho_origens WHERE retrabalho_id=?"), (rt_id,))
        for origem in cursor.fetchall():
            caixa_id = origem["caixa_id_origem"]
            quantidade = Decimal(str(origem["quantidade_reservada"]))
            if rt["unidade_estoque_origem"] == FAMILIA_PACOTE:
                fator = int(origem["galinhas_por_pacote_origem"] or 0)
                pacotes = int(quantidade // fator) if fator else 0
                cursor.execute(q("""
                    UPDATE pa_caixas SET quantidade_pacotes_reservados = quantidade_pacotes_reservados - ?
                    WHERE id=? AND quantidade_pacotes_reservados >= ?
                """), (pacotes, caixa_id, pacotes))
            else:
                cursor.execute(q("""
                    UPDATE pa_caixas SET disponibilidade='DISPONIVEL'
                    WHERE id=? AND disponibilidade='RESERVADO'
                """), (caixa_id,))
            _evento_estoque(
                cursor, caixa_id=caixa_id, acao="RETRABALHO_CANCELAMENTO", situacao_nova="DISPONIVEL",
                quantidade=quantidade, justificativa=justificativa,
                observacao=f"Reserva de {rt['numero']} liberada por cancelamento.",
                usuario=usuario, perfil=perfil,
            )

        cursor.execute(q("""
            UPDATE retrabalhos SET status=?, cancelado_por=?, cancelado_em=?, motivo_cancelamento=?, versao=versao+1
            WHERE id=?
        """), (STATUS_CANCELADA, usuario, _agora(), justificativa, rt_id))
        _evento_rt(cursor, rt_id, "CANCELAMENTO", rt["status"], STATUS_CANCELADA, usuario=usuario,
                  perfil=perfil, justificativa=justificativa, idempotency_key=idempotency_key)
        cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
        return dict(cursor.fetchone())


def estornar_retrabalho(rt_id, justificativa, *, usuario, perfil, idempotency_key=None):
    """Estorno compensatório de uma RT já encerrada. Nunca hard delete.

    Bloqueado se o produto formado já foi movimentado (reservado/expedido/bloqueado)
    ou se a camada de custo já foi parcialmente consumida.
    """
    perfil = (perfil or "").strip().lower()
    if perfil not in PERFIS_ESTORNAR:
        raise PermissionError("Perfil sem permissão para estornar Ordem de Retrabalho.")
    justificativa = str(justificativa or "").strip()
    if not justificativa:
        raise ValueError("A justificativa do estorno é obrigatória.")
    criar_tabelas_retrabalho()
    idempotency_key = idempotency_key or f"RT-ESTORNAR-{rt_id}-{uuid4().hex}"

    with transaction() as conn:
        cursor = conn.cursor()
        existente = _ja_processado(cursor, idempotency_key)
        if existente and existente["acao"] == "ESTORNO":
            cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
            return dict(cursor.fetchone())

        bloqueio = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q(f"SELECT * FROM retrabalhos WHERE id=?{bloqueio}"), (rt_id,))
        rt = cursor.fetchone()
        if not rt:
            raise ValueError("Ordem de Retrabalho não encontrada.")
        if rt["status"] != STATUS_ENCERRADA:
            raise ValueError("Somente uma Ordem de Retrabalho encerrada pode ser estornada.")

        cursor.execute(q("SELECT * FROM retrabalho_saidas WHERE retrabalho_id=?"), (rt_id,))
        saidas = cursor.fetchall()
        for saida in saidas:
            caixa_id = saida["caixa_id_destino"]
            cursor.execute(q(f"SELECT * FROM pa_caixas WHERE id=?{bloqueio}"), (caixa_id,))
            caixa = cursor.fetchone()
            if not caixa:
                raise ValueError("Produto formado pela Ordem de Retrabalho não encontrado para estorno.")
            if caixa["disponibilidade"] not in ("PENDENTE_OP", "DISPONIVEL"):
                raise ValueError(
                    "O produto formado já foi movimentado (reservado, expedido ou bloqueado) "
                    "e não pode mais ser estornado automaticamente."
                )
            if rt["unidade_estoque_destino"] == FAMILIA_PACOTE:
                if int(caixa["quantidade_pacotes_reservados"] or 0) > 0:
                    raise ValueError("O produto formado possui pacotes reservados; estorno bloqueado.")
                if int(caixa["quantidade_pacotes"] or 0) != int(saida["quantidade"]):
                    raise ValueError("O saldo do produto formado foi alterado; estorno bloqueado.")
            else:
                if abs(Decimal(str(caixa["peso_liquido"] or 0)) - Decimal(str(saida["quantidade"]))) > Decimal("0.001"):
                    raise ValueError("O saldo do produto formado foi alterado; estorno bloqueado.")

            cursor.execute(q("""
                UPDATE pa_caixas SET disponibilidade='ESTORNADO', status='Estornada',
                    estornada_em=?, estornada_por=?, estorno_motivo=? WHERE id=?
            """), (_agora(), usuario, justificativa, caixa_id))
            invalidar_jobs_caixa_cursor(cursor, caixa_id, motivo="RETRABALHO_ESTORNADO")
            _evento_estoque(
                cursor, caixa_id=caixa_id, acao="RETRABALHO_ESTORNO", situacao_anterior=caixa["disponibilidade"],
                situacao_nova="ESTORNADO", quantidade=saida["quantidade"], justificativa=justificativa,
                usuario=usuario, perfil=perfil,
            )

        cursor.execute(q("SELECT * FROM retrabalho_origens WHERE retrabalho_id=?"), (rt_id,))
        for origem in cursor.fetchall():
            caixa_id = origem["caixa_id_origem"]
            quantidade = Decimal(str(origem["quantidade_consumida"] or origem["quantidade_reservada"]))
            cursor.execute(q(f"SELECT id FROM pa_caixas WHERE id=?{bloqueio}"), (caixa_id,))
            if not cursor.fetchone():
                raise ValueError("Posição de origem não encontrada para restauração do estorno.")
            if rt["unidade_estoque_origem"] == FAMILIA_PACOTE:
                fator = int(origem["galinhas_por_pacote_origem"] or 0)
                pacotes = int(quantidade // fator) if fator else 0
                cursor.execute(q("""
                    UPDATE pa_caixas SET
                        quantidade_pacotes = quantidade_pacotes + ?,
                        quantidade_galinhas = quantidade_galinhas + ?,
                        disponibilidade = CASE WHEN disponibilidade='RETRABALHADO' THEN 'DISPONIVEL' ELSE disponibilidade END,
                        status = CASE WHEN status='Retrabalhada' THEN 'Em estoque' ELSE status END
                    WHERE id=?
                """), (pacotes, int(quantidade), caixa_id))
            else:
                cursor.execute(q("""
                    UPDATE pa_caixas SET
                        peso_liquido = peso_liquido + ?,
                        disponibilidade = CASE WHEN disponibilidade='RETRABALHADO' THEN 'DISPONIVEL' ELSE disponibilidade END,
                        status = CASE WHEN status='Retrabalhada' THEN 'Em estoque' ELSE status END
                    WHERE id=?
                """), (float(quantidade), caixa_id))
            _evento_estoque(
                cursor, caixa_id=caixa_id, acao="RETRABALHO_ESTORNO", situacao_nova="DISPONIVEL",
                quantidade=quantidade, justificativa=justificativa,
                observacao=f"Origem restaurada pelo estorno de {rt['numero']}.", usuario=usuario, perfil=perfil,
            )

        cursor.execute(q("""
            SELECT id FROM cmv_eventos WHERE tipo='RETRABALHO' AND origem_tipo='RETRABALHO' AND origem_id=?
        """), (str(rt_id),))
        evento_saida = cursor.fetchone()
        if evento_saida:
            cmv_estornar_saida(
                int(evento_saida["id"]), data_evento=_agora()[:10],
                idempotency_key=f"CMV:RT:{rt_id}:ESTORNO_SAIDA", justificativa=justificativa, usuario=usuario,
                cursor=cursor,
            )

        cursor.execute(q("""
            SELECT id, quantidade_disponivel, quantidade_inicial FROM cmv_camadas
            WHERE origem_tipo='RETRABALHO' AND origem_id=? AND idempotency_key=?
        """), (str(rt_id), f"CMV:RT:{rt_id}:CAMADA"))
        camada = cursor.fetchone()
        if camada:
            if Decimal(str(camada["quantidade_disponivel"])) != Decimal(str(camada["quantidade_inicial"])):
                raise ValueError(
                    "O produto formado por esta Ordem de Retrabalho já foi parcialmente consumido "
                    "no custeio (CMV); estorno bloqueado."
                )
            cursor.execute(q("UPDATE cmv_camadas SET status='ESTORNADA', quantidade_disponivel=0 WHERE id=?"),
                           (camada["id"],))

        cursor.execute(q("""
            UPDATE retrabalhos SET status=?, estornado_por=?, estornado_em=?, motivo_estorno=?, versao=versao+1
            WHERE id=?
        """), (STATUS_ESTORNADA, usuario, _agora(), justificativa, rt_id))
        _evento_rt(cursor, rt_id, "ESTORNO", STATUS_ENCERRADA, STATUS_ESTORNADA, usuario=usuario,
                  perfil=perfil, justificativa=justificativa, idempotency_key=idempotency_key)
        cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
        return dict(cursor.fetchone())


def listar_retrabalhos(filtros=None):
    criar_tabelas_retrabalho()
    filtros = filtros or {}
    clausulas, params = ["1=1"], []
    if filtros.get("numero"):
        clausulas.append("numero LIKE ?")
        params.append(f"%{filtros['numero']}%")
    if filtros.get("status"):
        clausulas.append("status = ?")
        params.append(filtros["status"])
    if filtros.get("sku_origem"):
        clausulas.append("sku_origem = ?")
        params.append(filtros["sku_origem"])
    if filtros.get("sku_destino"):
        clausulas.append("sku_destino = ?")
        params.append(filtros["sku_destino"])
    if filtros.get("inicio"):
        clausulas.append("data_retrabalho >= ?")
        params.append(filtros["inicio"])
    if filtros.get("fim"):
        clausulas.append("data_retrabalho <= ?")
        params.append(filtros["fim"])
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q(f"SELECT * FROM retrabalhos WHERE {' AND '.join(clausulas)} ORDER BY id DESC"), params)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def obter_detalhe_retrabalho(rt_id):
    criar_tabelas_retrabalho()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM retrabalhos WHERE id=?"), (rt_id,))
        linha = cursor.fetchone()
        if not linha:
            return None
        rt = dict(linha)
        cursor.execute(q("SELECT * FROM retrabalho_origens WHERE retrabalho_id=? ORDER BY id"), (rt_id,))
        rt["origens"] = [dict(r) for r in cursor.fetchall()]
        cursor.execute(q("SELECT * FROM retrabalho_saidas WHERE retrabalho_id=? ORDER BY id"), (rt_id,))
        rt["saidas"] = [dict(r) for r in cursor.fetchall()]
        cursor.execute(q("SELECT * FROM retrabalho_eventos WHERE retrabalho_id=? ORDER BY id"), (rt_id,))
        rt["eventos"] = [dict(r) for r in cursor.fetchall()]
        return rt
    finally:
        conn.close()


def buscar_origens_elegiveis(sku, unidade_estoque):
    """Reaproveita exatamente o critério oficial de saldo disponível (nunca uma query paralela)."""
    criar_tabelas_retrabalho()
    unidade_estoque = str(unidade_estoque or "").strip().upper()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""
            SELECT cx.*, (
                SELECT MIN(comp.op_id) FROM pa_caixa_composicao comp WHERE comp.caixa_id = cx.id
            ) AS op_id
            FROM pa_caixas cx
            WHERE cx.sku = ? AND cx.unidade_estoque = ? AND cx.condicao='CONFORME'
              AND cx.disponibilidade='DISPONIVEL' AND cx.estoque_operacional=1
            ORDER BY cx.data_validade ASC, cx.id ASC
        """), (sku, unidade_estoque))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
