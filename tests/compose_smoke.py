"""CI check against a running Compose stack; recreates its web container."""
import os
import secrets
import subprocess

import httpx


def main():
    port = os.environ.get('HOST_PORT', '8000')
    with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10) as client:
        for path in ('/', '/login', '/register'):
            assert client.get(path).status_code == 200, path
        csrf = client.get('/api/auth/me').json()['csrf']
        username = 'smoke_' + secrets.token_hex(6)
        response = client.post('/register', data={
            'username': username, 'password': secrets.token_urlsafe(20), 'csrf': csrf,
        })
        assert response.status_code == 303, response.text
        identity = client.get('/api/auth/me').json()
        assert identity['user']['username'] == username
        order = {'items': [{'productId': 'duck', 'quantity': 1}], 'requestId': secrets.token_hex(16)}
        headers = {'X-CSRF-Token': identity['csrf']}
        created = client.post('/api/orders', json=order, headers=headers)
        assert created.status_code == 201, created.text
        stock = next(p['stock'] for p in client.get('/api/products').json() if p['id'] == 'duck')

        subprocess.run(['docker', 'compose', 'up', '-d', '--force-recreate', '--wait',
                        '--wait-timeout', '60'], check=True, timeout=120)

        assert client.get('/api/auth/me').json() == identity
        repeated = client.post('/api/orders', json=order, headers=headers)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == created.json()
        assert next(p['stock'] for p in client.get('/api/products').json() if p['id'] == 'duck') == stock
        uid = subprocess.check_output(['docker', 'compose', 'exec', '-T', 'web',
                                      'python', '-c', 'import os; print(os.getuid())'], text=True, timeout=15)
        assert uid.strip() == '65532', uid
    print('PASS Compose: pages, non-root user, persistent account/session/order/stock after recreation')


if __name__ == '__main__':
    main()
