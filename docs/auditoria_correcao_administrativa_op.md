# Auditoria técnica — correção administrativa do peso de entrada da OP

Data da auditoria: 2026-07-29.

## Fonte e persistência

- O Peso de Entrada é persistido exclusivamente em `ordens_producao.peso_vivo`.
- `ordens_producao.peso_medio` também existe, mas não é a fonte do Peso de Entrada e
  não será alterado nesta sprint.
- Não existe tabela materializada de rendimento ou perdas percentuais. Esses valores
  são derivados em tempo de consulta.

## Dependências encontradas

- `modules/producao/services.py`: calcula o rendimento consolidado da OP com
  `kg_produzidos / peso_vivo`.
- `modules/dashboard/repositories.py` e `modules/dashboard/services.py`: somam
  `peso_vivo` no período e calculam o rendimento do dashboard.
- `modules/qualidade/routes.py`: calcula rendimento por OP e consolidado a partir de
  `peso_vivo`.
- `modules/relatorios/producao.py`: consulta, totaliza e exporta Peso de Entrada e
  rendimento nos relatórios de produção, eficiência e rendimento.
- `templates/consultar_op.html`, `templates/op_impressao.html`,
  `templates/relatorio_producao_oficial.html`, `templates/relatorio_rendimento.html`
  e `templates/dashboard.html`: apenas apresentam os valores fornecidos pelos
  serviços anteriores.
- `modules/importacao_oficial/routes.py`: grava o peso na criação/importação da OP,
  mas não mantém cópia derivada nem é executado durante uma correção.

## Impactos descartados por inspeção

Não foram encontradas leituras de `ordens_producao.peso_vivo` nos módulos ou tabelas
de estoque PI/PA, caixas/produto acabado, romaneios, expedição, DRE, CMV,
movimentações financeiras, almoxarifado ou consumo de insumos. Esses fluxos não
serão chamados pela correção.

## Decisão de implementação

A operação será uma transação curta que:

1. valida usuário, perfil, estado encerrado e ausência de cancelamento/bloqueio;
2. atualiza exclusivamente `ordens_producao.peso_vivo`;
3. insere um registro append-only em `correcoes_administrativas_op`;
4. mantém `status`, `peso_medio` e todos os dados operacionais intactos.

Como os indicadores e relatórios encontrados são calculados em leitura, não há
jobs, tabelas agregadas ou reprocessamentos destrutivos a disparar. A leitura
seguinte já usa o denominador corrigido.

Tentativas negadas serão registradas em `tentativas_correcao_administrativa_op`,
inclusive para perfis sem permissão e estados incompatíveis. A migration é apenas
aditiva.
