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
- A validacao final de metas deve ser feita no Render apos deploy, pois SQLite local vazio nao representa o volume de producao.
