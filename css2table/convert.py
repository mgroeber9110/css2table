"""Convert modern HTML/CSS pages into HTML4 with a table layout.

No layout is computed. Instead, the geometric constraints of the CSS
(flexbox, grid, widths, gaps) are translated into table attributes, so the
legacy browser adapts the page to the window size and fonts by itself.
"""

import re
from dataclasses import dataclass

import lxml.html
from lxml import etree

from .cascade import Style, StyleResolver
from .values import (color, font_face, html_font_size, length, px, tokens,
                     split_commas)

DOCTYPE = ('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" '
           '"http://www.w3.org/TR/html4/loose.dtd">')

HTML4_TAGS = {
    'a', 'abbr', 'acronym', 'address', 'b', 'big', 'blockquote', 'br', 'button',
    'caption', 'center', 'cite', 'code', 'col', 'colgroup', 'dd', 'del', 'dfn',
    'div', 'dl', 'dt', 'em', 'fieldset', 'font', 'form', 'h1', 'h2', 'h3', 'h4',
    'h5', 'h6', 'hr', 'i', 'img', 'input', 'ins', 'kbd', 'label', 'legend', 'li',
    'map', 'area', 'menu', 'ol', 'optgroup', 'option', 'p', 'pre', 'q', 's',
    'samp', 'select', 'small', 'span', 'strike', 'strong', 'sub', 'sup', 'table',
    'tbody', 'td', 'textarea', 'tfoot', 'th', 'thead', 'tr', 'tt', 'u', 'ul', 'var',
}
RENAME = {'header': 'div', 'footer': 'div', 'nav': 'div', 'main': 'div',
          'section': 'div', 'article': 'div', 'aside': 'div', 'figure': 'div',
          'figcaption': 'div', 'hgroup': 'div', 'details': 'div', 'summary': 'div',
          'mark': 'span', 'time': 'span', 'data': 'span', 'output': 'span'}
# Elements without an HTML4 equivalent; dropped together with their content
DROP = {'script', 'style', 'link', 'meta', 'iframe', 'object', 'embed', 'video',
        'audio', 'canvas', 'svg', 'math', 'template', 'source', 'track', 'base',
        'dialog', 'head', 'title', 'frame', 'frameset', 'portal'}
# Elements whose content is kept without the element itself
TRANSPARENT = {'picture', 'noscript', 'slot'}
VOID = {'br', 'hr', 'img', 'input', 'col', 'area'}
INLINE_TAGS = {'a', 'abbr', 'acronym', 'b', 'big', 'button', 'cite', 'code', 'del',
               'dfn', 'em', 'font', 'i', 'img', 'input', 'ins', 'kbd', 'label', 'q',
               's', 'samp', 'select', 'small', 'strike', 'strong', 'sub', 'sup',
               'textarea', 'tt', 'u', 'var'}

# Containers whose content can move directly into a table cell
BOX_MERGE = {'div', 'section', 'article', 'header', 'footer', 'nav', 'main',
             'aside', 'figure', 'hgroup', 'span'}
CELL_MERGE = BOX_MERGE | {'li'}

ALIGN_TAGS = {'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th'}
BOLD_TAGS = {'b', 'strong', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'th'}
ITALIC_TAGS = {'i', 'em', 'cite', 'var', 'dfn', 'address'}
# No <font> may be inserted into these elements
NO_FONT = {'table', 'tr', 'tbody', 'thead', 'tfoot', 'ul', 'ol', 'dl', 'select',
           'textarea', 'optgroup', 'option', 'colgroup', 'html'} | VOID
NO_TEXT = {'table', 'tr', 'tbody', 'thead', 'tfoot', 'ul', 'ol', 'dl', 'select'}

GLOBAL_ATTRS = {'id', 'title', 'lang', 'dir'}
TAG_ATTRS = {
    'a': {'href', 'name'},
    'img': {'src', 'alt', 'width', 'height', 'border', 'align', 'usemap'},
    'form': {'action', 'method', 'enctype', 'name'},
    'input': {'type', 'name', 'value', 'size', 'maxlength', 'checked', 'disabled', 'readonly'},
    'button': {'type', 'name', 'value', 'disabled'},
    'select': {'name', 'size', 'multiple', 'disabled'},
    'option': {'value', 'selected', 'disabled'},
    'optgroup': {'label'},
    'textarea': {'name', 'rows', 'cols', 'disabled', 'readonly'},
    'label': {'for'},
    'table': {'width', 'border', 'cellpadding', 'cellspacing', 'align', 'bgcolor', 'summary'},
    'tr': {'align', 'valign', 'bgcolor'},
    'td': {'colspan', 'rowspan', 'width', 'height', 'align', 'valign', 'bgcolor', 'nowrap'},
    'th': {'colspan', 'rowspan', 'width', 'height', 'align', 'valign', 'bgcolor', 'nowrap'},
    'col': {'span', 'width'}, 'colgroup': {'span', 'width'},
    'ol': {'start', 'type'}, 'ul': {'type'}, 'li': {'value', 'type'},
    'map': {'name'}, 'area': {'shape', 'coords', 'href', 'alt'},
    'blockquote': {'cite'}, 'q': {'cite'}, 'font': {'face', 'size', 'color'},
}
INPUT_TYPES = {'text', 'password', 'checkbox', 'radio', 'submit', 'reset',
               'file', 'hidden', 'image', 'button'}

BLOCK_DISPLAYS = {'block', 'list-item', 'flex', 'grid', 'table', 'flow-root'}
LAYOUT_DISPLAYS = {'flex', 'inline-flex', 'grid', 'inline-grid'}
VALIGN = {'center': 'middle', 'flex-end': 'bottom', 'end': 'bottom',
          'self-end': 'bottom', 'baseline': 'baseline'}

# Text shorter than this counts as a "label" and is not wrapped
SHORT_TEXT = 40


def text_ctx(s):
    """The font properties of a style that matter to legacy browsers."""
    align = (s['text-align'] or 'left').lower()
    align = {'start': 'left', 'end': 'right', '-webkit-center': 'center'}.get(align, align)
    weight = (s['font-weight'] or 'normal').lower()
    return {
        'color': color(s['color']) or '#000000',
        'face': font_face(s['font-family']),
        'size': round(s.font_size),
        'bold': weight in ('bold', 'bolder') or (weight.isdigit() and int(weight) >= 600),
        'italic': s['font-style'] in ('italic', 'oblique'),
        'align': align if align in ('left', 'center', 'right', 'justify') else 'left',
    }


DEFAULT_CTX = text_ctx(Style())


@dataclass
class Item:
    """Child of a flex or grid container (an element or loose text)."""
    el: object
    style: Style
    text: str = ''


def collapse(text):
    return re.sub(r'\s+', ' ', text)


def sub(parent, tag, **attrs):
    node = etree.SubElement(parent, tag)
    for k, v in attrs.items():
        node.set(k, str(v))
    return node


def make(tag, **attrs):
    node = etree.Element(tag)
    for k, v in attrs.items():
        node.set(k, str(v))
    return node


def add_text(node, text):
    if not text:
        return
    if len(node):
        node[-1].tail = (node[-1].tail or '') + text
    else:
        node.text = (node.text or '') + text


def pct(value):
    return '%d%%' % max(1, round(value))


class Converter:
    def __init__(self, doc, viewport_width=800, load_stylesheet=None):
        self.doc = doc
        self.viewport = viewport_width
        self.styles = StyleResolver(doc, viewport_width, load_stylesheet)

    def style(self, el):
        return self.styles.style(el)

    # -- Document -----------------------------------------------------------

    def build(self):
        html = make('html')
        head = sub(html, 'head')
        title = self.doc.find('.//title')
        if title is not None and title.text:
            sub(head, 'title').text = collapse(title.text).strip()

        src = self.doc.find('body')
        if src is None:
            src = self.doc
        bs = self.style(src)
        body = sub(html, 'body')
        bg = color(bs['background-color']) or color(self.style(self.doc)['background-color'])
        if bg:
            body.set('bgcolor', bg)
        ctx = text_ctx(bs)
        if ctx['color'] != DEFAULT_CTX['color']:
            body.set('text', ctx['color'])
        margin = px(bs['margin-left'], bs.font_size)
        if margin is not None and margin != 8:
            m = str(round(margin))
            for attr in ('leftmargin', 'topmargin', 'marginwidth', 'marginheight'):
                body.set(attr, m)
        avail = self.viewport - 2 * (margin if margin is not None else 8)

        inner, ctx = self.apply_text(body, ctx, DEFAULT_CTX)
        if bs['display'] in LAYOUT_DISPLAYS:
            inner.append(self.layout(src, bs, avail))
        else:
            self.emit_children(src, inner, avail, ctx)
        return html

    # -- Elements -----------------------------------------------------------

    def visible(self, el, s):
        if not isinstance(el.tag, str) or el.tag in DROP:
            return False
        if s['display'] == 'none' or s['visibility'] in ('hidden', 'collapse'):
            return False
        position = s['position']
        if position in ('absolute', 'fixed') and (self.offscreen(s) or s['opacity'] == '0'):
            return False
        if position == 'fixed' and (s['top'] in (None, 'auto') or s['bottom'] not in (None, 'auto')):
            # Overlays anchored to the bottom or covering the screen: cookie
            # banners, "back to top" buttons, modal dialogs
            return False
        # Anything else that is fixed (typically a header at the top) and
        # absolutely positioned stays in the normal flow.
        return True

    def offscreen(self, s):
        """Is a positioned element moved out of view (skip links, screen reader text, menus)?"""
        fs = s.font_size
        w, h = px(s['width'], fs), px(s['height'], fs)
        if (w is not None and w <= 1) or (h is not None and h <= 1):
            return True
        for side, size in (('top', h), ('left', w), ('right', w)):
            offset = px(s[side], fs)
            # far outside, or moved out by at least its own size (off-canvas menus)
            if offset is not None and (offset <= -999 or (size and offset <= -size)):
                return True
        if re.search(r'translate[xy]?\(\s*-?100%', (s['transform'] or '').lower()):
            return True
        return 'rect(0' in (s['clip'] or '').replace(' ', '') or 'inset(50%' in (s['clip-path'] or '')

    def emit_children(self, el, out, avail, ctx, pre=False):
        self.add_source_text(out, el.text, pre)
        for child in el:
            if isinstance(child.tag, str):
                self.emit(child, out, avail, ctx)
            self.add_source_text(out, child.tail, pre)

    def add_source_text(self, out, text, pre=False):
        if not text or (out.tag in NO_TEXT and not text.strip()):
            return
        add_text(out, text if pre else collapse(text))

    def emit(self, el, out, avail, ctx, boxed=False, shrink=False):
        s = self.style(el)
        if not self.visible(el, s):
            return
        tag = el.tag.lower()
        display = s['display']
        if tag in TRANSPARENT or display == 'contents':
            self.emit_children(el, out, avail, ctx)
            return
        if display in LAYOUT_DISPLAYS:
            node = self.layout(el, s, avail, shrink)
        elif not boxed and display in BLOCK_DISPLAYS and self.needs_box(tag, s):
            node = self.box(el, s, avail, ctx, shrink)
        else:
            node = self.plain(el, s, avail, ctx)
        out.append(node)

    def out_tag(self, el, s):
        tag = el.tag.lower()
        if tag in RENAME:
            return RENAME[tag]
        if tag == 'span' and s['display'] in BLOCK_DISPLAYS:
            return 'div'
        if tag in ('ul', 'ol', 'li') and s['list-style-type'] == 'none':
            return 'div'  # list without bullets
        if tag in HTML4_TAGS:
            return tag
        return 'div' if s['display'] in BLOCK_DISPLAYS else 'span'

    def copy_attrs(self, el, node):
        tag = node.tag
        allowed = GLOBAL_ATTRS | TAG_ATTRS.get(tag, set())
        for key, value in el.attrib.items():
            key = key.lower()
            if key in allowed:
                node.set(key, value)
        if tag == 'img' and not node.get('src'):
            src = el.get('data-src') or (el.get('srcset') or el.get('data-srcset') or '').split(' ')[0]
            if src:
                node.set('src', src)
        if tag == 'input' and (node.get('type') or 'text').lower() not in INPUT_TYPES:
            node.set('type', 'text')

    def plain(self, el, s, avail, ctx):
        """Keep the element with the same (or a similar HTML4) tag."""
        tag = self.out_tag(el, s)
        node = make(tag)
        self.copy_attrs(el, node)
        extra = []
        bg = color(s['background-color'])
        if bg:
            if tag in ('table', 'tr', 'td', 'th'):
                node.set('bgcolor', bg)
            else:
                extra.append('background-color:' + bg)
        decoration = s['text-decoration'] or s['text-decoration-line']
        if decoration:
            extra.append('text-decoration:' + decoration.split()[0])
        if tag in ('img', 'table') and not node.get('width'):
            width = length(s['width'], s.font_size)
            if width:
                node.set('width', str(round(width[1])) if width[0] == 'px' else pct(width[1]))
        if tag == 'table' and node.get('cellspacing') is None and s['border-collapse'] == 'collapse':
            node.set('cellspacing', '0')
        old = DEFAULT_CTX if tag in ('td', 'th') else ctx
        if tag == 'a' and el.get('href'):
            # Legacy browsers give links their own color: always set it explicitly
            old = dict(old, color=None)
        inner, ctx = self.apply_text(node, text_ctx(s), old, extra)
        if tag not in VOID:
            pre = (s['white-space'] or '').startswith('pre')
            self.emit_children(el, inner, avail, ctx, pre)
        if tag in INLINE_TAGS and s['display'] in BLOCK_DISPLAYS:
            wrapper = make('div')
            wrapper.append(node)
            return wrapper
        return node

    def apply_text(self, node, new, old, extra=None):
        """Express font differences from `old` as a style attribute and <font>.

        Returns the element the content belongs in, and the new context.
        """
        tag = node.tag
        css = []
        result = dict(old)
        diff = {k for k in new if new[k] != old[k]}
        if 'color' in diff:
            css.append('color:' + new['color'])
        if 'face' in diff and new['face']:
            css.append('font-family:' + new['face'])
        if 'size' in diff:
            css.append('font-size:%dpx' % new['size'])
        if 'bold' in diff:
            css.append('font-weight:' + ('bold' if new['bold'] else 'normal'))
        if 'italic' in diff:
            css.append('font-style:' + ('italic' if new['italic'] else 'normal'))
        if 'align' in diff and tag in ALIGN_TAGS:
            css.append('text-align:' + new['align'])
            node.set('align', new['align'])
            result['align'] = new['align']
        css += extra or []
        if css:
            node.set('style', '; '.join(css))
        if tag in NO_FONT:
            return node, result

        inner = node
        font = {}
        if 'face' in diff and new['face']:
            font['face'] = new['face']
        if 'color' in diff:
            font['color'] = new['color']
        if 'size' in diff and html_font_size(new['size']) != html_font_size(old['size']):
            font['size'] = str(html_font_size(new['size']))
        if font:
            inner = sub(inner, 'font', **font)
        if 'bold' in diff and new['bold'] and tag not in BOLD_TAGS:
            inner = sub(inner, 'b')
        if 'italic' in diff and new['italic'] and tag not in ITALIC_TAGS:
            inner = sub(inner, 'i')
        for key in ('color', 'face', 'size', 'bold', 'italic'):
            result[key] = new[key]
        return inner, result

    # -- Boxes: background, padding, border, width ------------------------------

    def padding(self, s, avail):
        values = [px(s['padding-' + side], s.font_size, avail) or 0
                  for side in ('top', 'right', 'bottom', 'left')]
        return round(sum(values) / 4)

    def border(self, s):
        if s['border-style'] in ('none', 'hidden'):
            return 0
        width = s['border-width']
        named = {'thin': 1, 'medium': 3, 'thick': 5}
        return named.get(width) or round(px(width, s.font_size) or 0)

    def needs_box(self, tag, s):
        if tag in VOID or tag in ('table', 'ul', 'ol', 'dl', 'form', 'pre'):
            return False
        return bool(color(s['background-color']) or self.padding(s, None) or self.border(s)
                    or length(s['width'], s.font_size) or length(s['max-width'], s.font_size)
                    or s['float'] in ('left', 'right'))

    def box_width(self, s, avail, shrink=False):
        """Width and alignment of a table, plus the estimated width in pixels."""
        fs = s.font_size
        width, max_width = length(s['width'], fs), length(s['max-width'], fs)
        attr, est = None, avail
        if width:
            kind, n = width
            attr, est = (str(round(n)), n) if kind == 'px' else (pct(n), avail * n / 100)
        elif max_width:
            kind, n = max_width
            if kind == '%':
                attr, est = pct(n), avail * n / 100
            elif n >= min(avail, self.viewport):
                attr = '100%'  # max-width wider than the screen: just use the full width
            else:
                attr, est = str(round(n)), n
        elif not shrink and s['float'] not in ('left', 'right') and s['display'] not in (
                'inline-flex', 'inline-grid', 'inline-block'):
            attr = '100%'
        align = None
        if s['float'] in ('left', 'right'):
            align = s['float']
        elif (width or max_width) and s['margin-left'] == 'auto' and s['margin-right'] == 'auto':
            align = 'center'
        return attr, align, est

    def box_table(self, s, avail, shrink=False):
        pad, border = self.padding(s, avail), self.border(s)
        width, align, est = self.box_width(s, avail, shrink)
        table = make('table', cellspacing=0, cellpadding=pad, border=border)
        if width:
            table.set('width', width)
        if align:
            table.set('align', align)
        bg = color(s['background-color'])
        if bg:
            table.set('bgcolor', bg)
        if border and color(s['border-color']):
            table.set('bordercolor', color(s['border-color']))
        td = sub(sub(table, 'tr'), 'td', valign='top')
        return table, td, est - 2 * (pad + border)

    def box(self, el, s, avail, ctx, shrink=False):
        """Block with background/padding/width as a single-cell table."""
        table, td, inner_avail = self.box_table(s, avail, shrink)
        if el.tag in BOX_MERGE:
            holder, cctx = self.apply_text(td, text_ctx(s), DEFAULT_CTX)
            self.emit_children(el, holder, inner_avail, cctx)
        else:
            holder, cctx = self.apply_text(td, ctx, DEFAULT_CTX)
            self.emit(el, holder, inner_avail, cctx, boxed=True)
        return table

    # -- Flexbox and grid --------------------------------------------------

    def layout(self, el, s, avail, shrink=False):
        if s['display'] in ('grid', 'inline-grid'):
            return self.grid(el, s, avail, shrink)
        return self.flex(el, s, avail, shrink)

    def frame(self, s, avail, shrink):
        """Table for a layout container; nested when it has padding."""
        if self.padding(s, avail) or self.border(s):
            outer, td, inner = self.box_table(s, avail, shrink)
            table = sub(td, 'table', cellspacing=0, cellpadding=0, border=0)
            if outer.get('width'):
                table.set('width', '100%')
            return outer, table, inner
        width, align, est = self.box_width(s, avail, shrink)
        table = make('table', cellspacing=0, cellpadding=0, border=0)
        if width:
            table.set('width', width)
        if align:
            table.set('align', align)
        bg = color(s['background-color'])
        if bg:
            table.set('bgcolor', bg)
        return table, table, est

    def items(self, el):
        out = []
        if el.text and el.text.strip():
            out.append(Item(None, self.style(el), el.text))
        for child in el:
            if isinstance(child.tag, str):
                cs = self.style(child)
                if self.visible(child, cs):
                    if cs['display'] == 'contents' or child.tag in TRANSPARENT:
                        out += self.items(child)
                    else:
                        out.append(Item(child, cs))
            if child.tail and child.tail.strip():
                out.append(Item(None, self.style(el), child.tail))
        return out

    def gap(self, s, prop, avail):
        return round(px(s[prop], s.font_size, avail) or 0)

    def fill_cell(self, td, item, container, avail, shrink=False):
        """Write the content of a flex or grid item into a table cell."""
        if item.el is None:
            holder, _ = self.apply_text(td, text_ctx(container), DEFAULT_CTX)
            add_text(holder, collapse(item.text).strip())
            return
        el, s = item.el, item.style
        if s['display'] not in LAYOUT_DISPLAYS and el.tag in CELL_MERGE:
            bg = color(s['background-color'])
            if bg:
                td.set('bgcolor', bg)
            holder = td
            pad, border = self.padding(s, avail), self.border(s)
            if pad or border:
                # height=100% so border and background fill the stretched cell
                inner = sub(td, 'table', width='100%', height='100%', cellspacing=0,
                            cellpadding=pad, border=border)
                if border and color(s['border-color']):
                    inner.set('bordercolor', color(s['border-color']))
                holder = sub(sub(inner, 'tr'), 'td', valign='top')
                avail -= 2 * (pad + border)
            holder, ctx = self.apply_text(holder, text_ctx(s), DEFAULT_CTX)
            self.emit_children(el, holder, avail, ctx, (s['white-space'] or '').startswith('pre'))
        else:
            holder, ctx = self.apply_text(td, text_ctx(container), DEFAULT_CTX)
            self.emit(el, holder, avail, ctx, shrink=shrink)

    def flex(self, el, s, avail, shrink=False):
        root, table, cavail = self.frame(s, avail, shrink or s['display'] == 'inline-flex')
        items = self.items(el)
        direction = s['flex-direction'] or 'row'
        if direction.endswith('reverse'):
            items.reverse()

        if direction.startswith('column'):
            table.set('cellspacing', str(self.gap(s, 'row-gap', cavail)))
            align = {'center': 'center', 'flex-end': 'right', 'end': 'right'}.get(s['align-items'])
            for item in items:
                td = sub(sub(table, 'tr'), 'td', valign='top')
                self.fill_cell(td, item, s, cavail)
                if align:
                    td.set('align', align)
            return root

        gap = self.gap(s, 'column-gap', cavail)
        lines = [items]
        if s['flex-wrap'] in ('wrap', 'wrap-reverse'):
            lines = self.flex_lines(items, cavail, gap)
        if len(lines) == 1:
            table.set('cellspacing', str(gap))
            self.flex_row(table, items, s, cavail, gap)
        else:
            # One table per line, so the column widths are independent
            for line in lines:
                td = sub(sub(table, 'tr'), 'td')
                row = sub(td, 'table', width='100%', cellspacing=gap, cellpadding=0, border=0)
                self.flex_row(row, line, s, cavail, gap)
        return root

    def flex_basis(self, s):
        basis = s['flex-basis'] or 'auto'
        size = None if basis in ('auto', 'content') else length(basis, s.font_size)
        if size and size[1] == 0:
            size = None
        if size is None:
            size = length(s['width'], s.font_size)
        try:
            grow = float(s['flex-grow'] or 0)
        except ValueError:
            grow = 0.0
        return size, grow

    def flex_lines(self, items, avail, gap):
        """Distribute flex-wrap items over lines based on their estimated widths."""
        sizes = []
        for item in items:
            size = self.flex_basis(item.style)[0] if item.el is not None else None
            if size is None:
                return [items]  # width unknown: everything on one line
            sizes.append(size)
        lines, used = [[]], 0
        for item, (kind, n) in zip(items, sizes):
            # Percentage widths usually already leave room for the gap,
            # e.g. calc(50% - 1rem), so the gap only counts for pixel widths
            w = n if kind == 'px' else n * avail / 100
            spacing = gap if kind == 'px' and lines[-1] else 0
            if lines[-1] and used + spacing + w > avail + 0.5:
                lines.append([])
                used, spacing = 0, 0
            used += spacing + w
            lines[-1].append(item)
        return lines

    def flex_row(self, table, line, s, avail, gap):
        tr = sub(table, 'tr')
        sizes = [self.flex_basis(i.style) if i.el is not None else (None, 0.0) for i in line]

        def size_px(size):
            if size is None:
                return 0
            return size[1] if size[0] == 'px' else size[1] * avail / 100

        base = sum(size_px(size) for size, _ in sizes)
        free = max(0.0, avail - base - gap * (len(line) - 1))
        total_grow = sum(g for _, g in sizes)
        used_pct = sum(size_px(size) for size, g in sizes if not g) * 100 / max(avail, 1)

        cells = []
        flexible = False  # does any cell take up the free space?
        for item, (size, grow) in zip(line, sizes):
            width, nowrap = None, False
            if grow > 0:
                inner = max(1.0, avail - gap * (len(line) - 1))
                width = pct((size_px(size) + free * grow / total_grow) * 100 / inner)
                flexible = True
            elif size:
                width = str(round(size[1])) if size[0] == 'px' else pct(size[1])
            elif len(collapse(self.text_of(item)).strip()) <= SHORT_TEXT:
                nowrap = True
            else:
                flexible = True  # long text: the browser distributes the space
            cells.append((item, width, nowrap, grow))

        justify = s['justify-content'] or 'normal'
        n = len(cells)
        if flexible or table.get('width') is None or used_pct >= 99:
            pattern = [False] * n  # no free space to distribute
        elif justify == 'center':
            pattern = [True] + [False] * n + [True]
        elif justify in ('flex-end', 'end', 'right'):
            pattern = [True] + [False] * n
        elif justify == 'space-between' and n > 1:
            pattern = [False] + [True, False] * (n - 1)
        elif justify in ('space-around', 'space-evenly'):
            pattern = [True] + [False, True] * n
        else:
            pattern = [False] * n + [True]
        spacers = pattern.count(True)
        spacer_width = max(0.0, 100 - used_pct) / spacers if spacers else 0

        valign_default = VALIGN.get(s['align-items'], 'top')
        cells = iter(cells)
        for is_spacer in pattern:
            if is_spacer:
                td = sub(tr, 'td')
                if spacer_width >= 1:
                    td.set('width', pct(spacer_width))
                continue
            item, width, nowrap, grow = next(cells)
            valign = valign_default
            if item.el is not None and item.style['align-self'] not in ('auto', None):
                valign = VALIGN.get(item.style['align-self'], 'top')
            td = sub(tr, 'td', valign=valign)
            if width:
                td.set('width', width)
            if nowrap:
                td.set('nowrap', 'nowrap')
            cell_avail = avail * float(width[:-1]) / 100 if width and width.endswith('%') else (
                float(width) if width else avail)
            self.fill_cell(td, item, s, cell_avail, shrink=not width and not grow)

    def text_of(self, item):
        if item.el is None:
            return item.text
        return ''.join(item.el.itertext())

    def grid(self, el, s, avail, shrink=False):
        root, table, cavail = self.frame(s, avail, shrink or s['display'] == 'inline-grid')
        column_gap = self.gap(s, 'column-gap', cavail)
        table.set('cellspacing', str(column_gap or self.gap(s, 'row-gap', cavail)))
        tracks = parse_tracks(s['grid-template-columns'], cavail, column_gap)
        areas = parse_areas(s['grid-template-areas'])
        ncols = max(len(tracks), max((len(r) for r in areas), default=0), 1)
        placed, ncols = place_items(self.items(el), ncols, areas)
        tracks += [{'kind': 'auto'}] * (ncols - len(tracks))
        widths = track_widths(tracks, cavail, column_gap)

        start = {(r, c): (item, rs, cs) for item, r, c, rs, cs in placed}
        covered = set()
        for item, r, c, rs, cs in placed:
            covered |= {(r + i, c + j) for i in range(rs) for j in range(cs)}
        nrows = max((r + rs for _, r, _, rs, _ in placed), default=0)
        valign_default = VALIGN.get(s['align-items'], 'top')

        for r in range(nrows):
            tr = sub(table, 'tr')
            for c in range(ncols):
                if (r, c) in start:
                    item, rs, cs = start[(r, c)]
                    td = sub(tr, 'td', valign=valign_default)
                    if item.el is not None and item.style['align-self'] not in ('auto', None):
                        td.set('valign', VALIGN.get(item.style['align-self'], 'top'))
                    if cs > 1:
                        td.set('colspan', str(cs))
                    if rs > 1:
                        td.set('rowspan', str(rs))
                    width, est = span_width(widths[c:c + cs], cavail, column_gap)
                    if width:
                        td.set('width', width)
                    self.fill_cell(td, item, s, est)
                elif (r, c) not in covered:
                    td = sub(tr, 'td')
                    width, _ = span_width(widths[c:c + 1], cavail, column_gap)
                    if width:
                        td.set('width', width)
        return root


# -- Grid helpers -------------------------------------------------------------

def parse_tracks(value, avail, gap):
    """Translate grid-template-columns into a list of track definitions."""
    if not value or value == 'none':
        return []
    out = []
    for t in tokens(value):
        if t.type == '[] block':
            continue  # line names
        if t.type == 'function' and t.lower_name == 'repeat':
            groups = split_commas(t.arguments)
            if len(groups) < 2 or not groups[0]:
                continue
            inner = parse_tracks(groups[1], avail, gap)
            count = groups[0][0]
            if count.type == 'number':
                out += inner * int(count.value)
            elif inner:  # auto-fill / auto-fit
                min_width = sum(t.get('min') or t.get('px') or 0 for t in inner)
                n = int((avail + gap) // (min_width + gap)) if min_width else 1
                out += inner * max(1, n)
            continue
        out.append(parse_track(t))
    return out


def parse_track(t):
    if t.type == 'dimension' and t.lower_unit == 'fr':
        return {'kind': 'fr', 'value': float(t.value)}
    if t.type == 'percentage':
        return {'kind': '%', 'value': float(t.value)}
    if t.type == 'function' and t.lower_name == 'minmax':
        groups = split_commas(t.arguments)
        if len(groups) == 2 and groups[0] and groups[1]:
            track = parse_track(groups[1][0])
            low = px(groups[0][0])
            if low:
                track['min'] = low
            return track
    if t.type in ('dimension', 'number'):
        n = px(t)
        if n is not None:
            return {'kind': 'px', 'px': n}
    return {'kind': 'auto'}


def track_widths(tracks, avail, gap):
    """Column widths as ('px', n), ('%', n) or None."""
    usable = max(1.0, avail - gap * (len(tracks) - 1))
    fixed_px = sum(t['px'] for t in tracks if t['kind'] == 'px')
    fixed_pct = sum(t['value'] for t in tracks if t['kind'] == '%')
    total_fr = sum(t['value'] for t in tracks if t['kind'] == 'fr')
    rest = max(0.0, 100 - fixed_pct - fixed_px * 100 / usable)
    out = []
    for t in tracks:
        if t['kind'] == 'fr':
            out.append(('%', rest * t['value'] / total_fr))
        elif t['kind'] == '%':
            out.append(('%', t['value']))
        elif t['kind'] == 'px':
            out.append(('px', t['px']))
        else:
            out.append(None)
    return out


def span_width(widths, avail, gap):
    """Width of a cell spanning several columns: attribute value and estimate in px."""
    if widths and all(w and w[0] == '%' for w in widths):
        total = sum(w[1] for w in widths)
        return pct(total), avail * total / 100
    if widths and all(w and w[0] == 'px' for w in widths):
        total = sum(w[1] for w in widths) + gap * (len(widths) - 1)
        return str(round(total)), total
    return None, avail


def parse_areas(value):
    if not value or value == 'none':
        return []
    return [t.value.split() for t in tokens(value) if t.type == 'string']


def area_rects(areas):
    rects = {}
    for r, row in enumerate(areas):
        for c, name in enumerate(row):
            if set(name) == {'.'}:
                continue
            r0, c0, r1, c1 = rects.get(name, (r, c, r + 1, c + 1))
            rects[name] = (min(r0, r), min(c0, c), max(r1, r + 1), max(c1, c + 1))
    return rects


def parse_line(value):
    value = (value or 'auto').strip()
    if value == 'auto' or not value:
        return None
    p = value.split()
    if p[0] == 'span':
        return ('span', int(p[1]) if len(p) > 1 and p[1].isdigit() else 1)
    try:
        return ('line', int(p[0]))
    except ValueError:
        return ('name', p[0])


def line_index(line, n, rects, axis, is_start):
    kind, value = line
    if kind == 'line':
        return value - 1 if value > 0 else max(0, n + 1 + value)
    name = value
    if name.endswith('-start'):
        name, is_start = name[:-6], True
    elif name.endswith('-end'):
        name, is_start = name[:-4], False
    rect = rects.get(name)
    if rect is None:
        return None
    return rect[axis] if is_start else rect[axis + 2]


def resolve_axis(start, end, n, rects, axis):
    """Start (0-based, or None for automatic) and span along one axis."""
    s, e = parse_line(start), parse_line(end)
    si = line_index(s, n, rects, axis, True) if s and s[0] != 'span' else None
    ei = line_index(e, n, rects, axis, False) if e and e[0] != 'span' else None
    span = s[1] if s and s[0] == 'span' else (e[1] if e and e[0] == 'span' else 1)
    if si is not None and ei is not None:
        if ei < si:
            si, ei = ei, si
        return si, max(1, ei - si)
    if si is not None:
        return si, span
    if ei is not None:
        return max(0, ei - span), span
    return None, span


def place_items(items, ncols, areas):
    """Place grid items in a grid (simplified auto-placement algorithm)."""
    rects = area_rects(areas)
    nrows = len(areas)
    specs = []
    for item in items:
        s = item.style
        if item.el is None:
            specs.append((item, (None, 1), (None, 1)))
            continue
        row = resolve_axis(s['grid-row-start'], s['grid-row-end'], nrows, rects, 0)
        col = resolve_axis(s['grid-column-start'], s['grid-column-end'], ncols, rects, 1)
        specs.append((item, row, col))
    for _, _, (c, cs) in specs:
        if c is not None:
            ncols = max(ncols, c + cs)

    occupied = set()
    placed = []

    def free(r, c, rs, cs):
        return c + cs <= ncols and all((r + i, c + j) not in occupied
                                       for i in range(rs) for j in range(cs))

    def put(item, r, c, rs, cs):
        occupied.update((r + i, c + j) for i in range(rs) for j in range(cs))
        placed.append((item, r, c, rs, cs))

    for item, (r, rs), (c, cs) in specs:
        if r is not None and c is not None:
            put(item, r, c, rs, cs)
    for item, (r, rs), (c, cs) in specs:
        if r is not None and c is None:
            cs = min(cs, ncols)
            c = next((c for c in range(ncols - cs + 1) if free(r, c, rs, cs)), 0)
            put(item, r, c, rs, cs)
    cur_r, cur_c = 0, 0
    for item, (r, rs), (c, cs) in specs:
        if r is not None:
            continue
        if c is not None:
            if c < cur_c:
                cur_r += 1
            while not free(cur_r, c, rs, cs):
                cur_r += 1
            put(item, cur_r, c, rs, cs)
            cur_c = c + cs
            continue
        cs = min(cs, ncols)
        while True:
            if cur_c + cs > ncols:
                cur_r, cur_c = cur_r + 1, 0
                continue
            if free(cur_r, cur_c, rs, cs):
                put(item, cur_r, cur_c, rs, cs)
                cur_c += cs
                break
            cur_c += 1
    placed.sort(key=lambda p: (p[1], p[2]))
    return placed, ncols


# -- Public interface ---------------------------------------------------------

def _newlines(node):
    """Line breaks between table rows, so the output stays readable."""
    for el in node.iter('table', 'tr'):
        if el.tail is None or not el.tail.strip():
            el.tail = '\n' + (el.tail or '').lstrip('\n')
        if el.tag == 'table' and len(el) and not el.text:
            el.text = '\n'


def convert(html, viewport_width=800, base_url=None, load_stylesheet=None):
    """Convert HTML text (str or bytes) into HTML 4.01 with a table layout.

    viewport_width: assumed screen width for media queries and estimates.
    base_url: relative links and images are made absolute against it.
    load_stylesheet: function url -> CSS text (or None) for <link>/@import.
    """
    doc = lxml.html.document_fromstring(html)
    if base_url:
        doc.make_links_absolute(base_url, resolve_base_href=True)
    out = Converter(doc, viewport_width, load_stylesheet).build()
    _newlines(out)
    result = lxml.html.tostring(out, doctype=DOCTYPE, encoding='unicode', method='html')
    meta = '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
    return result.replace('<head>', '<head>\n' + meta, 1)
