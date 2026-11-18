import pytest


@pytest.fixture
def order_data():
    return {'items': [{'productId': 'duck', 'quantity': 1}], 'requestId': 'same-order'}


def test_registration_requires_csrf(client):
    assert client.post('/register', data={'username': 'alice'}).status_code == 403


def test_registration_starts_authenticated_session(client, register_account):
    assert register_account(client).status_code == 303
    assert client.get('/api/auth/me').json()['user']['username'] == 'alice'


def test_guest_cannot_place_order(live_client, order_data):
    assert live_client.post('/api/orders', json=order_data).status_code == 401


def test_order_requires_csrf(signed_in_client, order_data):
    assert signed_in_client.post('/api/orders', json=order_data).status_code == 403


def test_logout_revokes_session(signed_in_client, signed_in_csrf):
    client = signed_in_client
    previous_cookie = client.cookies['session']

    assert client.post('/logout', data={'csrf': signed_in_csrf}).status_code == 303

    client.cookies.set('session', previous_cookie, domain='testserver.local', path='/')
    assert client.get('/api/auth/me').json()['user'] is None


def test_other_account_cannot_repeat_order(signed_in_client, signed_in_csrf, register_account, order_data):
    client = signed_in_client
    first = client.post('/api/orders', json=order_data, headers={'X-CSRF-Token': signed_in_csrf})
    assert first.status_code == 201
    assert register_account(client, username='bob').status_code == 303
    csrf = client.get('/api/auth/me').json()['csrf']

    response = client.post('/api/orders', json=order_data, headers={'X-CSRF-Token': csrf})
    assert response.status_code == 409


def test_expired_session_cannot_place_order(expired_client, signed_in_csrf, order_data):
    response = expired_client.post('/api/orders', json=order_data, headers={'X-CSRF-Token': signed_in_csrf})
    assert response.status_code == 401


def test_login_rejects_wrong_password(signed_in_client, signed_in_csrf):
    response = signed_in_client.post('/login', data={
        'username': 'alice', 'password': 'wrongpass', 'csrf': signed_in_csrf,
    })
    assert response.status_code == 401


def test_login_normalizes_username_and_returns_to_checkout(signed_in_client, signed_in_csrf):
    assert signed_in_client.post('/logout', data={'csrf': signed_in_csrf}).status_code == 303
    csrf = signed_in_client.get('/api/auth/me').json()['csrf']
    response = signed_in_client.post('/login', data={
        'username': 'ALICE', 'password': 'password123', 'csrf': csrf, 'next': 'checkout',
    })
    assert response.status_code == 303
    assert response.headers['location'] == '/?view=checkout'


def test_registration_rejects_duplicate_name(signed_in_client, register_account):
    assert register_account(signed_in_client).status_code == 409


def test_registration_rejects_invalid_credentials(client, register_account):
    assert register_account(client, username='x', password='short').status_code == 422
