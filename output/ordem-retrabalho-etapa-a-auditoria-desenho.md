# FRIGODATTA — Ordem de Retrabalho (RT)
## ETAPA A — AUDITORIA E DESENHO TÉCNICO (transformação de Produto Acabado em Produto Acabado)

**SHA auditado:** `6ca3b5d80e8eea15b9da9fd8cedd8c5072e90313` (branch `codex/melhoria-romaneio-multiplas-ops`)
**Data:** 2026-09-17
**Natureza:** somente auditoria e desenho. Nenhum código, migration, schema, OP, PNC, CMV ou estoque foi alterado. Nenhum commit funcional foi feito.

---

## ETAPA A.1 — CORREÇÃO DO DESENHO CONCEITUAL (2026-09-17)

Duas correções conceituais em relação à versão original deste documento, mantendo o restante da arquitetura (entidade própria `retrabalhos`, `retrabalho_origens`, `retrabalho_saidas`, reserva na abertura, transação atômica, auditoria, idempotência, estorno compensatório, reaproveitamento do CMV, ausência de impacto em Produção/OEE):

1. **A OP de origem não limita a formação da saída.** A versão anterior deste desenho havia importado, por engano, a restrição de paridade por OP da auditoria de estoque V1→V2 (Etapa A da tarefa de *regularização de estoque*, um problema diferente: lá a conversão precisava respeitar posições de estoque já existentes uma a uma). A Ordem de Retrabalho é uma operação nova, não uma correção de posições antigas — sua saída pertence à própria RT, e as OPs de origem entram apenas como composição quantitativa do que foi consumido. Isso elimina a exigência de par (2 aves da mesma OP) e o resíduo ímpar. Seções 21/28 (casos de validação) foram corrigidas abaixo.
2. **A saída não exige uma taxa de conversão pré-cadastrada.** Para transformações sem regra fixa (ex. Inteira → Cortada Congelada), a quantidade de saída é apontada pelo resultado físico real do retrabalho, na unidade oficial do SKU de destino — rendimento/perdas são calculados depois, não são pré-condição para encerrar a RT.

Foi feita ainda uma auditoria adicional, pedida explicitamente nesta rodada: **a dependência de `pa_caixa_composicao` para uma posição de PA originada por RT** (nova seção 15-A abaixo).

---

## 1–2. Arquitetura atual de OP

`ordens_producao` (ver [database schema local](../abatedouro.db), tabela inspecionada via `PRAGMA table_info`) é uma tabela **especificamente de abate**, não uma "ordem de produção" genérica:

```
id, data, fornecedor (NOT NULL), gta, nota_fiscal, quantidade_aves (NOT NULL),
mortes_antes_pendura, peso_vivo (NOT NULL), peso_medio (NOT NULL), observacoes,
status ('Aberta'/'Encerrada'), sku, estoque_classificacao, estoque_marco_id,
versao_operacional, bloqueada_administrativamente
```

Os campos `fornecedor`, `quantidade_aves`, `peso_vivo`, `peso_medio` são **NOT NULL** e representam a entrada de aves vivas de um fornecedor — não fazem sentido para uma transformação de PA→PA. O ciclo de vida (`Aberta → Encerrada`, `estoque_classificacao`, ativação de estoque pós-marco-zero) está inteiramente amarrado a esse contexto de abate (ver [modules/expedicao/estoque_service.py:301-345](../modules/expedicao/estoque_service.py#L301-L345), `classificar_ciclo_operacional_op`).

Todo relatório de Produção/Rendimento/OEE consulta `ordens_producao` diretamente por `op_id` (ex.: [modules/producao/oee.py:143](../modules/producao/oee.py#L143), `SELECT ... FROM ordens_producao WHERE id=?`). **Isso é a base da recomendação da seção 5/40/41 abaixo.**

## 3. Arquitetura atual de PA

`pa_caixas` é a tabela única de posições de estoque de Produto Acabado (PA), tanto para Galinha Cortada (KG/caixa/bandeja) quanto para Galinha Inteira (pacote/ave). Campos relevantes já auditados na Etapa A anterior: `sku`, `apresentacao`, `unidade_estoque`, `galinhas_por_pacote`, `quantidade_pacotes`, `quantidade_galinhas`, `quantidade_pacotes_reservados`, `condicao`, `disponibilidade`, `status`, `zona_estoque`, `local_estoque_id`, `estoque_operacional`, `data_fabricacao`, `data_validade`, `origem` (texto livre, ex. `"Embalagem Primaria"`), `formado_por`/`formado_em` (usuário/data de ativação — não é um vínculo de origem, é auditoria de quem ativou o estoque), `estornada_em/por/motivo`, `versao` (controle de concorrência otimista).

`pa_caixa_composicao` vincula `caixa_id` a **exatamente um `op_id` (NOT NULL, FK obrigatória)** — ver [modules/expedicao/services.py:626-630](../modules/expedicao/services.py#L626-L630). **Esta tabela não serve para RT sem alteração**, porque seu propósito é "quais OPs de abate compuseram esta caixa", e uma RT não é uma OP. Isso é tratado na seção 9/54.

## 4. Mecanismo de consumo de estoque

O padrão já estabelecido e usado consistentemente em `modules/expedicao/estoque_service.py` (`reservar_itens`, `atualizar_reserva_quantitativa`, `concluir_romaneio`) é:

1. `SELECT ... FOR UPDATE` (Postgres) / sem lock (SQLite, single-writer) sobre a linha de `pa_caixas`;
2. `UPDATE pa_caixas SET quantidade_pacotes = quantidade_pacotes - ? WHERE id=? AND quantidade_pacotes - COALESCE(quantidade_pacotes_reservados,0) >= ?` — a condição no `WHERE` é a proteção contra corrida, não apenas o lock;
3. Checar `cursor.rowcount == 1` — se não for 1, outra transação alterou a linha antes, e a operação levanta `ValueError` (nunca segue "otimisticamente");
4. Gravar em `estoque_eventos` com `idempotency_key`.

Este é exatamente o padrão que a RT deve seguir para consumir PA de origem — não há necessidade de inventar mecanismo novo (ver seção 25).

## 5. Comportamento de reservas

`quantidade_pacotes_reservados` (para PACOTE) e a lógica equivalente para caixas/bandejas garantem que o saldo "reservável" nunca inclua o que já está preso a um romaneio aberto. A RT deve usar **a mesma fonte de saldo "disponível"** já usada por `consolidar_estoque_camara()` (`condicao='CONFORME'`, `disponibilidade='DISPONIVEL'`, `quantidade_pacotes_reservados < quantidade_pacotes` ou o equivalente para KG) — nunca calcular disponibilidade com uma query paralela.

## 6. Qualidade / PNC

Dois mecanismos distintos e não sobrepostos (auditados em `modules/qualidade/liberacoes.py` e `modules/qualidade/reprocessamento.py`):

- **Liberação de inventário legado** (`pa_nao_conforme_solicitacoes`, estados `AGUARDANDO_VALIDACAO_GERENCIA → APROVADA/REJEITADA/REVOGADA_POR_CORRECAO`): aprova PA para virar estoque operacional normal.
- **Reprocessamento de PNC rastreado** (`pnc_reprocessamentos`, estados `EM_ANDAMENTO → CONCLUIDO/CANCELADO`): move um PNC de `BLOQUEADO` para `REPROCESSO` e, ao concluir, marca a caixa como `disponibilidade='REPROCESSADO'` — **um estado terminal/histórico, não `DISPONIVEL`**. Ou seja: hoje, mesmo depois de "reprocessado", o sistema não recoloca a caixa como PA vendável automaticamente; isso ficaria para uma etapa manual fora do sistema ou para a própria RT criar a posição de saída.

**Implicação para a RT:** uma RT só pode consumir PA com `condicao='CONFORME'` e `disponibilidade='DISPONIVEL'`. PA que veio de PNC só se torna elegível **depois** de passar por um desses dois fluxos e chegar a um estado conforme/disponível — a RT não deve reimplementar nem pular a liberação de qualidade.

## 7. Rastreabilidade

Confirmado na Etapa A anterior com dados reais de produção: a granularidade de `pa_caixas` para Galinha Inteira é **uma linha por (OP, variação V1/V2)**, nunca por pacote individual. O mesmo vale estruturalmente para Galinha Cortada (uma ou mais linhas por OP, nunca por bandeja individual fora de `pa_caixa_composicao`). Isso confirma o requisito da seção 8 do escopo: a RT só precisa de rastreabilidade **quantitativa por posição de origem** (que já carrega a OP), nunca por unidade física individual.

## 8. Unidade de controle por SKU

Não existe um "motor de unidades" genérico. O que existe são **duas famílias de campos hardcoded** em `pa_caixas`, escolhidas pelo `unidade_estoque`:

- `unidade_estoque='PACOTE'` → `galinhas_por_pacote`, `quantidade_pacotes`, `quantidade_galinhas` (família Galinha Inteira);
- `unidade_estoque≠'PACOTE'` (`'CAIXA'`) → `quantidade_bandejas`, `peso_liquido`, `peso_bruto`, `peso_tara` (família Galinha Cortada/KG).

`skus.unidade_venda` (Kg/Un/Cx/L/Ml/G/Pct) é só um rótulo comercial — **não** determina automaticamente qual família de campos usar. A escolha de família hoje é decidida por código explícito (`if sku == "Galinha Inteira"` em vários pontos, ex. [modules/cmv/services.py:172](../modules/cmv/services.py#L172), [modules/expedicao/consolidado_estoque.py:151](../modules/expedicao/consolidado_estoque.py#L151)).

**Implicação honesta para a RT:** uma arquitetura 100% genérica ("qualquer SKU para qualquer SKU") exigiria um cadastro formal de "família de unidade" por SKU, que **não existe hoje**. Sem isso, a RT pode ser desenhada de forma genérica na sua **estrutura de dados e fluxo** (entidade RT + origens + destino, ver seções 9–20), mas a **rotina de escrita do PA de destino** precisa, na prática, despachar para uma de duas implementações conhecidas (pacote×aves ou caixa/bandeja×peso) com base no `unidade_estoque` do SKU de destino — exatamente como o resto do sistema já faz. Isso é uma dependência explícita registrada na seção "Decisões Necessárias", não um bloqueio: os dois casos pedidos (V1→V2 e Inteira→Cortada) já cobrem as duas famílias existentes, então a RT já nasce cobrindo 100% dos casos reais hoje possíveis — só não cobre uma terceira família hipotética que ainda não existe no sistema.

## 9. Custo / CMV

**Achado mais importante da auditoria:** o mecanismo de custo em `modules/cmv/services.py` já é polimórfico e pronto para isto. `cmv_camadas` tem `origem_tipo`/`origem_id` genéricos (hoje só usa `'OP'`, mas nada no schema ou no código impede um novo valor). `registrar_saida()` consome FIFO por `(produto, unidade)` e grava em `cmv_consumos`; `registrar_camada()` cria uma nova camada com `custo_unitario` explícito. O único ponto que precisa de ajuste (não implementar agora) é a validação `if tipo_evento not in ("VENDA", "DESCARTE")` em [modules/cmv/services.py:234](../modules/cmv/services.py#L234), que precisaria aceitar um novo valor (ex. `"RETRABALHO"`).

**Fluxo de custo recomendado para a RT (desenho, não implementação):**
1. Ao encerrar a RT, para cada origem consumida, chamar `registrar_saida(produto=<sku origem>, unidade=<unidade origem>, quantidade=<consumida>, origem_tipo='RETRABALHO', origem_id=str(rt_id), tipo_evento='RETRABALHO')` — isso já faz o FIFO e devolve `custo_total` conhecido ou não.
2. Somar os `custo_total` das saídas de todas as origens + eventual custo adicional do próprio retrabalho (mão de obra/insumo, se a RT tiver isso — ver seção 15/43) = custo total do lote de saída.
3. Chamar `registrar_camada(produto=<sku destino>, unidade=<unidade destino>, quantidade=<produzida>, custo_unitario=<custo total / quantidade>, origem_tipo='RETRABALHO', origem_id=str(rt_id), ...)` para o PA resultante.

Isso reaproveita 100% do motor de custo existente — **nenhuma tabela de custo nova é necessária.**

## 10–11. Impacto em Produção e OEE

Como `modules/producao/oee.py` e os relatórios de rendimento consultam `ordens_producao` estritamente por `op_id` (ver seção 1), **se a RT não for uma linha em `ordens_producao`, ela é automaticamente invisível para Produção/Rendimento/OEE, sem precisar de nenhum filtro de exclusão.** Isso é o argumento decisivo a favor da Opção B na seção "Entidade recomendada" abaixo — a Opção A (reaproveitar `ordens_producao` com um campo `tipo`) exigiria adicionar filtros `WHERE tipo <> 'RETRABALHO'` em todo relatório de Produção/OEE/Rendimento hoje existente, com risco real de esquecer algum.

## 12. Impacto em Expedição

Nenhum — a saída da RT é apenas mais uma linha de `pa_caixas` `CONFORME/DISPONIVEL`, e toda a lógica de romaneio já auditada (reserva por `galinhas_por_pacote` dinâmico, ou por peso/caixa) já lida com qualquer linha nova de `pa_caixas` sem distinguir sua origem. Nenhuma mudança necessária em `modules/expedicao`.

## 13. Impacto em etiquetas

`modules/label_printing/services.py` já opera por `caixa_id`, com duas funções prontas e genéricas:
- `invalidar_jobs_caixa_cursor(cursor, caixa_id, motivo=...)` ([services.py:175](../modules/label_printing/services.py#L175)) — invalida etiquetas de uma posição que deixou de existir;
- `criar_job_caixa_cursor(cursor, caixa_id, solicitado_por=...)` ([services.py:136](../modules/label_printing/services.py#L136)) — cria um novo job de impressão para uma posição nova.

A RT reaproveita as duas sem nenhuma alteração: ao zerar/encerrar uma posição de origem, chama `invalidar_jobs_caixa_cursor`; ao criar a posição de destino, chama `criar_job_caixa_cursor`.

## 14. Validade / data de fabricação

Não existe hoje uma regra sanitária formal para "validade após retrabalho" em nenhum lugar do código (nenhuma constante, nenhuma função `calcular_validade_retrabalho` ou equivalente — só existe `calcular_validade_padrao(data_fabricacao)` para o caso de produção normal). **Isto é uma decisão necessária do usuário/Qualidade, não uma lacuna técnica que a auditoria possa resolver** (ver Decisões Necessárias). O mesmo vale para "nova data de fabricação vs. preservar a mais antiga" — não há regra hoje.

---

## 15-A. Dependência de `pa_caixa_composicao` para o PA resultante da RT

Pergunta desta rodada: uma posição nova em `pa_caixas` gerada por RT pode existir e funcionar corretamente **sem** nenhuma linha em `pa_caixa_composicao`? `pa_caixa_composicao.op_id` é `NOT NULL` e é FK conceitual para `ordens_producao` (tabela de abate) — não pode nem deve receber uma OP fictícia (proibido explicitamente pelo usuário, e já era a recomendação técnica: nunca inventar OP fake).

Auditoria linha a linha dos consumidores de `pa_caixa_composicao` (`grep` em todo `modules/`):

| Fluxo | Tipo de junção | Efeito se a posição RT não tiver linha em `pa_caixa_composicao` |
|---|---|---|
| Estoque consolidado (`consolidado_estoque.py::_linhas_pos_marco`) | **Nenhuma junção** — lê `pa_caixas` puro | Nenhum — a posição aparece normalmente no saldo disponível. |
| Estoque operacional (`estoque_service.py::buscar_estoque_operacional`, [linha 683](../modules/expedicao/estoque_service.py#L683)) | `LEFT JOIN` | Nenhum — `op_id` retorna `NULL`, posição aparece normalmente. |
| Reserva em romaneio (`estoque_service.py::reservar_itens`, [linha 1025-1032](../modules/expedicao/estoque_service.py#L1025-L1032)) | Subquery escalar `(SELECT MIN(comp.op_id) ...)`, não é junção que filtra | Nenhum — a caixa é buscada direto por `cx.id`; `op_id` fica `NULL`. Confirmado: `expedicao_itens.op_id` é **nullable** no schema, então a reserva grava normalmente. O único bloqueio seria se o romaneio for do tipo "por OP específica" (`op_id_esperada` informado) — nesse caso a posição RT simplesmente não aparece nessa tela filtrada, o que é o comportamento correto (ela não pertence a nenhuma OP). |
| Etiquetas (`label_printing/services.py`) | Nenhuma dependência — opera 100% por `caixa_id` | Nenhum. |
| CMV (`cmv/services.py::registrar_saida`/`registrar_camada`) | Nenhuma dependência — opera por `(produto, unidade)`, não por composição | Nenhum (a RT nunca chama `calcular_custo_op`, que é o único ponto do CMV que usa `pa_caixa_composicao` — e é exclusivo do fluxo de custeio de OP de abate). |
| Histórico (`estoque_eventos`) | Nenhuma dependência — grava por `caixa_id` | Nenhum. |
| Relatórios de Produção/Rendimento/OEE/reconciliação marco-zero (`relatorios/producao.py`, `dashboard/repositories.py`, `expedicao/reconciliacao_marco_zero.py`, `producao/integridade_encerramento.py`) | `INNER JOIN`/`EXISTS` sobre `pa_caixa_composicao` | A posição RT **fica de fora** desses relatórios — e isso é exatamente o comportamento desejado (seção 40 do escopo: RT não deve se misturar com produção primária). |
| Qualidade — registro de PNC oficial rastreado (`qualidade/produtos_nao_conformes.py`, [linha 243-252](../modules/qualidade/produtos_nao_conformes.py#L243-L252)) | `JOIN` obrigatório, exige `comp.op_id = ?` | **Único gap real encontrado.** O fluxo atual de "registrar Produto Não Conforme" está arquiteturalmente amarrado ao encerramento de uma OP (`registrar_itens_encerramento(cursor, op_id, itens, ...)`) e não tem hoje uma porta de entrada genérica "marcar esta caixa como PNC independente de OP". |

**Conclusão: `pa_caixa_composicao` é opcional para a posição de saída da RT.** A recomendação é **não criar nenhuma linha em `pa_caixa_composicao` para posições originadas por RT** — a rastreabilidade de origem passa a ser `retrabalho_saidas.caixa_id_destino → retrabalhos.id → retrabalho_origens` (seção 16), e o campo texto `pa_caixas.origem` grava `"Retrabalho"` só para leitura humana. Nenhuma migration em `pa_caixa_composicao` é necessária.

**Gap real registrado (não bloqueia a RT, mas precisa de decisão futura):** se uma posição originada por RT precisar ser flagrada como Produto Não Conforme depois de criada, o fluxo atual de Qualidade não tem caminho para isso (exige `op_id`). A menor adaptação seria, no futuro, permitir que a query de `qualidade/produtos_nao_conformes.py` aceite `op_id IS NULL` combinado com uma verificação alternativa via `retrabalho_saidas.caixa_id_destino = cx.id` — mudança pequena e isolada, não implementada nesta etapa. Registrado na lista de decisões pendentes.

---

## 15. Entidade recomendada: Ordem de Retrabalho como entidade própria (Opção B)

Comparando as três opções da seção 5 do escopo:

| Critério | A) `ordens_producao` + campo `tipo` | B) Entidade própria (`retrabalhos`) | C) Outra arquitetura |
|---|---|---|---|
| Risco de quebrar OP normal | **Alto** — campos NOT NULL (`fornecedor`, `quantidade_aves`, `peso_vivo`, `peso_medio`) exigiriam valores fictícios/nulos, e qualquer relatório que faça `SELECT * FROM ordens_producao` sem filtro de tipo passa a incluir RT | **Nenhum** — tabela nova, zero mudança em `ordens_producao` | — |
| Relatórios de Produção/Rendimento/OEE | Exige adicionar `WHERE tipo <> 'RETRABALHO'` em todo relatório existente (risco de esquecer) | Automaticamente fora, sem nenhuma alteração (seção 10–11) | — |
| Financeiro/CMV | Neutro nos dois casos — CMV já é por produto/origem, não por OP | Neutro | — |
| Permissões | Reaproveita perfis existentes nos dois casos | idem | — |
| Simplicidade | Aparenta menor esforço inicial, mas acumula dívida (campos inaplicáveis, filtros espalhados) | Mais tabelas novas, porém isoladas e sem efeito colateral | — |

**Recomendação: Opção B.** Nome de exibição **"Ordem de Retrabalho"**, identificador **`RT-000001`** (sequência própria, formato análogo ao já usado — comparar com `codigo_caixa` e a numeração de OP — mas com prefixo distinto `RT-` para nunca ser confundido visualmente com `OP-xxxxx` em nenhuma tela, etiqueta ou relatório). Tipo interno de tabela: `retrabalhos` (nome técnico livre, ver seção 53).

## 16. Tabelas/migrations prováveis (não criar agora)

**Obrigatório para o caso de uso real (V1→V2 e Inteira→Cortada):**

- `retrabalhos` — cabeçalho: `id, numero (RT-000001), status, motivo, sku_origem, apresentacao_origem, sku_destino, apresentacao_destino, quantidade_planejada_origem, unidade_origem, quantidade_planejada_destino, unidade_destino, responsavel, perfil_responsavel, data_planejada, criado_em, criado_por, encerrado_em, encerrado_por, idempotency_key, versao (lock otimista, igual a `pa_caixas.versao`)`.
- `retrabalho_origens` — linha por posição de origem consumida: `id, retrabalho_id, caixa_id_origem (FK pa_caixas), op_id_origem (herdado da composição da caixa, não obrigatório redigitar), quantidade_consumida, unidade, condicao_no_momento, snapshot_json, criado_em`. Exatamente como sugerido no escopo (seção 9) — a auditoria concorda que essa é a estrutura correta.
- `retrabalho_saidas` — linha por posição de destino criada: `id, retrabalho_id, caixa_id_destino (FK pa_caixas), quantidade, unidade, criado_em`. (Normalmente 1 linha, mas manter 1:N permite, por exemplo, uma RT gerar posições em mais de um lote de validade se necessário no futuro.)
- `retrabalho_eventos` — trilha de auditoria dedicada (mesmo padrão de `estoque_eventos`/`cmv_auditoria`): `id, retrabalho_id, acao, estado_anterior, estado_novo, usuario, perfil, origem, justificativa, dados_json, criado_em`.
- Um novo `acao` em `estoque_eventos` (não precisa de coluna nova, é um valor de texto): `"RETRABALHO_CONSUMO"` e `"RETRABALHO_FORMACAO"`, seguindo a convenção já usada (`FORMACAO_ESTOQUE`, `RESERVA`, `BLOQUEIO_NAO_CONFORMIDADE`, ver seção 4).

**Opcional/futuro (não obrigatório para os dois casos de validação):**

- Coluna `perdas_json` ou tabela `retrabalho_perdas` se o negócio precisar detalhar perdas por tipo (seção 17) — para o caso V1→V2 e Inteira→Cortada informados, não há perda esperada declarada, então pode ficar como campo simples `quantidade_perda`/`justificativa_perda` no cabeçalho por ora.
- Extensão de `cmv_services.registrar_saida` para aceitar `tipo_evento='RETRABALHO'` (mudança de uma linha, mas é código, não é desta etapa).
- Cadastro formal de "família de unidade por SKU" (mencionado na seção 8) — dependência de médio prazo, fora do escopo desta RT.

## 17. Máquina de estados

Simplificando a lista sugerida no escopo (não copiar OP sem necessidade — OP não tem estado `AGUARDANDO_CONFERENCIA` nem `RASCUNHO`, por exemplo, porque OP nasce direto "Aberta"):

```
RASCUNHO → ABERTA → EM_EXECUCAO → ENCERRADA
                 ↘ CANCELADA
                              ENCERRADA → ESTORNADA
```

- `RASCUNHO`: formulário salvo, nada reservado, pode ser descartado sem rastro além do próprio rascunho.
- `ABERTA`: origens selecionadas e **reservadas** (ver seção 18 — recomendação é reservar, não só "selecionar"). Ainda não houve baixa de estoque.
- `EM_EXECUCAO`: opcional — só necessário se a operação física do retrabalho não for instantânea (ex.: linha de reembalagem rodando). Para o caso V1→V2 (retrabalho já realizado fisicamente e só sendo regularizado no sistema), este estado pode ser pulado (`ABERTA → ENCERRADA` direto).
- `ENCERRADA`: baixa da origem + formação do destino já ocorreram, atomicamente (seção 19/25).
- `CANCELADA`: só a partir de `RASCUNHO` ou `ABERTA` — libera reserva, não mexe em estoque real.
- `ESTORNADA`: só a partir de `ENCERRADA` — compensatório (seção 27).

`AGUARDANDO_CONFERENCIA` do escopo original foi absorvido em `EM_EXECUCAO`/`ENCERRADA` para não criar um estado sem transição clara — se o negócio precisar de uma conferência humana obrigatória antes do encerramento, ela cabe dentro de `EM_EXECUCAO` sem precisar de estado novo.

## 18. Fluxo de criação (abertura)

Campos do formulário (todos já mapeáveis para tabelas existentes, nenhum dado novo a inventar): motivo (texto livre + justificativa obrigatória, mesmo padrão de `reprocessamento.py`), produto de origem (SKU ativo `PRODUTO_ACABADO`, de `skus`/`engenharia_produtos`), posições de origem (lista de `pa_caixas.id` elegíveis, ver query abaixo), quantidade a consumir por posição, SKU de destino (mesmo filtro de catálogo), apresentação de destino, observações, responsável (usuário da sessão), data planejada.

Query de seleção de origem (reaproveita exatamente os mesmos critérios de "disponível" já auditados, sem inventar novo):

```sql
SELECT cx.id, comp.op_id, cx.codigo_caixa, cx.quantidade_pacotes, cx.quantidade_galinhas,
       cx.quantidade_pacotes_reservados, cx.data_fabricacao, cx.data_validade
FROM pa_caixas cx
JOIN pa_caixa_composicao comp ON comp.caixa_id = cx.id
WHERE cx.sku = ? AND cx.galinhas_por_pacote = ?
  AND cx.condicao = 'CONFORME' AND cx.disponibilidade = 'DISPONIVEL'
  AND cx.estoque_operacional = 1
```

## 19. Fluxo de execução / reserva (seção 29 do escopo)

**Recomendação: reservar no momento da abertura (opção B do escopo), não só "selecionar".** Justificativa: o sistema já tem `quantidade_pacotes_reservados` exatamente para impedir que Expedição e outro processo disputem o mesmo saldo (ver `reservar_itens`, seção 4). Se a RT apenas "selecionasse" sem reservar, um romaneio concorrente poderia reservar o mesmo saldo entre a abertura e o encerramento da RT, e o encerramento falharia tarde (pior experiência) em vez de falhar cedo na abertura. Reservar imediatamente segue exatamente o padrão de risco que a seção 24 do escopo pede para evitar.

Implementação (desenho): incrementar `quantidade_pacotes_reservados` (ou o equivalente KG/caixa) nas posições de origem, dentro de uma transação com `SELECT...FOR UPDATE`, gravando a reserva em `retrabalho_origens`. Isso é literalmente o mesmo código-caminho de `reservar_itens`, generalizado para uma tabela de destino diferente (`retrabalho_origens` em vez de `expedicao_itens`).

## 20. Fluxo de encerramento

Transação única (ver seção 25):
1. Para cada `retrabalho_origens`: `UPDATE pa_caixas SET quantidade_pacotes = quantidade_pacotes - ?, quantidade_galinhas = quantidade_galinhas - ?, quantidade_pacotes_reservados = quantidade_pacotes_reservados - ? WHERE id=? AND ...` (mesma proteção de `rowcount==1` da seção 4); se a linha zerar, marcar como encerrada/estornada preservando histórico (não `DELETE`) e chamar `invalidar_jobs_caixa_cursor`.
2. Criar (ou, se já existir uma posição CONFORME/DISPONIVEL compatível — decisão de negócio, não técnica, ver Decisões Necessárias) a posição de destino em `pa_caixas`, com `origem='Retrabalho'`, **sem linha em `pa_caixa_composicao`** (ver seção 15-A — a rastreabilidade de origem vive em `retrabalho_saidas`, não em `pa_caixa_composicao`, que fica reservada só para OPs de abate), `condicao`/`disponibilidade` conforme seção 35, e `criar_job_caixa_cursor` para a etiqueta nova.
3. Gravar `retrabalho_saidas`.
4. Chamar `registrar_saida(...)` e `registrar_camada(...)` do CMV (seção 9).
5. Gravar `estoque_eventos` (`RETRABALHO_CONSUMO` por origem, `RETRABALHO_FORMACAO` para o destino) e `retrabalho_eventos`.
6. `UPDATE retrabalhos SET status='ENCERRADA', ...`.

## 21. Cancelamento

Só permitido em `RASCUNHO`/`ABERTA`. Reverte exatamente a reserva feita na seção 19 (`quantidade_pacotes_reservados -= ?` nas origens), sem tocar em `quantidade_pacotes` real (nada foi baixado ainda). Preserva o registro da RT com `status='CANCELADA'` e a justificativa — nunca `DELETE`.

## 22. Estorno

Só a partir de `ENCERRADA`. Compensatório, seguindo exatamente o padrão já usado em `estornar_saida` do CMV (seção 9) e em `embalagem_secundaria_estornos` (Etapa A anterior, seção 11): devolve `quantidade_pacotes`/`quantidade_galinhas` às posições de origem (ou cria uma nova posição de "devolução" se a antiga foi fisicamente encerrada — mesma lógica dos estornos já existentes), zera/encerra a posição de destino criada, estorna os eventos de CMV, invalida a etiqueta do destino e (se aplicável) recria job da origem. Nunca hard delete. Risco principal: se a posição de destino já foi parcialmente consumida por um romaneio antes do estorno, o estorno deve falhar com mensagem clara (mesmo comportamento de `remover_item_reservado`/`cancelar_romaneio` quando há reserva ativa) — não forçar.

## 23. Permissões

Perfis existentes no sistema (`modules/auth/services.py`): `admin, pcp, producao, qualidade, manutencao, gerencia`. Seguindo o padrão de `PERFIS_REPROCESSAMENTO = {"admin", "gerencia", "qualidade"}` ([modules/qualidade/reprocessamento.py:14](../modules/qualidade/reprocessamento.py#L14)), recomenda-se:

- **Criar RT:** `admin, pcp, producao, gerencia` (quem planeja produção deveria poder abrir);
- **Executar/encerrar:** `admin, gerencia` (ação que baixa estoque real e gera custo — mais restrita);
- **Cancelar:** mesmo perfil de quem criou, ou `admin, gerencia`;
- **Estornar:** `admin, gerencia` apenas (mesmo padrão de `PERFIS_REPROCESSAMENTO` para ações destrutivas/compensatórias).

Nenhum perfil novo é necessário. (Isto é uma recomendação técnica com base no padrão existente, não uma decisão de negócio — o usuário pode ajustar a matriz exata, ver Decisões Necessárias.)

## 24. Segregação de funções

Não há hoje, em nenhum módulo do sistema, uma regra formal de "quem cria não pode encerrar" (nem em romaneio, nem em reprocessamento, nem em correções administrativas — todos permitem que o mesmo usuário execute o ciclo completo se tiver o perfil). **Não é uma lacuna técnica, é ausência de política.** Registrado como decisão necessária.

## 25. Auditoria e histórico

Reaproveitar integralmente `estoque_eventos` (para as mudanças de `pa_caixas`) mais uma tabela dedicada `retrabalho_eventos` (para o ciclo de vida da própria RT: criação, reserva, cancelamento, encerramento, estorno), no mesmo formato de `snapshot_json`/`idempotency_key` já usado em `pnc_reprocessamentos` e `embalagem_secundaria_estornos`. Cada RT deve aparecer em `buscar_historico_estoque()` (função já existente, [estoque_service.py:967](../modules/expedicao/estoque_service.py#L967)) automaticamente, desde que os eventos usem `_inserir_evento` com `caixa_id` corretamente preenchido — nenhuma mudança nessa função é necessária.

## 26. Idempotência e transação

Padrão já onipresente no sistema (`estoque_eventos.idempotency_key UNIQUE`, `cmv_eventos.idempotency_key UNIQUE`, `pnc_reprocessamentos.idempotency_key UNIQUE`, `embalagem_secundaria_estornos.idempotency_key UNIQUE`, `label_print_jobs.idempotency_key`): toda ação de escrita recebe uma `idempotency_key` (gerada pelo cliente ou como `f"RT:{rt_id}:ENCERRAR"`), e a rotina primeiro faz `SELECT` por essa chave — se já existe, retorna o resultado anterior sem reexecutar. A RT deve seguir exatamente esse padrão para criação, encerramento, cancelamento e estorno. Transação: `with transaction() as conn:` (context manager já usado em todo `estoque_service.py`) com `SELECT...FOR UPDATE` nas linhas de `pa_caixas` envolvidas, igual à seção 4.

---

## 27. Riscos

1. **Dupla baixa de estoque** — mitigado por idempotency_key + `rowcount==1` (seção 26).
2. **Consumo de saldo reservado** — mitigado por reservar na abertura, não apenas na execução (seção 19).
3. **Quebra de rastreabilidade** — mitigado por `retrabalho_origens` (quantitativo por posição/OP) + `origem='Retrabalho'` em vez de reescrever a origem antiga.
4. **Mistura indevida de PA bloqueado** — mitigado exigindo `condicao='CONFORME' AND disponibilidade='DISPONIVEL'` nas origens, igual ao filtro já usado na Etapa A.
5. **Alteração de OP original** — mitigado por design: RT nunca escreve em `ordens_producao` (Opção B, seção 15).
6. **Duplicação de saída** — mitigado por idempotency_key no encerramento.
7. **Validade incorreta** — **sem mitigação técnica hoje; é decisão de negócio pendente (seção 14).**
8. **Custo incorreto** — mitigado reaproveitando o motor FIFO existente (seção 9) em vez de calcular custo à mão.
9. **Impacto em CMV** — nenhum, se o novo `tipo_evento` for aditivo (não quebra `VENDA`/`DESCARTE` existentes).
10. **Impacto em Produção/OEE** — nenhum, por design (seção 10–11).
11. **Estorno incompleto** — mitigado seguindo o mesmo padrão transacional de `embalagem_secundaria_estornos`/`cmv.estornar_saida`, nunca parcial fora de uma única transação.
12. **Concorrência com Expedição** — mitigado por `FOR UPDATE` + reserva imediata (mesma técnica que já protege romaneio vs. romaneio hoje).

---

## 28. Validação explícita dos dois casos obrigatórios (corrigido na Etapa A.1)

### Caso 1 — V1 → V2 (198 aves → 99 pacotes V2, sem resíduo)

```
RT-000001
Origem: Galinha Inteira V1 (LEG-2, galinhas_por_pacote=1)
  OP 79 → 82 aves   (posição GI-PCT-OP-00079-V1)
  OP 81 → 15 aves   (posição GI-PCT-OP-00081-V1)
  OP 88 →  1 ave    (posição GI-PCT-OP-00088-V1)
  OP 94 →  1 ave    (posição GI-PCT-OP-00094-V1)
  OP 98 → 98 aves   (posição GI-PCT-OP-00098-V1)
  OP 99 →  1 ave    (posição GI-PCT-OP-00099-V1)
  Total consumido: 198 aves (198 pacotes V1, todos com quantidade_pacotes_reservados=0)
Destino: Galinha Inteira V2 (LEG-2, galinhas_por_pacote=2)
  99 pacotes / 198 aves — UMA posição nova em pa_caixas, sem linha em pa_caixa_composicao
  (origem='Retrabalho', rastreada via retrabalho_saidas → RT-000001, ver seção 15-A)
Conciliação: 198 aves consumidas = 198 aves produzidas. Nenhum resíduo.
```

Não há pareamento por OP: a RT soma as 198 aves de todas as 6 origens e forma diretamente 99 pacotes V2 (198 ÷ 2) numa única posição de saída. A rastreabilidade fica inteiramente em `retrabalho_origens` (quanto foi consumido de cada uma das 6 posições/OPs) — o sistema não precisa (e não deve) saber "quais 2 aves específicas viraram qual pacote". Nenhuma OP é reaberta; todas permanecem `Encerrada`, intocadas.

### Caso 2 — Galinha Inteira → Galinha Cortada Congelada

```
RT-000002
Origem: Galinha Inteira (SKU LEG-2, qualquer apresentação/OP elegível)
  OP 81 → 300 aves
  OP 90 → 400 aves
  OP 95 → 300 aves
  Total consumido: 1.000 aves
Destino: SKU existente de Galinha Cortada Congelada (família KG/caixa/bandeja, não pacote/ave)
  Quantidade de saída: APONTADA no encerramento da RT a partir do resultado físico real
  (ex.: X kg pesados), na unidade oficial do SKU de destino — não depende de uma taxa de
  conversão aves→kg pré-cadastrada (que hoje não existe no sistema, ver seção 8).
  Rendimento/perda (1.000 aves → X kg) fica disponível como indicador calculado a
  posteriori (quantidade_planejada vs. quantidade apontada), não como pré-condição de encerramento.
```

A estrutura (`retrabalhos` + `retrabalho_origens` + `retrabalho_saidas`) é idêntica ao Caso 1 — nenhuma tabela nova, nenhum campo condicional a `if origem==V1`. A única parte que muda entre os dois casos é **qual rotina de escrita do PA de destino é chamada** (família pacote×ave vs. família caixa/bandeja×peso), escolhida pelo `unidade_estoque` cadastrado do SKU de destino — exatamente como o resto do sistema já decide isso hoje (seção 8). **Isto satisfaz a condição da seção 50 do escopo: nenhuma lógica arquitetural do tipo `if origem==V1 and destino==V2`.** A conciliação entre 1.000 aves (entrada) e X kg (saída) não exige igualdade de unidade — o par consumido/produzido é registrado em `retrabalhos` (`quantidade_planejada_origem`/`unidade_origem` vs. `quantidade_apontada_destino`/`unidade_destino`), e cada família é conciliada com sua própria métrica, sem uma regra universal de conversão.

---

## DECISÕES NECESSÁRIAS DO USUÁRIO (revisado na Etapa A.1; fechadas/implementadas na Etapa B/C)

**Removidas na Etapa A.1** (resolvidas pela correção conceitual da seção "ETAPA A.1" acima): tratamento de sobras ímpares por OP no Caso 1 (não existem mais — 198→99 sem resíduo); obrigatoriedade de taxa de conversão fixa Inteira→Cortada para permitir o encerramento da RT.

**Fechadas pelo usuário e já implementadas na Etapa B, confirmadas na Etapa C** (ver `output/ordem-retrabalho-etapa-c-auditoria-regressao.md`):
- item 3 (custo adicional de retrabalho): **decisão — não incorporar nesta versão.** Implementado: só o custo do PA consumido é transportado.
- item 4 (segregação de funções): **decisão — não exigir usuário diferente entre abrir e encerrar; a segregação real é execução↔liberação pela Qualidade.** Implementado exatamente assim.
- item 6 (reaproveitar posição existente vs. sempre criar nova): **decisão — sempre criar nova.** Implementado exatamente assim.
- item 2 (condição do PA ao nascer): implementado como `PENDENTE_OP` (reaproveitando o estado já existente no sistema para "formado, aguardando liberação"), com liberação explícita pela Qualidade via `liberar_retrabalho`.
- item 7 (gap de Qualidade para PA de RT): fechado pela função `registrar_pnc_avulso`, testada inclusive para o caso de PNC detectado antes da liberação (Etapa C).

**Ainda realmente pendentes:**
1. **Validade e data de fabricação após retrabalho:** o sistema agora *valida* que a validade não seja anterior à fabricação (Etapa C), mas a regra sanitária de negócio (manter a mais restritiva das origens? nova validade a partir do retrabalho?) continua não formalizada — precisa vir de Qualidade/regulatório.
5. **Matriz exata de perfis por ação:** a implementada (abrir/encerrar/cancelar: admin/gerência/pcp/produção; liberar: admin/gerência/qualidade; estornar: admin/gerência apenas) é a recomendação técnica adotada como decisão — sujeita a ajuste fino do usuário/gerência se necessário.

---

## PROIBIÇÕES RESPEITADAS

Nenhum código funcional foi alterado. Nenhuma migration, tabela, coluna ou índice foi criado. Nenhuma OP foi aberta, encerrada ou reaberta. Nenhum estoque foi consumido ou criado. Nenhum commit funcional, push ou deploy foi feito. Este arquivo é o único artefato produzido nesta etapa.

---

**ORDEM DE RETRABALHO — ETAPA A.1 CONCLUÍDA: RASTREABILIDADE QUANTITATIVA DE ORIGENS E SAÍDA POR RT CONSOLIDADAS — AGUARDANDO REVISÃO PARA ETAPA B**
