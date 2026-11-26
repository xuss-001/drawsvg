import io
import re
import xml.etree.ElementTree as ET

import pytest

import drawsvg as draw


def _find_by_id(root, element_id):
    return root.find(".//*[@id='{}']".format(element_id))


def _url_id(value):
    match = re.fullmatch(r'url\(#([^)]+)\)', value)
    assert match, value
    return match.group(1)


def test_equivalent_color_forms_and_special_values():
    d = draw.Drawing(120, 80)
    named = draw.Rectangle(0, 0, 20, 20, fill='red')
    hex_value = draw.Rectangle(25, 0, 20, 20, fill='#ff0000')
    rgb_value = draw.Rectangle(50, 0, 20, 20, fill='rgb(255, 0, 0)')
    no_fill = draw.Rectangle(75, 0, 20, 20, fill='none', stroke='red')
    current = draw.Rectangle(
        100, 0, 20, 20, fill='currentColor', color='red')
    d.extend([named, hex_value, rgb_value, no_fill, current])

    themed = d.recolor(
        {'rgb(255, 0, 0)': 'blue'}, elements=d.elements)
    svg = themed.as_svg()

    assert svg.count('fill="blue"') == 3
    assert 'fill="#ff0000"' not in svg
    assert 'fill="none"' in svg
    assert 'stroke="blue"' in svg
    assert 'fill="currentColor"' in svg
    assert 'color="blue"' in svg


def test_group_inheritance_and_local_override():
    d = draw.Drawing(120, 60)
    inherited_group = draw.Group(fill='red')
    inherited = draw.Rectangle(0, 0, 20, 20)
    inherited_group.append(inherited)
    overridden = draw.Rectangle(25, 0, 20, 20, fill='lime')
    inherited_group.append(overridden)
    d.append(inherited_group)

    outer = draw.Group(fill='red')
    selected_child = draw.Rectangle(55, 0, 20, 20)
    unselected_child = draw.Rectangle(80, 0, 20, 20)
    outer.extend([selected_child, unselected_child])
    d.append(outer)

    themed = d.recolor(
        {'#ff0000': 'blue', '#00ff00': 'yellow'},
        elements=[inherited_group, selected_child])
    svg = themed.as_svg()

    assert '<g fill="blue">' in svg
    assert 'fill="lime"' not in svg
    assert 'fill="yellow"' in svg
    assert selected_child.args.get('fill') is None
    assert outer.args['fill'] == 'red'
    assert themed.elements[1].children[0].args['fill'] == 'blue'
    assert themed.elements[1].children[1].args.get('fill') is None


def test_shared_gradient_and_gradient_href_are_isolated():
    base = draw.LinearGradient(0, 0, 200, 0, id='base')
    base.add_stop(0, 'red')
    base.add_stop(1, 'lime')
    referenced = draw.LinearGradient(
        0, 0, 200, 0, id='referenced', xlink__href='#base')
    d = draw.Drawing(200, 80)
    d.append_def(base)
    d.append_def(referenced)
    selected = draw.Rectangle(0, 0, 80, 40, fill='url(#referenced)')
    unselected = draw.Rectangle(100, 0, 80, 40, fill='url(#referenced)')
    d.extend([selected, unselected])

    original_svg = d.as_svg()
    themed = d.recolor({'red': 'blue', '#00ff00': 'yellow'}, elements=selected)
    svg = themed.as_svg()
    root = ET.fromstring(svg)

    selected_fill = themed.elements[0].args['fill']
    assert isinstance(selected_fill, draw.LinearGradient)
    selected_id = selected_fill.id
    selected_gradient = _find_by_id(root, selected_id)
    assert selected_gradient is not None

    selected_href = selected_gradient.attrib[
        '{http://www.w3.org/1999/xlink}href'][1:]
    selected_base = _find_by_id(root, selected_href)
    assert selected_base is not None
    assert [s.attrib['stop-color'] for s in selected_base] == [
        'blue', 'yellow']

    unselected_gradient = _find_by_id(
        root, _url_id(themed.elements[1].args['fill']))
    assert unselected_gradient is not None
    unselected_href = unselected_gradient.attrib[
        '{http://www.w3.org/1999/xlink}href'][1:]
    unselected_base = _find_by_id(root, unselected_href)
    assert [s.attrib['stop-color'] for s in unselected_base] == [
        'red', 'lime']
    ids = [element.attrib['id'] for element in root.iter()
           if 'id' in element.attrib]
    assert len(ids) == len(set(ids))

    assert original_svg == d.as_svg()
    assert svg == themed.as_svg()


def test_geometry_and_opacity_are_unchanged():
    d = draw.Drawing(100, 100)
    selected = draw.Rectangle(
        10, 20, 30, 40, fill='red', fill_opacity=0.25,
        stroke='lime', stroke_width=3, stroke_opacity=0.5, opacity=0.75,
        transform='translate(2 3)')
    unselected = draw.Rectangle(50, 10, 20, 20, fill='red')
    d.extend([selected, unselected])

    themed = d.recolor({'red': 'blue', 'lime': 'yellow'}, elements=selected)
    themed_selected = themed.elements[0]

    for key in ('x', 'y', 'width', 'height', 'fill-opacity',
                'stroke-width', 'stroke-opacity', 'opacity', 'transform'):
        assert themed_selected.args[key] == selected.args[key]
    assert themed_selected.args['fill'] == 'blue'
    assert themed_selected.args['stroke'] == 'yellow'
    assert themed.elements[1].args['fill'] == 'red'
    assert selected.args['fill'] == 'red'
    assert selected.args['stroke'] == 'lime'


def test_external_dependencies_raise_clear_errors():
    d = draw.Drawing(100, 100)
    d.append_css('@import url("https://example.com/theme.css");')
    shape = draw.Rectangle(
        0, 0, 20, 20, fill='red', class_='theme-shape')
    d.append(shape)
    with pytest.raises(draw.UnsupportedExternalResourceError, match='external'):
        d.recolor({'red': 'blue'}, elements=shape)

    d2 = draw.Drawing(100, 100)
    shape2 = draw.Rectangle(
        0, 0, 20, 20, fill='url(https://example.com/paint.svg#gradient)')
    d2.append(shape2)
    with pytest.raises(draw.UnsupportedExternalResourceError, match='external'):
        d2.recolor({'red': 'blue'}, elements=shape2)


def _build_render_drawing():
    d = draw.Drawing(320, 220)

    inherited = draw.Group(fill='red')
    inherited.append(draw.Rectangle(10, 10, 70, 50))
    local = draw.Rectangle(90, 10, 70, 50, fill='lime')
    unselected = draw.Group(fill='red')
    unselected.append(draw.Rectangle(170, 10, 70, 50))
    alpha = draw.Rectangle(
        250, 10, 60, 50, fill='rgba(255, 0, 0, 0.5)', fill_opacity=0.5)
    d.extend([inherited, local, unselected, alpha])

    gradient = draw.LinearGradient(0, 0, 320, 0)
    gradient.add_stop(0, 'red')
    gradient.add_stop(1, 'lime')
    gradient_selected = draw.Rectangle(10, 80, 120, 50, fill=gradient)
    gradient_unselected = draw.Rectangle(150, 80, 120, 50, fill=gradient)
    d.extend([gradient_selected, gradient_unselected])
    d.append(draw.Rectangle(10, 150, 70, 50, fill='currentColor',
                            color='black'))
    d.append(draw.Rectangle(90, 150, 70, 50, fill='none', stroke='red',
                            stroke_width=4))

    selected = [
        inherited, local, alpha, gradient_selected, d.elements[-2],
        d.elements[-1],
    ]
    return d, selected


def _render_png(drawing):
    cairosvg = pytest.importorskip('cairosvg')
    image_module = pytest.importorskip('PIL.Image')
    data = cairosvg.svg2png(bytestring=drawing.as_svg().encode('utf-8'))
    return image_module.open(io.BytesIO(data)).convert('RGBA')


def _pixel(image, xy):
    return image.getpixel(xy)


def _region(image, box):
    return image.crop(box).tobytes()


def test_rendered_colors_inheritance_alpha_and_unselected_pixels():
    d, selected = _build_render_drawing()
    themed = d.recolor(
        {'red': 'blue', 'lime': 'yellow'}, elements=selected)
    before = _render_png(d)
    after = _render_png(themed)

    assert _pixel(before, (45, 35))[:3] == (255, 0, 0)
    assert _pixel(after, (45, 35))[:3] == (0, 0, 255)
    assert _pixel(before, (125, 35))[:3] == (0, 255, 0)
    assert _pixel(after, (125, 35))[:3] == (255, 255, 0)

    assert _region(before, (170, 10, 240, 60)) == _region(
        after, (170, 10, 240, 60))
    assert _region(before, (150, 80, 270, 130)) == _region(
        after, (150, 80, 270, 130))

    before_alpha = _pixel(before, (280, 35))[3]
    after_alpha = _pixel(after, (280, 35))[3]
    assert before_alpha == pytest.approx(64, abs=2)
    assert after_alpha == pytest.approx(before_alpha, abs=1)
    assert _pixel(after, (280, 35))[:3] == (0, 0, 255)

    before_gradient = _pixel(before, (20, 105))[:3]
    after_gradient = _pixel(after, (20, 105))[:3]
    assert before_gradient[0] > before_gradient[1]
    assert after_gradient[2] > after_gradient[1]

    assert _pixel(before, (45, 175))[:3] == (0, 0, 0)
    assert _pixel(after, (45, 175))[:3] == (0, 0, 0)

    before_alpha_channel = [_pixel(before, (x, y))[3]
                            for x in range(2, 318, 4)
                            for y in range(2, 218, 4)]
    after_alpha_channel = [_pixel(after, (x, y))[3]
                           for x in range(2, 318, 4)
                           for y in range(2, 218, 4)]
    assert before_alpha_channel == after_alpha_channel
