# Relatorios de Almoxarifado - Onda 2 / Giro e FIFO Analitico

## Commit inicial

Sprint iniciada a partir de `01246eeb46dca3382a5eccdbff0e287d3962e4ba`.

## Decisao de viabilidade

### Giro de Estoque

Cenario C - base insuficiente para publicacao na Biblioteca.

O PRUMO possui modelo tecnico para eventos oficiais de entrada e consumo em `almoxarifado_movimentacoes`, saldo atual por lote em `almoxarifado_lotes` e unidade/categoria no cadastro de insumos. Porem a base publicada auditada ainda nao possui entradas, consumos ou lotes reais no Almoxarifado.

Como nao ha historico real para consumo, saldo inicial, saldos diarios ou estoque medio, o relatorio nao foi ativado no catalogo.

### FIFO Analitico

Cenario C - base insuficiente para publicacao na Biblioteca.

O FIFO analitico so sera verificavel quando existirem consumos oficiais com `lote_id` e historico anterior suficiente do mesmo insumo.

A base publicada auditada nao possui consumos oficiais, consumos com `lote_id` ou lotes reais. Portanto o card permanece em estruturacao, sem endpoint ativo no catalogo.

## Medicao da base publicada

Consulta realizada por rotas autenticadas no Render, cobrindo `2020-01-01` a `2030-12-31`:

| Item | Resultado |
|---|---:|
| Entradas oficiais | 0 |
| Consumos oficiais | 0 |
| Consumos com lote | 0 |
| Lotes rastreados | 0 |
| Itens com saldo | 0 |
| Produtos cadastrados visiveis no Estoque Atual | 3 |

Cobertura verificavel FIFO:

```text
0 consumos verificaveis / 0 consumos oficiais = nao aplicavel
```

Conformidade FIFO:

```text
0 conformes / 0 verificaveis = nao aplicavel
```

## Regra oficial de estoque

Fonte de saldo atual:

```text
saldo_atual = SUM(almoxarifado_lotes.quantidade_atual)
```

Fonte de eventos:

```text
almoxarifado_movimentacoes
```

Tipos oficiais usados:

| Tipo | Direcao analitica | Consumo oficial | Observacao |
|---|---|---:|---|
| ENTRADA | Entrada | Nao | Cria lote e movimento |
| SAIDA | Saida | Sim | Consumo sem OP |
| SAIDA_OP | Saida | Sim | Consumo vinculado a OP |
| ESTORNO_OP | Entrada/retorno | Nao | Retorna saldo ao lote |
| AJUSTE | Indefinida | Nao | Exibido no Giro, mas nao classificado como consumo |

## Regra operacional de FIFO

A regra operacional encontrada nos textos e na estrutura e FIFO por data de entrada do lote.

Desempate adotado pela propria ordenacao operacional existente:

```text
data_entrada ASC, id ASC
```

Nao ha campo de validade no Almoxarifado. Portanto, a regra nao e FEFO e o relatorio nao usa validade.

## Campos oficiais mapeados

| Informacao | Fonte | Campo |
|---|---|---|
| Produto | `almoxarifado_insumos` | `descricao` |
| Categoria | `almoxarifado_insumos` | `categoria` |
| Unidade | `almoxarifado_insumos` | `unidade` |
| Lote | `almoxarifado_lotes`, `almoxarifado_movimentacoes` | `lote`, `lote_id` |
| Data da entrada | `almoxarifado_lotes` | `data_entrada` |
| Data do evento | `almoxarifado_movimentacoes` | `data_movimentacao` |
| Hora/timestamp | `almoxarifado_movimentacoes` | `criado_em` |
| Quantidade entrada | `almoxarifado_lotes`, `almoxarifado_movimentacoes` | `quantidade_inicial`, `quantidade` |
| Quantidade saida/consumo | `almoxarifado_movimentacoes` | `quantidade` |
| Saldo por lote | `almoxarifado_lotes` | `quantidade_atual` |
| Tipo de movimento | `almoxarifado_movimentacoes` | `tipo` |
| OP | `almoxarifado_movimentacoes` | `op_id` |
| Documento | `almoxarifado_lotes`, `almoxarifado_movimentacoes` | `numero_nf` |
| Fornecedor | `almoxarifado_lotes`, `almoxarifado_movimentacoes` | `fornecedor` |
| Valor unitario | lotes/movimentos | `valor_unitario` |
| Valor total | lotes/movimentos | `valor_total` |

Campos ausentes:

- validade;
- local/deposito;
- usuario responsavel;
- cancelamento;
- bloqueio de lote;
- reserva;
- estorno/cancelamento do evento original por referencia;
- saldo inicial independente por produto/lote.

## Formula do Giro

Por produto e unidade:

```text
Giro = Consumo oficial do periodo / Estoque medio do periodo
```

Consumo oficial:

```text
SUM(quantidade) WHERE tipo IN ('SAIDA', 'SAIDA_OP')
```

Estoque medio:

```text
Estoque medio = soma dos saldos diarios de fechamento / quantidade de dias do periodo
```

Reconstrucao:

1. saldo de abertura = movimentos oficiais anteriores ao periodo;
2. movimentos do periodo agregados por dia;
3. fechamento diario acumulado;
4. media dos fechamentos diarios.

## Formula da Cobertura

```text
Consumo medio diario = consumo oficial do periodo / dias do periodo
Cobertura em dias = saldo final do periodo / consumo medio diario
```

Regras:

- consumo zero: sem consumo no periodo;
- saldo zero com consumo: cobertura de zero dia;
- saldo negativo: saldo inconsistente;
- unidades diferentes nao sao somadas em linha unica;
- cobertura nao e previsao de demanda.

## Definicao de violacao FIFO

Um consumo e marcado como `Possivel violacao` somente quando:

1. o consumo possui `lote_id`;
2. o lote consumido existe;
3. havia lote anterior elegivel com saldo positivo antes do consumo;
4. o lote consumido nao era o mais antigo pela regra `data_entrada, id`;
5. o historico do mesmo insumo nao estava comprometido por consumo anterior sem lote.

Estados:

- `Conforme`;
- `Possivel violacao`;
- `Nao verificavel`;
- `Sem lote`.

## Matriz de elegibilidade FIFO

| Criterio | Regra |
|---|---|
| Mesmo produto | `lote.insumo_id = movimento.insumo_id` |
| Entrada anterior | `lote.data_entrada <= movimento.data_movimentacao` |
| Saldo historico | saldo reconstruido do lote antes do consumo maior que zero |
| Lote bloqueado | nao avaliado; campo inexistente |
| Validade | nao avaliada; campo inexistente |
| Cancelamento | nao avaliado; campo inexistente |

## Tratamento de casos especiais

| Caso | Tratamento |
|---|---|
| Lote sem validade | Nao impacta; Almoxarifado nao possui validade |
| Lote sem data | Nao verificavel quando impede ordenacao |
| Saldo negativo | Giro marca saldo negativo; FIFO nao corrige |
| Devolucao/estorno | `ESTORNO_OP` retorna saldo e nao entra como consumo |
| Ajuste | Exibido em Giro, sem direcao oficial confiavel |
| Consumo parcial | Abate saldo historico do lote consumido |
| Lote esgotado | Permanece com saldo historico zero |
| Reentrada | Tratada como evento de entrada/estorno quando registrada |
| Cancelamento | Campo inexistente; nao inferido |

## Limitacoes e riscos

- A operacao atual visivel cria entradas, mas nao foi localizada rota operacional que grave a baixa automatica FIFO.
- O relatorio analisa eventos existentes; nao executa FIFO.
- Sem saldo inicial separado, periodos anteriores ao inicio do modulo podem ter historico insuficiente.
- Sem validade, nao ha FEFO nem vencimento de lote.
- Sem bloqueio/cancelamento, excecoes oficiais nao podem ser comprovadas.
- CMV permanece congelado; valores sao atributos auditaveis, nao apuracao de custo.

## Arquivos alterados

- `modules/relatorios/almoxarifado.py`
- `modules/relatorios/catalogo.py`
- `templates/relatorio_almoxarifado_oficial.html`
- `docs/relatorios_giro_fifo_onda2.md`

## Rotas

As rotas nao foram ativadas nesta publicacao porque a base operacional e insuficiente:

- `/relatorios/almoxarifado/giro` deve retornar 404.
- `/relatorios/almoxarifado/giro/exportar` deve retornar 404.
- `/relatorios/almoxarifado/fifo` deve retornar 404.
- `/relatorios/almoxarifado/fifo/exportar` deve retornar 404.

## Catalogo

Giro e FIFO Analitico permanecem como `Em estruturacao`.

Estoque por Local permanece `Em estruturacao`, sem endpoint.

CMV permanece `Congelado`, sem endpoint.

## Dependencias para ativacao futura

Giro:

- entradas reais registradas como `ENTRADA`;
- consumos reais registrados como `SAIDA` ou `SAIDA_OP`;
- lotes/saldos reconciliaveis;
- periodo operacional com historico suficiente.

FIFO:

- fluxo real de baixa por lote;
- consumos com `lote_id`;
- lote consumido gravado no evento;
- historico anterior suficiente para reconstruir saldo por lote;
- regra operacional preservada por `data_entrada, id`.

## Validacao local

Com banco temporario isolado foi criado cenario controlado para o motor analitico:

Giro:

- produto com saldo inicial, entrada, dois consumos e estorno;
- produto com saldo zerado;
- produto sem consumo;
- produto com saldo negativo controlado;
- unidades diferentes mantidas separadas.

Resultados conferidos manualmente:

- Produto A: saldo inicial 100, consumo 50, estoque medio 114, giro 0,4386, cobertura 21 dias.
- Produto B: `Saldo zerado`.
- Produto C: `Sem consumo`.
- Produto D: `Saldo negativo`.

FIFO:

- tres lotes com entradas em datas diferentes;
- consumo correto do lote mais antigo;
- consumo de lote posterior com lote anterior disponivel;
- consumo sem lote;
- consumo posterior com historico comprometido;
- estorno.

Estados validados:

- `Conforme`;
- `Possivel violacao`;
- `Sem lote`;
- `Nao verificavel`.

Rotas locais:

- Onda 1 de Almoxarifado permaneceu HTTP 200.
- Exportacoes da Onda 1 permaneceram XLSX validas.
- `/relatorios/almoxarifado/giro` retornou 404.
- `/relatorios/almoxarifado/giro/exportar` retornou 404.
- `/relatorios/almoxarifado/fifo` retornou 404.
- `/relatorios/almoxarifado/fifo/exportar` retornou 404.

Medianas locais principais:

| Rota | Mediana |
|---|---:|
| `/relatorios?dominio=Almoxarifado` | 1,8 ms |
| `/relatorios/almoxarifado/entradas` | 6,0 ms |
| `/relatorios/almoxarifado/consumo` | 6,5 ms |
| `/relatorios/almoxarifado/estoque-atual` | 5,5 ms |
| `/relatorios/almoxarifado/estoque-por-produto` | 7,5 ms |

## Validacao estatica

Comandos executados:

- `python -m compileall app.py modules\relatorios modules\almoxarifado`
- `git diff --check`

## PostgreSQL e visual

Como Giro e FIFO nao foram ativados como rotas publicas nesta sprint, a validacao PostgreSQL ficara restrita ao catalogo e as rotas ja existentes no Render.

A inspecao visual automatizada local nao foi declarada porque o ambiente desta maquina ja apresentou ausencia de navegador Playwright/Chrome em sprints anteriores. A validacao publicada deve confirmar a Biblioteca sem links ativos para Giro/FIFO.
