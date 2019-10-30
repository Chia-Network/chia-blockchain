from bson.binary import Binary
from src.util.streamable import Streamable
from bson.codec_options import TypeRegistry
from bson.codec_options import CodecOptions


def fallback_encoder(obj):
    if isinstance(obj, Streamable):
        return Binary(obj.serialize())
    return obj


codec_options = CodecOptions(
    type_registry=TypeRegistry(fallback_encoder=fallback_encoder)
)
