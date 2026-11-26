'''Render a before/after example of Drawing.recolor().

Run from the repository root:

    python examples/recolor.py --output-dir /tmp/drawsvg-recolor

The output includes SVG and PNG files so inherited colors, local overrides,
shared gradient isolation, and semi-transparent fills can be compared visually.
'''

import argparse
from pathlib import Path

import drawsvg as draw


def build_drawing():
    d = draw.Drawing(320, 220)

    inherited_group = draw.Group(fill='#ff0000')
    inherited_group.append(draw.Rectangle(10, 10, 70, 50))

    local_override = draw.Rectangle(90, 10, 70, 50, fill='#00ff00')

    unselected_group = draw.Group(fill='#ff0000')
    unselected_group.append(draw.Rectangle(170, 10, 70, 50))

    translucent = draw.Rectangle(
        250, 10, 60, 50, fill='rgba(255, 0, 0, 0.5)',
        fill_opacity=0.5)

    gradient = draw.LinearGradient(0, 0, 320, 0)
    gradient.add_stop(0, '#ff0000')
    gradient.add_stop(1, '#00ff00')
    gradient_selected = draw.Rectangle(10, 80, 120, 50, fill=gradient)
    gradient_unselected = draw.Rectangle(150, 80, 120, 50, fill=gradient)

    current_color = draw.Rectangle(
        10, 150, 70, 50, fill='currentColor', color='black')
    no_fill = draw.Rectangle(
        90, 150, 70, 50, fill='none', stroke='#ff0000', stroke_width=4)

    d.extend([
        inherited_group,
        local_override,
        unselected_group,
        translucent,
        gradient_selected,
        gradient_unselected,
        current_color,
        no_fill,
    ])

    selected = [
        inherited_group,
        local_override,
        translucent,
        gradient_selected,
        current_color,
        no_fill,
    ]
    return d, selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--output-dir', default='examples/recolor-output',
        help='directory for the generated SVG and PNG files')
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    drawing, selected = build_drawing()
    themed = drawing.recolor(
        {'#ff0000': '#0000ff', '#00ff00': '#ffff00'},
        elements=selected)

    drawing.save_svg(str(output_dir / 'before.svg'))
    themed.save_svg(str(output_dir / 'after.svg'))
    drawing.save_png(str(output_dir / 'before.png'))
    themed.save_png(str(output_dir / 'after.png'))
    print('Wrote before/after SVG and PNG files to {}'.format(output_dir))


if __name__ == '__main__':
    main()
