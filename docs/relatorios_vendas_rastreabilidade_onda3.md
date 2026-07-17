# Relatorios de Vendas e Rastreabilidade - Onda 3 Bloco 2

Commit inicial obrigatorio: `cab43e51096880f1ace8e73ec6d1d1d504c8935a`.

Worktree auditado: `C:\Users\g227716298.GRUPOSP-AD\.codex\worktrees\4ca3\abatedouro indicadores`.

## Decisao Executiva

| Relatorio | Cenario | Decisao | Rota publica | Exportacao |
|---|---|---|---|---|
| Vendas | C - Base insuficiente | Manter em estruturacao | 404 | 404 |
| Rastreabilidade | C - Base insuficiente para cadeia comercial completa | Manter em estruturacao | 404 | 404 |

Nenhum relatorio foi ativado artificialmente.

## Principio Preservado

Transferencia interna nao foi tratada como venda.

Saida fisica nao foi tratada como receita.

Emissao de NF nao foi inferida a partir de romaneio.

Baixa de PA nao foi tratada como realizacao financeira.

CMV permanece congelado.

## Inventario Encontrado

### Sankhya e NF Comercial

Nao foram encontrados modulos, rotas, templates, tabelas ou importadores oficiais de Sankhya ou Nota Fiscal de venda.

Campos com a palavra NF aparecem apenas como contexto produtivo em `ordens_producao.nota_fiscal`, isto e, documento de origem/recebimento de materia-prima. Esse campo nao identifica venda, cliente, receita, baixa de PA ou romaneio comercial.

### Vendas Legadas

Existe cadastro operacional legado:

- rota: `/vendas`;
- template: `templates/vendas.html`;
- tabela: `vendas_diarias`;
- funcoes principais: `criar_tabela_vendas`, `salvar_venda_diaria`, `buscar_vendas_diarias`, `buscar_venda_diaria_por_data_sku`.

Schema de `vendas_diarias`:

- `id`;
- `data`;
- `sku`;
- `quantidade`;
- `unidade`;
- `quantidade_unidades`;
- `quantidade_kg`;
- `receita`;
- `observacoes`;
- `criado_em`.

Conclusao: `vendas_diarias` nao e evento comercial oficial. Nao possui cliente, NF, serie, chave NF-e, item comercial, identificador externo, romaneio de venda, caixa, baixa de PA, cancelamento comercial, estorno ou vinculo financeiro oficial.

Regra atual da DRE:

- Receita Bruta vem da `Central de Movimentacoes` (`movimentacoes_financeiras`) por `data_documento`;
- `vendas_diarias` ainda e lida para quantidades/SKU e compatibilidade historica, mas nao alimenta mais Receita Bruta;
- CMV permanece congelado.

### Romaneios e Expedicao

Fluxo ativo:

- rotas: `/expedicao`, `/expedicao/novo`, `/expedicao/<id>`;
- tabelas: `expedicoes`, `expedicao_itens`, `pa_movimentacoes`;
- relatorios oficiais publicados: `transferencias`, `estoque-camara-fria`, `historico-por-caixa`.

Schema relevante de `expedicoes`:

- `numero_romaneio`;
- `data`;
- `tipo_movimentacao`;
- `destino`;
- `responsavel`;
- `observacoes`;
- `status`.

O tipo ativo e fixo: `TRANSFERENCIA`.

Schema relevante de `expedicao_itens`:

- `expedicao_id`;
- `caixa_id`;
- `op_id`;
- `sku`;
- `quantidade_unidades`;
- `quantidade_kg`.

Schema relevante de `pa_movimentacoes`:

- `caixa_id`;
- `local_origem_id`;
- `local_destino_id`;
- `tipo`;
- `expedicao_id`;
- `usuario`;
- `criado_em`.

Conclusao: a expedicao atual registra transferencia fisica entre Abatedouro e Camara Fria LSM. Nao registra venda, NF, cliente, receita, conta a receber ou CMV.

### Produto Acabado e Rastreabilidade Parcial

Tabelas disponiveis:

- `pa_caixas`;
- `pa_caixa_composicao`;
- `locais_estoque`;
- `pa_movimentacoes`;
- `expedicoes`;
- `expedicao_itens`;
- `ordens_producao`.

Elos comprovados hoje:

| Elo | Status |
|---|---|
| OP -> caixa PA | Comprovado por `pa_caixa_composicao` |
| Caixa PA -> SKU/peso/validade/status | Comprovado por `pa_caixas` |
| Caixa PA -> local atual | Comprovado por `pa_caixas.local_estoque_id` |
| Caixa PA -> transferencia | Comprovado por `pa_movimentacoes` e `expedicao_itens` |
| Transferencia -> romaneio logistico | Comprovado por `expedicoes` |
| Caixa PA -> NF de venda | Ausente |
| Caixa PA -> cliente | Ausente |
| Romaneio logistico -> venda | Ausente |
| Venda -> receita financeira | Ausente |
| Venda -> CMV | Congelado / ausente |

Ja existe relatorio parcial para consulta fisica:

- `/relatorios/expedicao/historico-por-caixa`.

Esse relatorio nao deve ser renomeado para "Rastreabilidade" completa porque nao chega a NF/cliente.

## Fluxos de Escrita Auditados

### Venda Diaria Legada

`salvar_venda_diaria`:

- cria `vendas_diarias` se necessario;
- valida data, SKU, quantidades e receita;
- impede duplicidade por `data + sku`;
- grava uma linha consolidada;
- faz `commit`.

Limite: a chave `data + sku` e adequada ao cadastro legado consolidado, mas nao representa idempotencia de venda comercial, NF, item, cliente ou caixa.

### Romaneio de Transferencia

`salvar_romaneio_expedicao`:

- cria cabecalho em `expedicoes`;
- `tipo_movimentacao = TRANSFERENCIA`;
- destino fixo: Camara Fria LSM;
- faz `commit`;
- nao gera financeiro.

`confirmar_transferencia_romaneio`:

- valida romaneio aberto;
- valida tipo `TRANSFERENCIA`;
- valida caixa em estoque no Abatedouro;
- atualiza `pa_caixas.local_estoque_id`;
- insere `expedicao_itens`;
- insere `pa_movimentacoes` com tipo `TRANSFERENCIA`;
- atualiza status do romaneio;
- faz `commit` unico;
- executa `rollback` em falha.

Limite: fluxo logistico, nao comercial.

### Central de Movimentacoes

`movimentacoes_financeiras` possui `documento_id`, `numero_documento`, `data_documento`, `data_vencimento`, `data_realizacao`, favorecido/parceiro e `import_key`.

Limite: nao foi encontrado vinculo oficial entre essas movimentacoes e uma NF/romaneio/caixa de Produto Acabado. A receita financeira pode existir sem cadeia comercial rastreavel.

## Cardinalidades e Risco de Multiplicacao

Nao foi criado SQL novo para Vendas/Rastreabilidade nesta sprint.

Riscos identificados para sprint futura:

- uma NF pode ter varios itens;
- um item pode envolver varias caixas;
- uma caixa pode ter composicao de OP;
- um romaneio pode ter varias caixas;
- uma venda pode ter parcelas/recebimentos financeiros.

Regra futura obrigatoria: agregar documento comercial, itens, caixas e financeiro por fonte antes de relacionar. Nunca somar cabecalho de documento depois de join com itens ou caixas.

## Cobertura Local

A base local de desenvolvimento, apos inicializacao de schema, continha:

| Tabela | Registros |
|---|---:|
| `vendas_diarias` | 0 |
| `expedicoes` | 0 |
| `expedicao_itens` | 0 |
| `pa_movimentacoes` | 0 |
| `pa_caixas` | 0 |
| `pa_caixa_composicao` | 0 |
| `movimentacoes_financeiras` | 0 |
| `locais_estoque` | 2 |

Essa medicao local nao foi usada para concluir cobertura de producao.

## Cobertura Render

Validacao de producao deve permanecer somente leitura e sem expor dados comerciais sensiveis.

Validacao autenticada realizada em `https://abatedouro-indicadores.onrender.com`.

Commit de merge publicado: `4bc1ee51062b8b8e36a0d5da0fbd047348fb1456`.

Rotas bloqueadas confirmadas:

| Rota | Status | Tempo |
|---|---:|---:|
| `/relatorios/expedicao/vendas` | 404 | 0,279s |
| `/relatorios/expedicao/vendas/exportar` | 404 | 0,250s |
| `/relatorios/expedicao/rastreabilidade` | 404 | 0,250s |
| `/relatorios/expedicao/rastreabilidade/exportar` | 404 | 0,378s |

Rotas oficiais existentes de Expedicao a preservar:

| Rota | Status | Tempo |
|---|---:|---:|
| `/relatorios` | 200 | 0,446s |
| `/relatorios?dominio=Expedicao` | 200 | 0,289s |
| `/dashboard` | 200 | 1,805s |
| `/relatorios/gerencial/dashboard-executivo` | 200 | 5,851s |
| `/relatorios/gerencial/indicadores` | 200 | 8,998s |
| `/relatorios/gerencial/comparativos` | 200 | 0,307s |
| `/relatorios/gerencial/tendencias` | 200 | 9,218s |
| `/dre-gerencial?competencia=2026-07` | 200 | 3,432s |
| `/fluxo-caixa` | 200 | 5,128s |
| `/movimentacoes/importar` | 200 | 0,270s |
| `/estoque-produtos` | 200 | 1,418s |
| `/expedicao` | 200 | 0,792s |
| `/relatorios/expedicao/transferencias` | 200 | 2,396s |
| `/relatorios/expedicao/estoque-camara-fria` | 200 | 2,271s |
| `/relatorios/expedicao/historico-por-caixa` | 200 | 1,675s |
| `/relatorios/producao/producao-por-op` | 200 | 3,747s |
| `/relatorios/almoxarifado/estoque-atual` | 200 | 2,512s |
| `/relatorios/financeiro/receitas` | 200 | 3,584s |

Catalogo de Expedicao confirmado com `Vendas`, `Rastreabilidade` e status `Em estruturacao`.

## Regras de Data

Vendas oficial futura:

- deve usar data comercial oficial do documento/venda;
- nao deve usar `data_realizacao`;
- nao deve usar data de transferencia;
- nao deve usar data de baixa de caixa como data de venda.

Financeiro preservado:

- DRE: `data_documento`;
- Fluxo previsto: `data_vencimento`;
- Realizado: `data_realizacao`.

## Catalogo

Itens revisados:

| Item | Status | Endpoint |
|---|---|---|
| Vendas | Em estruturacao | nenhum |
| Rastreabilidade | Em estruturacao | nenhum |

Dependencias registradas:

- integracao Sankhya/NF de venda;
- cliente comercial;
- itens comerciais;
- romaneio de venda;
- baixa PA por venda;
- vinculo financeiro/comercial oficial;
- NF/cliente como destino final da rastreabilidade.

## Testes Planejados para Quando a Base Permitir

Nao foi criado cenario artificial em producao.

O cenario controlado futuro devera incluir:

- venda completa com NF;
- NF com mais de um item;
- varias caixas do mesmo item;
- caixas de OPs diferentes;
- transferencia interna fora de vendas;
- venda sem vinculo financeiro;
- receita sem vinculo comercial;
- documento cancelado ou estornado;
- reimportacao do mesmo identificador externo;
- cadeia parcial de rastreabilidade.

## Arquivos Alterados

- `modules/relatorios/catalogo.py`;
- `docs/relatorios_vendas_rastreabilidade_onda3.md`.

## Conclusao Tecnica

Vendas: Cenario C.

A base atual nao possui evento comercial oficial com NF, cliente, item comercial, romaneio de venda e vinculo com baixa de PA. O cadastro `vendas_diarias` e legado, consolidado por data/SKU, e nao deve ser promovido a relatorio oficial de vendas comerciais.

Rastreabilidade: Cenario C para cadeia comercial completa.

Ha rastreabilidade fisica parcial de PA ate OP, caixa, local e transferencia. Falta o destino comercial: romaneio de venda, NF e cliente. Por isso o relatorio completo permanece em estruturacao, enquanto `Historico por Caixa` continua como consulta fisica parcial ja publicada.
