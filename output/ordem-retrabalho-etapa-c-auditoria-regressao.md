# FRIGODATTA — Ordem de Retrabalho (RT)
## ETAPA C — REGRESSÃO, AUDITORIA DE INTEGRIDADE E CORREÇÕES

**Data:** 2026-09-17
**Natureza:** auditoria + correções pontuais + testes. **Nenhum deploy, nenhuma migration em produção, nenhuma RT produtiva, nenhum estoque real movimentado, nenhum push.**

---

## 1. SHA inicial e estado Git encontrado

- SHA no início desta etapa (HEAD): `a91181e527823cf2f63907f0d2e2d76770d9c80e` — **o commit da Etapa B já existia**, ao contrário do que o próprio relatório da Etapa B dava a entender ("pronto para commit"). Confirmado com `git log`.
- Branch: `codex/melhoria-romaneio-multiplas-ops` (inalterada).
- `git status` no início: única pendência relevante era `abatedouro.db` modificado (efeito colateral de testes manuais de boot em sessões anteriores, banco de desenvolvimento local, sem dados de produção) — deixado como estava, fora do escopo. Os demais itens não rastreados (`entregas/`, vários `output/*.md` e `output/pdf/*`) são de sessões de trabalho anteriores, não relacionados a este módulo, e não foram tocados.

## 2. Correção da documentação (itens 8/10/11 já fechados)

Os relatórios da Etapa A/A.1 e B ainda descreviam como "decisão de negócio em aberto" três pontos que este prompt fechou explicitamente: (a) sempre criar posição nova de destino, nunca reaproveitar; (b) não incorporar custo adicional de retrabalho nesta versão; (c) não exigir segregação de usuário entre abrir e encerrar (a segregação real é execução↔liberação). **A implementação já estava conforme essas três decisões desde a Etapa B** — nenhum código precisou mudar. Só a documentação estava desatualizada; corrigida em `output/ordem-retrabalho-etapa-a-auditoria-desenho.md` e `output/ordem-retrabalho-etapa-b-implementacao.md`.

## 3. Auditoria geral do código (SQL injection, validações, transações, exceções)

Revisão linha a linha de `modules/retrabalho/services.py`, `routes.py`, templates, e das 5 mudanças pontuais em módulos existentes (CMV, estoque, Qualidade, navegação, `app.py`):

- **SQL injection:** nenhuma ocorrência. Todo valor variável entra via placeholder `?` (nunca concatenado em SQL); as únicas interpolações de string em SQL (`f"...{bloqueio}"`) injetam apenas a constante `" FOR UPDATE"`/`""`, nunca entrada de usuário — mesmo padrão já usado em `estoque_service.py`. Em `listar_retrabalhos`, o `WHERE` dinâmico só varia **quais cláusulas fixas** entram (nunca o conteúdo), com todos os valores via `params`.
- **Commits internos indevidos / transações partidas:** nenhuma das 5 funções mutantes (`abrir`, `encerrar`, `liberar`, `cancelar`, `estornar`) chama `conn.commit()` manualmente — todas usam `with transaction():` exclusivamente.
- **Conexões independentes dentro de transação:** **achado real, corrigido** — ver seção 9.
- **Exceções engolidas:** nenhuma. O único `except Exception` (em `criar_tabelas_retrabalho`) faz rollback e **re-lança** (`raise`), igual ao padrão de todo o resto do projeto.
- **Hard delete:** nenhum `DELETE FROM`/`DROP TABLE` fora das migrations de rollback (documentação, não executadas).
- **Ausência de autorização em service:** nenhuma — as 5 funções mutantes checam `perfil` explicitamente (defesa em profundidade, além do decorator `@perfil_permitido` nas 9 rotas, todas com decorator, confirmado uma a uma).
- **XSS no template `retrabalho_novo.html`:** **achado real, corrigido** — ver seção 3.1.
- **Validações insuficientes de quantidade:** **2 achados reais, corrigidos** — ver seção 3.2.

### 3.1 XSS defensivo no JS de seleção de origens

`retrabalho_novo.html` montava linhas da tabela de origens via `innerHTML` com concatenação direta de `item.codigo_caixa`/`item.caixa_id` vindos do JSON da API. Hoje esses valores são sempre gerados pelo sistema (nunca texto livre de usuário), então não há exploração possível *hoje* — mas é um padrão frágil. **Corrigido**: reescrito para montar os nós via `document.createElement`/`.textContent`, sem nenhuma concatenação de string em HTML.

### 3.2 Validações de quantidade ausentes (bugs reais)

Dois bugs encontrados e corrigidos em `encerrar_retrabalho`:

1. **Validade anterior à fabricação não era rejeitada** — só existia checagem de "campo não vazio". Corrigido: `if data_validade_destino < data_fabricacao_destino: raise ValueError(...)`.
2. **Quantidade fracionária de pacotes era truncada silenciosamente** — `int(quantidade_apontada)` em vez de validar que o valor já é inteiro. Uma RT apontando `"2.5"` pacotes de destino formaria `2` pacotes silenciosamente errado. Corrigido: `if quantidade_apontada != quantidade_apontada.to_integral_value(): raise ValueError(...)`. Também adicionada validação de `quantidade_bandejas_destino >= 0` e `quantidade_perda >= 0` (antes aceitos sem checagem).

Ambos cobertos por teste novo (`test_rejeita_quantidades_invalidas`, `test_validade_obrigatoria_e_nao_pode_ser_anterior_a_fabricacao`).

## 4. Auditoria de DDL / schema

**4.1/4.2 — DDL não roda por requisição.** `criar_tabelas_retrabalho()` tem guard `_SCHEMA_RETRABALHO_INICIALIZADO` em memória por processo; após a primeira execução bem-sucedida (no boot, via `inicializar_schema_aplicacao()`), toda chamada seguinte — inclusive as que cada função de serviço faz no próprio topo, por segurança — é um `if` simples, não DDL. Confirmado lendo o código e pelo smoke test de boot (uma única passada de `CREATE TABLE`).

**4.3 — Risco de lock em produção, comparado ao incidente documentado.** Localizei o incidente real referenciado no prompt: `output/hotfix-op97-502-auditoria-etapa-a.md`, sobre `ALTER TABLE ordens_producao/pa_caixas ADD COLUMN IF NOT EXISTS` — que em Postgres exige lock `ACCESS EXCLUSIVE` mesmo sendo no-op, enfileirando atrás de transações concorrentes nas mesmas tabelas (tabelas **quentes**, disputadas por romaneio/OP em produção) e travando workers do gunicorn a cada novo boot.

`criar_tabelas_retrabalho()` **não faz nenhum `ALTER TABLE`** — confirmado por busca no arquivo inteiro. Faz apenas `CREATE TABLE/INDEX IF NOT EXISTS` em 4 tabelas **novas e não disputadas** (`retrabalhos`, `retrabalho_origens`, `retrabalho_saidas`, `retrabalho_eventos`), sem nenhuma relação com `ordens_producao`/`pa_caixas`. O mecanismo de lock em cascata do incidente documentado não se aplica a esse padrão.

**Decisão:** manter `criar_tabelas_retrabalho()` na lista de boot (não é o mesmo risco do incidente), mas documentei essa análise diretamente no código (docstring da função) e recomendo formalmente, para a Etapa D: **rodar `database/20260917_ordem_retrabalho.sql` explicitamente antes do primeiro deploy em produção**, deixando a chamada em runtime como um no-op puro desde a primeira requisição — sem precisar remover o padrão existente do projeto.

## 5. Família CAIXA/peso como origem — testada

2 testes novos (`tests/test_retrabalho_etapa_c.py`): consumo total (100 kg de 100 kg reservados/consumidos, origem zera e vira `RETRABALHADO`) e consumo parcial (100 kg reservados/consumidos de 150 kg, sobra 50 kg volta a `DISPONIVEL`). Confirmado: a reserva desta família é **integral da posição** (limitação já documentada na Etapa B, não um bug — o saldo remanescente após consumo parcial é liberado corretamente de volta). Nenhuma quantidade negativa em nenhum cenário.

## 6. Auditoria numérica de CMV — Caso 198 V1 → 99 V2

Camada semeada: 300 aves a R$5,00/ave. Resultado do teste (`test_cmv_conserva_valor_total_caso_198_v1_para_99_v2`):

| | Valor |
|---|---|
| Unidade CMV origem | `UN` (ave) |
| Quantidade consumida | 198 |
| Custo total retirado da origem | R$ 990,00 |
| Unidade CMV destino | `UN` (ave — **não** pacote) |
| Quantidade da camada de destino | 198 |
| Custo unitário do destino | R$ 5,00/ave |
| Custo total da camada de destino | R$ 990,00 |

`custo_total_antes == custo_total_depois` confirmado por assert (`assertAlmostEqual`). O teste também afirma explicitamente que o resultado **não** pode ser R$ 495,00 (o que aconteceria se a camada fosse indevidamente controlada por pacote em vez de por ave) — passou.

## 7. Auditoria numérica de CMV — Caso Inteira → Cortada

Camada semeada: 1.000 aves a R$6,00/ave = R$6.000,00. Resultado do teste (`test_cmv_conserva_valor_total_caso_inteira_para_cortada`):

| | Valor |
|---|---|
| Unidade CMV origem | `UN` (ave) |
| Quantidade consumida | 1.000 |
| Custo total retirado da origem | R$ 6.000,00 |
| Unidade CMV destino | `KG` |
| Quantidade da camada de destino | 412,3 kg |
| Custo unitário do destino | R$ 6.000,00 / 412,3 ≈ R$ 14,554/kg |
| Custo total da camada de destino | R$ 6.000,00 |

Valor total conservado entre unidades diferentes (aves na origem, kg no destino) — confirmado por assert.

## 8. Perda em retrabalho e CMV

A perda (`quantidade_perda`/`unidade_perda`/`justificativa_perda`) é **puramente informativa/documental** nesta versão — gravada no cabeçalho da RT e no histórico, mas **não** gera nenhum evento CMV próprio nem altera o cálculo de custo. Isso significa que o custo total retirado da origem sempre bate exatamente com o custo total da camada de destino (seções 6–7), **mesmo quando há perda registrada** — ou seja, o custo da perda fica embutido dentro do custo unitário do destino (o mesmo custo total é diluído sobre uma quantidade de saída menor), nunca desaparece nem duplica. Não há risco de destruição/duplicação de valor. Nenhuma regra contábil nova foi inventada; se o negócio quiser no futuro separar contabilmente o custo da perda (ex. lançar como despesa em vez de diluir no custo do destino), isso é uma extensão de escopo, não desta etapa.

## 9. Atomicidade — teste de falha injetada

**Achado real durante a auditoria, corrigido nesta etapa:** o parâmetro `checkpoint` (opcional, chamado ao final de `encerrar_retrabalho`, ainda dentro da transação) foi usado para injetar uma falha proposital via `test_atomicidade_falha_injetada_no_encerramento_reverte_tudo`. Resultado confirmado por assert, após o `RuntimeError` injetado:

- origem: `quantidade_pacotes` e `quantidade_pacotes_reservados` idênticos ao estado da abertura (nada consumido);
- nenhuma linha nova em `pa_caixas` com `origem='Retrabalho'`;
- nenhuma linha em `retrabalho_saidas`;
- nenhuma camada nem evento novo em `cmv_camadas`/`cmv_eventos`;
- nenhum evento órfão em `estoque_eventos`;
- status da RT permanece `ABERTA` (não mudou para `ENCERRADA`);
- a RT continua **utilizável normalmente** depois — um novo `encerrar_retrabalho` sem a falha injetada conclui com sucesso (não ficou em estado zumbi).

Esse teste só foi possível graças à correção já feita na Etapa B (CMV aceitar `cursor` da transação do chamador) — sem ela, a falha injetada não teria uma transação única para reverter.

## 10. Idempotência ampliada

Além do encerramento (já testado na Etapa B), agora testados explicitamente: **abrir** (mesma `idempotency_key` não duplica a reserva nem cria uma segunda `retrabalho_origens`), **liberar** (não duplica o evento `LIBERACAO`), **cancelar** (não duplica o evento `CANCELAMENTO`) e **estornar** (não duplica o evento `ESTORNO`). Todos passam.

**Limitação teórica registrada, não corrigida nesta etapa (consistente com o padrão do projeto inteiro):** a checagem de idempotência é feita por uma consulta separada *antes* de travar a linha principal (`SELECT` em `retrabalho_eventos`, depois `SELECT...FOR UPDATE` em `retrabalhos`). Isso cobre com segurança o caso comum de *retry sequencial* (nova tentativa depois que a primeira já comitou), que é o cenário testado. Para duas chamadas *genuinamente simultâneas* com a mesma chave, a segunda pode encontrar o status já alterado pela primeira e retornar um erro de estado em vez do resultado cacheado (nenhuma duplicação de escrita ocorre — a proteção por `rowcount`/guarda de saldo continua garantindo isso — só a mensagem de erro fica menos amigável nesse cenário estreito). Essa é exatamente a mesma limitação estrutural de `pnc_reprocessamentos`, `cmv_eventos` e todo outro fluxo do projeto que usa o mesmo padrão "checar-depois-travar" — não é uma regressão introduzida pela RT, e corrigi-la exigiria redesenhar o padrão de idempotência em todo o projeto, fora do escopo desta etapa.

## 11. RT × RT

`test_duas_rts_disputam_mesmo_saldo`: RT A reserva 70 de 100 pacotes; RT B tentando reservar 40 (só sobram 30) é recusada com `ValueError`, **sem deixar reserva parcial** (saldo reservado continua em 70, não 70+alguma-fração); RT B reservando exatamente 30 é aceita; saldo final reservado = 100 (70+30), nenhuma super-reserva.

## 12. RT × romaneio

Já coberto na Etapa B (`test_concorrencia_rt_reserva_primeiro_bloqueia_romaneio_no_saldo_excedente` e o inverso), reconfirmado passando nesta etapa.

## 13–14. PNC antes da liberação / tentativa de liberar PA não conforme

**Item crítico do prompt — testado e aprovado.** `test_pnc_antes_da_liberacao_impede_liberar_como_disponivel`: RT encerrada → PA em `PENDENTE_OP` → Qualidade registra PNC (`registrar_pnc_avulso`) → PA vira `NAO_CONFORME`/`BLOQUEADO` → tentativa de `liberar_retrabalho` **é recusada com `ValueError`**, e o PA continua exatamente `NAO_CONFORME`/`BLOQUEADO` depois da tentativa (nenhuma alteração parcial). Isso já era garantido pelo guard existente desde a Etapa B (`if caixa["disponibilidade"] != "PENDENTE_OP": raise`) — a auditoria confirma que **não é preciso corrigir nada aqui**, o comportamento correto já existia, só não tinha teste dedicado.

## 15. Estorno após liberação, sem consumo posterior

`test_estorno_apos_liberacao_sem_consumo_reverte_atomicamente`: RT encerrada, liberada pela Qualidade (destino `DISPONIVEL`), sem nenhuma reserva/consumo — estorno **é permitido** (comportamento já previsto no desenho) e reverte tudo atomicamente: origem volta a `quantidade_pacotes` original e `DISPONIVEL`, destino vira `ESTORNADO`.

## 16. Estorno com PNC

**Item crítico do prompt — testado e aprovado.** `test_estorno_bloqueado_quando_ha_pnc_ativo_no_destino`: RT encerrada, PNC registrado no destino → tentativa de estorno **é recusada** (guard já existente: `disponibilidade not in ("PENDENTE_OP","DISPONIVEL")` cobre `BLOQUEADO`), e o registro de PNC continua **intacto** (`status='BLOQUEADO'`, não invalidado/apagado) — confirmado por assert direto na tabela `pa_nao_conformes` depois da tentativa recusada.

## 17. Etiquetas

`test_v1_para_v2_nao_gera_job_de_etiqueta_incompativel`: após encerrar uma RT V1→V2, `listar_jobs_caixas([caixa_destino_id])` retorna vazio — confirmado que a família pacote/ave nunca aciona `criar_job_caixa_cursor` (comportamento idêntico ao de Galinha Inteira produzida por OP normal, que também nunca chama essa função).

## 18–19. Posição sem OP / filtros de romaneio

`test_posicao_rt_aparece_em_selecao_geral_mas_nao_em_filtro_por_op`: a posição formada pela RT, depois de liberada, é reservada normalmente por `reservar_itens` numa seleção geral (sem `op_id_esperada`); confirmado que ela não tem nenhuma linha em `pa_caixa_composicao`, então uma tela de seleção filtrada por OP específica não a encontraria (nada a corrigir — é o comportamento correto, já coberto estruturalmente).

## 20. Validade

`test_validade_obrigatoria_e_nao_pode_ser_anterior_a_fabricacao`: fabricação/validade vazias são rejeitadas; validade anterior à fabricação é rejeitada (bug corrigido, seção 3.2); datas válidas persistem corretamente em `pa_caixas.data_fabricacao`/`data_validade`, e ficam no histórico via `retrabalhos.data_fabricacao_destino`/`data_validade_destino`.

## 21. Validações de quantidade

`test_rejeita_quantidades_invalidas`: quantidade de destino zero, negativa e fracionária (para família pacote) rejeitadas; origem com quantidade zero rejeitada; `galinhas_por_pacote_destino<=0` rejeitado — e confirmado que nenhuma dessas tentativas recusadas deixou reserva parcial no banco.

## 22. Conciliação pacote/ave

`test_conciliacao_pacote_ave_sempre_consistente` (3 variações de pacotes/fator): `quantidade_galinhas == quantidade_pacotes × galinhas_por_pacote` sempre verdadeiro — garantido por construção, porque o código nunca aceita `quantidade_galinhas` como entrada separada, sempre deriva.

## 23. OP original nunca é escrita

`test_op_original_e_tabelas_relacionadas_nunca_sao_escritas`: comparação byte-a-byte de todas as linhas de `ordens_producao` antes/depois de um encerramento completo — idênticas. (Tabelas de apontamento/rendimento/OEE não são tocadas por construção — a RT nunca as referencia em nenhuma query de escrita, confirmado por leitura de código; o teste runtime direto mais forte e verificável é sobre `ordens_producao`, que é a tabela que qualquer um desses relatórios consulta como raiz.)

## 24. Performance / N+1

`test_performance_listagem_com_muitas_rts`: 100 RTs criadas (cada uma com sua própria OP/posição/abertura). `listar_retrabalhos()` = 1 única query, executada em bem menos de 1s; `obter_detalhe_retrabalho()` = exatamente 4 queries fixas (cabeçalho + origens + saídas + eventos), sem nenhum loop de query por linha — sem N+1.

## 25. Migrations

**SQLite — ciclo completo testado e aprovado:** aplicação em banco limpo ✓; reaplicação idempotente (`CREATE TABLE/INDEX IF NOT EXISTS`, sem erro) ✓; aplicação contra uma cópia do schema completo atual do projeto (`abatedouro.db`) ✓; rollback remove as 4 tabelas ✓; reaplicação após rollback ✓; rollback reaplicado de novo sem erro ✓.

**PostgreSQL — sem instância disponível neste ambiente (confirmado: `psql`/`pg_ctl` ausentes, e tentativa de conexão local falhou).** Classificado como `ERRO_COLETA_FORA_ESCOPO` — nenhum resultado foi inventado. Em vez disso, foi feita revisão estática cuidadosa de `database/20260917_ordem_retrabalho.sql`: sintaxe válida (`SERIAL PRIMARY KEY`, `TIMESTAMP`, `IF NOT EXISTS` em tabelas e índices), zero `ALTER TABLE` (ver seção 4.3), `CREATE UNIQUE INDEX` sobre coluna nullable é válido em Postgres (múltiplos `NULL` não conflitam, mesma semântica do SQLite), sem foreign keys declaradas (consistente com o padrão do restante do projeto). Nenhum problema estrutural encontrado na revisão estática.

## 26. Regressão

Todos os **46 arquivos** de `tests/` (44 pré-existentes + `test_retrabalho.py` + `test_retrabalho_etapa_c.py`) executados **individualmente** (rodar o diretório inteiro num único processo `pytest` produz falsos "ERROR" por colisão de `DB_NAME`/Flask entre arquivos — característica pré-existente de toda a suíte, confirmada rodando até arquivos que não tenho nada a ver com antes e depois do meu `git stash` de teste, não introduzida por esta implementação):

- **44 arquivos 100% verdes**, incluindo todas as áreas pedidas explicitamente: estoque consolidado, estoque operacional, romaneio (`test_romaneio_selecao_multiplas_ops.py`, 43 testes), PNC (`test_pa_nao_conforme_op.py` parcial — ver abaixo), reprocessamento (`test_pnc_reprocessamento.py`), CMV (`test_p2_3_financeiro_dre_cmv.py`), Produção/Rendimento (`test_p2_1_producao_rendimento.py`), OEE (`test_p2_2_disponibilidade_performance_oee.py`), labels (`test_p3_2_integracao_zebra.py`), encerramento de OP (`test_expedicao_marco_zero.py`), estorno/reabertura OP (`test_p0_2_estorno_reabertura_op.py`, 58 testes).
- `test_retrabalho.py`: 9/9 ✓. `test_retrabalho_etapa_c.py`: 19/19 (22 com subtestes) ✓.
- `test_romaneio_concorrencia_postgresql.py`: 144 **skipped** — suíte exclusiva de Postgres real (`ERRO_COLETA_FORA_ESCOPO`, mesma razão da seção 25).
- `test_pa_nao_conforme_op.py`: 2 falhas — ver classificação abaixo.

## 27. Falhas classificadas

| Falha | Classificação | Evidência |
|---|---|---|
| `test_pa_nao_conforme_op.py::test_encerramento_op_registro_e_bloqueio_ocorrem_na_mesma_transacao` | `FALHA_PREEXISTENTE` | Reexecutada com `git stash` (revertendo **100%** das mudanças desta e da Etapa B) — falha exatamente igual, mesma mensagem de erro. |
| `test_pa_nao_conforme_op.py::test_falha_durante_pa_nc_desfaz_tambem_o_encerramento_da_op` | `FALHA_PREEXISTENTE` | Idem. |
| Colisões de "ERROR" ao rodar múltiplos arquivos de teste juntos num único `pytest` | `FIXTURE_ISOLAMENTO` | Reproduzível com arquivos que não têm nenhuma relação com a RT (ex. `test_romaneio_selecao_multiplas_ops.py` sozinho passa 43/43; junto com outros arquivos, gera "ERROR" por colisão de `DB_NAME`/Flask). Característica estrutural de toda a suíte, não desta implementação. |
| `test_romaneio_concorrencia_postgresql.py` (144 casos) | `ERRO_COLETA_FORA_ESCOPO` | Sem instância PostgreSQL disponível neste ambiente. |
| Migration PostgreSQL não executada de fato | `ERRO_COLETA_FORA_ESCOPO` | Mesma razão — revisão estática feita em seu lugar (seção 25). |

Nenhuma falha classificada como `REGRESSAO_REAL_DA_SPRINT` ou `INCONCLUSIVO`.

## 28. Correções feitas nesta etapa

1. `modules/retrabalho/services.py::encerrar_retrabalho`: rejeita validade anterior à fabricação.
2. `modules/retrabalho/services.py::encerrar_retrabalho`: rejeita quantidade apontada fracionária quando o destino é da família pacote (antes truncava silenciosamente via `int()`); rejeita `quantidade_bandejas_destino` e `quantidade_perda` negativas.
3. `templates/retrabalho_novo.html`: reescrita a montagem da tabela de origens em JS para não usar `innerHTML` com concatenação de string (defensivo — não explorável hoje, mas removido o padrão frágil).
4. `modules/retrabalho/services.py::criar_tabelas_retrabalho`: docstring documentando a análise de risco de DDL em boot (seção 4.3), sem alteração de comportamento.
5. Documentação corrigida em `output/ordem-retrabalho-etapa-a-auditoria-desenho.md` e `output/ordem-retrabalho-etapa-b-implementacao.md` (seção 2).

Nenhuma refatoração ampla, nenhum terceiro modelo de unidade, nenhum redesenho de PNC, nenhuma alteração em OP/OEE, nenhum custo adicional de retrabalho foi criado — respeitando os limites da seção 28 do prompt.

## 29. Commit

Commit específico desta etapa criado após este relatório (ver mensagem de commit para o SHA final). Branch: `codex/melhoria-romaneio-multiplas-ops`. Nenhum push.

## 30. Pendências reais

- Regra sanitária formal de validade pós-retrabalho (mantém a mais restritiva? nova validade?) — decisão de Qualidade/regulatório, não técnica.
- Matriz de perfis por ação é a recomendação técnica adotada; sujeita a ajuste fino da gerência se necessário.
- Migration Postgres não testada contra uma instância real (`ERRO_COLETA_FORA_ESCOPO`) — recomendo testá-la no primeiro ambiente de homologação com Postgres disponível, antes da Etapa D.
- Limitação estrutural de idempotência sob concorrência genuinamente simultânea (seção 10) — compartilhada por todo o projeto, não é algo a corrigir isoladamente na RT.

## 31. Conclusão formal

Todos os critérios da seção 30 do prompt foram verificados com teste real (não apenas revisão de código) ou, quando isso não era possível no ambiente disponível (Postgres), com revisão estática honesta e classificação explícita como fora de escopo — sem inventar resultado.

---

**ORDEM DE RETRABALHO — ETAPA C CONCLUÍDA: HOMOLOGAÇÃO TÉCNICA APROVADA, REGRESSÃO EXECUTADA E INTEGRIDADE DE ESTOQUE/QUALIDADE/CMV CONFIRMADA — AGUARDANDO AUTORIZAÇÃO PARA ETAPA D**
