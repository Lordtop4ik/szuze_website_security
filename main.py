"""Локальный сервер магазина и упаковка статической версии."""

import argparse
import os
from pathlib import Path
import tempfile
import zipfile


def raise_walk_error(error):
    raise error


def site_files(site):
    for directory, directories, files in os.walk(site, followlinks=False, onerror=raise_walk_error):
        root = Path(directory)
        for entry in directories + files:
            path = root / entry
            if path.is_symlink() or path.is_junction():
                raise ValueError(f'Ссылка в site: {path}')
        for entry in files:
            path = root / entry
            if not path.is_file():
                raise ValueError(f'Необычный файл: {path}')
            yield path


def pack(site):
    fd, name = tempfile.mkstemp(prefix='shop-', suffix='.zip', dir='.')
    os.close(fd)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(
            temporary, 'w', compression=zipfile.ZIP_DEFLATED, strict_timestamps=False
        ) as archive:
            for path in site_files(site):
                archive.write(path, path.relative_to(site).as_posix())
        # Windows requires the archive to be closed before replacement.
        os.replace(temporary, 'shop.zip')
    finally:
        temporary.unlink(missing_ok=True)
    print('Ready: shop.zip (index.html at archive root)')


def parse_args(site):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', action='store_true', help='Упаковать site/ в shop.zip')
    args = parser.parse_args()
    if not (site / 'index.html').is_file():
        parser.error('Запустите из корня проекта: нет site/index.html')
    return args


def run_server():
    # Keep packaging available without server dependencies.
    import uvicorn

    from webapp import create_app

    uvicorn.run(
        create_app(),
        host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', '8000')),
        proxy_headers=False,
    )


def main():
    site = Path('site')
    if parse_args(site).pack:
        pack(site)
    else:
        run_server()


if __name__ == '__main__':
    main()
