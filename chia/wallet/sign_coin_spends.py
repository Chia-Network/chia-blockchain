from __future__ import annotations

import inspect
from typing import Any, Callable, List

from chia_rs import AugSchemeMPL, G1Element, G2Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict


async def sign_coin_spends(
    coin_spends: List[CoinSpend],
    secret_key_for_public_key_f: Any,  # Potentially awaitable function from G1Element => Optional[PrivateKey]
    secret_key_for_puzzle_hash: Any,  # Potentially awaitable function from bytes32 => Optional[PrivateKey]
    additional_data: bytes,
    max_cost: int,
    potential_derivation_functions: List[Callable[[G1Element], bytes32]],
) -> SpendBundle:
    """
    Sign_coin_spends runs the puzzle code with the given argument and searches the
    result for an AGG_SIG_ME condition, which it attempts to sign by requesting a
    matching PrivateKey corresponding with the given G1Element (public key) specified
    in the resulting condition output.

    It's important to note that as mentioned in the documentation about the standard
    spend that the public key presented to the secret_key_for_public_key_f function
    provided to sign_coin_spends must be prepared to do the key derivations required
    by the coin types it's allowed to spend (at least the derivation of the standard
    spend as done by calculate_synthetic_secret_key with DEFAULT_PUZZLE_HASH).

    If a coin performed a different key derivation, the pk presented to this function
    would be similarly alien, and would need to be tried against the first stage
    derived keys (those returned by master_sk_to_wallet_sk from the ['sk'] member of
    wallet rpc's get_private_key method).
    """
    signatures: List[G2Element] = []
    pk_list: List[G1Element] = []
    msg_list: List[bytes] = []
    for coin_spend in coin_spends:
        # Get AGG_SIG conditions
        conditions_dict = conditions_dict_for_solution(coin_spend.puzzle_reveal, coin_spend.solution, max_cost)
        # Create signature
        for pk_bytes, msg in pkm_pairs_for_conditions_dict(conditions_dict, coin_spend.coin, additional_data):
            pk = G1Element.from_bytes(pk_bytes)
            pk_list.append(pk)
            msg_list.append(msg)
            if inspect.iscoroutinefunction(secret_key_for_public_key_f):
                secret_key = await secret_key_for_public_key_f(pk)
            else:
                secret_key = secret_key_for_public_key_f(pk)
            if secret_key is None or secret_key.get_g1() != pk:
                for derive in potential_derivation_functions:
                    if inspect.iscoroutinefunction(secret_key_for_puzzle_hash):
                        secret_key = await secret_key_for_puzzle_hash(derive(pk))
                    else:
                        secret_key = secret_key_for_puzzle_hash(derive(pk))
                    if secret_key is not None and secret_key.get_g1() == pk:
                        break
                else:
                    raise ValueError(f"no secret key for {pk}")
            signature = AugSchemeMPL.sign(secret_key, msg)
            assert AugSchemeMPL.verify(pk, msg, signature)
            signatures.append(signature)

    # Aggregate signatures
    aggsig = AugSchemeMPL.aggregate(signatures)
    assert AugSchemeMPL.aggregate_verify(pk_list, msg_list, aggsig)
    return SpendBundle(coin_spends, aggsig)
