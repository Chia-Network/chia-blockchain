from typing import List, Optional

from blspy import AugSchemeMPL, PrivateKey, G1Element

from chia.util.ints import uint32

# EIP 2334 bls key derivation
# https://eips.ethereum.org/EIPS/eip-2334
# 12381 = bls spec number
# 8444 = Chia blockchain number and port number
# 0, 1, 2, 3, 4, 5, 6 farmer, pool, wallet, local, backup key, singleton, pooling authentication key numbers


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


def master_sk_to_singleton_owner_sk(master: PrivateKey, wallet_id: uint32) -> PrivateKey:
    """
    This key controls a singleton on the blockchain, allowing for dynamic pooling (changing pools)
    """
    return _derive_path(master, [12381, 8444, 5, wallet_id])


def master_sk_to_pooling_authentication_sk(master: PrivateKey, wallet_id: uint32, index: uint32) -> PrivateKey:
    """
    This key is used for the farmer to authenticate to the pool when sending partials
    """
    assert index < 10000
    assert wallet_id < 10000
    return _derive_path(master, [12381, 8444, 6, wallet_id * 10000 + index])


async def find_owner_sk(all_sks: List[PrivateKey], owner_pk: G1Element) -> Optional[G1Element]:
    for wallet_id in range(50):
        for sk in all_sks:
            auth_sk = master_sk_to_singleton_owner_sk(sk, uint32(wallet_id))
            if auth_sk.get_g1() == owner_pk:
                return auth_sk
    return None


async def find_authentication_sk(all_sks: List[PrivateKey], authentication_pk: G1Element) -> Optional[PrivateKey]:
    # NOTE: might need to increase this if using a large number of wallets, or have switched authentication keys
    # many times.
    for auth_key_index in range(20):
        for wallet_id in range(20):
            for sk in all_sks:
                auth_sk = master_sk_to_pooling_authentication_sk(sk, uint32(wallet_id), uint32(auth_key_index))
                if auth_sk.get_g1() == authentication_pk:
                    return auth_sk
    return None
