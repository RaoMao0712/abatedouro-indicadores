# P1.2 — Integridade de Expedição, Reservas, Romaneios e Pedidos

## Identificação

- Data da auditoria e implementação: 25/08/2026 (America/Manaus).
- Commit inicial de `origin/main`: `82b3715331d84c65c314f723630bd5756e5feab3`.
- Branch: `codex/p1-2-integridade-expedicao`.
- Backup lógico anterior à sprint: `backup/pre-p1-2-integridade-expedicao-20260825`.
- Escopo: estabilização do fluxo existente, sem nova funcionalidade comercial.

## Mapa do domínio

| Entidade/ação | Cria movimento físico? | Reserva saldo? | Baixa saldo físico? | Pode ser estornada? |
| --- | --- | --- | --- | --- |
| Estoque físico (`pa_caixas`/legado agregado) | É a fotografia física | Não | Não | Somente pelo documento que o alterou |
| Reserva em romaneio aberto | Não | Sim | Não | É liberada por remoção/cancelamento |
| Pedido de venda | Não | Não automaticamente | Nunca | Cancela somente demanda pendente |
| Item de pedido | Não | Recebe a leitura da reserva física vinculada | Nunca | Segue pedido/atendimento |
| Romaneio aberto | Não | Seus itens reservam | Não | Cancelável antes da efetivação |
| Conclusão de romaneio | Sim | Consome a reserva | Sim, uma vez | Sim, por estorno |
| Vínculo romaneio ↔ pedido | Não | Não | Nunca | Seu efeito comercial é revertido no estorno |
| Atendimento comercial | Não | Não | Não | Sim, junto com o romaneio |
| Cancelamento de romaneio aberto | Não | Libera | Não | Idempotência por estado |
| Estorno de romaneio concluído | Movimento inverso | Não | Restaura exatamente o físico | Duplo estorno é bloqueado |
| Transferência | Sim na conclusão | Reserva enquanto aberta | Sim | Sim |
| Inventário/marco zero | Registra origem física controlada | Não | Não por pedido | Conforme regra documental |
| Ajuste | Sim, quando autorizado pelo domínio | Não | Pode corrigir físico | Exige trilha própria |
| PNC bloqueado | Continua físico, mas segregado | Não para venda | Não por venda | Liberação/reprocesso/descarte próprios |
| Estoque legado agregado | É saldo físico segregado | Sim no romaneio | Sim na conclusão | Sim |
| Estoque pós-marco-zero | É saldo físico unitário | Sim no romaneio | Sim na conclusão | Sim |

## Fonte única e unidades

O saldo operacional segue `Disponível = Físico - Reservado - Bloqueado`. Pedido, quantidade solicitada, snapshot e histórico não substituem o saldo físico. Itens PNC ou em reprocessamento/descarte não compõem o disponível comercial.

- Galinha Cortada: caixas, bandejas e kg são reconciliados sem conversão por média.
- Galinha Inteira c/1: pacotes e galinhas, fator exato 1.
- Galinha Inteira c/2: pacotes e galinhas, fator exato 2.
- Apresentações e unidades distintas não compensam excesso entre si.

## Regras estabilizadas

1. Reserva: somente produto `CONFORME` e `DISPONIVEL` entra em venda/transferência normal. A reserva reduz o disponível, preserva o físico e é protegida por transação, revalidação e bloqueio de linha no PostgreSQL.
2. PNC: somente produto `NAO_CONFORME` e `BLOQUEADO` entra nos romaneios PNC autorizados. Estado `REPROCESSAMENTO` não é interpretado como disponível, mesmo quando a condição persistida for inconsistente.
3. Pedido: registra demanda e saldo comercial; nunca efetua baixa física. A tela calcula, a partir de itens ativos de romaneios abertos, os estados Pendente de estoque, Parcialmente reservado e Totalmente reservado.
4. Romaneio: reserva enquanto aberto e efetiva a baixa física somente na conclusão oficial. Cancelamento é permitido antes da baixa; documento concluído exige estorno.
5. Vínculo posterior: aceita somente Venda Direta concluída, compatível e ainda não vinculada; consome exclusivamente saldo comercial. O lote múltiplo é atômico, idempotente e validado pelo agregado de produto, apresentação e unidade.
6. Estorno: restaura o físico, marca atendimentos como estornados, recalcula entregue/saldo/status do pedido e remove o vínculo ativo do documento na mesma transação. As tabelas históricas de vínculo e eventos permanecem preservadas.
7. Exclusão: remoções de itens de romaneio aberto agora são lógicas (`ativo=0`) e registram data, usuário e motivo. Leituras operacionais ignoram itens inativos; a trilha permanece disponível.
8. Legado: reserva agregada verifica o `rowcount` do débito condicional, evitando que uma disputa concorrente gere item sem saldo. Consolidado e ações de PNC consideram somente itens ativos.

## Achados e correções mínimas

- Pacotes conformes em estado de reprocessamento podiam inflar o card disponível: o card agora exige estado operacional disponível/reservado.
- Caixa bloqueada e conforme podia entrar em venda normal: validação alterada para combinação exata de condição e disponibilidade.
- Reserva agregada legada não confirmava o sucesso do débito atômico: incluída validação de linha alterada.
- Remoções usavam `DELETE`: substituídas por inativação auditável.
- Operações críticas não bloqueavam o documento no PostgreSQL: incluído `FOR UPDATE` em reservar, remover, concluir, cancelar e estornar.
- Estorno comercial deixava o vínculo ativo no romaneio: o vínculo operacional agora é limpo depois da restauração do pedido.
- Pedido não expunha estado real da reserva: incluídos estado calculado e quantidade reservada por item.

## Migration

- PostgreSQL: `database/20260825_p1_2_integridade_expedicao.sql`.
- Rollback PostgreSQL: `database/20260825_p1_2_integridade_expedicao_rollback.sql`.
- SQLite de teste: versões `_sqlite.sql` e `_sqlite_rollback.sql`.
- Natureza: quatro colunas aditivas e um índice; sem backfill pesado, recálculo de saldo ou exclusão de dados.
- A inicialização da aplicação também aplica as colunas com `IF NOT EXISTS`, tornando o deploy repetível.

## Matriz de validação

| Grupo solicitado | Cobertura |
| --- | --- |
| Reserva 1–7 | reserva integral/parcial, insuficiência, concorrência, remoção/cancelamento e não negatividade |
| Pedido 8–13 | confirmação sem baixa, pedido sem estoque, estados calculados, saldo pendente e cancelamento |
| Romaneio 14–20 | Venda Direta, baixa oficial, parcial, múltiplos itens, insuficiência, cancelamento e estorno |
| Vínculo 21–36 | um/vários/todos, incompatibilidades, estados inválidos, excesso individual/agregado, rollback, idempotência e ausência de nova baixa |
| Estorno 37–44 | vinculado/não vinculado, físico e pedido restaurados, status e duplo estorno |
| PNC 45–49 | bloqueado/reprocessamento/descarte fora do disponível, liberação controlada e finalizados fora dos cards |
| Legado/marco zero | origem rastreável, ausência de dupla contagem e reserva agregada concorrente |
| Telas/relatórios | cards, consolidado da câmara, pedido, romaneio e histórico usam itens operacionais ativos |

## Reconciliações de referência

- Reserva: físico 1.000; reservado 300; bloqueado 100 → disponível 600. Remover a reserva retorna reservado a 0 e disponível a 900, sem alterar físico.
- Vínculo múltiplo: pedido 1.000; romaneios concluídos 300 + 450 → entregue 750 e saldo comercial 250; eventos físicos adicionais no vínculo: 0.
- Estorno vinculado: físico após saída 250; estorno de 750 → físico 1.000; entregue retorna a 0 e saldo comercial a 1.000, sem apagar histórico.
- Pacote c/2: 400 pacotes representam exatamente 800 galinhas; nenhum cálculo por peso médio participa da reconciliação.

## Homologação pós-deploy (somente leitura)

1. Confirmar o commit implantado e HTTP 200.
2. Abrir Estoque da Câmara e comparar físico, reservado, bloqueado e disponível por apresentação/unidade.
3. Abrir pedidos existentes e conferir estado/quantidade reservada, entregue e saldo.
4. Abrir romaneios abertos, concluídos, cancelados e estornados; conferir itens, origem e histórico sem executar ações.
5. Verificar logs da implantação e navegação, buscando erro 500/traceback.
6. Não criar, alterar, cancelar, vincular ou estornar dados reais durante o smoke test.
