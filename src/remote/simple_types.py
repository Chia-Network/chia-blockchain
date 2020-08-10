"""
This converts arbitrary python types into "simple" types supported by JSON.

If you have additional python types that need to be serialized that aren't
currently supported, you can add support here.
"""

import datetime


def convert_with_table(v, t, lookup):
    f = lookup.get(t)
    if f:
        return f(v)
    raise TypeError(f"can't convert {v} to type {t}")


def from_simple_types(v, t):
    d = {
        None: lambda a: None,
        bool: lambda a: True if a else False,
        str: lambda a: a,
        int: lambda a: a,
        datetime.datetime: lambda v: datetime.datetime.fromtimestamp(float(v)),
    }
    return convert_with_table(v, t, d)


def to_simple_types(v, t):
    d = {
        None: lambda a: 0,
        bool: lambda a: 1 if a else 0,
        str: lambda a: a,
        int: lambda a: a,
        datetime.datetime: lambda v: str(v.timestamp()),
    }
    return convert_with_table(v, t, d)
