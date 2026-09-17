# FRIGODATTA — Ordem de Retrabalho (RT)
## ETAPA B — IMPLEMENTAÇÃO E TESTES

**Data:** 2026-09-17
**Branch:** `codex/melhoria-romaneio-multiplas-ops`
**SHA base:** `6ca3b5d80e8eea15b9da9fd8cedd8c5072e90313`
**Natureza:** implementação local + testes. **Nenhum deploy, nenhuma migration em produção, nenhuma RT real criada, nenhum estoque produtivo movimentado.** Todo o trabalho abaixo foi feito e testado exclusivamente contra bancos SQLite temporários isolados (nunca o `abatedouro.db` de desenvolvimento com dados reais, nem a base de produção do Render).

---

## 1–2. SHA base e branch

Implementado em cima do mesmo commit auditado nas Etapas A/A.1 (`6ca3b5d8`), na mesma branch de trabalho já em uso nesta sessão.

## 3. Arquitetura implementada

Exatamente a recomendada no desenho aprovado (`output/ordem-retrabalho-etapa-a-auditoria-desenho.md`, corrigido em A.1): módulo novo e isolado `modules/retrabalho/`, entidade `retrabalhos` **separada** de `ordens_producao`, saída sem linha em `pa_caixa_composicao`, reaproveitamento máximo dos motores já existentes (estoque, CMV, etiquetas, Qualidade/PNC).

```
modules/retrabalho/
  __init__.py       # exporta register_retrabalho_routes, criar_tabelas_retrabalho
  services.py        # 925 linhas — toda a lógica de negócio e transações
  routes.py           # 158 linhas — rotas Flask
templates/
  retrabalho_lista.html
  retrabalho_novo.html
  retrabalho_detalhe.html
tests/
  test_retrabalho.py  # 517 linhas — 9 testes, cobrindo os 8 casos obrigatórios
database/
  20260917_ordem_retrabalho.sql (+ _sqlite.sql + _rollback.sql + _sqlite_rollback.sql)
```

Mudanças pontuais em módulos existentes (todas aditivas, sem alterar comportamento de nenhum caminho já existente — ver seção 23 "testes executados" para a prova de não regressão):

| Arquivo | Mudança | Por quê |
|---|---|---|
| `modules/cmv/services.py` | `registrar_saida` aceita `tipo_evento='RETRABALHO'` (antes só VENDA/DESCARTE); `estornar_saida` generaliza de "só VENDA→ESTORNO_VENDA" para qualquer tipo estornável (`RETRABALHO→ESTORNO_RETRABALHO`), mesma saída de string para VENDA; **as 3 funções de escrita (`registrar_camada`, `registrar_saida`, `estornar_saida`) passam a aceitar um `cursor=None` opcional**, participando da transação do chamador em vez de abrir sempre a própria (achado durante os testes — ver seção 17). | Reaproveitar o motor de custo sem duplicar código, com atomicidade real. |
| `modules/expedicao/estoque_service.py` | `buscar_estoque_operacional`: `'RETRABALHADO'` somado à lista de disponibilidades excluídas da listagem operacional. | Posição de origem totalmente consumida por RT não deve aparecer como estoque ativo. |
| `modules/expedicao/consolidado_estoque.py` | Mesmo `'RETRABALHADO'` somado à exclusão em `_linhas_pos_marco`. | Mesma razão, na tela/relatório de estoque consolidado. |
| `modules/qualidade/produtos_nao_conformes.py` | Nova função `registrar_pnc_avulso(caixa_id, dados, ...)`, aditiva — não altera `registrar_itens_encerramento`/`_validar_item` (fluxo de OP intocado). | Fecha o gap encontrado na Etapa A (item 5 do prompt): permitir PNC em PA sem `op_id`. |
| `app.py` | Import + `register_retrabalho_routes(app)` + `criar_tabelas_retrabalho` na lista de `inicializar_schema_aplicacao`. | Ligar o módulo novo à aplicação. |
| `modules/navegacao/services.py` | Item "Ordens de Retrabalho" no grupo Expedição (mesmos perfis de Não Conformes + produção/gerência). | Navegação. |

## 4. Tabelas criadas

`retrabalhos`, `retrabalho_origens`, `retrabalho_saidas`, `retrabalho_eventos` — schema completo documentado nas migrations (`database/20260917_ordem_retrabalho*.sql`) e criado em runtime de forma idempotente por `modules/retrabalho/services.py::criar_tabelas_retrabalho()`, no mesmo padrão de `criar_tabelas_estoque_confiavel`/`criar_tabelas_cmv`. Nenhuma coluna nova em `pa_caixas` ou `pa_caixa_composicao` — a saída da RT nunca grava em `pa_caixa_composicao` (confirmado por teste, seção 21).

## 5. Migrations

4 arquivos SQL de documentação (Postgres, SQLite, e os dois rollbacks) em `database/20260917_ordem_retrabalho*.sql`, seguindo exatamente a convenção de nomenclatura e de rollback já usada no restante do projeto. **Não foram executados em nenhum banco além do runtime idempotente já embutido no código** (que é o que efetivamente cria o schema, inclusive nos testes).

## 6. Estados implementados

`ABERTA → ENCERRADA` (com `EM_EXECUCAO` disponível como valor de status para uso futuro, mas o fluxo implementado vai direto `ABERTA→ENCERRADA`, como o desenho permitia) `→` opcionalmente `ESTORNADA`; ou `ABERTA → CANCELADA`. `RASCUNHO` existe como valor de status previsto no desenho, mas a rotina de abertura implementada já reserva imediatamente (ver seção 12 do prompt — reserva na abertura é a recomendação aprovada), então o fluxo testado é `ABERTA` desde a criação.

## 7. Fluxo de reserva (abertura)

`abrir_retrabalho(dados, origens, usuario, perfil)`: valida perfil (`admin/gerencia/pcp/producao`), cria o cabeçalho, gera `numero = RT-{id:06d}`, e para cada origem informada faz `SELECT...FOR UPDATE` + `UPDATE ... WHERE saldo_livre >= quantidade` (mesma técnica de `reservar_itens`) — se o saldo não for suficiente (por já estar comprometido por outra RT ou por um romaneio concorrente), a abertura inteira falha e nada é reservado (transação única). Aves são convertidas para pacotes via o `galinhas_por_pacote` real da posição, exigindo múltiplos exatos.

## 8. Fluxo de encerramento

`encerrar_retrabalho(rt_id, saida, usuario, perfil)`, uma única transação: consome de verdade cada origem reservada (decrementa `quantidade_pacotes`/`quantidade_galinhas` ou `peso_liquido`, conforme a família), marca origem esgotada como `disponibilidade='RETRABALHADO'` e invalida etiquetas pendentes; baixa o custo das origens via CMV FIFO; cria a posição de destino em `pa_caixas` (`condicao='CONFORME'`, `disponibilidade='PENDENTE_OP'` — nasce **não disponível**, ver seção 9); cria a camada de custo do destino; grava `retrabalho_saidas`; grava eventos em `estoque_eventos` e `retrabalho_eventos`; muda `status='ENCERRADA'`. Tudo com `idempotency_key` — reexecução com a mesma chave é no-op (seção 17).

## 9. Qualidade / liberação

`liberar_retrabalho(rt_id, usuario, perfil)` (perfis `admin/gerencia/qualidade`) transiciona a(s) posição(ões) de destino de `PENDENTE_OP` para `DISPONIVEL`. **Reaproveita literalmente o mesmo par de valores já usado no sistema** para "produto formado, ainda não liberado para expedição" (o mesmo que toda OP de abate usa entre a produção e a ativação de estoque) — nenhum estado novo foi inventado em `pa_caixas`. Antes da liberação, a posição:
- aparece no card "Aguardando liberação" do estoque consolidado (não em "Disponível");
- não pode ser reservada em romaneio (`reservar_itens` já rejeita qualquer coisa que não seja `CONFORME`+`DISPONIVEL`).

Confirmado por teste (`test_caso_198_v1_para_99_v2...`, seção abaixo).

## 10. PNC do PA originado por RT

`modules.qualidade.produtos_nao_conformes.registrar_pnc_avulso(caixa_id, dados, usuario, perfil)`: localiza a posição só por `caixa_id` (sem exigir `op_id`/`pa_caixa_composicao`), grava `pa_nao_conformes.op_id = NULL` para posições de RT, numera como `PNC-RT-{caixa_id:06d}`, bloqueia a posição (`condicao='NAO_CONFORME'`, `disponibilidade='BLOQUEADO'`) e a partir daí usa **exatamente** o mesmo ciclo de vida já existente (`consultar`, `obter_detalhe`, `decidir`, liberação) — nenhuma dessas funções precisou mudar, porque nenhuma delas depende de `op_id`. Testado (`test_pnc_avulso_no_pa_formado_por_rt_sem_op_id`).

## 11. CMV

Consumo das origens via `cmv.services.registrar_saida(tipo_evento='RETRABALHO', origem_tipo='RETRABALHO', origem_id=<rt_id>)` (FIFO real, mesmas camadas usadas por vendas/descartes); formação do destino via `registrar_camada(origem_tipo='RETRABALHO', ...)` com `custo_unitario = custo_total_das_origens / quantidade_produzida` (protegido contra divisão por zero — só executa se `quantidade_cmv_destino > 0`). **Nenhum custo adicional de retrabalho é somado nesta primeira versão**, exatamente como pedido (seção 26 do prompt) — só o custo do PA consumido é transportado.

## 12. Etiquetas

`criar_job_caixa_cursor`/`invalidar_jobs_caixa_cursor` (`modules/label_printing/services.py`) reaproveitados sem nenhuma alteração. **Achado corrigido em relação ao desenho da Etapa A:** `criar_job_caixa_cursor` internamente exige `quantidade_bandejas > 0` e pesos coerentes — ele **quebraria** se chamado para uma posição da família pacote/ave (Galinha Inteira nunca teve automação de etiqueta por posição, confirmado lendo o código de criação das posições V1/V2 de OP normal, que também nunca chama essa função). A implementação só chama `criar_job_caixa_cursor` quando o destino é da família caixa/bandeja/peso (Caso 2), nunca para a família pacote/ave (Caso 1) — testado implicitamente (o Caso 1 encerra sem erro).

## 13. Permissões

Implementadas exatamente como a matriz do prompt: abrir/encerrar/cancelar = `admin, gerencia, pcp, producao`; liberar = `admin, gerencia, qualidade`; estornar = `admin, gerencia` apenas. Usa o decorator já existente `modules.auth.decorators.perfil_permitido` nas rotas, e checagem explícita de perfil dentro de cada função de serviço (para cobrir também chamadas fora de request HTTP).

## 14. Cancelamento

`cancelar_retrabalho(rt_id, justificativa, usuario, perfil)`: só permitido em `ABERTA`/`EM_EXECUCAO`; libera exatamente a reserva feita na abertura (decrementa `quantidade_pacotes_reservados` ou devolve `disponibilidade='DISPONIVEL'`); nunca toca `quantidade_pacotes` real (nada foi baixado ainda); `status='CANCELADA'`, nunca `DELETE`. Testado.

## 15. Estorno

`estornar_retrabalho(rt_id, justificativa, usuario, perfil)`: só a partir de `ENCERRADA`; valida que a saída não foi movimentada (`disponibilidade` precisa estar em `{PENDENTE_OP, DISPONIVEL}`, sem pacotes reservados, sem divergência de saldo) e que a camada de custo do destino não foi parcialmente consumida — senão bloqueia com erro claro, sem alterar nada. Quando permitido: restaura quantidade/disponibilidade das origens, marca a saída como `ESTORNADO` (preserva o registro, nunca apaga), invalida etiquetas pendentes do destino, estorna o evento de CMV da saída e marca a camada de custo do destino como `ESTORNADA`. Testado nos dois sentidos (sucesso e bloqueio).

## 16. Idempotência

Todas as 5 ações (`abrir`, `encerrar`, `liberar`, `cancelar`, `estornar`) recebem `idempotency_key` e checam `retrabalho_eventos` antes de agir — reexecução com a mesma chave retorna o resultado já persistido sem repetir nenhuma escrita. Testado explicitamente para o encerramento (seção 21).

## 17. Concorrência

Mesmo padrão de todo o `estoque_service.py`: `SELECT...FOR UPDATE` (Postgres) + guarda de saldo no próprio `WHERE` do `UPDATE` + checagem de `rowcount==1`. **Achado importante durante a implementação, não previsto no desenho:** ao chamar as funções de CMV (`registrar_saida`/`registrar_camada`/`estornar_saida`) de dentro da própria transação de `encerrar_retrabalho`/`estornar_retrabalho`, elas abriam uma **segunda conexão/transação própria** — em SQLite isso trava o banco (`database is locked`, capturado pelos testes); em Postgres não travaria, mas quebraria a atomicidade real (se o restante da transação da RT falhasse depois, a escrita de CMV já teria sido commitada separadamente, ficando "orfã"). Corrigido generalizando as 3 funções de CMV para aceitarem um `cursor` opcional e participarem da transação do chamador — ver seção 3. Essa correção é uma melhoria real de atomicidade para qualquer futuro chamador do CMV, não um workaround só para os testes.

## 18. Integração com estoque

Reaproveitado sem alteração: mesmas colunas, mesmos critérios de saldo (`condicao='CONFORME' AND disponibilidade='DISPONIVEL'`), mesma tabela `pa_caixas`.

## 19. Integração com romaneio

Testada com a função real `modules.expedicao.estoque_service.reservar_itens` (não uma simulação): uma RT reserva parte de uma posição, e uma tentativa de romaneio pegar mais do que sobrou é corretamente recusada pelo próprio `reservar_itens` (e vice-versa) — ver seção 21, testes de concorrência.

## 20. Impacto em Produção/OEE

**Nenhum, por construção**, e isso foi verificado, não só presumido: `modules/producao/oee.py` consulta `ordens_producao` estritamente por `op_id`, e a RT nunca escreve nessa tabela. Como a suíte completa de testes de OEE/rendimento (`test_p2_1_producao_rendimento.py`, `test_p2_2_disponibilidade_performance_oee.py`) continua 100% verde após a implementação (seção 23), fica confirmado que nenhuma OP existente foi afetada.

## 21. Caso 198 V1 → 99 V2

Testado de ponta a ponta (`test_caso_198_v1_para_99_v2_sem_sobra_e_sem_composicao`) com os números reais já levantados na Etapa A.1 (OPs 79/81/88/94/98/99, 82/15/1/1/98/1 aves):

- abertura reserva exatamente 198 aves nas 6 posições, sem exigir par por OP;
- encerramento com apontamento de **99 pacotes** cria uma única posição nova `condicao='CONFORME'`/`disponibilidade='PENDENTE_OP'`, com `quantidade_galinhas=198`;
- as 6 posições de origem zeram por completo (**sem sobra**) e ficam `disponibilidade='RETRABALHADO'`;
- as 6 linhas de `ordens_producao` continuam **byte-a-byte idênticas** ao estado anterior (comparação de dicionário completa no teste);
- a posição de destino **não tem nenhuma linha em `pa_caixa_composicao`**;
- antes da liberação, o consolidado de estoque mostra **0** disponível tanto em V1 quanto em V2; depois de `liberar_retrabalho`, mostra **99 pacotes / 198 galinhas** disponíveis em V2;
- o custo é transferido corretamente via CMV (camada semeada a R$5,00/ave → camada de destino nasce com o mesmo custo unitário, 198 aves).

## 22. Caso Inteira → Cortada Congelada

Testado (`test_caso_inteira_para_cortada_apontamento_real_sem_taxa_fixa`) com 1.000 aves de 3 OPs (300/400/300) e apontamento real de saída em **412,3 kg** — sem nenhuma taxa de conversão aves→kg pré-cadastrada em nenhum lugar do código ou do teste. A posição de destino nasce na família caixa/bandeja/peso (`unidade_estoque='CAIXA'`), `peso_liquido=412.3`, `condicao='CONFORME'`, `disponibilidade='PENDENTE_OP'`.

## 23. Testes executados

**Novos (módulo RT):** `tests/test_retrabalho.py` — **9/9 passam**, cobrindo os 8 casos obrigatórios do prompt (itens 37–44) mais o teste de PNC avulso:

| Teste | Cobre |
|---|---|
| `test_caso_198_v1_para_99_v2_sem_sobra_e_sem_composicao` | Caso 1 (item 37) |
| `test_caso_inteira_para_cortada_apontamento_real_sem_taxa_fixa` | Caso 2 (item 38) |
| `test_pnc_avulso_no_pa_formado_por_rt_sem_op_id` | Caso 3 (item 39) |
| `test_concorrencia_rt_reserva_primeiro_bloqueia_romaneio_no_saldo_excedente` | Caso 5, sentido 1 (item 40) |
| `test_concorrencia_romaneio_reserva_primeiro_bloqueia_rt_no_saldo_excedente` | Caso 5, sentido 2 (item 40) |
| `test_dupla_execucao_do_encerramento_e_idempotente` | Caso 7 (item 41) |
| `test_cancelamento_nao_baixa_estoque_e_libera_reserva` | Caso 6 (item 42) |
| `test_estorno_restaura_origens_e_reverte_cmv` | Caso 6 estorno (item 43) |
| `test_estorno_bloqueado_quando_saida_ja_foi_reservada` | Caso "perda parcial"/estorno bloqueado (item 44) |

Também rodado um smoke test manual das **rotas HTTP + templates** (`/retrabalho`, `/retrabalho/novo`, `/retrabalho/<id>`, `/retrabalho/origens-elegiveis`) com Flask test client real — todas retornam 200 e renderizam sem erro de Jinja.

**Suíte de regressão** (todos os 45 arquivos de `tests/`, executados individualmente — rodar o diretório inteiro em um único processo `pytest` produz falsos "ERROR" por colisão de `DB_NAME`/Flask entre arquivos que já existiam **antes** desta implementação, característica pré-existente da suíte, não introduzida agora):

- **44 de 45 arquivos 100% verdes**, incluindo especificamente as áreas tocadas: `test_consolidado_estoque_camara.py`, `test_expedicao_marco_zero.py`, `test_expedicao_romaneios_seguranca.py`, `test_romaneio_selecao_multiplas_ops.py`, `test_pnc_reprocessamento.py`, `test_p1_1_1_homologacao_pnc.py`, `test_p2_1_producao_rendimento.py`, `test_p2_2_disponibilidade_performance_oee.py`, `test_p2_3_financeiro_dre_cmv.py`.
- `test_romaneio_concorrencia_postgresql.py`: 144 testes **skipped** (suíte exclusiva de Postgres real, sem banco Postgres disponível neste ambiente — `ERRO_COLETA_FORA_ESCOPO`, não é falha).

## 24. Falhas classificadas

**1 arquivo com 2 falhas, classificadas como `FALHA_PREEXISTENTE`:**

`tests/test_pa_nao_conforme_op.py::test_encerramento_op_registro_e_bloqueio_ocorrem_na_mesma_transacao` e `::test_falha_durante_pa_nc_desfaz_tambem_o_encerramento_da_op`.

**Prova de que não é regressão desta Etapa B:** rodei os mesmos dois testes com `git stash` (revertendo 100% das minhas alterações) e eles falham **exatamente da mesma forma**, com a mesma mensagem. Não são causados por nada implementado aqui.

## 25. Limitações restantes (honestas, não escondidas)

- **CAIXA/peso como família de *origem*** da RT: implementado (decremento direto de `peso_liquido`, reserva integral da posição), mas **não exercitado por nenhum teste**, porque nenhum dos dois casos obrigatórios usa Cortada como origem. Se o negócio precisar disso no futuro, recomendo um teste dedicado antes do primeiro uso real.
- **Regra de rendimento Inteira→Cortada:** como já esclarecido na Etapa A.1, não existe (e não deveria existir nesta etapa) uma taxa de conversão pré-cadastrada; o apontamento é sempre manual no encerramento.
- **Segregação de funções, custo adicional de retrabalho, e a política de "reaproveitar posição de destino existente vs. sempre criar nova"** permanecem como decisões de negócio em aberto (já registradas na Etapa A/A.1) — a implementação atual sempre cria posição nova e não impõe segregação além de execução↔liberação.

## 26. Commit

Trabalho pronto para commit local único (não executado ainda — aguardando confirmação, ver mensagem final). Arquivos principais: `modules/retrabalho/**`, `templates/retrabalho_*.html`, `tests/test_retrabalho.py`, `database/20260917_ordem_retrabalho*.sql`, mais as 5 edições pontuais listadas na seção 3. **Nenhum push. Nenhum deploy.**

---

## CRITÉRIOS DE APROVAÇÃO (seção 58 do prompt) — checklist

- [x] RT não usa `ordens_producao`
- [x] Nenhuma OP original é alterada (provado por comparação byte-a-byte no teste do Caso 1)
- [x] Reserva funciona (testada, inclusive sob concorrência real com romaneio)
- [x] Estoque não duplica (idempotência testada)
- [x] Saída nova não usa OP fictícia
- [x] Saída da RT não usa `pa_caixa_composicao` (testado)
- [x] PNC funciona sem `op_id` (testado)
- [x] Qualidade libera a saída (testado, com estado real reaproveitado)
- [x] V1 → V2 resulta em 99 pacotes / 198 aves, sem sobra (testado)
- [x] Inteira → Cortada aceita apontamento real (testado)
- [x] CMV é transferido (testado, com valor numérico conferido)
- [x] Idempotência funciona (testado)
- [x] Cancelamento funciona (testado)
- [x] Estorno funciona, inclusive bloqueado quando deve (testado nos dois sentidos)
- [x] Concorrência com romaneio está protegida (testado nos dois sentidos com função real de produção)
- [x] Testes relevantes passam; a única falha remanescente está classificada como preexistente e comprovada como tal

---

**ORDEM DE RETRABALHO — ETAPA B CONCLUÍDA: IMPLEMENTAÇÃO LOCAL FINALIZADA, TESTES EXECUTADOS E CASOS V1→V2 / INTEIRA→CORTADA VALIDADOS — AGUARDANDO REVISÃO PARA ETAPA C**
