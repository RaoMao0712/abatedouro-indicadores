"""Definições fixas dos formulários PLM digitalizados pelo SGI."""


FORMULARIOS_PLM = {
    "plm01_instalacoes": {
        "codigo": "PLM 01",
        "nome": "Instalações e Equipamentos em Geral",
        "vinculos": ["Ambiente", "Estrutura", "Equipamento"],
        "itens": [
            ("condicao", "Condição verificada", "resultado"),
            ("atividade", "Descrição da atividade", "texto"),
            ("manutencao", "Necessidade de manutenção", "resultado"),
            ("higienizacao", "Higienização após reparo", "resultado_na"),
            ("produto", "Condições do produto", "resultado_na"),
        ],
    },
    "plm01_balancas": {
        "codigo": "PLM 01",
        "nome": "Balanças, Manutenção e Calibração",
        "vinculos": ["Equipamento"],
        "itens": [
            ("condicao", "Condição da balança", "resultado"),
            ("manutencao", "Manutenção", "resultado"),
            ("calibracao", "Calibração", "resultado"),
            ("descricao", "Descrição", "texto"),
            ("produto", "Condições do produto", "resultado_na"),
        ],
    },
    "plm02_sanitarios": {
        "codigo": "PLM 02",
        "nome": "Banheiros, Vestiários e Barreira Sanitária",
        "vinculos": ["Estrutura"],
        "itens": [
            ("limpeza", "Limpeza", "resultado"),
            ("lava_botas", "Lava-botas", "resultado_na"),
            ("lavatorio", "Lavatório", "resultado_na"),
            ("sabao", "Sabão líquido", "resultado_na_reposicao"),
            ("sanitizante", "Sanitizante", "resultado_na_reposicao"),
            ("papel_toalha", "Papel toalha", "resultado_na_reposicao"),
            ("papel_higienico", "Papel higiênico", "resultado_na_reposicao"),
            ("lixeira", "Lixeira", "resultado_na"),
            ("organizacao", "Organização", "resultado_na"),
            ("banco", "Banco", "resultado_na"),
            ("espelho", "Espelho", "resultado_na"),
            ("armarios", "Armários", "resultado_na"),
            ("manutencao", "Necessidade de manutenção", "resultado_na"),
            ("descricao", "Descrição", "texto"),
        ],
    },
    "plm03_iluminacao": {
        "codigo": "PLM 03",
        "nome": "Controle de Iluminação",
        "vinculos": ["Ambiente"],
        "itens": [("iluminancia", "Iluminância medida a 0,75 m do chão", "lux")],
    },
    "plm04_ventilacao": {
        "codigo": "PLM 04",
        "nome": "Controle de Ventilação",
        "vinculos": ["Ambiente"],
        "itens": [
            ("tela", "Tela", "resultado_na"),
            ("exaustor", "Exaustor", "resultado_na"),
            ("ar_condicionado", "Ar-condicionado", "resultado_na"),
            ("ventiladores", "Ventiladores", "resultado_na"),
        ],
    },
    "plm05_condensacao": {
        "codigo": "PLM 05",
        "nome": "Controle de Condensação",
        "vinculos": ["Ambiente"],
        "itens": [
            ("condensacao", "Ausência de condensação", "resultado"),
            ("descricao", "Descrição do problema", "texto"),
            ("manutencao", "Necessidade de manutenção", "resultado"),
        ],
    },
}


LIMITES_LUX = {
    "Camara fria e estocagem": 110,
    "Producao e recepcao": 220,
    "Inspecao oficial e seguranca critica": 540,
}


CRITICIDADES = ["NORMAL", "ALTA", "CRITICA"]
RESULTADOS = ["C", "NC", "NA"]
