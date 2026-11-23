'''Embed several drawings as independently placed layers.

Each source drawing below deliberately uses the same ids ("paint", "clip",
"petal", and "badge"). The combined output keeps those resources separate
between layers while still reusing them inside each layer.
'''

import drawsvg as draw


def make_badge(color_a, color_b):
    drawing = draw.Drawing(120, 120)

    paint = draw.LinearGradient(0, 0, 120, 120, id='paint')
    paint.add_stop(0, color_a)
    paint.add_stop(1, color_b)

    clip = draw.ClipPath(id='clip')
    clip.append(draw.Circle(60, 60, 48))

    petal = draw.Circle(60, 60, 28, fill=paint, id='petal')
    badge = draw.Group(id='badge')
    badge.append(draw.Circle(
        60, 60, 48, fill='none', stroke=paint, stroke_width=8,
        clip_path=clip))
    badge.append(draw.Use(petal, 0, 0))

    drawing.append(badge)
    drawing.append(draw.Use(badge, 24, 0, opacity=0.35))
    return drawing


canvas = draw.Drawing(600, 240, id_prefix='canvas')
canvas.append(draw.Rectangle(0, 0, 600, 240, fill='#20242c'))

canvas.add_layer(
    make_badge('#ff7b00', '#ff0055'), x=40, y=60, width=120, height=120)
canvas.add_layer(
    make_badge('#00d4ff', '#0055ff'), x=210, y=60, width=120, height=120)

# A combined drawing can itself be embedded as a layer.
inner = draw.Drawing(300, 140, id_prefix='inner')
inner.add_layer(
    make_badge('#aaff00', '#00aa55'), x=20, y=10, width=120, height=120)
canvas.add_layer(inner, x=400, y=80, width=150, height=70)

canvas.save_svg('examples/embed_layers.svg')
canvas.save_png('examples/embed_layers.png')
