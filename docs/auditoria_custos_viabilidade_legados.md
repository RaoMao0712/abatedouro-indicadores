# Auditoria de Legados: Custos e Viabilidade

## Baseline

- Worktree: `C:\Users\g227716298.GRUPOSP-AD\.codex\worktrees\4ca3\abatedouro indicadores`
- Commit inicial obrigatorio: `bdbf460aa5449a915d32d82362da721f248b5632`
- Branch: `codex/encerramento-legados-custos-viabilidade`
- Escopo: somente `/relatorio-custos` e `/relatorio-viabilidade`
- Nao rastreados preservados fora dos commits: `entregas/`, `tools/`, `reset_financeiro_producao_20260709_133850.zip`

## Resumo Executivo

Nenhuma das duas rotas possui equivalencia total com relatorio oficial da Biblioteca.

`/relatorio-custos` deve ser preservado temporariamente como requisito gerencial legado fora dos 38 relatorios, porque usa a tabela manual `custos_mensais` e nao a Central de Movimentacoes, Plano de Contas ou DRE.

`/relatorio-viabilidade` deve ser preservado como ferramenta/relatorio operacional da Qualidade fora da Biblioteca, porque calcula viabilidade de aves a partir de OPs e apontamentos de perdas, com filtros operacionais que nao existem como relatorio oficial 1:1.

Nao houve redirect. Nao houve 410. Nenhum 39o relatorio foi criado.

## Inventario: `/relatorio-custos`

| Item | Evidencia |
| --- | --- |
| Endpoint Flask | `relatorio_custos` |
| Modulo | `modules/relatorios/routes.py` |
| Metodo | `GET` |
| Permissao | `perfil_permitido("pcp")` |
| Template | `templates/relatorio_custos.html` |
| Service | `buscar_dados_relatorio_custos` em `modules/relatorios/services.py` |
| Repository | `buscar_custos_mensais_agrupados` em `modules/relatorios/repositories.py` |
| Tabela principal | `custos_mensais` |
| Tabelas auxiliares criadas pelo modulo | `parametros_custos`, `custos_mensais` |
| Parametros | `competencia_inicio`, `competencia_fim`, `categoria` |
| Data de referencia | competencia mensal `YYYY-MM` |
| Filtros | competencia inicial, competencia final, categoria |
| Exportacao | inexistente |
| Impressao | apenas impressao do navegador, sem formato oficial anunciado |
| Links de entrada | nao ha link ativo de menu; somente bookmarks ou acesso direto |
| Links internos | formulario aponta para `url_for("relatorio_custos")` |
| JavaScript | Chart.js local da pagina para linha mensal |
| Persistencia | a rota nao grava dados, mas o service chama `criar_tabelas_custos()` antes da leitura |

### Fontes e formulas

Fonte:

```sql
SELECT competencia, categoria, COALESCE(SUM(valor), 0) AS total
FROM custos_mensais
WHERE competencia BETWEEN ? AND ?
GROUP BY competencia, categoria
ORDER BY competencia, categoria
```

Indicadores:

- custo total: soma dos valores por categoria no periodo;
- media mensal: custo total dividido pela quantidade de competencias;
- maior categoria: categoria com maior soma no periodo;
- maior crescimento: diferenca entre ultimo e primeiro mes da categoria;
- participacao: total da categoria dividido pelo custo total.

Nao usa:

- `movimentacoes_financeiras`;
- Plano de Contas;
- compras;
- producao;
- estoque;
- CMV;
- DRE;
- Fluxo de Caixa.

## Matriz de Equivalencia: Custos

| Candidato oficial | Equivalencia | Motivo |
| --- | --- | --- |
| Despesas por Categoria | Parcial | Tambem agrupa valores monetarios por categoria, mas usa `movimentacoes_financeiras`, categoria do Plano de Contas e data de documento/vencimento/realizacao. |
| Despesas por Subcategoria | Nao | Granularidade de subcategoria/favorecido nao existe em `custos_mensais`. |
| Evolucao Financeira | Parcial | Tambem mostra evolucao mensal, mas calcula DRE/caixa/aportes na Central Financeira. |
| Producao por Periodo | Nao | Fonte produtiva, unidade fisica, sem custos manuais. |
| Rendimento | Nao | Percentual produtivo, sem valor monetario. |
| Eficiencia | Nao | Produtividade horaria, sem valor monetario. |
| CMV congelado | Nao | CMV permanece congelado e nao pode ser inferido de custo mensal manual. |

Equivalencia total: **nao**.

Risco de redirecionamento: alto. Redirecionar para despesas ou evolucao financeira mudaria fonte, data, formula e significado gerencial sem aviso.

Decisao: **Cenario D - requisito gerencial legado fora dos 38**, preservado temporariamente ate decisao humana.

## Inventario: `/relatorio-viabilidade`

| Item | Evidencia |
| --- | --- |
| Endpoint Flask | `relatorio_viabilidade` |
| Modulo | `modules/qualidade/routes.py` |
| Metodo | `GET` |
| Permissao | `perfil_permitido("pcp")` |
| Template | `templates/relatorio_viabilidade.html` |
| Services locais | `normalizar_data_relatorio_viabilidade`, `buscar_opcoes_relatorio_viabilidade`, `buscar_dados_relatorio_viabilidade` |
| Tabelas | `ordens_producao`, `apontamentos_descartes` |
| Parametros | `data_inicio`, `data_fim`, `fornecedor`, `motivo`, `setor` |
| Data de referencia | `ordens_producao.data` |
| Filtros | periodo, fornecedor, motivo, setor |
| Exportacao | inexistente |
| Impressao | botao `window.print()` |
| Links de entrada | nao ha link ativo de menu; somente bookmarks ou acesso direto |
| Links internos | formulario e limpar apontam para `url_for("relatorio_viabilidade")` |
| JavaScript | Chart.js para evolucao diaria |
| Persistencia | nao grava dados |

### Fontes e formulas

Fontes:

- OPs por periodo e fornecedor: `ordens_producao`;
- perdas, descartes, condenacoes e morte na gaiola apontada: `apontamentos_descartes`;
- morte antes da pendura legada: `ordens_producao.mortes_antes_pendura`.

Formula principal:

```text
viabilidade = (aves recebidas - mortes na gaiola - condenacoes - descartes) / aves recebidas * 100
```

Observacao tecnica: o codigo soma `mortes_antes_pendura` da OP quando o filtro de motivo e vazio/Todos/Morte na gaiola e soma tambem `apontamentos_descartes` cujo motivo e `morte na gaiola`.

Indicadores:

- aves recebidas;
- mortes na gaiola;
- condenacoes;
- descartes;
- total de perdas;
- aves viaveis;
- viabilidade percentual;
- evolucao diaria;
- perdas por setor;
- ranking de motivos;
- comparativo por fornecedor.

Nao usa:

- preco de venda;
- custo estimado;
- custos mensais;
- Central Financeira;
- DRE;
- Fluxo de Caixa;
- CMV.

## Matriz de Equivalencia: Viabilidade

| Candidato oficial | Equivalencia | Motivo |
| --- | --- | --- |
| Rendimento | Nao | Rendimento mede kg produzido sobre peso vivo; Viabilidade mede aves viaveis sobre aves recebidas. |
| Eficiencia | Nao | Eficiencia mede produtividade horaria; Viabilidade mede perdas de aves. |
| Producao por OP | Parcial | Compartilha OPs e perdas, mas nao entrega ranking por motivo/setor nem indicador de viabilidade. |
| Producao por SKU | Nao | Viabilidade nao e por SKU. |
| Condenacoes | Parcial | Condenacoes e um componente de Viabilidade, nao o indicador completo. |
| Perdas | Parcial | Perdas compartilha eventos, mas nao substitui comparativo de viabilidade por fornecedor e evolucao do percentual. |
| Indicadores | Parcial | Pode consumir perdas oficiais, mas nao apresenta a ferramenta operacional de causa/setor/fornecedor. |
| Comparativos | Nao | Compara indicadores oficiais; nao substitui o diagnostico operacional. |
| Tendencias | Nao | Tendencia descritiva de indicadores; nao possui filtros operacionais equivalentes. |
| Dashboard Executivo | Parcial | Consolida leitura executiva, mas nao substitui a analise operacional detalhada. |
| CMV congelado | Nao | Sem relacao financeira ou custo de mercadoria vendida. |

Equivalencia total: **nao**.

Risco de redirecionamento: medio/alto. Redirecionar para Perdas ou Condenacoes apagaria a formula de viabilidade e parte dos filtros de decisao operacional.

Decisao: **Cenario B - ferramenta/relatorio operacional legitimo da Qualidade**, preservado fora da Biblioteca.

## Historico Git Relevante

Custos:

- `43018f8 Tempo por setor`
- `54b0a59 ajustes nos relatórios de custos`
- `a6b9b7a ajustes nos relatórios de custos`
- `0634d85 Backup antes Sprint 1.3 relatorio custos`
- `c48eda9 Sprint 2 filtros relatório custos`
- `9d4649b refactor(relatorios): extrai custos dre e relatorios`
- `b571e14 Cria biblioteca oficial de relatorios`

Viabilidade:

- `982f532 Relatório Viabilidade`
- `66a321f Relatório Viabilidade`
- `875b4dc Relatório Viabilidade`
- `db479f3 Ajusta apontamento de descartes`
- `758c3a0 refactor(qualidade): extrai módulo de qualidade`
- `c5a84b0 Consolida governanca da biblioteca de relatorios`

## Acao Recomendada

1. Preservar ambas as rotas.
2. Manter ambas fora da Biblioteca dos 38.
3. Nao redirecionar e nao usar 410.
4. Ajustar linguagem visual para reduzir confusao:
   - Custos: deixar claro que e analise de custos mensais cadastrados, nao DRE, Fluxo ou CMV.
   - Viabilidade: deixar claro que e ferramenta operacional da Qualidade, nao DRE, Fluxo ou CMV.
5. Atualizar teste de governanca para proteger classificacao, ausencia no catalogo e comportamento autenticado.

## Pendencias Humanas

- Decidir se Custos Mensais deve ser migrado para uma regra oficial futura, incorporado ao financeiro ou descontinuado apos transicao.
- Decidir se Viabilidade deve virar um item oficial em sprint futura, sem ultrapassar os 38 atuais nesta sprint.
- Definir se `criar_tabelas_custos()` em leitura GET deve ser removido em sprint tecnica especifica; nesta sprint nenhuma DDL foi alterada.
