import os
import pytest


@pytest.fixture(scope="module")
def ambiente():
    dsn = os.environ.get("PG_REPROCESSAMENTO_E2E_DSN")
    if not dsn:
        pytest.skip("PostgreSQL descartável não configurado")
    from urllib.parse import urlsplit
    assert urlsplit(dsn).hostname == "127.0.0.1"
    assert urlsplit(dsn).path == "/frigodatta_reprocessamento_e2e"
    os.environ["DATABASE_URL"] = dsn
    from app import app
    from database import transaction
    return app, transaction


def test_galinha_inteira_reseta_formacao_e_encerra_ciclo_2(ambiente):
    app, transaction = ambiente
    from flask import session
    from modules.expedicao.services import registrar_apontamento_embalagem_primaria
    from modules.producao.planejamento_reversao_op import registrar_previa_reprocessamento
    from modules.producao.reprocessamento_op import executar_reprocessamento_op
    from modules.producao.services import buscar_op_por_id

    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ordens_producao (data,sku,fornecedor,quantidade_aves,peso_vivo,peso_medio,
                status,estoque_classificacao)
            VALUES ('2026-11-27','Galinha Inteira','Fixture 129',8,20,2.5,'Aberta','POS_MARCO') RETURNING id
        """)
        op_id = cursor.fetchone()["id"]
    with app.test_request_context("/"):
        session.update(usuario_id=1, nome="Admin E2E", perfil="admin")
        primeiro = registrar_apontamento_embalagem_primaria(
            buscar_op_por_id(op_id), None, pacotes_1_ave=4, pacotes_2_aves=2,
        )
        previa = registrar_previa_reprocessamento(op_id, usuario="Admin E2E", perfil="admin")
        args = dict(usuario="Admin E2E", perfil="admin", motivo="Teste controlado", confirmacao=True)
        for etapa in ("apos_expedicao", "apos_pa", "apos_caixas", "apos_pi", "apos_invalidar_ciclo", "antes_novo_ciclo"):
            def falhar(atual):
                if atual == etapa:
                    raise RuntimeError(atual)
            with pytest.raises(RuntimeError, match=etapa):
                executar_reprocessamento_op(op_id, previa["plano_id"], checkpoint=falhar, **args)
            assert buscar_op_por_id(op_id)["status"] == "Encerrada"
        reset = executar_reprocessamento_op(op_id, previa["plano_id"], **args)
        assert reset["ciclo_atual"] == 2
        assert executar_reprocessamento_op(op_id, previa["plano_id"], **args)["ciclo_atual"] == 2
        segundo = registrar_apontamento_embalagem_primaria(
            buscar_op_por_id(op_id), None, pacotes_1_ave=2, pacotes_2_aves=3,
        )
    assert set(primeiro["codigos_lote"]).isdisjoint(segundo["codigos_lote"])
    assert all("-C2-" in codigo for codigo in segundo["codigos_lote"])
    assert buscar_op_por_id(op_id)["status"] == "Encerrada"
    cliente_http = app.test_client()
    with cliente_http.session_transaction() as sessao:
        sessao.update(usuario_id=1, nome="Admin E2E", perfil="producao")
    assert cliente_http.get(f"/op/{op_id}/reprocessar").status_code == 403
    with cliente_http.session_transaction() as sessao:
        sessao["perfil"] = "admin"
    resposta = cliente_http.get(f"/op/{op_id}/reprocessar")
    assert resposta.status_code == 200 and "Hash da prévia" in resposta.get_data(as_text=True)
    historico = cliente_http.get(f"/op/{op_id}/ciclos/1")
    assert historico.status_code == 200
    assert all(codigo in historico.get_data(as_text=True) for codigo in primeiro["codigos_lote"])
    assert all(codigo not in historico.get_data(as_text=True) for codigo in segundo["codigos_lote"])
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT c.status, count(*) total FROM pa_caixas c
            JOIN pa_caixa_composicao p ON p.caixa_id=c.id WHERE p.op_id=%s GROUP BY c.status""", (op_id,))
        assert {linha["status"]: linha["total"] for linha in cursor.fetchall()} == {"Estornada": 2, "Em estoque": 2}
        cursor.execute("""SELECT count(*) total FROM estoque_eventos e JOIN pa_caixa_composicao p ON p.caixa_id=e.caixa_id
            WHERE p.op_id=%s AND e.acao='ESTORNO_CAIXA_EMBALAGEM' AND e.evento_origem_id IS NOT NULL""", (op_id,))
        assert cursor.fetchone()["total"] == 2


def criar_op_pg(transaction, sku, aves, fornecedor):
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ordens_producao (data,sku,fornecedor,quantidade_aves,peso_vivo,peso_medio,
                status,estoque_classificacao)
            VALUES ('2026-11-27',%s,%s,%s,%s,2.5,'Aberta','POS_MARCO') RETURNING id
        """, (sku, fornecedor, aves, aves * 2.5))
        return cursor.fetchone()["id"]


def semear_caixa_cortada(cursor, op_id, codigo, bandejas):
    cursor.execute("""
        INSERT INTO pa_caixas (codigo_caixa,sku,data_fabricacao,data_validade,peso_bruto,peso_tara,
            peso_liquido,quantidade_bandejas,status,origem,local_estoque_id,estoque_operacional,
            condicao,disponibilidade,zona_estoque,unidade_estoque)
        VALUES (%s,'Galinha Cortada','2026-11-27','2027-11-27',10.5,.5,10,%s,'Em estoque',
            'Embalagem Secundaria',(SELECT id FROM locais_estoque WHERE nome='Abatedouro' LIMIT 1),
            0,'CONFORME','PENDENTE_OP','Conforme','CAIXA') RETURNING id
    """, (codigo, bandejas))
    caixa_id = cursor.fetchone()["id"]
    cursor.execute("INSERT INTO pa_caixa_composicao (caixa_id,op_id,quantidade_bandejas) VALUES (%s,%s,%s)",
                   (caixa_id, op_id, bandejas))
    return caixa_id


def test_113_caixas_sem_pa_resetam_e_novo_ciclo_encerra(ambiente):
    app, transaction = ambiente
    from flask import session
    from modules.expedicao.services import (
        finalizar_embalagem_secundaria_op, registrar_apontamento_embalagem_primaria,
        registrar_caixas_pa_lote, registrar_saida_pi_por_caixa,
    )
    from modules.producao.planejamento_reversao_op import registrar_previa_reprocessamento
    from modules.producao.reprocessamento_op import executar_reprocessamento_op
    from modules.producao.services import buscar_op_por_id

    op_id = criar_op_pg(transaction, "Galinha Cortada", 1500, "Fixture 93")
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO embalagem_primaria_apontamentos (op_id,data_apontamento,sku,quantidade_bandejas)
            VALUES (%s,'2026-11-27','Galinha Cortada',1468) RETURNING id""", (op_id,))
        apontamento_id = cursor.fetchone()["id"]
        cursor.execute("""INSERT INTO estoque_produto_intermediario
            (op_id,tipo,sku,quantidade_bandejas,data_movimentacao,origem,apontamento_origem_id)
            VALUES (%s,'ENTRADA_EMBALAGEM_PRIMARIA','Galinha Cortada',1468,'2026-11-27','Fixture',%s)""",
            (op_id, apontamento_id))
        cursor.execute("""INSERT INTO apontamentos_descartes (op_id,data,setor,categoria,motivo,quantidade,unidade)
            VALUES (%s,'2026-11-27','Embalagem','Descarte','Fixture histórica',44,'aves')""", (op_id,))
        caixas = []
        for indice in range(113):
            bandejas = 10 if indice == 112 else 12
            caixa_id = semear_caixa_cortada(cursor, op_id, f"E2E-{op_id}-C1-{indice}", bandejas)
            caixas.append(caixa_id)
            registrar_saida_pi_por_caixa(cursor, op_id, "Galinha Cortada", bandejas, caixa_id)
        for indice in range(166):
            bandejas = 8 if indice == 165 else 12
            cursor.execute("""INSERT INTO estoque_produto_intermediario
                (op_id,tipo,sku,quantidade_bandejas,data_movimentacao,origem)
                VALUES (%s,'SAIDA_EMBALAGEM_SECUNDARIA','Galinha Cortada',%s,'2026-11-27','Fixture')
                RETURNING id""", (op_id, bandejas))
            origem = cursor.fetchone()["id"]
            cursor.execute("""INSERT INTO estoque_produto_intermediario
                (op_id,tipo,sku,quantidade_bandejas,movimento_origem_id,data_movimentacao,origem)
                VALUES (%s,'ENTRADA_ESTORNO_CAIXA','Galinha Cortada',%s,%s,'2026-11-27','Fixture')""",
                (op_id, bandejas, origem))
    with app.test_request_context("/"):
        session.update(usuario_id=1, nome="Admin E2E", perfil="admin")
        previa = registrar_previa_reprocessamento(op_id, usuario="Admin E2E", perfil="admin")
        resultado = executar_reprocessamento_op(op_id, previa["plano_id"], usuario="Admin E2E",
                                              perfil="admin", motivo="PI incorreto", confirmacao=True)
        assert len(resultado["efeitos"]["pa"]) == 113
        assert not any(item["formacao_origem_id"] for item in resultado["efeitos"]["pa"])
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) total FROM pa_caixas WHERE id=ANY(%s) AND status='Estornada'", (caixas,))
            assert cursor.fetchone()["total"] == 113
            cursor.execute("SELECT count(*) total FROM estoque_eventos WHERE caixa_id=ANY(%s)", (caixas,))
            assert cursor.fetchone()["total"] == 0
            cursor.execute("""INSERT INTO apontamentos_descartes (op_id,data,setor,categoria,motivo,quantidade,unidade)
                VALUES (%s,'2026-11-27','Embalagem','Descarte','Fixture ciclo 2',44,'aves')""", (op_id,))
        registrar_apontamento_embalagem_primaria(buscar_op_por_id(op_id), 1456)
        for bandejas, quantidade in ((12, 121), (4, 1)):
            codigos = registrar_caixas_pa_lote({
                "op_principal": op_id, "bandejas_principal": str(bandejas),
                "pesos_brutos_lote": "\n".join(["10,5"] * quantidade),
                "idempotency_key": f"C2-{op_id}-{bandejas}",
            })
            assert len(codigos) == quantidade
        assert finalizar_embalagem_secundaria_op(op_id)["sucesso"]
    assert buscar_op_por_id(op_id)["status"] == "Encerrada"


def test_documento_compartilhado_preserva_outra_op_e_cmv(ambiente):
    app, transaction = ambiente
    from flask import session
    from modules.cmv.services import registrar_camada, registrar_saida
    from modules.expedicao.estoque_service import DESTINOS_CONTROLADOS, concluir_romaneio, reservar_itens
    from modules.expedicao.palletizacao import adicionar_caixas, criar_pallet
    from modules.expedicao.services import registrar_apontamento_embalagem_primaria
    from modules.producao.planejamento_reversao_op import registrar_previa_reprocessamento
    from modules.producao.reprocessamento_op import executar_reprocessamento_op
    from modules.producao.services import buscar_op_por_id

    alvo = criar_op_pg(transaction, "Galinha Inteira", 4, "Fixture venda A")
    outra = criar_op_pg(transaction, "Galinha Inteira", 4, "Fixture venda B")
    numero = f"E2E-VENDA-{alvo}"
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO clientes (razao_social,tipo_pessoa,status,criado_por,atualizado_por,criado_em,atualizado_em)
            VALUES (%s,'PJ','Ativo','E2E','E2E',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id""",
            (f"Cliente teste {alvo}",))
        cliente = cursor.fetchone()["id"]
        cursor.execute("""INSERT INTO expedicoes (numero_romaneio,data,tipo_movimentacao,origem,destino,status,cliente_id)
            VALUES (%s,'2026-11-27','VENDA_DIRETA','Abatedouro',%s,'Aberto',%s) RETURNING id""",
            (numero, DESTINOS_CONTROLADOS["VENDA_DIRETA"], cliente))
        romaneio = cursor.fetchone()["id"]
        cursor.execute("SELECT id FROM locais_estoque WHERE nome='Abatedouro' LIMIT 1")
        local = cursor.fetchone()["id"]

    with app.test_request_context("/"):
        session.update(usuario_id=1, nome="Admin E2E", perfil="admin")
        caixa_a, caixa_b = [registrar_apontamento_embalagem_primaria(
            buscar_op_por_id(op_id), None, pacotes_1_ave=4,
        )["posicao_ids"][0] for op_id in (alvo, outra)]
        pallet = criar_pallet(usuario="Admin E2E", idempotency_key=f"P-{alvo}", localizacao_atual_id=local)
        adicionar_caixas(pallet["id"], [caixa_a], usuario="Admin E2E", idempotency_key=f"PA-{alvo}")
        reservar_itens(romaneio, [caixa_a], {caixa_a: 2}, pallet_origem_id=pallet["id"],
                       usuario="Admin E2E", idempotency_key=f"RESERVA-{alvo}")
        reservar_itens(romaneio, [caixa_b], {caixa_b: 2})
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""INSERT INTO pedidos_venda (numero,cliente_id,cliente_snapshot,destino,data_pedido,
                responsavel,status,forma_pagamento,condicao_pagamento,criado_por,atualizado_por,criado_em,atualizado_em)
                VALUES (%s,%s,'{}','Teste','2026-11-27','E2E','CONFIRMADO','PIX','A_VISTA',
                    'E2E','E2E',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id""", (numero, cliente))
            pedido_id = cursor.fetchone()["id"]
            cursor.execute("""INSERT INTO pedido_venda_itens (pedido_id,sku,produto_snapshot,quantidade_negociada_mil,
                unidade_comercial,preco_unitario_centavos,valor_bruto_centavos,valor_liquido_centavos,criado_em)
                VALUES (%s,'Galinha Inteira','{}',4000,'PACOTE',1000,4000,4000,CURRENT_TIMESTAMP) RETURNING id""",
                (pedido_id,))
            pedido_item_id = cursor.fetchone()["id"]
            cursor.execute("UPDATE expedicoes SET pedido_venda_id=%s WHERE id=%s", (pedido_id, romaneio))
            cursor.execute("UPDATE expedicao_itens SET pedido_item_id=%s WHERE expedicao_id=%s", (pedido_item_id, romaneio))
        concluir_romaneio(romaneio)
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id,caixa_id FROM expedicao_itens WHERE expedicao_id=%s ORDER BY caixa_id", (romaneio,))
            itens = {item["caixa_id"]: item["id"] for item in cursor.fetchall()}
        produto = f"Galinha Inteira E2E {alvo}"
        for posicao, op_id, custo in ((caixa_a, alvo, 8), (caixa_b, outra, 13)):
            registrar_camada(produto=produto, unidade="PACOTE", data_entrada="2026-11-27",
                             quantidade=2, custo_unitario=custo, origem_tipo="OP", origem_id=str(op_id),
                             op_id=op_id, idempotency_key=f"CAMADA-{op_id}")
            registrar_saida(produto=produto, unidade="PACOTE", data_evento="2026-11-27", documento=numero,
                            quantidade=2, origem_tipo="EXPEDICAO_ITEM", origem_id=str(itens[posicao]),
                            idempotency_key=f"VENDA-{op_id}")
        previa = registrar_previa_reprocessamento(alvo, usuario="Admin E2E", perfil="admin")
        def estado():
            with transaction() as conn:
                cursor = conn.cursor()
                consultas = [
                    ("SELECT * FROM pa_caixas WHERE id=ANY(%s) ORDER BY id", ([caixa_a, caixa_b],)),
                    ("SELECT * FROM expedicao_itens WHERE expedicao_id=%s ORDER BY id", (romaneio,)),
                    ("SELECT * FROM cmv_eventos WHERE documento=%s ORDER BY id", (numero,)),
                    ("SELECT * FROM cmv_camadas WHERE produto=%s ORDER BY id", (produto,)),
                    ("SELECT * FROM op_ciclos WHERE op_id=ANY(%s) ORDER BY id", ([alvo, outra],)),
                    ("SELECT * FROM pedido_venda_atendimentos WHERE expedicao_id=%s ORDER BY expedicao_item_id", (romaneio,)),
                    ("SELECT * FROM estoque_produto_intermediario WHERE op_id=ANY(%s) ORDER BY id", ([alvo, outra],)),
                    ("SELECT * FROM estoque_eventos WHERE caixa_id=ANY(%s) ORDER BY id", ([caixa_a, caixa_b],)),
                    ("SELECT * FROM op_operacoes_auditoria WHERE op_id=ANY(%s) ORDER BY id", ([alvo, outra],)),
                    ("SELECT * FROM pallet_caixas_atuais WHERE pallet_id=%s ORDER BY id", (pallet["id"],)),
                    ("SELECT * FROM pallet_caixa_eventos WHERE pallet_id=%s ORDER BY id", (pallet["id"],)),
                    ("SELECT * FROM pedido_venda_eventos WHERE pedido_id=%s ORDER BY id", (pedido_id,)),
                    ("SELECT * FROM ordens_producao WHERE id=ANY(%s) ORDER BY id", ([alvo, outra],)),
                    ("SELECT * FROM op_ciclo_registros_invalidados WHERE ciclo_id=%s ORDER BY tabela,registro_id",
                     (previa["snapshot"]["ciclo"]["id"],)),
                ]
                dados = []
                for sql, params in consultas:
                    cursor.execute(sql, params)
                    dados.append([dict(linha) for linha in cursor.fetchall()])
                return dados
        antes = estado()
        args = dict(usuario="Admin E2E", perfil="admin", motivo="Corrigir a OP alvo", confirmacao=True)
        for etapa in ("apos_venda", "apos_expedicao", "apos_pa", "apos_caixas", "apos_pi",
                      "apos_invalidar_ciclo", "antes_novo_ciclo"):
            def falhar(atual):
                if atual == etapa:
                    raise RuntimeError(atual)
            with pytest.raises(RuntimeError, match=etapa):
                executar_reprocessamento_op(alvo, previa["plano_id"], checkpoint=falhar, **args)
            assert estado() == antes
        resultado = executar_reprocessamento_op(alvo, previa["plano_id"], **args)
        assert resultado["ciclo_atual"] == 2
        depois = estado()
        assert depois[0][1] == antes[0][1]
        assert next(i for i in depois[1] if i["caixa_id"] == caixa_b) == next(
            i for i in antes[1] if i["caixa_id"] == caixa_b
        )
        assert next(i for i in depois[1] if i["caixa_id"] == caixa_a)["ativo"] == 0
        assert depois[2][:2] == antes[2]
        assert len(depois[2]) == 3 and depois[2][-1]["custo_total"] == -16
        assert depois[3][1] == antes[3][1]
        assert depois[3][0]["status"] == "INVALIDADA_REPROCESSAMENTO"
        assert depois[4][1] == antes[4][1]
        assert depois[5][0]["status"] == "ESTORNADO"
        assert depois[5][1] == antes[5][1]
        assert depois[9] == []
        assert depois[12][1] == antes[12][1]
        assert executar_reprocessamento_op(alvo, previa["plano_id"], **args) == resultado
        assert estado() == depois
        novo = registrar_apontamento_embalagem_primaria(buscar_op_por_id(alvo), None, pacotes_2_aves=2)
        assert "-C2-" in novo["codigos_lote"][0]
        assert buscar_op_por_id(alvo)["status"] == "Encerrada"
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM expedicoes WHERE id=%s", (romaneio,))
        assert cursor.fetchone()["status"] == "Concluído"


@pytest.mark.parametrize(("referencia", "itens_alvo", "compartilhados"), [(123, 8, 3), (124, 7, 5)])
def test_simulacao_romaneios_historicos(ambiente, referencia, itens_alvo, compartilhados):
    app, transaction = ambiente
    from flask import session
    from modules.expedicao.estoque_service import DESTINOS_CONTROLADOS, concluir_romaneio, reservar_itens
    from modules.expedicao.services import registrar_apontamento_embalagem_primaria
    from modules.producao.planejamento_reversao_op import registrar_previa_reprocessamento
    from modules.producao.reprocessamento_op import executar_reprocessamento_op
    from modules.producao.services import buscar_op_por_id

    alvo = criar_op_pg(transaction, "Galinha Inteira", itens_alvo, f"Simulação {referencia}")
    outra = criar_op_pg(transaction, "Galinha Inteira", compartilhados, "Outra OP")
    with app.test_request_context("/"):
        session.update(usuario_id=1, nome="Admin E2E", perfil="admin")
        caixas = [registrar_apontamento_embalagem_primaria(
            buscar_op_por_id(op_id), None, pacotes_1_ave=aves,
        )["posicao_ids"][0] for op_id, aves in ((alvo, itens_alvo), (outra, compartilhados))]
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""INSERT INTO clientes (razao_social,tipo_pessoa,status,criado_por,atualizado_por,criado_em,atualizado_em)
                VALUES (%s,'PJ','Ativo','E2E','E2E',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id""",
                (f"Cliente simulação {referencia}",))
            cliente = cursor.fetchone()["id"]
        documentos = []
        for indice in range(itens_alvo):
            with transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("""INSERT INTO expedicoes (numero_romaneio,data,tipo_movimentacao,origem,destino,status,cliente_id)
                    VALUES (%s,'2026-11-27','VENDA_DIRETA','Abatedouro',%s,'Aberto',%s) RETURNING id""",
                    (f"E2E-{referencia}-{alvo}-{indice}", DESTINOS_CONTROLADOS["VENDA_DIRETA"], cliente))
                documento = cursor.fetchone()["id"]
                documentos.append(documento)
            selecionadas = caixas if indice < compartilhados else caixas[:1]
            reservar_itens(documento, selecionadas, dict.fromkeys(selecionadas, 1))
            concluir_romaneio(documento)
        previa = registrar_previa_reprocessamento(alvo, usuario="Admin E2E", perfil="admin")
        assert previa["snapshot"]["executavel"], previa["snapshot"]["impedimentos"]
        assert sum(bool(doc["itens_ativos_fora_op"]) for doc in previa["snapshot"]["documentos"]) == compartilhados
        resultado = executar_reprocessamento_op(
            alvo, previa["plano_id"], usuario="Admin E2E", perfil="admin",
            motivo=f"Simular reprocessamento da OP {referencia}", confirmacao=True,
        )
        assert len(resultado["efeitos"]["expedicao"]) == itens_alvo
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""SELECT caixa_id,ativo,COUNT(*) total FROM expedicao_itens
                WHERE expedicao_id=ANY(%s) GROUP BY caixa_id,ativo ORDER BY caixa_id""", (documentos,))
            assert [(item["caixa_id"], item["ativo"], item["total"]) for item in cursor.fetchall()] == [
                (caixas[0], 0, itens_alvo), (caixas[1], 1, compartilhados),
            ]
            cursor.execute("""SELECT caixa_id,COUNT(*) total FROM estoque_eventos
                WHERE expedicao_id=ANY(%s) AND acao='ESTORNO_ROMANEIO'
                  AND evento_origem_id IS NOT NULL GROUP BY caixa_id""", (documentos,))
            assert [dict(item) for item in cursor.fetchall()] == [{"caixa_id": caixas[0], "total": itens_alvo}]
        assert buscar_op_por_id(outra)["status"] == "Encerrada"
