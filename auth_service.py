"""Проверка учётных данных и работа с пользователями."""

from contextlib import closing
import re
import sqlite3

from pwdlib import PasswordHash

from shop_api import ApiError, connect

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash('dummy-password')


def register_user(database, username, password):
    with closing(connect(database)) as conn, conn:
        try:
            return conn.execute(
                'INSERT INTO users(username,password_hash) VALUES (?,?)',
                (username, passwords.hash(password)),
            ).lastrowid
        except sqlite3.IntegrityError:
            raise ApiError(409, 'Этот логин уже занят.') from None


def verify_credentials(database, username, password):
    with closing(connect(database)) as conn:
        user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    valid = passwords.verify(password, user['password_hash'] if user else DUMMY_HASH)
    if user and valid:
        return user['id']
    raise ApiError(401, 'Неверный логин или пароль.')


def authenticate_user(database, username, password, *, register):
    username = username.strip().lower()
    if not re.fullmatch(r'[a-z0-9_]{3,32}', username) or not 8 <= len(password) <= 128:
        raise ApiError(422, 'Логин: 3–32 латинских буквы, цифры или _. Пароль: 8–128 символов.')
    if register:
        return register_user(database, username, password)
    return verify_credentials(database, username, password)
