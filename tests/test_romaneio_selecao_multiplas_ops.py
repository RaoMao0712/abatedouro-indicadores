"""Seleção pontual de caixas do romaneio por múltiplas OPs e peso."""

import os
from pathlib import Path
import inspect
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARQUIVO_BANCO = tempfile.NamedTemporaryFile(
    prefix="frigodatta-romaneio-multiplas-ops-", suffix=".db", delete=False
)
ARQUIVO_BANCO.close()
os.environ["DB_NAME"] = ARQUIVO_BANCO.name
os.environ.pop("DATABASE_URL", None)

from flask import Flask  # noqa: E402

from database import conectar, q  # noqa: E402
import modules.expedicao.estoque_service as estoque_service  # noqa: E402
from modules.expedicao.palletizacao import (  # noqa: E402
    adicionar_caixas, criar_estrutura_palletizacao, criar_pallet, reservar_pallet_no_romaneio,
    resumo_pallet_para_romaneio,
)
from modules.expedicao.estoque_service import (  # noqa: E402
    atualizar_reserva_quantitativa,
    buscar_caixas_elegiveis_op,
    buscar_caixas_por_op_e_peso,
    buscar_op_para_romaneio,
    buscar_saldos_quantitativos_op,
    concluir_romaneio,
    criar_tabelas_estoque_confiavel,
    remover_item_reservado,
    reservar_itens,
)
from modules.expedicao.routes import register_expedicao_routes  # noqa: E402
from modules.expedicao.services import (  # noqa: E402
    buscar_itens_expedicao,
    calcular_resumo_itens_expedicao,
    criar_tabelas_expedicao,
    criar_tabelas_estoque_pi_pa,
)


def executar(sql, parametros=()):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(sql), parametros)
    conn.commit()
    ultimo_id = cursor.lastrowid
    conn.close()
    return ultimo_id


def consultar(sql, parametros=()):
    conn = conectar()
    linhas = conn.execute(q(sql), parametros).fetchall()
    conn.close()
    return linhas


class SelecaoMultiplasOpsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = conectar()
        conn.executescript("""
        CREATE TABLE ordens_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL,
            fornecedor TEXT NOT NULL, quantidade_aves INTEGER NOT NULL,
            mortes_antes_pendura INTEGER DEFAULT 0, peso_vivo REAL NOT NULL,
            peso_medio REAL NOT NULL, status TEXT DEFAULT 'Encerrada',
            sku TEXT DEFAULT 'Galinha Cortada'
        );
        CREATE TABLE apontamentos_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER NOT NULL,
            data TEXT, setor TEXT, quantidade REAL DEFAULT 0,
            unidade TEXT NOT NULL, observacoes TEXT
        );
        """)
        conn.commit()
        conn.close()
        criar_tabelas_expedicao()
        criar_tabelas_estoque_pi_pa()
        criar_tabelas_estoque_confiavel()
        criar_estrutura_palletizacao()
        cls.local_abatedouro = consultar(
            "SELECT id FROM locais_estoque WHERE nome='Abatedouro'"
        )[0]["id"]
        cls.local_lsm = consultar(
            "SELECT id FROM locais_estoque WHERE nome='Câmara Fria LSM'"
        )[0]["id"]

        cls.app = Flask(__name__, template_folder=str(ROOT / "templates"))
        cls.app.secret_key = "teste"
        cls.app.config["TESTING"] = True
        cls.app.jinja_env.filters["br_numero"] = (
            lambda valor, casas=2: f"{float(valor or 0):.{int(casas)}f}"
        )
        cls.app.url_build_error_handlers.append(lambda error, endpoint, values: "#")
        cls.app.add_url_rule("/dashboard", "dashboard", lambda: "dashboard")
        cls.app.add_url_rule("/login", "login", lambda: "login")
        cls.app.add_url_rule("/consultar-op", "consultar_op", lambda: "op")
        cls.app.add_url_rule("/apontamento-descartes", "apontamento_descartes", lambda: "qualidade")
        register_expedicao_routes(cls.app)

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(ARQUIVO_BANCO.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        conn = conectar()
        for tabela in (
            "pallet_caixas_atuais",
            "estoque_eventos", "expedicao_itens", "pa_caixa_composicao",
            "pa_caixas", "expedicoes", "ordens_producao",
        ):
            conn.execute(f"DELETE FROM {tabela}")
        conn.commit()
        conn.close()
        self.op83 = self.criar_op(83)
        self.op84 = self.criar_op(84)
        self.romaneio = self.criar_romaneio("ROM-MULTI-1")

    def criar_op(self, numero):
        executar("""
        INSERT INTO ordens_producao (
            id, data, fornecedor, quantidade_aves, peso_vivo, peso_medio, status, sku
        ) VALUES (?, '2026-09-02', 'Fornecedor', 100, 250, 2.5, 'Encerrada', 'Galinha Cortada')
        """, (numero,))
        return numero

    def criar_romaneio(self, numero):
        return executar("""
        INSERT INTO expedicoes (
            numero_romaneio, data, tipo_movimentacao, tipo_saida, origem, destino,
            responsavel, status, criado_por, perfil_criacao
        ) VALUES (?, '2026-09-02', 'TRANSFERENCIA', 'TRANSFERENCIA_LSM',
                  'Abatedouro', 'Câmara Fria LSM', 'PCP', 'Aberto', 'PCP', 'pcp')
        """, (numero,))

    def criar_caixa(self, codigo, op_id, bruto, liquido, *, disponibilidade="DISPONIVEL",
                    condicao="CONFORME", operacional=1, status="Em estoque"):
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, peso_bruto,
            peso_tara, peso_liquido, quantidade_bandejas, status, origem,
            local_estoque_id, estoque_operacional, condicao, disponibilidade,
            zona_estoque, unidade_estoque, apresentacao
        ) VALUES (?, 'Galinha Cortada', '2026-09-02', '2027-09-02', ?, 0.5, ?,
                  12, ?, 'Embalagem Secundária', ?, ?, ?, ?, 'Conforme', 'CAIXA', 'Caixa')
        """, (codigo, bruto, liquido, status, self.local_abatedouro,
              operacional, condicao, disponibilidade))
        executar("""
        INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas)
        VALUES (?, ?, 12)
        """, (caixa_id, op_id))
        return caixa_id

    def criar_saldo_quantitativo(self, codigo, op_id, pacotes, aves_por_pacote=1,
                                  *, disponibilidade="DISPONIVEL", condicao="CONFORME"):
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, status, origem,
            local_estoque_id, estoque_operacional, condicao, disponibilidade,
            zona_estoque, unidade_estoque, apresentacao, galinhas_por_pacote,
            quantidade_pacotes, quantidade_galinhas, quantidade_pacotes_reservados
        ) VALUES (?, 'Produto configurado', '2026-09-02', '2027-09-02', 'Em estoque',
                  'Embalagem Primária', ?, 1, ?, ?, 'Conforme', 'PACOTE', ?, ?, ?, ?, 0)
        """, (codigo, self.local_abatedouro, condicao, disponibilidade,
              f"Pacote oficial com {aves_por_pacote}", aves_por_pacote,
              pacotes, pacotes * aves_por_pacote))
        executar("""
        INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas)
        VALUES (?, ?, 0)
        """, (caixa_id, op_id))
        return caixa_id

    def cliente(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": "PCP", "perfil": "pcp"})
        return cliente

    def test_carrega_uma_e_varias_ops_com_caixas_imediatamente(self):
        caixa_83 = self.criar_caixa("CX-CARGA-83", 83, 3, 2.5)
        caixa_84 = self.criar_caixa("CX-CARGA-84", 84, 4, 3.5)
        self.assertEqual(buscar_op_para_romaneio(self.romaneio, self.op83)["id"], 83)
        self.assertEqual(buscar_op_para_romaneio(self.romaneio, self.op84)["id"], 84)
        cliente = self.cliente()
        carga_83 = cliente.get(f"/expedicao/{self.romaneio}/selecao-ops/83").get_json()
        carga_84 = cliente.get(f"/expedicao/{self.romaneio}/selecao-ops/84").get_json()
        self.assertEqual([item["id"] for item in carga_83["caixas"]], [caixa_83])
        self.assertEqual([item["id"] for item in carga_84["caixas"]], [caixa_84])
        texto = self.cliente().get(f"/expedicao/{self.romaneio}").get_data(as_text=True)
        self.assertIn("Carregar OP", texto)
        self.assertNotIn("CX-", texto)

    def test_op_inexistente_e_estado_do_romaneio_sao_validados(self):
        with self.assertRaisesRegex(ValueError, "OP não encontrada"):
            buscar_op_para_romaneio(self.romaneio, 999)
        executar("UPDATE expedicoes SET status='Concluído' WHERE id=?", (self.romaneio,))
        with self.assertRaisesRegex(ValueError, "abertos"):
            buscar_op_para_romaneio(self.romaneio, self.op83)

    def test_pesquisa_por_bruto_liquido_virgula_ponto_e_equivalencia(self):
        bruto = self.criar_caixa("CX-BRUTO", 83, 2.5, 2.0)
        liquido = self.criar_caixa("CX-LIQ", 83, 3.0, 2.5)
        for peso in ("2,5", "2.5", "2,500", "2.500"):
            ids = {item["id"] for item in buscar_caixas_por_op_e_peso(self.romaneio, 83, peso)}
            self.assertEqual(ids, {bruto, liquido})

    def test_pesquisa_normaliza_real_legado_na_precisao_oficial(self):
        caixa = self.criar_caixa("CX-REAL-LEGADO", 83, 3.1000001, 2.3500001)
        encontrados = buscar_caixas_por_op_e_peso(self.romaneio, 83, "2,350")
        self.assertEqual([item["id"] for item in encontrados], [caixa])

    def test_pesquisa_isolada_por_op_retorna_todas_as_correspondencias(self):
        ids_83 = {self.criar_caixa(f"CX-83-{i}", 83, 2.85, 2.35) for i in range(3)}
        self.criar_caixa("CX-84", 84, 2.85, 2.35)
        encontrados = buscar_caixas_por_op_e_peso(self.romaneio, 83, "2,350")
        self.assertEqual({item["id"] for item in encontrados}, ids_83)

    def test_peso_vazio_restaura_lista_e_rejeita_valores_invalidos(self):
        caixa = self.criar_caixa("CX-FILTRO-VAZIO", 83, 3, 2.5)
        self.assertEqual(
            [item["id"] for item in buscar_caixas_por_op_e_peso(self.romaneio, 83, "")],
            [caixa],
        )
        for peso in ("0", "-1", "abc", "2,5004"):
            with self.subTest(peso=peso), self.assertRaises(ValueError):
                buscar_caixas_por_op_e_peso(self.romaneio, 83, peso)

    def test_lista_completa_tem_pesos_canonicos_e_ordem_estavel(self):
        segunda = self.criar_caixa("CX-SEGUNDA", 83, 3.1000001, 2.3500001)
        primeira = self.criar_caixa("CX-PRIMEIRA", 83, 3.1, 2.35)
        caixas = buscar_caixas_elegiveis_op(self.romaneio, 83)
        self.assertEqual([item["id"] for item in caixas], [segunda, primeira])
        self.assertTrue(all(item["peso_bruto_canonico"] == "3.100" for item in caixas))
        self.assertTrue(all(item["peso_liquido_canonico"] == "2.350" for item in caixas))

    def test_indisponiveis_estornadas_consumidas_reservadas_e_bloqueadas_nao_aparecem(self):
        self.criar_caixa("CX-RES", 83, 3, 2.5, disponibilidade="RESERVADO")
        self.criar_caixa("CX-BLOQ", 83, 3, 2.5, disponibilidade="BLOQUEADO", condicao="NAO_CONFORME")
        self.criar_caixa("CX-EXP", 83, 3, 2.5, disponibilidade="EXPEDIDO", status="Expedido")
        self.criar_caixa("CX-EST", 83, 3, 2.5, disponibilidade="DISPONIVEL", status="Estornado")
        self.criar_caixa("CX-LEG", 83, 3, 2.5, operacional=0)
        self.assertEqual(buscar_caixas_por_op_e_peso(self.romaneio, 83, "2.5"), [])

    def test_vinculo_ativo_inconsistente_falha_fechado_na_listagem(self):
        caixa = self.criar_caixa("CX-JA-VINCULADA", 83, 3, 2.5)
        outro = self.criar_romaneio("ROM-VINCULO-ATIVO")
        reservar_itens(outro, [caixa], op_id_esperada=83)
        executar("""
        UPDATE pa_caixas
        SET disponibilidade='DISPONIVEL', reservado_expedicao_id=NULL
        WHERE id=?
        """, (caixa,))
        self.assertEqual(buscar_caixas_elegiveis_op(self.romaneio, 83), [])

    def test_pesquisa_nao_seleciona_automaticamente(self):
        caixa = self.criar_caixa("CX-SEM-AUTO", 83, 3, 2.5)
        buscar_caixas_por_op_e_peso(self.romaneio, 83, "2.5")
        self.assertEqual(consultar("SELECT * FROM expedicao_itens"), [])
        self.assertEqual(consultar("SELECT disponibilidade FROM pa_caixas WHERE id=?", (caixa,))[0][0], "DISPONIVEL")

    def test_pesquisas_sucessivas_e_ops_diferentes_acumulam_sem_duplicar(self):
        a = self.criar_caixa("CX-83-A", 83, 2.85, 2.35)
        b = self.criar_caixa("CX-83-B", 83, 2.91, 2.41)
        c = self.criar_caixa("CX-84-A", 84, 2.85, 2.35)
        reservar_itens(self.romaneio, [a], op_id_esperada=83)
        reservar_itens(self.romaneio, [b], op_id_esperada=83)
        reservar_itens(self.romaneio, [c], op_id_esperada=84)
        itens = buscar_itens_expedicao(self.romaneio)
        self.assertEqual({item["caixa_id"] for item in itens}, {a, b, c})
        self.assertEqual({item["op_id"] for item in itens}, {83, 84})
        with self.assertRaises(ValueError):
            reservar_itens(self.romaneio, [a], op_id_esperada=83)

    def test_adulteracao_de_caixa_de_outra_op_e_rejeitada(self):
        caixa = self.criar_caixa("CX-84-MANUAL", 84, 3, 2.5)
        with self.assertRaisesRegex(ValueError, "não pertence"):
            reservar_itens(self.romaneio, [caixa], op_id_esperada=83)
        self.assertEqual(consultar("SELECT * FROM expedicao_itens"), [])

    def test_rollback_integral_se_uma_caixa_for_invalida(self):
        valida = self.criar_caixa("CX-VALIDA", 83, 3, 2.5)
        outra_op = self.criar_caixa("CX-OUTRA", 84, 3, 2.5)
        with self.assertRaises(ValueError):
            reservar_itens(self.romaneio, [valida, outra_op], op_id_esperada=83)
        self.assertEqual(consultar("SELECT * FROM expedicao_itens"), [])
        situacoes = consultar("SELECT disponibilidade FROM pa_caixas ORDER BY id")
        self.assertTrue(all(item[0] == "DISPONIVEL" for item in situacoes))

    def test_concorrencia_impede_mesma_caixa_em_dois_romaneios(self):
        caixa = self.criar_caixa("CX-CONCORRENTE", 83, 3, 2.5)
        outro = self.criar_romaneio("ROM-MULTI-2")
        reservar_itens(self.romaneio, [caixa], op_id_esperada=83)
        with self.assertRaisesRegex(ValueError, "disponivel|reservado"):
            reservar_itens(outro, [caixa], op_id_esperada=83)
        self.assertEqual(len(consultar("SELECT * FROM expedicao_itens")), 1)

    def test_remover_op_exige_decisao_na_interface_e_remove_caixas_atomicamente(self):
        a = self.criar_caixa("CX-RM-A", 83, 3, 2.5)
        b = self.criar_caixa("CX-RM-B", 83, 3, 2.5)
        reservar_itens(self.romaneio, [a, b], op_id_esperada=83)
        cliente = self.cliente()
        recusada = cliente.delete(f"/expedicao/{self.romaneio}/selecao-ops/83")
        self.assertEqual(recusada.status_code, 400)
        removida = cliente.delete(
            f"/expedicao/{self.romaneio}/selecao-ops/83",
            json={"confirmar_remocao_caixas": True},
        )
        self.assertEqual(set(removida.get_json()["caixa_ids"]), {a, b})
        historico = consultar("""
            SELECT caixa_id,ativo,removido_em,removido_por,motivo_remocao
            FROM expedicao_itens ORDER BY id
        """)
        self.assertEqual([item["caixa_id"] for item in historico], [a, b])
        self.assertTrue(all(item["ativo"] == 0 for item in historico))
        self.assertTrue(all(item["removido_em"] for item in historico))
        self.assertTrue(all(item["removido_por"] for item in historico))
        self.assertTrue(all(
            item["motivo_remocao"] == estoque_service.MOTIVO_REMOCAO_RESERVA
            for item in historico
        ))
        texto = (ROOT / "templates" / "romaneio_detalhe.html").read_text(encoding="utf-8")
        self.assertIn("também retirará esses itens", texto)

    def test_op_quantitativa_carrega_saldo_sem_reservar_automaticamente(self):
        saldo_id = self.criar_saldo_quantitativo("GI-OP83-V1", 83, 240)
        resposta = self.cliente().get(
            f"/expedicao/{self.romaneio}/selecao-ops/83"
        ).get_json()
        self.assertEqual(resposta["caixas"], [])
        self.assertTrue(resposta["modalidades"]["controle_quantidade"])
        self.assertFalse(resposta["modalidades"]["controle_caixas"])
        self.assertIsNone(resposta["mensagem"])
        self.assertEqual(resposta["saldos_quantitativos"][0]["id"], saldo_id)
        self.assertEqual(resposta["saldos_quantitativos"][0]["quantidade_disponivel_aves"], 240)
        self.assertEqual(resposta["saldos_quantitativos"][0]["quantidade_selecionada_aves"], 0)
        self.assertEqual(consultar("SELECT * FROM expedicao_itens"), [])
        self.assertEqual(calcular_resumo_itens_expedicao([])["total_itens"], 0)

    def test_reserva_80_aves_de_240_mantem_160_disponiveis(self):
        saldo_id = self.criar_saldo_quantitativo("GI-PARCIAL", 83, 240)
        retorno = atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, "80")
        self.assertEqual(retorno["quantidade_selecionada_aves"], 80)
        self.assertEqual(retorno["quantidade_disponivel_aves"], 160)
        itens = buscar_itens_expedicao(self.romaneio)
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["op_id"], 83)
        self.assertEqual(itens[0]["quantidade_galinhas"], 80)
        self.assertEqual(itens[0]["quantidade_pacotes"], 80)
        saldo = buscar_saldos_quantitativos_op(self.romaneio, 83)[0]
        self.assertEqual(saldo["quantidade_disponivel_aves"], 160)
        self.assertEqual(saldo["limite_edicao_aves"], 240)

    def test_edicao_substitui_quantidade_sem_duplicar_e_devolve_saldo(self):
        saldo_id = self.criar_saldo_quantitativo("GI-EDICAO", 83, 240)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 80)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 100)
        self.assertEqual(len(buscar_itens_expedicao(self.romaneio)), 1)
        self.assertEqual(buscar_itens_expedicao(self.romaneio)[0]["quantidade_galinhas"], 100)
        reduzir = atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 60)
        self.assertEqual(reduzir["quantidade_disponivel_aves"], 180)
        self.assertEqual(buscar_itens_expedicao(self.romaneio)[0]["quantidade_galinhas"], 60)
        eventos_antes = consultar("SELECT COUNT(*) AS total FROM estoque_eventos")[0]["total"]
        repetir = atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 60)
        eventos_depois = consultar("SELECT COUNT(*) AS total FROM estoque_eventos")[0]["total"]
        self.assertEqual(repetir["quantidade_disponivel_aves"], 180)
        self.assertEqual(eventos_depois, eventos_antes)
        self.assertEqual(consultar(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (saldo_id,)
        )[0][0], 60)

    def test_remocao_quantitativa_libera_integralmente_a_reserva(self):
        saldo_id = self.criar_saldo_quantitativo("GI-REMOVER", 83, 100)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 40)
        remover_item_reservado(self.romaneio, saldo_id, op_id_esperada=83)
        self.assertEqual(buscar_itens_expedicao(self.romaneio), [])
        posicao = consultar(
            "SELECT quantidade_pacotes_reservados,disponibilidade FROM pa_caixas WHERE id=?",
            (saldo_id,),
        )[0]
        self.assertEqual(posicao["quantidade_pacotes_reservados"], 0)
        self.assertEqual(posicao["disponibilidade"], "DISPONIVEL")

    def test_remover_op_ignora_item_quantitativo_ja_inativo(self):
        saldo_id = self.criar_saldo_quantitativo("GI-INATIVO", 83, 100)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 40)
        remover_item_reservado(self.romaneio, saldo_id, op_id_esperada=83)
        self.assertEqual(
            estoque_service.remover_itens_reservados_op(self.romaneio, 83), []
        )
        self.assertEqual(consultar(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (saldo_id,)
        )[0][0], 0)

    def test_edicao_obsoleta_nao_recria_reserva_removida(self):
        saldo_id = self.criar_saldo_quantitativo("GI-EDICAO-OBSOLETA", 83, 240)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 80, 0)
        estoque_service.remover_itens_reservados_op(self.romaneio, 83)

        with self.assertRaisesRegex(ValueError, "alterada ou removida"):
            atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 100, 80)

        self.assertEqual(buscar_itens_expedicao(self.romaneio), [])
        self.assertEqual(consultar(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (saldo_id,)
        )[0][0], 0)

    def test_endpoint_retorna_409_para_edicao_obsoleta(self):
        saldo_id = self.criar_saldo_quantitativo("GI-CONFLITO-HTTP", 83, 240)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 80, 0)
        estoque_service.remover_itens_reservados_op(self.romaneio, 83)

        resposta = self.cliente().put(
            f"/expedicao/{self.romaneio}/selecao-ops/83/saldos/{saldo_id}",
            json={"quantidade_aves": 100, "quantidade_anterior_aves": 80},
        )

        self.assertEqual(resposta.status_code, 409)
        self.assertIn("Recarregue a OP", resposta.get_json()["mensagem"])

    def test_quantidade_anterior_invalida_e_rejeitada_sem_mutacao(self):
        saldo_id = self.criar_saldo_quantitativo("GI-VERSAO-INVALIDA", 83, 240)
        with self.assertRaisesRegex(ValueError, "quantidade anterior"):
            atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 80, "inválida")
        self.assertEqual(buscar_itens_expedicao(self.romaneio), [])

    def test_remocao_integral_revalida_romaneio_fechado_sob_lock(self):
        saldo_id = self.criar_saldo_quantitativo("GI-ROMANEIO-FECHADO", 83, 240)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 80, 0)
        executar("UPDATE expedicoes SET status='Concluído' WHERE id=?", (self.romaneio,))
        with self.assertRaisesRegex(ValueError, "abertos"):
            estoque_service.remover_itens_reservados_op(self.romaneio, 83)
        self.assertEqual(consultar(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (saldo_id,)
        )[0][0], 80)

    def test_retry_da_remocao_da_op_e_idempotente(self):
        saldo_id = self.criar_saldo_quantitativo("GI-RETRY", 83, 100)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 80)
        eventos_antes = consultar("SELECT COUNT(*) total FROM estoque_eventos")[0]["total"]

        self.assertEqual(
            estoque_service.remover_itens_reservados_op(self.romaneio, 83), [saldo_id]
        )
        self.assertEqual(
            estoque_service.remover_itens_reservados_op(self.romaneio, 83), []
        )

        eventos_depois = consultar("SELECT COUNT(*) total FROM estoque_eventos")[0]["total"]
        self.assertEqual(eventos_depois - eventos_antes, 1)
        self.assertEqual(consultar(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (saldo_id,)
        )[0][0], 0)

    def test_remocao_da_op_faz_rollback_se_evento_falhar(self):
        saldo_id = self.criar_saldo_quantitativo("GI-ROLLBACK-EVENTO", 83, 100)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 80)
        eventos_antes = consultar("SELECT COUNT(*) total FROM estoque_eventos")[0]["total"]

        with patch.object(estoque_service, "_inserir_evento", side_effect=RuntimeError("falha")):
            with self.assertRaisesRegex(RuntimeError, "falha"):
                estoque_service.remover_itens_reservados_op(self.romaneio, 83)

        itens = buscar_itens_expedicao(self.romaneio)
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["quantidade_galinhas"], 80)
        self.assertEqual(consultar(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (saldo_id,)
        )[0][0], 80)
        self.assertEqual(
            consultar("SELECT COUNT(*) total FROM estoque_eventos")[0]["total"],
            eventos_antes,
        )

    def test_remocao_da_op_faz_rollback_se_inativacao_falhar(self):
        saldo_id = self.criar_saldo_quantitativo("GI-ROLLBACK-INATIVACAO", 83, 100)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 80)
        executar("""
        CREATE TRIGGER falhar_inativacao_reserva BEFORE UPDATE OF ativo ON expedicao_itens
        WHEN NEW.ativo=0
        BEGIN SELECT RAISE(ABORT, 'falha simulada na inativacao'); END
        """)
        try:
            with self.assertRaisesRegex(Exception, "falha simulada na inativacao"):
                estoque_service.remover_itens_reservados_op(self.romaneio, 83)
        finally:
            executar("DROP TRIGGER falhar_inativacao_reserva")

        self.assertEqual(len(buscar_itens_expedicao(self.romaneio)), 1)
        self.assertEqual(consultar(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (saldo_id,)
        )[0][0], 80)

    def test_remocao_integral_preserva_historico_e_evento_rastreavel(self):
        saldo_id = self.criar_saldo_quantitativo("GI-HISTORICO", 83, 100)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 40)
        item_antes = dict(consultar(
            "SELECT * FROM expedicao_itens WHERE expedicao_id=? AND caixa_id=?",
            (self.romaneio, saldo_id),
        )[0])

        estoque_service.remover_itens_reservados_op(self.romaneio, 83)

        item_depois = dict(consultar(
            "SELECT * FROM expedicao_itens WHERE id=?", (item_antes["id"],)
        )[0])
        for campo in ("expedicao_id", "caixa_id", "op_id", "sku", "pedido_item_id"):
            self.assertEqual(item_depois.get(campo), item_antes.get(campo))
        self.assertEqual(item_depois["ativo"], 0)
        evento = consultar("""
            SELECT justificativa,observacao,idempotency_key
            FROM estoque_eventos WHERE acao='REMOCAO_RESERVA' AND caixa_id=?
        """, (saldo_id,))[-1]
        self.assertEqual(evento["justificativa"], estoque_service.MOTIVO_REMOCAO_RESERVA)
        self.assertIn(f'"expedicao_item_id": {item_antes["id"]}', evento["observacao"])
        self.assertIn('"op_id": 83', evento["observacao"])
        self.assertTrue(evento["idempotency_key"].startswith(
            f'REMOCAO_RESERVA-{item_antes["id"]}:ORIGEM:'
        ))

    def test_protocolo_de_locks_declara_ordem_canonica_e_deterministica(self):
        for funcao in (
            estoque_service.atualizar_reserva_quantitativa,
            estoque_service.remover_item_reservado,
            estoque_service.remover_itens_reservados_op,
        ):
            fonte = inspect.getsource(funcao)
            self.assertLess(fonte.index("FROM expedicoes"), fonte.index("FROM expedicao_itens"))
            self.assertLess(fonte.index("FROM expedicao_itens"), fonte.index("FROM pa_caixas"))
            self.assertIn("FOR UPDATE", fonte)
        fonte_lote = inspect.getsource(estoque_service.remover_itens_reservados_op)
        self.assertIn("sorted({int(item", fonte_lote)

    def test_remover_op_com_multiplos_saldos_preserva_outra_op_e_caixa(self):
        saldo_83_a = self.criar_saldo_quantitativo("GI-83-A", 83, 100)
        saldo_83_b = self.criar_saldo_quantitativo("GI-83-B", 83, 100)
        saldo_84 = self.criar_saldo_quantitativo("GI-84", 84, 100)
        caixa_84 = self.criar_caixa("CX-84-PRESERVADA", 84, 3, 2.5)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_83_a, 80)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_83_b, 40)
        atualizar_reserva_quantitativa(self.romaneio, 84, saldo_84, 30)
        reservar_itens(self.romaneio, [caixa_84], op_id_esperada=84)

        removidos = estoque_service.remover_itens_reservados_op(self.romaneio, 83)

        self.assertEqual(removidos, [saldo_83_a, saldo_83_b])
        itens = buscar_itens_expedicao(self.romaneio)
        self.assertEqual({item["caixa_id"] for item in itens}, {saldo_84, caixa_84})
        self.assertEqual({item["op_id"] for item in itens}, {84})
        self.assertEqual(consultar(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (saldo_84,)
        )[0][0], 30)
        self.assertEqual(consultar(
            "SELECT disponibilidade FROM pa_caixas WHERE id=?", (caixa_84,)
        )[0][0], "RESERVADO")

    def test_smoke_autenticado_reserva_80_remove_op_e_preserva_outra(self):
        saldo_83 = self.criar_saldo_quantitativo("GI-SMOKE-83", 83, 240)
        saldo_84 = self.criar_saldo_quantitativo("GI-SMOKE-84", 84, 100)
        cliente = self.cliente()
        reserva_83 = cliente.put(
            f"/expedicao/{self.romaneio}/selecao-ops/83/saldos/{saldo_83}",
            json={"quantidade_aves": 80, "quantidade_anterior_aves": 0},
        )
        reserva_84 = cliente.put(
            f"/expedicao/{self.romaneio}/selecao-ops/84/saldos/{saldo_84}",
            json={"quantidade_aves": 40, "quantidade_anterior_aves": 0},
        )
        self.assertEqual((reserva_83.status_code, reserva_84.status_code), (200, 200))

        remocao = cliente.delete(
            f"/expedicao/{self.romaneio}/selecao-ops/83",
            json={"confirmar_remocao_itens": True},
        )

        self.assertEqual(remocao.status_code, 200)
        self.assertEqual(remocao.get_json()["caixa_ids"], [saldo_83])
        itens = buscar_itens_expedicao(self.romaneio)
        self.assertEqual([(item["op_id"], item["quantidade_galinhas"]) for item in itens], [(84, 40)])
        saldos = consultar(
            "SELECT id,quantidade_pacotes_reservados FROM pa_caixas WHERE id IN (?,?) ORDER BY id",
            (saldo_83, saldo_84),
        )
        self.assertEqual([(item["id"], item["quantidade_pacotes_reservados"]) for item in saldos], [
            (saldo_83, 0), (saldo_84, 40),
        ])

    def test_quantidade_de_aves_rejeita_vazio_zero_negativo_decimal_e_excesso(self):
        saldo_id = self.criar_saldo_quantitativo("GI-VALIDACAO", 83, 10)
        for valor in (None, "", "0", "-1", "1.5", "abc"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, valor)
        with self.assertRaisesRegex(ValueError, "excede"):
            atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 11)
        self.assertEqual(consultar("SELECT * FROM expedicao_itens"), [])

    def test_apresentacoes_usam_fator_oficial_e_exigem_pacote_fechado(self):
        v1 = self.criar_saldo_quantitativo("GI-V1", 83, 10, 1)
        v2 = self.criar_saldo_quantitativo("GI-V2", 83, 10, 2)
        v3 = self.criar_saldo_quantitativo("GI-V3", 83, 10, 3)
        atualizar_reserva_quantitativa(self.romaneio, 83, v1, 7)
        atualizar_reserva_quantitativa(self.romaneio, 83, v2, 20)
        atualizar_reserva_quantitativa(self.romaneio, 83, v3, 9)
        with self.assertRaisesRegex(ValueError, "pacotes completos de 2"):
            atualizar_reserva_quantitativa(self.romaneio, 83, v2, 19)
        itens = buscar_itens_expedicao(self.romaneio)
        self.assertEqual(sum(item["quantidade_galinhas"] for item in itens), 36)
        self.assertEqual({item["galinhas_por_pacote"] for item in itens}, {1, 2, 3})

    def test_edicao_considera_reserva_propria_e_reservas_de_outros_romaneios(self):
        saldo_id = self.criar_saldo_quantitativo("GI-CONCORRENCIA", 83, 100)
        outro = self.criar_romaneio("ROM-OUTRO-QUANT")
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 20)
        atualizar_reserva_quantitativa(outro, 83, saldo_id, 30)
        saldo = buscar_saldos_quantitativos_op(self.romaneio, 83)[0]
        self.assertEqual(saldo["quantidade_disponivel_aves"], 50)
        self.assertEqual(saldo["limite_edicao_aves"], 70)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 70)
        with self.assertRaisesRegex(ValueError, "excede"):
            atualizar_reserva_quantitativa(outro, 83, saldo_id, 31)
        atualizar_reserva_quantitativa(self.romaneio, 83, saldo_id, 60)
        self.assertEqual(buscar_saldos_quantitativos_op(outro, 83)[0]["quantidade_disponivel_aves"], 10)

    def test_multiplas_ops_e_fluxo_misto_preservam_origens(self):
        aves_83 = self.criar_saldo_quantitativo("GI-MISTA-83", 83, 100, 1)
        aves_84 = self.criar_saldo_quantitativo("GI-MISTA-84", 84, 40, 2)
        caixa_84 = self.criar_caixa("CX-MISTA-84", 84, 3, 2.5)
        atualizar_reserva_quantitativa(self.romaneio, 83, aves_83, 80)
        atualizar_reserva_quantitativa(self.romaneio, 84, aves_84, 40)
        reservar_itens(self.romaneio, [caixa_84], op_id_esperada=84)
        itens = buscar_itens_expedicao(self.romaneio)
        self.assertEqual(len(itens), 3)
        self.assertEqual({item["op_id"] for item in itens}, {83, 84})
        self.assertEqual(sum(item["quantidade_galinhas"] or 0 for item in itens), 120)
        self.assertEqual({item["caixa_id"] for item in itens}, {aves_83, aves_84, caixa_84})

    def test_endpoints_quantitativos_atualizam_e_removem_sem_cruzar_ops(self):
        saldo_id = self.criar_saldo_quantitativo("GI-API", 83, 50, 2)
        cliente = self.cliente()
        criada = cliente.put(
            f"/expedicao/{self.romaneio}/selecao-ops/83/saldos/{saldo_id}",
            json={"quantidade_aves": 20, "quantidade_anterior_aves": 0},
        )
        self.assertEqual(criada.status_code, 200)
        self.assertEqual(criada.get_json()["op"]["aves_selecionadas"], 20)
        indevida = cliente.delete(
            f"/expedicao/{self.romaneio}/selecao-ops/84/saldos/{saldo_id}"
        )
        self.assertEqual(indevida.status_code, 400)
        removida = cliente.delete(
            f"/expedicao/{self.romaneio}/selecao-ops/83/saldos/{saldo_id}"
        )
        self.assertEqual(removida.status_code, 200)
        self.assertEqual(removida.get_json()["op"]["aves_selecionadas"], 0)

    def test_mensagens_distinguem_saldo_quantitativo_caixas_e_op_sem_item(self):
        saldo_id = self.criar_saldo_quantitativo("GI-MENSAGEM", 83, 10)
        carga_gi = self.cliente().get(
            f"/expedicao/{self.romaneio}/selecao-ops/83"
        ).get_json()
        self.assertIsNone(carga_gi["mensagem"])
        executar("UPDATE pa_caixas SET disponibilidade='TRANSFERIDO',status='Transferido' WHERE id=?", (saldo_id,))
        self.criar_caixa("CX-SEM-SALDO", 84, 3, 2.5, disponibilidade="EXPEDIDO", status="Expedido")
        carga_caixa = self.cliente().get(
            f"/expedicao/{self.romaneio}/selecao-ops/84"
        ).get_json()
        self.assertEqual(
            carga_caixa["mensagem"],
            "Esta OP não possui caixas disponíveis para inclusão no romaneio.",
        )

    def test_interface_quantitativa_inicia_vazia_e_exibe_equivalencia_em_aves(self):
        template = (ROOT / "templates" / "romaneio_detalhe.html").read_text(encoding="utf-8")
        self.assertIn('label.textContent = "Quantidade de aves"', template)
        self.assertIn('input.placeholder = "Informe as aves"', template)
        self.assertIn('input.value = saldo.quantidade_selecionada_aves > 0', template)
        self.assertIn("aves — ${aves / saldo.galinhas_por_pacote} pacotes", template)
        self.assertIn("saldos_quantitativos", template)
        self.assertIn("if (mode.controle_caixas) block.appendChild(search);", template)
        self.assertNotIn("saldo.quantidade_disponivel_aves) : String", template)

    def test_um_romaneio_multiplas_ops_mantem_totais_e_conclui(self):
        a = self.criar_caixa("CX-TOTAL-A", 83, 3, 2.5)
        b = self.criar_caixa("CX-TOTAL-B", 84, 4, 3.5)
        reservar_itens(self.romaneio, [a], op_id_esperada=83)
        reservar_itens(self.romaneio, [b], op_id_esperada=84)
        resumo = calcular_resumo_itens_expedicao(buscar_itens_expedicao(self.romaneio))
        self.assertEqual(resumo["total_itens"], 2)
        self.assertEqual(resumo["total_kg"], 6)
        concluir_romaneio(self.romaneio)
        self.assertEqual(consultar("SELECT status FROM expedicoes WHERE id=?", (self.romaneio,))[0][0], "Concluído")
        self.assertEqual({item[0] for item in consultar("SELECT disponibilidade FROM pa_caixas")}, {"TRANSFERIDO"})

    def test_endpoints_json_preservam_resultado_por_op_e_validam_permissao(self):
        caixa = self.criar_caixa("CX-API", 83, 3, 2.5)
        cliente = self.cliente()
        carga = cliente.get(f"/expedicao/{self.romaneio}/selecao-ops/83")
        self.assertEqual(carga.status_code, 200)
        self.assertEqual(carga.get_json()["caixas"][0]["id"], caixa)
        sem_filtro = cliente.get(f"/expedicao/{self.romaneio}/selecao-ops/83/caixas?peso=")
        self.assertEqual(sem_filtro.get_json()["caixas"][0]["id"], caixa)
        self.assertIsNone(sem_filtro.get_json()["mensagem"])
        resposta = cliente.get(f"/expedicao/{self.romaneio}/selecao-ops/83/caixas?peso=2,500")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json()["caixas"][0]["id"], caixa)
        reserva = cliente.post(
            f"/expedicao/{self.romaneio}/selecao-ops/83/reservar",
            json={"caixa_ids": [caixa]},
        )
        self.assertEqual(reserva.status_code, 200)
        self.assertEqual(reserva.get_json()["op"]["selecionadas"], 1)
        self.assertNotEqual(self.app.test_client().get(
            f"/expedicao/{self.romaneio}/selecao-ops/83"
        ).status_code, 200)

    def test_consulta_usa_indice_da_op_e_nao_carrega_todo_estoque(self):
        plano = consultar("""
        EXPLAIN QUERY PLAN
        SELECT cx.id FROM pa_caixa_composicao comp
        INNER JOIN pa_caixas cx ON cx.id=comp.caixa_id
        WHERE comp.op_id=83 AND (cx.peso_bruto=2.5 OR cx.peso_liquido=2.5)
        """)
        detalhe = " ".join(str(coluna) for linha in plano for coluna in linha)
        self.assertIn("idx_pa_composicao_op", detalhe)
        template = (ROOT / "templates" / "romaneio_detalhe.html").read_text(encoding="utf-8")
        self.assertIn("await fetch(url, options)", template)
        self.assertIn("collections.set(key, data.caixas || [])", template)
        self.assertNotIn("/caixas?peso=${encodeURIComponent(input.value)}", template)

    def test_interface_trata_peso_como_filtro_opcional_e_preserva_selecao(self):
        template = (ROOT / "templates" / "romaneio_detalhe.html").read_text(encoding="utf-8")
        self.assertIn('input.placeholder = "Digite o peso"', template)
        self.assertNotIn('input.placeholder = "0,000"', template)
        self.assertNotIn("input.required = true", template)
        self.assertIn("const draftOrigins = new Map()", template)
        self.assertIn("filters.delete(String(op.id))", template)
        self.assertIn("Nenhuma caixa desta OP corresponde ao peso informado.", template)
        self.assertIn("const ids = pendingForOp(opId)", template)

    def test_interface_seleciona_todas_as_caixas_elegiveis_isolada_por_op(self):
        template = (ROOT / "templates" / "romaneio_detalhe.html").read_text(encoding="utf-8")
        self.assertIn('selectAllText.textContent = "Selecionar todas as caixas desta OP"', template)
        self.assertIn("selectAll.checked = eligible.length > 0 && selectedEligible.length === eligible.length", template)
        self.assertIn("selectAll.indeterminate = selectedEligible.length > 0 && selectedEligible.length < eligible.length", template)
        self.assertIn("selectAll.disabled = eligible.length === 0", template)
        self.assertIn("eligibleForOp(opId).forEach", template)
        self.assertIn("if (selectAll.checked) draftOrigins.set(id, Number(opId))", template)
        self.assertIn("else if (draftOrigins.get(id) === Number(opId)) draftOrigins.delete(id)", template)

    def test_post_reserva_exatamente_as_193_caixas_selecionadas_de_200(self):
        caixas = [self.criar_caixa(f"CX-MASSA-{indice:03d}", 83, 3, 2.5) for indice in range(200)]
        selecionadas = caixas[:193]
        resposta = self.cliente().post(
            f"/expedicao/{self.romaneio}/selecao-ops/83/reservar",
            json={"caixa_ids": selecionadas},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json()["op"]["selecionadas"], 193)
        ids_recebidos = {
            linha[0] for linha in consultar(
                "SELECT caixa_id FROM expedicao_itens WHERE expedicao_id=? AND COALESCE(ativo, 1)=1",
                (self.romaneio,),
            )
        }
        self.assertEqual(ids_recebidos, set(selecionadas))
        self.assertEqual(len(set(caixas) - ids_recebidos), 7)

    def test_carregamento_da_op_faz_quantidade_constante_de_selects(self):
        for indice in range(40):
            self.criar_caixa(f"CX-VOLUME-{indice:03d}", 83, 3, 2.5)
        selects = []
        conectar_real = estoque_service.conectar

        def conectar_instrumentado():
            conn = conectar_real()
            conn.set_trace_callback(
                lambda sql: selects.append(sql)
                if sql.lstrip().upper().startswith("SELECT") else None
            )
            return conn

        # A consulta consolidada deve devolver o volume sem executar uma consulta por caixa.
        with patch.object(estoque_service, "conectar", side_effect=conectar_instrumentado):
            caixas = buscar_caixas_elegiveis_op(self.romaneio, 83)
        self.assertEqual(len(caixas), 40)
        self.assertLessEqual(len(selects), 6)

    def test_pdf_e_apresentacao_final_nao_recebem_controles_de_selecao(self):
        impressao = (ROOT / "templates" / "romaneio_impressao.html").read_text(encoding="utf-8")
        css_impressao = (ROOT / "static" / "romaneio_impressao.css").read_text(encoding="utf-8")
        for texto in (impressao, css_impressao):
            self.assertNotIn("selecao-ops", texto)
            self.assertNotIn("Peso bruto ou líquido", texto)

    def test_p6_pallet_preflight_reserva_parcial_auditoria_e_vinculo_fisico(self):
        caixa_a = self.criar_caixa("P6-CX-A", 83, 3, 2.5)
        caixa_b = self.criar_caixa("P6-CX-B", 84, 4, 3.5)
        pallet = criar_pallet(usuario="PCP", idempotency_key="P6-PALLET")
        adicionar_caixas(
            pallet["id"], [caixa_a, caixa_b], usuario="PCP",
            idempotency_key="P6-ADD",
        )
        resumo = resumo_pallet_para_romaneio(self.romaneio, pallet["codigo"])
        self.assertEqual(resumo["elegiveis"], 2)
        reservar_pallet_no_romaneio(
            self.romaneio, pallet["id"], [caixa_a], {},
            usuario="PCP", idempotency_key="P6-RESERVA",
        )
        itens = consultar("SELECT * FROM expedicao_itens WHERE expedicao_id=? ORDER BY caixa_id",
                          (self.romaneio,))
        self.assertEqual({item["caixa_id"] for item in itens}, {caixa_a})
        self.assertTrue(all(item["origem_selecao"] == "PALLET" for item in itens))
        self.assertTrue(all(item["pallet_origem_codigo"] == pallet["codigo"] for item in itens))
        self.assertEqual(consultar("SELECT COUNT(*) n FROM pallet_caixas_atuais WHERE pallet_id=?",
                                   (pallet["id"],))[0]["n"], 2)
        evento = consultar("SELECT * FROM pallet_caixa_eventos WHERE idempotency_key='P6-RESERVA'")[0]
        self.assertEqual(evento["tipo_evento"], "PALLET_RESERVADO")
        self.assertEqual(evento["expedicao_id"], self.romaneio)
        # Retry não duplica reserva nem evento.
        reservar_pallet_no_romaneio(
            self.romaneio, pallet["id"], [caixa_a], {},
            usuario="PCP", idempotency_key="P6-RESERVA",
        )
        self.assertEqual(consultar("SELECT COUNT(*) n FROM expedicao_itens WHERE expedicao_id=?",
                                   (self.romaneio,))[0]["n"], 1)

    def test_p6_pallet_pacote_reserva_quantitativa(self):
        pacote = self.criar_saldo_quantitativo("P6-PAC", 83, 10, 2)
        pallet = criar_pallet(usuario="PCP", idempotency_key="P6-PALLET-PAC")
        adicionar_caixas(pallet["id"], [pacote], usuario="PCP", idempotency_key="P6-ADD-PAC")
        reservar_pallet_no_romaneio(
            self.romaneio, pallet["id"], [pacote], {str(pacote): "4"},
            usuario="PCP", idempotency_key="P6-RESERVA-PAC",
        )
        item = consultar("SELECT * FROM expedicao_itens WHERE expedicao_id=?", (self.romaneio,))[0]
        self.assertEqual((item["quantidade_pacotes"], item["quantidade_galinhas"]), (4, 8))

    def test_p6_tela_busca_selecao_em_massa_e_confirmacao(self):
        caixa = self.criar_caixa("P6-UI", 83, 3, 2.5)
        pallet = criar_pallet(usuario="PCP", idempotency_key="P6-PALLET-UI")
        adicionar_caixas(pallet["id"], [caixa], usuario="PCP", idempotency_key="P6-ADD-UI")
        cliente = self.cliente()
        resposta = cliente.get(
            f"/expedicao/{self.romaneio}/adicionar-pallet?codigo={pallet['codigo']}"
        )
        pagina = resposta.get_data(as_text=True)
        self.assertEqual(resposta.status_code, 200)
        for trecho in ("Selecionar todos", "Desmarcar todos", 'id="mestre"', "Totais selecionados"):
            self.assertIn(trecho, pagina)
        with cliente.session_transaction() as sessao:
            chave = sessao[f"romaneio_{self.romaneio}_pallet_chave"]
        resposta = cliente.post(f"/expedicao/{self.romaneio}/adicionar-pallet", data={
            "codigo": pallet["codigo"], "pallet_id": pallet["id"],
            "idempotency_key": chave, "caixa_ids": str(caixa),
        })
        self.assertEqual(resposta.status_code, 302)
        detalhe = cliente.get(f"/expedicao/{self.romaneio}").get_data(as_text=True)
        self.assertIn(f"Selecionado via pallet {pallet['codigo']}", detalhe)

    def test_p6_lote_invalido_faz_rollback_integral(self):
        caixa_a = self.criar_caixa("P6-OK", 83, 3, 2.5)
        caixa_b = self.criar_caixa("P6-BLOQ", 83, 3, 2.5, disponibilidade="RESERVADO")
        pallet = criar_pallet(usuario="PCP", idempotency_key="P6-PALLET-ROLLBACK")
        adicionar_caixas(pallet["id"], [caixa_a, caixa_b], usuario="PCP",
                         idempotency_key="P6-ADD-ROLLBACK")
        with self.assertRaises(ValueError):
            reservar_pallet_no_romaneio(
                self.romaneio, pallet["id"], [caixa_a, caixa_b], {},
                usuario="PCP", idempotency_key="P6-ROLLBACK",
            )
        self.assertEqual(consultar("SELECT COUNT(*) n FROM expedicao_itens WHERE expedicao_id=?",
                                   (self.romaneio,))[0]["n"], 0)
        self.assertEqual(consultar("SELECT disponibilidade FROM pa_caixas WHERE id=?",
                                   (caixa_a,))[0]["disponibilidade"], "DISPONIVEL")


if __name__ == "__main__":
    unittest.main()
