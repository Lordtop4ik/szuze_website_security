from concurrent.futures import ThreadPoolExecutor
import json

import pytest

CATALOG_FILTER = {'q': 'УТКА', 'category': 'Отладка'}


def order(product_id='duck', quantity=1, **fields):
    return {'items': [{'productId': product_id, 'quantity': quantity, 'price': 1}], **fields}


def stock(client, product_id):
    products = client.get('/api/products').json()
    return next(product['stock'] for product in products if product['id'] == product_id)


@pytest.fixture
def product_data():
    return {
        'name': 'Последний товар', 'category': 'Тест', 'description': 'Описание',
        'price': 301, 'stock': 1, 'image': 'duck.svg',
    }


@pytest.fixture
def admin_headers(admin_token):
    return {'X-Admin-Token': admin_token}


@pytest.fixture
def last_product(shop_client, admin_headers, product_data):
    response = shop_client.put('/api/products/last', json=product_data, headers=admin_headers)
    assert response.status_code == 200
    return 'last'


@pytest.fixture
def discounted_order():
    return order(quantity=3, promo='DEBUG10', requestId='unique-test-id')


def test_catalog_filters_by_category_and_case_insensitive_name(client):
    response = client.get('/api/products', params=CATALOG_FILTER)
    assert response.status_code == 200
    assert [product['id'] for product in response.json()] == ['duck']


def test_initial_catalog_stock_is_in_seed_range(client):
    assert 5 <= stock(client, 'duck') <= 20


def test_admin_token_is_required(client, admin_token, product_data):
    assert client.put('/api/products/last', json=product_data).status_code == 403


def test_catalog_changes_are_disabled_without_configured_token(client, monkeypatch, product_data):
    monkeypatch.delenv('SHOP_ADMIN_TOKEN', raising=False)
    response = client.put('/api/products/last', json=product_data)
    assert response.status_code == 403
    assert response.json() == {'error': 'Изменение каталога отключено.'}


def test_admin_can_save_product(client, admin_headers, product_data):
    response = client.put('/api/products/last', json=product_data, headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == {'id': 'last', **product_data}


def test_admin_product_name_must_be_utf8(client, admin_headers, product_data):
    # Send the escaped surrogate directly so the test client need not encode it as UTF-8.
    body = json.dumps(dict(product_data, name=chr(0xD800)))
    response = client.put(
        '/api/products/last', content=body,
        headers={**admin_headers, 'Content-Type': 'application/json'},
    )
    assert response.status_code == 400


@pytest.mark.parametrize('body', [
    order('missing'),
    order(quantity=1.5),
    {'items': []},
])
def test_order_rejects_invalid_items(shop_client, body):
    assert shop_client.post('/api/orders', json=body).status_code == 400


def test_failed_order_rolls_back_stock(shop_client, last_product):
    before = stock(shop_client, 'duck')
    body = order()
    body['items'].extend(order(last_product, 2)['items'])
    assert shop_client.post('/api/orders', json=body).status_code == 409
    assert stock(shop_client, 'duck') == before


def test_only_one_concurrent_order_can_buy_last_item(shop_client, last_product):
    body = order(last_product)

    def place_order(_):
        return shop_client.post('/api/orders', json=body).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(place_order, range(2)))
    assert sorted(statuses) == [201, 409]


def test_order_uses_catalog_price_and_applies_promo(shop_client, discounted_order):
    response = shop_client.post('/api/orders', json=discounted_order)
    assert response.status_code == 201
    assert response.json()['totalKopecks'] == 27000


def test_order_can_be_repeated_without_changing_stock(shop_client, discounted_order):
    created = shop_client.post('/api/orders', json=discounted_order)
    assert created.status_code == 201
    before_repeat = stock(shop_client, 'duck')
    repeated = shop_client.post('/api/orders', json=discounted_order)
    assert repeated.status_code == 200
    assert repeated.json() == created.json()
    assert stock(shop_client, 'duck') == before_repeat


def test_stock_persists_after_restart(shop_client, reopen_shop, last_product, discounted_order):
    before = stock(shop_client, 'duck')
    assert shop_client.post('/api/orders', json=discounted_order).status_code == 201
    assert shop_client.post('/api/orders', json=order(last_product)).status_code == 201
    with reopen_shop() as client:
        assert stock(client, 'duck') == before - 3
        assert stock(client, last_product) == 0


def test_order_can_be_repeated_after_restart(shop_client, reopen_shop, discounted_order):
    created = shop_client.post('/api/orders', json=discounted_order)
    assert created.status_code == 201
    with reopen_shop() as client:
        repeated = client.post('/api/orders', json=discounted_order)
    assert repeated.status_code == 200
    assert repeated.json() == created.json()
