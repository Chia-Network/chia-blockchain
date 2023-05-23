from __future__ import annotations

import inspect
from typing import Any, List

import blspy
from blspy import AugSchemeMPL

from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict


async def sign_coin_spends(
    coin_spends: List[CoinSpend],
    secret_key_for_public_key_f: Any,  # Potentially awaitable function from G1Element => Optional[PrivateKey]
    additional_data: bytes,
    max_cost: int,
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
    signatures: List[blspy.G2Element] = []
    pk_list: List[blspy.G1Element] = []
    msg_list: List[bytes] = []
    for coin_spend in coin_spends:
        # Get AGG_SIG conditions
        err, conditions_dict, cost = conditions_dict_for_solution(
            coin_spend.puzzle_reveal, coin_spend.solution, max_cost
        )
        if err or conditions_dict is None:
            error_msg = f"Sign transaction failed, con:{conditions_dict}, error: {err}"
            raise ValueError(error_msg)

        # Create signature
        for pk_bytes, msg in pkm_pairs_for_conditions_dict(conditions_dict, coin_spend.coin.name(), additional_data):
            pk = blspy.G1Element.from_bytes(pk_bytes)
            pk_list.append(pk)
            msg_list.append(msg)
            if inspect.iscoroutinefunction(secret_key_for_public_key_f):
                secret_key = await secret_key_for_public_key_f(pk)
            else:
                secret_key = secret_key_for_public_key_f(pk)
            if secret_key is None:
                e_msg = f"no secret key for {pk}"
                raise ValueError(e_msg)
            assert bytes(secret_key.get_g1()) == bytes(pk)
            signature = AugSchemeMPL.sign(secret_key, msg)
            assert AugSchemeMPL.verify(pk, msg, signature)
            signatures.append(signature)

    # Aggregate signatures
    aggsig = AugSchemeMPL.aggregate(signatures)
    assert AugSchemeMPL.aggregate_verify(pk_list, msg_list, aggsig)
    return SpendBundle(coin_spends, aggsig)
