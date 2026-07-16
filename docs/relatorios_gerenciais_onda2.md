# Relatorios Gerenciais - Onda 2

Commit base publicado antes da sprint: `7a2ff1752d0b68a302b9741f7ccf84f2395fcf4d`.

## Escopo entregue

A Onda 2 criou a camada gerencial oficial para:

- Indicadores: `/relatorios/gerencial/indicadores`
- Comparativos: `/relatorios/gerencial/comparativos`
- Tendencias: `/relatorios/gerencial/tendencias`
- Exportacao Excel para cada rota.

Esses relatorios consomem apenas services oficiais existentes. A camada gerencial nao grava resultados, nao substitui DRE, Fluxo de Caixa, Producao, Almoxarifado ou Expedicao, e nao cria fonte paralela de verdade.

## Fontes oficiais consumidas

- DRE Gerencial: receita, deducoes, resultado operacional, resultado nao operacional e resultado gerencial.
- Fluxo de Caixa: entradas, saidas e saldo realizado.
- Relatorios Financeiros Oficiais: aportes.
- Relatorios de Producao: OPs, aves, peso produzido, caixas, rendimento, condenacoes, perdas e produtividade por hora-setor.
- Relatorios de Almoxarifado: entradas, consumo e itens com saldo.
- Relatorios de Expedicao: transferencias e estoque da Camara Fria LSM.

## Regras de interpretacao

- Valor oficial zero permanece zero.
- Ausencia de base, fonte indisponivel ou metrica nao sustentada pelo periodo recebe status `Sem dados no periodo`.
- Itens congelados, futuros ou em estruturacao nao sao convertidos em zero.
- Comparativos usam o periodo anterior equivalente ao intervalo filtrado. Quando o filtro cobre meses completos, a comparacao tambem usa meses completos anteriores para manter coerencia com fontes mensais como a DRE.
- Tendencias sao descritivas. Nao ha previsao, meta inventada ou favorabilidade automatica.
- Tendencia exige pelo menos tres pontos validos para indicar direcao; caso contrario retorna `Historico insuficiente`.

## Indicadores ativos

Financeiro:

- Receita Bruta
- Deducoes
- Receita Operacional Liquida
- Despesas Operacionais
- Resultado Operacional
- Resultado Nao Operacional
- Resultado Liquido Gerencial
- Entradas de Caixa
- Saidas de Caixa
- Saldo de Caixa
- Aportes

Producao:

- Quantidade de OPs
- Aves Processadas
- Peso Produzido
- Caixas Produzidas
- Rendimento
- Condenacoes
- Perdas

Almoxarifado:

- Entradas de Almoxarifado
- Consumo de Almoxarifado
- Produtos com Saldo

Expedicao:

- Transferencias
- Caixas Transferidas
- Peso Transferido
- Caixas na Camara Fria

## Indicadores com ressalva

- Produtividade por Hora-Setor: disponivel com status `Disponivel - requer evolucao`; nao representa percentual de eficiencia, meta, capacidade ou OEE.

## Indicadores bloqueados

- CMV: `Congelado`.
- OEE: `Futuro`.

## Catalogo

Os itens `gerencial-indicadores`, `gerencial-comparativos` e `gerencial-tendencias` foram promovidos para Onda 2 com tela e Excel.

O item `gerencial-dashboard-executivo` permanece catalogado para decisao futura, sem endpoint oficial. A rota `/dashboard` atual nao foi alterada nem renomeada.

## Nao implementado

- CMV gerencial.
- Margem bruta definitiva.
- OEE.
- Giro/FIFO.
- Vendas.
- Forecast.
- Metas inventadas.
- Rastreabilidade completa.
- Alteracoes em DRE, Fluxo de Caixa, Central de Movimentacoes, Producao, Almoxarifado ou Expedicao.
