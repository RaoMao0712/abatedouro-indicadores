# Requisição de Compra — Etapa C

## 1. Identificação e estado Git

- SHA base/inicial: `8e1b94db1eb8af07dc9dd9960de7bfe2fa6d8a8b`.
- Commit final da Etapa B: `f7b1c7117353c4327f528dfc1616d689dd73a5f7` (`feat: implementar requisicao de compra vinculada a origem`).
- Branch: `codex/melhoria-romaneio-multiplas-ops`.
- O commit da Etapa B não foi reescrito.
- `abatedouro.db`, `entregas/` e artefatos anteriores de `output/` foram excluídos do escopo e não foram adicionados ao commit.

## 2. Auditoria geral e correções

Foram revisados módulo, origens, serviços, rotas, templates, PDF, migrations e integrações com OS, Almoxarifado e SGI. Correções aplicadas: autorização efetiva da origem no envio/cancelamento; envio restrito ao autor ou gestão; saldo físico/reservado/disponível na reposição; rejeição de origens inativas/canceladas/encerradas; separação entre snapshot e situação atual; retry seguro de criação, ações e vínculo de material; lock do item provisório em PostgreSQL; auditoria completa antes/depois da edição; limites de entrada; link reverso de reposição em consulta única; cabeçalho/rodapé por página no PDF.

SQL dinâmico usa apenas nomes internos controlados e parâmetros para entradas. Templates mantêm autoescape, sem `safe` ou `innerHTML`. O projeto não possui proteção CSRF transversal formal; o módulo segue o padrão atual. Risco documentado, sem redesenho global.

## 3. Migrations e DDL/boot

- SQLite: banco limpo, schema existente, reaplicação, rollback, nova aplicação e preservação de dados aprovados; índices esperados presentes.
- PostgreSQL: `ERRO_COLETA_FORA_ESCOPO`. O host não dispõe de Docker, Podman, `psql`, `postgres`, `pg_ctl`, serviço PostgreSQL ou distribuição WSL. Não foi usado banco produtivo e revisão estática não foi apresentada como homologação.
- O bootstrap ocorre no boot, é idempotente e não é chamado por request. Não há `ALTER` repetitivo em tabela quente.
- Consequência: tipos, constraints, sequences, locks, concorrência e rollback/reaplicação não foram confirmados em PostgreSQL real.

## 4. Origens, snapshots e itens

As origens formais rejeitam ID nulo/inexistente e estado inválido. A matriz de perfis foi exercitada, inclusive Qualidade em OS apenas com vínculo SGI. Origens documentais validam campos conforme o tipo. A origem não é alterada na edição. O snapshot permanece imutável enquanto a situação atual é consultada separadamente e rotulada na tela.

Itens provisórios rejeitam descrição vazia/longa, unidade inválida e quantidade não positiva; caracteres especiais permanecem dados escapados. Vínculo posterior exige admin/PCP, material ativo e unidade compatível, preserva o snapshot e é idempotente. Duplicados na mesma RC são bloqueados; entre RCs geram alerta, sem bloqueio. Prioridades inválidas são rejeitadas e urgente/crítica exigem justificativa não vazia.

## 5. Estados, autorização, concorrência e idempotência

Autoaprovação foi bloqueada por identidade para admin e gerência, inclusive retry e service direto; `solicitante_id` do payload não substitui o ator autenticado. Aprovação/rejeição/cancelamento verificam estado, perfil, versão e motivo. Estados futuros e campos de Pedido/Fornecedor/NF/Financeiro são ignorados pelo MVP.

Em SQLite, versão otimista, transações e retries sequenciais foram aprovados. Em código PostgreSQL, ações usam `FOR UPDATE`, atualização com versão e UNIQUE de idempotência; vínculo de material passou a bloquear RC/item e tratar a corrida da chave. Concorrência real aprovação×cancelamento, aprovação×rejeição, edição×envio, criação e ações com a mesma chave permanece `ERRO_COLETA_FORA_ESCOPO`, pois exige PostgreSQL real. Não é considerada homologada.

Não existe hard delete de RC/eventos. A substituição de itens só existe em rascunho, dentro da transação, e gera evento com conteúdo completo anterior/posterior.

## 6. Integrações e invariantes

Os testes dirigidos confirmam delta zero em lotes, movimentações, reservas, requisições/alocações do Almoxarifado e tabelas financeiras durante o ciclo da RC. A linha da OS e fluxos de NC não são mutados; links reversos derivam da RC. Na OS, materiais de estoque e compras necessárias permanecem blocos distintos. Na reposição, o snapshot contém saldo físico, reservado, disponível, unidade e data, sem estoque mínimo inventado. O lookup reverso foi agrupado para evitar N+1.

## 7. PDF e navegação

Foram gerados e renderizados casos de OS, reposição, administrativa, item provisório, 75 itens e origem longa. Resultado: A4; 1 a 4 páginas; tabela paginada; cabeçalho/rodapé e número de página; acentuação legível; sem sobreposição observada; sem Pedido, Fornecedor ou NF. Valores do PDF foram confrontados com os objetos geradores (número, status, quantidade, unidade, origem, solicitante, aprovador e justificativa). Os arquivos foram apenas artefatos intermediários de QA.

A navegação Compras → Requisições de Compra e controles por perfil foram revisados. A segurança crítica está no service, não apenas no menu; acesso direto não permite criar/decidir fora da matriz.

## 8. Performance, busca e segurança web

Com 100 RCs, listagem executou uma consulta e detalhe até quatro; link reverso de reposição é batelado. Filtros por estado, tipo, setor, prioridade, período e texto usam parâmetros; tentativa de SQL injection não retornou expansão indevida. Descrições/motivos HTML são escapados pelo Jinja.

## 9. Regressão

- Suíte dirigida final da RC: `25 passed in 2.36s` (`test_requisicoes_compra.py` + `test_requisicoes_compra_etapa_c.py`).
- Regressão ampla isolada previamente executada: 57 arquivos em aproximadamente 156 s; 55 arquivos verdes e 2 arquivos com falhas.
- Skips observados: 154 (6 de bootstrap PostgreSQL, 4 de DDL PostgreSQL e 144 de concorrência PostgreSQL).
- `tests/test_expedicao_corretiva.py`: 1 falha, 39 aprovados — fixture sem `cliente_parceiro_id`.
- `tests/test_pa_nao_conforme_op.py`: 2 falhas, 25 aprovados — fixture/expectativa sem `consumo_liquido`.
- Evidência comparativa: não há diferenças da Etapa B nos módulos/testes afetados (`git diff 8e1b94d..f7b1c71` vazio para esses caminhos). Classificação: `FALHA_PREEXISTENTE`.
- A tentativa de agregar arquivos que alteram globalmente `DB_NAME` confirmou a limitação conhecida de isolamento; o resultado válido é o de execução arquivo a arquivo. Classificação da execução agregada: `FIXTURE_ISOLAMENTO`.

## 10. Classificação de achados

- Bugs corrigidos de autorização, saldo/snapshot, idempotência, lock, N+1 e PDF: `REGRESSAO_REAL_DA_SPRINT`.
- Duas suítes alheias descritas acima: `FALHA_PREEXISTENTE`.
- Agregação de testes com `DB_NAME` global: `FIXTURE_ISOLAMENTO`.
- PostgreSQL real e concorrência dependente dele: `ERRO_COLETA_FORA_ESCOPO`.
- Não restou achado crítico local classificado como `INCONCLUSIVO`.

## 11. Pendências e conclusão formal

Antes da Etapa D é obrigatório executar, em PostgreSQL descartável real: migration/rollback/reaplicação; constraints e índices; sequence/numeração; `FOR UPDATE`; concorrência das quatro ações; retries simultâneos; ausência de eventos terminais incompatíveis. Também é recomendável tratar separadamente as duas fixtures preexistentes e planejar CSRF transversal.

Não houve deploy, migration produtiva, RC produtiva, alteração de estoque/Financeiro real, push para `main` ou início da Etapa D.

**HOMOLOGAÇÃO TÉCNICA NÃO APROVADA.** A implementação local e SQLite ficou consistente, mas a exigência obrigatória de PostgreSQL real e concorrência não foi satisfeita neste host.

**REQUISIÇÃO DE COMPRA — ETAPA C CONCLUÍDA: HOMOLOGAÇÃO TÉCNICA NÃO APROVADA — BLOQUEIOS DOCUMENTADOS — AGUARDANDO CORREÇÃO**
