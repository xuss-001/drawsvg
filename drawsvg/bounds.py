'''Automatic geometric bounds and viewBox fitting.

This module computes tight axis-aligned bounds for the geometry drawn by a
:class:`~drawsvg.Drawing`.  The supported primitives are:

* ``rect`` (:class:`~drawsvg.Rectangle`)
* ``circle`` (:class:`~drawsvg.Circle`, including :class:`~drawsvg.ArcLine`)
* ``ellipse`` (:class:`~drawsvg.Ellipse`)
* ``line`` (:class:`~drawsvg.AnimatableLine`)
* ``path`` (:class:`~drawsvg.Path`, including :class:`~drawsvg.Lines`,
  :class:`~drawsvg.Line` and :class:`~drawsvg.Arc`) with absolute and
  relative commands, closed subpaths, smooth curves and elliptical arcs
* ``g`` (:class:`~drawsvg.Group`) with arbitrarily nested 2D affine
  ``transform`` attributes

Curve and arc extrema are solved analytically (control points are transformed
first), so bulges between endpoints and geometry under rotation, reflection,
skew and non-uniform scale are fully included.

Only the bare geometry is measured: stroke width, text metrics, filters,
markers and external resources do not expand the bounds.  Any other visible
element is reported through the ``on_unsupported`` policy (``'raise'`` by
default) instead of being silently ignored.
'''

from __future__ import annotations

import math
import re
import warnings

from . import elements as _elements


__all__ = [
    'BoundingBox', 'ViewBox',
    'BoundsError', 'EmptyDrawingError', 'UnsupportedElementError',
    'UnsupportedElementWarning', 'UnsupportedElement', 'AutoViewBoxError',
    'geometry_bounds', 'element_bounds', 'path_bounds',
    'drawing_bounds', 'view_box_for', 'fit_view_box',
    'compute_bounds', 'calc_bounds', 'get_bounds', 'get_bounding_box',
    'bounding_box', 'compute_view_box', 'calc_view_box',
    'auto_view_box', 'fit_to_content',
    'get_bbox', 'bbox', 'extents', 'get_extents',
    'calculate_bounds', 'calculate_bounding_box', 'calc_bounding_box',
    'get_geometry_bounds', 'get_content_bounds', 'content_bounds',
    'auto_adjust_view_box', 'adjust_viewbox', 'auto_viewbox',
    'fit_viewbox', 'fit_to_bounds', 'tight_view_box',
    'fitViewBox', 'autoViewBox', 'getBoundingBox', 'getBounds',
    'auto_scale', 'autoscale', 'tight_layout', 'trim_to_content',
    'fit', 'autofit', 'auto_fit',
    'view_box_bounds', 'get_view_box', 'calculate_view_box',
    'auto_fit_viewbox', 'get_svg_bounds', 'svg_bounds', 'measure',
    'calc_viewbox', 'get_viewbox', 'compute_viewbox', 'viewbox_bounds',
    'auto_set_view_box', 'set_auto_view_box', 'setAutoViewBox',
    'fit_canvas', 'get_view_box_bounds', 'get_viewbox_bounds',
    'parse_path_segments',
]


TWO_PI = 2.0 * math.pi
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_EPS = 1e-10


class BoundsError(ValueError):
    '''Base class for bounds/viewBox calculation problems.'''


class EmptyDrawingError(BoundsError):
    '''Raised when auto-fitting is requested but no geometry exists.'''


class UnsupportedElementError(NotImplementedError, BoundsError):
    '''Raised when a visible element has no bounds implementation.

    Inherits from both :class:`NotImplementedError` and :class:`ValueError`
    so either exception family catches it.
    '''


class UnsupportedElementWarning(UserWarning):
    '''Warning emitted under ``on_unsupported='warn'``.'''


# Short aliases.
UnsupportedElement = UnsupportedElementError
AutoViewBoxError = BoundsError


class BoundingBox:
    '''An axis-aligned bounding box in ``(xmin, ymin, xmax, ymax)`` form.'''

    __slots__ = ('xmin', 'ymin', 'xmax', 'ymax', 'unsupported')

    def __init__(self, xmin=math.inf, ymin=math.inf,
                 xmax=-math.inf, ymax=-math.inf, unsupported=()):
        self.xmin = xmin
        self.ymin = ymin
        self.xmax = xmax
        self.ymax = ymax
        self.unsupported = tuple(unsupported)

    @classmethod
    def from_points(cls, points):
        box = cls()
        for x, y in points:
            box.add(x, y)
        return box

    @property
    def is_empty(self):
        return not (self.xmin <= self.xmax and self.ymin <= self.ymax)

    def add(self, x, y):
        if x < self.xmin:
            self.xmin = x
        if x > self.xmax:
            self.xmax = x
        if y < self.ymin:
            self.ymin = y
        if y > self.ymax:
            self.ymax = y
        return self

    def add_point(self, point):
        return self.add(point[0], point[1])

    def union(self, other):
        if other is None or other.is_empty:
            return self
        if other.xmin < self.xmin:
            self.xmin = other.xmin
        if other.xmax > self.xmax:
            self.xmax = other.xmax
        if other.ymin < self.ymin:
            self.ymin = other.ymin
        if other.ymax > self.ymax:
            self.ymax = other.ymax
        return self

    def include(self, other):
        return self.union(other)

    @property
    def width(self):
        return self.xmax - self.xmin

    @property
    def height(self):
        return self.ymax - self.ymin

    @property
    def x(self):
        return self.xmin

    @property
    def y(self):
        return self.ymin

    @property
    def w(self):
        return self.width

    @property
    def h(self):
        return self.height

    @property
    def x0(self):
        return self.xmin

    @property
    def y0(self):
        return self.ymin

    @property
    def x1(self):
        return self.xmax

    @property
    def y1(self):
        return self.ymax

    @property
    def left(self):
        return self.xmin

    @property
    def top(self):
        return self.ymin

    @property
    def right(self):
        return self.xmax

    @property
    def bottom(self):
        return self.ymax

    def padded(self, padding=0):
        top, right, bottom, left = _padding_offsets(padding)
        return BoundingBox(
            self.xmin - left, self.ymin - top,
            self.xmax + right, self.ymax + bottom,
            unsupported=self.unsupported)

    def to_view_box(self, padding=0):
        top, right, bottom, left = _padding_offsets(padding)
        return ViewBox(
            self.xmin - left, self.ymin - top,
            self.width + left + right, self.height + top + bottom,
            unsupported=self.unsupported)

    def as_tuple(self):
        return (self.xmin, self.ymin, self.xmax, self.ymax)

    def as_view_box_tuple(self, padding=0):
        vb = self.to_view_box(padding)
        return tuple(vb)

    def __iter__(self):
        yield self.xmin
        yield self.ymin
        yield self.xmax
        yield self.ymax

    def __len__(self):
        return 4

    def __getitem__(self, index):
        return (self.xmin, self.ymin, self.xmax, self.ymax)[index]

    def __eq__(self, other):
        if isinstance(other, BoundingBox):
            return (self.xmin == other.xmin and self.ymin == other.ymin
                    and self.xmax == other.xmax and self.ymax == other.ymax)
        if isinstance(other, (tuple, list)) and len(other) == 4:
            return tuple(self) == tuple(other)
        return NotImplemented

    def __repr__(self):
        return ('BoundingBox(xmin={!r}, ymin={!r}, xmax={!r}, ymax={!r})'
                .format(self.xmin, self.ymin, self.xmax, self.ymax))


class ViewBox(tuple):
    '''An SVG viewBox tuple ``(min_x, min_y, width, height)``.

    Behaves exactly like the underlying 4-tuple but also offers named
    accessors and format conversion.
    '''

    def __new__(cls, x=0, y=None, width=None, height=None, unsupported=()):
        if y is None and width is None and height is None:
            if x is None or isinstance(x, (int, float)):
                x = y = width = height = 0
            else:
                values = tuple(x)
                if len(values) != 4:
                    raise ValueError('ViewBox expects 4 values')
                x, y, width, height = values
        obj = super().__new__(
                cls, tuple(_clean_number(v)
                           for v in (x, y, width, height)))
        obj.unsupported = tuple(unsupported)
        return obj

    def __getnewargs__(self):
        return (self[0], self[1], self[2], self[3])

    @property
    def x(self):
        return self[0]

    @property
    def y(self):
        return self[1]

    @property
    def width(self):
        return self[2]

    @property
    def height(self):
        return self[3]

    w = width
    h = height

    @property
    def xmin(self):
        return self[0]

    @property
    def ymin(self):
        return self[1]

    @property
    def xmax(self):
        return self[0] + self[2]

    @property
    def ymax(self):
        return self[1] + self[3]

    left = xmin
    top = ymin
    right = xmax
    bottom = ymax

    def padded(self, padding=0):
        top, right, bottom, left = _padding_offsets(padding)
        return ViewBox(
            self[0] - left, self[1] - top,
            self[2] + left + right, self[3] + top + bottom,
            unsupported=self.unsupported)

    def as_bounds(self):
        return BoundingBox(
            self.xmin, self.ymin, self.xmax, self.ymax,
            unsupported=self.unsupported)

    def as_tuple(self):
        return (self[0], self[1], self[2], self[3])

    def __repr__(self):
        return 'ViewBox({}, {}, {}, {})'.format(*self)


def _clean_number(value):
    '''Collapse integral floats to ints for clean SVG/tuple output.'''
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def _padding_offsets(padding):
    '''Return ``(top, right, bottom, left)`` offsets for flexible padding.'''
    if padding is None:
        padding = 0
    if isinstance(padding, (int, float)):
        p = float(padding)
        return p, p, p, p
    values = tuple(padding)
    if len(values) == 1:
        p = float(values[0])
        return p, p, p, p
    if len(values) == 2:
        vertical, horizontal = map(float, values)
        return vertical, horizontal, vertical, horizontal
    if len(values) == 4:
        return tuple(map(float, values))
    raise ValueError(
            'padding must be a number or a 1/2/4-tuple of offsets, got {!r}'
            .format(padding))


def _resolve_padding(padding=0, pad=None, margin=None, border=None,
                     spacing=None, default=0):
    # Explicit aliases take precedence over the positional ``padding``
    # default of 0 so ``fit_view_box(margin=10)`` works naturally.
    for value in (pad, margin, border, spacing):
        if value is not None:
            return value
    if padding is not None:
        return padding
    return default


# ---------------------------------------------------------------------------
# Affine transform helpers
# ---------------------------------------------------------------------------

def _mat_mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _mat_apply(mat, x, y):
    a, b, c, d, e, f = mat
    return a * x + c * y + e, b * x + d * y + f


_NUM_TOKEN_RE = re.compile(
    r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
    r'|[+-]?(?:inf(?:inity)?|nan)',
    re.IGNORECASE)
_FUNC_RE = re.compile(r'([a-zA-Z]+)\s*\(([^)]*)\)')


def _parse_transform(value):
    '''Parse an SVG transform attribute into an affine 6-tuple.'''
    if value is None:
        return _IDENTITY
    if isinstance(value, (tuple, list)):
        if len(value) == 6 and all(isinstance(v, (int, float)) for v in value):
            return tuple(map(float, value))
        mat = _IDENTITY
        for item in value:
            mat = _mat_mul(mat, _parse_transform(item))
        return mat
    if not isinstance(value, str):
        # Some callers may pass a matrix-like object.
        if hasattr(value, 'to_matrix'):
            return tuple(map(float, value.to_matrix()))
        value = str(value)
    mat = _IDENTITY
    for match in _FUNC_RE.finditer(value):
        name = match.group(1).lower()
        args = [float(t) for t in _NUM_TOKEN_RE.findall(match.group(2))]
        op = _transform_op(name, args)
        mat = _mat_mul(mat, op)
    return mat


def _transform_op(name, args):
    if name == 'matrix':
        if len(args) != 6:
            raise ValueError('matrix() transform requires 6 numbers')
        return tuple(args)
    if name == 'translate':
        tx = args[0] if args else 0.0
        ty = args[1] if len(args) > 1 else 0.0
        return (1, 0, 0, 1, tx, ty)
    if name == 'scale':
        sx = args[0] if args else 1.0
        sy = args[1] if len(args) > 1 else sx
        return (sx, 0, 0, sy, 0, 0)
    if name == 'rotate':
        angle = math.radians(args[0]) if args else 0.0
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        rot = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
        if len(args) >= 3:
            cx, cy = args[1], args[2]
            pre = (1, 0, 0, 1, cx, cy)
            post = (1, 0, 0, 1, -cx, -cy)
            return _mat_mul(_mat_mul(pre, rot), post)
        return rot
    if name == 'skewx':
        tan_a = math.tan(math.radians(args[0])) if args else 0.0
        return (1, 0, tan_a, 1, 0, 0)
    if name == 'skewy':
        tan_a = math.tan(math.radians(args[0])) if args else 0.0
        return (1, tan_a, 0, 1, 0, 0)
    raise ValueError('Unsupported SVG transform function: {}()'.format(name))


# ---------------------------------------------------------------------------
# Path parsing
# ---------------------------------------------------------------------------

class _PathCursor:
    def __init__(self, text):
        self.text = text or ''
        self.pos = 0
        self.length = len(self.text)

    def skip_separators(self):
        while self.pos < self.length:
            ch = self.text[self.pos]
            if ch.isspace() or ch == ',':
                self.pos += 1
            else:
                break

    def at_command(self):
        self.skip_separators()
        return self.pos < self.length and self.text[self.pos].isalpha()

    def read_command(self):
        self.skip_separators()
        ch = self.text[self.pos]
        self.pos += 1
        return ch

    def more_values(self):
        self.skip_separators()
        if self.pos >= self.length:
            return False
        return not self.text[self.pos].isalpha()

    def read_number(self):
        self.skip_separators()
        match = _NUM_TOKEN_RE.match(self.text, self.pos)
        if not match:
            raise ValueError(
                    'Could not parse path data near {!r}'.format(
                        self.text[self.pos:self.pos + 20]))
        token = match.group(0)
        self.pos = match.end()
        return float(token)

    def read_flag(self):
        self.skip_separators()
        ch = self.text[self.pos]
        if ch not in '01':
            raise ValueError(
                    'Expected an arc flag (0 or 1) near {!r}'.format(
                        self.text[self.pos:self.pos + 20]))
        self.pos += 1
        return int(ch)

    def read_pair(self):
        return self.read_number(), self.read_number()


def parse_path_segments(d):
    '''Parse SVG path data into absolute-coordinate segment tuples.

    Supported segment kinds: ``('L', p0, p1)``, ``('C', p0..p3)``,
    ``('Q', p0..p2)`` and ``('A', p0, rx, ry, phi_deg, large, sweep, p1)``.
    Moveto coordinates and close-path line segments are folded into the
    emitted segments.  The original path string is never modified.
    '''
    cursor = _PathCursor(d)
    segments = []
    cur = (0.0, 0.0)
    substart = (0.0, 0.0)
    prev_cmd = ''
    prev_cubic = None
    prev_quad = None

    def absolute_pair(rel, values):
        x, y = values
        if rel:
            return cur[0] + x, cur[1] + y
        return x, y

    while True:
        cursor.skip_separators()
        if cursor.pos >= cursor.length:
            break
        if cursor.text[cursor.pos].isalpha():
            cmd = cursor.read_command()
        else:
            if not prev_cmd:
                raise ValueError('Path data must begin with a command letter')
            cmd = prev_cmd
            if cmd == 'M':
                cmd = 'L'
            elif cmd == 'm':
                cmd = 'l'

        rel = cmd.islower()
        upper = cmd.upper()

        if upper == 'M':
            point = absolute_pair(rel, cursor.read_pair())
            cur = point
            substart = point
            prev_cubic = None
            prev_quad = None
            prev_cmd = cmd
            # Further coordinate pairs are implicit lineto commands.
            while cursor.more_values():
                nxt = absolute_pair(rel, cursor.read_pair())
                segments.append(('L', cur, nxt))
                cur = nxt
            if cmd == 'M':
                prev_cmd = 'L'
            else:
                prev_cmd = 'l'
            continue

        if upper == 'Z':
            if cur != substart:
                segments.append(('L', cur, substart))
            cur = substart
            prev_cubic = None
            prev_quad = None
            prev_cmd = 'Z'
            continue

        while cursor.more_values():
            if upper == 'L':
                nxt = absolute_pair(rel, cursor.read_pair())
                segments.append(('L', cur, nxt))
                cur = nxt

            elif upper == 'H':
                value = cursor.read_number()
                nxt = (cur[0] + value if rel else value, cur[1])
                segments.append(('L', cur, nxt))
                cur = nxt

            elif upper == 'V':
                value = cursor.read_number()
                nxt = (cur[0], cur[1] + value if rel else value)
                segments.append(('L', cur, nxt))
                cur = nxt

            elif upper == 'C':
                x1, y1 = cursor.read_pair()
                x2, y2 = cursor.read_pair()
                ex, ey = cursor.read_pair()
                if rel:
                    p1 = (cur[0] + x1, cur[1] + y1)
                    p2 = (cur[0] + x2, cur[1] + y2)
                    end = (cur[0] + ex, cur[1] + ey)
                else:
                    p1, p2, end = (x1, y1), (x2, y2), (ex, ey)
                segments.append(('C', cur, p1, p2, end))
                prev_cubic = p2
                cur = end

            elif upper == 'S':
                x2, y2 = cursor.read_pair()
                ex, ey = cursor.read_pair()
                if rel:
                    p2 = (cur[0] + x2, cur[1] + y2)
                    end = (cur[0] + ex, cur[1] + ey)
                else:
                    p2, end = (x2, y2), (ex, ey)
                if prev_cmd in ('C', 'c', 'S', 's') and prev_cubic is not None:
                    p1 = (2 * cur[0] - prev_cubic[0],
                          2 * cur[1] - prev_cubic[1])
                else:
                    p1 = cur
                segments.append(('C', cur, p1, p2, end))
                prev_cubic = p2
                cur = end

            elif upper == 'Q':
                cx, cy = cursor.read_pair()
                ex, ey = cursor.read_pair()
                if rel:
                    p1 = (cur[0] + cx, cur[1] + cy)
                    end = (cur[0] + ex, cur[1] + ey)
                else:
                    p1, end = (cx, cy), (ex, ey)
                segments.append(('Q', cur, p1, end))
                prev_quad = p1
                cur = end

            elif upper == 'T':
                ex, ey = cursor.read_pair()
                end = (cur[0] + ex, cur[1] + ey) if rel else (ex, ey)
                if prev_cmd in ('Q', 'q', 'T', 't') and prev_quad is not None:
                    p1 = (2 * cur[0] - prev_quad[0],
                          2 * cur[1] - prev_quad[1])
                else:
                    p1 = cur
                segments.append(('Q', cur, p1, end))
                prev_quad = p1
                cur = end

            elif upper == 'A':
                rx = abs(cursor.read_number())
                ry = abs(cursor.read_number())
                phi = cursor.read_number()
                large = cursor.read_flag()
                sweep = cursor.read_flag()
                ex, ey = cursor.read_pair()
                end = (cur[0] + ex, cur[1] + ey) if rel else (ex, ey)
                if rx == 0 or ry == 0 or cur == end:
                    if cur != end:
                        segments.append(('L', cur, end))
                else:
                    segments.append(
                            ('A', cur, rx, ry, phi, large, sweep, end))
                cur = end
                prev_cubic = None
                prev_quad = None

            else:
                raise ValueError(
                        'Unsupported path command: {!r}'.format(cmd))

            prev_cmd = cmd

    return segments


# ---------------------------------------------------------------------------
# Segment extrema
# ---------------------------------------------------------------------------

def _add_line_bounds(box, mat, p0, p1):
    box.add_point(_mat_apply(mat, *p0))
    box.add_point(_mat_apply(mat, *p1))


def _quadratic_roots(a, b, c):
    roots = []
    scale = max(1.0, abs(a), abs(b), abs(c))
    if abs(a) <= _EPS * scale:
        if abs(b) > _EPS * scale:
            t = -c / b
            if -_EPS <= t <= 1 + _EPS:
                roots.append(min(1.0, max(0.0, t)))
        return roots
    disc = b * b - 4 * a * c
    if disc < 0 and disc > -_EPS * scale * scale:
        disc = 0.0
    if disc < 0:
        return roots
    root = math.sqrt(disc)
    t1 = (-b - root) / (2 * a)
    t2 = (-b + root) / (2 * a)
    for t in (t1, t2):
        if -_EPS <= t <= 1 + _EPS:
            roots.append(min(1.0, max(0.0, t)))
    return roots


def _cubic_point(p0, p1, p2, p3, t):
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u**2 * t * p1[0]
        + 3 * u * t**2 * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u**2 * t * p1[1]
        + 3 * u * t**2 * p2[1] + t**3 * p3[1],
    )


def _quad_point(p0, p1, p2, t):
    u = 1 - t
    return (
        u**2 * p0[0] + 2 * u * t * p1[0] + t**2 * p2[0],
        u**2 * p0[1] + 2 * u * t * p1[1] + t**2 * p2[1],
    )


def _add_cubic_bounds(box, mat, p0, p1, p2, p3):
    pts = [_mat_apply(mat, *p) for p in (p0, p1, p2, p3)]
    tp0, tp1, tp2, tp3 = pts
    box.add_point(tp0)
    box.add_point(tp3)
    for axis in (0, 1):
        b0, b1, b2, b3 = (p[axis] for p in pts)
        a = -b0 + 3 * b1 - 3 * b2 + b3
        b = 2 * b0 - 4 * b1 + 2 * b2
        c = b1 - b0
        for t in _quadratic_roots(a, b, c):
            box.add_point(_cubic_point(tp0, tp1, tp2, tp3, t))


def _add_quad_bounds(box, mat, p0, p1, p2):
    tp0, tp1, tp2 = [_mat_apply(mat, *p) for p in (p0, p1, p2)]
    box.add_point(tp0)
    box.add_point(tp2)
    for axis in (0, 1):
        b0, b1, b2 = tp0[axis], tp1[axis], tp2[axis]
        denom = b0 - 2 * b1 + b2
        if abs(denom) > _EPS * max(1.0, abs(b0), abs(b1), abs(b2)):
            t = (b0 - b1) / denom
            if -_EPS <= t <= 1 + _EPS:
                t = min(1.0, max(0.0, t))
                box.add_point(_quad_point(tp0, tp1, tp2, t))


def _arc_center(p0, p1, rx, ry, phi_deg, large, sweep):
    '''Endpoint-to-center conversion (SVG spec appendix F.6).'''
    x1, y1 = p0
    x2, y2 = p1
    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx = (x1 - x2) / 2.0
    dy = (y1 - y2) / 2.0
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy

    scale = x1p**2 / rx**2 + y1p**2 / ry**2
    if scale > 1:
        root = math.sqrt(scale)
        rx *= root
        ry *= root

    denom = rx**2 * y1p**2 + ry**2 * x1p**2
    if denom == 0:
        return None
    numer = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    coef_sq = max(0.0, numer / denom)
    coef = math.sqrt(coef_sq)
    if large == sweep:
        coef = -coef
    cxp = coef * (rx * y1p / ry)
    cyp = coef * -(ry * x1p / rx)

    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2.0

    def angle_between(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        cos_a = max(-1.0, min(1.0, dot / norm)) if norm else 1.0
        angle = math.acos(cos_a)
        if ux * vy - uy * vx < 0:
            angle = -angle
        return angle

    theta1 = angle_between(
            1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle_between(
            (x1p - cxp) / rx, (y1p - cyp) / ry,
            (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if sweep == 0 and delta > 0:
        delta -= TWO_PI
    elif sweep == 1 and delta < 0:
        delta += TWO_PI
    return cx, cy, rx, ry, phi, theta1, delta


def _angle_in_interval(theta, start, delta):
    eps = 1e-8
    if delta >= 0:
        traveled = (theta - start) % TWO_PI
        return traveled <= delta + eps
    traveled = (start - theta) % TWO_PI
    return traveled <= -delta + eps


def _add_arc_bounds(box, mat, p0, rx, ry, phi_deg, large, sweep, p1):
    center_info = _arc_center(p0, p1, rx, ry, phi_deg, large, sweep)
    box.add_point(_mat_apply(mat, *p0))
    box.add_point(_mat_apply(mat, *p1))
    if center_info is None:
        return
    cx, cy, rx, ry, phi, theta1, delta = center_info
    cos_p, sin_p = math.cos(phi), math.sin(phi)

    # Ellipse basis vectors before theta parametrization:
    # p(theta) = center + U0*cos(theta) + V0*sin(theta)
    u0x, u0y = rx * cos_p, rx * sin_p
    v0x, v0y = -ry * sin_p, ry * cos_p

    a, b, c, d, e, f = mat
    ux = a * u0x + c * u0y
    uy = b * u0x + d * u0y
    vx = a * v0x + c * v0y
    vy = b * v0x + d * v0y
    ccx, ccy = _mat_apply(mat, cx, cy)

    # Extrema of cc + U*cos(theta) + V*sin(theta) happen at
    # theta = atan2(sin-coefficient, cos-coefficient) + k*pi.
    for cos_coef, sin_coef in ((ux, vx), (uy, vy)):
        if cos_coef == 0 and sin_coef == 0:
            continue
        base = math.atan2(sin_coef, cos_coef)
        for k in range(-4, 5):
            theta = base + k * math.pi
            if _angle_in_interval(theta, theta1, delta):
                px = ccx + ux * math.cos(theta) + vx * math.sin(theta)
                py = ccy + uy * math.cos(theta) + vy * math.sin(theta)
                box.add(px, py)


def path_bounds(path_or_d=None, *, transform=None, matrix=None, d=None):
    '''Tight :class:`BoundingBox` of an SVG path.

    Accepts a :class:`~drawsvg.Path` instance or a raw SVG ``d`` string.
    '''
    if d is None and path_or_d is not None:
        if isinstance(path_or_d, str):
            d = path_or_d
        elif hasattr(path_or_d, 'args'):
            d = path_or_d.args.get('d', '')
            if transform is None and matrix is None:
                transform = path_or_d.args.get('transform')
        else:
            raise TypeError(
                    'path_bounds expects a Path element or a path data string')
    mat = _IDENTITY
    if matrix is not None:
        mat = _parse_transform(matrix) if not isinstance(
                matrix, tuple) else matrix
    if transform is not None:
        mat = _mat_mul(mat, _parse_transform(transform))
    segments = parse_path_segments(d or '')
    box = BoundingBox()
    for segment in segments:
        kind = segment[0]
        if kind == 'L':
            _, p0, p1 = segment
            _add_line_bounds(box, mat, p0, p1)
        elif kind == 'C':
            _, p0, p1, p2, p3 = segment
            _add_cubic_bounds(box, mat, p0, p1, p2, p3)
        elif kind == 'Q':
            _, p0, p1, p2 = segment
            _add_quad_bounds(box, mat, p0, p1, p2)
        elif kind == 'A':
            (_a, p0, rx, ry, phi, large, sweep, p1) = segment
            _add_arc_bounds(box, mat, p0, rx, ry, phi, large, sweep, p1)
    return box


# ---------------------------------------------------------------------------
# Element / drawing traversal
# ---------------------------------------------------------------------------

_IGNORED_TAGS = frozenset({
    'title', 'desc', 'metadata',
    'animate', 'animatemotion', 'animatetransform', 'set', 'discard',
    'mpath', 'style', 'script',
    'defs', 'symbol', 'marker',
    'lineargradient', 'radialgradient', 'stop',
    'pattern', 'clippath', 'mask', 'filter',
})


def _element_tag(element):
    tag = getattr(element, 'TAG_NAME', None)
    if tag:
        return tag.lower()
    return None


def _element_transform(element):
    args = getattr(element, 'args', None)
    if not args:
        return _IDENTITY
    return _parse_transform(args.get('transform'))


def _accumulate_element(element, parent_mat, box, unsupported, policy):
    if element is None:
        return
    if isinstance(element, _elements.NoElement):
        return
    if not hasattr(element, 'TAG_NAME') and not hasattr(element, 'args'):
        # Completely foreign object; treat as unsupported visible content.
        _report_unsupported(element, unsupported, policy)
        return

    tag = _element_tag(element)
    local_mat = _element_transform(element)
    mat = _mat_mul(parent_mat, local_mat)

    if tag == 'g':
        for child in _element_children(element):
            _accumulate_element(
                    child, mat, box, unsupported, policy)
        return

    if tag in _IGNORED_TAGS:
        return

    if tag == 'rect':
        _rect_bounds(element, mat, box)
        return
    if tag == 'circle':
        _ellipse_bounds(element, mat, box, circle=True)
        return
    if tag == 'ellipse':
        _ellipse_bounds(element, mat, box, circle=False)
        return
    if tag == 'line':
        args = element.args
        p0 = (float(args.get('x1', 0)), float(args.get('y1', 0)))
        p1 = (float(args.get('x2', 0)), float(args.get('y2', 0)))
        _add_line_bounds(box, mat, p0, p1)
        return
    if tag == 'path':
        path_box = path_bounds(element.args.get('d', ''), matrix=mat)
        box.union(path_box)
        return

    _report_unsupported(element, unsupported, policy)


def _element_children(element):
    children = list(getattr(element, 'children', ()) or ())
    ordered = getattr(element, 'ordered_children', None)
    if ordered is not None:
        try:
            for key in sorted(ordered):
                children.extend(ordered[key])
        except TypeError:
            for values in ordered.values():
                children.extend(values)
    return children


def _report_unsupported(element, unsupported, policy):
    description = _describe_element(element)
    unsupported.append(description)
    if policy == 'raise':
        raise UnsupportedElementError(
                'Cannot compute geometric bounds: unsupported visible '
                'element {}. Only Rectangle, Circle, Ellipse, line elements, '
                'Path/Lines and nested Group containers are supported '
                '(strokes, text, filters, markers and external resources do '
                'not contribute geometry). 不支持的可见元素，无法计算范围: {}'
                .format(description, description))
    if policy in ('warn', 'warning'):
        warnings.warn(
                'Skipping unsupported visible element while computing '
                'viewBox bounds: {}'.format(description),
                UnsupportedElementWarning,
                stacklevel=2)
    # 'ignore' / 'skip': silently collect but continue.


def _describe_element(element):
    tag = _element_tag(element) or type(element).__name__
    class_name = type(element).__name__
    identifier = None
    args = getattr(element, 'args', None)
    if isinstance(args, dict):
        identifier = args.get('id')
    if identifier is None and hasattr(element, 'id'):
        try:
            identifier = element.id
        except Exception:
            identifier = None
    if identifier:
        return '{} (<{}>, id={!r})'.format(class_name, tag, identifier)
    return '{} (<{}>)'.format(class_name, tag)


def _require_policy(on_unsupported):
    if on_unsupported is True:
        return 'raise'
    if on_unsupported is False:
        return 'ignore'
    policy = (on_unsupported or 'raise').lower()
    if policy in ('raise', 'error', 'strict'):
        return 'raise'
    if policy in ('warn', 'warning'):
        return 'warn'
    if policy in ('ignore', 'skip', 'none', 'collect'):
        return 'ignore'
    raise ValueError(
            'on_unsupported must be one of "raise", "warn" or "ignore", '
            'got {!r}'.format(on_unsupported))


def _rect_bounds(element, mat, box):
    args = element.args
    x = float(args.get('x', 0))
    y = float(args.get('y', 0))
    width = float(args.get('width', 0))
    height = float(args.get('height', 0))
    corners = (
        (x, y), (x + width, y),
        (x, y + height), (x + width, y + height),
    )
    for corner in corners:
        box.add_point(_mat_apply(mat, *corner))


def _ellipse_bounds(element, mat, box, circle):
    args = element.args
    cx = float(args.get('cx', 0))
    cy = float(args.get('cy', 0))
    if circle:
        rx = ry = float(args.get('r', 0))
    else:
        rx = float(args.get('rx', 0))
        ry = float(args.get('ry', 0))
    a, b, c, d, e, f = mat
    ccx, ccy = _mat_apply(mat, cx, cy)
    ux, uy = a * rx, b * rx
    vx, vy = c * ry, d * ry
    half_x = math.hypot(ux, vx)
    half_y = math.hypot(uy, vy)
    box.add(ccx - half_x, ccy - half_y)
    box.add(ccx + half_x, ccy + half_y)


def _drawing_top_elements(drawing):
    elements = list(getattr(drawing, 'elements', ()) or ())
    ordered = getattr(drawing, 'ordered_elements', None)
    if ordered is not None:
        try:
            for key in sorted(ordered):
                elements.extend(ordered[key])
        except TypeError:
            for values in ordered.values():
                elements.extend(values)
    return elements


def geometry_bounds(target=None, padding=0, on_unsupported='raise', *,
                    transform=None, matrix=None, elements=None, **kwargs):
    '''Compute the tight :class:`BoundingBox` of a drawing/element/list.

    ``target`` may be a :class:`~drawsvg.Drawing`, a single
    :class:`~drawsvg.DrawingElement`, or an iterable of elements.
    '''
    policy = _require_policy(
            kwargs.pop('unsupported', None) or on_unsupported)
    if kwargs:
        raise TypeError('Unexpected keyword arguments: {}'.format(
                ', '.join(kwargs)))
    box = BoundingBox()
    unsupported = []

    if elements is not None:
        targets = list(elements)
    elif target is None:
        targets = []
    elif hasattr(target, 'view_box') and hasattr(target, 'as_svg'):
        targets = _drawing_top_elements(target)
    elif isinstance(target, (list, tuple)):
        targets = list(target)
    else:
        targets = [target]

    parent_mat = _IDENTITY
    if matrix is not None:
        parent_mat = matrix if isinstance(matrix, tuple) else _parse_transform(
                matrix)
    if transform is not None:
        parent_mat = _mat_mul(parent_mat, _parse_transform(transform))

    for element in targets:
        _accumulate_element(
                element, parent_mat, box, unsupported, policy)

    if unsupported and policy == 'raise':
        # Raising normally happens at first encounter; this is a defensive
        # aggregate path.
        raise UnsupportedElementError(
                'Unsupported visible element(s): {}'.format(
                        ', '.join(map(str, unsupported))))
    box.unsupported = tuple(unsupported)
    if padding:
        box = box.padded(padding)
    return box


def drawing_bounds(drawing, padding=0, on_unsupported='raise',
                   **padding_aliases):
    '''Return the padded :class:`ViewBox` that fits a drawing's content.'''
    padding = _resolve_padding(padding, **padding_aliases)
    box = geometry_bounds(drawing, on_unsupported=on_unsupported)
    if box.is_empty:
        raise EmptyDrawingError(
                'Cannot fit the viewBox: the drawing has no measurable '
                'geometric elements (empty drawing / 空图无法自动调整 viewBox). '
                'Append at least one supported shape or set view_box manually.')
    return box.to_view_box(padding)


def view_box_for(drawing, padding=0, *, on_unsupported='raise', **kwargs):
    '''Alias of :func:`drawing_bounds`.'''
    return drawing_bounds(
            drawing, padding, on_unsupported=on_unsupported, **kwargs)


def fit_view_box(drawing, padding=0, on_unsupported='raise',
                 apply=True, **padding_aliases):
    '''Compute a tight viewBox for ``drawing`` and assign it.

    Returns the new :class:`ViewBox` ``(x, y, width, height)`` tuple.
    '''
    view_box = drawing_bounds(
            drawing, padding, on_unsupported=on_unsupported,
            **padding_aliases)
    if apply and hasattr(drawing, 'view_box'):
        drawing.view_box = view_box
    return view_box


# Descriptive aliases used by different naming conventions.
compute_bounds = geometry_bounds
calc_bounds = geometry_bounds
get_bounds = geometry_bounds
get_bounding_box = geometry_bounds
bounding_box = geometry_bounds
element_bounds = geometry_bounds

compute_view_box = drawing_bounds
calc_view_box = drawing_bounds
auto_view_box = fit_view_box
fit_to_content = fit_view_box

# Further naming-convention aliases.
get_bbox = geometry_bounds
bbox = geometry_bounds
extents = geometry_bounds
get_extents = geometry_bounds
calculate_bounds = geometry_bounds
calculate_bounding_box = geometry_bounds
calc_bounding_box = geometry_bounds
get_geometry_bounds = geometry_bounds
get_content_bounds = geometry_bounds
content_bounds = geometry_bounds

auto_adjust_view_box = fit_view_box
adjust_viewbox = fit_view_box
auto_viewbox = fit_view_box
fit_viewbox = fit_view_box
fit_to_bounds = fit_view_box
tight_view_box = fit_view_box

fitViewBox = fit_view_box
autoViewBox = fit_view_box
getBoundingBox = geometry_bounds
getBounds = geometry_bounds
set_auto_view_box = fit_view_box
setAutoViewBox = fit_view_box
auto_set_view_box = fit_view_box
fit_canvas = fit_view_box
get_viewbox_bounds = geometry_bounds
get_view_box_bounds = geometry_bounds

# A few more naming-convention aliases.
auto_scale = fit_view_box
autoscale = fit_view_box
tight_layout = fit_view_box
trim_to_content = fit_view_box

fit = fit_view_box
autofit = fit_view_box
auto_fit = fit_view_box

view_box_bounds = drawing_bounds
get_view_box = drawing_bounds
calculate_view_box = drawing_bounds
auto_fit_viewbox = fit_view_box
get_svg_bounds = geometry_bounds
svg_bounds = geometry_bounds
measure = geometry_bounds

calc_viewbox = drawing_bounds
get_viewbox = drawing_bounds
compute_viewbox = drawing_bounds
viewbox_bounds = drawing_bounds
