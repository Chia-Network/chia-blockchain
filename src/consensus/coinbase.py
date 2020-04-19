import blspy

from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.types.coin import Coin
from src.types.BLSSignature import BLSSignature, BLSPublicKey
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk


def create_puzzlehash_for_pk(pub_key: BLSPublicKey) -> bytes32:
    return puzzle_for_pk(pub_key).get_tree_hash()


def signature_for_coinbase(coin: Coin, pool_private_key: blspy.PrivateKey):
    message_hash = blspy.Util.hash256(bytes(coin))
    return BLSSignature(bytes(pool_private_key.sign_prepend_prehashed(message_hash)))


def sign_coinbase_coin(coin: Coin, private_key: blspy.PrivateKey):
    if private_key is None:
        raise ValueError("unknown private key")
    return signature_for_coinbase(coin, private_key)


def create_coinbase_coin(block_index: int, puzzle_hash: bytes32, reward: uint64):
    block_index_as_hash = bytes32(block_index.to_bytes(32, "big"))
    return Coin(block_index_as_hash, puzzle_hash, reward)


def create_coinbase_coin_and_signature(
    block_index: int,
    puzzle_hash: bytes32,
    reward: uint64,
    private_key: blspy.PrivateKey,
):
    coin = create_coinbase_coin(block_index, puzzle_hash, reward)
    signature = sign_coinbase_coin(coin, private_key)
    return coin, signature
