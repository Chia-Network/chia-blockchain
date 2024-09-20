from __future__ import annotations

from typing import Dict, List

from clvm.casts import int_from_bytes

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


def compute_memos_for_spend(coin_spend: CoinSpend) -> Dict[bytes32, List[bytes]]:
    _, result = coin_spend.puzzle_reveal.run_with_cost(INFINITE_COST, coin_spend.solution)
    memos: Dict[bytes32, List[bytes]] = {}
    for condition in result.as_python():
        if condition[0] == ConditionOpcode.CREATE_COIN and len(condition) >= 4:
            # If only 3 elements (opcode + 2 args), there is no memo, this is ph, amount
            coin_added = Coin(coin_spend.coin.name(), bytes32(condition[1]), uint64(int_from_bytes(condition[2])))
            if type(condition[3]) is not list:
                # If it's not a list, it's not the correct format
                continue
            memos[coin_added.name()] = condition[3]
    return memos


def compute_memos(bundle: WalletSpendBundle) -> Dict[bytes32, List[bytes]]:
    """
    Retrieves the memos for additions in this spend_bundle, which are formatted as a list in the 3rd parameter of
    CREATE_COIN. If there are no memos, the addition coin_id is not included. If they are not formatted as a list
    of bytes, they are not included. This is expensive to call, it should not be used in full node code.
    """
    memos: Dict[bytes32, List[bytes]] = {}
    for coin_spend in bundle.coin_spends:
        spend_memos = compute_memos_for_spend(coin_spend)
        for coin_name, coin_memos in spend_memos.items():
            existing_memos = memos.get(coin_name)
            if existing_memos is None:
                memos[coin_name] = coin_memos
            else:
                memos[coin_name] = existing_memos + coin_memos
    return memos
