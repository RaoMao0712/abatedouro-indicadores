"""Pareamento e validação canônica de eventos compensatórios da Expedição."""

import json
from decimal import Decimal

from database import conectar, q, transaction


ORIGENS_COMPATIVEIS = {
    "REMOCAO_RESERVA": ("RESERVA", "ATUALIZACAO_RESERVA"),
    "LIBERACAO_PARCIAL_RESERVA": ("RESERVA", "ATUALIZACAO_RESERVA"),
    "CANCELAMENTO_ROMANEIO": ("RESERVA", "ATUALIZACAO_RESERVA"),
    "ESTORNO_ROMANEIO": ("CONFIRMACAO_ROMANEIO", "VENDA_DIRETA"),
    "ESTORNO_CAIXA_EMBALAGEM": ("FORMACAO_ESTOQUE",),
}

ACOES_COMPENSATORIAS = frozenset(ORIGENS_COMPATIVEIS)


def _decimal(valor):
    return Decimal(str(valor or 0))


def _item_id(observacao):
    try:
        return int(json.loads(observacao or "{}").get("expedicao_item_id"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def localizar_origens_compensaveis_cursor(
    cursor, *, acao, caixa_id, expedicao_id, quantidade, expedicao_item_id=None,
    antes_do_evento_id=None,
):
    """Aloca a compensação em origens compatíveis ainda não compensadas."""
    origens = ORIGENS_COMPATIVEIS.get(acao)
    if not origens:
        raise ValueError(f"A ação {acao} não é compensatória reconhecida.")
    quantidade = abs(_decimal(quantidade))
    if quantidade <= 0:
        raise ValueError("A quantidade compensada deve ser positiva.")
    marcadores = ",".join("?" for _ in origens)
    parametros = [caixa_id, *origens]
    filtro_expedicao = ""
    if acao != "ESTORNO_CAIXA_EMBALAGEM":
        filtro_expedicao = "AND origem.expedicao_id = ?"
        parametros.append(expedicao_id)
    filtro_tempo = ""
    if antes_do_evento_id is not None:
        filtro_tempo = "AND origem.id < ?"
        parametros.append(antes_do_evento_id)
    cursor.execute(q(f"""
        SELECT origem.*,
          COALESCE((SELECT SUM(ABS(comp.quantidade)) FROM estoque_eventos comp
                    WHERE comp.evento_origem_id=origem.id),0) AS quantidade_compensada
        FROM estoque_eventos origem
        WHERE origem.caixa_id=? AND origem.acao IN ({marcadores})
          AND COALESCE(origem.quantidade,0)>0
          {filtro_expedicao} {filtro_tempo}
        ORDER BY origem.id
    """), tuple(parametros))
    restante = quantidade
    alocacoes = []
    for origem in cursor.fetchall():
        origem_item_id = _item_id(origem["observacao"])
        if expedicao_item_id is not None and origem_item_id not in (None, int(expedicao_item_id)):
            continue
        disponivel = _decimal(origem["quantidade"]) - _decimal(origem["quantidade_compensada"])
        if disponivel <= 0:
            continue
        parcela = min(restante, disponivel)
        alocacoes.append((origem, parcela))
        restante -= parcela
        if restante == 0:
            break
    if restante != 0:
        raise ValueError(
            f"A compensação {acao} excede a quantidade original disponível em {restante}."
        )
    return alocacoes


def validar_evento_origem_cursor(cursor, *, evento_origem_id, acao, caixa_id,
                                  expedicao_id, quantidade, expedicao_item_id=None):
    """Valida vínculo explícito sem permitir origem incompatível ou sobrecompensação."""
    cursor.execute(q("SELECT * FROM estoque_eventos WHERE id=?"), (evento_origem_id,))
    origem = cursor.fetchone()
    if not origem:
        raise ValueError("O evento de origem não existe.")
    if origem["acao"] not in ORIGENS_COMPATIVEIS.get(acao, ()):
        raise ValueError("O tipo do evento de origem é incompatível com a compensação.")
    if int(origem["caixa_id"] or 0) != int(caixa_id or 0):
        raise ValueError("O evento de origem pertence a outra posição de estoque.")
    if acao != "ESTORNO_CAIXA_EMBALAGEM" and int(origem["expedicao_id"] or 0) != int(expedicao_id or 0):
        raise ValueError("O evento de origem pertence a outro romaneio.")
    origem_item_id = _item_id(origem["observacao"])
    if expedicao_item_id is not None and origem_item_id not in (None, int(expedicao_item_id)):
        raise ValueError("O evento de origem pertence a outro item operacional.")
    cursor.execute(q("""SELECT COALESCE(SUM(ABS(quantidade)),0) AS total
        FROM estoque_eventos WHERE evento_origem_id=?"""), (evento_origem_id,))
    compensado = _decimal(cursor.fetchone()["total"])
    if compensado + abs(_decimal(quantidade)) > _decimal(origem["quantidade"]):
        raise ValueError("A quantidade compensada excede a quantidade do evento de origem.")
    return origem


def classificar_pareamento_legado_cursor(cursor, evento):
    """Classifica sem escrever; somente um candidato exato é inequívoco."""
    if evento["acao"] not in ACOES_COMPENSATORIAS:
        return "LEGADO_PRE_CANONICO", None
    origens = ORIGENS_COMPATIVEIS[evento["acao"]]
    marcadores = ",".join("?" for _ in origens)
    parametros = [evento["caixa_id"], *origens, evento["id"], abs(_decimal(evento["quantidade"]))]
    filtro_expedicao = ""
    if evento["acao"] != "ESTORNO_CAIXA_EMBALAGEM":
        filtro_expedicao = "AND origem.expedicao_id=?"
        parametros.append(evento["expedicao_id"])
    cursor.execute(q(f"""SELECT origem.id,origem.observacao FROM estoque_eventos origem
        WHERE origem.caixa_id=? AND origem.acao IN ({marcadores})
          AND origem.id<? AND ABS(origem.quantidade)=? {filtro_expedicao}
          AND NOT EXISTS (SELECT 1 FROM estoque_eventos comp
                          WHERE comp.evento_origem_id=origem.id)
        ORDER BY origem.id"""), tuple(parametros))
    evento_item_id = _item_id(evento["observacao"])
    candidatos = [candidato for candidato in cursor.fetchall()
                  if evento_item_id is None or _item_id(candidato["observacao"]) in
                  (None, evento_item_id)]
    if not candidatos:
        return "SEM_ORIGEM_COMPATIVEL", None
    if len(candidatos) != 1:
        return "AMBIGUO", None
    return "PAREAMENTO_INEQUIVOCO", int(candidatos[0]["id"])


def diagnosticar_vinculos_compensatorios():
    """Reconciliação read-only dos vínculos entre compensação e origem."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT * FROM estoque_eventos
            WHERE acao IN (?,?,?,?,?) ORDER BY id"""), tuple(sorted(ACOES_COMPENSATORIAS)))
        eventos = cursor.fetchall()
        resultado = []
        for evento in eventos:
            item = dict(evento)
            origem_id = evento["evento_origem_id"]
            if origem_id is None:
                classificacao, candidato = classificar_pareamento_legado_cursor(cursor, evento)
                item.update(classificacao=classificacao, origem_candidata_id=candidato)
                resultado.append(item)
                continue
            cursor.execute(q("SELECT * FROM estoque_eventos WHERE id=?"), (origem_id,))
            origem = cursor.fetchone()
            divergencias = []
            if not origem:
                divergencias.append("ORIGEM_INEXISTENTE")
            else:
                if origem["acao"] not in ORIGENS_COMPATIVEIS[evento["acao"]]:
                    divergencias.append("TIPO_INCOMPATIVEL")
                if int(origem["caixa_id"] or 0) != int(evento["caixa_id"] or 0):
                    divergencias.append("ENTIDADE_INCOMPATIVEL")
                if evento["acao"] != "ESTORNO_CAIXA_EMBALAGEM" and int(origem["expedicao_id"] or 0) != int(evento["expedicao_id"] or 0):
                    divergencias.append("EXPEDICAO_INCOMPATIVEL")
                cursor.execute(q("""SELECT COALESCE(SUM(ABS(quantidade)),0) AS total
                    FROM estoque_eventos WHERE evento_origem_id=?"""), (origem_id,))
                if _decimal(cursor.fetchone()["total"]) > _decimal(origem["quantidade"]):
                    divergencias.append("QUANTIDADE_COMPENSADA_EXCEDIDA")
            item.update(
                classificacao=(",".join(divergencias) if divergencias else "VINCULO_VALIDO"),
                origem_candidata_id=origem_id,
            )
            resultado.append(item)
        return resultado
    finally:
        conn.close()


def backfill_eventos_origem_inequivocos():
    """Preenche apenas vínculos legados inequívocos, sem alterar outros campos."""
    atualizados = []
    classificacoes = {chave: 0 for chave in (
        "PAREAMENTO_INEQUIVOCO", "AMBIGUO", "SEM_ORIGEM_COMPATIVEL", "LEGADO_PRE_CANONICO"
    )}
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT * FROM estoque_eventos
            WHERE evento_origem_id IS NULL AND acao IN (?,?,?,?,?) ORDER BY id"""),
            tuple(sorted(ACOES_COMPENSATORIAS)))
        for evento in cursor.fetchall():
            classificacao, origem_id = classificar_pareamento_legado_cursor(cursor, evento)
            classificacoes[classificacao] += 1
            if classificacao != "PAREAMENTO_INEQUIVOCO":
                continue
            cursor.execute(q("""UPDATE estoque_eventos SET evento_origem_id=?
                WHERE id=? AND evento_origem_id IS NULL"""), (origem_id, evento["id"]))
            if cursor.rowcount == 1:
                atualizados.append(int(evento["id"]))
    return {"atualizados": len(atualizados), "ids": atualizados,
            "classificacoes": classificacoes}

