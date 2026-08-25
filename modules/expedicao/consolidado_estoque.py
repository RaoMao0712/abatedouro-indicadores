"""Consolidação somente leitura da posição física da Câmara.

Fontes oficiais:

* ``pa_caixas``: posições individualizadas posteriores ao marco zero;
* ``pa_nao_conformes``: inventário legado agregado, preservado por origem;
* ``skus``: identidade oficial do produto (LEG-1 e LEG-2);
* ``galinhas_por_pacote``: apresentação e fator oficial da Galinha Inteira.

Eventos e itens de romaneio são usados somente para reconciliar reservas do
legado. Eles nunca são somados como uma terceira fonte física, evitando dupla
contagem. Tela e PDF devem consumir exclusivamente ``consolidar_estoque_camara``.
"""

from collections import OrderedDict
from datetime import datetime
from decimal import Decimal

from database import DATABASE_URL, conectar, q
from modules.qualidade.liberacoes import (
    APROVADA,
    PENDENTE,
    SKU_INVENTARIO_CODIGO,
    SKU_INVENTARIO_ID,
    SKU_INVENTARIO_NOME,
    TIPO_LEGADO,
    garantir_schema,
)

from .estoque_service import FUSO_MANAUS, criar_tabelas_estoque_confiavel


SITUACOES_CONFORMES = ("disponivel", "reservado")
SITUACOES_BLOQUEADAS = (
    "nao_conforme_bloqueado",
    "reprocessamento",
    "aguardando_liberacao",
)
SITUACOES = SITUACOES_CONFORMES + SITUACOES_BLOQUEADAS

ROTULOS_SITUACOES = {
    "disponivel": "Disponível para expedição",
    "reservado": "Reservado",
    "nao_conforme_bloqueado": "Não conforme bloqueado",
    "reprocessamento": "Em reprocessamento",
    "aguardando_liberacao": "Aguardando liberação",
}

UNIDADES_CORTADA = ("caixas", "bandejas", "peso_kg")
UNIDADES_INTEIRA = ("galinhas", "pacotes")


def _decimal(valor):
    return Decimal(str(valor or 0))


def _inteiro(valor):
    return int(Decimal(str(valor or 0)))


def _vazio(unidades):
    return {
        unidade: Decimal("0") if unidade == "peso_kg" else 0
        for unidade in unidades
    }


def _grupo(chave, produto, apresentacao, unidades, *, produto_id=None,
           sku_codigo=None, fator_aves=None, obrigatorio=False,
           classificado=True):
    return {
        "chave": chave,
        "produto_id": produto_id,
        "sku_codigo": sku_codigo,
        "produto": produto,
        "apresentacao": apresentacao,
        "fator_aves": fator_aves,
        "unidades": list(unidades),
        "obrigatorio": obrigatorio,
        "classificado": classificado,
        "situacoes": {
            situacao: {
                "rotulo": ROTULOS_SITUACOES[situacao],
                "quantidades": _vazio(unidades),
                "origens": set(),
            }
            for situacao in SITUACOES
        },
    }


def _grupos_obrigatorios(catalogo):
    por_codigo = {str(item["codigo"] or "").strip().upper(): item for item in catalogo}
    cortada = por_codigo.get(SKU_INVENTARIO_CODIGO)
    inteira = por_codigo.get("LEG-2")
    return OrderedDict((grupo["chave"], grupo) for grupo in (
        _grupo(
            "galinha_cortada", "Galinha Cortada", "Congelada",
            UNIDADES_CORTADA, produto_id=(cortada or {}).get("id", SKU_INVENTARIO_ID),
            sku_codigo=(cortada or {}).get("codigo", SKU_INVENTARIO_CODIGO),
            obrigatorio=True,
        ),
        _grupo(
            "galinha_inteira_v1", "Galinha Inteira", "Pacote com 1 ave",
            UNIDADES_INTEIRA, produto_id=(inteira or {}).get("id"),
            sku_codigo=(inteira or {}).get("codigo", "LEG-2"), fator_aves=1,
            obrigatorio=True,
        ),
        _grupo(
            "galinha_inteira_v2", "Galinha Inteira", "Pacote com 2 aves",
            UNIDADES_INTEIRA, produto_id=(inteira or {}).get("id"),
            sku_codigo=(inteira or {}).get("codigo", "LEG-2"), fator_aves=2,
            obrigatorio=True,
        ),
    ))


def _catalogo(cursor):
    try:
        cursor.execute("""SELECT id,codigo,nome FROM skus
            WHERE COALESCE(ativo,'Sim')='Sim' AND excluido_em IS NULL ORDER BY id""")
    except Exception as erro:
        # Instalações antigas e bancos mínimos de homologação podem ainda não
        # possuir o catálogo. Os três grupos oficiais continuam obrigatórios e
        # as posições ficam explicitamente não classificadas, sem inferência.
        if "no such table: skus" in str(erro).lower():
            return []
        raise
    return [dict(linha) for linha in cursor.fetchall()]


def _produto_oficial(catalogo, sku_armazenado):
    chave = str(sku_armazenado or "").strip().casefold()
    candidatos = [
        item for item in catalogo
        if chave in {
            str(item.get("codigo") or "").strip().casefold(),
            str(item.get("nome") or "").strip().casefold(),
        }
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def _classificar_posicao(grupos, catalogo, linha):
    produto = _produto_oficial(catalogo, linha.get("sku"))
    codigo = str((produto or {}).get("codigo") or "").strip().upper()
    unidade = str(linha.get("unidade_estoque") or "CAIXA").strip().upper()
    fator = _inteiro(linha.get("galinhas_por_pacote")) or None
    if codigo == SKU_INVENTARIO_CODIGO and unidade != "PACOTE":
        return grupos["galinha_cortada"]
    if codigo == "LEG-2" and unidade == "PACOTE" and fator in {1, 2}:
        return grupos[f"galinha_inteira_v{fator}"]

    unidades = UNIDADES_INTEIRA if unidade == "PACOTE" else UNIDADES_CORTADA
    identidade = (produto or {}).get("id") or str(linha.get("sku") or "sem-sku").strip()
    apresentacao = str(linha.get("apresentacao") or "Apresentação não classificada").strip()
    chave = f"nao_classificado:{identidade}:{apresentacao.casefold()}:{unidade}:{fator or 0}"
    if chave not in grupos:
        grupos[chave] = _grupo(
            chave,
            (produto or {}).get("nome") or str(linha.get("sku") or "Produto não classificado"),
            apresentacao or "Apresentação não classificada",
            unidades,
            produto_id=(produto or {}).get("id"),
            sku_codigo=(produto or {}).get("codigo"),
            fator_aves=fator,
            classificado=False,
        )
    return grupos[chave]


def _situacao_pos_marco(linha):
    condicao = str(linha.get("condicao") or "").upper()
    disponibilidade = str(linha.get("disponibilidade") or "").upper()
    if _inteiro(linha.get("liberacao_pendente")):
        return "aguardando_liberacao"
    if condicao == "CONFORME" and disponibilidade in {"DISPONIVEL", "RESERVADO"}:
        return disponibilidade.lower()
    if disponibilidade == "REPROCESSAMENTO":
        return "reprocessamento"
    if condicao == "NAO_CONFORME" or disponibilidade == "BLOQUEADO":
        return "nao_conforme_bloqueado"
    return "aguardando_liberacao"


def _somar(grupo, situacao, valores, origem):
    destino = grupo["situacoes"][situacao]
    for unidade in grupo["unidades"]:
        destino["quantidades"][unidade] += valores.get(unidade, 0)
    destino["origens"].add(origem)


def _somar_pos_marco(grupos, catalogo, linhas, alertas):
    for linha in linhas:
        grupo = _classificar_posicao(grupos, catalogo, linha)
        unidade = str(linha.get("unidade_estoque") or "CAIXA").upper()
        origem = "Pós-marco-zero"
        if unidade == "PACOTE":
            pacotes = max(0, _inteiro(linha.get("pacotes")))
            reservados = min(pacotes, max(0, _inteiro(linha.get("pacotes_reservados"))))
            fator = _inteiro(linha.get("galinhas_por_pacote"))
            aves_oficiais = max(0, _inteiro(linha.get("galinhas")))
            aves_esperadas = pacotes * fator if fator else 0
            if aves_oficiais and fator and aves_oficiais != aves_esperadas:
                alertas.append(
                    f"{linha.get('sku') or '-'} / {linha.get('apresentacao') or '-'}: "
                    f"{aves_oficiais} aves oficiais divergem de {aves_esperadas} pelo fator configurado."
                )
            aves_total = aves_oficiais if aves_oficiais else aves_esperadas
            situacao = _situacao_pos_marco(linha)
            if situacao in SITUACOES_CONFORMES:
                if situacao == "reservado" and reservados == 0:
                    reservados = pacotes
                aves_reservadas = min(aves_total, reservados * fator) if fator else 0
                _somar(grupo, "reservado", {
                    "pacotes": reservados, "galinhas": aves_reservadas,
                }, origem)
                _somar(grupo, "disponivel", {
                    "pacotes": pacotes - reservados,
                    "galinhas": aves_total - aves_reservadas,
                }, origem)
            else:
                _somar(grupo, situacao, {
                    "pacotes": pacotes, "galinhas": aves_total,
                }, origem)
            continue

        situacao = _situacao_pos_marco(linha)
        _somar(grupo, situacao, {
            "caixas": max(0, _inteiro(linha.get("caixas"))),
            "bandejas": max(0, _inteiro(linha.get("bandejas"))),
            "peso_kg": max(Decimal("0"), _decimal(linha.get("peso_kg"))),
        }, origem)


def _somar_legado(grupos, linhas):
    grupo = grupos["galinha_cortada"]
    origem = "Inventário legado"
    for linha in linhas:
        pendente_peso = max(0, _inteiro(linha.get("saldo_pendente_g")))
        bloqueado_peso = max(0, _inteiro(linha.get("saldo_bloqueado_g")) - pendente_peso)
        pendente_caixas = min(
            max(0, _inteiro(linha.get("caixas_bloqueadas"))),
            max(0, _inteiro(linha.get("pendente_caixas"))),
        )
        pendente_bandejas = min(
            max(0, _inteiro(linha.get("bandejas_bloqueadas"))),
            max(0, _inteiro(linha.get("pendente_bandejas"))),
        )
        bloqueado_caixas = max(0, _inteiro(linha.get("caixas_bloqueadas")) - pendente_caixas)
        bloqueado_bandejas = max(0, _inteiro(linha.get("bandejas_bloqueadas")) - pendente_bandejas)

        if str(linha.get("condicao_inicial") or "").upper() == "CONFORME_AGUARDANDO_LIBERACAO":
            pendente_peso += bloqueado_peso
            pendente_caixas += bloqueado_caixas
            pendente_bandejas += bloqueado_bandejas
            bloqueado_peso = bloqueado_caixas = bloqueado_bandejas = 0

        _somar(grupo, "nao_conforme_bloqueado", {
            "caixas": bloqueado_caixas,
            "bandejas": bloqueado_bandejas,
            "peso_kg": Decimal(bloqueado_peso) / Decimal(1000),
        }, origem)
        _somar(grupo, "aguardando_liberacao", {
            "caixas": pendente_caixas,
            "bandejas": pendente_bandejas,
            "peso_kg": Decimal(pendente_peso) / Decimal(1000),
        }, origem)

        reservadas_caixas = max(0, _inteiro(linha.get("reservadas_caixas")))
        reservadas_bandejas = max(0, _inteiro(linha.get("reservadas_bandejas")))
        aprovadas_caixas = max(0, _inteiro(linha.get("aprovadas_caixas")))
        aprovadas_bandejas = max(0, _inteiro(linha.get("aprovadas_bandejas")))
        destinadas_caixas = max(0, _inteiro(linha.get("destinadas_caixas")))
        destinadas_bandejas = max(0, _inteiro(linha.get("destinadas_bandejas")))
        disponiveis_caixas = max(0, aprovadas_caixas - reservadas_caixas - destinadas_caixas)
        disponiveis_bandejas = max(0, aprovadas_bandejas - reservadas_bandejas - destinadas_bandejas)
        _somar(grupo, "disponivel", {
            "caixas": disponiveis_caixas,
            "bandejas": disponiveis_bandejas,
            "peso_kg": Decimal(max(0, _inteiro(linha.get("saldo_operacional_g")))) / Decimal(1000),
        }, origem)
        _somar(grupo, "reservado", {
            "caixas": reservadas_caixas,
            "bandejas": reservadas_bandejas,
            "peso_kg": Decimal(max(0, _inteiro(linha.get("saldo_reservado_operacional_g")))) / Decimal(1000),
        }, origem)


def _linhas_pos_marco(cursor):
    cursor.execute(q("""SELECT
            cx.sku,cx.apresentacao,cx.unidade_estoque,cx.galinhas_por_pacote,
            cx.condicao,cx.disponibilidade,COALESCE(lp.liberacao_pendente,0) AS liberacao_pendente,
            COUNT(*) AS caixas,
            COALESCE(SUM(cx.quantidade_bandejas),0) AS bandejas,
            COALESCE(SUM(cx.peso_liquido),0) AS peso_kg,
            COALESCE(SUM(cx.quantidade_pacotes),0) AS pacotes,
            COALESCE(SUM(cx.quantidade_galinhas),0) AS galinhas,
            COALESCE(SUM(cx.quantidade_pacotes_reservados),0) AS pacotes_reservados
        FROM pa_caixas cx
        LEFT JOIN (
            SELECT nc.caixa_id,1 AS liberacao_pendente
            FROM pa_nao_conformes nc
            JOIN pa_nao_conforme_solicitacoes s ON s.pa_nao_conforme_id=nc.id
            WHERE nc.caixa_id IS NOT NULL AND s.status=?
            GROUP BY nc.caixa_id
        ) lp ON lp.caixa_id=cx.id
        WHERE COALESCE(cx.estoque_operacional,0)=1
          AND UPPER(COALESCE(cx.disponibilidade,'')) NOT IN
              ('TRANSFERIDO','EXPEDIDO','DESCARTADO','DEVOLVIDO','CANCELADO','ESTORNADO')
          AND UPPER(COALESCE(cx.status,'')) NOT IN ('CANCELADO','ESTORNADO')
          AND (
              (UPPER(COALESCE(cx.unidade_estoque,'CAIXA'))='PACOTE'
               AND COALESCE(cx.quantidade_pacotes,0)>0)
              OR
              (UPPER(COALESCE(cx.unidade_estoque,'CAIXA'))<>'PACOTE'
               AND (COALESCE(cx.quantidade_bandejas,0)>0 OR COALESCE(cx.peso_liquido,0)>0))
          )
        GROUP BY cx.sku,cx.apresentacao,cx.unidade_estoque,cx.galinhas_por_pacote,
                 cx.condicao,cx.disponibilidade,lp.liberacao_pendente
        ORDER BY cx.sku,cx.apresentacao,cx.condicao,cx.disponibilidade"""),
        (PENDENTE,))
    return [dict(linha) for linha in cursor.fetchall()]


def _linhas_legado(cursor):
    if DATABASE_URL:
        cursor.execute("""SELECT 1 FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='expedicao_itens'
              AND column_name='ativo'""")
        possui_ativo = bool(cursor.fetchone())
    else:
        cursor.execute("PRAGMA table_info(expedicao_itens)")
        possui_ativo = any(linha[1] == "ativo" for linha in cursor.fetchall())
    filtro_ativo = "AND COALESCE(i.ativo,1)=1" if possui_ativo else ""
    cursor.execute(q(f"""SELECT nc.*,
            COALESCE(p.pendente_caixas,0) AS pendente_caixas,
            COALESCE(p.pendente_bandejas,0) AS pendente_bandejas,
            COALESCE(a.aprovadas_caixas,0) AS aprovadas_caixas,
            COALESCE(a.aprovadas_bandejas,0) AS aprovadas_bandejas,
            COALESCE(m.reservadas_caixas,0) AS reservadas_caixas,
            COALESCE(m.reservadas_bandejas,0) AS reservadas_bandejas,
            COALESCE(m.destinadas_caixas,0) AS destinadas_caixas,
            COALESCE(m.destinadas_bandejas,0) AS destinadas_bandejas
        FROM pa_nao_conformes nc
        LEFT JOIN (
            SELECT pa_nao_conforme_id,SUM(caixas) AS pendente_caixas,
                   SUM(bandejas) AS pendente_bandejas
            FROM pa_nao_conforme_solicitacoes WHERE status=?
            GROUP BY pa_nao_conforme_id
        ) p ON p.pa_nao_conforme_id=nc.id
        LEFT JOIN (
            SELECT pa_nao_conforme_id,SUM(caixas) AS aprovadas_caixas,
                   SUM(bandejas) AS aprovadas_bandejas
            FROM pa_nao_conforme_solicitacoes WHERE status=?
            GROUP BY pa_nao_conforme_id
        ) a ON a.pa_nao_conforme_id=nc.id
        LEFT JOIN (
            SELECT i.pa_nao_conforme_id,
                SUM(CASE WHEN e.status='Aberto' THEN COALESCE(i.quantidade_caixas,0) ELSE 0 END) AS reservadas_caixas,
                SUM(CASE WHEN e.status='Aberto' THEN COALESCE(i.quantidade_bandejas,0) ELSE 0 END) AS reservadas_bandejas,
                SUM(CASE WHEN e.status='Concluído' THEN COALESCE(i.quantidade_caixas,0) ELSE 0 END) AS destinadas_caixas,
                SUM(CASE WHEN e.status='Concluído' THEN COALESCE(i.quantidade_bandejas,0) ELSE 0 END) AS destinadas_bandejas
            FROM expedicao_itens i JOIN expedicoes e ON e.id=i.expedicao_id
            WHERE i.pa_nao_conforme_id IS NOT NULL
              {filtro_ativo}
              AND e.status IN ('Aberto','Concluído')
            GROUP BY i.pa_nao_conforme_id
        ) m ON m.pa_nao_conforme_id=nc.id
        WHERE nc.tipo_registro=?
          AND (COALESCE(nc.saldo_bloqueado_g,0)+COALESCE(nc.saldo_operacional_g,0)
               +COALESCE(nc.saldo_reservado_operacional_g,0))>0
        ORDER BY nc.id"""), (PENDENTE, APROVADA, TIPO_LEGADO))
    return [dict(linha) for linha in cursor.fetchall()]


def _finalizar(grupos, incluir_nao_conforme):
    totais_gerais = {}
    for grupo in grupos.values():
        for situacao in SITUACOES:
            item = grupo["situacoes"][situacao]
            item["origens"] = sorted(item["origens"])
            if not incluir_nao_conforme and situacao in SITUACOES_BLOQUEADAS:
                item["quantidades"] = _vazio(grupo["unidades"])
                item["origens"] = []
        grupo["total_conforme"] = _vazio(grupo["unidades"])
        grupo["total_bloqueado"] = _vazio(grupo["unidades"])
        grupo["total_fisico"] = _vazio(grupo["unidades"])
        for unidade in grupo["unidades"]:
            conforme = sum(
                grupo["situacoes"][situacao]["quantidades"][unidade]
                for situacao in SITUACOES_CONFORMES
            )
            bloqueado = sum(
                grupo["situacoes"][situacao]["quantidades"][unidade]
                for situacao in SITUACOES_BLOQUEADAS
            )
            grupo["total_conforme"][unidade] = conforme
            grupo["total_bloqueado"][unidade] = bloqueado
            grupo["total_fisico"][unidade] = conforme + bloqueado
            totais_gerais[unidade] = totais_gerais.get(unidade, 0) + conforme + bloqueado
    return list(grupos.values()), totais_gerais


def consolidar_estoque_camara(*, incluir_nao_conforme=True):
    """Retorna uma fotografia consolidada sem criar eventos ou movimentações."""
    if not isinstance(incluir_nao_conforme, bool):
        raise ValueError("A opção de estoque não conforme deve ser booleana.")
    criar_tabelas_estoque_confiavel()
    garantir_schema(criar_local=False)
    conn = conectar()
    try:
        cursor = conn.cursor()
        catalogo = _catalogo(cursor)
        grupos = _grupos_obrigatorios(catalogo)
        alertas = []
        _somar_pos_marco(grupos, catalogo, _linhas_pos_marco(cursor), alertas)
        _somar_legado(grupos, _linhas_legado(cursor))
        grupos_final, totais_gerais = _finalizar(grupos, incluir_nao_conforme)
        gerado_em = datetime.now(FUSO_MANAUS)
        return {
            "gerado_em": gerado_em,
            "gerado_em_formatado": gerado_em.strftime("%d/%m/%Y às %H:%M"),
            "fuso_horario": "America/Manaus",
            "incluir_nao_conforme": incluir_nao_conforme,
            "grupos": grupos_final,
            "totais_gerais_por_unidade": totais_gerais,
            "alertas_tecnicos": alertas,
        }
    finally:
        conn.close()
