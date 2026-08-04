"""Regressão do marco zero e do estoque operacional da Expedição."""

import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARQUIVO_BANCO = tempfile.NamedTemporaryFile(prefix="frigodatta-expedicao-", suffix=".db", delete=False)
ARQUIVO_BANCO.close()
os.environ["DB_NAME"] = ARQUIVO_BANCO.name
os.environ.pop("DATABASE_URL", None)

from flask import Flask, session  # noqa: E402

from database import conectar, q  # noqa: E402
from modules.expedicao.routes import register_expedicao_routes  # noqa: E402
from modules.expedicao.services import (  # noqa: E402
    buscar_expedicao_por_id,
    buscar_itens_expedicao,
    calcular_validade_padrao,
    criar_tabelas_expedicao,
    criar_tabelas_estoque_pi_pa,
)
from modules.expedicao.estoque_service import (  # noqa: E402
    ativar_estoque_da_op,
    bloquear_produto,
    buscar_estoque_operacional,
    buscar_historico_estoque,
    cancelar_romaneio,
    concluir_romaneio,
    criar_tabelas_estoque_confiavel,
    destinar_produto,
    estornar_romaneio,
    obter_marco_zero,
    registrar_itens_historicos,
    reservar_itens,
)
from modules.producao.services import registrar_peso_caixa_op  # noqa: E402
from modules.clientes.services import (  # noqa: E402
    alterar_status,
    criar_tabelas_clientes,
    historico_cliente,
    listar_clientes,
    salvar_cliente,
)
from modules.clientes.routes import register_clientes_routes  # noqa: E402
from modules.expedicao.services import salvar_romaneio_expedicao  # noqa: E402


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


class ExpedicaoMarcoZeroTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("""
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
        )
        """)
        cursor.execute("""
        CREATE TABLE apontamentos_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            quantidade REAL DEFAULT 0,
            unidade TEXT NOT NULL
        )
        """)
        cursor.execute("""
        INSERT INTO ordens_producao (
            data, fornecedor, quantidade_aves, peso_vivo, peso_medio, status, sku
        ) VALUES ('2026-07-23', 'Fornecedor histórico', 100, 250, 2.5, 'Encerrada', 'Galinha Inteira')
        """)
        cls.op_legada = cursor.lastrowid
        conn.commit()
        conn.close()

        criar_tabelas_expedicao()
        criar_tabelas_estoque_pi_pa()

        cls.local_abatedouro = consultar_um(
            "SELECT id FROM locais_estoque WHERE nome = ?",
            ("Abatedouro",),
        )["id"]
        cls.local_lsm = consultar_um(
            "SELECT id FROM locais_estoque WHERE nome = ?",
            ("Câmara Fria LSM",),
        )["id"]

        cls.caixa_legada = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, peso_bruto,
            peso_liquido, quantidade_bandejas, status, origem, local_estoque_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "GI-OP-LEGADA", "Galinha Inteira", "2026-07-23", "2027-07-23",
            100, 100, 80, "Em estoque", "Embalagem Primaria", cls.local_abatedouro,
        ))
        executar(
            "INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas) VALUES (?, ?, ?)",
            (cls.caixa_legada, cls.op_legada, 80),
        )

        criar_tabelas_estoque_confiavel()
        criar_tabelas_clientes()
        cls.marco = obter_marco_zero()

        cls.app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"))
        cls.app.secret_key = "teste"
        cls.app.config["TESTING"] = True
        cls.app.jinja_env.filters["br_numero"] = lambda valor, casas=2: f"{float(valor or 0):.{int(casas)}f}"
        cls.app.url_build_error_handlers.append(lambda error, endpoint, values: "#")
        cls.app.add_url_rule("/dashboard", "dashboard", lambda: "dashboard")
        cls.app.add_url_rule("/login", "login", lambda: "login")
        cls.app.add_url_rule("/apontamento-descartes", "apontamento_descartes", lambda: "qualidade")
        register_expedicao_routes(cls.app)
        register_clientes_routes(cls.app)

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(ARQUIVO_BANCO.name)
        except FileNotFoundError:
            pass

    def contexto(self, perfil="pcp"):
        contexto = self.app.test_request_context("/")
        contexto.push()
        session.update({"usuario_id": 1, "nome": f"Usuário {perfil}", "perfil": perfil})
        self.addCleanup(contexto.pop)
        return contexto

    def criar_op_nova(self, sku="Galinha Cortada", status="Encerrada"):
        return executar("""
        INSERT INTO ordens_producao (
            data, fornecedor, quantidade_aves, peso_vivo, peso_medio, status, sku
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("2026-07-25", "Fornecedor novo", 120, 300, 2.5, status, sku))

    def criar_pa(self, op_id, codigo, sku="Galinha Cortada", status_op="Encerrada", peso=10):
        executar("UPDATE ordens_producao SET status = ? WHERE id = ?", (status_op, op_id))
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, peso_bruto,
            peso_tara, peso_liquido, quantidade_bandejas, status, origem,
            local_estoque_id, estoque_operacional, condicao, disponibilidade,
            zona_estoque
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'CONFORME', 'PENDENTE_OP', 'Conforme')
        """, (
            codigo, sku, "2026-07-25", calcular_validade_padrao("2026-07-25"),
            peso + 0.5, 0.5, peso, 12, "Em estoque", "Embalagem Secundária",
            self.local_abatedouro,
        ))
        executar(
            "INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas) VALUES (?, ?, ?)",
            (caixa_id, op_id, 12),
        )
        return caixa_id

    def criar_romaneio(self, tipo="TRANSFERENCIA", destino="Câmara Fria LSM"):
        return executar("""
        INSERT INTO expedicoes (
            numero_romaneio, data, tipo_movimentacao, origem, destino,
            responsavel, status, criado_por, perfil_criacao
        ) VALUES (?, '2026-07-25', ?, 'Abatedouro', ?, 'Operador', 'Aberto', 'Operador', 'pcp')
        """, (f"ROM-TESTE-{os.urandom(4).hex()}", tipo, destino))

    def test_01_marco_classifica_legado_sem_estoque_operacional(self):
        op = consultar_um("SELECT * FROM ordens_producao WHERE id = ?", (self.op_legada,))
        caixa = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (self.caixa_legada,))
        self.assertEqual(op["estoque_classificacao"], "LEGADA")
        self.assertEqual(op["estoque_marco_id"], self.marco["id"])
        self.assertEqual(caixa["estoque_operacional"], 0)
        self.assertEqual(caixa["disponibilidade"], "LEGADO")

    def test_02_op_nova_forma_estoque_uma_unica_vez_e_preserva_sku(self):
        self.contexto()
        op_cortada = self.criar_op_nova("Galinha Cortada")
        op_inteira = self.criar_op_nova("Galinha Inteira")
        caixa_cortada = self.criar_pa(op_cortada, "CX-NOVA-001", "Galinha Cortada")
        caixa_inteira = self.criar_pa(op_inteira, "GI-NOVA-001", "Galinha Inteira", peso=90)

        ativar_estoque_da_op(op_cortada)
        ativar_estoque_da_op(op_cortada)
        ativar_estoque_da_op(op_inteira)

        cortada = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_cortada,))
        inteira = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_inteira,))
        eventos = consultar_um(
            "SELECT COUNT(*) AS total FROM estoque_eventos WHERE idempotency_key = ?",
            (f"FORMACAO-PA-{caixa_cortada}",),
        )
        self.assertEqual(cortada["estoque_operacional"], 1)
        self.assertEqual(cortada["disponibilidade"], "DISPONIVEL")
        self.assertEqual(cortada["peso_tara"], 0.5)
        self.assertEqual(inteira["sku"], "Galinha Inteira")
        self.assertEqual(cortada["sku"], "Galinha Cortada")
        self.assertEqual(eventos["total"], 1)

    def test_03_op_aberta_nao_disponibiliza_pa(self):
        self.contexto()
        op_id = self.criar_op_nova(status="Aberta")
        caixa_id = self.criar_pa(op_id, "CX-PENDENTE-001", status_op="Aberta")
        ativar_estoque_da_op(op_id)
        caixa = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_id,))
        self.assertEqual(caixa["estoque_operacional"], 0)
        self.assertEqual(caixa["disponibilidade"], "PENDENTE_OP")

    def test_03b_pesagem_respeita_tara_e_aguarda_encerramento(self):
        self.contexto()
        op_id = self.criar_op_nova(status="Aberta")
        contexto = registrar_peso_caixa_op(op_id, "10,500")
        caixa = contexto["caixa_etiqueta"]
        self.assertEqual(caixa["peso_bruto"], 10.5)
        self.assertEqual(caixa["peso_tara"], 0.5)
        self.assertEqual(caixa["peso_liquido"], 10)
        self.assertEqual(caixa["disponibilidade"], "PENDENTE_OP")
        executar("UPDATE ordens_producao SET status = 'Encerrada' WHERE id = ?", (op_id,))
        ativar_estoque_da_op(op_id)
        formada = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa["id"],))
        self.assertEqual(formada["disponibilidade"], "DISPONIVEL")

    def test_04_reserva_exclusiva_cancelamento_confirmacao_e_estorno(self):
        self.contexto()
        op_id = self.criar_op_nova()
        caixa_id = self.criar_pa(op_id, "CX-FLUXO-001")
        ativar_estoque_da_op(op_id)
        romaneio_1 = self.criar_romaneio()
        romaneio_2 = self.criar_romaneio()

        reservar_itens(romaneio_1, [caixa_id])
        with self.assertRaises(ValueError):
            reservar_itens(romaneio_2, [caixa_id])
        cancelar_romaneio(romaneio_1, "Correção operacional")
        self.assertEqual(
            consultar_um("SELECT disponibilidade FROM pa_caixas WHERE id = ?", (caixa_id,))["disponibilidade"],
            "DISPONIVEL",
        )

        reservar_itens(romaneio_2, [caixa_id])
        concluir_romaneio(romaneio_2)
        transferido = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_id,))
        self.assertEqual(transferido["disponibilidade"], "TRANSFERIDO")
        self.assertEqual(transferido["local_estoque_id"], self.local_lsm)
        with self.assertRaises(ValueError):
            concluir_romaneio(romaneio_2)

        estornar_romaneio(romaneio_2, "Retorno autorizado")
        restaurado = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_id,))
        self.assertEqual(restaurado["disponibilidade"], "DISPONIVEL")
        self.assertEqual(restaurado["local_estoque_id"], self.local_abatedouro)

    def test_05_nao_conforme_segrega_fisico_e_exige_romaneio_especifico(self):
        self.contexto("qualidade")
        op_id = self.criar_op_nova()
        caixa_id = self.criar_pa(op_id, "CX-NC-001")
        ativar_estoque_da_op(op_id)
        bloquear_produto(caixa_id, "Embalagem avariada", "Segregado na zona de PNC")

        _, resumo = buscar_estoque_operacional()
        self.assertGreaterEqual(resumo["itens_fisicos"], 1)
        self.assertGreaterEqual(resumo["itens_bloqueados"], 1)
        romaneio_normal = self.criar_romaneio()
        with self.assertRaises(ValueError):
            reservar_itens(romaneio_normal, [caixa_id])

        destinar_produto(caixa_id, "LIBERAR", "Produto reinspecionado e aprovado")
        caixa = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_id,))
        self.assertEqual(caixa["condicao"], "CONFORME")
        self.assertEqual(caixa["disponibilidade"], "DISPONIVEL")

    def test_06_romaneio_historico_preserva_producao_e_nao_cria_estoque(self):
        self.contexto()
        status_antes = consultar_um("SELECT status FROM ordens_producao WHERE id = ?", (self.op_legada,))["status"]
        romaneio = self.criar_romaneio("HISTORICO_MARCO_ZERO")
        registrar_itens_historicos(romaneio, [
            {"sku": "Galinha Inteira", "quantidade_pacotes": 40, "galinhas_por_pacote": 1},
            {"sku": "Galinha Inteira", "quantidade_pacotes": 20, "galinhas_por_pacote": 2},
            {"sku": "Galinha Cortada", "quantidade": 120, "peso": 150},
        ])
        concluir_romaneio(romaneio)
        status_depois = consultar_um("SELECT status FROM ordens_producao WHERE id = ?", (self.op_legada,))["status"]
        self.assertEqual(status_antes, status_depois)
        self.assertEqual(buscar_expedicao_por_id(romaneio)["status"], "Concluído")
        self.assertEqual(len(buscar_itens_expedicao(romaneio)), 3)
        self.assertEqual(
            consultar_um("SELECT estoque_operacional FROM pa_caixas WHERE id = ?", (self.caixa_legada,))["estoque_operacional"],
            0,
        )

    def test_07_historico_reconstroi_movimentacao(self):
        eventos = buscar_historico_estoque()
        acoes = {evento["acao"] for evento in eventos}
        self.assertIn("FORMACAO_ESTOQUE", acoes)
        self.assertIn("RESERVA", acoes)
        self.assertIn("CONFIRMACAO_ROMANEIO", acoes)
        self.assertIn("ESTORNO_ROMANEIO", acoes)
        self.assertIn("BLOQUEIO_NAO_CONFORMIDADE", acoes)

    def test_08_perfis_e_impressao(self):
        for perfil in ("pcp", "qualidade"):
            cliente = self.app.test_client()
            with cliente.session_transaction() as sessao:
                sessao.update({"usuario_id": 1, "nome": perfil, "perfil": perfil})
            self.assertEqual(cliente.get("/expedicao").status_code, 200)
            self.assertEqual(cliente.get("/expedicao/estoque").status_code, 200)

        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 2, "nome": "Produção", "perfil": "producao"})
        self.assertEqual(cliente.get("/expedicao").status_code, 302)

        romaneio = self.criar_romaneio()
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 3, "nome": "PCP", "perfil": "pcp"})
        resposta = cliente.get(f"/expedicao/{romaneio}/imprimir")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"FrigoDatta", resposta.data)

    def test_09_validade_novos_registros_e_de_um_ano(self):
        self.assertEqual(calcular_validade_padrao("2026-07-24"), "2027-07-24")
        self.assertEqual(calcular_validade_padrao("2028-02-29"), "2029-02-28")

    def criar_cliente(self, documento, nome):
        self.contexto("pcp")
        return salvar_cliente({"razao_social": nome, "nome_fantasia": "Teste",
                               "tipo_pessoa": "PF", "documento": documento,
                               "cidade": "Manaus", "uf": "AM"})

    def test_10_cadastro_cliente_valida_documento_duplicidade_e_permissoes(self):
        cliente_id = self.criar_cliente("52998224725", "Cliente Teste")
        with self.assertRaisesRegex(ValueError, "já cadastrado"):
            salvar_cliente({"razao_social": "Duplicado", "tipo_pessoa": "PF",
                            "documento": "529.982.247-25"}, usuario="PCP", perfil="pcp")
        with self.assertRaisesRegex(ValueError, "inválido"):
            salvar_cliente({"razao_social": "Inválido", "tipo_pessoa": "PJ",
                            "documento": "123"}, usuario="PCP", perfil="pcp")
        with self.assertRaises(PermissionError):
            alterar_status(cliente_id, "Inativo", usuario="PCP", perfil="pcp")
        alterar_status(cliente_id, "Inativo", usuario="Gerente", perfil="gerencia")
        self.assertEqual(consultar_um("SELECT status FROM clientes WHERE id=?", (cliente_id,))["status"], "Inativo")
        pj = salvar_cliente({"razao_social": "Empresa Válida", "tipo_pessoa": "PJ",
                            "documento": "11.444.777/0001-61"}, usuario="PCP", perfil="pcp")
        self.assertEqual(consultar_um("SELECT documento FROM clientes WHERE id=?", (pj,))["documento"],
                         "11444777000161")

    def test_10b_permissoes_frontend_e_backend_clientes(self):
        cliente_id = self.criar_cliente("12345678909", "Cliente Permissões")
        for perfil, esperado in (("pcp", 200), ("gerencia", 200), ("expedicao", 200),
                                 ("producao", 302)):
            cliente = self.app.test_client()
            with cliente.session_transaction() as sessao:
                sessao.update({"usuario_id": 10, "nome": perfil, "perfil": perfil})
            self.assertEqual(cliente.get("/cadastros/clientes").status_code, esperado)
        expedicao = self.app.test_client()
        with expedicao.session_transaction() as sessao:
            sessao.update({"usuario_id": 11, "nome": "Expedição", "perfil": "expedicao"})
        self.assertEqual(expedicao.get("/cadastros/clientes/novo").status_code, 302)
        self.assertEqual(expedicao.get(f"/cadastros/clientes/{cliente_id}").status_code, 200)

    def test_11_venda_direta_caixa_regular_exige_cliente_e_preserva_snapshot(self):
        cliente_id = self.criar_cliente("11144477735", "Comprador Original")
        op_id = self.criar_op_nova()
        caixa_id = self.criar_pa(op_id, "CX-VENDA-DIRETA", peso=18)
        ativar_estoque_da_op(op_id)
        with self.assertRaisesRegex(ValueError, "cliente ativo"):
            salvar_romaneio_expedicao({"data": "2026-08-04", "tipo_saida": "VENDA_DIRETA",
                                       "responsavel": "PCP"})
        numero = salvar_romaneio_expedicao({
            "data": "2026-08-04", "tipo_saida": "VENDA_DIRETA", "cliente_id": cliente_id,
            "responsavel": "PCP", "veiculo": "ABC1D23", "motorista": "Motorista",
        })
        romaneio = consultar_um("SELECT * FROM expedicoes WHERE numero_romaneio=?", (numero,))
        self.assertEqual((romaneio["tipo_saida"], romaneio["tipo_movimentacao"], romaneio["destino"]),
                         ("VENDA_DIRETA", "VENDA_DIRETA", "Venda direta"))
        reservar_itens(romaneio["id"], [caixa_id])
        concluir_romaneio(romaneio["id"])
        caixa = consultar_um("SELECT * FROM pa_caixas WHERE id=?", (caixa_id,))
        final = consultar_um("SELECT * FROM expedicoes WHERE id=?", (romaneio["id"],))
        self.assertEqual(caixa["disponibilidade"], "EXPEDIDO")
        self.assertIsNone(final["destino_local_id"])
        self.assertIn("Comprador Original", final["cliente_snapshot"])
        salvar_cliente({"razao_social": "Nome Futuro", "tipo_pessoa": "PF",
                        "documento": "11144477735"}, cliente_id, usuario="PCP", perfil="pcp")
        self.assertEqual(buscar_expedicao_por_id(romaneio["id"])["cliente_nome"], "Comprador Original")
        navegador = self.app.test_client()
        with navegador.session_transaction() as sessao:
            sessao.update({"usuario_id": 12, "nome": "PCP", "perfil": "pcp"})
        impressao = navegador.get(f"/expedicao/{romaneio['id']}/imprimir").get_data(as_text=True)
        self.assertIn("ROMANEIO DE VENDA DIRETA", impressao)
        self.assertIn("Comprador Original", impressao)
        self.assertNotIn("Nome Futuro", impressao)
        central = navegador.get(
            f"/expedicao?data_inicio=2026-08-04&data_fim=2026-08-04&tipo=VENDA_DIRETA&cliente_id={cliente_id}"
        ).get_data(as_text=True)
        self.assertIn(numero, central)
        self.assertIn("Comprador Original", central)
        with self.assertRaisesRegex(ValueError, "abertos"):
            concluir_romaneio(romaneio["id"])

    def test_12_transferencia_lsm_permanece_sem_cliente(self):
        self.contexto("pcp")
        numero = salvar_romaneio_expedicao({"data": "2026-08-04",
            "tipo_saida": "TRANSFERENCIA_LSM", "responsavel": "PCP"})
        item = consultar_um("SELECT * FROM expedicoes WHERE numero_romaneio=?", (numero,))
        self.assertEqual(item["tipo_movimentacao"], "TRANSFERENCIA")
        self.assertEqual(item["tipo_saida"], "TRANSFERENCIA_LSM")
        self.assertEqual(item["destino"], "Câmara Fria LSM")
        self.assertIsNone(item["cliente_id"])

    def test_13_cliente_inativo_fica_no_historico_e_fora_da_selecao(self):
        cliente_id = self.criar_cliente("98765432100", "Cliente Inativável")
        alterar_status(cliente_id, "Inativo", usuario="Gerente", perfil="gerencia")
        self.assertNotIn(cliente_id, {item["id"] for item in listar_clientes(somente_ativos=True)})
        self.assertIn("CLIENTE_INATIVADO", {item["acao"] for item in historico_cliente(cliente_id)})
        navegador = self.app.test_client()
        with navegador.session_transaction() as sessao:
            sessao.update({"usuario_id": 13, "nome": "PCP", "perfil": "pcp"})
        self.assertNotIn("Cliente Inativável", navegador.get("/expedicao/novo").get_data(as_text=True))
        with self.assertRaises(PermissionError):
            alterar_status(cliente_id, "Ativo", usuario="PCP", perfil="pcp")
        self.assertIn("TENTATIVA_STATUS_NEGADA", {item["acao"] for item in historico_cliente(cliente_id)})

    def test_14_venda_direta_cancelamento_estorno_e_rollback_cliente_inativo(self):
        self.contexto("pcp")
        cliente_id = salvar_cliente({"razao_social": "Cliente Fluxo", "tipo_pessoa": "PJ"})
        op_cancelar = self.criar_op_nova()
        caixa_cancelar = self.criar_pa(op_cancelar, "CX-VD-CANCELAR", peso=21)
        ativar_estoque_da_op(op_cancelar)
        numero = salvar_romaneio_expedicao({"data": "2026-08-04", "tipo_saida": "VENDA_DIRETA",
                                            "cliente_id": cliente_id, "responsavel": "PCP"})
        romaneio = consultar_um("SELECT id FROM expedicoes WHERE numero_romaneio=?", (numero,))["id"]
        reservar_itens(romaneio, [caixa_cancelar])
        cancelar_romaneio(romaneio, "Venda cancelada antes da saída")
        self.assertEqual(consultar_um("SELECT disponibilidade FROM pa_caixas WHERE id=?",
                                     (caixa_cancelar,))["disponibilidade"], "DISPONIVEL")

        op_estorno = self.criar_op_nova()
        caixa_estorno = self.criar_pa(op_estorno, "CX-VD-ESTORNAR", peso=22)
        ativar_estoque_da_op(op_estorno)
        numero = salvar_romaneio_expedicao({"data": "2026-08-04", "tipo_saida": "VENDA_DIRETA",
                                            "cliente_id": cliente_id, "responsavel": "PCP"})
        romaneio = consultar_um("SELECT id FROM expedicoes WHERE numero_romaneio=?", (numero,))["id"]
        reservar_itens(romaneio, [caixa_estorno])
        concluir_romaneio(romaneio)
        estornar_romaneio(romaneio, "Retorno físico autorizado")
        self.assertEqual(consultar_um("SELECT disponibilidade FROM pa_caixas WHERE id=?",
                                     (caixa_estorno,))["disponibilidade"], "DISPONIVEL")
        with self.assertRaisesRegex(ValueError, "concluídos"):
            estornar_romaneio(romaneio, "Tentativa repetida")

        op_rollback = self.criar_op_nova()
        caixa_rollback = self.criar_pa(op_rollback, "CX-VD-ROLLBACK", peso=23)
        ativar_estoque_da_op(op_rollback)
        numero = salvar_romaneio_expedicao({"data": "2026-08-04", "tipo_saida": "VENDA_DIRETA",
                                            "cliente_id": cliente_id, "responsavel": "PCP"})
        romaneio = consultar_um("SELECT id FROM expedicoes WHERE numero_romaneio=?", (numero,))["id"]
        reservar_itens(romaneio, [caixa_rollback])
        alterar_status(cliente_id, "Inativo", usuario="Gerente", perfil="gerencia")
        with self.assertRaisesRegex(ValueError, "cliente ativo"):
            concluir_romaneio(romaneio)
        self.assertEqual(consultar_um("SELECT status FROM expedicoes WHERE id=?", (romaneio,))["status"],
                         "Aberto")
        self.assertEqual(consultar_um("SELECT disponibilidade FROM pa_caixas WHERE id=?",
                                     (caixa_rollback,))["disponibilidade"], "RESERVADO")

    def test_15_tipo_saida_obrigatorio(self):
        self.contexto("pcp")
        with self.assertRaisesRegex(ValueError, "Tipo de saída"):
            salvar_romaneio_expedicao({"data": "2026-08-04", "responsavel": "PCP"})


if __name__ == "__main__":
    unittest.main()
