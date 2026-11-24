'''Geometry helpers used to calculate tight drawing bounds.

Only path-like geometry is considered.  Stroke width, markers, text, filters,
and external resources are intentionally excluded.
'''

from __future__ import annotations

import dataclasses
import math
import re
from typing import Iterable, Optional


_EPSILON = 1e-12


class UnsupportedGeometryError(NotImplementedError, ValueError):
    '''Raised when a visible element's geometry cannot be calculated.'''


@dataclasses.dataclass(frozen=True)
class Bounds:
    '''An axis-aligned bounding box.'''
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self):
        return self.max_x - self.min_x

    @property
    def height(self):
        return self.max_y - self.min_y

    def union(self, other: Optional['Bounds']) -> 'Bounds':
        if other is None:
            return self
        return Bounds(
                min(self.min_x, other.min_x),
                min(self.min_y, other.min_y),
                max(self.max_x, other.max_x),
                max(self.max_y, other.max_y))

    def expanded(self, margin: float) -> 'Bounds':
        margin = _number(margin, 'margin')
        if margin < 0:
            raise ValueError('margin must be non-negative')
        return Bounds(
                self.min_x - margin, self.min_y - margin,
                self.max_x + margin, self.max_y + margin)

    def as_view_box(self):
        return (self.min_x, self.min_y, self.width, self.height)


@dataclasses.dataclass(frozen=True)
class Affine2D:
    '''A two-dimensional affine transformation matrix.'''
    a: float = 1
    b: float = 0
    c: float = 0
    d: float = 1
    e: float = 0
    f: float = 0

    def __matmul__(self, other: 'Affine2D') -> 'Affine2D':
        '''Return the transform equivalent to applying other, then self.'''
        return Affine2D(
                self.a*other.a + self.c*other.b,
                self.b*other.a + self.d*other.b,
                self.a*other.c + self.c*other.d,
                self.b*other.c + self.d*other.d,
                self.a*other.e + self.c*other.f + self.e,
                self.b*other.e + self.d*other.f + self.f)

    def apply(self, x, y):
        return (self.a*x + self.c*y + self.e,
                self.b*x + self.d*y + self.f)

    def apply_vector(self, x, y):
        return (self.a*x + self.c*y, self.b*x + self.d*y)


IDENTITY = Affine2D()


_NUMBER_PATTERN = r'[-+]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][-+]?\d+)?'
_NUMBER_RE = re.compile(_NUMBER_PATTERN)
_TRANSFORM_RE = re.compile(r'([A-Za-z]+)\s*\(([^)]*)\)')
_PATH_TOKEN_RE = re.compile(
        r'[AaCcHhLlMmQqSsTtVvZz]|' + _NUMBER_PATTERN)
_PATH_COMMANDS = frozenset('AaCcHhLlMmQqSsTtVvZz')
_PATH_ARG_COUNTS = {
    'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4,
    'T': 2, 'A': 7, 'Z': 0,
}


def _number(value, name='coordinate'):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as e:
        raise ValueError(f'{name} must be a finite number, got {value!r}') from e
    if not math.isfinite(result):
        raise ValueError(f'{name} must be a finite number, got {value!r}')
    return result


class _BoundsBuilder:
    def __init__(self):
        self.min_x = math.inf
        self.min_y = math.inf
        self.max_x = -math.inf
        self.max_y = -math.inf

    def add_point(self, x, y):
        self.min_x = min(self.min_x, x)
        self.min_y = min(self.min_y, y)
        self.max_x = max(self.max_x, x)
        self.max_y = max(self.max_y, y)

    def add_bounds(self, bounds: Optional[Bounds]):
        if bounds is not None:
            self.add_point(bounds.min_x, bounds.min_y)
            self.add_point(bounds.max_x, bounds.max_y)

    def build(self) -> Optional[Bounds]:
        if self.min_x == math.inf:
            return None
        return Bounds(self.min_x, self.min_y, self.max_x, self.max_y)


def _parse_number_list(text: str) -> list[float]:
    values = []
    pos = 0
    for match in _NUMBER_RE.finditer(text):
        if text[pos:match.start()].strip(' \t\r\n,'):
            raise ValueError(f'invalid number list {text!r}')
        values.append(_number(match.group()))
        pos = match.end()
    if text[pos:].strip(' \t\r\n,'):
        raise ValueError(f'invalid number list {text!r}')
    return values


def parse_transform(transform) -> Affine2D:
    '''Parse an SVG transform attribute into an affine matrix.'''
    if transform is None:
        return IDENTITY
    if isinstance(transform, Affine2D):
        return transform
    if not isinstance(transform, str):
        raise ValueError(f'invalid transform {transform!r}')
    transform = transform.strip()
    if not transform or transform.lower() == 'none':
        return IDENTITY

    result = IDENTITY
    pos = 0
    for match in _TRANSFORM_RE.finditer(transform):
        if transform[pos:match.start()].strip(' \t\r\n,'):
            raise ValueError(f'invalid transform {transform!r}')
        name = match.group(1).lower()
        args = _parse_number_list(match.group(2))
        if name == 'matrix' and len(args) == 6:
            current = Affine2D(*args)
        elif name == 'translate' and len(args) in (1, 2):
            ty = args[1] if len(args) == 2 else 0
            current = Affine2D(1, 0, 0, 1, args[0], ty)
        elif name == 'scale' and len(args) in (1, 2):
            sy = args[1] if len(args) == 2 else args[0]
            current = Affine2D(args[0], 0, 0, sy, 0, 0)
        elif name == 'rotate' and len(args) in (1, 3):
            angle = math.radians(args[0])
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            current = Affine2D(cos_a, sin_a, -sin_a, cos_a, 0, 0)
            if len(args) == 3:
                cx, cy = args[1:]
                current = (Affine2D(1, 0, 0, 1, cx, cy) @ current
                           @ Affine2D(1, 0, 0, 1, -cx, -cy))
        elif name == 'skewx' and len(args) == 1:
            current = Affine2D(1, 0, math.tan(math.radians(args[0])), 1,
                               0, 0)
        elif name == 'skewy' and len(args) == 1:
            current = Affine2D(1, math.tan(math.radians(args[0])), 0, 1,
                               0, 0)
        else:
            raise ValueError(
                    f'unsupported SVG transform {match.group(0)!r}')
        result = result @ current
        pos = match.end()
    if transform[pos:].strip(' \t\r\n,'):
        raise ValueError(f'invalid transform {transform!r}')
    return result


def _tokenize_path(d: str) -> list[str]:
    tokens = []
    pos = 0
    for match in _PATH_TOKEN_RE.finditer(d):
        if d[pos:match.start()].strip(' \t\r\n,'):
            raise ValueError(f'invalid path data near {d[pos:]!r}')
        tokens.append(match.group())
        pos = match.end()
    if d[pos:].strip(' \t\r\n,'):
        raise ValueError(f'invalid path data near {d[pos:]!r}')
    return tokens


def _is_path_command(token: str) -> bool:
    return len(token) == 1 and token in _PATH_COMMANDS


def _take_path_args(tokens, index, count):
    end = index + count
    if end > len(tokens):
        raise ValueError('path command has too few arguments')
    values = tokens[index:end]
    if any(_is_path_command(token) for token in values):
        raise ValueError('path command has too few arguments')
    return [_number(token) for token in values], end


def _line_bounds(x1, y1, x2, y2, transform: Affine2D) -> Bounds:
    x1, y1 = transform.apply(x1, y1)
    x2, y2 = transform.apply(x2, y2)
    return Bounds(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def _points_bounds(points, transform: Affine2D) -> Bounds:
    bounds = _BoundsBuilder()
    for point in points:
        bounds.add_point(*transform.apply(*point))
    return bounds.build()


def _quadratic_roots(a, b, c):
    if abs(a) <= _EPSILON:
        if abs(b) <= _EPSILON:
            return ()
        return (-c / b,)
    discriminant = b*b - 4*a*c
    if discriminant < -_EPSILON:
        return ()
    discriminant = max(0.0, discriminant)
    root = math.sqrt(discriminant)
    return ((-b - root) / (2*a), (-b + root) / (2*a))


def _cubic_bounds(p0, p1, p2, p3, transform: Affine2D) -> Bounds:
    points = [transform.apply(*point) for point in (p0, p1, p2, p3)]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    bounds = _BoundsBuilder()
    bounds.add_point(*points[0])
    bounds.add_point(*points[3])

    def evaluate(t):
        return (_cubic_x(points, t), _cubic_y(points, t))

    for values in (xs, ys):
        x0, x1, x2, x3 = values
        a = -x0 + 3*x1 - 3*x2 + x3
        b = 2 * (x0 - 2*x1 + x2)
        c = x1 - x0
        for t in _quadratic_roots(a, b, c):
            if -_EPSILON <= t <= 1 + _EPSILON:
                bounds.add_point(*evaluate(min(1.0, max(0.0, t))))
    return bounds.build()


def _cubic_x(points, t):
    mt = 1 - t
    return (mt**3 * points[0][0] + 3 * mt**2 * t * points[1][0]
            + 3 * mt * t**2 * points[2][0] + t**3 * points[3][0])


def _cubic_y(points, t):
    mt = 1 - t
    return (mt**3 * points[0][1] + 3 * mt**2 * t * points[1][1]
            + 3 * mt * t**2 * points[2][1] + t**3 * points[3][1])


def _quadratic_bounds(p0, p1, p2, transform: Affine2D) -> Bounds:
    points = [transform.apply(*point) for point in (p0, p1, p2)]
    bounds = _BoundsBuilder()
    bounds.add_point(*points[0])
    bounds.add_point(*points[2])

    def evaluate(t):
        mt = 1 - t
        return (mt*mt*points[0][0] + 2*mt*t*points[1][0] + t*t*points[2][0],
                mt*mt*points[0][1] + 2*mt*t*points[1][1] + t*t*points[2][1])

    for axis in (0, 1):
        p0v, p1v, p2v = (point[axis] for point in points)
        denominator = p0v - 2*p1v + p2v
        if abs(denominator) > _EPSILON:
            t = (p0v - p1v) / denominator
            if -_EPSILON <= t <= 1 + _EPSILON:
                bounds.add_point(*evaluate(min(1.0, max(0.0, t))))
    return bounds.build()


def _ellipse_bounds(cx, cy, rx, ry, transform: Affine2D) -> Bounds:
    center = transform.apply(cx, cy)
    cos_axis = transform.apply_vector(rx, 0)
    sin_axis = transform.apply_vector(0, ry)
    bounds = _BoundsBuilder()

    def evaluate(theta):
        return (center[0] + cos_axis[0]*math.cos(theta)
                    + sin_axis[0]*math.sin(theta),
                center[1] + cos_axis[1]*math.cos(theta)
                    + sin_axis[1]*math.sin(theta))

    for axis in (0, 1):
        a = cos_axis[axis]
        b = sin_axis[axis]
        if abs(a) <= _EPSILON and abs(b) <= _EPSILON:
            bounds.add_point(*center)
            continue
        theta = math.atan2(b, a)
        bounds.add_point(*evaluate(theta))
        bounds.add_point(*evaluate(theta + math.pi))
    return bounds.build()


def _angle_in_sweep(theta, start, delta):
    if delta >= 0:
        amount = (theta - start) % (2*math.pi)
        return amount <= delta + _EPSILON
    amount = (start - theta) % (2*math.pi)
    return amount <= -delta + _EPSILON


def _arc_bounds(x1, y1, rx, ry, phi, large_arc, sweep, x2, y2,
                transform: Affine2D) -> Bounds:
    rx, ry = abs(rx), abs(ry)
    if rx <= _EPSILON or ry <= _EPSILON:
        return _line_bounds(x1, y1, x2, y2, transform)

    phi = math.radians(phi % 360)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx = (x1 - x2) / 2
    dy = (y1 - y2) / 2
    x1p = cos_phi*dx + sin_phi*dy
    y1p = -sin_phi*dx + cos_phi*dy

    radii_scale = x1p*x1p/(rx*rx) + y1p*y1p/(ry*ry)
    if radii_scale > 1:
        scale = math.sqrt(radii_scale)
        rx *= scale
        ry *= scale

    numerator = max(0.0, rx*rx*ry*ry - rx*rx*y1p*y1p - ry*ry*x1p*x1p)
    denominator = rx*rx*y1p*y1p + ry*ry*x1p*x1p
    coefficient = 0.0
    if denominator > _EPSILON:
        coefficient = math.sqrt(numerator / denominator)
        if large_arc == sweep:
            coefficient = -coefficient
    cxp = coefficient * rx * y1p / ry
    cyp = -coefficient * ry * x1p / rx
    cx = cos_phi*cxp - sin_phi*cyp + (x1 + x2)/2
    cy = sin_phi*cxp + cos_phi*cyp + (y1 + y2)/2

    ux = (x1p - cxp) / rx
    uy = (y1p - cyp) / ry
    vx = (-x1p - cxp) / rx
    vy = (-y1p - cyp) / ry
    start_angle = math.atan2(uy, ux)
    delta_angle = math.atan2(ux*vy - uy*vx, ux*vx + uy*vy)
    if not sweep and delta_angle > 0:
        delta_angle -= 2*math.pi
    elif sweep and delta_angle < 0:
        delta_angle += 2*math.pi

    center = transform.apply(cx, cy)
    cos_axis = transform.apply_vector(cos_phi*rx, sin_phi*rx)
    sin_axis = transform.apply_vector(-sin_phi*ry, cos_phi*ry)
    bounds = _BoundsBuilder()

    def evaluate(theta):
        return (center[0] + cos_axis[0]*math.cos(theta)
                    + sin_axis[0]*math.sin(theta),
                center[1] + cos_axis[1]*math.cos(theta)
                    + sin_axis[1]*math.sin(theta))

    bounds.add_point(*evaluate(start_angle))
    bounds.add_point(*evaluate(start_angle + delta_angle))
    for axis in (0, 1):
        a = cos_axis[axis]
        b = sin_axis[axis]
        if abs(a) <= _EPSILON and abs(b) <= _EPSILON:
            continue
        theta = math.atan2(b, a)
        for candidate in (theta, theta + math.pi):
            if _angle_in_sweep(candidate, start_angle, delta_angle):
                bounds.add_point(*evaluate(candidate))
    return bounds.build()


def _path_bounds(d, transform: Affine2D) -> Optional[Bounds]:
    if d is None:
        return None
    if not isinstance(d, str):
        raise ValueError(f'path data must be a string, got {type(d).__name__}')
    tokens = _tokenize_path(d)
    if not tokens:
        return None

    bounds = _BoundsBuilder()
    current_x = current_y = 0.0
    start_x = start_y = 0.0
    command = None
    last_command = None
    previous_cubic_control = None
    previous_quadratic_control = None
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if _is_path_command(token):
            command = token
            index += 1
            if command in 'Zz':
                bounds.add_bounds(_line_bounds(
                        current_x, current_y, start_x, start_y, transform))
                current_x, current_y = start_x, start_y
                previous_cubic_control = None
                previous_quadratic_control = None
                last_command = command
                command = None
                continue
        elif command is None:
            raise ValueError(
                    f'path data contains unexpected token {token!r}')

        base = command.upper()
        relative = command.islower()
        count = _PATH_ARG_COUNTS[base]
        values, index = _take_path_args(tokens, index, count)

        if base == 'M':
            nx, ny = values
            if relative:
                current_x += nx
                current_y += ny
            else:
                current_x, current_y = nx, ny
            start_x, start_y = current_x, current_y
            previous_cubic_control = None
            previous_quadratic_control = None
            # Extra coordinate pairs after a moveto are treated as lineto.
            command = 'l' if relative else 'L'
        elif base == 'L':
            nx, ny = values
            if relative:
                nx += current_x
                ny += current_y
            bounds.add_bounds(_line_bounds(
                    current_x, current_y, nx, ny, transform))
            current_x, current_y = nx, ny
            previous_cubic_control = None
            previous_quadratic_control = None
        elif base == 'H':
            nx = values[0] + (current_x if relative else 0)
            bounds.add_bounds(_line_bounds(
                    current_x, current_y, nx, current_y, transform))
            current_x = nx
            previous_cubic_control = None
            previous_quadratic_control = None
        elif base == 'V':
            ny = values[0] + (current_y if relative else 0)
            bounds.add_bounds(_line_bounds(
                    current_x, current_y, current_x, ny, transform))
            current_y = ny
            previous_cubic_control = None
            previous_quadratic_control = None
        elif base == 'C':
            if relative:
                c1x, c1y = current_x + values[0], current_y + values[1]
                c2x, c2y = current_x + values[2], current_y + values[3]
                nx, ny = current_x + values[4], current_y + values[5]
            else:
                c1x, c1y, c2x, c2y, nx, ny = values
            bounds.add_bounds(_cubic_bounds(
                    (current_x, current_y), (c1x, c1y), (c2x, c2y),
                    (nx, ny), transform))
            previous_cubic_control = (c2x, c2y)
            previous_quadratic_control = None
            current_x, current_y = nx, ny
        elif base == 'S':
            if last_command in ('C', 'c', 'S', 's') and previous_cubic_control:
                c1x = 2*current_x - previous_cubic_control[0]
                c1y = 2*current_y - previous_cubic_control[1]
            else:
                c1x, c1y = current_x, current_y
            if relative:
                c2x, c2y = current_x + values[0], current_y + values[1]
                nx, ny = current_x + values[2], current_y + values[3]
            else:
                c2x, c2y, nx, ny = values
            bounds.add_bounds(_cubic_bounds(
                    (current_x, current_y), (c1x, c1y), (c2x, c2y),
                    (nx, ny), transform))
            previous_cubic_control = (c2x, c2y)
            previous_quadratic_control = None
            current_x, current_y = nx, ny
        elif base == 'Q':
            if relative:
                cx, cy = current_x + values[0], current_y + values[1]
                nx, ny = current_x + values[2], current_y + values[3]
            else:
                cx, cy, nx, ny = values
            bounds.add_bounds(_quadratic_bounds(
                    (current_x, current_y), (cx, cy), (nx, ny), transform))
            previous_quadratic_control = (cx, cy)
            previous_cubic_control = None
            current_x, current_y = nx, ny
        elif base == 'T':
            if (last_command in ('Q', 'q', 'T', 't')
                    and previous_quadratic_control):
                cx = 2*current_x - previous_quadratic_control[0]
                cy = 2*current_y - previous_quadratic_control[1]
            else:
                cx, cy = current_x, current_y
            if relative:
                nx, ny = current_x + values[0], current_y + values[1]
            else:
                nx, ny = values
            bounds.add_bounds(_quadratic_bounds(
                    (current_x, current_y), (cx, cy), (nx, ny), transform))
            previous_quadratic_control = (cx, cy)
            previous_cubic_control = None
            current_x, current_y = nx, ny
        elif base == 'A':
            rx, ry, phi, large_arc, sweep, nx, ny = values
            if relative:
                nx += current_x
                ny += current_y
            bounds.add_bounds(_arc_bounds(
                    current_x, current_y, rx, ry, phi, bool(large_arc),
                    bool(sweep), nx, ny, transform))
            previous_cubic_control = None
            previous_quadratic_control = None
            current_x, current_y = nx, ny
        last_command = command

    return bounds.build()


def _children(parent):
    for child in parent.children:
        yield child
    for z in sorted(parent.ordered_children):
        yield from parent.ordered_children[z]


def _unsupported(element):
    tag = getattr(element, 'TAG_NAME', type(element).__name__)
    raise UnsupportedGeometryError(
            'cannot calculate automatic viewBox: unsupported visible element '
            f'{type(element).__name__} (<{tag}>)')


def element_bounds(element, transform: Affine2D = IDENTITY) -> Optional[Bounds]:
    '''Return the tight geometric bounds of an element and its children.'''
    from . import elements

    args = getattr(element, 'args', {})
    if args.get('display') == 'none' or args.get('visibility') in (
            'hidden', 'collapse'):
        return None

    if isinstance(element, elements.Group):
        local_transform = transform @ parse_transform(
                element.args.get('transform'))
        result = None
        for child in _children(element):
            child_bounds = element_bounds(child, local_transform)
            result = child_bounds if result is None else result.union(
                    child_bounds)
        return result

    # Text, external images, titles, and animation metadata do not contribute
    # geometry to the viewBox calculation.
    ignored_types = (
            elements.Text, elements._TextContainingElement,
            elements._TextPath, elements.Image, elements.NoElement,
            elements.Animate,
    )
    if isinstance(element, ignored_types):
        return None

    local_transform = transform @ parse_transform(
            getattr(element, 'args', {}).get('transform'))
    if isinstance(element, elements.Rectangle):
        x = _number(element.args['x'], 'rectangle x')
        y = _number(element.args['y'], 'rectangle y')
        width = _number(element.args['width'], 'rectangle width')
        height = _number(element.args['height'], 'rectangle height')
        return _points_bounds((
                (x, y), (x+width, y), (x+width, y+height), (x, y+height)),
                local_transform)
    if isinstance(element, elements.Circle):
        cx = _number(element.args['cx'], 'circle cx')
        cy = _number(element.args['cy'], 'circle cy')
        r = abs(_number(element.args['r'], 'circle r'))
        return _ellipse_bounds(cx, cy, r, r, local_transform)
    if isinstance(element, elements.Ellipse):
        cx = _number(element.args['cx'], 'ellipse cx')
        cy = _number(element.args['cy'], 'ellipse cy')
        rx = abs(_number(element.args['rx'], 'ellipse rx'))
        ry = abs(_number(element.args['ry'], 'ellipse ry'))
        return _ellipse_bounds(cx, cy, rx, ry, local_transform)
    if isinstance(element, elements.AnimatableLine):
        x1 = _number(element.args['x1'], 'line x1')
        y1 = _number(element.args['y1'], 'line y1')
        x2 = _number(element.args['x2'], 'line x2')
        y2 = _number(element.args['y2'], 'line y2')
        return _line_bounds(x1, y1, x2, y2, local_transform)
    if isinstance(element, elements.Path):
        return _path_bounds(element.args.get('d', ''), local_transform)

    _unsupported(element)


def drawing_bounds(elements: Iterable) -> Optional[Bounds]:
    '''Return the union of the tight geometric bounds of many elements.'''
    result = None
    for element in elements:
        bounds = element_bounds(element)
        result = bounds if result is None else result.union(bounds)
    return result
