from pathlib import Path
import os
import socket
import subprocess
import sys
import time
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

@pytest.fixture(scope='session')
def live_server(tmp_path_factory):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, HOST='127.0.0.1', PORT=str(port), SHOP_DB=str(tmp_path_factory.mktemp('db')/'test.sqlite3'), COOKIE_SECURE='0')
    with (tmp_path_factory.mktemp('logs')/'server.log').open('w+') as log:
        server = subprocess.Popen([sys.executable, 'main.py'], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            url = f'http://127.0.0.1:{port}'
            for _ in range(100):
                if server.poll() is not None:
                    log.seek(0)
                    pytest.fail(log.read())
                try:
                    if httpx.get(url, timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                pytest.fail('Server readiness timeout')
            yield url
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
