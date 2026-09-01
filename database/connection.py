"""Conexões e helpers transacionais do banco de dados."""

from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import sqlite3
import time
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras


DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "abatedouro.db")
_metricas_sql = ContextVar("metricas_sql", default=None)


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


def q(sql):
    if DATABASE_URL:
        return sql.replace("?", "%s")

    return sql


def get_connection():
    if DATABASE_URL:
        result = urlparse(DATABASE_URL)
        inicio = time.perf_counter()
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port,
            cursor_factory=CursorPostgresInstrumentado,
        )
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
