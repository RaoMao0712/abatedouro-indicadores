"""Regressao da sprint corretiva de seguranca transacional da Expedicao."""

import os
from pathlib import Path
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest import mock


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
    remover_item_reservado,
    reservar_itens,
)
from modules.expedicao.routes import register_expedicao_routes  # noqa: E402
from modules.expedicao import estornos_embalagem as estornos_embalagem  # noqa: E402
from modules.expedicao import encerramento_op  # noqa: E402
from modules.expedicao.encerramento_op import preflight_encerramento_op  # noqa: E402
from modules.expedicao.conferencia_embalagem import (  # noqa: E402
    confirmar_conferencia_op,
    obter_conferencia_op,
)
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
from modules.producao.operacoes_op import (  # noqa: E402
    criar_tabelas_operacoes_op,
    retomar_embalagem_secundaria,
)
from modules.producao import integridade_encerramento as integridade  # noqa: E402
from modules.producao.commands import register_producao_commands  # noqa: E402
from modules.producao.integridade_encerramento import (  # noqa: E402
    ENCERRADA,
    ESTADO_INCONSISTENTE,
    PRONTA_PARA_ENCERRAMENTO,
    auditar_integridade_encerramento,
    montar_paineis_encerramento,
    obter_estado_funcional_op,
)
from modules.qualidade.produtos_nao_conformes import criar_tabelas_pa_nao_conforme  # noqa: E402


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
        criar_tabelas_operacoes_op()
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
        register_producao_commands(cls.app)

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

    def preparar_cortada_integra(self, codigo):
        op_id, caixa_id = self.preparar_cortada(codigo)
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes)
            VALUES('2026-07-25','ENTRADA_EMBALAGEM_PRIMARIA',?,'Galinha Cortada',12,
            'Embalagem Primária','Fixture íntegro')""", (op_id,))
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,caixa_id,
            observacoes,idempotency_key)
            VALUES('2026-07-25','SAIDA_EMBALAGEM_SECUNDARIA',?,'Galinha Cortada',12,
            'Embalagem Secundária',?,'Fixture íntegro',?)""",
            (op_id, caixa_id, f"FIXTURE-PI-{caixa_id}"))
        return op_id, caixa_id

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
        repeticao = registrar_apontamento_embalagem_primaria(
            op, None, pacotes_1_ave=4, pacotes_2_aves=2
        )
        self.assertTrue(repeticao["ja_encerrada"])
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM estoque_eventos WHERE acao='FORMACAO_ESTOQUE' "
            "AND caixa_id IN (SELECT caixa_id FROM pa_caixa_composicao WHERE op_id=?)",
            (op_id,),
        )["total"], 2)
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
        repeticao = finalizar_embalagem_secundaria_op(op_id)
        self.assertTrue(repeticao["ja_encerrada"])
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
                409,
            )
            self.assertEqual(
                consultar_um("SELECT status FROM ordens_producao WHERE id = ?", (op_id,))["status"],
                "Aberta",
            )
            conferencia = obter_conferencia_op(op_id)
            confirmar_conferencia_op(
                op_id, usuario=perfil, perfil=perfil,
                hash_informado=conferencia["hash"],
            )
            self.assertEqual(
                cliente.post(
                    f"/embalagem-secundaria/{op_id}/finalizar",
                    data={"conferencia_hash": conferencia["hash"]},
                ).status_code,
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
        with self.assertRaisesRegex(ValueError, "composição mista"):
            finalizar_embalagem_secundaria_op(op_a)
        self.assertEqual(
            consultar_um("SELECT estoque_operacional FROM pa_caixas WHERE id = ?", (caixa_id,))["estoque_operacional"],
            0,
        )
        with self.assertRaisesRegex(ValueError, "composição mista"):
            finalizar_embalagem_secundaria_op(op_b)
        self.assertEqual(
            consultar_um("SELECT estoque_operacional FROM pa_caixas WHERE id = ?", (caixa_id,))["estoque_operacional"],
            0,
        )
        pesos = consultar("""
        SELECT op_id, quantidade FROM apontamentos_producao
        WHERE op_id IN (?, ?) AND setor = 'Expedição' AND unidade = 'kg'
        ORDER BY op_id
        """, (op_a, op_b))
        self.assertEqual(sum(item["quantidade"] for item in pesos), 0)
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM estoque_eventos WHERE idempotency_key = ?",
            (f"FORMACAO-PA-{caixa_id}",),
        )["total"], 0)

    def test_13_idempotencia_da_inclusao_individual_usa_identidade_da_requisicao(self):
        self.contexto("pcp")
        op_id = self.criar_op("Galinha Cortada", 24)
        executar("""INSERT INTO embalagem_primaria_apontamentos(
            op_id,data_apontamento,sku,quantidade_bandejas)
            VALUES(?,'2026-07-25','Galinha Cortada',24)""", (op_id,))
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem)
            VALUES('2026-07-25','ENTRADA_EMBALAGEM_PRIMARIA',?,'Galinha Cortada',24,'Teste')""", (op_id,))
        formulario = {
            "op_principal": str(op_id), "bandejas_principal": "12",
            "peso_bruto": "10.500", "data_fabricacao": "2026-07-25",
            "data_validade": "2027-07-25", "idempotency_key": "INCLUSAO-IDEM-1",
        }
        primeiro = registrar_caixa_pa_manual(formulario, usuario="pcp")
        segundo = registrar_caixa_pa_manual(formulario, usuario="pcp")
        self.assertEqual(segundo, primeiro)
        self.assertEqual(consultar_um(
            "SELECT usuario_pesagem FROM pa_caixas WHERE codigo_caixa=?", (primeiro,)
        )["usuario_pesagem"], "pcp")
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM pa_caixa_composicao WHERE op_id=?", (op_id,)
        )["total"], 1)
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM estoque_produto_intermediario WHERE op_id=? AND tipo='SAIDA_EMBALAGEM_SECUNDARIA'", (op_id,)
        )["total"], 1)
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": "pcp", "perfil": "pcp"})
        resposta = cliente.get(f"/embalagem-secundaria?op_id={op_id}")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Conferência de Caixas da OP", resposta.get_data(as_text=True))

    def test_14_retry_com_saldo_zerado_e_caixas_reais_de_mesmo_peso(self):
        op_retry = self.criar_op("Galinha Cortada", 12)
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem)
            VALUES('2026-07-25','ENTRADA_EMBALAGEM_PRIMARIA',?,'Galinha Cortada',12,'Teste')""", (op_retry,))
        formulario = {
            "op_principal": str(op_retry), "bandejas_principal": "12", "peso_bruto": "10.500",
            "data_fabricacao": "2026-07-25", "data_validade": "2027-07-25",
            "idempotency_key": "RETRY-SALDO-ZERO",
        }
        primeiro = registrar_caixa_pa_manual(formulario, usuario="pcp")
        self.assertEqual(registrar_caixa_pa_manual(formulario, usuario="pcp"), primeiro)
        auditoria_retry = consultar_um(
            "SELECT repeticoes,ultimo_reenvio_em FROM embalagem_secundaria_requisicoes WHERE idempotency_key=?",
            ("RETRY-SALDO-ZERO",),
        )
        self.assertEqual(auditoria_retry["repeticoes"], 1)
        self.assertTrue(auditoria_retry["ultimo_reenvio_em"])
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM pa_caixa_composicao WHERE op_id=?", (op_retry,)
        )["total"], 1)

        op_mesmo_peso = self.criar_op("Galinha Cortada", 24)
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem)
            VALUES('2026-07-25','ENTRADA_EMBALAGEM_PRIMARIA',?,'Galinha Cortada',24,'Teste')""", (op_mesmo_peso,))
        base = dict(formulario, op_principal=str(op_mesmo_peso))
        caixa_a = registrar_caixa_pa_manual(dict(base, idempotency_key="PESO-REAL-A"), usuario="pcp")
        caixa_b = registrar_caixa_pa_manual(dict(base, idempotency_key="PESO-REAL-B"), usuario="pcp")
        self.assertNotEqual(caixa_a, caixa_b)
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM pa_caixa_composicao WHERE op_id=?", (op_mesmo_peso,)
        )["total"], 2)

    def test_15_continuidade_a_b_c_estorna_b_lanca_d_confere_e_encerra(self):
        os.environ["SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED"] = "true"
        op_id = self.criar_op("Galinha Cortada", 36)
        executar("""INSERT INTO embalagem_primaria_apontamentos(
            op_id,data_apontamento,sku,quantidade_bandejas)
            VALUES(?,'2026-07-25','Galinha Cortada',36)""", (op_id,))
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem)
            VALUES('2026-07-25','ENTRADA_EMBALAGEM_PRIMARIA',?,'Galinha Cortada',36,'Teste')""", (op_id,))
        def lancar(chave, peso):
            return registrar_caixa_pa_manual({
                "op_principal": str(op_id), "bandejas_principal": "12", "peso_bruto": peso,
                "data_fabricacao": "2026-07-25", "data_validade": "2027-07-25",
                "idempotency_key": chave,
            }, usuario="pcp")
        codigos = [lancar("CONT-A", "10.500"), lancar("CONT-B", "10.600"), lancar("CONT-C", "10.700")]
        caixa_b = consultar_um("SELECT id FROM pa_caixas WHERE codigo_caixa=?", (codigos[1],))["id"]
        estornos_embalagem.estornar_caixa_embalagem_secundaria(
            op_id, caixa_b, usuario="pcp", perfil="pcp", justificativa="Peso informado incorretamente",
            idempotency_key="CONT-EST-B",
        )
        codigo_d = lancar("CONT-D", "10.800")
        painel = obter_conferencia_op(op_id, {"situacao": "todas"})
        confirmar_conferencia_op(op_id, usuario="pcp", perfil="pcp", hash_informado=painel["hash"])
        finalizar_embalagem_secundaria_op(
            op_id, conferencia_hash=painel["hash"], exigir_conferencia=True,
        )
        caixas = consultar("""SELECT codigo_caixa,status FROM pa_caixas
            WHERE id IN (SELECT caixa_id FROM pa_caixa_composicao WHERE op_id=?) ORDER BY id""", (op_id,))
        self.assertEqual([item["codigo_caixa"] for item in caixas if item["status"] == "Em estoque"],
                         [codigos[0], codigos[2], codigo_d])
        self.assertEqual([item["codigo_caixa"] for item in caixas if item["status"] == "Estornada"], [codigos[1]])
        self.assertEqual(consultar_um("SELECT status FROM ordens_producao WHERE id=?", (op_id,))["status"], "Encerrada")

    def test_16_cenario_op_83_d1_d8_estorno_retomada_d12_e_encerramento(self):
        self.contexto("pcp", "Supervisora")
        criar_tabelas_pa_nao_conforme()
        op_id = self.criar_op("Galinha Cortada", 36, status="Aguardando Embalagem Secundária")
        executar("""INSERT INTO embalagem_primaria_apontamentos(
            op_id,data_apontamento,sku,quantidade_bandejas,observacoes)
            VALUES(?,'2026-07-25','Galinha Cortada',36,'Produção D1')""", (op_id,))
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes)
            VALUES('2026-07-25','ENTRADA_EMBALAGEM_PRIMARIA',?,'Galinha Cortada',36,
            'Embalagem Primária','Produção D1')""", (op_id,))
        caixa_ativa = self.criar_caixa_cortada(op_id, f"CX-OP83-{op_id}-ATIVA")
        caixa_estornada = self.criar_caixa_cortada(op_id, f"CX-OP83-{op_id}-DUP")
        for caixa_id in (caixa_ativa, caixa_estornada):
            executar("""INSERT INTO estoque_produto_intermediario(
                data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,caixa_id,
                observacoes,idempotency_key) VALUES(
                '2026-08-01','SAIDA_EMBALAGEM_SECUNDARIA',?,'Galinha Cortada',12,
                'Embalagem Secundária',?,'Apontamento D8',?)""",
                (op_id, caixa_id, f"OP83-SAIDA-{caixa_id}"))
        executar("UPDATE pa_caixas SET status='Estornada',estoque_operacional=0,disponibilidade='ESTORNADO' WHERE id=?", (caixa_estornada,))
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,caixa_id,
            movimento_origem_id,observacoes,idempotency_key) VALUES(
            '2026-08-01','ENTRADA_ESTORNO_CAIXA',?,'Galinha Cortada',12,
            'Estorno de duplicidade',?,NULL,'Correção D8',?)""",
            (op_id, caixa_estornada, f"OP83-ESTORNO-{caixa_estornada}"))
        painel_anterior = obter_conferencia_op(op_id)
        confirmar_conferencia_op(op_id, usuario="Supervisora", perfil="pcp", hash_informado=painel_anterior["hash"])

        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": "Supervisora", "perfil": "pcp"})
        preflight_estorno = cliente.get(f"/embalagem-secundaria/{op_id}/estorno/preflight")
        self.assertEqual(preflight_estorno.status_code, 200)
        self.assertIn("permitido", preflight_estorno.get_json())
        estorno_sem_csrf = cliente.post(f"/embalagem-secundaria/{op_id}/estornar", data={})
        self.assertEqual(estorno_sem_csrf.status_code, 403)
        self.assertIn("Estorno integral não executado", estorno_sem_csrf.get_data(as_text=True))
        pagina_antes = cliente.get(f"/embalagem-secundaria?op_id={op_id}")
        html_antes = pagina_antes.get_data(as_text=True)
        self.assertEqual(pagina_antes.status_code, 200)
        self.assertIn("Retomar Embalagem Secundária", html_antes)
        self.assertIn("Continue o apontamento das caixas restantes", html_antes)
        self.assertNotIn('id="form-caixa-individual"', html_antes)

        resultado = retomar_embalagem_secundaria(
            op_id, usuario="Supervisora", perfil="pcp", idempotency_key=f"RETOMAR-OP83-{op_id}",
            confirmacao=True,
        )
        self.assertEqual(resultado["status_op_posterior"], "Aberta")
        self.assertFalse(obter_conferencia_op(op_id)["confirmacao_valida"])
        pagina_depois = cliente.get(f"/embalagem-secundaria?op_id={op_id}")
        html_depois = pagina_depois.get_data(as_text=True)
        self.assertIn('id="form-caixa-individual"', html_depois)
        self.assertIn('name="data_fabricacao" value="2026-07-25"', html_depois)

        base = {
            "op_principal": str(op_id), "bandejas_principal": "12",
            "data_fabricacao": "2026-07-25", "data_validade": "2027-07-25",
        }
        registrar_caixa_pa_manual(dict(base, peso_bruto="10.600", idempotency_key=f"OP83-D12-A-{op_id}"), usuario="Supervisora")
        registrar_caixa_pa_manual(dict(base, peso_bruto="10.700", idempotency_key=f"OP83-D12-B-{op_id}"), usuario="Supervisora")
        painel_final = obter_conferencia_op(op_id)
        self.assertEqual(painel_final["totais"]["caixas_ativas"], 3)
        self.assertEqual(painel_final["totais"]["caixas_estornadas"], 1)
        self.assertEqual(float(painel_final["totais"]["saldo_pendente"]), 0)
        confirmar_conferencia_op(op_id, usuario="Supervisora", perfil="pcp", hash_informado=painel_final["hash"])
        finalizar_embalagem_secundaria_op(op_id, conferencia_hash=painel_final["hash"], exigir_conferencia=True)
        self.assertEqual(consultar_um("SELECT status FROM ordens_producao WHERE id=?", (op_id,))["status"], "Encerrada")

    def test_15b_caixa_parcial_preserva_quantidade_tara_e_liquido(self):
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

    def test_16_bloqueado_conforme_falha_fechado_para_venda(self):
        self.contexto("pcp")
        op_id, caixa_id = self.preparar_cortada("CX-BLOQUEADA-P12")
        finalizar_embalagem_secundaria_op(op_id)
        executar("UPDATE pa_caixas SET disponibilidade='BLOQUEADO' WHERE id=?", (caixa_id,))
        romaneio = self.criar_romaneio("VENDA_DIRETA", "Venda direta")
        with self.assertRaisesRegex(ValueError, "conforme e disponivel"):
            reservar_itens(romaneio, [caixa_id])
        _, resumo = buscar_estoque_operacional()
        self.assertGreaterEqual(resumo["unidades_outras_condicoes"], 1)
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM expedicao_itens WHERE expedicao_id=?", (romaneio,)
        )["total"], 0)

    def test_17_pacotes_em_reprocessamento_nao_compoem_disponivel(self):
        self.contexto("pcp")
        _, resumo_antes = buscar_estoque_operacional()
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa,sku,status,local_estoque_id,estoque_operacional,
            unidade_estoque,apresentacao,galinhas_por_pacote,
            quantidade_pacotes,quantidade_galinhas,quantidade_pacotes_reservados,
            condicao,disponibilidade,zona_estoque
        ) VALUES ('GI-REPROCESSO-P12','Galinha Inteira','Em estoque',?,1,
            'PACOTE','Pacote com 1 ave',1,10,10,0,
            'CONFORME','REPROCESSAMENTO','Produto Não Conforme')
        """, (self.local_abatedouro,))
        _, resumo = buscar_estoque_operacional()
        self.assertEqual(
            resumo["unidades_reprocessamento"] - resumo_antes["unidades_reprocessamento"], 10)
        romaneio = self.criar_romaneio("VENDA_DIRETA", "Venda direta")
        with self.assertRaisesRegex(ValueError, "conforme e disponivel"):
            reservar_itens(romaneio, [caixa_id], {caixa_id: 1})
        self.assertEqual(consultar_um(
            "SELECT quantidade_pacotes_reservados FROM pa_caixas WHERE id=?", (caixa_id,)
        )["quantidade_pacotes_reservados"], 0)

    def test_18_remocao_de_reserva_preserva_item_inativo_e_auditoria(self):
        self.contexto("pcp")
        op_id, caixa_id = self.preparar_cortada("CX-SOFT-DELETE-P12")
        finalizar_embalagem_secundaria_op(op_id)
        romaneio = self.criar_romaneio()
        reservar_itens(romaneio, [caixa_id])
        item_id = consultar_um("""SELECT id FROM expedicao_itens
            WHERE expedicao_id=? AND caixa_id=? AND COALESCE(ativo,1)=1""",
            (romaneio, caixa_id))["id"]
        remover_item_reservado(romaneio, caixa_id)
        item = consultar_um("SELECT * FROM expedicao_itens WHERE id=?", (item_id,))
        self.assertEqual(item["ativo"], 0)
        self.assertTrue(item["removido_em"] and item["removido_por"] and item["motivo_remocao"])
        self.assertEqual(buscar_itens_expedicao(romaneio), [])
        self.assertEqual(consultar_um(
            "SELECT disponibilidade FROM pa_caixas WHERE id=?", (caixa_id,)
        )["disponibilidade"], "DISPONIVEL")
        self.assertEqual(consultar_um("""SELECT COUNT(*) total FROM estoque_eventos
            WHERE expedicao_id=? AND caixa_id=? AND acao='REMOCAO_RESERVA'""",
            (romaneio, caixa_id))["total"], 1)

    def test_19_confirmacao_do_usuario_encerra_sem_segundo_clique(self):
        op_id, _ = self.preparar_cortada("CX-CONFIRMA-E-ENCERRA")
        cliente = self.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": "Operadora", "perfil": "pcp"})
        self.assertEqual(cliente.get(f"/embalagem-secundaria?op_id={op_id}").status_code, 200)
        conferencia = obter_conferencia_op(op_id)
        with cliente.session_transaction() as sessao:
            csrf = sessao["estorno_embalagem_csrf"]
        resposta = cliente.post(
            f"/embalagem-secundaria/{op_id}/conferencia/confirmar",
            data={
                "csrf_token": csrf, "confirmacao": "1",
                "conferencia_hash": conferencia["hash"],
                "idempotency_key": f"TESTE-CONFIRMA-{op_id}",
                "versao_operacional": "0",
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(consultar_um(
            "SELECT status FROM ordens_producao WHERE id=?", (op_id,)
        )["status"], "Encerrada")

    def test_20_preflight_pronta_e_livro_pi_com_estorno_compensado(self):
        op_id, _ = self.preparar_cortada_integra("CX-PI-ESTORNO-COMPENSADO")
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,op_id,sku,tipo,quantidade_bandejas,observacoes)
            VALUES('2026-07-25',?,'Galinha Cortada','ENTRADA_ESTORNO_CAIXA',12,'estorno legítimo')""", (op_id,))
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,op_id,sku,tipo,quantidade_bandejas,observacoes)
            VALUES('2026-07-25',?,'Galinha Cortada','SAIDA_EMBALAGEM_SECUNDARIA',12,'nova caixa após estorno')""", (op_id,))
        preflight = preflight_encerramento_op(op_id)
        self.assertTrue(preflight["pronta_para_encerramento"])
        self.assertEqual(preflight["pi"]["saldo"], 0)
        self.assertEqual(preflight["estado_funcional"], PRONTA_PARA_ENCERRAMENTO)
        self.assertEqual(obter_estado_funcional_op(op_id)["estado_funcional"], PRONTA_PARA_ENCERRAMENTO)
        self.assertEqual(auditar_integridade_encerramento(op_id=op_id)["criticos"], 0)

    def test_21_saldo_real_pi_bloqueia_com_valores_explicitos(self):
        op_id, _ = self.preparar_cortada("CX-PI-DIVERGENTE")
        executar("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,op_id,sku,tipo,quantidade_bandejas,observacoes)
            VALUES('2026-07-25',?,'Galinha Cortada','ENTRADA_ESTORNO_CAIXA',3,'saldo não consumido')""", (op_id,))
        preflight = preflight_encerramento_op(op_id)
        self.assertFalse(preflight["permitido"])
        self.assertIn("Esperado 0, encontrado 3", " ".join(preflight["bloqueios"]))
        with self.assertRaisesRegex(ValueError, "Esperado 0, encontrado 3"):
            finalizar_embalagem_secundaria_op(op_id)
        self.assertEqual(consultar_um(
            "SELECT status FROM ordens_producao WHERE id=?", (op_id,)
        )["status"], "Aberta")

    def test_22_conflito_de_versao_retorna_motivo_sem_mutacao(self):
        op_id, caixa_id = self.preparar_cortada("CX-VERSAO-CONFLITO")
        with self.assertRaisesRegex(ValueError, "Esperada 99, encontrada 0"):
            finalizar_embalagem_secundaria_op(op_id, versao_esperada=99)
        self.assertEqual(consultar_um(
            "SELECT status FROM ordens_producao WHERE id=?", (op_id,)
        )["status"], "Aberta")
        self.assertEqual(consultar_um(
            "SELECT disponibilidade FROM pa_caixas WHERE id=?", (caixa_id,)
        )["disponibilidade"], "PENDENTE_OP")

    def test_23_falha_na_auditoria_reverte_status_producao_e_pa(self):
        op_id, caixa_id = self.preparar_cortada("CX-ROLLBACK-AUDITORIA")
        with mock.patch.object(encerramento_op, "_auditar", side_effect=RuntimeError("auditoria indisponível")):
            with self.assertRaisesRegex(RuntimeError, "auditoria indisponível"):
                finalizar_embalagem_secundaria_op(
                    op_id, idempotency_key=f"TESTE-AUDITORIA-{op_id}"
                )
        self.assertEqual(consultar_um(
            "SELECT status FROM ordens_producao WHERE id=?", (op_id,)
        )["status"], "Aberta")
        caixa = consultar_um(
            "SELECT estoque_operacional,disponibilidade FROM pa_caixas WHERE id=?", (caixa_id,)
        )
        self.assertEqual((caixa["estoque_operacional"], caixa["disponibilidade"]), (0, "PENDENTE_OP"))
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM apontamentos_producao WHERE op_id=?", (op_id,)
        )["total"], 0)

    def test_24_idempotencia_preserva_financeiro_e_demais_ops(self):
        executar("CREATE TABLE IF NOT EXISTS financeiro_guard_teste(id INTEGER PRIMARY KEY, estado TEXT, evento TEXT)")
        executar("DELETE FROM financeiro_guard_teste")
        executar("""INSERT INTO financeiro_guard_teste VALUES(
            1,'FINANCEIRO_EM_RECONSTRUCAO','17d465d8-63d2-480a-98c1-b484cf62fbb7')""")
        op_controle, _ = self.preparar_cortada("CX-OP-CONTROLE")
        op_id, caixa_id = self.preparar_cortada("CX-IDEMP-AUDITADA")
        chave = f"TESTE-IDEMP-{op_id}"
        primeiro = finalizar_embalagem_secundaria_op(op_id, idempotency_key=chave)
        segundo = finalizar_embalagem_secundaria_op(op_id, idempotency_key=chave)
        self.assertTrue(primeiro["sucesso"] and segundo["ja_encerrada"])
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM op_operacoes_auditoria WHERE idempotency_key=?", (chave,)
        )["total"], 1)
        self.assertEqual(consultar_um(
            "SELECT COUNT(*) total FROM estoque_eventos WHERE idempotency_key=?",
            (f"FORMACAO-PA-{caixa_id}",),
        )["total"], 1)
        self.assertEqual(consultar_um(
            "SELECT status FROM ordens_producao WHERE id=?", (op_controle,)
        )["status"], "Aberta")
        guard = consultar_um("SELECT estado,evento FROM financeiro_guard_teste WHERE id=1")
        self.assertEqual(
            (guard["estado"], guard["evento"]),
            ("FINANCEIRO_EM_RECONSTRUCAO", "17d465d8-63d2-480a-98c1-b484cf62fbb7"),
        )

    def test_25_preflight_nao_executa_bootstrap_ou_ddl(self):
        op_id, _ = self.preparar_cortada("CX-PREFLIGHT-SOMENTE-SELECT")
        with mock.patch(
            "modules.expedicao.services.garantir_schema_producao",
            side_effect=AssertionError("preflight tentou bootstrap de produção"),
        ), mock.patch(
            "modules.expedicao.services.criar_tabelas_estoque_pi_pa",
            side_effect=AssertionError("preflight tentou DDL de estoque"),
        ):
            resultado = preflight_encerramento_op(op_id)
        self.assertTrue(resultado["permitido"])

    def test_26_estado_central_identifica_op_pronta(self):
        op_id, _ = self.preparar_cortada_integra("CX-ESTADO-PRONTA")
        estado = obter_estado_funcional_op(op_id)
        self.assertEqual(estado["estado_funcional"], PRONTA_PARA_ENCERRAMENTO)
        self.assertEqual(estado["saldo_pi"], 0)

    def test_27_painel_mantem_pronta_e_expoe_ultima_rejeicao(self):
        op_id, _ = self.preparar_cortada_integra("CX-PAINEL-REJEICAO")
        with self.assertRaisesRegex(ValueError, "Identificador"):
            finalizar_embalagem_secundaria_op(op_id, versao_esperada=999)
        painel = montar_paineis_encerramento({"por_pagina_encerramento": "50"})
        item = next(i for i in painel["ops_prontas_encerramento"]["itens"] if i["op_id"] == op_id)
        self.assertIn("Conflito de versão", item["ultima_falha"])

    def test_28_painel_identifica_estado_inconsistente(self):
        op_id, caixa_id = self.preparar_cortada_integra("CX-PAINEL-INCONSISTENTE")
        executar("UPDATE pa_caixas SET estoque_operacional=1,disponibilidade='DISPONIVEL' WHERE id=?", (caixa_id,))
        painel = montar_paineis_encerramento({"por_pagina_encerramento": "50"})
        item = next(i for i in painel["estados_inconsistentes_producao"]["itens"] if i["op_id"] == op_id)
        self.assertEqual(item["estado_funcional"], ESTADO_INCONSISTENTE)
        self.assertIn("OP aberta", item["validacoes"])

    def test_29_auditor_retorna_zero_para_op_encerrada_integra(self):
        op_id, _ = self.preparar_cortada_integra("CX-AUDITOR-INTEGRA")
        finalizar_embalagem_secundaria_op(op_id, idempotency_key=f"AUDITOR-INTEGRA-{op_id}")
        resultado = auditar_integridade_encerramento(op_id=op_id)
        self.assertEqual(resultado["criticos"], 0)
        self.assertEqual(obter_estado_funcional_op(op_id)["estado_funcional"], ENCERRADA)

    def test_30_auditor_detecta_aberta_pi_zero_pendente(self):
        op_id, _ = self.preparar_cortada_integra("CX-AUDITOR-PRONTA")
        resultado = auditar_integridade_encerramento(op_id=op_id)
        self.assertEqual(resultado["atencoes"], 1)
        self.assertIn("PENDENTE_OP", resultado["achados"][0]["motivo"])

    def test_31_auditor_detecta_encerrada_com_caixa_pendente(self):
        op_id, _ = self.preparar_cortada_integra("CX-AUDITOR-FECHADA-PENDENTE")
        executar("UPDATE ordens_producao SET status='Encerrada' WHERE id=?", (op_id,))
        resultado = auditar_integridade_encerramento(op_id=op_id)
        self.assertGreater(resultado["criticos"], 0)
        self.assertTrue(any("encerrada" in i["motivo"].lower() and "PENDENTE_OP" in i["motivo"]
                            for i in resultado["achados"]))

    def test_32_auditor_detecta_pa_operacional_com_op_aberta(self):
        op_id, caixa_id = self.preparar_cortada_integra("CX-AUDITOR-ABERTA-PA")
        executar("UPDATE pa_caixas SET estoque_operacional=1,disponibilidade='DISPONIVEL' WHERE id=?", (caixa_id,))
        resultado = auditar_integridade_encerramento(op_id=op_id)
        self.assertTrue(any("OP aberta" in i["motivo"] for i in resultado["achados"]))

    def test_33_pos_condicao_divergente_reverte_tudo(self):
        op_id, caixa_id = self.preparar_cortada_integra("CX-POS-CONDICAO-ROLLBACK")
        with mock.patch.object(
            encerramento_op, "_validar_pos_condicoes",
            side_effect=RuntimeError("peso operacional divergente"),
        ):
            with self.assertRaisesRegex(RuntimeError, "peso operacional divergente"):
                finalizar_embalagem_secundaria_op(op_id, idempotency_key=f"POS-ROLLBACK-{op_id}")
        self.assertEqual(consultar_um("SELECT status FROM ordens_producao WHERE id=?", (op_id,))["status"], "Aberta")
        caixa = consultar_um("SELECT estoque_operacional,disponibilidade FROM pa_caixas WHERE id=?", (caixa_id,))
        self.assertEqual((caixa["estoque_operacional"], caixa["disponibilidade"]), (0, "PENDENTE_OP"))

    def test_34_tentativa_rejeitada_persiste_correlacao_e_motivo(self):
        op_id, _ = self.preparar_cortada_integra("CX-TENTATIVA-CORRELACAO")
        with self.assertRaisesRegex(ValueError, "Identificador"):
            finalizar_embalagem_secundaria_op(
                op_id, versao_esperada=71, request_id="REQ-TESTE-34",
                idempotency_key=f"TENTATIVA-REJEITADA-{op_id}",
            )
        tentativa = consultar_um("""SELECT * FROM op_encerramento_tentativas
            WHERE op_id=? ORDER BY id DESC LIMIT 1""", (op_id,))
        self.assertEqual((tentativa["request_id"], tentativa["resultado"]), ("REQ-TESTE-34", "REJEITADA"))
        self.assertIn("Conflito de versão", tentativa["motivo_rejeicao"])
        self.assertTrue(tentativa["correlation_id"])

    def test_35_consulta_do_painel_tem_contagem_sql_constante(self):
        self.preparar_cortada_integra("CX-N1-BASE")

        class CursorContador:
            def __init__(self, cursor, contador): self._cursor, self._contador = cursor, contador
            def execute(self, *args, **kwargs):
                self._contador[0] += 1
                return self._cursor.execute(*args, **kwargs)
            def __getattr__(self, nome): return getattr(self._cursor, nome)

        class ConexaoContadora:
            def __init__(self, conn, contador): self._conn, self._contador = conn, contador
            def cursor(self): return CursorContador(self._conn.cursor(), self._contador)
            def __getattr__(self, nome): return getattr(self._conn, nome)

        original = integridade.conectar
        def medir():
            contador = [0]
            with mock.patch.object(integridade, "conectar", side_effect=lambda: ConexaoContadora(original(), contador)):
                montar_paineis_encerramento({"por_pagina_encerramento": "50"})
            return contador[0]
        consultas_base = medir()
        for indice in range(6):
            self.preparar_cortada_integra(f"CX-N1-{indice}")
        self.assertEqual(medir(), consultas_base)

    def test_36_interface_impede_reenvio_e_mostra_processamento(self):
        fonte = (ROOT / "templates" / "embalagem_secundaria.html").read_text(encoding="utf-8")
        self.assertIn("data-form-encerramento", fonte)
        self.assertIn('form.dataset.enviando === "1"', fonte)
        self.assertIn("Encerrando com segurança...", fonte)

    def test_37_duas_requisicoes_concorrentes_nao_duplicam_efeitos(self):
        op_id, caixa_id = self.preparar_cortada_integra("CX-CONCORRENCIA-ENCERRAMENTO")
        chave = f"CONCORRENTE-{op_id}"
        def encerrar():
            return finalizar_embalagem_secundaria_op(op_id, idempotency_key=chave)
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = [f.result() for f in [executor.submit(encerrar), executor.submit(encerrar)]]
        self.assertEqual(sum(1 for r in resultados if not r["ja_encerrada"]), 1)
        self.assertEqual(consultar_um("SELECT COUNT(*) total FROM op_operacoes_auditoria WHERE idempotency_key=?", (chave,))["total"], 1)
        self.assertEqual(consultar_um("SELECT COUNT(*) total FROM estoque_eventos WHERE idempotency_key=?", (f"FORMACAO-PA-{caixa_id}",))["total"], 1)

    def test_38_cli_json_e_exit_code_critico_sem_mutacao(self):
        op_id, caixa_id = self.preparar_cortada_integra("CX-CLI-AUDITOR")
        executar("UPDATE pa_caixas SET estoque_operacional=1,disponibilidade='DISPONIVEL' WHERE id=?", (caixa_id,))
        antes = dict(consultar_um("SELECT status FROM ordens_producao WHERE id=?", (op_id,)))
        resultado = self.app.test_cli_runner().invoke(
            args=["auditar-encerramento-ops", "--op", str(op_id), "--json-output"]
        )
        self.assertEqual(resultado.exit_code, 2)
        self.assertIn('"somente_leitura": true', resultado.output)
        self.assertIn('"criticos":', resultado.output)
        self.assertEqual(dict(consultar_um("SELECT status FROM ordens_producao WHERE id=?", (op_id,))), antes)


if __name__ == "__main__":
    unittest.main()
