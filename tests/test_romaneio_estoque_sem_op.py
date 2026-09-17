"""Hotfix: seleção de Produto Acabado disponível sem OP no romaneio (estoque originado por
Ordem de Retrabalho). Reproduz, em fixtures, exatamente a forma da posição real
RT-PA-000001-01 (pacote/ave, sem linha em pa_caixa_composicao, origem='Retrabalho')."""

import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARQUIVO_BANCO = tempfile.NamedTemporaryFile(
    prefix="frigodatta-romaneio-sem-op-", suffix=".db", delete=False
)
ARQUIVO_BANCO.close()
os.environ["DB_NAME"] = ARQUIVO_BANCO.name
os.environ.pop("DATABASE_URL", None)

from flask import Flask  # noqa: E402

from database import conectar, q  # noqa: E402
from modules.expedicao.estoque_service import (  # noqa: E402
    atualizar_reserva_quantitativa,
    buscar_caixas_elegiveis_op,
    buscar_estoque_operacional,
    buscar_op_para_romaneio,
    cancelar_romaneio,
    concluir_romaneio,
    criar_tabelas_estoque_confiavel,
    remover_item_reservado,
    reservar_itens,
)
from modules.expedicao.routes import register_expedicao_routes  # noqa: E402
from modules.expedicao.services import (  # noqa: E402
    buscar_itens_expedicao,
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


class RomaneioEstoqueSemOpTest(unittest.TestCase):
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
        cls.local_abatedouro = consultar(
            "SELECT id FROM locais_estoque WHERE nome='Abatedouro'"
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
            "estoque_eventos", "expedicao_itens", "pa_caixa_composicao",
            "pa_caixas", "expedicoes", "ordens_producao",
        ):
            conn.execute(f"DELETE FROM {tabela}")
        conn.commit()
        conn.close()
        self.op83 = self.criar_op(83)
        self.romaneio = self.criar_romaneio("ROM-SEM-OP-1")

    def criar_op(self, numero):
        executar("""
        INSERT INTO ordens_producao (
            id, data, fornecedor, quantidade_aves, peso_vivo, peso_medio, status, sku
        ) VALUES (?, '2026-09-15', 'Fornecedor', 100, 250, 2.5, 'Encerrada', 'Galinha Cortada')
        """, (numero,))
        return numero

    def criar_romaneio(self, numero, tipo_movimentacao="TRANSFERENCIA"):
        return executar("""
        INSERT INTO expedicoes (
            numero_romaneio, data, tipo_movimentacao, tipo_saida, origem, destino,
            responsavel, status, criado_por, perfil_criacao
        ) VALUES (?, '2026-09-17', ?, 'TRANSFERENCIA_LSM',
                  'Abatedouro', 'Câmara Fria LSM', 'PCP', 'Aberto', 'PCP', 'pcp')
        """, (numero, tipo_movimentacao))

    def criar_saldo_op(self, codigo, op_id, pacotes, aves_por_pacote=1,
                        *, disponibilidade="DISPONIVEL", condicao="CONFORME"):
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, status, origem,
            local_estoque_id, estoque_operacional, condicao, disponibilidade,
            zona_estoque, unidade_estoque, apresentacao, galinhas_por_pacote,
            quantidade_pacotes, quantidade_galinhas, quantidade_pacotes_reservados
        ) VALUES (?, 'Galinha Inteira', '2026-09-15', '2027-09-15', 'Em estoque',
                  'Embalagem Primária', ?, 1, ?, ?, 'Conforme', 'PACOTE', ?, ?, ?, ?, 0)
        """, (codigo, self.local_abatedouro, condicao, disponibilidade,
              f"V{aves_por_pacote}", aves_por_pacote, pacotes, pacotes * aves_por_pacote))
        executar("""
        INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas)
        VALUES (?, ?, 0)
        """, (caixa_id, op_id))
        return caixa_id

    def criar_caixa_retrabalho(self, codigo, pacotes, aves_por_pacote=2, *,
                                disponibilidade="DISPONIVEL", condicao="CONFORME",
                                numero_rt="RT-000001"):
        """Reproduz a forma exata da posição real RT-PA-000001-01: PACOTE, sem
        linha em pa_caixa_composicao, origem='Retrabalho'."""
        return executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, status, origem, observacoes,
            local_estoque_id, estoque_operacional, condicao, disponibilidade,
            zona_estoque, unidade_estoque, apresentacao, galinhas_por_pacote,
            quantidade_pacotes, quantidade_galinhas, quantidade_pacotes_reservados
        ) VALUES (?, 'Galinha Inteira', '2026-09-15', '2027-09-15', 'Em estoque',
                  'Retrabalho', ?, ?, 1, ?, ?, 'Conforme', 'PACOTE', 'V2', ?, ?, ?, 0)
        """, (
            codigo, f"Formado pela Ordem de Retrabalho {numero_rt}.",
            self.local_abatedouro, condicao, disponibilidade,
            aves_por_pacote, pacotes, pacotes * aves_por_pacote,
        ))

    def criar_caixa_retrabalho_cortada(self, codigo, bruto, liquido, *,
                                        disponibilidade="DISPONIVEL", condicao="CONFORME",
                                        numero_rt="RT-000002"):
        """Variante família CAIXA/peso (ex.: Galinha Inteira -> Galinha Cortada Congelada)."""
        return executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, peso_bruto,
            peso_tara, peso_liquido, quantidade_bandejas, status, origem, observacoes,
            local_estoque_id, estoque_operacional, condicao, disponibilidade,
            zona_estoque, unidade_estoque, apresentacao
        ) VALUES (?, 'Galinha Cortada', '2026-09-15', '2027-09-15', ?, 0.5, ?, 12, ?,
                  'Retrabalho', ?, ?, 1, ?, ?, 'Conforme', 'CAIXA', 'Caixa')
        """, (
            codigo, bruto, liquido, "Em estoque",
            f"Formado pela Ordem de Retrabalho {numero_rt}.",
            self.local_abatedouro, condicao, disponibilidade,
        ))

    def cliente(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": "PCP", "perfil": "pcp"})
        return cliente

    # ---- Etapa A (regressão): "Carregar OP" e atualizar_reserva_quantitativa continuam
    # exclusivos de OP e não são afetados pela existência de estoque sem OP. ----

    def test_atualizar_reserva_quantitativa_continua_exclusiva_de_op(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        with self.assertRaises(ValueError):
            atualizar_reserva_quantitativa(self.romaneio, 83, rt, 10)

    def test_carregar_op_nao_lista_nem_e_afetado_por_estoque_sem_op(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        op_caixa = self.criar_saldo_op("CX-OP-83", 83, 50, 2)
        cliente = self.cliente()
        resposta = cliente.get(f"/expedicao/{self.romaneio}/selecao-ops/83").get_json()
        ids = [item["id"] for item in resposta.get("saldos_quantitativos", [])] + \
            [item["id"] for item in resposta.get("caixas", [])]
        self.assertIn(op_caixa, ids)
        self.assertNotIn(rt, ids)
        self.assertEqual(buscar_caixas_elegiveis_op(self.romaneio, 83), [])

    # ---- Painel "Adicionar estoque disponível" ----

    def test_estoque_sem_op_aparece_na_pagina_e_carregar_op_continua_sem_mostrar(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        texto = self.cliente().get(f"/expedicao/{self.romaneio}").get_data(as_text=True)
        self.assertIn("Adicionar estoque disponível", texto)
        self.assertIn("RT-PA-000001-01", texto)
        self.assertIn("Retrabalho", texto)

    def test_estoque_sem_op_nao_aparece_para_romaneio_de_descarte(self):
        self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        descarte = self.criar_romaneio("ROM-DESCARTE-1", tipo_movimentacao="DESCARTE")
        texto = self.cliente().get(f"/expedicao/{descarte}").get_data(as_text=True)
        self.assertNotIn("Adicionar estoque disponível", texto)

    def test_pendente_op_nao_aparece_no_painel(self):
        rt = self.criar_caixa_retrabalho(
            "RT-PA-000002-01", 10, 1, disponibilidade="PENDENTE_OP",
        )
        estoque, _ = buscar_estoque_operacional()
        elegiveis = [i for i in estoque if i["op_id"] is None and i["condicao"] == "CONFORME"
                     and i["disponibilidade"] == "DISPONIVEL"]
        self.assertNotIn(rt, [i["id"] for i in elegiveis])

    # ---- Reserva (reutiliza reservar_itens sem alteração) ----

    def test_reserva_parcial_de_pacotes_sem_op(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [rt], {str(rt): 40})
        linha = consultar(
            "SELECT quantidade_pacotes_reservados, disponibilidade FROM pa_caixas WHERE id=?", (rt,)
        )[0]
        self.assertEqual(linha["quantidade_pacotes_reservados"], 40)
        self.assertEqual(linha["disponibilidade"], "DISPONIVEL")
        item = buscar_itens_expedicao(self.romaneio)[0]
        self.assertIsNone(item["op_id"])
        self.assertEqual(item["origem_caixa"], "Retrabalho")
        self.assertEqual(item["quantidade_pacotes"], 40)
        self.assertEqual(item["quantidade_galinhas"], 80)

    def test_reserva_total_flipa_para_reservado_e_some_do_painel(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [rt], {str(rt): 99})
        linha = consultar("SELECT disponibilidade FROM pa_caixas WHERE id=?", (rt,))[0]
        self.assertEqual(linha["disponibilidade"], "RESERVADO")
        estoque, _ = buscar_estoque_operacional()
        self.assertNotIn(rt, [i["id"] for i in estoque
                               if i["disponibilidade"] == "DISPONIVEL" and i["op_id"] is None])

    def test_segunda_reserva_alem_do_saldo_falha_com_erro_de_negocio(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [rt], {str(rt): 90})
        outro = self.criar_romaneio("ROM-SEM-OP-2")
        with self.assertRaisesRegex(ValueError, "excede o saldo dispon"):
            reservar_itens(outro, [rt], {str(rt): 20})

    def test_reserva_repetida_no_mesmo_romaneio_e_bloqueada(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [rt], {str(rt): 30})
        with self.assertRaisesRegex(ValueError, "ja esta incluido"):
            reservar_itens(self.romaneio, [rt], {str(rt): 10})

    def test_remover_item_retrabalho_restaura_saldo(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [rt], {str(rt): 40})
        remover_item_reservado(self.romaneio, rt)
        linha = consultar(
            "SELECT quantidade_pacotes_reservados, disponibilidade FROM pa_caixas WHERE id=?", (rt,)
        )[0]
        self.assertEqual(linha["quantidade_pacotes_reservados"], 0)
        self.assertEqual(linha["disponibilidade"], "DISPONIVEL")
        self.assertEqual(buscar_itens_expedicao(self.romaneio), [])

    def test_familia_caixa_peso_sem_op_e_reservavel(self):
        rt = self.criar_caixa_retrabalho_cortada("RT-PA-000002-01", 3.0, 2.5)
        reservar_itens(self.romaneio, [rt])
        linha = consultar("SELECT disponibilidade FROM pa_caixas WHERE id=?", (rt,))[0]
        self.assertEqual(linha["disponibilidade"], "RESERVADO")
        item = buscar_itens_expedicao(self.romaneio)[0]
        self.assertIsNone(item["op_id"])
        self.assertEqual(item["origem_caixa"], "Retrabalho")

    # ---- Ciclo de vida completo (mistura OP + RT, RT-only, cancelamento) ----

    def test_romaneio_misto_op_e_retrabalho_conclui_corretamente(self):
        op_caixa = self.criar_saldo_op("CX-OP-83", 83, 50, 2)
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [op_caixa], {str(op_caixa): 50}, op_id_esperada=83)
        reservar_itens(self.romaneio, [rt], {str(rt): 99})
        concluir_romaneio(self.romaneio)
        situacoes = {
            r["id"]: r["disponibilidade"]
            for r in consultar("SELECT id, disponibilidade FROM pa_caixas")
        }
        self.assertEqual(situacoes[op_caixa], "TRANSFERIDO")
        self.assertEqual(situacoes[rt], "TRANSFERIDO")
        self.assertEqual(consultar("SELECT status FROM expedicoes WHERE id=?",
                                    (self.romaneio,))[0]["status"], "Concluído")

    def test_romaneio_somente_retrabalho_fluxo_completo(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [rt], {str(rt): 99})
        concluir_romaneio(self.romaneio)
        linha = consultar("SELECT disponibilidade, status FROM pa_caixas WHERE id=?", (rt,))[0]
        self.assertEqual(linha["disponibilidade"], "TRANSFERIDO")
        self.assertEqual(linha["status"], "Transferido")

    def test_cancelar_romaneio_com_item_de_retrabalho_restaura(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [rt], {str(rt): 99})
        cancelar_romaneio(self.romaneio, "Teste de cancelamento com item de retrabalho.")
        linha = consultar(
            "SELECT quantidade_pacotes_reservados, disponibilidade FROM pa_caixas WHERE id=?", (rt,)
        )[0]
        self.assertEqual(linha["quantidade_pacotes_reservados"], 0)
        self.assertEqual(linha["disponibilidade"], "DISPONIVEL")
        self.assertEqual(consultar("SELECT status FROM expedicoes WHERE id=?",
                                    (self.romaneio,))[0]["status"], "Cancelado")

    # ---- Preview / impressão ----

    def test_impressao_mostra_retrabalho_como_origem(self):
        rt = self.criar_caixa_retrabalho("RT-PA-000001-01", 99, 2)
        reservar_itens(self.romaneio, [rt], {str(rt): 99})
        concluir_romaneio(self.romaneio)
        texto = self.cliente().get(f"/expedicao/{self.romaneio}/imprimir").get_data(as_text=True)
        self.assertIn("Retrabalho", texto)
        self.assertIn("RT-PA-000001-01", texto)


if __name__ == "__main__":
    unittest.main()
