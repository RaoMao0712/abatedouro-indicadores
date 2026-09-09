"""Regras do Cadastro Mestre de Parceiros e compatibilidade com legados."""

from datetime import datetime
import json
import re
import unicodedata
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import has_request_context, session

from database import DATABASE_URL, conectar, q, transaction


FUSO_MANAUS = ZoneInfo("America/Manaus")
STATUS_ATIVO = "Ativo"
STATUS_INATIVO = "Inativo"

PAPEL_CLIENTE = "CLIENTE"
PAPEL_FORNECEDOR = "FORNECEDOR"
PAPEL_PRESTADOR = "PRESTADOR_SERVICOS"
PAPEL_CLT = "COLABORADOR_CLT"
PAPEIS_VALIDOS = {PAPEL_CLIENTE, PAPEL_FORNECEDOR, PAPEL_PRESTADOR, PAPEL_CLT}
PAPEIS_TRABALHISTAS = {PAPEL_CLT, PAPEL_PRESTADOR}
ROTULOS_PAPEIS = {
    PAPEL_CLIENTE: "Cliente",
    PAPEL_FORNECEDOR: "Fornecedor",
    PAPEL_PRESTADOR: "Prestador de Serviços",
    PAPEL_CLT: "Colaborador CLT",
}

PERFIS_CONSULTA = {"admin", "gerencia", "pcp", "producao", "expedicao"}
PERFIS_EDICAO = {"admin", "gerencia", "pcp"}
PERFIS_STATUS = {"admin", "gerencia"}


def _agora():
    return datetime.now(FUSO_MANAUS).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _identidade(usuario=None, perfil=None):
    if has_request_context():
        usuario = usuario or session.get("nome")
        perfil = perfil or session.get("perfil")
    return usuario or "Sistema", (perfil or "sistema").lower()


def _adicionar_coluna(cursor, postgres, sqlite):
    try:
        cursor.execute(postgres if DATABASE_URL else sqlite)
    except Exception:
        if DATABASE_URL:
            raise


def criar_tabelas_parceiros():
    """Bootstrap aditivo e idempotente para PostgreSQL e SQLite."""
    conn = conectar()
    cursor = conn.cursor()
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp = "TIMESTAMP" if DATABASE_URL else "TEXT"
    try:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS parceiros (
                id {pk}, uuid TEXT NOT NULL UNIQUE, tipo_pessoa TEXT NOT NULL,
                razao_social TEXT NOT NULL, nome_fantasia TEXT, documento TEXT,
                telefone TEXT, email TEXT, endereco TEXT, complemento TEXT,
                bairro TEXT, cidade TEXT, uf TEXT, cep TEXT, observacoes TEXT,
                status TEXT NOT NULL DEFAULT 'Ativo', criado_por TEXT NOT NULL,
                atualizado_por TEXT NOT NULL, criado_em {timestamp} NOT NULL,
                atualizado_em {timestamp} NOT NULL
            )
        """)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS parceiro_papeis (
                id {pk}, parceiro_id INTEGER NOT NULL, papel TEXT NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1, adicionado_por TEXT NOT NULL,
                adicionado_em {timestamp} NOT NULL, removido_por TEXT,
                removido_em {timestamp}, UNIQUE(parceiro_id, papel)
            )
        """)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS parceiro_eventos (
                id {pk}, parceiro_id INTEGER NOT NULL, acao TEXT NOT NULL,
                papel TEXT, estado_anterior TEXT, estado_posterior TEXT,
                usuario TEXT NOT NULL, perfil TEXT NOT NULL,
                criado_em {timestamp} NOT NULL
            )
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_parceiros_documento ON parceiros(documento) WHERE documento IS NOT NULL")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_parceiros_busca ON parceiros(status,tipo_pessoa,razao_social)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_parceiro_papeis_elegibilidade ON parceiro_papeis(papel,ativo,parceiro_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_parceiro_eventos_historico ON parceiro_eventos(parceiro_id,criado_em)")

        _adicionar_coluna(cursor, "ALTER TABLE apontamentos_mao_obra ADD COLUMN IF NOT EXISTS parceiro_id INTEGER", "ALTER TABLE apontamentos_mao_obra ADD COLUMN parceiro_id INTEGER")
        _adicionar_coluna(cursor, "ALTER TABLE apontamentos_mao_obra ADD COLUMN IF NOT EXISTS parceiro_nome_snapshot TEXT", "ALTER TABLE apontamentos_mao_obra ADD COLUMN parceiro_nome_snapshot TEXT")
        _adicionar_coluna(cursor, "ALTER TABLE apontamentos_mao_obra ADD COLUMN IF NOT EXISTS natureza_vinculo TEXT", "ALTER TABLE apontamentos_mao_obra ADD COLUMN natureza_vinculo TEXT")
        _adicionar_coluna(cursor, "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS parceiro_id INTEGER", "ALTER TABLE clientes ADD COLUMN parceiro_id INTEGER")
        _adicionar_coluna(cursor, "ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS parceiro_id INTEGER", "ALTER TABLE fornecedores ADD COLUMN parceiro_id INTEGER")
        for coluna in (
            "documento TEXT", "status TEXT DEFAULT 'Ativo'", "tipo_pessoa TEXT DEFAULT 'PJ'",
            "telefone TEXT", "email TEXT", "endereco TEXT", "complemento TEXT",
            "bairro TEXT", "cidade TEXT", "uf TEXT", "cep TEXT", "observacoes TEXT",
        ):
            _adicionar_coluna(cursor, f"ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS {coluna}",
                              f"ALTER TABLE fornecedores ADD COLUMN {coluna}")
        _adicionar_coluna(cursor, "ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS cliente_parceiro_id INTEGER", "ALTER TABLE expedicoes ADD COLUMN cliente_parceiro_id INTEGER")
        _adicionar_coluna(cursor, "ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS fornecedor_parceiro_id INTEGER", "ALTER TABLE ordens_producao ADD COLUMN fornecedor_parceiro_id INTEGER")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS parceiro_migracoes_legado (
            id {pk}, tipo_legado TEXT NOT NULL, id_legado INTEGER NOT NULL,
            parceiro_id INTEGER, parceiro_criado INTEGER NOT NULL DEFAULT 0,
            papel_adicionado INTEGER NOT NULL DEFAULT 0, resultado TEXT NOT NULL,
            detalhes TEXT, executor TEXT NOT NULL, executado_em {timestamp} NOT NULL,
            UNIQUE(tipo_legado,id_legado)
        )""")
        _adicionar_coluna(cursor,
                          "CREATE INDEX IF NOT EXISTS idx_apontamentos_mao_obra_parceiro ON apontamentos_mao_obra(parceiro_id,op_id)",
                          "CREATE INDEX IF NOT EXISTS idx_apontamentos_mao_obra_parceiro ON apontamentos_mao_obra(parceiro_id,op_id)")
        for indice in (
            "CREATE INDEX IF NOT EXISTS idx_clientes_parceiro ON clientes(parceiro_id)",
            "CREATE INDEX IF NOT EXISTS idx_fornecedores_parceiro ON fornecedores(parceiro_id)",
            "CREATE INDEX IF NOT EXISTS idx_expedicoes_cliente_parceiro ON expedicoes(cliente_parceiro_id,data)",
            "CREATE INDEX IF NOT EXISTS idx_ops_fornecedor_parceiro ON ordens_producao(fornecedor_parceiro_id,data)",
        ):
            _adicionar_coluna(cursor, indice, indice)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def normalizar_documento(valor):
    documento = re.sub(r"\D", "", str(valor or ""))
    return documento or None


def normalizar_nome(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return " ".join(texto.casefold().split())


def _digitos_cpf(base):
    soma = sum(int(numero) * peso for numero, peso in zip(base, range(len(base) + 1, 1, -1)))
    resto = (soma * 10) % 11
    return "0" if resto == 10 else str(resto)


def cpf_valido(documento):
    documento = normalizar_documento(documento) or ""
    if len(documento) != 11 or documento == documento[0] * 11:
        return False
    primeiro = _digitos_cpf(documento[:9])
    segundo = _digitos_cpf(documento[:9] + primeiro)
    return documento[-2:] == primeiro + segundo


def _digito_cnpj(base, pesos):
    resto = sum(int(numero) * peso for numero, peso in zip(base, pesos)) % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(documento):
    documento = normalizar_documento(documento) or ""
    if len(documento) != 14 or documento == documento[0] * 14:
        return False
    primeiro = _digito_cnpj(documento[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    segundo = _digito_cnpj(documento[:12] + primeiro, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return documento[-2:] == primeiro + segundo


def validar_documento(tipo_pessoa, documento):
    documento = normalizar_documento(documento)
    if not documento:
        return None
    if tipo_pessoa == "PF" and not cpf_valido(documento):
        raise ValueError("CPF inválido.")
    if tipo_pessoa == "PJ" and not cnpj_valido(documento):
        raise ValueError("CNPJ inválido.")
    return documento


def _papeis_form(form):
    papeis = form.getlist("papeis") if hasattr(form, "getlist") else form.get("papeis", [])
    if isinstance(papeis, str):
        papeis = [papeis]
    papeis = {str(papel).strip().upper() for papel in papeis if str(papel).strip()}
    invalidos = papeis - PAPEIS_VALIDOS
    if invalidos:
        raise ValueError("Papel de parceiro inválido.")
    return papeis


def _dados_form(form):
    tipo = str(form.get("tipo_pessoa") or "").upper().strip()
    razao = str(form.get("razao_social") or "").strip()
    if tipo not in {"PF", "PJ"}:
        raise ValueError("Tipo de pessoa deve ser Física ou Jurídica.")
    if not razao:
        raise ValueError("Nome ou razão social é obrigatório.")
    return {
        "tipo_pessoa": tipo,
        "razao_social": razao,
        "nome_fantasia": str(form.get("nome_fantasia") or "").strip(),
        "documento": validar_documento(tipo, form.get("documento")),
        "telefone": str(form.get("telefone") or "").strip(),
        "email": str(form.get("email") or "").strip().lower(),
        "endereco": str(form.get("endereco") or "").strip(),
        "complemento": str(form.get("complemento") or "").strip(),
        "bairro": str(form.get("bairro") or "").strip(),
        "cidade": str(form.get("cidade") or "").strip(),
        "uf": str(form.get("uf") or "").strip().upper()[:2],
        "cep": re.sub(r"\D", "", str(form.get("cep") or ""))[:8],
        "observacoes": str(form.get("observacoes") or "").strip(),
    }, _papeis_form(form)


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str) if valor is not None else None


def _evento(cursor, parceiro_id, acao, antes, depois, usuario, perfil, papel=None):
    cursor.execute(q("""INSERT INTO parceiro_eventos
        (parceiro_id,acao,papel,estado_anterior,estado_posterior,usuario,perfil,criado_em)
        VALUES (?,?,?,?,?,?,?,?)"""),
        (parceiro_id, acao, papel, _json(antes), _json(depois), usuario, perfil, _agora()))


def _papeis_ativos_cursor(cursor, parceiro_id):
    cursor.execute(q("SELECT papel FROM parceiro_papeis WHERE parceiro_id=? AND ativo=1 ORDER BY papel"), (parceiro_id,))
    return {linha["papel"] for linha in cursor.fetchall()}


def salvar_parceiro(form, parceiro_id=None, *, usuario=None, perfil=None):
    usuario, perfil = _identidade(usuario, perfil)
    if perfil not in PERFIS_EDICAO:
        raise PermissionError("Perfil sem permissão para cadastrar ou editar parceiros.")
    criar_tabelas_parceiros()
    dados, papeis_novos = _dados_form(form)
    agora = _agora()
    with transaction() as conn:
        cursor = conn.cursor()
        antes = None
        papeis_anteriores = set()
        if parceiro_id:
            cursor.execute(q("SELECT * FROM parceiros WHERE id=?"), (parceiro_id,))
            registro = cursor.fetchone()
            if not registro:
                raise ValueError("Parceiro não encontrado.")
            antes = dict(registro)
            papeis_anteriores = _papeis_ativos_cursor(cursor, parceiro_id)
        if dados["documento"]:
            cursor.execute(q("SELECT id FROM parceiros WHERE documento=? AND id<>?"), (dados["documento"], int(parceiro_id or 0)))
            if cursor.fetchone():
                raise ValueError("CPF/CNPJ já cadastrado em outro parceiro.")

        campos = tuple(dados.values())
        if parceiro_id:
            cursor.execute(q("""UPDATE parceiros SET tipo_pessoa=?,razao_social=?,nome_fantasia=?,
                documento=?,telefone=?,email=?,endereco=?,complemento=?,bairro=?,cidade=?,uf=?,cep=?,
                observacoes=?,atualizado_por=?,atualizado_em=? WHERE id=?"""),
                campos + (usuario, agora, parceiro_id))
        elif DATABASE_URL:
            cursor.execute(q("""INSERT INTO parceiros
                (uuid,tipo_pessoa,razao_social,nome_fantasia,documento,telefone,email,endereco,
                 complemento,bairro,cidade,uf,cep,observacoes,status,criado_por,atualizado_por,criado_em,atualizado_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id"""),
                (str(uuid4()),) + campos + (STATUS_ATIVO, usuario, usuario, agora, agora))
            parceiro_id = cursor.fetchone()["id"]
        else:
            cursor.execute(q("""INSERT INTO parceiros
                (uuid,tipo_pessoa,razao_social,nome_fantasia,documento,telefone,email,endereco,
                 complemento,bairro,cidade,uf,cep,observacoes,status,criado_por,atualizado_por,criado_em,atualizado_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
                (str(uuid4()),) + campos + (STATUS_ATIVO, usuario, usuario, agora, agora))
            parceiro_id = cursor.lastrowid

        adicionados = papeis_novos - papeis_anteriores
        removidos = papeis_anteriores - papeis_novos
        for papel in adicionados:
            cursor.execute(q("SELECT id FROM parceiro_papeis WHERE parceiro_id=? AND papel=?"), (parceiro_id, papel))
            existente = cursor.fetchone()
            if existente:
                cursor.execute(q("""UPDATE parceiro_papeis SET ativo=1,adicionado_por=?,adicionado_em=?,
                    removido_por=NULL,removido_em=NULL WHERE id=?"""), (usuario, agora, existente["id"]))
            else:
                cursor.execute(q("""INSERT INTO parceiro_papeis
                    (parceiro_id,papel,ativo,adicionado_por,adicionado_em) VALUES (?,?,?,?,?)"""),
                    (parceiro_id, papel, 1, usuario, agora))
        for papel in removidos:
            cursor.execute(q("""UPDATE parceiro_papeis SET ativo=0,removido_por=?,removido_em=?
                WHERE parceiro_id=? AND papel=?"""), (usuario, agora, parceiro_id, papel))

        cursor.execute(q("SELECT * FROM parceiros WHERE id=?"), (parceiro_id,))
        depois = dict(cursor.fetchone())
        estado_antes = {**(antes or {}), "papeis": sorted(papeis_anteriores)} if antes else None
        estado_depois = {**depois, "papeis": sorted(papeis_novos)}
        _evento(cursor, parceiro_id, "PARCEIRO_EDITADO" if antes else "PARCEIRO_CRIADO", estado_antes, estado_depois, usuario, perfil)
        if antes and antes.get("documento") != depois.get("documento"):
            _evento(cursor, parceiro_id, "DOCUMENTO_ALTERADO", estado_antes, estado_depois, usuario, perfil)
        for papel in sorted(adicionados):
            _evento(cursor, parceiro_id, "PAPEL_ADICIONADO", estado_antes, estado_depois, usuario, perfil, papel)
        for papel in sorted(removidos):
            _evento(cursor, parceiro_id, "PAPEL_REMOVIDO", estado_antes, estado_depois, usuario, perfil, papel)
        return parceiro_id


def alterar_status(parceiro_id, status, *, usuario=None, perfil=None):
    usuario, perfil = _identidade(usuario, perfil)
    if perfil not in PERFIS_STATUS:
        raise PermissionError("Somente Gerência ou Administrador pode alterar o status do parceiro.")
    if status not in {STATUS_ATIVO, STATUS_INATIVO}:
        raise ValueError("Status de parceiro inválido.")
    criar_tabelas_parceiros()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM parceiros WHERE id=?"), (parceiro_id,))
        registro = cursor.fetchone()
        if not registro:
            raise ValueError("Parceiro não encontrado.")
        antes = dict(registro)
        cursor.execute(q("UPDATE parceiros SET status=?,atualizado_por=?,atualizado_em=? WHERE id=?"), (status, usuario, _agora(), parceiro_id))
        cursor.execute(q("SELECT * FROM parceiros WHERE id=?"), (parceiro_id,))
        depois = dict(cursor.fetchone())
        _evento(cursor, parceiro_id, "PARCEIRO_ATIVADO" if status == STATUS_ATIVO else "PARCEIRO_INATIVADO", antes, depois, usuario, perfil)


def _anexar_papeis(cursor, registros):
    itens = [dict(item) for item in registros]
    if not itens:
        return itens
    ids = [item["id"] for item in itens]
    placeholders = ",".join("?" for _ in ids)
    cursor.execute(q(f"SELECT parceiro_id,papel FROM parceiro_papeis WHERE ativo=1 AND parceiro_id IN ({placeholders}) ORDER BY papel"), tuple(ids))
    mapa = {parceiro_id: [] for parceiro_id in ids}
    for linha in cursor.fetchall():
        mapa[linha["parceiro_id"]].append(linha["papel"])
    for item in itens:
        item["papeis"] = mapa[item["id"]]
        item["papeis_rotulos"] = [ROTULOS_PAPEIS[papel] for papel in item["papeis"]]
    return itens


def buscar_parceiro(parceiro_id):
    criar_tabelas_parceiros()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM parceiros WHERE id=?"), (parceiro_id,))
        itens = _anexar_papeis(cursor, cursor.fetchall())
        return itens[0] if itens else None
    finally:
        conn.close()


def listar_parceiros(busca="", status="Todos", tipo_pessoa="Todos", papel="Todos"):
    criar_tabelas_parceiros()
    filtros, parametros = [], []
    if status in {STATUS_ATIVO, STATUS_INATIVO}:
        filtros.append("p.status=?"); parametros.append(status)
    if tipo_pessoa in {"PF", "PJ"}:
        filtros.append("p.tipo_pessoa=?"); parametros.append(tipo_pessoa)
    if papel in PAPEIS_VALIDOS:
        filtros.append("EXISTS (SELECT 1 FROM parceiro_papeis pp WHERE pp.parceiro_id=p.id AND pp.papel=? AND pp.ativo=1)")
        parametros.append(papel)
    busca = str(busca or "").strip()
    if busca:
        termo, termo_original = f"%{busca.lower()}%", f"%{busca}%"
        filtros.append("""(
            LOWER(p.razao_social) LIKE ? OR p.razao_social LIKE ? OR
            LOWER(COALESCE(p.nome_fantasia,'')) LIKE ? OR COALESCE(p.nome_fantasia,'') LIKE ? OR
            p.documento LIKE ? OR LOWER(COALESCE(p.telefone,'')) LIKE ? OR
            LOWER(COALESCE(p.email,'')) LIKE ?
        )""")
        parametros.extend([termo, termo_original, termo, termo_original, termo, termo, termo])
    where = " WHERE " + " AND ".join(filtros) if filtros else ""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT p.* FROM parceiros p" + where + " ORDER BY p.razao_social,p.id"), tuple(parametros))
        return _anexar_papeis(cursor, cursor.fetchall())
    finally:
        conn.close()


def listar_parceiros_por_papel(papel, somente_ativos=True):
    """Fonte oficial de opções cadastrais para Cliente e Fornecedor."""
    if papel not in PAPEIS_VALIDOS:
        raise ValueError("Papel de parceiro inválido.")
    return listar_parceiros(
        status=STATUS_ATIVO if somente_ativos else "Todos",
        papel=papel,
    )


def listar_clientes_ativos():
    return listar_parceiros_por_papel(PAPEL_CLIENTE)


def listar_fornecedores_ativos():
    fornecedores = listar_parceiros_por_papel(PAPEL_FORNECEDOR)
    for fornecedor in fornecedores:
        fornecedor["nome"] = fornecedor["razao_social"]
    return fornecedores


def id_legado_do_parceiro(tipo_legado, parceiro_id):
    """Retorna o vínculo técnico legado, quando existe, sem torná-lo canônico."""
    tabela = {"CLIENTE": "clientes", "FORNECEDOR": "fornecedores"}.get(
        str(tipo_legado or "").upper()
    )
    if not tabela:
        raise ValueError("Tipo legado inválido.")
    criar_tabelas_parceiros()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q(f"SELECT id FROM {tabela} WHERE parceiro_id=? ORDER BY id LIMIT 1"),
                       (int(parceiro_id),))
        linha = cursor.fetchone()
        return int(linha["id"]) if linha else None
    finally:
        conn.close()


def snapshot_parceiro(parceiro):
    """Snapshot comercial imutável compatível com os documentos históricos."""
    return {
        "id": parceiro["id"], "razao_social": parceiro["razao_social"],
        "nome_fantasia": parceiro.get("nome_fantasia"),
        "documento": parceiro.get("documento"), "endereco": parceiro.get("endereco"),
        "complemento": parceiro.get("complemento"), "bairro": parceiro.get("bairro"),
        "cidade": parceiro.get("cidade"), "uf": parceiro.get("uf"),
    }


def obter_parceiro_por_papel(parceiro_id, papel, exigir_ativo=True):
    try:
        parceiro_id = int(parceiro_id or 0)
    except (TypeError, ValueError):
        parceiro_id = 0
    parceiro = buscar_parceiro(parceiro_id) if parceiro_id else None
    rotulo = ROTULOS_PAPEIS.get(papel, papel)
    if not parceiro or papel not in parceiro.get("papeis", []):
        raise ValueError(f"Selecione um parceiro com papel {rotulo}.")
    if exigir_ativo and parceiro["status"] != STATUS_ATIVO:
        raise ValueError(f"Selecione um parceiro {rotulo} ativo.")
    return parceiro


def resolver_parceiro_legado(tipo_legado, id_legado):
    """Resolve um ID legado sem alterar o documento histórico."""
    tabela = {"CLIENTE": "clientes", "FORNECEDOR": "fornecedores"}.get(
        str(tipo_legado or "").upper()
    )
    if not tabela:
        raise ValueError("Tipo legado inválido.")
    criar_tabelas_parceiros()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q(f"SELECT parceiro_id FROM {tabela} WHERE id=?"), (int(id_legado),))
        linha = cursor.fetchone()
        return buscar_parceiro(linha["parceiro_id"]) if linha and linha["parceiro_id"] else None
    finally:
        conn.close()


def _registrar_migracao(cursor, tipo, legado_id, parceiro_id, criado, papel_adicionado,
                        resultado, detalhes, executor, agora):
    valores = (parceiro_id, int(criado), int(papel_adicionado), resultado,
               _json(detalhes), executor, agora, tipo, legado_id)
    cursor.execute(q("""UPDATE parceiro_migracoes_legado SET parceiro_id=?,parceiro_criado=?,
        papel_adicionado=?,resultado=?,detalhes=?,executor=?,executado_em=?
        WHERE tipo_legado=? AND id_legado=?"""), valores)
    if cursor.rowcount == 0:
        cursor.execute(q("""INSERT INTO parceiro_migracoes_legado
            (tipo_legado,id_legado,parceiro_id,parceiro_criado,papel_adicionado,
             resultado,detalhes,executor,executado_em) VALUES (?,?,?,?,?,?,?,?,?)"""),
            (tipo, legado_id, parceiro_id, int(criado), int(papel_adicionado),
             resultado, _json(detalhes), executor, agora))


def _tabela_existe(cursor, tabela):
    if DATABASE_URL:
        cursor.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=%s", (tabela,))
    else:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,))
    return bool(cursor.fetchone())


def _candidatos_nome(cursor, nome):
    cursor.execute("SELECT id,razao_social,status FROM parceiros ORDER BY id")
    alvo = normalizar_nome(nome)
    return [dict(item) for item in cursor.fetchall()
            if normalizar_nome(item["razao_social"]) == alvo]


def _adicionar_papel_migracao(cursor, parceiro_id, papel, executor, agora):
    cursor.execute(q("SELECT id,ativo FROM parceiro_papeis WHERE parceiro_id=? AND papel=?"),
                   (parceiro_id, papel))
    existente = cursor.fetchone()
    if existente and int(existente["ativo"] or 0) == 1:
        return False
    if existente:
        cursor.execute(q("""UPDATE parceiro_papeis SET ativo=1,adicionado_por=?,adicionado_em=?,
            removido_por=NULL,removido_em=NULL WHERE id=?"""),
            (executor, agora, existente["id"]))
    else:
        cursor.execute(q("""INSERT INTO parceiro_papeis
            (parceiro_id,papel,ativo,adicionado_por,adicionado_em) VALUES (?,?,?,?,?)"""),
            (parceiro_id, papel, 1, executor, agora))
    return True


def migrar_clientes_fornecedores_legados(*, executor="P3.4 migration"):
    """Backfill aditivo, auditável e idempotente dos dois cadastros legados."""
    criar_tabelas_parceiros()
    agora = _agora()
    resumo = {"migrados": 0, "criados": 0, "reutilizados": 0,
              "ambiguos": 0, "conflitos": 0}
    with transaction() as conn:
        cursor = conn.cursor()
        fontes = (
            ("CLIENTE", "clientes", PAPEL_CLIENTE,
             "razao_social,nome_fantasia,tipo_pessoa,documento,telefone,endereco,complemento,bairro,cidade,uf,cep,observacoes,status"),
            ("FORNECEDOR", "fornecedores", PAPEL_FORNECEDOR,
             "nome,tipo_pessoa,documento,telefone,email,endereco,complemento,bairro,cidade,uf,cep,observacoes,status"),
        )
        for tipo, tabela, papel, colunas in fontes:
            if not _tabela_existe(cursor, tabela):
                continue
            cursor.execute(f"SELECT id,{colunas},parceiro_id FROM {tabela} ORDER BY id")
            for bruto in cursor.fetchall():
                legado = dict(bruto)
                legado_id = legado["id"]
                if legado.get("parceiro_id"):
                    _registrar_migracao(cursor, tipo, legado_id, legado["parceiro_id"],
                                        False, False, "JA_VINCULADO", {}, executor, agora)
                    resumo["reutilizados"] += 1
                    continue
                nome = legado.get("razao_social") or legado.get("nome")
                documento = normalizar_documento(legado.get("documento"))
                candidatos = []
                if documento:
                    cursor.execute(q("SELECT id,razao_social,status FROM parceiros WHERE documento=?"),
                                   (documento,))
                    candidatos = [dict(item) for item in cursor.fetchall()]
                if not candidatos:
                    candidatos = _candidatos_nome(cursor, nome)
                if len(candidatos) > 1:
                    _registrar_migracao(cursor, tipo, legado_id, None, False, False,
                                        "AMBIGUO", {"candidatos": [x["id"] for x in candidatos]},
                                        executor, agora)
                    resumo["ambiguos"] += 1
                    continue
                status_legado = legado.get("status") or STATUS_ATIVO
                criado = not candidatos
                if candidatos and candidatos[0]["status"] != status_legado:
                    _registrar_migracao(cursor, tipo, legado_id, candidatos[0]["id"], False,
                                        False, "CONFLITO_STATUS",
                                        {"legado": status_legado, "parceiro": candidatos[0]["status"]},
                                        executor, agora)
                    resumo["conflitos"] += 1
                    continue
                if candidatos:
                    parceiro_id = candidatos[0]["id"]
                    resumo["reutilizados"] += 1
                else:
                    dados = {
                        "tipo_pessoa": legado.get("tipo_pessoa") or "PJ",
                        "razao_social": nome,
                        "nome_fantasia": legado.get("nome_fantasia") or "",
                        "documento": documento,
                        "telefone": legado.get("telefone") or "",
                        "email": legado.get("email") or "", "endereco": legado.get("endereco") or "",
                        "complemento": legado.get("complemento") or "",
                        "bairro": legado.get("bairro") or "", "cidade": legado.get("cidade") or "",
                        "uf": legado.get("uf") or "", "cep": legado.get("cep") or "",
                        "observacoes": legado.get("observacoes") or "",
                    }
                    campos = tuple(dados.values())
                    sql = """INSERT INTO parceiros
                        (uuid,tipo_pessoa,razao_social,nome_fantasia,documento,telefone,email,
                         endereco,complemento,bairro,cidade,uf,cep,observacoes,status,criado_por,
                         atualizado_por,criado_em,atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
                    valores = (str(uuid4()),) + campos + (status_legado, executor, executor, agora, agora)
                    if DATABASE_URL:
                        cursor.execute(q(sql + " RETURNING id"), valores)
                        parceiro_id = cursor.fetchone()["id"]
                    else:
                        cursor.execute(q(sql), valores)
                        parceiro_id = cursor.lastrowid
                    resumo["criados"] += 1
                    _evento(cursor, parceiro_id, "PARCEIRO_CRIADO_POR_MIGRACAO", None,
                            {"tipo_legado": tipo, "id_legado": legado_id}, executor, "sistema")
                papel_adicionado = _adicionar_papel_migracao(
                    cursor, parceiro_id, papel, executor, agora)
                if papel_adicionado:
                    _evento(cursor, parceiro_id, "PAPEL_ADICIONADO_POR_MIGRACAO", None,
                            {"tipo_legado": tipo, "id_legado": legado_id}, executor, "sistema", papel)
                cursor.execute(q(f"UPDATE {tabela} SET parceiro_id=? WHERE id=?"),
                               (parceiro_id, legado_id))
                _registrar_migracao(cursor, tipo, legado_id, parceiro_id, criado,
                                    papel_adicionado, "MIGRADO", {}, executor, agora)
                resumo["migrados"] += 1
        # Chaves canônicas são preenchidas sem reescrever snapshots nem textos
        # históricos. A OP continua exibindo o fornecedor gravado à época.
        if _tabela_existe(cursor, "pedidos_venda") and _tabela_existe(cursor, "clientes"):
            cursor.execute("""UPDATE pedidos_venda SET cliente_parceiro_id=(
                SELECT c.parceiro_id FROM clientes c WHERE c.id=pedidos_venda.cliente_id)
                WHERE cliente_parceiro_id IS NULL AND cliente_id IS NOT NULL""")
        if _tabela_existe(cursor, "expedicoes") and _tabela_existe(cursor, "clientes"):
            cursor.execute("""UPDATE expedicoes SET cliente_parceiro_id=(
                SELECT c.parceiro_id FROM clientes c WHERE c.id=expedicoes.cliente_id)
                WHERE cliente_parceiro_id IS NULL AND cliente_id IS NOT NULL""")
        if _tabela_existe(cursor, "fornecedores") and _tabela_existe(cursor, "ordens_producao"):
            cursor.execute("SELECT id,nome,parceiro_id FROM fornecedores WHERE parceiro_id IS NOT NULL")
            fornecedores = [dict(item) for item in cursor.fetchall()]
            cursor.execute("SELECT id,fornecedor FROM ordens_producao WHERE fornecedor_parceiro_id IS NULL")
            for op in cursor.fetchall():
                correspondencias = [f for f in fornecedores
                                     if normalizar_nome(f["nome"]) == normalizar_nome(op["fornecedor"])]
                if len(correspondencias) == 1:
                    cursor.execute(q("UPDATE ordens_producao SET fornecedor_parceiro_id=? WHERE id=?"),
                                   (correspondencias[0]["parceiro_id"], op["id"]))
    return resumo


def listar_parceiros_elegiveis():
    criar_tabelas_parceiros()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT DISTINCT p.* FROM parceiros p
            JOIN parceiro_papeis pp ON pp.parceiro_id=p.id AND pp.ativo=1
            WHERE p.status=? AND pp.papel IN (?,?) ORDER BY p.razao_social,p.id"""),
            (STATUS_ATIVO, PAPEL_CLT, PAPEL_PRESTADOR))
        return _anexar_papeis(cursor, cursor.fetchall())
    finally:
        conn.close()


def obter_parceiro_elegivel(parceiro_id, natureza=None):
    parceiro = buscar_parceiro(int(parceiro_id or 0))
    if not parceiro or parceiro["status"] != STATUS_ATIVO:
        raise ValueError("Selecione um parceiro ativo elegível para Mão de Obra.")
    papeis = set(parceiro["papeis"]) & PAPEIS_TRABALHISTAS
    if not papeis:
        raise ValueError("O parceiro não possui papel de CLT ou Prestador de Serviços.")
    natureza = str(natureza or "").strip().upper()
    if not natureza and len(papeis) == 1:
        natureza = next(iter(papeis))
    if natureza not in papeis:
        raise ValueError("Selecione a natureza do vínculo válida para este parceiro.")
    return parceiro, natureza


def historico_parceiro(parceiro_id):
    criar_tabelas_parceiros()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM parceiro_eventos WHERE parceiro_id=? ORDER BY id DESC"), (parceiro_id,))
        return cursor.fetchall()
    finally:
        conn.close()
