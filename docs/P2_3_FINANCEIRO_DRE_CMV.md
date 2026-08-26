# P2.3 — Financeiro, DRE e CMV

## Mapa financeiro e datas oficiais

| Entidade | Fonte oficial | Natureza | Data oficial | Efeito na DRE |
|---|---|---|---|---|
| Receita faturada | `movimentacoes_financeiras` classificada como Receita Bruta | Entrada documental | `data_documento` | Receita Bruta |
| Receita recebida | baixa da movimentação financeira | Entrada de caixa | `data_realizacao` | Nenhum; Fluxo de Caixa |
| Despesa incorrida | `movimentacoes_financeiras` com conta estruturada | Saída documental | `data_documento` | Deduções, Despesas Operacionais ou Não Operacional conforme Plano |
| Despesa paga | baixa da movimentação financeira | Saída de caixa | `data_realizacao` | Nenhum; Fluxo de Caixa |
| Título em aberto / aging | movimentação não liquidada | Direito/obrigação | `data_vencimento` | Nenhum efeito temporal adicional |
| CMV | `cmv_eventos` + `cmv_consumos` | Custo da venda | `data_evento` da saída elegível | CMV somente com camada oficial |
| Estoque valorizado | saldo das `cmv_camadas` | Ativo gerencial | data da camada | Não entra na DRE até a venda |
| Descarte | evento `DESCARTE` | Perda | data do descarte | Fora do CMV de venda; aguarda conta gerencial oficial |

Fluxo de Caixa usa realização; previsão e aging usam vencimento; DRE usa competência documental. Pedido e romaneio não são receita por si mesmos. A fonte única de Receita Bruta é a movimentação financeira classificada, impedindo somar pedido, romaneio e importação da mesma venda.

## Plano de Contas e DRE

O Plano Mestre mantém Receita Bruta, Deduções, CMV, Despesas Operacionais, Resultado Não Operacional e Neutro. Lançamento manual novo exige conta, grupo e linha DRE estruturados. Compras formadoras de estoque permanecem no grupo CMV e não são absorvidas automaticamente como despesa operacional. A DRE é calculada em `modules/dre/services.py`; tela, resumo e exportação reutilizam o mesmo serviço.

Estrutura: Receita Bruta − Deduções = Receita Operacional Líquida − CMV = Margem Bruta − Despesas Operacionais = Resultado Operacional ± Resultado Não Operacional = Resultado Líquido Gerencial.

## Regra de CMV e calculabilidade

O método oficial é FIFO por produto e unidade. Entradas explícitas criam camadas; vendas consomem as mais antigas em transação; estorno restaura exatamente as camadas consumidas. Descarte consome valor, mas fica fora do CMV de venda. Nenhuma operação do subledger altera estoque físico.

Estados:

- `CALCULAVEL`: 100% da quantidade líquida possui custo conhecido, inclusive custo zero explicitamente informado;
- `PARCIAL`: há custo conhecido para parte da quantidade;
- `NAO_CALCULAVEL`: não há cobertura oficial;
- `INCONSISTENTE`: reservado a divergência estrutural detectada.

Margem Bruta e resultados dependentes ficam `N/A` quando o CMV não é integralmente calculável. O valor parcial conhecido e a cobertura continuam auditáveis no relatório de CMV. Saldo físico legado não é retrovalorizado; deve ser reconciliado por importação explícita futura.

## Fontes de custo auditadas

O Almoxarifado possui lote, quantidade, valor unitário e consumo por OP para matéria-prima/insumos. Entretanto, a base histórica não assegura vínculo completo entre todos os custos industriais, toda saída de produto acabado e sua venda. Parâmetros legados por SKU não constituem custo histórico e não alimentam mais a DRE. Mão de obra e manutenção de veículos permanecem nas contas aprovadas, sem reclassificação automática para custo industrial.

## Idempotência, concorrência e auditoria

Camadas e eventos possuem chave única. O consumo e o estorno executam em transação; PostgreSQL bloqueia linhas elegíveis com `FOR UPDATE`. A restauração é única por evento original. Criação, consumo, estorno e descarte registram trilha em `cmv_auditoria`. Importadores financeiros existentes mantêm lote, linha, origem e `import_key`; reclassificação mantém estado anterior/posterior na auditoria financeira.

## Limitações declaradas

- Não há backfill de custo histórico.
- Receita não vinculada a evento quantitativo de CMV pode aparecer na DRE com CMV `N/A`.
- Descarte não é lançado automaticamente em conta financeira até existir regra gerencial aprovada.
- A reconciliação automática completa por OP depende de cobertura oficial de todos os componentes industriais e do vínculo inequívoco OP–produto–venda.
