'''Geometry helpers used to fit a drawing's viewBox to its contents.

This module deliberately works on the element attribute values without
changing them.  Bounds are calculated from geometry only; stroke, markers,
text, filters, and external resources are not included.
'''

from __future__ import annotations

import math
import re
from dataclasses import dataclass


class EmptyDrawingError(ValueError):
    '''Raised when automatic viewBox fitting has no geometry to fit.'''


class UnsupportedGeometryError(NotImplementedError):
    '''Raised for visible elements whose geometry cannot be measured safely.'''


_NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
_NUMBER_RE = re.compile(_NUMBER)
_PATH_TOKEN_RE = re.compile(r'[AaCcHhLlMmQqSsTtVvZz]|' + _NUMBER)
_SEPARATOR_RE = re.compile(r'[\s,]*')
_TRANSFORM_RE = re.compile(r'([A-Za-z]+)\s*\(([^)]*)\)')


def _as_float(value, description='number'):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'invalid {description}: {value!r}') from exc
    if not math.isfinite(result):
        raise ValueError(f'non-finite {description}: {value!r}')
    return result


@dataclass(frozen=True)
class Matrix:
    '''A two-dimensional affine transform.

    SVG's matrix(a, b, c, d, e, f) maps (x, y) to
    (a*x + c*y + e, b*x + d*y + f).
    '''
    a: float = 1
    b: float = 0
    c: float = 0
    d: float = 1
    e: float = 0
    f: float = 0

    def __matmul__(self, other):
        '''Compose transforms, applying ``other`` before ``self``.'''
        return Matrix(
            self.a*other.a + self.c*other.b,
            self.b*other.a + self.d*other.b,
            self.a*other.c + self.c*other.d,
            self.b*other.c + self.d*other.d,
            self.a*other.e + self.c*other.f + self.e,
            self.b*other.e + self.d*other.f + self.f,
        )

    def point(self, x, y):
        return (self.a*x + self.c*y + self.e,
                self.b*x + self.d*y + self.f)

    def vector(self, x, y):
        return (self.a*x + self.c*y,
                self.b*x + self.d*y)


def _transform_args(text):
    values = []
    position = 0
    for match in _NUMBER_RE.finditer(text):
        if not _SEPARATOR_RE.fullmatch(text[position:match.start()]):
            raise ValueError(f'invalid transform arguments: {text!r}')
        values.append(_as_float(match.group(0), 'transform argument'))
        position = match.end()
    if not _SEPARATOR_RE.fullmatch(text[position:]):
        raise ValueError(f'invalid transform arguments: {text!r}')
    return values


def parse_transform(transform):
    '''Parse an SVG transform list into a :class:`Matrix`.'''
    if transform is None or transform == '':
        return Matrix()
    if not isinstance(transform, str):
        raise ValueError(f'unsupported transform value: {transform!r}')

    matrix = Matrix()
    position = 0
    for match in _TRANSFORM_RE.finditer(transform):
        if not _SEPARATOR_RE.fullmatch(transform[position:match.start()]):
            raise ValueError(f'invalid transform: {transform!r}')
        name = match.group(1)
        values = _transform_args(match.group(2))
        lower_name = name.lower()
        if lower_name == 'matrix' and len(values) == 6:
            operation = Matrix(*values)
        elif lower_name == 'translate' and len(values) in (1, 2):
            tx = values[0]
            ty = values[1] if len(values) == 2 else 0
            operation = Matrix(e=tx, f=ty)
        elif lower_name == 'scale' and len(values) in (1, 2):
            sx = values[0]
            sy = values[1] if len(values) == 2 else sx
            operation = Matrix(a=sx, d=sy)
        elif lower_name == 'rotate' and len(values) in (1, 3):
            angle = math.radians(values[0])
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            rotation = Matrix(cos_a, sin_a, -sin_a, cos_a, 0, 0)
            if len(values) == 3:
                cx, cy = values[1:]
                operation = (Matrix(e=cx, f=cy) @ rotation
                             @ Matrix(e=-cx, f=-cy))
            else:
                operation = rotation
        elif lower_name == 'skewx' and len(values) == 1:
            operation = Matrix(c=math.tan(math.radians(values[0])))
        elif lower_name == 'skewy' and len(values) == 1:
            operation = Matrix(b=math.tan(math.radians(values[0])))
        else:
            raise ValueError(f'invalid transform function: {transform!r}')
        matrix = matrix @ operation
        position = match.end()
    if not _SEPARATOR_RE.fullmatch(transform[position:]):
        raise ValueError(f'invalid transform: {transform!r}')
    return matrix


class Bounds:
    '''An axis-aligned bounding box accumulator.'''
    def __init__(self):
        self.minx = math.inf
        self.miny = math.inf
        self.maxx = -math.inf
        self.maxy = -math.inf

    @property
    def is_empty(self):
        return self.minx > self.maxx

    def add_point(self, x, y):
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError('geometry contains a non-finite coordinate')
        self.minx = min(self.minx, x)
        self.miny = min(self.miny, y)
        self.maxx = max(self.maxx, x)
        self.maxy = max(self.maxy, y)

    def add_points(self, points):
        for x, y in points:
            self.add_point(x, y)

    def add_cubic(self, p0, p1, p2, p3):
        self.add_points((p0, p3))
        for axis in (0, 1):
            p0v, p1v, p2v, p3v = (p[axis] for p in (p0, p1, p2, p3))
            # The derivative divided by 3 is a quadratic:
            # (-p0 + 3*p1 - 3*p2 + p3)t^2
            # + 2*(p0 - 2*p1 + p2)t + (p1 - p0)
            quadratic = -p0v + 3*p1v - 3*p2v + p3v
            linear = 2*(p0v - 2*p1v + p2v)
            constant = p1v - p0v
            for t in _quadratic_roots(quadratic, linear, constant):
                if 0 < t < 1:
                    self.add_point(*_cubic_point(p0, p1, p2, p3, t))

    def add_quadratic(self, p0, p1, p2):
        self.add_points((p0, p2))
        for axis in (0, 1):
            p0v, p1v, p2v = (p[axis] for p in (p0, p1, p2))
            denominator = p0v - 2*p1v + p2v
            numerator = p0v - p1v
            if denominator != 0:
                t = numerator / denominator
                if 0 < t < 1:
                    self.add_point(*_quadratic_point(p0, p1, p2, t))

    def add_ellipse(self, center, cos_vector, sin_vector, start_angle=0,
                    sweep_angle=2*math.pi):
        '''Add an elliptical arc given by C + Vc*cos(t) + Vs*sin(t).'''
        end_angle = start_angle + sweep_angle
        self.add_point(*_ellipse_point(
            center, cos_vector, sin_vector, start_angle))
        self.add_point(*_ellipse_point(
            center, cos_vector, sin_vector, end_angle))
        for axis in (0, 1):
            # d/dt (Vc*cos(t) + Vs*sin(t)) = 0
            angle = math.atan2(sin_vector[axis], cos_vector[axis])
            for candidate in (angle, angle + math.pi):
                if _angle_on_sweep(candidate, start_angle, sweep_angle):
                    self.add_point(*_ellipse_point(
                        center, cos_vector, sin_vector, candidate))

    def as_tuple(self, padding=0):
        if self.is_empty:
            raise EmptyDrawingError(
                'cannot fit viewBox: drawing contains no supported geometry')
        return (self.minx - padding, self.miny - padding,
                self.maxx - self.minx + 2*padding,
                self.maxy - self.miny + 2*padding)


def _quadratic_roots(a, b, c):
    if abs(a) < 1e-15:
        if abs(b) < 1e-15:
            return ()
        return (-c / b,)
    discriminant = b*b - 4*a*c
    if discriminant < 0:
        return ()
    root = math.sqrt(discriminant)
    return ((-b - root) / (2*a), (-b + root) / (2*a))


def _cubic_point(p0, p1, p2, p3, t):
    one_minus_t = 1 - t
    return tuple(
        one_minus_t**3*p0[i] + 3*one_minus_t**2*t*p1[i]
        + 3*one_minus_t*t**2*p2[i] + t**3*p3[i]
        for i in (0, 1))


def _quadratic_point(p0, p1, p2, t):
    one_minus_t = 1 - t
    return tuple(
        one_minus_t**2*p0[i] + 2*one_minus_t*t*p1[i] + t**2*p2[i]
        for i in (0, 1))


def _ellipse_point(center, cos_vector, sin_vector, angle):
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return (center[0] + cos_vector[0]*cos_a + sin_vector[0]*sin_a,
            center[1] + cos_vector[1]*cos_a + sin_vector[1]*sin_a)


def _angle_on_sweep(angle, start, sweep):
    if abs(sweep) >= 2*math.pi - 1e-12:
        return True
    if sweep >= 0:
        return (angle - start) % (2*math.pi) <= sweep + 1e-12
    return (start - angle) % (2*math.pi) <= -sweep + 1e-12


def _tokenize_path(path):
    if not isinstance(path, str):
        raise ValueError(f'invalid path data: {path!r}')
    tokens = []
    position = 0
    for match in _PATH_TOKEN_RE.finditer(path):
        if not _SEPARATOR_RE.fullmatch(path[position:match.start()]):
            raise ValueError(f'invalid path data near {path[position:]!r}')
        tokens.append(match.group(0))
        position = match.end()
    if not _SEPARATOR_RE.fullmatch(path[position:]):
        raise ValueError(f'invalid path data near {path[position:]!r}')
    return tokens


_PATH_ARG_COUNTS = {
    'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4, 'T': 2,
    'A': 7, 'Z': 0,
}


def _arc_center(start, end, rx, ry, rotation, large_arc, sweep):
    '''Return (center, rx, ry, start_angle, sweep_angle) in user space.'''
    if start == end:
        return None
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return None

    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx = (start[0] - end[0]) / 2
    dy = (start[1] - end[1]) / 2
    x1p = cos_phi*dx + sin_phi*dy
    y1p = -sin_phi*dx + cos_phi*dy

    radii_scale = x1p*x1p/(rx*rx) + y1p*y1p/(ry*ry)
    if radii_scale > 1:
        scale = math.sqrt(radii_scale)
        rx *= scale
        ry *= scale

    rx2, ry2 = rx*rx, ry*ry
    x1p2, y1p2 = x1p*x1p, y1p*y1p
    denominator = rx2*y1p2 + ry2*x1p2
    numerator = rx2*ry2 - rx2*y1p2 - ry2*x1p2
    factor = 0 if denominator == 0 else math.sqrt(
        max(0, numerator / denominator))
    if bool(large_arc) == bool(sweep):
        factor = -factor
    cxp = factor * rx * y1p / ry
    cyp = -factor * ry * x1p / rx
    center = (
        cos_phi*cxp - sin_phi*cyp + (start[0] + end[0])/2,
        sin_phi*cxp + cos_phi*cyp + (start[1] + end[1])/2,
    )

    start_angle = math.atan2(
        (y1p - cyp) / ry, (x1p - cxp) / rx)
    end_angle = math.atan2(
        (-y1p - cyp) / ry, (-x1p - cxp) / rx)
    sweep_angle = end_angle - start_angle
    if sweep and sweep_angle < 0:
        sweep_angle += 2*math.pi
    elif not sweep and sweep_angle > 0:
        sweep_angle -= 2*math.pi
    return center, rx, ry, start_angle, sweep_angle


def _add_arc(bounds, start, end, rx, ry, rotation, large_arc, sweep, matrix):
    arc = _arc_center(start, end, rx, ry, rotation, large_arc, sweep)
    bounds.add_point(*matrix.point(*start))
    bounds.add_point(*matrix.point(*end))
    if arc is None:
        return

    center, rx, ry, start_angle, sweep_angle = arc
    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    transformed_center = matrix.point(*center)
    cos_vector = matrix.vector(cos_phi*rx, sin_phi*rx)
    sin_vector = matrix.vector(-sin_phi*ry, cos_phi*ry)
    bounds.add_ellipse(
        transformed_center, cos_vector, sin_vector,
        start_angle, sweep_angle)


def path_bounds(path_data, matrix=None):
    '''Calculate the geometry bounds of SVG path data after a transform.'''
    if matrix is None:
        matrix = Matrix()
    tokens = _tokenize_path(path_data)
    bounds = Bounds()
    index = 0
    command = None
    current = (0.0, 0.0)
    subpath_start = current
    previous_command = None
    previous_cubic_control = None
    previous_quadratic_control = None

    def values(count):
        nonlocal index
        if index + count > len(tokens):
            raise ValueError(f'incomplete path command {command!r}')
        chunk = tokens[index:index+count]
        if any(token in 'AaCcHhLlMmQqSsTtVvZz' for token in chunk):
            raise ValueError(f'incomplete path command {command!r}')
        index += count
        return tuple(_as_float(token, 'path coordinate') for token in chunk)

    while index < len(tokens):
        token = tokens[index]
        if token in 'AaCcHhLlMmQqSsTtVvZz':
            command = token
            index += 1
        elif command is None:
            raise ValueError('path data must start with a command')
        elif command in 'Zz':
            raise ValueError('unexpected number after path close command')

        upper = command.upper()
        relative = command.islower()
        if upper == 'Z':
            bounds.add_point(*matrix.point(*subpath_start))
            current = subpath_start
            previous_command = 'Z'
            previous_cubic_control = None
            previous_quadratic_control = None
            continue

        count = _PATH_ARG_COUNTS[upper]
        args = values(count)
        if upper == 'M':
            point = _path_point(args[0], args[1], current, relative)
            current = subpath_start = point
            bounds.add_point(*matrix.point(*current))
            previous_cubic_control = None
            previous_quadratic_control = None
        elif upper == 'L':
            point = _path_point(args[0], args[1], current, relative)
            _add_line(bounds, current, point, matrix)
            current = point
            previous_cubic_control = None
            previous_quadratic_control = None
        elif upper == 'H':
            x = args[0] + current[0] if relative else args[0]
            point = (x, current[1])
            _add_line(bounds, current, point, matrix)
            current = point
            previous_cubic_control = None
            previous_quadratic_control = None
        elif upper == 'V':
            y = args[0] + current[1] if relative else args[0]
            point = (current[0], y)
            _add_line(bounds, current, point, matrix)
            current = point
            previous_cubic_control = None
            previous_quadratic_control = None
        elif upper == 'C':
            control1 = _path_point(args[0], args[1], current, relative)
            control2 = _path_point(args[2], args[3], current, relative)
            end = _path_point(args[4], args[5], current, relative)
            _add_cubic(bounds, current, control1, control2, end, matrix)
            current = end
            previous_cubic_control = control2
            previous_quadratic_control = None
        elif upper == 'S':
            if previous_command in ('C', 'S'):
                control1 = (
                    2*current[0] - previous_cubic_control[0],
                    2*current[1] - previous_cubic_control[1])
            else:
                control1 = current
            control2 = _path_point(args[0], args[1], current, relative)
            end = _path_point(args[2], args[3], current, relative)
            _add_cubic(bounds, current, control1, control2, end, matrix)
            current = end
            previous_cubic_control = control2
            previous_quadratic_control = None
        elif upper == 'Q':
            control = _path_point(args[0], args[1], current, relative)
            end = _path_point(args[2], args[3], current, relative)
            _add_quadratic(bounds, current, control, end, matrix)
            current = end
            previous_quadratic_control = control
            previous_cubic_control = None
        elif upper == 'T':
            if previous_command in ('Q', 'T'):
                control = (
                    2*current[0] - previous_quadratic_control[0],
                    2*current[1] - previous_quadratic_control[1])
            else:
                control = current
            end = _path_point(args[0], args[1], current, relative)
            _add_quadratic(bounds, current, control, end, matrix)
            current = end
            previous_quadratic_control = control
            previous_cubic_control = None
        elif upper == 'A':
            end = _path_point(args[5], args[6], current, relative)
            _add_arc(
                bounds, current, end, args[0], args[1], args[2],
                bool(args[3]), bool(args[4]), matrix)
            current = end
            previous_cubic_control = None
            previous_quadratic_control = None

        previous_command = upper
        if upper == 'M':
            command = 'l' if relative else 'L'

    return bounds


def _path_point(x, y, current, relative):
    if relative:
        return (current[0] + x, current[1] + y)
    return (x, y)


def _add_line(bounds, start, end, matrix):
    bounds.add_point(*matrix.point(*start))
    bounds.add_point(*matrix.point(*end))


def _add_cubic(bounds, start, control1, control2, end, matrix):
    bounds.add_cubic(
        matrix.point(*start), matrix.point(*control1),
        matrix.point(*control2), matrix.point(*end))


def _add_quadratic(bounds, start, control, end, matrix):
    bounds.add_quadratic(
        matrix.point(*start), matrix.point(*control), matrix.point(*end))


def _attribute_float(args, name, default=None):
    value = args.get(name, default)
    if value is None:
        raise ValueError(f'missing required geometry attribute {name!r}')
    return _as_float(value, f'geometry attribute {name!r}')


def element_bounds(element, matrix=None, bounds=None):
    '''Accumulate the geometry bounds of an element and its visible children.'''
    from . import elements, defs

    if matrix is None:
        matrix = Matrix()
    if bounds is None:
        bounds = Bounds()

    if isinstance(element, elements.NoElement):
        return bounds
    if isinstance(element, (elements.Title, elements.Animate, elements.Raw)):
        if isinstance(element, elements.Raw):
            raise UnsupportedGeometryError(
                'cannot automatically fit viewBox around Raw SVG content')
        return bounds
    if isinstance(element, (elements.Text, elements.Image)):
        return bounds
    if isinstance(element, (defs.DrawingDef, defs.DrawingDefSub)):
        return bounds

    tag_name = getattr(element, 'TAG_NAME', None)
    if isinstance(element, elements.Group) or tag_name == 'g':
        local_matrix = matrix @ parse_transform(element.args.get('transform'))
        children = list(element.children)
        for z in sorted(element.ordered_children):
            children.extend(element.ordered_children[z])
        for child in children:
            element_bounds(child, local_matrix, bounds)
        return bounds

    local_matrix = matrix @ parse_transform(element.args.get('transform'))
    args = element.args
    if isinstance(element, elements.Rectangle) or tag_name == 'rect':
        x = _attribute_float(args, 'x', 0)
        y = _attribute_float(args, 'y', 0)
        width = _attribute_float(args, 'width')
        height = _attribute_float(args, 'height')
        bounds.add_points(local_matrix.point(x, y) for x, y in (
            (x, y), (x + width, y), (x, y + height), (x + width, y + height)))
    elif isinstance(element, elements.Circle) or tag_name == 'circle':
        cx = _attribute_float(args, 'cx', 0)
        cy = _attribute_float(args, 'cy', 0)
        radius = _attribute_float(args, 'r')
        bounds.add_ellipse(
            local_matrix.point(cx, cy),
            local_matrix.vector(radius, 0),
            local_matrix.vector(0, radius))
    elif isinstance(element, elements.Ellipse) or tag_name == 'ellipse':
        cx = _attribute_float(args, 'cx', 0)
        cy = _attribute_float(args, 'cy', 0)
        rx = _attribute_float(args, 'rx')
        ry = _attribute_float(args, 'ry')
        bounds.add_ellipse(
            local_matrix.point(cx, cy),
            local_matrix.vector(rx, 0),
            local_matrix.vector(0, ry))
    elif isinstance(element, elements.Path) or tag_name == 'path':
        path_bounds_value = path_bounds(args.get('d', ''), local_matrix)
        if not path_bounds_value.is_empty:
            bounds.add_point(path_bounds_value.minx, path_bounds_value.miny)
            bounds.add_point(path_bounds_value.maxx, path_bounds_value.maxy)
    elif tag_name == 'line':
        x1 = _attribute_float(args, 'x1', 0)
        y1 = _attribute_float(args, 'y1', 0)
        x2 = _attribute_float(args, 'x2', 0)
        y2 = _attribute_float(args, 'y2', 0)
        bounds.add_point(*local_matrix.point(x1, y1))
        bounds.add_point(*local_matrix.point(x2, y2))
    elif tag_name in ('polyline', 'polygon'):
        _add_points_attribute(bounds, args.get('points', ''), local_matrix)
    else:
        raise UnsupportedGeometryError(
            f'cannot automatically fit viewBox around unsupported visible '
            f'element <{tag_name or type(element).__name__}>')
    return bounds


def _add_points_attribute(bounds, points_text, matrix):
    if not isinstance(points_text, str):
        raise ValueError(f'invalid points attribute: {points_text!r}')
    values = [_as_float(value, 'point coordinate')
              for value in _NUMBER_RE.findall(points_text)]
    if len(values) % 2:
        raise ValueError('points attribute must contain x/y pairs')
    bounds.add_points(
        matrix.point(values[i], values[i+1])
        for i in range(0, len(values), 2))


def drawing_bounds(elements, transform=None):
    '''Calculate bounds for a sequence of top-level drawing elements.'''
    bounds = Bounds()
    root_matrix = parse_transform(transform)
    for element in elements:
        element_bounds(element, root_matrix, bounds)
    return bounds
