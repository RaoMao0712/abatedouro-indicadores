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
- A execução exige o token literal `RESET_FINANCEIRO_FRIGODATTA`, o relatório de
  dry-run íntegro, motivo, executor e diretório de backup.
- O backup é integral: cópia online com `integrity_check` no SQLite ou dump
  customizado validado por `pg_restore --list` no PostgreSQL.
- O estado é comparado antes do backup e novamente sob bloqueio transacional.
- Vínculos financeiros opcionais em documentos operacionais são anulados sem
  excluir o documento.
- Qualquer erro, divergência de checksum ou FK inválida causa rollback integral.
- A auditoria global das movimentações é preservada. Um único evento de reset
  registra commit, ambiente, motivo, backup, hash do dry-run e inventários.
- A antiga importação financeira fica bloqueada após o reset. Esta sprint não
  cria nem habilita a carga Sankhya.

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
  --confirm RESET_FINANCEIRO_FRIGODATTA `
  --dry-run-report output/reset-financeiro/dry-run.json `
  --backup-dir backups/reset-financeiro `
  --motivo "Substituir carga financeira incompleta antes da integração Sankhya" `
  --executor "Responsável autorizado" `
  --report output/reset-financeiro/execucao.json
```

Em PostgreSQL, `pg_dump` e `pg_restore` precisam estar instalados e compatíveis
com o servidor. A ausência de qualquer ferramenta interrompe a execução antes da
primeira alteração.

## Validação e condição de parada

O relatório final deve registrar zero linhas em todas as tabelas-alvo, zero
órfãos, checksums operacionais idênticos e o evento de auditoria. Execute smoke
tests nas telas Central de Movimentações, Fluxo de Caixa e DRE. Não prossiga se
qualquer tela retornar erro, se o backup não puder ser listado/restaurado, se os
checksums divergirem ou se o dry-run precisar ser regenerado.
