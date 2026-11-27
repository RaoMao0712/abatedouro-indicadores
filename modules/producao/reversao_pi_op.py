"""Compensação do saldo por linhagem de movimento PI, na transação do chamador."""

from collections import defaultdict
from decimal import Decimal

from database import DATABASE_URL, q


ORIGENS = {
    "ENTRADA_OP": 1, "ENTRADA_EMBALAGEM_PRIMARIA": 1,
    "SAIDA_EMBALAGEM_SECUNDARIA": -1, "SAIDA_FORMACAO_PA_PRIMARIA": -1,
}
COMPENSACOES = {
    "ENTRADA_ESTORNO_CAIXA": 1, "ENTRADA_REVERSAO_ESTORNO_OP": 1,
    "ENTRADA_REPROCESSAMENTO_PI": 1,
    "SAIDA_ESTORNO_OP": -1, "SAIDA_REVERSAO_EMBALAGEM_PRIMARIA": -1,
    "SAIDA_REPROCESSAMENTO_PI": -1,
}


def planejar_compensacoes_pi_cursor(cursor, op_id, *, bloquear=False):
    sql = """SELECT id,tipo,sku,quantidade_bandejas,caixa_id,movimento_origem_id
        FROM estoque_produto_intermediario WHERE op_id=? ORDER BY id"""
    if bloquear and DATABASE_URL:
        sql += " FOR UPDATE"
    cursor.execute(q(sql), (op_id,))
    movimentos = {linha["id"]: dict(linha) for linha in cursor.fetchall()}
    raizes = {}
    saldos = defaultdict(Decimal)
    for identificador, movimento in movimentos.items():
        tipo = movimento["tipo"]
        origem_id = movimento["movimento_origem_id"]
        quantidade = Decimal(str(movimento["quantidade_bandejas"]))
        if not quantidade.is_finite() or quantidade < 0:
            raise ValueError(f"PI #{identificador}: quantidade inválida.")
        if origem_id is None and tipo in ORIGENS:
            raiz = identificador
            sinal = ORIGENS[tipo]
        elif origem_id in raizes and tipo in COMPENSACOES:
            if movimento["sku"] != movimentos[origem_id]["sku"]:
                raise ValueError(f"PI #{identificador}: SKU difere do movimento de origem #{origem_id}.")
            raiz = raizes[origem_id]
            sinal = COMPENSACOES[tipo]
        else:
            raise ValueError(f"PI #{identificador} ({tipo}): origem #{origem_id} não conciliada na OP #{op_id}.")
        raizes[identificador] = raiz
        saldos[raiz] += quantidade * sinal

    plano = []
    for raiz, saldo in saldos.items():
        movimento = movimentos[raiz]
        original = Decimal(str(movimento["quantidade_bandejas"])) * ORIGENS[movimento["tipo"]]
        if (saldo > 0 > original or saldo < 0 < original or abs(saldo) > abs(original)):
            raise ValueError(f"PI #{raiz}: saldo residual {saldo} incompatível com a origem {original}.")
        if not saldo:
            continue
        if saldo < 0:
            tipo = "ENTRADA_REPROCESSAMENTO_PI"
        elif movimento["tipo"] == "ENTRADA_EMBALAGEM_PRIMARIA":
            tipo = "SAIDA_REVERSAO_EMBALAGEM_PRIMARIA"
        else:
            tipo = "SAIDA_REPROCESSAMENTO_PI"
        plano.append({
            "origem_id": raiz, "tipo": tipo, "sku": movimento["sku"],
            "caixa_id": movimento["caixa_id"], "quantidade": str(abs(saldo)),
        })
    return plano


def compensar_pi_cursor(cursor, op_id, *, plano, operacao_id, agora):
    atual = planejar_compensacoes_pi_cursor(cursor, op_id, bloquear=True)
    if atual != plano:
        raise ValueError("As consequências de PI mudaram desde a análise.")
    for item in atual:
        cursor.execute(q("""INSERT INTO estoque_produto_intermediario (
            op_id,tipo,sku,quantidade_bandejas,caixa_id,movimento_origem_id,
            data_movimentacao,origem,observacoes,idempotency_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?)"""), (
            op_id, item["tipo"], item["sku"], item["quantidade"], item["caixa_id"],
            item["origem_id"], agora[:10], "Reprocessamento da OP",
            f"Compensação do movimento PI #{item['origem_id']}.",
            f"{operacao_id}:PI:{item['origem_id']}",
        ))
    if planejar_compensacoes_pi_cursor(cursor, op_id, bloquear=True):
        raise RuntimeError("A compensação não neutralizou todas as origens de PI.")
