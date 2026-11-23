'''Tests for automatic text layout and wrapping.'''

import pytest

import drawsvg as draw


def _width(text):
    return len(text)


def _display_width(text):
    return sum(2 if ord(char) >= 0x2E80 else 1 for char in text)


def test_preserves_line_breaks_and_blank_lines_and_collapses_spaces():
    text = '  alpha   beta \r\n\r\n gamma\t\tdelta  '
    assert draw.layout_text(
            text, measure=_width, max_width=100, max_lines=10) == [
                    'alpha beta', '', 'gamma delta']

    assert draw.layout_text(
            'alpha\n', measure=_width, max_width=100, max_lines=10) == [
                    'alpha', '']
    assert draw.layout_text(
            'a\n\n\nb', measure=_width, max_width=100, max_lines=10) == [
                    'a', '', '', 'b']


def test_keeps_english_words_whole_and_wraps_between_cjk_characters():
    assert draw.layout_text(
            'hello world', measure=_width, max_width=7, max_lines=10) == [
                    'hello', 'world']
    assert draw.layout_text(
            'hello world', measure=_width, max_width=11, max_lines=10) == [
                    'hello world']
    assert draw.layout_text(
            '中文自动换行测试', measure=_display_width, max_width=4,
            max_lines=10) == ['中文', '自动', '换行', '测试']


def test_breaks_an_overlong_word_between_complete_characters():
    assert draw.layout_text(
            'supercalifragilistic', measure=_width, max_width=5,
            max_lines=10) == ['super', 'calif', 'ragil', 'istic']


@pytest.mark.parametrize('sequence', [
    'e\u0301',
    '\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466',
    '\U0001F1E8\U0001F1F3',
    '1\ufe0f\u20e3',
    '\U0001F44D\U0001F3FD',
    '\u0915\u094d\u0937',
    '\u1100\u1161',
])
def test_does_not_split_grapheme_clusters(sequence):
    assert draw.layout_text(
            sequence * 2, measure=_width, max_width=len(sequence),
            max_lines=10) == [sequence, sequence]


def test_an_overwide_grapheme_gets_its_own_line():
    family = '\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466'
    assert draw.layout_text(
            family * 2, measure=_width, max_width=len(family) - 1,
            max_lines=10) == [family, family]


def test_width_is_measured_for_the_complete_line():
    def measure(text):
        if text == 'hello world':
            return 5
        return len(text)

    assert draw.layout_text(
            'hello world', measure=measure, max_width=6, max_lines=2) == [
                    'hello world']

    def cjk_measure(text):
        if text == '中文':
            return 5
        return len(text) * 10

    assert draw.layout_text(
            '中文', measure=cjk_measure, max_width=5, max_lines=2) == ['中文']


def test_truncates_the_last_line_with_an_ellipsis():
    assert draw.layout_text(
            'one two three four five', measure=_width, max_width=5,
            max_lines=2) == ['one', 'two\u2026']
    assert draw.layout_text(
            'one two three four five', measure=_width, max_width=5,
            max_lines=3) == ['one', 'two', 'thre\u2026']


def test_leaves_the_last_line_empty_when_the_ellipsis_does_not_fit():
    assert draw.layout_text(
            'abc', measure=_width, max_width=1, max_lines=1) == ['\u2026']
    assert draw.layout_text(
            'abc', measure=_width, max_width=0.5, max_lines=1) == ['']


def test_mixed_chinese_english_and_emoji_layout():
    family = '\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466'
    text = (
        'DrawSVG 自动换行\n\n'
        '标签支持 English words 和 emoji {}，宽度受限时自动截断。'.format(
                family))
    lines = draw.layout_text(
            text, measure=_display_width, max_width=24, max_lines=5)

    assert lines == [
        'DrawSVG 自动换行',
        '',
        '标签支持 English words',
        '和 emoji {}\uff0c宽'.format(family),
        '度受限时自动截断。',
    ]
    assert lines[1] == ''
    assert all(_display_width(line) <= 24 for line in lines)


def test_text_uses_layout_without_modifying_source_and_stays_compatible():
    source = 'alpha beta'
    text = draw.Text(
            source, 10, 0, 0, measure=_width, max_width=5, max_lines=3)
    assert source == 'alpha beta'
    assert [child.escaped_text for child in text.children] == ['alpha', 'beta']

    source_lines = ['alpha beta', '', 'gamma']
    text = draw.Text(
            source_lines, 10, 0, 0, measure=_width, max_width=5, max_lines=5)
    assert source_lines == ['alpha beta', '', 'gamma']
    assert [child.escaped_text for child in text.children] == [
            'alpha', 'beta', '', 'gamma']

    text = draw.Text('alpha beta', 10, 0, 0)
    assert text.escaped_text == 'alpha beta'
    assert text.children == []

    text = draw.Text(
            'alpha beta', 10, 0, 0, measure=_width, max_width=100,
            max_lines=2)
    assert text.escaped_text == 'alpha beta'
    assert text.children == []


def test_text_wrapping_on_a_path_returns_a_group():
    path = draw.Path()
    path.M(0, 0).L(100, 0)
    text = draw.Text(
            '自动换行 English words for labels', 10, path=path,
            measure=_display_width, max_width=30, max_lines=4)
    assert isinstance(text, draw.Group)
    assert len(text.children) > 1


@pytest.mark.parametrize('max_width', [
    0, -1, float('nan'), float('inf'), '10', True, None])
def test_invalid_max_width_raises(max_width):
    with pytest.raises(ValueError):
        draw.layout_text(
                'text', measure=_width, max_width=max_width, max_lines=1)


@pytest.mark.parametrize('max_lines', [0, -1, 1.5, '2', True, None])
def test_invalid_max_lines_raises(max_lines):
    with pytest.raises(ValueError):
        draw.layout_text(
                'text', measure=_width, max_width=10, max_lines=max_lines)


@pytest.mark.parametrize('measure', [None, 1, 'len'])
def test_invalid_measure_raises(measure):
    with pytest.raises(TypeError):
        draw.layout_text(
                'text', measure=measure, max_width=10, max_lines=1)


@pytest.mark.parametrize('value', [None, -1, float('nan'), float('inf'), True])
def test_invalid_measurement_result_raises(value):
    with pytest.raises(ValueError):
        draw.layout_text(
                'text', measure=lambda text: value, max_width=10,
                max_lines=1)


def test_text_rejects_incomplete_wrapping_arguments():
    with pytest.raises(TypeError):
        draw.Text('text', 10, 0, 0, max_width=10, max_lines=1)
    with pytest.raises(TypeError):
        draw.Text(
                'text', 10, 0, 0, measure=_width, measure_text=_width,
                max_width=10, max_lines=1)
    with pytest.raises(ValueError):
        draw.Text(
                'text', 10, 0, 0, measure=_width, max_width=0,
                max_lines=1)
