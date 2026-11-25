'''Tests for automatic viewBox fitting / geometry bounds.

Run with pytest from the repository root.
'''

import math
import warnings

import pytest

import drawsvg as draw
from drawsvg.bounds import (
    BoundingBox, ViewBox, EmptyDrawingError, UnsupportedElementError,
    geometry_bounds, path_bounds,
)


def approx_tuple(values, abs_tol=1e-6):
    return pytest.approx(tuple(values), abs=abs_tol)


# ---------------------------------------------------------------------------
# Basic primitives
# ---------------------------------------------------------------------------

def test_rectangle_bounds_and_padding():
    d = draw.Drawing(100, 100)
    d.append(draw.Rectangle(10, 20, 30, 40))
    box = d.get_bounding_box()
    assert (box.xmin, box.ymin, box.xmax, box.ymax) == (10, 20, 40, 60)
    vb = d.fit_view_box(padding=5)
    assert tuple(vb) == approx_tuple((5, 15, 40, 50))
    assert tuple(d.view_box) == approx_tuple((5, 15, 40, 50))
    assert 'viewBox="5 15 40 50"' in d.as_svg()


def test_circle_negative_coordinates():
    d = draw.Drawing(10, 10)
    d.append(draw.Circle(-20, -30, 5))
    vb = d.fit_view_box()
    assert tuple(vb) == approx_tuple((-25, -35, 10, 10))


def test_ellipse_bounds():
    elem = draw.Ellipse(0, 0, 40, 20)
    box = elem.get_bounds()
    assert (box.xmin, box.ymin, box.xmax, box.ymax) == approx_tuple(
            (-40, -20, 40, 20))


def test_line_elements():
    d = draw.Drawing(10, 10)
    d.append(draw.Line(-5, -7, 11, 13))
    vb = d.fit_view_box()
    assert tuple(vb) == approx_tuple((-5, -7, 16, 20))

    d2 = draw.Drawing(10, 10)
    d2.append(draw.AnimatableLine(1, 2, 8, 9))
    vb2 = d2.fit_view_box()
    assert tuple(vb2) == approx_tuple((1, 2, 7, 7))


def test_lines_polyline_and_close():
    d = draw.Drawing(10, 10)
    d.append(draw.Lines(0, 0, 10, 0, 5, 8, close=True))
    vb = d.fit_view_box()
    assert tuple(vb) == approx_tuple((0, 0, 10, 8))


# ---------------------------------------------------------------------------
# Curves: bulges between endpoints must be included
# ---------------------------------------------------------------------------

def test_quadratic_bulge():
    # Endpoints sit on y=0 but the curve reaches y=50.
    p = draw.Path()
    p.M(0, 0)
    p.Q(50, 100, 100, 0)
    box = path_bounds(p)
    assert (box.xmin, box.xmax) == approx_tuple((0, 100))
    assert box.ymin == pytest.approx(0, abs=1e-9)
    assert box.ymax == pytest.approx(50, abs=1e-6)


def test_cubic_bulge():
    # Symmetric hump: control points at y=100, curve top at y=75.
    p = draw.Path()
    p.M(0, 0)
    p.C(0, 100, 100, 100, 100, 0)
    box = path_bounds(p)
    assert tuple(box) == approx_tuple((0, 0, 100, 75))
    # The control points themselves (y=100) must not be used as the bound.
    assert box.ymax < 100


def test_cubic_with_overshoot_below_endpoints():
    p = draw.Path('M0,0 C100,200 200,-100 300,0')
    box = path_bounds(p)
    assert box.ymin < -20       # bulges below the endpoint line
    assert box.ymax > 70        # and above it
    assert box.xmin == 0 and box.xmax == 300


def test_smooth_curves_s_and_t():
    p = draw.Path()
    p.M(0, 0)
    p.C(20, 80, 40, 80, 50, 0)
    p.S(80, -60, 100, 0)
    box = path_bounds(p)
    assert box.xmin == pytest.approx(0)
    assert box.xmax == pytest.approx(100)
    assert box.ymax > 30
    assert box.ymin < -10


def test_relative_commands():
    p = draw.Path()
    p.M(0, 0)
    p.l(10, 10)
    p.q(5, 20, 10, 0)
    box = path_bounds(p)
    # l draws (0,0)->(10,10); relative q control (15,30), end (20,10);
    # the quadratic bulges to y=20.  The line start keeps min at (0,0).
    assert tuple(box) == approx_tuple((0, 0, 20, 20))
    assert box.xmax == pytest.approx(20, abs=1e-6)
    assert box.ymin == pytest.approx(0, abs=1e-6)
    assert box.ymax == pytest.approx(20, abs=1e-6)


def test_horizontal_vertical_commands():
    p = draw.Path('M5,5 H50 V60 h-20 v-10 Z')
    box = path_bounds(p)
    assert tuple(box) == approx_tuple((5, 5, 50, 60))


def test_closed_subpath():
    p = draw.Path()
    p.M(10, 10)
    p.L(90, 10)
    p.L(50, 80)
    p.Z()
    box = path_bounds(p)
    assert tuple(box) == approx_tuple((10, 10, 90, 80))


def test_elliptical_arc_full_circle():
    p = draw.Path()
    p.M(0, 0)
    p.A(50, 50, 0, 1, 0, 100, 0)
    p.A(50, 50, 0, 1, 0, 0, 0)
    box = path_bounds(p)
    assert tuple(box) == approx_tuple((0, -50, 100, 50), abs_tol=1e-5)


def test_elliptical_arc_half():
    p = draw.Path('M-50,0 A50,50 0 0 1 50,0')
    box = path_bounds(p)
    assert box.xmin == pytest.approx(-50, abs=1e-5)
    assert box.xmax == pytest.approx(50, abs=1e-5)
    assert box.ymin == pytest.approx(-50, abs=1e-5)
    assert box.ymax == pytest.approx(0, abs=1e-5)


def test_rotated_elliptical_arc():
    p = draw.Path()
    p.M(0, 0)
    p.A(50, 20, 30, 1, 1, 80, 60)
    box = path_bounds(p)
    # Must extend beyond both endpoints in at least one axis.
    assert box.width > 80 or box.height > 60


# ---------------------------------------------------------------------------
# Transforms and nested groups
# ---------------------------------------------------------------------------

def test_rotation_of_rectangle():
    d = draw.Drawing(100, 100)
    d.append(draw.Rectangle(-10, -10, 20, 20, transform='rotate(45)'))
    vb = d.fit_view_box()
    r = 10 * math.sqrt(2)
    assert tuple(vb) == approx_tuple((-r, -r, 2 * r, 2 * r), abs_tol=1e-6)


def test_reflection_is_not_clipped():
    p = draw.Path('M0,0 Q50,100 100,0', transform='scale(1,-1)')
    box = p.get_bounds()
    assert tuple(box) == approx_tuple((0, -50, 100, 0))


def test_nested_group_transforms_exact():
    # Curve hump box (0,0,100,75); rotate(90) maps it to (-75,0,0,100);
    # outer translate(20,30) -> (-55,30,20,130); padding 10 -> (-65,20,95,120).
    curve = draw.Path('M0,0 C0,100 100,100 100,0')
    inner = draw.Group(transform='rotate(90)')
    inner.append(curve)
    outer = draw.Group(transform='translate(20,30)')
    outer.append(inner)
    d = draw.Drawing(300, 300)
    d.append(outer)
    vb = d.fit_view_box(padding=10)
    assert tuple(vb) == approx_tuple((-65, 20, 95, 120))


def test_deeply_nested_affine_matrix():
    curve = draw.Path('M0,0 L10,0 L10,10 Z')
    g1 = draw.Group(transform='translate(5,5)')
    g2 = draw.Group(transform='scale(2)')
    g3 = draw.Group(transform='matrix(1,0,0,1,3,4)')
    g1.append(g2)
    g2.append(g3)
    g3.append(curve)
    d = draw.Drawing(50, 50)
    d.append(g1)
    vb = d.fit_view_box()
    # Root matrix: T(5,5) * S(2) * T(3,4), so p -> 2*(p+(3,4))+(5,5)
    # = 2p + (11,13). Vertices map to (11,13), (31,13), (31,33);
    # viewBox tuple is (xmin, ymin, width, height) -> (11,13,20,20).
    assert tuple(vb) == approx_tuple((11, 13, 20, 20))
    assert (vb.xmax, vb.ymax) == approx_tuple((31, 33))


def test_rotated_circle_keeps_radius_bounds():
    d = draw.Drawing(10, 10)
    g = draw.Group(transform='rotate(37) scale(2,1)')
    g.append(draw.Circle(0, 0, 10))
    d.append(g)
    vb = d.fit_view_box()
    angle = math.radians(37)
    half_x = math.hypot(20 * math.cos(angle), 10 * math.sin(angle))
    half_y = math.hypot(20 * math.sin(angle), 10 * math.cos(angle))
    assert tuple(vb) == pytest.approx(
            (-half_x, -half_y, 2 * half_x, 2 * half_y), abs=1e-6)


# ---------------------------------------------------------------------------
# Padding
# ---------------------------------------------------------------------------

def test_equal_padding_all_sides():
    d = draw.Drawing(10, 10)
    d.append(draw.Rectangle(0, 0, 100, 50))
    for kwargs in ({'padding': 10}, {'pad': 10}, {'margin': 10}):
        vb = d.fit_view_box(**kwargs)
        assert tuple(vb) == approx_tuple((-10, -10, 120, 70))


# ---------------------------------------------------------------------------
# Empty / unsupported handling
# ---------------------------------------------------------------------------

def test_empty_drawing_raises_clear_error():
    d = draw.Drawing(100, 100)
    with pytest.raises(ValueError):
        d.fit_view_box()
    with pytest.raises(EmptyDrawingError):
        draw.fit_view_box(d)


def test_unsupported_text_raises_by_default():
    d = draw.Drawing(100, 100)
    d.append(draw.Circle(0, 0, 5))
    d.append(draw.Text('hello', 10, x=10, y=10))
    with pytest.raises((ValueError, NotImplementedError)):
        d.fit_view_box()
    with pytest.raises(UnsupportedElementError):
        d.fit_view_box()


@pytest.mark.parametrize('element', [
    draw.Image(0, 0, 5, 5, data=b'fake'),
    draw.Use('#ref', 0, 0),
    draw.Raw('<custom/>'),
])
def test_unsupported_visible_elements(element):
    d = draw.Drawing(20, 20)
    d.append(element)
    with pytest.raises(UnsupportedElementError):
        d.fit_view_box()


def test_unsupported_warn_policy():
    d = draw.Drawing(20, 20)
    d.append(draw.Circle(0, 0, 5))
    d.append(draw.Text('hi', 4, x=2, y=2))
    with pytest.warns(UserWarning):
        vb = d.fit_view_box(on_unsupported='warn')
    assert tuple(vb) == approx_tuple((-5, -5, 10, 10))


def test_unsupported_ignore_policy():
    d = draw.Drawing(20, 20)
    d.append(draw.Circle(0, 0, 5))
    d.append(draw.Text('hi', 4, x=2, y=2))
    vb = d.fit_view_box(on_unsupported='ignore')
    assert tuple(vb) == approx_tuple((-5, -5, 10, 10))


def test_titles_and_animations_are_not_unsupported():
    r = draw.Rectangle(0, 0, 10, 10)
    r.append_title('tooltip')
    r.append_anim(draw.Animate('x', '1s', from_or_values=0, to=5))
    d = draw.Drawing(20, 20)
    d.append(r)
    vb = d.fit_view_box()
    assert tuple(vb) == approx_tuple((0, 0, 10, 10))


# ---------------------------------------------------------------------------
# Non-mutation / compatibility
# ---------------------------------------------------------------------------

def test_original_geometry_not_modified():
    p = draw.Path(stroke='black', stroke_width=2)
    p.M(1, 2)
    p.C(3, 4, 5, 6, 7, 8)
    p.A(10, 10, 0, 1, 0, 9, 9)
    d = draw.Drawing(50, 50)
    d.append(p)
    d.append(draw.Rectangle(0, 0, 5, 5))
    d_before = p.args['d']
    args_before = dict(p.args)
    d.fit_view_box(padding=4)
    assert p.args['d'] == d_before
    assert p.args == args_before


def test_manual_view_box_still_works():
    d = draw.Drawing(200, 100, origin='center')
    assert tuple(d.view_box) == (-100, -50, 200, 100)
    d.view_box = (1, 2, 3, 4)
    assert 'viewBox="1 2 3 4"' in d.as_svg()
    d.set_view_box(10, 20, 30, 40)
    assert tuple(d.view_box) == (10, 20, 30, 40)
    d.set_view_box((7, 8, 9, 10))
    assert tuple(d.view_box) == (7, 8, 9, 10)


def test_constructor_auto_fit_option():
    d = draw.Drawing(100, 100, fit_view_box=True, padding=4)
    d.append(draw.Circle(50, 50, 10))
    assert 'viewBox="36 36 28 28"' in d.as_svg()


def test_view_box_auto_string_and_render_kwargs():
    d = draw.Drawing(100, 100)
    d.append(draw.Rectangle(40, 40, 20, 20))
    d.view_box = 'auto'
    assert 'viewBox="40 40 20 20"' in d.as_svg()

    d2 = draw.Drawing(100, 100)
    d2.append(draw.Circle(25, 25, 5))
    svg = d2.as_svg(auto_view_box=True, padding=2)
    assert 'viewBox="18 18 14 14"' in svg


def test_manual_viewbox_overrides_constructor_auto():
    d = draw.Drawing(50, 50, fit_view_box=True, padding=5)
    d.append(draw.Circle(25, 25, 5))
    d.view_box = (0, 0, 50, 50)
    assert 'viewBox="0 0 50 50"' in d.as_svg()


def test_viewbox_object_is_tuple():
    d = draw.Drawing(10, 10)
    d.append(draw.Rectangle(1, 2, 3, 4))
    vb = d.fit_view_box()
    assert isinstance(vb, tuple)
    assert isinstance(vb, ViewBox)
    assert vb.x == 1 and vb.y == 2
    assert vb.width == 3 and vb.height == 4
    assert vb.xmax == 4 and vb.ymax == 6
    box = vb.as_bounds()
    assert isinstance(box, BoundingBox)


def test_module_level_functions_accept_element_list():
    elems = [draw.Rectangle(0, 0, 10, 10), draw.Circle(50, 50, 2)]
    box = geometry_bounds(elems)
    assert (box.xmin, box.ymin) == (0, 0)
    assert box.xmax == pytest.approx(52) and box.ymax == pytest.approx(52)
