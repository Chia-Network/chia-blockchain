from blspy import PrependSignature
from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.types.proof_of_space import ProofOfSpace
from src.types.challenge import Challenge
from src.types.coinbase import CoinbaseInfo
from src.types.fees_target import FeesTarget


@streamable
class ProofOfSpaceFinalized:
    challenge_hash: bytes32
    height: uint32
    quality_string: bytes


@streamable
class ProofOfSpaceArrived:
    height: uint32
    quality_string: bytes


@streamable
class RequestBlockHash:
    challenge: Challenge
    proof_of_space: ProofOfSpace
    coinbase_target: CoinbaseInfo
    coinbase_signature: PrependSignature
    fees_target: FeesTarget


@streamable
class HeaderHash:
    pos_hash: bytes32
    header_hash: bytes32


@streamable
class BlockSignature:
    info_hash: bytes32
    signature: PrependSignature


@streamable
class AverageBlockQuality:
    average_quality: uint64
