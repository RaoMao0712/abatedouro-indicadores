"""Rotas do modulo de Qualidade."""

from datetime import datetime

from flask import flash, redirect, render_template, request, session, url_for

from database import conectar, q
from modules.auth.decorators import perfil_permitido
from modules.auth.services import usuario_eh_admin
from modules.producao.services import buscar_fornecedores, contexto_apontamento
from .services import salvar_apontamento_descarte, salvar_apontamentos_descartes_lote
from . import services as qualidade_service

_CRIAR_BANCO = None


def register_qualidade_routes(app, integracoes=None):
    global _CRIAR_BANCO
    integracoes = integracoes or {}
    _CRIAR_BANCO = integracoes.get("criar_banco")


    def garantir_schema_producao():
        if _CRIAR_BANCO:
            _CRIAR_BANCO()


    def formatar_numero_br(valor, casas=2):
        try:
            numero = float(valor or 0)
        except Exception:
            numero = 0
        texto = f"{numero:,.{casas}f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")


    def formatar_percentual_br(valor):
        return f"{formatar_numero_br(valor, 2)}%"


    def obter_registros_por_ids(tabela, ids):
        if not ids:
            return []

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        SELECT
            r.*,
            o.status as op_status
        FROM {tabela} r
        JOIN ordens_producao o ON o.id = r.op_id
        WHERE r.id IN ({placeholders})
        ORDER BY r.id ASC
        """), tuple(ids))

        registros = cursor.fetchall()
        conn.close()
        return registros


    def ids_do_request(nome="ids"):
        valores = request.values.getlist(nome)

        if not valores:
            valores = request.form.getlist(nome)

        ids = []

        for valor in valores:
            try:
                ids.append(int(valor))
            except (TypeError, ValueError):
                pass

        return ids


    def primeiro_op_id(registros):
        if not registros:
            return None
        return registros[0]["op_id"]


    def edicao_bloqueada_por_status(registros):
        if usuario_eh_admin():
            return False

        for registro in registros:
            if registro["op_status"] == "Encerrada":
                return True

        return False


    # ============================================================
    # RELATÓRIO DE RENDIMENTO
    # ============================================================

    @app.route("/relatorio-rendimento")
    @perfil_permitido("pcp")
    def relatorio_rendimento():
        return redirect(url_for("relatorio_producao_oficial", slug="rendimento", **request.args))


    def relatorio_rendimento_legado_descontinuado():
        agora = datetime.now()
        hoje = agora.strftime("%Y-%m-%d")
        primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

        data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
        data_fim = request.args.get("data_fim") or hoje
        sku_filtro = request.args.get("sku") or "Todos"
        fornecedor_filtro = request.args.get("fornecedor") or "Todos"

        meta_rendimento = 63.0

        condicoes = [
            "o.data BETWEEN ? AND ?",
            "COALESCE(o.status, 'Aberta') = 'Encerrada'"
        ]
        parametros = [data_inicio, data_fim]

        if sku_filtro != "Todos":
            condicoes.append("COALESCE(o.sku, 'Galinha Cortada') = ?")
            parametros.append(sku_filtro)

        if fornecedor_filtro != "Todos":
            condicoes.append("o.fornecedor = ?")
            parametros.append(fornecedor_filtro)

        where_sql = " AND ".join(condicoes)

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        SELECT
            o.data,
            o.fornecedor,
            COALESCE(SUM(o.peso_vivo), 0) as peso_vivo,
            COALESCE(SUM(prod.kg_produzidos), 0) as kg_produzidos
        FROM ordens_producao o
        LEFT JOIN (
            SELECT
                op_id,
                COALESCE(SUM(quantidade), 0) as kg_produzidos
            FROM apontamentos_producao
            WHERE LOWER(unidade) = 'kg'
            GROUP BY op_id
        ) prod ON prod.op_id = o.id
        WHERE {where_sql}
        GROUP BY o.data, o.fornecedor
        ORDER BY o.data ASC, o.fornecedor ASC
        """), tuple(parametros))

        registros = cursor.fetchall()
        conn.close()

        datas = sorted({item["data"] for item in registros})
        fornecedores_grafico = sorted({item["fornecedor"] for item in registros})

        dados_por_chave = {}

        total_kg_produzidos = 0
        total_peso_vivo = 0
        tabela_linhas = []

        for item in registros:
            data = item["data"]
            fornecedor = item["fornecedor"]
            kg_produzidos = float(item["kg_produzidos"] or 0)
            peso_vivo = float(item["peso_vivo"] or 0)
            rendimento = (kg_produzidos / peso_vivo * 100) if peso_vivo > 0 else 0
            desvio_meta = rendimento - meta_rendimento

            total_kg_produzidos += kg_produzidos
            total_peso_vivo += peso_vivo

            linha = {
                "data": data,
                "fornecedor": fornecedor,
                "kg_produzidos": round(kg_produzidos, 2),
                "peso_vivo": round(peso_vivo, 2),
                "rendimento": round(rendimento, 2),
                "desvio_meta": round(desvio_meta, 2)
            }

            dados_por_chave[(data, fornecedor)] = linha
            tabela_linhas.append(linha)

        rendimento_medio = (
            total_kg_produzidos / total_peso_vivo * 100
            if total_peso_vivo > 0
            else 0
        )

        cores = [
            "#2563eb",
            "#16a34a",
            "#f97316",
            "#8b5cf6",
            "#0891b2",
            "#dc2626",
            "#64748b"
        ]

        datasets = []

        for indice, fornecedor in enumerate(fornecedores_grafico):
            dados_linha = []
            detalhes_linha = []

            for data in datas:
                linha = dados_por_chave.get((data, fornecedor))

                if linha:
                    dados_linha.append(linha["rendimento"])
                    detalhes_linha.append({
                        "kg_produzidos": linha["kg_produzidos"],
                        "peso_vivo": linha["peso_vivo"]
                    })
                else:
                    dados_linha.append(None)
                    detalhes_linha.append(None)

            cor = cores[indice % len(cores)]

            datasets.append({
                "label": fornecedor,
                "data": dados_linha,
                "detalhes": detalhes_linha,
                "borderColor": cor,
                "backgroundColor": cor,
                "tension": 0.25,
                "pointRadius": 4,
                "pointHoverRadius": 6,
                "spanGaps": False
            })

        if datas:
            datasets.append({
                "label": f"Meta {formatar_percentual_br(meta_rendimento)}",
                "data": [meta_rendimento for _ in datas],
                "borderColor": "#111827",
                "backgroundColor": "#111827",
                "borderDash": [8, 6],
                "pointRadius": 0,
                "pointHoverRadius": 0,
                "tension": 0,
                "ehMeta": True
            })

        return render_template(
            "relatorio_rendimento.html",
            data_inicio=data_inicio,
            data_fim=data_fim,
            sku_filtro=sku_filtro,
            fornecedor_filtro=fornecedor_filtro,
            fornecedores=buscar_fornecedores(),
            skus=["Galinha Inteira", "Galinha Cortada"],
            datas=datas,
            datasets=datasets,
            tabela_linhas=tabela_linhas,
            rendimento_medio=round(rendimento_medio, 2),
            meta_rendimento=meta_rendimento,
            total_kg_produzidos=round(total_kg_produzidos, 2),
            total_peso_vivo=round(total_peso_vivo, 2)
        )


    # ============================================================
    # RELATÓRIO DE VIABILIDADE
    # Relatório executivo de viabilidade das aves.
    # Escopo: perdas operacionais por período, fornecedor, motivo e setor.
    # ============================================================


    def normalizar_data_relatorio_viabilidade(valor, padrao):
        if not valor:
            return padrao

        try:
            datetime.strptime(valor, "%Y-%m-%d")
            return valor
        except Exception:
            return padrao


    def buscar_opcoes_relatorio_viabilidade(data_inicio, data_fim, fornecedor_filtro="Todos"):
        garantir_schema_producao()

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        SELECT DISTINCT fornecedor
        FROM ordens_producao
        WHERE data BETWEEN ? AND ?
          AND fornecedor IS NOT NULL
          AND fornecedor <> ''
        ORDER BY fornecedor
        """), (data_inicio, data_fim))
        fornecedores_periodo = [item["fornecedor"] for item in cursor.fetchall()]

        cursor.execute(q("""
        SELECT DISTINCT d.setor
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE o.data BETWEEN ? AND ?
          AND d.setor IS NOT NULL
          AND d.setor <> ''
        ORDER BY d.setor
        """), (data_inicio, data_fim))
        setores = [item["setor"] for item in cursor.fetchall()]

        filtros_motivos = ["o.data BETWEEN ? AND ?"]
        parametros_motivos = [data_inicio, data_fim]

        if fornecedor_filtro and fornecedor_filtro != "Todos":
            filtros_motivos.append("o.fornecedor = ?")
            parametros_motivos.append(fornecedor_filtro)

        where_motivos = " AND ".join(filtros_motivos)

        cursor.execute(q(f"""
        SELECT DISTINCT d.motivo
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_motivos}
          AND d.motivo IS NOT NULL
          AND d.motivo <> ''
        ORDER BY d.motivo
        """), tuple(parametros_motivos))
        motivos = [item["motivo"] for item in cursor.fetchall()]

        conn.close()

        return {
            "fornecedores": fornecedores_periodo,
            "setores": setores,
            "motivos": motivos
        }


    def buscar_dados_relatorio_viabilidade(data_inicio, data_fim, fornecedor_filtro="Todos", motivo_filtro="Todos", setor_filtro="Todos"):
        garantir_schema_producao()

        filtros_op = ["o.data BETWEEN ? AND ?"]
        parametros_op = [data_inicio, data_fim]

        if fornecedor_filtro and fornecedor_filtro != "Todos":
            filtros_op.append("o.fornecedor = ?")
            parametros_op.append(fornecedor_filtro)

        where_op = " AND ".join(filtros_op)

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        SELECT
            COALESCE(SUM(o.quantidade_aves), 0) AS aves_recebidas,
            COALESCE(SUM(o.mortes_antes_pendura), 0) AS mortes_antes_pendura,
            COUNT(o.id) AS total_ops
        FROM ordens_producao o
        WHERE {where_op}
        """), tuple(parametros_op))
        resumo_op = cursor.fetchone()

        aves_recebidas = float(resumo_op["aves_recebidas"] or 0)
        mortes_legado_base = float(resumo_op["mortes_antes_pendura"] or 0)
        motivo_normalizado = str(motivo_filtro or "").strip().lower()
        mortes_legado_aplicavel = motivo_normalizado in ["", "todos", "morte na gaiola"]
        mortes_antes_pendura = mortes_legado_base if mortes_legado_aplicavel else 0
        total_ops = int(resumo_op["total_ops"] or 0)

        filtros_perdas = list(filtros_op)
        parametros_perdas = list(parametros_op)

        if motivo_filtro and motivo_filtro != "Todos":
            filtros_perdas.append("d.motivo = ?")
            parametros_perdas.append(motivo_filtro)

        if setor_filtro and setor_filtro != "Todos":
            filtros_perdas.append("d.setor = ?")
            parametros_perdas.append(setor_filtro)

        filtros_perdas.append("LOWER(COALESCE(d.unidade, '')) IN ('aves', 'ave', 'unidade', 'unidades')")
        where_perdas = " AND ".join(filtros_perdas)

        cursor.execute(q(f"""
        SELECT
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                THEN d.quantidade ELSE 0 END), 0) AS condenacoes,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                  OR LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN 0 ELSE d.quantidade END), 0) AS descartes
            ,
            COALESCE(SUM(CASE
                WHEN LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN d.quantidade ELSE 0 END), 0) AS mortes_na_gaiola
            ,
            COALESCE(SUM(CASE
                WHEN LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN d.quantidade ELSE 0 END), 0) AS mortes_na_gaiola
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_perdas}
        """), tuple(parametros_perdas))
        perdas = cursor.fetchone()

        condenacoes = float(perdas["condenacoes"] or 0)
        descartes = float(perdas["descartes"] or 0)
        mortes_antes_pendura += float(perdas["mortes_na_gaiola"] or 0)
        total_perdas = mortes_antes_pendura + condenacoes + descartes
        aves_viaveis = max(0, aves_recebidas - total_perdas)
        viabilidade_percentual = (aves_viaveis / aves_recebidas * 100) if aves_recebidas > 0 else 0

        cursor.execute(q(f"""
        SELECT
            o.data,
            COALESCE(SUM(o.quantidade_aves), 0) AS aves_recebidas,
            COALESCE(SUM(o.mortes_antes_pendura), 0) AS mortes_antes_pendura
        FROM ordens_producao o
        WHERE {where_op}
        GROUP BY o.data
        ORDER BY o.data
        """), tuple(parametros_op))
        ops_por_data = {
            item["data"]: {
                "aves_recebidas": float(item["aves_recebidas"] or 0),
                "mortes_antes_pendura": float(item["mortes_antes_pendura"] or 0)
            }
            for item in cursor.fetchall()
        }

        cursor.execute(q(f"""
        SELECT
            o.data,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                THEN d.quantidade ELSE 0 END), 0) AS condenacoes,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                  OR LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN 0 ELSE d.quantidade END), 0) AS descartes
            ,
            COALESCE(SUM(CASE
                WHEN LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN d.quantidade ELSE 0 END), 0) AS mortes_na_gaiola
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_perdas}
        GROUP BY o.data
        ORDER BY o.data
        """), tuple(parametros_perdas))
        perdas_por_data = {
            item["data"]: {
                "condenacoes": float(item["condenacoes"] or 0),
                "descartes": float(item["descartes"] or 0),
                "mortes_na_gaiola": float(item["mortes_na_gaiola"] or 0)
            }
            for item in cursor.fetchall()
        }

        evolucao_diaria = []
        for data in sorted(ops_por_data.keys()):
            base = ops_por_data.get(data, {})
            perda = perdas_por_data.get(data, {})
            aves_dia = float(base.get("aves_recebidas", 0) or 0)
            mortes_dia = float(base.get("mortes_antes_pendura", 0) or 0) if mortes_legado_aplicavel else 0
            mortes_dia += float(perda.get("mortes_na_gaiola", 0) or 0)
            condenacoes_dia = float(perda.get("condenacoes", 0) or 0)
            descartes_dia = float(perda.get("descartes", 0) or 0)
            total_perdas_dia = mortes_dia + condenacoes_dia + descartes_dia
            aves_viaveis_dia = max(0, aves_dia - total_perdas_dia)
            viabilidade_dia = (aves_viaveis_dia / aves_dia * 100) if aves_dia > 0 else 0

            try:
                data_formatada = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m")
            except Exception:
                data_formatada = data

            evolucao_diaria.append({
                "data": data,
                "data_formatada": data_formatada,
                "aves_recebidas": round(aves_dia, 2),
                "mortes_antes_pendura": round(mortes_dia, 2),
                "condenacoes": round(condenacoes_dia, 2),
                "descartes": round(descartes_dia, 2),
                "total_perdas": round(total_perdas_dia, 2),
                "viabilidade_percentual": round(viabilidade_dia, 2)
            })

        filtros_perdas_sem_setor = list(filtros_op)
        parametros_perdas_sem_setor = list(parametros_op)

        if motivo_filtro and motivo_filtro != "Todos":
            filtros_perdas_sem_setor.append("d.motivo = ?")
            parametros_perdas_sem_setor.append(motivo_filtro)

        if setor_filtro and setor_filtro != "Todos":
            filtros_perdas_sem_setor.append("d.setor = ?")
            parametros_perdas_sem_setor.append(setor_filtro)

        filtros_perdas_sem_setor.append("LOWER(COALESCE(d.unidade, '')) IN ('aves', 'ave', 'unidade', 'unidades')")
        where_setor = " AND ".join(filtros_perdas_sem_setor)

        cursor.execute(q(f"""
        SELECT
            COALESCE(NULLIF(d.setor, ''), 'Sem setor') AS setor,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                THEN d.quantidade ELSE 0 END), 0) AS condenacoes,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                  OR LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN 0 ELSE d.quantidade END), 0) AS descartes,
            COALESCE(SUM(d.quantidade), 0) AS total
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_setor}
        GROUP BY COALESCE(NULLIF(d.setor, ''), 'Sem setor')
        ORDER BY total DESC
        """), tuple(parametros_perdas_sem_setor))

        perdas_por_setor = []
        for item in cursor.fetchall():
            total = float(item["total"] or 0)
            percentual = (total / total_perdas * 100) if total_perdas > 0 else 0
            perdas_por_setor.append({
                "setor": item["setor"],
                "condenacoes": round(float(item["condenacoes"] or 0), 2),
                "descartes": round(float(item["descartes"] or 0), 2),
                "total": round(total, 2),
                "percentual": round(percentual, 2)
            })

        cursor.execute(q(f"""
        SELECT
            COALESCE(NULLIF(d.motivo, ''), 'Sem motivo') AS motivo,
            COALESCE(NULLIF(d.setor, ''), 'Sem setor') AS setor,
            COALESCE(SUM(d.quantidade), 0) AS total
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_perdas}
        GROUP BY COALESCE(NULLIF(d.motivo, ''), 'Sem motivo'), COALESCE(NULLIF(d.setor, ''), 'Sem setor')
        ORDER BY total DESC
        LIMIT 20
        """), tuple(parametros_perdas))

        ranking_motivos = []
        for item in cursor.fetchall():
            total = float(item["total"] or 0)
            percentual = (total / total_perdas * 100) if total_perdas > 0 else 0
            ranking_motivos.append({
                "motivo": item["motivo"],
                "setor": item["setor"],
                "total": round(total, 2),
                "percentual": round(percentual, 2)
            })

        cursor.execute(q(f"""
        SELECT
            o.fornecedor,
            COALESCE(SUM(o.quantidade_aves), 0) AS aves_recebidas,
            COALESCE(SUM(o.mortes_antes_pendura), 0) AS mortes_antes_pendura
        FROM ordens_producao o
        WHERE {where_op}
        GROUP BY o.fornecedor
        ORDER BY o.fornecedor
        """), tuple(parametros_op))
        fornecedores_base = {
            item["fornecedor"]: {
                "aves_recebidas": float(item["aves_recebidas"] or 0),
                "mortes_antes_pendura": float(item["mortes_antes_pendura"] or 0)
            }
            for item in cursor.fetchall()
        }

        cursor.execute(q(f"""
        SELECT
            o.fornecedor,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                THEN d.quantidade ELSE 0 END), 0) AS condenacoes,
            COALESCE(SUM(CASE
                WHEN LOWER(COALESCE(d.categoria, '')) LIKE '%%conden%%'
                  OR LOWER(COALESCE(d.motivo, '')) LIKE '%%conden%%'
                  OR LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN 0 ELSE d.quantidade END), 0) AS descartes,
            COALESCE(SUM(CASE
                WHEN LOWER(TRIM(COALESCE(d.motivo, ''))) = 'morte na gaiola'
                THEN d.quantidade ELSE 0 END), 0) AS mortes_na_gaiola
        FROM apontamentos_descartes d
        JOIN ordens_producao o ON o.id = d.op_id
        WHERE {where_perdas}
        GROUP BY o.fornecedor
        ORDER BY o.fornecedor
        """), tuple(parametros_perdas))
        fornecedores_perdas = {
            item["fornecedor"]: {
                "condenacoes": float(item["condenacoes"] or 0),
                "descartes": float(item["descartes"] or 0),
                "mortes_na_gaiola": float(item["mortes_na_gaiola"] or 0)
            }
            for item in cursor.fetchall()
        }

        comparativo_fornecedores = []
        for fornecedor, base in fornecedores_base.items():
            perdas_fornecedor = fornecedores_perdas.get(fornecedor, {})
            aves_fornecedor = float(base.get("aves_recebidas", 0) or 0)
            mortes_fornecedor = float(base.get("mortes_antes_pendura", 0) or 0) if mortes_legado_aplicavel else 0
            mortes_fornecedor += float(perdas_fornecedor.get("mortes_na_gaiola", 0) or 0)
            condenacoes_fornecedor = float(perdas_fornecedor.get("condenacoes", 0) or 0)
            descartes_fornecedor = float(perdas_fornecedor.get("descartes", 0) or 0)
            total_perdas_fornecedor = mortes_fornecedor + condenacoes_fornecedor + descartes_fornecedor
            viabilidade_fornecedor = ((aves_fornecedor - total_perdas_fornecedor) / aves_fornecedor * 100) if aves_fornecedor > 0 else 0

            comparativo_fornecedores.append({
                "fornecedor": fornecedor,
                "aves_recebidas": round(aves_fornecedor, 2),
                "mortes_antes_pendura": round(mortes_fornecedor, 2),
                "condenacoes": round(condenacoes_fornecedor, 2),
                "descartes": round(descartes_fornecedor, 2),
                "total_perdas": round(total_perdas_fornecedor, 2),
                "viabilidade_percentual": round(viabilidade_fornecedor, 2)
            })

        comparativo_fornecedores = sorted(
            comparativo_fornecedores,
            key=lambda item: item["viabilidade_percentual"],
            reverse=True
        )

        conn.close()

        return {
            "resumo": {
                "aves_recebidas": round(aves_recebidas, 2),
                "mortes_antes_pendura": round(mortes_antes_pendura, 2),
                "condenacoes": round(condenacoes, 2),
                "descartes": round(descartes, 2),
                "total_perdas": round(total_perdas, 2),
                "aves_viaveis": round(aves_viaveis, 2),
                "viabilidade_percentual": round(viabilidade_percentual, 2),
                "total_ops": total_ops
            },
            "evolucao_diaria": evolucao_diaria,
            "perdas_por_setor": perdas_por_setor,
            "ranking_motivos": ranking_motivos,
            "comparativo_fornecedores": comparativo_fornecedores
        }


    @app.route("/relatorio-viabilidade")
    @perfil_permitido("pcp")
    def relatorio_viabilidade():
        hoje = datetime.now().strftime("%Y-%m-%d")
        primeiro_dia_mes = datetime.now().replace(day=1).strftime("%Y-%m-%d")

        data_inicio = normalizar_data_relatorio_viabilidade(
            request.args.get("data_inicio"),
            primeiro_dia_mes
        )
        data_fim = normalizar_data_relatorio_viabilidade(
            request.args.get("data_fim"),
            hoje
        )

        fornecedor_filtro = request.args.get("fornecedor", "Todos") or "Todos"
        motivo_filtro = request.args.get("motivo", "Todos") or "Todos"
        setor_filtro = request.args.get("setor", "Todos") or "Todos"

        opcoes = buscar_opcoes_relatorio_viabilidade(
            data_inicio,
            data_fim,
            fornecedor_filtro
        )

        dados = buscar_dados_relatorio_viabilidade(
            data_inicio,
            data_fim,
            fornecedor_filtro,
            motivo_filtro,
            setor_filtro
        )

        return render_template(
            "relatorio_viabilidade.html",
            data_inicio=data_inicio,
            data_fim=data_fim,
            fornecedor_filtro=fornecedor_filtro,
            motivo_filtro=motivo_filtro,
            setor_filtro=setor_filtro,
            fornecedores=opcoes["fornecedores"],
            motivos=opcoes["motivos"],
            setores=opcoes["setores"],
            resumo=dados["resumo"],
            evolucao_diaria=dados["evolucao_diaria"],
            perdas_por_setor=dados["perdas_por_setor"],
            ranking_motivos=dados["ranking_motivos"],
            comparativo_fornecedores=dados["comparativo_fornecedores"]
        )


    @app.route("/apontamento-descartes", methods=["GET", "POST"])
    @perfil_permitido("qualidade")
    def apontamento_descartes():
        if request.method == "POST":
            try:
                if request.form.get("tipo_apontamento") == "descarte_lote":
                    salvar_apontamentos_descartes_lote(request.form)
                else:
                    salvar_apontamento_descarte(request.form)
                flash("Apontamento de descarte/condenação salvo.")
            except ValueError as erro:
                flash(str(erro))

            return redirect(url_for("apontamento_descartes"))

        return render_template("apontamento_descartes.html", **contexto_apontamento())


    @app.route("/descartes/lote/editar", methods=["GET", "POST"])
    @perfil_permitido("qualidade")
    def editar_descartes_lote():
        ids = ids_do_request("ids")

        if not ids:
            flash("Selecione pelo menos um descarte.")
            return redirect(url_for("consultar_op"))

        registros = obter_registros_por_ids("apontamentos_descartes", ids)

        if not registros:
            flash("Nenhum descarte encontrado.")
            return redirect(url_for("consultar_op"))

        op_id = primeiro_op_id(registros)

        if edicao_bloqueada_por_status(registros):
            flash("Esta OP está encerrada. Edição de descartes bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        if request.method == "POST" and request.form.get("acao") == "salvar":
            categoria = request.form["categoria"]
            motivo = request.form["motivo"]
            unidade = request.form["unidade"]
            observacoes = request.form.get("observacoes", "")

            placeholders = ",".join(["?"] * len(ids))

            conn = conectar()
            cursor = conn.cursor()

            cursor.execute(q(f"""
            UPDATE apontamentos_descartes
            SET categoria = ?,
                motivo = ?,
                unidade = ?,
                observacoes = ?
            WHERE id IN ({placeholders})
            """), (categoria, motivo, unidade, observacoes, *ids))

            conn.commit()
            conn.close()

            flash("Descartes atualizados com sucesso.")
            return redirect(url_for("consultar_op", op_id=op_id))

        return render_template(
            "editar_descartes_lote.html",
            registros=registros,
            ids=ids
        )


    @app.route("/descartes/lote/excluir", methods=["POST"])
    @perfil_permitido("qualidade")
    def excluir_descartes_lote():
        ids = ids_do_request("ids")

        if not ids:
            flash("Selecione pelo menos um descarte.")
            return redirect(url_for("consultar_op"))

        registros = obter_registros_por_ids("apontamentos_descartes", ids)

        if not registros:
            flash("Nenhum descarte encontrado.")
            return redirect(url_for("consultar_op"))

        op_id = primeiro_op_id(registros)

        if edicao_bloqueada_por_status(registros):
            flash("Esta OP está encerrada. Exclusão de descartes bloqueada.")
            return redirect(url_for("consultar_op", op_id=op_id))

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        DELETE FROM apontamentos_descartes
        WHERE id IN ({placeholders})
        """), tuple(ids))

        conn.commit()
        conn.close()

        flash("Descartes excluídos com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    @app.route("/sgi/qualidade")
    @app.route("/sgi/qualidade/verificacoes")
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_qualidade():
        return render_template("sgi_qualidade.html", **qualidade_service.contexto_central_sgi(request.args))

    @app.route("/sgi/qualidade/cadastros/locais", methods=["POST"])
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_cadastrar_local():
        try:
            qualidade_service.cadastrar_local_sgi(request.form)
            flash("Local incluido na Central de Configuracao.")
        except Exception as erro:
            flash(str(erro))
        return redirect(url_for("sgi_qualidade"))

    @app.route("/sgi/qualidade/verificacoes/nova/<tipo>", methods=["GET", "POST"])
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_nova_verificacao(tipo):
        try:
            contexto = qualidade_service.contexto_nova_verificacao(tipo)
            if request.method == "POST":
                verificacao_id = qualidade_service.salvar_verificacao_sgi(
                    tipo, request.form, session["usuario_id"], session.get("nome", "Usuario"))
                flash("Verificacao concluida e registrada no historico.")
                return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=verificacao_id))
            return render_template("sgi_verificacao_form.html", **contexto)
        except Exception as erro:
            flash(str(erro))
            return redirect(url_for("sgi_qualidade"))

    @app.route("/sgi/qualidade/verificacoes/<int:verificacao_id>")
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_verificacao_detalhe(verificacao_id):
        try:
            return render_template("sgi_verificacao_detalhe.html", **qualidade_service.contexto_verificacao(verificacao_id))
        except ValueError as erro:
            flash(str(erro))
            return redirect(url_for("sgi_qualidade"))

    @app.route("/sgi/qualidade/reposicoes/<int:acao_id>/confirmar", methods=["POST"])
    @perfil_permitido("qualidade")
    def sgi_confirmar_reposicao(acao_id):
        qualidade_service.confirmar_reposicao_sgi(
            acao_id, request.form, session["usuario_id"], session.get("nome", "Usuario"))
        flash("Segunda verificacao registrada.")
        return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))

    @app.route("/sgi/qualidade/ncs/<int:nc_id>/decisao-gerencia", methods=["POST"])
    @perfil_permitido("gerencia")
    def sgi_decisao_gerencia(nc_id):
        qualidade_service.decidir_nc_critica(
            nc_id, request.form, session["usuario_id"], session.get("nome", "Usuario"))
        flash("Decisao da Gerencia registrada.")
        return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))

    @app.route("/sgi/qualidade/ncs/<int:nc_id>/eficacia", methods=["POST"])
    @perfil_permitido("qualidade")
    def sgi_validar_eficacia(nc_id):
        qualidade_service.validar_eficacia_sgi(
            nc_id, request.form, session["usuario_id"], session.get("nome", "Usuario"))
        flash("Eficacia registrada. Confira o resultado antes do encerramento.")
        return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))

    @app.route("/sgi/qualidade/ncs/<int:nc_id>/encerrar", methods=["POST"])
    @perfil_permitido("qualidade")
    def sgi_encerrar_nc(nc_id):
        qualidade_service.encerrar_nc_sgi(
            nc_id, session["usuario_id"], session.get("nome", "Usuario"))
        flash("Nao conformidade encerrada definitivamente.")
        return redirect(url_for("sgi_verificacao_detalhe", verificacao_id=int(request.form["verificacao_id"])))

    @app.route("/sgi/qualidade/consolidado")
    @perfil_permitido("qualidade", "pcp", "gerencia")
    def sgi_consolidado_mensal():
        return render_template("sgi_consolidado.html", **qualidade_service.contexto_consolidado(request.args))
