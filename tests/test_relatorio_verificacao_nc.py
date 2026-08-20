from contextlib import contextmanager
from io import BytesIO
import sqlite3

import pytest
from flask import Flask
from pypdf import PdfReader

from modules.expedicao import relatorio_nc_service as servico
from modules.expedicao import routes
from modules.expedicao.relatorio_nc_pdf import gerar_relatorio_nc_pdf


@pytest.fixture()
def banco_relatorio(tmp_path, monkeypatch):
    caminho = tmp_path / "relatorio-nc.db"

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transacao():
        conn = conectar()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(servico, "conectar", conectar)
    monkeypatch.setattr(servico, "transaction", transacao)
    monkeypatch.setattr(servico, "DATABASE_URL", None)
    monkeypatch.setattr(servico, "criar_tabelas_estoque_confiavel", lambda: None)
    monkeypatch.setattr(servico, "garantir_schema", lambda **_: None)

    conn = conectar()
    conn.executescript("""
        CREATE TABLE skus (
            id INTEGER PRIMARY KEY, codigo TEXT, nome TEXT,
            unidade_venda TEXT, ativo TEXT, excluido_em TEXT
        );
        INSERT INTO skus VALUES
            (1, 'LEG-1', 'Galinha Cortada', 'CAIXA', 'Sim', NULL),
            (2, 'LEG-2', 'Galinha Inteira', 'PACOTE', 'Sim', NULL);

        CREATE TABLE pa_caixas (
            id INTEGER PRIMARY KEY, codigo_caixa TEXT, sku TEXT,
            apresentacao TEXT, unidade_estoque TEXT, galinhas_por_pacote INTEGER,
            condicao TEXT, disponibilidade TEXT, status TEXT,
            estoque_operacional INTEGER, quantidade_bandejas INTEGER,
            peso_liquido REAL, quantidade_pacotes INTEGER,
            quantidade_galinhas INTEGER, quantidade_pacotes_reservados INTEGER,
            lote TEXT, validade TEXT, local_estoque_id INTEGER
        );
        INSERT INTO pa_caixas VALUES
            (1,'CX-SEGREDO-1','LEG-1','Congelada','CAIXA',NULL,'NAO_CONFORME','BLOQUEADO','Em estoque',1,12,10.125,0,0,0,'LOTE-X','2027-01-01',99),
            (2,'CX-SEGREDO-2','LEG-2','Pacote com 1 ave','PACOTE',1,'NAO_CONFORME','BLOQUEADO','Em estoque',1,0,NULL,20,20,0,'LOTE-Y','2027-02-01',99),
            (3,'CX-SEGREDO-3','LEG-2','Pacote com 2 aves','PACOTE',2,'NAO_CONFORME','REPROCESSAMENTO','Em estoque',1,0,NULL,5,10,0,'LOTE-Z','2027-03-01',99),
            (4,'CX-SEGREDO-4','LEG-1','Congelada','CAIXA',NULL,'NAO_CONFORME','BLOQUEADO','Em estoque',1,6,4.500,0,0,0,'LOTE-W','2027-04-01',99),
            (5,'CX-CANCELADA','LEG-1','Congelada','CAIXA',NULL,'NAO_CONFORME','BLOQUEADO','CANCELADO',1,99,99,0,0,0,'LOTE-C','2027-05-01',99);

        CREATE TABLE pa_nao_conformes (
            id INTEGER PRIMARY KEY, numero TEXT, op_id INTEGER, caixa_id INTEGER,
            lote TEXT, produto TEXT, apresentacao TEXT, quantidade REAL, peso REAL,
            unidade TEXT, motivo TEXT, descricao TEXT, status TEXT,
            local_estoque_id INTEGER, registrado_por TEXT, perfil_registro TEXT,
            registrado_em TEXT, tipo_registro TEXT, condicao_inicial TEXT,
            caixas_bloqueadas INTEGER DEFAULT 0, bandejas_bloqueadas INTEGER DEFAULT 0,
            saldo_bloqueado_g INTEGER DEFAULT 0, saldo_pendente_g INTEGER DEFAULT 0,
            saldo_operacional_g INTEGER DEFAULT 0,
            saldo_reservado_operacional_g INTEGER DEFAULT 0
        );
        INSERT INTO pa_nao_conformes VALUES
            (1,'PNC-TECNICO-1',71,1,'LOTE-X','Galinha Cortada','Congelada',12,10.125,'BANDEJA','Carne Escura',NULL,'BLOQUEADO',99,'Qualidade','qualidade','2026-08-20','CAIXA_RASTREADA','NAO_CONFORME',0,0,0,0,0,0),
            (2,'PNC-TECNICO-2',72,2,'LOTE-Y','Galinha Inteira','Pacote com 1 ave',20,NULL,'PACOTE','Outro','Avaria de embalagem','BLOQUEADO',99,'Qualidade','qualidade','2026-08-20','CAIXA_RASTREADA','NAO_CONFORME',0,0,0,0,0,0),
            (3,'PNC-TECNICO-3',73,3,'LOTE-Z','Galinha Inteira','Pacote com 2 aves',5,NULL,'PACOTE','Carcaça Incompleta',NULL,'REPROCESSO',99,'Qualidade','qualidade','2026-08-20','CAIXA_RASTREADA','NAO_CONFORME',0,0,0,0,0,0),
            (4,'PNC-TECNICO-4',74,4,'LOTE-W','Galinha Cortada','Congelada',6,4.5,'BANDEJA','Carne Escura',NULL,'BLOQUEADO',99,'Qualidade','qualidade','2026-08-20','CAIXA_RASTREADA','NAO_CONFORME',0,0,0,0,0,0),
            (10,'PNC-LEGADO-10',NULL,NULL,'LEGADO','Galinha Cortada','Congelada',60,50,'BANDEJA','Queimadura de Frio',NULL,'BLOQUEADO',99,'Inventário','qualidade','2026-08-01','INVENTARIO_LEGADO_AGREGADO','NAO_CONFORME',5,60,50000,10000,0,0);

        CREATE TABLE pa_nao_conforme_solicitacoes (
            id INTEGER PRIMARY KEY, pa_nao_conforme_id INTEGER,
            peso_g INTEGER, caixas INTEGER, bandejas INTEGER, status TEXT
        );
        INSERT INTO pa_nao_conforme_solicitacoes VALUES
            (1,4,4500,1,6,'AGUARDANDO_VALIDACAO_GERENCIA'),
            (2,10,10000,1,12,'AGUARDANDO_VALIDACAO_GERENCIA');

        CREATE TABLE expedicoes (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE expedicao_itens (
            id INTEGER PRIMARY KEY, expedicao_id INTEGER,
            pa_nao_conforme_id INTEGER, quantidade_caixas INTEGER,
            quantidade_bandejas INTEGER
        );
        CREATE TABLE estoque_eventos (id INTEGER PRIMARY KEY, acao TEXT);
        INSERT INTO estoque_eventos VALUES (1,'BASELINE');
    """)
    conn.commit()
    conn.close()
    return conectar


def _fotografia_estoque(conectar):
    conn = conectar()
    try:
        return {
            tabela: [tuple(linha) for linha in conn.execute(f"SELECT * FROM {tabela} ORDER BY id")]
            for tabela in ("pa_caixas", "pa_nao_conformes", "pa_nao_conforme_solicitacoes", "estoque_eventos")
        }
    finally:
        conn.close()


def test_filtros_e_selecao_multipla_consolidam_fontes(banco_relatorio):
    itens, opcoes, _ = servico.listar_saldos_nc()
    assert len(itens) == 6
    assert "Carne Escura" in opcoes["caracteristica"]
    assert "Avaria de embalagem" in opcoes["caracteristica"]
    assert {item["situacao"] for item in itens} == {
        "nao_conforme_bloqueado", "reprocessamento", "aguardando_liberacao",
    }

    filtrados, _, _ = servico.listar_saldos_nc({
        "produto": "Galinha Inteira", "apresentacao": "Pacote com 1 ave",
        "caracteristica": "Avaria de embalagem", "situacao": "nao_conforme_bloqueado",
        "busca": "embalagem",
    })
    assert [item["chave"] for item in filtrados] == ["caixa:2"]

    previa = servico.consolidar_selecao(["caixa:1", "caixa:4"])
    assert previa["quantidade_registros"] == 2
    assert previa["secoes"][0]["linhas"][0]["quantidades"] == {
        "caixas": 2, "bandejas": 18, "peso_kg": pytest.approx(14.625),
    }


def test_emissao_revalida_saldo_e_nao_movimenta_estoque(banco_relatorio):
    antes = _fotografia_estoque(banco_relatorio)
    previa = servico.consolidar_selecao(["caixa:1", "caixa:2"])
    relatorio = servico.emitir_relatorio_nc(
        ["caixa:1", "caixa:2"], previa["token"], {"produto": ""},
        usuario="Teste Qualidade", perfil="qualidade",
    )
    assert relatorio["numero"].startswith("RNC-")
    assert relatorio["resultado"] == "GERADO"
    assert _fotografia_estoque(banco_relatorio) == antes
    conn = banco_relatorio()
    assert conn.execute("SELECT COUNT(*) FROM relatorios_nc_verificacao_eventos").fetchone()[0] == 1
    detalhes = conn.execute("SELECT detalhes_json FROM relatorios_nc_verificacao_eventos").fetchone()[0]
    assert all(campo in detalhes for campo in ('"numero"', '"totais"', '"resultado":"GERADO"'))
    conn.execute("UPDATE pa_caixas SET peso_liquido=11 WHERE id=1")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="mudaram"):
        servico.emitir_relatorio_nc(
            ["caixa:1", "caixa:2"], previa["token"], {},
            usuario="Teste Qualidade", perfil="qualidade",
        )


def test_reimpressao_preserva_snapshot_e_pdf_oculta_identificadores(banco_relatorio):
    previa = servico.consolidar_selecao(["caixa:1", "caixa:2", "caixa:3"])
    relatorio = servico.emitir_relatorio_nc(
        ["caixa:1", "caixa:2", "caixa:3"], previa["token"], {},
        usuario="Teste Qualidade", perfil="qualidade",
    )
    conn = banco_relatorio()
    conn.execute("UPDATE pa_caixas SET peso_liquido=99 WHERE id=1")
    conn.commit()
    conn.close()
    reimpresso = servico.obter_relatorio_nc(relatorio["id"])
    assert reimpresso["snapshot"] == relatorio["snapshot"]

    pdf = gerar_relatorio_nc_pdf(reimpresso, logo="")
    texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages)
    assert pdf.startswith(b"%PDF")
    assert "RELATÓRIO DE VERIFICAÇÃO E AUTORIZAÇÃO" in texto
    assert "Carne Escura" in texto
    assert "Avaria de embalagem" in texto
    assert "Decisão da Diretoria" in texto
    for proibido in ("LEG-1", "LEG-2", "LOTE-X", "PNC-TECNICO", "CX-SEGREDO", "SKU", "Validade", "Local"):
        assert proibido not in texto


def test_integridade_impede_reimpressao_adulterada(banco_relatorio):
    previa = servico.consolidar_selecao(["caixa:1"])
    relatorio = servico.emitir_relatorio_nc(
        ["caixa:1"], previa["token"], {}, usuario="Teste", perfil="gerencia",
    )
    conn = banco_relatorio()
    conn.execute("UPDATE relatorios_nc_verificacao SET snapshot_json='{}' WHERE id=?", (relatorio["id"],))
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="integridade"):
        servico.obter_relatorio_nc(relatorio["id"])


def test_rotas_exigem_perfil_e_expoem_controles(monkeypatch):
    app = Flask(__name__, template_folder="../templates")
    app.secret_key = "teste"
    app.jinja_env.filters["br_numero"] = lambda valor, casas=2: f"{float(valor):.{int(casas)}f}"
    app.url_build_error_handlers.append(lambda error, endpoint, values: "#")
    routes.register_expedicao_routes(app)
    item = {
        "chave": "caixa:1", "produto": "Galinha Cortada", "apresentacao": "Congelada",
        "caracteristica": "Carne Escura", "situacao": "nao_conforme_bloqueado",
        "situacao_rotulo": "Não conforme bloqueado", "unidades": ["caixas", "bandejas", "peso_kg"],
        "quantidades": {"caixas": 1, "bandejas": 12, "peso_kg": 10.125},
    }
    monkeypatch.setattr(routes, "listar_saldos_nc", lambda _filtros: ([item], {
        "produto": ["Galinha Cortada"], "apresentacao": ["Congelada"],
        "caracteristica": ["Carne Escura"], "situacao": ["nao_conforme_bloqueado"],
    }, _filtros))
    monkeypatch.setattr(routes, "listar_relatorios_nc", lambda: [])
    monkeypatch.setattr(routes, "buscar_estoque_operacional", lambda: ([], {}))
    monkeypatch.setattr(routes, "consolidar_selecao", lambda _chaves: {
        "token": "abc", "quantidade_registros": 1,
        "secoes": [{"produto": "Galinha Cortada", "apresentacao": "Congelada",
                    "unidades": ["caixas"], "totais": {"caixas": 1}}],
    })

    with app.test_client() as cliente:
        sem_sessao = cliente.get("/expedicao/nao-conformes")
        with cliente.session_transaction() as sessao:
            sessao.update(usuario_id=1, perfil="qualidade", nome="Qualidade")
        pagina = cliente.get("/expedicao/nao-conformes")
        previa = cliente.post("/expedicao/nao-conformes/relatorio/previa", data={"saldo_id": "caixa:1"})
        with cliente.session_transaction() as sessao:
            sessao["perfil"] = "producao"
        proibido = cliente.post("/expedicao/nao-conformes/relatorio/previa", data={"saldo_id": "caixa:1"})

    html = pagina.get_data(as_text=True)
    assert sem_sessao.status_code == proibido.status_code == 302
    assert pagina.status_code == 200
    assert previa.get_json()["token"] == "abc"
    assert "Selecionar todos os resultados" in html
    assert "Atualizar prévia" in html
    assert "Gerar relatório de verificação" in html
    assert 'name="snapshot_token"' in html
