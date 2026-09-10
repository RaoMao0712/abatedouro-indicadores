# P3.5 — Requisições de Almoxarifado — Etapa A

## 1. Escopo auditado

Esta etapa registra a auditoria e o desenho técnico anteriores à implementação das requisições formais de almoxarifado. O escopo permanece restrito à reserva, aprovação de exceções, confirmação da entrega física, baixa rastreável, cancelamento, estorno compensatório, impressão e indicadores de consumo por requisição.

Ficam explicitamente fora desta sprint a baixa automática por Ordem de Produção, aplicativo móvel, assinatura eletrônica, exclusão de históricos e redesign amplo do estoque.

## 2. Estado atual confirmado

### Código e dependências

- A base da sprint é o commit `bc14c4af69b2496a38682f7e489b663887424dc9` de `origin/main`.
- O Almoxarifado já possui cadastros de insumos, lotes, entradas, correções, movimentações e relatórios de saldo/rastreabilidade.
- O saldo físico é representado por `almoxarifado_lotes.quantidade_atual`; não existe hoje uma camada de reserva.
- As movimentações já guardam usuário, data, lote, quantidade, custo e origem, mas ainda não possuem vínculo formal com requisição, item, solicitante, saldos anterior/posterior ou movimento estornado.
- Parceiros já expõem consulta de pessoas elegíveis ativas com papel `COLABORADOR_CLT` ou `PRESTADOR_SERVICOS`.
- A autorização existente admite PCP e Admin nas rotas de almoxarifado; o perfil Admin satisfaz permissões de outros perfis.
- O módulo de Qualidade contém um padrão reutilizável de aprovação transacional, idempotência, bloqueio de autoaprovação e auditoria.
- A navegação do Almoxarifado ainda não possui entrada de Requisições.
- Os relatórios atuais interpretam `SAIDA` como consumo e `ENTRADA` como reposição, permitindo manter compatibilidade usando a origem para qualificar a nova movimentação.

### Produção — fotografia anterior à implementação

Leitura autenticada e somente leitura realizada no serviço produtivo do Render, instância no commit `bc14c4a`:

| Evidência | Resultado |
|---|---:|
| Insumos cadastrados | 17 |
| Insumos ativos | 17 |
| Lotes | 17 |
| Lotes abertos | 17 |
| Movimentações | 17 |
| Movimentações por tipo/origem | 17 `ENTRADA` / `Entrada manual` |
| Lotes com saldo negativo | 0 |
| Parceiros ativos elegíveis | 1 |
| Usuários Admin | 3 |
| Usuários Gerência | 0 |
| Embalagens | 9 |
| EPI | 7 |
| Matérias-primas | 1 |
| Quantidade física agregada | 115.895,06 |
| Valor agregado do estoque | 87.881,695 |
| Tabelas de requisição preexistentes | 0 |

Não há saídas históricas a converter nem consumo anterior de requisições a inventar. Os dez itens de Embalagem/Matéria-prima serão classificados como consumo oficial por Ordem de Produção; os sete EPI serão classificados como consumo oficial por Requisição de Almoxarifado.

## 3. Modelo de dados aprovado para implementação

### Insumos

Adicionar `origem_baixa` a `almoxarifado_insumos`, com valores controlados:

- `REQUISICAO_ALMOXARIFADO`: consumo geral;
- `ORDEM_PRODUCAO`: Embalagem e Matéria-prima.

O backfill será determinístico pela categoria atual, idempotente e sem alterar históricos.

### Requisição

Criar `almoxarifado_requisicoes` com número único, parceiro solicitante, retrato imutável do nome e papel do solicitante, setor, finalidade, justificativa, indicador de exceção, estado, versão, idempotência, emissão, aprovação/rejeição, confirmação, cancelamento, estorno e respectivos usuários e horários.

Criar `almoxarifado_requisicao_itens` com vínculo ao insumo e snapshots imutáveis de descrição, categoria, unidade e origem oficial, além das quantidades solicitada, reservada, entregue e baixada e do estado do item.

Criar `almoxarifado_requisicao_alocacoes` para registrar a alocação exata por lote, quantidade, custo e movimentação. Essa tabela permitirá baixa FIFO verificável e estorno no mesmo lote e valor.

Criar `almoxarifado_requisicao_eventos` como trilha append-only de ações, estados, detalhes, usuário, perfil e horário.

Estender `almoxarifado_movimentacoes` de forma aditiva com vínculos à requisição, item e parceiro, saldos anterior/posterior, movimento original estornado e chave de idempotência.

## 4. Estados e transições

| Estado | Transição permitida |
|---|---|
| `AGUARDANDO_APROVACAO` | aprovar, rejeitar ou cancelar |
| `EMITIDA` | confirmar entrega ou cancelar |
| `BAIXADA` | estornar |
| `PARCIALMENTE_ATENDIDA` | estornar |
| `REJEITADA` | terminal |
| `CANCELADA` | terminal |
| `ESTORNADA` | terminal |

Requisição comum nasce `EMITIDA`. Requisição que contenha item cuja origem oficial seja Ordem de Produção nasce `AGUARDANDO_APROVACAO` e deve trazer finalidade e justificativa. A emissão reserva, mas não reduz o saldo físico.

A confirmação aceita entrega integral ou parcial. Na entrega parcial, somente o efetivamente entregue é baixado e toda reserva remanescente é liberada; a requisição passa a `PARCIALMENTE_ATENDIDA`, sem reabertura silenciosa.

O cancelamento libera a reserva e não cria movimento físico. O estorno nunca exclui nem edita a saída original: cria entrada compensatória ligada a ela e restaura exatamente os lotes alocados.

## 5. Permissões e segregação

- PCP e Admin podem emitir requisições comuns.
- Somente Admin pode solicitar exceção para item de origem `ORDEM_PRODUCAO`.
- Admin ou Gerência podem aprovar/rejeitar exceções.
- O aprovador deve ser uma identidade diferente do emissor; autoaprovação é bloqueada em serviço e auditada.
- PCP e Admin podem confirmar entrega e cancelar requisição emitida.
- Estorno exige Admin ou Gerência e justificativa obrigatória.
- O solicitante deve ser Parceiro ativo elegível no instante da emissão; seus dados relevantes ficam congelados na requisição.

A produção possui três usuários Admin e nenhum usuário Gerência, portanto a segregação é operacionalmente viável entre dois Admin distintos.

## 6. Reserva, concorrência e baixa

O disponível será calculado como saldo físico dos lotes abertos menos reservas de itens em estados ativos (`EMITIDA` e, após aprovação, requisições excepcionais emitidas).

Emissão, aprovação, confirmação, cancelamento e estorno serão transações atômicas. A implementação usará versão otimista da requisição, chaves de idempotência e bloqueios compatíveis com o banco disponível. A confirmação validará novamente o saldo, alocará FIFO por lote e produzirá uma movimentação por lote:

- `tipo = SAIDA`;
- `origem = SAIDA_REQUISICAO_ALMOXARIFADO`.

O estorno produzirá:

- `tipo = ENTRADA`;
- `origem = ESTORNO_SAIDA_REQUISICAO`;
- vínculo com a movimentação original.

Nenhum lançamento financeiro será criado: o valor sai e retorna pelos próprios lotes, evitando duplicidade de despesa ou CMV.

## 7. Documento e imutabilidade

O documento imprimível seguirá a identidade FrigoDatta e mostrará número, estado, emissão, solicitante, papel, setor, finalidade, itens, quantidades, unidades e campos de assinatura/entrega. Requisições excepcionais terão aviso explícito e justificativa. O documento será reconstruído pelos snapshots da requisição e dos itens, não pelos cadastros mutáveis atuais.

## 8. Rastreabilidade, filtros e indicadores

A consulta histórica permitirá filtrar por número/requisição, item, período, solicitante e tipo/origem. Cada saída exibirá requisição, item, parceiro, emissor, aprovador quando aplicável, confirmador, horários, lote, quantidade, custo e saldos anterior/posterior.

Para giro e cobertura:

- janela padrão: 30 dias corridos;
- apenas saídas confirmadas de requisições comuns compõem consumo por requisição;
- exceções de itens produtivos aparecem separadamente e não viram consumo produtivo por OP;
- disponibilidade, e não saldo físico bruto, é o numerador da cobertura;
- exigir no mínimo 7 dias corridos desde o primeiro consumo confirmado e 2 dias distintos com consumo;
- antes disso: `N/A — histórico insuficiente`;
- histórico suficiente sem consumo na janela: `N/A — sem consumo no período`;
- consumo positivo com disponibilidade zero: cobertura igual a zero.

Essas regras não retroagem nem fabricam consumo anterior.

## 9. Riscos e controles definidos

| Risco | Controle |
|---|---|
| Saldo negativo por concorrência | transação, revalidação no momento da confirmação e atualização condicionada do lote |
| Dupla confirmação/reenvio | versão, estado terminal e chave de idempotência |
| Reserva acima do disponível | cálculo transacional de reservas ativas e validação por item |
| Autoaprovação | comparação obrigatória entre emissor e aprovador |
| Exceção produtiva sem governança | perfil Admin, justificativa/finalidade e aprovação distinta |
| Perda de rastreabilidade por edição cadastral | snapshots imutáveis |
| Estorno destrutivo | movimento compensatório ligado ao original |
| Duplicidade contábil | nenhuma integração financeira nesta sprint |
| Indicador enganoso com pouco histórico | estados `N/A` explícitos e limiar mínimo de evidência |

## 10. Conclusão da Etapa A

A auditoria encontrou uma base compatível com evolução aditiva, sem conflitos de modelo nem dados produtivos que exijam conversão destrutiva. A fotografia produtiva foi registrada, os papéis e estados foram fechados, as regras de reserva/baixa/estorno foram definidas e os critérios de segurança, custo, impressão e indicadores foram aprovados para implementação.

**ETAPA A CONCLUÍDA — IMPLEMENTAÇÃO LIBERADA SEM AMPLIAÇÃO DE ESCOPO.**
