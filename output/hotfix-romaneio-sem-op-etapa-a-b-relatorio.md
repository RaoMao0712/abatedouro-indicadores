# FRIGODATTA — Hotfix Romaneio: seleção de PA disponível sem OP (suporte a estoque de Retrabalho)

Etapas A (auditoria) e B (implementação) — sem deploy, sem produção.

## 1. Objetivo
Permitir que o romaneio (TRANSFERENCIA e VENDA_DIRETA) selecione e reserve posições de
Produto Acabado `CONFORME`/`DISPONIVEL` que não possuem OP vinculada (`pa_caixa_composicao`
vazia) — hoje, a única origem real desse tipo de estoque é a Ordem de Retrabalho (RT) — sem
alterar a modelagem de RT, sem criar OP fictícia e sem escrever em `pa_caixa_composicao`.

## 2. Etapa A — Auditoria (achados)

1. Rota de detalhe: `detalhe_romaneio_expedicao` em [modules/expedicao/routes.py:738](modules/expedicao/routes.py#L738).
2. Template: [templates/romaneio_detalhe.html](templates/romaneio_detalhe.html).
3. "Carregar OP" usa os endpoints `/expedicao/<id>/selecao-ops/<op_id>[...]`, todos construídos
   sobre `buscar_op_para_romaneio`, `buscar_caixas_elegiveis_op`, `buscar_saldos_quantitativos_op`,
   `buscar_modalidades_controle_op` — todos exigem `op_id` e fazem `JOIN`/`EXISTS` contra
   `pa_caixa_composicao`. Nenhum deles foi alterado.
4. `reservar_itens` (modules/expedicao/estoque_service.py:993) **já tolera `op_id=NULL`**: quando
   chamada sem `op_id_esperada`, busca a caixa só por `cx.id` (o `op_id` vem de um subselect
   escalar `MIN(comp.op_id)`, não de um JOIN filtrante) e não valida nenhuma composição. Essa é
   exatamente a função já usada pela seção "Itens elegíveis para reserva" dos romaneios
   DESCARTE/DEVOLUCAO/TRANSFERENCIA_AUTORIZADA (checkbox + campo de quantidade) — só que essa
   seção nunca é mostrada para TRANSFERENCIA/VENDA_DIRETA, que só oferecem "Carregar OP".
   **Esse é o bloqueio real: puramente de descoberta/seleção na tela, não no backend.**
5. `atualizar_reserva_quantitativa` (linha 1156) é **estrutural e propositalmente exclusiva de
   OP**: exige `EXISTS (... pa_caixa_composicao WHERE caixa_id=? AND op_id=?)`. É o ajuste fino
   de "saldo em aves" do fluxo "Carregar OP" (Galinha Inteira). Não é necessária para o novo
   painel, pois `reservar_itens` já aceita a quantidade exata de pacotes no ato da reserva
   (mesmo padrão já usado na tabela de NÃO CONFORME). Verificado que ela continua rejeitando
   uma posição de RT (sem composição) com `ValueError` — comportamento preservado, não alterado.
6. `remover_item_reservado` já opera só por `caixa_id`, com `op_id_esperada` opcional — funciona
   para itens sem OP sem qualquer alteração.
7. `concluir_romaneio`, `cancelar_romaneio`, `estornar_romaneio` operam inteiramente por
   `expedicao_itens.caixa_id` via `LEFT/INNER JOIN pa_caixas`; nenhum depende de `op_id` ou de
   `pa_caixa_composicao`. Confirmado por leitura completa das três funções.
8. `concluir_reservas_cursor`/`cancelar_reservas_cursor`/`estornar_baixas_cursor`
   (modules/qualidade/liberacoes.py) filtram por `origem_tipo=TIPO_LEGADO` (saldo agregado
   legado) — não tocam em itens de romaneio normais (com ou sem OP); nenhuma interação com RT.
9. `buscar_estoque_operacional()` (linha 679) já é genérica: `LEFT JOIN pa_caixa_composicao`
   (não filtra por ela) e já exclui `disponibilidade='RETRABALHADO'` (das posições de origem já
   consumidas pela RT). A posição de destino da RT (`CONFORME`/`DISPONIVEL` após liberação da
   Qualidade) aparece nela normalmente, com `op_id=NULL`.
10. `pa_caixas.origem='Retrabalho'` e `observacoes='Formado pela Ordem de Retrabalho {numero}.'`
    são gravados por `encerrar_retrabalho` (modules/retrabalho/services.py:551,569) — usados aqui
    apenas para exibição, sem nenhuma consulta nova.
11. `buscar_itens_expedicao` (modules/expedicao/services.py:2146) não expunha `origem`/
    `observacoes` da caixa — por isso a tela "Itens do romaneio" e a impressão mostravam
    "Não identificada" para um item de RT já reservado, mesmo com o backend funcionando.

**Conclusão da Etapa A:** não há bloqueio estrutural em `reservar_itens`, `remover_item_reservado`
nem no ciclo de vida do romaneio. O único bloqueio é a ausência de uma tela de seleção para
estoque sem OP nos tipos TRANSFERENCIA/VENDA_DIRETA, e a rotulagem de origem ("Não identificada")
nas telas de item/impressão.

## 3. Etapa B — Implementação (aditiva)

1. [modules/expedicao/routes.py](modules/expedicao/routes.py) — `detalhe_romaneio_expedicao`:
   novo cálculo `estoque_sem_op` (apenas para TRANSFERENCIA/VENDA_DIRETA, romaneio Aberto):
   `condicao='CONFORME' AND disponibilidade='DISPONIVEL' AND op_id IS NULL`, excluindo itens já
   selecionados no próprio romaneio. Zero alteração nas rotas/funções de "Carregar OP".
2. [modules/expedicao/services.py](modules/expedicao/services.py) — `buscar_itens_expedicao`
   passa a trazer `cx.origem AS origem_caixa` e `cx.observacoes AS observacoes_caixa` (2 colunas
   a mais no SELECT; usado pela tela de itens e pela impressão).
3. [templates/romaneio_detalhe.html](templates/romaneio_detalhe.html) — nova seção "Adicionar
   estoque disponível (sem OP)", visível só para TRANSFERENCIA/VENDA_DIRETA, reaproveitando o
   mesmo padrão de formulário (`acao=reservar`, checkbox `caixa_ids`, campo
   `quantidade_pacotes_<id>`) já usado na tabela de itens NÃO CONFORME — sem JavaScript novo.
   Coluna "Origem" mostra "Retrabalho" (com o texto de `observacoes` no `title`) ou "Sem OP".
   Tabela "Itens do romaneio": coluna OP agora mostra "OP {id}" quando houver, "Retrabalho"
   quando a origem da caixa for RT, e mantém "Não identificada" apenas como fallback genérico.
4. [templates/romaneio_impressao.html](templates/romaneio_impressao.html) — mesma lógica de
   rótulo aplicada às tabelas de Galinha Inteira e Galinha Cortada da pré-visualização/impressão
   oficial.

Nenhuma alteração em: `reservar_itens`, `remover_item_reservado`, `concluir/cancelar/estornar_romaneio`,
`atualizar_reserva_quantitativa`, `buscar_caixas_elegiveis_op`, `buscar_saldos_quantitativos_op`,
`buscar_modalidades_controle_op`, módulo `retrabalho`, `pa_caixa_composicao`.

## 4. Testes

Novo arquivo [tests/test_romaneio_estoque_sem_op.py](tests/test_romaneio_estoque_sem_op.py) — 15
testes, fixtures reproduzindo exatamente a forma da posição real `RT-PA-000001-01` (PACOTE, sem
linha em `pa_caixa_composicao`, `origem='Retrabalho'`):

- painel aparece só para TRANSFERENCIA/VENDA_DIRETA e nunca em DESCARTE;
- posição `PENDENTE_OP` (ainda não liberada pela Qualidade) não aparece no painel;
- reserva parcial de pacotes sem OP (40 de 99) preserva `DISPONIVEL` e concilia pacote×ave;
- reserva total flipa para `RESERVADO` e some do painel;
- segunda tentativa de reserva além do saldo falha com o mesmo erro de negócio já existente;
- reserva duplicada no mesmo romaneio é bloqueada (mensagem já existente);
- remoção de item de RT restaura saldo e disponibilidade;
- família CAIXA/peso (ex.: Inteira → Cortada) sem OP também é reservável;
- romaneio misto (1 item de OP real + 1 item de RT) conclui corretamente, baixando os dois;
- romaneio somente-RT completa o ciclo de vida;
- cancelamento com item de RT restaura saldo/disponibilidade;
- impressão mostra "Retrabalho" como origem;
- regressão: `atualizar_reserva_quantitativa` continua rejeitando posição sem composição;
- regressão: "Carregar OP" continua isolado (não lista nem é afetado pelo item de RT).

Suíte dirigida pelo hotfix (cada arquivo executado isoladamente, conforme convenção do projeto
para `DB_NAME` por processo): `test_romaneio_estoque_sem_op.py` (15/15),
`test_romaneio_selecao_multiplas_ops.py` (43/43), `test_expedicao_romaneios_seguranca.py`
(26/26), `test_expedicao_marco_zero.py` (17/17), `test_retrabalho.py` (9/9),
`test_retrabalho_etapa_c.py` (19/19), `test_p1_2_integridade_expedicao.py` (5/5 — inclui o teste
de conteúdo de template que exigia manter o literal `"Não identificada"` no arquivo).

Suíte completa (55 arquivos, cada um isolado): 2 falhas, **ambas pré-existentes e confirmadas
independentes deste hotfix** (reproduzidas de forma idêntica com o diff revertido via
`git stash`):
- `test_expedicao_corretiva.py::test_07_mz_audita_acoes_e_gi_nao_exige_peso` —
  `table expedicoes has no column named cliente_parceiro_id` (falta de migração de
  `cliente_parceiro_id` no schema de teste; já documentada como pré-existente na Etapa D deste
  mesmo dia, oriunda do trabalho de parceiros de outra sessão).
- `test_pa_nao_conforme_op.py::test_encerramento_op_registro_e_bloqueio_ocorrem_na_mesma_transacao`
  e `::test_falha_durante_pa_nc_desfaz_tambem_o_encerramento_da_op` — mensagem de erro de
  `encerramento_op.py` mudou de texto (não relacionada a romaneio/RT).

Nenhuma das duas falhas toca código deste hotfix.

## 5. Estado do repositório / decisão de deploy

- Branch de trabalho `codex/melhoria-romaneio-multiplas-ops` está exatamente na ponta de
  `origin/main` (0 ahead/0 behind) no momento da auditoria — sem divergência a resolver.
- Alteração isolada a 4 arquivos de código + 1 arquivo de teste; nenhuma migração de banco é
  necessária (nenhuma tabela/coluna nova — apenas 2 colunas adicionais numa consulta já existente
  e lógica de template).
- **Aguardando autorização explícita para commit final na main, push e deploy no Render**, e
  para a homologação real contra a posição `RT-PA-000001-01` (id 1993) em produção, conforme
  protocolo desta sessão (nenhuma ação de escrita/push/deploy é executada sem confirmação prévia
  por etapa).
