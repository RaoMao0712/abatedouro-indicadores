# Biblioteca Oficial de Relatorios - Auditoria Inicial

Sprint: Biblioteca Oficial de Relatorios - Fundacao, Auditoria e Centralizacao  
Data: 2026-07-16

## Decisao Executada

Foi criada a fundacao da Biblioteca Oficial de Relatorios do PRUMO como catalogo central, backlog e ponto unico de acesso aos relatorios oficiais.

Nesta sprint nao foram alterados calculos, consultas financeiras, DRE, Fluxo de Caixa, importadores, CMV, estoque, producao, expedicao ou rastreabilidade.

A descontinuacao executada foi controlada e limitada ao menu lateral: atalhos redundantes para relatorios foram removidos da navegacao principal e substituidos por um unico item "Biblioteca de Relatorios". As rotas oficiais continuam ativas para preservar links, exportacoes e compatibilidade.

## Registro Oficial

O catalogo oficial foi registrado em `modules/relatorios/catalogo.py` com 38 relatorios oficiais.

Campos registrados:

- ID;
- nome;
- dominio;
- objetivo gerencial;
- endpoint;
- prioridade;
- onda;
- status;
- dependencias;
- formatos disponiveis;
- permissao necessaria;
- disponibilidade via endpoint.

## Inventario de Rotas com Funcao de Relatorio ou Leitura Gerencial

| Nome atual | Rota | Template | Dominio | Finalidade | Relatorio oficial correspondente | Classificacao | Situacao atual | Dependencias | Acao proposta | Risco | Decisao executada nesta sprint |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Dashboard | `/dashboard` | `dashboard.html` | Gerencial | Indicadores executivos e leitura consolidada | Indicadores; Dashboard Executivo; Producao por Periodo | MANTER E ADEQUAR | Disponivel | Producao, financeiro e indicadores atuais | Vincular ao catalogo | Baixo | Mantido e referenciado na Biblioteca |
| Fluxo de Caixa | `/fluxo-caixa` | `fluxo_caixa.html` | Financeiro | Disponibilidade prevista e realizada | Fluxo de Caixa; Competencia x Realizacao | MANTER E ADEQUAR | Disponivel | Central de Movimentacoes, Matriz de Impacto | Centralizar acesso pela Biblioteca | Baixo | Mantido, link redundante removido do menu |
| DRE Gerencial | `/dre-gerencial` | `dre_gerencial.html` | Financeiro | Desempenho economico por competencia | DRE Gerencial | MANTER E ADEQUAR | Disponivel | Plano de Contas, DRE, Movimentacoes | Centralizar acesso pela Biblioteca | Baixo | Mantido, link redundante removido do menu |
| Exportacao DRE | `/dre-gerencial/exportar-excel` | sem template | Financeiro | Exportar DRE para Excel | DRE Gerencial | MANTER E ADEQUAR | Disponivel | DRE Gerencial | Preservar endpoint | Medio se removido | Mantido |
| Entradas Financeiras | `/movimentacoes/entradas` | `financeiro.html` | Financeiro | Lancamento e consulta de entradas | Entradas de Caixa; Receitas | PRESERVAR TEMPORARIAMENTE | Tela operacional com leitura | Central de Movimentacoes | Evoluir para relatorio dedicado futuramente | Alto se confundida com relatorio puro | Mantida como tela operacional e referenciada como acesso atual |
| Saidas Financeiras | `/movimentacoes/despesas` | `financeiro.html` | Financeiro | Lancamento e consulta de saidas | Saidas de Caixa | PRESERVAR TEMPORARIAMENTE | Tela operacional com leitura | Central de Movimentacoes | Evoluir para relatorio dedicado futuramente | Alto se removida | Mantida |
| Financeiro legado | `/financeiro` | redireciona | Financeiro | Compatibilidade para Movimentacoes | Entradas de Caixa | CONSOLIDAR | Redireciona para `/movimentacoes/entradas` | Movimentacoes | Manter compatibilidade | Medio | Mantido |
| Movimentacoes legado | `/movimentacoes` | redireciona | Financeiro | Compatibilidade para Movimentacoes | Entradas de Caixa | CONSOLIDAR | Redireciona para `/movimentacoes/entradas` | Movimentacoes | Manter compatibilidade | Medio | Mantido |
| Liquidacao Financeira | `/movimentacoes/liquidacao` | `movimentacoes_liquidacao.html` | Financeiro | Titulos analisados, vencidos e baixa | Contas a Pagar; Contas a Receber | MANTER E ADEQUAR | Disponivel | Central de Movimentacoes | Referenciar na Biblioteca | Baixo | Mantido |
| Exportacao Liquidacao | `/movimentacoes/liquidacao/exportar` | sem template | Financeiro | Exportar liquidacao para Excel | Contas a Pagar; Contas a Receber | MANTER E ADEQUAR | Disponivel | Liquidacao Financeira | Preservar endpoint | Medio se removido | Mantido |
| Auditoria Financeira | `/movimentacoes/auditoria` | `movimentacoes_auditoria.html` | Financeiro | Auditoria e reclassificacao de movimentos | Despesas por Categoria; Despesas por Subcategoria; Aportes | MANTER E ADEQUAR | Disponivel | Central de Movimentacoes, Plano de Contas | Referenciar na Biblioteca | Baixo | Mantido |
| Exportacao Auditoria | `/movimentacoes/auditoria/exportar` | sem template | Financeiro | Exportar auditoria para Excel | Despesas por Categoria; Despesas por Subcategoria; Aportes | MANTER E ADEQUAR | Disponivel | Auditoria Financeira | Preservar endpoint | Medio se removido | Mantido |
| Pendencias de Classificacao | `/movimentacoes/pendencias` | `movimentacoes_pendencias.html` | Financeiro | Consulta operacional de classificacao pendente | Auditoria Financeira | PRESERVAR TEMPORARIAMENTE | Operacional | Importador e Plano de Contas | Manter fora de relatorios oficiais | Baixo | Mantido |
| Importacao Financeira | `/movimentacoes/importar` | `movimentacoes_importar.html` | Financeiro | Importar planilha oficial | Nao e relatorio | PRESERVAR TEMPORARIAMENTE | Operacional | Importador Financeiro | Preservar | Alto se removido | Mantido |
| Modelo Importacao | `/movimentacoes/modelo-importacao-oficial` | sem template | Financeiro | Baixar modelo oficial | Nao e relatorio | PRESERVAR TEMPORARIAMENTE | Operacional/exportacao utilitaria | Importador Financeiro | Preservar | Medio | Mantido |
| Importar Vendas Financeiras | `/movimentacoes/importar-vendas` | `movimentacoes_importar.html` | Financeiro | Importar receitas | Receitas | PRESERVAR TEMPORARIAMENTE | Operacional | Importador Financeiro | Preservar ate Romaneio de Venda | Alto | Mantido |
| Plano de Contas Gerencial | `/plano-contas-gerencial` | `plano_contas_gerencial.html` | Financeiro | Consulta do Plano Mestre | Plano de Contas, nao relatorio oficial | PRESERVAR TEMPORARIAMENTE | Documentacao operacional | Plano Mestre | Preservar | Alto se removido | Mantido |
| Evolucao Custos | `/relatorio-custos` | `relatorio_custos.html` | Financeiro/Gerencial | Evolucao de custos mensais legados | Evolucao Financeira | CONSOLIDAR | Disponivel, baseado em `custos_mensais` | Custos mensais | Preservar temporariamente e referenciar com alerta de evolucao | Medio | Link redundante removido do menu; rota mantida |
| Rendimento | `/relatorio-rendimento` | `relatorio_rendimento.html` | Producao | Rendimento industrial | Rendimento; Producao por Fornecedor | MANTER E ADEQUAR | Disponivel | OPs encerradas, pesagem | Centralizar acesso pela Biblioteca | Baixo | Link redundante removido do menu; rota mantida |
| Viabilidade | `/relatorio-viabilidade` | `relatorio_viabilidade.html` | Producao | Perdas, condenacoes e viabilidade | Condenacoes; Perdas | MANTER E ADEQUAR | Disponivel | Qualidade, descartes, OPs | Centralizar acesso pela Biblioteca | Baixo | Link redundante removido do menu; rota mantida |
| Consultar OP | `/consultar-op` | `consultar_op.html` | Producao | Consulta de ordens e filtros | Producao por OP; Producao por SKU | MANTER E ADEQUAR | Consulta operacional e gerencial | OPs | Referenciar como acesso atual | Baixo | Mantido |
| Impressao OP | `/op/<id>/imprimir` | `op_impressao.html` | Producao | Impressao individual da OP | Producao por OP | PRESERVAR TEMPORARIAMENTE | Consulta individual | OP | Preservar | Alto se removido | Mantido |
| Custos | `/custos` | `custos.html` | Financeiro | Cadastro/gestao de custos mensais legados | Nao e relatorio oficial puro | PRESERVAR TEMPORARIAMENTE | Operacional legado | Custos mensais | Nao remover nesta sprint | Alto | Mantido |
| Vendas | `/vendas` | `vendas.html` | Financeiro/Expedicao | Cadastro legado de vendas diarias | Vendas; Receitas | PRESERVAR TEMPORARIAMENTE | Operacional legado | Vendas diarias | Preservar ate Romaneio de Venda | Alto | Mantido |
| Almoxarifado Saldo | `/almoxarifado/saldo` | `almoxarifado_saldo.html` | Almoxarifado | Saldo de insumos | Estoque Atual; Estoque por Produto | MANTER E ADEQUAR | Disponivel | Estoque almoxarifado | Referenciar na Biblioteca | Baixo | Mantido |
| Almoxarifado Movimentacoes | `/almoxarifado/movimentacoes` | `almoxarifado_movimentacoes.html` | Almoxarifado | Historico de entradas e saidas | Consumo | MANTER E ADEQUAR | Disponivel | Movimentacoes almoxarifado | Referenciar na Biblioteca | Baixo | Mantido |
| Almoxarifado Entrada | `/almoxarifado/entrada` | `almoxarifado_entrada.html` | Almoxarifado | Registrar e consultar entradas | Entradas | PRESERVAR TEMPORARIAMENTE | Operacional com consulta | Almoxarifado | Preservar | Alto se removido | Mantido |
| Almoxarifado Rastreabilidade | `/almoxarifado/rastreabilidade` | `almoxarifado_rastreabilidade.html` | Almoxarifado | Consulta de lotes/uso | FIFO; Rastreabilidade de insumos | PRESERVAR TEMPORARIAMENTE | Consulta operacional | Lotes almoxarifado | Mapear em onda futura | Medio | Mantido |
| Estoque PA/PI | `/estoque-produtos` | `estoque_produtos.html` | Expedicao | Estoque PA por local e caixas | Estoque Camara Fria; Historico por Caixa; Rastreabilidade | MANTER E ADEQUAR | Disponivel | PA por local, composicao | Referenciar na Biblioteca | Baixo | Mantido |
| Expedicao | `/expedicao` | `expedicao.html` | Expedicao | Historico/lista de romaneios | Transferencias | MANTER E ADEQUAR | Disponivel | Romaneios | Referenciar na Biblioteca | Baixo | Mantido |
| Novo Romaneio | `/expedicao/novo` | `novo_romaneio.html` | Expedicao | Criar transferencia | Nao e relatorio | PRESERVAR TEMPORARIAMENTE | Operacional | Romaneio Transferencia | Preservar | Alto se removido | Mantido |
| Detalhe Romaneio | `/expedicao/<id>` | `romaneio_detalhe.html` | Expedicao | Consulta e confirmacao individual | Transferencias; Historico por Caixa | PRESERVAR TEMPORARIAMENTE | Consulta individual/operacional | Romaneio | Preservar | Alto | Mantido |
| Historico Romaneios legado | template `historico_romaneios.html` | sem rota ativa identificada no registro atual | Expedicao | Historico antigo de romaneios | Transferencias | DESCONTINUAR | Arquivo legado sem rota registrada | Rotas antigas de expedicao | Remover somente apos confirmacao adicional | Medio | Preservado temporariamente; sem link novo |
| Romaneio Expedicao legado | template `romaneio_expedicao.html` | sem rota ativa identificada no registro atual | Expedicao | Baixa antiga de estoque por romaneio | Vendas | DESCONTINUAR | Arquivo legado sem rota registrada | Romaneio de Venda futuro | Nao remover nesta sprint | Alto | Preservado temporariamente; sem link novo |
| Romaneio Visualizar legado | template `romaneio_visualizar.html` | sem rota ativa identificada no registro atual | Expedicao | Visualizacao/impressao antiga | Transferencias/Vendas | DESCONTINUAR | Arquivo legado sem rota registrada | Rotas antigas | Nao remover nesta sprint | Medio | Preservado temporariamente; sem link novo |
| Biblioteca de Relatorios | `/relatorios` | `biblioteca_relatorios.html` | Gerencial | Catalogo oficial e centralizacao | Todos os 38 relatorios | MANTER E ADEQUAR | Criado nesta sprint | Catalogo em codigo | Ponto unico de acesso | Baixo | Implantado |

## Itens do Catalogo Oficial Sem Relatorio Dedicado Nesta Sprint

Os itens abaixo foram registrados no catalogo, mas nao receberam nova implementacao funcional nesta sprint:

- Producao: Eficiencia, OEE;
- Almoxarifado: Giro, Estoque por Local, FIFO, CMV;
- Expedicao: Vendas;
- Gerencial: Comparativos, Tendencias.

Decisoes:

- OEE: status `Futuro`;
- CMV: status `Congelado`;
- Vendas: status `Dependencia funcional`, dependente do Romaneio de Venda;
- demais: `Em estruturacao`.

## Consolidacoes Identificadas

- `/financeiro` e `/movimentacoes` continuam como redirecionamentos para a Central de Movimentacoes.
- Evolucao Custos foi vinculada ao catalogo como etapa intermediaria de Evolucao Financeira.
- Entradas/Saidas/Receitas usam a Central de Movimentacoes como acesso atual, com status "Disponivel - requer evolucao".
- Contas a Pagar/Receber usam a Liquidacao Financeira como acesso atual.
- Despesas por Categoria/Subcategoria e Aportes usam a Auditoria Financeira como acesso atual.

## Descontinuacoes Executadas

Nenhuma rota, tabela, template ou dado foi removido nesta sprint.

Descontinuacao executada:

- remocao de atalhos redundantes do menu lateral para `Rendimento`, `Viabilidade`, `Evolucao Custos`, `DRE Gerencial` e `Fluxo de Caixa`;
- substituicao por `Biblioteca de Relatorios`.

## Preservados Temporariamente

- telas operacionais de cadastro, lancamento, importacao, edicao, criacao de OP, embalagem, expedicao e almoxarifado;
- templates legados de romaneio sem rota ativa detectada;
- rotas oficiais antigas dos relatorios, para nao quebrar URLs existentes;
- exportacoes Excel de DRE, Auditoria e Liquidacao.

## Riscos e Pendencias

- Alguns relatorios oficiais ainda usam telas operacionais como acesso atual. Isso foi documentado com status "Disponivel - requer evolucao".
- Templates legados de romaneio devem ser revisados em sprint propria antes de qualquer remocao.
- O catalogo oficial nao deve ser duplicado em templates; novas alteracoes devem ocorrer em `modules/relatorios/catalogo.py`.
- A Biblioteca nao cria base paralela, nao grava eventos e nao altera impactos financeiros.
