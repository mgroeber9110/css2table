"""Convert and evaluate saved web pages from testpages/.

Each page lives in its own subfolder, as the browser stores it with
"Save page as" (page.html plus page_files/ with the CSS):

    testpages/tagesschau/tagesschau.de.html
    testpages/tagesschau/tagesschau.de_files/main.css

Usage: python tools/testpages.py [folder]
The output goes to testpages/out/<name>.html.
"""

import os
import re
import sys
import time
from collections import Counter

import lxml.html

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from css2table import convert  # noqa: E402
from css2table.__main__ import file_loader  # noqa: E402
from css2table.convert import DROP, Converter, parse  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'testpages')


def find_pages(root=ROOT):
    """All HTML files directly inside the subfolders of `root`."""
    pages = []
    if not os.path.isdir(root):
        return pages
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if name == 'out' or not os.path.isdir(folder):
            continue
        for f in sorted(os.listdir(folder)):
            if f.endswith(('.html', '.htm')):
                pages.append(os.path.join(folder, f))
    return pages


def words(text):
    return Counter(re.findall(r'\w+', text.lower()))


def visible_words(html, base_dir, heuristics=True):
    """Words that are visible in the original page.

    With `heuristics`, the converter's own visibility rules apply (hidden
    overlays, off-screen and screen-reader-only elements), so the coverage
    measures what the layout conversion loses. Without, only display: none
    and visibility: hidden count as hidden.
    """
    doc = parse(html)
    converter = Converter(doc, load_stylesheet=file_loader(base_dir))
    parts = []

    def shown(el):
        s = converter.style(el)
        if heuristics:
            return converter.visible(el, s)
        return el.tag not in DROP and s['display'] != 'none' and s['visibility'] != 'hidden'

    def walk(el):
        if not shown(el):
            return
        if el.text:
            parts.append(el.text)
        for child in el:
            if isinstance(child.tag, str):
                walk(child)
            if child.tail:
                parts.append(child.tail)

    body = doc.find('body')
    walk(body if body is not None else doc)
    return words(' '.join(parts))


def output_words(html):
    doc = lxml.html.document_fromstring(html)
    body = doc.find('body')
    return words((body if body is not None else doc).text_content())


def check(path, out_dir=None):
    """Convert a page; returns metrics as a dict."""
    with open(path, 'rb') as f:
        html = f.read()
    base_dir = os.path.dirname(path)
    start = time.perf_counter()
    result = convert(html, load_stylesheet=file_loader(base_dir))
    seconds = time.perf_counter() - start
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, os.path.basename(path)), 'w', encoding='utf-8') as f:
            f.write(result)
    original = visible_words(html, base_dir)
    css_visible = sum(visible_words(html, base_dir, heuristics=False).values())
    converted = output_words(result)
    kept = sum((original & converted).values())
    return {
        'page': os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
        'seconds': seconds,
        'size_in': len(html),
        'size_out': len(result.encode('utf-8')),
        'tables': result.count('<table'),
        'images': (html.count(b'<img'), result.count('<img')),
        'text_coverage': kept / max(1, sum(original.values())),
        # words dropped as hidden by the heuristics (skip links, menus, ...)
        'text_hidden': 1 - sum(original.values()) / max(1, css_visible),
        'html': result,
    }


def main(argv=None):
    root = (argv or sys.argv[1:] or [ROOT])[0]
    pages = find_pages(root)
    if not pages:
        print(f'No test pages found in {root}.')
        return 1
    out_dir = os.path.join(root, 'out')
    print(f'{"Page":40} {"Time":>6} {"KB in":>7} {"KB out":>7} {"Tables":>8} {"Img out/in":>10} {"Text":>6} {"Hidden":>6}')
    for path in pages:
        r = check(path, out_dir)
        print(f'{r["page"]:40} {r["seconds"]:5.1f}s {r["size_in"] // 1024:7} '
              f'{r["size_out"] // 1024:7} {r["tables"]:8} {"%d/%d" % r["images"][::-1]:>10} '
              f'{r["text_coverage"]:6.0%} {r["text_hidden"]:6.0%}')
    print(f'Output in {out_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
