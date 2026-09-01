"""Comandos administrativos, somente leitura, de integridade de Produção."""

import click

from .integridade_encerramento import auditar_integridade_encerramento, serializar_auditoria


def register_producao_commands(app):
    @app.cli.command("auditar-encerramento-ops")
    @click.option("--op", "op_id", type=int, help="Restringe a auditoria a uma OP.")
    @click.option("--data-corte", type=click.DateTime(formats=["%Y-%m-%d"]),
                  help="Analisa OPs desde a data informada (AAAA-MM-DD).")
    @click.option("--json-output", is_flag=True, default=True,
                  help="Emite o relatório estruturado em JSON.")
    def auditar_encerramento_ops(op_id, data_corte, json_output):
        """Detecta estados incoerentes sem executar qualquer UPDATE ou correção."""
        corte = data_corte.strftime("%Y-%m-%d") if data_corte else None
        resultado = auditar_integridade_encerramento(op_id=op_id, data_corte=corte)
        if json_output:
            click.echo(serializar_auditoria(resultado))
        if resultado["criticos"]:
            raise click.exceptions.Exit(2)
