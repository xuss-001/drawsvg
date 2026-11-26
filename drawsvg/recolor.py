'''Recolor selected drawing elements without modifying the original drawing.

The public entry point is :func:`recolor`, which is also exposed as
``Drawing.recolor()``.  Color matching is based on RGB values, so equivalent
names, hex values, and ``rgb()``/``rgba()`` values all match the same key.
'''

import copy
import re
from dataclasses import dataclass

from .types import DrawingElement


class RecolorError(ValueError):
    '''Base error raised when a drawing cannot be recolored safely.'''


class UnsupportedExternalResourceError(RecolorError):
    '''Raised when a selected element depends on an unsupported external
    stylesheet or resource.'''


@dataclass(frozen=True)
class _Color:
    r: int
    g: int
    b: int
    alpha: float
    alpha_text: str
    raw: str

    @property
    def rgb(self):
        return self.r, self.g, self.b


_NAMED_COLORS = {
    'aliceblue': 'f0f8ff', 'antiquewhite': 'faebd7', 'aqua': '00ffff',
    'aquamarine': '7fffd4', 'azure': 'f0ffff', 'beige': 'f5f5dc',
    'bisque': 'ffe4c4', 'black': '000000', 'blanchedalmond': 'ffebcd',
    'blue': '0000ff', 'blueviolet': '8a2be2', 'brown': 'a52a2a',
    'burlywood': 'deb887', 'cadetblue': '5f9ea0', 'chartreuse': '7fff00',
    'chocolate': 'd2691e', 'coral': 'ff7f50', 'cornflowerblue': '6495ed',
    'cornsilk': 'fff8dc', 'crimson': 'dc143c', 'cyan': '00ffff',
    'darkblue': '00008b', 'darkcyan': '008b8b', 'darkgoldenrod': 'b8860b',
    'darkgray': 'a9a9a9', 'darkgreen': '006400', 'darkgrey': 'a9a9a9',
    'darkkhaki': 'bdb76b', 'darkmagenta': '8b008b',
    'darkolivegreen': '556b2f', 'darkorange': 'ff8c00',
    'darkorchid': '9932cc', 'darkred': '8b0000', 'darksalmon': 'e9967a',
    'darkseagreen': '8fbc8f', 'darkslateblue': '483d8b',
    'darkslategray': '2f4f4f', 'darkslategrey': '2f4f4f',
    'darkturquoise': '00ced1', 'darkviolet': '9400d3',
    'deeppink': 'ff1493', 'deepskyblue': '00bfff', 'dimgray': '696969',
    'dimgrey': '696969', 'dodgerblue': '1e90ff', 'firebrick': 'b22222',
    'floralwhite': 'fffaf0', 'forestgreen': '228b22', 'fuchsia': 'ff00ff',
    'gainsboro': 'dcdcdc', 'ghostwhite': 'f8f8ff', 'gold': 'ffd700',
    'goldenrod': 'daa520', 'gray': '808080', 'green': '008000',
    'greenyellow': 'adff2f', 'grey': '808080', 'honeydew': 'f0fff0',
    'hotpink': 'ff69b4', 'indianred': 'cd5c5c', 'indigo': '4b0082',
    'ivory': 'fffff0', 'khaki': 'f0e68c', 'lavender': 'e6e6fa',
    'lavenderblush': 'fff0f5', 'lawngreen': '7cfc00',
    'lemonchiffon': 'fffacd', 'lightblue': 'add8e6',
    'lightcoral': 'f08080', 'lightcyan': 'e0ffff',
    'lightgoldenrodyellow': 'fafad2', 'lightgray': 'd3d3d3',
    'lightgreen': '90ee90', 'lightgrey': 'd3d3d3', 'lightpink': 'ffb6c1',
    'lightsalmon': 'ffa07a', 'lightseagreen': '20b2aa',
    'lightskyblue': '87cefa', 'lightslategray': '778899',
    'lightslategrey': '778899', 'lightsteelblue': 'b0c4de',
    'lightyellow': 'ffffe0', 'lime': '00ff00', 'limegreen': '32cd32',
    'linen': 'faf0e6', 'magenta': 'ff00ff', 'maroon': '800000',
    'mediumaquamarine': '66cdaa', 'mediumblue': '0000cd',
    'mediumorchid': 'ba55d3', 'mediumpurple': '9370db',
    'mediumseagreen': '3cb371', 'mediumslateblue': '7b68ee',
    'mediumspringgreen': '00fa9a', 'mediumturquoise': '48d1cc',
    'mediumvioletred': 'c71585', 'midnightblue': '191970',
    'mintcream': 'f5fffa', 'mistyrose': 'ffe4e1', 'moccasin': 'ffe4b5',
    'navajowhite': 'ffdead', 'navy': '000080', 'oldlace': 'fdf5e6',
    'olive': '808000', 'olivedrab': '6b8e23', 'orange': 'ffa500',
    'orangered': 'ff4500', 'orchid': 'da70d6',
    'palegoldenrod': 'eee8aa', 'palegreen': '98fb98',
    'paleturquoise': 'afeeee', 'palevioletred': 'db7093',
    'papayawhip': 'ffefd5', 'peachpuff': 'ffdab9', 'peru': 'cd853f',
    'pink': 'ffc0cb', 'plum': 'dda0dd', 'powderblue': 'b0e0e6',
    'purple': '800080', 'rebeccapurple': '663399', 'red': 'ff0000',
    'rosybrown': 'bc8f8f', 'royalblue': '4169e1', 'saddlebrown': '8b4513',
    'salmon': 'fa8072', 'sandybrown': 'f4a460', 'seagreen': '2e8b57',
    'seashell': 'fff5ee', 'sienna': 'a0522d', 'silver': 'c0c0c0',
    'skyblue': '87ceeb', 'slateblue': '6a5acd', 'slategray': '708090',
    'slategrey': '708090', 'snow': 'fffafa', 'springgreen': '00ff7f',
    'steelblue': '4682b4', 'tan': 'd2b48c', 'teal': '008080',
    'thistle': 'd8bfd8', 'tomato': 'ff6347', 'turquoise': '40e0d0',
    'violet': 'ee82ee', 'wheat': 'f5deb3', 'white': 'ffffff',
    'whitesmoke': 'f5f5f5', 'yellow': 'ffff00', 'yellowgreen': '9acd32',
}

_SPECIAL_COLORS = {
    'none', 'currentcolor', 'inherit', 'unset', 'initial',
    'context-fill', 'context-stroke',
}
_PAINT_PROPERTIES = {
    'fill', 'stroke', 'color', 'stop-color', 'flood-color', 'lighting-color',
}
_INHERITED_PROPERTIES = {'fill', 'stroke', 'color'}
_URL_RE = re.compile(r'''url\(\s*(['"]?)(.*?)\1\s*\)''', re.IGNORECASE)
_RGB_RE = re.compile(r'^(rgba?|hsla?)\((.*)\)$', re.IGNORECASE)
_HEX_RE = re.compile(r'^#([0-9a-fA-F]{3,8})$')


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _format_float(value):
    text = ('{:.6f}'.format(value)).rstrip('0').rstrip('.')
    return text or '0'


def _alpha_from_text(text):
    text = text.strip()
    if text.endswith('%'):
        return _clamp(float(text[:-1]) / 100)
    return _clamp(float(text))


def _parse_hue(text):
    text = text.strip().lower()
    if text.endswith('deg'):
        return float(text[:-3]) / 360
    if text.endswith('turn'):
        return float(text[:-4])
    if text.endswith('rad'):
        return float(text[:-3]) / (2 * 3.141592653589793)
    if text.endswith('grad'):
        return float(text[:-4]) / 400
    return float(text) / 360


def _hsl_to_rgb(h, s, light):
    h = h % 1
    s = _clamp(s)
    light = _clamp(light)
    chroma = (1 - abs(2 * light - 1)) * s
    x = chroma * (1 - abs((h * 6) % 2 - 1))
    if h < 1 / 6:
        r, g, b = chroma, x, 0
    elif h < 2 / 6:
        r, g, b = x, chroma, 0
    elif h < 3 / 6:
        r, g, b = 0, chroma, x
    elif h < 4 / 6:
        r, g, b = 0, x, chroma
    elif h < 5 / 6:
        r, g, b = x, 0, chroma
    else:
        r, g, b = chroma, 0, x
    m = light - chroma / 2
    return tuple(round((v + m) * 255) for v in (r, g, b))


def _split_function_args(body):
    body = body.strip()
    if '/' in body:
        main, alpha = body.split('/', 1)
        return re.split(r'[,\s]+', main.strip()), alpha.strip()
    parts = [v for v in re.split(r'[,\s]+', body) if v]
    if len(parts) == 4 and ',' in body:
        return parts[:3], parts[3]
    return parts, None


def _parse_function_color(name, body, raw):
    parts, alpha_text = _split_function_args(body)
    if len(parts) != 3:
        raise ValueError('expected three color components')
    if name == 'rgb':
        values = []
        for part in parts:
            if part.endswith('%'):
                values.append(round(_clamp(float(part[:-1]) / 100) * 255))
            else:
                values.append(round(_clamp(float(part) / 255) * 255))
        r, g, b = values
    else:
        h = _parse_hue(parts[0])
        s = float(parts[1].rstrip('%')) / 100
        light = float(parts[2].rstrip('%')) / 100
        r, g, b = _hsl_to_rgb(h, s, light)
    alpha = 1.0 if alpha_text is None else _alpha_from_text(alpha_text)
    return _Color(
        int(r), int(g), int(b), alpha,
        _format_float(alpha), raw)


def _parse_color(value):
    '''Parse a CSS color. Return None for non-color values or invalid input.'''
    if not isinstance(value, str):
        return None
    raw = value.strip()
    lower = raw.lower()
    if lower in _SPECIAL_COLORS or lower == 'transparent':
        if lower == 'transparent':
            return _Color(0, 0, 0, 0, '0', raw)
        return None
    if lower in _NAMED_COLORS:
        hex_value = _NAMED_COLORS[lower]
        return _Color(
            int(hex_value[0:2], 16), int(hex_value[2:4], 16),
            int(hex_value[4:6], 16), 1.0, '1', raw)
    match = _HEX_RE.match(raw)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            digits = ''.join(ch * 2 for ch in digits)
        if len(digits) not in (6, 8):
            return None
        alpha_text = '1'
        alpha = 1.0
        if len(digits) == 8:
            alpha = int(digits[6:8], 16) / 255
            alpha_text = _format_float(alpha)
        return _Color(
            int(digits[0:2], 16), int(digits[2:4], 16),
            int(digits[4:6], 16), alpha, alpha_text, raw)
    match = _RGB_RE.match(raw)
    if match:
        name = match.group(1).lower()
        if name.startswith('rgb'):
            name = 'rgb'
        else:
            name = 'hsl'
        try:
            return _parse_function_color(name, match.group(2), raw)
        except (TypeError, ValueError):
            return None
    return None


def _without_alpha(color):
    raw = color.raw.strip()
    if raw.startswith('#'):
        digits = raw[1:]
        if len(digits) == 4:
            return '#' + ''.join(ch * 2 for ch in digits[:3])
        if len(digits) == 8:
            return '#' + digits[:6]
        return raw
    if color.raw.lower().startswith('rgba'):
        return 'rgb({}, {}, {})'.format(color.r, color.g, color.b)
    if color.raw.lower().startswith('hsla'):
        return '#{:02x}{:02x}{:02x}'.format(color.r, color.g, color.b)
    if color.raw.lower() == 'transparent':
        return 'rgb(0, 0, 0)'
    return color.raw


def _replacement_text(color, original):
    if original.alpha >= 1 and color.alpha >= 1:
        return color.raw
    if original.alpha >= 1:
        return _without_alpha(color)
    return 'rgba({}, {}, {}, {})'.format(
        color.r, color.g, color.b, original.alpha_text)


def _normalize_replacements(replacements):
    if replacements is None:
        raise TypeError('missing color replacement mapping')
    if not hasattr(replacements, 'items'):
        raise TypeError('color replacements must be a mapping')
    normalized = {}
    for source, target in replacements.items():
        source_color = _parse_color(source)
        if source_color is None:
            raise ValueError(
                'invalid source color in replacement mapping: {!r}'.format(
                    source))
        if not isinstance(target, str):
            raise TypeError(
                'replacement color must be a string, got {!r}'.format(target))
        target_color = _parse_color(target)
        if target_color is None and target.strip().lower() not in _SPECIAL_COLORS:
            raise ValueError(
                'invalid replacement color: {!r}'.format(target))
        normalized[source_color.rgb] = target
    return normalized


def _split_css_declarations(value):
    pieces = []
    start = 0
    depth = 0
    quote = None
    for i, char in enumerate(value):
        if quote is not None:
            if char == quote and (i == 0 or value[i - 1] != '\\'):
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth = max(0, depth - 1)
        elif char == ';' and depth == 0:
            pieces.append(value[start:i])
            start = i + 1
    pieces.append(value[start:])
    return pieces


def _parse_style(style):
    declarations = []
    for piece in _split_css_declarations(style):
        if not piece.strip():
            continue
        if ':' not in piece:
            declarations.append((None, piece.strip(), '', None))
            continue
        name, value = piece.split(':', 1)
        name = name.strip().lower()
        original_value = value.strip()
        important = ''
        match = re.search(r'\s*!important\s*$', original_value, re.IGNORECASE)
        if match:
            important = original_value[match.start():].strip()
            original_value = original_value[:match.start()].strip()
        declarations.append((name, original_value, important, value))
    return declarations


def _write_style(declarations):
    output = []
    for name, value, important, _ in declarations:
        if name is None:
            output.append(value)
        else:
            suffix = ' ' + important if important else ''
            output.append('{}: {}{}'.format(name, value, suffix))
    return '; '.join(output)


def _style_values(style):
    if not isinstance(style, str):
        return {}
    return {
        name: value for name, value, _, _ in _parse_style(style)
        if name is not None
    }


def _iter_urls(value):
    if not isinstance(value, str):
        return
    for match in _URL_RE.finditer(value):
        yield match.group(0), match.group(2).strip()


def _is_local_ref(value):
    return isinstance(value, str) and value.startswith('#')


def _is_external_url(value):
    value = value.strip()
    return not (value.startswith('#') or value.lower().startswith('data:'))


def _iter_direct_children(element):
    children = list(getattr(element, 'children', ()))
    ordered = getattr(element, 'ordered_children', None)
    if ordered:
        for key in sorted(ordered):
            children.extend(ordered[key])
    for value in getattr(element, 'args', {}).values():
        if isinstance(value, DrawingElement):
            children.append(value)
    return children


def _iter_visual_children(element):
    children = list(getattr(element, 'children', ()))
    ordered = getattr(element, 'ordered_children', None)
    if ordered:
        for key in sorted(ordered):
            children.extend(ordered[key])
    return children


def _walk_elements(roots):
    seen = set()
    stack = list(roots)
    while stack:
        element = stack.pop()
        if not isinstance(element, DrawingElement) or id(element) in seen:
            continue
        seen.add(id(element))
        yield element
        stack.extend(_iter_direct_children(element))


def _drawing_roots(drawing):
    return list(drawing.all_elements()) + list(drawing.other_defs)


def _build_index(drawing):
    parent = {}
    by_id = {}
    roots = _drawing_roots(drawing)
    for root in roots:
        if isinstance(root, DrawingElement):
            parent[id(root)] = drawing
    for element in _walk_elements(roots):
        element_id = getattr(element, 'id', None)
        if element_id is not None and element_id not in by_id:
            by_id[element_id] = element
        for child in _iter_direct_children(element):
            parent[id(child)] = element
    return parent, by_id


def _ancestor_chain(element, parent):
    output = []
    current = parent.get(id(element))
    while isinstance(current, DrawingElement):
        output.append(current)
        current = parent.get(id(current))
    return output


def _effective_inherited(element, parent, prop):
    values = []
    for ancestor in reversed(_ancestor_chain(element, parent)):
        style = _style_values(getattr(ancestor, 'args', {}).get('style'))
        if prop in style:
            values.append(style[prop])
        elif getattr(ancestor, 'args', {}).get(prop) is not None:
            values.append(ancestor.args[prop])
    current = None
    for value in values:
        lower = value.strip().lower() if isinstance(value, str) else ''
        if lower in ('inherit', 'unset'):
            continue
        current = value
    return current


def _external_stylesheet(css_list):
    for css in css_list:
        if not isinstance(css, str):
            continue
        if re.search(r'@import\b', css, re.IGNORECASE):
            return True
        for _, url in _iter_urls(css):
            if _is_external_url(url):
                return True
    return False


def _validate_selected(drawing, selected, selected_roots, by_id, parent):
    css_list = drawing.all_css()
    if _external_stylesheet(css_list):
        raise UnsupportedExternalResourceError(
            'selected elements may depend on an external stylesheet, '
            'which recolor() does not support')
    if css_list:
        for element in selected_roots:
            for candidate in [element, *_ancestor_chain(element, parent)]:
                if 'class' in candidate.args and (
                        candidate.args['class'] is not None):
                    raise RecolorError(
                        'selected elements depend on a CSS stylesheet; '
                        'recolor() cannot evaluate CSS selectors')
    checked = set()
    stack = list(selected_roots)
    while stack:
        element = stack.pop()
        if not isinstance(element, DrawingElement) or id(element) in checked:
            continue
        checked.add(id(element))
        for key, value in element.args.items():
            if isinstance(value, str):
                if key in ('href', 'xlink:href'):
                    if (not value.startswith('#') and
                            not value.lower().startswith('data:') and
                            key == 'xlink:href'):
                        raise UnsupportedExternalResourceError(
                            'selected element references an external '
                            'resource: {!r}'.format(value))
                    if (key == 'href' and element.TAG_NAME in {
                            'use', 'image', 'textPath', 'mpath', 'pattern',
                            'filter', 'feImage', 'linearGradient',
                            'radialGradient'} and not _is_local_ref(value)
                            and not value.lower().startswith('data:')):
                        raise UnsupportedExternalResourceError(
                            'selected element references an external '
                            'resource: {!r}'.format(value))
                if key == 'style':
                    style_value = ';'.join(
                        style_value for _, style_value, _, _ in
                        _parse_style(value))
                else:
                    style_value = value
                for raw_url, url in _iter_urls(style_value):
                    if _is_external_url(url):
                        raise UnsupportedExternalResourceError(
                            'selected element references an external '
                            'resource: {!r}'.format(raw_url))
                    if url.startswith('#'):
                        target = by_id.get(url[1:])
                        if target is not None:
                            stack.append(target)
                if (_is_local_ref(value) and
                        key in ('href', 'xlink:href')):
                    target = by_id.get(value[1:])
                    if target is not None:
                        stack.append(target)
            elif value is not None and not isinstance(value, DrawingElement):
                continue
        if (getattr(element, 'TAG_NAME', '') == 'Raw'
                or element.__class__.__name__ == 'Raw'):
            content = getattr(element, 'content', '')
            if re.search(r'<link\b|@import\b', content, re.IGNORECASE):
                raise UnsupportedExternalResourceError(
                    'selected Raw element contains an external stylesheet')
            if re.search(
                    r'''(?:href|xlink:href)\s*=\s*["'](?:https?:|file:|\.{0,2}/)''',
                    content, re.IGNORECASE):
                raise UnsupportedExternalResourceError(
                    'selected Raw element references an external resource')
            for _, url in _iter_urls(content):
                if _is_external_url(url):
                    raise UnsupportedExternalResourceError(
                        'selected Raw element references an external '
                        'resource: {!r}'.format(url))
        stack.extend(_iter_direct_children(element))
    selected_style = _style_values(selected.args.get('style'))
    for prop in _INHERITED_PROPERTIES:
        local_value = selected_style.get(prop, selected.args.get(prop))
        local_lower = (local_value.strip().lower()
                       if isinstance(local_value, str) else '')
        if local_value is not None and local_lower not in ('inherit', 'unset'):
            continue
        value = _effective_inherited(selected, parent, prop)
        if isinstance(value, str):
            for raw_url, url in _iter_urls(value):
                if _is_external_url(url):
                    raise UnsupportedExternalResourceError(
                        'selected element inherits a reference to an '
                        'external resource: {!r}'.format(raw_url))


class _PrivateResourceManager:
    def __init__(self, drawing, replacements):
        self.replacements = replacements
        self.by_id = {}
        for element in _walk_elements(_drawing_roots(drawing)):
            element_id = getattr(element, 'id', None)
            if element_id is not None and element_id not in self.by_id:
                self.by_id[element_id] = element
        self.clone_map = {}
        self.clone_memo = {}
        self.private_objects = set()
        self.private_roots = []
        self.prepared = set()
        self.old_ids = {}
        self.generated_ids = {}
        self.used_ids = set(self.by_id)
        self.id_counter = 0

    def _new_id(self, old_id):
        while True:
            base = old_id if old_id else 'resource'
            candidate = '{}__recolor{}'.format(base, self.id_counter)
            self.id_counter += 1
            if candidate not in self.used_ids:
                self.used_ids.add(candidate)
                return candidate

    def _register_graph(self, root):
        for element in _walk_elements([root]):
            self.private_objects.add(id(element))
            old_id = getattr(element, 'id', None)
            if old_id is not None:
                previous = self.old_ids.get(old_id)
                if previous is not None and previous is not element:
                    raise RecolorError(
                        'duplicate id {!r} in selected resource graph'.format(
                            old_id))
                self.old_ids[old_id] = element

    def _assign_ids(self, root, force_root=False):
        for index, element in enumerate(_walk_elements([root])):
            self.private_objects.add(id(element))
            old_id = getattr(element, 'id', None)
            if old_id is None and not (force_root and index == 0):
                continue
            if old_id is not None:
                previous = self.old_ids.get(old_id)
                if previous is not None and previous is not element:
                    raise RecolorError(
                        'duplicate id {!r} in selected resource graph'.format(
                            old_id))
            new_id = self._new_id(old_id)
            element.args['id'] = new_id
            self.generated_ids[new_id] = element
            if old_id is not None:
                self.old_ids[old_id] = element

    def resolve(self, element_id):
        if element_id in self.generated_ids:
            return self.generated_ids[element_id]
        if element_id in self.old_ids:
            return self.old_ids[element_id]
        target = self.by_id.get(element_id)
        if target is None:
            return None
        return self.clone_def(target)

    def clone_def(self, element):
        if not isinstance(element, DrawingElement):
            return element
        if id(element) in self.private_objects:
            return element
        if id(element) in self.clone_map:
            return self.clone_map[id(element)]
        clone = copy.deepcopy(element, self.clone_memo)
        self.clone_map[id(element)] = clone
        self.private_roots.append(clone)
        self.prepared.add(id(clone))
        self._register_graph(clone)
        self._assign_ids(clone, force_root=True)
        _recolor_tree(
            clone, self.replacements, {}, False, self,
            materialize_inherited=False)
        _rewrite_references(clone, self)
        return clone

    def prepare_value(self, value, prop, inherited_value=None):
        if isinstance(value, DrawingElement):
            return self.clone_def(value)
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        lower = stripped.lower()
        if lower in ('inherit', 'unset'):
            value = inherited_value
            if value is None:
                return None
            stripped = value.strip() if isinstance(value, str) else ''
            lower = stripped.lower()
        if isinstance(value, DrawingElement):
            return self.clone_def(value)
        match = _URL_RE.fullmatch(stripped)
        if match:
            target = match.group(2).strip()
            if target.startswith('#'):
                clone = self.resolve(target[1:])
                if clone is None:
                    raise RecolorError(
                        'cannot resolve local resource {!r}'.format(target))
                return clone
            return value
        if prop in ('href', 'xlink:href'):
            if _is_local_ref(stripped):
                clone = self.resolve(stripped[1:])
                if clone is None:
                    raise RecolorError(
                        'cannot resolve local resource {!r}'.format(stripped))
                return clone
            return value
        return _recolor_color_text(value, self.replacements)


def _recolor_color_text(value, replacements):
    color = _parse_color(value)
    if color is None:
        return value
    target = replacements.get(color.rgb)
    if target is None:
        return value
    target_special = target.strip().lower()
    if target_special in _SPECIAL_COLORS:
        return target.strip()
    target_color = _parse_color(target)
    return _replacement_text(target_color, color)


def _rewrite_urls(value, manager):
    def replace(match):
        target = match.group(2).strip()
        if not target.startswith('#'):
            return match.group(0)
        clone = manager.resolve(target[1:])
        if clone is None:
            raise RecolorError(
                'cannot resolve local resource {!r}'.format(target))
        new_id = getattr(clone, 'id', None)
        if new_id is None:
            raise RecolorError(
                'local resource {!r} has no generated id'.format(target))
        return 'url(#{})'.format(new_id)
    return _URL_RE.sub(replace, value)


def _rewrite_references(root, manager):
    for element in _walk_elements([root]):
        for key, value in list(element.args.items()):
            if isinstance(value, DrawingElement):
                if id(value) in manager.private_objects:
                    continue
                element.args[key] = manager.clone_def(value)
            elif isinstance(value, str):
                stripped = value.strip()
                url_match = _URL_RE.fullmatch(stripped)
                if url_match and url_match.group(2).strip().startswith('#'):
                    target = url_match.group(2).strip()[1:]
                    clone = manager.resolve(target)
                    if clone is None:
                        raise RecolorError(
                            'cannot resolve local resource {!r}'.format(
                                target))
                    element.args[key] = clone
                elif (key in ('href', 'xlink:href') and
                      _is_local_ref(stripped)):
                    clone = manager.resolve(stripped[1:])
                    if clone is None:
                        raise RecolorError(
                            'cannot resolve local resource {!r}'.format(
                                stripped))
                    element.args[key] = clone
                elif 'url(' in value.lower():
                    element.args[key] = _rewrite_urls(value, manager)


def _recolor_style(style, replacements, inherited, manager):
    declarations = _parse_style(style)
    changed = False
    for index, (name, value, important, _) in enumerate(declarations):
        if name not in _PAINT_PROPERTIES:
            continue
        inherited_value = inherited.get(name) if name in _INHERITED_PROPERTIES else None
        new_value = manager.prepare_value(value, name, inherited_value)
        if new_value is None:
            continue
        if isinstance(new_value, DrawingElement):
            new_value = 'url(#{})'.format(new_value.id)
        if new_value != value:
            declarations[index] = (name, new_value, important, value)
            changed = True
    return _write_style(declarations) if changed else style


def _recolor_tree(element, replacements, inherited, is_root, manager,
                  materialize_inherited=True, seen=None):
    if seen is None:
        seen = set()
    if id(element) in seen:
        return
    seen.add(id(element))
    args = getattr(element, 'args', None)
    if args is None:
        return
    style_map = _style_values(args.get('style'))
    effective = dict(inherited)

    if 'style' in args and isinstance(args['style'], str):
        new_style = _recolor_style(
            args['style'], replacements, inherited, manager)
        if new_style != args['style']:
            args['style'] = new_style
        style_map = _style_values(args['style'])

    for prop in _PAINT_PROPERTIES:
        style_has_prop = prop in style_map
        if style_has_prop:
            local_value = style_map[prop]
        elif prop in args:
            local_value = args[prop]
        else:
            local_value = None

        if prop in _INHERITED_PROPERTIES:
            lower = (local_value.strip().lower()
                     if isinstance(local_value, str) else '')
            if local_value is None or lower in ('inherit', 'unset'):
                effective[prop] = inherited.get(prop)
            else:
                effective[prop] = local_value

        if prop in args and not style_has_prop:
            original = args[prop]
            new_value = manager.prepare_value(
                original, prop, inherited.get(prop))
            if new_value is not None and new_value != original:
                args[prop] = new_value
            elif isinstance(original, str):
                lower = original.strip().lower()
                if lower in ('inherit', 'unset') and new_value is not None:
                    args[prop] = new_value

        if (is_root and materialize_inherited and prop in _INHERITED_PROPERTIES
                and not style_has_prop and prop not in args):
            inherited_value = inherited.get(prop)
            if inherited_value is not None:
                new_value = manager.prepare_value(
                    inherited_value, prop, inherited_value)
                if new_value != inherited_value:
                    args[prop] = new_value

    for child in _iter_visual_children(element):
        _recolor_tree(
            child, replacements, effective, False, manager,
            materialize_inherited=False, seen=seen)


def _normalize_selected(drawing, elements, selection):
    if elements is not None and selection is not None:
        raise TypeError('specify only one of elements and selection')
    selected = selection if selection is not None else elements
    by_id = _build_index(drawing)[1]
    if selected is None:
        roots = list(drawing.all_elements())
    elif isinstance(selected, DrawingElement):
        roots = [selected]
    elif isinstance(selected, str):
        root = by_id.get(selected)
        if root is None:
            raise ValueError('unknown element id: {!r}'.format(selected))
        roots = [root]
    else:
        roots = []
        for item in selected:
            if isinstance(item, str):
                root = by_id.get(item)
                if root is None:
                    raise ValueError('unknown element id: {!r}'.format(item))
                roots.append(root)
            else:
                roots.append(item)
    unique_roots = []
    seen_roots = set()
    for root in roots:
        if not isinstance(root, DrawingElement):
            raise TypeError(
                'selected elements must be DrawingElement instances, '
                'got {!r}'.format(root))
        if id(root) not in seen_roots:
            unique_roots.append(root)
            seen_roots.add(id(root))
    roots = unique_roots
    roots = [
        root for root in roots
        if not any(id(root) in
                   {id(grandchild) for grandchild in
                    _walk_elements(_iter_direct_children(other))}
                   for other in roots if other is not root)
    ]
    return roots


def _merge_replacements(replacements, colors, color_map, palette):
    supplied = [
        value for value in (replacements, colors, color_map, palette)
        if value is not None
    ]
    if len(supplied) > 1:
        raise TypeError('specify only one color replacement mapping')
    if not supplied:
        raise TypeError('missing color replacement mapping')
    return _normalize_replacements(supplied[0])


def recolor(drawing, replacements=None, elements=None, *, colors=None,
            color_map=None, palette=None, selection=None):
    '''Return a recolored copy of ``drawing``.

    Args:
        drawing: The source :class:`drawsvg.Drawing`. It is not modified.
        replacements: Mapping of old colors to new colors. Source colors are
            matched by RGB value, so ``'red'``, ``'#ff0000'``, and
            ``'rgb(255, 0, 0)'`` are equivalent. Replacement alpha is ignored;
            the source color's alpha is retained.
        elements: A selected element, element id, or iterable of elements.
            Selecting a group selects its descendants. If omitted, all visible
            top-level elements are selected.
        colors, color_map, palette: Aliases for ``replacements``.
        selection: Alias for ``elements``.

    Raises:
        UnsupportedExternalResourceError: If a selected element depends on an
            external stylesheet or external resource.
        RecolorError: If a selected local resource or gradient reference
            cannot be resolved safely.
    '''
    from .drawing import Drawing
    if not isinstance(drawing, Drawing):
        raise TypeError('drawing must be a drawsvg.Drawing')
    normalized = _merge_replacements(replacements, colors, color_map, palette)
    roots = _normalize_selected(drawing, elements, selection)
    parent, by_id = _build_index(drawing)
    for root in roots:
        _validate_selected(drawing, root, [root], by_id, parent)

    memo = {}
    themed = copy.deepcopy(drawing, memo)
    manager = _PrivateResourceManager(themed, normalized)
    for original_root in roots:
        copied_root = memo.get(id(original_root))
        if copied_root is None:
            raise RecolorError('selected element is not part of the drawing')
        inherited = {
            prop: _effective_inherited(original_root, parent, prop)
            for prop in _INHERITED_PROPERTIES
        }
        _recolor_tree(
            copied_root, normalized, inherited, True, manager,
            materialize_inherited=True)
        _rewrite_references(copied_root, manager)
    from .defs import DrawingDef
    appended = {id(element) for element in themed.other_defs}
    for resource in manager.private_roots:
        if isinstance(resource, DrawingElement) and id(resource) not in appended:
            themed.other_defs.append(resource)
            appended.add(id(resource))
        for element in _walk_elements([resource]):
            if isinstance(element, DrawingDef) and id(element) not in appended:
                themed.other_defs.append(element)
                appended.add(id(element))
    return themed


def replace_colors(drawing, replacements=None, elements=None, *, colors=None,
                   color_map=None, palette=None, selection=None):
    '''Alias for :func:`recolor`.'''
    return recolor(
        drawing, replacements, elements, colors=colors, color_map=color_map,
        palette=palette, selection=selection)
