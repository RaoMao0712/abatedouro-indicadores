from datetime import datetime


def calcular_horas_programadas(hora_inicio, hora_fim):
    inicio = datetime.strptime(hora_inicio, "%H:%M")
    fim = datetime.strptime(hora_fim, "%H:%M")
    diferenca = fim - inicio
    horas = diferenca.total_seconds() / 3600

    if horas < 0:
        horas += 24

    return round(horas, 2)


def calcular_produtividade(quantidade, colaboradores, horas_programadas, horas_paradas):
    horas_uteis = horas_programadas - horas_paradas

    if horas_uteis <= 0:
        return 0

    homem_hora = colaboradores * horas_uteis

    if homem_hora <= 0:
        return 0

    produtividade = quantidade / homem_hora
    return round(produtividade, 2)


def setores_padrao():
    return [
        "Recepção e Pendura",
        "Escalda e Depenagem",
        "Evisceração",
        "Corte",
        "Embalagem",
        "Expedição"
    ]


def normalizar_chave_setor(setor):
    return (
        setor
        .replace(" ", "_")
        .replace("/", "_")
        .replace("ç", "c")
        .replace("ã", "a")
        .replace("é", "e")
    )
