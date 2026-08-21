"""PDF gerencial, somente leitura, dos romaneios de descarte PNC."""

from collections import defaultdict
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

from config import EMPRESA_EMITENTE, ESTABELECIMENTO_DOCUMENTO
from .descarte_pnc_relatorio import MODALIDADES, TIPOS_DATA


AZUL = colors.HexColor("#184d69")
TINTA = colors.HexColor("#26343a")
CINZA = colors.HexColor("#607078")
LINHA = colors.HexColor("#cbd5d9")
FUNDO = colors.HexColor("#eef3f5")
FUSO_MANAUS = ZoneInfo("America/Manaus")


def _texto(valor, padrao="Não informado"):
    texto = str(valor or "").strip()
    return texto or padrao


def _numero(valor, casas=0):
    texto = f"{float(valor or 0):,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _data(valor, com_hora=False):
    texto = str(valor or "")
    try:
        data = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        return data.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")
    except ValueError:
        return _texto(valor, "-")


def _p(valor, estilo):
    return Paragraph(escape(_texto(valor, "-")), estilo)


def _quantidades(item):
    if item["tipo_unidade"] == "INTEIRA":
        return f"{_numero(item['galinhas'])} galinhas; {_numero(item['pacotes'])} pacotes"
    return (f"{_numero(item['caixas'])} caixas; {_numero(item['bandejas'])} bandejas; "
            f"{_numero(item['peso_g'] / 1000, 3)} kg")


class _Documento(BaseDocTemplate):
    def __init__(self, destino, *, emissao, usuario, logo, modalidade):
        self.paisagem = modalidade == "SINTETICO"
        pagina = landscape(A4) if self.paisagem else A4
        self.formato_pagina = pagina
        super().__init__(destino, pagesize=pagina, leftMargin=10*mm, rightMargin=10*mm,
                         topMargin=34*mm, bottomMargin=14*mm,
                         title="Relatório Consolidado de Romaneios de Descarte", author=usuario)
        self.emissao = emissao
        self.usuario = usuario
        self.logo = logo
        quadro = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
                       id="conteudo_relatorio_descarte")
        self.addPageTemplates(PageTemplate(id="relatorio_descarte", frames=[quadro], onPageEnd=self._pagina))

    def _pagina(self, canvas, _doc):
        largura, altura = self.formato_pagina
        canvas.saveState()
        if self.logo and Path(self.logo).exists():
            canvas.drawImage(self.logo, 10*mm, altura-24*mm, width=13*mm, height=13*mm,
                             preserveAspectRatio=True, mask=None)
        canvas.setFillColor(AZUL)
        canvas.setFont("Helvetica-Bold", 9.5)
        canvas.drawString(27*mm, altura-15*mm, ESTABELECIMENTO_DOCUMENTO)
        canvas.setFillColor(CINZA)
        canvas.setFont("Helvetica", 7.3)
        canvas.drawString(27*mm, altura-20*mm, EMPRESA_EMITENTE)
        canvas.setStrokeColor(AZUL)
        canvas.setLineWidth(1.1)
        canvas.line(10*mm, altura-26*mm, largura-10*mm, altura-26*mm)
        canvas.setFont("Helvetica", 6.8)
        canvas.drawString(10*mm, 6.5*mm, f"Gerado em {self.emissao} - America/Manaus")
        canvas.drawCentredString(largura/2, 6.5*mm,
                                 f"Usuário: {self.usuario} | Documento gerencial - não movimenta estoque")
        canvas.drawRightString(largura-10*mm, 6.5*mm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()


def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("desc_titulo", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=14, leading=17, textColor=AZUL, alignment=TA_CENTER, spaceAfter=1.5*mm),
        "subtitulo": ParagraphStyle("desc_sub", parent=base["Normal"], fontSize=8.2, leading=10,
            textColor=CINZA, alignment=TA_CENTER, spaceAfter=2.5*mm),
        "normal": ParagraphStyle("desc_normal", parent=base["Normal"], fontSize=7.2, leading=8.7, textColor=TINTA),
        "pequeno": ParagraphStyle("desc_pequeno", parent=base["Normal"], fontSize=6.3, leading=7.5, textColor=TINTA),
        "cab": ParagraphStyle("desc_cab", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=6.2, leading=7.2, textColor=colors.white, alignment=TA_CENTER),
        "direita": ParagraphStyle("desc_dir", parent=base["Normal"], fontSize=7, leading=8.5,
            textColor=TINTA, alignment=TA_RIGHT),
        "secao": ParagraphStyle("desc_secao", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10, leading=12, textColor=AZUL, spaceBefore=3*mm, spaceAfter=1.5*mm),
        "alerta": ParagraphStyle("desc_alerta", parent=base["Normal"], fontSize=7, leading=8.5,
            textColor=colors.HexColor("#8a3b12"), spaceAfter=2*mm),
    }


def _tabela(dados, larguras, *, cabecalho=True, total=False):
    tabela = Table(dados, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    comandos = [("GRID", (0,0), (-1,-1), .35, LINHA), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("LEFTPADDING", (0,0), (-1,-1), 3.5), ("RIGHTPADDING", (0,0), (-1,-1), 3.5),
                ("TOPPADDING", (0,0), (-1,-1), 3.5), ("BOTTOMPADDING", (0,0), (-1,-1), 3.5)]
    if cabecalho:
        comandos += [("BACKGROUND", (0,0), (-1,0), AZUL), ("TEXTCOLOR", (0,0), (-1,0), colors.white)]
    if total:
        comandos += [("BACKGROUND", (0,-1), (-1,-1), FUNDO), ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold")]
    tabela.setStyle(TableStyle(comandos))
    return tabela


def _filtros_texto(filtros):
    partes = [
        f"Período: {_data(filtros['data_inicio'])} a {_data(filtros['data_fim'])}",
        f"Data-base: {TIPOS_DATA[filtros['tipo_data']][1]}",
        f"Status: {', '.join(filtros['status'])}",
    ]
    for chave, rotulo in (("numero", "Romaneio"), ("produto", "Produto"),
                          ("apresentacao", "Apresentação"), ("motivo", "Característica"),
                          ("destino", "Destino"), ("motorista", "Motorista"),
                          ("placa", "Placa"), ("usuario_emissor", "Emissor")):
        valor = filtros.get(chave)
        if valor:
            partes.append(f"{rotulo}: {', '.join(valor) if isinstance(valor, list) else valor}")
    return " | ".join(partes)


def _cards(relatorio, estilos, largura):
    resumo = relatorio["resumo"]
    itens = [("Confirmados", resumo["romaneios_confirmados"]),
             ("Destinos", resumo["destinos_distintos"]),
             ("Características", resumo["caracteristicas_distintas"])]
    for campo, rotulo, casas, divisor in (("caixas", "Caixas", 0, 1), ("bandejas", "Bandejas", 0, 1),
                                          ("peso_g", "Peso", 3, 1000), ("galinhas", "Galinhas", 0, 1),
                                          ("pacotes", "Pacotes", 0, 1)):
        if resumo[campo]:
            valor = _numero(resumo[campo]/divisor, casas) + (" kg" if campo == "peso_g" else "")
            itens.append((rotulo, valor))
    colunas = min(6, len(itens)) or 1
    linhas = []
    for inicio in range(0, len(itens), colunas):
        linha = itens[inicio:inicio+colunas] + [("", "")] * (colunas-len(itens[inicio:inicio+colunas]))
        linhas.append([Paragraph(f"<font color='#607078'>{escape(str(a))}</font><br/><b>{escape(str(b))}</b>", estilos["normal"]) for a,b in linha])
    tabela = Table(linhas, colWidths=[largura/colunas]*colunas)
    tabela.setStyle(TableStyle([("BOX",(0,0),(-1,-1),.5,LINHA),("INNERGRID",(0,0),(-1,-1),.35,LINHA),
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#f7f9fa")),("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    return tabela


def _sintetico(relatorio, estilos):
    cab = estilos["cab"]
    pequeno = estilos["pequeno"]
    cabecalho = [_p(x, cab) for x in ("Número / data", "Produto / apresentação", "Característica",
                                      "Destino", "Motorista / placa", "Quantidades", "Status")]
    linhas = []
    for item in relatorio["efetivos"]:
        linhas.append([_p(f"{item['numero']}\n{_data(item['saida_fisica_em'])}", pequeno),
                      _p(f"{item['produto']}\n{item['apresentacao']}", pequeno), _p(item["motivo"], pequeno),
                      _p(item["destino"], pequeno), _p(f"{item['motorista']}\n{item['placa']}", pequeno),
                      _p(_quantidades(item), pequeno), _p(item["status"], pequeno)])
    if not linhas:
        linhas.append([_p("Nenhum romaneio confirmado para os filtros selecionados.", pequeno), "", "", "", "", "", ""])
    # A primeira página já contém filtros e cards. Blocos explícitos evitam que
    # tabelas altas invadam o cabeçalho nas páginas intermediárias do ReportLab.
    elementos = []
    inicio = 0
    capacidade = 8
    while inicio < len(linhas):
        bloco = linhas[inicio:inicio+capacidade]
        elementos.append(_tabela([cabecalho]+bloco, [31*mm,45*mm,38*mm,46*mm,40*mm,52*mm,25*mm]))
        inicio += len(bloco)
        if inicio < len(linhas):
            elementos.extend([PageBreak(), Spacer(1, 25*mm)])
            capacidade = 11
    return elementos


def _consolidado(relatorio, estilos):
    elementos = []
    secoes = defaultdict(list)
    for grupo in relatorio["grupos"]:
        secoes[(grupo["produto"], grupo["apresentacao"], grupo["tipo_unidade"])].append(grupo)
    for (produto, apresentacao, tipo), grupos in secoes.items():
        elementos.append(Paragraph(escape(f"{produto} - {apresentacao}"), estilos["secao"]))
        if tipo == "INTEIRA":
            titulos, campos, larguras = ("Característica", "Romaneios", "Galinhas", "Pacotes"), ("romaneios","galinhas","pacotes"), [78*mm,34*mm,34*mm,34*mm]
        else:
            titulos, campos, larguras = ("Característica", "Romaneios", "Caixas", "Bandejas", "Peso"), ("romaneios","caixas","bandejas","peso_g"), [65*mm,28*mm,28*mm,28*mm,31*mm]
        dados = [[_p(x, estilos["cab"]) for x in titulos]]
        totais = defaultdict(int)
        for grupo in grupos:
            valores = [grupo["motivo"]]
            for campo in campos:
                totais[campo] += grupo[campo]
                valores.append(_numero(grupo[campo]/1000, 3)+" kg" if campo == "peso_g" else _numero(grupo[campo]))
            dados.append([_p(valor, estilos["direita"] if i else estilos["normal"]) for i,valor in enumerate(valores)])
        total = ["Total da seção"] + [(_numero(totais[c]/1000,3)+" kg" if c=="peso_g" else _numero(totais[c])) for c in campos]
        dados.append([_p(valor, estilos["direita"] if i else estilos["normal"]) for i,valor in enumerate(total)])
        elementos += [_tabela(dados, larguras, total=True), Spacer(1, 2*mm)]
    if not secoes:
        elementos.append(Paragraph("Nenhum descarte efetivo para os filtros selecionados.", estilos["normal"]))
    return elementos


def _excecoes(relatorio, estilos, largura_total):
    if not relatorio["excecoes"]:
        return []
    elementos = [Paragraph("Documentos sem efeito no total físico", estilos["secao"]),
                 Paragraph("Rascunhos, cancelados e estornados são informativos e foram excluídos da totalização física oficial.", estilos["alerta"])]
    dados = [[_p(x, estilos["cab"]) for x in ("Número / data", "Status", "Produto / característica", "Quantidade original", "Motivo")]]
    for item in relatorio["excecoes"]:
        dados.append([_p(f"{item['numero']}\n{_data(item['saida_fisica_em'])}", estilos["pequeno"]),
                      _p(item["status"], estilos["pequeno"]),
                      _p(f"{item['produto']}\n{item['motivo']}", estilos["pequeno"]),
                      _p(_quantidades(item), estilos["pequeno"]),
                      _p(item["justificativa_sem_efeito"], estilos["pequeno"])])
    proporcoes = [0.16,0.10,0.25,0.24,0.25]
    elementos.append(_tabela(dados, [largura_total*x for x in proporcoes]))
    return elementos


def gerar_relatorio_consolidado_descarte_pdf(relatorio, *, usuario, emissao=None, logo=None):
    """Gera o documento gerencial sem executar qualquer operação de escrita."""
    filtros = relatorio["filtros"]
    modalidade = filtros["modalidade"]
    instante = emissao or datetime.now(FUSO_MANAUS)
    emissao_texto = instante.strftime("%d/%m/%Y às %H:%M") if isinstance(instante, datetime) else str(instante)
    usuario = _texto(usuario, "Usuário não identificado")
    if logo is None:
        logo = str(Path(__file__).resolve().parents[2] / "static" / "imagens" / "logo.png")
    buffer = BytesIO()
    doc = _Documento(buffer, emissao=emissao_texto, usuario=usuario, logo=logo, modalidade=modalidade)
    estilos = _estilos()
    largura_total = (277 if modalidade == "SINTETICO" else 190) * mm
    historia = [Paragraph("RELATÓRIO CONSOLIDADO DE ROMANEIOS DE DESCARTE", estilos["titulo"]),
                Paragraph(MODALIDADES[modalidade], estilos["subtitulo"]),
                Paragraph(escape(_filtros_texto(filtros)), estilos["pequeno"]), Spacer(1,2*mm),
                _cards(relatorio, estilos, largura_total), Spacer(1,3*mm)]
    if modalidade == "SINTETICO":
        historia += [Paragraph("Descarte líquido efetivo", estilos["secao"])] + _sintetico(relatorio, estilos)
    else:
        historia += _consolidado(relatorio, estilos)
    if relatorio["excecoes"]:
        historia.extend([PageBreak(), Spacer(1, 25*mm)])
    historia += _excecoes(relatorio, estilos, largura_total)
    doc.build(historia)
    return buffer.getvalue()
