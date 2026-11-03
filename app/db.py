"""Acceso a PostgreSQL + pgvector."""
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

from . import config

_pool: ConnectionPool | None = None


def _configurar(conn: psycopg.Connection) -> None:
    # La extensión debe existir antes de registrar el tipo vector en el driver.
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
    except psycopg.Error:
        conn.rollback()          # otra conexión la creó al mismo tiempo
    register_vector(conn)


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            config.DATABASE_URL, min_size=1, max_size=8,
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=_configurar, open=True,
        )
    return _pool


@contextmanager
def conexion():
    with pool().connection() as conn:
        yield conn


def consultar(sql: str, params=None) -> list[dict]:
    with conexion() as conn:
        return conn.execute(sql, params).fetchall()


def uno(sql: str, params=None) -> dict | None:
    with conexion() as conn:
        return conn.execute(sql, params).fetchone()


def ejecutar(sql: str, params=None) -> None:
    with conexion() as conn:
        conn.execute(sql, params)


def cerrar() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
