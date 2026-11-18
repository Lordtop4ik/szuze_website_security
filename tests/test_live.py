import pytest


@pytest.mark.parametrize('path, content_type', [
    ('/', 'text/html'),
    ('/login', 'text/html'),
    ('/register', 'text/html'),
    ('/styles.css', 'text/css'),
    ('/app.js', 'javascript'),
    ('/assets/shop.svg', 'image/svg+xml'),
    ('/products.json', 'application/json'),
])
def test_live_resource(live_client, path, content_type):
    response = live_client.get(path)
    assert response.status_code == 200
    assert content_type in response.headers['Content-Type']
    assert response.content


def test_registration_page_contains_password_field(live_client):
    assert 'name="password"' in live_client.get('/register').text


@pytest.mark.parametrize('path', [
    '/absent.txt', '/README.md', '/Main.java', '/Program.cs', '/main.go',
    '/NuGet.Config', '/main.py', '/auth_service.py', '/api_docs.py', '/data/shop.sqlite3',
])
def test_live_server_does_not_expose_private_files(live_client, path):
    assert live_client.get(path).status_code == 404


def test_live_server_serves_updated_file(live_client, live_project):
    path = live_project / 'site/version.txt'
    try:
        path.write_bytes(b'version1')
        assert live_client.get('/version.txt').content == b'version1'
        path.write_bytes(b'version2')
        assert live_client.get('/version.txt').content == b'version2'
    finally:
        path.unlink(missing_ok=True)
