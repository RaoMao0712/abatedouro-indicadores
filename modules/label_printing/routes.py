"""Endpoints mínimos do conector local P3.2."""

from flask import jsonify, request, session

from modules.auth.decorators import perfil_permitido

from .services import (
    autenticar_agente, configurar_impressao_agente, criar_codigo_pareamento, obter_proximo_job,
    parear_agente, registrar_heartbeat, registrar_resultado,
)


def _bearer():
    cabecalho = request.headers.get("Authorization", "")
    return cabecalho[7:].strip() if cabecalho.startswith("Bearer ") else ""


def register_label_printing_routes(app):
    @app.post("/api/local-print-agents/pair")
    def label_agent_pair():
        dados = request.get_json(silent=True) or {}
        try:
            token = parear_agente(str(dados.get("agent_uuid") or ""), str(dados.get("code") or ""),
                                  agent_version=dados.get("agent_version"))
            return jsonify({"token": token, "token_storage": "DPAPI_OR_CREDENTIAL_MANAGER"})
        except ValueError as erro:
            return jsonify({"error": str(erro)}), 400

    @app.post("/api/local-print-agents/pairing-code")
    @perfil_permitido("gerencia")
    def label_agent_pairing_code():
        dados = request.get_json(silent=True) or request.form
        try:
            codigo = criar_codigo_pareamento(str(dados.get("agent_uuid") or ""),
                str(dados.get("name") or "Estação de impressão"), str(dados.get("station_code") or ""))
            return jsonify({"pairing_code": codigo, "expires_in_seconds": 600})
        except ValueError as erro:
            return jsonify({"error": str(erro)}), 400

    @app.post("/api/local-print-agents/heartbeat")
    def label_agent_heartbeat():
        agente = autenticar_agente(_bearer())
        if not agente:
            return jsonify({"error": "Agente não autorizado."}), 401
        dados = request.get_json(silent=True) or {}
        registrar_heartbeat(agente["id"], {chave: dados.get(chave) for chave in ("agent_version", "printer_available", "adapter_available")})
        return jsonify({"ok": True, "agent_id": agente["id"]})

    @app.post("/api/local-print-agents/<agent_uuid>/auto-print")
    @perfil_permitido("gerencia")
    def label_agent_auto_print(agent_uuid):
        dados = request.get_json(silent=True) or request.form
        try:
            configurar_impressao_agente(agent_uuid, str(dados.get("enabled", "")).lower() in {"1","true","on","sim"},
                                         usuario=session.get("nome") or "Administrador")
            return jsonify({"ok": True})
        except ValueError as erro:
            return jsonify({"error": str(erro)}), 400

    @app.post("/api/label-print-jobs/lease")
    def label_job_lease():
        agente = autenticar_agente(_bearer())
        if not agente:
            return jsonify({"error": "Agente não autorizado."}), 401
        dados = request.get_json(silent=True) or {}
        try:
            job = obter_proximo_job(agente["id"], printer_name=str(dados.get("printer_name") or ""),
                                    printer_model=str(dados.get("printer_model") or ""))
            return jsonify({"job": job})
        except ValueError as erro:
            return jsonify({"error": str(erro)}), 409

    @app.post("/api/label-print-jobs/<job_uuid>/result")
    def label_job_result(job_uuid):
        agente = autenticar_agente(_bearer())
        if not agente:
            return jsonify({"error": "Agente não autorizado."}), 401
        dados = request.get_json(silent=True) or {}
        try:
            estado = registrar_resultado(job_uuid, dados.get("lease_token"), outcome=dados.get("outcome"),
                spool_reference=dados.get("spool_reference"), error_code=dados.get("error_code"),
                error_message=dados.get("error_message"))
            return jsonify({"state": estado})
        except ValueError as erro:
            return jsonify({"error": str(erro)}), 409
