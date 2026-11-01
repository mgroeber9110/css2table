"""Small test pages in tests/pages/ that rebuild patterns found on real sites.

Each page imitates the structure and CSS of one saved news page from
testpages/ (which cannot be checked in) with neutral text, so the features
needed for those sites stay covered.
"""

import pathlib

import lxml.html
import pytest

from tools.testpages import check

PAGES = pathlib.Path(__file__).parent / 'pages'
NBSP = ' '


def convert_page(name):
    result = check(str(PAGES / f'{name}.html'))
    doc = lxml.html.document_fromstring(result['html'])
    return result, doc


def text(el):
    return ' '.join(' '.join(el.itertext()).split())


def cell_with(doc, words):
    """The innermost table cell containing `words`."""
    cells = [td for td in doc.iter('td') if words in text(td)]
    return min(cells, key=lambda td: (len(text(td)), -len(list(td.iterancestors()))))


@pytest.mark.parametrize('name', sorted(p.stem for p in PAGES.glob('*.html')))
def test_page_is_legacy_html(name):
    result, doc = convert_page(name)
    html = result['html']
    assert html.startswith('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01')
    for forbidden in ('<script', '<svg', '<source', '<picture', ' class='):
        assert forbidden not in html
    assert result['text_coverage'] == 1.0
    for el in doc.iter('img', 'table', 'td'):
        width = el.get('width') or ''
        assert not (width.isdigit() and int(width) > 800), lxml.html.tostring(el)[:200]


def test_news_article():
    result, doc = convert_page('news-article')
    body = text(doc.find('body'))
    # The fixed header stays in the flow
    header = doc.xpath('//table[@bgcolor="#0c3a6e"]')
    assert header and 'Sections' in text(header[0])
    # Skip link, screen reader text, off-canvas menu and cookie banner are dropped
    for hidden in ('Skip to content', 'Main navigation', 'Flyout entry', 'Cookie banner'):
        assert hidden not in body
    # The <img> inside <picture> is kept
    assert [img.get('src') for img in doc.iter('img')] == ['lead.jpg']
    # calc(50% - gap / 2) gives two teasers per line
    one = cell_with(doc, 'Teaser one')
    assert one.get('width') == '50%'
    assert 'Teaser two' in text(one.getparent()) and 'Teaser three' not in text(one.getparent())


def test_teaser_grid():
    result, doc = convert_page('teaser-grid')
    assert 'Hidden menu entry' not in text(doc.find('body'))  # translateX(-100%)
    # grid-template-areas with fr columns
    assert cell_with(doc, 'Lead teaser').get('width') == '67%'
    assert cell_with(doc, 'Side teaser').get('width') == '33%'
    assert cell_with(doc, 'Footer teaser').get('colspan') == '2'
    # Widest srcset candidate that fits the screen
    assert doc.find('.//img').get('src') == 'lead-640.jpg'
    # all: unset; display: revert keeps the list
    assert doc.find('.//li') is not None
    assert cell_with(doc, 'Left half').get('width') == '50%'


def test_home_sliders():
    result, doc = convert_page('home-sliders')
    # rem relative to html { font-size: 62.5% }
    box = cell_with(doc, 'Box of 30rem').getparent().getparent()
    assert box.get('width') == '300'
    # The scrolling menu is wrapped into several lines
    elections = cell_with(doc, 'Elections').getparent()
    assert 'Elections' in text(elections) and 'Sports' not in text(elections)
    # Slides sized by JavaScript get the screen width, one per line
    for slide in ('Slide one', 'Slide two', 'Slide three'):
        assert cell_with(doc, slide).get('width') == '100%'
    assert 'Slide two' not in text(cell_with(doc, 'Slide one').getparent())
    # The -webkit-box headline is a block below the inline-block topline
    headline = [d for d in doc.iter('div') if text(d) == 'Candidate leaves the country']
    assert headline
    # Menu links spaced by margin and padding get non-breaking spaces
    link = [a for a in doc.iter('a') if 'Elections' in text(a)][0]
    assert link.text_content().startswith(NBSP)


def test_table_menu():
    result, doc = convert_page('table-menu')
    # display: table-cell items become cells of one row
    row = cell_with(doc, 'South').getparent()
    while not all(w in text(row) for w in ('South', 'Radio live')):
        row = row.getparent()
    assert row.tag == 'tr' and len(row.findall('td')) == 4
    assert all(td.get('nowrap') is not None for td in row.findall('td'))
    # text-transform: uppercase
    assert 'MOUNTAIN TOWN' in text(doc.find('body'))
    # Icon boxes are empty and removed; padding-top for the fixed header is ignored
    assert doc.find('.//i') is None
    assert all(int(t.get('cellpadding', '0')) <= 8 for t in doc.iter('table'))


def test_utility_classes():
    result, doc = convert_page('utility-classes')
    body = text(doc.find('body'))
    # External stylesheet with media queries for an 800 pixel screen
    assert 'Ticker' in body and 'Mobile only link' not in body
    alts = [img.get('alt') for img in doc.iter('img')]
    assert 'Light logo' in alts and 'Dark logo' not in alts
    # Image width from CSS instead of the file size in the width attribute
    big = [img for img in doc.iter('img') if img.get('alt') == 'Big image'][0]
    assert big.get('width') == '100%' and big.get('height') is None
    # grid-auto-flow: column puts the articles side by side
    first = cell_with(doc, 'First column')
    assert first.get('width') == '33%' and 'Third column' in text(first.getparent())
    # The slider of fixed-width cards is wrapped
    one = cell_with(doc, 'Product one').getparent()
    while 'Product two' not in text(one):
        one = one.getparent()
    assert 'Product five' not in text(one)
    # Gaps are cells of their own, links inherit text-decoration: none
    assert doc.xpath('//td[@width="16"]')
    assert all('text-decoration:none' in (a.get('style') or '') for a in doc.iter('a'))


def test_scroll_rows():
    result, doc = convert_page('scroll-rows')
    body = text(doc.find('body'))
    # Skip link scaled to 0, flyout moved by translateX(calc(100% + 10px)),
    # and the content of a closed <details> are hidden; the summary stays
    for hidden in ('Jump to content', 'Flyout entry', 'Collapsed entry'):
        assert hidden not in body
    assert 'Sections' in body
    # Items on the same named grid lines share a cell instead of being lost
    edition = cell_with(doc, 'Edition')
    assert 'Masthead logo' in text(edition) and edition.find('.//br') is not None
    assert edition.get('colspan') == '12'
    assert 'Pillar links' in body
    # Flex cards with min-width wrap into lines
    one = cell_with(doc, 'Card one').getparent()
    while 'Card two' not in text(one):
        one = one.getparent()
    assert 'Card five' not in text(one)
    # A column-flow grid with calc(100% - 6rem) columns shows one item per row
    assert 'Ticker two' not in text(cell_with(doc, 'Ticker one').getparent())
    # Fixed-width cards (inside display: contents) get fewer equal columns
    strip = cell_with(doc, 'Strip one')
    while strip.tag != 'td' or strip.get('width') is None:
        strip = strip.getparent()
    assert strip.get('width') == '50%'
    # width: 100% of an auto-fill grid item refers to its column
    category = cell_with(doc, 'Category one')
    while category.get('width') != '25%':
        category = category.getparent()
    assert 'Category four' in text(category.getparent())
