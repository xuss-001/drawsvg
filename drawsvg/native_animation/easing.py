"""Easing functions controlling the pacing of one key-frame interval.

An easing maps a normalized time progress ``x`` in the range ``[0, 1]`` to a
normalized value-change progress ``y``.  Every easing satisfies ``y(0) == 0``
and ``y(1) == 1`` so the animated attribute always starts and ends exactly on
its neighboring key-frame values.

Three kinds of pacing are supported, matching the SVG ``calcMode`` options:

- :data:`LINEAR`: straight-line, uniform change (the default behavior).
- :data:`DISCRETE`: hold the previous key-frame value until the end of the
  interval, then jump to the next value (SVG ``calcMode="discrete"``).
- :class:`CubicBezierEasing`: a cubic Bezier curve, equivalent to SVG
  ``calcMode="spline"`` with ``keySplines``.  The Bezier x-coordinates are
  time progress and must both lie in ``[0, 1]``; the y-coordinates (value
  progress) are unrestricted.
"""

from numbers import Real
import math


class Easing:
    """Base class for interval pacing functions."""
    calc_mode = None

    def __call__(self, progress):
        raise NotImplementedError

    @property
    def key_spline(self):
        """The SVG ``keySplines`` control-point string, or ``None``."""
        return None


class LinearEasing(Easing):
    """Uniform linear change across the interval."""
    calc_mode = 'linear'

    def __call__(self, progress):
        return float(progress)

    def __eq__(self, other):
        return isinstance(other, LinearEasing)

    def __hash__(self):
        return hash(('easing', 'linear'))

    def __repr__(self):
        return 'LinearEasing()'


class DiscreteEasing(Easing):
    """Hold the previous value until the interval ends, then jump."""
    calc_mode = 'discrete'

    def __call__(self, progress):
        return 1.0 if progress >= 1 else 0.0

    def __eq__(self, other):
        return isinstance(other, DiscreteEasing)

    def __hash__(self):
        return hash(('easing', 'discrete'))

    def __repr__(self):
        return 'DiscreteEasing()'


def _format_number(value):
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return repr(number)


class CubicBezierEasing(Easing):
    """Cubic Bezier pacing with anchor points ``(0, 0)`` and ``(1, 1)``.

    ``x1, y1`` and ``x2, y2`` are the two control points.  The x-coordinates
    represent normalized time and must both be finite values in ``[0, 1]``;
    the y-coordinates are normalized value progress and may be outside
    ``[0, 1]`` to allow overshoot.
    """
    calc_mode = 'spline'

    def __init__(self, x1, y1, x2, y2):
        self.x1 = self._validate_x(x1, 'x1')
        self.x2 = self._validate_x(x2, 'x2')
        self.y1 = self._validate_y(y1, 'y1')
        self.y2 = self._validate_y(y2, 'y2')

    @staticmethod
    def _validate_x(value, name):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(
                f'cubic Bezier control point {name} must be a real number, '
                f'not {type(value).__name__}')
        number = float(value)
        if not math.isfinite(number) or number < 0 or number > 1:
            raise ValueError(
                f'cubic Bezier control point {name}={value} must be in the '
                'range [0, 1] because it is a time coordinate')
        return number

    @staticmethod
    def _validate_y(value, name):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(
                f'cubic Bezier control point {name} must be a real number, '
                f'not {type(value).__name__}')
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(
                f'cubic Bezier control point {name}={value} must be finite')
        return number

    def _x_at(self, t):
        one_minus_t = 1 - t
        return (3 * one_minus_t**2 * t * self.x1
                + 3 * one_minus_t * t**2 * self.x2 + t**3)

    def _y_at(self, t):
        one_minus_t = 1 - t
        return (3 * one_minus_t**2 * t * self.y1
                + 3 * one_minus_t * t**2 * self.y2 + t**3)

    def _dx_at(self, t):
        one_minus_t = 1 - t
        return (3 * one_minus_t**2 * self.x1
                + 6 * one_minus_t * t * (self.x2 - self.x1)
                + 3 * t**2 * (1 - self.x2))

    def _solve_t(self, progress):
        # Newton-Raphson first, with bisection fallback for horizontal
        # tangents (zero derivative) where Newton makes no progress.
        t = progress
        for _ in range(12):
            error = self._x_at(t) - progress
            if abs(error) < 1e-12:
                return t
            derivative = self._dx_at(t)
            if abs(derivative) < 1e-10:
                break
            t = min(1.0, max(0.0, t - error / derivative))
        low, high = 0.0, 1.0
        for _ in range(60):
            middle = (low + high) / 2
            if self._x_at(middle) < progress:
                low = middle
            else:
                high = middle
        return (low + high) / 2

    def __call__(self, progress):
        if isinstance(progress, bool) or not isinstance(progress, Real):
            raise TypeError('progress must be a real number in [0, 1]')
        x = float(progress)
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        return self._y_at(self._solve_t(x))

    @property
    def key_spline(self):
        return ' '.join(_format_number(v) for v in (
                self.x1, self.y1, self.x2, self.y2))

    def __eq__(self, other):
        return (isinstance(other, CubicBezierEasing)
                and self.x1 == other.x1 and self.y1 == other.y1
                and self.x2 == other.x2 and self.y2 == other.y2)

    def __hash__(self):
        return hash(('easing', 'spline',
                     self.x1, self.y1, self.x2, self.y2))

    def __repr__(self):
        return (f'CubicBezierEasing({_format_number(self.x1)}, '
                f'{_format_number(self.y1)}, {_format_number(self.x2)}, '
                f'{_format_number(self.y2)})')


LINEAR = LinearEasing()
DISCRETE = DiscreteEasing()

# Common CSS-compatible presets.
EASE = CubicBezierEasing(0.25, 0.1, 0.25, 1)
EASE_IN = CubicBezierEasing(0.42, 0, 1, 1)
EASE_OUT = CubicBezierEasing(0, 0, 0.58, 1)
EASE_IN_OUT = CubicBezierEasing(0.42, 0, 0.58, 1)


def parse_easing(easing):
    """Coerce several spellings into an :class:`Easing` instance.

    Accepts ``None`` (linear), the strings ``"linear"`` and ``"discrete"``,
    an existing :class:`Easing`, or a 4-element sequence
    ``(x1, y1, x2, y2)`` constructing a :class:`CubicBezierEasing`.
    """
    if easing is None:
        return LINEAR
    if isinstance(easing, Easing):
        return easing
    if isinstance(easing, str):
        name = easing.strip().lower().replace('-', '_')
        if name == 'linear':
            return LINEAR
        if name == 'discrete':
            return DISCRETE
        raise ValueError(
            f'unknown easing {easing!r}; expected "linear", "discrete", or '
            'a CubicBezierEasing')
    if isinstance(easing, (tuple, list)) and len(easing) == 4:
        return CubicBezierEasing(*easing)
    raise TypeError(
        f'cannot use {easing!r} as an easing; expected None, "linear", '
        '"discrete", a CubicBezierEasing, or a 4-element (x1, y1, x2, y2) '
        'sequence')
