from typing import List
from blspy import AugSchemeMPL, PrivateKey

from src.util.ints import uint32

# EIP 2334 bls key derivation
# https://eips.ethereum.org/EIPS/eip-2334
# 12381 = bls spec number
# 8444 = Chia blockchain number and port number
# 0, 1, 2, 3, 4, farmer, pool, wallet, local, backup key numbers


def _derive_path(sk: PrivateKey, path: List[int]) -> PrivateKey:
    for index in path:
        sk = AugSchemeMPL.derive_child_sk(sk, index)
    return sk


def master_sk_to_farmer_sk(master: PrivateKey) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 0, 0])


def master_sk_to_pool_sk(master: PrivateKey) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 1, 0])


def master_sk_to_wallet_sk(master: PrivateKey, index: uint32) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 2, index])


def master_sk_to_local_sk(master: PrivateKey) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 3, 0])


def master_sk_to_backup_sk(master: PrivateKey) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 4, 0])
