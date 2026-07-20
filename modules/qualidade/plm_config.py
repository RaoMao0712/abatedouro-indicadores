"""Definicoes fixas dos formularios PLM digitalizados pelo SGI."""


FORMULARIOS_PLM = {
    "plm01_instalacoes": {
        "codigo": "PLM 01",
        "nome": "Instalacoes e Equipamentos em Geral",
        "vinculos": ["Ambiente", "Estrutura", "Equipamento"],
        "itens": [
            ("condicao", "Condicao verificada", "resultado"),
            ("atividade", "Descricao da atividade", "texto"),
            ("manutencao", "Necessidade de manutencao", "resultado"),
            ("higienizacao", "Higienizacao apos reparo", "resultado_na"),
            ("produto", "Condicoes do produto", "resultado_na"),
        ],
    },
    "plm01_balancas": {
        "codigo": "PLM 01",
        "nome": "Balancas, Manutencao e Calibracao",
        "vinculos": ["Equipamento"],
        "itens": [
            ("condicao", "Condicao da balanca", "resultado"),
            ("manutencao", "Manutencao", "resultado"),
            ("calibracao", "Calibracao", "resultado"),
            ("descricao", "Descricao", "texto"),
            ("produto", "Condicoes do produto", "resultado_na"),
        ],
    },
    "plm02_sanitarios": {
        "codigo": "PLM 02",
        "nome": "Banheiros, Vestiarios e Barreira Sanitaria",
        "vinculos": ["Estrutura"],
        "itens": [
            ("limpeza", "Limpeza", "resultado"),
            ("lava_botas", "Lava-botas", "resultado_na"),
            ("lavatorio", "Lavatorio", "resultado_na"),
            ("sabao", "Sabao liquido", "resultado_na_reposicao"),
            ("sanitizante", "Sanitizante", "resultado_na_reposicao"),
            ("papel_toalha", "Papel toalha", "resultado_na_reposicao"),
            ("papel_higienico", "Papel higienico", "resultado_na_reposicao"),
            ("lixeira", "Lixeira", "resultado_na"),
            ("organizacao", "Organizacao", "resultado_na"),
            ("banco", "Banco", "resultado_na"),
            ("espelho", "Espelho", "resultado_na"),
            ("armarios", "Armarios", "resultado_na"),
            ("manutencao", "Necessidade de manutencao", "resultado_na"),
            ("descricao", "Descricao", "texto"),
        ],
    },
    "plm03_iluminacao": {
        "codigo": "PLM 03",
        "nome": "Controle de Iluminacao",
        "vinculos": ["Ambiente"],
        "itens": [("iluminancia", "Iluminancia medida a 0,75 m do chao", "lux")],
    },
    "plm04_ventilacao": {
        "codigo": "PLM 04",
        "nome": "Controle de Ventilacao",
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
        "nome": "Controle de Condensacao",
        "vinculos": ["Ambiente"],
        "itens": [
            ("condensacao", "Ausencia de condensacao", "resultado"),
            ("descricao", "Descricao do problema", "texto"),
            ("manutencao", "Necessidade de manutencao", "resultado"),
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
