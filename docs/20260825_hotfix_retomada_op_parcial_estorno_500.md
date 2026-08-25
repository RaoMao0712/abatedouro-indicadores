# Hotfix — retomada de OP parcial e estorno integral

Data da execução: 25/08/2026 (America/Manaus)

## Identificação

- Commit inicial (`origin/main`): `08986964c385d34f89c46885f033f86f4c387fe9`.
- Branch: `codex/hotfix-retomada-op-parcial-estorno-500`.
- Hotfixes-base confirmados no histórico: P0 `b9abc8b` e P0.2 `a675c4f`.
- Migração: nenhuma.

## Diagnóstico do HTTP 500

Evento localizado nos logs autenticados do Render:

- horário: 25/08/2026 22:13:16 UTC (18:13:16 em America/Manaus);
- método e rota: `POST /embalagem-secundaria/83/estornar`;
- função da rota: `estornar_embalagem_secundaria_op`;
- usuário da sessão autenticada: administrador identificado na interface (credenciais não registradas);
- exceção: `psycopg2.errors.FeatureNotSupported: FOR UPDATE is not allowed with DISTINCT clause`;
- origem: `modules/expedicao/routes.py`, linha 271, chamando `modules/producao/operacoes_op.py`, linhas 291 e 129;
- etapa transacional: leitura bloqueante das caixas no preflight do estorno integral, antes de qualquer mutação.

A causa raiz era a combinação `SELECT DISTINCT cx.* ... FOR UPDATE`, não aceita pelo PostgreSQL. A consulta passou a selecionar `pa_caixas` com `WHERE EXISTS`, mantendo uma única linha por caixa e permitindo o bloqueio pessimista dos registros que serão revalidados ou revertidos.

## Correção funcional

- Retomada explícita para OP em `Aguardando Embalagem Secundária`, com caixas ativas e saldo PI pendente.
- Transição atômica para `Aberta`, sem novo estado ou migration.
- Preservação de PI, PA, caixas ativas, caixas estornadas, lote, fabricação e histórico.
- Invalidação da conferência vigente; uma nova conferência é obrigatória após inclusão ou estorno.
- Bloqueio e revalidação transacional do estado e do saldo antes de novas caixas.
- Fabricação fixada na data original da OP; a data posterior da retomada não substitui a data do lote.
- Idempotência e auditoria da retomada.
- Erros operacionais esperados do estorno integral e da retomada retornam HTTP 4xx com mensagem amigável, sem mutação parcial.
- Preflight autenticado e somente leitura disponível para o estorno integral.

## Arquivos alterados

- `modules/producao/operacoes_op.py`
- `modules/producao/routes.py`
- `modules/expedicao/services.py`
- `modules/expedicao/routes.py`
- `templates/embalagem_secundaria.html`
- `templates/erro_operacional.html`
- `tests/test_p0_2_estorno_reabertura_op.py`
- `tests/test_expedicao_corretiva.py`

## Testes

- `tests/test_p0_2_estorno_reabertura_op.py`: 57 aprovados.
- `tests/test_estorno_embalagem_secundaria.py`: 39 aprovados.
- `tests/test_expedicao_corretiva.py`: 20 aprovados.
- `compileall`: aprovado.
- `git diff --check`: aprovado.
- suíte completa com `PYTHONPATH=pesagem_app/src`: 559 aprovados, 1 falha e 63 erros preexistentes de isolamento entre módulos de teste SQLite (`test_qual_sgi`/tabelas importadas em banco diferente); nenhum erro nos testes focados do hotfix.

O cenário equivalente à OP 83 cobre produção em D1, caixas em D8, duplicidades estornadas, retomada em D12, inclusão posterior, invalidação e nova conferência e encerramento final, sem perda ou duplicação de PI/PA.

## Snapshot pré-deploy da OP 83

Consulta autenticada e somente leitura em `https://abatedouro-indicadores.onrender.com/embalagem-secundaria?op_id=83`:

- status/estágio: `Aguardando Embalagem Secundária`;
- produção/fabricação: 13/08/2026;
- SKU: Galinha Cortada; aves: 2.000;
- caixas ativas: 52; caixas estornadas: 2;
- bandejas ativas: 624;
- peso bruto: 670,040 kg; tara: 26,000 kg; líquido: 644,040 kg;
- saldo PI e saldo pendente: 1.320 bandejas;
- conferência exibida como vigente antes da retomada; o hotfix a invalida ao retomar e ao incluir nova caixa;
- histórico de dois estornos individuais preservado (24/08/2026 20:29:13 e 20:31:30);
- nenhum estorno integral, inclusão ou alteração de status foi executado no diagnóstico.

## Preservação pré-deploy

- Branch remota de recuperação do código: `backup/pre-hotfix-retomada-op-parcial-estorno-500-20260825`, apontando para o commit inicial.
- Export lógico completo do PostgreSQL criado no Render em 25/08/2026 18:58 (America/Manaus), além da recuperação contínua disponibilizada pelo provedor.

O commit publicado e o snapshot pós-deploy autenticado são registrados no relatório final da execução, após a conclusão do deploy.
