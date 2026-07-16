# Relatorio de Eficiencia da Producao - Onda 2

## Decisao tecnica

O PRUMO possui base oficial suficiente para publicar um relatorio operacional de produtividade horaria, mas ainda nao possui denominador oficial para calcular percentual de eficiencia, aderencia a meta ou OEE.

Classificacao da sprint: base parcial, com entrega funcional em tela e Excel.

## Dados auditados

### Ordens de Producao

Tabela: `ordens_producao`

Campos oficiais encontrados:

- OP.
- data.
- fornecedor.
- SKU.
- quantidade de aves.
- mortes antes da pendura.
- peso vivo.
- peso medio.
- status.

Campos nao encontrados:

- meta oficial de eficiencia por OP.
- capacidade nominal por linha/processo.
- quantidade planejada.
- peso planejado.
- linha produtiva.
- calendario/jornada oficial por OP.
- tempo padrao por SKU.

### Producao realizada

Tabela: `apontamentos_producao`

Campos oficiais encontrados:

- OP.
- data.
- setor.
- quantidade.
- unidade.
- observacoes.

Uso aprovado nesta sprint:

- peso produzido em kg.
- unidades produzidas quando registradas.

### Produto Acabado

Tabelas: `pa_caixas`, `pa_caixa_composicao`

Uso aprovado nesta sprint:

- caixas PA por OP.
- peso liquido PA como base complementar quando nao houver kg apontado em `apontamentos_producao`.

### Tempos por setor

Tabela: `apontamentos_tempos_setor`

Campos oficiais encontrados:

- OP.
- data.
- setor.
- hora inicial.
- hora final.

Uso aprovado nesta sprint:

- calculo de horas registradas por setor.
- soma por OP como hora-setor registrada.

### Paradas

Tabela: `apontamentos_paradas`

Campos oficiais encontrados:

- OP.
- data.
- setor.
- motivo.
- hora inicial.
- hora final.
- horas paradas.

Uso aprovado nesta sprint:

- abatimento das horas paradas por OP, data e setor.

## O que nao foi considerado eficiencia

### Rendimento

Rendimento continua sendo kg produzido dividido por peso vivo. Ele mede aproveitamento industrial de materia-prima e nao mede eficiencia operacional.

### Viabilidade

Viabilidade de aves nao foi usada como eficiencia. Ela mede aves aproveitadas em relacao a aves recebidas e nao substitui meta operacional, tempo padrao ou capacidade.

### OEE

OEE nao foi implementado. O sistema ainda nao possui motor oficial de disponibilidade, performance e qualidade com meta/capacidade por equipamento ou linha.

## Indicador publicado

Nome operacional: produtividade horaria oficial.

Formula:

```text
horas registradas = soma(hora_fim - hora_inicio) por OP/setor
horas produtivas = horas registradas - horas paradas
kg por hora-setor = peso produzido / horas produtivas
caixas por hora-setor = caixas PA / horas produtivas
```

Observacao: o denominador e hora-setor registrada. Ele nao representa capacidade de linha nem tempo padrao.

## Limitacoes oficiais exibidas no relatorio

- Base parcial: o PRUMO possui producao, tempos e paradas oficiais, mas nao possui meta/capacidade oficial por OP.
- O relatorio mede produtividade horaria por hora-setor registrada.
- O relatorio nao calcula percentual de eficiencia, aderencia a meta ou OEE.
- Rendimento industrial permanece no relatorio Rendimento e nao foi reutilizado como eficiencia.

## Arquivos alterados

- `modules/relatorios/producao.py`
- `modules/relatorios/catalogo.py`
- `modules/relatorios/routes.py`
- `templates/relatorio_eficiencia_producao.html`
- `docs/relatorio_eficiencia_producao_onda2.md`

## Catalogo

Relatorio: Producao / Eficiencia

Status: Disponivel - requer evolucao

Motivo: ha base oficial para produtividade horaria, mas nao ha meta/capacidade oficial para percentual de eficiencia.

## Proposta estrutural futura minima

Para transformar produtividade em eficiencia percentual oficial, o PRUMO precisara aprovar ao menos um denominador operacional:

- meta de kg/hora por SKU/processo;
- capacidade nominal por linha/processo;
- tempo padrao por SKU;
- calendario/jornada oficial por OP;
- regra de alocacao quando setores trabalham em paralelo.

Sem essa aprovacao, qualquer percentual de eficiencia seria inferido e nao oficial.
