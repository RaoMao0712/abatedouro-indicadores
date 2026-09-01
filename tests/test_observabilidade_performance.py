import json
import logging

from flask import Flask

from modules.observabilidade import registrar_observabilidade_performance


def test_telemetria_expoe_metricas_sem_parametros_sensiveis(caplog):
    app = Flask(__name__)
    registrar_observabilidade_performance(app)

    @app.get("/teste/<int:item_id>")
    def rota_teste(item_id):
        return {"ok": bool(item_id)}

    with caplog.at_level(logging.INFO):
        resposta = app.test_client().get(
            "/teste/83?senha=nao-deve-aparecer",
            headers={"X-Request-ID": "REQ-PERF-83"},
        )

    assert resposta.status_code == 200
    assert resposta.headers["X-Correlation-ID"] == "REQ-PERF-83"
    assert resposta.headers["X-Performance-SQL-Count"] == "0"
    assert "app;dur=" in resposta.headers["Server-Timing"]
    linha = next(item.message for item in caplog.records if item.message.startswith("PERF "))
    registro = json.loads(linha.removeprefix("PERF "))
    assert registro["rota"] == "/teste/<int:item_id>"
    assert registro["correlation_id"] == "REQ-PERF-83"
    assert "senha" not in linha and "nao-deve-aparecer" not in linha
