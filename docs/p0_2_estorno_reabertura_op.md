# P0.2 — Estorno e reabertura de ordem de produção

## Conceitos operacionais

**Reabrir OP** é uma correção operacional. A OP volta de `Encerrada` para `Aberta`, com destino explícito em Embalagem Secundária ou Conferência final. Produção, movimentos de PI, caixas e estoque PA permanecem válidos. A confirmação de conferência e os snapshots derivados deixam de ser atuais e devem ser refeitos antes do novo encerramento.

**Estornar OP integralmente** é uma anulação operacional. A OP passa para `Estornada`; caixas ativas são estornadas logicamente; saídas de PI usadas na formação das caixas recebem entradas compensatórias; entradas originais da Embalagem Primária recebem saídas compensatórias do tipo `SAIDA_ESTORNO_OP`; apontamentos automáticos deixam de ser vigentes. Nenhum movimento, caixa, composição ou apontamento é apagado.

## Matriz de estados

| Estado atual | Reabrir | Estornar integralmente | Encerrar | Observação |
|---|---:|---:|---:|---|
| Aberta | Não | Sim, após preflight | Sim, pelo fluxo de conferência | Reabertura seria ambígua |
| Aguardando Embalagem Secundária | Não | Sim, após preflight | Não diretamente | Estado legado aceito no estorno |
| Encerrada | Sim, após preflight | Sim, após preflight | Não | Único estado elegível para reabertura |
| Estornada | Não | Idempotente somente com a mesma chave | Não | Estado terminal operacional |
| Cancelada | Não | Não | Não | Estado terminal administrativo |

O sistema não cria novos estados de negócio. `versao_operacional` é apenas controle concorrente e de auditoria.

## Mapa de efeitos

| Recurso | Reabertura | Estorno integral |
|---|---|---|
| OP | `Encerrada → Aberta`, incrementa versão | `* → Estornada`, incrementa versão |
| Embalagem Primária | Preservada | Preservada como evidência; PI de entrada recebe compensação |
| Livro de PI | Preservado sem novo movimento | Movimentos originais preservados e compensados |
| Composição das caixas | Preservada | Preservada |
| Caixas PA | Preservadas no estado atual | Ativas passam a `Estornada`, sem exclusão |
| Estoque operacional PA | Preservado | Retirado logicamente das caixas estornadas |
| PNC | Preservado se ainda não destinado | Bloqueia o estorno; exige tratamento específico antes |
| Conferência de caixas | Confirmações anteriores invalidadas | Confirmações anteriores invalidadas |
| Apontamentos automáticos | Preservados | `vigente=0`, com usuário e data |
| Indicadores e relatórios | Continuam usando dados vigentes | OP estornada e apontamentos não vigentes são excluídos |
| Auditoria | Evento `REABERTURA` | Evento `ESTORNO_INTEGRAL` e eventos por caixa |

## Preflight e bloqueios

O preflight é somente leitura. A operação abre uma transação, bloqueia a OP e as caixas no PostgreSQL (`FOR UPDATE`), repete integralmente as validações e somente depois inicia mutações.

Bloqueios específicos incluem:

- caixa com composição de mais de uma OP;
- reserva operacional ativa ou quantidade reservada;
- vínculo com romaneio ou expedição;
- transferência ou outra movimentação posterior;
- ajuste, reprocessamento, descarte ou outro evento sucessor;
- PNC com destinação, liberação, descarte ou saldo destinado;
- PNC ativo no estorno integral (deve ser tratado antes);
- inconsistência entre composição da caixa e movimento original de saída de PI;
- feature flag desativada;
- alteração concorrente de estado ou versão.

PNC apenas bloqueado, sem destinação posterior, não impede a reabertura porque os registros e o estoque são preservados. Ele impede o estorno integral para evitar uma anulação parcial do fluxo de qualidade.

## Concorrência, idempotência e auditoria

- Perfis autorizados: `admin`, `pcp` e `gerencia`.
- Toda execução exige motivo, confirmação forte e chave de idempotência.
- `op_operacoes_auditoria.idempotency_key` é única.
- Repetição da mesma chave retorna o resultado armazenado, sem novos movimentos.
- Atualizações de estado usam compare-and-swap; qualquer mudança concorrente causa rollback integral.
- A auditoria registra identidade, perfil, IP, estado anterior/posterior, etapa, preflight e efeitos em JSON.

## Migração e rollback

Artefatos PostgreSQL e SQLite:

- `database/20260825_p0_2_estorno_reabertura_op.sql`
- `database/20260825_p0_2_estorno_reabertura_op_rollback.sql`
- `database/20260825_p0_2_estorno_reabertura_op_sqlite.sql`
- `database/20260825_p0_2_estorno_reabertura_op_sqlite_rollback.sql`

A migração é aditiva. O rollback remove apenas os índices, a tabela de auditoria e as colunas introduzidas pela P0.2; ele não tenta desfazer eventos operacionais já executados.

## Rollout e observabilidade

- `OP_REVERSAL_REOPEN_ENABLED=false` interrompe reabertura e estorno integral.
- `SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED=false` interrompe os estornos de caixas e, por consequência, o estorno integral.
- Falhas de preflight não geram mutação nem evento de sucesso.
- Para investigação, consultar `op_operacoes_auditoria`, `embalagem_secundaria_estornos`, `estoque_produto_intermediario` e `estoque_eventos` pela OP e pela chave idempotente.
