"""Consulta e consolidação somente leitura dos romaneios de descarte PNC."""

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

from database import conectar, q


FUSO_MANAUS = ZoneInfo("America/Manaus")
STATUS_DOCUMENTO = ("CONFIRMADO", "RASCUNHO", "CANCELADO", "ESTORNADO")
TIPOS_DATA = {
    "SAIDA_FISICA": ("saida_fisica_em", "Data da saída física"),
    "LANCAMENTO": ("lancado_em", "Data do lançamento no sistema"),
    "EMISSAO": ("criado_em", "Data de emissão do romaneio"),
}
MODALIDADES = {
    "SINTETICO": "Sintético por Romaneio",
    "CARACTERISTICA": "Consolidado por Característica",
}


def _lista(valor):
    if valor is None:
        return []
    if isinstance(valor, (list, tuple, set)):
        valores = valor
    else:
        valores = str(valor).split(",")
    return [str(item).strip() for item in valores if str(item).strip()]


def normalizar_filtros(filtros=None, *, agora=None):
    filtros = dict(filtros or {})
    agora = agora or datetime.now(FUSO_MANAUS)
    tipo_data = str(filtros.get("tipo_data") or "SAIDA_FISICA").upper()
    modalidade = str(filtros.get("modalidade") or "SINTETICO").upper()
    if tipo_data not in TIPOS_DATA:
        tipo_data = "SAIDA_FISICA"
    if modalidade not in MODALIDADES:
        modalidade = "SINTETICO"
    inicio_padrao = agora.date().replace(day=1)
    fim_padrao = agora.date()
    try:
        data_inicio = date.fromisoformat(str(filtros.get("data_inicio") or inicio_padrao))
    except ValueError:
        data_inicio = inicio_padrao
    try:
        data_fim = date.fromisoformat(str(filtros.get("data_fim") or fim_padrao))
    except ValueError:
        data_fim = fim_padrao
    if data_fim < data_inicio:
        data_inicio, data_fim = data_fim, data_inicio
    return {
        "data_inicio": data_inicio.isoformat(),
        "data_fim": data_fim.isoformat(),
        "tipo_data": tipo_data,
        "numero": str(filtros.get("numero") or "").strip(),
        "status": [item.upper() for item in _lista(filtros.get("status"))] or ["CONFIRMADO"],
        "produto": _lista(filtros.get("produto")),
        "apresentacao": str(filtros.get("apresentacao") or "").strip(),
        "motivo": _lista(filtros.get("motivo")),
        "destino": _lista(filtros.get("destino")),
        "motorista": str(filtros.get("motorista") or "").strip(),
        "placa": str(filtros.get("placa") or "").strip(),
        "usuario_emissor": str(filtros.get("usuario_emissor") or "").strip(),
        "modalidade": modalidade,
    }


def _in(campo, valores, condicoes, parametros):
    if not valores:
        return
    condicoes.append(f"{campo} IN ({','.join('?' for _ in valores)})")
    parametros.extend(valores)


def _snapshot(linha):
    try:
        return json.loads(linha["snapshot_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _registro_historico(linha):
    linha = dict(linha)
    snapshot = _snapshot(linha)
    saida = snapshot.get("saida") or {}
    registro = {
        "id": linha["id"],
        "numero": snapshot.get("numero") or linha["numero"],
        "pnc_numero": snapshot.get("pnc_numero") or linha.get("pnc_numero"),
        "status": linha["status"],
        "saida_fisica_em": snapshot.get("saida_fisica_em") or linha["saida_fisica_em"],
        "lancado_em": snapshot.get("lancado_em") or linha["lancado_em"],
        "criado_em": linha["criado_em"],
        "produto": snapshot.get("produto") or linha["produto"],
        "apresentacao": snapshot.get("apresentacao") or linha["apresentacao"],
        "motivo": snapshot.get("motivo") or linha["motivo"],
        "destino": snapshot.get("destino") or linha["destino"],
        "motorista": snapshot.get("motorista") or linha["motorista"],
        "placa": snapshot.get("placa") or linha["placa"],
        "usuario_emissor": snapshot.get("usuario_emissor") or linha["usuario_emissor"],
        "caixas": int(saida.get("caixas", linha["caixas"]) or 0),
        "bandejas": int(saida.get("bandejas", linha["bandejas"]) or 0),
        "galinhas": int(saida.get("galinhas", linha["galinhas"]) or 0),
        "pacotes": int(saida.get("pacotes", linha["pacotes"]) or 0),
        "peso_g": int(saida.get("peso_g", linha["peso_g"]) or 0),
        "justificativa_sem_efeito": linha.get("justificativa_estorno"),
        "snapshot": snapshot,
    }
    registro["efetivo"] = registro["status"] == "CONFIRMADO"
    registro["tipo_unidade"] = _tipo_unidade(registro)
    return registro


def _tipo_unidade(registro):
    descricao = f"{registro.get('produto', '')} {registro.get('apresentacao', '')}".casefold()
    if "inteira" in descricao or (
        (registro.get("galinhas") or registro.get("pacotes"))
        and not (registro.get("caixas") or registro.get("bandejas") or registro.get("peso_g"))
    ):
        return "INTEIRA"
    return "CORTADA"


def consultar_romaneios_descarte(filtros=None, *, conexao=None):
    """Filtra por colunas persistidas e só então desserializa snapshots imutáveis."""
    filtros = normalizar_filtros(filtros)
    coluna_data = TIPOS_DATA[filtros["tipo_data"]][0]
    fim_exclusivo = date.fromisoformat(filtros["data_fim"]) + timedelta(days=1)
    condicoes = [f"r.{coluna_data} >= ?", f"r.{coluna_data} < ?"]
    parametros = [filtros["data_inicio"], fim_exclusivo.isoformat()]
    if filtros["numero"]:
        condicoes.append("LOWER(r.numero) LIKE LOWER(?)")
        parametros.append(f"%{filtros['numero']}%")
    _in("r.status", filtros["status"], condicoes, parametros)
    _in("i.produto", filtros["produto"], condicoes, parametros)
    if filtros["apresentacao"]:
        condicoes.append("LOWER(i.apresentacao) LIKE LOWER(?)")
        parametros.append(f"%{filtros['apresentacao']}%")
    _in("i.motivo", filtros["motivo"], condicoes, parametros)
    _in("r.destino", filtros["destino"], condicoes, parametros)
    for chave, campo in (("motorista", "r.motorista"), ("placa", "r.placa"),
                         ("usuario_emissor", "r.usuario_emissor")):
        if filtros[chave]:
            condicoes.append(f"LOWER({campo}) LIKE LOWER(?)")
            parametros.append(f"%{filtros[chave]}%")
    sql = f"""SELECT r.id,r.numero,r.status,r.saida_fisica_em,r.lancado_em,r.criado_em,
        r.destino,r.motorista,r.placa,r.usuario_emissor,r.justificativa_estorno,r.snapshot_json,
        i.produto,i.apresentacao,i.motivo,i.caixas,i.bandejas,i.galinhas,i.pacotes,i.peso_g,
        nc.numero AS pnc_numero
        FROM pnc_romaneios_descarte r
        JOIN pnc_romaneio_descarte_itens i ON i.romaneio_id=r.id
        JOIN pa_nao_conformes nc ON nc.id=r.pa_nao_conforme_id
        WHERE {' AND '.join(condicoes)}
        ORDER BY r.{coluna_data} DESC,r.id DESC"""
    propria = conexao is None
    conn = conexao or conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q(sql), parametros)
        registros = [_registro_historico(item) for item in cursor.fetchall()]
    finally:
        if propria:
            conn.close()
    return montar_relatorio(registros, filtros)


def montar_relatorio(registros, filtros=None):
    filtros = normalizar_filtros(filtros)
    registros = list(registros)
    efetivos = [item for item in registros if item["efetivo"]]
    excecoes = [item for item in registros if not item["efetivo"]]
    totais = defaultdict(int)
    grupos = {}
    for item in efetivos:
        for campo in ("caixas", "bandejas", "galinhas", "pacotes", "peso_g"):
            totais[campo] += int(item[campo] or 0)
        chave = (item["produto"], item["apresentacao"], item["motivo"])
        grupo = grupos.setdefault(chave, {
            "produto": chave[0], "apresentacao": chave[1], "motivo": chave[2],
            "tipo_unidade": item["tipo_unidade"], "romaneios": 0,
            "caixas": 0, "bandejas": 0, "galinhas": 0, "pacotes": 0, "peso_g": 0,
        })
        grupo["romaneios"] += 1
        for campo in ("caixas", "bandejas", "galinhas", "pacotes", "peso_g"):
            grupo[campo] += int(item[campo] or 0)
    resumo = {
        "romaneios_confirmados": len(efetivos),
        "documentos_sem_efeito": len(excecoes),
        "destinos_distintos": len({item["destino"] for item in efetivos if item["destino"]}),
        "caracteristicas_distintas": len({item["motivo"] for item in efetivos if item["motivo"]}),
        **{campo: totais[campo] for campo in ("caixas", "bandejas", "galinhas", "pacotes", "peso_g")},
    }
    return {
        "filtros": filtros,
        "registros": registros,
        "efetivos": efetivos,
        "excecoes": excecoes,
        "grupos": sorted(grupos.values(), key=lambda x: (x["produto"], x["apresentacao"], x["motivo"])),
        "resumo": resumo,
    }


def opcoes_filtros_relatorio(*, conexao=None):
    propria = conexao is None
    conn = conexao or conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("""SELECT DISTINCT i.produto,i.apresentacao,i.motivo,r.destino
            FROM pnc_romaneios_descarte r
            JOIN pnc_romaneio_descarte_itens i ON i.romaneio_id=r.id
            ORDER BY i.produto,i.apresentacao,i.motivo,r.destino""")
        linhas = [dict(item) for item in cursor.fetchall()]
    finally:
        if propria:
            conn.close()
    return {
        "produtos": sorted({item["produto"] for item in linhas if item["produto"]}),
        "apresentacoes": sorted({item["apresentacao"] for item in linhas if item["apresentacao"]}),
        "motivos": sorted({item["motivo"] for item in linhas if item["motivo"]}),
        "destinos": sorted({item["destino"] for item in linhas if item["destino"]}),
    }
