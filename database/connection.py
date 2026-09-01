"""Conexões e helpers transacionais do banco de dados."""

from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import sqlite3
from threading import Lock
import time
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import psycopg2.pool


DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "abatedouro.db")
_metricas_sql = ContextVar("metricas_sql", default=None)
_pool_postgres = None
_pool_lock = Lock()


def iniciar_metricas_sql():
    metricas = {
        "sql_count": 0, "sql_ms": 0.0, "slowest_sql_ms": 0.0,
        "slowest_sql": None, "connections": 0, "connection_ms": 0.0,
    }
    _metricas_sql.set(metricas)
    return metricas


def finalizar_metricas_sql():
    metricas = _metricas_sql.get()
    _metricas_sql.set(None)
    return dict(metricas or {})


def _rotulo_sql(sql):
    texto = re.sub(r"\s+", " ", str(sql or "")).strip()
    return texto[:180]


def _registrar_sql(sql, duracao_ms):
    metricas = _metricas_sql.get()
    if metricas is None:
        return
    metricas["sql_count"] += 1
    metricas["sql_ms"] += duracao_ms
    if duracao_ms > metricas["slowest_sql_ms"]:
        metricas["slowest_sql_ms"] = duracao_ms
        metricas["slowest_sql"] = _rotulo_sql(sql)


def _registrar_conexao(duracao_ms):
    metricas = _metricas_sql.get()
    if metricas is not None:
        metricas["connections"] += 1
        metricas["connection_ms"] += duracao_ms


class CursorPostgresInstrumentado(psycopg2.extras.RealDictCursor):
    def execute(self, query, vars=None):
        inicio = time.perf_counter()
        try:
            return super().execute(query, vars)
        finally:
            _registrar_sql(query, (time.perf_counter() - inicio) * 1000)

    def executemany(self, query, vars_list):
        inicio = time.perf_counter()
        try:
            return super().executemany(query, vars_list)
        finally:
            _registrar_sql(query, (time.perf_counter() - inicio) * 1000)


class CursorSQLiteInstrumentado(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        inicio = time.perf_counter()
        try:
            return super().execute(sql, parameters)
        finally:
            _registrar_sql(sql, (time.perf_counter() - inicio) * 1000)

    def executemany(self, sql, seq_of_parameters):
        inicio = time.perf_counter()
        try:
            return super().executemany(sql, seq_of_parameters)
        finally:
            _registrar_sql(sql, (time.perf_counter() - inicio) * 1000)


class ConexaoSQLiteInstrumentada(sqlite3.Connection):
    def cursor(self, factory=CursorSQLiteInstrumentado):
        return super().cursor(factory)


class ConexaoPostgresPool:
    """Proxy que devolve a conexão ao pool quando o código legado chama close()."""

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._devolvida = False

    def __getattr__(self, nome):
        return getattr(self._conn, nome)

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traceback):
        if tipo is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False

    def close(self):
        if self._devolvida:
            return
        try:
            self._conn.rollback()
        finally:
            self._pool.putconn(self._conn)
            self._devolvida = True


def _obter_pool_postgres():
    global _pool_postgres
    if _pool_postgres is None:
        with _pool_lock:
            if _pool_postgres is None:
                result = urlparse(DATABASE_URL)
                _pool_postgres = psycopg2.pool.ThreadedConnectionPool(
                    1,
                    max(1, int(os.getenv("DB_POOL_MAX", "5"))),
                    database=result.path[1:],
                    user=result.username,
                    password=result.password,
                    host=result.hostname,
                    port=result.port,
                    cursor_factory=CursorPostgresInstrumentado,
                )
    return _pool_postgres


def q(sql):
    if DATABASE_URL:
        return sql.replace("?", "%s")

    return sql


def get_connection():
    if DATABASE_URL:
        inicio = time.perf_counter()
        pool = _obter_pool_postgres()
        conn = ConexaoPostgresPool(pool.getconn(), pool)
        _registrar_conexao((time.perf_counter() - inicio) * 1000)
        return conn

    inicio = time.perf_counter()
    conn = sqlite3.connect(DB_NAME, factory=ConexaoSQLiteInstrumentada)
    conn.row_factory = sqlite3.Row
    _registrar_conexao((time.perf_counter() - inicio) * 1000)
    return conn


def conectar():
    return get_connection()


@contextmanager
def transaction():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
