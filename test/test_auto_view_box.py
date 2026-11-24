import re

import pytest

import drawsvg as draw


def assert_view_box(actual, expected):
    assert actual == pytest.approx(expected)


def test_auto_view_box_covers_supported_primitives_and_margin():
    d = draw.Drawing(10, 10)
    d.append(draw.Rectangle(-10, 5, 20, 10))
    d.append(draw.Circle(30, -4, 3))
    d.append(draw.Ellipse(-5, -5, 4, 2))
    d.append(draw.Lines(40, 20, -20, 30, 30, 40))

    assert_view_box(d.calc_view_box(), (-20, -7, 60, 47))
    assert_view_box(d.auto_view_box(margin=2).view_box, (-22, -9, 64, 51))
    assert (d.width, d.height) == pytest.approx((64, 51))


def test_transformed_rectangle_uses_all_four_corners():
    d = draw.Drawing(1, 1)
    d.append(draw.Rectangle(0, 0, 10, 20, transform='rotate(45)'))
    assert_view_box(d.calc_view_box(), (
            -10 * 2**0.5, 0, 15 * 2**0.5, 15 * 2**0.5))


def test_path_curve_extrema_are_not_just_endpoints():
    d = draw.Drawing(1, 1)
    cubic = draw.Path()
    cubic.M(0, 0).C(0, 100, 100, 100, 100, 0)
    d.append(cubic)
    assert_view_box(d.calc_view_box(), (0, 0, 100, 75))

    d.clear()
    quadratic = draw.Path()
    quadratic.M(0, 0).Q(50, 100, 100, 0)
    d.append(quadratic)
    assert_view_box(d.calc_view_box(), (0, 0, 100, 50))


def test_relative_closed_and_smooth_path_commands():
    d = draw.Drawing(1, 1)
    relative = draw.Path('m 10 10 c 0 40 40 40 40 0 z')
    d.append(relative)
    assert_view_box(d.calc_view_box(), (10, 10, 40, 30))

    d.clear()
    smooth = draw.Path('M 0 0 C 0 10 10 10 10 0 S 20 -10 20 0')
    d.append(smooth)
    assert_view_box(d.calc_view_box(), (0, -7.5, 20, 15))

    d.clear()
    smooth_quadratic = draw.Path('M 0 0 Q 10 20 20 0 T 40 0')
    d.append(smooth_quadratic)
    assert_view_box(d.calc_view_box(), (0, -10, 40, 20))

    d.clear()
    multiple_subpaths = draw.Path('m 10 10 h 20 v 10 h -20 z m 100 100 h 10 v 10 h -10 z')
    d.append(multiple_subpaths)
    assert_view_box(d.calc_view_box(), (10, 10, 110, 110))


def test_elliptical_arc_bounds_include_transformed_extrema():
    d = draw.Drawing(1, 1)
    arc = draw.Path('M 0 0 A 10 10 0 0 1 20 0')
    d.append(arc)
    assert_view_box(d.calc_view_box(), (0, -10, 20, 10))

    rotated = draw.Path('M 0 0 A 10 10 0 0 1 20 0',
                        transform='rotate(90)')
    d = draw.Drawing(1, 1)
    d.append(rotated)
    assert_view_box(d.calc_view_box(3), (-3, -3, 16, 26))


def test_nested_group_transforms_curves_and_margin():
    inner = draw.Group(transform='translate(10, 20) scale(1, -1)')
    curve = draw.Path()
    curve.M(0, 0).C(0, 40, 40, 40, 40, 0)
    inner.append(curve)
    outer = draw.Group(transform='rotate(90)')
    outer.append(inner)

    d = draw.Drawing(1, 1)
    d.append(outer)
    geometry_before = curve.args['d'], inner.args['transform'], outer.args['transform']

    d.auto_view_box(margin=5)
    assert_view_box(d.view_box, (-25, 5, 40, 50))
    assert (d.width, d.height) == pytest.approx((40, 50))
    assert (curve.args['d'], inner.args['transform'],
            outer.args['transform']) == geometry_before

    svg = d.as_svg()
    view_box_text = re.search(r'viewBox="([^"]+)"', svg).group(1)
    assert tuple(map(float, view_box_text.split())) == pytest.approx(
            (-25, 5, 40, 50))
    assert 'width="40.0"' in svg
    assert 'height="50.0"' in svg


def test_manual_view_box_and_geometry_are_unchanged():
    d = draw.Drawing(100, 80, viewBox='-5 -2 20 10')
    d.append(draw.Circle(0, 0, 3))
    svg = d.as_svg()
    assert 'viewBox="-5 -2 20 10"' in svg
    assert d.view_box == (0, 0, 100, 80)

    d.set_view_box((-10, -20, 30, 40))
    d.append(draw.Rectangle(50, 50, 5, 5))
    svg = d.as_svg()
    assert 'viewBox="-10 -20 30 40"' in svg


def test_auto_view_box_ignores_text_but_rejects_unsupported_shapes():
    d = draw.Drawing(1, 1)
    d.append(draw.Circle(0, 0, 5))
    d.append(draw.Text('not geometry', 20, 1000, 1000))
    assert_view_box(d.calc_view_box(), (-5, -5, 10, 10))

    d = draw.Drawing(1, 1)
    d.append(draw.Use(draw.Circle(0, 0, 5), 0, 0))
    with pytest.raises(NotImplementedError, match='Use'):
        d.calc_view_box()

    d = draw.Drawing(1, 1)
    d.append(draw.Circle(0, 0, 5))
    d.append(draw.Use(draw.Circle(1000, 1000, 5), 0, 0, display='none'))
    assert_view_box(d.calc_view_box(), (-5, -5, 10, 10))


def test_empty_auto_view_box_raises_clear_error():
    d = draw.Drawing(1, 1, auto_view_box=True)
    with pytest.raises(ValueError, match='no supported geometry'):
        d.as_svg()
