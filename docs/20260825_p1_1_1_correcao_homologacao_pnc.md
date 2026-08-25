# P1.1.1 — correção da homologação de Produtos Não Conformes

## Diagnóstico anterior à correção

Produção consultada em modo somente leitura no commit
`9117d5ef433fbd4bd544892c7a0e40171d51caa4`.

O único candidato encontrado foi
`PNC-LEG-2026_07_30_AGUARDANDO_LIBERACAO` (ID 3):

- estado documental: `BLOQUEADO`;
- saldo inicial: 595.500 g;
- saldo bloqueado e pendente: 0 g;
- saldo operacional: 41.460 g;
- saldo destinado: 554.040 g;
- caixas/bandejas bloqueadas: 0/0;
- solicitação aprovada: ID 2, 595.500 g, 48 caixas e 570 bandejas;
- aprovação: 04/08/2026 21:17:08;
- evento de aprovação: ID 8, com fotografia 595.500 g bloqueados antes e
  595.500 g operacionais depois;
- movimento operacional posterior: romaneio 4 estornado e romaneio 26
  concluído com 554.040 g, 46 caixas e 552 bandejas.

A busca por solicitação aprovada, saldo bloqueado zerado, evento de aprovação
existente e estado diferente de `LIBERADO` retornou somente esse registro.
Nenhum outro PNC foi autorizado ou alcançado pela correção.

Não foram encontrados valores com entidades HTML nas colunas textuais de
`pa_nao_conformes` verificadas. A falha visual era causada por entidades
escritas dentro de expressões Jinja; o autoescape transformava `&` em texto
literal. O importador oficial já persiste Unicode normal.

## Causa raiz

A aprovação integral ocorreu em 04/08/2026, quando o fluxo legado transferia o
saldo para o estoque operacional, mas preservava o estado `BLOQUEADO` e também
registrava esse mesmo estado no evento. O commit P1.1 de 25/08/2026 já corrigiu
o fluxo atual para persistir `LIBERADO` na mesma transação de uma aprovação
integral. O defeito remanescente era exclusivamente documental no registro
histórico anterior a essa regra.

## Correção

O comando versionado `flask reconciliar-pnc-p1-1-1` é simulação por padrão.
`--confirmar` aplica somente ao número autorizado e exige, sob bloqueio
transacional:

- estado `BLOQUEADO`;
- uma única solicitação aprovada e integral;
- saldos bloqueado e pendente zerados;
- controles auxiliares bloqueados zerados;
- posição operacional/reservada/destinada reconciliada com o saldo inicial;
- evento de aprovação vinculado à solicitação, com fotografias antes/depois;
- inexistência de descarte, reprocessamento ou destinação incompatível;
- inexistência de transição ou reconciliação anterior para `LIBERADO`.

O comando altera apenas os campos documentais, cria o evento permanente
`RECONCILIACAO_ESTADO_LEGADO_P1_1_1` e não escreve em nenhum campo de estoque,
solicitação, romaneio ou movimento. Uma segunda execução é inócua. O comando
`flask reverter-reconciliacao-pnc-p1-1-1 --confirmar` restaura somente a
fotografia documental anterior se nenhum evento ou saldo tiver mudado e grava
um novo evento de rollback; eventos anteriores nunca são apagados.

Os templates PNC agora usam Unicode normal dentro de expressões. O autoescape
permanece habilitado, não há `|safe` nem `html.unescape`, e conteúdo proveniente
do banco continua tratado como texto. O CSV usa os mesmos rótulos Unicode para
OP e lote ausentes.

## Testes antes do deploy

- testes específicos e inventário/liberação: 21 aprovados;
- 110 testes direcionados anteriores de PNC + 6 novos: 116 aprovados;
- regressões P0, P0.2, pedidos e romaneios: 132 aprovados;
- suítes legadas com bancos temporários fixos, executadas isoladamente:
  15 + 17 + 26 (e 9 subtestes) + 12 aprovados.

A execução monolítica confirmou 539 testes aprovados, mas evidenciou uma
limitação preexistente de isolamento entre três módulos legados que compartilham
o `DB_NAME` no mesmo processo. Um benchmark financeiro, fora do escopo, gerou
corretamente as 5.000 linhas, porém excedeu o limite local de 45 s tanto na
branch P1.1.1 (53,3 s) quanto na `main` publicada (58,9 s). Nenhum teste foi
reduzido, ignorado ou marcado como `xfail`, e nenhum módulo financeiro foi
alterado.
