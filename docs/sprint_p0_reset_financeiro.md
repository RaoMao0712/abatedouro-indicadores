# Sprint P0 — reset controlado do Financeiro

Este procedimento remove somente entidades financeiras comprovadas pelo schema.
Ele preserva vendas operacionais, custos/CMV, cadastros, estoque, produção,
pedidos, romaneios, expedições, PNC, plano de contas, configuração de corte e a
auditoria histórica das movimentações.

## Proteções incorporadas

- O dry-run é estritamente de leitura e gera inventário por tabela/classe,
  totais financeiros, dependências, ordem de exclusão e checksums operacionais.
- Tabela financeira desconhecida ou FK operacional obrigatória torna o relatório
  não executável.
- A execução exige o token literal `RESET_TOTAL_FINANCEIRO_FRIGODATTA`, o relatório de
  dry-run íntegro, motivo, executor e diretório de backup.
- O backup é integral: cópia online com `integrity_check` no SQLite ou dump
  customizado validado por `pg_restore --list` no PostgreSQL.
- O estado é comparado antes do backup e novamente sob bloqueio transacional.
- Vínculos financeiros opcionais em documentos operacionais são anulados sem
  excluir o documento.
- Qualquer erro, divergência de checksum ou FK inválida causa rollback integral.
- A auditoria global das movimentações é preservada. Um único evento de reset
  registra commit, ambiente, motivo, backup, hash do dry-run e inventários.
- Somente o commit bem-sucedido da transação de reset ativa o estado persistente
  `FINANCEIRO_EM_RECONSTRUCAO`, derivado do evento imutável de auditoria. Dry-run,
  rollback e banco sintético local não o ativam; uma segunda execução já zerada
  mantém o estado sem criar outra fonte de verdade.
- Enquanto esse estado estiver ativo, todas as escritas financeiras antigas ficam
  bloqueadas no servidor: importações de despesas e vendas, criação manual,
  edição, realização/baixa, cancelamento, reabertura, reclassificação em lote e
  comandos administrativos históricos. Consultas e exportações permanecem
  disponíveis e as telas financeiras exibem aviso de reconstrução.
- Esta sprint não cria, habilita nem permite desativar manualmente a proteção para
  antecipar a carga Sankhya.

## Dry-run local/homologação

```powershell
python -m flask --app app reset-financeiro --dry-run `
  --report output/reset-financeiro/dry-run.json
```

Prossiga somente se `executable` for `true`, `blockers` estiver vazio, todas as
tabelas esperadas estiverem inventariadas e os módulos preservados estiverem
cobertos pelos checksums.

## Execução real

```powershell
python -m flask --app app reset-financeiro `
  --confirm RESET_TOTAL_FINANCEIRO_FRIGODATTA `
  --dry-run-report output/reset-financeiro/dry-run.json `
  --backup-dir backups/reset-financeiro `
  --motivo "Substituir carga financeira incompleta antes da integração Sankhya" `
  --executor "Responsável autorizado" `
  --report output/reset-financeiro/execucao.json
```

Em PostgreSQL, `pg_dump` e `pg_restore` precisam estar instalados e compatíveis
com o servidor. A ausência de qualquer ferramenta interrompe a execução antes da
primeira alteração.

## Durabilidade obrigatória do backup produtivo

O arquivo criado no filesystem da aplicação é apenas a cópia técnica imediata;
em Render ou infraestrutura efêmera ele **não é evidência suficiente** de
recuperação. Antes de autorizar o reset produtivo, o responsável deve comprovar
ao menos uma proteção externa e durável: backup lógico transferido para storage
persistente fora da instância, snapshot/backup gerenciado do PostgreSQL ou
capacidade de restauração point-in-time (PITR) validada para o banco de produção.

A evidência operacional deve registrar identificador externo do backup ou ponto
de restauração, destino durável, horário, tamanho em bytes, SHA-256 quando houver
artefato exportável e responsável pela validação. O hash, o tamanho e o
identificador precisam ser anexados ao chamado/runbook junto do dry-run aprovado.

Se a cópia ainda estiver somente no disco efêmero da aplicação, se a transferência
externa não puder ser comprovada ou se o procedimento de restauração/PITR não
estiver validado, a execução produtiva deve parar antes do comando real. Esta
etapa não implementa integração automática com S3 ou outro storage.

## Validação e condição de parada

O relatório final deve registrar zero linhas em todas as tabelas-alvo, zero
órfãos, checksums operacionais idênticos e o evento de auditoria. Execute smoke
tests nas telas Central de Movimentações, Fluxo de Caixa e DRE. Não prossiga se
qualquer tela retornar erro, se o backup não puder ser listado/restaurado, se os
checksums divergirem ou se o dry-run precisar ser regenerado.
