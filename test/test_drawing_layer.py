'''Tests for embedding a Drawing as an independent layer.'''

import io
import xml.etree.ElementTree as ET

import pytest

import drawsvg as draw


SVG_NS = '{http://www.w3.org/2000/svg}'
XLINK_NS = '{http://www.w3.org/1999/xlink}'


def make_source(color):
    drawing = draw.Drawing(100, 80)
    gradient = draw.LinearGradient(0, 0, 100, 0, id='shared-gradient')
    gradient.add_stop(0, color)
    gradient.add_stop(1, 'white')
    clip = draw.ClipPath(id='shared-clip')
    clip.append(draw.Rectangle(0, 0, 80, 80))
    dot = draw.Circle(20, 20, 10, fill=gradient, id='shared-dot')
    tile = draw.Group(id='shared-tile', transform='translate(5 5)')
    tile.append(draw.Rectangle(
        0, 0, 40, 40, fill=gradient, clip_path=clip))
    tile.append(draw.Use(dot, 20, 20))
    drawing.append(tile)
    drawing.append(draw.Use(tile, 50, 0))
    drawing.append(dot)
    return drawing, gradient, clip, dot, tile


def find_by_id(root, element_id):
    return root.find(".//*[@id='{}']".format(element_id))


def test_layers_rewrite_ids_and_preserve_internal_references():
    source_a, gradient_a, clip_a, dot_a, tile_a = make_source('red')
    source_b, gradient_b, clip_b, dot_b, tile_b = make_source('blue')
    original_a = source_a.as_svg()
    original_b = source_b.as_svg()

    target = draw.Drawing(420, 120)
    layer_a = target.add_layer(
        source_a, x=10, y=20, width=180, height=90)
    layer_b = target.add_layer(
        source_b, x=220, y=20, width=180, height=90)

    assert isinstance(layer_a, draw.DrawingLayer)
    assert isinstance(layer_b, draw.Layer)
    svg = target.as_svg()
    root = ET.fromstring(svg)

    nested = root.findall(SVG_NS + 'svg')
    assert len(nested) == 2
    for layer, expected_x in zip(nested, ('10', '220')):
        assert layer.get('x') == expected_x
        assert layer.get('y') == '20'
        assert layer.get('width') == '180'
        assert layer.get('height') == '90'
        assert layer.get('viewBox') == '0 0 100 80'

    ids = [element.get('id') for element in root.iter()
           if element.get('id') is not None]
    assert len(ids) == len(set(ids))
    assert len(root.findall('.//' + SVG_NS + 'linearGradient')) == 2

    gradient_ids = []
    for layer, color in zip(nested, ('red', 'blue')):
        first_use = layer.find(SVG_NS + 'use')
        tile = find_by_id(root, first_use.get(XLINK_NS + 'href')[1:])
        rect = tile.find('.//' + SVG_NS + 'rect')
        fill = rect.get('fill')
        assert fill.startswith('url(#')
        gradient_id = fill[len('url(#'):-1]
        gradient_ids.append(gradient_id)

        gradient = find_by_id(root, gradient_id)
        assert gradient.tag == SVG_NS + 'linearGradient'
        assert gradient.find(SVG_NS + 'stop').get('stop-color') == color

        clip_id = rect.get('clip-path')[len('url(#'):-1]
        assert find_by_id(root, clip_id).tag == SVG_NS + 'clipPath'

        prefix = gradient_id[:-len('shared-gradient')]
        for use in layer.iter(SVG_NS + 'use'):
            href = use.get(XLINK_NS + 'href')
            assert href.startswith('#' + prefix)
            assert find_by_id(root, href[1:]) is not None

    assert gradient_ids[0] != gradient_ids[1]
    assert find_by_id(root, gradient_ids[0]).find(
        SVG_NS + 'stop').get('stop-color') == 'red'
    assert find_by_id(root, gradient_ids[1]).find(
        SVG_NS + 'stop').get('stop-color') == 'blue'

    # The source drawings and their element ids are untouched.
    assert source_a.as_svg() == original_a
    assert source_b.as_svg() == original_b
    assert gradient_a.id == 'shared-gradient'
    assert gradient_b.id == 'shared-gradient'
    assert clip_a.id == 'shared-clip'
    assert clip_b.id == 'shared-clip'
    assert dot_a.id == 'shared-dot'
    assert dot_b.id == 'shared-dot'
    assert tile_a.id == 'shared-tile'
    assert tile_b.id == 'shared-tile'

    # Exporting multiple times does not change the combined drawing.
    assert target.as_svg() == svg


def test_layer_preserves_elements_then_z_order():
    source = draw.Drawing(100, 100)
    source.append(draw.Rectangle(1, 0, 1, 1, id='first'))
    source.append(draw.Rectangle(2, 0, 2, 2, id='later'))
    source.append(draw.Rectangle(3, 0, 3, 3, id='earlier'), z=10)
    source.append(draw.Rectangle(4, 0, 4, 4, id='last'), z=-5)

    target = draw.Drawing(100, 100)
    target.add_layer(source)
    root = ET.fromstring(target.as_svg())
    layer = root.find(SVG_NS + 'svg')
    xs = [child.get('x') for child in layer if child.tag == SVG_NS + 'rect']
    assert xs == ['1', '2', '4', '3']
    widths = [child.get('width') for child in layer
              if child.tag == SVG_NS + 'rect']
    assert widths == ['1', '2', '4', '3']


def test_draw_can_embed_a_drawing():
    source = draw.Drawing(40, 20)
    source.append(draw.Rectangle(0, 0, 40, 20, fill='red'))
    target = draw.Drawing(100, 100)
    target.draw(source, x=5, y=6, width=20, height=10)

    root = ET.fromstring(target.as_svg())
    layer = root.find(SVG_NS + 'svg')
    assert layer.get('x') == '5'
    assert layer.get('y') == '6'
    assert layer.get('width') == '20'
    assert layer.get('height') == '10'
    assert layer.get('viewBox') == '0 0 40 20'


def test_combined_drawing_can_be_embedded_again():
    source_a, *_ = make_source('red')
    source_b, *_ = make_source('blue')

    middle = draw.Drawing(400, 100)
    middle.add_layer(source_a, x=0, y=0, width=180, height=90)
    middle.add_layer(source_b, x=220, y=0, width=180, height=90)
    middle_svg = middle.as_svg()

    outer = draw.Drawing(500, 200)
    outer.add_layer(middle, x=30, y=40, width=400, height=100)
    outer_svg = outer.as_svg()
    root = ET.fromstring(outer_svg)

    ids = [element.get('id') for element in root.iter()
           if element.get('id') is not None]
    assert len(ids) == len(set(ids))

    nested_layers = root.findall('.//' + SVG_NS + 'svg')
    assert len(nested_layers) == 3
    for layer in nested_layers:
        for use in layer.iter(SVG_NS + 'use'):
            assert find_by_id(root, use.get(XLINK_NS + 'href')[1:]) is not None
        for rect in layer.iter(SVG_NS + 'rect'):
            for attr in ('fill', 'clip-path'):
                value = rect.get(attr)
                if value is not None and value.startswith('url(#'):
                    assert find_by_id(root, value[len('url(#'):-1]) is not None

    assert middle.as_svg() == middle_svg
    assert source_a.as_svg() == make_source('red')[0].as_svg()
    assert source_b.as_svg() == make_source('blue')[0].as_svg()


def test_layer_preserves_viewbox_context_and_string_references():
    source = draw.Drawing(
        100, 80, origin='center', context=draw.Context(invert_y=True))
    gradient = draw.LinearGradient(0, 0, 100, 0, id='paint')
    gradient.add_stop(0, 'red')
    gradient.add_stop(1, 'red')
    source.append_def(gradient)
    source.append(draw.Rectangle(
        -10, -10, 20, 5, id='shape', fill='url(#paint)'))
    source.append(draw.Use('shape', 30, 0))
    source.append(draw.Rectangle(0, 0, 1, 1, id='ff0000'))
    source.append(draw.Rectangle(0, 0, 2, 2, fill='#ff0000'))

    source_root = ET.fromstring(source.as_svg())
    target = draw.Drawing(240, 120)
    target.add_layer(
        source, x=20, y=10, width=200, height=100)
    root = ET.fromstring(target.as_svg())
    layer = root.find(SVG_NS + 'svg')

    assert layer.get('viewBox') == source_root.get('viewBox')
    rect = layer.find(SVG_NS + 'rect')
    gradient_id = rect.get('fill')[len('url(#'):-1]
    assert find_by_id(root, gradient_id).tag == SVG_NS + 'linearGradient'
    use = layer.find(SVG_NS + 'use')
    use_target = use.get(XLINK_NS + 'href')[1:]
    assert use_target == rect.get('id')
    assert find_by_id(root, use_target) is not None
    fills = [element.get('fill') for element in layer.iter(SVG_NS + 'rect')]
    assert '#ff0000' in fills


def test_layer_position_display_size_and_rendering():
    cairosvg = pytest.importorskip('cairosvg')
    Image = pytest.importorskip('PIL.Image')

    red = draw.Drawing(100, 100)
    red.append(draw.Rectangle(0, 0, 100, 100, fill='#ff0000'))
    blue = draw.Drawing(100, 100)
    blue.append(draw.Rectangle(0, 0, 100, 100, fill='#0000ff'))

    target = draw.Drawing(300, 100)
    target.add_layer(red, x=0, y=0, width=100, height=100)
    target.add_layer(blue, x=200, y=0, width=50, height=50)

    png = cairosvg.svg2png(
        bytestring=target.as_svg().encode(), output_width=300,
        output_height=100)
    image = Image.open(io.BytesIO(png)).convert('RGBA')

    red_pixel = image.getpixel((50, 50))
    blue_pixel = image.getpixel((220, 20))
    gap_pixel = image.getpixel((150, 50))
    outside_blue_layer = image.getpixel((270, 50))

    assert red_pixel[0] > 240 and red_pixel[1] < 15 and red_pixel[2] < 15
    assert blue_pixel[2] > 240 and blue_pixel[0] < 15 and blue_pixel[1] < 15
    assert gap_pixel[3] == 0
    assert outside_blue_layer[3] == 0


def test_layer_gradients_render_without_cross_layer_references():
    cairosvg = pytest.importorskip('cairosvg')
    Image = pytest.importorskip('PIL.Image')

    def gradient_source(start, end):
        drawing = draw.Drawing(100, 100)
        gradient = draw.LinearGradient(
            0, 0, 100, 0, id='gradient', gradientUnits='userSpaceOnUse')
        gradient.add_stop(0, start)
        gradient.add_stop(1, end)
        drawing.append(draw.Rectangle(0, 0, 100, 100, fill=gradient))
        return drawing

    first = gradient_source('red', 'red')
    second = gradient_source('blue', 'blue')
    target = draw.Drawing(200, 100)
    target.add_layer(first, x=0, y=0, width=100, height=100)
    target.add_layer(second, x=100, y=0, width=100, height=100)

    png = cairosvg.svg2png(
        bytestring=target.as_svg().encode(), output_width=200,
        output_height=100)
    image = Image.open(io.BytesIO(png)).convert('RGBA')

    left = image.getpixel((50, 50))
    right = image.getpixel((150, 50))
    assert left[0] > 240 and left[1] < 15 and left[2] < 15
    assert right[2] > 240 and right[0] < 15 and right[1] < 15
