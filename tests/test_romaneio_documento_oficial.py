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


def test_css_define_a4_horizontal_repeticao_e_quebras_seguras():
    compacto = "".join(CSS.split()).lower()
    assert "@page{size:a4landscape;margin:10mm11mm}" in compacto
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
    assert "<strong>Paisagem</strong>" in TEMPLATE
    assert "Cabe&ccedil;alhos e rodap&eacute;s" in TEMPLATE
    assert 'class="rom-doc-screen-tools no-print"' in TEMPLATE


def test_rodape_oficial_e_assinaturas_estao_presentes():
    assert "rom-doc-footer" in TEMPLATE
    assert "Documento oficial" in TEMPLATE
    assert "Respons&aacute;vel pela movimenta&ccedil;&atilde;o" in TEMPLATE
    assert "Confer&ecirc;ncia / Recebimento" in TEMPLATE


def test_tipografia_de_impressao_tem_escala_legivel_em_a4_horizontal():
    compacto = "".join(CSS.split()).lower()
    for contrato in (
        ".rom-doc-titleh1{margin:1mm00;color:var(--rom-blue);font-size:16pt",
        ".rom-doc-meta-gridsmall{color:var(--rom-muted);font-size:8.5pt",
        ".rom-doc-meta-gridstrong{font-size:11pt",
        ".rom-doc-item-table{width:100%;margin:0;border-collapse:collapse;table-layout:fixed;font-size:10pt",
        ".rom-doc-item-tabletheadth{background:#e8eef1;color:#254f60;font-size:9pt",
        ".rom-doc-notesp{margin:0;padding:3mm;font-size:10.5pt",
        ".rom-doc-signatures{display:grid;grid-template-columns:1fr1fr;gap:28mm;margin-top:18mm;min-height:22mm",
    ):
        assert contrato in compacto
    assert "@page{size:a4landscape" in compacto


def test_fallbacks_jinja_usam_unicode_sem_entidades_duplamente_codificadas():
    assert 'expedicao.observacoes or "Sem observações."' in TEMPLATE
    assert 'or "Não identificado"' in TEMPLATE
    assert "Inventário legado" in TEMPLATE
    assert "NÃ" not in TEMPLATE
    assert 'or "Sem observa&ccedil;&otilde;es."' not in TEMPLATE
    assert "|safe" not in TEMPLATE


def test_fechamento_curto_fica_unido_e_tabela_cortada_distribui_as_colunas():
    compacto = "".join(CSS.split()).lower()
    assert "rom-doc-closing" in TEMPLATE
    assert "|length<600" in "".join(TEMPLATE.split())
    assert ".rom-doc-closing.keep-together{break-inside:avoid;page-break-inside:avoid}" in compacto
    assert ".rom-doc-cut-tableth:nth-child(8){width:13%}" in compacto


def test_colunas_horizontais_e_quebra_somente_entre_palavras():
    compacto = "".join(CSS.split()).lower()
    assert "overflow-wrap:anywhere" not in compacto
    assert "word-break:normal" in compacto
    assert ".rom-doc-item-tabletheadth.wrap{white-space:normal;text-align:center}" in compacto
    assert ".rom-doc-whole-tableth:first-child{width:25%}" in compacto
    assert ".rom-doc-whole-tableth:nth-child(2){width:30%}" in compacto
    assert ".rom-doc-whole-tableth:nth-child(6){width:15%}" in compacto
    assert 'class="rom-doc-item-table rom-doc-whole-table"' in TEMPLATE
    assert 'class="wrap">Lote / identifica&ccedil;&atilde;o' in TEMPLATE
