"""Adaptadores do agente local; nenhum deles altera a configuração da impressora."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
from pathlib import Path


def installed_printer_names():
    try:
        import win32print  # fornecido pela estação Windows, não redistribuído
        return {item[2] for item in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)}
    except Exception:
        return set()


@dataclass(frozen=True)
class PrintResult:
    outcome: str
    spool_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class LabelPrintAdapter(ABC):
    @abstractmethod
    def capability(self) -> dict: ...

    @abstractmethod
    def send(self, job: dict, printer_name: str) -> PrintResult: ...

    @staticmethod
    def verify_template(job: dict) -> Path:
        caminho = Path(job["template_path"]).resolve(strict=True)
        atual = hashlib.sha256(caminho.read_bytes()).hexdigest().lower()
        esperado = str(job["template_sha256"]).lower()
        if atual != esperado:
            raise RuntimeError("MODEL_HASH_MISMATCH")
        return caminho


class NiceLabelAutomationAdapter(LabelPrintAdapter):
    """Contrato fail-closed para NiceLabel Automation.

    A API concreta depende da edição/licença instalada e só deve ser habilitada
    depois da auditoria local do componente Automation. Não usa ZPL bruto.
    """
    def capability(self) -> dict:
        return {"available": False, "reason": "NICELABEL_AUTOMATION_NOT_AUDITED",
                "printers_read_only": sorted(installed_printer_names())}

    def send(self, job: dict, printer_name: str) -> PrintResult:
        self.verify_template(job)
        if printer_name not in installed_printer_names():
            return PrintResult("PERMANENT_FAILURE", error_code="AUTHORIZED_PRINTER_NOT_FOUND",
                               error_message="A impressora exata autorizada não foi encontrada; não há fallback.")
        return PrintResult("PERMANENT_FAILURE", error_code="NICELABEL_AUTOMATION_NOT_AUDITED",
                           error_message="NiceLabel Automation precisa ser auditado e configurado nesta estação.")


class SimulatedAdapter(LabelPrintAdapter):
    def capability(self) -> dict:
        return {"available": True, "simulated": True}

    def send(self, job: dict, printer_name: str) -> PrintResult:
        self.verify_template(job)
        return PrintResult("SPOOL_ACCEPTED", spool_reference=f"SIM-{job['job_uuid'][:8]}")
