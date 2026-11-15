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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pwdlib import PasswordHash

from shop_api import ApiError, ShopService, connect, prepare_database

ROOT = Path(__file__).resolve().parent
passwords = PasswordHash.recommended()
DUMMY = passwords.hash('dummy-password')


def client_ip(request):
    return request.client.host if request.client else ''


def create_app(database=None, cookie_secure=None):
    database = Path(database or os.getenv('SHOP_DB') or ROOT / 'data/shop.sqlite3').resolve()
    if database.is_relative_to((ROOT / 'site').resolve()):
        raise ValueError('SHOP_DB должен находиться вне site/')
    secure = os.getenv('COOKIE_SECURE', '0') == '1' if cookie_secure is None else cookie_secure

    @asynccontextmanager
    async def lifespan(app):
        prepare_database(database, ROOT / 'site/catalog.js')
        yield

    app = FastAPI(lifespan=lifespan)
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

    async def read_body(request, form=False):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 32768:
                raise ApiError(413, 'Недопустимый размер запроса.')
        if form:
            if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                raise ApiError(415, 'Требуется HTML-форма.')
            from urllib.parse import parse_qs
            try:
                return {k: v[-1] for k, v in parse_qs(body.decode('utf-8'), keep_blank_values=True).items()}
            except UnicodeError:
                raise ApiError(400, 'Некорректная форма.') from None
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise ApiError(415, 'Требуется Content-Type: application/json.')
        try:
            data = json.loads(body)
        except (ValueError, RecursionError):
            raise ApiError(400, 'Некорректный JSON.') from None
        if not isinstance(data, dict):
            raise ApiError(400, 'Требуется объект JSON.')
        return data

    def destination(value):
        return '/?view=checkout' if value == 'checkout' else '/'

    @app.get('/api/auth/me')
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

    @app.get('/login')
    @app.get('/register')
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

    @app.post('/login')
    @app.post('/register')
    async def authenticate(request: Request):
        data = await read_body(request, form=True)
        current = session(request)
        check_csrf(current, data.get('csrf'))
        username, password = data.get('username', '').strip().lower(), data.get('password', '')
        register = request.url.path == '/register'
        error, status, uid = '', 422, None
        if not re.fullmatch(r'[a-z0-9_]{3,32}', username) or not 8 <= len(password) <= 128:
            error = 'Логин: 3–32 латинских буквы, цифры или _. Пароль: 8–128 символов.'
        else:
            with closing(connect(database)) as conn, conn:
                if register:
                    try:
                        uid = conn.execute('INSERT INTO users(username,password_hash) VALUES (?,?)', (username, passwords.hash(password))).lastrowid
                    except sqlite3.IntegrityError:
                        error, status = 'Этот логин уже занят.', 409
                else:
                    user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
                    valid = passwords.verify(password, user['password_hash'] if user else DUMMY)
                    if user and valid:
                        uid = user['id']
                    else:
                        error, status = 'Неверный логин или пароль.', 401
        if error:
            return templates.TemplateResponse(request=request, name='auth.html', context={
                'register': register, 'csrf': current['csrf'], 'next': data.get('next', ''), 'error': error}, status_code=status)
        response = RedirectResponse(destination(data.get('next')), status_code=303)
        new_session(response, uid, current)
        return response

    @app.post('/logout')
    async def logout(request: Request):
        data = await read_body(request, form=True)
        current = session(request)
        check_csrf(current, data.get('csrf'))
        with closing(connect(database)) as conn, conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=?', (current['token_hash'],))
        response = RedirectResponse('/', status_code=303)
        response.delete_cookie('session', secure=secure, httponly=True, samesite='lax')
        return response

    def service(request, body=None, user_id=None):
        return ShopService(database, os.getenv('SHOP_ADMIN_TOKEN', ''), request.headers, body, user_id)

    @app.get('/api/products')
    def products(request: Request):
        status, data = service(request).get_products(request.url.query)
        return JSONResponse(data, status_code=status)

    @app.post('/api/orders')
    async def orders(request: Request):
        current = session(request)
        if not current or not current['user_id']:
            raise ApiError(401, 'Войдите для оформления заказа.')
        check_csrf(current, request.headers.get('X-CSRF-Token'))
        body = await read_body(request)
        status, data = service(request, body, current['user_id']).create_order()
        return JSONResponse(data, status_code=status)

    @app.put('/api/products/{product_id}')
    async def update_product(product_id: str, request: Request):
        if not re.fullmatch(r'[a-z0-9-]{1,40}', product_id):
            raise ApiError(404, 'Маршрут не найден.')
        status, data = service(request, await read_body(request)).put_product(product_id)
        return JSONResponse(data, status_code=status)

    @app.get('/shop-mode.js')
    def mode():
        return Response('const apiEnabled = true;\n', media_type='text/javascript')

    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT'])
    def missing(path: str):
        raise ApiError(404, 'Маршрут не найден.')

    app.mount('/', StaticFiles(directory=ROOT / 'site', html=True), name='site')
    return app
