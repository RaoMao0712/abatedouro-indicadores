# Relatorios de Almoxarifado - Onda 1

Sprint: Biblioteca Oficial de Relatorios - Onda 1 / Bloco Almoxarifado  
Data: 2026-07-16

## Objetivo

Implantar os cinco relatorios oficiais de Almoxarifado da Onda 1 usando somente eventos e saldos ja registrados pelo modulo operacional. Esta sprint nao cria, corrige, exclui, baixa, transfere ou valoriza estoque por regra nova.

## Itens Oficiais da Sprint

| Relatorio | Slug | Decisao |
|---|---|---|
| Entradas | `entradas` | Criar relatorio oficial dedicado a eventos `ENTRADA` |
| Consumo | `consumo` | Criar relatorio oficial dedicado a eventos de saida/consumo |
| Estoque Atual | `estoque-atual` | Expor saldo oficial calculado pelos lotes |
| Estoque por Local | - | Manter em estruturacao; nao existe fonte oficial de local |
| Estoque por Produto | `estoque-por-produto` | Detalhar saldo por insumo/produto com lotes |

Giro permanece Onda 2. FIFO como relatorio analitico permanece Onda 2. CMV permanece congelado/Onda 3. A regra operacional de FIFO existente nos textos e na estrutura de lotes nao foi alterada.

## Fontes Oficiais Auditadas

| Informacao | Fonte oficial | Campo/regra | Observacao |
|---|---|---|---|
| Produto/insumo | `almoxarifado_insumos` | `id`, `descricao` | Cadastro mestre do Almoxarifado |
| Categoria | `almoxarifado_insumos` | `categoria` | Lista operacional do modulo |
| Unidade | `almoxarifado_insumos` | `unidade` | Unidade de controle do insumo |
| Status do insumo | `almoxarifado_insumos` | `ativo` | Nao altera saldo |
| Entrada | `almoxarifado_movimentacoes` | `tipo = 'ENTRADA'` | Criada junto com lote |
| Saida/consumo | `almoxarifado_movimentacoes` | `tipo in ('SAIDA', 'SAIDA_OP')` | `SAIDA_OP` representa vinculo com OP |
| Estorno de OP | `almoxarifado_movimentacoes` | `tipo = 'ESTORNO_OP'` | Tratado como retorno de saldo, nao como consumo |
| Ajuste | `almoxarifado_movimentacoes` | `tipo = 'AJUSTE'` | Tipo previsto; sem direcao confiavel no schema atual |
| Lote | `almoxarifado_lotes` e movimento | `lote`, `lote_id` | Fonte da rastreabilidade e FIFO operacional |
| Validade | inexistente | - | Nao inventar campo |
| Local | inexistente | - | Estoque por Local nao foi ativado para nao simular deposito |
| Fornecedor | lote/movimento | `fornecedor` | Informado em entradas |
| Documento | lote/movimento | `numero_nf` | NF/documento de entrada |
| OP | movimento | `op_id` | Vinculo oficial quando preenchido |
| Quantidade | lote/movimento | `quantidade`, `quantidade_atual` | Evento e saldo sao separados |
| Valor unitario | lote/movimento | `valor_unitario` | Valor historico do evento/lote |
| Valor total | lote/movimento | `valor_total` | Entrada usa quantidade x valor unitario |
| Saldo | `almoxarifado_lotes` | `SUM(quantidade_atual)` | Fonte oficial atual do saldo |
| Reserva | inexistente | - | Nao ha campo de reserva |
| Disponibilidade | derivada do saldo | `quantidade_atual > 0` | Disponivel apenas como leitura |
| Usuario responsavel | inexistente | - | Nao ha campo de usuario no evento |
| Data/hora do evento | movimento/lote | `data_movimentacao`, `criado_em` | Data operacional e timestamp de criacao |

## Regra de Saldo

O saldo oficial atual nao e uma tabela propria e nao e reconstruido pelo relatorio. Ele e calculado pela soma dos lotes em `almoxarifado_lotes.quantidade_atual`, agrupada por insumo.

`saldo_atual = SUM(almoxarifado_lotes.quantidade_atual)`

`valor_estoque = SUM(almoxarifado_lotes.quantidade_atual * almoxarifado_lotes.valor_unitario)`

O relatorio apenas le esses campos. Nao executa DDL, backfill, `INSERT`, `UPDATE`, `DELETE`, `commit` ou ajuste automatico em GET.

## Matriz Oficial de Movimentacoes

| Tipo | Direcao | Impacta saldo | Representa consumo | Representa transferencia | Possui lote | Possui local | Vincula OP | Valor oficial | Relatorios |
|---|---|---|---|---|---|---|---|---|---|
| `ENTRADA` | Entrada | Sim | Nao | Nao | Sim | Nao | Nao usual | Sim | Entradas; Estoques |
| `SAIDA` | Saida | Sim quando operacionalmente gravada | Sim | Nao | Sim quando `lote_id` preenchido | Nao | Nao | Sim quando preenchido | Consumo |
| `SAIDA_OP` | Saida | Sim quando operacionalmente gravada | Sim | Nao | Sim quando `lote_id` preenchido | Nao | Sim | Sim quando preenchido | Consumo |
| `ESTORNO_OP` | Entrada/retorno | Sim quando operacionalmente gravada | Nao | Nao | Sim quando `lote_id` preenchido | Nao | Sim | Sim quando preenchido | Movimentacao, nao consumo |
| `AJUSTE` | Indefinida | Indefinido no schema | Nao classificar automaticamente | Nao | Opcional | Nao | Opcional | Opcional | Auditoria futura |

## Transferencias

Nao foi identificado campo de origem/destino nem tipo operacional de transferencia entre locais no Almoxarifado. Portanto:

- nao ha dupla contagem de transferencias a evitar nesta sprint;
- `Estoque por Local` nao cria deposito artificial;
- o relatorio permanece em estruturacao no catalogo ate existir local oficial;
- qualquer futura transferencia interna deve criar campo/evento proprio antes de virar relatorio analitico.

## FIFO

O cadastro de entrada cria lotes com `data_entrada`, `quantidade_inicial`, `quantidade_atual` e `status`, e as telas operacionais mencionam consumo FIFO. Esta sprint preserva essa estrutura. O relatorio analitico oficial de FIFO continua fora da Onda 1.

## Distincao Entre Estoques

Estes relatorios usam apenas:

- `almoxarifado_insumos`;
- `almoxarifado_lotes`;
- `almoxarifado_movimentacoes`.

Nao misturam produto intermediario, caixas de produto acabado, estoque por local de PA, romaneios, Camara Fria LSM ou CMV.

## Limitacoes Conhecidas

- Nao existe campo de local/deposito no Almoxarifado.
- Nao existe validade de lote.
- Nao existe reserva.
- Nao existe usuario responsavel por movimentacao.
- `AJUSTE` nao possui sinal/direcao confiavel no schema atual.
- Transferencias internas do Almoxarifado nao possuem modelo identificado.
- O valor de estoque atual e uma leitura pelos lotes remanescentes, nao uma valorizacao completa por custo medio ou CMV.

## Decisoes de Implementacao

- Criar `modules/relatorios/almoxarifado.py` como servico compartilhado somente leitura.
- Criar rotas `/relatorios/almoxarifado/<slug>` e `/relatorios/almoxarifado/<slug>/exportar` para Entradas, Consumo, Estoque Atual e Estoque por Produto.
- Usar filtros aplicados no banco: periodo, categoria, insumo, tipo, fornecedor, NF, lote, OP e status do lote.
- Usar o saldo oficial por lotes para Estoque Atual, Estoque por Local e Estoque por Produto.
- Manter Estoque por Local sem endpoint, pois nao ha campo oficial de local/deposito.
- Gerar Excel a partir do mesmo contexto da tela.
- Atualizar o catalogo oficial para os cinco relatorios Onda 1, mantendo Giro/FIFO/CMV fora de escopo.

## Validacao Local

Cenario controlado criado com:

- dois insumos;
- dois lotes;
- duas entradas;
- uma `SAIDA_OP`;
- uma `SAIDA`;
- um `ESTORNO_OP`.

Resultado reconciliado:

- Entradas: 2 eventos, 150 unidades, R$ 750,00.
- Consumo: 2 eventos, 80 unidades, R$ 575,00.
- `ESTORNO_OP` nao entrou como consumo.
- Estoque Atual: 1 item com saldo, 2 lotes, saldo total 70, valor em estoque R$ 175,00.
- Estoque por Produto: mesmos saldos oficiais por insumo/lote.

Rotas locais validadas com Flask test client:

- `/relatorios?dominio=Almoxarifado`
- `/relatorios/almoxarifado/entradas`
- `/relatorios/almoxarifado/consumo`
- `/relatorios/almoxarifado/estoque-atual`
- `/relatorios/almoxarifado/estoque-por-produto`
- exportacao Excel dos quatro relatorios disponiveis
- `/relatorios/almoxarifado/estoque-por-local` retorna 404 por URL direta e permanece sem endpoint no catalogo
- rotas legadas de Almoxarifado: cadastro, entrada, saldo, movimentacoes e rastreabilidade
- regressoes principais: Biblioteca de Producao, relatorio de Producao por OP, Dashboard, Estoque PA, Expedicao e DRE.

Tempos locais medidos em tres execucoes com Flask test client:

| Rota | Status | Primeira abertura | Mediana |
|---|---:|---:|---:|
| `/relatorios?dominio=Almoxarifado` | 200 | 31,4 ms | 5,7 ms |
| `/relatorios/almoxarifado/entradas` | 200 | 37,5 ms | 4,8 ms |
| `/relatorios/almoxarifado/consumo` | 200 | 6,3 ms | 6,3 ms |
| `/relatorios/almoxarifado/estoque-atual` | 200 | 3,7 ms | 3,9 ms |
| `/relatorios/almoxarifado/estoque-por-produto` | 200 | 8,5 ms | 4,6 ms |
| `/relatorios/almoxarifado/entradas/exportar` | 200 | 23,4 ms | 19,7 ms |
| `/relatorios/almoxarifado/consumo/exportar` | 200 | 21,2 ms | 18,1 ms |
| `/relatorios/almoxarifado/estoque-atual/exportar` | 200 | 19,4 ms | 19,4 ms |
| `/relatorios/almoxarifado/estoque-por-produto/exportar` | 200 | 22,2 ms | 22,2 ms |

Comandos executados:

- `python -m compileall app.py modules\relatorios modules\almoxarifado`
- `git diff --check`
- busca por DDL/escrita no novo servico e template oficial.

Inspecao visual automatizada por Playwright nao foi concluida localmente porque o binario Chromium do perfil nao estava instalado e nao havia Chrome/Edge do sistema disponivel. A renderizacao Jinja das telas e os exports foram validados via Flask test client.
