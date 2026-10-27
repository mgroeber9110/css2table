"""Conversion of real, saved web pages from testpages/.

The pages themselves are not in the repository (see testpages/README.md);
without them these tests are skipped.
"""

import os

import pytest

from tools.testpages import check, find_pages

PAGES = find_pages()

# Minimum share of the visible original text that must be kept
MIN_TEXT_COVERAGE = 0.95


@pytest.mark.skipif(not PAGES, reason='no test pages in testpages/')
@pytest.mark.parametrize('path', PAGES, ids=[os.path.relpath(p, os.path.dirname(os.path.dirname(p))) for p in PAGES])
def test_saved_page(path):
    result = check(path)
    html = result['html']
    assert html.startswith('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01')
    for forbidden in ('<script', '<iframe', '<svg', 'class='):
        assert forbidden not in html
    assert result['text_coverage'] >= MIN_TEXT_COVERAGE
    assert result['seconds'] < 10
