"""P3: vínculo operacional em lote sem alterar estoque, OP ou disponibilidade."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

import pytest

from modules.expedicao import palletizacao
from modules.expedicao.etiqueta_pallet import montar_etiqueta


ROOT = Path(__file__).resolve().parents[1]
MIGRACAO = (ROOT / "database" / "20261018_p1_palletizacao_sqlite.sql").read_text(encoding="utf-8")


@pytest.fixture
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "p3.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    with conectar() as conn:
        conn.executescript("""
            CREATE TABLE locais_estoque(id INTEGER PRIMARY KEY,nome TEXT, tipo TEXT, ativo TEXT DEFAULT 'Sim');
            CREATE TABLE expedicoes(id INTEGER PRIMARY KEY, numero_romaneio TEXT);
            CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY, sku TEXT);
            CREATE TABLE pa_caixas(
              id INTEGER PRIMARY KEY,codigo_caixa TEXT UNIQUE,sku TEXT,
              quantidade_bandejas REAL DEFAULT 0,peso_liquido REAL DEFAULT 0,
              quantidade_pacotes INTEGER DEFAULT 0,quantidade_galinhas INTEGER DEFAULT 0,
              unidade_estoque TEXT DEFAULT 'CAIXA',apresentacao TEXT,
              status TEXT DEFAULT 'Em estoque',disponibilidade TEXT DEFAULT 'DISPONIVEL',
              condicao TEXT DEFAULT 'CONFORME',estoque_operacional INTEGER DEFAULT 1,
              local_estoque_id INTEGER
            );
            CREATE TABLE pa_caixa_composicao(
              id INTEGER PRIMARY KEY,caixa_id INTEGER,op_id INTEGER,quantidade_bandejas REAL DEFAULT 0
            );
            INSERT INTO locais_estoque VALUES(1,'Câmara A','interno','Sim');
            INSERT INTO locais_estoque VALUES(99,'Abatedouro','interno','Sim');
            INSERT INTO ordens_producao VALUES
              (121,'Galinha Cortada'),(122,'Galinha Cortada'),(123,'Galinha Inteira');
            INSERT INTO pa_caixas VALUES
              (1,'CX-1','Galinha Cortada',12,22,0,0,'CAIXA','BANDEJA','Em estoque','DISPONIVEL','CONFORME',1,1),
              (2,'CX-2','Galinha Cortada',8,14,0,0,'CAIXA','BANDEJA','Em estoque','DISPONIVEL','CONFORME',1,1),
              (3,'CX-3','Galinha Cortada',10,18,0,0,'CAIXA','BANDEJA','Em estoque','DISPONIVEL','CONFORME',1,1),
              (4,'PA-4','Galinha Inteira',0,100,962,1924,'PACOTE','PACOTE','Em estoque','DISPONIVEL','CONFORME',1,1),
              (5,'CX-5','Galinha Inteira',0,50,0,0,'CAIXA','BANDEJA','Em estoque','DISPONIVEL','CONFORME',1,1),
              (6,'CX-6','Galinha Cortada',4,7,0,0,'CAIXA','BANDEJA','Em estoque','DISPONIVEL','NAO_CONFORME',1,1),
              (7,'CX-7','Galinha Cortada',4,7,0,0,'CAIXA','BANDEJA','ESTORNADA','DISPONIVEL','CONFORME',0,1);
            INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES
              (1,121,12),(2,121,8),(3,122,10),(4,123,0),(5,123,0),(6,121,4),(7,121,4);
            ALTER TABLE pa_caixas ADD COLUMN peso_bruto REAL;
            ALTER TABLE pa_caixas ADD COLUMN quantidade_pacotes_reservados INTEGER DEFAULT 0;
            ALTER TABLE pa_caixas ADD COLUMN reservado_expedicao_id INTEGER;
            ALTER TABLE pa_caixas ADD COLUMN galinhas_por_pacote INTEGER;
            ALTER TABLE pa_caixas ADD COLUMN posicao_origem_id INTEGER;
            ALTER TABLE pa_caixas ADD COLUMN quantidade_original_galinhas INTEGER;
            UPDATE pa_caixas SET galinhas_por_pacote=2 WHERE unidade_estoque='PACOTE';
            ALTER TABLE expedicoes ADD COLUMN status TEXT DEFAULT 'Aberto';
            ALTER TABLE ordens_producao ADD COLUMN status TEXT DEFAULT 'Aberta';
            CREATE TABLE expedicao_itens(id INTEGER PRIMARY KEY,expedicao_id INTEGER,caixa_id INTEGER,ativo INTEGER DEFAULT 1);
            CREATE TABLE estoque_eventos(id INTEGER PRIMARY KEY AUTOINCREMENT,caixa_id INTEGER,
              expedicao_id INTEGER,acao TEXT,situacao_anterior TEXT,situacao_nova TEXT,
              condicao_anterior TEXT,condicao_nova TEXT,quantidade REAL,peso REAL,
              justificativa TEXT,observacao TEXT,usuario TEXT,perfil TEXT,criado_em TEXT,
              idempotency_key TEXT UNIQUE,evento_origem_id INTEGER);
        """)
        conn.executescript(MIGRACAO)

    @contextmanager
    def transaction():
        conn = conectar()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(palletizacao, "conectar", conectar)
    monkeypatch.setattr(palletizacao, "transaction", transaction)
    monkeypatch.setattr(palletizacao, "DATABASE_URL", None)
    return conectar


def criar(chave):
    return palletizacao.criar_pallet(
        usuario="PCP", idempotency_key=chave, localizacao_atual_id=1,
    )


def snapshot(conectar, ids):
    with conectar() as conn:
        marcadores = ",".join("?" for _ in ids)
        return [tuple(item) for item in conn.execute(
            f"SELECT id,status,disponibilidade,estoque_operacional FROM pa_caixas WHERE id IN ({marcadores}) ORDER BY id",
            ids,
        )]


def test_p10_fracionamento_sucessivo_idempotente_e_invariante(banco):
    pallet_a = criar("P10-PALLET-A")
    pallet_b = criar("P10-PALLET-B")
    palletizacao.palletizar_quantidade_pacote(
        pallet_a["id"], 4, 330, usuario="PCP", idempotency_key="P10-FRAC-330",
    )
    palletizacao.palletizar_quantidade_pacote(
        pallet_a["id"], 4, 330, usuario="PCP", idempotency_key="P10-FRAC-330",
    )
    palletizacao.palletizar_quantidade_pacote(
        pallet_b["id"], 4, 400, usuario="PCP", idempotency_key="P10-FRAC-400",
    )
    with banco() as conn:
        origem = conn.execute("SELECT quantidade_galinhas,quantidade_pacotes FROM pa_caixas WHERE id=4").fetchone()
        filhas = conn.execute("SELECT quantidade_galinhas,posicao_origem_id FROM pa_caixas WHERE posicao_origem_id=4 ORDER BY id").fetchall()
        assert tuple(origem) == (1194, 597)
        assert [tuple(item) for item in filhas] == [(330, 4), (400, 4)]
        assert conn.execute("SELECT COUNT(*) FROM pallet_caixa_eventos WHERE tipo_evento='FRACIONAMENTO_POSICAO_PACOTE'").fetchone()[0] == 2
    assert palletizacao.auditar_fracionamento_posicao(4)["status"] == "OK"


def test_p10_quantidade_total_nao_cria_filha_e_validacoes(banco):
    pallet = criar("P10-TOTAL-PALLET")
    palletizacao.palletizar_quantidade_pacote(
        pallet["id"], 4, 1924, usuario="PCP", idempotency_key="P10-TOTAL",
    )
    with banco() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE posicao_origem_id=4").fetchone()[0] == 0
        assert conn.execute("SELECT caixa_id FROM pallet_caixas_atuais").fetchone()[0] == 4


def test_p10_v2_1844_aceita_330_e_preserva_total_rastreabilidade(banco):
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET quantidade_galinhas=1844,quantidade_pacotes=922 WHERE id=4")
    pallet = criar("P10-V2-330-PALLET")
    palletizacao.palletizar_quantidade_pacote(
        pallet["id"], 4, 330, usuario="PCP", idempotency_key="P10-V2-330",
    )
    with banco() as conn:
        origem = conn.execute(
            "SELECT quantidade_galinhas,quantidade_pacotes,status,disponibilidade,estoque_operacional FROM pa_caixas WHERE id=4"
        ).fetchone()
        filha = conn.execute(
            "SELECT quantidade_galinhas,quantidade_pacotes,posicao_origem_id FROM pa_caixas WHERE posicao_origem_id=4"
        ).fetchone()
        assert tuple(origem) == (1514, 757, "Em estoque", "DISPONIVEL", 1)
        assert tuple(filha) == (330, 165, 4)
    auditoria = palletizacao.auditar_fracionamento_posicao(4)
    assert auditoria["quantidade_original"] == auditoria["soma_atual"] == 1844
    assert auditoria["status"] == "OK"


@pytest.mark.parametrize("quantidade", [329, 331, 1845])
def test_p10_v2_rejeita_impar_ou_acima_do_saldo_sem_mutacao(banco, quantidade):
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET quantidade_galinhas=1844,quantidade_pacotes=922 WHERE id=4")
    pallet = criar(f"P10-V2-INVALIDA-{quantidade}-PALLET")
    with pytest.raises(ValueError, match="múltipla de 2 aves para V2|superior ao saldo"):
        palletizacao.palletizar_quantidade_pacote(
            pallet["id"], 4, quantidade, usuario="PCP",
            idempotency_key=f"P10-V2-INVALIDA-{quantidade}",
        )
    with banco() as conn:
        assert tuple(conn.execute(
            "SELECT quantidade_galinhas,quantidade_pacotes FROM pa_caixas WHERE id=4"
        ).fetchone()) == (1844, 922)
        assert conn.execute("SELECT COUNT(*) FROM pallet_caixas_atuais").fetchone()[0] == 0


def test_p10_v2_aceita_saldo_total_1844(banco):
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET quantidade_galinhas=1844,quantidade_pacotes=922 WHERE id=4")
    pallet = criar("P10-V2-TOTAL-1844-PALLET")
    palletizacao.palletizar_quantidade_pacote(
        pallet["id"], 4, 1844, usuario="PCP", idempotency_key="P10-V2-TOTAL-1844",
    )
    with banco() as conn:
        assert conn.execute("SELECT caixa_id FROM pallet_caixas_atuais").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM pa_caixas WHERE posicao_origem_id=4").fetchone()[0] == 0


@pytest.mark.parametrize("quantidade", [329, 330, 331])
def test_p10_v1_aceita_qualquer_inteiro_positivo_no_saldo(banco, quantidade):
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET quantidade_galinhas=1844,quantidade_pacotes=1844,galinhas_por_pacote=1 WHERE id=4")
    pallet = criar(f"P10-V1-{quantidade}-PALLET")
    palletizacao.palletizar_quantidade_pacote(
        pallet["id"], 4, quantidade, usuario="PCP", idempotency_key=f"P10-V1-{quantidade}",
    )
    with banco() as conn:
        filha = conn.execute(
            "SELECT quantidade_galinhas,quantidade_pacotes FROM pa_caixas WHERE posicao_origem_id=4"
        ).fetchone()
        assert tuple(filha) == (quantidade, quantidade)


def test_p10_input_html_usa_fator_como_step_e_base():
    template = (ROOT / "templates" / "pallet_adicionar_caixas.html").read_text(encoding="utf-8")
    assert 'min="{{ fator }}"' in template
    assert 'step="{{ fator }}"' in template
    assert 'min="1"' not in template


def test_pallet_vazio_herda_localizacao_da_primeira_posicao(banco):
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET local_estoque_id=99 WHERE id=1")
    pallet = criar("LOCAL-HERDA-PALLET")
    palletizacao.adicionar_caixas(
        pallet["id"], [1], usuario="PCP", idempotency_key="LOCAL-HERDA-ADD",
    )
    with banco() as conn:
        atual = conn.execute(
            "SELECT localizacao_atual_id,posicao_atual FROM pallets WHERE id=?", (pallet["id"],)
        ).fetchone()
        assert tuple(atual) == (99, None)


def test_pallet_ocupado_rejeita_local_divergente_sem_mutacao(banco):
    pallet = criar("LOCAL-OCUPADO-PALLET")
    palletizacao.adicionar_caixas(
        pallet["id"], [1], usuario="PCP", idempotency_key="LOCAL-OCUPADO-PRIMEIRA",
    )
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET local_estoque_id=99 WHERE id=2")
    antes = snapshot(banco, [1, 2])
    with pytest.raises(ValueError, match='Abatedouro.*Câmara A'):
        palletizacao.adicionar_caixas(
            pallet["id"], [2], usuario="PCP", idempotency_key="LOCAL-OCUPADO-DIVERGENTE",
        )
    assert snapshot(banco, [1, 2]) == antes
    with banco() as conn:
        assert conn.execute(
            "SELECT localizacao_atual_id FROM pallets WHERE id=?", (pallet["id"],)
        ).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM pallet_caixas_atuais").fetchone()[0] == 1


def test_transferencia_para_pallet_vazio_herda_localizacao(banco):
    origem = criar("LOCAL-TRANSFER-ORIGEM")
    destino = criar("LOCAL-TRANSFER-DESTINO")
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET local_estoque_id=99 WHERE id=1")
    palletizacao.adicionar_caixas(
        origem["id"], [1], usuario="PCP", idempotency_key="LOCAL-TRANSFER-ADD",
    )
    palletizacao.transferir_caixas(
        origem["id"], destino["id"], [1], usuario="PCP",
        idempotency_key="LOCAL-TRANSFER-MOVE",
    )
    with banco() as conn:
        assert conn.execute(
            "SELECT localizacao_atual_id FROM pallets WHERE id=?", (destino["id"],)
        ).fetchone()[0] == 99


def test_p10_parcial_pallet_vazio_herda_local_e_preserva_invariantes(banco):
    pallet = criar("LOCAL-P10-PALLET")
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET local_estoque_id=99 WHERE id=4")
    antes = snapshot(banco, [4])
    palletizacao.palletizar_quantidade_pacote(
        pallet["id"], 4, 330, usuario="PCP", idempotency_key="LOCAL-P10-330",
    )
    with banco() as conn:
        assert conn.execute(
            "SELECT localizacao_atual_id FROM pallets WHERE id=?", (pallet["id"],)
        ).fetchone()[0] == 99
        filha = conn.execute(
            "SELECT local_estoque_id,quantidade_galinhas,quantidade_pacotes,status,disponibilidade,estoque_operacional "
            "FROM pa_caixas WHERE posicao_origem_id=4"
        ).fetchone()
        assert tuple(filha) == (99, 330, 165, antes[0][1], antes[0][2], antes[0][3])
    assert palletizacao.auditar_fracionamento_posicao(4)["status"] == "OK"


def test_tela_adicionar_mantem_divergente_visivel_com_motivo():
    template = (ROOT / "templates" / "pallet_adicionar_caixas.html").read_text(encoding="utf-8")
    assert "Localização diferente do pallet" in template
    assert "caixa.motivo_divergencia" in template


@pytest.mark.parametrize("quantidade", [0, -1, 1925, "1.5", 331])
def test_p10_rejeita_quantidade_invalida_sem_mutacao(banco, quantidade):
    pallet = criar(f"P10-INV-PALLET-{quantidade}")
    with pytest.raises(ValueError):
        palletizacao.palletizar_quantidade_pacote(
            pallet["id"], 4, quantidade, usuario="PCP", idempotency_key=f"P10-INV-{quantidade}",
        )
    with banco() as conn:
        assert conn.execute("SELECT quantidade_galinhas FROM pa_caixas WHERE id=4").fetchone()[0] == 1924
        assert conn.execute("SELECT COUNT(*) FROM pallet_caixas_atuais").fetchone()[0] == 0


def test_p8_primeira_impressao_reimpressao_desatualizacao_e_zero_mutacao(banco):
    pallet = criar("P8-CRIAR")
    palletizacao.adicionar_caixas(
        pallet["id"], [1, 2], usuario="PCP", idempotency_key="P8-ADD",
    )
    antes = snapshot(banco, [1, 2])
    primeira = palletizacao.registrar_impressao_etiqueta(
        pallet["id"], usuario="Expedicao", idempotency_key="P8-PRINT-1",
    )
    retry = palletizacao.registrar_impressao_etiqueta(
        pallet["id"], usuario="Expedicao", idempotency_key="P8-PRINT-1",
    )
    assert primeira == retry
    assert primeira["versao"] == 1 and primeira["tipo"] == "PRIMEIRA_IMPRESSAO"
    assert palletizacao.estado_etiqueta_pallet(pallet["id"])["desatualizada"] is False
    with pytest.raises(ValueError, match="Motivo obrigatorio"):
        palletizacao.registrar_impressao_etiqueta(
            pallet["id"], usuario="Expedicao", idempotency_key="P8-PRINT-2",
        )
    segunda = palletizacao.registrar_impressao_etiqueta(
        pallet["id"], usuario="Expedicao", idempotency_key="P8-PRINT-2B",
        justificativa="Etiqueta danificada no manuseio",
    )
    assert segunda["versao"] == 2 and segunda["tipo"] == "REIMPRESSAO"
    assert snapshot(banco, [1, 2]) == antes
    palletizacao.mover_pallet(
        pallet["id"], 1, usuario="PCP", idempotency_key="P8-MOVE",
        posicao_destino="RUA-02",
    )
    assert palletizacao.estado_etiqueta_pallet(pallet["id"])["desatualizada"] is True
    with banco() as conn:
        impressoes = conn.execute("""SELECT justificativa,dados_json FROM pallet_caixa_eventos
                                     WHERE tipo_evento='ETIQUETA_PALLET_IMPRESSA'
                                     ORDER BY id""").fetchall()
        assert len(impressoes) == 2
        assert impressoes[1]["justificativa"] == "Etiqueta danificada no manuseio"


def test_p8_etiqueta_visual_caixa_pacote_mistos_qr_e_cancelado(banco):
    pallet = criar("P8-VISUAL")
    # A camada visual aceita fotografia mista legada e explicita unidade/alertas.
    fotografia = palletizacao.consultar_pallet(pallet["id"])
    fotografia["caixas"] = [
        {"unidade_estoque": "CAIXA", "peso_bruto": 23, "peso_liquido": 22},
        {"unidade_estoque": "PACOTE", "peso_bruto": 102, "peso_liquido": 100},
    ]
    fotografia["ops"] = [{"op_id": 121}, {"op_id": 123}]
    fotografia["produtos"] = ["Galinha Cortada", "Galinha Inteira"]
    fotografia["condicoes"] = ["CONFORME", "NAO_CONFORME"]
    etiqueta = montar_etiqueta(
        fotografia, "https://exemplo/expedicao/pallets/1", 3,
    )
    assert etiqueta["versao"] == 3
    assert etiqueta["qr_payload"].endswith("/expedicao/pallets/1")
    assert etiqueta["qr_data_url"].startswith("data:image/svg+xml;base64,")
    assert etiqueta["barcode_data_url"].startswith("data:image/svg+xml;base64,")
    assert etiqueta["unidades_texto"] == "CAIXA / PACOTE"
    assert etiqueta["peso_bruto"] == 125
    assert set(etiqueta["mistos"]) == {
        "MISTO POR OP", "MISTO POR PRODUTO", "MISTO POR CONDIÇÃO",
    }
    cancelado = criar("P8-CANCEL")
    palletizacao.cancelar_pallet(
        cancelado["id"], usuario="Gerencia", idempotency_key="P8-CANCELAR",
        justificativa="Cadastro duplicado",
    )
    with pytest.raises(ValueError, match="cancelado"):
        palletizacao.registrar_impressao_etiqueta(
            cancelado["id"], usuario="Expedicao", idempotency_key="P8-CANCEL-PRINT",
        )
    excecao = palletizacao.registrar_impressao_etiqueta(
        cancelado["id"], usuario="Gerencia", idempotency_key="P8-CANCEL-ADMIN",
        justificativa="Auditoria física solicitada", permitir_cancelado=True,
    )
    assert excecao["excecao_cancelado"] is True


@pytest.mark.parametrize(
    ("fator", "aves", "pacotes", "produto", "equivalentes", "padrao"),
    [
        (2, 330, 165, "Galinha Inteira V2", 41.25,
         "Padrão: 8 aves por caixa (4 pacotes V2)"),
        (1, 331, 331, "Galinha Inteira V1", 41.375,
         "Padrão: 8 aves por caixa"),
    ],
)
def test_hotfix_etiqueta_v1_v2_e_caixas_equivalentes(
    fator, aves, pacotes, produto, equivalentes, padrao,
):
    pallet = {
        "codigo": "PALT-000121", "caixas": [{
            "sku": "Galinha Inteira", "unidade_estoque": "PACOTE",
            "galinhas_por_pacote": fator, "quantidade_galinhas": aves,
            "quantidade_pacotes": pacotes, "peso_liquido": 20,
        }],
        "ops": [{"op_id": 121}], "produtos": ["Galinha Inteira"],
        "condicoes": ["CONFORME"],
    }
    etiqueta = montar_etiqueta(pallet, "https://exemplo/expedicao/pallets/121", 1)
    assert etiqueta["produtos_texto"] == produto
    assert etiqueta["caixas_equivalentes"] == equivalentes
    assert etiqueta["padrao_caixas"] == padrao
    assert etiqueta["barcode_data_url"].startswith("data:image/svg+xml;base64,")
    assert etiqueta["qr_data_url"].startswith("data:image/svg+xml;base64,")


def test_hotfix_etiqueta_a4_quantidades_separadas_e_sem_escala():
    template = (ROOT / "templates" / "pallet_etiqueta.html").read_text(encoding="utf-8")
    assert "@page{size:A4 portrait;margin:0}" in template
    assert "width:190mm;height:138mm" in template
    assert "margin:9mm auto 0" in template
    assert "break-inside:avoid" in template
    assert "page-break-inside:avoid" in template
    assert "transform:scale" not in template.replace(" ", "")
    for rotulo in ("Caixas equivalentes", "Posições", "Bandejas", "Pacotes", "Aves", "Unidade"):
        assert f"<span>{rotulo}</span>" in template
    assert "Bandejas · pacotes · aves" not in template


def test_p9_historico_logistico_filtros_sem_mutacao(banco):
    pallet = criar("P9-HIST")
    palletizacao.adicionar_caixa(
        pallet["id"], 1, usuario="PCP", idempotency_key="P9-HIST-ADD",
        dados={"op_id": 121},
    )
    antes = snapshot(banco, [1])
    eventos = palletizacao.listar_historico_logistico({
        "pallet": pallet["codigo"], "op": "121", "tipo_evento": "ADICIONADA",
        "usuario": "pcp",
    })
    assert len(eventos) == 1
    assert eventos[0]["evento"] == "CAIXA_ADICIONADA"
    assert eventos[0]["objeto"] == "CX-1"
    assert eventos[0]["op"] == 121
    assert snapshot(banco, [1]) == antes


def test_p4_resumo_retomada_excecao_e_zero_mutacao(banco):
    pallet = criar("P4-RESUMO")
    antes = snapshot(banco, [1, 2])
    inicial = palletizacao.resumo_organizacao_op(121)
    assert inicial["nao_organizadas"] == 3  # inclui a posição PNC, ainda pertencente à OP
    palletizacao.adicionar_caixas(
        pallet["id"], [1, 2], usuario="PCP", idempotency_key="P4-ADD",
        dados={"op_id": 121, "origem": "ENCERRAMENTO_OP"},
    )
    retomada = palletizacao.resumo_organizacao_op(121)
    assert retomada["organizadas"] == 2 and retomada["nao_organizadas"] == 1
    assert retomada["pallets"][0]["totais"]["posicoes"] == 2
    with pytest.raises(ValueError, match="justificativa"):
        palletizacao.validar_organizacao_para_encerramento(121)
    aprovado = palletizacao.validar_organizacao_para_encerramento(
        121, justificativa="Posição PNC segregada fora do pallet",
        usuario="PCP", idempotency_key="P4-EXC",
    )
    assert aprovado["excecao_registrada"] is True
    assert snapshot(banco, [1, 2]) == antes


def test_p4_selecao_em_massa_200_duas_distribuicoes_e_sete_excecoes(banco):
    with banco() as conn:
        conn.execute("INSERT INTO ordens_producao(id,sku) VALUES(200,'Galinha Cortada')")
        for indice in range(1000, 1200):
            conn.execute("""INSERT INTO pa_caixas(
                id,codigo_caixa,sku,quantidade_bandejas,peso_liquido,unidade_estoque,
                apresentacao,status,disponibilidade,condicao,estoque_operacional,local_estoque_id
            ) VALUES(?,?,?,?,?,'CAIXA','BANDEJA','Em estoque','DISPONIVEL','CONFORME',1,1)""",
                         (indice, f"P4-{indice}", "Galinha Cortada", 12, 20))
            conn.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(?,?,12)",
                         (indice, 200))
        conn.commit()
    p1, p2 = criar("P4-200-A"), criar("P4-200-B")
    palletizacao.adicionar_caixas(p1["id"], range(1000, 1100), usuario="PCP", idempotency_key="P4-LOTE-A")
    palletizacao.adicionar_caixas(p2["id"], range(1100, 1193), usuario="PCP", idempotency_key="P4-LOTE-B")
    resumo = palletizacao.resumo_organizacao_op(200)
    assert resumo["organizadas"] == 193 and resumo["nao_organizadas"] == 7
    assert len(resumo["pallets"]) == 2


def test_adicionar_lote_ops_compativeis_retry_e_preservacao(banco):
    pallet = criar("P3-A")
    antes = snapshot(banco, [1, 2, 3])
    resultado = palletizacao.adicionar_caixas(
        pallet["id"], [1, 2, 3], usuario="PCP", idempotency_key="P3-ADD",
    )
    retry = palletizacao.adicionar_caixas(
        pallet["id"], [3, 2, 1], usuario="PCP", idempotency_key="P3-ADD",
    )
    assert resultado["totais"]["caixas"] == retry["totais"]["caixas"] == 3
    assert {op["op_id"] for op in resultado["ops"]} == {121, 122}
    assert snapshot(banco, [1, 2, 3]) == antes
    with banco() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pallet_caixas_atuais").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM pallet_caixa_eventos WHERE tipo_evento='CAIXA_ADICIONADA'").fetchone()[0] == 3


def test_caixa_ja_vinculada_incompatibilidade_e_lote_atomico(banco):
    primeiro, segundo = criar("P3-B1"), criar("P3-B2")
    palletizacao.adicionar_caixa(primeiro["id"], 1, usuario="PCP", idempotency_key="P3-B-ADD")
    with pytest.raises(ValueError, match="ja vinculada"):
        palletizacao.adicionar_caixa(segundo["id"], 1, usuario="PCP", idempotency_key="P3-B-DUP")
    with pytest.raises(ValueError, match="conteudo homogeneo"):
        palletizacao.adicionar_caixa(primeiro["id"], 5, usuario="PCP", idempotency_key="P3-B-SKU")
    with pytest.raises(ValueError, match="condicao nao permite"):
        palletizacao.adicionar_caixas(segundo["id"], [2, 6], usuario="PCP", idempotency_key="P3-B-LOTE")
    assert palletizacao.consultar_pallet(segundo["id"])["totais"]["caixas"] == 0
    with banco() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pallet_caixa_eventos WHERE idempotency_key LIKE 'P3-B-LOTE%'").fetchone()[0] == 0


def test_remover_e_transferir_lotes_historico_completo(banco):
    origem, destino = criar("P3-C1"), criar("P3-C2")
    palletizacao.adicionar_caixas(origem["id"], [1, 2, 3], usuario="PCP", idempotency_key="P3-C-ADD")
    palletizacao.remover_caixas(origem["id"], [1, 2], usuario="PCP", idempotency_key="P3-C-REM")
    palletizacao.adicionar_caixas(origem["id"], [1, 2], usuario="PCP", idempotency_key="P3-C-READD")
    movido = palletizacao.transferir_caixas(
        origem["id"], destino["id"], [1, 2, 3], usuario="PCP", idempotency_key="P3-C-TRANS",
    )
    assert movido["totais"]["caixas"] == 3
    assert palletizacao.consultar_pallet(origem["id"])["totais"]["caixas"] == 0
    eventos = palletizacao.listar_eventos_pallet(origem["id"])
    tipos = [item["tipo_evento"] for item in eventos]
    assert tipos.count("CAIXA_ADICIONADA") == 5
    assert tipos.count("CAIXA_REMOVIDA") == 2
    assert tipos.count("CAIXA_TRANSFERIDA") == 3


def test_transferencia_incompativel_rollback_integral(banco):
    origem, destino = criar("P3-D1"), criar("P3-D2")
    palletizacao.adicionar_caixas(origem["id"], [1, 2], usuario="PCP", idempotency_key="P3-D-ADD1")
    palletizacao.adicionar_caixa(destino["id"], 5, usuario="PCP", idempotency_key="P3-D-ADD2")
    with pytest.raises(ValueError, match="conteudo homogeneo"):
        palletizacao.transferir_caixas(
            origem["id"], destino["id"], [1, 2], usuario="PCP", idempotency_key="P3-D-TRANS",
        )
    assert palletizacao.consultar_pallet(origem["id"])["totais"]["caixas"] == 2
    assert palletizacao.consultar_pallet(destino["id"])["totais"]["caixas"] == 1


def test_pacote_e_posicao_fisica_unica(banco):
    pallet = criar("P3-E")
    antes = snapshot(banco, [4])
    resultado = palletizacao.adicionar_caixa(
        pallet["id"], 4, usuario="PCP", idempotency_key="P3-E-ADD",
    )
    assert resultado["totais"] == {
        "caixas": 1, "bandejas": 0.0, "peso_liquido": 100.0,
        "pacotes": 962, "aves": 1924,
    }
    assert snapshot(banco, [4]) == antes
    with banco() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pallet_caixas_atuais WHERE caixa_id=4").fetchone()[0] == 1


def test_listagem_especifica_exclui_pnc_estorno_e_vinculadas(banco):
    pallet = criar("P3-F")
    palletizacao.adicionar_caixa(pallet["id"], 1, usuario="PCP", idempotency_key="P3-F-ADD")
    disponiveis = palletizacao.listar_caixas_disponiveis_palletizacao({"op": "121"})
    assert [item["id"] for item in disponiveis] == [2]


def test_p5_estoque_agregado_filtros_reservas_pnc_pacote_e_sem_mutacao(banco):
    vazio, cortada, pacote = criar("P5-VAZIO"), criar("P5-CORTADA"), criar("P5-PACOTE")
    palletizacao.adicionar_caixas(cortada["id"], [1, 2, 3], usuario="PCP", idempotency_key="P5-ADD-C")
    palletizacao.adicionar_caixa(pacote["id"], 4, usuario="PCP", idempotency_key="P5-ADD-P")
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET disponibilidade='RESERVADO',reservado_expedicao_id=10 WHERE id=1")
        conn.execute("UPDATE pa_caixas SET quantidade_pacotes_reservados=100 WHERE id=4")
        conn.execute("UPDATE pa_caixas SET condicao='NAO_CONFORME' WHERE id=3")
        conn.execute("INSERT INTO expedicoes(id,numero_romaneio,status) VALUES(10,'R-10','Aberto')")
        conn.execute("INSERT INTO expedicao_itens(id,expedicao_id,caixa_id,ativo) VALUES(1,10,1,1)")
        conn.commit()
    antes = snapshot(banco, [1, 2, 3, 4, 5, 6, 7])
    visao = palletizacao.visao_estoque_por_pallet()
    por_id = {item["id"]: item for item in visao["pallets"]}
    assert por_id[vazio["id"]]["disponibilidade_agregada"] == "VAZIO"
    assert por_id[cortada["id"]]["disponibilidade_agregada"] == "COM_RESTRICOES"
    assert "MISTO POR OP" in por_id[cortada["id"]]["alertas"]
    assert "Conteudo com restricoes" in por_id[cortada["id"]]["alertas"]
    assert por_id[cortada["id"]]["totais"]["peso_liquido"] == 54
    assert por_id[pacote["id"]]["totais"]["pacotes"] == 962
    assert por_id[pacote["id"]]["caixas"][0]["posicao_quantitativa_parcial"] is True
    assert por_id[pacote["id"]]["disponibilidade_agregada"] == "PARCIALMENTE_RESERVADO"
    assert {item["id"] for item in visao["sem_pallet"]} == {5, 6}
    assert palletizacao.visao_estoque_por_pallet({"op": "122"})["pallets"][0]["id"] == cortada["id"]
    assert palletizacao.visao_estoque_por_pallet({"produto": "inteira"})["pallets"][0]["id"] == pacote["id"]
    assert palletizacao.visao_estoque_por_pallet({"localizacao": "1"})["pallets"]
    assert palletizacao.visao_estoque_por_pallet({}, {"op": "123"})["sem_pallet"][0]["id"] == 5
    assert visao["indicadores"]["posicoes_palletizadas"] == 4
    assert visao["indicadores"]["posicoes_sem_pallet"] == 2
    assert snapshot(banco, [1, 2, 3, 4, 5, 6, 7]) == antes


def test_p7_movimento_integral_vazio_com_conteudo_e_rollback(banco):
    with banco() as conn:
        conn.execute("INSERT INTO locais_estoque VALUES(2,'Câmara B','interno','Sim')")
        conn.commit()
    vazio = criar("P7-MOV-VAZIO")
    palletizacao.mover_pallet(vazio["id"], 2, posicao_destino="B-01", usuario="EXP",
                              idempotency_key="P7-MOV-0")
    assert palletizacao.consultar_pallet(vazio["id"])["localizacao_atual_id"] == 2
    cheio = criar("P7-MOV-CHEIO")
    palletizacao.adicionar_caixas(cheio["id"], [1, 2], usuario="PCP", idempotency_key="P7-MOV-ADD")
    palletizacao.mover_pallet(cheio["id"], 2, usuario="EXP", idempotency_key="P7-MOV-2")
    with banco() as conn:
        assert {r[0] for r in conn.execute("SELECT local_estoque_id FROM pa_caixas WHERE id IN (1,2)")} == {2}
    bloqueado = criar("P7-MOV-BLOQ")
    palletizacao.adicionar_caixa(bloqueado["id"], 3, usuario="PCP", idempotency_key="P7-MOV-BADD")
    with banco() as conn:
        conn.execute("UPDATE pa_caixas SET estoque_operacional=0 WHERE id=3"); conn.commit()
    with pytest.raises(ValueError, match="não pode acompanhar"):
        palletizacao.mover_pallet(bloqueado["id"], 2, usuario="EXP", idempotency_key="P7-MOV-RB")
    assert palletizacao.consultar_pallet(bloqueado["id"])["localizacao_atual_id"] == 1


def test_p7_estados_cancelamento_reabertura_e_idempotencia(banco):
    pallet = criar("P7-ESTADO")
    palletizacao.encerrar_pallet(pallet["id"], usuario="PCP", idempotency_key="P7-ENC")
    with pytest.raises(ValueError, match="encerrado"):
        palletizacao.adicionar_caixa(pallet["id"], 1, usuario="PCP", idempotency_key="P7-ADD-ENC")
    palletizacao.reabrir_pallet(pallet["id"], usuario="ADM", idempotency_key="P7-REAB",
                               justificativa="Correção operacional aprovada")
    assert palletizacao.consultar_pallet(pallet["id"])["status"] == "DISPONIVEL"
    palletizacao.cancelar_pallet(pallet["id"], usuario="ADM", idempotency_key="P7-CANC",
                                justificativa="Pallet vazio sem uso")
    palletizacao.cancelar_pallet(pallet["id"], usuario="ADM", idempotency_key="P7-CANC",
                                justificativa="Pallet vazio sem uso")
    assert palletizacao.consultar_pallet(pallet["id"])["status"] == "CANCELADO"


def test_p7_agrupar_desagrupar_sem_duplicar_posicoes(banco):
    a, b, destino = criar("P7-G-A"), criar("P7-G-B"), criar("P7-G-D")
    palletizacao.adicionar_caixa(a["id"], 1, usuario="PCP", idempotency_key="P7-G-A1")
    palletizacao.adicionar_caixa(b["id"], 2, usuario="PCP", idempotency_key="P7-G-B1")
    agrupado = palletizacao.agrupar_pallets(destino["id"], [a["id"], b["id"]],
                                            usuario="PCP", idempotency_key="P7-G")
    assert agrupado["totais"]["caixas"] == 2
    novo = criar("P7-D-D")
    palletizacao.desagrupar_pallet(destino["id"], novo["id"], [1], usuario="PCP",
                                   idempotency_key="P7-D")
    with banco() as conn:
        assert tuple(conn.execute("SELECT COUNT(*),COUNT(DISTINCT caixa_id) FROM pallet_caixas_atuais").fetchone()) == (2, 2)
