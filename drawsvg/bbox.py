'''Compatibility alias for the bounds / auto-viewBox feature.'''
from .bounds import *  # noqa: F401,F403
from . import bounds as _bounds

globals().update({name: getattr(_bounds, name)
                  for name in _bounds.__all__})
