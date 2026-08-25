# P1.3 — Reconciliação de estoque e relatórios operacionais

## Princípio e classificação

Esta Sprint separa explicitamente três semânticas:

- **Posição atual:** fotografia do saldo físico corrente. Não soma documentos nem eventos como nova origem.
- **Movimento histórico:** documento/evento imutável, incluindo documentos sem efeito líquido identificados pelo status.
- **Snapshot documental:** valores e linhas congelados na confirmação/emissão, independentes do cadastro ou saldo posterior.

Relatórios não movimentam estoque. Consultas, PDFs, CSVs e Excel auditados são operações de leitura.

## Inventário técnico auditado

| Relatório/tela | Tipo | Rota e formato | Fonte anterior | Fonte oficial/correta | Filtros e paginação | Status P1.3 |
|---|---|---|---|---|---|---|
| Estoque da Câmara | Posição atual | `/expedicao/estoque` (tela) e `/expedicao/estoque/relatorio-consolidado.pdf` | Consolidado oficial | `consolidar_estoque_camara` | Sem paginação; opção de incluir PNC no PDF | Conforme |
| Estoque Câmara Fria — biblioteca | Posição atual | `/relatorios/expedicao/estoque-camara-fria` (tela/Excel) | `pa_caixas`, somente pós-marco-zero e `LIMIT 300` | `consolidar_estoque_camara` | SKU, apresentação, situação e origem; cards sobre todo o conjunto filtrado | **Corrigido** |
| Consolidado por Produto | Posição atual | Bloco da tela da Câmara e PDF | Mesmo consolidado | `consolidar_estoque_camara` | Galinha Cortada: caixas/bandejas/kg; Inteira: galinhas/pacotes | Conforme |
| Transferências | Movimento histórico | `/relatorios/expedicao/transferencias` (tela/Excel) | `pa_movimentacoes` + `expedicoes` | Eventos `TRANSFERENCIA`, sem somar ao saldo corrente | Período, caixa, OP, SKU, lote, origem, destino, usuário e romaneio; detalhes limitados, totais SQL completos | Conforme; limitação de detalhe documentada |
| Histórico por caixa | Movimento histórico | `/relatorios/expedicao/historico-por-caixa` (tela/impressão) | `pa_movimentacoes` | Evento físico + documento relacionado | Caixa/OP/SKU/lote; consulta individual | Conforme |
| Expedições e romaneios comerciais | Movimento histórico | `/expedicao`, `/expedicao/historico`, `/expedicao/<id>`, impressão | `expedicoes`, itens ativos e eventos | Documento original; vínculo ao pedido é referência, não nova saída | Status/documento; sem recontar vínculo | Conforme após P1.2, revalidado |
| Pedidos e vínculos | Movimento comercial | `/pedidos-venda`, `/pedidos-venda/<id>`, PDF | Pedido, itens, atendimentos e vínculos | Pedido − entregue; reservado separado de entregue | Pedido/cliente/status; múltiplos romaneios não duplicam saída | Conforme após P1.2, revalidado |
| PNC Ativos/Finalizados | Posição atual + histórico | `/qualidade/produtos-nao-conformes` | `consultar_pa_nc` | Saldo físico remanescente canônico | Período, OP, lote, produto, motivo, status, local, responsável, destinação e situação; tabela paginada, cards completos | Conforme |
| CSV de PNC | Posição/histórico filtrado | `/qualidade/produtos-nao-conformes/exportar.csv` | `consultar_pa_nc` | Exatamente a mesma consulta e filtros da tela, sem paginação | Todos os filtros da tela, UTF-8 com BOM | Conforme |
| Romaneio individual de descarte | Snapshot documental | detalhe e PDF de descarte | `snapshot_json` | Snapshot imutável do documento | Por documento | Conforme |
| Consolidado de descarte | Movimento histórico líquido | lista e relatório PDF de romaneios de descarte | Documentos persistidos + snapshot | Somente `CONFIRMADO` totaliza; rascunho/cancelado/estornado são exceções sem efeito | Período/tipo de data, número, status, produto, apresentação, motivo, destino, motorista, placa e emissor | Conforme |
| Conferência Analítica da Embalagem Secundária | Snapshot documental | `/embalagem-secundaria/<op>/conferencia/relatorio.pdf` | Reconsulta das caixas correntes, embora IDs/totais estivessem confirmados | `snapshot_json` completo da confirmação | Documento congelado; caixas posteriores não entram | **Corrigido** |
| Produção por OP/SKU/fornecedor/período | Movimento produtivo | `/relatorios/producao/<slug>` (tela/Excel) | OP + apontamentos + PA | OP estornada/cancelada permanece na auditoria própria, mas é excluída do volume produtivo válido | Período, SKU, fornecedor, status e granularidade; totais SQL independentes do limite de detalhes | Conforme |
| Rendimento | Movimento produtivo válido | `/relatorios/producao/rendimento` (tela/Excel) | OPs encerradas | Somente `Encerrada`, caixas ativas e apontamentos vigentes | Período/SKU/fornecedor | Conforme |

Financeiro/DRE, OEE, Zebra e NiceLabel não foram alterados por estarem fora do escopo. A falha conhecida do benchmark financeiro acima de 45 segundos permanece registrada separadamente e não reprova esta Sprint.

## Fórmulas e fontes dos cards da Câmara

Todos os cards do relatório oficial da Câmara são somas das mesmas linhas projetadas pela fotografia filtrada:

- físico conforme = disponível + reservado;
- bloqueado = não conforme bloqueado + reprocessamento + aguardando liberação;
- físico total = conforme + bloqueado;
- disponível = físico total − reservado − bloqueado;
- legado e pós-marco-zero são origens da mesma posição, nunca uma terceira soma documental.

As unidades não são convertidas entre si: Galinha Cortada usa caixas, bandejas e kg; Galinha Inteira usa galinhas e pacotes. Cálculos de peso usam `Decimal` e o Excel recebe células numéricas.

## Divergências corrigidas

1. O relatório da biblioteca “Estoque Câmara Fria” ignorava saldo legado, pacotes e PNC, e seus detalhes eram truncados em 300 caixas. Ele agora projeta diretamente `consolidar_estoque_camara`; tela, cards, agrupamentos e Excel compartilham a mesma lista filtrada.
2. Filtros de caixa, OP, lote e validade, inadequados à fotografia agregada, foram retirados dessa tela. Foram adotados SKU, apresentação, situação e origem física.
3. A reimpressão da Conferência Analítica podia refletir caixas lançadas depois da confirmação. Novas confirmações persistem snapshot completo, e o PDF prefere esse snapshot.
4. Os relatórios produtivos já excluíam OP estornada/cancelada e caixas inativas; a regra foi coberta por teste explícito de regressão, sem criar cálculo paralelo.
5. A auditoria do pedido exibia snapshots JSON extensos como justificativa. A interface agora apresenta ação e resumo operacionais, incluindo número e ID do romaneio, enquanto o snapshot bruto permanece imutável no banco.

## Migration

Migration aditiva e reversível: `snapshot_json TEXT` em `embalagem_secundaria_conferencias`.

- PostgreSQL: `database/20260825_p1_3_snapshot_conferencia_embalagem.sql`
- PostgreSQL rollback: `database/20260825_p1_3_snapshot_conferencia_embalagem_rollback.sql`
- SQLite: `database/20260825_p1_3_snapshot_conferencia_embalagem_sqlite.sql`
- SQLite rollback: `database/20260825_p1_3_snapshot_conferencia_embalagem_sqlite_rollback.sql`

Não há backfill, hard delete ou alteração de saldo. Confirmações antigas continuam legíveis com os campos históricos existentes; novas confirmações passam a ter o snapshot completo.

## Índices e desempenho

Nenhum índice novo foi adicionado: não foi encontrada evidência que justificasse alteração de índice. A principal melhoria remove o relatório paralelo e o limite semântico de 300 linhas da posição atual; a consolidação oficial já agrega no banco e retorna poucas linhas por produto/situação.

## Reconciliação automatizada

`tests/test_p1_3_reconciliacao_relatorios.py` compara serviço, linhas de tela, cards, agrupamento e Excel, incluindo filtros e diferença de `0,001 kg`. Também verifica que o Excel contém números reais e que OP estornada é neutralizada sem desaparecer do histórico.
