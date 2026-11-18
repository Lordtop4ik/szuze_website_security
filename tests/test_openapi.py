import pytest


@pytest.fixture
def schema(client):
    response = client.get('/openapi.json')
    assert response.status_code == 200
    return response.json()


def test_swagger_ui_is_available(client):
    response = client.get('/docs')
    assert response.status_code == 200
    assert 'Swagger UI' in response.text


def test_openapi_only_lists_json_routes(schema):
    assert set(schema['paths']) == {
        '/api/auth/me', '/api/products', '/api/orders', '/api/products/{product_id}',
    }


def test_openapi_documents_catalog_filters(schema):
    operation = schema['paths']['/api/products']['get']
    assert {parameter['name'] for parameter in operation['parameters']} == {'q', 'category'}


def test_openapi_documents_order_contract(schema):
    operation = schema['paths']['/api/orders']['post']
    assert set(operation['responses']) == {'200', '201', '400', '401', '403', '409', '413', '415', '503'}
    request = operation['requestBody']['content']['application/json']['schema']
    assert request['required'] == ['items']
    result = operation['responses']['201']['content']['application/json']['schema']
    assert set(result['required']) == {'id', 'totalKopecks'}
    assert operation['security'] == [{'SessionCookie': [], 'CsrfToken': []}]


def test_openapi_documents_admin_product_contract(schema):
    operation = schema['paths']['/api/products/{product_id}']['put']
    request = operation['requestBody']['content']['application/json']['schema']
    assert set(request['required']) == {'name', 'category', 'description', 'price', 'stock', 'image'}
    assert operation['security'] == [{'AdminToken': []}]
    assert '404' in operation['responses']


def test_openapi_defines_security_credentials(schema):
    schemes = schema['components']['securitySchemes']
    assert {(scheme['in'], scheme['name']) for scheme in schemes.values()} == {
        ('cookie', 'session'), ('header', 'X-CSRF-Token'), ('header', 'X-Admin-Token'),
    }
