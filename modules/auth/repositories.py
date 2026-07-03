"""Persistência de usuários para autenticação."""

from werkzeug.security import generate_password_hash

from database import conectar, q


def buscar_usuario_por_email(email):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM usuarios
    WHERE email = ?
    """), (email,))

    usuario = cursor.fetchone()
    conn.close()

    return usuario


def inserir_usuario(nome, email, senha, perfil):
    senha_hash = generate_password_hash(senha)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO usuarios (
        nome,
        email,
        senha_hash,
        perfil
    )
    VALUES (?, ?, ?, ?)
    """), (
        nome,
        email,
        senha_hash,
        perfil
    ))

    conn.commit()
    conn.close()
