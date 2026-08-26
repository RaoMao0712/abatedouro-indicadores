"""Agente Windows leve. Executa sob o usuário, sem serviço e sem privilégio admin."""

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen

from adapters import NiceLabelAutomationAdapter, SimulatedAdapter
from credentials import protect, unprotect


BASE = Path(os.getenv("LOCALAPPDATA", ".")) / "FrigoDatta" / "PrintAgent"
CONFIG = BASE / "config.json"
TOKEN = BASE / "token.dpapi"


def _logger():
    BASE.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("frigodatta-print-agent")
    if not logger.handlers:
        handler = RotatingFileHandler(BASE / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s")); logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def _request(url, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    req = Request(url, json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(req, timeout=20) as resposta:
        return json.loads(resposta.read().decode())


def pair(args):
    resposta = _request(args.server.rstrip("/") + "/api/local-print-agents/pair",
        {"agent_uuid": args.agent_uuid, "code": args.code, "agent_version": "1.0"})
    protect(resposta["token"], TOKEN)
    BASE.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"server": args.server, "agent_uuid": args.agent_uuid,
        "printer_name": args.printer_name, "printer_model": args.printer_model,
        "adapter": args.adapter}, indent=2), encoding="utf-8")


def diagnostic():
    config = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    adaptador = SimulatedAdapter() if config.get("adapter") == "simulated" else NiceLabelAutomationAdapter()
    print(json.dumps({"config_present": CONFIG.exists(), "token_protected_present": TOKEN.exists(),
        "printer_name": config.get("printer_name"), "printer_model": config.get("printer_model"),
        "adapter": adaptador.capability()}, indent=2))


def run_once():
    config = json.loads(CONFIG.read_text(encoding="utf-8")); token = unprotect(TOKEN)
    adaptador = SimulatedAdapter() if config.get("adapter") == "simulated" else NiceLabelAutomationAdapter()
    resposta = _request(config["server"].rstrip("/") + "/api/label-print-jobs/lease",
        {"printer_name": config["printer_name"], "printer_model": config["printer_model"]}, token)
    job = resposta.get("job")
    if not job: return
    try:
        resultado = adaptador.send(job, config["printer_name"])
    except Exception as erro:
        resultado = type("R", (), {"outcome": "PERMANENT_FAILURE", "spool_reference": None,
            "error_code": str(erro), "error_message": str(erro)})()
    _request(config["server"].rstrip("/") + f"/api/label-print-jobs/{job['job_uuid']}/result",
        {"lease_token": job["lease_token"], "outcome": resultado.outcome,
         "spool_reference": resultado.spool_reference, "error_code": resultado.error_code,
         "error_message": resultado.error_message}, token)
    _logger().info("job=%s outcome=%s", job["job_uuid"], resultado.outcome)


def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pair"); p.add_argument("--server", required=True); p.add_argument("--agent-uuid", required=True)
    p.add_argument("--code", required=True); p.add_argument("--printer-name", required=True); p.add_argument("--printer-model", required=True)
    p.add_argument("--adapter", choices=("nicelabel", "simulated"), default="nicelabel")
    sub.add_parser("diagnostic"); sub.add_parser("once"); run = sub.add_parser("run"); run.add_argument("--interval", type=int, default=5)
    args = parser.parse_args()
    if args.command == "pair": pair(args)
    elif args.command == "diagnostic": diagnostic()
    elif args.command == "once": run_once()
    else:
        while True:
            try:
                run_once()
            except Exception as erro:
                _logger().warning("ciclo indisponivel: %s", type(erro).__name__)
            time.sleep(max(2, args.interval))


if __name__ == "__main__": main()
