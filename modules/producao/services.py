"""Regras operacionais do m?dulo de Produ??o."""

import uuid
from datetime import datetime

from database import DATABASE_URL, conectar, q
from modules.auth.services import nome_usuario_atual, usuario_eh_admin
from services import manutencao_service
from utils import calcular_horas_programadas, normalizar_chave_setor, setores_padrao


def criar_tabela_tempos_setor():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_tempos_setor (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_tempos_setor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()


def buscar_fornecedores():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM fornecedores
    ORDER BY nome
    """)

    fornecedores = cursor.fetchall()
    conn.close()

    return fornecedores


def buscar_ordens():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT *
    FROM ordens_producao
    ORDER BY id DESC
    """)
    ordens = cursor.fetchall()
    conn.close()
    return ordens


def buscar_ordens_abertas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT *
    FROM ordens_producao
    WHERE status IS NULL OR status <> 'Encerrada'
    ORDER BY id DESC
    """)
    ordens = cursor.fetchall()
    conn.close()
    return ordens


def op_esta_encerrada(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT status
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    op = cursor.fetchone()
    conn.close()

    if not op:
        return False

    return op["status"] == "Encerrada"


def validar_op_aberta(op_id):
    if op_esta_encerrada(op_id) and not usuario_eh_admin():
        raise ValueError("Esta OP já está encerrada. Novos lançamentos não são permitidos.")


def calcular_resumo_op(op, producoes, descartes):
    total_descartes_aves = sum(
        item["quantidade"] for item in descartes
        if item["unidade"].lower() in ["aves", "ave", "unidade", "unidades"]
    )

    mortes_na_gaiola_descartes = sum(
        item["quantidade"] for item in descartes
        if item["unidade"].lower() in ["aves", "ave", "unidade", "unidades"]
        and str(item["motivo"] or "").strip().lower() == "morte na gaiola"
    )

    mortes_na_gaiola = mortes_na_gaiola_descartes + float(op["mortes_antes_pendura"] or 0)

    total_descartes_kg = sum(
        item["quantidade"] for item in descartes
        if item["unidade"].lower() == "kg"
    )

    kg_produzidos = sum(
        item["quantidade"] for item in producoes
        if item["unidade"].lower() == "kg"
    )

    aves_abatidas = op["quantidade_aves"] - mortes_na_gaiola
    descartes_aves = total_descartes_aves + float(op["mortes_antes_pendura"] or 0)
    viabilidade = op["quantidade_aves"] - descartes_aves

    viabilidade_percentual = 0
    if op["quantidade_aves"] > 0:
        viabilidade_percentual = (viabilidade / op["quantidade_aves"]) * 100

    rendimento = 0
    if op["peso_vivo"] > 0:
        rendimento = (kg_produzidos / op["peso_vivo"]) * 100

    return {
        "aves_abatidas": aves_abatidas,
        "descartes_aves": total_descartes_aves,
        "descartes_kg": total_descartes_kg,
        "mortes_na_gaiola": mortes_na_gaiola,
        "kg_produzidos": kg_produzidos,
        "viabilidade": viabilidade,
        "viabilidade_percentual": round(viabilidade_percentual, 2),
        "rendimento": round(rendimento, 2)
    }



def salvar_apontamento_mao_obra(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_mao_obra (
        op_id, data, colaborador, funcao, setor, turno, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        op_id,
        form["data"],
        form["colaborador"],
        form["funcao"],
        form["setor"],
        form.get("turno", ""),
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()



def copiar_mao_obra_de_op(origem_op_id, destino_op_id, data_destino):
    origem_op_id = int(origem_op_id)
    destino_op_id = int(destino_op_id)

    if origem_op_id == destino_op_id:
        raise ValueError("A OP de origem não pode ser a mesma OP de destino.")

    validar_op_aberta(destino_op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM apontamentos_mao_obra
    WHERE op_id = ?
    ORDER BY id ASC
    """), (origem_op_id,))

    registros_origem = cursor.fetchall()

    if not registros_origem:
        conn.close()
        raise ValueError("A OP de origem não possui lançamentos de mão de obra para copiar.")

    cursor.execute(q("""
    DELETE FROM apontamentos_mao_obra
    WHERE op_id = ?
    """), (destino_op_id,))

    for item in registros_origem:
        cursor.execute(q("""
        INSERT INTO apontamentos_mao_obra (
            op_id, data, colaborador, funcao, setor, turno, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """), (
            destino_op_id,
            data_destino,
            item["colaborador"],
            item["funcao"],
            item["setor"],
            item["turno"],
            item["observacoes"]
        ))

    conn.commit()
    conn.close()

    return len(registros_origem)



def salvar_apontamento_parada(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    setores_form = form.getlist("setores") if hasattr(form, "getlist") else form.get("setores", [])
    if isinstance(setores_form, str):
        setores_form = [setores_form]

    if not form.get("equipamento_id") and (setores_form or form.get("horas_paradas")):
        setores_impactados = setores_form

        if not setores_impactados and form.get("setor"):
            setores_impactados = [form.get("setor")]

        if not setores_impactados:
            raise ValueError("Selecione pelo menos um setor impactado pela parada.")

        conn = conectar()
        cursor = conn.cursor()
        evento_id = uuid.uuid4().hex
        horas_paradas = float(form.get("horas_paradas") or 0)

        if horas_paradas <= 0 and form.get("hora_inicio") and form.get("hora_fim"):
            horas_paradas = calcular_horas_programadas(
                form["hora_inicio"],
                form["hora_fim"]
            )

        for setor_legado in setores_impactados:
            cursor.execute(q("""
            INSERT INTO apontamentos_paradas (
                evento_id, op_id, data, setor, motivo, hora_inicio, hora_fim, horas_paradas, observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """), (
                evento_id,
                op_id,
                form["data"],
                setor_legado,
                form["motivo"],
                form.get("hora_inicio", ""),
                form.get("hora_fim", ""),
                horas_paradas,
                form.get("observacoes", "")
            ))

        conn.commit()
        conn.close()
        return

    equipamento_id = int(form.get("equipamento_id") or 0)
    equipamento_texto = form.get("equipamento", "").strip()
    setor = (form.get("setor") or "Linha de producao").strip()
    motivo = (form.get("motivo") or "Quebra de equipamento").strip()
    abrir_os = form.get("abrir_os") == "Sim"
    hora_inicio = form.get("hora_inicio", "").strip()
    hora_fim = form.get("hora_fim", "").strip()

    motivos_manutencao = manutencao_service.MOTIVOS_MANUTENCAO

    if not equipamento_id and not equipamento_texto:
        raise ValueError("Informe o equipamento onde se originou o problema.")

    if not hora_inicio:
        raise ValueError("Informe a hora que parou.")

    if motivo not in motivos_manutencao:
        abrir_os = False

    if not abrir_os and not hora_fim:
        raise ValueError("Informe a hora que voltou a funcionar ou abra uma ordem de servico.")

    if equipamento_id:
        equipamento = next(
            (item for item in manutencao_service.buscar_equipamentos_manutencao() if int(item["id"]) == equipamento_id),
            None
        )
        if not equipamento:
            raise ValueError("Equipamento nao encontrado.")
        equipamento_texto = f"{equipamento['codigo']} - {equipamento['nome']}"

    conn = conectar()
    cursor = conn.cursor()

    evento_id = uuid.uuid4().hex

    horas_paradas = float(form.get("horas_paradas") or 0)

    if horas_paradas <= 0 and hora_fim:
        horas_paradas = calcular_horas_programadas(
            hora_inicio,
            hora_fim
        )

    if horas_paradas <= 0 and not abrir_os:
        conn.close()
        raise ValueError("O tempo parado precisa ser maior que zero.")

    cursor.execute(q("""
    INSERT INTO apontamentos_paradas (
        evento_id, op_id, data, data_fim, setor, motivo, equipamento, equipamento_id,
        hora_inicio, hora_fim, horas_paradas, observacoes, manutencao_aberta
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        evento_id,
        op_id,
        form["data"],
        form["data"] if hora_fim else "",
        setor,
        motivo,
        equipamento_texto,
        equipamento_id or None,
        hora_inicio,
        hora_fim or "",
        horas_paradas,
        form.get("observacoes", ""),
        "Sim" if abrir_os else "Nao"
    ))

    conn.commit()
    cursor.execute("SELECT LASTVAL() as id" if DATABASE_URL else "SELECT last_insert_rowid() as id")
    parada_id = cursor.fetchone()["id"]
    conn.close()

    if abrir_os:
        manutencao_service.criar_ordem_por_parada(
            parada_id=parada_id,
            op_id=op_id,
            equipamento_id=equipamento_id,
            setor=setor,
            motivo=motivo,
            data=form["data"],
            hora_inicio=hora_inicio,
            usuario=nome_usuario_atual(),
            observacoes=form.get("observacoes", ""),
        )

def gerar_producao_automatica_setores(op, data_lancamento, hora_inicio, hora_fim, unidades_produzidas, kg_produzidos=None, descontar_almoco=False):
    setores_por_sku = {
        "Galinha Inteira": [
            "Recepção e Pendura",
            "Escalda e Depenagem",
            "Evisceração",
            "Embalagem"
        ],
        "Galinha Cortada": [
            "Recepção e Pendura",
            "Escalda e Depenagem",
            "Evisceração",
            "Corte",
            "Embalagem"
        ]
    }

    sku = op["sku"] or "Galinha Cortada"
    setores = setores_por_sku.get(sku, setores_por_sku["Galinha Cortada"])

    texto_almoco = "Sim" if descontar_almoco else "Não"

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    DELETE FROM apontamentos_producao
    WHERE op_id = ?
    """), (op["id"],))

    cursor.execute(q("""
    SELECT setor, COALESCE(SUM(quantidade), 0) as total
    FROM apontamentos_descartes
    WHERE op_id = ?
      AND LOWER(unidade) IN ('aves', 'ave', 'unidade', 'unidades')
      AND LOWER(TRIM(motivo)) <> 'morte na gaiola'
    GROUP BY setor
    """), (op["id"],))

    descartes = cursor.fetchall()
    descartes_por_setor = {
        item["setor"]: float(item["total"] or 0)
        for item in descartes
    }

    cursor.execute(q("""
    SELECT COALESCE(SUM(quantidade), 0) as total
    FROM apontamentos_descartes
    WHERE op_id = ?
      AND LOWER(unidade) IN ('aves', 'ave', 'unidade', 'unidades')
      AND LOWER(TRIM(motivo)) = 'morte na gaiola'
    """), (op["id"],))

    mortes_na_gaiola = float(cursor.fetchone()["total"] or 0) + float(op["mortes_antes_pendura"] or 0)
    entrada_setor = float((op["quantidade_aves"] or 0) - mortes_na_gaiola)

    for setor in setores:
        quantidade_setor = max(0, entrada_setor)

        cursor.execute(q("""
        INSERT INTO apontamentos_producao (
            op_id, data, setor, quantidade, unidade, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """), (
            op["id"],
            data_lancamento,
            setor,
            quantidade_setor,
            "unidades",
            f"Gerado automaticamente no encerramento da OP | Início: {hora_inicio} | Fim: {hora_fim} | Descontar almoço 1h12: {texto_almoco}"
        ))

        entrada_setor = quantidade_setor - descartes_por_setor.get(setor, 0)

    cursor.execute(q("""
    INSERT INTO apontamentos_producao (
        op_id, data, setor, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?)
    """), (
        op["id"],
        data_lancamento,
        "Expedição",
        float(unidades_produzidas),
        "unidades",
        f"Produção final informada no encerramento da OP | Início: {hora_inicio} | Fim: {hora_fim} | Descontar almoço 1h12: {texto_almoco}"
    ))

    if kg_produzidos is not None and float(kg_produzidos or 0) > 0:
        cursor.execute(q("""
        INSERT INTO apontamentos_producao (
            op_id, data, setor, quantidade, unidade, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """), (
            op["id"],
            data_lancamento,
            "Expedição",
            float(kg_produzidos),
            "kg",
            f"Kg final produzido informado no encerramento da OP | Início: {hora_inicio} | Fim: {hora_fim} | Descontar almoço 1h12: {texto_almoco}"
        ))

    conn.commit()
    conn.close()


def buscar_op_por_id(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    op = cursor.fetchone()
    conn.close()

    return op




def setores_por_sku(sku):
    if sku == "Galinha Inteira":
        return [
            "Recepção e Pendura",
            "Escalda e Depenagem",
            "Evisceração",
            "Embalagem"
        ]

    return [
        "Recepção e Pendura",
        "Escalda e Depenagem",
        "Evisceração",
        "Corte",
        "Embalagem"
    ]


def salvar_tempos_setor(form):
    criar_tabela_tempos_setor()
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    op = cursor.fetchone()

    if not op:
        conn.close()
        raise ValueError("OP não encontrada.")

    setores = setores_por_sku(op["sku"] or "Galinha Cortada")

    cursor.execute(q("""
    DELETE FROM apontamentos_tempos_setor
    WHERE op_id = ?
    """), (op_id,))

    for setor in setores:
        chave = normalizar_chave_setor(setor)
        hora_inicio = form.get(f"hora_inicio_{chave}")
        hora_fim = form.get(f"hora_fim_{chave}")

        if not hora_inicio or not hora_fim:
            conn.close()
            raise ValueError(f"Informe hora inicial e final para o setor {setor}.")

        cursor.execute(q("""
        INSERT INTO apontamentos_tempos_setor (
            op_id, data, setor, hora_inicio, hora_fim, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """), (
            op_id,
            op["data"],
            setor,
            hora_inicio,
            hora_fim,
            form.get("observacoes", "")
        ))

    conn.commit()
    conn.close()


def buscar_tempos_setor_por_op(op_id):
    criar_tabela_tempos_setor()
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM apontamentos_tempos_setor
    WHERE op_id = ?
    ORDER BY id ASC
    """), (op_id,))

    tempos = cursor.fetchall()
    conn.close()

    return tempos


def buscar_op_por_id(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    op = cursor.fetchone()
    conn.close()

    return op



def contexto_apontamento():
    return {
        "hoje": datetime.now().strftime("%Y-%m-%d"),
        "ordens": buscar_ordens_abertas(),
        "setores": setores_padrao(),
        "equipamentos_manutencao": manutencao_service.buscar_equipamentos_manutencao(),
        "motivos_manutencao": manutencao_service.MOTIVOS_MANUTENCAO,
        "motivos_operacionais": manutencao_service.MOTIVOS_OPERACIONAIS,
    }
