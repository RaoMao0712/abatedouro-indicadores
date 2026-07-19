# Relatorio Competencia x Realizacao - Origem dos Pagamentos

## Lacuna corrigida

O relatorio oficial Competencia x Realizacao existia na Biblioteca Financeira, mas nao respondia de forma auditavel a origem dos pagamentos realizados em um periodo. A visao anterior tambem nao possuia filtro explicito de Natureza e recortava a competencia pela data do documento/vencimento, mesmo quando o usuario selecionava referencia por Realizacao/Baixa.

## Definicao tecnica de pagamento realizado

Para a analise de origem dos pagamentos, um pagamento realizado e um evento financeiro que atende simultaneamente:

- Natureza interna `Saida`;
- `data_realizacao` dentro do periodo filtrado;
- status realizado oficial: `Pago`, `Recebido` ou `Realizado`;
- `impacta_fluxo_caixa = 1`;
- status diferente de `Cancelado`;
- valor realizado maior que zero.

O valor usado e `valor_pago` quando preenchido. Se nao houver `valor_pago`, a regra oficial reaproveitada considera o valor do evento apenas quando ha baixa e status realizado.

## Filtro Natureza

O relatorio passou a aceitar o filtro `natureza` com valores seguros:

- `Todas`;
- `Entrada`;
- `Saida`.

O padrao e `Todas`, preservando bookmarks e comportamento anterior. Valores invalidos retornam para `Todas`.

## Competencia de origem

A competencia de origem e sempre o mes da `data_documento`.

Quando `data_documento` esta ausente, o evento fica em `Sem data do documento`. O sistema nao infere origem pela data de vencimento nem pela data de baixa.

## Transferencias e eventos neutros

Transferencias entre contas proprias e eventos neutros do Fluxo Consolidado permanecem fora da analise de pagamentos quando `impacta_fluxo_caixa = 0`. A decisao de inclusao nao usa `impacta_dre` como criterio unico.

## Top 5

O Top 5 mostra eventos financeiros individuais, sem agrupamento por categoria, favorecido ou documento.

A ordenacao e deterministica:

1. valor realizado decrescente;
2. data de realizacao;
3. identificador interno do evento.

## Reconciliacao

Na combinacao `Referencia = Realizacao / baixa` e `Natureza = Saida`, o relatorio demonstra:

`Total pago no periodo = soma por competencia de origem = soma da base detalhada filtrada`

O Top 5 e apenas um subconjunto do total e possui valor e percentual proprios.

## Exportacao

Para a analise ativa, a exportacao XLSX inclui:

- `Resumo`;
- `Top 5 Pagamentos`;
- `Origem por Competencia`;
- `Dados Detalhados`;
- `Parametros`.

As abas usam valores numericos reais, filtros, congelamento de cabecalho e metadados de regra.

Nas demais combinacoes de filtro, a exportacao generica anterior e preservada.

## Testes controlados

Foi criada uma base SQLite temporaria cobrindo:

- documento de janeiro pago em marco;
- documento de fevereiro pago em marco;
- documento de marco pago em marco;
- mais de seis saidas para validar Top 5;
- entrada realizada em marco;
- aporte realizado em marco;
- transferencia neutra;
- documento em aberto;
- saida realizada fora de marco;
- pagamento sem Data do Documento;
- saida pequena fora do Top 5;
- categorias e favorecidos distintos;
- empate entre pagamentos;
- cancelamento.

Validacoes automatizadas:

- entrada fora do filtro `Saida`;
- aporte fora do filtro `Saida`;
- transferencia neutra fora dos pagamentos;
- aberto fora do realizado;
- evento fora do periodo excluido;
- `Sem data do documento` incluido corretamente;
- Top 5 com exatamente cinco eventos;
- ordenacao deterministica;
- total por competencia igual ao total pago;
- percentual das competencias reconciliado;
- valor do Top 5 menor ou igual ao total;
- tela e Excel reconciliados;
- nenhuma duplicacao de valor.

Comandos:

```powershell
python tests\test_competencia_realizacao_origem_pagamentos.py
python -m compileall modules\relatorios tests\test_competencia_realizacao_origem_pagamentos.py
```

## Performance

A implementacao usa uma base filtrada unica da Central de Movimentacoes e agregacoes em memoria por evento ja filtrado. Nao ha consulta por linha, `JOIN` multiplicador, DDL, backfill ou gravacao em requisicoes GET.

## Validacao Render

Pendente ate merge, push e deploy automatico.

Parametros obrigatorios para apuracao real:

- Data Inicial: `2026-03-01`;
- Data Final: `2026-03-31`;
- Referencia: `realizacao`;
- Natureza: `Saida`.

Registrar apos deploy:

- total pago em marco de 2026;
- quantidade de pagamentos;
- Top 5;
- valor e percentual do Top 5;
- distribuicao por competencia de origem;
- principal competencia;
- eventos sem Data do Documento;
- tempo de tela;
- tempo de exportacao.
