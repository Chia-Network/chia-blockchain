import blspy

from src.util.ints import uint64
from src.types.hashable.Program import ProgramHash
from src.types.hashable.Coin import Coin
from src.types.hashable.Hash import Hash
from src.types.hashable.BLSSignature  import BLSSignature

def signature_for_coinbase(coin: Coin, pool_private_key: blspy.PrivateKey):
    message_hash = blspy.Util.hash256(bytes(coin))
    return BLSSignature(pool_private_key.sign_prepend_prehashed(message_hash).serialize())


def sign_coinbase_coin(coin: Coin, private_key: blspy.PrivateKey):
    if private_key is None:
        raise ValueError("unknown private key")
    return signature_for_coinbase(coin, private_key)


def create_coinbase_coin(block_index: int, puzzle_hash: ProgramHash, reward: uint64):
    block_index_as_hash = Hash(block_index.to_bytes(32, "big"))
    return Coin(block_index_as_hash, puzzle_hash, reward)


def create_coinbase_coin_and_signature(
        block_index: int, puzzle_hash: ProgramHash,
        reward: uint64, private_key: blspy.PrivateKey):
    coin = create_coinbase_coin(block_index, puzzle_hash, reward)
    signature = sign_coinbase_coin(coin, private_key)
    return coin, signature
