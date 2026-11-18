"""Filesystem error must preserve the previous archive."""

import os
from pathlib import Path

import pytest

from main import pack


@pytest.fixture
def unreadable_site(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    site = Path('site')
    (site / 'blocked').mkdir(parents=True)
    (site / 'index.html').write_text('hello', encoding='utf-8')
    Path('shop.zip').write_bytes(b'previous archive')
    scandir = os.scandir

    def fail_on_blocked(path):
        if Path(path).name == 'blocked':
            raise PermissionError('access denied')
        return scandir(path)

    monkeypatch.setattr(os, 'scandir', fail_on_blocked)
    return site


def test_unreadable_directory_preserves_previous_zip(unreadable_site):
    with pytest.raises(PermissionError, match='access denied'):
        pack(unreadable_site)
    assert Path('shop.zip').read_bytes() == b'previous archive'
