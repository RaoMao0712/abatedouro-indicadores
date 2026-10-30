"""Diagnostico consultivo de integridade operacional (somente leitura).

Reaproveita as fontes ja homologadas (``pa_caixas``, ``pa_nao_conformes``,
``expedicoes``/``expedicao_itens``, ``pnc_*_descarte`` e ``cmv_*``) e apenas
compara valores ja gravados. Nenhum saldo e recalculado e nenhum vinculo e
inferido: cada regra declara exatamente quais campos confronta.

Nao chama ``criar_tabelas_*`` nem qualquer DDL. A conexao e aberta em modo
somente leitura (``PRAGMA query_only`` no SQLite, ``SET TRANSACTION READ ONLY``
no PostgreSQL) e sempre encerrada com rollback.
"""

from decimal import Decimal

from database import DATABASE_URL, conectar, q


CATEGORIAS = {
    "saldo_negativo": "Saldos negativos",
    "expedicao_duplicada": "Expedicoes duplicadas",
    "divergencia_quantidade": "Divergencias de quantidades",
    "venda_sem_cmv": "Vendas sem apropriacao de CMV",
}

# Vinculo CMV x romaneio: o modulo de expedicao nao grava eventos de CMV na
# conclusao da venda. Um evento so e reconhecido quando ja traz, de forma
# explicita, o id do romaneio em ``origem_id`` com uma destas origens, ou o
# numero do romaneio em ``documento``. Nada alem disso e inferido.
ORIGENS_CMV_ROMANEIO = ("ROMANEIO", "EXPEDICAO", "VENDA_DIRETA")

LIMITACOES = [
    "Relatorio consultivo: nenhuma correcao e aplicada; apenas valores gravados sao comparados.",
    "Vendas sem CMV: a conclusao de romaneio de Venda Direta nao grava evento de CMV no codigo atual. "
    "Venda sem vinculo rastreavel e listada como 'Nao avaliavel' (fora da contagem de achados). So e achado quando "
    "existe vinculo explicito (cmv_eventos.origem_id = id do romaneio, origem ROMANEIO/EXPEDICAO/VENDA_DIRETA) e a venda "
    "e do mesmo dia ou posterior ao primeiro evento assim vinculado.",
    "Nao ha vinculo fisico entre romaneio de venda e camada CMV (cmv_camadas): a cobertura e verificada somente ao nivel do evento.",
    "Pacotes (PACOTE) podem aparecer em varios romaneios por serem baixa parcial; a duplicidade so e avaliada para caixas inteiras.",
    "Tabelas ausentes no banco consultado sao ignoradas e listadas em 'Fontes nao avaliadas'.",
]


def _numero(valor):
    try:
        return Decimal(str(valor if valor is not None else 0))
    except Exception:
        return Decimal("0")


def _achado(categoria, regra, origem, registro_id, referencia, comparados, descricao):
    return {
        "categoria": categoria,
        "categoria_rotulo": CATEGORIAS[categoria],
        "regra": regra,
        "origem": origem,
        "registro_id": registro_id,
        "referencia": referencia or "-",
        "comparados": comparados,
        "descricao": descricao,
    }


def _tabela_existe(cursor, nome):
    if DATABASE_URL:
        cursor.execute(q("""SELECT 1 FROM information_schema.tables
            WHERE table_schema=current_schema() AND table_name=?"""), (nome,))
    else:
        cursor.execute(q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?"), (nome,))
    return bool(cursor.fetchone())


def _colunas(cursor, nome):
    if DATABASE_URL:
        cursor.execute(q("""SELECT column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name=?"""), (nome,))
        return {linha[0] if not isinstance(linha, dict) else linha["column_name"] for linha in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({nome})")
    return {linha[1] for linha in cursor.fetchall()}


def _consultar(cursor, sql, parametros=()):
    cursor.execute(q(sql), tuple(parametros))
    return [dict(linha) for linha in cursor.fetchall()]


def _exige(cursor, nao_avaliadas, tabela, colunas=()):
    """True quando a tabela (e colunas) existem; senao registra a limitacao."""
    if not _tabela_existe(cursor, tabela):
        nao_avaliadas.append(f"{tabela} (tabela ausente)")
        return False
    faltantes = [c for c in colunas if c not in _colunas(cursor, tabela)]
    if faltantes:
        nao_avaliadas.append(f"{tabela} (colunas ausentes: {', '.join(faltantes)})")
        return False
    return True


# --------------------------------------------------------------------------
# Regras
# --------------------------------------------------------------------------

def _saldos_negativos(cursor, nao_avaliadas):
    achados = []
    campos_caixa = ("quantidade_pacotes", "quantidade_galinhas", "quantidade_pacotes_reservados",
                    "quantidade_bandejas", "peso_liquido")
    if _exige(cursor, nao_avaliadas, "pa_caixas", ("id", "codigo_caixa") + campos_caixa):
        condicao = " OR ".join(f"COALESCE({c},0)<0" for c in campos_caixa)
        for linha in _consultar(cursor, f"SELECT * FROM pa_caixas WHERE {condicao} ORDER BY id"):
            for campo in campos_caixa:
                if _numero(linha.get(campo)) < 0:
                    achados.append(_achado(
                        "saldo_negativo", f"pa_caixas.{campo} < 0", "pa_caixas", linha["id"],
                        linha.get("codigo_caixa"), [(campo, linha.get(campo)), ("limite minimo", 0)],
                        f"Caixa {linha.get('codigo_caixa')} com {campo} negativo.",
                    ))
    campos_pnc = ("saldo_bloqueado_g", "saldo_pendente_g", "saldo_operacional_g",
                  "saldo_reservado_operacional_g", "saldo_destinado_g")
    if _exige(cursor, nao_avaliadas, "pa_nao_conformes", ("id", "numero") + campos_pnc):
        condicao = " OR ".join(f"COALESCE({c},0)<0" for c in campos_pnc)
        for linha in _consultar(cursor, f"SELECT * FROM pa_nao_conformes WHERE {condicao} ORDER BY id"):
            for campo in campos_pnc:
                if _numero(linha.get(campo)) < 0:
                    achados.append(_achado(
                        "saldo_negativo", f"pa_nao_conformes.{campo} < 0", "pa_nao_conformes", linha["id"],
                        linha.get("numero"), [(campo, linha.get(campo)), ("limite minimo", 0)],
                        f"PNC {linha.get('numero')} com {campo} negativo.",
                    ))
    if _exige(cursor, nao_avaliadas, "cmv_camadas", ("id", "quantidade_disponivel")):
        for linha in _consultar(cursor, "SELECT * FROM cmv_camadas WHERE COALESCE(quantidade_disponivel,0)<0 ORDER BY id"):
            achados.append(_achado(
                "saldo_negativo", "cmv_camadas.quantidade_disponivel < 0", "cmv_camadas", linha["id"],
                linha.get("documento") or linha.get("produto"),
                [("quantidade_disponivel", linha["quantidade_disponivel"]), ("limite minimo", 0)],
                f"Camada CMV de {linha.get('produto')} com saldo disponivel negativo.",
            ))
    return achados


def _expedicoes_duplicadas(cursor, nao_avaliadas):
    achados = []
    if _exige(cursor, nao_avaliadas, "expedicao_itens", ("id", "expedicao_id", "caixa_id", "ativo", "unidade_estoque")) \
            and _exige(cursor, nao_avaliadas, "expedicoes", ("id", "numero_romaneio", "status")):
        itens = _consultar(cursor, """
            SELECT i.id AS item_id, i.caixa_id, i.expedicao_id, e.numero_romaneio, e.status,
                   cx.codigo_caixa, cx.unidade_estoque
            FROM expedicao_itens i
            JOIN expedicoes e ON e.id = i.expedicao_id
            LEFT JOIN pa_caixas cx ON cx.id = i.caixa_id
            WHERE COALESCE(i.ativo,1)=1 AND i.caixa_id IS NOT NULL
              AND e.status IN ('Aberto','Concluído')
              AND UPPER(COALESCE(cx.unidade_estoque, i.unidade_estoque, 'CAIXA')) <> 'PACOTE'
            ORDER BY i.caixa_id, i.id""")
        por_caixa = {}
        for item in itens:
            por_caixa.setdefault(item["caixa_id"], []).append(item)
        for caixa_id, lista in por_caixa.items():
            if len(lista) < 2:
                continue
            romaneios = ", ".join(f"{i['numero_romaneio']} (item {i['item_id']}, {i['status']})" for i in lista)
            achados.append(_achado(
                "expedicao_duplicada", "caixa inteira em mais de um item ativo de romaneio",
                "expedicao_itens", caixa_id, lista[0].get("codigo_caixa") or f"caixa {caixa_id}",
                [("itens ativos", len(lista)), ("esperado", 1)],
                f"Caixa {lista[0].get('codigo_caixa') or caixa_id} presente em {len(lista)} itens ativos: {romaneios}.",
            ))
    if _exige(cursor, nao_avaliadas, "cmv_eventos",
              ("id", "tipo", "origem_tipo", "origem_id", "evento_original_id")):
        eventos = _consultar(cursor, """
            SELECT ev.* FROM cmv_eventos ev
            WHERE ev.tipo IN ('VENDA','DESCARTE','RETRABALHO') AND ev.origem_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM cmv_eventos es
                              WHERE es.evento_original_id = ev.id AND es.tipo IN ('ESTORNO_VENDA','ESTORNO_RETRABALHO','ESTORNO_DESCARTE'))
            ORDER BY ev.id""")
        grupos = {}
        for ev in eventos:
            grupos.setdefault((ev["tipo"], ev["origem_tipo"], ev["origem_id"], ev["produto"]), []).append(ev)
        for (tipo, origem_tipo, origem_id, _produto), lista in grupos.items():
            if len(lista) > 1:
                ids = ", ".join(str(e["id"]) for e in lista)
                achados.append(_achado(
                    "expedicao_duplicada", "mais de um evento CMV ativo para a mesma origem",
                    "cmv_eventos", lista[0]["id"], f"{origem_tipo}:{origem_id}",
                    [("eventos ativos", len(lista)), ("esperado", 1)],
                    f"Evento {tipo} duplicado para {origem_tipo} {origem_id} (eventos {ids}) sem estorno.",
                ))
    return achados


def _divergencias_quantidade(cursor, nao_avaliadas):
    achados = []
    if _exige(cursor, nao_avaliadas, "pa_caixas",
              ("id", "codigo_caixa", "unidade_estoque", "quantidade_pacotes", "quantidade_galinhas",
               "galinhas_por_pacote", "quantidade_pacotes_reservados", "disponibilidade",
               "reservado_expedicao_id")):
        for linha in _consultar(cursor, """
                SELECT * FROM pa_caixas
                WHERE UPPER(COALESCE(unidade_estoque,'CAIXA'))='PACOTE' ORDER BY id"""):
            pacotes = _numero(linha["quantidade_pacotes"])
            reservados = _numero(linha["quantidade_pacotes_reservados"])
            gpp = _numero(linha["galinhas_por_pacote"])
            galinhas = _numero(linha["quantidade_galinhas"])
            if reservados > pacotes and pacotes >= 0:
                achados.append(_achado(
                    "divergencia_quantidade", "pacotes reservados > pacotes em estoque", "pa_caixas",
                    linha["id"], linha.get("codigo_caixa"),
                    [("quantidade_pacotes_reservados", reservados), ("quantidade_pacotes", pacotes)],
                    "Reserva de pacotes excede o saldo de pacotes da posicao.",
                ))
            if gpp > 0 and galinhas != pacotes * gpp:
                achados.append(_achado(
                    "divergencia_quantidade", "quantidade_galinhas <> pacotes x galinhas_por_pacote", "pa_caixas",
                    linha["id"], linha.get("codigo_caixa"),
                    [("quantidade_galinhas", galinhas), ("pacotes x galinhas_por_pacote", pacotes * gpp)],
                    "Aves registradas nao conferem com pacotes multiplicados pelo fator de aves por pacote.",
                ))
        reservadas = _consultar(cursor, """
            SELECT cx.id, cx.codigo_caixa, cx.reservado_expedicao_id, cx.unidade_estoque,
                   cx.quantidade_pacotes_reservados, e.status AS status_romaneio, e.numero_romaneio
            FROM pa_caixas cx LEFT JOIN expedicoes e ON e.id = cx.reservado_expedicao_id
            WHERE UPPER(COALESCE(cx.disponibilidade,''))='RESERVADO' ORDER BY cx.id""") \
            if _tabela_existe(cursor, "expedicoes") else []
        for linha in reservadas:
            if linha["reservado_expedicao_id"] is None:
                if str(linha.get("unidade_estoque") or "").upper() != "PACOTE":
                    achados.append(_achado(
                        "divergencia_quantidade", "caixa RESERVADO sem romaneio de reserva", "pa_caixas",
                        linha["id"], linha.get("codigo_caixa"),
                        [("disponibilidade", "RESERVADO"), ("reservado_expedicao_id", None)],
                        "Caixa marcada como reservada sem romaneio vinculado.",
                    ))
            elif linha["status_romaneio"] != "Aberto":
                achados.append(_achado(
                    "divergencia_quantidade", "reserva aponta romaneio que nao esta Aberto", "pa_caixas",
                    linha["id"], linha.get("codigo_caixa"),
                    [("reservado_expedicao_id", linha["reservado_expedicao_id"]),
                     ("status do romaneio", linha["status_romaneio"] or "inexistente")],
                    "Caixa reservada para romaneio inexistente, concluido, cancelado ou estornado.",
                ))
    achados += _divergencias_descarte(cursor, nao_avaliadas)
    achados += _divergencias_cmv(cursor, nao_avaliadas)
    return achados


def _divergencias_descarte(cursor, nao_avaliadas):
    achados = []
    if not (_exige(cursor, nao_avaliadas, "pnc_romaneios_descarte", ("id", "numero", "status"))
            and _exige(cursor, nao_avaliadas, "pnc_romaneio_descarte_itens", ("romaneio_id",))
            and _exige(cursor, nao_avaliadas, "pnc_movimentos_descarte", ("romaneio_id", "tipo"))):
        return achados
    campos = ("caixas", "bandejas", "galinhas", "pacotes", "peso_g")
    for rom in _consultar(cursor, "SELECT * FROM pnc_romaneios_descarte WHERE status='CONFIRMADO' ORDER BY id"):
        itens = _consultar(cursor, "SELECT * FROM pnc_romaneio_descarte_itens WHERE romaneio_id=?", (rom["id"],))
        movs = _consultar(cursor, """SELECT * FROM pnc_movimentos_descarte
            WHERE romaneio_id=? AND tipo='SAIDA_DESCARTE_PNC'""", (rom["id"],))
        if not itens or not movs:
            achados.append(_achado(
                "divergencia_quantidade", "descarte confirmado sem item ou sem movimento de saida",
                "pnc_romaneios_descarte", rom["id"], rom.get("numero"),
                [("itens", len(itens)), ("movimentos SAIDA_DESCARTE_PNC", len(movs))],
                "Romaneio de descarte confirmado sem a contrapartida de item/movimento.",
            ))
            continue
        for campo in campos:
            soma_item = sum(_numero(i.get(campo)) for i in itens)
            soma_mov = sum(_numero(m.get(campo)) for m in movs)
            if soma_item != soma_mov:
                achados.append(_achado(
                    "divergencia_quantidade", f"descarte: item.{campo} <> movimento.{campo}",
                    "pnc_romaneios_descarte", rom["id"], rom.get("numero"),
                    [(f"pnc_romaneio_descarte_itens.{campo}", soma_item),
                     (f"pnc_movimentos_descarte.{campo}", soma_mov)],
                    f"Romaneio de descarte {rom.get('numero')} com {campo} divergente entre documento e movimento.",
                ))
    return achados


def _divergencias_cmv(cursor, nao_avaliadas):
    achados = []
    if not (_exige(cursor, nao_avaliadas, "cmv_eventos",
                   ("id", "tipo", "quantidade", "quantidade_com_custo", "quantidade_sem_custo"))
            and _exige(cursor, nao_avaliadas, "cmv_consumos", ("evento_id", "quantidade"))):
        return achados
    eventos = _consultar(cursor, """
        SELECT ev.*, (SELECT COALESCE(SUM(c.quantidade),0) FROM cmv_consumos c WHERE c.evento_id=ev.id) AS soma_consumos
        FROM cmv_eventos ev ORDER BY ev.id""")
    for ev in eventos:
        quantidade = _numero(ev["quantidade"])
        com, sem = _numero(ev["quantidade_com_custo"]), _numero(ev["quantidade_sem_custo"])
        referencia = ev.get("documento") or f"evento {ev['id']}"
        if com + sem != quantidade:
            achados.append(_achado(
                "divergencia_quantidade", "evento CMV: com_custo + sem_custo <> quantidade", "cmv_eventos",
                ev["id"], referencia,
                [("quantidade_com_custo + quantidade_sem_custo", com + sem), ("quantidade", quantidade)],
                f"Evento {ev['tipo']} com cobertura de custo que nao fecha a quantidade.",
            ))
        if not str(ev["tipo"]).startswith("ESTORNO") and _numero(ev["soma_consumos"]) != quantidade:
            achados.append(_achado(
                "divergencia_quantidade", "evento CMV: soma de consumos <> quantidade", "cmv_eventos",
                ev["id"], referencia,
                [("soma cmv_consumos.quantidade", _numero(ev["soma_consumos"])), ("quantidade", quantidade)],
                f"Evento {ev['tipo']} cujos consumos FIFO nao totalizam a quantidade baixada.",
            ))
    return achados


def _vendas_sem_cmv(cursor, fontes_ausentes):
    """Devolve (achados, nao_avaliaveis).

    Ausencia de CMV so e divergencia comprovada quando o vinculo venda->CMV e
    verificavel: existe ao menos um evento VENDA com vinculo explicito
    (origem ROMANEIO/EXPEDICAO/VENDA_DIRETA + origem_id) e a venda e do mesmo
    dia ou posterior ao primeiro desses eventos. Fora disso a venda e
    "nao avaliavel", nunca achado.
    """
    achados, nao_avaliaveis = [], []
    if not _exige(cursor, fontes_ausentes, "expedicoes", ("id", "numero_romaneio", "status", "tipo_movimentacao", "data")):
        return achados, nao_avaliaveis
    possui_eventos = _exige(cursor, fontes_ausentes, "cmv_eventos",
                            ("id", "tipo", "data_evento", "origem_tipo", "origem_id", "documento", "evento_original_id"))
    vendas = _consultar(cursor, """
        SELECT id, numero_romaneio, data, cliente_id FROM expedicoes
        WHERE tipo_movimentacao='VENDA_DIRETA' AND status='Concluído' ORDER BY id""")
    eventos = []
    if possui_eventos:
        eventos = _consultar(cursor, """
            SELECT ev.id, ev.data_evento, ev.origem_tipo, ev.origem_id, ev.documento FROM cmv_eventos ev
            WHERE ev.tipo='VENDA'
              AND NOT EXISTS (SELECT 1 FROM cmv_eventos es
                              WHERE es.evento_original_id = ev.id AND es.tipo='ESTORNO_VENDA')""")
    explicitos = [e for e in eventos
                  if e["origem_id"] is not None and str(e["origem_tipo"]).upper() in ORIGENS_CMV_ROMANEIO]
    por_origem = {str(e["origem_id"]) for e in explicitos}
    por_documento = {str(e["documento"]) for e in eventos if e["documento"]}
    datas = [str(e["data_evento"])[:10] for e in explicitos if e["data_evento"]]
    ancora = min(datas) if datas else None
    for venda in vendas:
        if str(venda["id"]) in por_origem or str(venda["numero_romaneio"]) in por_documento:
            continue
        data_venda = str(venda.get("data") or "")[:10]
        if ancora is None:
            motivo = ("Nenhum evento CMV de VENDA traz vinculo explicito com romaneio; "
                      "nao ha como afirmar que a venda deveria ter sido apropriada.")
        elif not data_venda or data_venda < ancora:
            motivo = (f"Venda anterior ao primeiro vinculo CMV explicito com romaneio ({ancora}); "
                      "o vinculo nao existia no periodo.")
        else:
            achados.append(_achado(
                "venda_sem_cmv", "romaneio de Venda Direta concluido sem evento CMV de VENDA vinculado",
                "expedicoes", venda["id"], venda.get("numero_romaneio"),
                [("eventos CMV VENDA vinculados", 0), ("esperado", ">= 1"),
                 ("primeiro vinculo explicito", ancora)],
                f"Venda do romaneio {venda.get('numero_romaneio')} ({venda.get('data')}) sem apropriacao de CMV, "
                "em periodo com vinculo explicito ativo.",
            ))
            continue
        nao_avaliaveis.append({
            "origem": "expedicoes", "registro_id": venda["id"],
            "referencia": venda.get("numero_romaneio") or "-", "data": venda.get("data"),
            "justificativa": motivo,
        })
    return achados, nao_avaliaveis


# --------------------------------------------------------------------------
# Orquestracao
# --------------------------------------------------------------------------

def _abrir_somente_leitura():
    conn = conectar()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("SET TRANSACTION READ ONLY")
    else:
        cursor.execute("PRAGMA query_only = ON")
    return conn, cursor


def montar_diagnostico_integridade(args=None):
    """Executa todas as regras e devolve o contexto do relatorio."""
    args = args or {}
    categoria_filtro = args.get("categoria") or "Todas"
    conn, cursor = _abrir_somente_leitura()
    nao_avaliadas = []
    nao_avaliaveis = []
    try:
        achados = []
        achados += _saldos_negativos(cursor, nao_avaliadas)
        achados += _expedicoes_duplicadas(cursor, nao_avaliadas)
        achados += _divergencias_quantidade(cursor, nao_avaliadas)
        achados_vendas, nao_avaliaveis = _vendas_sem_cmv(cursor, nao_avaliadas)
        achados += achados_vendas
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()
    resumo = [
        {"chave": chave, "rotulo": rotulo, "total": sum(1 for a in achados if a["categoria"] == chave)}
        for chave, rotulo in CATEGORIAS.items()
    ]
    visiveis = [a for a in achados if categoria_filtro in ("Todas", a["categoria"])]
    return {
        "achados": visiveis,
        "total_achados": len(achados),
        "resumo": resumo,
        "categorias": CATEGORIAS,
        "filtros": {"categoria": categoria_filtro},
        "limitacoes": LIMITACOES,
        "nao_avaliadas": sorted(set(nao_avaliadas)),
        "nao_avaliaveis": nao_avaliaveis,
        "total_nao_avaliaveis": len(nao_avaliaveis),
        "consistente": not achados,
    }
