"""Seleção pontual de caixas do romaneio por múltiplas OPs e peso."""

import os
from pathlib import Path
import sys
import tempfile
import unittest


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
from modules.expedicao.estoque_service import (  # noqa: E402
    buscar_caixas_por_op_e_peso,
    buscar_op_para_romaneio,
    concluir_romaneio,
    criar_tabelas_estoque_confiavel,
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

    def cliente(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": "PCP", "perfil": "pcp"})
        return cliente

    def test_carrega_uma_e_varias_ops_sem_buscar_caixas(self):
        self.assertEqual(buscar_op_para_romaneio(self.romaneio, self.op83)["id"], 83)
        self.assertEqual(buscar_op_para_romaneio(self.romaneio, self.op84)["id"], 84)
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

    def test_peso_vazio_zero_negativo_invalido_e_precisao_excessiva(self):
        for peso in ("", "0", "-1", "abc", "2,5004"):
            with self.subTest(peso=peso), self.assertRaises(ValueError):
                buscar_caixas_por_op_e_peso(self.romaneio, 83, peso)

    def test_indisponiveis_estornadas_consumidas_reservadas_e_bloqueadas_nao_aparecem(self):
        self.criar_caixa("CX-RES", 83, 3, 2.5, disponibilidade="RESERVADO")
        self.criar_caixa("CX-BLOQ", 83, 3, 2.5, disponibilidade="BLOQUEADO", condicao="NAO_CONFORME")
        self.criar_caixa("CX-EXP", 83, 3, 2.5, disponibilidade="EXPEDIDO", status="Expedido")
        self.criar_caixa("CX-EST", 83, 3, 2.5, disponibilidade="DISPONIVEL", status="Estornado")
        self.criar_caixa("CX-LEG", 83, 3, 2.5, operacional=0)
        self.assertEqual(buscar_caixas_por_op_e_peso(self.romaneio, 83, "2.5"), [])

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
        self.assertEqual(consultar("SELECT * FROM expedicao_itens"), [])
        texto = (ROOT / "templates" / "romaneio_detalhe.html").read_text(encoding="utf-8")
        self.assertIn("também retirará essas caixas", texto)

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

    def test_pdf_e_apresentacao_final_nao_recebem_controles_de_selecao(self):
        impressao = (ROOT / "templates" / "romaneio_impressao.html").read_text(encoding="utf-8")
        css_impressao = (ROOT / "static" / "romaneio_impressao.css").read_text(encoding="utf-8")
        for texto in (impressao, css_impressao):
            self.assertNotIn("selecao-ops", texto)
            self.assertNotIn("Peso bruto ou líquido", texto)


if __name__ == "__main__":
    unittest.main()
