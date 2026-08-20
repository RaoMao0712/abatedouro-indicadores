"""PDF oficial da posição consolidada do estoque da Câmara."""

from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from config import EMPRESA_EMITENTE

from .consolidado_estoque import SITUACOES_BLOQUEADAS, SITUACOES_CONFORMES
from .relatorio_entregas import AZUL, CINZA, FUNDO, LINHA, TINTA, _Documento


ROTULOS_UNIDADES = {
    "caixas": "Caixas",
    "bandejas": "Bandejas",
    "peso_kg": "Peso em kg",
    "galinhas": "Galinhas",
    "pacotes": "Pacotes",
}


def _numero(valor, casas=0):
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _valor(unidade, valor):
    return _numero(valor, 3 if unidade == "peso_kg" else 0)


def _p(texto, estilo):
    return Paragraph(escape(str(texto or "-")), estilo)


def _possui_saldo(grupo, situacoes):
    return any(
        grupo["situacoes"][situacao]["quantidades"].get(unidade, 0) != 0
        for situacao in situacoes for unidade in grupo["unidades"]
    )


def _tabela_grupo(grupo, situacoes, total_chave, estilos):
    cabecalho = ["Situação"] + [ROTULOS_UNIDADES[u] for u in grupo["unidades"]] + ["Origem"]
    dados = [[_p(valor, estilos["cab"]) for valor in cabecalho]]
    for situacao in situacoes:
        item = grupo["situacoes"][situacao]
        dados.append([
            _p(item["rotulo"], estilos["normal"]),
            *[
                Paragraph(_valor(unidade, item["quantidades"][unidade]), estilos["direita"])
                for unidade in grupo["unidades"]
            ],
            _p("; ".join(item["origens"]) or "-", estilos["pequeno"]),
        ])
    total_rotulo = "Total físico conforme" if total_chave == "total_conforme" else "Total bloqueado"
    dados.append([
        Paragraph(f"<b>{escape(total_rotulo)}</b>", estilos["normal"]),
        *[
            Paragraph(f"<b>{_valor(unidade, grupo[total_chave][unidade])}</b>", estilos["direita"])
            for unidade in grupo["unidades"]
        ],
        _p("-", estilos["pequeno"]),
    ])
    largura_numerica = 32 * mm
    larguras = [52 * mm] + [largura_numerica] * len(grupo["unidades"])
    larguras.append(277 * mm - sum(larguras))
    tabela = Table(dados, colWidths=larguras, repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .35, LINHA),
        ("BACKGROUND", (0, -1), (-1, -1), FUNDO),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    titulo = f"{grupo['produto']} — {grupo['apresentacao']}"
    return KeepTogether([
        Paragraph(escape(titulo), estilos["grupo"]),
        tabela,
        Spacer(1, 2.5 * mm),
    ])


def gerar_relatorio_estoque_pdf(consolidado, *, usuario, logo=None):
    """Renderiza exclusivamente os números já calculados pelo serviço central."""
    incluir_nc = consolidado["incluir_nao_conforme"]
    emissao = consolidado["gerado_em_formatado"]
    logo = logo or str(Path(__file__).resolve().parents[2] / "static" / "imagens" / "logo.png")
    buffer = BytesIO()
    doc = _Documento(
        buffer, emissao, usuario or "Usuário não identificado", logo,
        "Posição Consolidada do Estoque da Câmara",
    )
    base = getSampleStyleSheet()
    estilos = {
        "titulo": ParagraphStyle(
            "estoque_titulo", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=15, leading=18, textColor=AZUL, alignment=TA_CENTER,
            spaceAfter=2 * mm,
        ),
        "subtitulo": ParagraphStyle(
            "estoque_subtitulo", parent=base["Normal"], fontSize=8.5,
            leading=11, textColor=CINZA, alignment=TA_CENTER, spaceAfter=3 * mm,
        ),
        "normal": ParagraphStyle(
            "estoque_normal", parent=base["Normal"], fontSize=8,
            leading=10, textColor=TINTA,
        ),
        "pequeno": ParagraphStyle(
            "estoque_pequeno", parent=base["Normal"], fontSize=7,
            leading=8.5, textColor=TINTA,
        ),
        "direita": ParagraphStyle(
            "estoque_direita", parent=base["Normal"], fontSize=8,
            leading=10, textColor=TINTA, alignment=TA_RIGHT,
        ),
        "cab": ParagraphStyle(
            "estoque_cab", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=7.5, leading=9, textColor=colors.white, alignment=TA_CENTER,
        ),
        "grupo": ParagraphStyle(
            "estoque_grupo", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9.5, leading=12, textColor=AZUL, spaceBefore=2 * mm,
            spaceAfter=1 * mm,
        ),
        "secao": ParagraphStyle(
            "estoque_secao", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, textColor=AZUL, spaceBefore=3 * mm,
            spaceAfter=1.5 * mm,
        ),
    }
    historia = [
        Paragraph("POSIÇÃO CONSOLIDADA DO ESTOQUE DA CÂMARA", estilos["titulo"]),
        Paragraph("Posição física e disponibilidade atual da Câmara", estilos["subtitulo"]),
    ]
    metadados = [
        ["Empresa", EMPRESA_EMITENTE, "Data e hora da posição", emissao],
        ["Fuso horário", consolidado["fuso_horario"], "Emitido por", usuario or "Usuário não identificado"],
        ["Estoque não conforme incluído", "Sim" if incluir_nc else "Não", "Escopo", "Posição atual consolidada"],
    ]
    meta = Table([
        [Paragraph(f"<b>{escape(a)}</b>", estilos["pequeno"]), _p(b, estilos["normal"]),
         Paragraph(f"<b>{escape(c)}</b>", estilos["pequeno"]), _p(d, estilos["normal"])]
        for a, b, c, d in metadados
    ], colWidths=[38 * mm, 100 * mm, 45 * mm, 94 * mm])
    meta.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, LINHA),
        ("BACKGROUND", (0, 0), (0, -1), FUNDO),
        ("BACKGROUND", (2, 0), (2, -1), FUNDO),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    historia += [meta, Spacer(1, 3 * mm), Paragraph("Estoque conforme", estilos["secao"])]
    for grupo in consolidado["grupos"]:
        historia.append(_tabela_grupo(grupo, SITUACOES_CONFORMES, "total_conforme", estilos))

    if incluir_nc:
        historia.append(Paragraph("Estoque não conforme e bloqueado", estilos["secao"]))
        grupos_bloqueados = [
            grupo for grupo in consolidado["grupos"]
            if _possui_saldo(grupo, SITUACOES_BLOQUEADAS)
        ]
        if grupos_bloqueados:
            for grupo in grupos_bloqueados:
                historia.append(_tabela_grupo(
                    grupo, SITUACOES_BLOQUEADAS, "total_bloqueado", estilos))
        else:
            historia.append(Paragraph("Nenhum saldo não conforme ou bloqueado na posição.", estilos["normal"]))

    if consolidado["alertas_tecnicos"]:
        historia += [Paragraph("Observações técnicas", estilos["secao"])]
        for alerta in consolidado["alertas_tecnicos"]:
            historia.append(Paragraph(f"• {escape(alerta)}", estilos["pequeno"]))

    doc.build(historia)
    return buffer.getvalue()
