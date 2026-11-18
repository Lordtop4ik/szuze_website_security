import os
import zipfile

import pytest


def archive_names(path):
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def test_zip_contains_site_resources(pack_project, pack_cli):
    (pack_project / 'site/products.json').write_text('[]', encoding='utf-8')
    result = pack_cli()
    assert result.returncode == 0, result.stderr
    names = archive_names(pack_project / 'shop.zip')
    assert {'index.html', 'styles.css', 'app.js', 'assets/shop.svg', 'products.json'} <= set(names)


def test_zip_excludes_paths_outside_site_and_server_sources(published_zip):
    names = archive_names(published_zip)
    assert all(not name.startswith(('site/', '../', '/')) for name in names)
    assert all(not name.endswith(('.go', '.java', '.cs', '.csproj', '.py')) for name in names)


def test_repack_removes_deleted_file(pack_project, pack_cli):
    old_file = pack_project / 'site/old.txt'
    old_file.write_text('old', encoding='utf-8')
    result = pack_cli()
    assert result.returncode == 0, result.stderr
    archive = pack_project / 'shop.zip'
    assert 'old.txt' in archive_names(archive)
    old_file.unlink()
    result = pack_cli()
    assert result.returncode == 0, result.stderr
    assert 'old.txt' not in archive_names(archive)


def test_missing_index_preserves_previous_zip(pack_project, published_zip, pack_cli):
    previous = published_zip.read_bytes()
    (pack_project / 'site/index.html').unlink()
    assert pack_cli().returncode != 0
    assert published_zip.read_bytes() == previous


@pytest.mark.skipif(os.name == 'nt', reason='Symlink creation requires privileges on Windows')
def test_symlink_preserves_previous_zip(pack_project, published_zip, pack_cli):
    previous = published_zip.read_bytes()
    outside = pack_project / 'outside.txt'
    outside.write_text('must not leak', encoding='utf-8')
    (pack_project / 'site/link.txt').symlink_to(outside)
    assert pack_cli().returncode != 0
    assert published_zip.read_bytes() == previous


def test_pack_with_cp1252_console(pack_cli):
    result = pack_cli(env=dict(os.environ, PYTHONIOENCODING='cp1252'))
    assert result.returncode == 0, result.stderr
    assert b'Ready: shop.zip' in result.stdout
