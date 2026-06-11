import os
import sqlite3
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras


DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "abatedouro.db")


def q(sql):
    if DATABASE_URL:
        return sql.replace("?", "%s")
    return sql


def conectar():
    if DATABASE_URL:
        result = urlparse(DATABASE_URL)
        return psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port,
            cursor_factory=psycopg2.extras.RealDictCursor
        )

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn
