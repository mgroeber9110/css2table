import lxml.html
import pytest

from css2table import convert
from css2table.cascade import StyleResolver
from css2table.values import color, font_face, media_matches


def page(css, body):
    return f'<html><head><style>{css}</style></head><body>{body}</body></html>'


def parse(html, **kwargs):
    return lxml.html.document_fromstring(convert(html, **kwargs))


def styles(css, body, width=800):
    doc = lxml.html.document_fromstring(page(css, body))
    return doc, StyleResolver(doc, width)


# -- Kaskade ------------------------------------------------------------------

def test_specificity_and_order():
    doc, r = styles('#x { color: red } p.a { color: blue } p { color: green }',
                    '<p id="x" class="a">t</p><p class="a">u</p>')
    first, second = doc.findall('.//p')
    assert r.style(first)['color'] == 'red'
    assert r.style(second)['color'] == 'blue'


def test_important_beats_inline_style():
    doc, r = styles('p { color: red !important } p { font-size: 20px }',
                    '<p style="color: blue; font-size: 10px">t</p>')
    s = r.style(doc.find('.//p'))
    assert s['color'] == 'red'
    assert s.font_size == 10


def test_inheritance_and_em():
    doc, r = styles('body { font-size: 20px; color: #333 } h1 { font-size: 2em }',
                    '<div><h1>t</h1></div>')
    s = r.style(doc.find('.//h1'))
    assert s.font_size == 40
    assert s['color'] == '#333'


def test_custom_properties():
    doc, r = styles(':root { --gap: 12px; --c: #f00 } .g { gap: var(--gap); color: var(--c, blue) }'
                    ' .h { color: var(--missing, green) }',
                    '<div class="g">t</div><div class="h">u</div>')
    g, h = doc.findall('.//div')
    assert r.style(g)['column-gap'] == '12px'
    assert r.style(g)['color'] == '#f00'
    assert r.style(h)['color'] == 'green'


def test_media_queries():
    assert media_matches('(min-width: 768px)', 800)
    assert not media_matches('(min-width: 1024px)', 800)
    assert media_matches('screen and (max-width: 900px)', 800)
    assert not media_matches('print', 800)
    assert media_matches('(width >= 600px)', 800)
    doc, r = styles('.a { color: red } @media (min-width: 1200px) { .a { color: blue } }',
                    '<p class="a">t</p>')
    assert r.style(doc.find('.//p'))['color'] == 'red'


def test_values():
    assert color('rgb(255, 0, 0)') == '#ff0000'
    assert color('rgba(0, 0, 0, 0.5)') == '#808080'
    assert color('transparent') is None
    assert font_face('Inter, system-ui, sans-serif') == 'Inter, Arial, Helvetica, sans-serif'


# -- Ausgabe allgemein ----------------------------------------------------------

def test_output_is_html4_without_scripts_and_classes():
    html = page('.x { color: red }',
                '<header class="x" onclick="f()">a</header><script>alert(1)</script>'
                '<iframe src="x"></iframe><main data-foo="1">b</main>')
    out = convert(html)
    assert out.startswith('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN"')
    for forbidden in ('<script', '<iframe', '<header', '<main', 'class=', 'onclick', 'data-foo'):
        assert forbidden not in out


def test_hidden_and_fixed_elements_are_dropped():
    out = convert(page('.cookie { position: fixed } .no { display: none }',
                       '<div class="cookie">Cookie</div><p class="no">weg</p><p hidden>auch</p><p>da</p>'))
    assert 'Cookie' not in out and 'weg' not in out and 'auch' not in out
    assert 'da' in out


def test_colors_become_attributes_and_font_tags():
    doc = parse(page('body { background: #eee; color: #123456; font-family: Arial, sans-serif }'
                     ' .box { background-color: #ff0000; padding: 10px }',
                     '<div class="box">Text</div>'))
    body = doc.find('body')
    assert body.get('bgcolor') == '#eeeeee'
    assert body.get('text') == '#123456'
    table = doc.find('.//table')
    assert table.get('bgcolor') == '#ff0000'
    assert table.get('cellpadding') == '10'
    font = table.find('.//td/font')
    assert font.get('face') == 'Arial, Helvetica, sans-serif'
    assert font.get('color') == '#123456'


def test_centered_max_width_container():
    doc = parse(page('.c { max-width: 600px; margin: 0 auto; background: #fff }', '<div class="c">x</div>'))
    table = doc.find('.//table')
    assert table.get('width') == '600'
    assert table.get('align') == 'center'
    # breiter als der Bildschirm: volle Breite statt fester Pixel
    doc = parse(page('.c { max-width: 1200px; margin: 0 auto; background: #fff }', '<div class="c">x</div>'))
    assert doc.find('.//table').get('width') == '100%'


# -- Flexbox --------------------------------------------------------------------

def test_flex_row_equal_columns():
    doc = parse(page('.f { display: flex; gap: 10px } .f > div { flex: 1 }',
                     '<div class="f"><div>a</div><div>b</div></div>'))
    table = doc.find('.//table')
    assert table.get('cellspacing') == '10'
    assert table.get('width') == '100%'
    cells = table.findall('tr/td')
    assert len(cells) == 2
    assert [c.get('width') for c in cells] == ['50%', '50%']


def test_flex_sidebar_fixed_and_growing():
    doc = parse(page('.f { display: flex } .s { width: 200px } .m { flex: 1 }',
                     '<div class="f"><div class="s">side</div><div class="m">main</div></div>'))
    side, main = doc.findall('.//table/tr/td')
    assert side.get('width') == '200'
    assert main.get('width').endswith('%')


def test_flex_space_between_uses_spacer():
    doc = parse(page('.f { display: flex; justify-content: space-between; align-items: center }',
                     '<div class="f"><a href="/">Logo</a><a href="/x">Menü</a></div>'))
    cells = doc.findall('.//table/tr/td')
    assert len(cells) == 3
    assert cells[1].get('width') == '100%' and len(cells[1]) == 0
    assert cells[0].get('valign') == 'middle'
    assert cells[0].get('nowrap') is not None


def test_flex_center():
    doc = parse(page('.f { display: flex; justify-content: center }',
                     '<div class="f"><span>a</span></div>'))
    cells = doc.findall('.//table/tr/td')
    assert len(cells) == 3
    assert cells[0].get('width') == cells[2].get('width') == '50%'


def test_flex_column():
    doc = parse(page('.f { display: flex; flex-direction: column; align-items: center; gap: 5px }',
                     '<div class="f"><p>a</p><p>b</p><p>c</p></div>'))
    table = doc.find('.//table')
    rows = table.findall('tr')
    assert len(rows) == 3
    assert all(r.find('td').get('align') == 'center' for r in rows)
    assert table.get('cellspacing') == '5'


def test_flex_wrap_splits_lines():
    tiles = ''.join(f'<div class="t">{i}</div>' for i in range(5))
    doc = parse(page('.f { display: flex; flex-wrap: wrap } .t { flex: 1 1 250px }',
                     f'<div class="f">{tiles}</div>'))
    lines = doc.find('.//table').findall('tr/td/table')
    assert [len(line.findall('tr/td')) for line in lines] == [3, 2]


# -- Grid -------------------------------------------------------------------------

def test_grid_fr_columns_to_percent():
    doc = parse(page('.g { display: grid; grid-template-columns: 1fr 2fr 1fr }',
                     '<div class="g"><div>a</div><div>b</div><div>c</div><div>d</div></div>'))
    rows = doc.find('.//table').findall('tr')
    assert len(rows) == 2
    assert [td.get('width') for td in rows[0]] == ['25%', '50%', '25%']
    assert len(rows[1]) == 3  # eine Zelle mit Inhalt, zwei leere


def test_grid_span_becomes_colspan_and_rowspan():
    doc = parse(page('.g { display: grid; grid-template-columns: repeat(3, 1fr) }'
                     ' .w { grid-column: span 2 } .t { grid-row: 1 / 3 }',
                     '<div class="g"><div class="t">T</div><div class="w">W</div>'
                     '<div>x</div><div>y</div></div>'))
    rows = doc.find('.//table').findall('tr')
    first = rows[0].findall('td')
    assert first[0].get('rowspan') == '2'
    assert first[1].get('colspan') == '2'
    assert first[1].get('width') == '67%'
    assert len(rows[1].findall('td')) == 2


def test_grid_template_areas():
    css = ('.g { display: grid; grid-template-columns: 200px 1fr;'
           ' grid-template-areas: "head head" "side main" }'
           ' .h { grid-area: head } .s { grid-area: side } .m { grid-area: main }')
    doc = parse(page(css, '<div class="g"><div class="m">M</div><div class="s">S</div><div class="h">H</div></div>'))
    rows = doc.find('.//table').findall('tr')
    assert rows[0].find('td').get('colspan') == '2'
    assert 'H' in rows[0].text_content()
    side, main = rows[1].findall('td')
    assert side.get('width') == '200' and 'S' in side.text_content()
    assert 'M' in main.text_content()


@pytest.mark.parametrize('width, expected', [(800, 4), (400, 2)])
def test_grid_auto_fill(width, expected):
    cards = ''.join(f'<div>{i}</div>' for i in range(8))
    doc = parse(page('body { margin: 0 } .g { display: grid;'
                     ' grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)) }',
                     f'<div class="g">{cards}</div>'), viewport_width=width)
    assert len(doc.find('.//table').find('tr').findall('td')) == expected


def test_example_pages_convert():
    import pathlib
    from css2table.__main__ import file_loader
    examples = pathlib.Path(__file__).parent.parent / 'examples'
    for name in ('grid.html', 'flex.html'):
        out = convert((examples / name).read_bytes(), load_stylesheet=file_loader(str(examples)))
        assert '<table' in out and '<script' not in out
