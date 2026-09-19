# Requisição de Compra — Etapa C.3 — Homologação PostgreSQL real

## 1. Estado inicial e isolamento

- SHA inicial / commit Etapa C: `15d47441171f5d0b122d733463e21deac43ec23c`.
- Commit Etapa B: `f7b1c7117353c4327f528dfc1616d689dd73a5f7`.
- Branch: `codex/melhoria-romaneio-multiplas-ops`.
- PostgreSQL: 17.11, x86_64 Windows, MSVC 19.44.
- Host/porta/database/usuário: `127.0.0.1:55432/frigodatta_rc_c3`, usuário `frigodatta_test`.
- URL sanitizada: `postgresql://frigodatta_test:***@127.0.0.1:55432/frigodatta_rc_c3`.
- Cluster temporário: `%TEMP%/frigodatta-rc-c3-a3fde257ea83448d8955dd760f709127/pgdata`.
- A instância preexistente na porta 5433 permaneceu em outro PID e não foi conectada, parada ou modificada.
- A senha temporária não foi registrada. `DATABASE_URL` produtiva não foi configurada; cada subprocesso de teste recebeu apenas `TEST_DATABASE_URL`, e a própria suíte a projetou internamente para o driver da aplicação.

## 2. Migration, rollback e schema

A migration `20260919_requisicoes_compra.sql` foi aplicada em schema-base descartável, reaplicada sem erro, revertida por `20260919_requisicoes_compra_rollback.sql` e aplicada novamente. A tabela-sentinela do schema-base permaneceu intacta após rollback.

Objetos confirmados:

- tabelas `requisicoes_compra`, `requisicao_compra_itens` e `requisicao_compra_eventos`;
- sequences próprias para os três IDs;
- PKs das três tabelas;
- UNIQUE em `requisicoes_compra.numero`, `requisicoes_compra.chave_criacao` e `requisicao_compra_eventos.idempotency_key`;
- índices `idx_rc_origem`, `idx_rc_status_data`, `idx_rc_solicitante` e `idx_rc_item_material`;
- `versao INTEGER NOT NULL DEFAULT 0` e tipos/nullability da migration aceitos pelo PostgreSQL 17.

A migration atual não declara FKs ou CHECKs de domínio; não foram inventadas constraints novas durante homologação.

## 3. Numeração, locks e concorrência

- Numeração sequencial confirmada como `RC-{id:06d}`: `RC-000001`, `RC-000002`.
- Criações simultâneas com chaves diferentes produziram IDs e números distintos.
- Rollback após consumo de sequence produziu apenas gap aceitável, sem número vazio ou duplicado.
- Um backend segurando `SELECT ... FOR UPDATE` bloqueou efetivamente a decisão no segundo backend até o commit.
- Aprovação × cancelamento e aprovação × rejeição, com mesma versão e chaves diferentes: uma única ação venceu; a outra falhou por versão/estado; versão final 2; um único evento terminal.
- Edição × envio: uma única operação venceu e nenhuma quantidade editada foi perdida silenciosamente.

## 4. Idempotência e item provisório

- Criação simultânea com a mesma `chave_criacao`: uma única RC lógica, retornada corretamente às duas chamadas.
- Envio, aprovação e cancelamento simultâneos com a mesma chave: dois retornos idempotentes, um único evento lógico.
- UNIQUEs reais foram exercitadas sem vazamento de `IntegrityError` nos retries legítimos do service.
- Vínculos concorrentes de item provisório: uma vinculação efetiva, uma rejeição coerente, um único evento e snapshot descritivo preservado.
- Autoaprovação por identidade permaneceu bloqueada para solicitante admin e gerência.

## 5. Snapshots, queries e performance básica

Snapshots com acentuação, aspas e `&` foram persistidos e relidos integralmente. Foram exercitados listagem, detalhe, filtros combinados, busca textual por item, tentativa de SQL injection e lookups reversos de OS, reposição e NC.

Com aproximadamente 100 RCs e seus itens/eventos, listagem, detalhe e lookup reverso concluíram abaixo do limite funcional de 5 segundos usado pela suíte, sem SQL incompatível, lock inesperado ou N+1 evidente. Ao final da última suíte havia 103 RCs de teste no database descartável.

## 6. Resultados executáveis

- `tests/test_requisicoes_compra_postgresql.py`: **15 passed in 34.47s**.
- `tests/test_p3_6_ddl_postgresql.py`: **4 passed in 4.72s**.
- `tests/test_hotfix_op502_ddl_bootstrap.py`: **6 passed in 5.91s**.
- `tests/test_romaneio_concorrencia_postgresql.py`: **144 passed in 100.83s**.
- `tests/test_requisicoes_compra.py`: **8 passed in 0.87s**.
- `tests/test_requisicoes_compra_etapa_c.py`: **17 passed in 2.53s**.
- `tests/test_p3_6_os_rastreabilidade.py`: **15 passed in 5.30s**.
- `tests/test_p3_5_requisicoes_almoxarifado.py`: **9 passed in 2.46s**.
- `tests/test_qual_sgi_01.py`: **12 passed in 5.54s**.
- `tests/test_nova_navegacao_inicio.py`: **18 passed in 2.77s**.

Total desta etapa: 248 testes aprovados, zero falha e zero skip nos arquivos executados.

## 7. Falhas e correções

A primeira execução da nova suíte teve uma falha no filtro de catálogo do próprio teste, que usava um padrão incapaz de selecionar o plural `requisicoes_compra`. Classificação: `REGRESSAO_REAL_DA_SPRINT` restrita ao novo teste C.3. O seletor foi corrigido para nomes explícitos. Nenhum bug funcional da RC foi encontrado e nenhum código de produção ou migration precisou ser alterado.

Não houve `FALHA_PREEXISTENTE`, `FIXTURE_ISOLAMENTO`, `ERRO_COLETA_FORA_ESCOPO` ou resultado `INCONCLUSIVO` nesta execução.

## 8. Segurança e conclusão

Não houve acesso a produção, uso de credencial produtiva, conexão à porta 5433, deploy, push, migration produtiva, criação de RC real ou início da Etapa D. O cluster C.3 foi criado sem serviço permanente e deve ser encerrado e removido após preservação deste relatório e da suíte.

**HOMOLOGAÇÃO TÉCNICA APROVADA.** Migration, rollback, reaplicação, schema, sequences, constraints, locks, versão otimista, concorrência, idempotência, vínculo de material, autoaprovação, queries e regressão crítica foram comprovados em PostgreSQL 17.11 real.

**REQUISIÇÃO DE COMPRA — ETAPA C.3 CONCLUÍDA: HOMOLOGAÇÃO TÉCNICA APROVADA EM POSTGRESQL REAL, MIGRATIONS/LOCKS/CONCORRÊNCIA/IDEMPOTÊNCIA VALIDADOS E AMBIENTE TEMPORÁRIO HIGIENIZADO — AGUARDANDO AUTORIZAÇÃO PARA ETAPA D**
