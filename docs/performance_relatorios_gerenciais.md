# Performance dos Relatorios Gerenciais

Commit inicial da sprint corretiva: `9c34a19bb9a5d3ca2bae6deb70f8cbf5a43ddae8`.

## Baseline

Os arquivos locais nao rastreados `entregas/`, `tools/` e `reset_financeiro_producao_20260709_133850.zip` foram preservados fora do commit.

### Render antes da correcao

Na validacao publicada do commit `9c34a19`, as rotas responderam HTTP 200, mas com tempos operacionais inadequados:

| Rota | Dominio | Periodo | Cold start | Mediana quente | Pior tempo | Registros | Observacao |
|---|---|---|---:|---:|---:|---:|---|
| indicadores | Todos | padrao | 73,43s | nao medido | 73,43s | 28 | visao completa carregava todos os services analiticos |
| comparativos | Todos | padrao | 72,78s | nao medido | 72,78s | 26 | periodo atual e anterior repetiam chamadas analiticas |
| tendencias | Todos | padrao | 36,73s | nao medido | 36,73s | 26 | serie chamava services por periodo |
| indicadores/exportar | Todos | padrao | 36,26s | nao medido | 36,26s | 28 | exportacao recalculava o contexto |
| comparativos/exportar | Todos | padrao | 78,11s | nao medido | 78,11s | 26 | pior caso observado |
| tendencias/exportar | Todos | padrao | 36,45s | nao medido | 36,45s | 26 | exportacao recalculava a serie |

Por dominio, ainda no Render antes da correcao:

| Rota | Dominio | Periodo | Cold start | Mediana quente | Pior tempo | Registros | Observacao |
|---|---|---|---:|---:|---:|---:|---|
| indicadores | Financeiro | padrao | 11,67s | nao medido | 11,67s | 11 | DRE, Fluxo e Aportes |
| indicadores | Producao | padrao | 17,37s | nao medido | 17,37s | 9 | maior gargalo por dominio |
| indicadores | Almoxarifado | padrao | 5,23s | nao medido | 5,23s | 4 | relatorios analiticos para totais |
| indicadores | Expedicao | padrao | 4,63s | nao medido | 4,63s | 4 | relatorios analiticos para totais |
| comparativos | Financeiro | padrao | 22,38s | nao medido | 22,38s | 11 | atual + anterior |
| comparativos | Producao | padrao | 34,28s | nao medido | 34,28s | 8 | atual + anterior |
| comparativos | Almoxarifado | padrao | 10,25s | nao medido | 10,25s | 3 | atual + anterior |
| comparativos | Expedicao | padrao | 8,17s | nao medido | 8,17s | 4 | atual + anterior |

Uma medicao completa adicional do Render foi interrompida apos exceder 30 minutos de execucao acumulada do script local. A interrupcao foi tratada como evidencia adicional de que o baseline publicado nao era operacional para medicao sequencial completa.

### Local antes da correcao

Banco temporario vazio, aplicacao aquecida:

| Rota | Dominio | Periodo | Cold start | Mediana quente | Pior tempo | Registros | Observacao |
|---|---|---|---:|---:|---:|---:|---|
| indicadores | Todos | padrao | 0,159s | 0,118s | 0,159s | 28 | banco vazio nao reproduz gargalo de volume |
| comparativos | Todos | padrao | 0,173s | 0,219s | 0,246s | 26 | banco vazio |
| tendencias | Todos | amplo | 0,731s | 0,587s | 0,774s | 26 | 7 periodos mensais |

## Mapa de chamadas antes

Rota Gerencial -> Registro de Indicadores -> resolver por indicador -> service oficial analitico -> detalhes/agrupamentos/resumo -> valor do KPI.

Gargalos comprovados:

- Producao carregava relatorios completos por OP, perdas, condenacoes, rendimento e eficiencia para extrair poucos totais.
- Almoxarifado carregava detalhes de movimentacoes e saldos para extrair `Quantidade` e `Itens com saldo`.
- Expedicao carregava listas de transferencias e estoque de Camara Fria para extrair contagens e peso.
- Aportes carregava o relatorio financeiro de caixa para extrair `Total previsto`.
- Comparativos duplicavam o custo ao montar periodo atual e anterior.
- Tendencias multiplicavam o custo por periodo da serie.
- Exportacoes montavam o mesmo contexto da tela antes de gerar o workbook.

Nao foram identificadas chamadas HTTP internas, DDL em GET, backfill em GET ou alteracao de permissao.

## Correcao aplicada

Foram criados resumos gerenciais oficiais nos dominios de origem:

- `modules/relatorios/financeiro.py`: `montar_resumo_gerencial_financeiro`
- `modules/relatorios/producao.py`: `montar_resumo_gerencial_producao`
- `modules/relatorios/almoxarifado.py`: `montar_resumo_gerencial_almoxarifado`
- `modules/relatorios/expedicao.py`: `montar_resumo_gerencial_expedicao`
- `modules/fluxo_caixa/services.py`: `montar_resumo_gerencial_fluxo_caixa`
- `modules/dre/services.py`: `buscar_resumo_dre_gerencial`

A camada gerencial passou a consumir esses resumos para os KPIs, preservando:

- mesmas tabelas oficiais;
- mesmos filtros de periodo;
- mesmas regras de status sem dados;
- mesmos campos de origem;
- mesmos IDs, unidades e status dos indicadores;
- mesma exportacao Excel.

Nao foi criado cache persistente, indice novo, DDL em GET, job externo ou Dashboard Executivo.

## Matriz de equivalencia

Fixture local com financeiro, producao, almoxarifado e expedicao:

| Indicador | Antes | Depois | Diferenca | Status |
|---|---:|---:|---:|---|
| Aportes | 1000,0000 | 1000,0000 | 0 | OK |
| OPs | 1,0000 | 1,0000 | 0 | OK |
| Aves Processadas | 100,0000 | 100,0000 | 0 | OK |
| Peso Produzido | 120,0000 | 120,0000 | 0 | OK |
| Caixas Produzidas | 1,0000 | 1,0000 | 0 | OK |
| Rendimento | 48,0000 | 48,0000 | 0 | OK |
| Condenacoes | 3,0000 | 3,0000 | 0 | OK |
| Perdas | 6,0000 | 6,0000 | 0 | OK |
| Produtividade por Hora-Setor | 80,0000 | 80,0000 | 0 | OK |
| Entradas Almoxarifado | 100,0000 | 100,0000 | 0 | OK |
| Consumo Almoxarifado | 20,0000 | 20,0000 | 0 | OK |
| Produtos com Saldo | 1,0000 | 1,0000 | 0 | OK |
| Transferencias | 1,0000 | 1,0000 | 0 | OK |
| Caixas na Camara Fria | 1,0000 | 1,0000 | 0 | OK |

## Local apos correcao

Banco temporario vazio:

| Rota | Dominio | Periodo | Cold start | Mediana quente | Pior tempo | Registros | Observacao |
|---|---|---|---:|---:|---:|---:|---|
| indicadores | Todos | padrao | 0,1032s | 0,0295s | 0,1032s | 28 | OK |
| comparativos | Todos | padrao | 0,0642s | 0,0587s | 0,0642s | 26 | OK |
| tendencias | Todos | padrao | 0,0311s | 0,0319s | 0,0332s | 26 | OK |
| indicadores/exportar | Todos | padrao | 0,0740s | 0,0532s | 0,0740s | 28 | XLSX OK |
| comparativos/exportar | Todos | padrao | 0,0808s | 0,0743s | 0,0808s | 26 | XLSX OK |
| tendencias/exportar | Todos | padrao | 0,0668s | 0,0546s | 0,0668s | 26 | XLSX OK |

## Limitacoes

- DRE e Fluxo de Caixa continuam usando seus services oficiais existentes.
- Tendencias ainda montam a serie por periodos, mas cada ponto passou a usar agregados oficiais em vez de relatorios analiticos completos para Producao, Almoxarifado, Expedicao e Aportes.
- Fluxo de Caixa gerencial passou a usar agregacao direta oficial para entradas, saidas e saldo realizado, sem carregar a linha do tempo completa.
- DRE gerencial passou a expor um resumo oficial para os campos consumidos pelos indicadores, preservando o CMV interno usado no Resultado Operacional sem montar graficos e listas da tela da DRE.

## Render apos correcao

Commit final validado: `f89c2726afa62e82eaceaf830449115c7f29aa4d`.

| Rota | Dominio | Periodo | Cold start | Mediana quente | Pior tempo | Registros | Observacao |
|---|---|---|---:|---:|---:|---:|---|
| indicadores | Todos | padrao | 10,62s | 10,44s | 11,06s | 28 | melhora material; ainda acima da meta de 5s/10s |
| comparativos | Todos | padrao | 17,63s | 18,39s | 18,98s | 26 | melhora material; meta nao atingida |
| tendencias | Todos | padrao | 9,38s | 9,32s | 10,33s | 26 | dentro/limite da meta operacional de 10s, com pior ligeiramente acima |
| indicadores | Financeiro | padrao | 3,31s | 3,52s | 3,65s | 11 | perto da meta por dominio |
| comparativos | Financeiro | padrao | 4,94s | 5,05s | 5,74s | 11 | ligeiramente acima da meta por dominio |
| indicadores/exportar | Todos | padrao | 9,22s | 9,22s | 9,22s | 28 | meta de exportacao Todos atingida |
| comparativos/exportar | Todos | padrao | 18,33s | 18,33s | 18,33s | 26 | melhora material; meta de 15s nao atingida |
| tendencias/exportar | Todos | padrao | 9,22s | 9,22s | 9,22s | 26 | meta de exportacao Todos atingida |

Regressoes validadas no Render:

- `/dashboard`: 200.
- `/dre-gerencial?competencia=2026-07`: 200.
- `/fluxo-caixa`: 200.
- `/relatorios/financeiro/entradas-caixa`: 200.
- `/relatorios/producao/producao-por-op`: 200.
- `/relatorios/producao/eficiencia`: 200.
- `/relatorios/almoxarifado/estoque-atual`: 200.
- `/relatorios/expedicao/transferencias`: 200.
- `/movimentacoes/importar`: 200.
- `/relatorios/almoxarifado/giro`: 404, preservado como bloqueado.
- `/relatorios/almoxarifado/fifo`: 404, preservado como bloqueado.

Metas nao atingidas:

- Visao `Todos` de Indicadores ficou em 10,44s de mediana quente, acima da meta preferencial de 5s e pouco acima do limite comum de 10s.
- Visao `Todos` de Comparativos ficou em 18,39s de mediana quente.
- Exportacao `Todos` de Comparativos ficou em 18,33s.
- Tendencia ampla de Producao, de janeiro a julho de 2026, permaneceu pesada porque ainda executa serie periodo a periodo para preservar equivalencia com os services oficiais.
- A validacao final de metas deve ser feita no Render apos deploy, pois SQLite local vazio nao representa o volume de producao.

## Rodada 2 - Comparativos e Tendencias de Producao

Commit inicial da Rodada 2: `8d043366eebb2f08b900037ee0f314e55ec977ab`.

Pre-requisitos conferidos:

- Branch `main` sincronizada com `origin/main`.
- HEAD inicial igual ao commit publicado `8d043366eebb2f08b900037ee0f314e55ec977ab`.
- Arquivos locais nao rastreados preservados fora do commit: `entregas/`, `tools/` e `reset_financeiro_producao_20260709_133850.zip`.
- Sem cache persistente, DDL, backfill ou alteracao de regras de negocio.

### Baseline especifico da Rodada 2

A medicao sequencial completa no Render foi iniciada contra o commit `8d043366`, com login autenticado e uma rota por vez. A bateria excedeu 30 minutos de execucao local antes de devolver saida ao terminal, reforcando que o conjunto completo de Comparativos por dominio, exportacoes e Tendencias amplas de Producao ainda era pesado demais para validacao operacional longa.

Como referencia publicada da sprint anterior, os tempos finais do Render antes da Rodada 2 eram:

| Rota | Dominio | Periodo | Mediana quente | Pior tempo | Observacao |
|---|---|---|---:|---:|---|
| comparativos | Todos | padrao | 18,39s | 18,98s | meta nao atingida |
| comparativos/exportar | Todos | padrao | 18,33s | 18,33s | meta nao atingida |
| tendencias | Todos | padrao | 9,32s | 10,33s | no limite operacional |
| indicadores | Todos | padrao | 10,44s | 11,06s | nao deveria regredir |

### Mapa de chamadas ajustado

Antes da Rodada 2, Comparativos chamava `resolver_indicador` para o periodo atual e novamente para o periodo anterior. A cache por request evitava duplicidade entre indicadores do mesmo slug/periodo, mas Producao ainda reconstruia os resumos por slug em chamadas separadas.

Tendencias de Producao chamava o service completo de cada indicador para cada ponto da serie. Em periodos amplos, isso multiplicava OPs, perdas, rendimento e eficiencia pelo numero de dias, semanas ou meses.

### Correcao aplicada na Rodada 2

Foi criada uma API gerencial multiperiodo em Producao:

- `montar_resumos_gerenciais_producao_periodos`
- `montar_resumos_ops_gerenciais_periodos`
- `montar_resumos_perdas_gerenciais_periodos`
- `montar_resumos_eficiencia_gerenciais_periodos`

A camada gerencial passou a:

- carregar os periodos `atual` e `anterior` de Producao uma unica vez por slug em Comparativos;
- carregar a serie completa de Producao uma unica vez por slug em Tendencias;
- manter o caminho antigo como fallback para dominios nao alterados e casos nao suportados;
- preservar a mesma montagem de variacao, comparabilidade, direcao de tendencia, status sem dados e exportacao XLSX.

### Matriz de equivalencia local da Rodada 2

Validacao local comparou o caminho antigo periodo a periodo contra o caminho novo em lote:

| Escopo | Indicadores | Periodos | Resultado |
|---|---:|---:|---|
| Tendencia Producao mensal 2026-01 a 2026-07 | 8 | 7 | 0 diferencas |
| Comparativos Producao 2026-07 x 2026-06 | 8 | 2 | 0 diferencas |

Campos comparados:

- serie;
- direcao de tendencia;
- cobertura;
- valor atual;
- valor anterior;
- variacao absoluta;
- variacao percentual;
- comparabilidade;
- leitura;
- status dos dados.

### Local apos Rodada 2

Banco local SQLite:

| Rota | Dominio | Periodo | Cold start | Mediana quente | Pior tempo | Registros |
|---|---|---|---:|---:|---:|---:|
| comparativos | Todos | 2026-07 | 0,0492s | 0,0317s | 0,0492s | 27 |
| comparativos | Financeiro | 2026-07 | 0,0097s | 0,0096s | 0,0097s | 12 |
| comparativos | Producao | 2026-07 | 0,0126s | 0,0137s | 0,0155s | 9 |
| comparativos | Almoxarifado | 2026-07 | 0,0090s | 0,0081s | 0,0090s | 4 |
| comparativos | Expedicao | 2026-07 | 0,0088s | 0,0058s | 0,0088s | 5 |
| comparativos/exportar | Todos | 2026-07 | 0,0815s | 0,0521s | 0,0815s | XLSX |
| tendencias | Producao dia amplo | 2026-07 | 0,0163s | 0,0153s | 0,0163s | 9 |
| tendencias | Producao semana amplo | 2026-01 a 2026-07 | 0,0156s | 0,0172s | 0,0184s | 9 |
| tendencias | Producao mes amplo | 2026-01 a 2026-07 | 0,0128s | 0,0168s | 0,0169s | 9 |
| tendencias | Producao dia curto | 2026-07-01 a 2026-07-07 | 0,0142s | 0,0123s | 0,0142s | 9 |
| indicadores | Todos | 2026-07 | 0,0220s | 0,0206s | 0,0220s | 29 |
| tendencias | Todos | 2026-07 | 0,0208s | 0,0205s | 0,0208s | 27 |

### Limites restantes

- A otimizacao da Rodada 2 foi restrita a Producao, que era o gargalo conceitual remanescente em Comparativos e Tendencias amplas.
- Financeiro, Almoxarifado e Expedicao continuam usando os resumos gerenciais da Rodada 1.
- A validacao final de meta continua dependente do Render/PostgreSQL, porque o SQLite local nao representa o volume real.

### Render apos Rodada 2

Commit de merge publicado: `3527c43`.

Validacao autenticada no Render, executada uma rota por vez:

| Rota | Dominio | Periodo | Cold start | Mediana quente | Pior tempo | Registros | Resultado |
|---|---|---|---:|---:|---:|---:|---|
| comparativos | Todos | 2026-07 | 14,068s | 13,916s | 14,336s | 27 | melhorou, mas meta de 10s nao atingida |
| comparativos | Producao | 2026-07 | 5,107s | 5,075s | 5,157s | 9 | melhora material do dominio-alvo |
| comparativos/exportar | Todos | 2026-07 | 13,310s | 13,205s | 13,310s | XLSX | melhorou, mas meta de 12s nao atingida |
| tendencias | Producao semana ampla | 2026-01 a 2026-07 | 5,636s | 4,613s | 5,636s | 9 | meta atingida para tendencia ampla de Producao |
| indicadores | Todos | 2026-07 | 9,296s | 9,032s | 9,296s | 29 | sem regressao sobre 9-10s publicados |
| tendencias | Todos | 2026-07 | 11,140s | 9,140s | 11,140s | 27 | mediana sem regressao relevante |

Rotas de regressao publicadas:

| Rota | Status | Tempo | Resultado |
|---|---:|---:|---|
| `/relatorios` | 200 | 1,799s | OK |
| `/dashboard` | 200 | 2,598s | OK |
| `/dre-gerencial?competencia=2026-07` | 200 | 3,653s | OK |
| `/fluxo-caixa` | 200 | 4,433s | OK |
| `/relatorios/financeiro/entradas-caixa` | 200 | 5,181s | OK |
| `/relatorios/producao/eficiencia` | 200 | 3,626s | OK |
| `/relatorios/almoxarifado/giro` | 404 | 2,146s | bloqueio preservado |
| `/relatorios/almoxarifado/fifo` | 404 | 1,399s | bloqueio preservado |
| `/relatorios/expedicao/transferencias` | 200 | 9,251s | OK |
| `/movimentacoes/importar` | 200 | 0,691s | OK |

Conclusao da Rodada 2:

- O gargalo especifico de Producao foi reduzido de forma comprovada.
- Tendencia ampla de Producao deixou de executar o processamento completo periodo a periodo e passou a usar resumo multiperiodo.
- Comparativos Todos melhorou, mas ainda ficou acima da meta de aceite de 10s por conter custo acumulado dos demais dominios.
- Exportacao de Comparativos Todos melhorou, mas ainda ficou acima da meta de 12s.
- Nao houve regressao relevante em Indicadores Todos nem em Tendencias Todos.
- Para atingir menos de 10s em Comparativos Todos, o proximo gargalo deve ser investigado por dominio restante, sem iniciar Dashboard Executivo.
