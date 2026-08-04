"""Inventario legado agregado e liberacao de PA em dois niveis."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from uuid import uuid4

from flask import has_request_context, request, session

from database import DATABASE_URL, conectar, q, transaction
from . import produtos_nao_conformes as nc


TIPO_CAIXA = "CAIXA_RASTREADA"
TIPO_LEGADO = "INVENTARIO_LEGADO_AGREGADO"
PENDENTE = "AGUARDANDO_VALIDACAO_GERENCIA"
APROVADA = "APROVADA"
REJEITADA = "REJEITADA"
REVOGADA_POR_CORRECAO = "REVOGADA_POR_CORRECAO"
LOCAL_INVENTARIO = "Câmara de Estocagem - Estoque Não Conforme"
LOCAL_INVENTARIO_ID = 4
SKU_INVENTARIO_ID = 1
SKU_INVENTARIO_CODIGO = "LEG-1"
SKU_INVENTARIO_NOME = "Galinha Cortada"
APRESENTACAO_INVENTARIO = "Congelada"

INVENTARIO_OFICIAL = (
    {"chave": "INVENTARIO_NC_2026_07_30_CARNE_ESCURA", "motivo": "Carne Escura", "condicao": "NAO_CONFORME", "caixas": 689, "bandejas": 8268, "kg": "8340.430"},
    {"chave": "INVENTARIO_NC_2026_07_30_CARCACA_INCOMPLETA", "motivo": "Carcaça Incompleta", "condicao": "NAO_CONFORME", "caixas": 130, "bandejas": 1560, "kg": "1536.130"},
    {"chave": "INVENTARIO_NC_2026_07_30_AGUARDANDO_LIBERACAO", "motivo": "Aguardando Liberação", "condicao": "CONFORME_AGUARDANDO_LIBERACAO", "caixas": 48, "bandejas": 570, "kg": "595.500"},
)


def _agora():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _identidade(usuario=None, perfil=None, origem=None, usuario_id=None):
    if has_request_context():
        usuario = usuario or session.get("nome") or "Usuario nao identificado"
        perfil = perfil or session.get("perfil") or "nao identificado"
        origem = origem or request.remote_addr or "web"
        usuario_id = usuario_id if usuario_id is not None else session.get("usuario_id")
    return (usuario or "Sistema", (perfil or "sistema").lower(),
            origem or "interno", usuario_id)


def _mesma_identidade(solicitacao, usuario, usuario_id):
    solicitante_id = solicitacao["solicitado_por_id"]
    if solicitante_id is not None and usuario_id is not None:
        return int(solicitante_id) == int(usuario_id)
    return str(solicitacao["solicitado_por"] or "").strip().casefold() == str(usuario or "").strip().casefold()


def gramas(valor, campo="Peso"):
    texto = str(valor if valor is not None else "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError) as erro:
        raise ValueError(f"{campo} deve ser um numero valido.") from erro
    if not numero.is_finite() or numero <= 0:
        raise ValueError(f"{campo} deve ser maior que zero.")
    resultado = numero * 1000
    if resultado != resultado.to_integral_value():
        raise ValueError(f"{campo} aceita no maximo tres casas decimais.")
    return int(resultado)


def inteiro(valor, campo):
    texto = str(valor if valor not in (None, "") else "0").strip()
    try:
        numero = Decimal(texto)
    except InvalidOperation as erro:
        raise ValueError(f"{campo} deve ser inteiro e nao negativo.") from erro
    if numero < 0 or numero != numero.to_integral_value():
        raise ValueError(f"{campo} deve ser inteiro e nao negativo.")
    return int(numero)


def _evento(cursor, registro_id, acao, anterior, novo, usuario, perfil, origem,
            justificativa=None, detalhes=None):
    cursor.execute(q("""
        INSERT INTO pa_nao_conforme_eventos (
            pa_nao_conforme_id, acao, status_anterior, status_novo,
            usuario, perfil, justificativa, detalhes, origem, criado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (registro_id, acao, anterior, novo, usuario, perfil, justificativa,
           detalhes, origem, _agora()))


def _auditar_negacao(registro_id, usuario, perfil, origem, detalhes):
    garantir_schema()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT status FROM pa_nao_conformes WHERE id=?"), (registro_id,))
        registro = cursor.fetchone()
        if registro:
            _evento(cursor, registro_id, "TENTATIVA_NEGADA", registro["status"],
                    registro["status"], usuario, perfil, origem, detalhes=detalhes)


def garantir_schema(*, criar_local=True):
    nc.criar_tabelas_pa_nao_conforme()
    conn = conectar()
    try:
        cursor = conn.cursor()
        if criar_local:
            cursor.execute(q("""
                INSERT INTO locais_estoque (nome, tipo, ativo)
                SELECT ?, 'segregacao', 'Sim'
                WHERE NOT EXISTS (SELECT 1 FROM locais_estoque WHERE nome = ?)
            """), (LOCAL_INVENTARIO, LOCAL_INVENTARIO))
        conn.commit()
    finally:
        conn.close()


def simular_carga():
    totais = {
        "registros": len(INVENTARIO_OFICIAL),
        "caixas": sum(item["caixas"] for item in INVENTARIO_OFICIAL),
        "bandejas": sum(item["bandejas"] for item in INVENTARIO_OFICIAL),
        "peso_g": sum(gramas(item["kg"]) for item in INVENTARIO_OFICIAL),
    }
    esperado = {"registros": 3, "caixas": 867, "bandejas": 10398, "peso_g": 10472060}
    if totais != esperado:
        raise RuntimeError("A carga oficial nao reconciliou com os totais de controle.")
    return totais


def carregar_inventario(*, confirmar=False, usuario="Sistema", perfil="admin", origem="comando"):
    totais = simular_carga()
    if not confirmar:
        return {**totais, "modo": "SIMULACAO", "inseridos": 0, "existentes": 0}
    garantir_schema(criar_local=False)
    inseridos = existentes = 0
    ids = []
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT id,codigo,nome,ativo,excluido_em FROM skus
            WHERE id=?"""), (SKU_INVENTARIO_ID,))
        sku = cursor.fetchone()
        if (not sku or sku["codigo"] != SKU_INVENTARIO_CODIGO
                or sku["nome"] != SKU_INVENTARIO_NOME or sku["ativo"] != "Sim"
                or sku["excluido_em"] is not None):
            raise RuntimeError("O SKU oficial 1/LEG-1/Galinha Cortada não está íntegro e ativo.")
        cursor.execute(q("SELECT id,nome,tipo,ativo FROM locais_estoque WHERE id=?"),
                       (LOCAL_INVENTARIO_ID,))
        local = cursor.fetchone()
        if (not local or local["nome"] != LOCAL_INVENTARIO
                or local["tipo"] != "segregacao" or local["ativo"] != "Sim"):
            raise RuntimeError("O local oficial 4 de estoque não conforme não está íntegro e ativo.")
        local_id = local["id"]
        chaves = tuple(item["chave"] for item in INVENTARIO_OFICIAL)
        cursor.execute(q("""SELECT id,idempotency_key FROM pa_nao_conformes
            WHERE idempotency_key IN (?,?,?) ORDER BY id"""), chaves)
        existentes_antes = cursor.fetchall()
        if len(existentes_antes) not in {0, len(INVENTARIO_OFICIAL)}:
            raise RuntimeError("Carga parcial detectada; nenhuma alteração foi realizada.")
        if not existentes_antes:
            cursor.execute(q("""SELECT COUNT(*) AS registros,
                COALESCE(SUM(saldo_inicial_g),0) AS peso_g
                FROM pa_nao_conformes WHERE tipo_registro=?"""), (TIPO_LEGADO,))
            legado = cursor.fetchone()
            if int(legado["registros"] or 0) or int(legado["peso_g"] or 0):
                raise RuntimeError("Já existe inventário legado sem as chaves oficiais.")
        for item in INVENTARIO_OFICIAL:
            cursor.execute(q("SELECT id FROM pa_nao_conformes WHERE idempotency_key=?"), (item["chave"],))
            existente = cursor.fetchone()
            if existente:
                existentes += 1
                ids.append(existente["id"])
                continue
            peso_g = gramas(item["kg"])
            agora = _agora()
            numero = item["chave"].replace("INVENTARIO_NC_", "PNC-LEG-")
            params = (
                numero, SKU_INVENTARIO_NOME, APRESENTACAO_INVENTARIO,
                item["bandejas"], peso_g / 1000, item["motivo"], local_id,
                usuario, perfil, agora,
                "SKU oficial LEG-1 (ID 1). Conservação: Congelada. "
                "OP inexistente; lote e validade não identificados.", agora, agora,
                TIPO_LEGADO, item["chave"], "Inventário físico de Produtos Não Conformes — 30/07/2026",
                "2026-07-30", "Gabriel Menezes e Francimara Abreu", "Edivânia Nascimento",
                "Thiago Nascimento", item["condicao"], item["caixas"], item["bandejas"],
                item["caixas"], item["bandejas"], peso_g, peso_g,
            )
            sql = """
                INSERT INTO pa_nao_conformes (
                    numero, op_id, caixa_id, lote, validade, produto, apresentacao, quantidade,
                    peso, unidade, motivo, status, local_estoque_id, registrado_por, perfil_registro,
                    registrado_em, observacoes, criado_em, atualizado_em, tipo_registro,
                    idempotency_key, origem_entrada, data_contagem, responsaveis_contagem,
                    validacao_qualidade, validacao_gerencia, condicao_inicial, caixas_iniciais,
                    bandejas_iniciais, caixas_bloqueadas, bandejas_bloqueadas, saldo_inicial_g,
                    saldo_bloqueado_g, saldo_pendente_g, saldo_operacional_g,
                    saldo_reservado_operacional_g, saldo_destinado_g
                ) VALUES (?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, 'KG', ?, 'BLOQUEADO', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
            """
            if DATABASE_URL:
                cursor.execute(q(sql + " RETURNING id"), params)
                registro_id = cursor.fetchone()["id"]
            else:
                cursor.execute(q(sql), params)
                registro_id = cursor.lastrowid
            ids.append(registro_id)
            _evento(cursor, registro_id, "CARGA_INICIAL", None, "BLOQUEADO", usuario,
                    perfil, origem, "Inventario fisico oficial de 30/07/2026",
                    json.dumps({"peso_g": peso_g, "caixas": item["caixas"],
                                "bandejas": item["bandejas"],
                                "sku_id": SKU_INVENTARIO_ID,
                                "sku_codigo": SKU_INVENTARIO_CODIGO,
                                "produto": SKU_INVENTARIO_NOME,
                                "apresentacao": APRESENTACAO_INVENTARIO}, sort_keys=True))
            inseridos += 1
    return {**totais, "modo": "EXECUCAO", "inseridos": inseridos,
            "existentes": existentes, "ids": ids}


def solicitar(registro_id, peso, caixas, bandejas, justificativa, observacoes="", *,
              usuario=None, perfil=None, origem=None, usuario_id=None, idempotency_key=None):
    usuario, perfil, origem, usuario_id = _identidade(usuario, perfil, origem, usuario_id)
    if perfil not in {"qualidade", "admin"}:
        _auditar_negacao(registro_id, usuario, perfil, origem,
                         "Perfil sem permissao para solicitar liberacao.")
        raise PermissionError("Somente a Qualidade pode solicitar liberacao.")
    peso_g = gramas(peso, "Peso a liberar")
    caixas = inteiro(caixas, "Caixas")
    bandejas = inteiro(bandejas, "Bandejas")
    if caixas <= 0 or bandejas <= 0:
        raise ValueError("Informe caixas e bandejas envolvidas com valores maiores que zero.")
    justificativa = str(justificativa or "").strip()
    if not justificativa:
        raise ValueError("A justificativa da solicitacao e obrigatoria.")
    garantir_schema()
    chave = idempotency_key or f"LIB-{registro_id}-{uuid4().hex}"
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE id=?"), (registro_id,))
        registro = cursor.fetchone()
        if not registro:
            raise ValueError("Produto Nao Conforme nao encontrado.")
        cursor.execute(q("SELECT id FROM pa_nao_conforme_solicitacoes WHERE idempotency_key=?"), (chave,))
        existente = cursor.fetchone()
        if existente:
            return existente["id"]
        if registro["tipo_registro"] == TIPO_LEGADO:
            disponivel = int(registro["saldo_bloqueado_g"] or 0) - int(registro["saldo_pendente_g"] or 0)
            if peso_g > disponivel:
                raise ValueError("O peso solicitado excede o saldo bloqueado disponivel.")
            if caixas > int(registro["caixas_bloqueadas"] or 0) or bandejas > int(registro["bandejas_bloqueadas"] or 0):
                raise ValueError("Caixas ou bandejas excedem o controle fisico auxiliar.")
        else:
            if peso_g != gramas(registro["peso"], "Peso da caixa"):
                raise ValueError("Caixa rastreada individualmente nao pode ser fracionada.")
            if caixas != 1 or bandejas != int(Decimal(str(registro["quantidade"] or 0))):
                raise ValueError("Caixa rastreada exige uma caixa e todas as bandejas do registro.")
            cursor.execute(q("SELECT COUNT(*) AS total FROM pa_nao_conforme_solicitacoes WHERE pa_nao_conforme_id=? AND status=?"), (registro_id, PENDENTE))
            if int(cursor.fetchone()["total"] or 0):
                raise ValueError("A caixa ja possui liberacao aguardando validacao.")
        agora = _agora()
        params = (registro_id, chave, peso_g, caixas, bandejas, PENDENTE, justificativa,
                  str(observacoes or "").strip(), usuario, usuario_id, perfil, agora, agora, agora)
        sql = """INSERT INTO pa_nao_conforme_solicitacoes (
            pa_nao_conforme_id,idempotency_key,peso_g,caixas,bandejas,status,justificativa,
            observacoes,solicitado_por,solicitado_por_id,perfil_solicitante,
            solicitado_em,criado_em,atualizado_em
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        if DATABASE_URL:
            cursor.execute(q(sql + " RETURNING id"), params)
            solicitacao_id = cursor.fetchone()["id"]
        else:
            cursor.execute(q(sql), params)
            solicitacao_id = cursor.lastrowid
        if registro["tipo_registro"] == TIPO_LEGADO:
            cursor.execute(q("UPDATE pa_nao_conformes SET saldo_pendente_g=saldo_pendente_g+?, atualizado_em=? WHERE id=?"), (peso_g, agora, registro_id))
        _evento(cursor, registro_id, "SOLICITACAO_LIBERACAO", registro["status"], registro["status"],
                usuario, perfil, origem, justificativa,
                json.dumps({"solicitacao_id": solicitacao_id, "peso_g": peso_g,
                            "caixas": caixas, "bandejas": bandejas}, sort_keys=True))
        return solicitacao_id


def validar(solicitacao_id, decisao, justificativa, *, usuario=None, perfil=None, origem=None,
            usuario_id=None):
    usuario, perfil, origem, usuario_id = _identidade(usuario, perfil, origem, usuario_id)
    decisao = str(decisao or "").upper()
    justificativa = str(justificativa or "").strip()
    if perfil not in {"gerencia", "admin"}:
        garantir_schema()
        conn = conectar()
        try:
            cursor = conn.cursor()
            cursor.execute(q("SELECT pa_nao_conforme_id FROM pa_nao_conforme_solicitacoes WHERE id=?"), (solicitacao_id,))
            solicitacao = cursor.fetchone()
        finally:
            conn.close()
        if solicitacao:
            _auditar_negacao(solicitacao["pa_nao_conforme_id"], usuario, perfil, origem,
                             "Perfil sem permissao para validar liberacao.")
        raise PermissionError("Somente Gerencia ou Administrador podem validar liberacao.")
    if decisao not in {"APROVAR", "REJEITAR"} or not justificativa:
        raise ValueError("Informe aprovacao ou rejeicao e a respectiva justificativa.")
    garantir_schema()
    registro_autoaprovacao = None
    with transaction() as conn:
        cursor = conn.cursor()
        bloqueio = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q("""SELECT s.*,nc.tipo_registro,nc.status AS nc_status,nc.caixa_id,
            nc.saldo_bloqueado_g,nc.saldo_pendente_g,nc.saldo_operacional_g
            FROM pa_nao_conforme_solicitacoes s JOIN pa_nao_conformes nc
            ON nc.id=s.pa_nao_conforme_id WHERE s.id=?""" + bloqueio), (solicitacao_id,))
        solicitacao = cursor.fetchone()
        if not solicitacao:
            raise ValueError("Solicitacao de liberacao nao encontrada.")
        if solicitacao["status"] != PENDENTE:
            raise ValueError("Esta solicitacao ja foi validada.")
        if _mesma_identidade(solicitacao, usuario, usuario_id):
            registro_autoaprovacao = solicitacao["pa_nao_conforme_id"]
        else:
            agora = _agora()
            novo_status = APROVADA if decisao == "APROVAR" else REJEITADA
            cursor.execute(q("""UPDATE pa_nao_conforme_solicitacoes SET status=?,decidido_por=?,
                decidido_por_id=?,perfil_decisor=?,decidido_em=?,justificativa_decisao=?,atualizado_em=?
                WHERE id=? AND status=?"""),
                (novo_status, usuario, usuario_id, perfil, agora, justificativa, agora,
                 solicitacao_id, PENDENTE))
            if cursor.rowcount != 1:
                raise ValueError("A solicitacao foi validada simultaneamente por outro usuario.")
            peso_g = int(solicitacao["peso_g"])
            if solicitacao["tipo_registro"] == TIPO_LEGADO:
                if decisao == "APROVAR":
                    cursor.execute(q("""UPDATE pa_nao_conformes SET saldo_bloqueado_g=saldo_bloqueado_g-?,
                        saldo_pendente_g=saldo_pendente_g-?,saldo_operacional_g=saldo_operacional_g+?,
                        caixas_bloqueadas=caixas_bloqueadas-?,bandejas_bloqueadas=bandejas_bloqueadas-?,
                        atualizado_em=? WHERE id=? AND saldo_bloqueado_g>=? AND saldo_pendente_g>=?
                        AND caixas_bloqueadas>=? AND bandejas_bloqueadas>=?"""),
                        (peso_g, peso_g, peso_g, solicitacao["caixas"], solicitacao["bandejas"],
                         agora, solicitacao["pa_nao_conforme_id"], peso_g, peso_g,
                         solicitacao["caixas"], solicitacao["bandejas"]))
                else:
                    cursor.execute(q("""UPDATE pa_nao_conformes SET
                        saldo_pendente_g=saldo_pendente_g-?,atualizado_em=?
                        WHERE id=? AND saldo_pendente_g>=?"""),
                        (peso_g, agora, solicitacao["pa_nao_conforme_id"], peso_g))
                if cursor.rowcount != 1:
                    raise ValueError("A reserva de peso ou o controle auxiliar nao esta integro.")
            elif decisao == "APROVAR":
                cursor.execute(q("""UPDATE pa_caixas SET condicao='CONFORME',
                    disponibilidade='DISPONIVEL',zona_estoque='Conforme',
                    motivo_nao_conformidade=NULL
                    WHERE id=? AND disponibilidade='BLOQUEADO'"""),
                    (solicitacao["caixa_id"],))
                if cursor.rowcount != 1:
                    raise ValueError("A caixa nao esta mais integralmente bloqueada.")
                cursor.execute(q("""UPDATE pa_nao_conformes SET status='LIBERADO',
                    decisao='LIBERAR',decidido_por=?,perfil_decisao=?,decidido_em=?,
                    justificativa_destinacao=?,atualizado_em=? WHERE id=?"""),
                    (usuario, perfil, agora, justificativa, agora,
                     solicitacao["pa_nao_conforme_id"]))
            acao = "APROVACAO_LIBERACAO" if decisao == "APROVAR" else "REJEICAO_LIBERACAO"
            antes = {
                "saldo_bloqueado_g": int(solicitacao["saldo_bloqueado_g"] or 0),
                "saldo_pendente_g": int(solicitacao["saldo_pendente_g"] or 0),
                "saldo_operacional_g": int(solicitacao["saldo_operacional_g"] or 0),
            }
            depois = dict(antes)
            depois["saldo_pendente_g"] -= peso_g if solicitacao["tipo_registro"] == TIPO_LEGADO else 0
            if decisao == "APROVAR" and solicitacao["tipo_registro"] == TIPO_LEGADO:
                depois["saldo_bloqueado_g"] -= peso_g
                depois["saldo_operacional_g"] += peso_g
            _evento(cursor, solicitacao["pa_nao_conforme_id"], acao, solicitacao["nc_status"],
                "LIBERADO" if decisao == "APROVAR" and solicitacao["tipo_registro"] != TIPO_LEGADO else solicitacao["nc_status"],
                usuario, perfil, origem, justificativa,
                json.dumps({"solicitacao_id": solicitacao_id, "peso_g": peso_g,
                            "caixas": solicitacao["caixas"], "bandejas": solicitacao["bandejas"],
                            "antes": antes, "depois": depois}, sort_keys=True))
    if registro_autoaprovacao is not None:
        # A auditoria usa outra transacao para sobreviver ao bloqueio da operacao principal.
        _auditar_negacao(registro_autoaprovacao, usuario, perfil, origem,
                         "Autoaprovacao bloqueada: a solicitacao deve ser avaliada por outro usuario autorizado.")
        raise PermissionError("Esta solicitacao deve ser avaliada por outro usuario autorizado.")


def reverter_liberacao_administrativa(solicitacao_id, *, usuario=None, perfil=None,
                                      origem=None, usuario_id=None):
    """Revoga uma aprovacao sem uso posterior e restaura o bloqueio na mesma transacao."""
    usuario, perfil, origem, usuario_id = _identidade(usuario, perfil, origem, usuario_id)
    if perfil != "admin":
        raise PermissionError("Somente Administrador pode executar a reversao administrativa.")
    garantir_schema(criar_local=False)
    motivo = ("Liberacao revertida porque o mesmo usuario solicitou e aprovou a movimentacao, "
              "contrariando a segregacao de funcoes definida para Qualidade e Gerencia.")
    with transaction() as conn:
        cursor = conn.cursor()
        bloqueio = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q("""SELECT s.*,nc.idempotency_key AS registro_chave,
            nc.tipo_registro,nc.status AS nc_status,nc.condicao_inicial,
            nc.saldo_inicial_g,nc.saldo_bloqueado_g,nc.saldo_pendente_g,
            nc.saldo_operacional_g,nc.saldo_reservado_operacional_g,nc.saldo_destinado_g,
            nc.caixas_bloqueadas,nc.bandejas_bloqueadas
            FROM pa_nao_conforme_solicitacoes s JOIN pa_nao_conformes nc
            ON nc.id=s.pa_nao_conforme_id WHERE s.id=?""" + bloqueio), (solicitacao_id,))
        solicitacao = cursor.fetchone()
        if not solicitacao:
            raise ValueError("Solicitacao de liberacao nao encontrada.")
        if solicitacao["status"] == REVOGADA_POR_CORRECAO:
            return {"solicitacao_id": solicitacao_id, "registro_id": solicitacao["pa_nao_conforme_id"],
                    "status": REVOGADA_POR_CORRECAO, "ja_revertida": True}
        if solicitacao["status"] != APROVADA:
            raise ValueError("Somente uma solicitacao aprovada pode ser revertida.")
        if solicitacao["tipo_registro"] != TIPO_LEGADO:
            raise ValueError("Esta reversao administrativa exige inventario legado agregado.")
        cursor.execute(q("SELECT COUNT(*) AS total FROM expedicao_itens WHERE pa_nao_conforme_id=?"),
                       (solicitacao["pa_nao_conforme_id"],))
        if int(cursor.fetchone()["total"] or 0):
            raise ValueError("O saldo possui item de romaneio; a reversao foi interrompida.")
        peso_g = int(solicitacao["peso_g"])
        caixas = int(solicitacao["caixas"])
        bandejas = int(solicitacao["bandejas"])
        antes = {
            "saldo_bloqueado_g": int(solicitacao["saldo_bloqueado_g"] or 0),
            "saldo_pendente_g": int(solicitacao["saldo_pendente_g"] or 0),
            "saldo_operacional_g": int(solicitacao["saldo_operacional_g"] or 0),
            "saldo_reservado_operacional_g": int(solicitacao["saldo_reservado_operacional_g"] or 0),
            "saldo_destinado_g": int(solicitacao["saldo_destinado_g"] or 0),
            "caixas_bloqueadas": int(solicitacao["caixas_bloqueadas"] or 0),
            "bandejas_bloqueadas": int(solicitacao["bandejas_bloqueadas"] or 0),
        }
        if (antes["saldo_reservado_operacional_g"] != 0 or antes["saldo_destinado_g"] != 0
                or antes["saldo_pendente_g"] != 0 or antes["saldo_operacional_g"] != peso_g):
            raise ValueError("O saldo aprovado foi utilizado ou alterado; a reversao foi interrompida.")
        cursor.execute(q("""SELECT id,acao,detalhes FROM pa_nao_conforme_eventos
            WHERE pa_nao_conforme_id=? AND acao IN ('SOLICITACAO_LIBERACAO','APROVACAO_LIBERACAO')
            ORDER BY id"""), (solicitacao["pa_nao_conforme_id"],))
        eventos_originais = []
        for evento in cursor.fetchall():
            try:
                detalhes = json.loads(evento["detalhes"] or "{}")
            except (TypeError, ValueError):
                detalhes = {}
            if int(detalhes.get("solicitacao_id") or 0) == int(solicitacao_id):
                eventos_originais.append({"id": evento["id"], "acao": evento["acao"]})
        if {item["acao"] for item in eventos_originais} != {
                "SOLICITACAO_LIBERACAO", "APROVACAO_LIBERACAO"}:
            raise ValueError("Os eventos originais da liberacao nao estao integros.")
        agora = _agora()
        cursor.execute(q("""UPDATE pa_nao_conformes SET status='BLOQUEADO',
            saldo_bloqueado_g=saldo_bloqueado_g+?,saldo_operacional_g=saldo_operacional_g-?,
            caixas_bloqueadas=caixas_bloqueadas+?,bandejas_bloqueadas=bandejas_bloqueadas+?,
            atualizado_em=? WHERE id=? AND saldo_operacional_g=?
            AND saldo_reservado_operacional_g=0 AND saldo_destinado_g=0 AND saldo_pendente_g=0"""),
            (peso_g, peso_g, caixas, bandejas, agora, solicitacao["pa_nao_conforme_id"], peso_g))
        if cursor.rowcount != 1:
            raise ValueError("O saldo mudou simultaneamente; a reversao foi interrompida.")
        cursor.execute(q("""UPDATE pa_nao_conforme_solicitacoes SET status=?,atualizado_em=?
            WHERE id=? AND status=?"""),
            (REVOGADA_POR_CORRECAO, agora, solicitacao_id, APROVADA))
        if cursor.rowcount != 1:
            raise ValueError("A solicitacao mudou simultaneamente; a reversao foi interrompida.")
        depois = dict(antes)
        depois.update({
            "saldo_bloqueado_g": antes["saldo_bloqueado_g"] + peso_g,
            "saldo_operacional_g": antes["saldo_operacional_g"] - peso_g,
            "caixas_bloqueadas": antes["caixas_bloqueadas"] + caixas,
            "bandejas_bloqueadas": antes["bandejas_bloqueadas"] + bandejas,
        })
        _evento(cursor, solicitacao["pa_nao_conforme_id"],
                "REVERSAO_LIBERACAO_ADMINISTRATIVA", solicitacao["nc_status"], "BLOQUEADO",
                usuario, perfil, origem, motivo,
                json.dumps({
                    "solicitacao_id": solicitacao_id,
                    "registro_id": solicitacao["pa_nao_conforme_id"],
                    "registro_chave": solicitacao["registro_chave"],
                    "executor_usuario_id": usuario_id,
                    "peso_g": peso_g, "caixas": caixas, "bandejas": bandejas,
                    "antes": antes, "depois": depois,
                    "eventos_originais": eventos_originais,
                    "origem_correcao": origem,
                }, sort_keys=True))
        return {
            "solicitacao_id": solicitacao_id,
            "registro_id": solicitacao["pa_nao_conforme_id"],
            "registro_chave": solicitacao["registro_chave"],
            "status": REVOGADA_POR_CORRECAO,
            "peso_g": peso_g, "caixas": caixas, "bandejas": bandejas,
            "antes": antes, "depois": depois, "ja_revertida": False,
        }


def pendentes(usuario_id=None, usuario=None):
    garantir_schema()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT s.*,nc.numero,nc.produto,nc.motivo,nc.peso,nc.saldo_inicial_g,
            nc.saldo_bloqueado_g,nc.tipo_registro FROM pa_nao_conforme_solicitacoes s
            JOIN pa_nao_conformes nc ON nc.id=s.pa_nao_conforme_id
            WHERE s.status=? ORDER BY s.solicitado_em,s.id"""), (PENDENTE,))
        resultados = []
        for linha in cursor.fetchall():
            item = dict(linha)
            item["pode_validar"] = not _mesma_identidade(item, usuario, usuario_id)
            resultados.append(item)
        return resultados
    finally:
        conn.close()


def solicitacoes_do_registro(registro_id):
    garantir_schema()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM pa_nao_conforme_solicitacoes WHERE pa_nao_conforme_id=? ORDER BY criado_em DESC,id DESC"), (registro_id,))
        return cursor.fetchall()
    finally:
        conn.close()


def saldos_legados_operacionais():
    garantir_schema(criar_local=False)
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT nc.*,le.nome AS local_nome FROM pa_nao_conformes nc
            JOIN locais_estoque le ON le.id=nc.local_estoque_id
            WHERE nc.tipo_registro=? AND nc.saldo_operacional_g>0 ORDER BY nc.data_contagem,nc.id"""), (TIPO_LEGADO,))
        return cursor.fetchall()
    finally:
        conn.close()


def inventario_legado_fisico():
    """Lista o legado ainda presente fisicamente, independentemente da disponibilidade."""
    garantir_schema(criar_local=False)
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT nc.*,le.nome AS local_nome
            FROM pa_nao_conformes nc
            JOIN locais_estoque le ON le.id=nc.local_estoque_id
            WHERE nc.tipo_registro=?
              AND (nc.saldo_inicial_g-COALESCE(nc.saldo_destinado_g,0))>0
            ORDER BY nc.data_contagem,nc.id"""), (TIPO_LEGADO,))
        registros = []
        for linha in cursor.fetchall():
            item = dict(linha)
            item["sku_codigo"] = SKU_INVENTARIO_CODIGO
            item["origem_fisica"] = "Inventário Legado"
            item["peso_fisico_g"] = max(
                0, int(item["saldo_inicial_g"] or 0) - int(item["saldo_destinado_g"] or 0)
            )
            if item["condicao_inicial"] == "NAO_CONFORME":
                item["condicao_fisica"] = "Não conforme"
            else:
                item["condicao_fisica"] = "Conforme — aguardando liberação"
            if int(item["saldo_bloqueado_g"] or 0) > 0:
                item["disponibilidade_fisica"] = "Bloqueado"
            elif int(item["saldo_reservado_operacional_g"] or 0) > 0:
                item["disponibilidade_fisica"] = "Reservado"
            else:
                item["disponibilidade_fisica"] = "Disponível"
            registros.append(item)
        return registros
    finally:
        conn.close()


def resumo_inventario_legado_fisico(registros=None):
    registros = inventario_legado_fisico() if registros is None else registros
    nao_conformes = [item for item in registros if item["condicao_inicial"] == "NAO_CONFORME"]
    aguardando = [item for item in registros if item["condicao_inicial"] == "CONFORME_AGUARDANDO_LIBERACAO"]
    return {
        "registros": len(registros),
        "caixas_fisicas": sum(int(item["caixas_iniciais"] or 0) for item in registros),
        "bandejas_fisicas": sum(int(item["bandejas_iniciais"] or 0) for item in registros),
        "peso_fisico_g": sum(int(item["peso_fisico_g"] or 0) for item in registros),
        "caixas_bloqueadas_nc": sum(int(item["caixas_bloqueadas"] or 0) for item in nao_conformes),
        "peso_bloqueado_nc_g": sum(int(item["saldo_bloqueado_g"] or 0) for item in nao_conformes),
        "caixas_aguardando": sum(int(item["caixas_bloqueadas"] or 0) for item in aguardando),
        "peso_aguardando_g": sum(int(item["saldo_bloqueado_g"] or 0) for item in aguardando),
        "peso_disponivel_g": sum(int(item["saldo_operacional_g"] or 0) for item in registros),
        "peso_reservado_g": sum(int(item["saldo_reservado_operacional_g"] or 0) for item in registros),
    }


def reservar_operacional(expedicao_id, registro_id, peso, caixas, bandejas, *,
                         usuario=None, perfil=None, origem=None):
    """Reserva saldo legado por kg para um romaneio normal aberto."""
    usuario, perfil, origem, _ = _identidade(usuario, perfil, origem)
    peso_g = gramas(peso, "Peso a movimentar")
    caixas = inteiro(caixas, "Caixas")
    bandejas = inteiro(bandejas, "Bandejas")
    if caixas <= 0 or bandejas <= 0:
        raise ValueError("Informe caixas e bandejas envolvidas com valores maiores que zero.")
    garantir_schema()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM expedicoes WHERE id=?"), (expedicao_id,))
        romaneio = cursor.fetchone()
        if not romaneio or romaneio["status"] != "Aberto" or romaneio["tipo_movimentacao"] != "TRANSFERENCIA":
            raise ValueError("Saldo legado liberado so pode entrar em romaneio normal aberto.")
        cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE id=? AND tipo_registro=?"), (registro_id, TIPO_LEGADO))
        registro = cursor.fetchone()
        if not registro or int(registro["saldo_operacional_g"] or 0) < peso_g:
            raise ValueError("O peso excede o saldo legado operacional disponivel.")
        agora = _agora()
        cursor.execute(q("""UPDATE pa_nao_conformes SET saldo_operacional_g=saldo_operacional_g-?,
            saldo_reservado_operacional_g=saldo_reservado_operacional_g+?,atualizado_em=?
            WHERE id=? AND saldo_operacional_g>=?"""), (peso_g,peso_g,agora,registro_id,peso_g))
        cursor.execute(q("""INSERT INTO expedicao_itens (
            expedicao_id,caixa_id,op_id,sku,quantidade_unidades,quantidade_kg,
            situacao_anterior,condicao_anterior,unidade_estoque,apresentacao,lote,
            pa_nao_conforme_id,quantidade_caixas,quantidade_bandejas,origem_tipo
            ) VALUES (?,NULL,NULL,?,?,?,?,?,'KG',?,NULL,?,?,?,?)"""),
            (expedicao_id,registro["produto"],caixas,peso_g/1000,"DISPONIVEL","CONFORME",
             "Inventario legado agregado",registro_id,caixas,bandejas,TIPO_LEGADO))
        item_id = cursor.lastrowid if not DATABASE_URL else None
        _evento(cursor, registro_id, "RESERVA_ROMANEIO", "DISPONIVEL", "RESERVADO", usuario,
                perfil, origem, f"Romaneio #{expedicao_id}",
                json.dumps({"peso_g":peso_g,"caixas":caixas,"bandejas":bandejas}, sort_keys=True))
        return item_id


def remover_reserva_operacional(expedicao_id, item_id, *, usuario=None, perfil=None, origem=None):
    usuario, perfil, origem, _ = _identidade(usuario, perfil, origem)
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT i.*,e.status FROM expedicao_itens i JOIN expedicoes e ON e.id=i.expedicao_id
            WHERE i.id=? AND i.expedicao_id=? AND i.origem_tipo=?"""), (item_id,expedicao_id,TIPO_LEGADO))
        item = cursor.fetchone()
        if not item or item["status"] != "Aberto":
            raise ValueError("Reserva agregada nao encontrada em romaneio aberto.")
        peso_g = gramas(item["quantidade_kg"], "Peso reservado")
        cursor.execute(q("""UPDATE pa_nao_conformes SET saldo_operacional_g=saldo_operacional_g+?,
            saldo_reservado_operacional_g=saldo_reservado_operacional_g-?,atualizado_em=?
            WHERE id=? AND saldo_reservado_operacional_g>=?"""),
            (peso_g,peso_g,_agora(),item["pa_nao_conforme_id"],peso_g))
        if cursor.rowcount != 1:
            raise ValueError("A reserva agregada nao esta integra.")
        cursor.execute(q("DELETE FROM expedicao_itens WHERE id=?"), (item_id,))
        _evento(cursor,item["pa_nao_conforme_id"],"REMOCAO_RESERVA_ROMANEIO","RESERVADO","DISPONIVEL",
                usuario,perfil,origem,f"Romaneio #{expedicao_id}")


def concluir_reservas_cursor(cursor, expedicao_id, usuario="Sistema", perfil="sistema", origem="romaneio"):
    cursor.execute(q("SELECT * FROM expedicao_itens WHERE expedicao_id=? AND origem_tipo=?"), (expedicao_id,TIPO_LEGADO))
    itens = cursor.fetchall()
    for item in itens:
        peso_g = gramas(item["quantidade_kg"], "Peso reservado")
        cursor.execute(q("""UPDATE pa_nao_conformes SET saldo_reservado_operacional_g=saldo_reservado_operacional_g-?,
            saldo_destinado_g=saldo_destinado_g+?,atualizado_em=? WHERE id=? AND saldo_reservado_operacional_g>=?"""),
            (peso_g,peso_g,_agora(),item["pa_nao_conforme_id"],peso_g))
        if cursor.rowcount != 1:
            raise ValueError("A reserva agregada do romaneio nao esta integra.")
        _evento(cursor,item["pa_nao_conforme_id"],"BAIXA_ROMANEIO","RESERVADO","TRANSFERIDO",
                usuario,perfil,origem,f"Romaneio #{expedicao_id}",
                json.dumps({"peso_g":peso_g,"caixas":item["quantidade_caixas"],"bandejas":item["quantidade_bandejas"]}, sort_keys=True))
    return len(itens)


def cancelar_reservas_cursor(cursor, expedicao_id, justificativa, usuario="Sistema", perfil="sistema", origem="romaneio"):
    cursor.execute(q("SELECT * FROM expedicao_itens WHERE expedicao_id=? AND origem_tipo=?"), (expedicao_id,TIPO_LEGADO))
    for item in cursor.fetchall():
        peso_g = gramas(item["quantidade_kg"], "Peso reservado")
        cursor.execute(q("""UPDATE pa_nao_conformes SET saldo_reservado_operacional_g=saldo_reservado_operacional_g-?,
            saldo_operacional_g=saldo_operacional_g+?,atualizado_em=? WHERE id=? AND saldo_reservado_operacional_g>=?"""),
            (peso_g,peso_g,_agora(),item["pa_nao_conforme_id"],peso_g))
        if cursor.rowcount != 1:
            raise ValueError("A reserva agregada do romaneio nao esta integra.")
        _evento(cursor,item["pa_nao_conforme_id"],"CANCELAMENTO_ROMANEIO","RESERVADO","DISPONIVEL",
                usuario,perfil,origem,justificativa)


def estornar_baixas_cursor(cursor, expedicao_id, justificativa, usuario="Sistema", perfil="sistema", origem="romaneio"):
    cursor.execute(q("SELECT * FROM expedicao_itens WHERE expedicao_id=? AND origem_tipo=?"), (expedicao_id,TIPO_LEGADO))
    for item in cursor.fetchall():
        peso_g = gramas(item["quantidade_kg"], "Peso movimentado")
        cursor.execute(q("""UPDATE pa_nao_conformes SET saldo_destinado_g=saldo_destinado_g-?,
            saldo_operacional_g=saldo_operacional_g+?,atualizado_em=?
            WHERE id=? AND saldo_destinado_g>=?"""),
            (peso_g,peso_g,_agora(),item["pa_nao_conforme_id"],peso_g))
        if cursor.rowcount != 1:
            raise ValueError("A baixa agregada nao pode ser estornada sem saldo destinado integro.")
        _evento(cursor,item["pa_nao_conforme_id"],"ESTORNO_ROMANEIO","TRANSFERIDO","DISPONIVEL",
                usuario,perfil,origem,justificativa,
                json.dumps({"peso_g":peso_g,"caixas":item["quantidade_caixas"],"bandejas":item["quantidade_bandejas"]}, sort_keys=True))
