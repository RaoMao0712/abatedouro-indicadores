# Relatorios de Producao - Onda 1

Sprint: Biblioteca Oficial de Relatorios - Onda 1 / Bloco Producao  
Data: 2026-07-16

## Objetivo

Implantar os sete relatorios oficiais de Producao da Onda 1 sem criar, alterar, recalcular ou corrigir eventos produtivos. Os relatorios consomem eventos oficiais ja registrados e preservam as regras homologadas de producao, qualidade, PI, PA e fechamento de OP.

## Itens Oficiais da Sprint

| Relatorio | Slug | Decisao |
|---|---|---|
| Producao por OP | `producao-por-op` | Criar relatorio oficial dedicado |
| Producao por SKU | `producao-por-sku` | Criar relatorio oficial dedicado |
| Producao por Fornecedor | `producao-por-fornecedor` | Criar relatorio oficial dedicado |
| Producao por Periodo | `producao-por-periodo` | Criar relatorio oficial dedicado |
| Rendimento | `rendimento` | Integrar ao servico oficial preservando formula homologada |
| Condenacoes | `condenacoes` | Criar relatorio oficial dedicado a registros de condenacao |
| Perdas | `perdas` | Criar relatorio oficial dedicado sem sobreposicao de tipos |

Eficiencia permanece fora desta sprint. OEE permanece futuro. O relatorio de Viabilidade atual continua rota operacional/analitica e nao vira 39o item oficial.

## Fontes Oficiais Auditadas

| Indicador | Fonte oficial | Campo/regra | Observacao |
|---|---|---|---|
| Numero da OP | `ordens_producao` | `id` | Identificador oficial da OP |
| Data da OP | `ordens_producao` | `data` | Referencia temporal padrao desta sprint |
| Data de encerramento | nao existe campo dedicado | `status = 'Encerrada'` sem data propria | Limitacao documentada; nao inferir encerramento por outros eventos |
| Status | `ordens_producao` | `status` | Aberta, Aguardando Embalagem Secundaria, Encerrada |
| Fornecedor | `ordens_producao` | `fornecedor` | Origem da materia-prima |
| SKU | `ordens_producao` | `sku` | Default historico: Galinha Cortada |
| Lote | derivado operacional | `OP-<id>` | Nao ha campo de lote produtivo dedicado; usar identificador rastreavel da OP |
| Aves recebidas/vivas | `ordens_producao` | `quantidade_aves` | Denominador de fechamento de aves |
| Peso de entrada | `ordens_producao` | `peso_vivo` | Denominador do rendimento homologado |
| Peso medio | `ordens_producao` | `peso_medio` | Armazenado na OP |
| Mortes antes da pendura | `ordens_producao` | `mortes_antes_pendura` | Componente legado de perdas/viabilidade |
| Producao primaria / PI | `embalagem_primaria_apontamentos` | `quantidade_bandejas` | Entrada oficial de PI; para Galinha Inteira representa aves embaladas |
| Estoque PI | `estoque_produto_intermediario` | entradas/saidas por OP | Fonte operacional de saldo, nao base principal do relatorio |
| Producao secundaria / PA | `pa_caixas` + `pa_caixa_composicao` | caixas, `peso_liquido`, `peso_bruto`, `quantidade_bandejas` | Agregar por OP antes de relacionar para evitar duplicidade |
| Peso produzido homologado | `apontamentos_producao` | `unidade = 'kg'` | Usado pelo relatorio atual de Rendimento |
| Unidades produzidas | `apontamentos_producao` | `unidade in ('unidades','aves','bandejas','caixas')` por setor | Nao misturar como uma unidade unica sem rotulo |
| Descartes | `apontamentos_descartes` | categoria/motivo nao condenacao e motivo diferente de morte na gaiola | Somente unidades de aves/unidades entram no fechamento de aves |
| Condenacoes | `apontamentos_descartes` | `categoria` ou `motivo` contendo condenacao | Nao inferir por diferenca de fechamento |
| Mortes na gaiola | `apontamentos_descartes` | `motivo = 'morte na gaiola'` | Somar com `mortes_antes_pendura` quando aplicavel |
| Perdas em kg | `apontamentos_descartes` | `unidade = 'kg'` | Nao converter kg em aves ou aves em kg |
| Causa | `apontamentos_descartes` | `motivo` | Fonte de Pareto de perdas/condenacoes |
| Setor/etapa | `apontamentos_descartes`, `apontamentos_producao`, `embalagem_primaria_apontamentos`, `pa_caixas.origem` | conforme evento | Nomes operacionais existentes |
| Metas | Relatorio atual de Rendimento | meta fixa 63,0% | Preservar sem criar meta nova |

## Regras Homologadas Preservadas

Fechamento industrial auditado em `modules/expedicao/services.py`, funcao `calcular_fechamento_industrial_op`:

`Aves vivas = bandejas da Embalagem Primaria + descartes + condenacoes + mortes antes da pendura + mortes na gaiola`

Tambem exige:

- todas as bandejas de PI consumidas em caixas PA;
- existencia de peso liquido em caixas PA;
- OP ainda nao encerrada no momento do fechamento.

Esta sprint nao altera essa regra.

## Calculo Atual de Rendimento

Fonte atual: `modules/qualidade/routes.py`, rota `/relatorio-rendimento`.

Formula homologada:

`rendimento = kg_produzidos / peso_vivo * 100`

Onde:

- `kg_produzidos` = soma de `apontamentos_producao.quantidade` com `LOWER(unidade) = 'kg'`;
- `peso_vivo` = soma de `ordens_producao.peso_vivo`;
- filtro por `ordens_producao.data`;
- somente OPs com `status = 'Encerrada'`;
- meta fixa de 63,0%;
- agrupamento atual por data e fornecedor.

Decisao: preservar formula, fonte, filtro de status e meta. A nova rota oficial podera expor Excel, mas tela, Excel e acesso legado devem usar a mesma base e formula.

## Relatorio Atual de Viabilidade

Rota: `/relatorio-viabilidade`.

Classificacao:

- tela analitica operacional/gerencial existente;
- fonte temporaria de leitura para perdas e condenacoes;
- nao e novo item oficial do catalogo;
- pode continuar como rota legada preservada.

Regras atuais:

- aves recebidas por OP;
- mortes antes da pendura da OP;
- mortes na gaiola em `apontamentos_descartes`;
- condenacoes por categoria ou motivo contendo condenacao;
- descartes como perdas nao condenacao e nao morte na gaiola;
- somente unidades de aves/unidades entram na viabilidade.

Limitacao encontrada: nao ha data de encerramento propria da OP e nao ha peso condenado oficial quando a perda foi registrada em aves.

## Matriz Oficial de Perdas para Esta Sprint

| Tipo | Fonte | Unidade | Momento | Entra no total de perdas em aves | Pode coincidir |
|---|---|---|---|---|---|
| Mortes antes da pendura | `ordens_producao.mortes_antes_pendura` | aves | abertura/recebimento da OP | Sim | Nao possui causa/setor detalhado |
| Morte na gaiola | `apontamentos_descartes.motivo = 'morte na gaiola'` | aves/unidades | apontamento de qualidade | Sim | Nao entra como descarte |
| Condenacao | `apontamentos_descartes.categoria/motivo` contendo condenacao | aves/unidades ou kg | apontamento de qualidade | Sim quando unidade ave/unidade | Nao somar tambem como descarte |
| Descarte operacional | `apontamentos_descartes` sem condenacao e sem morte na gaiola | aves/unidades ou kg | apontamento de qualidade/processo | Sim quando unidade ave/unidade | Nao inclui condenacao |
| Perda em kg | `apontamentos_descartes.unidade = 'kg'` | kg | apontamento de qualidade/processo | Nao no total de aves | Apresentar separado sem conversao |
| Diferenca de fechamento | calculada no fechamento | aves | validacao de encerramento | Nao nesta sprint | Nao virar perda oficial por inferencia |

## Decisoes de Implementacao

- Criar `modules/relatorios/producao.py` como servico compartilhado somente leitura.
- Criar rotas `/relatorios/producao/<slug>` e `/relatorios/producao/<slug>/exportar`.
- Aplicar filtros no banco: periodo, OP, status, SKU, fornecedor, lote, causa, setor, situacao e granularidade.
- Agregar cada fonte por OP antes de compor relatorios por SKU, fornecedor e periodo.
- Nao chamar funcoes de criacao de schema, DDL, backfill ou commit dentro de GET.
- Nao usar SQL no template e nao fazer agregacao em JavaScript.
- Nao criar familia de SKU inexistente.
- Nao converter unidades sem regra oficial.
- Usar expressoes completas no `GROUP BY`, evitando alias para compatibilidade PostgreSQL.

## Limitacoes Conhecidas

- Nao existe campo dedicado de data de encerramento da OP.
- Nao existe lote produtivo separado; o lote exibido sera `OP-00000`.
- Condenacoes podem ter quantidade em aves/unidades ou kg; sem peso oficial nao sera estimado.
- Perdas em kg nao entram na taxa de perda em aves.
- PDF de Rendimento atual e impressao do navegador, nao arquivo PDF gerado no backend.
- Dados historicos divergentes nao serao corrigidos por relatorio.

## Riscos Controlados

- Multiplicacao por joins entre OP, descartes, caixas e apontamentos: mitigado por subconsultas agregadas por OP.
- Sobreposicao entre condenacao, descarte e morte na gaiola: mitigado pela matriz de perdas.
- Divergencia entre tela e Excel: mitigado por geracao de Excel a partir do mesmo contexto do servico.
- Diferenca SQLite/PostgreSQL em agrupamentos: evitar `GROUP BY` por alias.

## Validacao Local

Cenario controlado criado com:

- duas OPs encerradas;
- dois SKUs;
- dois fornecedores;
- producao primaria;
- producao secundaria com tres caixas PA;
- condenacao;
- descarte operacional;
- morte na gaiola;
- mortes antes da pendura;
- perda em kg.

Resultado reconciliado:

- Producao por OP: 2 OPs, 180 aves, 360 kg de entrada, 160 unidades de PI, 3 caixas PA, 220 kg produzidos, 18 aves de perdas, rendimento 61,11%.
- Producao por SKU: soma dos SKUs = total produtivo.
- Producao por Fornecedor: soma dos fornecedores = total produtivo.
- Producao por Periodo: soma do periodo = total por OP.
- Rendimento: mesma formula homologada, 220 / 360 = 61,11%.
- Condenacoes: 5 aves, sem inferencia por diferenca.
- Perdas: 18 aves incluindo mortes antes da pendura, morte na gaiola, condenacoes e descartes; perda em kg exibida separadamente.
- Tela e Excel dos sete relatorios retornaram 200 no test client.
- Acesso anonimo redireciona para login.
- Perfil sem permissao PCP/admin foi bloqueado.
- Inspecao visual local validou Biblioteca de Producao e telas oficiais sem overflow horizontal em desktop e mobile.

Comandos executados:

- `python -m compileall app.py modules\relatorios modules\producao modules\qualidade modules\expedicao`
- `git diff --check`
- teste controlado via Flask test client para as sete rotas e sete exportacoes.

