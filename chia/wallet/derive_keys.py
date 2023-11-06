from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional, Set, Tuple

from blspy import AugSchemeMPL, G1Element, PrivateKey

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32

# EIP 2334 bls key derivation
# https://eips.ethereum.org/EIPS/eip-2334
# 12381 = bls spec number
# 8444 = Chia blockchain number and port number
# 0, 1, 2, 3, 4, 5, 6 farmer, pool, wallet, local, backup key, singleton, pooling authentication key numbers

# Allows up to 100 pool wallets (plot NFTs)
MAX_POOL_WALLETS = 100


"""
Cache derivations during testing. This reduces the times spent in bls, and saves us about 12% of our time in pytest.
Do not use this cache in production. BlockTools should only be used for testing.
"""
DerivationCache = Dict[Tuple[bytes, int, bool], bytes]


def _derive_path_maybe_cached(
    sk: PrivateKey,
    path: List[int],
    derivation_function: Callable[[PrivateKey, int], PrivateKey],
    hardened: bool,
    cache: Optional[DerivationCache] = None,
) -> PrivateKey:
    for index in path:
        parent_sk = sk
        if cache and (bytes(parent_sk), index, hardened) in cache:
            sk = PrivateKey.from_bytes(cache[(bytes(parent_sk), index, True)])
        else:
            sk = derivation_function(sk, index)
            # To create more DerivationCache entries for new tests, append entries to 'tests/derivation_cache.json'
            print(f"DerivationCache miss: {json.dumps((bytes(parent_sk).hex(), index, True, bytes(sk).hex()))},")
            if cache:
                cache[(bytes(parent_sk), index, hardened)] = bytes(sk)
    return sk


def _derive_path(sk: PrivateKey, path: List[int], cache: Optional[DerivationCache] = None) -> PrivateKey:
    return _derive_path_maybe_cached(sk, path, AugSchemeMPL.derive_child_sk, True, cache)


def _derive_path_unhardened(sk: PrivateKey, path: List[int], cache: Optional[DerivationCache] = None) -> PrivateKey:
    return _derive_path_maybe_cached(sk, path, AugSchemeMPL.derive_child_sk_unhardened, False, cache)


def master_sk_to_farmer_sk(master: PrivateKey, cache: Optional[DerivationCache] = None) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 0, 0], cache)


def master_sk_to_pool_sk(master: PrivateKey, cache: Optional[DerivationCache] = None) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 1, 0], cache)


def master_sk_to_wallet_sk_intermediate(master: PrivateKey, cache: Optional[DerivationCache] = None) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 2], cache)


def master_sk_to_wallet_sk(master: PrivateKey, index: uint32, cache: Optional[DerivationCache] = None) -> PrivateKey:
    intermediate = master_sk_to_wallet_sk_intermediate(master)
    return _derive_path(intermediate, [index], cache)


def master_sk_to_wallet_sk_unhardened_intermediate(
    master: PrivateKey, cache: Optional[DerivationCache] = None
) -> PrivateKey:
    return _derive_path_unhardened(master, [12381, 8444, 2], cache)


def master_sk_to_wallet_sk_unhardened(
    master: PrivateKey, index: uint32, cache: Optional[DerivationCache] = None
) -> PrivateKey:
    intermediate = master_sk_to_wallet_sk_unhardened_intermediate(master)
    return _derive_path_unhardened(intermediate, [index], cache)


def master_sk_to_local_sk(master: PrivateKey, cache: Optional[DerivationCache] = None) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 3, 0], cache)


def master_sk_to_backup_sk(master: PrivateKey, cache: Optional[DerivationCache] = None) -> PrivateKey:
    return _derive_path(master, [12381, 8444, 4, 0], cache)


def master_sk_to_singleton_owner_sk(
    master: PrivateKey, pool_wallet_index: uint32, cache: Optional[DerivationCache] = None
) -> PrivateKey:
    """
    This key controls a singleton on the blockchain, allowing for dynamic pooling (changing pools)
    """
    return _derive_path(master, [12381, 8444, 5, pool_wallet_index], cache)


def master_sk_to_pooling_authentication_sk(
    master: PrivateKey, pool_wallet_index: uint32, index: uint32, cache: Optional[DerivationCache] = None
) -> PrivateKey:
    """
    This key is used for the farmer to authenticate to the pool when sending partials
    """
    assert index < 10000
    assert pool_wallet_index < 10000
    return _derive_path(master, [12381, 8444, 6, pool_wallet_index * 10000 + index], cache)


def find_owner_sk(all_sks: List[PrivateKey], owner_pk: G1Element) -> Optional[Tuple[PrivateKey, uint32]]:
    for pool_wallet_index in range(MAX_POOL_WALLETS):
        for sk in all_sks:
            try_owner_sk = master_sk_to_singleton_owner_sk(sk, uint32(pool_wallet_index))
            if try_owner_sk.get_g1() == owner_pk:
                return try_owner_sk, uint32(pool_wallet_index)
    return None


def find_authentication_sk(all_sks: List[PrivateKey], owner_pk: G1Element) -> Optional[PrivateKey]:
    # NOTE: might need to increase this if using a large number of wallets, or have switched authentication keys
    # many times.
    for pool_wallet_index in range(MAX_POOL_WALLETS):
        for sk in all_sks:
            try_owner_sk = master_sk_to_singleton_owner_sk(sk, uint32(pool_wallet_index))
            if try_owner_sk.get_g1() == owner_pk:
                # NOTE: ONLY use 0 for authentication key index to ensure compatibility
                return master_sk_to_pooling_authentication_sk(sk, uint32(pool_wallet_index), uint32(0))
    return None


def match_address_to_sk(
    sk: PrivateKey, addresses_to_search: List[bytes32], max_ph_to_search: int = 500
) -> Set[bytes32]:
    """
    Checks the list of given address is a derivation of the given sk within the given number of derivations
    Returns a Set of the addresses that are derivations of the given sk
    """
    if sk is None or not addresses_to_search:
        return set()

    found_addresses: Set[bytes32] = set()
    search_list: Set[bytes32] = set(addresses_to_search)

    for i in range(max_ph_to_search):
        phs = [
            create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(i)).get_g1()),
            create_puzzlehash_for_pk(master_sk_to_wallet_sk_unhardened(sk, uint32(i)).get_g1()),
        ]

        for address in search_list:
            if address in phs:
                found_addresses.add(address)

        search_list = search_list - found_addresses
        if not len(search_list):
            return found_addresses

    return found_addresses
