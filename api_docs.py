"""Схемы Swagger для маршрутов с ручным чтением ограниченного тела."""

TEXT = {'type': 'string'}
INTEGER = {'type': 'integer'}
PRODUCT_ID = {'type': 'string', 'pattern': '^[a-z0-9-]{1,40}$'}


def object_schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required}


def json_content(schema):
    return {'application/json': {'schema': schema}}


def body(schema, example):
    return {'required': True, 'content': {'application/json': {'schema': schema, 'example': example}}}


def response(description, schema):
    return {'description': description, 'content': json_content(schema)}


ERROR = object_schema({'error': TEXT}, ['error'])
DATABASE_ERROR = response('База временно недоступна', ERROR)
BODY_ERRORS = {
    400: response('Некорректные данные запроса', ERROR),
    413: response('Превышен допустимый размер тела запроса', ERROR),
    415: response('Требуется Content-Type: application/json', ERROR),
    503: DATABASE_ERROR,
}

PRODUCT_FIELDS = {
    'name': {'type': 'string', 'minLength': 1, 'maxLength': 100},
    'category': {'type': 'string', 'minLength': 1, 'maxLength': 60},
    'description': {'type': 'string', 'minLength': 1, 'maxLength': 240},
    'price': {'type': 'integer', 'minimum': 1, 'maximum': 1_000_000},
    'stock': {'type': 'integer', 'minimum': 0, 'maximum': 999_999},
    'image': {'type': 'string', 'pattern': r'^[a-z0-9-]{1,60}\.(svg|png|webp|jpe?g)$'},
}
PRODUCT_BODY = object_schema(PRODUCT_FIELDS, list(PRODUCT_FIELDS))
PRODUCT_EXAMPLE = {
    'name': 'Чехол', 'category': 'Аксессуары', 'description': 'Чехол для телефона',
    'price': 301, 'stock': 5, 'image': 'duck.svg',
}
# Legacy and seeded catalogue entries need not meet the admin input constraints.
PRODUCT = object_schema({
    'id': TEXT, 'name': TEXT, 'category': TEXT, 'description': TEXT,
    'price': INTEGER, 'stock': INTEGER, 'image': TEXT,
}, ['id', *PRODUCT_FIELDS])
PRODUCTS = {'type': 'array', 'items': PRODUCT}
PRODUCT_FILTERS = [
    {'name': 'q', 'in': 'query', 'description': 'Подстрока названия без учёта регистра', 'schema': TEXT},
    {'name': 'category', 'in': 'query', 'description': 'Точное название категории', 'schema': TEXT},
]

USER = object_schema({'id': INTEGER, 'username': TEXT}, ['id', 'username'])
SESSION = object_schema({'user': {'anyOf': [USER, {'type': 'null'}]}, 'csrf': TEXT}, ['user', 'csrf'])
ORDER_ITEM = object_schema({
    'productId': PRODUCT_ID,
    'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 999},
}, ['productId', 'quantity'])
ORDER_BODY = object_schema({
    'items': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': ORDER_ITEM},
    'promo': {'type': 'string', 'enum': ['', 'DEBUG10'], 'description': 'DEBUG10 даёт скидку 10%'},
    'requestId': {'type': ['string', 'null'], 'pattern': '^[a-zA-Z0-9-]{1,80}$'},
}, ['items'])
ORDER = object_schema({'id': INTEGER, 'totalKopecks': INTEGER}, ['id', 'totalKopecks'])

SECURITY_SCHEMES = {
    'SessionCookie': {'type': 'apiKey', 'in': 'cookie', 'name': 'session'},
    'CsrfToken': {'type': 'apiKey', 'in': 'header', 'name': 'X-CSRF-Token'},
    'AdminToken': {'type': 'apiKey', 'in': 'header', 'name': 'X-Admin-Token'},
}


def configure_openapi(app):
    generate_schema = app.openapi

    def openapi():
        schema = generate_schema()
        components = schema.setdefault('components', {})
        components.setdefault('securitySchemes', {}).update(SECURITY_SCHEMES)
        # The path value is a string. Its format is checked by the route and returns 404.
        schema['paths']['/api/products/{product_id}']['put']['responses'].pop('422', None)
        return schema

    app.openapi = openapi
