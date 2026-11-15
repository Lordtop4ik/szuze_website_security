"""HTTP integration tests with a fresh temporary SQLite database."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from webapp import create_app

@contextmanager
def serve(database):
    import os
    from unittest.mock import patch
    with patch.dict(os.environ, SHOP_ADMIN_TOKEN='test-only'):
        with TestClient(create_app(database)) as client:
            csrf = client.get('/api/auth/me').json()['csrf']
            response = client.post('/register', data={'username':'tester', 'password':'test-password', 'csrf':csrf}, follow_redirects=False)
            if response.status_code == 409:
                response = client.post('/login', data={'username':'tester', 'password':'test-password', 'csrf':csrf}, follow_redirects=False)
            assert response.status_code == 303
            client.headers['X-CSRF-Token'] = client.get('/api/auth/me').json()['csrf']
            yield client

def request(base, path, *, method='GET', body=None, token=''):
    headers = {'X-Admin-Token':token}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    response = base.request(method, path, content=None if body is None else json.dumps(body).encode(), headers=headers)
    return response.status_code, response.json()


def order(product_id, quantity=1):
    return {'items': [{'productId': product_id, 'quantity': quantity, 'price': 1}]}


class ShopApiTests(unittest.TestCase):
    def test_catalog_orders_admin_and_persistence(self):
        with TemporaryDirectory() as tmp:
            database = Path(tmp) / 'shop.sqlite3'
            with serve(database) as base:
                query = urlencode({'q': 'УТКА', 'category': 'Отладка'})
                status, matches = request(base, '/api/products?' + query)
                self.assertEqual((status, [p['id'] for p in matches]), (200, ['duck']))
                duck_stock = matches[0]['stock']
                self.assertTrue(5 <= duck_stock <= 20)
                custom = {'name': 'Последний товар', 'category': 'Тест', 'description': 'Описание',
                          'price': 301, 'stock': 1, 'image': 'duck.svg'}
                self.assertEqual(request(base, '/api/products/last', method='PUT', body=custom)[0], 403)
                self.assertEqual(request(base, '/api/products/last', method='PUT', body=custom, token='test-only')[0], 200)
                invalid = dict(custom, name=chr(0xD800))
                self.assertEqual(request(base, '/api/products/last', method='PUT', body=invalid, token='test-only')[0], 400)
                self.assertEqual(request(base, '/api/orders', method='POST', body=order('missing'))[0], 400)
                self.assertEqual(request(base, '/api/orders', method='POST', body=order('duck', 1.5))[0], 400)
                self.assertEqual(request(base, '/api/orders', method='POST', body={'items': []})[0], 400)
                failed = order('duck')
                failed['items'].extend(order('last', 2)['items'])
                self.assertEqual(request(base, '/api/orders', method='POST', body=failed)[0], 409)
                self.assertEqual(request(base, '/api/products?' + query)[1][0]['stock'], duck_stock)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: request(base, '/api/orders', method='POST', body=order('last')), range(2)))
                self.assertEqual(sorted(status for status, _ in results), [201, 409])
                discounted = order('duck', 3)
                discounted.update(promo='DEBUG10', requestId='unique-test-id')
                status, result = request(base, '/api/orders', method='POST', body=discounted)
                self.assertEqual((status, result['totalKopecks']), (201, 27000))
                self.assertEqual(request(base, '/api/orders', method='POST', body=discounted), (200, result))
            with serve(database) as base:
                self.assertEqual(request(base, '/api/products?' + query)[1][0]['stock'], duck_stock - 3)
                self.assertEqual(request(base, '/api/products?' + urlencode({'category': 'Тест'}))[1][0]['stock'], 0)
                self.assertEqual(request(base, '/api/orders', method='POST', body=discounted), (200, result))


if __name__ == '__main__':
    unittest.main()
