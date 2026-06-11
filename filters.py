def formatar_numero_br(valor, casas_decimais=2):
    try:
        numero = float(valor or 0)
        return f"{numero:,.{casas_decimais}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"{0:,.{casas_decimais}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_moeda_br(valor):
    try:
        numero = float(valor or 0)
        return "R$ " + f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def br_numero(valor):
    return formatar_numero_br(valor, 2)


def br_moeda(valor):
    return formatar_moeda_br(valor)


def br_percentual(valor):
    return formatar_numero_br(valor, 2) + "%"


def registrar_filtros_jinja(app):
    app.add_template_filter(br_numero, "br_numero")
    app.add_template_filter(br_moeda, "br_moeda")
    app.add_template_filter(br_percentual, "br_percentual")
