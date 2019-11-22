import pytest

from prompt_toolkit.styles import AdjustBrightnessStyleTransformation, Attrs


@pytest.fixture
def default_attrs():
    return Attrs(
        color='', bgcolor='', bold=False,
        underline=False, italic=False, blink=False,
        reverse=False, hidden=False)


def test_adjust_brightness_style_transformation(default_attrs):
    tr = AdjustBrightnessStyleTransformation(.5, 1.0)

    attrs = tr.transform_attrs(default_attrs._replace(color='ff0000'))
    assert attrs.color == 'ff7f7f'

    attrs = tr.transform_attrs(default_attrs._replace(color='00ffaa'))
    assert attrs.color == '7fffd4'

    # When a background color is given, nothing should change.
    attrs = tr.transform_attrs(default_attrs._replace(color='00ffaa', bgcolor='white'))
    assert attrs.color == '00ffaa'

    # Test ansi colors.
    attrs = tr.transform_attrs(default_attrs._replace(color='ansiblue'))
    assert attrs.color == '6666ff'

    # Test 'ansidefault'. This shouldn't change.
    attrs = tr.transform_attrs(default_attrs._replace(color='ansidefault'))
    assert attrs.color == 'ansidefault'

    # When 0 and 1 are given, don't do any style transformation.
    tr2 = AdjustBrightnessStyleTransformation(0, 1)

    attrs = tr2.transform_attrs(default_attrs._replace(color='ansiblue'))
    assert attrs.color == 'ansiblue'

    attrs = tr2.transform_attrs(default_attrs._replace(color='00ffaa'))
    assert attrs.color == '00ffaa'
