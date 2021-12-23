import zlib

from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles import p2_delegated_puzzle_or_hidden_puzzle as standard_puzzle
from chia.wallet.puzzles.cc_loader import CC_MOD

OFFER_MOD = load_clvm("settlement_payments.clvm")

ZDICT = [
     bytes(standard_puzzle.MOD) + bytes(CC_MOD),
     bytes(OFFER_MOD),
    # more dictionaries go here
]

LATEST_VERSION = len(ZDICT)

class CompressionVersionError(Exception):
    def __init__(self, version_number: int):
        self.message = f"The data is compressed with version {version_number} and cannot be parsed. "
        self.message += "Update software and try again."

def zdict_for_version(version: int) -> bytes:
    summed_dictionary = b''
    for version_dict in ZDICT[0:version]:
        summed_dictionary += version_dict
    return summed_dictionary

def compress_with_zdict(blob: bytes, zdict: bytes) -> bytes:
    comp_obj = zlib.compressobj(zdict = zdict)
    compressed_blob = comp_obj.compress(blob)
    compressed_blob += comp_obj.flush()
    return compressed_blob

def decompress_with_zdict(blob: bytes, zdict: bytes) -> bytes:
    do = zlib.decompressobj(zdict = zdict)
    return do.decompress(blob)

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