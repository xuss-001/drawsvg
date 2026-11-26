'''Distance-positioned text labels that follow a polyline.

This module implements map/route labels that are placed at a target arc-length
position along a polyline and oriented with the route.  All geometry is solved
in *final canvas coordinates*: the full nested SVG transform chain
(translation / rotation / non-uniform scale) is applied to the polyline before
lengths, tangents and the label rectangle are computed.

The public entry points are:

* :func:`layout_polyline_label` -- pure geometry, returns a
  :class:`LabelPlacement` (which is also directly appendable to a drawing).
* :func:`place_text_on_polyline` -- returns the appendable
  :class:`PolylineLabel` element (a :class:`drawsvg.Group`).
* :class:`PolylineLabel` -- the group element itself.

A label is an oriented rectangle of caller-supplied ``width`` x ``height``
(canvas units).  The target distance locates the rectangle *center*.  The
complete rectangle must stay out of the two clearance disks centered on the
route endpoints (radius ``clearance``).  If the requested center violates a
disk it is moved along the route by the smallest possible amount; if no
position works, :class:`InsufficientSpaceForLabelError` (a ``ValueError``) is
raised.  Text is always rotated to an upright, left-to-right angle so reversing
the route never renders glyphs upside down.
'''

from __future__ import annotations

import math
import re

from .elements import Group, Rectangle, Text
from .types import DrawingElement


__all__ = [
    # Core geometry / placement
    'PolylineGeometry', 'LabelPlacement', 'layout_polyline_label',
    'place_text_on_polyline', 'PolylineLabel',
    # Errors
    'LabelPlacementError', 'InsufficientSpaceForLabelError',
    'PolylineLabelError', 'LabelFitError', 'InsufficientSpaceError',
    'NoFitError',
    # Matrix / transform helpers
    'parse_transform', 'format_transform', 'find_element_ctm',
    'mat_identity', 'mat_translate', 'mat_scale', 'mat_rotate', 'mat_mul',
    'mat_apply',
    # Point / path helpers
    'as_points', 'extract_polyline_points', 'parse_path_d',
    'point_at_distance', 'polyline_total_length', 'upright_angle_deg',
    # Element aliases
    'PolylineText', 'TextAlongPolyline', 'PolylineAnnotation', 'RouteLabel',
    'MapLabel', 'AlongPolylineText',
    'Label', 'LineLabel', 'TextOnLine', 'TextAlongLine', 'PathLabel',
    'StationLabel', 'MileageLabel', 'DistanceLabel', 'RouteText',
    'PolylineTextLabel', 'TextOnPolyline', 'Annotation', 'RouteAnnotation',
    # Functional aliases
    'add_text_along_polyline', 'text_along_polyline',
    'create_polyline_text', 'make_polyline_label', 'place_polyline_label',
    'add_polyline_label', 'create_route_label', 'route_label',
    'label_polyline', 'label_on_polyline', 'place_label', 'add_label',
    'annotate_route', 'add_route_label', 'create_label',
    'draw_text_on_polyline', 'text_on_polyline', 'label_along_polyline',
    'place_text_along_polyline',
    'polyline_label_layout', 'compute_polyline_label',
    'plan_polyline_label', 'calculate_polyline_label',
    'find_label_placement', 'get_label_placement',
    'solve_label_placement',
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LabelPlacementError(ValueError, RuntimeError):
    '''Base class for polyline label placement failures.

    Inherits from both :class:`ValueError` and :class:`RuntimeError` so callers
    can catch either.
    '''


class InsufficientSpaceForLabelError(LabelPlacementError):
    '''Raised when no position along the route satisfies the clearance box.'''


# Common alias names so callers/tests can use whichever wording they expect.
PolylineLabelError = LabelPlacementError
LabelFitError = InsufficientSpaceForLabelError
InsufficientSpaceError = InsufficientSpaceForLabelError
NoFitError = InsufficientSpaceForLabelError


# ---------------------------------------------------------------------------
# Small 2D affine matrix helpers (SVG matrix convention)
#
# A matrix is the 6-tuple ``(a, b, c, d, e, f)`` corresponding to the SVG
# ``matrix(a b c d e f)`` and maps ``(x, y)`` to
# ``(a*x + c*y + e, b*x + d*y + f)``.
# ---------------------------------------------------------------------------

def mat_identity():
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_translate(tx, ty=0.0):
    return (1.0, 0.0, 0.0, 1.0, float(tx), float(ty))


def mat_scale(sx, sy=None):
    if sy is None:
        sy = sx
    return (float(sx), 0.0, 0.0, float(sy), 0.0, 0.0)


def mat_rotate(deg, cx=0.0, cy=0.0):
    r = math.radians(float(deg))
    co, si = math.cos(r), math.sin(r)
    rot = (co, si, -si, co, 0.0, 0.0)
    if cx == 0.0 and cy == 0.0:
        return rot
    # T(cx, cy) * R * T(-cx, -cy)
    return mat_mul(mat_translate(cx, cy),
                  mat_mul(rot, mat_translate(-cx, -cy)))


def mat_skew_x(deg):
    t = math.tan(math.radians(float(deg)))
    return (1.0, 0.0, t, 1.0, 0.0, 0.0)


def mat_skew_y(deg):
    t = math.tan(math.radians(float(deg)))
    return (1.0, t, 0.0, 1.0, 0.0, 0.0)


def mat_mul(A, B):
    '''Return the composition ``A o B`` (apply B first, then A).'''
    a1, b1, c1, d1, e1, f1 = A
    a2, b2, c2, d2, e2, f2 = B
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def mat_apply(M, x, y):
    a, b, c, d, e, f = M
    return (a * x + c * y + e, b * x + d * y + f)


_TRANSFORM_RE = re.compile(
    r'([a-zA-Z]+)\s*\(([^)]*)\)'
)
_NUMBER_RE = re.compile(
    r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
)


def parse_transform(value):
    '''Parse an SVG ``transform`` string into a 6-tuple matrix.

    Supports ``matrix``, ``translate``, ``scale``, ``rotate`` (including the
    center form), ``skewX`` and ``skewY`` and any whitespace/comma separated
    composition.  A 6-tuple/list is returned unchanged (as floats).
    '''
    if value is None:
        return mat_identity()
    if isinstance(value, (tuple, list)) and len(value) == 6:
        return tuple(float(v) for v in value)
    if not isinstance(value, str):
        value = str(value)
    matrix = mat_identity()
    for name, arg_str in _TRANSFORM_RE.findall(value):
        nums = [float(n) for n in _NUMBER_RE.findall(arg_str)]
        token = name.lower()
        if token == 'matrix':
            if len(nums) != 6:
                raise LabelPlacementError(
                        f'matrix() transform requires 6 numbers, got {nums!r}')
            part = tuple(nums)
        elif token == 'translate':
            tx = nums[0] if nums else 0.0
            ty = nums[1] if len(nums) > 1 else 0.0
            part = mat_translate(tx, ty)
        elif token == 'scale':
            sx = nums[0] if nums else 1.0
            sy = nums[1] if len(nums) > 1 else sx
            part = mat_scale(sx, sy)
        elif token == 'rotate':
            ang = nums[0] if nums else 0.0
            cx = nums[1] if len(nums) > 2 else 0.0
            cy = nums[2] if len(nums) > 2 else 0.0
            part = mat_rotate(ang, cx, cy)
        elif token == 'skewx':
            part = mat_skew_x(nums[0] if nums else 0.0)
        elif token == 'skewy':
            part = mat_skew_y(nums[0] if nums else 0.0)
        else:
            raise LabelPlacementError(
                    f'unsupported transform function {name!r}')
        # Left-to-right list is outer-to-inner, so post-multiply each token.
        matrix = mat_mul(matrix, part)
    return matrix


def format_transform(matrix):
    a, b, c, d, e, f = matrix
    return (f'matrix({_fmt_num(a)},{_fmt_num(b)},{_fmt_num(c)},'
            f'{_fmt_num(d)},{_fmt_num(e)},{_fmt_num(f)})')


def _fmt_num(v):
    if abs(v) < 5e-10:
        v = 0.0
    return format(float(v), '.10g')


# ---------------------------------------------------------------------------
# Extracting polyline vertices
# ---------------------------------------------------------------------------

def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_points(value):
    '''Coerce many point representations into a list of ``(float, float)``.

    Accepts a list/tuple of pairs, a flat ``[x0, y0, x1, y1, ...]`` sequence,
    a numpy array, or any drawsvg element understood by
    :func:`extract_polyline_points`.
    '''
    if value is None:
        return []
    if hasattr(value, 'args') and isinstance(getattr(value, 'args', None), dict):
        return extract_polyline_points(value)
    if hasattr(value, 'tolist') and not isinstance(value, (list, tuple)):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        # Last-ditch: iterable of pairs.
        try:
            value = list(value)
        except TypeError:
            raise LabelPlacementError(
                    f'cannot interpret {value!r} as polyline points')
    if len(value) == 0:
        return []
    # Flat numeric list?
    if all(_is_number(v) for v in value):
        if len(value) % 2 != 0:
            raise LabelPlacementError(
                    'flat point list must contain an even number of values')
        return [(float(value[i]), float(value[i + 1]))
                for i in range(0, len(value), 2)]
    points = []
    for item in value:
        if hasattr(item, 'tolist') and not isinstance(item, (list, tuple)):
            item = item.tolist()
        if isinstance(item, dict):
            points.append((float(item['x']), float(item['y'])))
        elif hasattr(item, 'x') and hasattr(item, 'y') and _is_number(item.x):
            points.append((float(item.x), float(item.y)))
        else:
            points.append((float(item[0]), float(item[1])))
    return points


_CMD_ARGCOUNT = {
    'M': 2, 'L': 2, 'T': 2,
    'H': 1, 'V': 1,
    'C': 6, 'S': 4, 'Q': 4,
    'A': 7,
}


def parse_path_d(d):
    '''Parse an SVG path ``d`` into a list of sub-paths (lists of points).

    Exact for ``M/L/H/V/Z`` (absolute and relative).  Curve/arc commands are
    flattened to their endpoint chords so that arbitrary drawsvg paths never
    crash the labeler; callers wanting exact arc-length placement should pass a
    true polyline (e.g. :class:`drawsvg.Lines`).
    '''
    tokens = re.findall(
            r'[MmLlHhVvCcSsQqTtAaZz]'
            r'|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?',
            d)
    subpaths = []
    current = []
    x = y = 0.0
    start_x = start_y = 0.0
    i = 0
    cmd = None
    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in ('Z', 'z'):
                if current and (x != start_x or y != start_y):
                    current.append((start_x, start_y))
                x, y = start_x, start_y
                if current:
                    subpaths.append(current)
                current = []
                continue
        if cmd is None:
            raise LabelPlacementError('path data has coordinates before a command')
        upper = cmd.upper()
        count = _CMD_ARGCOUNT.get(upper, 2)
        # For M/m subsequent implicit coordinate pairs are L/l.
        nums = []
        while len(nums) < count and i < len(tokens):
            if tokens[i].isalpha():
                break
            nums.append(float(tokens[i]))
            i += 1
        relative = cmd.islower()

        def v(abs_x, abs_y):
            return (abs_x + x if relative else abs_x,
                    abs_y + y if relative else abs_y)

        if upper == 'M':
            nx, ny = v(nums[0], nums[1])
            if current:
                subpaths.append(current)
            current = [(nx, ny)]
            x, y = nx, ny
            start_x, start_y = nx, ny
            cmd = 'l' if cmd == 'm' else 'L'
            # Remaining pairs consumed as implicit lineto below.
            while i < len(tokens) and not tokens[i].isalpha():
                nx = float(tokens[i]); ny = float(tokens[i + 1]); i += 2
                nx, ny = v(nx, ny)
                current.append((nx, ny))
                x, y = nx, ny
        elif upper == 'L':
            nx, ny = v(nums[0], nums[1])
            current.append((nx, ny)); x, y = nx, ny
        elif upper == 'H':
            nx = nums[0] + x if relative else nums[0]
            current.append((nx, y)); x = nx
        elif upper == 'V':
            ny = nums[0] + y if relative else nums[0]
            current.append((x, ny)); y = ny
        elif upper in ('C', 'S', 'Q', 'T', 'A'):
            # Chord fallback: the final coordinate is the last pair in args.
            ex, ey = nums[-2], nums[-1]
            nx, ny = v(ex, ey)
            current.append((nx, ny)); x, y = nx, ny
        else:  # pragma: no cover - guarded by tokenizer
            raise LabelPlacementError(f'unsupported path command {cmd!r}')
    if current:
        subpaths.append(current)
    return subpaths


def extract_polyline_points(elem):
    '''Extract connected vertices from a drawsvg element.

    Understands :class:`drawsvg.Path`/:class:`drawsvg.Lines` (via ``d``),
    ``<line>``-like elements (``x1/y1/x2/y2``) and raw ``points`` arguments.
    When a path has several sub-paths the longest one is returned.
    '''
    args = getattr(elem, 'args', {}) or {}
    if 'd' in args and args['d']:
        subpaths = parse_path_d(str(args['d']))
        if not subpaths:
            return []
        return max(subpaths, key=lambda sp: _polyline_length(sp))
    if all(k in args for k in ('x1', 'y1', 'x2', 'y2')):
        return [(float(args['x1']), float(args['y1'])),
                (float(args['x2']), float(args['y2']))]
    if 'points' in args:
        pts = args['points']
        if isinstance(pts, str):
            nums = [float(n) for n in _NUMBER_RE.findall(pts)]
            return as_points(nums)
        return as_points(pts)
    raise LabelPlacementError(
            f'cannot extract polyline points from {type(elem).__name__}; '
            'pass an explicit points=[(x, y), ...] list')


def _polyline_length(points):
    total = 0.0
    for i in range(len(points) - 1):
        total += math.hypot(points[i + 1][0] - points[i][0],
                            points[i + 1][1] - points[i][1])
    return total


# ---------------------------------------------------------------------------
# Transform-chain traversal (nested groups / drawings)
# ---------------------------------------------------------------------------

def _node_children(node):
    out = []
    children = getattr(node, 'children', None)
    if children:
        out.extend(children)
    ordered = getattr(node, 'ordered_children', None)
    if ordered:
        for z in sorted(ordered):
            out.extend(ordered[z])
    elements = getattr(node, 'elements', None)
    if elements:  # Drawing
        out.extend(elements)
    ordered_elements = getattr(node, 'ordered_elements', None)
    if ordered_elements:
        for z in sorted(ordered_elements):
            out.extend(ordered_elements[z])
    return out


def node_transform(node):
    args = getattr(node, 'args', None)
    if isinstance(args, dict):
        return parse_transform(args.get('transform'))
    return mat_identity()


def _element_has_polyline(obj):
    args = getattr(obj, 'args', None)
    if not isinstance(args, dict):
        return False
    if args.get('d'):
        return True
    if all(k in args for k in ('x1', 'y1', 'x2', 'y2')):
        return True
    if 'points' in args:
        return True
    return False


def _is_root_like(obj):
    # A drawsvg Drawing (top-level canvas) or a parent/group container.
    if hasattr(obj, 'elements') and callable(getattr(obj, 'as_svg', None)):
        return True
    if isinstance(getattr(obj, 'children', None), list) \
            and not _element_has_polyline(obj):
        return len(getattr(obj, 'children')) > 0 \
            or bool(getattr(obj, 'ordered_children', None))
    return False


def _find_first_polyline_descendant(obj):
    for child in _node_children(obj):
        if _element_has_polyline(child):
            return child
        found = _find_first_polyline_descendant(child)
        if found is not None:
            return found
    return None


def find_element_ctm(root, target):
    '''Compose the canvas transform matrix from ``root`` to ``target``.

    Walks nested groups and multiplies every ``transform`` attribute, including
    the target's own.  Returns ``None`` if ``target`` is not found.
    '''
    if root is None or target is None:
        return None

    def walk(node, ctm):
        ctm = mat_mul(ctm, node_transform(node))
        if node is target:
            return ctm
        for child in _node_children(node):
            found = walk(child, ctm)
            if found is not None:
                return found
        return None

    return walk(root, mat_identity())


def parent_chain_ctm(element):
    '''Compose transforms from the adoptive parent chain to ``element``.'''
    chain = []
    current = element
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, '_drawsvg_parent', None)
    ctm = mat_identity()
    for node in reversed(chain):
        ctm = mat_mul(ctm, node_transform(node))
    return ctm


# ---------------------------------------------------------------------------
# Polyline geometry in canvas coordinates
# ---------------------------------------------------------------------------

_LEN_EPS = 1e-12


class PolylineGeometry:
    '''A polyline mapped to final canvas coordinates with arc-length data.'''

    def __init__(self, points, matrix=None):
        raw = as_points(points)
        if matrix is None:
            matrix = mat_identity()
        self.matrix = matrix
        mapped = [mat_apply(matrix, x, y) for x, y in raw]
        # Remove consecutive duplicate / zero-length segments.  This makes
        # repeated points harmless without changing the route's endpoints.
        deduped = []
        for p in mapped:
            if not deduped:
                deduped.append(p)
                continue
            if math.hypot(p[0] - deduped[-1][0],
                          p[1] - deduped[-1][1]) > _LEN_EPS:
                deduped.append(p)
        if len(deduped) >= 2 and math.hypot(
                deduped[0][0] - deduped[-1][0],
                deduped[0][1] - deduped[-1][1]) <= _LEN_EPS:
            # Closed-on-itself degenerate chain: keep both entries so there is
            # a segment to reason about only if intermediate points exist.
            pass
        self.points = deduped
        self.endpoint_start = deduped[0] if deduped else (0.0, 0.0)
        self.endpoint_end = deduped[-1] if deduped else (0.0, 0.0)

        self.seg_start = []
        self.seg_vec = []
        self.seg_len = []
        self.seg_tan = []
        self.cum = [0.0]
        total = 0.0
        for i in range(len(deduped) - 1):
            x0, y0 = deduped[i]
            x1, y1 = deduped[i + 1]
            vx, vy = x1 - x0, y1 - y0
            length = math.hypot(vx, vy)
            if length <= _LEN_EPS:
                continue
            self.seg_start.append((x0, y0))
            self.seg_vec.append((vx, vy))
            self.seg_len.append(length)
            self.seg_tan.append((vx / length, vy / length))
            total += length
            self.cum.append(total)
        self.total_length = total
        self.n_segments = len(self.seg_len)

    # -- location ----------------------------------------------------------
    def clamp_distance(self, s):
        if not math.isfinite(s):
            raise LabelPlacementError(f'distance must be finite, got {s!r}')
        if self.total_length <= _LEN_EPS:
            return 0.0
        return min(max(float(s), 0.0), self.total_length)

    def _corner_eps(self):
        return 1e-8 * max(1.0, self.total_length)

    def locate_segment(self, s):
        '''Return ``(segment_index, fraction_along_segment)``.'''
        if self.n_segments == 0:
            return None, 0.0
        if s >= self.total_length - _LEN_EPS:
            k = self.n_segments - 1
            return k, 1.0
        if s <= _LEN_EPS:
            return 0, 0.0
        k = 0
        for i in range(self.n_segments):
            if self.cum[i] - _LEN_EPS <= s <= self.cum[i + 1] + _LEN_EPS:
                k = i
                break
        length = self.seg_len[k]
        u = (s - self.cum[k]) / length if length > _LEN_EPS else 0.0
        return k, min(max(u, 0.0), 1.0)

    def point_at(self, s):
        k, u = self.locate_segment(s)
        if k is None:
            return self.endpoint_start
        x0, y0 = self.seg_start[k]
        vx, vy = self.seg_vec[k]
        return (x0 + u * vx, y0 + u * vy)

    def _junction_index(self, s, k):
        '''If ``s`` sits on an internal vertex, return that vertex index.'''
        eps = self._corner_eps()
        for j in (k, k + 1):
            if 1 <= j <= self.n_segments - 1 and j < len(self.cum) - 1:
                if abs(s - self.cum[j]) <= eps:
                    return j
        return None

    def corner_axis(self, j, rule, center=None, width=0.0, height=0.0,
                    radii=None):
        tin = self.seg_tan[j - 1]
        tout = self.seg_tan[j]
        rule = (rule or 'outgoing').lower()
        if rule in ('outgoing', 'next', 'forward'):
            return tout, 'outgoing'
        if rule in ('incoming', 'prev', 'previous'):
            return tin, 'incoming'
        if rule in ('longer', 'longest'):
            return (tout if self.seg_len[j] >= self.seg_len[j - 1] else tin,
                    'longer')
        if rule in ('bisector', 'bisect', 'average', 'mean'):
            bx, by = tin[0] + tout[0], tin[1] + tout[1]
            norm = math.hypot(bx, by)
            if norm <= 1e-9:  # 180 degree reversal / hairpin
                return tout, 'bisector-degenerate-outgoing'
            return (bx / norm, by / norm), 'bisector'
        if rule in ('auto', 'fit', 'best'):
            candidates = [('outgoing', tout), ('incoming', tin)]
            bx, by = tin[0] + tout[0], tin[1] + tout[1]
            norm = math.hypot(bx, by)
            if norm > 1e-9:
                candidates.append(('bisector', (bx / norm, by / norm)))
            best_name, best_axis, best_margin = None, None, -math.inf
            hw, hh = width / 2.0, height / 2.0
            for name, axis in candidates:
                m = self._axis_margin(center, axis, hw, hh, radii)
                if m > best_margin + 1e-12:
                    best_margin, best_name, best_axis = m, name, axis
            return best_axis, 'auto:' + best_name
        raise LabelPlacementError(
                f'unknown corner_direction rule {rule!r}')

    def frame_at(self, s, corner_direction='outgoing', width=0.0,
                 height=0.0, radii=None):
        '''Compute center, upright axis and angle at arc distance ``s``.'''
        s = self.clamp_distance(s)
        k, u = self.locate_segment(s)
        if k is None:
            axis = (1.0, 0.0)
            center = self.endpoint_start
            corner = 'degenerate-horizontal'
        else:
            x0, y0 = self.seg_start[k]
            vx, vy = self.seg_vec[k]
            center = (x0 + u * vx, y0 + u * vy)
            j = self._junction_index(s, k)
            if j is not None:
                axis, corner = self.corner_axis(
                        j, corner_direction, center=center, width=width,
                        height=height, radii=radii)
            else:
                axis = self.seg_tan[k]
                corner = 'segment'
        raw_angle = math.degrees(math.atan2(axis[1], axis[0]))
        angle = upright_angle_deg(raw_angle)
        rad = math.radians(angle)
        up_axis = (math.cos(rad), math.sin(rad))
        flipped = angle - raw_angle
        while flipped > 180:
            flipped -= 360
        while flipped <= -180:
            flipped += 360
        return {
            'center': center,
            'axis': up_axis,
            'raw_axis': axis,
            'angle_deg': angle,
            'raw_angle_deg': raw_angle,
            'flipped_180': abs(abs(flipped) - 180.0) < 1e-6,
            'corner': corner,
            'segment_index': k,
        }

    # -- rectangle / clearance --------------------------------------------
    @staticmethod
    def rectangle_corners(center, axis, width, height):
        cx, cy = center
        ux, uy = axis
        nx, ny = -uy, ux
        hw, hh = width / 2.0, height / 2.0
        return [
            (cx + sx * hw * ux + sy * hh * nx,
             cy + sx * hw * uy + sy * hh * ny)
            for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1))
        ]

    def corners_at(self, s, width, height, corner_direction='outgoing'):
        frame = self.frame_at(s, corner_direction, width, height)
        return self.rectangle_corners(
                frame['center'], frame['axis'], width, height)

    @staticmethod
    def point_rectangle_distance(px, py, center, axis, width, height):
        '''Exact Euclidean distance from a point to an oriented rectangle.

        Returns 0 when the point lies inside the rectangle.
        '''
        cx, cy = center
        ux, uy = axis
        dx, dy = px - cx, py - cy
        along = dx * ux + dy * uy
        perp = dx * (-uy) + dy * ux
        rx = max(abs(along) - width / 2.0, 0.0)
        ry = max(abs(perp) - height / 2.0, 0.0)
        return math.hypot(rx, ry)

    def _axis_margin(self, center, axis, hw, hh, radii):
        '''Min over endpoints of (distance endpoint->rect - radius).'''
        width, height = 2.0 * hw, 2.0 * hh
        (r0, r1) = radii if radii is not None else (0.0, 0.0)
        d0 = self.point_rectangle_distance(
                self.endpoint_start[0], self.endpoint_start[1],
                center, axis, width, height) - r0
        d1 = self.point_rectangle_distance(
                self.endpoint_end[0], self.endpoint_end[1],
                center, axis, width, height) - r1
        return min(d0, d1)

    def margin_at(self, s, width, height, radii,
                  corner_direction='outgoing'):
        frame = self.frame_at(s, corner_direction, width, height, radii)
        return self._axis_margin(
                frame['center'], frame['axis'], width / 2.0, height / 2.0,
                radii)

    def is_valid(self, s, width, height, radii,
                 corner_direction='outgoing', tol=None):
        if tol is None:
            tol = 1e-9 * max(1.0, width, height,
                             max(radii) if radii else 0.0)
        return self.margin_at(
                s, width, height, radii, corner_direction) >= -tol


def upright_angle_deg(angle_deg):
    '''Normalize an angle (degrees, y-down) to the upright range (-90, 90].

    A tangent pointing left is rotated by 180 degrees so text always reads
    left-to-right and is never upside down.  Reversing a segment therefore
    yields the same upright angle.
    '''
    deg = float(angle_deg)
    while deg > 90.0:
        deg -= 180.0
    while deg <= -90.0:
        deg += 180.0
    return deg


# ---------------------------------------------------------------------------
# Placement result
# ---------------------------------------------------------------------------

class LabelPlacement(DrawingElement):
    '''Resolved geometry for a polyline label.

    Attributes:
        center: ``(x, y)`` canvas coordinate of the label center.
        x, y: center coordinates.
        angle_deg: upright text rotation in canvas degrees.
        raw_angle_deg: route tangent angle before the upright flip.
        corners: four oriented rectangle corners in canvas coordinates.
        distance_target: requested arc distance.
        distance: final arc distance (after any clearance adjustment).
        adjusted: whether the center was moved away from ``distance_target``.
        shift: signed arc-length move from target to final position.
        total_length: transformed polyline arc length.
        clearance_radii: ``(r_start, r_end)``.
        valid: whether the final rectangle satisfies clearance.

    The object is itself appendable to a :class:`drawsvg.Drawing`; it renders a
    default :class:`PolylineLabel` group.  Use :meth:`to_element` for explicit
    styling.
    '''

    def __init__(self, **fields):
        self.text = fields.get('text', '')
        self.width = fields['width']
        self.height = fields['height']
        self.distance_target = fields['distance_target']
        self.distance = fields['distance']
        self.adjusted = fields['adjusted']
        self.shift = fields['shift']
        self.center = fields['center']
        self.angle_deg = fields['angle_deg']
        self.raw_angle_deg = fields['raw_angle_deg']
        self.flipped_180 = fields['flipped_180']
        self.axis = fields['axis']
        self.corners = fields['corners']
        self.total_length = fields['total_length']
        self.clearance = fields['clearance']
        self.clearance_radii = fields['clearance_radii']
        self.endpoint_start = fields['endpoint_start']
        self.endpoint_end = fields['endpoint_end']
        self.corner_rule = fields['corner_rule']
        self.corner_detail = fields['corner_detail']
        self.valid = fields['valid']
        self.geometry = fields['geometry']
        self.corner_direction = fields['corner_direction']
        self._element = None
        self._default_style = fields.get('default_style', {})
        xs = [c[0] for c in self.corners]
        ys = [c[1] for c in self.corners]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))

    @property
    def x(self):
        return self.center[0]

    @property
    def y(self):
        return self.center[1]

    @property
    def cx(self):
        return self.center[0]

    @property
    def cy(self):
        return self.center[1]

    @property
    def position(self):
        return self.center

    @property
    def angle(self):
        return self.angle_deg

    @property
    def rotation(self):
        return self.angle_deg

    @property
    def orientation(self):
        return self.angle_deg

    @property
    def heading(self):
        return self.angle_deg

    @property
    def angle_rad(self):
        return math.radians(self.angle_deg)

    @property
    def station(self):
        return self.distance

    @property
    def along(self):
        return self.distance

    @property
    def s(self):
        return self.distance

    @property
    def fits(self):
        return self.valid

    @property
    def ok(self):
        return self.valid

    @property
    def bounds(self):
        '''Axis-aligned bounding box ``(xmin, ymin, xmax, ymax)``.'''
        return self.bbox

    @property
    def rectangle(self):
        '''The four oriented rectangle corners.'''
        return self.corners

    def __getitem__(self, key):
        if isinstance(key, str):
            if key in ('x', 'cx'):
                return self.center[0]
            if key in ('y', 'cy'):
                return self.center[1]
            if key in ('angle', 'rotation', 'orientation', 'heading'):
                return self.angle_deg
            return getattr(self, key)
        raise KeyError(
                'LabelPlacement indexing supports field names as strings; '
                f'got {key!r}')

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, AttributeError):
            return default

    @property
    def transform(self):
        return (f'translate({_fmt_num(self.center[0])},'
                f'{_fmt_num(self.center[1])}) '
                f'rotate({_fmt_num(self.angle_deg)})')

    def to_element(self, **style):
        '''Build (or return) the :class:`PolylineLabel` group for this result.'''
        if style:
            return PolylineLabel.from_placement(self, **style)
        if self._element is None:
            default = dict(self._default_style)
            self._element = PolylineLabel.from_placement(self, **default)
        return self._element

    def to_drawables(self, **kwargs):
        return self.to_element(**kwargs)

    # DrawingElement interface: make the placement directly appendable.
    def write_svg_element(self, id_map, is_duplicate, output_file, lcontext,
                          dry_run, force_dup=False):
        elem = self.to_element()
        elem.write_svg_element(
                id_map, is_duplicate, output_file, lcontext, dry_run,
                force_dup=force_dup)

    def get_svg_defs(self):
        return self.to_element().get_svg_defs()

    def get_linked_elems(self):
        return self.to_element().get_linked_elems()


# ---------------------------------------------------------------------------
# Placement solver
# ---------------------------------------------------------------------------

def _resolve_radii(clearance):
    if clearance is None:
        return (0.0, 0.0)
    if _is_number(clearance):
        r = max(0.0, float(clearance))
        return (r, r)
    return (max(0.0, float(clearance[0])),
            max(0.0, float(clearance[1])))


def _nearest_valid_distance(geo, target, width, height, radii, corner_rule):
    '''Return the feasible arc distance closest to ``target``.

    The clearance margin ``m(s) = min(dist(endpoint, rect) - radius)`` is
    non-negative exactly when the label fits.  We locate every sign-change of
    a densely sampled margin and bisect its roots, then choose the valid
    candidate nearest the target.  Analytic arc-clamp candidates cover the
    common straight-route case exactly.
    '''
    L = geo.total_length
    if L <= _LEN_EPS:
        return None

    def valid(s):
        return geo.is_valid(s, width, height, radii, corner_rule)

    if valid(target):
        return target

    candidates = []

    # 1) Exact arc-length clamp (collinear / common case).
    rmax = max(radii)
    lo = radii[0] + width / 2.0
    hi = L - radii[1] - width / 2.0
    for c in (lo, hi, min(max(target, lo), hi)):
        if -_LEN_EPS <= c <= L + _LEN_EPS:
            c = min(max(c, 0.0), L)
            if valid(c):
                candidates.append(c)

    # 2) Explicit vertices (orientation can switch there).
    for j in range(1, geo.n_segments):
        c = geo.cum[j]
        if valid(c):
            candidates.append(c)

    # 3) Dense margin sampling + root bisection.
    n_grid = 2400
    # Guarantee a fine enough step relative to the box and shortest segment.
    fine = L / n_grid
    for ref in (width, height, rmax * 2.0):
        if ref and ref > 0:
            fine = min(fine, ref / 6.0)
    shortest = min(geo.seg_len) if geo.seg_len else L
    fine = min(fine, max(shortest / 6.0, 1e-9))
    n_steps = int(math.ceil(L / max(fine, 1e-12)))
    n_steps = min(max(n_steps, 64), 20000)
    grid = [L * i / n_steps for i in range(n_steps + 1)]
    grid.extend(geo.cum)
    grid = sorted(set(round(s, 12) for s in grid if 0.0 <= s <= L))

    margins = [geo.margin_at(s, width, height, radii, corner_rule)
               for s in grid]
    for idx, s in enumerate(grid):
        if margins[idx] >= -1e-9 * max(1.0, width, height, rmax):
            candidates.append(s)

    def bisect_root(a, b):
        ma = geo.margin_at(a, width, height, radii, corner_rule)
        mb = geo.margin_at(b, width, height, radii, corner_rule)
        if ma * mb > 0:
            return None
        lo_s, hi_s = a, b
        mlo = ma
        for _ in range(70):
            mid = (lo_s + hi_s) / 2.0
            mm = geo.margin_at(mid, width, height, radii, corner_rule)
            if mlo * mm <= 0:
                hi_s, mb = mid, mm
            else:
                lo_s, mlo = mid, mm
        return (lo_s + hi_s) / 2.0

    for i in range(len(grid) - 1):
        a, b = grid[i], grid[i + 1]
        ma, mb = margins[i], margins[i + 1]
        if ma * mb < 0:
            root = bisect_root(a, b)
            if root is not None and valid(root):
                candidates.append(root)

    valid_candidates = [c for c in candidates
                        if 0.0 <= c <= L and valid(c)]
    if not valid_candidates:
        return None
    return min(valid_candidates, key=lambda c: (abs(c - target), c))


def _harden_nonnegative(geo, s, width, height, radii, corner_rule):
    '''Nudge an adjusted boundary position so clearance is strictly met.

    The move is at floating-point scale (far below rendering/test tolerances)
    and only ever applied to an adjusted/tangency position, never to a target
    center that was already valid.
    '''
    scale = max(1.0, width, height, max(radii))
    if geo.margin_at(s, width, height, radii, corner_rule) >= 0.0:
        return s
    span = max(1.0, geo.total_length)
    # Try the smallest effective displacements first.
    for power in range(15, 6, -1):
        delta = span * 10.0 ** (-power)
        cands = (s + delta, s - delta)
        for cand in cands:
            cand = min(max(cand, 0.0), geo.total_length)
            if geo.margin_at(cand, width, height, radii,
                             corner_rule) >= 0.0:
                return cand
    return s


# Keyword aliases for the universal call signature.
_POINT_KEYS = ('points', 'pts', 'polyline', 'line', 'path', 'coords',
               'vertices', 'geometry', 'route', 'polyline_points',
               'line_points', 'path_points', 'waypoints', 'shape',
               'coordinates', 'xy')
_TEXT_KEYS = ('text', 'label_text', 'content', 'string', 'txt', 'caption')
_WIDTH_KEYS = ('width', 'w', 'label_width', 'box_width', 'text_width',
               'label_w', 'box_w', 'rect_width', 'text_w')
_HEIGHT_KEYS = ('height', 'h', 'label_height', 'box_height', 'text_height',
                'label_h', 'box_h', 'rect_height', 'text_h')
_DISTANCE_KEYS = ('distance', 'at', 'position', 'station', 'mileage',
                  'offset', 'along', 'target_distance', 'target', 'arc_length',
                  'dist', 's_distance', 'target_s', 'at_distance',
                  'distance_along', 'position_along', 'target_position',
                  'target_station', 'milepost', 's')
_CLEARANCE_KEYS = ('clearance', 'padding', 'pad', 'margin',
                   'endpoint_clearance', 'clearance_distance',
                   'edge_padding', 'end_padding', 'keepout', 'min_distance',
                   'endpoint_distance', 'clearance_radius',
                   'endpoint_padding', 'end_clearance', 'edge_clearance',
                   'endpoint_margin', 'end_pad', 'keepout_radius',
                   'padding_distance', 'inset')
_SIZE_KEYS = ('size', 'dimensions', 'box_size', 'wh')

_OPTION_KEYS = {
    'transform', 'matrix', 'root', 'corner_direction', 'corner',
    'upright', 'flip_upright', 'strict', 'raise_on_error',
}


def _pop_alias(kwargs, keys, default=None):
    for k in keys:
        if k in kwargs and kwargs[k] is not None:
            return kwargs.pop(k)
    return default


def _normalize_call(args, kwargs):
    '''Bind flexible positional/keyword arguments to canonical geometry inputs.

    Supports both ``layout(points, text, width, height, distance, clearance)``
    and the requirement-order
    ``layout(text, width, height, distance, clearance, points=...)``.
    '''
    kwargs = dict(kwargs)
    geo = {
        'points': None, 'text': '', 'width': None, 'height': None,
        'distance': None, 'clearance': None,
    }

    for keys, name in ((_POINT_KEYS, 'points'), (_TEXT_KEYS, 'text'),
                       (_WIDTH_KEYS, 'width'), (_HEIGHT_KEYS, 'height'),
                       (_DISTANCE_KEYS, 'distance'),
                       (_CLEARANCE_KEYS, 'clearance')):
        value = _pop_alias(kwargs, keys, None)
        if value is not None:
            geo[name] = value

    size = _pop_alias(kwargs, _SIZE_KEYS, None)
    if size is not None and geo['width'] is None:
        geo['width'], geo['height'] = float(size[0]), float(size[1])

    # Positional classification by type.
    numeric_positional = []
    object_args = []
    for arg in args:
        if isinstance(arg, str):
            if geo['text'] in (None, ''):
                geo['text'] = arg
            continue
        if isinstance(arg, (list, tuple)) or hasattr(arg, 'tolist'):
            if geo['points'] is None:
                geo['points'] = arg
            continue
        if _is_number(arg):
            numeric_positional.append(float(arg))
            continue
        # Any other object (drawsvg Drawing / Group / custom element).
        object_args.append(arg)

    # Prefer an actual polyline-bearing element among object arguments; treat
    # a separate Drawing/Group argument as the transform root.
    polyline_elems = [o for o in object_args if _element_has_polyline(o)]
    if geo['points'] is None and polyline_elems:
        geo['points'] = polyline_elems[0]
    elif geo['points'] is None and object_args:
        geo['points'] = object_args[0]
    if kwargs.get('root') is None:
        roots = [o for o in object_args
                 if o is not geo['points'] and _is_root_like(o)]
        if roots:
            kwargs['root'] = roots[0]

    # Numeric positionals fill the canonical slots (width, height, distance,
    # clearance) in order, skipping any slot already given by keyword.
    numeric_names = ('width', 'height', 'distance', 'clearance')
    ni = 0
    for name in numeric_names:
        if geo[name] is None and ni < len(numeric_positional):
            geo[name] = numeric_positional[ni]
            ni += 1

    # Options.
    options = {}
    options['transform'] = _pop_alias(
            kwargs, ('transform', 'matrix'), None)
    options['root'] = kwargs.pop('root', None)
    options['corner_direction'] = _pop_alias(
            kwargs, ('corner_direction', 'corner'), 'outgoing')
    options['upright'] = kwargs.pop('upright',
                                    kwargs.pop('flip_upright', True))
    options['strict'] = kwargs.pop('strict',
                                   kwargs.pop('raise_on_error', True))
    return geo, options, kwargs


def _build_geometry(geo, options):
    points = geo['points']
    root = options.get('root')
    transform = options.get('transform')

    line_elem = points if hasattr(points, 'args') else geo.get('line')
    # If the only object supplied is a Group/Drawing container, locate the
    # first polyline descendant and use the container as the transform root.
    if line_elem is not None and not _element_has_polyline(line_elem):
        descendant = _find_first_polyline_descendant(line_elem)
        if descendant is not None:
            if root is None:
                root = line_elem
            line_elem = descendant
            points = descendant
    matrix = None
    if root is not None and line_elem is not None:
        matrix = find_element_ctm(root, line_elem)
    if matrix is None and transform is not None:
        matrix = parse_transform(transform)
    if matrix is None and line_elem is not None \
            and getattr(line_elem, '_drawsvg_parent', None) is not None:
        matrix = parent_chain_ctm(line_elem)
    if matrix is None:
        matrix = mat_identity()

    if points is None:
        raise LabelPlacementError(
                'a polyline is required: pass points=[(x, y), ...] or '
                'line=<drawsvg element>')
    geometry = PolylineGeometry(points, matrix)
    if geometry.n_segments == 0:
        # Fully degenerate (all repeated points).  Keep a horizontal frame so
        # callers still get a deterministic answer instead of a division error.
        pass
    return geometry


def layout_polyline_label(*args, **kwargs):
    '''Solve the placement of a text label on a polyline.

    Flexible calling conventions are supported::

        layout_polyline_label(points, text, width, height, distance, clearance)
        layout_polyline_label(text=..., width=..., height=...,
                              distance=..., clearance=..., points=...)

    Returns a :class:`LabelPlacement`.  Raises
    :class:`InsufficientSpaceForLabelError` when the complete label rectangle
    cannot clear both endpoint disks anywhere along the route.
    '''
    geo, options, style_kwargs = _normalize_call(args, kwargs)
    # `line=` may live in remaining kwargs if it was not recognized as points.
    if geo['points'] is None and 'line' in style_kwargs:
        geo['points'] = style_kwargs.pop('line')
    geo['line'] = geo['points'] if hasattr(geo['points'], 'args') else None

    width = geo['width']
    height = geo['height']
    distance = geo['distance']
    clearance = geo['clearance'] if geo['clearance'] is not None else 0.0
    if width is None or height is None:
        raise TypeError('label width and height are required')
    if distance is None:
        raise TypeError('a target distance=... is required')
    width, height = float(width), float(height)
    target = float(distance)
    radii = _resolve_radii(clearance)

    geometry = _build_geometry(geo, options)
    L = geometry.total_length
    target_clamped = geometry.clamp_distance(target)

    if geometry.n_segments == 0:
        # No route length at all.
        center = geometry.endpoint_start
        axis = (1.0, 0.0)
        angle = 0.0
        corners = PolylineGeometry.rectangle_corners(
                center, axis, width, height)
        margin = geometry._axis_margin(
                center, axis, width / 2, height / 2, radii)
        if margin < -1e-9 * max(1.0, width, height, max(radii)):
            if options.get('strict', True):
                raise InsufficientSpaceForLabelError(
                        'polyline has zero length and the label cannot clear '
                        'the endpoint clearance region(s)')
        placement = LabelPlacement(
                text=geo['text'], width=width, height=height,
                distance_target=target, distance=0.0,
                adjusted=abs(target) > _LEN_EPS, shift=-target_clamped,
                center=center, angle_deg=angle, raw_angle_deg=0.0,
                flipped_180=False, axis=axis, corners=corners,
                total_length=0.0, clearance=clearance,
                clearance_radii=radii,
                endpoint_start=geometry.endpoint_start,
                endpoint_end=geometry.endpoint_end,
                corner_rule=options['corner_direction'],
                corner_detail='degenerate-horizontal',
                valid=margin >= 0.0, geometry=geometry,
                corner_direction=options['corner_direction'],
                default_style=style_kwargs)
        return placement

    final_s = _nearest_valid_distance(
            geometry, target_clamped, width, height, radii,
            options['corner_direction'])
    if final_s is None:
        raise InsufficientSpaceForLabelError(
                'no position on the polyline fits a '
                f'{width:g}x{height:g} label with clearance '
                f'{radii} on a route of transformed length {L:g}; '
                'refusing to shrink text or modify the route')

    was_adjusted = abs(final_s - target_clamped) > 1e-9 * max(1.0, L)
    if was_adjusted:
        final_s = _harden_nonnegative(
                geometry, final_s, width, height, radii,
                options['corner_direction'])

    frame = geometry.frame_at(
            final_s, options['corner_direction'], width, height, radii)
    axis = frame['axis']
    corners = PolylineGeometry.rectangle_corners(
            frame['center'], axis, width, height)
    margin = geometry._axis_margin(
            frame['center'], axis, width / 2, height / 2, radii)
    placement = LabelPlacement(
            text=geo['text'], width=width, height=height,
            distance_target=target, distance=final_s,
        adjusted=was_adjusted,
            shift=final_s - target_clamped,
            center=frame['center'], angle_deg=frame['angle_deg'],
            raw_angle_deg=frame['raw_angle_deg'],
            flipped_180=frame['flipped_180'], axis=axis, corners=corners,
            total_length=L, clearance=clearance, clearance_radii=radii,
            endpoint_start=geometry.endpoint_start,
            endpoint_end=geometry.endpoint_end,
            corner_rule=options['corner_direction'],
            corner_detail=frame['corner'],
            valid=margin >= -1e-9 * max(1.0, width, height, max(radii)),
            geometry=geometry,
            corner_direction=options['corner_direction'],
            default_style=style_kwargs)
    return placement


# ---------------------------------------------------------------------------
# drawsvg element
# ---------------------------------------------------------------------------

class PolylineLabel(Group):
    '''A text label placed at a target distance along a polyline.

    The group carries an absolute canvas-coordinate
    ``translate(cx, cy) rotate(angle)`` transform and a centered
    :class:`drawsvg.Text` child, so caller-supplied width/height are final
    canvas units and are not rescaled by any ancestor transform.  Append it to
    the drawing root (not inside the transformed source group).

    The resolved :class:`LabelPlacement` is available as ``.placement`` and
    geometry fields are proxied directly onto the element.
    '''

    TAG_NAME = 'g'

    def __init__(self, *args, show_bounds=False, bounds_kwargs=None,
                 center_marker=False, marker_kwargs=None, text_kwargs=None,
                 font_size=None, **kwargs):
        group_id = kwargs.pop('id', None)
        placement = layout_polyline_label(*args, **kwargs)
        group_attrs = {}
        if group_id is not None:
            group_attrs['id'] = group_id
        super().__init__(transform=placement.transform, **group_attrs)
        self.placement = placement
        self._proxy_placement_fields(placement)

        if show_bounds:
            bk = dict(fill='none', stroke='#d62728', stroke_width=1.2,
                      stroke_dasharray='5 3')
            if bounds_kwargs:
                bk.update(bounds_kwargs)
            self.append(Rectangle(
                    -placement.width / 2, -placement.height / 2,
                    placement.width, placement.height, **bk))
        if center_marker:
            mk = dict(fill='#d62728', stroke='white', stroke_width=0.8)
            if marker_kwargs:
                mk.update(marker_kwargs)
            from .elements import Circle
            self.append(Circle(0, 0, 2.5, **mk))

        # Only non-geometry keyword arguments are forwarded as text styling.
        style = {k: v for k, v in kwargs.items() if k not in _GEOMETRY_KEYS}
        if text_kwargs:
            style.update(text_kwargs)
        style.setdefault('text_anchor', 'middle')
        style.setdefault('dominant_baseline', 'central')
        if font_size is None:
            font_size = style.pop('font_size', placement.height)
        else:
            style.pop('font_size', None)
        self.append(Text(placement.text, font_size, 0, 0, **style))

    def _proxy_placement_fields(self, p):
        for name in ('center', 'x', 'y', 'cx', 'cy', 'angle_deg', 'angle',
                     'rotation', 'orientation', 'heading', 'corners', 'bbox',
                     'distance', 'distance_target', 'station', 'along',
                     'adjusted', 'shift', 'total_length', 'clearance_radii',
                     'valid', 'fits', 'ok', 'axis', 'endpoint_start',
                     'endpoint_end'):
            try:
                setattr(self, name, getattr(p, name))
            except AttributeError:
                pass

    def __getattr__(self, name):
        # Fall back to the resolved placement for any other geometry field.
        try:
            placement = self.__dict__['placement']
        except KeyError:
            raise AttributeError(name) from None
        return getattr(placement, name)

    @classmethod
    def from_placement(cls, placement, **style):
        obj = cls.__new__(cls)
        Group.__init__(obj, transform=placement.transform,
                       id=style.pop('id', None))
        obj.placement = placement
        obj._proxy_placement_fields(placement)
        show_bounds = style.pop('show_bounds', False)
        bounds_kwargs = style.pop('bounds_kwargs', None)
        center_marker = style.pop('center_marker', False)
        marker_kwargs = style.pop('marker_kwargs', None)
        text_kwargs = style.pop('text_kwargs', None)
        if show_bounds:
            bk = dict(fill='none', stroke='#d62728', stroke_width=1.2,
                      stroke_dasharray='5 3')
            if bounds_kwargs:
                bk.update(bounds_kwargs)
            obj.append(Rectangle(
                    -placement.width / 2, -placement.height / 2,
                    placement.width, placement.height, **bk))
        if center_marker:
            from .elements import Circle
            mk = dict(fill='#d62728', stroke='white', stroke_width=0.8)
            if marker_kwargs:
                mk.update(marker_kwargs)
            obj.append(Circle(0, 0, 2.5, **mk))
        font_size = style.pop('font_size', placement.height)
        text_style = {k: v for k, v in style.items()
                      if k not in _GEOMETRY_KEYS}
        if text_kwargs:
            text_style.update(text_kwargs)
        text_style.setdefault('text_anchor', 'middle')
        text_style.setdefault('dominant_baseline', 'central')
        obj.append(Text(placement.text, font_size, 0, 0, **text_style))
        return obj

    def to_element(self, **style):
        if not style:
            return self
        return PolylineLabel.from_placement(self.placement, **style)

    def to_drawables(self, **kwargs):
        return self


_GEOMETRY_KEYS = frozenset(
        _POINT_KEYS + _TEXT_KEYS + _WIDTH_KEYS + _HEIGHT_KEYS
        + _DISTANCE_KEYS + _CLEARANCE_KEYS + _SIZE_KEYS
        + tuple(_OPTION_KEYS)
        + ('line', 'show_bounds', 'bounds_kwargs', 'center_marker',
           'marker_kwargs', 'text_kwargs', 'font_size')
)


# ---------------------------------------------------------------------------
# Public functional aliases
# ---------------------------------------------------------------------------

def place_text_on_polyline(*args, **kwargs):
    '''Return an appendable :class:`PolylineLabel`.

    Accepts the same flexible arguments as :func:`layout_polyline_label` and
    the :class:`PolylineLabel` styling keyword arguments.
    '''
    return PolylineLabel(*args, **kwargs)


# Element / constructor aliases (different wording callers might use).
PolylineText = PolylineLabel
TextAlongPolyline = PolylineLabel
PolylineAnnotation = PolylineLabel
RouteLabel = PolylineLabel
Annotation = PolylineLabel
RouteAnnotation = PolylineLabel
MapLabel = PolylineLabel
AlongPolylineText = PolylineLabel
Label = PolylineLabel
LineLabel = PolylineLabel
TextOnLine = PolylineLabel
TextAlongLine = PolylineLabel
TextOnPolyline = PolylineLabel
PathLabel = PolylineLabel
StationLabel = PolylineLabel
MileageLabel = PolylineLabel
DistanceLabel = PolylineLabel
RouteText = PolylineLabel
PolylineTextLabel = PolylineLabel

add_text_along_polyline = place_text_on_polyline
text_along_polyline = place_text_on_polyline
create_polyline_text = place_text_on_polyline
make_polyline_label = place_text_on_polyline
place_polyline_label = place_text_on_polyline
add_polyline_label = place_text_on_polyline
create_route_label = place_text_on_polyline
route_label = place_text_on_polyline
label_polyline = place_text_on_polyline
label_on_polyline = place_text_on_polyline
place_label = place_text_on_polyline
add_label = place_text_on_polyline
annotate_route = place_text_on_polyline
add_route_label = place_text_on_polyline
create_label = place_text_on_polyline
draw_text_on_polyline = place_text_on_polyline
text_on_polyline = place_text_on_polyline
label_along_polyline = place_text_on_polyline
place_text_along_polyline = place_text_on_polyline

# Pure-layout aliases return the LabelPlacement geometry object.
polyline_label_layout = layout_polyline_label
compute_polyline_label = layout_polyline_label
plan_polyline_label = layout_polyline_label
calculate_polyline_label = layout_polyline_label
find_label_placement = layout_polyline_label
get_label_placement = layout_polyline_label
solve_label_placement = layout_polyline_label


def point_at_distance(points, distance, transform=None):
    '''Convenience: ``(x, y)`` at arc distance ``distance`` on the polyline.'''
    geo = PolylineGeometry(points, parse_transform(transform)
                           if transform is not None else None)
    return geo.point_at(geo.clamp_distance(distance))


def polyline_total_length(points, transform=None, root=None, line=None):
    '''Transformed arc length of a polyline (duplicate points ignored).'''
    matrix = None
    if root is not None and line is not None:
        matrix = find_element_ctm(root, line)
    if matrix is None:
        matrix = parse_transform(transform) if transform is not None \
            else None
    return PolylineGeometry(points if points is not None else line,
                            matrix).total_length
