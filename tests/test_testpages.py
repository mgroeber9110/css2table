"""Umwandlung echter, gespeicherter Webseiten aus testpages/.

Die Seiten selbst sind nicht im Repo (siehe testpages/README.md); ohne sie
werden diese Tests übersprungen.
"""

import os

import pytest

from tools.testpages import check, find_pages

PAGES = find_pages()

# Anteil des sichtbaren Originaltexts, der mindestens erhalten bleiben muss
MIN_TEXT_COVERAGE = 0.8


@pytest.mark.skipif(not PAGES, reason='keine Testseiten in testpages/')
@pytest.mark.parametrize('path', PAGES, ids=[os.path.relpath(p, os.path.dirname(os.path.dirname(p))) for p in PAGES])
def test_saved_page(path):
    result = check(path)
    html = result['html']
    assert html.startswith('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01')
    for forbidden in ('<script', '<iframe', '<svg', 'class='):
        assert forbidden not in html
    assert result['text_coverage'] >= MIN_TEXT_COVERAGE
    assert result['seconds'] < 10
