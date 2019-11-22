import os
from enum import Enum

from prompt_toolkit.utils import is_windows

__all__ = [
    'ColorDepth',
]


class ColorDepth(str, Enum):
    """
    Possible color depth values for the output.
    """
    value: str

    #: One color only.
    DEPTH_1_BIT = 'DEPTH_1_BIT'

    #: ANSI Colors.
    DEPTH_4_BIT = 'DEPTH_4_BIT'

    #: The default.
    DEPTH_8_BIT = 'DEPTH_8_BIT'

    #: 24 bit True color.
    DEPTH_24_BIT = 'DEPTH_24_BIT'

    # Aliases.
    MONOCHROME = DEPTH_1_BIT
    ANSI_COLORS_ONLY = DEPTH_4_BIT
    DEFAULT = DEPTH_8_BIT
    TRUE_COLOR = DEPTH_24_BIT

    @classmethod
    def default(cls, term: str = '') -> 'ColorDepth':
        """
        If the user doesn't specify a color depth, use this as a default.
        """
        if term in ('linux', 'eterm-color'):
            return cls.DEPTH_4_BIT

        # For now, always use 4 bit color on Windows 10 by default, even when
        # vt100 escape sequences with ENABLE_VIRTUAL_TERMINAL_PROCESSING are
        # supported. We don't have a reliable way yet to know whether our
        # console supports true color or only 4-bit.
        if is_windows() and 'PROMPT_TOOLKIT_COLOR_DEPTH' not in os.environ:
            return cls.DEPTH_4_BIT

        # Check the `PROMPT_TOOLKIT_COLOR_DEPTH` environment variable.
        all_values = [i.value for i in ColorDepth]

        if os.environ.get('PROMPT_TOOLKIT_COLOR_DEPTH') in all_values:
            return cls(os.environ['PROMPT_TOOLKIT_COLOR_DEPTH'])

        return cls.DEPTH_8_BIT
