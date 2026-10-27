import lxml.html
import pytest

from css2table import convert
from css2table.cascade import StyleResolver
from css2table.values import color, font_face, length, media_matches


def page(css, body):
    return f'<html><head><style>{css}</style></head><body>{body}</body></html>'


def parse(html, **kwargs):
    return lxml.html.document_fromstring(convert(html, **kwargs))


def styles(css, body, width=800):
    doc = lxml.html.document_fromstring(page(css, body))
    return doc, StyleResolver(doc, width)


# -- Cascade ------------------------------------------------------------------

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


def test_revert_and_all():
    doc, r = styles('*:where(:not(html)) { all: unset; display: revert } h1 { font-size: 30px }',
                    '<div><h1>t</h1><span>u</span></div>')
    div, h1, span = doc.find('.//div'), doc.find('.//h1'), doc.find('.//span')
    assert r.style(div)['display'] == 'block'
    assert r.style(span)['display'] == 'inline'
    assert r.style(h1)['display'] == 'block'
    assert r.style(h1).font_size == 30
    assert r.style(h1)['font-weight'] == 'normal'  # reset by `all: unset`


@pytest.mark.parametrize('value, expected', [
    ('calc(50% - 1.44rem/2)', ('%', 50.0)),
    ('calc((100% - 20px) / 4)', ('%', 25.0)),
    ('calc(100px + 2em)', ('px', 132.0)),
    ('calc(2 * 10px)', ('px', 20.0)),
    ('min(300px, 600px)', ('px', 300.0)),
    ('min(100%, 600px)', ('%', 100.0)),
    ('clamp(10px, 50px, 30px)', ('px', 30.0)),
    ('calc(10px +)', None),
])
def test_math_functions(value, expected):
    assert length(value) == expected


def test_flex_wrap_with_calc_widths():
    teasers = ''.join(f'<div class="t">{i}</div>' for i in range(4))
    doc = parse(page('.f { display: flex; flex-wrap: wrap; gap: 1.44rem } .t { width: calc(50% - 1.44rem/2) }',
                     f'<div class="f">{teasers}</div>'))
    lines = doc.find('.//table').findall('tr/td/table')
    assert [len(line.findall('tr/td')) for line in lines] == [2, 2]
    assert lines[0].find('tr/td').get('width') == '50%'


def test_values():
    assert color('rgb(255, 0, 0)') == '#ff0000'
    assert color('rgba(0, 0, 0, 0.5)') == '#808080'
    assert color('transparent') is None
    assert font_face('Inter, system-ui, sans-serif') == 'Inter, Arial, Helvetica, sans-serif'


# -- General output -------------------------------------------------------------

def test_output_is_html4_without_scripts_and_classes():
    html = page('.x { color: red }',
                '<header class="x" onclick="f()">a</header><script>alert(1)</script>'
                '<iframe src="x"></iframe><main data-foo="1">b</main>')
    out = convert(html)
    assert out.startswith('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN"')
    for forbidden in ('<script', '<iframe', '<header', '<main', 'class=', 'onclick', 'data-foo'):
        assert forbidden not in out


def test_images_in_picture_are_kept():
    out = parse(page('', '<picture><source type="image/webp" srcset="a.webp 400w">'
                         '<img src="a.jpg" alt="Photo" width="400"></picture><p>after</p>'))
    img = out.find('.//img')
    assert img is not None
    assert (img.get('src'), img.get('alt'), img.get('width')) == ('a.jpg', 'Photo', '400')
    assert out.find('.//source') is None
    assert 'after' in out.find('.//body').text_content()


@pytest.mark.parametrize('srcset, expected', [
    ('s.jpg 320w, m.jpg 768w, l.jpg 1920w', 'm.jpg'),
    ('l.jpg 1920w, xl.jpg 3000w', 'l.jpg'),
    ('a.jpg 2x, b.jpg 1x', 'b.jpg'),
])
def test_image_without_src_uses_srcset(srcset, expected):
    out = parse(page('', f'<img srcset="{srcset}" alt="x">'))
    assert out.find('.//img').get('src') == expected


def test_hidden_and_fixed_elements_are_dropped():
    out = convert(page('.cookie { position: fixed; bottom: 0 } .no { display: none }',
                       '<div class="cookie">Cookie</div><p class="no">gone</p><p hidden>also</p><p>here</p>'))
    assert 'Cookie' not in out and 'gone' not in out and 'also' not in out
    assert 'here' in out


def test_fixed_header_stays_in_flow():
    out = convert(page('header { position: fixed; top: 0; width: 100% } .top { position: fixed; bottom: 2rem }'
                       ' .modal { position: fixed; inset: 0 }',
                       '<header>Logo</header><a class="top" href="#">Up</a><div class="modal">Dialog</div><p>Text</p>'))
    assert 'Logo' in out and 'Text' in out
    assert 'Up' not in out and 'Dialog' not in out


def test_offscreen_elements_are_dropped():
    css = ('.skip { position: absolute; left: -10000px } .menu { position: fixed; top: 0; left: -300px; width: 300px }'
           ' .slide { position: absolute; transform: translate(100%) } .sr { position: absolute; clip: rect(0 0 0 0) }'
           ' .fade { position: absolute; opacity: 0 }')
    body = ('<a class="skip" href="#c">Skip</a><div class="menu">Menu</div><div class="slide">Slide</div>'
            '<span class="sr">Hidden</span><span class="fade">Faded</span><p id="c">Content</p>')
    out = convert(page(css, body))
    for gone in ('Skip', 'Menu', 'Slide', 'Hidden', 'Faded'):
        assert gone not in out
    assert 'Content' in out


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
    # wider than the screen: full width instead of fixed pixels
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
                     '<div class="f"><a href="/">Logo</a><a href="/x">Menu</a></div>'))
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
    assert len(rows[1]) == 3  # one cell with content, two empty


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
