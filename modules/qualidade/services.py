"""Servicos do modulo de Qualidade."""

from database import conectar, q
from modules.producao.services import validar_op_aberta


def salvar_apontamento_descarte(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_descartes (
        op_id, data, setor, categoria, motivo, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        op_id,
        form["data"],
        form["setor"],
        form["categoria"],
        form["motivo"],
        float(form["quantidade"]),
        form["unidade"],
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()


def salvar_apontamentos_descartes_lote(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    data = form["data"]
    observacoes = form.get("observacoes", "")
    quantidades = form.getlist("quantidade[]")
    motivos = form.getlist("motivo[]")
    setores = form.getlist("setor[]")

    if not quantidades:
        raise ValueError("Adicione pelo menos uma linha de descarte antes de confirmar.")

    if not (len(quantidades) == len(motivos) == len(setores)):
        raise ValueError("As linhas de descarte estao incompletas. Revise quantidades, motivos e setores.")

    linhas = []
    for indice, quantidade_raw in enumerate(quantidades, start=1):
        try:
            quantidade = float(quantidade_raw)
        except (TypeError, ValueError):
            raise ValueError(f"Informe uma quantidade valida na linha {indice}.")

        if quantidade <= 0:
            raise ValueError(f"A quantidade da linha {indice} precisa ser maior que zero.")

        motivo = motivos[indice - 1]
        setor = setores[indice - 1]

        if not motivo or not setor:
            raise ValueError(f"Selecione motivo e setor na linha {indice}.")

        linhas.append((op_id, data, setor, "Descarte", motivo, quantidade, "aves", observacoes))

    conn = conectar()
    cursor = conn.cursor()

    cursor.executemany(q("""
    INSERT INTO apontamentos_descartes (
        op_id, data, setor, categoria, motivo, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), linhas)

    conn.commit()
    conn.close()

    return len(linhas)
