"""Rota e contexto global da nova navegação."""

from flask import render_template, request, session

from modules.auth.decorators import login_obrigatorio

from .services import acessos_principais, cards_das_areas, montar_navegacao, nome_perfil


def register_navegacao_routes(app):
    @app.context_processor
    def contexto_navegacao():
        if not session.get("usuario_id"):
            return {}
        navegacao = montar_navegacao(
            session.get("perfil", ""),
            request.endpoint or "",
            request.view_args or {},
        )
        return {
            "navegacao_sidebar": navegacao,
            "perfil_nome": nome_perfil(session.get("perfil", "")),
        }

    @app.route("/inicio")
    @login_obrigatorio
    def inicio():
        navegacao = montar_navegacao(
            session.get("perfil", ""),
            request.endpoint or "",
            request.view_args or {},
        )
        primeiro_nome = (session.get("nome") or "Usuário").strip().split()[0]
        return render_template(
            "inicio.html",
            primeiro_nome=primeiro_nome,
            perfil_nome=nome_perfil(session.get("perfil", "")),
            areas=cards_das_areas(navegacao),
            acessos=acessos_principais(navegacao),
        )
