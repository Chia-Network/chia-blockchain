from blspy import G1Element

from deafwave.types.blockchain_format.coin import Coin
from deafwave.types.blockchain_format.sized_bytes import bytes32
from deafwave.util.ints import uint32, uint64
from deafwave.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk


def create_puzzlehash_for_pk(pub_key: G1Element) -> bytes32:
    return puzzle_for_pk(pub_key).get_tree_hash()


def pool_parent_id(block_height: uint32, genesis_challenge: bytes32) -> uint32:
    return bytes32(genesis_challenge[:16] + block_height.to_bytes(16, "big"))


def farmer_parent_id(block_height: uint32, genesis_challenge: bytes32) -> uint32:
    return bytes32(genesis_challenge[16:] + block_height.to_bytes(16, "big"))

def postfarm_parent_id(block_height: uint32, genesis_challenge: bytes32) -> uint32:
    return bytes32(genesis_challenge[8:8] + block_height.to_bytes(16, "big"))


def create_pool_coin(block_height: uint32, puzzle_hash: bytes32, reward: uint64, genesis_challenge: bytes32):
    parent_id = pool_parent_id(block_height, genesis_challenge)
    return Coin(parent_id, puzzle_hash, reward)


def create_farmer_coin(block_height: uint32, puzzle_hash: bytes32, reward: uint64, genesis_challenge: bytes32):
    parent_id = farmer_parent_id(block_height, genesis_challenge)
    return Coin(parent_id, puzzle_hash, reward)

def create_postfarm_coin(block_height: uint32, puzzle_hash: bytes32, reward: uint64, genesis_challenge: bytes32):
    parent_id = postfarm_parent_id(block_height, genesis_challenge)
    return Coin(parent_id, puzzle_hash, reward)
