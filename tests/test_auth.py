from contextlib import closing
import sqlite3

import httpx
from fastapi.testclient import TestClient
from webapp import create_app
from shop_api import connect, prepare_database
from pathlib import Path


def register(client, username='alice'):
    csrf = client.get('/api/auth/me').json()['csrf']
    return client.post('/register', data={'username':username,'password':'password123','csrf':csrf}, follow_redirects=False)


def test_live_pages(live_server):
    with httpx.Client(base_url=live_server) as client:
        for path in ('/', '/login', '/register'):
            response = client.get(path)
            assert response.status_code == 200
        assert 'name="password"' in response.text
        assert client.get('/main.py').status_code == 404
        assert client.get('/data/shop.sqlite3').status_code == 404
        assert client.post('/api/orders', json={}).status_code == 401


def test_sessions_orders_and_csrf(tmp_path):
    db = tmp_path/'shop.sqlite3'
    app = create_app(db, cookie_secure=False)
    with TestClient(app) as client:
        assert client.post('/register', data={'username':'alice'}).status_code == 403
        assert register(client).status_code == 303
        old_cookie = client.cookies['session']
        me = client.get('/api/auth/me').json()
        assert me['user']['username'] == 'alice'
        order = {'items':[{'productId':'duck','quantity':1}], 'requestId':'same-order'}
        assert client.post('/api/orders', json=order).status_code == 403
        headers = {'X-CSRF-Token':me['csrf']}
        first = client.post('/api/orders', json=order, headers=headers)
        assert first.status_code == 201
        assert client.post('/api/orders', json=order, headers=headers).json() == first.json()
        response = client.post('/logout', data={'csrf':me['csrf']}, follow_redirects=False)
        assert response.status_code == 303
        client.cookies.clear()
        client.cookies.set('session', old_cookie, domain='testserver.local', path='/')
        assert client.get('/api/auth/me').json()['user'] is None
        assert register(client, 'bob').status_code == 303
        assert client.post('/api/orders', json=order, headers={'X-CSRF-Token':client.get('/api/auth/me').json()['csrf']}).status_code == 409
        with closing(connect(db)) as conn, conn:
            row = conn.execute('SELECT * FROM users WHERE username="alice"').fetchone()
            assert row['password_hash'].startswith('$argon2id$')
            assert conn.execute('SELECT token_hash FROM sessions').fetchone()[0] != client.cookies['session']
            conn.execute('UPDATE sessions SET expires=0')
        assert client.post('/api/orders', json=order, headers=headers).status_code == 401
        csrf = client.get('/api/auth/me').json()['csrf']
        assert client.post('/login', data={'username':'alice','password':'wrongpass','csrf':csrf}).status_code == 401
        response = client.post('/login', data={'username':'ALICE','password':'password123','csrf':csrf,'next':'checkout'}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == '/?view=checkout'
        assert register(client).status_code == 409
        csrf = client.get('/api/auth/me').json()['csrf']
        assert client.post('/register', data={'username':'x','password':'short','csrf':csrf}).status_code == 422
        assert client.post('/api/orders', content=b'x'*32769, headers={'X-CSRF-Token':csrf,'Content-Type':'application/json'}).status_code == 413


def test_existing_database_migration(tmp_path):
    db = tmp_path/'legacy.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE orders(id INTEGER PRIMARY KEY, request_id TEXT UNIQUE, payload TEXT NOT NULL, total_kopecks INTEGER NOT NULL)')
        conn.execute("INSERT INTO orders VALUES(1,'old','[]',100)")
    catalog = Path(__file__).resolve().parents[1]/'site/catalog.js'
    prepare_database(db, catalog)
    prepare_database(db, catalog)
    with closing(connect(db)) as conn:
        assert tuple(conn.execute('SELECT id,total_kopecks,user_id FROM orders').fetchone()) == (1,100,None)
