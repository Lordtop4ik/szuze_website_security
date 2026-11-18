from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3

import pytest

from shop_api import prepare_database

CATALOG = Path(__file__).resolve().parents[1] / 'site/catalog.js'


@pytest.fixture
def legacy_connection(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                'CREATE TABLE orders(id INTEGER PRIMARY KEY, request_id TEXT UNIQUE, '
                'payload TEXT NOT NULL, total_kopecks INTEGER NOT NULL)'
            )
            conn.execute("INSERT INTO orders VALUES(1,'old','[]',100)")
        yield conn


def test_database_migration_preserves_legacy_order(db_path, legacy_connection):
    prepare_database(db_path, CATALOG)
    prepare_database(db_path, CATALOG)
    row = legacy_connection.execute('SELECT id,total_kopecks,user_id FROM orders').fetchone()
    assert row == (1, 100, None)


def test_database_stores_argon2id_password_hash(signed_in_client, db_connection):
    stored = db_connection.execute('SELECT password_hash FROM users').fetchone()[0]
    assert stored.startswith('$argon2id$')


def test_database_stores_session_token_hash(signed_in_client, db_connection):
    stored = db_connection.execute('SELECT token_hash FROM sessions').fetchone()[0]
    cookie = signed_in_client.cookies['session']
    assert stored == hashlib.sha256(cookie.encode()).hexdigest()
