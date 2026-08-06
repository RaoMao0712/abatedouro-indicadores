"""Contratos do documento oficial imprimível de romaneio."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "romaneio_impressao.html").read_text(encoding="utf-8")
BASE = (ROOT / "templates" / "base_impressao.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "romaneio_impressao.css").read_text(encoding="utf-8")


def test_documento_usa_base_isolada_sem_navegacao_da_aplicacao():
    assert '{% extends "base_impressao.html" %}' in TEMPLATE
    assert "fd-sidebar" not in BASE
    assert "navigation.js" not in BASE
    assert "container-com-sidebar" not in BASE


def test_logo_titulo_numero_status_e_emissao_estao_no_cabecalho():
    assert "imagens/logo.png" in TEMPLATE
    assert "Logo oficial do Abatedouro" in TEMPLATE
    assert "ROMANEIO DE {{ tipo_descricao|upper }}" in TEMPLATE
    assert "expedicao.numero_romaneio" in TEMPLATE
    assert "expedicao.status" in TEMPLATE
    assert "emissao_formatada" in TEMPLATE


def test_dados_pessoais_e_datas_usam_valores_pre_formatados():
    assert "documento_cliente_formatado" in TEMPLATE
    assert "data_romaneio_formatada" in TEMPLATE
    assert "conclusao_formatada" in TEMPLATE
    assert "expedicao.concluido_em" not in TEMPLATE


def test_tabelas_preservam_inteira_cortada_e_legado_com_totais():
    for contrato in (
        "Galinha Inteira - controle por pacotes",
        "Galinha Cortada - controle por caixas e peso",
        "INVENTARIO_LEGADO_AGREGADO",
        "quantidade_caixas",
        "quantidade_bandejas",
        "total_pacotes",
        "total_galinhas",
        "total_caixas",
        "total_kg",
    ):
        assert contrato in TEMPLATE


def test_css_define_a4_retrato_repeticao_e_quebras_seguras():
    compacto = "".join(CSS.split()).lower()
    assert "@page{size:a4portrait;margin:10mm11mm}" in compacto
    assert ".rom-doc-shell>thead{display:table-header-group}" in compacto
    assert ".rom-doc-item-tablethead{display:table-header-group}" in compacto
    assert "break-inside:avoid" in compacto
    assert "page-break-inside:avoid" in compacto
    assert "page-break-before" not in compacto
    assert "break-before" not in compacto


def test_template_nao_incorpora_url_e_orienta_configuracao_do_navegador():
    assert "http://" not in TEMPLATE
    assert "https://" not in TEMPLATE
    assert "1 p&aacute;gina por folha" in TEMPLATE
    assert "Cabe&ccedil;alhos e rodap&eacute;s" in TEMPLATE
    assert 'class="rom-doc-screen-tools no-print"' in TEMPLATE


def test_rodape_oficial_e_assinaturas_estao_presentes():
    assert "rom-doc-footer" in TEMPLATE
    assert "Documento oficial" in TEMPLATE
    assert "Respons&aacute;vel pela movimenta&ccedil;&atilde;o" in TEMPLATE
    assert "Confer&ecirc;ncia / Recebimento" in TEMPLATE
