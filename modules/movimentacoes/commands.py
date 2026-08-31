"""Comandos administrativos explícitos para correções financeiras legadas."""

import json

import click

from modules.movimentacoes.services import (
    corrigir_natureza_aportes_fluxo_caixa,
    sincronizar_movimentacoes_plano_contas,
)
from modules.movimentacoes.reset_financeiro import (
    CONFIRMATION_TOKEN,
    ResetSafetyError,
    build_dry_run,
    execute_reset,
    write_report,
)


def register_movimentacoes_commands(app):
    @app.cli.command("reset-financeiro")
    @click.option("--dry-run", is_flag=True, help="Gera inventario e plano sem alterar dados.")
    @click.option("--report", type=click.Path(dir_okay=False), help="Arquivo JSON do relatorio.")
    @click.option("--confirm", help=f"Token da execucao real: {CONFIRMATION_TOKEN}.")
    @click.option("--dry-run-report", type=click.Path(exists=True, dir_okay=False), help="Dry-run aprovado.")
    @click.option("--backup-dir", type=click.Path(file_okay=False), help="Diretorio do backup restauravel.")
    @click.option("--motivo", help="Motivo auditavel da limpeza.")
    @click.option("--executor", default="CLI administrativo", show_default=True)
    def reset_financeiro(dry_run, report, confirm, dry_run_report, backup_dir, motivo, executor):
        """Inventaria ou executa o reset P0 controlado do Financeiro."""
        try:
            if dry_run:
                if confirm or dry_run_report or backup_dir:
                    raise click.UsageError("Dry-run nao aceita opcoes de execucao real.")
                if not report:
                    raise click.UsageError("Dry-run exige --report para preservar a evidencia.")
                resultado = build_dry_run()
                resultado["report_file"] = write_report(resultado, report)
                click.echo(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
                if not resultado["executable"]:
                    raise click.ClickException("Dry-run bloqueado por dependencias nao comprovadas.")
                return

            missing = [
                name for name, value in (
                    ("--confirm", confirm), ("--dry-run-report", dry_run_report),
                    ("--backup-dir", backup_dir), ("--motivo", motivo),
                ) if not value
            ]
            if missing:
                raise click.UsageError("Execucao real exige " + ", ".join(missing) + ".")
            resultado = execute_reset(
                confirmation=confirm, dry_run_report=dry_run_report,
                backup_dir=backup_dir, reason=motivo, executor=executor,
            )
            if report:
                resultado["report_file"] = write_report(resultado, report)
            click.echo(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
        except ResetSafetyError as error:
            raise click.ClickException(str(error)) from error

    @app.cli.command("sincronizar-plano-movimentacoes")
    @click.option("--confirmar", is_flag=True, help="Confirma a alteração histórica.")
    @click.option("--justificativa", required=True, help="Motivo auditável da execução.")
    def sincronizar_plano_movimentacoes(confirmar, justificativa):
        """Sincroniza classificações legadas por execução administrativa intencional."""
        if not confirmar:
            raise click.UsageError("Use --confirmar para autorizar a sincronização.")
        resultado = sincronizar_movimentacoes_plano_contas(justificativa=justificativa)
        click.echo(json.dumps(resultado or {"executado": True}, ensure_ascii=False))

    @app.cli.command("hotfix-aportes-fluxo")
    @click.option("--confirmar", is_flag=True, help="Confirma a alteração histórica.")
    @click.option("--justificativa", required=True, help="Motivo auditável da execução.")
    def hotfix_aportes_fluxo(confirmar, justificativa):
        """Executa uma única vez o hotfix legado de natureza dos aportes."""
        if not confirmar:
            raise click.UsageError("Use --confirmar para autorizar o hotfix.")
        resultado = corrigir_natureza_aportes_fluxo_caixa(justificativa=justificativa)
        click.echo(json.dumps(resultado, ensure_ascii=False))
