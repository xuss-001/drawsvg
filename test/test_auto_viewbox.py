'''Tests for fitting a Drawing's viewBox to its geometry.'''

import pytest

import drawsvg as draw


def assert_view_box(drawing, expected, rel=1e-9, abs_=1e-9):
    assert drawing.view_box == pytest.approx(expected, rel=rel, abs=abs_)


def test_primitives_and_uniform_padding():
    d = draw.Drawing(auto_viewbox=True, padding=2)
    d.append(draw.Rectangle(-5, 10, 20, 4))
    d.append(draw.Circle(-12, 0, 3))
    d.append(draw.Ellipse(20, 10, 4, 7))
    d.append(draw.Lines(30, -5, 35, -5, 35, -1, 30, -1, close=True))

    assert_view_box(d, (-17, -7, 54, 26))

    d.padding = 0
    assert_view_box(d, (-15, -5, 50, 22))


def test_curve_extrema_are_not_control_points_or_endpoints():
    cubic = draw.Path().M(0, 0).C(0, 100, 100, 100, 100, 0)
    d = draw.Drawing(auto_viewbox=True)
    d.append(cubic)
    assert_view_box(d, (0, 0, 100, 75))

    quadratic = draw.Path().M(0, 0).Q(50, 100, 100, 0)
    d = draw.Drawing(auto_viewbox=True)
    d.append(quadratic)
    assert_view_box(d, (0, 0, 100, 50))


def test_relative_commands_smooth_curves_and_closed_subpaths():
    p = draw.Path().M(0, 0).l(10, 0).l(0, 10).Z().m(100, 0).l(10, 0)
    d = draw.Drawing(auto_viewbox=True)
    d.append(p)
    assert_view_box(d, (0, 0, 110, 10))

    p = draw.Path().M(0, 0).c(0, 100, 100, 100, 100, 0).S(200, -100, 200, 0)
    d = draw.Drawing(auto_viewbox=True)
    d.append(p)
    assert_view_box(d, (0, -75, 200, 150))

    p = draw.Path().M(0, 0).q(50, 100, 100, 0).T(200, 0)
    d = draw.Drawing(auto_viewbox=True)
    d.append(p)
    assert_view_box(d, (0, -50, 200, 100))


@pytest.mark.parametrize('sweep, expected', [
    (1, (0, -50, 100, 50)),
    (0, (0, 0, 100, 50)),
])
def test_elliptical_arc_bounds(sweep, expected):
    p = draw.Path().M(0, 0).A(50, 50, 0, 0, sweep, 100, 0)
    d = draw.Drawing(auto_viewbox=True)
    d.append(p)
    assert_view_box(d, expected)

    relative = draw.Path().M(10, 10).a(
        50, 50, 0, 0, sweep, 100, 0)
    d = draw.Drawing(auto_viewbox=True)
    d.append(relative)
    assert_view_box(d, (10, expected[1] + 10, 100, expected[3]))


def test_nested_affine_transforms_rotation_reflection_and_padding():
    p = draw.Path().M(0, 0).Q(50, -40, 100, 0)

    inner = draw.Group(transform='rotate(90)')
    inner.append(p)
    middle = draw.Group(transform='translate(10,-5) scale(2,1)')
    middle.append(inner)
    outer = draw.Group(transform='scale(1,-1)')
    outer.append(middle)

    d = draw.Drawing(auto_viewbox=True, padding=2)
    d.append(outer)

    assert_view_box(d, (8, -97, 44, 104))
    assert ('viewBox="8.0 -97.0 44.0 104.0"' in d.as_svg())


def test_arc_is_not_clipped_after_reflection_and_scale():
    p = draw.Path(stroke='red', fill='none')
    p.M(0, 0).A(50, 50, 0, 0, 1, 100, 0)
    g = draw.Group(transform='scale(-1,2) translate(10,5)')
    g.append(p)

    d = draw.Drawing(auto_viewbox=True)
    d.append(g)
    assert_view_box(d, (-110, -90, 100, 100))


def test_transform_matrix_and_skew_are_supported():
    p = draw.Path().M(0, 0).L(10, 0)
    g = draw.Group(transform='matrix(1 0 1 1 5 7) skewY(45)')
    g.append(p)

    d = draw.Drawing(auto_viewbox=True)
    d.append(g)
    assert_view_box(d, (5, 7, 20, 10))


def test_geometry_data_is_not_modified():
    path_data = 'M0,0 q50,-40 100,0 a20,10 30 0 1 20,20 z'
    transform = 'translate(3,4) rotate(20)'
    p = draw.Path(d=path_data, transform=transform)
    d = draw.Drawing(auto_viewbox=True)
    d.append(p)

    d.view_box

    assert p.args['d'] == path_data
    assert p.args['transform'] == transform


def test_text_images_strokes_and_filters_are_not_counted():
    d = draw.Drawing(auto_viewbox=True, padding=1)
    rect = draw.Rectangle(0, 0, 10, 10, stroke='black', stroke_width=100)
    rect.append_title('ignored')
    d.append(rect)
    d.append(draw.Text('ignored', 1000, 5000, 5000))
    d.append(draw.Image(5000, 5000, 100, 100, path='missing.png'))
    d.append(draw.Filter(x=-1000, y=-1000, width=10000, height=10000))

    assert_view_box(d, (-1, -1, 12, 12))


def test_only_non_geometry_is_empty():
    d = draw.Drawing(auto_viewbox=True)
    d.append(draw.Text('nothing to measure', 12, 0, 0))

    with pytest.raises(draw.EmptyDrawingError):
        d.view_box
    with pytest.raises(draw.EmptyDrawingError):
        d.as_svg()


def test_empty_drawing_raises():
    d = draw.Drawing(auto_viewbox=True)
    with pytest.raises(draw.EmptyDrawingError):
        d.calc_view_box()


def test_unsupported_visible_element_raises_clear_error():
    d = draw.Drawing(auto_viewbox=True)
    d.append(draw.Use(draw.Rectangle(0, 0, 1, 1), 0, 0))

    with pytest.raises(draw.UnsupportedGeometryError, match='<use>'):
        d.view_box


def test_manual_view_box_still_works_and_auto_is_opt_in():
    d = draw.Drawing(100, 50, viewBox='-1 -2 3 4')
    d.append(draw.Rectangle(1000, 1000, 10, 10))

    assert d.view_box == (0, 0, 100, 50)
    assert 'viewBox="-1 -2 3 4"' in d.as_svg()

    fixed = draw.Drawing(100, 50)
    fixed.view_box = (-10, -20, 30, 40)
    assert fixed.view_box == (-10, -20, 30, 40)
    assert 'viewBox="-10 -20 30 40"' in fixed.as_svg()


def test_auto_dimensions_when_width_and_height_are_omitted():
    d = draw.Drawing(auto_viewbox=True, padding=5)
    d.append(draw.Rectangle(10, 20, 30, 40))

    assert_view_box(d, (5, 15, 40, 50))
    svg = d.as_svg()
    assert 'width="40.0" height="50.0"' in svg
    assert 'viewBox="5.0 15.0 40.0 50.0"' in svg


def test_auto_viewbox_can_be_enabled_with_string_conveniences():
    for d in (
            draw.Drawing(origin='auto', padding=1),
            draw.Drawing(viewBox='auto', padding=1)):
        d.append(draw.Rectangle(0, 0, 10, 20))
        assert_view_box(d, (-1, -1, 12, 22))
