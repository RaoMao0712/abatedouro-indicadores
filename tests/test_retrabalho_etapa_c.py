"""Ordem de Retrabalho — Etapa C: auditoria de integridade e regressão ampliada.

Cobre os cenários exigidos pelo prompt da Etapa C que não estavam na suíte da
Etapa B (`tests/test_retrabalho.py`, mantida intacta): família CAIXA/peso como
origem, conservação de valor no CMV (com assert numérico), atomicidade sob
falha injetada, idempotência de todas as ações, concorrência RT×RT, PNC antes
da liberação, estorno após liberação e estorno bloqueado por PNC, validade,
validações de quantidade e um smoke de performance.

Mesmo padrão de bootstrap dos demais arquivos de teste do projeto: um sqlite
temporário isolado, schema real criado pelas próprias funções `criar_tabelas_*`.
"""

import os
import time
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARQUIVO_BANCO = tempfile.NamedTemporaryFile(prefix="frigodatta-retrabalho-etapa-c-", suffix=".db", delete=False)
ARQUIVO_BANCO.close()
os.environ["DB_NAME"] = ARQUIVO_BANCO.name
os.environ.pop("DATABASE_URL", None)

from database import conectar, q  # noqa: E402
from modules.cmv.services import criar_tabelas_cmv, registrar_camada as cmv_registrar_camada  # noqa: E402
from modules.expedicao.consolidado_estoque import consolidar_estoque_camara  # noqa: E402
from modules.expedicao.estoque_service import criar_tabelas_estoque_confiavel, reservar_itens  # noqa: E402
from modules.expedicao.services import criar_tabelas_estoque_pi_pa, criar_tabelas_expedicao  # noqa: E402
from modules.label_printing.services import criar_tabelas_impressao_etiquetas, listar_jobs_caixas  # noqa: E402
from modules.qualidade.produtos_nao_conformes import (  # noqa: E402
    criar_tabelas_pa_nao_conforme, registrar_pnc_avulso,
)
from modules.retrabalho import services as rt  # noqa: E402


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


def consultar_um(sql, parametros=()):
    linhas = consultar(sql, parametros)
    return dict(linhas[0]) if linhas else None


class OrdemRetrabalhoEtapaCTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = conectar()
        conn.executescript("""
        CREATE TABLE ordens_producao (
            id INTEGER PRIMARY KEY, data TEXT NOT NULL,
            fornecedor TEXT NOT NULL, quantidade_aves INTEGER NOT NULL,
            mortes_antes_pendura INTEGER DEFAULT 0, peso_vivo REAL NOT NULL,
            peso_medio REAL NOT NULL, status TEXT DEFAULT 'Encerrada',
            sku TEXT DEFAULT 'Galinha Inteira'
        );
        CREATE TABLE skus (
            id INTEGER PRIMARY KEY, codigo TEXT, nome TEXT, ativo TEXT DEFAULT 'Sim',
            excluido_em TEXT
        );
        INSERT INTO skus (id, codigo, nome, ativo) VALUES
            (1, 'LEG-1', 'Galinha Cortada', 'Sim'),
            (2, 'LEG-2', 'Galinha Inteira', 'Sim'),
            (3, 'LEG-3', 'Galinha Cortada Congelada', 'Sim');
        """)
        conn.commit()
        conn.close()
        criar_tabelas_expedicao()
        criar_tabelas_estoque_pi_pa()
        criar_tabelas_estoque_confiavel()
        conn = conectar()
        for coluna in (
            "estornada_em TEXT", "estornada_por TEXT", "estorno_motivo TEXT",
            "estorno_evento_id INTEGER", "versao INTEGER NOT NULL DEFAULT 0", "usuario_pesagem TEXT",
        ):
            try:
                conn.execute(f"ALTER TABLE pa_caixas ADD COLUMN {coluna}")
            except Exception:
                pass
        conn.commit()
        conn.close()
        criar_tabelas_cmv()
        criar_tabelas_pa_nao_conforme()
        criar_tabelas_impressao_etiquetas()
        rt.criar_tabelas_retrabalho()
        cls.local_id = consultar("SELECT id FROM locais_estoque WHERE nome='Abatedouro'")[0]["id"]

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(ARQUIVO_BANCO.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        conn = conectar()
        for tabela in (
            "estoque_eventos", "expedicao_itens", "pa_caixa_composicao", "pa_caixas",
            "expedicoes", "ordens_producao", "retrabalho_eventos", "retrabalho_saidas",
            "retrabalho_origens", "retrabalhos", "cmv_camadas", "cmv_consumos", "cmv_eventos",
            "pa_nao_conformes", "pa_nao_conforme_eventos", "label_print_jobs",
        ):
            conn.execute(f"DELETE FROM {tabela}")
        conn.commit()
        conn.close()

    # ---------- helpers ----------

    def criar_op(self, op_id, *, aves=1000, sku="Galinha Inteira"):
        executar("""
        INSERT INTO ordens_producao (id, data, fornecedor, quantidade_aves, peso_vivo, peso_medio, status, sku)
        VALUES (?, '2026-08-01', 'Fornecedor Teste', ?, 2500, 2.5, 'Encerrada', ?)
        """, (op_id, aves, sku))
        return op_id

    def criar_posicao_galinha_inteira(self, codigo, op_id, pacotes, *, aves_por_pacote=1,
                                       sku="Galinha Inteira", apresentacao="Pacote com 1 galinha inteira",
                                       disponibilidade="DISPONIVEL", condicao="CONFORME",
                                       reservados=0, data_validade="2027-08-01"):
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, status, origem,
            local_estoque_id, estoque_operacional, condicao, disponibilidade, zona_estoque,
            unidade_estoque, apresentacao, galinhas_por_pacote, quantidade_pacotes,
            quantidade_galinhas, quantidade_pacotes_reservados
        ) VALUES (?, ?, '2026-08-01', ?, 'Em estoque', 'Embalagem Primaria', ?, 1, ?, ?, 'Conforme',
                  'PACOTE', ?, ?, ?, ?, ?)
        """, (codigo, sku, data_validade, self.local_id, condicao, disponibilidade, apresentacao,
              aves_por_pacote, pacotes, pacotes * aves_por_pacote, reservados))
        if op_id is not None:
            executar("INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas) VALUES (?, ?, ?)",
                     (caixa_id, op_id, pacotes * aves_por_pacote))
        return caixa_id

    def criar_posicao_cortada_peso(self, codigo, op_id, peso_liquido, *, sku="Galinha Cortada",
                                    apresentacao="Congelada", bandejas=10, data_validade="2027-08-01"):
        caixa_id = executar("""
        INSERT INTO pa_caixas (
            codigo_caixa, sku, data_fabricacao, data_validade, status, origem,
            local_estoque_id, estoque_operacional, condicao, disponibilidade, zona_estoque,
            unidade_estoque, apresentacao, peso_bruto, peso_liquido, peso_tara, quantidade_bandejas
        ) VALUES (?, ?, '2026-08-01', ?, 'Em estoque', 'Embalagem Secundaria', ?, 1, 'CONFORME',
                  'DISPONIVEL', 'Conforme', 'CAIXA', ?, ?, ?, 0.5, ?)
        """, (codigo, sku, data_validade, self.local_id, apresentacao,
              peso_liquido + 0.5, peso_liquido, bandejas))
        if op_id is not None:
            executar("INSERT INTO pa_caixa_composicao (caixa_id, op_id, quantidade_bandejas) VALUES (?, ?, ?)",
                     (caixa_id, op_id, bandejas))
        return caixa_id

    def criar_romaneio(self, numero):
        return executar("""
        INSERT INTO expedicoes (
            numero_romaneio, data, tipo_movimentacao, tipo_saida, origem, destino,
            responsavel, status, criado_por, perfil_criacao
        ) VALUES (?, '2026-09-17', 'TRANSFERENCIA', 'TRANSFERENCIA_LSM',
                  'Abatedouro', 'Câmara Fria LSM', 'PCP', 'Aberto', 'PCP', 'pcp')
        """, (numero,))

    def caixa(self, caixa_id):
        return consultar_um("SELECT * FROM pa_caixas WHERE id=?", (caixa_id,))

    def abrir_rt_pacote(self, origens_op_aves, *, sku_destino="Galinha Inteira",
                        apresentacao_destino="Pacote com 2 galinhas inteiras", galinhas_por_pacote_destino=2,
                        motivo="Teste", idempotency_key=None):
        caixas = {}
        for op_id, aves in origens_op_aves:
            self.criar_op(op_id, aves=aves)
            caixas[op_id] = self.criar_posicao_galinha_inteira(f"GI-PCT-OP-{op_id:05d}-V1", op_id, aves)
        rt_aberta = rt.abrir_retrabalho(
            {"motivo": motivo, "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": sku_destino, "apresentacao_destino": apresentacao_destino,
             "unidade_estoque_destino": "PACOTE", "galinhas_por_pacote_destino": galinhas_por_pacote_destino,
             "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixas[op_id], "quantidade": aves} for op_id, aves in origens_op_aves],
            usuario="PCP", perfil="pcp", idempotency_key=idempotency_key,
        )
        return rt_aberta, caixas

    # ---------- seção 5: família CAIXA/peso como origem ----------

    def test_familia_caixa_peso_como_origem_reserva_consumo_e_cancelamento(self):
        op_id = 500
        self.criar_op(op_id, aves=0, sku="Galinha Cortada")
        caixa_id = self.criar_posicao_cortada_peso("CX-CORTADA-500", op_id, 100.0, bandejas=20)

        rt_aberta = rt.abrir_retrabalho(
            {"motivo": "Origem por peso", "sku_origem": "Galinha Cortada", "unidade_estoque_origem": "CAIXA",
             "sku_destino": "Galinha Cortada Congelada", "apresentacao_destino": "Congelada reembalada",
             "unidade_estoque_destino": "CAIXA", "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": "100.0"}], usuario="PCP", perfil="pcp",
        )
        origem = self.caixa(caixa_id)
        self.assertEqual(origem["disponibilidade"], "RESERVADO", "familia peso reserva a posicao inteira")

        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": "95.5", "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-03-17", "local_estoque_id_destino": self.local_id,
             "quantidade_bandejas_destino": 18, "quantidade_perda": "4.5", "unidade_perda": "KG",
             "justificativa_perda": "Aparas no reprocesso"},
            usuario="PCP", perfil="pcp",
        )
        origem = self.caixa(caixa_id)
        self.assertEqual(float(origem["peso_liquido"]), 0.0)
        self.assertEqual(origem["disponibilidade"], "RETRABALHADO")
        self.assertGreaterEqual(float(origem["peso_liquido"]), 0, "nenhuma quantidade negativa")

        destino = self.caixa(resultado["caixa_destino_id"])
        self.assertEqual(destino["unidade_estoque"], "CAIXA")
        self.assertAlmostEqual(float(destino["peso_liquido"]), 95.5, places=2)
        self.assertAlmostEqual(float(destino["peso_bruto"]), 95.5, places=2)
        self.assertEqual(destino["quantidade_bandejas"], 18)
        self.assertEqual(destino["condicao"], "CONFORME")
        self.assertEqual(destino["disponibilidade"], "PENDENTE_OP")

        evento = consultar_um(
            "SELECT * FROM estoque_eventos WHERE caixa_id=? AND acao='RETRABALHO_CONSUMO'", (caixa_id,)
        )
        self.assertIsNotNone(evento)
        evento_formacao = consultar_um(
            "SELECT * FROM estoque_eventos WHERE caixa_id=? AND acao='RETRABALHO_FORMACAO'",
            (resultado["caixa_destino_id"],),
        )
        self.assertIsNotNone(evento_formacao)

    def test_familia_caixa_peso_como_origem_consumo_parcial_devolve_disponibilidade(self):
        op_id = 501
        self.criar_op(op_id, aves=0, sku="Galinha Cortada")
        caixa_id = self.criar_posicao_cortada_peso("CX-CORTADA-501", op_id, 150.0, bandejas=30)
        rt_aberta = rt.abrir_retrabalho(
            {"motivo": "Origem parcial", "sku_origem": "Galinha Cortada", "unidade_estoque_origem": "CAIXA",
             "sku_destino": "Galinha Cortada Congelada", "unidade_estoque_destino": "CAIXA",
             "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": "100.0"}], usuario="PCP", perfil="pcp",
        )
        rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": "90", "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-03-17", "local_estoque_id_destino": self.local_id,
             "quantidade_bandejas_destino": 18},
            usuario="PCP", perfil="pcp",
        )
        origem = self.caixa(caixa_id)
        self.assertAlmostEqual(float(origem["peso_liquido"]), 50.0, places=2, msg="150 - 100 consumidos = 50 kg restantes")
        self.assertEqual(origem["disponibilidade"], "DISPONIVEL", "saldo remanescente volta a ficar disponivel")
        self.assertGreaterEqual(float(origem["peso_liquido"]), 0)

    # ---------- seções 6–7: CMV, conservação de valor ----------

    def test_cmv_conserva_valor_total_caso_198_v1_para_99_v2(self):
        origens_op_aves = [(79, 82), (81, 15), (88, 1), (94, 1), (98, 98), (99, 1)]
        rt_aberta, caixas = self.abrir_rt_pacote(origens_op_aves)
        cmv_registrar_camada(
            produto="Galinha Inteira", unidade="UN", data_entrada="2026-08-01", quantidade=300,
            custo_unitario=Decimal("5.00"), custo_conhecido=True, origem_tipo="OP", origem_id="79",
            idempotency_key="SEED-CMV-198",
        )
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 99, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        evento_saida = consultar_um(
            "SELECT * FROM cmv_eventos WHERE tipo='RETRABALHO' AND origem_id=?", (str(rt_aberta["id"]),)
        )
        camada_destino = consultar_um(
            "SELECT * FROM cmv_camadas WHERE origem_tipo='RETRABALHO' AND origem_id=?", (str(rt_aberta["id"]),)
        )

        self.assertEqual(evento_saida["unidade"], "UN")
        self.assertEqual(int(evento_saida["quantidade"]), 198)
        self.assertAlmostEqual(float(evento_saida["custo_total"]), 990.00, places=2,
                                msg="198 aves x R$5,00 = R$990,00 retirados da origem")

        self.assertEqual(camada_destino["unidade"], "UN", "camada de Galinha Inteira permanece por ave, nao por pacote")
        self.assertEqual(int(camada_destino["quantidade_inicial"]), 198)
        self.assertAlmostEqual(float(camada_destino["custo_unitario"]), 5.00, places=2)
        custo_total_destino = float(camada_destino["quantidade_inicial"]) * float(camada_destino["custo_unitario"])
        self.assertAlmostEqual(custo_total_destino, 990.00, places=2)

        # Regra central: valor total nao pode ser criado nem destruido.
        self.assertAlmostEqual(float(evento_saida["custo_total"]), custo_total_destino, places=2)
        # E explicitamente NAO pode ser 99 x 5,00 = 495,00 (metade do valor, se a
        # camada fosse indevidamente controlada por pacote em vez de por ave).
        self.assertNotAlmostEqual(custo_total_destino, 495.00, places=2)

    def test_cmv_conserva_valor_total_caso_inteira_para_cortada(self):
        # abrir_rt_pacote sempre monta PACOTE no destino; aqui a origem segue
        # PACOTE mas o destino precisa ser CAIXA — monta-se manualmente.
        origens_op_aves = [(81, 300), (90, 400), (95, 300)]
        caixas2 = {}
        for op_id, aves in origens_op_aves:
            self.criar_op(op_id, aves=aves)
            caixas2[op_id] = self.criar_posicao_galinha_inteira(f"GI-PCT-OP-{op_id:05d}-V1B", op_id, aves)
        cmv_registrar_camada(
            produto="Galinha Inteira", unidade="UN", data_entrada="2026-08-01", quantidade=1000,
            custo_unitario=Decimal("6.00"), custo_conhecido=True, origem_tipo="OP", origem_id="81",
            idempotency_key="SEED-CMV-CORTADA",
        )
        rt_aberta2 = rt.abrir_retrabalho(
            {"motivo": "Inteira -> Cortada", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": "Galinha Cortada Congelada", "unidade_estoque_destino": "CAIXA",
             "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixas2[op_id], "quantidade": aves} for op_id, aves in origens_op_aves],
            usuario="PCP", perfil="pcp",
        )
        rt.encerrar_retrabalho(
            rt_aberta2["id"],
            {"quantidade_apontada_destino": "412.3", "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-03-17", "local_estoque_id_destino": self.local_id,
             "quantidade_bandejas_destino": 50},
            usuario="PCP", perfil="pcp",
        )
        evento_saida = consultar_um(
            "SELECT * FROM cmv_eventos WHERE tipo='RETRABALHO' AND origem_id=?", (str(rt_aberta2["id"]),)
        )
        camada_destino = consultar_um(
            "SELECT * FROM cmv_camadas WHERE origem_tipo='RETRABALHO' AND origem_id=?", (str(rt_aberta2["id"]),)
        )
        self.assertEqual(evento_saida["unidade"], "UN")
        self.assertEqual(int(evento_saida["quantidade"]), 1000)
        self.assertAlmostEqual(float(evento_saida["custo_total"]), 6000.00, places=2)

        self.assertEqual(camada_destino["unidade"], "KG")
        self.assertAlmostEqual(float(camada_destino["quantidade_inicial"]), 412.3, places=2)
        custo_unitario_esperado = 6000.00 / 412.3
        self.assertAlmostEqual(float(camada_destino["custo_unitario"]), custo_unitario_esperado, places=4)
        custo_total_destino = float(camada_destino["quantidade_inicial"]) * float(camada_destino["custo_unitario"])
        self.assertAlmostEqual(custo_total_destino, float(evento_saida["custo_total"]), places=1,
                                msg="valor total conservado entre origem (aves) e destino (kg)")

    # ---------- seção 9: atomicidade sob falha injetada ----------

    def test_atomicidade_falha_injetada_no_encerramento_reverte_tudo(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(400, 40)])
        caixa_id = caixas[400]

        def checkpoint_que_falha(_rotulo):
            raise RuntimeError("falha injetada de teste — nada deve ser persistido")

        with self.assertRaises(RuntimeError):
            rt.encerrar_retrabalho(
                rt_aberta["id"],
                {"quantidade_apontada_destino": 20, "data_fabricacao_destino": "2026-09-17",
                 "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
                usuario="PCP", perfil="pcp", checkpoint=checkpoint_que_falha,
            )

        origem = self.caixa(caixa_id)
        self.assertEqual(origem["quantidade_pacotes"], 40, "origem nao pode ter sido consumida")
        self.assertEqual(origem["quantidade_pacotes_reservados"], 40, "reserva da abertura permanece intacta")
        self.assertEqual(origem["disponibilidade"], "DISPONIVEL")

        self.assertEqual(consultar_um("SELECT COUNT(*) AS n FROM pa_caixas WHERE origem='Retrabalho'")["n"], 0)
        self.assertEqual(
            consultar_um("SELECT COUNT(*) AS n FROM retrabalho_saidas WHERE retrabalho_id=?",
                        (rt_aberta["id"],))["n"], 0)
        self.assertEqual(
            consultar_um("SELECT COUNT(*) AS n FROM cmv_camadas WHERE origem_tipo='RETRABALHO'")["n"], 0,
            "nenhuma camada CMV orfa")
        self.assertEqual(
            consultar_um("SELECT COUNT(*) AS n FROM cmv_eventos WHERE origem_tipo='RETRABALHO'")["n"], 0,
            "nenhum consumo CMV orfao")
        self.assertEqual(
            consultar_um("SELECT COUNT(*) AS n FROM estoque_eventos WHERE acao IN "
                        "('RETRABALHO_CONSUMO','RETRABALHO_FORMACAO')")["n"], 0,
            "nenhum evento de estoque orfao")
        status = consultar_um("SELECT status FROM retrabalhos WHERE id=?", (rt_aberta["id"],))
        self.assertEqual(status["status"], rt.STATUS_ABERTA, "status da RT nao deve ter mudado")

        # A RT continua utilizavel normalmente apos a falha (nao ficou num estado zumbi).
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 20, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        self.assertEqual(resultado["status"], rt.STATUS_ENCERRADA)

    # ---------- seção 10: idempotência ampliada (abrir/liberar/cancelar/estornar) ----------

    def test_idempotencia_abrir_e_nao_duplica_reserva(self):
        op_id = 402
        self.criar_op(op_id, aves=20)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00402-V1", op_id, 20)
        chave = "RT-ABRIR-FIXA-402"
        primeira = rt.abrir_retrabalho(
            {"motivo": "Idempotencia abertura", "sku_origem": "Galinha Inteira",
             "unidade_estoque_origem": "PACOTE", "sku_destino": "Galinha Inteira",
             "unidade_estoque_destino": "PACOTE", "galinhas_por_pacote_destino": 2,
             "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 20}], usuario="PCP", perfil="pcp", idempotency_key=chave,
        )
        repetida = rt.abrir_retrabalho(
            {"motivo": "Idempotencia abertura", "sku_origem": "Galinha Inteira",
             "unidade_estoque_origem": "PACOTE", "sku_destino": "Galinha Inteira",
             "unidade_estoque_destino": "PACOTE", "galinhas_por_pacote_destino": 2,
             "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 20}], usuario="PCP", perfil="pcp", idempotency_key=chave,
        )
        self.assertEqual(primeira["id"], repetida["id"])
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 20, "reserva nao duplicou")
        total_origens = consultar_um("SELECT COUNT(*) AS n FROM retrabalho_origens WHERE retrabalho_id=?",
                                     (primeira["id"],))
        self.assertEqual(total_origens["n"], 1)

    def test_idempotencia_liberar_e_cancelar_e_estornar(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(403, 20)])
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 10, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        chave_lib = "RT-LIBERAR-FIXA-403"
        rt.liberar_retrabalho(rt_aberta["id"], usuario="Qualidade", perfil="qualidade", idempotency_key=chave_lib)
        rt.liberar_retrabalho(rt_aberta["id"], usuario="Qualidade", perfil="qualidade", idempotency_key=chave_lib)
        eventos_liberacao = consultar_um(
            "SELECT COUNT(*) AS n FROM retrabalho_eventos WHERE retrabalho_id=? AND acao='LIBERACAO'",
            (rt_aberta["id"],),
        )
        self.assertEqual(eventos_liberacao["n"], 1, "liberacao repetida nao duplica evento")
        self.assertEqual(self.caixa(resultado["caixa_destino_id"])["disponibilidade"], "DISPONIVEL")

        chave_est = "RT-ESTORNAR-FIXA-403"
        rt.estornar_retrabalho(rt_aberta["id"], "Erro", usuario="Admin", perfil="admin", idempotency_key=chave_est)
        rt.estornar_retrabalho(rt_aberta["id"], "Erro", usuario="Admin", perfil="admin", idempotency_key=chave_est)
        eventos_estorno = consultar_um(
            "SELECT COUNT(*) AS n FROM retrabalho_eventos WHERE retrabalho_id=? AND acao='ESTORNO'",
            (rt_aberta["id"],),
        )
        self.assertEqual(eventos_estorno["n"], 1, "estorno repetido nao duplica evento")

        # Cancelamento idempotente em uma RT separada (cancelamento so vale para ABERTA).
        rt_aberta2, caixas2 = self.abrir_rt_pacote([(404, 15)])
        chave_canc = "RT-CANCELAR-FIXA-404"
        rt.cancelar_retrabalho(rt_aberta2["id"], "Motivo", usuario="PCP", perfil="pcp", idempotency_key=chave_canc)
        rt.cancelar_retrabalho(rt_aberta2["id"], "Motivo", usuario="PCP", perfil="pcp", idempotency_key=chave_canc)
        eventos_cancel = consultar_um(
            "SELECT COUNT(*) AS n FROM retrabalho_eventos WHERE retrabalho_id=? AND acao='CANCELAMENTO'",
            (rt_aberta2["id"],),
        )
        self.assertEqual(eventos_cancel["n"], 1)
        self.assertEqual(self.caixa(caixas2[404])["quantidade_pacotes_reservados"], 0)

    # ---------- seção 11: RT × RT ----------

    def test_duas_rts_disputam_mesmo_saldo(self):
        op_id = 405
        self.criar_op(op_id, aves=100)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00405-V1", op_id, 100)

        rt_a = rt.abrir_retrabalho(
            {"motivo": "RT A", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
             "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 70}], usuario="PCP", perfil="pcp",
        )
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 70)

        with self.assertRaises(ValueError):
            rt.abrir_retrabalho(
                {"motivo": "RT B", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
                 "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
                 "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
                [{"caixa_id": caixa_id, "quantidade": 40}], usuario="PCP", perfil="pcp",
            )
        # A tentativa recusada nao pode ter deixado reserva parcial.
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 70)

        rt_b = rt.abrir_retrabalho(
            {"motivo": "RT B", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
             "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 30}], usuario="PCP", perfil="pcp",
        )
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 100)
        self.assertNotEqual(rt_a["id"], rt_b["id"])

    # ---------- seções 12–14: Qualidade / PNC antes da liberação ----------

    def test_pnc_avulso_exige_autorizacao_e_posicao_valida(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(406, 10)])
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 5, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        caixa_destino_id = resultado["caixa_destino_id"]
        with self.assertRaises(ValueError):
            registrar_pnc_avulso(999999, {"motivo": "Embalagem danificada", "local_estoque_id": self.local_id},
                                 usuario="Qualidade", perfil="qualidade")
        with self.assertRaises(ValueError):
            registrar_pnc_avulso(caixa_destino_id, {"motivo": "", "local_estoque_id": self.local_id},
                                 usuario="Qualidade", perfil="qualidade")
        chave = "PNC-FIXA-406"
        primeiro = registrar_pnc_avulso(
            caixa_destino_id, {"motivo": "Embalagem danificada", "local_estoque_id": self.local_id},
            usuario="Qualidade", perfil="qualidade", idempotency_key=chave,
        )
        repetido = registrar_pnc_avulso(
            caixa_destino_id, {"motivo": "Embalagem danificada", "local_estoque_id": self.local_id},
            usuario="Qualidade", perfil="qualidade", idempotency_key=chave,
        )
        self.assertEqual(primeiro, repetido, "idempotencia do registro de PNC")
        total = consultar_um("SELECT COUNT(*) AS n FROM pa_nao_conformes WHERE caixa_id=?", (caixa_destino_id,))
        self.assertEqual(total["n"], 1)

    def test_pnc_antes_da_liberacao_impede_liberar_como_disponivel(self):
        """Item critico da Etapa C: PNC detectado antes da liberacao nao pode virar CONFORME/DISPONIVEL."""
        rt_aberta, caixas = self.abrir_rt_pacote([(407, 10)])
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 5, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        caixa_destino_id = resultado["caixa_destino_id"]
        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["disponibilidade"], "PENDENTE_OP", "ainda nao liberado")

        registrar_pnc_avulso(
            caixa_destino_id, {"motivo": "Carne Escura", "local_estoque_id": self.local_id},
            usuario="Qualidade", perfil="qualidade",
        )
        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["condicao"], "NAO_CONFORME")
        self.assertEqual(destino["disponibilidade"], "BLOQUEADO")

        # liberar_retrabalho NAO pode sobrescrever o bloqueio sanitario.
        with self.assertRaises(ValueError):
            rt.liberar_retrabalho(rt_aberta["id"], usuario="Qualidade", perfil="qualidade")
        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["condicao"], "NAO_CONFORME", "liberacao nao pode ter mudado a condicao")
        self.assertEqual(destino["disponibilidade"], "BLOQUEADO", "liberacao nao pode ter destravado o PA")

    # ---------- seção 15: estorno após liberação, sem consumo posterior ----------

    def test_estorno_apos_liberacao_sem_consumo_reverte_atomicamente(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(408, 20)])
        caixa_id = caixas[408]
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 10, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        rt.liberar_retrabalho(rt_aberta["id"], usuario="Qualidade", perfil="qualidade")
        caixa_destino_id = resultado["caixa_destino_id"]
        self.assertEqual(self.caixa(caixa_destino_id)["disponibilidade"], "DISPONIVEL")

        estornada = rt.estornar_retrabalho(rt_aberta["id"], "Erro pos liberacao", usuario="Admin", perfil="admin")
        self.assertEqual(estornada["status"], rt.STATUS_ESTORNADA)
        origem = self.caixa(caixa_id)
        self.assertEqual(origem["quantidade_pacotes"], 20)
        self.assertEqual(origem["disponibilidade"], "DISPONIVEL")
        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["disponibilidade"], "ESTORNADO")

    # ---------- seção 16: estorno com PNC ativo ----------

    def test_estorno_bloqueado_quando_ha_pnc_ativo_no_destino(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(409, 20)])
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 10, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        caixa_destino_id = resultado["caixa_destino_id"]
        nc_id = registrar_pnc_avulso(
            caixa_destino_id, {"motivo": "Carne Escura", "local_estoque_id": self.local_id},
            usuario="Qualidade", perfil="qualidade",
        )
        with self.assertRaises(ValueError):
            rt.estornar_retrabalho(rt_aberta["id"], "Tentativa com PNC ativo", usuario="Admin", perfil="admin")
        # O PNC nao pode ter sido apagado/invalidado silenciosamente pela tentativa de estorno.
        registro = consultar_um("SELECT * FROM pa_nao_conformes WHERE id=?", (nc_id,))
        self.assertEqual(registro["status"], "BLOQUEADO")
        status_rt = consultar_um("SELECT status FROM retrabalhos WHERE id=?", (rt_aberta["id"],))
        self.assertEqual(status_rt["status"], rt.STATUS_ENCERRADA, "RT continua ENCERRADA, estorno nao ocorreu")

    # ---------- seção 17: etiquetas ----------

    def test_v1_para_v2_nao_gera_job_de_etiqueta_incompativel(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(410, 10)])
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 5, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        jobs = listar_jobs_caixas([resultado["caixa_destino_id"]])
        self.assertEqual(jobs, {}, "Galinha Inteira (pacote/ave) nunca teve automacao de etiqueta por posicao")

    # ---------- seções 18–19: posição sem OP / filtros de romaneio ----------

    def test_posicao_rt_aparece_em_selecao_geral_mas_nao_em_filtro_por_op(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(411, 10)])
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 5, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        rt.liberar_retrabalho(rt_aberta["id"], usuario="Qualidade", perfil="qualidade")
        caixa_destino_id = resultado["caixa_destino_id"]

        romaneio_id = self.criar_romaneio("ROM-RT-FILTRO-OP")
        # Selecao geral: reserva funciona normalmente, sem op_id_esperada.
        reservar_itens(romaneio_id, [caixa_destino_id], quantidades_pacotes={str(caixa_destino_id): 5})
        self.assertEqual(self.caixa(caixa_destino_id)["disponibilidade"], "RESERVADO")

        # Filtro por uma OP especifica: a posicao da RT nao pertence a nenhuma OP.
        vinculo = consultar_um(
            "SELECT COUNT(*) AS n FROM pa_caixa_composicao WHERE caixa_id=?", (caixa_destino_id,)
        )
        self.assertEqual(vinculo["n"], 0)

    # ---------- seção 20: validade ----------

    def test_validade_obrigatoria_e_nao_pode_ser_anterior_a_fabricacao(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(412, 10)])
        with self.assertRaises(ValueError):
            rt.encerrar_retrabalho(
                rt_aberta["id"],
                {"quantidade_apontada_destino": 5, "data_fabricacao_destino": "",
                 "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
                usuario="PCP", perfil="pcp",
            )
        with self.assertRaises(ValueError):
            rt.encerrar_retrabalho(
                rt_aberta["id"],
                {"quantidade_apontada_destino": 5, "data_fabricacao_destino": "2026-09-17",
                 "data_validade_destino": "2026-01-01", "local_estoque_id_destino": self.local_id},
                usuario="PCP", perfil="pcp",
            )
        # Nenhuma das duas tentativas invalidas pode ter alterado a RT.
        status = consultar_um("SELECT status FROM retrabalhos WHERE id=?", (rt_aberta["id"],))
        self.assertEqual(status["status"], rt.STATUS_ABERTA)

        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 5, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        destino = self.caixa(resultado["caixa_destino_id"])
        self.assertEqual(destino["data_fabricacao"], "2026-09-17")
        self.assertEqual(destino["data_validade"], "2027-09-17")

    # ---------- seção 21: validações de quantidade ----------

    def test_rejeita_quantidades_invalidas(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(413, 10)])
        casos_invalidos = [
            {"quantidade_apontada_destino": 0},
            {"quantidade_apontada_destino": -5},
            {"quantidade_apontada_destino": "2.5"},  # fracao de pacote
        ]
        for extra in casos_invalidos:
            dados = {"data_fabricacao_destino": "2026-09-17", "data_validade_destino": "2027-09-17",
                     "local_estoque_id_destino": self.local_id}
            dados.update(extra)
            with self.assertRaises(ValueError):
                rt.encerrar_retrabalho(rt_aberta["id"], dados, usuario="PCP", perfil="pcp")

        # Origem com quantidade <= 0 na abertura.
        op_id = 414
        self.criar_op(op_id, aves=10)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00414-V1", op_id, 10)
        with self.assertRaises(ValueError):
            rt.abrir_retrabalho(
                {"motivo": "Origem invalida", "sku_origem": "Galinha Inteira",
                 "unidade_estoque_origem": "PACOTE", "sku_destino": "Galinha Inteira",
                 "unidade_estoque_destino": "PACOTE", "galinhas_por_pacote_destino": 2,
                 "data_retrabalho": "2026-09-17"},
                [{"caixa_id": caixa_id, "quantidade": 0}], usuario="PCP", perfil="pcp",
            )
        with self.assertRaises(ValueError):
            rt.abrir_retrabalho(
                {"motivo": "Origem invalida", "sku_origem": "Galinha Inteira",
                 "unidade_estoque_origem": "PACOTE", "sku_destino": "Galinha Inteira",
                 "unidade_estoque_destino": "PACOTE", "galinhas_por_pacote_destino": 0,
                 "data_retrabalho": "2026-09-17"},
                [{"caixa_id": caixa_id, "quantidade": 10}], usuario="PCP", perfil="pcp",
            )
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 0, "nenhuma reserva parcial vazou")

    # ---------- seção 22: conciliação pacote/ave ----------

    def test_conciliacao_pacote_ave_sempre_consistente(self):
        for pacotes, fator in ((99, 2), (1, 2), (50, 3)):
            with self.subTest(pacotes=pacotes, fator=fator):
                rt_aberta, caixas = self.abrir_rt_pacote(
                    [(9000 + pacotes * 10 + fator, pacotes * fator)], galinhas_por_pacote_destino=fator,
                )
                resultado = rt.encerrar_retrabalho(
                    rt_aberta["id"],
                    {"quantidade_apontada_destino": pacotes, "data_fabricacao_destino": "2026-09-17",
                     "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
                    usuario="PCP", perfil="pcp",
                )
                destino = self.caixa(resultado["caixa_destino_id"])
                self.assertEqual(
                    destino["quantidade_galinhas"], destino["quantidade_pacotes"] * destino["galinhas_por_pacote"]
                )

    # ---------- seção 23: OP original nunca é escrita ----------

    def test_op_original_e_tabelas_relacionadas_nunca_sao_escritas(self):
        rt_aberta, caixas = self.abrir_rt_pacote([(415, 30)])
        antes = {row["id"]: dict(row) for row in consultar("SELECT * FROM ordens_producao")}
        rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 15, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        for row in consultar("SELECT * FROM ordens_producao"):
            self.assertEqual(dict(row), antes[row["id"]])

    # ---------- seção 24: performance / N+1 ----------

    def test_performance_listagem_com_muitas_rts(self):
        for i in range(100):
            op_id = 10000 + i
            self.criar_op(op_id, aves=4)
            caixa_id = self.criar_posicao_galinha_inteira(f"GI-PCT-OP-{op_id:05d}-V1", op_id, 4)
            rt.abrir_retrabalho(
                {"motivo": f"Perf {i}", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
                 "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
                 "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
                [{"caixa_id": caixa_id, "quantidade": 4}], usuario="PCP", perfil="pcp",
            )
        inicio = time.perf_counter()
        registros = rt.listar_retrabalhos({})
        duracao_lista = time.perf_counter() - inicio
        self.assertEqual(len(registros), 100)
        self.assertLess(duracao_lista, 1.0, "listagem de 100 RTs nao pode ser lenta (indicio de N+1)")

        inicio = time.perf_counter()
        detalhe = rt.obter_detalhe_retrabalho(registros[0]["id"])
        duracao_detalhe = time.perf_counter() - inicio
        self.assertIsNotNone(detalhe)
        self.assertLess(duracao_detalhe, 0.5)


if __name__ == "__main__":
    unittest.main()
