from typing import Callable, List, Optional
from blspy import AugSchemeMPL, PrivateKey
from src.types.coin_solution import CoinSolution
from src.types.spend_bundle import SpendBundle
from src.util.condition_tools import (
    conditions_dict_for_solution,
    pkm_pairs_for_conditions_dict,
)


async def sign_coin_solutions(
    coin_solutions: List[CoinSolution],
    secret_key_for_public_key_f: Callable[[bytes], Optional[PrivateKey]],
) -> SpendBundle:
    signatures = []
    pk_list = []
    msg_list = []
    for coin_solution in coin_solutions:
        # Get AGGSIG conditions
        err, conditions_dict, cost = conditions_dict_for_solution(coin_solution.solution)
        if err or conditions_dict is None:
            error_msg = f"Sign transaction failed, con:{conditions_dict}, error: {err}"
            raise ValueError(error_msg)

        # Create signature
        for _, msg in pkm_pairs_for_conditions_dict(conditions_dict, bytes(coin_solution.coin.name())):
            pk_list.append(_)
            msg_list.append(msg)
            secret_key = secret_key_for_public_key_f(_)
            if secret_key is None:
                e_msg = f"no secret key for {_}"
                raise ValueError(e_msg)
            assert bytes(secret_key.get_g1()) == bytes(_)
            signature = AugSchemeMPL.sign(secret_key, msg)
            assert AugSchemeMPL.verify(_, msg, signature)
            signatures.append(signature)

    # Aggregate signatures
    aggsig = AugSchemeMPL.aggregate(signatures)
    assert AugSchemeMPL.aggregate_verify(pk_list, msg_list, aggsig)
    return SpendBundle(coin_solutions, aggsig)
