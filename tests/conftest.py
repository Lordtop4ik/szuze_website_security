from contextlib import closing, contextmanager
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from shop_api import connect
from webapp import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / 'shop.sqlite3'


@pytest.fixture
def app(db_path):
    return create_app(db_path, cookie_secure=False)


@pytest.fixture
def client(app):
    # Startup initializes the isolated database and its catalog.
    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def register_account():
    def register(client, username='alice', password='password123', **fields):
        csrf = client.get('/api/auth/me').json()['csrf']
        return client.post('/register', data={
            'username': username, 'password': password, 'csrf': csrf, **fields,
        })

    return register


@pytest.fixture
def signed_in_client(client, register_account):
    assert register_account(client).status_code == 303
    return client


@pytest.fixture
def signed_in_csrf(signed_in_client):
    return signed_in_client.get('/api/auth/me').json()['csrf']


@pytest.fixture
def db_connection(client, db_path):
    with closing(connect(db_path)) as conn:
        yield conn


@pytest.fixture
def expired_client(signed_in_client, signed_in_csrf, db_connection):
    with db_connection:
        db_connection.execute('UPDATE sessions SET expires=0')
    return signed_in_client


@pytest.fixture
def admin_token(monkeypatch):
    token = 'test-only'
    monkeypatch.setenv('SHOP_ADMIN_TOKEN', token)
    return token


@pytest.fixture
def shop_client(signed_in_client, signed_in_csrf, admin_token):
    signed_in_client.headers['X-CSRF-Token'] = signed_in_csrf
    return signed_in_client


@pytest.fixture
def reopen_shop(db_path):
    @contextmanager
    def reopen():
        with TestClient(create_app(db_path, cookie_secure=False), follow_redirects=False) as client:
            data = client.get('/api/auth/me').json()
            response = client.post('/login', data={
                'username': 'alice', 'password': 'password123', 'csrf': data['csrf'],
            })
            assert response.status_code == 303
            client.headers['X-CSRF-Token'] = client.get('/api/auth/me').json()['csrf']
            yield client

    return reopen


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_for_server(process, url, log):
    for _ in range(100):
        if process.poll() is not None:
            break
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    log.seek(0)
    pytest.fail(f'Uvicorn did not become ready (exit code {process.poll()}):\n{log.read()}')


def stop_server(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture(scope='session')
def live_project(tmp_path_factory):
    project = tmp_path_factory.mktemp('live-project')
    for module in ('main.py', 'webapp.py', 'shop_api.py', 'auth_service.py', 'api_docs.py'):
        shutil.copy2(ROOT / module, project)
    for directory in ('site', 'templates'):
        shutil.copytree(ROOT / directory, project / directory)
    (project / 'site/products.json').write_text('[]', encoding='utf-8')
    return project


@pytest.fixture(scope='session')
def live_server(live_project):
    port = free_port()
    url = f'http://127.0.0.1:{port}'
    env = dict(os.environ, HOST='127.0.0.1', PORT=str(port),
               SHOP_DB=str(live_project / 'data/shop.sqlite3'), COOKIE_SECURE='0')
    with (live_project / 'server.log').open('w+', encoding='utf-8', errors='replace') as log:
        process = subprocess.Popen(
            [sys.executable, 'main.py'], cwd=live_project, env=env, stdout=log, stderr=log,
        )
        try:
            wait_for_server(process, url, log)
            yield url
        finally:
            stop_server(process)


@pytest.fixture
def live_client(live_server):
    with httpx.Client(base_url=live_server) as client:
        yield client


@pytest.fixture
def pack_project(tmp_path):
    shutil.copytree(ROOT / 'site', tmp_path / 'site')
    return tmp_path


@pytest.fixture
def pack_cli(pack_project):
    def run(*, env=None):
        return subprocess.run(
            [sys.executable, '-S', str(ROOT / 'main.py'), '--pack'],
            cwd=pack_project, env=env, capture_output=True, timeout=30,
        )

    return run


@pytest.fixture
def published_zip(pack_project, pack_cli):
    result = pack_cli()
    assert result.returncode == 0, result.stderr
    return pack_project / 'shop.zip'
