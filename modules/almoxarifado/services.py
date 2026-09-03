"""Servicos do modulo de Almoxarifado."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from database import DATABASE_URL, conectar, q


PERFIS_CORRIGIR_ENTRADA_ESTOQUE = frozenset({"admin", "gerencia"})
ESCALA_QUANTIDADE = Decimal("0.0001")
ESCALA_MONETARIA = Decimal("0.0001")


class ConflitoCorrecaoEntrada(RuntimeError):
    """Indica que o snapshot aberto pelo usuario ficou desatualizado."""


def _decimal_positivo(valor, campo, *, permite_zero=False, escala=ESCALA_QUANTIDADE):
    texto = str(valor if valor is not None else "").strip()
    if not texto:
        raise ValueError(f"Informe {campo.lower()}.")
    if "," in texto and "." in texto:
        raise ValueError(f"{campo} inválido.")
    try:
        numero = Decimal(texto.replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{campo} inválido.") from None
    if not numero.is_finite():
        raise ValueError(f"{campo} inválido.")
    if numero < 0 or (numero == 0 and not permite_zero):
        comparacao = "maior ou igual a zero" if permite_zero else "maior que zero"
        raise ValueError(f"{campo} precisa ser {comparacao}.")
    if numero.as_tuple().exponent < -4:
        raise ValueError(f"{campo} aceita no máximo 4 casas decimais.")
    return numero.quantize(escala, rounding=ROUND_HALF_UP)


def _texto_decimal(valor, escala=ESCALA_MONETARIA):
    return format(Decimal(str(valor or 0)).quantize(escala, rounding=ROUND_HALF_UP), "f")


def perfil_pode_corrigir_entrada(perfil):
    return str(perfil or "").lower() in PERFIS_CORRIGIR_ENTRADA_ESTOQUE


def _alterar_coluna(cursor, conn, postgres, sqlite):
    try:
        cursor.execute(postgres if DATABASE_URL else sqlite)
        conn.commit()
    except Exception:
        conn.rollback()


CATEGORIAS_ALMOXARIFADO = [
    "Matéria-prima",
    "Embalagem",
    "Produto Químico",
    "Peça de Reposição",
    "EPI",
    "Material de Limpeza",
    "Material de Escritório",
    "Combustível / Lubrificante",
    "Outros"
]

UNIDADES_ALMOXARIFADO = [
    "Kg",
    "Un",
    "Cx",
    "Pacote",
    "Litro",
    "Metro",
    "Par",
    "Galão",
    "Saco"
]


def criar_tabelas_almoxarifado():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_insumos (
            id SERIAL PRIMARY KEY,
            descricao TEXT NOT NULL UNIQUE,
            categoria TEXT NOT NULL,
            unidade TEXT NOT NULL,
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL UNIQUE,
            categoria TEXT NOT NULL,
            unidade TEXT NOT NULL,
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()


def salvar_insumo_almoxarifado(form):
    criar_tabelas_almoxarifado()

    descricao = form.get("descricao", "").strip()
    categoria = form.get("categoria", "").strip()
    unidade = form.get("unidade", "").strip()
    ativo = form.get("ativo", "Sim").strip()
    observacoes = form.get("observacoes", "").strip()

    if not descricao:
        raise ValueError("Informe a descrição do insumo.")

    if categoria not in CATEGORIAS_ALMOXARIFADO:
        raise ValueError("Categoria inválida.")

    if unidade not in UNIDADES_ALMOXARIFADO:
        raise ValueError("Unidade inválida.")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO almoxarifado_insumos (
        descricao, categoria, unidade, ativo, observacoes
    ) VALUES (?, ?, ?, ?, ?)
    """), (
        descricao,
        categoria,
        unidade,
        ativo,
        observacoes
    ))

    conn.commit()
    conn.close()


def buscar_insumos_almoxarifado(filtro_categoria="Todas", filtro_status="Todos", termo=""):
    condicoes = ["1 = 1"]
    parametros = []

    if filtro_categoria and filtro_categoria != "Todas":
        condicoes.append("categoria = ?")
        parametros.append(filtro_categoria)

    if filtro_status and filtro_status != "Todos":
        condicoes.append("ativo = ?")
        parametros.append(filtro_status)

    if termo:
        condicoes.append("LOWER(descricao) LIKE ?")
        parametros.append(f"%{termo.lower()}%")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT *
    FROM almoxarifado_insumos
    WHERE {where_sql}
    ORDER BY ativo DESC, categoria ASC, descricao ASC
    """), tuple(parametros))

    insumos = cursor.fetchall()
    conn.close()
    return insumos


def buscar_insumo_almoxarifado_por_id(insumo_id):
    criar_tabelas_almoxarifado()
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM almoxarifado_insumos
    WHERE id = ?
    """), (insumo_id,))

    insumo = cursor.fetchone()
    conn.close()
    return insumo


def atualizar_insumo_almoxarifado(insumo_id, form):
    criar_tabelas_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    UPDATE almoxarifado_insumos
    SET descricao = ?,
        categoria = ?,
        unidade = ?,
        ativo = ?,
        observacoes = ?
    WHERE id = ?
    """), (
        form.get("descricao", "").strip(),
        form.get("categoria", "").strip(),
        form.get("unidade", "").strip(),
        form.get("ativo", "Sim").strip(),
        form.get("observacoes", "").strip(),
        insumo_id
    ))

    conn.commit()
    conn.close()



def criar_tabelas_estoque_almoxarifado():
    criar_tabelas_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_lotes (
            id SERIAL PRIMARY KEY,
            insumo_id INTEGER NOT NULL,
            data_entrada TEXT NOT NULL,
            lote TEXT,
            fornecedor TEXT,
            numero_nf TEXT,
            quantidade_inicial REAL NOT NULL,
            quantidade_atual REAL NOT NULL,
            valor_unitario REAL NOT NULL,
            valor_total REAL NOT NULL,
            status TEXT DEFAULT 'Aberto',
            validade TEXT,
            criado_por TEXT,
            versao INTEGER NOT NULL DEFAULT 0,
            atualizado_em TIMESTAMP,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_movimentacoes (
            id SERIAL PRIMARY KEY,
            data_movimentacao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            insumo_id INTEGER NOT NULL,
            lote_id INTEGER,
            quantidade REAL NOT NULL,
            valor_unitario REAL DEFAULT 0,
            valor_total REAL DEFAULT 0,
            fornecedor TEXT,
            numero_nf TEXT,
            lote TEXT,
            origem TEXT DEFAULT 'Manual',
            op_id INTEGER,
            observacoes TEXT,
            criado_por TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_lotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insumo_id INTEGER NOT NULL,
            data_entrada TEXT NOT NULL,
            lote TEXT,
            fornecedor TEXT,
            numero_nf TEXT,
            quantidade_inicial REAL NOT NULL,
            quantidade_atual REAL NOT NULL,
            valor_unitario REAL NOT NULL,
            valor_total REAL NOT NULL,
            status TEXT DEFAULT 'Aberto',
            validade TEXT,
            criado_por TEXT,
            versao INTEGER NOT NULL DEFAULT 0,
            atualizado_em TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_movimentacao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            insumo_id INTEGER NOT NULL,
            lote_id INTEGER,
            quantidade REAL NOT NULL,
            valor_unitario REAL DEFAULT 0,
            valor_total REAL DEFAULT 0,
            fornecedor TEXT,
            numero_nf TEXT,
            lote TEXT,
            origem TEXT DEFAULT 'Manual',
            op_id INTEGER,
            observacoes TEXT,
            criado_por TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()

    for coluna, tipo in (
        ("validade", "TEXT"),
        ("criado_por", "TEXT"),
        ("versao", "INTEGER NOT NULL DEFAULT 0"),
        ("atualizado_em", "TIMESTAMP" if DATABASE_URL else "TEXT"),
    ):
        _alterar_coluna(
            cursor, conn,
            f"ALTER TABLE almoxarifado_lotes ADD COLUMN IF NOT EXISTS {coluna} {tipo}",
            f"ALTER TABLE almoxarifado_lotes ADD COLUMN {coluna} {tipo}",
        )
    _alterar_coluna(
        cursor, conn,
        "ALTER TABLE almoxarifado_movimentacoes ADD COLUMN IF NOT EXISTS criado_por TEXT",
        "ALTER TABLE almoxarifado_movimentacoes ADD COLUMN criado_por TEXT",
    )

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_correcoes_entrada (
            id SERIAL PRIMARY KEY,
            entrada_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            usuario TEXT NOT NULL,
            usuario_id INTEGER,
            perfil TEXT NOT NULL,
            motivo TEXT NOT NULL,
            quantidade_anterior TEXT NOT NULL,
            quantidade_nova TEXT NOT NULL,
            valor_unitario_anterior TEXT NOT NULL,
            valor_unitario_novo TEXT NOT NULL,
            total_anterior TEXT NOT NULL,
            total_novo TEXT NOT NULL,
            impacto_financeiro TEXT NOT NULL,
            fornecedor_anterior TEXT,
            fornecedor_novo TEXT,
            documento_anterior TEXT,
            documento_novo TEXT,
            lote_anterior TEXT,
            lote_novo TEXT,
            validade_anterior TEXT,
            validade_nova TEXT,
            observacao_anterior TEXT,
            observacao_nova TEXT,
            metodo TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            versao_anterior INTEGER NOT NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_correcoes_entrada (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entrada_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            usuario TEXT NOT NULL,
            usuario_id INTEGER,
            perfil TEXT NOT NULL,
            motivo TEXT NOT NULL,
            quantidade_anterior TEXT NOT NULL,
            quantidade_nova TEXT NOT NULL,
            valor_unitario_anterior TEXT NOT NULL,
            valor_unitario_novo TEXT NOT NULL,
            total_anterior TEXT NOT NULL,
            total_novo TEXT NOT NULL,
            impacto_financeiro TEXT NOT NULL,
            fornecedor_anterior TEXT,
            fornecedor_novo TEXT,
            documento_anterior TEXT,
            documento_novo TEXT,
            lote_anterior TEXT,
            lote_novo TEXT,
            validade_anterior TEXT,
            validade_nova TEXT,
            observacao_anterior TEXT,
            observacao_nova TEXT,
            metodo TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            versao_anterior INTEGER NOT NULL,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_almox_correcoes_entrada ON almoxarifado_correcoes_entrada (entrada_id, id)")
    conn.commit()
    conn.close()


def salvar_entrada_estoque_almoxarifado(form, *, usuario=None):
    criar_tabelas_estoque_almoxarifado()

    insumo_id = int(form.get("insumo_id") or 0)
    data_entrada = form.get("data_entrada", "").strip()
    quantidade = _decimal_positivo(form.get("quantidade"), "Quantidade")
    valor_unitario = _decimal_positivo(
        form.get("valor_unitario"), "Valor unitário", permite_zero=True,
        escala=ESCALA_MONETARIA,
    )
    fornecedor = form.get("fornecedor", "").strip()
    numero_nf = form.get("numero_nf", "").strip()
    lote = form.get("lote", "").strip()
    validade = form.get("validade", "").strip()
    observacoes = form.get("observacoes", "").strip()

    if not buscar_insumo_almoxarifado_por_id(insumo_id):
        raise ValueError("Selecione um insumo válido.")

    if not data_entrada:
        raise ValueError("Informe a data de entrada.")

    valor_total = (quantidade * valor_unitario).quantize(ESCALA_MONETARIA, rounding=ROUND_HALF_UP)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO almoxarifado_lotes (
        insumo_id,
        data_entrada,
        lote,
        fornecedor,
        numero_nf,
        quantidade_inicial,
        quantidade_atual,
        valor_unitario,
        valor_total,
        status,
        validade,
        criado_por
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        insumo_id,
        data_entrada,
        lote,
        fornecedor,
        numero_nf,
        str(quantidade),
        str(quantidade),
        str(valor_unitario),
        str(valor_total),
        "Aberto",
        validade or None,
        usuario or "Sistema"
    ))

    lote_id = None
    try:
        if DATABASE_URL:
            cursor.execute("SELECT LASTVAL() as id")
            lote_id = cursor.fetchone()["id"]
        else:
            lote_id = cursor.lastrowid
    except Exception:
        lote_id = None

    cursor.execute(q("""
    INSERT INTO almoxarifado_movimentacoes (
        data_movimentacao,
        tipo,
        insumo_id,
        lote_id,
        quantidade,
        valor_unitario,
        valor_total,
        fornecedor,
        numero_nf,
        lote,
        origem,
        observacoes,
        criado_por
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        data_entrada,
        "ENTRADA",
        insumo_id,
        lote_id,
        str(quantidade),
        str(valor_unitario),
        str(valor_total),
        fornecedor,
        numero_nf,
        lote,
        "Entrada manual",
        observacoes,
        usuario or "Sistema"
    ))

    conn.commit()
    conn.close()


def buscar_entrada_estoque_almoxarifado(entrada_id):
    """Retorna o lote de entrada e seu movimento original, sem recalcular fontes."""
    criar_tabelas_estoque_almoxarifado()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT l.*, i.descricao AS insumo, i.unidade, i.categoria,
           m.id AS movimento_entrada_id, m.observacoes,
           COALESCE(l.criado_por, m.criado_por, 'Não informado') AS usuario_entrada,
           (SELECT COUNT(*) FROM almoxarifado_correcoes_entrada c
             WHERE c.entrada_id = l.id) AS total_correcoes
    FROM almoxarifado_lotes l
    JOIN almoxarifado_insumos i ON i.id = l.insumo_id
    LEFT JOIN almoxarifado_movimentacoes m ON m.id = (
        SELECT MIN(me.id) FROM almoxarifado_movimentacoes me
        WHERE me.lote_id = l.id AND me.tipo = 'ENTRADA'
    )
    WHERE l.id = ?
    """), (entrada_id,))
    entrada = cursor.fetchone()
    conn.close()
    return entrada


def buscar_historico_correcoes_entrada(entrada_id):
    criar_tabelas_estoque_almoxarifado()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT * FROM almoxarifado_correcoes_entrada
    WHERE entrada_id = ? ORDER BY id DESC
    """), (entrada_id,))
    historico = cursor.fetchall()
    conn.close()
    return historico


def _carregar_entrada_bloqueada(cursor, entrada_id):
    sufixo = " FOR UPDATE" if DATABASE_URL else ""
    cursor.execute(q(f"""
    SELECT l.*, i.descricao AS insumo, i.unidade
    FROM almoxarifado_lotes l
    JOIN almoxarifado_insumos i ON i.id = l.insumo_id
    WHERE l.id = ?{sufixo}
    """), (entrada_id,))
    entrada = cursor.fetchone()
    if not entrada:
        return None
    dados = dict(entrada)
    cursor.execute(q(f"""
    SELECT id, observacoes FROM almoxarifado_movimentacoes
    WHERE lote_id = ? AND tipo = 'ENTRADA' ORDER BY id LIMIT 1{sufixo}
    """), (entrada_id,))
    movimento = cursor.fetchone()
    dados["movimento_entrada_id"] = movimento["id"] if movimento else None
    dados["observacoes"] = movimento["observacoes"] if movimento else None
    return dados


def corrigir_entrada_estoque_almoxarifado(
        entrada_id, form, *, usuario, usuario_id=None, perfil, idempotency_key=None):
    """Corrige uma entrada intacta e registra snapshot imutavel na mesma transacao."""
    if not perfil_pode_corrigir_entrada(perfil):
        raise PermissionError("Usuário sem permissão para corrigir entradas de estoque.")

    motivo = str(form.get("motivo_correcao") or "").strip()
    if not motivo:
        raise ValueError("Informe o motivo da correção.")
    if str(form.get("confirmacao") or "").lower() not in {"sim", "on", "1", "true"}:
        raise ValueError("Confirme explicitamente a prévia antes de salvar.")

    chave = str(idempotency_key or form.get("idempotency_key") or "").strip()
    if not chave:
        raise ValueError("Solicitação de correção inválida. Recarregue a página.")
    try:
        versao_esperada = int(form.get("versao") or 0)
    except (TypeError, ValueError):
        raise ValueError("Versão da entrada inválida. Recarregue a página.") from None

    quantidade_nova = _decimal_positivo(form.get("quantidade"), "Quantidade")
    valor_unitario_novo = _decimal_positivo(
        form.get("valor_unitario"), "Valor unitário", permite_zero=True,
        escala=ESCALA_MONETARIA,
    )
    fornecedor_novo = str(form.get("fornecedor") or "").strip()
    documento_novo = str(form.get("numero_nf") or "").strip()
    lote_novo = str(form.get("lote") or "").strip()
    validade_nova = str(form.get("validade") or "").strip()
    observacao_nova = str(form.get("observacoes") or "").strip()

    criar_tabelas_estoque_almoxarifado()
    conn = conectar()
    try:
        if not DATABASE_URL:
            conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        cursor.execute(q("""
        SELECT id, entrada_id FROM almoxarifado_correcoes_entrada
        WHERE idempotency_key = ?
        """), (chave,))
        repetida = cursor.fetchone()
        if repetida:
            conn.rollback()
            if int(repetida["entrada_id"]) != int(entrada_id):
                raise ValueError("Solicitação de correção já utilizada para outra entrada.")
            return {"entrada_id": repetida["entrada_id"], "correcao_id": repetida["id"], "reaplicada": False}

        entrada = _carregar_entrada_bloqueada(cursor, entrada_id)
        if not entrada or not entrada["movimento_entrada_id"]:
            raise ValueError("Entrada de estoque não encontrada ou sem movimento original íntegro.")
        if int(entrada["versao"] or 0) != versao_esperada:
            raise ConflitoCorrecaoEntrada(
                "Esta entrada foi alterada por outro usuário. Recarregue os dados antes de corrigir."
            )
        if form.get("insumo_id") and int(form.get("insumo_id")) != int(entrada["insumo_id"]):
            raise ValueError("O material de uma entrada salva não pode ser alterado. Estorne e crie uma nova entrada.")

        sufixo = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q(f"""
        SELECT id, tipo, quantidade FROM almoxarifado_movimentacoes
        WHERE lote_id = ? AND id <> ? ORDER BY id{sufixo}
        """), (entrada_id, entrada["movimento_entrada_id"]))
        dependentes = cursor.fetchall()
        quantidade_anterior = Decimal(str(entrada["quantidade_inicial"]))
        quantidade_atual = Decimal(str(entrada["quantidade_atual"]))
        quantidade_movimentada = max(Decimal("0"), quantidade_anterior - quantidade_atual)
        if quantidade_nova < quantidade_movimentada:
            raise ValueError("A quantidade informada é inferior à quantidade já movimentada a partir desta entrada.")
        if dependentes or quantidade_atual != quantidade_anterior:
            raise ValueError(
                "Esta entrada já possui movimentações posteriores e não pode ser alterada diretamente. "
                "Utilize o procedimento de estorno e nova entrada."
            )

        valor_unitario_anterior = Decimal(str(entrada["valor_unitario"]))
        total_anterior = (quantidade_anterior * valor_unitario_anterior).quantize(
            ESCALA_MONETARIA, rounding=ROUND_HALF_UP)
        total_novo = (quantidade_nova * valor_unitario_novo).quantize(
            ESCALA_MONETARIA, rounding=ROUND_HALF_UP)
        impacto = (total_novo - total_anterior).quantize(ESCALA_MONETARIA, rounding=ROUND_HALF_UP)
        agora = datetime.now().isoformat(timespec="seconds")

        cursor.execute(q("""
        UPDATE almoxarifado_lotes
        SET quantidade_inicial = ?, quantidade_atual = ?, valor_unitario = ?, valor_total = ?,
            fornecedor = ?, numero_nf = ?, lote = ?, validade = ?, status = 'Aberto',
            versao = versao + 1, atualizado_em = ?
        WHERE id = ? AND versao = ?
        """), (
            str(quantidade_nova), str(quantidade_nova), str(valor_unitario_novo), str(total_novo),
            fornecedor_novo or None, documento_novo or None, lote_novo or None,
            validade_nova or None, agora, entrada_id, versao_esperada,
        ))
        if cursor.rowcount != 1:
            raise ConflitoCorrecaoEntrada(
                "Esta entrada foi alterada por outro usuário. Recarregue os dados antes de corrigir."
            )

        cursor.execute(q("""
        UPDATE almoxarifado_movimentacoes
        SET quantidade = ?, valor_unitario = ?, valor_total = ?, fornecedor = ?, numero_nf = ?,
            lote = ?, observacoes = ?
        WHERE id = ? AND tipo = 'ENTRADA' AND lote_id = ?
        """), (
            str(quantidade_nova), str(valor_unitario_novo), str(total_novo), fornecedor_novo or None,
            documento_novo or None, lote_novo or None, observacao_nova or None,
            entrada["movimento_entrada_id"], entrada_id,
        ))
        if cursor.rowcount != 1:
            raise RuntimeError("Falha ao atualizar o movimento original da entrada.")

        cursor.execute(q("""
        INSERT INTO almoxarifado_correcoes_entrada (
            entrada_id, insumo_id, usuario, usuario_id, perfil, motivo,
            quantidade_anterior, quantidade_nova, valor_unitario_anterior, valor_unitario_novo,
            total_anterior, total_novo, impacto_financeiro,
            fornecedor_anterior, fornecedor_novo, documento_anterior, documento_novo,
            lote_anterior, lote_novo, validade_anterior, validade_nova,
            observacao_anterior, observacao_nova, metodo, idempotency_key, versao_anterior, criado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            entrada_id, entrada["insumo_id"], usuario or "Sistema", usuario_id, str(perfil).lower(), motivo,
            _texto_decimal(quantidade_anterior, ESCALA_QUANTIDADE), _texto_decimal(quantidade_nova, ESCALA_QUANTIDADE),
            _texto_decimal(valor_unitario_anterior), _texto_decimal(valor_unitario_novo),
            _texto_decimal(total_anterior), _texto_decimal(total_novo), _texto_decimal(impacto),
            entrada["fornecedor"], fornecedor_novo or None, entrada["numero_nf"], documento_novo or None,
            entrada["lote"], lote_novo or None, entrada["validade"], validade_nova or None,
            entrada["observacoes"], observacao_nova or None, "correção direta", chave,
            versao_esperada, agora,
        ))
        correcao_id = cursor.lastrowid if not DATABASE_URL else None
        if DATABASE_URL:
            cursor.execute("SELECT LASTVAL() AS id")
            correcao_id = cursor.fetchone()["id"]
        conn.commit()
        return {"entrada_id": entrada_id, "correcao_id": correcao_id, "reaplicada": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def buscar_saldos_almoxarifado():
    criar_tabelas_estoque_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        i.id,
        i.descricao,
        i.categoria,
        i.unidade,
        i.ativo,
        COALESCE(SUM(l.quantidade_atual), 0) as saldo_atual,
        COALESCE(SUM(l.quantidade_atual * l.valor_unitario), 0) as valor_estoque
    FROM almoxarifado_insumos i
    LEFT JOIN almoxarifado_lotes l ON l.insumo_id = i.id
    GROUP BY i.id, i.descricao, i.categoria, i.unidade, i.ativo
    ORDER BY i.categoria ASC, i.descricao ASC
    """)

    saldos = cursor.fetchall()
    conn.close()
    return saldos


def buscar_lotes_almoxarifado(limite=50):
    criar_tabelas_estoque_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        l.*,
        i.descricao as insumo,
        i.unidade as unidade,
        i.categoria as categoria
    FROM almoxarifado_lotes l
    JOIN almoxarifado_insumos i ON i.id = l.insumo_id
    ORDER BY l.data_entrada ASC, l.id ASC
    LIMIT ?
    """), (limite,))

    lotes = cursor.fetchall()
    conn.close()
    return lotes


def buscar_movimentacoes_almoxarifado(limite=80):
    criar_tabelas_estoque_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        m.*,
        i.descricao as insumo,
        i.unidade as unidade,
        i.categoria as categoria
    FROM almoxarifado_movimentacoes m
    JOIN almoxarifado_insumos i ON i.id = m.insumo_id
    ORDER BY m.data_movimentacao DESC, m.id DESC
    LIMIT ?
    """), (limite,))

    movimentacoes = cursor.fetchall()
    conn.close()
    return movimentacoes


def calcular_resumo_estoque_almoxarifado(saldos):
    total_itens_com_saldo = sum(1 for item in saldos if float(item["saldo_atual"] or 0) > 0)
    valor_total = sum(float(item["valor_estoque"] or 0) for item in saldos)
    itens_zerados = sum(1 for item in saldos if float(item["saldo_atual"] or 0) <= 0)

    return {
        "itens_com_saldo": total_itens_com_saldo,
        "itens_zerados": itens_zerados,
        "valor_total": round(valor_total, 2),
        "total_itens": len(saldos)
    }



def buscar_saldos_almoxarifado_filtrado(filtro_categoria="Todas", termo=""):
    criar_tabelas_estoque_almoxarifado()

    condicoes = ["1 = 1"]
    parametros = []

    if filtro_categoria and filtro_categoria != "Todas":
        condicoes.append("i.categoria = ?")
        parametros.append(filtro_categoria)

    if termo:
        condicoes.append("LOWER(i.descricao) LIKE ?")
        parametros.append(f"%{termo.lower()}%")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        i.id,
        i.descricao,
        i.categoria,
        i.unidade,
        i.ativo,
        COALESCE(SUM(l.quantidade_atual), 0) as saldo_atual,
        COALESCE(SUM(l.quantidade_atual * l.valor_unitario), 0) as valor_estoque
    FROM almoxarifado_insumos i
    LEFT JOIN almoxarifado_lotes l ON l.insumo_id = i.id
    WHERE {where_sql}
    GROUP BY i.id, i.descricao, i.categoria, i.unidade, i.ativo
    ORDER BY i.categoria ASC, i.descricao ASC
    """), tuple(parametros))

    saldos = cursor.fetchall()
    conn.close()
    return saldos


def buscar_movimentacoes_almoxarifado_filtrado(data_inicio, data_fim, tipo_filtro="Todos", termo="", limite=300):
    criar_tabelas_estoque_almoxarifado()

    condicoes = ["m.data_movimentacao BETWEEN ? AND ?"]
    parametros = [data_inicio, data_fim]

    if tipo_filtro and tipo_filtro != "Todos":
        condicoes.append("m.tipo = ?")
        parametros.append(tipo_filtro)

    if termo:
        condicoes.append("LOWER(i.descricao) LIKE ?")
        parametros.append(f"%{termo.lower()}%")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        m.*,
        i.descricao as insumo,
        i.unidade as unidade,
        i.categoria as categoria
    FROM almoxarifado_movimentacoes m
    JOIN almoxarifado_insumos i ON i.id = m.insumo_id
    WHERE {where_sql}
    ORDER BY m.data_movimentacao DESC, m.id DESC
    LIMIT ?
    """), tuple(parametros + [limite]))

    movimentacoes = cursor.fetchall()
    conn.close()
    return movimentacoes


def buscar_lotes_almoxarifado_filtrado(
        insumo_id="", status_filtro="Todos", termo="", data_entrada="", fornecedor="",
        numero_nf="", entrada_id="", limite=300):
    criar_tabelas_estoque_almoxarifado()

    condicoes = ["1 = 1"]
    parametros = []

    if insumo_id:
        try:
            insumo_id_valido = int(insumo_id)
            condicoes.append("l.insumo_id = ?")
            parametros.append(insumo_id_valido)
        except (TypeError, ValueError):
            condicoes.append("1 = 0")

    if status_filtro and status_filtro != "Todos":
        condicoes.append("l.status = ?")
        parametros.append(status_filtro)

    if termo:
        condicoes.append("LOWER(i.descricao) LIKE ?")
        parametros.append(f"%{termo.lower()}%")

    if data_entrada:
        condicoes.append("l.data_entrada = ?")
        parametros.append(data_entrada)

    if fornecedor:
        condicoes.append("LOWER(COALESCE(l.fornecedor, '')) LIKE ?")
        parametros.append(f"%{fornecedor.lower()}%")

    if numero_nf:
        condicoes.append("LOWER(COALESCE(l.numero_nf, '')) LIKE ?")
        parametros.append(f"%{numero_nf.lower()}%")

    if entrada_id:
        try:
            entrada_id_valido = int(entrada_id)
            condicoes.append("l.id = ?")
            parametros.append(entrada_id_valido)
        except (TypeError, ValueError):
            condicoes.append("1 = 0")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        l.*,
        i.descricao as insumo,
        i.unidade as unidade,
        i.categoria as categoria
    FROM almoxarifado_lotes l
    JOIN almoxarifado_insumos i ON i.id = l.insumo_id
    WHERE {where_sql}
    ORDER BY l.data_entrada ASC, l.id ASC
    LIMIT ?
    """), tuple(parametros + [limite]))

    lotes = cursor.fetchall()
    conn.close()
    return lotes


def calcular_resumo_rastreabilidade(lotes):
    lotes_abertos = sum(1 for item in lotes if item["status"] == "Aberto")
    lotes_fechados = sum(1 for item in lotes if item["status"] == "Fechado")
    quantidade_total = sum(float(item["quantidade_atual"] or 0) for item in lotes)
    valor_total = sum(float(item["quantidade_atual"] or 0) * float(item["valor_unitario"] or 0) for item in lotes)

    return {
        "total_lotes": len(lotes),
        "lotes_abertos": lotes_abertos,
        "lotes_fechados": lotes_fechados,
        "quantidade_total": round(quantidade_total, 4),
        "valor_total": round(valor_total, 2)
    }


def calcular_resumo_almoxarifado(insumos):
    total_itens = len(insumos)
    itens_ativos = sum(1 for item in insumos if item["ativo"] == "Sim")
    itens_inativos = total_itens - itens_ativos
    categorias_usadas = len(set(item["categoria"] for item in insumos))

    return {
        "total_itens": total_itens,
        "itens_ativos": itens_ativos,
        "itens_inativos": itens_inativos,
        "categorias_usadas": categorias_usadas
    }
