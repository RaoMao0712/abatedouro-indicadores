"""Rota e contexto global da nova navegação."""

from urllib.parse import urlsplit

from flask import render_template, request, session, url_for

from modules.auth.decorators import login_obrigatorio

from .services import acessos_principais, cards_das_areas, montar_navegacao, nome_perfil


_BACK_URLS_SESSION_KEY = "fd_back_urls"
_BACK_REDIRECT_SESSION_KEY = "fd_redirect_back"
_BLOCKED_BACK_PATHS = {"/", "/inicio", "/sair"}


def _internal_path(value):
    """Retorna path + query somente para destinos HTTP internos seguros."""
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        return None
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc and parsed.netloc != request.host:
        return None
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None
    if parsed.path in _BLOCKED_BACK_PATHS:
        return None
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _contextual_back_url():
    fallback = url_for("inicio")
    if request.endpoint == "inicio":
        return fallback

    current_path = request.path
    stored = dict(session.get(_BACK_URLS_SESSION_KEY, {}))
    redirects = dict(session.get(_BACK_REDIRECT_SESSION_KEY, {}))
    explicit = _internal_path(request.args.get("return_to"))
    referrer = _internal_path(request.referrer)
    redirected_from = redirects.pop(current_path, None)
    if redirected_from:
        session[_BACK_REDIRECT_SESSION_KEY] = redirects

    if explicit:
        back_url = explicit
    elif redirected_from:
        back_url = redirected_from
    elif referrer and urlsplit(referrer).path != current_path:
        back_url = referrer
    elif referrer and urlsplit(referrer).path == current_path:
        back_url = stored.get(current_path, fallback)
    else:
        back_url = fallback

    if back_url != fallback:
        stored[current_path] = back_url
        # Limita o cookie de sessão sem perder os retornos mais recentes.
        session[_BACK_URLS_SESSION_KEY] = dict(list(stored.items())[-20:])
    return back_url


def register_navegacao_routes(app):
    @app.after_request
    def preservar_retorno_apos_redirect(response):
        if session.get("usuario_id") and request.method == "POST" and 300 <= response.status_code < 400:
            stored = dict(session.get(_BACK_URLS_SESSION_KEY, {}))
            origem = stored.get(request.path)
            destino = _internal_path(response.headers.get("Location"))
            if origem and destino:
                stored[urlsplit(destino).path] = origem
                session[_BACK_URLS_SESSION_KEY] = dict(list(stored.items())[-20:])
                redirects = dict(session.get(_BACK_REDIRECT_SESSION_KEY, {}))
                redirects[urlsplit(destino).path] = origem
                session[_BACK_REDIRECT_SESSION_KEY] = dict(list(redirects.items())[-20:])
        return response

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
            "fd_back_url": _contextual_back_url(),
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
