"""Relatorio oficial, somente leitura, dos romaneios filtrados na Central."""

from collections import defaultdict
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config import EMPRESA_EMITENTE, ESTABELECIMENTO_DOCUMENTO, IDENTIFICACAO_TECNOLOGIA
from modules.auth.services import nome_usuario_atual

from .estoque_service import TIPOS_ROMANEIO, TIPOS_SAIDA
from .services import buscar_itens_expedicao


AZUL = colors.HexColor("#184d69")
TINTA = colors.HexColor("#26343a")
CINZA = colors.HexColor("#607078")
LINHA = colors.HexColor("#cbd5d9")
FUNDO = colors.HexColor("#eef3f5")
AGRUPAMENTO_ROMANEIO = "ROMANEIO"
AGRUPAMENTO_OP = "OP"


def _texto(valor, padrao="Não informado"):
    valor = str(valor or "").strip()
    return valor or padrao


def _numero(valor, casas=0):
    numero = float(valor or 0)
    texto = f"{numero:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _data_br(valor):
    try:
        return datetime.strptime(str(valor), "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return _texto(valor)


def _tipo(item):
    codigo = item.get("tipo_saida") or item.get("tipo_movimentacao")
    return TIPOS_SAIDA.get(codigo, TIPOS_ROMANEIO.get(codigo, str(codigo or "Não informado").replace("_", " ").title()))


def _cliente(item):
    return _texto(item.get("cliente_nome") or item.get("cliente_fantasia") or item.get("destino"))


def _unidade(item):
    unidade = str(item.get("unidade_estoque") or "UNIDADE").strip().upper()
    mapa = {
        "CAIXA": "caixas", "BANDEJA": "bandejas", "PACOTE": "pacotes",
        "UNIDADE": "unidades", "GALINHA": "galinhas", "KG": "quilogramas",
    }
    return mapa.get(unidade, unidade.lower())


def _quantidade_item(item):
    unidade = _unidade(item)
    if unidade == "pacotes":
        return float(item.get("quantidade_pacotes") or item.get("quantidade_unidades") or 0)
    if unidade == "caixas":
        return float(item.get("quantidade_caixas") or (1 if item.get("caixa_id") else item.get("quantidade_unidades") or 0))
    if unidade == "bandejas":
        return float(item.get("quantidade_bandejas") or item.get("quantidade_unidades") or 0)
    if unidade == "quilogramas":
        return float(item.get("quantidade_kg") or 0)
    return float(item.get("quantidade_unidades") or 0)


def _totais_unidades(itens):
    totais = defaultdict(float)
    for item in itens:
        unidade = _unidade(item)
        if unidade != "quilogramas":
            totais[unidade] += _quantidade_item(item)
        bandejas = float(item.get("quantidade_bandejas") or 0)
        if bandejas and unidade != "bandejas":
            totais["bandejas"] += bandejas
        galinhas = float(item.get("quantidade_galinhas") or 0)
        if galinhas:
            totais["galinhas"] += galinhas
    return {unidade: total for unidade, total in totais.items() if total}


def _normalizar_agrupamento(valor):
    return AGRUPAMENTO_OP if str(valor or "").strip().upper() == AGRUPAMENTO_OP else AGRUPAMENTO_ROMANEIO


def _expedicoes_unicas(expedicoes):
    unicas = {}
    for expedicao in expedicoes:
        unicas.setdefault(expedicao["id"], expedicao)
    return list(unicas.values())


def _peso_itens(itens):
    return sum(float(item.get("quantidade_kg") or 0) for item in itens)


def _rotulo_unidade(unidade, total):
    singular = {"caixas": "caixa", "bandejas": "bandeja", "pacotes": "pacote", "unidades": "unidade", "galinhas": "galinha"}
    return singular.get(unidade, unidade) if total == 1 else unidade


def _resumo_quantidades(itens):
    ordem = ("caixas", "bandejas", "pacotes", "unidades", "galinhas")
    totais = _totais_unidades(itens)
    partes = [
        f"{_numero(totais[unidade], 0 if totais[unidade].is_integer() else 2)} {_rotulo_unidade(unidade, totais[unidade])}"
        for unidade in ordem if totais.get(unidade)
    ]
    partes.extend(
        f"{_numero(total, 0 if total.is_integer() else 2)} {unidade}"
        for unidade, total in sorted(totais.items()) if unidade not in ordem
    )
    return "; ".join(partes) or "sem quantidade informada"


def _p(texto, estilo):
    return Paragraph(escape(_texto(texto)), estilo)


class _Documento(SimpleDocTemplate):
    def __init__(self, destino, emissao, usuario, logo, titulo_documento):
        super().__init__(
            destino, pagesize=landscape(A4),
            leftMargin=10 * mm, rightMargin=10 * mm,
            topMargin=38 * mm, bottomMargin=13 * mm,
            title=titulo_documento,
            author=usuario,
        )
        self.emissao = emissao
        self.usuario = usuario
        self.logo = logo

    def build(self, flowables, **kwargs):
        return super().build(flowables, **kwargs)

    def afterPage(self):
        self._pagina(self.canv, self)

    def _pagina(self, canvas, doc):
        canvas.saveState()
        if self.logo and Path(self.logo).exists():
            canvas.drawImage(self.logo, 10 * mm, 188 * mm, width=14 * mm, height=14 * mm, preserveAspectRatio=True, mask="auto")
        canvas.setFillColor(AZUL)
        canvas.setFont("Helvetica-Bold", 9.5)
        canvas.drawString(27 * mm, 197 * mm, ESTABELECIMENTO_DOCUMENTO)
        canvas.setFillColor(CINZA)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(27 * mm, 192.5 * mm, "DOCUMENTO OFICIAL")
        canvas.setStrokeColor(AZUL)
        canvas.setLineWidth(1.2)
        canvas.line(10 * mm, 187 * mm, 287 * mm, 187 * mm)
        canvas.setFillColor(CINZA)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(10 * mm, 6.5 * mm, f"Emitido em {self.emissao} - horário de Manaus")
        canvas.drawCentredString(
            148.5 * mm, 6.5 * mm,
            f"{IDENTIFICACAO_TECNOLOGIA} | Emitido por: {self.usuario}",
        )
        canvas.drawRightString(287 * mm, 6.5 * mm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()


def gerar_relatorio_entregas_pdf(expedicoes, filtros, cliente_selecionado=None, emissao=None, usuario=None, logo=None, agrupamento=None):
    """Gera as visoes comercial ou analitica sem alterar dados operacionais."""
    agrupamento = _normalizar_agrupamento(agrupamento or filtros.get("agrupamento"))
    expedicoes = _expedicoes_unicas(expedicoes)
    visao_op = agrupamento == AGRUPAMENTO_OP
    titulo_texto = "RELATÓRIO ANALÍTICO DE ENTREGAS POR ORDEM DE PRODUÇÃO" if visao_op else "RELATÓRIO DE ENTREGAS POR CLIENTE"
    titulo_documento = "Relatório Analítico de Entregas por Ordem de Produção" if visao_op else "Relatório de Entregas por Cliente"
    agrupamento_texto = "Por Ordem de Produção - Visão analítica" if visao_op else "Por romaneio - Visão comercial"
    emissao = emissao or datetime.now().strftime("%d/%m/%Y às %H:%M")
    usuario = _texto(usuario or nome_usuario_atual(), "Usuário não identificado")
    logo = logo or str(Path(__file__).resolve().parents[2] / "static" / "imagens" / "logo.png")
    buffer = BytesIO()
    doc = _Documento(buffer, emissao, usuario, logo, titulo_documento)
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("titulo", parent=estilos["Title"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=AZUL, alignment=TA_CENTER, spaceAfter=2 * mm)
    subtitulo = ParagraphStyle("subtitulo", parent=estilos["Normal"], fontSize=8.5, leading=11, textColor=CINZA, alignment=TA_CENTER, spaceAfter=3 * mm)
    normal = ParagraphStyle("normal", parent=estilos["Normal"], fontSize=7.2, leading=9, textColor=TINTA)
    pequeno = ParagraphStyle("pequeno", parent=normal, fontSize=6.4, leading=7.6)
    analitico = ParagraphStyle("analitico", parent=normal, fontSize=5.8, leading=7)
    cab = ParagraphStyle("cab", parent=pequeno, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_CENTER)
    cab_analitico = ParagraphStyle("cab_analitico", parent=analitico, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_CENTER)
    direita = ParagraphStyle("direita", parent=pequeno, alignment=TA_RIGHT)
    direita_analitico = ParagraphStyle("direita_analitico", parent=analitico, alignment=TA_RIGHT)
    grupo = ParagraphStyle("grupo", parent=normal, fontName="Helvetica-Bold", fontSize=9, textColor=AZUL, spaceBefore=2 * mm, spaceAfter=1 * mm)

    historia = [Paragraph(titulo_texto, titulo), Paragraph(f"Agrupamento: {agrupamento_texto}", subtitulo)]

    cliente_filtro = _texto(cliente_selecionado, "Todos")
    tipo_codigo = filtros.get("tipo") or "Todos"
    tipo_filtro = "Todos" if tipo_codigo == "Todos" else TIPOS_SAIDA.get(tipo_codigo, TIPOS_ROMANEIO.get(tipo_codigo, tipo_codigo))
    metadados = [
        ["Empresa", EMPRESA_EMITENTE, "Cliente", cliente_filtro],
        ["Período", f"{_data_br(filtros.get('data_inicio'))} a {_data_br(filtros.get('data_fim'))}", "Status", _texto(filtros.get("status"), "Todos")],
        ["Tipo de operação", tipo_filtro, "Nº romaneio", _texto(filtros.get("numero"), "Todos")],
        ["Produto", _texto(filtros.get("produto"), "Todos"), "Destino", _texto(filtros.get("destino"), "Todos")],
    ]
    meta = Table([[Paragraph(f"<b>{escape(a)}</b>", pequeno), _p(b, normal), Paragraph(f"<b>{escape(c)}</b>", pequeno), _p(d, normal)] for a, b, c, d in metadados], colWidths=[29*mm, 96*mm, 29*mm, 123*mm])
    meta.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), .35, LINHA), ("BACKGROUND", (0,0), (0,-1), FUNDO),
        ("BACKGROUND", (2,0), (2,-1), FUNDO), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    historia += [meta, Spacer(1, 3 * mm)]

    todos_itens = []
    itens_por_romaneio = {}
    for romaneio in expedicoes:
        itens = [dict(item) for item in buscar_itens_expedicao(romaneio["id"])]
        itens_por_romaneio[romaneio["id"]] = itens
        todos_itens.extend(itens)

    status = defaultdict(int)
    for romaneio in expedicoes:
        status[str(romaneio.get("status") or "").lower()] += 1
    indicadores = [
        ("Total de romaneios", len(expedicoes)), ("Concluídos", status["concluído"]),
        ("Cancelados", status["cancelado"]), ("Estornados", status["estornado"]),
    ]
    totais_unidades = _totais_unidades(todos_itens)
    for unidade in ("caixas", "bandejas", "pacotes", "unidades", "galinhas"):
        total = totais_unidades.get(unidade)
        if total:
            indicadores.append((unidade.capitalize(), _numero(total, 0 if total.is_integer() else 2)))
    peso = _peso_itens(todos_itens)
    if peso:
        indicadores.append(("Peso entregue", f"{_numero(peso, 3)} kg"))
    max_colunas = min(6, max(1, len(indicadores)))
    linhas_cards = []
    for inicio in range(0, len(indicadores), max_colunas):
        linha = indicadores[inicio:inicio + max_colunas]
        linha += [("", "")] * (max_colunas - len(linha))
        linhas_cards.append([Paragraph(f"<font color='#607078'>{escape(str(rotulo))}</font><br/><b>{escape(str(valor))}</b>", normal) for rotulo, valor in linha])
    cards = Table(linhas_cards, colWidths=[277*mm/max_colunas]*max_colunas)
    cards.setStyle(TableStyle([("BOX",(0,0),(-1,-1),.5,LINHA),("INNERGRID",(0,0),(-1,-1),.35,LINHA),("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#f7f9fa")),("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    historia += [cards, Spacer(1, 3 * mm)]

    grupos = defaultdict(list)
    ordenadas = sorted(expedicoes, key=lambda x: (str(x.get("cliente_nome") or x.get("destino") or ""), str(x.get("data") or ""), str(x.get("numero_romaneio") or "")))
    for expedicao in ordenadas:
        grupos[_cliente(expedicao)].append(expedicao)

    for nome_cliente, romaneios in grupos.items():
        itens_cliente = []
        historia.append(Paragraph(f"Cliente: {escape(nome_cliente)}", grupo))
        if visao_op:
            colunas = ["Romaneio", "OP / lote", "Produto / apresentação", "Quantidade", "Peso", "Cliente / destino", "Responsável", "Status"]
            larguras = [25, 26, 48, 28, 20, 53, 48, 29]
            linhas = [[Paragraph(c, cab_analitico) for c in colunas]]
            for romaneio in romaneios:
                itens = itens_por_romaneio[romaneio["id"]] or [{}]
                itens_cliente.extend(item for item in itens if item)
                for item in itens:
                    unidade = _unidade(item) if item else "-"
                    quantidade = _quantidade_item(item) if item else 0
                    op_lote = f"<b>OP:</b> {escape(_texto(item.get('op_id') if item else None, '-'))}<br/><b>Lote:</b> {escape(_texto((item.get('lote') or item.get('codigo_caixa')) if item else None, '-'))}"
                    produto = f"{escape(_texto(item.get('sku') if item else None))}<br/><font color='#607078'>{escape(_texto(item.get('apresentacao') if item else None, '-'))}</font>"
                    cliente_destino = f"<b>Cliente:</b> {escape(_cliente(romaneio))}<br/><b>Destino:</b> {escape(_texto(romaneio.get('destino')))}"
                    linhas.append([
                        _p(romaneio.get("numero_romaneio"), analitico), Paragraph(op_lote, analitico), Paragraph(produto, analitico),
                        Paragraph(f"{_numero(quantidade, 0 if quantidade.is_integer() else 2)} {escape(_rotulo_unidade(unidade, quantidade))}", direita_analitico),
                        _p(f"{_numero(item.get('quantidade_kg'), 3)} kg" if item and item.get("quantidade_kg") else "-", direita_analitico),
                        Paragraph(cliente_destino, analitico), _p(romaneio.get("responsavel") or romaneio.get("criado_por"), analitico), _p(romaneio.get("status"), analitico),
                    ])
        else:
            colunas = ["Romaneio", "Data", "Cliente / destino", "Tipo", "Produtos / apresentações", "Quantidade entregue", "Peso", "Responsável", "Status"]
            larguras = [25, 16, 39, 24, 59, 31, 19, 38, 26]
            linhas = [[Paragraph(c, cab) for c in colunas]]
            for romaneio in romaneios:
                itens = itens_por_romaneio[romaneio["id"]]
                itens_cliente.extend(itens)
                apresentacoes = defaultdict(list)
                for item in itens:
                    apresentacoes[(_texto(item.get("sku")), _texto(item.get("apresentacao"), "-"))].append(item)
                produtos = []
                for (sku, apresentacao), itens_apresentacao in sorted(apresentacoes.items()):
                    detalhe = _resumo_quantidades(itens_apresentacao)
                    peso_apresentacao = _peso_itens(itens_apresentacao)
                    if peso_apresentacao:
                        detalhe += f"; {_numero(peso_apresentacao, 3)} kg"
                    produtos.append(f"<b>{escape(sku)}</b> - {escape(apresentacao)}<br/><font color='#607078'>{escape(detalhe)}</font>")
                cliente_destino = f"<b>Cliente:</b> {escape(_cliente(romaneio))}<br/><b>Destino:</b> {escape(_texto(romaneio.get('destino')))}"
                peso_romaneio = _peso_itens(itens)
                linhas.append([
                    _p(romaneio.get("numero_romaneio"), pequeno), _p(_data_br(romaneio.get("data")), pequeno), Paragraph(cliente_destino, pequeno),
                    _p(_tipo(romaneio), pequeno), Paragraph("<br/>".join(produtos) if produtos else "Sem itens", pequeno),
                    _p(_resumo_quantidades(itens), direita), _p(f"{_numero(peso_romaneio, 3)} kg" if peso_romaneio else "-", direita),
                    _p(romaneio.get("responsavel") or romaneio.get("criado_por"), pequeno), _p(romaneio.get("status"), pequeno),
                ])

        tabela = Table(linhas, repeatRows=1, colWidths=[x*mm for x in larguras], hAlign="LEFT")
        tabela.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),AZUL),("GRID",(0,0),(-1,-1),.3,LINHA),("VALIGN",(0,0),(-1,-1),"TOP"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafb")]),
            ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ]))
        peso_cliente = _peso_itens(itens_cliente)
        resumo_cliente = _resumo_quantidades(itens_cliente)
        if peso_cliente:
            resumo_cliente += f"; {_numero(peso_cliente, 3)} kg"
        historia += [tabela, KeepTogether([Paragraph(f"Subtotal - {escape(nome_cliente)}: {escape(resumo_cliente)}", grupo), Spacer(1, 2*mm)])]

    totais_gerais = _resumo_quantidades(todos_itens)
    if peso:
        totais_gerais += f"; {_numero(peso, 3)} kg"
    geral = Table([[Paragraph("TOTAL GERAL", cab), Paragraph(escape(totais_gerais), normal)]], colWidths=[40*mm, 237*mm])
    geral.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),AZUL),("BOX",(0,0),(-1,-1),.7,AZUL),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    historia.append(KeepTogether([Spacer(1, 2*mm), geral]))
    doc.build(historia)
    return buffer.getvalue()
