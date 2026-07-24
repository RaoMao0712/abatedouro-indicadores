"""Critérios da sprint visual e de segurança operacional dos romaneios."""

import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARQUIVO_BANCO = tempfile.NamedTemporaryFile(
    prefix="frigodatta-romaneios-seguranca-",
    suffix=".db",
    delete=False,
)
ARQUIVO_BANCO.close()
os.environ["DB_NAME"] = ARQUIVO_BANCO.name
os.environ.pop("DATABASE_URL", None)

from flask import Flask, session  # noqa: E402

from database import conectar, q  # noqa: E402
from modules.expedicao.estoque_service import (  # noqa: E402
    cancelar_romaneio,
    concluir_romaneio,
    criar_tabelas_estoque_confiavel,
    editar_romaneio_aberto,
    registrar_itens_historicos,
)
from modules.expedicao.routes import register_expedicao_routes  # noqa: E402
from modules.expedicao.services import (  # noqa: E402
    buscar_expedicao_por_id,
    buscar_itens_expedicao,
    calcular_resumo_mz,
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


def consultar_um(sql, parametros=()):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(sql), parametros)
    item = cursor.fetchone()
    conn.close()
    return item


class RomaneiosSegurancaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = conectar()
        cursor = conn.cursor()
        cursor.executescript("""
        CREATE TABLE ordens_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            fornecedor TEXT NOT NULL,
            quantidade_aves INTEGER NOT NULL,
            mortes_antes_pendura INTEGER DEFAULT 0,
            peso_vivo REAL NOT NULL,
            peso_medio REAL NOT NULL,
            status TEXT DEFAULT 'Aberta',
            sku TEXT DEFAULT 'Galinha Cortada'
        );
        CREATE TABLE apontamentos_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            quantidade REAL DEFAULT 0,
            unidade TEXT NOT NULL
        );
        """)
        conn.commit()
        conn.close()
        criar_tabelas_expedicao()
        criar_tabelas_estoque_pi_pa()
        criar_tabelas_estoque_confiavel()

        cls.mz_real_id = executar("""
        INSERT INTO expedicoes (
            numero_romaneio, data, tipo_movimentacao, origem, destino,
            responsavel, observacoes, status, criado_por, perfil_criacao
        ) VALUES (
            'MZ-20260724-001', '2026-07-24', 'HISTORICO_MARCO_ZERO',
            'Abatedouro', 'Câmara Fria LSM', 'Responsável definitivo',
            'Documento real preservado', 'Aberto', 'Administrador', 'pcp'
        )
        """)
        cls.mz_real_antes = dict(buscar_expedicao_por_id(cls.mz_real_id))

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

    def contexto(self, perfil="pcp", nome="PCP Teste"):
        contexto = self.app.test_request_context("/")
        contexto.push()
        session.update({"usuario_id": 1, "nome": nome, "perfil": perfil})
        self.addCleanup(contexto.pop)

    def cliente(self, perfil="pcp", nome="PCP Teste"):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": nome, "perfil": perfil})
        return cliente

    def criar_mz(self, status="Aberto", responsavel="Operador histórico"):
        sufixo = os.urandom(4).hex()
        return executar("""
        INSERT INTO expedicoes (
            numero_romaneio, data, tipo_movimentacao, origem, destino,
            responsavel, observacoes, status, criado_por, perfil_criacao
        ) VALUES (?, '2026-07-24', 'HISTORICO_MARCO_ZERO', 'Abatedouro',
                  'Câmara Fria LSM', ?, 'Documento isolado', ?, 'PCP Teste', 'pcp')
        """, (f"MZ-TESTE-{sufixo}", responsavel, status))

    @staticmethod
    def linhas(v1="2", v2="3", caixas="4", peso="40,500"):
        return [
            {"sku": "Galinha Inteira", "quantidade_pacotes": v1, "galinhas_por_pacote": 1},
            {"sku": "Galinha Inteira", "quantidade_pacotes": v2, "galinhas_por_pacote": 2},
            {"sku": "Galinha Cortada", "quantidade": caixas, "peso": peso},
        ]

    def test_01_responsavel_aparece_preenchido_na_edicao(self):
        resposta = self.cliente().get(f"/expedicao/{self.mz_real_id}")
        texto = resposta.get_data(as_text=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('name="responsavel" value="Responsável definitivo"', texto)

    def test_02_salvar_vazio_nao_apaga_responsavel(self):
        self.contexto()
        mz_id = self.criar_mz(responsavel="Responsável preservado")
        alterado = editar_romaneio_aberto(mz_id, {
            "data": "2026-07-24",
            "origem": "Abatedouro",
            "destino": "Câmara Fria LSM",
            "responsavel": "",
            "observacoes": "Documento isolado",
        })
        self.assertFalse(alterado)
        self.assertEqual(buscar_expedicao_por_id(mz_id)["responsavel"], "Responsável preservado")

    def test_03_v1_somente_inteiro_nao_negativo(self):
        self.contexto()
        for valor in ("1.5", "-1", "abc"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                registrar_itens_historicos(self.criar_mz(), self.linhas(v1=valor))

    def test_04_v2_somente_inteiro_nao_negativo(self):
        self.contexto()
        for valor in ("2.2", "-2", "x"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                registrar_itens_historicos(self.criar_mz(), self.linhas(v2=valor))

    def test_05_caixas_somente_inteiro_nao_negativo(self):
        self.contexto()
        for valor in ("3.1", "-3", "caixa"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                registrar_itens_historicos(self.criar_mz(), self.linhas(caixas=valor))

    def test_06_peso_aceita_decimal_valido(self):
        self.contexto()
        mz_id = self.criar_mz()
        registrar_itens_historicos(mz_id, self.linhas(peso="40.750"))
        resumo = calcular_resumo_mz(buscar_itens_expedicao(mz_id))
        self.assertEqual(resumo["peso_cortada"], 40.75)

    def test_07_peso_com_virgula_e_normalizado(self):
        self.contexto()
        mz_id = self.criar_mz()
        registrar_itens_historicos(mz_id, self.linhas(peso="40,750"))
        resumo = calcular_resumo_mz(buscar_itens_expedicao(mz_id))
        self.assertEqual(resumo["peso_cortada"], 40.75)

    def test_08_caixas_sem_peso_sao_rejeitadas(self):
        self.contexto()
        with self.assertRaisesRegex(ValueError, "em conjunto"):
            registrar_itens_historicos(self.criar_mz(), self.linhas(caixas="4", peso="0"))

    def test_09_peso_sem_caixas_e_rejeitado(self):
        self.contexto()
        with self.assertRaisesRegex(ValueError, "em conjunto"):
            registrar_itens_historicos(self.criar_mz(), self.linhas(caixas="0", peso="10"))

    def test_10_todos_totais_zerados_impedem_conclusao(self):
        self.contexto()
        mz_id = self.criar_mz()
        executar("""
        INSERT INTO expedicao_itens (
            expedicao_id, sku, quantidade_unidades, quantidade_kg, unidade_estoque
        ) VALUES (?, 'Galinha Cortada', 0, 0, 'CAIXA')
        """, (mz_id,))
        with self.assertRaisesRegex(ValueError, "positivo"):
            concluir_romaneio(mz_id)

    def test_11_totais_nao_salvos_impedem_conclusao(self):
        self.contexto()
        with self.assertRaisesRegex(ValueError, "item|totais"):
            concluir_romaneio(self.criar_mz())

    def test_12_alteracoes_nao_salvas_geram_aviso_visual(self):
        resposta = self.cliente().get(f"/expedicao/{self.mz_real_id}")
        texto = resposta.get_data(as_text=True)
        self.assertIn("Existem alterações não salvas.", texto)
        self.assertIn("anyDirty", texto)

    def test_13_total_de_pacotes_calculado(self):
        self.contexto()
        mz_id = self.criar_mz()
        registrar_itens_historicos(mz_id, self.linhas(v1="7", v2="5", caixas="0", peso="0"))
        self.assertEqual(calcular_resumo_mz(buscar_itens_expedicao(mz_id))["total_pacotes"], 12)

    def test_14_total_de_galinhas_usa_v1_mais_duas_v2(self):
        self.contexto()
        mz_id = self.criar_mz()
        registrar_itens_historicos(mz_id, self.linhas(v1="7", v2="5", caixas="0", peso="0"))
        self.assertEqual(calcular_resumo_mz(buscar_itens_expedicao(mz_id))["total_galinhas"], 17)

    def test_15_mz_aberto_imprime_como_rascunho(self):
        mz_id = self.criar_mz()
        resposta = self.cliente().get(f"/expedicao/{mz_id}/imprimir")
        self.assertIn("RASCUNHO", resposta.get_data(as_text=True))

    def test_16_mz_concluido_imprime_sem_rascunho(self):
        self.contexto()
        mz_id = self.criar_mz()
        registrar_itens_historicos(mz_id, self.linhas(caixas="0", peso="0"))
        concluir_romaneio(mz_id)
        texto = self.cliente().get(f"/expedicao/{mz_id}/imprimir").get_data(as_text=True)
        self.assertNotIn('class="documento-marca rascunho"', texto)

    def test_17_cancelado_recebe_marca_visual(self):
        mz_id = self.criar_mz(status="Cancelado")
        texto = self.cliente().get(f"/expedicao/{mz_id}/imprimir").get_data(as_text=True)
        self.assertIn("CANCELADO", texto)
        self.assertIn("documento-marca invalidado", texto)

    def test_18_estornado_recebe_marca_visual(self):
        mz_id = self.criar_mz(status="Estornado")
        texto = self.cliente().get(f"/expedicao/{mz_id}/imprimir").get_data(as_text=True)
        self.assertIn("ESTORNADO", texto)
        self.assertIn("documento-marca invalidado", texto)

    def test_19_cancelamento_exige_justificativa_e_confirmacao(self):
        mz_id = self.criar_mz()
        cliente = self.cliente()
        resposta = cliente.post(f"/expedicao/{mz_id}", data={
            "acao": "cancelar",
            "justificativa": "Motivo válido",
        })
        self.assertIn("Confirme o cancelamento", resposta.get_data(as_text=True))
        self.assertEqual(buscar_expedicao_por_id(mz_id)["status"], "Aberto")
        with self.assertRaises(ValueError):
            cancelar_romaneio(mz_id, "")

    def test_20_documento_concluido_nao_pode_ser_editado(self):
        self.contexto()
        mz_id = self.criar_mz()
        registrar_itens_historicos(mz_id, self.linhas(caixas="0", peso="0"))
        concluir_romaneio(mz_id)
        with self.assertRaises(ValueError):
            editar_romaneio_aberto(mz_id, {
                "data": "2026-07-24", "origem": "Abatedouro",
                "destino": "Câmara Fria LSM", "responsavel": "Outro",
            })
        with self.assertRaises(ValueError):
            registrar_itens_historicos(mz_id, self.linhas())

    def test_21_conclusao_mz_nao_movimenta_estoque_operacional(self):
        self.contexto()
        antes = consultar_um("SELECT COUNT(*) total FROM pa_caixas WHERE estoque_operacional = 1")["total"]
        mz_id = self.criar_mz()
        registrar_itens_historicos(mz_id, self.linhas())
        concluir_romaneio(mz_id)
        depois = consultar_um("SELECT COUNT(*) total FROM pa_caixas WHERE estoque_operacional = 1")["total"]
        self.assertEqual(antes, depois)

    def test_22_mz_real_permanece_aberto_sem_totais_e_inalterado(self):
        atual = dict(buscar_expedicao_por_id(self.mz_real_id))
        self.assertEqual(atual, self.mz_real_antes)
        self.assertEqual(
            consultar_um("SELECT COUNT(*) total FROM expedicao_itens WHERE expedicao_id = ?", (self.mz_real_id,))["total"],
            0,
        )

    def test_23_listagem_reconhece_documentos_mz(self):
        texto = self.cliente().get(
            "/expedicao?data_inicio=2026-07-01&data_fim=2026-07-31"
        ).get_data(as_text=True)
        self.assertIn("MZ-20260724-001", texto)
        self.assertIn("Marco Zero", texto)
        self.assertIn("Totais pendentes", texto)

    def test_24_estornados_podem_ser_filtrados(self):
        mz_id = self.criar_mz(status="Estornado")
        numero = buscar_expedicao_por_id(mz_id)["numero_romaneio"]
        texto = self.cliente().get(
            "/expedicao?data_inicio=2026-07-01&data_fim=2026-07-31&status=Estornado"
        ).get_data(as_text=True)
        self.assertIn(numero, texto)
        self.assertIn("badge-expedicao estornado", texto)

    def test_25_permissoes_existentes_permanecem(self):
        for perfil in ("pcp", "qualidade"):
            self.assertEqual(self.cliente(perfil).get("/expedicao").status_code, 200)
        self.assertEqual(self.cliente("producao").get("/expedicao").status_code, 302)

    def test_26_regressoes_de_estoque_e_encerramento_preservadas(self):
        self.contexto()
        mz_id = self.criar_mz()
        linhas = self.linhas(v1="1", v2="2", caixas="3", peso="30")
        registrar_itens_historicos(mz_id, linhas)
        resumo = calcular_resumo_mz(buscar_itens_expedicao(mz_id))
        self.assertEqual(
            (resumo["total_pacotes"], resumo["total_galinhas"], resumo["caixas_cortada"]),
            (3, 5, 3),
        )
        eventos_antes = consultar_um(
            "SELECT COUNT(*) total FROM estoque_eventos WHERE expedicao_id = ? AND acao = 'TOTAIS_MZ_ALTERADOS'",
            (mz_id,),
        )["total"]
        self.assertFalse(registrar_itens_historicos(mz_id, linhas))
        eventos_depois = consultar_um(
            "SELECT COUNT(*) total FROM estoque_eventos WHERE expedicao_id = ? AND acao = 'TOTAIS_MZ_ALTERADOS'",
            (mz_id,),
        )["total"]
        self.assertEqual(eventos_antes, eventos_depois)
        concluir_romaneio(mz_id)
        with self.assertRaises(ValueError):
            concluir_romaneio(mz_id)


if __name__ == "__main__":
    unittest.main()
