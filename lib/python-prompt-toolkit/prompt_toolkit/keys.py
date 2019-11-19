from enum import Enum
from typing import Dict, List

__all__ = [
    'Keys',
    'ALL_KEYS',
]


class Keys(str, Enum):
    """
    List of keys for use in key bindings.

    Note that this is an "StrEnum", all values can be compared against
    strings.
    """
    value: str

    Escape = 'escape'  # Also Control-[

    ControlAt = 'c-@'  # Also Control-Space.

    ControlA = 'c-a'
    ControlB = 'c-b'
    ControlC = 'c-c'
    ControlD = 'c-d'
    ControlE = 'c-e'
    ControlF = 'c-f'
    ControlG = 'c-g'
    ControlH = 'c-h'
    ControlI = 'c-i'  # Tab
    ControlJ = 'c-j'  # Newline
    ControlK = 'c-k'
    ControlL = 'c-l'
    ControlM = 'c-m'  # Carriage return
    ControlN = 'c-n'
    ControlO = 'c-o'
    ControlP = 'c-p'
    ControlQ = 'c-q'
    ControlR = 'c-r'
    ControlS = 'c-s'
    ControlT = 'c-t'
    ControlU = 'c-u'
    ControlV = 'c-v'
    ControlW = 'c-w'
    ControlX = 'c-x'
    ControlY = 'c-y'
    ControlZ = 'c-z'

    ControlBackslash   = 'c-\\'
    ControlSquareClose = 'c-]'
    ControlCircumflex  = 'c-^'
    ControlUnderscore  = 'c-_'

    ControlLeft        = 'c-left'
    ControlRight       = 'c-right'
    ControlUp          = 'c-up'
    ControlDown        = 'c-down'
    ControlHome        = 'c-home'
    ControlEnd         = 'c-end'
    ControlInsert      = 'c-insert'

    ShiftControlLeft   = 's-c-left'
    ShiftControlRight  = 's-c-right'
    ShiftControlHome   = 's-c-home'
    ShiftControlEnd    = 's-c-end'

    Up          = 'up'
    Down        = 'down'
    Right       = 'right'
    Left        = 'left'

    ShiftLeft   = 's-left'
    ShiftUp     = 's-up'
    ShiftDown   = 's-down'
    ShiftRight  = 's-right'
    ShiftDelete = 's-delete'
    BackTab     = 's-tab'  # shift + tab
    ShiftHome   = 's-home'
    ShiftEnd    = 's-end'
    ShiftInsert = 's-insert'

    Home        = 'home'
    End         = 'end'
    Delete      = 'delete'
    ControlDelete = 'c-delete'
    PageUp      = 'pageup'
    PageDown    = 'pagedown'
    Insert      = 'insert'

    F1 = 'f1'
    F2 = 'f2'
    F3 = 'f3'
    F4 = 'f4'
    F5 = 'f5'
    F6 = 'f6'
    F7 = 'f7'
    F8 = 'f8'
    F9 = 'f9'
    F10 = 'f10'
    F11 = 'f11'
    F12 = 'f12'
    F13 = 'f13'
    F14 = 'f14'
    F15 = 'f15'
    F16 = 'f16'
    F17 = 'f17'
    F18 = 'f18'
    F19 = 'f19'
    F20 = 'f20'
    F21 = 'f21'
    F22 = 'f22'
    F23 = 'f23'
    F24 = 'f24'

    # Matches any key.
    Any = '<any>'

    # Special.
    ScrollUp    = '<scroll-up>'
    ScrollDown  = '<scroll-down>'

    CPRResponse = '<cursor-position-response>'
    Vt100MouseEvent = '<vt100-mouse-event>'
    WindowsMouseEvent = '<windows-mouse-event>'
    BracketedPaste = '<bracketed-paste>'

    # For internal use: key which is ignored.
    # (The key binding for this key should not do anything.)
    Ignore = '<ignore>'

    # Some 'Key' aliases (for backwards-compatibility).
    ControlSpace = ControlAt
    Tab          = ControlI
    Enter        = ControlM
    Backspace    = ControlH


ALL_KEYS: List[str] = [k.value for k in Keys]


# Aliases.
KEY_ALIASES: Dict[str, str] = {
    'backspace': 'c-h',
    'c-space': 'c-@',
    'enter': 'c-m',
    'tab': 'c-i',
}
