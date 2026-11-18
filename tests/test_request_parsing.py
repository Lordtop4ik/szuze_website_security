import pytest


@pytest.mark.parametrize('content,content_type,status,error', [
    (b'{}', 'text/plain', 415, 'Требуется Content-Type: application/json.'),
    (b'{', 'application/json', 400, 'Некорректный JSON.'),
    (b'[]', 'application/json', 400, 'Требуется объект JSON.'),
    (b'x' * 32769, 'application/json', 413, 'Недопустимый размер запроса.'),
    (b'x' * 32769, 'text/plain', 413, 'Недопустимый размер запроса.'),
])
def test_order_reports_body_errors(shop_client, content, content_type, status, error):
    response = shop_client.post('/api/orders', content=content, headers={'Content-Type': content_type})
    assert response.status_code == status
    assert response.json() == {'error': error}


def test_order_checks_csrf_before_body(signed_in_client):
    response = signed_in_client.post('/api/orders', content=b'{')
    assert response.status_code == 403


def test_product_checks_path_before_body(client):
    response = client.put('/api/products/INVALID', content=b'{')
    assert response.status_code == 404


def test_product_checks_body_before_admin_token(client, admin_token):
    response = client.put('/api/products/duck', content=b'{', headers={'Content-Type': 'application/json'})
    assert response.status_code == 400


@pytest.mark.parametrize('content_type,status,error', [
    ('application/json', 415, 'Требуется HTML-форма.'),
    ('application/x-www-form-urlencoded', 400, 'Некорректная форма.'),
])
def test_form_reports_body_errors_before_csrf(client, content_type, status, error):
    response = client.post('/login', content=b'\xff', headers={'Content-Type': content_type})
    assert response.status_code == status
    assert response.json() == {'error': error}
