# P1.1 — ciclo físico e documental de Produtos Não Conformes

## Fonte única de verdade

`saldo_fisico_remanescente()` é a fonte oficial de leitura para listagem, cards e CSV.
Ela usa os campos consolidados de `pa_nao_conformes` para inventário legado e após
baixa parcial, a posição corrente de `pa_caixas` para caixa rastreada e a quantidade
em `pnc_reprocessamentos` enquanto o material estiver fisicamente em processo.
Snapshots de romaneio são históricos e nunca são usados como saldo atual.

As grandezas permanecem separadas: Galinha Cortada usa caixas, bandejas e gramas;
Galinha Inteira usa pacotes e galinhas. Peso é convertido com `Decimal` e persistido
em gramas inteiras nos movimentos.

PNC ativo é, sem exceção, saldo físico remanescente maior que zero e estado aberto.
Estados terminais apresentam saldo remanescente zero no domínio do PNC, ainda que o
produto exista em outro domínio físico, como estoque operacional após liberação.

## Máquina de estados

| Estado atual | Ação | Estado seguinte | Efeito físico/documental |
| --- | --- | --- | --- |
| — | Criação no encerramento da OP | `BLOQUEADO` | Caixa é segregada e evento de criação/bloqueio é gravado na mesma transação. |
| `BLOQUEADO`/`MANTIDO_BLOQUEADO` | Iniciar avaliação | `EM_AVALIACAO` | Sem movimento físico; mantém bloqueio. |
| Estado aberto | Manter bloqueado | `MANTIDO_BLOQUEADO` | Sem movimento físico; decisão e justificativa ficam auditadas. |
| Estado aberto | Solicitar liberação | mesmo estado | Reserva peso legado em `saldo_pendente_g`; caixa rastreada permanece integral. |
| Solicitação pendente | Rejeitar | mesmo estado | Desfaz reserva, sem entrada operacional. |
| Solicitação pendente | Aprovar por segundo usuário | `LIBERADO` integral ou aberto parcial | Sai do bloqueio e entra no saldo operacional somente após aprovação. |
| Estado aberto | Destinar a descarte | `DESCARTE` | Mantém saldo bloqueado até a saída; liberação posterior é incompatível. |
| `DESCARTE` | Confirmar saída parcial | `DESCARTE_PARCIAL` | Movimento de saída reduz exatamente cada unidade bloqueada. |
| `DESCARTE`/`DESCARTE_PARCIAL` | Confirmar saída integral | `DESCARTADO` | Zera remanescente e preserva romaneio, snapshot, PDF e movimento. |
| Saída confirmada | Estornar romaneio | `DESCARTE`/`DESCARTE_PARCIAL` | Movimento inverso restaura apenas o bloqueio e reabre o PNC. |
| Rascunho | Cancelar romaneio | cancelado documentalmente | Sem efeito físico. Saída confirmada exige estorno. |
| Estado aberto | Iniciar reprocessamento | `REPROCESSO` | Parcela sai do bloqueio e entra em processo; solicitação de liberação incompatível é cancelada. |
| `REPROCESSO` | Concluir integral | `REPROCESSADO` | Quantidade em processo é consumida e o PNC finaliza. |
| `REPROCESSO` | Concluir parcial legado | `BLOQUEADO` | Parcela tratada fica no histórico; somente o remanescente volta à visão ativa. |
| `REPROCESSO` | Cancelar | `BLOQUEADO` | Restaura exatamente peso e controles auxiliares ao bloqueio. |

`RETRABALHO` continua sendo uma destinação integral existente. Não foi criada uma
movimentação genérica para ela porque o domínio atual não possui origem/destino
físico estruturado equivalente.

## Integridade e concorrência

Liberação, descarte e reprocessamento revalidam estado e saldo dentro da transação.
No PostgreSQL as linhas são selecionadas com `FOR UPDATE`; as atualizações também
usam comparação de estado e conferem `rowcount`. Chaves únicas impedem repetição de
início, solicitação e saída. Cancelamento e conclusão repetidos são idempotentes e
nenhum fluxo executa `DELETE` sobre PNC, eventos, solicitações, romaneios ou movimentos.

Para cada unidade aplicável, a reconciliação é:

`inicial = bloqueado atual + liberado + descartado líquido + reprocessado concluído + saldo em processo`

Solicitações pendentes são reserva dentro do bloqueado, não uma saída adicional.
