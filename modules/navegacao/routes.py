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
        titulo = "Início"
        subtitulo = "Visão geral e acessos autorizados do FrigoDatta."
        if request.endpoint == "inicio":
            primeiro_nome = (session.get("nome") or "Usuário").strip().split()[0]
            subtitulo = f"Olá, {primeiro_nome}. Escolha uma área para começar."
        else:
            for dominio in navegacao:
                item_ativo = next(
                    (item for item in dominio.get("itens", []) if item.get("ativo")),
                    None,
                )
                if item_ativo:
                    titulo = item_ativo["titulo"]
                    subtitulo = dominio.get("descricao", subtitulo)
                    break
                if dominio.get("ativo") and dominio.get("endpoint"):
                    titulo = dominio["titulo"]
                    subtitulo = dominio.get("descricao", subtitulo)
                    break
        dominio_ativo = next(
            (dominio for dominio in navegacao if dominio.get("ativo") and dominio.get("itens")),
            None,
        )
        return {
            "perfil_nome": nome_perfil(session.get("perfil", "")),
            "hero_titulo": titulo,
            "hero_subtitulo": subtitulo,
            "dominio_ativo": dominio_ativo,
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
