from typing import Any, Dict, get_type_hints
import cbor2
from src.protocols.cbor_tags import custom_tags

"""
Uses custom CBOR types to encode and decode messages.
If messages don't have a custom CBOR tag, we call .serialize on
them to convert them to bytes.
https://cbor2.readthedocs.io/en/latest/customizing.html
"""


def default_encoder(encoder, value: Any):
    """
    Checks in our custom tags dict to see if we can encode this type.
    If so, it encodes it with the correct tag. Cbor will recursively call this
    on each property.
    """
    if type(value) in custom_tags:
        tag = custom_tags[type(value)]
        fields: Dict = get_type_hints(value)
        els = [getattr(value, f_name) for f_name in fields.keys()]
        encoder.encode(cbor2.CBORTag(tag, els))
    elif hasattr(type(value), "serialize"):
        encoder.encode(value.serialize())
    else:
        raise NotImplementedError(f"can't CBOR encode {type(value)}:{value}")


def tag_hook(decoder, tag, shareable_index=None):
    """
    If we find a custom tag, decode this. Otherwise, just return the tag (no decoding).
    """
    for (cls, cls_tag) in custom_tags.items():
        if tag.tag == cls_tag:
            return cls(*tag.value)
    return tag


def dumps(data: Any) -> bytes:
    return cbor2.dumps(data, default=default_encoder)


def loads(data: bytes) -> Any:
    return cbor2.loads(data, tag_hook=tag_hook)
