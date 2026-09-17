"""Ordem de Retrabalho: casos obrigatórios da Etapa B (ver PROMPT/relatório da Etapa A/A.1).

Segue o mesmo padrão de bootstrap de tests/test_romaneio_selecao_multiplas_ops.py:
um arquivo sqlite temporário isolado, com o schema real criado pelas próprias
funções `criar_tabelas_*` de cada módulo (nunca uma cópia paralela do schema).
"""

import os
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARQUIVO_BANCO = tempfile.NamedTemporaryFile(prefix="frigodatta-retrabalho-", suffix=".db", delete=False)
ARQUIVO_BANCO.close()
os.environ["DB_NAME"] = ARQUIVO_BANCO.name
os.environ.pop("DATABASE_URL", None)

from database import conectar, q  # noqa: E402
from modules.cmv.services import criar_tabelas_cmv, registrar_camada as cmv_registrar_camada  # noqa: E402
from modules.expedicao.consolidado_estoque import consolidar_estoque_camara  # noqa: E402
from modules.expedicao.estoque_service import criar_tabelas_estoque_confiavel, reservar_itens  # noqa: E402
from modules.expedicao.services import criar_tabelas_estoque_pi_pa, criar_tabelas_expedicao  # noqa: E402
from modules.label_printing.services import criar_tabelas_impressao_etiquetas  # noqa: E402
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


class OrdemRetrabalhoTest(unittest.TestCase):
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
        # Colunas de estorno de pa_caixas normalmente vêm de
        # criar_tabelas_estornos_embalagem(), mas essa função também mexe em
        # apontamentos_producao (fora do escopo deste teste); adicionamos só as
        # colunas de pa_caixas que a Ordem de Retrabalho realmente usa no estorno.
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
            "pa_nao_conformes", "pa_nao_conforme_eventos",
        ):
            conn.execute(f"DELETE FROM {tabela}")
        conn.commit()
        conn.close()

    # ---------- helpers ----------

    def criar_op(self, op_id, *, aves=1000):
        executar("""
        INSERT INTO ordens_producao (id, data, fornecedor, quantidade_aves, peso_vivo, peso_medio, status, sku)
        VALUES (?, '2026-08-01', 'Fornecedor Teste', ?, 2500, 2.5, 'Encerrada', 'Galinha Inteira')
        """, (op_id, aves))
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

    # ---------- caso 1: 198 V1 -> 99 V2 (item 37) ----------

    def test_caso_198_v1_para_99_v2_sem_sobra_e_sem_composicao(self):
        origens_op_aves = [(79, 82), (81, 15), (88, 1), (94, 1), (98, 98), (99, 1)]
        for op_id, aves in origens_op_aves:
            self.criar_op(op_id, aves=aves)
        caixas = {
            op_id: self.criar_posicao_galinha_inteira(f"GI-PCT-OP-{op_id:05d}-V1", op_id, aves)
            for op_id, aves in origens_op_aves
        }
        cmv_registrar_camada(
            produto="Galinha Inteira", unidade="UN", data_entrada="2026-08-01", quantidade=300,
            custo_unitario=Decimal("5.00"), custo_conhecido=True, origem_tipo="OP", origem_id="79",
            idempotency_key="SEED-CAMADA-GI",
        )

        rt_aberta = rt.abrir_retrabalho(
            {
                "motivo": "Regularização sistêmica V1 -> V2", "sku_origem": "Galinha Inteira",
                "unidade_estoque_origem": "PACOTE", "sku_destino": "Galinha Inteira",
                "unidade_estoque_destino": "PACOTE", "galinhas_por_pacote_destino": 2,
                "data_retrabalho": "2026-09-17",
            },
            [{"caixa_id": caixas[op_id], "quantidade": aves} for op_id, aves in origens_op_aves],
            usuario="PCP", perfil="pcp",
        )
        self.assertEqual(rt_aberta["status"], rt.STATUS_ABERTA)
        self.assertEqual(rt_aberta["numero"], f"RT-{rt_aberta['id']:06d}")
        self.assertEqual(int(rt_aberta["quantidade_planejada_origem"]), 198)
        for op_id, aves in origens_op_aves:
            self.assertEqual(self.caixa(caixas[op_id])["quantidade_pacotes_reservados"], aves)

        # As 6 OPs originais permanecem intocadas.
        ops_antes = {row["id"]: dict(row) for row in consultar("SELECT * FROM ordens_producao")}

        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {
                "quantidade_apontada_destino": 99, "data_fabricacao_destino": "2026-09-17",
                "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id,
            },
            usuario="PCP", perfil="pcp",
        )
        self.assertEqual(resultado["status"], rt.STATUS_ENCERRADA)
        caixa_destino_id = resultado["caixa_destino_id"]

        # Nenhuma sobra: as 6 posições de origem zeraram por completo.
        for op_id, aves in origens_op_aves:
            origem = self.caixa(caixas[op_id])
            self.assertEqual(origem["quantidade_pacotes"], 0)
            self.assertEqual(origem["quantidade_galinhas"], 0)
            self.assertEqual(origem["disponibilidade"], "RETRABALHADO")

        # OPs originais 100% inalteradas.
        for row in consultar("SELECT * FROM ordens_producao"):
            self.assertEqual(dict(row), ops_antes[row["id"]])

        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["sku"], "Galinha Inteira")
        self.assertEqual(destino["galinhas_por_pacote"], 2)
        self.assertEqual(destino["quantidade_pacotes"], 99)
        self.assertEqual(destino["quantidade_galinhas"], 198)
        self.assertEqual(destino["condicao"], "CONFORME")
        self.assertEqual(destino["disponibilidade"], "PENDENTE_OP", "deve nascer aguardando liberação da Qualidade")
        self.assertEqual(destino["estoque_operacional"], 1)

        # Sem linha em pa_caixa_composicao: a origem sistêmica é a própria RT.
        vinculo = consultar_um("SELECT COUNT(*) AS n FROM pa_caixa_composicao WHERE caixa_id=?", (caixa_destino_id,))
        self.assertEqual(vinculo["n"], 0)

        # Antes da liberação: não aparece como disponível no consolidado.
        consolidado = consolidar_estoque_camara()
        grupo_v2 = next(g for g in consolidado["grupos"] if g["chave"] == "galinha_inteira_v2")
        self.assertEqual(grupo_v2["situacoes"]["disponivel"]["quantidades"]["pacotes"], 0)
        grupo_v1 = next(g for g in consolidado["grupos"] if g["chave"] == "galinha_inteira_v1")
        self.assertEqual(grupo_v1["situacoes"]["disponivel"]["quantidades"]["pacotes"], 0)

        # CMV: custo transferido via FIFO (198 aves ao custo de R$5,00/ave semeado).
        camada_destino = consultar_um(
            "SELECT * FROM cmv_camadas WHERE origem_tipo='RETRABALHO' AND origem_id=?", (str(rt_aberta["id"]),)
        )
        self.assertEqual(int(camada_destino["quantidade_inicial"]), 198)
        self.assertAlmostEqual(float(camada_destino["custo_unitario"]), 5.00, places=2)

        # Liberação da Qualidade: só agora fica realmente disponível.
        rt.liberar_retrabalho(rt_aberta["id"], usuario="Qualidade", perfil="qualidade")
        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["disponibilidade"], "DISPONIVEL")
        consolidado = consolidar_estoque_camara()
        grupo_v2 = next(g for g in consolidado["grupos"] if g["chave"] == "galinha_inteira_v2")
        self.assertEqual(grupo_v2["situacoes"]["disponivel"]["quantidades"]["pacotes"], 99)
        self.assertEqual(grupo_v2["situacoes"]["disponivel"]["quantidades"]["galinhas"], 198)

    # ---------- caso 2: Inteira -> Cortada, apontamento real (item 38) ----------

    def test_caso_inteira_para_cortada_apontamento_real_sem_taxa_fixa(self):
        origens_op_aves = [(81, 300), (90, 400), (95, 300)]
        for op_id, aves in origens_op_aves:
            self.criar_op(op_id, aves=aves)
        caixas = {
            op_id: self.criar_posicao_galinha_inteira(f"GI-PCT-OP-{op_id:05d}-V1", op_id, aves)
            for op_id, aves in origens_op_aves
        }

        rt_aberta = rt.abrir_retrabalho(
            {
                "motivo": "Retrabalho para Cortada Congelada", "sku_origem": "Galinha Inteira",
                "unidade_estoque_origem": "PACOTE", "sku_destino": "Galinha Cortada Congelada",
                "unidade_estoque_destino": "CAIXA", "data_retrabalho": "2026-09-17",
            },
            [{"caixa_id": caixas[op_id], "quantidade": aves} for op_id, aves in origens_op_aves],
            usuario="PCP", perfil="pcp",
        )
        self.assertEqual(int(rt_aberta["quantidade_planejada_origem"]), 1000)

        # Apontamento do resultado físico real — não existe taxa aves->kg pré-cadastrada.
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {
                "quantidade_apontada_destino": "412.3", "data_fabricacao_destino": "2026-09-17",
                "data_validade_destino": "2027-03-17", "local_estoque_id_destino": self.local_id,
                "quantidade_bandejas_destino": 50,
            },
            usuario="PCP", perfil="pcp",
        )
        self.assertEqual(resultado["status"], rt.STATUS_ENCERRADA)
        destino = self.caixa(resultado["caixa_destino_id"])
        self.assertEqual(destino["sku"], "Galinha Cortada Congelada")
        self.assertEqual(destino["unidade_estoque"], "CAIXA")
        self.assertAlmostEqual(float(destino["peso_liquido"]), 412.3, places=2)
        self.assertEqual(destino["condicao"], "CONFORME")
        self.assertEqual(destino["disponibilidade"], "PENDENTE_OP")

        for op_id, aves in origens_op_aves:
            self.assertEqual(self.caixa(caixas[op_id])["quantidade_pacotes"], 0)

    # ---------- item 39: PNC no PA formado pela RT, sem op_id ----------

    def test_pnc_avulso_no_pa_formado_por_rt_sem_op_id(self):
        op_id, aves = 79, 10
        self.criar_op(op_id, aves=aves)
        caixa_id = self.criar_posicao_galinha_inteira(f"GI-PCT-OP-{op_id:05d}-V1", op_id, aves)
        rt_aberta = rt.abrir_retrabalho(
            {
                "motivo": "Teste PNC", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
                "sku_destino": "Galinha Inteira", "apresentacao_destino": "Pacote com 2 galinhas inteiras",
                "unidade_estoque_destino": "PACOTE",
                "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17",
            },
            [{"caixa_id": caixa_id, "quantidade": aves}], usuario="PCP", perfil="pcp",
        )
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 5, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        rt.liberar_retrabalho(rt_aberta["id"], usuario="Qualidade", perfil="qualidade")
        caixa_destino_id = resultado["caixa_destino_id"]

        nc_id = registrar_pnc_avulso(
            caixa_destino_id, {"motivo": "Embalagem danificada", "local_estoque_id": self.local_id},
            usuario="Qualidade", perfil="qualidade",
        )
        registro = consultar_um("SELECT * FROM pa_nao_conformes WHERE id=?", (nc_id,))
        self.assertIsNone(registro["op_id"], "PA originado por RT nao tem OP; op_id deve ficar nulo")
        self.assertEqual(registro["caixa_id"], caixa_destino_id)
        self.assertTrue(registro["numero"].startswith("PNC-RT-"))
        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["condicao"], "NAO_CONFORME")
        self.assertEqual(destino["disponibilidade"], "BLOQUEADO")

    # ---------- item 40: concorrência com romaneio (nos dois sentidos) ----------

    def test_concorrencia_rt_reserva_primeiro_bloqueia_romaneio_no_saldo_excedente(self):
        op_id = 300
        self.criar_op(op_id, aves=100)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00300-V1", op_id, 100)
        romaneio_id = self.criar_romaneio("ROM-RT-CONC-1")

        rt.abrir_retrabalho(
            {"motivo": "Concorrencia", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
             "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 60}], usuario="PCP", perfil="pcp",
        )
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 60)

        with self.assertRaises(ValueError):
            reservar_itens(romaneio_id, [caixa_id], quantidades_pacotes={str(caixa_id): 50})

        reservar_itens(romaneio_id, [caixa_id], quantidades_pacotes={str(caixa_id): 40})
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 100)

    def test_concorrencia_romaneio_reserva_primeiro_bloqueia_rt_no_saldo_excedente(self):
        op_id = 301
        self.criar_op(op_id, aves=150)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00301-V1", op_id, 150)
        romaneio_id = self.criar_romaneio("ROM-RT-CONC-2")

        reservar_itens(romaneio_id, [caixa_id], quantidades_pacotes={str(caixa_id): 100})
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 100)

        with self.assertRaises(ValueError):
            rt.abrir_retrabalho(
                {"motivo": "Concorrencia inversa", "sku_origem": "Galinha Inteira",
                 "unidade_estoque_origem": "PACOTE", "sku_destino": "Galinha Inteira",
                 "unidade_estoque_destino": "PACOTE", "galinhas_por_pacote_destino": 2,
                 "data_retrabalho": "2026-09-17"},
                [{"caixa_id": caixa_id, "quantidade": 60}], usuario="PCP", perfil="pcp",
            )
        # A tentativa recusada nao deve ter alterado o saldo ja reservado pelo romaneio.
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 100)

    # ---------- item 41: dupla execução / idempotência ----------

    def test_dupla_execucao_do_encerramento_e_idempotente(self):
        op_id = 302
        self.criar_op(op_id, aves=20)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00302-V1", op_id, 20)
        rt_aberta = rt.abrir_retrabalho(
            {"motivo": "Idempotencia", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
             "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 20}], usuario="PCP", perfil="pcp",
        )
        chave = "RT-ENCERRAR-TESTE-FIXA"
        primeiro = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 10, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp", idempotency_key=chave,
        )
        repetido = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 10, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp", idempotency_key=chave,
        )
        self.assertEqual(primeiro["caixa_destino_id"], repetido["caixa_destino_id"])
        total_saidas = consultar_um("SELECT COUNT(*) AS n FROM retrabalho_saidas WHERE retrabalho_id=?",
                                    (rt_aberta["id"],))
        self.assertEqual(total_saidas["n"], 1)
        total_destino = consultar_um("SELECT COUNT(*) AS n FROM pa_caixas WHERE origem='Retrabalho'")
        self.assertEqual(total_destino["n"], 1)
        total_camadas = consultar_um(
            "SELECT COUNT(*) AS n FROM cmv_camadas WHERE origem_tipo='RETRABALHO' AND origem_id=?",
            (str(rt_aberta["id"]),),
        )
        self.assertEqual(total_camadas["n"], 1)

    # ---------- item 42: cancelamento ----------

    def test_cancelamento_nao_baixa_estoque_e_libera_reserva(self):
        op_id = 303
        self.criar_op(op_id, aves=30)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00303-V1", op_id, 30)
        rt_aberta = rt.abrir_retrabalho(
            {"motivo": "Cancelamento", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
             "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 18}], usuario="PCP", perfil="pcp",
        )
        self.assertEqual(self.caixa(caixa_id)["quantidade_pacotes_reservados"], 18)

        cancelada = rt.cancelar_retrabalho(rt_aberta["id"], "Origem selecionada por engano",
                                            usuario="PCP", perfil="pcp")
        self.assertEqual(cancelada["status"], rt.STATUS_CANCELADA)
        origem = self.caixa(caixa_id)
        self.assertEqual(origem["quantidade_pacotes_reservados"], 0)
        self.assertEqual(origem["quantidade_pacotes"], 30, "estoque fisico nao pode ter sido baixado")

    # ---------- item 43: estorno ----------

    def test_estorno_restaura_origens_e_reverte_cmv(self):
        op_id = 304
        self.criar_op(op_id, aves=40)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00304-V1", op_id, 40)
        cmv_registrar_camada(
            produto="Galinha Inteira", unidade="UN", data_entrada="2026-08-01", quantidade=200,
            custo_unitario=Decimal("4.00"), custo_conhecido=True, origem_tipo="OP", origem_id=str(op_id),
            idempotency_key="SEED-CAMADA-304",
        )
        rt_aberta = rt.abrir_retrabalho(
            {"motivo": "Estorno", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
             "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 40}], usuario="PCP", perfil="pcp",
        )
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 20, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        caixa_destino_id = resultado["caixa_destino_id"]

        estornada = rt.estornar_retrabalho(rt_aberta["id"], "Erro na apuracao do resultado fisico",
                                           usuario="Admin", perfil="admin")
        self.assertEqual(estornada["status"], rt.STATUS_ESTORNADA)

        origem = self.caixa(caixa_id)
        self.assertEqual(origem["quantidade_pacotes"], 40)
        self.assertEqual(origem["quantidade_galinhas"], 40)
        self.assertEqual(origem["disponibilidade"], "DISPONIVEL")

        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["disponibilidade"], "ESTORNADO")

        camada = consultar_um(
            "SELECT * FROM cmv_camadas WHERE origem_tipo='RETRABALHO' AND origem_id=?", (str(rt_aberta["id"]),)
        )
        self.assertEqual(camada["status"], "ESTORNADA")
        self.assertEqual(float(camada["quantidade_disponivel"]), 0)
        estorno_saida = consultar_um(
            "SELECT * FROM cmv_eventos WHERE tipo='ESTORNO_RETRABALHO' AND origem_id=?", (str(rt_aberta["id"]),)
        )
        self.assertIsNotNone(estorno_saida, "o estorno da baixa CMV da origem deve existir")

    # ---------- item 44: estorno bloqueado ----------

    def test_estorno_bloqueado_quando_saida_ja_foi_reservada(self):
        op_id = 305
        self.criar_op(op_id, aves=40)
        caixa_id = self.criar_posicao_galinha_inteira("GI-PCT-OP-00305-V1", op_id, 40)
        rt_aberta = rt.abrir_retrabalho(
            {"motivo": "Estorno bloqueado", "sku_origem": "Galinha Inteira", "unidade_estoque_origem": "PACOTE",
             "sku_destino": "Galinha Inteira", "unidade_estoque_destino": "PACOTE",
             "galinhas_por_pacote_destino": 2, "data_retrabalho": "2026-09-17"},
            [{"caixa_id": caixa_id, "quantidade": 40}], usuario="PCP", perfil="pcp",
        )
        resultado = rt.encerrar_retrabalho(
            rt_aberta["id"],
            {"quantidade_apontada_destino": 20, "data_fabricacao_destino": "2026-09-17",
             "data_validade_destino": "2027-09-17", "local_estoque_id_destino": self.local_id},
            usuario="PCP", perfil="pcp",
        )
        rt.liberar_retrabalho(rt_aberta["id"], usuario="Qualidade", perfil="qualidade")
        caixa_destino_id = resultado["caixa_destino_id"]

        romaneio_id = self.criar_romaneio("ROM-RT-ESTORNO-BLOQ")
        # Reserva o saldo inteiro (20 de 20): a posicao vira RESERVADO por completo.
        reservar_itens(romaneio_id, [caixa_destino_id], quantidades_pacotes={str(caixa_destino_id): 20})

        with self.assertRaises(ValueError):
            rt.estornar_retrabalho(rt_aberta["id"], "Tentativa apos reserva", usuario="Admin", perfil="admin")
        # Nenhuma alteracao parcial: a posicao de destino continua exatamente como estava.
        destino = self.caixa(caixa_destino_id)
        self.assertEqual(destino["disponibilidade"], "RESERVADO")
        self.assertEqual(destino["quantidade_pacotes_reservados"], 20)


if __name__ == "__main__":
    unittest.main()
