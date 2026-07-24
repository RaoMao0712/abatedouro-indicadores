# Expedição — marco zero do estoque

## Comportamento auditado antes da alteração

- Galinha Inteira encerrava na Embalagem Primária e gerava um registro agregado
  `GI-OP-*`, cuja quantidade representava unidades vendáveis e cujo peso era
  usado no rendimento.
- Galinha Cortada passava pela Embalagem Secundária e gerava caixas `CX-*`
  individualizadas, com composição por uma ou mais OPs.
- O caminho de pesagem da OP também gerava caixas `OP*-CX*`.
- A transferência existente mudava o local para Câmara Fria LSM, mas mantinha
  o campo de situação como `Em estoque`.
- Não existiam reserva exclusiva, condição de não conformidade, estorno com
  restauração de estado nem separação entre PA histórico e estoque operacional.

## Decisão implementada

O marco `MARCO_ZERO` é persistido em `estoque_marcos` com maior ID de OP
existente, usuário, data/hora e fuso de Manaus. Todas as OPs até esse ID são
marcadas `LEGADA`; novas OPs recebem `POS_MARCO`.

O PA histórico é preservado, classificado como `LEGADO` e excluído das consultas
operacionais. PA novo nasce `PENDENTE_OP` e somente vira `DISPONIVEL` quando
todas as OPs de sua composição são pós-marco e estão encerradas. A chave
`FORMACAO-PA-{id}` torna a formação idempotente.

As unidades operacionais originais foram mantidas:

- Galinha Inteira: lote agregado por OP;
- Galinha Cortada: caixa física, inclusive composição multi-OP;
- Pesagem da OP: caixa física.

Nenhuma conversão entre SKUs foi criada.

## Movimentação e auditoria

Romaneios abertos reservam o item de forma exclusiva. Conclusão, cancelamento e
estorno usam transação e registram estado anterior, novo estado, condição,
quantidade, peso, usuário, perfil, data/hora e justificativa em
`estoque_eventos`.

Produtos Não Conformes mantêm SKU, OP, lote, quantidade e peso, mas ficam na
zona segregada e fora do disponível. Descarte, devolução e transferência
autorizada exigem romaneio específico.

O romaneio `MZ-*` registra apenas os totais declarados da transferência
histórica e não escreve em Produção, Rendimento, Financeiro ou DRE.

## Reversão

O arquivo `database/20260724_marco_zero_estoque_rollback.sql` remove apenas a
camada estrutural desta sprint. Antes de executá-lo, exportar a trilha de
auditoria. OPs, apontamentos, caixas e composições históricas não são excluídos.
