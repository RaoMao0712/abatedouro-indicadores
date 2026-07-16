# Relatorios de Expedicao - Onda 1

Sprint: Biblioteca Oficial de Relatorios - Onda 1 / Bloco Expedicao  
Data: 2026-07-16  
Commit inicial homologado: `df018f8`

## Objetivo

Implantar a camada oficial de inteligencia da Expedicao para consultar transferencias fisicas, estoque atual da Camara Fria LSM e historico fisico por caixa. Esta sprint nao cria venda, receita, baixa por NF, financeiro, DRE, CMV, FIFO analitico ou rastreabilidade completa ate cliente.

## Itens Oficiais da Sprint

| Relatorio | Slug | Decisao |
|---|---|---|
| Transferencias | `transferencias` | Criar relatorio oficial dedicado a eventos `pa_movimentacoes.tipo = 'TRANSFERENCIA'` |
| Estoque Camara Fria | `estoque-camara-fria` | Criar relatorio oficial da posicao atual em `Camara Fria LSM` |
| Historico por Caixa | `historico-por-caixa` | Criar consulta oficial individual por caixa, com impressao do navegador |

Vendas permanecem Onda 3/dependencia funcional. Rastreabilidade completa permanece Onda 3/dependencia funcional.

## Fontes Oficiais Auditadas

| Informacao | Fonte oficial | Campo/regra | Observacao |
|---|---|---|---|
| Codigo da caixa | `pa_caixas` | `codigo_caixa` | Identidade fisica oficial da caixa |
| OP | `pa_caixa_composicao` | `op_id` | Uma caixa pode ter composicao; usar agregacao por caixa para evitar multiplicacao |
| SKU | `pa_caixas` | `sku` | Produto acabado da caixa |
| Lote | derivado operacional | `OP-<op_id>` quando ha composicao | Nao existe campo de lote dedicado em `pa_caixas` |
| Data de producao | `pa_caixas` | `data_fabricacao` | Valor salvo na caixa |
| Validade | `pa_caixas` | `data_validade` | Nao recalcular se ja salvo |
| Peso bruto | `pa_caixas` | `peso_bruto` | Valor salvo |
| Tara | inexistente | - | Nao ha campo oficial de tara na caixa |
| Peso liquido | `pa_caixas` | `peso_liquido` | Usar valor salvo; nao aplicar tara novamente |
| Quantidade/bandejas | `pa_caixas` | `quantidade_bandejas` | Unidades da caixa |
| Caixa parcial | inexistente | - | Nao ha flag oficial; nao inferir |
| Status | `pa_caixas` | `status` | Ex.: `Em estoque`, `Cancelada` |
| Local atual | `pa_caixas.local_estoque_id` + `locais_estoque` | local salvo na caixa | Atualizado pelo service de transferencia |
| Local de origem | `pa_movimentacoes` | `local_origem_id` | Evento unico com origem e destino |
| Local de destino | `pa_movimentacoes` | `local_destino_id` | Evento unico com origem e destino |
| Data/hora da transferencia | `pa_movimentacoes` | `criado_em` | Timestamp do evento fisico |
| Usuario responsavel | `pa_movimentacoes` | `usuario` | Gravado na confirmacao do romaneio |
| Romaneio de transferencia | `expedicoes` | `id`, `numero_romaneio`, `tipo_movimentacao` | Cabecalho operacional do romaneio |
| Itens do romaneio | `expedicao_itens` | `caixa_id`, `op_id`, `sku`, `quantidade_kg` | Itens gravados na confirmacao |
| Historico da caixa | `pa_movimentacoes` | eventos por `caixa_id` | Atualmente registra transferencia; criacao da caixa vem de `pa_caixas` |
| Cancelamento/estorno | parcial | `expedicoes.status = 'Cancelado'`; `pa_caixas.status = 'Cancelada'` | Nao ha evento de estorno de transferencia identificado |

## Ciclo de Vida Oficial da Caixa

1. Caixa nasce na Pesagem da OP, Embalagem Secundaria ou Galinha Inteira via Embalagem Primaria.
2. A caixa recebe `local_estoque_id` inicial do Abatedouro.
3. A transferencia operacional cria/usa romaneio `expedicoes.tipo_movimentacao = 'TRANSFERENCIA'`.
4. Ao confirmar o romaneio:
   - valida caixa em estoque e no Abatedouro;
   - atualiza `pa_caixas.local_estoque_id` para Camara Fria LSM;
   - grava `expedicao_itens`;
   - grava um evento `pa_movimentacoes` com origem, destino, caixa, usuario e romaneio.
5. A transferencia nao altera `status` da caixa e nao cria financeiro, DRE, CMV ou receita.

## Regra de Local Atual

O local atual oficial e o campo `pa_caixas.local_estoque_id`, resolvido em `locais_estoque.nome`.

O historico oficial e o livro `pa_movimentacoes`. Para caixas transferidas, o ultimo evento fisico valido deve coincidir com `pa_caixas.local_estoque_id`. Caixas sem movimentacao podem estar corretamente no Abatedouro por backfill/local inicial.

## Tipos de Movimentacao

| Tipo | Fonte | Direcao | Altera estoque consolidado | Relatorios |
|---|---|---|---|---|
| `TRANSFERENCIA` | `pa_movimentacoes` | Origem -> destino no mesmo evento | Nao | Transferencias; Historico por Caixa |
| Criacao/entrada PA | `pa_caixas` | Entrada fisica inicial | Sim, pela criacao da caixa | Historico por Caixa como marco de criacao |

Nao foi identificado evento separado de venda, baixa de PA por venda, NF, cliente, estorno de transferencia ou cancelamento de transferencia.

## Decisoes de Implementacao

- Criar `modules/relatorios/expedicao.py` como servico compartilhado somente leitura.
- Criar rotas `/relatorios/expedicao/<slug>` e `/relatorios/expedicao/<slug>/exportar`.
- Gerar Excel para Transferencias e Estoque Camara Fria.
- Historico por Caixa tera tela e impressao do navegador; nao declarar PDF dedicado.
- Atualizar catalogo oficial para os tres relatorios Onda 1.
- Manter Vendas e Rastreabilidade completa sem endpoint ativo.
- Nao usar SQL em template, nao agregar em JavaScript, nao chamar DDL/backfill/commit em GET.

## Limitacoes Conhecidas

- Nao ha campo oficial de tara.
- Nao ha flag de caixa parcial.
- Nao ha campo dedicado de lote; lote exibido e derivado de OP quando a composicao existe.
- Historico atual nao inclui NF, cliente ou destino final.
- Nao ha evento de estorno de transferencia identificado.
- Criacao da caixa nao esta em `pa_movimentacoes`; o Historico por Caixa mostra a criacao a partir de `pa_caixas`.
- O PDF dedicado nao existe; o formato oficial desta sprint para historico e tela/impressao.

## Reconciliacoes

- Transferencias usam evento unico `pa_movimentacoes`, evitando contar saida e entrada em duplicidade.
- Estoque Camara Fria usa somente `pa_caixas.local_estoque_id` atual, nao a existencia historica de transferencia.
- Caixa transferida que sair da Camara Fria em sprint futura deixara de aparecer se o local atual mudar.
- Peso total e soma direta de `pa_caixas.peso_liquido`/`peso_bruto` das caixas filtradas.
- Transferencia nao cria registro em `movimentacoes_financeiras`, nao altera DRE e nao gera CMV.

## Validacao Local

Cenario controlado criado com:

- duas OPs;
- dois SKUs;
- quatro caixas;
- duas caixas transferidas do Abatedouro para Camara Fria LSM;
- uma caixa permanecendo no Abatedouro;
- uma caixa cancelada;
- pesos bruto e liquido;
- validade presente e uma caixa sem validade;
- romaneio de transferencia;
- eventos `pa_movimentacoes.tipo = 'TRANSFERENCIA'`.

Resultado reconciliado:

- Transferencias: 2 eventos, 2 caixas unicas, 23,000 kg liquidos, 24,000 kg brutos.
- Estoque Camara Fria: 2 caixas, 23,000 kg liquidos, 1 SKU, 1 lote.
- Historico por Caixa: caixa `CX-A1` encontrada com 1 evento fisico e marco de criacao exibido.
- Exportacao Excel valida para Transferencias e Estoque Camara Fria.
- Exportacao direta de Historico por Caixa retorna 404, pois o formato oficial e tela/impressao.
- Acesso anonimo a `/relatorios/expedicao/transferencias` redireciona para login.

Rotas locais validadas:

- `/relatorios`
- `/relatorios?dominio=Expedicao`
- `/relatorios/expedicao/transferencias`
- `/relatorios/expedicao/estoque-camara-fria`
- `/relatorios/expedicao/historico-por-caixa`
- `/relatorios/expedicao/transferencias/exportar`
- `/relatorios/expedicao/estoque-camara-fria/exportar`
- `/expedicao`
- `/expedicao/novo`
- `/estoque-produtos`
- `/consultar-op`
- `/embalagem-primaria`
- `/embalagem-secundaria`
- Biblioteca de Producao
- Biblioteca de Almoxarifado
- Dashboard
- DRE
- Fluxo de Caixa
- Importacao financeira

Tempos locais medidos em tres execucoes com Flask test client:

| Rota | Status | Primeira abertura | Mediana |
|---|---:|---:|---:|
| `/relatorios?dominio=Expedicao` | 200 | 3,3 ms | 3,3 ms |
| `/relatorios/expedicao/transferencias` | 200 | 77,3 ms | 12,8 ms |
| `/relatorios/expedicao/estoque-camara-fria` | 200 | 18,2 ms | 18,2 ms |
| `/relatorios/expedicao/historico-por-caixa` | 200 | 18,4 ms | 12,9 ms |
| `/relatorios/expedicao/transferencias/exportar` | 200 | 62,2 ms | 40,5 ms |
| `/relatorios/expedicao/estoque-camara-fria/exportar` | 200 | 45,7 ms | 45,2 ms |

Comandos executados:

- `python -m compileall app.py modules\relatorios modules\expedicao`
- `git diff --check`
- busca por DDL/escrita no novo servico e template oficial.

Inspecao visual automatizada local ainda depende de navegador disponivel. Se o Playwright local permanecer sem Chromium/Chrome/Edge, a inspecao visual obrigatoria sera realizada no Render.
