from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from clvm.casts import int_from_bytes

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64


@dataclass(frozen=True)
class HintedCoin:
    coin: Coin
    hint: bytes32


def hinted_coin_from_condition(condition: Program, parent_coin_id: bytes32) -> HintedCoin:
    data = condition.as_python()
    if len(data) != 4 or data[0] != ConditionOpcode.CREATE_COIN:
        raise ValueError(f"Not a hinted coin: {data}")

    try:
        coin = Coin(parent_coin_id, bytes32(data[1]), uint64(int_from_bytes(data[2])))
    except Exception as e:
        raise ValueError(f"Invalid coin: {e}, data: {data[1:2]}") from e

    try:
        hint = bytes32(data[3][0])
    except Exception as e:
        raise ValueError(f"Invalid hint: {e}, data: {data[3:]}") from e

    return HintedCoin(coin, hint)


def hinted_coins_in_coin_spend(coin_spend: CoinSpend) -> Iterator[HintedCoin]:
    _, result_program = coin_spend.puzzle_reveal.run_with_cost(INFINITE_COST, coin_spend.solution)
    parent_coin_id = coin_spend.coin.name()
    for condition in result_program.as_iter():
        try:
            yield hinted_coin_from_condition(condition, parent_coin_id)
        except Exception:
            continue


def hinted_coin_with_coin_id(coin_spend: CoinSpend, coin_id: bytes32) -> HintedCoin:
    for hinted_coin in hinted_coins_in_coin_spend(coin_spend):
        if hinted_coin.coin.name() == coin_id:
            return hinted_coin
    raise ValueError(f"coin_id {coin_id.hex()} not found in coin_spend: {coin_spend}")
