"""Telemetria leve por requisição para diagnóstico de performance."""

import json
import re
import time
import uuid

from flask import g, request

from database import finalizar_metricas_sql, iniciar_metricas_sql


_REQUEST_ID_SEGURO = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


def _correlation_id():
    recebido = str(request.headers.get("X-Request-ID") or "").strip()
    return recebido if _REQUEST_ID_SEGURO.fullmatch(recebido) else str(uuid.uuid4())


def registrar_observabilidade_performance(app):
    @app.before_request
    def _iniciar_medicao_performance():
        g.performance_inicio = time.perf_counter()
        g.performance_correlation_id = _correlation_id()
        iniciar_metricas_sql()

    @app.after_request
    def _finalizar_medicao_performance(response):
        duracao_ms = (time.perf_counter() - g.performance_inicio) * 1000
        metricas = finalizar_metricas_sql()
        sql_ms = float(metricas.get("sql_ms") or 0)
        registro = {
            "evento": "http_performance",
            "rota": request.url_rule.rule if request.url_rule else request.path,
            "metodo": request.method,
            "status": response.status_code,
            "duracao_ms": round(duracao_ms, 1),
            "sql_count": int(metricas.get("sql_count") or 0),
            "sql_ms": round(sql_ms, 1),
            "slowest_sql_ms": round(float(metricas.get("slowest_sql_ms") or 0), 1),
            "slowest_sql": metricas.get("slowest_sql"),
            "connections": int(metricas.get("connections") or 0),
            "connection_ms": round(float(metricas.get("connection_ms") or 0), 1),
            "correlation_id": g.performance_correlation_id,
        }
        app.logger.info("PERF %s", json.dumps(registro, ensure_ascii=True))
        response.headers["X-Correlation-ID"] = g.performance_correlation_id
        response.headers["X-Performance-SQL-Count"] = str(registro["sql_count"])
        response.headers["X-Performance-Connections"] = str(registro["connections"])
        response.headers["Server-Timing"] = (
            f"app;dur={duracao_ms:.1f}, db;dur={sql_ms:.1f}, "
            f"connect;dur={registro['connection_ms']:.1f}"
        )
        return response
