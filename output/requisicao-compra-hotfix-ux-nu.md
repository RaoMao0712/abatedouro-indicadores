# FRIGODATTA — Requisição de Compra — Hotfix UX/NU

## 1. SHA inicial

`34dbfd76028e8e274f605d998da8e61e6ba69f9f`.

## 2. Branch

`codex/melhoria-romaneio-multiplas-ops`; backup remoto pré-release em `backup/pre-rc-ux-nu-20260919`.

## 3. Auditoria

Templates, rotas, service, modelo, migrations, PDF, eventos, permissões e CSS foram auditados. A arquitetura do módulo foi preservada, sem Cotação, Pedido, Recebimento ou integração financeira.

## 4. Alterações UX

Formulário, listagem e detalhe foram reorganizados com menos ruído, labels explícitos, espaçamento consistente e ações secundárias discretas.

## 5. Formulário dinâmico

Cada tipo de origem exibe somente seus campos relevantes. IDs internos continuam no backend e não são digitados pelo usuário.

## 6. Coerência de reposição

O material de reposição determina a origem e o item correspondente; a validação também existe no service.

## 7. Listagem

Filtros receberam labels, status usa badge leve, origem/solicitante foram compactados e a NU aparece como `—`, valor único ou quantidade de NUs.

## 8. Hierarquia visual

`Nova RC` e ações contextuais são primárias; `Filtrar`, `Limpar`, PDF e navegação são secundárias; cancelamento não compete com a ação principal.

## 9. Modelo de NU

`nu` pertence exclusivamente a `requisicao_compra_itens`, é textual, nullable e preserva zeros à esquerda.

## 10. Migration

Migration oficial adiciona apenas `nu TEXT NULL`, com apply/rollback/reapply compatíveis com PostgreSQL e SQLite.

## 11. Validação numérica

Regex de somente dígitos, limite de 30 caracteres. Letras, espaços, sinais, pontuação, vazio e símbolos são rejeitados; `001234` é preservado.

## 12. Aplicação a todos

Uma operação transacional atualiza todos os itens elegíveis e gera um único evento lógico.

## 13. Aplicação aos selecionados

Checkboxes enviam IDs; o backend valida pertencimento, elegibilidade, estado, perfil e versão.

## 14. Alteração de NU

Substituição é permitida somente em RC aprovada, com confirmação quando já há NU e preservação do histórico anterior.

## 15. Auditoria

Eventos amigáveis `NU_APLICADA` e `NU_ALTERADA` registram modo, itens, valores, usuário e data/hora.

## 16. Idempotência

Chave de idempotência impede repetição da operação e duplicação do evento; retry convergente foi testado.

## 17. Concorrência

Versão otimista e `FOR UPDATE` impedem lost update. O cenário concorrente foi validado em PostgreSQL real descartável.

## 18. Permissões

Perfis autorizados: `admin`, `gerencia` e `pcp`. O solicitante não é requisito; autoaprovação continua bloqueada.

## 19. PDF

A coluna NU foi adicionada e rebalanceada. QA cobriu 55 itens, cinco páginas, descrições longas e NU de 30 dígitos. A produção exibiu `567890` e `001234` sem sobreposição.

## 20. Performance

Aplicação em massa usa transação única, carregamento agregado e atualização em lote, sem commit por item nem evento por linha.

## 21. Testes

- RC + Etapa C: 41 aprovados.
- PostgreSQL RC: 16 aprovados.
- Regressões isoladas: OS 15, Almoxarifado 9, SGI 12, navegação 18; total 54 aprovados.
- Compilação Python, templates e inspeção de diff: aprovadas.
- A execução combinada em banco compartilhado apresentou 15 ocorrências classificadas `FIXTURE_ISOLAMENTO`; todas as suítes isoladas passaram.

## 22. PostgreSQL

PostgreSQL 17.11 descartável, porta 55432: apply, rollback e reapply aprovados, com preservação dos dados; 16 testes passaram.

## 23. Regressão

Nenhuma regressão real encontrada em RC, OS, Almoxarifado, Qualidade, navegação, PDF ou migrations.

## 24. Invariantes

NU não altera status por si, estoque, lotes, reservas, movimentos, Financeiro, CMV, DRE ou contas a pagar.

## 25. Commits

- `8537668690cf5c976d0388c874e6764f998feddc` — implementação do hotfix.
- `ed14ef7fca0dd140a97d1cb9a341aadaee2d9e2b` — refinamento visual final.

## 26. Migration produtiva

Aplicada em PostgreSQL 18.4 em 109,5 ms. A coluna ficou `YES/text`; a RC existente e seu item permaneceram, com NU nula. PITR de sete dias foi confirmado antes da execução.

## 27. Deploy

- Implementação: `dep-dange1u8bjmc73aikni0`, Live, 1m58s.
- Refinamento visual: `dep-danvbccs728c73b6o26g`, Live, 2m05s.

## 28. Homologação visual

Nova RC, origem dinâmica, seletores, listagem, filtros, badges, botão principal, detalhe, ações contextuais e responsividade desktop foram validados na aplicação produtiva.

## 29. Homologação NU

RC controlada `RC-000002`: criada com dois itens, enviada por Thiago, autoaprovação corretamente bloqueada e auditada, aprovada por usuário Administrador independente, NU `001234` aplicada a todos, item A alterado para `567890`, resumo `2 NUs`, histórico e PDF conferidos. A RC foi cancelada ao final sem apagar seu histórico.

## 30. Logs

Deploys concluíram Live sem falha de build/migration. Durante a homologação não houve 5xx, erro SQL, `IntegrityError`, falha de template/PDF, deadlock ou timeout perceptível.

## 31. Limpeza

Cluster PostgreSQL descartável foi parado e removido; porta 55432 ficou livre. Os PDFs/PNGs temporários de QA foram removidos ao final. Nenhum worktree ou clone temporário foi criado.

## 32. Estado final

`origin/main` e HEAD em `ed14ef7fca0dd140a97d1cb9a341aadaee2d9e2b` antes deste relatório. `abatedouro.db`, `entregas/` e artefatos antigos de `output/` foram deliberadamente preservados por serem anteriores à Sprint. Estoque/Financeiro permaneceram nos totais de referência 50/72/0 e a RC controlada ficou `CANCELADA` com NUs e eventos preservados.

REQUISIÇÃO DE COMPRA — HOTFIX UX/NU CONCLUÍDO: FORMULÁRIO E LISTAGEM REFINADOS, CAMPO NU POR ITEM IMPLEMENTADO COM APLICAÇÃO EM MASSA, PDF ATUALIZADO E PRODUÇÃO HOMOLOGADA
