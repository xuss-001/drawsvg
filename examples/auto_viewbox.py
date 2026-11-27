'''Generate an SVG whose viewBox fits a transformed curved path.

Run from the repository root:

    python examples/auto_viewbox.py
'''

import pathlib

import drawsvg as draw


path = draw.Path(fill='#1166cc')
path.M(0, 0).Q(50, -40, 100, 0).Z()

inner = draw.Group(transform='rotate(90)')
inner.append(path)

middle = draw.Group(transform='translate(10,-5) scale(2,1)')
middle.append(inner)

outer = draw.Group(transform='scale(1,-1)')
outer.append(middle)

drawing = draw.Drawing(auto_viewbox=True, padding=12)
drawing.append(outer)

output = pathlib.Path(__file__).with_suffix('.svg')
drawing.save_svg(output)

print('viewBox:', ' '.join(map(str, drawing.view_box)))
print('saved:', output)
