from blspy import G1Element, PrivateKey, G2Element, AugSchemeMPL

from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.types.blockchain_format.coin import Coin
from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk
from src.util.hash import std_hash


def create_puzzlehash_for_pk(pub_key: G1Element) -> bytes32:
    return puzzle_for_pk(bytes(pub_key)).get_tree_hash()


def signature_for_coinbase(coin: Coin, pool_private_key: PrivateKey):
    # noinspection PyTypeChecker
    return G2Element.from_bytes(bytes(AugSchemeMPL.sign(pool_private_key, bytes(coin))))


def sign_coinbase_coin(coin: Coin, private_key: PrivateKey):
    if private_key is None:
        raise ValueError("unknown private key")
    return signature_for_coinbase(coin, private_key)


def create_pool_coin(block_index: uint32, puzzle_hash: bytes32, reward: uint64):
    block_index_as_hash = bytes32(block_index.to_bytes(32, "big"))
    return Coin(block_index_as_hash, puzzle_hash, reward)


def create_farmer_coin(block_index: uint32, puzzle_hash: bytes32, reward: uint64):
    block_index_as_hash = std_hash(std_hash(block_index.to_bytes(4, "big")))
    return Coin(block_index_as_hash, puzzle_hash, reward)
