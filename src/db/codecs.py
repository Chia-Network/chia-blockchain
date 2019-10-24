from bson.codec_options import TypeCodec
from bson.binary import Binary
from src.util.streamable import Streamable
from src.types.block_body import BlockBody
from src.types.block_header import BlockHeader
from src.types.full_block import FullBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.trunk_block import TrunkBlock
from bson.codec_options import TypeRegistry
from bson.codec_options import CodecOptions


def make_streamable_codec(streamable_cls: Streamable, subtype: int):
    return type(
        streamable_cls.__name__ + "Codec",
        (TypeCodec,),
        {
            "python_type": streamable_cls,
            "bson_type": Binary,
            "transform_python": (lambda _, v: Binary(v.serialize(), subtype=subtype)),
            "transform_bson": convert_binary_to_obj,
        },
    )()


def convert_binary_to_obj(_, b: Binary):
    if b.subtype == 128:
        return FullBlock.from_bytes(b)
    elif b.subtype == 129:
        return TrunkBlock.from_bytes(b)
    elif b.subtype == 130:
        return BlockBody.from_bytes(b)
    elif b.subtype == 131:
        return BlockHeader.from_bytes(b)
    elif b.subtype == 132:
        return ProofOfSpace.from_bytes(b)
    else:
        raise Exception(f"Binary subtype {b.subtype} not recognized.")
        # return bytes(b)


codec_options = CodecOptions(
    type_registry=TypeRegistry(
        [  # Mongo recommends userdefined binary subtypes to be in range 0x80-0xFF
            make_streamable_codec(FullBlock, 128),
            make_streamable_codec(TrunkBlock, 129),
            make_streamable_codec(BlockBody, 130),
            make_streamable_codec(BlockHeader, 131),
            make_streamable_codec(ProofOfSpace, 132),
        ]
    )
)
