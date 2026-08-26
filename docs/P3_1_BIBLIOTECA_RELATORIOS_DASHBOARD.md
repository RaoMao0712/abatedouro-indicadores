# P3.1 — Biblioteca de Relatórios e Dashboard Gerencial

## Escopo consolidado

A Biblioteca usa `RELATORIOS_OFICIAIS` como fonte única e preserva as 41 entradas e rotas existentes. A camada de apresentação acrescenta módulo, finalidade, nível de gestão, formatos, fonte, calculabilidade e perfis autorizados. A busca é insensível a maiúsculas e acentos. Os filtros oficiais são módulo, finalidade, nível e formato.

Não foram criadas regras de negócio, tabelas, migrations, favoritos ou tracking de recentes. Relatórios ainda não calculáveis continuam no catálogo sem link operacional e com seu estado explícito.

## Matriz de acesso

| Módulo | Perfis de leitura |
|---|---|
| Financeiro | admin, pcp, gerencia |
| Produção | admin, pcp, producao, gerencia |
| Estoque e Insumos | admin, pcp, producao, gerencia |
| Estoque e Expedição | admin, pcp, qualidade, gerencia |
| Gerencial | admin, pcp, gerencia |

O mesmo recorte é aplicado aos cards e às rotas genéricas de tela/exportação. O administrador vê a matriz na própria Biblioteca.

## Inventário oficial

| ID | Relatório | Módulo | Finalidade | Fonte | Filtros | Exportação | Estado |
|---|---|---|---|---|---|---|---|
| financeiro-fluxo-caixa | Fluxo de Caixa | Financeiro | Análise | Movimentações financeiras | Período | Tela | Disponível |
| financeiro-entradas-caixa | Entradas de Caixa | Financeiro | Movimentação | Movimentações financeiras | Período | Tela/Excel | Disponível |
| financeiro-saidas-caixa | Saídas de Caixa | Financeiro | Movimentação | Movimentações financeiras | Período | Tela/Excel | Disponível |
| financeiro-contas-pagar | Contas a Pagar | Financeiro | Posição atual | Movimentações financeiras | Período/status | Tela/Excel | Disponível |
| financeiro-contas-receber | Contas a Receber | Financeiro | Posição atual | Movimentações financeiras | Período/status | Tela/Excel | Disponível |
| financeiro-dre-gerencial | DRE Gerencial | Financeiro | Análise | DRE oficial | Competência | Tela/Excel | Disponível |
| financeiro-despesas-categoria | Despesas por Categoria | Financeiro | Análise | Movimentações financeiras | Período/categoria | Tela/Excel | Disponível |
| financeiro-despesas-subcategoria | Despesas por Subcategoria | Financeiro | Análise | Movimentações financeiras | Período/subcategoria | Tela/Excel | Disponível |
| financeiro-receitas | Receitas | Financeiro | Movimentação | Movimentações financeiras | Período | Tela/Excel | Disponível |
| financeiro-aportes | Aportes | Financeiro | Movimentação | Movimentações financeiras | Período | Tela/Excel | Disponível |
| financeiro-evolucao-financeira | Evolução Financeira | Financeiro | Análise | Movimentações financeiras | Período | Tela/Excel | Disponível |
| financeiro-competencia-realizacao | Competência x Realização | Financeiro | Análise | Movimentações financeiras | Período | Tela/Excel | Disponível |
| producao-op | Produção por OP | Produção | Movimentação | OP/apontamentos | Período/OP | Tela/Excel | Disponível |
| producao-sku | Produção por SKU | Produção | Movimentação | OP/apontamentos | Período/SKU | Tela/Excel | Disponível |
| producao-fornecedor | Produção por Fornecedor | Produção | Movimentação | OP/apontamentos | Período/fornecedor | Tela/Excel | Disponível |
| producao-periodo | Produção por Período | Produção | Movimentação | OP/apontamentos | Período | Tela/Excel | Disponível |
| producao-rendimento | Rendimento | Produção | Análise | Pesos oficiais | Período/OP/SKU | Tela/Excel/Impressão | Disponível |
| producao-condenacoes | Condenações | Produção | Movimentação | Descartes oficiais | Período | Tela/Excel | Disponível |
| producao-perdas | Perdas | Produção | Movimentação | Produção/descartes | Período | Tela/Excel | Disponível |
| producao-eficiencia | Eficiência | Produção | Análise | Produção/tempo | Período | Tela/Excel | Disponível |
| producao-disponibilidade | Disponibilidade da Linha | Produção | Análise | Tempos oficiais | Período/OP | Tela/Excel | Disponível |
| producao-performance | Performance da Linha | Produção | Análise | Produção/tempo operacional | Período/OP | Tela/Excel | Disponível |
| producao-oee | OEE | Produção | Análise | D/P/Q oficiais | Período/OP | Tela/Excel | Disponível com evolução |
| almoxarifado-entradas | Entradas | Estoque e Insumos | Movimentação | Movimentos do almoxarifado | Período/insumo | Tela/Excel | Disponível |
| almoxarifado-consumo | Consumo | Estoque e Insumos | Movimentação | Movimentos do almoxarifado | Período/insumo | Tela/Excel | Disponível |
| almoxarifado-giro | Giro | Estoque e Insumos | Análise | Histórico de consumo/saldo | — | Catálogo | Em estruturação |
| almoxarifado-estoque-atual | Estoque Atual | Estoque e Insumos | Posição atual | Saldo do almoxarifado | Insumo | Tela/Excel | Disponível |
| almoxarifado-estoque-local | Estoque por Local | Estoque e Insumos | Análise | Localização de estoque | — | Catálogo | Em estruturação |
| almoxarifado-estoque-produto | Estoque por Produto | Estoque e Insumos | Análise | Saldo do almoxarifado | Produto | Tela/Excel | Disponível |
| almoxarifado-fifo | FIFO | Estoque e Insumos | Histórico | Lotes e saídas | — | Catálogo | Em estruturação |
| almoxarifado-cmv | CMV | Financeiro | Análise | Motor CMV homologado | Competência | Tela/Impressão | Disponível |
| expedicao-transferencias | Transferências | Estoque e Expedição | Movimentação | Movimentos de PA | Período | Tela/Excel | Disponível |
| expedicao-entregas-cliente | Entregas por Cliente | Estoque e Expedição | Movimentação | Romaneios | Período/cliente | Impressão | Disponível |
| expedicao-vendas | Vendas | Estoque e Expedição | Movimentação | NF/romaneio de venda | — | Catálogo | Em estruturação |
| expedicao-estoque-camara-fria | Estoque Câmara Fria | Estoque e Expedição | Posição atual | Consolidado de estoque | Produto/lote | Tela/Excel | Disponível |
| expedicao-historico-caixa | Histórico por Caixa | Estoque e Expedição | Histórico | Movimentos de caixas | Caixa | Tela/Impressão | Disponível |
| expedicao-rastreabilidade | Rastreabilidade | Estoque e Expedição | Histórico | Lotes/destino final | — | Catálogo | Em estruturação |
| gerencial-indicadores | Indicadores | Gerencial | Análise | Registro oficial de indicadores | Período/domínio | Tela/Excel | Disponível |
| gerencial-comparativos | Comparativos | Gerencial | Análise | Camada gerencial | Período/domínio | Tela/Excel | Disponível |
| gerencial-tendencias | Tendências | Gerencial | Histórico | Camada gerencial | Período/granularidade | Tela/Excel | Disponível |
| gerencial-dashboard-executivo | Dashboard Executivo | Gerencial | Análise | Indicadores oficiais | Preset/período/bloco | Tela/Impressão | Disponível |

## Redundâncias e legado

- `relatorio_rendimento` é mantido apenas como redirecionamento compatível para o relatório oficial de Rendimento.
- `relatorio_custos` e `relatorio_viabilidade` permanecem fora do catálogo por não possuírem substituto 1:1; suas rotas são preservadas.
- Impressões operacionais de manutenção e PNC permanecem na allowlist de governança e não são promovidas a relatórios gerenciais.
- Não foram removidas ou renomeadas rotas nesta sprint.

## Dashboard executivo

O dashboard separa três leituras:

1. **Operação atual:** OPs não encerradas, PNC ativos e pedidos confirmados/parcialmente atendidos, obtidos em uma única query somente leitura.
2. **Posição atual:** indicadores cuja referência temporal já é posição, como estoque de Câmara Fria.
3. **Período selecionado:** produção, rendimento, perdas e finanças, com comparação equivalente.

Presets: Hoje, Mês atual, Mês anterior e Personalizado. Ausência de base aparece como `N/A`; alertas de PNC e pedidos são objetivos e clicáveis. CMV está marcado como disponível, com cobertura parcial/N/A quando aplicável. Os blocos completos continuam sob demanda para evitar carga inicial excessiva.

## Performance e governança

- Biblioteca: transformação em memória de 41 itens, sem consulta ao banco e sem N+1.
- Operação atual: uma consulta com três agregações escalares.
- Dashboard: reutiliza comparativos, tendências e consolidadores existentes; resumo inicial limitado a sete indicadores.
- Allowlist: testes existentes continuam governando endpoints oficiais, exportações e rotas legadas.

## Verificação

O arquivo `tests/test_p3_1_biblioteca_dashboard.py` cobre os 29 cenários obrigatórios: biblioteca (1–9), dashboard (10–20), performance (21–24) e navegação (25–29). As regressões oficiais de relatórios, Produção/P2.1/P2.2, Estoque, Expedição, PNC, DRE, CMV e exportações devem ser executadas antes da liberação.
