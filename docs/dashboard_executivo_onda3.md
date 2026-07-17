# Dashboard Executivo - Onda 3 Bloco 1

Commit inicial: `10e242701ca57622167228d3159a75ca926f625a`.

## Objetivo

Implantar o Dashboard Executivo oficial da Biblioteca de Relatorios sem substituir o `/dashboard` operacional. A nova rota e `/relatorios/gerencial/dashboard-executivo`.

O Dashboard Executivo consome somente:

- registro central de indicadores;
- comparativos oficiais;
- tendencias oficiais;
- resumos oficiais por dominio;
- permissoes ja existentes da Biblioteca.

Nao cria base paralela, snapshot, cache persistente, eventos ou formulas novas.

## Publico

Usuarios com permissao `pcp` e administradores. A rota segue a mesma protecao dos relatorios gerenciais oficiais.

## Auditoria do Registro Central

Total auditado: 28 indicadores.

| Status | Quantidade |
|---|---:|
| Disponivel | 25 |
| Disponivel - requer evolucao | 1 |
| Congelado | 1 |
| Futuro | 1 |

| Dominio | Quantidade |
|---|---:|
| Financeiro | 11 |
| Producao | 9 |
| Almoxarifado | 4 |
| Expedicao | 4 |

## Indicadores Selecionados

| ID | Nome | Dominio | Pergunta gerencial | Fonte | Unidade | Referencia | Regra | Tendencia | Status | Aprofundamento |
|---|---|---|---|---|---|---|---|---|---|---|
| `fin_receita_liquida` | Receita Operacional Liquida | Financeiro | O resultado economico tem base de receita liquida? | DRE Gerencial | R$ | Competencia | periodo equivalente | mensal | Disponivel | DRE |
| `fin_resultado_operacional` | Resultado Operacional | Financeiro | A operacao industrial gerou resultado operacional? | DRE Gerencial | R$ | Competencia | periodo equivalente | mensal | Disponivel | DRE |
| `fin_saldo_caixa` | Saldo de Caixa | Financeiro | A disponibilidade financeira realizada esta positiva? | Fluxo de Caixa | R$ | Realizacao | periodo equivalente | serie | Disponivel | Fluxo |
| `fin_aportes` | Aportes | Financeiro | Houve reforco financeiro fora da DRE? | Aportes | R$ | Vencimento | periodo equivalente | serie | Disponivel | Aportes |
| `prod_peso` | Peso Produzido | Producao | Quanto foi produzido em peso oficial? | Producao por OP | kg | Data da OP | periodo equivalente | serie | Disponivel | Producao por OP |
| `prod_rendimento` | Rendimento | Producao | A conversao produtiva esta sustentada? | Rendimento | % | Data da OP | periodo equivalente | serie | Disponivel | Rendimento |
| `prod_perdas` | Perdas | Producao | As perdas fisicas exigem atencao? | Perdas | aves | Data da OP | periodo equivalente | serie | Disponivel | Perdas |
| `prod_produtividade_hora_setor` | Produtividade por Hora-Setor | Producao | A produtividade por hora-setor tem base oficial? | Eficiencia | kg/hora-setor | Data da OP | periodo equivalente | serie | Disponivel - requer evolucao | Eficiencia |
| `alm_itens_saldo` | Produtos com Saldo | Almoxarifado | Existe leitura de saldo de insumos? | Estoque Atual | insumos | Saldo atual | periodo equivalente | mensal | Disponivel | Estoque Atual |
| `exp_caixas_transferidas` | Caixas Transferidas | Expedicao | Houve transferencia fisica no periodo? | Transferencias | caixas | Data do evento | periodo equivalente | serie | Disponivel | Transferencias |
| `exp_peso_transferido` | Peso Transferido | Expedicao | Qual peso saiu em transferencia fisica? | Transferencias | kg | Data do evento | periodo equivalente | serie | Disponivel | Transferencias |
| `exp_caixas_camara` | Caixas na Camara Fria | Expedicao | Qual a posicao atual da Camara Fria? | Estoque Camara Fria | caixas | Posicao atual | periodo equivalente | mensal | Disponivel | Estoque Camara Fria |

## Indicadores Rejeitados da Tela Inicial

| ID | Motivo |
|---|---|
| `fin_receita_bruta`, `fin_deducoes`, `fin_despesas_operacionais`, `fin_resultado_nao_operacional`, `fin_resultado_liquido` | Mantidos nos relatorios oficiais, mas redundantes para a abertura executiva enxuta. |
| `fin_entradas_caixa`, `fin_saidas_caixa` | Detalhamento financeiro; saldo e aportes ficam na abertura. |
| `prod_ops`, `prod_aves`, `prod_caixas`, `prod_condenacoes` | Disponiveis para aprofundamento, mas nao entram no nucleo inicial para evitar excesso de cards. |
| `alm_entradas`, `alm_consumo` | Base publicada ainda sem uso oficial relevante; preservados em bloco de dominio. |
| `exp_transferencias` | Numero de eventos e coberto indiretamente pelo bloco de Expedicao. |
| `cmv` | Congelado. Nao deve aparecer como zero. |
| `oee` | Futuro. Nao ha motor oficial. |

## Regras de Atencao

Alertas objetivos implementados:

- Saldo de caixa negativo oficial.
- Perdas ou produtividade por hora-setor com leitura oficial `Aumentou`.
- Indicador executivo sem dados no periodo.

Nao ha meta inventada, limite arbitrario ou favorabilidade automatica.

## Dependencias Abertas

- CMV: congelado ate existir criterio oficial definitivo de custo.
- OEE: futuro, depende de motor oficial.
- Vendas: depende de NF e Romaneio de Venda.
- Rastreabilidade completa: depende do destino final e venda.
- Giro: depende de historico consistente.
- FIFO Analitico: depende de rastreabilidade oficial de lotes e saidas.
- Estoque por Local de Almoxarifado: ainda sem local oficial.
- Eficiencia percentual: depende de meta/capacidade oficial.

## Performance e Carregamento

A abertura inicial carrega apenas o nucleo financeiro executivo:

- Receita Operacional Liquida;
- Resultado Operacional;
- Saldo de Caixa;
- Aportes.

Os blocos completos por dominio sao carregados por parametro da propria rota:

- `bloco=Financeiro`;
- `bloco=Producao`;
- `bloco=Almoxarifado`;
- `bloco=Expedicao`;
- `bloco=Todos`.

Nao ha endpoint auxiliar novo. Nao ha calculo em JavaScript.

## Impressao / PDF

Nao foi encontrado gerador PDF oficial dedicado para essa tela. O formato entregue e:

- `Imprimir / Salvar em PDF` via navegador.

O layout de impressao oculta navegacao e filtros, preservando titulo, periodo, indicadores, alertas e dependencias.

## Reconciliacao

| Indicador | Dashboard | Registro | Relatorio de origem | Diferenca | Status |
|---|---|---|---|---:|---|
| 12 indicadores selecionados | Comparativo oficial por ID | `REGISTRO_INDICADORES` | Services oficiais dos dominios | 0 | OK |
| Tendencia resumida | Tendencia oficial por ID | `REGISTRO_INDICADORES` | Services oficiais dos dominios | 0 | OK |
| Drill-down | Endpoint oficial existente | Catalogo / routes | Relatorio oficial | 0 | OK |

## Limitacoes

- Abertura inicial nao carrega todos os dominios automaticamente.
- A visao economica permanece incompleta enquanto CMV estiver congelado.
- OEE, Vendas, Rastreabilidade completa, Giro e FIFO seguem em evolucao.
- Permissoes parciais por dominio ainda dependem do modelo atual de perfis; nesta sprint a protecao segue `pcp/admin`.

## Validacao Render

URL validada: `https://abatedouro-indicadores.onrender.com`.

Commit de merge publicado: `77fc02e` (`Merge dashboard executivo onda 3 bloco 1`).

| Rota | Status | Tempo |
|---|---:|---:|
| `/relatorios/gerencial/dashboard-executivo` | 200 | 5,489s |
| `/relatorios/gerencial/dashboard-executivo?bloco=Financeiro` | 200 | 6,013s |
| `/relatorios/gerencial/dashboard-executivo?bloco=Producao` | 200 | 6,443s |
| `/relatorios/gerencial/dashboard-executivo?bloco=Almoxarifado` | 200 | 1,612s |
| `/relatorios/gerencial/dashboard-executivo?bloco=Expedicao` | 200 | 3,385s |
| `/relatorios/gerencial/dashboard-executivo?bloco=Todos` | 200 | 16,711s |
| `/relatorios?dominio=Gerencial` | 200 | 0,302s |
| `/dashboard` | 200 | 1,508s |
| `/relatorios/gerencial/comparativos` | 200 | 0,323s |
| `/relatorios/gerencial/indicadores` | 200 | 7,808s |
| `/relatorios/gerencial/tendencias` | 200 | 8,911s |
| `/dre-gerencial?competencia=2026-07` | 200 | 3,279s |
| `/fluxo-caixa` | 200 | 3,819s |
| `/relatorios/producao/eficiencia` | 200 | 3,277s |
| `/relatorios/expedicao/transferencias` | 200 | 2,261s |
| `/movimentacoes/importar` | 200 | 0,295s |
| `/relatorios/gerencial/dashboard-executivo/exportar` | 404 | esperado |

Confirmacoes:

- O Dashboard Executivo apareceu na Biblioteca de Relatorios.
- O `/dashboard` operacional permaneceu intacto e exibiu `Centro de Controle Industrial`.
- A acao publicada para PDF e `Imprimir / Salvar em PDF`, usando impressao do navegador.
- Nao foi criado endpoint falso de PDF.
- O carregamento `Todos` permanece sob acao explicita e manteve comportamento semelhante aos relatorios completos oficiais.
