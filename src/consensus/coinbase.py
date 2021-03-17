from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey

from src.types.blockchain_format.coin import Coin
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk


def create_puzzlehash_for_pk(pub_key: G1Element) -> bytes32:
    return puzzle_for_pk(bytes(pub_key)).get_tree_hash()


def signature_for_coinbase(coin: Coin, pool_private_key: PrivateKey):
    # noinspection PyTypeChecker
    return G2Element.from_bytes(bytes(AugSchemeMPL.sign(pool_private_key, bytes(coin))))


def sign_coinbase_coin(coin: Coin, private_key: PrivateKey):
    if private_key is None:
        raise ValueError("unknown private key")
    return signature_for_coinbase(coin, private_key)


def pool_parent_id(block_height: uint32, genesis_challenge: bytes32) -> uint32:
    return bytes32(genesis_challenge[:16] + block_height.to_bytes(16, "big"))


def farmer_parent_id(block_height: uint32, genesis_challenge: bytes32) -> uint32:
    return bytes32(genesis_challenge[16:] + block_height.to_bytes(16, "big"))


def create_pool_coin(block_height: uint32, puzzle_hash: bytes32, reward: uint64, genesis_challenge: bytes32):
    parent_id = pool_parent_id(block_height, genesis_challenge)
    return Coin(parent_id, puzzle_hash, reward)


def create_farmer_coin(block_height: uint32, puzzle_hash: bytes32, reward: uint64, genesis_challenge: bytes32):
    parent_id = farmer_parent_id(block_height, genesis_challenge)
    return Coin(parent_id, puzzle_hash, reward)
