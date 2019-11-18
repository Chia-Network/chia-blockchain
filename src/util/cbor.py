from typing import Any, Dict, get_type_hints

import cbor2


"""
Encode CBOR objects (python objects with @cbor_message decorator), as dictionaries.
Everything else is encded by using bytes(obj), which calls obj.__bytes__.
https://cbor2.readthedocs.io/en/latest/customizing.html
"""


def default_encoder(encoder, value: Any):
    """
    Checks in our custom tags dict to see if we can encode this type.
    If so, it encodes it with the correct tag. Cbor will recursively call this
    on each property.
    """
    if hasattr(type(value), "__cbor_message__"):
        fields: Dict = get_type_hints(value)
        els = {f_name: getattr(value, f_name) for f_name in fields.keys()}
        encoder.encode(els)
    elif hasattr(type(value), "__bytes__"):
        encoder.encode(bytes(value))
    else:
        raise NotImplementedError(f"can't CBOR encode {type(value)}:{value}")


def dumps(data: Any) -> bytes:
    return cbor2.dumps(data, default=default_encoder)


def loads(data: bytes) -> Any:
    return cbor2.loads(data)
