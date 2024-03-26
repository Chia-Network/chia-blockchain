from __future__ import annotations

import zlib
from typing import List

from chia.types.blockchain_format.program import Program
from chia.wallet.cat_wallet.cat_utils import CAT_MOD
from chia.wallet.nft_wallet.nft_puzzles import (
    NFT_METADATA_UPDATER,
    NFT_OWNERSHIP_LAYER,
    NFT_STATE_LAYER_MOD,
    NFT_TRANSFER_PROGRAM_DEFAULT,
    SINGLETON_TOP_LAYER_MOD,
)
from chia.wallet.puzzles import p2_delegated_puzzle_or_hidden_puzzle as standard_puzzle
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

# Need the legacy CAT mod for zlib backwards compatibility
LEGACY_CAT_MOD = Program.fromhex(
    "ff02ffff01ff02ff5effff04ff02ffff04ffff04ff05ffff04ffff0bff2cff0580ffff04ff0bff80808080ffff04ffff02ff17ff2f80ffff04ff5fffff04ffff02ff2effff04ff02ffff04ff17ff80808080ffff04ffff0bff82027fff82057fff820b7f80ffff04ff81bfffff04ff82017fffff04ff8202ffffff04ff8205ffffff04ff820bffff80808080808080808080808080ffff04ffff01ffffffff81ca3dff46ff0233ffff3c04ff01ff0181cbffffff02ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff22ffff0bff2cff3480ffff0bff22ffff0bff22ffff0bff2cff5c80ff0980ffff0bff22ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ff0bffff01ff02ffff03ffff09ffff02ff2effff04ff02ffff04ff13ff80808080ff820b9f80ffff01ff02ff26ffff04ff02ffff04ffff02ff13ffff04ff5fffff04ff17ffff04ff2fffff04ff81bfffff04ff82017fffff04ff1bff8080808080808080ffff04ff82017fff8080808080ffff01ff088080ff0180ffff01ff02ffff03ff17ffff01ff02ffff03ffff20ff81bf80ffff0182017fffff01ff088080ff0180ffff01ff088080ff018080ff0180ffff04ffff04ff05ff2780ffff04ffff10ff0bff5780ff778080ff02ffff03ff05ffff01ff02ffff03ffff09ffff02ffff03ffff09ff11ff7880ffff0159ff8080ff0180ffff01818f80ffff01ff02ff7affff04ff02ffff04ff0dffff04ff0bffff04ffff04ff81b9ff82017980ff808080808080ffff01ff02ff5affff04ff02ffff04ffff02ffff03ffff09ff11ff7880ffff01ff04ff78ffff04ffff02ff36ffff04ff02ffff04ff13ffff04ff29ffff04ffff0bff2cff5b80ffff04ff2bff80808080808080ff398080ffff01ff02ffff03ffff09ff11ff2480ffff01ff04ff24ffff04ffff0bff20ff2980ff398080ffff010980ff018080ff0180ffff04ffff02ffff03ffff09ff11ff7880ffff0159ff8080ff0180ffff04ffff02ff7affff04ff02ffff04ff0dffff04ff0bffff04ff17ff808080808080ff80808080808080ff0180ffff01ff04ff80ffff04ff80ff17808080ff0180ffffff02ffff03ff05ffff01ff04ff09ffff02ff26ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff010b80ff0180ff0bff22ffff0bff2cff5880ffff0bff22ffff0bff22ffff0bff2cff5c80ff0580ffff0bff22ffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bff2cff058080ff0180ffff04ffff04ff28ffff04ff5fff808080ffff02ff7effff04ff02ffff04ffff04ffff04ff2fff0580ffff04ff5fff82017f8080ffff04ffff02ff7affff04ff02ffff04ff0bffff04ff05ffff01ff808080808080ffff04ff17ffff04ff81bfffff04ff82017fffff04ffff0bff8204ffffff02ff36ffff04ff02ffff04ff09ffff04ff820affffff04ffff0bff2cff2d80ffff04ff15ff80808080808080ff8216ff80ffff04ff8205ffffff04ff820bffff808080808080808080808080ff02ff2affff04ff02ffff04ff5fffff04ff3bffff04ffff02ffff03ff17ffff01ff09ff2dffff0bff27ffff02ff36ffff04ff02ffff04ff29ffff04ff57ffff04ffff0bff2cff81b980ffff04ff59ff80808080808080ff81b78080ff8080ff0180ffff04ff17ffff04ff05ffff04ff8202ffffff04ffff04ffff04ff24ffff04ffff0bff7cff2fff82017f80ff808080ffff04ffff04ff30ffff04ffff0bff81bfffff0bff7cff15ffff10ff82017fffff11ff8202dfff2b80ff8202ff808080ff808080ff138080ff80808080808080808080ff018080"  # noqa
)

OFFER_MOD_OLD = Program.fromhex(
    "ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080"  # noqa
)
OFFER_MOD = load_clvm_maybe_recompile("settlement_payments.clsp")

# For backwards compatibility to work, we must assume that these mods (already deployed) will not change
# In the case that they do change and we don't support the old asset then we need to keep around the legacy module
ZDICT = [
    bytes(standard_puzzle.MOD) + bytes(LEGACY_CAT_MOD),
    bytes(OFFER_MOD_OLD),
    bytes(SINGLETON_TOP_LAYER_MOD)
    + bytes(NFT_STATE_LAYER_MOD)
    + bytes(NFT_OWNERSHIP_LAYER)
    + bytes(NFT_METADATA_UPDATER)
    + bytes(NFT_TRANSFER_PROGRAM_DEFAULT),
    bytes(CAT_MOD),
    bytes(OFFER_MOD),
    b"",  # purposefully break compatibility with older versions
    # more dictionaries go here
]

LATEST_VERSION = len(ZDICT)


class CompressionVersionError(Exception):
    def __init__(self, version_number: int):
        self.message = f"The data is compressed with version {version_number} and cannot be parsed. "
        self.message += "Update software and try again."


def zdict_for_version(version: int) -> bytes:
    summed_dictionary = b""
    for version_dict in ZDICT[0:version]:
        summed_dictionary += version_dict
    return summed_dictionary


def compress_with_zdict(blob: bytes, zdict: bytes) -> bytes:
    comp_obj = zlib.compressobj(zdict=zdict)
    compressed_blob = comp_obj.compress(blob)
    compressed_blob += comp_obj.flush()
    return compressed_blob


def decompress_with_zdict(blob: bytes, zdict: bytes) -> bytes:
    do = zlib.decompressobj(zdict=zdict)
    return do.decompress(blob, max_length=6 * 1024 * 1024)  # Limit output size


def decompress_object_with_puzzles(compressed_object_blob: bytes) -> bytes:
    version = int.from_bytes(compressed_object_blob[0:2], "big")
    if version > len(ZDICT):
        raise CompressionVersionError(version)
    zdict = zdict_for_version(version)
    object_bytes = decompress_with_zdict(compressed_object_blob[2:], zdict)
    return object_bytes


def compress_object_with_puzzles(object_bytes: bytes, version: int) -> bytes:
    version_blob = version.to_bytes(length=2, byteorder="big")
    zdict = zdict_for_version(version)
    compressed_object_blob = compress_with_zdict(object_bytes, zdict)
    return version_blob + compressed_object_blob


def lowest_best_version(puzzle_list: List[bytes], max_version: int = len(ZDICT)) -> int:
    highest_version = 1
    for mod in puzzle_list:
        for version, dict in enumerate(ZDICT):
            if version > max_version:
                break
            if bytes(mod) in dict:
                highest_version = max(highest_version, version + 1)
    return highest_version
