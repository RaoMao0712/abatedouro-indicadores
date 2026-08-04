"""Cadastro simples, auditável e sem acoplamento financeiro de clientes."""

from datetime import datetime
import json
import re

from flask import has_request_context, session

from database import DATABASE_URL, conectar, q, transaction


STATUS_ATIVO = "Ativo"
STATUS_INATIVO = "Inativo"
PERFIS_CONSULTA = {"admin", "gerencia", "pcp", "expedicao"}
PERFIS_EDICAO = {"admin", "gerencia", "pcp"}
PERFIS_STATUS = {"admin", "gerencia"}


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _identidade(usuario=None, perfil=None):
    if has_request_context():
        usuario = usuario or session.get("nome")
        perfil = perfil or session.get("perfil")
    return usuario or "Sistema", (perfil or "sistema").lower()


def _alterar(cursor, postgres, sqlite):
    try:
        cursor.execute(postgres if DATABASE_URL else sqlite)
    except Exception:
        if DATABASE_URL:
            raise


def criar_tabelas_clientes():
    conn = conectar()
    cursor = conn.cursor()
    id_pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp = "TIMESTAMP" if DATABASE_URL else "TEXT"
    try:
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS clientes (
            id {id_pk}, razao_social TEXT NOT NULL, nome_fantasia TEXT,
            tipo_pessoa TEXT NOT NULL, documento TEXT, telefone TEXT,
            endereco TEXT, complemento TEXT, bairro TEXT, cidade TEXT,
            uf TEXT, cep TEXT, observacoes TEXT, status TEXT NOT NULL DEFAULT 'Ativo',
            criado_por TEXT NOT NULL, atualizado_por TEXT NOT NULL,
            criado_em {timestamp} NOT NULL, atualizado_em {timestamp} NOT NULL
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS cliente_eventos (
            id {id_pk}, cliente_id INTEGER NOT NULL, acao TEXT NOT NULL,
            dados_anteriores TEXT, dados_novos TEXT, usuario TEXT NOT NULL,
            perfil TEXT NOT NULL, criado_em {timestamp} NOT NULL
        )
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_clientes_documento ON clientes(documento) WHERE documento IS NOT NULL")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_clientes_busca ON clientes(status,razao_social,cidade)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cliente_eventos ON cliente_eventos(cliente_id,criado_em)")
        for coluna in (
            "tipo_saida TEXT", "cliente_id INTEGER", "cliente_snapshot TEXT",
            "veiculo TEXT", "motorista TEXT",
        ):
            _alterar(cursor, f"ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS {coluna}",
                     f"ALTER TABLE expedicoes ADD COLUMN {coluna}")
        cursor.execute("""UPDATE expedicoes SET tipo_saida='TRANSFERENCIA_LSM'
            WHERE tipo_saida IS NULL AND tipo_movimentacao='TRANSFERENCIA'""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expedicoes_tipo_saida ON expedicoes(tipo_saida,status,data)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expedicoes_cliente ON expedicoes(cliente_id,data)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def normalizar_documento(valor):
    documento = re.sub(r"\D", "", str(valor or ""))
    return documento or None


def _digitos_cpf(base):
    soma = sum(int(numero) * peso for numero, peso in zip(base, range(len(base) + 1, 1, -1)))
    resto = (soma * 10) % 11
    return "0" if resto == 10 else str(resto)


def cpf_valido(documento):
    if len(documento) != 11 or documento == documento[0] * 11:
        return False
    primeiro = _digitos_cpf(documento[:9])
    segundo = _digitos_cpf(documento[:9] + primeiro)
    return documento[-2:] == primeiro + segundo


def _digito_cnpj(base, pesos):
    resto = sum(int(numero) * peso for numero, peso in zip(base, pesos)) % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(documento):
    if len(documento) != 14 or documento == documento[0] * 14:
        return False
    primeiro = _digito_cnpj(documento[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    segundo = _digito_cnpj(documento[:12] + primeiro, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return documento[-2:] == primeiro + segundo


def validar_documento(tipo_pessoa, documento):
    documento = normalizar_documento(documento)
    if not documento:
        return None
    valido = cpf_valido(documento) if tipo_pessoa == "PF" else cnpj_valido(documento)
    if not valido:
        raise ValueError("CPF/CNPJ inválido.")
    return documento


def _dados_form(form):
    razao = str(form.get("razao_social") or "").strip()
    tipo = str(form.get("tipo_pessoa") or "").upper().strip()
    if not razao:
        raise ValueError("Nome ou razão social é obrigatório.")
    if tipo not in {"PF", "PJ"}:
        raise ValueError("Tipo de pessoa deve ser Física ou Jurídica.")
    return {
        "razao_social": razao,
        "nome_fantasia": str(form.get("nome_fantasia") or "").strip(),
        "tipo_pessoa": tipo,
        "documento": validar_documento(tipo, form.get("documento")),
        "telefone": str(form.get("telefone") or "").strip(),
        "endereco": str(form.get("endereco") or "").strip(),
        "complemento": str(form.get("complemento") or "").strip(),
        "bairro": str(form.get("bairro") or "").strip(),
        "cidade": str(form.get("cidade") or "").strip(),
        "uf": str(form.get("uf") or "").strip().upper()[:2],
        "cep": re.sub(r"\D", "", str(form.get("cep") or ""))[:8],
        "observacoes": str(form.get("observacoes") or "").strip(),
    }


def _evento(cursor, cliente_id, acao, antes, depois, usuario, perfil):
    cursor.execute(q("""INSERT INTO cliente_eventos
        (cliente_id,acao,dados_anteriores,dados_novos,usuario,perfil,criado_em)
        VALUES (?,?,?,?,?,?,?)"""), (
            cliente_id, acao,
            json.dumps(antes, ensure_ascii=False, sort_keys=True, default=str) if antes else None,
            json.dumps(depois, ensure_ascii=False, sort_keys=True, default=str) if depois else None,
            usuario, perfil, _agora(),
        ))


def salvar_cliente(form, cliente_id=None, *, usuario=None, perfil=None):
    usuario, perfil = _identidade(usuario, perfil)
    if perfil not in PERFIS_EDICAO:
        if cliente_id:
            criar_tabelas_clientes()
            with transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(q("SELECT * FROM clientes WHERE id=?"), (cliente_id,))
                registro = cursor.fetchone()
                if registro:
                    _evento(cursor, cliente_id, "TENTATIVA_EDICAO_NEGADA", dict(registro),
                            None, usuario, perfil)
        raise PermissionError("Perfil sem permissão para alterar clientes.")
    criar_tabelas_clientes()
    dados = _dados_form(form)
    agora = _agora()
    with transaction() as conn:
        cursor = conn.cursor()
        antes = None
        if cliente_id:
            cursor.execute(q("SELECT * FROM clientes WHERE id=?"), (cliente_id,))
            registro = cursor.fetchone()
            if not registro:
                raise ValueError("Cliente não encontrado.")
            antes = dict(registro)
        if dados["documento"]:
            cursor.execute(q("SELECT id FROM clientes WHERE documento=? AND id<>?"),
                           (dados["documento"], int(cliente_id or 0)))
            if cursor.fetchone():
                raise ValueError("CPF/CNPJ já cadastrado.")
        campos = tuple(dados.values())
        if cliente_id:
            cursor.execute(q("""UPDATE clientes SET razao_social=?,nome_fantasia=?,tipo_pessoa=?,
                documento=?,telefone=?,endereco=?,complemento=?,bairro=?,cidade=?,uf=?,cep=?,
                observacoes=?,atualizado_por=?,atualizado_em=? WHERE id=?"""),
                campos + (usuario, agora, cliente_id))
        else:
            if DATABASE_URL:
                cursor.execute(q("""INSERT INTO clientes (razao_social,nome_fantasia,tipo_pessoa,
                    documento,telefone,endereco,complemento,bairro,cidade,uf,cep,observacoes,status,
                    criado_por,atualizado_por,criado_em,atualizado_em)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id"""),
                    campos + (STATUS_ATIVO, usuario, usuario, agora, agora))
                cliente_id = cursor.fetchone()["id"]
            else:
                cursor.execute(q("""INSERT INTO clientes (razao_social,nome_fantasia,tipo_pessoa,
                    documento,telefone,endereco,complemento,bairro,cidade,uf,cep,observacoes,status,
                    criado_por,atualizado_por,criado_em,atualizado_em)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
                    campos + (STATUS_ATIVO, usuario, usuario, agora, agora))
                cliente_id = cursor.lastrowid
        cursor.execute(q("SELECT * FROM clientes WHERE id=?"), (cliente_id,))
        depois = dict(cursor.fetchone())
        _evento(cursor, cliente_id, "CLIENTE_EDITADO" if antes else "CLIENTE_CRIADO",
                antes, depois, usuario, perfil)
        return cliente_id


def alterar_status(cliente_id, status, *, usuario=None, perfil=None):
    usuario, perfil = _identidade(usuario, perfil)
    if perfil not in PERFIS_STATUS:
        criar_tabelas_clientes()
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(q("SELECT * FROM clientes WHERE id=?"), (cliente_id,))
            registro = cursor.fetchone()
            if registro:
                _evento(cursor, cliente_id, "TENTATIVA_STATUS_NEGADA", dict(registro),
                        {"status_solicitado": status}, usuario, perfil)
        raise PermissionError("Somente Gerência ou Administrador pode alterar o status do cliente.")
    if status not in {STATUS_ATIVO, STATUS_INATIVO}:
        raise ValueError("Status de cliente inválido.")
    criar_tabelas_clientes()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM clientes WHERE id=?"), (cliente_id,))
        registro = cursor.fetchone()
        if not registro:
            raise ValueError("Cliente não encontrado.")
        antes = dict(registro)
        cursor.execute(q("UPDATE clientes SET status=?,atualizado_por=?,atualizado_em=? WHERE id=?"),
                       (status, usuario, _agora(), cliente_id))
        cursor.execute(q("SELECT * FROM clientes WHERE id=?"), (cliente_id,))
        depois = dict(cursor.fetchone())
        _evento(cursor, cliente_id, "CLIENTE_ATIVADO" if status == STATUS_ATIVO else "CLIENTE_INATIVADO",
                antes, depois, usuario, perfil)


def buscar_cliente(cliente_id):
    criar_tabelas_clientes()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM clientes WHERE id=?"), (cliente_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def listar_clientes(busca="", status="Todos", somente_ativos=False):
    criar_tabelas_clientes()
    filtros, parametros = [], []
    if somente_ativos:
        filtros.append("status='Ativo'")
    elif status in {STATUS_ATIVO, STATUS_INATIVO}:
        filtros.append("status=?")
        parametros.append(status)
    if busca:
        termo = f"%{busca.strip()}%"
        filtros.append("(razao_social LIKE ? OR nome_fantasia LIKE ? OR documento LIKE ? OR cidade LIKE ?)")
        parametros.extend([termo] * 4)
    where = " WHERE " + " AND ".join(filtros) if filtros else ""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM clientes" + where + " ORDER BY razao_social,id"), tuple(parametros))
        return cursor.fetchall()
    finally:
        conn.close()


def historico_cliente(cliente_id):
    criar_tabelas_clientes()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM cliente_eventos WHERE cliente_id=? ORDER BY id DESC"), (cliente_id,))
        return cursor.fetchall()
    finally:
        conn.close()


def snapshot_cliente(registro):
    return json.dumps({
        "id": registro["id"], "razao_social": registro["razao_social"],
        "nome_fantasia": registro["nome_fantasia"], "documento": registro["documento"],
        "endereco": registro["endereco"], "complemento": registro["complemento"],
        "bairro": registro["bairro"], "cidade": registro["cidade"], "uf": registro["uf"],
    }, ensure_ascii=False, sort_keys=True)
