"""Comandos administrativos explícitos para correções financeiras legadas."""

import json

import click

from modules.movimentacoes.services import (
    corrigir_natureza_aportes_fluxo_caixa,
    sincronizar_movimentacoes_plano_contas,
)


def register_movimentacoes_commands(app):
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
