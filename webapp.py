"""FastAPI transport; shop rules stay in shop_api, authentication in auth routes."""
from contextlib import asynccontextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import api_docs as docs
from auth_service import authenticate_user
from shop_api import ApiError, ShopService, connect, prepare_database

ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 32768


def client_ip(request):
    return request.client.host if request.client else ''


async def read_body(request):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise ApiError(413, 'Недопустимый размер запроса.')
        body.extend(chunk)
    return body


def content_type(request):
    return request.headers.get('content-type', '').split(';')[0]


async def read_form(request):
    body = await read_body(request)
    if content_type(request) != 'application/x-www-form-urlencoded':
        raise ApiError(415, 'Требуется HTML-форма.')
    try:
        fields = parse_qs(body.decode('utf-8'), keep_blank_values=True)
    except UnicodeError:
        raise ApiError(400, 'Некорректная форма.') from None
    return {key: values[-1] for key, values in fields.items()}


async def read_json(request):
    body = await read_body(request)
    if content_type(request) != 'application/json':
        raise ApiError(415, 'Требуется Content-Type: application/json.')
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise ApiError(400, 'Некорректный JSON.') from None
    if not isinstance(data, dict):
        raise ApiError(400, 'Требуется объект JSON.')
    return data


def create_app(database=None, cookie_secure=None):
    database = Path(database or os.getenv('SHOP_DB') or ROOT / 'data/shop.sqlite3').resolve()
    if database.is_relative_to((ROOT / 'site').resolve()):
        raise ValueError('SHOP_DB должен находиться вне site/')
    secure = os.getenv('COOKIE_SECURE', '0') == '1' if cookie_secure is None else cookie_secure

    @asynccontextmanager
    async def lifespan(app):
        prepare_database(database, ROOT / 'site/catalog.js')
        yield

    app = FastAPI(
        title='Магазин — API',
        description='Каталог, сессии и заказы магазина.',
        swagger_ui_parameters={'withCredentials': True},
        lifespan=lifespan,
    )
    templates = Jinja2Templates(directory=ROOT / 'templates')

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.url.path.startswith('/api/') or request.url.path in ('/login', '/register', '/logout'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, error):
        return JSONResponse({'error': str(error)}, status_code=error.status)

    @app.exception_handler(sqlite3.Error)
    async def db_error(request, error):
        return JSONResponse({'error': 'База временно недоступна. Повторите запрос.'}, status_code=503)

    def session(request):
        token = request.cookies.get('session', '')
        with closing(connect(database)) as conn:
            row = conn.execute('SELECT s.*, u.username FROM sessions s LEFT JOIN users u ON u.id=s.user_id WHERE token_hash=? AND expires>?',
                               (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return dict(row) if row else None

    def new_session(response, user_id=None, previous=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with closing(connect(database)) as conn, conn:
            if previous:
                conn.execute('DELETE FROM sessions WHERE token_hash=?', (previous['token_hash'],))
            conn.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
            conn.execute('INSERT INTO sessions VALUES (?, ?, ?, ?)',
                         (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, time.time()+86400))
        response.set_cookie('session', token, max_age=86400, httponly=True, secure=secure, samesite='lax')
        return csrf

    def check_csrf(current, value):
        if not current or not secrets.compare_digest(current['csrf'], value or ''):
            raise ApiError(403, 'Обновите страницу и повторите отправку формы.')

    def destination(value):
        return '/?view=checkout' if value == 'checkout' else '/'

    @app.get(
        '/api/auth/me', tags=['Сессия'], summary='Получить сессию и CSRF-токен',
        description='Создаёт гостевую сессию, если действующей сессии ещё нет.',
        responses={200: docs.response('Текущая сессия', docs.SESSION), 503: docs.DATABASE_ERROR},
        openapi_extra={'security': [{}, {'SessionCookie': []}]},
    )
    def me(request: Request):
        current = session(request)
        response = JSONResponse({'user': {'id': current['user_id'], 'username': current['username']} if current and current['user_id'] else None,
                                 'csrf': current['csrf'] if current else None})
        if not current:
            csrf = new_session(response)
            response.body = json.dumps({'user': None, 'csrf': csrf}).encode()
            response.headers['content-length'] = str(len(response.body))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/login', include_in_schema=False)
    @app.get('/register', include_in_schema=False)
    def form_page(request: Request):
        current = session(request)
        response = templates.TemplateResponse(request=request, name='auth.html', context={
            'register': request.url.path == '/register', 'csrf': current['csrf'] if current else '',
            'next': 'checkout' if request.query_params.get('next') == 'checkout' else '', 'error': ''})
        if not current:
            csrf = new_session(response)
            # Render again with the new anonymous session's CSRF token.
            rendered = templates.TemplateResponse(request=request, name='auth.html', context={
                'register': request.url.path == '/register', 'csrf': csrf,
                'next': 'checkout' if request.query_params.get('next') == 'checkout' else '', 'error': ''})
            rendered.headers['set-cookie'] = response.headers['set-cookie']
            response = rendered
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/login', include_in_schema=False)
    @app.post('/register', include_in_schema=False)
    async def authenticate(request: Request):
        data = await read_form(request)
        current = session(request)
        check_csrf(current, data.get('csrf'))
        register = request.url.path == '/register'
        try:
            user_id = authenticate_user(
                database, data.get('username', ''), data.get('password', ''), register=register
            )
        except ApiError as error:
            return templates.TemplateResponse(
                request=request,
                name='auth.html',
                context={
                    'register': register,
                    'csrf': current['csrf'],
                    'next': data.get('next', ''),
                    'error': str(error),
                },
                status_code=error.status,
            )
        response = RedirectResponse(destination(data.get('next')), status_code=303)
        new_session(response, user_id, current)
        return response

    @app.post('/logout', include_in_schema=False)
    async def logout(request: Request):
        data = await read_form(request)
        current = session(request)
        check_csrf(current, data.get('csrf'))
        with closing(connect(database)) as conn, conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=?', (current['token_hash'],))
        response = RedirectResponse('/', status_code=303)
        response.delete_cookie('session', secure=secure, httponly=True, samesite='lax')
        return response

    def service(request, body=None, user_id=None):
        return ShopService(database, os.getenv('SHOP_ADMIN_TOKEN', ''), request.headers, body, user_id)

    @app.get(
        '/api/products', tags=['Каталог'], summary='Получить каталог',
        responses={200: docs.response('Список товаров', docs.PRODUCTS), 503: docs.DATABASE_ERROR},
        openapi_extra={'parameters': docs.PRODUCT_FILTERS},
    )
    def products(request: Request):
        status, data = service(request).get_products(request.url.query)
        return JSONResponse(data, status_code=status)

    @app.post(
        '/api/orders', tags=['Заказы'], summary='Оформить заказ', status_code=201,
        description=(
            'Войдите через /login и получите CSRF-токен из /api/auth/me. '
            'Повтор с тем же requestId, составом заказа и владельцем возвращает прежний заказ.'
        ),
        responses={
            **docs.BODY_ERRORS,
            200: docs.response('Результат ранее созданного заказа', docs.ORDER),
            201: docs.response('Новый заказ', docs.ORDER),
            401: docs.response('Требуется вход', docs.ERROR),
            403: docs.response('Некорректный CSRF-токен', docs.ERROR),
            409: docs.response('Недостаточно товара или requestId уже использован', docs.ERROR),
        },
        openapi_extra={
            'requestBody': docs.body(docs.ORDER_BODY, {'items': [{'productId': 'duck', 'quantity': 1}]}),
            'security': [{'SessionCookie': [], 'CsrfToken': []}],
        },
    )
    async def orders(request: Request):
        current = session(request)
        if not current or not current['user_id']:
            raise ApiError(401, 'Войдите для оформления заказа.')
        check_csrf(current, request.headers.get('X-CSRF-Token'))
        body = await read_json(request)
        status, data = service(request, body, current['user_id']).create_order()
        return JSONResponse(data, status_code=status)

    @app.put(
        '/api/products/{product_id}', tags=['Каталог'], summary='Обновить или добавить товар',
        description=(
            'Доступно при настроенном SHOP_ADMIN_TOKEN. '
            'ID товара содержит от 1 до 40 строчных латинских букв, цифр или дефисов.'
        ),
        responses={
            **docs.BODY_ERRORS,
            200: docs.response('Сохранённый товар', docs.PRODUCT),
            403: docs.response('Изменение отключено или токен администратора неверен', docs.ERROR),
            404: docs.response('Некорректный ID товара', docs.ERROR),
        },
        openapi_extra={
            'requestBody': docs.body(docs.PRODUCT_BODY, docs.PRODUCT_EXAMPLE),
            'security': [{'AdminToken': []}],
        },
    )
    async def update_product(product_id: str, request: Request):
        if not re.fullmatch(r'[a-z0-9-]{1,40}', product_id):
            raise ApiError(404, 'Маршрут не найден.')
        status, data = service(request, await read_json(request)).put_product(product_id)
        return JSONResponse(data, status_code=status)

    @app.get('/shop-mode.js', include_in_schema=False)
    def mode():
        return Response('const apiEnabled = true;\n', media_type='text/javascript')

    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT'], include_in_schema=False)
    def missing(path: str):
        raise ApiError(404, 'Маршрут не найден.')

    docs.configure_openapi(app)
    app.mount('/', StaticFiles(directory=ROOT / 'site', html=True), name='site')
    return app
