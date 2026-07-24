"""Regressao da sprint corretiva de seguranca transacional da Expedicao."""

import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARQUIVO_BANCO = tempfile.NamedTemporaryFile(prefix="frigodatta-corretiva-", suffix=".db", delete=False)
ARQUIVO_BANCO.close()
os.environ["DB_NAME"] = ARQUIVO_BANCO.name
os.environ.pop("DATABASE_URL", None)

from flask import Flask, session  # noqa: E402

from database import conectar, q  # noqa: E402
from modules.expedicao.estoque_service import (  # noqa: E402
    buscar_estoque_operacional,
    cancelar_romaneio,
    concluir_romaneio,
    criar_tabelas_estoque_confiavel,
    destinar_produto,
    editar_romaneio_aberto,
    estornar_romaneio,
    registrar_emissao_romaneio,
    registrar_itens_historicos,
    reservar_itens,
)
from modules.expedicao.routes import register_expedicao_routes  # noqa: E402
from modules.expedicao.services import (  # noqa: E402
    buscar_expedicao_por_id,
    buscar_itens_expedicao,
    calcular_validade_padrao,
    criar_tabelas_expedicao,
    criar_tabelas_estoque_pi_pa,
    finalizar_embalagem_secundaria_op,
    registrar_apontamento_embalagem_primaria,
    registrar_caixa_pa_manual,
    salvar_romaneio_expedicao,
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
    cursor = conn.cursor()
    cursor.execute(q(sql), parametros)
    itens = cursor.fetchall()
    conn.close()
    return itens


def consultar_um(sql, parametros=()):
    itens = consultar(sql, parametros)
    return itens[0] if itens else None


class ExpedicaoCorretivaTest(unittest.TestCase):
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
            data TEXT,
            setor TEXT,
            quantidade REAL DEFAULT 0,
            unidade TEXT NOT NULL,
            observacoes TEXT
        );
        CREATE TABLE apontamentos_descartes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            setor TEXT,
            motivo TEXT,
            categoria TEXT,
            quantidade REAL DEFAULT 0,
            unidade TEXT
        );
        CREATE TABLE financeiro_teste (id INTEGER PRIMARY KEY, marcador TEXT);
        CREATE TABLE dre_teste (id INTEGER PRIMARY KEY, marcador TEXT);
        INSERT INTO financeiro_teste VALUES (1, 'preservado');
        INSERT INTO dre_teste VALUES (1, 'preservado');
        """)
        conn.commit()
        conn.close()
        criar_tabelas_expedicao()
        criar_tabelas_estoque_pi_pa()
        criar_tabelas_estoque_confiavel()
        cls.local_abatedouro = consultar_um(
            "SELECT id FROM locais_estoque WHERE nome = 'Abatedouro'"
        )["id"]
        cls.local_lsm = consultar_um(
            "SELECT id FROM locais_estoque WHERE nome = ?",
            ("Câmara Fria LSM",),
        )["id"]

        cls.app = Flask(__name__, template_folder=str(ROOT / "templates"))
        cls.app.secret_key = "teste"
        cls.app.config["TESTING"] = True
        cls.app.jinja_env.filters["br_numero"] = lambda valor, casas=2: f"{float(valor or 0):.{int(casas)}f}"
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

    def contexto(self, perfil="pcp", nome=None):
        contexto = self.app.test_request_context("/")
        contexto.push()
        session.update({"usuario_id": 1, "nome": nome or perfil, "perfil": perfil})
        self.addCleanup(contexto.pop)
        return contexto

    def criar_op(self, sku, aves, status="Aberta"):
        return executar("""
        INSERT INTO ordens_producao (
            data, fornecedor, quantidade_aves, peso_vivo, peso_medio, status, sku
        ) VALUES ('2026-07-25', 'Fornecedor', ?, 100, 2.5, ?, ?)
        """, (aves, status, sku))

    def criar_caixa_cortada(self, op_id, codigo):
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade,
            peso_bruto, peso_tara, peso_liquido, quantidade_bandejas,
            status, origem, local_estoque_id, estoque_operacional,
            condicao, disponibilidade, zona_estoque, unidade_estoque
        ) VALUES (?, 'Galinha Cortada', '2026-07-25', '2027-07-25',
                  10.5, 0.5, 10, 12, 'Em estoque', 'Embalagem Secundaria',
                  ?, 0, 'CONFORME', 'PENDENTE_OP', 'Conforme', 'CAIXA')
        """, (codigo, self.local_abatedouro))
        executar(
            "INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas) VALUES (?, ?, 12)",
            (caixa_id, op_id),
        )
        return caixa_id

    def preparar_cortada(self, codigo):
        op_id = self.criar_op("Galinha Cortada", 12)
        executar("""
        INSERT INTO embalagem_primaria_apontamentos (
            op_id, data_apontamento, sku, quantidade_bandejas
        ) VALUES (?, '2026-07-25', 'Galinha Cortada', 12)
        """, (op_id,))
        return op_id, self.criar_caixa_cortada(op_id, codigo)

    def criar_romaneio(self, tipo="TRANSFERENCIA", destino="Câmara Fria LSM"):
        return executar("""
        INSERT INTO expedicoes (
            numero_romaneio, data, tipo_movimentacao, origem, destino,
            responsavel, status, criado_por, perfil_criacao
        ) VALUES (?, '2026-07-25', ?, 'Abatedouro', ?, 'Operador',
                  'Aberto', 'Operador', 'pcp')
        """, (f"ROM-COR-{os.urandom(4).hex()}", tipo, destino))

    def test_01_galinha_inteira_forma_v1_v2_sem_peso_e_concilia_galinhas(self):
        self.contexto("producao")
        op_id = self.criar_op("Galinha Inteira", 8)
        op = consultar_um("SELECT * FROM ordens_producao WHERE id = ?", (op_id,))
        resultado = registrar_apontamento_embalagem_primaria(
            op, None, pacotes_1_ave=4, pacotes_2_aves=2
        )
        self.assertEqual(resultado["aves_embaladas"], 8)
        self.assertEqual(resultado["unidades_vendaveis"], 6)
        posicoes = consultar(
            "SELECT * FROM pa_caixas WHERE codigo_caixa LIKE ? ORDER BY apresentacao",
            (f"GI-PCT-OP-{op_id:05d}-%",),
        )
        self.assertEqual(len(posicoes), 2)
        self.assertEqual({item["quantidade_pacotes"] for item in posicoes}, {2, 4})
        self.assertEqual(sum(item["quantidade_galinhas"] for item in posicoes), 8)
        self.assertTrue(all(item["peso_bruto"] is None for item in posicoes))
        self.assertTrue(all(item["peso_liquido"] is None for item in posicoes))
        self.assertTrue(all(item["peso_tara"] is None for item in posicoes))
        producao_final = consultar_um("""
        SELECT quantidade FROM apontamentos_producao
        WHERE op_id = ? AND setor = 'Expedição' AND unidade = 'unidades'
        """, (op_id,))
        self.assertEqual(producao_final["quantidade"], 8)
        with self.assertRaises(ValueError):
            registrar_apontamento_embalagem_primaria(
                op, None, pacotes_1_ave=4, pacotes_2_aves=2
            )
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM pa_caixa_composicao WHERE op_id = ?", (op_id,)
        )["total"], 2)

    def test_02_saida_parcial_de_gi_exige_pacotes_inteiros(self):
        self.contexto()
        op_id = self.criar_op("Galinha Inteira", 6)
        op = consultar_um("SELECT * FROM ordens_producao WHERE id = ?", (op_id,))
        registrar_apontamento_embalagem_primaria(op, None, pacotes_1_ave=6, pacotes_2_aves=0)
        posicao = consultar_um("SELECT * FROM pa_caixas WHERE codigo_caixa = ?", (f"GI-PCT-OP-{op_id:05d}-V1",))
        romaneio = self.criar_romaneio()
        with self.assertRaises(ValueError):
            reservar_itens(romaneio, [posicao["id"]], {posicao["id"]: 1.5})
        reservar_itens(romaneio, [posicao["id"]], {posicao["id"]: 2})
        item = buscar_itens_expedicao(romaneio)[0]
        self.assertEqual(item["quantidade_pacotes"], 2)
        self.assertEqual(item["quantidade_galinhas"], 2)
        concluir_romaneio(romaneio)
        saldo = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (posicao["id"],))
        self.assertEqual(saldo["quantidade_pacotes"], 4)
        self.assertEqual(saldo["quantidade_galinhas"], 4)
        self.assertEqual(saldo["local_estoque_id"], self.local_abatedouro)
        estornar_romaneio(romaneio, "Retorno conferido ao estoque")
        saldo_estornado = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (posicao["id"],))
        self.assertEqual(saldo_estornado["quantidade_pacotes"], 6)
        self.assertEqual(saldo_estornado["quantidade_galinhas"], 6)
        self.assertEqual(saldo_estornado["local_estoque_id"], self.local_abatedouro)
        self.assertEqual(
            consultar_um("SELECT status FROM expedicoes WHERE id = ?", (romaneio,))["status"],
            "Estornado",
        )

        romaneio_cancelado = self.criar_romaneio()
        reservar_itens(romaneio_cancelado, [posicao["id"]], {posicao["id"]: 3})
        cancelar_romaneio(romaneio_cancelado, "Reserva operacional cancelada")
        saldo_cancelado = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (posicao["id"],))
        self.assertEqual(saldo_cancelado["quantidade_pacotes"], 6)
        self.assertEqual(saldo_cancelado["quantidade_pacotes_reservados"], 0)
        self.assertEqual(saldo_cancelado["disponibilidade"], "DISPONIVEL")

    def test_03_falhas_gi_fazem_rollback_integral(self):
        self.contexto("producao")
        for indice, etapa in enumerate((
            "antes_formacao_estoque",
            "durante_formacao_estoque",
            "apos_formacao_estoque",
        )):
            op_id = self.criar_op("Galinha Inteira", 4)
            op = consultar_um("SELECT * FROM ordens_producao WHERE id = ?", (op_id,))

            def falhar(atual, alvo=etapa):
                if atual == alvo:
                    raise RuntimeError(f"falha-{indice}")

            with self.assertRaises(RuntimeError):
                registrar_apontamento_embalagem_primaria(
                    op, None, pacotes_1_ave=2, pacotes_2_aves=1, checkpoint=falhar
                )
            self.assertEqual(
                consultar_um("SELECT status FROM ordens_producao WHERE id = ?", (op_id,))["status"],
                "Aberta",
            )
            self.assertEqual(consultar_um(
                "SELECT COUNT(*) total FROM pa_caixa_composicao WHERE op_id = ?", (op_id,)
            )["total"], 0)
            self.assertEqual(consultar_um(
                "SELECT COUNT(*) total FROM apontamentos_producao WHERE op_id = ?", (op_id,)
            )["total"], 0)

    def test_04_cortada_mantem_caixa_tara_e_rollback_transacional(self):
        self.contexto("producao")
        for indice, etapa in enumerate((
            "antes_formacao_estoque",
            "durante_formacao_estoque",
            "apos_formacao_estoque",
        )):
            op_id, caixa_id = self.preparar_cortada(f"CX-ROLL-{indice}")

            def falhar(atual, alvo=etapa):
                if atual == alvo:
                    raise RuntimeError(alvo)

            with self.assertRaises(RuntimeError):
                finalizar_embalagem_secundaria_op(op_id, checkpoint=falhar)
            self.assertEqual(
                consultar_um("SELECT status FROM ordens_producao WHERE id = ?", (op_id,))["status"],
                "Aberta",
            )
            caixa = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_id,))
            self.assertEqual(caixa["peso_tara"], 0.5)
            self.assertEqual(caixa["peso_liquido"], 10)
            self.assertEqual(caixa["estoque_operacional"], 0)
            self.assertEqual(consultar_um(
                "SELECT COUNT(*) total FROM apontamentos_producao WHERE op_id = ?", (op_id,)
            )["total"], 0)

    def test_05_reenvio_nao_duplica_cortada(self):
        self.contexto("pcp")
        op_id, caixa_id = self.preparar_cortada("CX-IDEMP-1")
        finalizar_embalagem_secundaria_op(op_id)
        producoes = consultar_um(
            "SELECT COUNT(*) total FROM apontamentos_producao WHERE op_id = ?", (op_id,)
        )["total"]
        with self.assertRaises(ValueError):
            finalizar_embalagem_secundaria_op(op_id)
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM apontamentos_producao WHERE op_id = ?", (op_id,)
        )["total"], producoes)
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM estoque_eventos WHERE idempotency_key = ?",
            (f"FORMACAO-PA-{caixa_id}",),
        )["total"], 1)

    def test_06_permissoes_encerramento_e_camara(self):
        for indice, perfil in enumerate(("pcp", "producao")):
            op_id, _ = self.preparar_cortada(f"CX-PERFIL-{indice}")
            cliente = self.app.test_client()
            with cliente.session_transaction() as sessao:
                sessao.update({"usuario_id": 1, "nome": perfil, "perfil": perfil})
            self.assertNotEqual(cliente.get("/embalagem-secundaria").status_code, 302)
            self.assertEqual(
                cliente.post(f"/embalagem-secundaria/{op_id}/finalizar").status_code,
                302,
            )
            self.assertEqual(
                consultar_um("SELECT status FROM ordens_producao WHERE id = ?", (op_id,))["status"],
                "Encerrada",
            )
        op_bloqueada, _ = self.preparar_cortada("CX-PERFIL-BLOQ")
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 2, "nome": "Qualidade", "perfil": "qualidade"})
        self.assertEqual(cliente.get("/embalagem-secundaria").status_code, 302)
        self.assertEqual(
            cliente.post(f"/embalagem-secundaria/{op_bloqueada}/finalizar").status_code,
            302,
        )
        self.assertEqual(
            consultar_um("SELECT status FROM ordens_producao WHERE id = ?", (op_bloqueada,))["status"],
            "Aberta",
        )
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 3, "nome": "Produção", "perfil": "producao"})
        self.assertEqual(cliente.get("/expedicao").status_code, 302)

    def test_07_mz_audita_acoes_e_gi_nao_exige_peso(self):
        self.contexto("qualidade", "Auditora")
        numero = salvar_romaneio_expedicao({
            "data": "2026-07-25",
            "tipo_movimentacao": "HISTORICO_MARCO_ZERO",
            "origem": "Abatedouro",
            "responsavel": "Auditora",
            "observacoes": "Levantamento",
        })
        romaneio = consultar_um("SELECT * FROM expedicoes WHERE numero_romaneio = ?", (numero,))
        editar_romaneio_aberto(romaneio["id"], {
            "data": "2026-07-25",
            "origem": "Abatedouro",
            "destino": "texto ignorado",
            "responsavel": "Auditora",
            "observacoes": "Conferido",
        })
        registrar_itens_historicos(romaneio["id"], [
            {"sku": "Galinha Inteira", "quantidade_pacotes": 3, "galinhas_por_pacote": 1},
            {"sku": "Galinha Inteira", "quantidade_pacotes": 2, "galinhas_por_pacote": 2},
            {"sku": "Galinha Cortada", "quantidade": 4, "peso": 40},
        ])
        registrar_emissao_romaneio(romaneio["id"])
        concluir_romaneio(romaneio["id"])
        itens = buscar_itens_expedicao(romaneio["id"])
        inteiras = [item for item in itens if item["sku"] == "Galinha Inteira"]
        self.assertTrue(all(item["quantidade_kg"] is None for item in inteiras))
        self.assertEqual(sum(item["quantidade_galinhas"] for item in inteiras), 7)
        eventos = consultar(
            "SELECT * FROM estoque_eventos WHERE expedicao_id = ?", (romaneio["id"],)
        )
        acoes = {item["acao"] for item in eventos}
        self.assertTrue({
            "CRIACAO_ROMANEIO", "CABECALHO_ROMANEIO_ALTERADO",
            "TOTAIS_MZ_ALTERADOS", "EMISSAO_ROMANEIO", "CONCLUSAO_MZ",
        }.issubset(acoes))
        self.assertTrue(all(item["usuario"] and item["perfil"] and item["criado_em"] for item in eventos))
        evento_totais = next(item for item in eventos if item["acao"] == "TOTAIS_MZ_ALTERADOS")
        self.assertIn('"antes"', evento_totais["observacao"])
        self.assertIn('"depois"', evento_totais["observacao"])
        mz_cancelado = self.criar_romaneio("HISTORICO_MARCO_ZERO")
        cancelar_romaneio(mz_cancelado, "Documento substituido antes da conclusao")
        evento_cancelamento = consultar_um("""
        SELECT * FROM estoque_eventos
        WHERE expedicao_id = ? AND acao = 'CANCELAMENTO_MZ'
        """, (mz_cancelado,))
        self.assertIsNotNone(evento_cancelamento)
        self.assertIn("Documento substituido", evento_cancelamento["justificativa"])

    def test_08_destino_invalido_bloqueia_e_valido_move_para_local_documentado(self):
        self.contexto()
        op_id, caixa_id = self.preparar_cortada("CX-DESTINO-1")
        finalizar_embalagem_secundaria_op(op_id)
        romaneio = self.criar_romaneio(destino="Destino livre")
        reservar_itens(romaneio, [caixa_id])
        with self.assertRaises(ValueError):
            concluir_romaneio(romaneio)
        self.assertEqual(
            consultar_um("SELECT disponibilidade FROM pa_caixas WHERE id = ?", (caixa_id,))["disponibilidade"],
            "RESERVADO",
        )
        executar("UPDATE expedicoes SET destino = ? WHERE id = ?", ("Câmara Fria LSM", romaneio))
        concluir_romaneio(romaneio)
        documento = buscar_expedicao_por_id(romaneio)
        caixa = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_id,))
        self.assertEqual(documento["destino_local_id"], self.local_lsm)
        self.assertEqual(caixa["local_estoque_id"], self.local_lsm)

    def test_09_reprocessamento_reconcilia_estoque_fisico(self):
        self.contexto("qualidade")
        op_id, caixa_id = self.preparar_cortada("CX-REPROCESSO-1")
        finalizar_embalagem_secundaria_op(op_id)
        executar("""
        UPDATE pa_caixas SET condicao = 'NAO_CONFORME', disponibilidade = 'BLOQUEADO'
        WHERE id = ?
        """, (caixa_id,))
        destinar_produto(caixa_id, "REPROCESSAMENTO", "Reprocessar internamente")
        _, resumo = buscar_estoque_operacional()
        soma = (
            resumo["unidades_disponiveis"]
            + resumo["unidades_reservadas"]
            + resumo["unidades_bloqueadas"]
            + resumo["unidades_reprocessamento"]
            + resumo["unidades_outras_condicoes"]
        )
        self.assertEqual(resumo["unidades_fisicas"], soma)
        self.assertGreaterEqual(resumo["unidades_reprocessamento"], 1)

    def test_10_impressao_diferencia_skus_legado_e_modulos_preservados(self):
        self.contexto()
        romaneio = self.criar_romaneio()
        executar("""
        INSERT INTO expedicao_itens (
            expedicao_id, sku, quantidade_unidades, quantidade_kg,
            unidade_estoque, apresentacao, galinhas_por_pacote,
            quantidade_pacotes, quantidade_galinhas, lote
        ) VALUES (?, 'Galinha Inteira', 2, NULL, 'PACOTE',
                  'Pacote com 2 galinhas inteiras', 2, 2, 4, 'GI-TESTE')
        """, (romaneio,))
        executar("""
        INSERT INTO expedicao_itens (
            expedicao_id, sku, quantidade_unidades, quantidade_kg,
            unidade_estoque, peso_bruto, peso_tara, lote
        ) VALUES (?, 'Galinha Cortada', 12, 10, 'CAIXA', 10.5, 0.5, 'CX-TESTE')
        """, (romaneio,))
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": "PCP", "perfil": "pcp"})
        resposta = cliente.get(f"/expedicao/{romaneio}/imprimir")
        self.assertEqual(resposta.status_code, 200)
        texto = resposta.get_data(as_text=True)
        self.assertIn("controle por pacotes", texto)
        self.assertIn("Não aplicável", texto)
        self.assertIn("Peso bruto", texto)
        self.assertIn("Emitido por", texto)
        self.assertEqual(consultar_um("SELECT marcador FROM financeiro_teste WHERE id = 1")["marcador"], "preservado")
        self.assertEqual(consultar_um("SELECT marcador FROM dre_teste WHERE id = 1")["marcador"], "preservado")
        legado = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, status, local_estoque_id,
            estoque_operacional, disponibilidade
        ) VALUES ('LEGADO-VISUAL', 'Galinha Inteira', 'Historico', ?, 0, 'LEGADO')
        """, (self.local_abatedouro,))
        self.assertEqual(
            consultar_um("SELECT estoque_operacional FROM pa_caixas WHERE id = ?", (legado,))["estoque_operacional"],
            0,
        )
        resposta_legado = cliente.get("/estoque-produtos")
        self.assertEqual(resposta_legado.status_code, 200)
        self.assertIn("Registro histórico anterior ao marco zero", resposta_legado.get_data(as_text=True))
        self.assertIn("Não compõe o estoque operacional", resposta_legado.get_data(as_text=True))

    def test_11_validade_da_cortada_e_validada_no_backend(self):
        op_id = self.criar_op("Galinha Cortada", 12)
        executar("""
        INSERT INTO estoque_produto_intermediario (
            data_movimentacao, tipo, op_id, sku, quantidade_bandejas
        ) VALUES ('2026-07-25', 'ENTRADA_EMBALAGEM_PRIMARIA', ?,
                  'Galinha Cortada', 12)
        """, (op_id,))
        with self.assertRaises(ValueError):
            registrar_caixa_pa_manual({
                "op_principal": str(op_id),
                "bandejas_principal": "12",
                "peso_bruto": "10.500",
                "data_fabricacao": "2026-07-25",
                "data_validade": "2028-07-25",
            })
        self.assertEqual(calcular_validade_padrao("2026-07-25"), "2027-07-25")

    def test_12_caixa_parcial_e_complementar_preservam_peso_sem_dupla_formacao(self):
        self.contexto("pcp")
        op_a = self.criar_op("Galinha Cortada", 6)
        op_b = self.criar_op("Galinha Cortada", 6)
        for op_id in (op_a, op_b):
            executar("""
            INSERT INTO embalagem_primaria_apontamentos (
                op_id, data_apontamento, sku, quantidade_bandejas
            ) VALUES (?, '2026-07-25', 'Galinha Cortada', 6)
            """, (op_id,))
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade,
            peso_bruto, peso_tara, peso_liquido, quantidade_bandejas,
            status, origem, local_estoque_id, estoque_operacional,
            condicao, disponibilidade, zona_estoque, unidade_estoque
        ) VALUES ('CX-MISTA-1', 'Galinha Cortada', '2026-07-25', '2027-07-25',
                  10.5, 0.5, 10, 12, 'Em estoque', 'Embalagem Secundaria',
                  ?, 0, 'CONFORME', 'PENDENTE_OP', 'Conforme', 'CAIXA')
        """, (self.local_abatedouro,))
        executar(
            "INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas) VALUES (?, ?, 6)",
            (caixa_id, op_a),
        )
        executar(
            "INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas) VALUES (?, ?, 6)",
            (caixa_id, op_b),
        )
        finalizar_embalagem_secundaria_op(op_a)
        self.assertEqual(
            consultar_um("SELECT estoque_operacional FROM pa_caixas WHERE id = ?", (caixa_id,))["estoque_operacional"],
            0,
        )
        finalizar_embalagem_secundaria_op(op_b)
        self.assertEqual(
            consultar_um("SELECT estoque_operacional FROM pa_caixas WHERE id = ?", (caixa_id,))["estoque_operacional"],
            1,
        )
        pesos = consultar("""
        SELECT op_id, quantidade FROM apontamentos_producao
        WHERE op_id IN (?, ?) AND setor = 'Expedição' AND unidade = 'kg'
        ORDER BY op_id
        """, (op_a, op_b))
        self.assertEqual(sum(item["quantidade"] for item in pesos), 10)
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM estoque_eventos WHERE idempotency_key = ?",
            (f"FORMACAO-PA-{caixa_id}",),
        )["total"], 1)

        op_parcial = self.criar_op("Galinha Cortada", 6)
        executar("""
        INSERT INTO embalagem_primaria_apontamentos (
            op_id, data_apontamento, sku, quantidade_bandejas
        ) VALUES (?, '2026-07-25', 'Galinha Cortada', 6)
        """, (op_parcial,))
        caixa_parcial = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade,
            peso_bruto, peso_tara, peso_liquido, quantidade_bandejas,
            status, origem, local_estoque_id, estoque_operacional,
            condicao, disponibilidade, zona_estoque, unidade_estoque
        ) VALUES ('CX-PARCIAL-1', 'Galinha Cortada', '2026-07-25', '2027-07-25',
                  5.5, 0.5, 5, 6, 'Em estoque', 'Embalagem Secundaria',
                  ?, 0, 'CONFORME', 'PENDENTE_OP', 'Conforme', 'CAIXA')
        """, (self.local_abatedouro,))
        executar(
            "INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas) VALUES (?, ?, 6)",
            (caixa_parcial, op_parcial),
        )
        finalizar_embalagem_secundaria_op(op_parcial)
        parcial = consultar_um("SELECT * FROM pa_caixas WHERE id = ?", (caixa_parcial,))
        self.assertEqual(parcial["quantidade_bandejas"], 6)
        self.assertEqual(parcial["peso_tara"], 0.5)
        self.assertEqual(parcial["peso_liquido"], 5)


if __name__ == "__main__":
    unittest.main()
